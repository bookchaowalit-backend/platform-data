"""Composite service trust and durable two-phase recovery against real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from fastapi.testclient import TestClient
from platform_backend_core import Database
from platform_data.app import create_app
from test_api import runtime, put_policy, reserve


@pytest.fixture
def service(runtime):
    _,_,_,_,test,verifier,headers=runtime
    system,tenant1,tenant2=uuid4(),uuid4(),uuid4()
    service_actor,actor1,actor2=uuid4(),uuid4(),uuid4()
    # Extra constructor option must preserve the original public app interface.
    app=create_app(Database(test.runtime_dsn,max_size=16),verifier,system_workspace=system)
    with TestClient(app) as client:
        service_auth=headers(system,'quotas:service quotas:write',service_actor)
        caller1=headers(tenant1,'ai:generate',actor1)
        caller2=headers(tenant2,'ai:generate',actor2)
        put_policy(client,service_auth,limit=10,key='global')
        put_policy(client,headers(tenant1),limit=100,key='tenant')
        put_policy(client,headers(tenant2),limit=100,key='tenant')
        def pair(caller=caller1,auth=service_auth):
            return {**auth,'X-Workspace-Authorization':caller['Authorization']}
        yield client,pair,test,headers,system,tenant1,tenant2,service_actor,actor1


def admission(client,headers,key='one',units=4,**overrides):
    body={'policy':'tenant','global_policy':'global','units':units,'idempotency_key':key,'ttl_seconds':120}
    body.update(overrides)
    return client.post('/v1/service/admissions',headers=headers,json=body)


def test_verifies_both_signed_tokens_and_system_workspace(service):
    c,pair,test,headers,system,tenant,*_=service
    assert admission(c,{}).status_code==401
    assert admission(c,headers(system,'quotas:service')).status_code==401
    assert admission(c,{'Authorization':'Bearer forged','X-Workspace-Authorization':'Bearer forged'}).status_code==401
    assert admission(c,pair(auth=headers(tenant,'quotas:service'))).status_code==403
    assert admission(c,pair(caller=headers(tenant,'quotas:reserve'))).status_code==403
    assert admission(c,pair(caller={'Authorization':'Bearer forged'})).status_code==401
    assert admission(c,pair(),workspace_id=str(tenant)).status_code==422


def test_two_workspaces_share_global_ceiling(service):
    c,pair,test,headers,system,tenant1,tenant2,*_=service
    first=admission(c,pair(),units=6)
    assert first.status_code==200
    other=pair(caller=headers(tenant2,'ai:generate'))
    assert admission(c,other,key='two',units=5).status_code==429
    second=admission(c,other,key='three',units=4)
    assert second.status_code==200
    assert second.json()['available']==0


def test_actor_bound_mapping_and_payload_replay(service):
    c,pair,test,headers,system,tenant,_,service_actor,actor=service
    first=admission(c,pair()).json()
    assert admission(c,pair()).json()==first
    assert admission(c,pair(),units=5).status_code==409
    path='/v1/service/admissions/'+first['id']+'/settle'
    assert c.post(path,headers=pair(auth=headers(system,'quotas:service')),json={'actual_units':2}).status_code==403
    assert c.post(path,headers=pair(caller=headers(tenant,'ai:generate')),json={'actual_units':2}).status_code==403
    assert c.post(path,headers=pair(caller=headers(uuid4(),'ai:generate')),json={'actual_units':2}).status_code==404
    result=c.post(path,headers=pair(),json={'actual_units':2})
    assert result.status_code==200 and result.json()['available']==8
    assert c.post(path,headers=pair(),json={'actual_units':2}).status_code==200
    assert c.post(path,headers=pair(),json={'actual_units':3}).status_code==409
    assert c.post(path.replace('/settle','/release'),headers=pair(),json={}).status_code==409


def test_concurrent_duplicate_composite_and_release(service):
    c,pair,*_=service
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses=list(pool.map(lambda _:admission(c,pair()),range(20)))
    assert all(r.status_code==200 for r in responses)
    assert len({r.json()['id'] for r in responses})==1
    path='/v1/service/admissions/'+responses[0].json()['id']+'/release'
    with ThreadPoolExecutor(max_workers=10) as pool:
        released=list(pool.map(lambda _:c.post(path,headers=pair(),json={}),range(15)))
    assert all(r.status_code==200 and r.json()['available']==10 for r in released)


def install_fault(test,tenant,operation):
    """A real SQL failure between committed global and tenant legs, no mocked DB."""
    with psycopg.connect(test.admin_dsn) as conn:
        conn.execute(sql.SQL('''CREATE FUNCTION fail_tenant_leg() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF NEW.workspace_id = {}::uuid THEN RAISE EXCEPTION 'local acceptance fault'; END IF; RETURN NEW; END $$''').format(sql.Literal(str(tenant))))
        conn.execute(sql.SQL('CREATE TRIGGER local_acceptance_fault BEFORE {} ON data_reservations FOR EACH ROW EXECUTE FUNCTION fail_tenant_leg()').format(sql.SQL(operation)))


def remove_fault(test):
    with psycopg.connect(test.admin_dsn) as conn:
        conn.execute('DROP TRIGGER local_acceptance_fault ON data_reservations')
        conn.execute('DROP FUNCTION fail_tenant_leg()')


def test_partial_reserve_outage_recovers_stable_mapping(service):
    c,pair,test,headers,system,tenant,*_=service
    install_fault(test,tenant,'INSERT')
    assert admission(c,pair()).status_code==500
    with psycopg.connect(test.admin_dsn) as conn:
        assert conn.execute('SELECT used FROM data_quota_buckets WHERE workspace_id=%s',(system,)).fetchone()==(4,)
    remove_fault(test)
    first=admission(c,pair())
    assert first.status_code==200 and first.json()['available']==6
    assert admission(c,pair()).json()==first.json()
    with psycopg.connect(test.admin_dsn) as conn:
        assert conn.execute('SELECT count(*) FROM data_reservations').fetchone()==(2,)


def test_partial_settlement_recovers_without_double_refund(service):
    c,pair,test,headers,system,tenant,*_=service
    first=admission(c,pair()).json()
    path='/v1/service/admissions/'+first['id']+'/settle'
    install_fault(test,tenant,'UPDATE')
    assert c.post(path,headers=pair(),json={'actual_units':2}).status_code==500
    assert c.post(path,headers=pair(),json={'actual_units':3}).status_code==409
    remove_fault(test)
    result=c.post(path,headers=pair(),json={'actual_units':2})
    assert result.status_code==200 and result.json()['available']==8
    with psycopg.connect(test.admin_dsn) as conn:
        assert conn.execute('SELECT used FROM data_quota_buckets ORDER BY workspace_id').fetchall()==[(2,),(2,)]


def test_tenant_failure_retains_global_and_later_recovers(service):
    c,pair,test,headers,system,tenant,*_=service
    put_policy(c,headers(tenant),limit=0,key='tenant')
    assert admission(c,pair()).status_code==429
    with psycopg.connect(test.admin_dsn) as conn:
        assert conn.execute('SELECT used FROM data_quota_buckets WHERE workspace_id=%s',(system,)).fetchone()==(4,)
    put_policy(c,headers(tenant),limit=10,key='tenant')
    assert admission(c,pair()).status_code==200


def test_readiness_checks_each_write_privilege(service):
    c,pair,test,*_=service
    for table in ('data_cache','data_counters','data_documents','data_quota_policies','data_quota_buckets','data_reservations','data_service_admissions'):
        for privilege in ('INSERT','UPDATE','DELETE'):
            with psycopg.connect(test.admin_dsn) as conn:
                conn.execute(sql.SQL('REVOKE {} ON {} FROM {}').format(sql.SQL(privilege),sql.Identifier(table),sql.Identifier(test.runtime_role)))
            assert c.get('/readyz').status_code==503
            with psycopg.connect(test.admin_dsn) as conn:
                conn.execute(sql.SQL('GRANT {} ON {} TO {}').format(sql.SQL(privilege),sql.Identifier(table),sql.Identifier(test.runtime_role)))
    assert c.get('/readyz').status_code==200


def test_missing_system_configuration_fails_closed(runtime):
    c,a,b,db,test,verifier,headers=runtime
    auth=headers(uuid4(),'quotas:service')
    assert admission(c,{**auth,'X-Workspace-Authorization':headers(uuid4(),'ai:generate')['Authorization']}).status_code==503


def test_expired_composite_preserves_both_charges_and_late_settles(service):
    import time
    c,pair,test,*_=service
    first=admission(c,pair(),ttl_seconds=1).json()
    time.sleep(1.1)
    path='/v1/service/admissions/'+first['id']
    result=c.post(path+'/release',headers=pair(),json={})
    assert result.status_code==200 and result.json()['status']=='expired'
    with psycopg.connect(test.admin_dsn) as conn:
        assert conn.execute('SELECT used FROM data_quota_buckets ORDER BY workspace_id').fetchall()==[(4,),(4,)]
    result=c.post(path+'/settle',headers=pair(),json={'actual_units':2})
    assert result.status_code==200 and result.json()['status']=='settled'
    with psycopg.connect(test.admin_dsn) as conn:
        assert conn.execute('SELECT used FROM data_quota_buckets ORDER BY workspace_id').fetchall()==[(2,),(2,)]


def test_partial_release_retry_never_double_refunds(service):
    c,pair,test,headers,system,tenant,*_=service
    first=admission(c,pair()).json()
    path='/v1/service/admissions/'+first['id']+'/release'
    install_fault(test,tenant,'UPDATE')
    result=c.post(path,headers=pair(),json={})
    assert result.status_code==500
    remove_fault(test)
    assert c.post(path,headers=pair(),json={}).status_code==200
    assert c.post(path,headers=pair(),json={}).status_code==200
    with psycopg.connect(test.admin_dsn) as conn:
        assert conn.execute('SELECT used FROM data_quota_buckets ORDER BY workspace_id').fetchall()==[(0,),(0,)]


def test_composite_actual_overrun_keeps_global_debt(service):
    c,pair,test,headers,system,tenant1,tenant2,*_=service
    first=admission(c,pair()).json()
    result=c.post('/v1/service/admissions/'+first['id']+'/settle',headers=pair(),json={'actual_units':13})
    assert result.status_code==200 and result.json()['available']==0
    assert admission(c,pair(caller=headers(tenant2,'ai:generate')),key='other',units=1).status_code==429
    with psycopg.connect(test.admin_dsn) as conn:
        assert conn.execute('SELECT debt FROM data_quota_policies WHERE workspace_id=%s',(system,)).fetchone()==(3,)
        assert conn.execute('SELECT used FROM data_quota_buckets ORDER BY workspace_id').fetchall()==[(13,),(13,)]


def test_missing_global_policy_never_reserves_tenant(service):
    c,pair,test,*_=service
    result=admission(c,pair(),global_policy='missing')
    assert result.status_code==503
    with psycopg.connect(test.admin_dsn) as conn:
        assert conn.execute('SELECT count(*) FROM data_reservations').fetchone()==(0,)


def test_composite_mapping_survives_app_recreation(service,runtime):
    c,pair,test,headers,system,*_=service
    first=admission(c,pair()).json()
    with TestClient(create_app(Database(test.runtime_dsn),runtime[5],system_workspace=system)) as replica:
        replay=admission(replica,pair())
        assert replay.status_code==200 and replay.json()==first
        result=replica.post('/v1/service/admissions/'+first['id']+'/settle',headers=pair(),json={'actual_units':3})
        assert result.status_code==200 and result.json()['available']==7


def test_unavailable_database_never_grants_admission(service):
    c,pair,*_=service
    c.app.state.database.close()
    assert c.get('/readyz').status_code==503
    result=admission(c,pair())
    assert result.status_code==500


def test_concurrent_tenants_cannot_overshoot_shared_global(service):
    c,pair,test,headers,system,tenant1,tenant2,*_=service
    other=pair(caller=headers(tenant2,'ai:generate'))
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses=list(pool.map(lambda i:admission(c,pair() if i%2 else other,key=f'parallel-{i}',units=1),range(30)))
    assert sum(r.status_code==200 for r in responses)==10
    assert sum(r.status_code==429 for r in responses)==20
    with psycopg.connect(test.admin_dsn) as conn:
        assert conn.execute('SELECT used FROM data_quota_buckets WHERE workspace_id=%s',(system,)).fetchone()==(10,)
