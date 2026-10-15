"""Real PostgreSQL acceptance; requires explicit disposable local admin DSN."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from platform_backend_core import Database, MigrationRunner, TokenVerifier
from platform_backend_core.testing import temporary_database

from platform_data.app import create_app
from platform_data.migrations import MIGRATIONS

SCOPES = 'cache:read cache:write counters:write documents:read documents:write quotas:write quotas:reserve quotas:settle'

@pytest.fixture
def runtime():
    admin = os.environ['PLATFORM_TEST_DSN']  # fail rather than silently skip
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = TokenVerifier(issuer='local-test', audience='platform-api', public_key=key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    with temporary_database(admin, prefix='data_test_') as test:
        MigrationRunner(test.admin_dsn, namespace='data').apply(MIGRATIONS)
        test.grant_schema('public')
        db = Database(test.runtime_dsn, max_size=16)
        app = create_app(db, verifier)
        with TestClient(app) as client:
            def headers(ws, scopes=SCOPES, actor=None):
                now = int(time.time())
                token = jwt.encode(dict(iss='local-test', aud='platform-api', sub=str(actor or uuid4()), ws=str(ws), iat=now, exp=now+300, jti=str(uuid4()), scope=scopes), key, algorithm='RS256')
                return {'Authorization': 'Bearer '+token}
            yield client, headers(uuid4()), headers(uuid4()), db, test, verifier, headers


def put_policy(c, h, limit=10, window=31536000, key='tokens'):
    r = c.put('/v1/quotas/'+key, headers=h, json={'limit':limit, 'window_seconds':window})
    assert r.status_code == 200, r.text


def reserve(c, h, key='one', units=4, policy='tokens', ttl=120):
    return c.post('/v1/reservations', headers=h, json={'policy':policy,'units':units,'idempotency_key':key,'ttl_seconds':ttl})


def test_cache_isolation_expiry_and_bounds(runtime):
    c,a,b,*_ = runtime
    assert c.put('/v1/cache/shared', headers=a, json={'value':{'ok':1},'ttl_seconds':1}).status_code == 200
    first=c.get('/v1/cache/shared', headers=a).json()
    assert first['value'] == {'ok':1}
    assert c.get('/v1/cache/shared', headers=b).status_code == 404
    assert c.put('/v1/cache/shared', headers=b, json={'value':'other','ttl_seconds':60}).status_code == 200
    assert c.get('/v1/cache/shared', headers=a).json()['value'] == {'ok':1}
    assert c.get('/v1/cache/shared', headers=a).json()['expires_at'] == first['expires_at']
    assert c.put('/v1/cache/k', headers=a, json={'value':0,'ttl_seconds':86401}).status_code == 422
    time.sleep(1.1)
    assert c.get('/v1/cache/shared', headers=a).status_code == 404


def test_counters_atomic_stable_window_and_tenant(runtime):
    c,a,b,*_ = runtime
    def inc(_):
        r=c.post('/v1/counters/hits/increment',headers=a,json={'amount':1,'window_seconds':60})
        assert r.status_code == 200, r.text
        return r.json()
    with ThreadPoolExecutor(max_workers=12) as pool:
        rows=list(pool.map(inc,range(40)))
    assert sorted(r['value'] for r in rows)==list(range(1,41))
    assert len(set(r['expires_at'] for r in rows))==1
    assert c.post('/v1/counters/hits/increment',headers=b,json={'amount':1,'window_seconds':60}).json()['value']==1
    assert c.post('/v1/counters/hits/increment',headers=a,json={'amount':1,'window_seconds':61}).status_code==409


def test_search_plain_text_isolation_and_page(runtime):
    c,a,b,*_ = runtime
    for name,text in [('one','alpha beta สวัสดี'),('two','alpha gamma')]:
        assert c.put('/v1/documents/'+name,headers=a,json={'text':text,'metadata':{'name':name}}).status_code==200
    r=c.get('/v1/documents',headers=a,params={'q':'alpha','limit':1}).json()
    assert len(r['items'])==1
    assert c.get('/v1/documents',headers=b,params={'q':'alpha'}).json()['items']==[]
    assert c.put('/v1/documents/one',headers=b,json={'text':'unrelated tenant'}).status_code==200
    assert len(c.get('/v1/documents',headers=a,params={'q':'alpha'}).json()['items'])==2
    assert c.get('/v1/documents',headers=a,params={'q':"alpha' | !"}).status_code==200
    assert c.get('/v1/documents',headers=a,params={'q':'alpha','limit':101}).status_code==422


def test_missing_policy_auth_and_caller_authority(runtime):
    c,a,b,db,t,v,headers=runtime
    assert reserve(c,a).status_code==503
    assert c.put('/v1/quotas/tokens',headers=headers(uuid4(),'quotas:reserve'),json={'limit':10,'window_seconds':60}).status_code==403
    assert c.put('/v1/quotas/tokens',headers=a,json={'limit':10,'window_seconds':60,'workspace_id':str(uuid4())}).status_code==422
    put_policy(c,a)
    assert reserve(c,b).status_code==503
    assert reserve(c,a,units=True).status_code==422


def test_concurrent_reservations_never_overshoot(runtime):
    c,a,*_=runtime
    put_policy(c,a,limit=10)
    with ThreadPoolExecutor(max_workers=12) as pool:
        rows=list(pool.map(lambda i:reserve(c,a,key=str(i),units=1),range(30)))
    assert sum(r.status_code==200 for r in rows)==10
    assert sum(r.status_code==429 for r in rows)==20


def test_idempotency_conflict_and_settle_release_exactly_once(runtime):
    c,a,*_=runtime
    put_policy(c,a)
    first=reserve(c,a).json()
    assert first['units']==4 and first['status']=='pending' and first['available']==6
    assert reserve(c,a).json()==first
    assert reserve(c,a,units=5).status_code==409
    path='/v1/reservations/'+first['id']+'/settle'
    assert c.post(path,headers=a,json={'actual_units':2}).json()['status']=='settled'
    assert c.post(path,headers=a,json={'actual_units':2}).json()['available']==8
    assert c.post(path,headers=a,json={'actual_units':3}).status_code==409
    assert c.post('/v1/reservations/'+first['id']+'/release',headers=a,json={}).status_code==409
    second=reserve(c,a,key='two',units=8).json()
    path='/v1/reservations/'+second['id']+'/release'
    assert c.post(path,headers=a,json={}).json()['available']==8
    assert c.post(path,headers=a,json={}).json()['available']==8


def test_expiry_stays_charged_and_late_settlement(runtime):
    c,a,*_=runtime
    put_policy(c,a,limit=4)
    first=reserve(c,a,ttl=1).json()
    time.sleep(1.1)
    assert reserve(c,a,key='two',units=1).status_code==429
    assert c.post('/v1/reservations/'+first['id']+'/release',headers=a,json={}).json()['status']=='expired'
    assert reserve(c,a,key='two',units=1).status_code==429
    assert c.post('/v1/reservations/'+first['id']+'/settle',headers=a,json={'actual_units':2}).json()['available']==2


def test_overrun_debt_blocks_following_windows(runtime):
    c,a,*_=runtime
    put_policy(c,a,limit=4,window=1)
    first=reserve(c,a,units=4).json()
    r=c.post('/v1/reservations/'+first['id']+'/settle',headers=a,json={'actual_units':7})
    assert r.status_code==200 and r.json()['available']==0
    time.sleep(1.1)
    assert reserve(c,a,key='two',units=1).status_code==429


def test_restart_and_cross_tenant_reservation(runtime):
    c,a,b,db,t,v,_=runtime
    put_policy(c,a)
    first=reserve(c,a).json()
    assert c.post('/v1/reservations/'+first['id']+'/release',headers=b,json={}).status_code==404
    other=Database(t.runtime_dsn)
    with TestClient(create_app(other,v)) as replica:
        assert reserve(replica,a).json()==first
        assert replica.post('/v1/reservations/'+first['id']+'/settle',headers=a,json={'actual_units':3}).json()['available']==7


def test_missing_migration_readiness(runtime):
    c,a,b,db,t,v,_=runtime
    with temporary_database(os.environ['PLATFORM_TEST_DSN'],prefix='data_test_') as missing:
        other=Database(missing.runtime_dsn)
        with TestClient(create_app(other,v)) as replica:
            assert replica.get('/readyz').status_code==503
    assert c.get('/readyz').status_code==200


def process_reserves(args):
    dsn,public_key,auth,index=args
    verifier=TokenVerifier(issuer='local-test',audience='platform-api',public_key=public_key)
    with TestClient(create_app(Database(dsn,max_size=2),verifier)) as client:
        return [reserve(client,auth,key=f'process-{index}-{i}',units=1).status_code for i in range(10)]


def test_independent_processes_share_capacity(runtime):
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    c,a,b,db,t,v,_=runtime
    # Processes receive only a configured public PEM, never the signing key.
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pem=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    now=int(time.time())
    workspace=uuid4()
    token=jwt.encode(dict(iss='local-test',aud='platform-api',sub=str(uuid4()),ws=str(workspace),iat=now,exp=now+300,jti=str(uuid4()),scope=SCOPES),key,algorithm='RS256')
    auth={'Authorization':'Bearer '+token}
    verifier=TokenVerifier(issuer='local-test',audience='platform-api',public_key=pem)
    with TestClient(create_app(Database(t.runtime_dsn),verifier)) as setup:
        put_policy(setup,auth,limit=13)
    with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('spawn')) as pool:
        rows=list(pool.map(process_reserves,[(t.runtime_dsn,pem,auth,i) for i in range(4)]))
    statuses=[status for row in rows for status in row]
    assert statuses.count(200)==13
    assert statuses.count(429)==27


def test_readiness_checks_migration_history(runtime):
    import psycopg
    c,a,b,db,t,*_=runtime
    with psycopg.connect(t.admin_dsn) as conn:
        conn.execute("UPDATE platform_schema_migrations SET checksum='drift' WHERE namespace='data'")
    assert c.get('/readyz').status_code==503


def test_rejects_postgres_unsupported_text_and_large_json(runtime):
    c,a,*_=runtime
    assert c.put('/v1/documents/nul',headers=a,json={'text':'bad\x00text'}).status_code==422
    assert c.put('/v1/cache/nul',headers=a,json={'value':{'bad':'\x00'},'ttl_seconds':10}).status_code==422
    assert c.put('/v1/cache/large',headers=a,json={'value':'x'*65537,'ttl_seconds':10}).status_code==422


def test_cli_missing_configuration_fails_safely():
    import subprocess
    result=subprocess.run([__import__('sys').executable,'-m','platform_data','migrate'],env={'PATH':os.environ['PATH']},capture_output=True,text=True)
    assert result.returncode!=0
    assert 'DATABASE_URL' in result.stderr
    assert 'Traceback' not in result.stderr


def test_concurrent_duplicate_finalize_only_changes_usage_once(runtime):
    c,a,*_=runtime
    put_policy(c,a,limit=10)
    first=reserve(c,a,units=8).json()
    path='/v1/reservations/'+first['id']+'/settle'
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows=list(pool.map(lambda _:c.post(path,headers=a,json={'actual_units':3}),range(12)))
    assert all(r.status_code==200 and r.json()['available']==7 for r in rows)
    assert reserve(c,a,key='remaining',units=7).status_code==200
    assert reserve(c,a,key='excess',units=1).status_code==429


def test_runtime_role_force_rls_and_cross_workspace_write(runtime):
    import psycopg
    c,a,b,db,t,*_=runtime
    with db.transaction(uuid4()) as conn:
        role=conn.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        assert role==(False,False)
        tables=conn.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname LIKE 'data_%' AND relkind='r'").fetchall()
        assert len(tables)==7 and all(enabled and forced for _,enabled,forced in tables)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO data_cache VALUES(%s,'foreign','{}',clock_timestamp()+interval '1 hour')",(uuid4(),))
    # Failed writes roll back and do not poison the pool.
    assert c.get('/readyz').status_code==200


def test_counter_window_expires_once(runtime):
    c,a,*_=runtime
    first=c.post('/v1/counters/short/increment',headers=a,json={'amount':3,'window_seconds':1}).json()
    time.sleep(1.1)
    second=c.post('/v1/counters/short/increment',headers=a,json={'amount':2,'window_seconds':1}).json()
    assert second['value']==2
    assert second['expires_at']>first['expires_at']


def test_cache_accepts_literal_escaped_unicode_text(runtime):
    c,a,*_=runtime
    r=c.put('/v1/cache/literal',headers=a,json={'value':r'\u0000','ttl_seconds':60})
    assert r.status_code==200
    assert c.get('/v1/cache/literal',headers=a).json()['value']==r'\u0000'


def test_cli_explicit_migrate_is_repeatable(runtime):
    import subprocess
    c,a,b,db,t,*_=runtime
    result=subprocess.run([__import__('sys').executable,'-m','platform_data','migrate'],env={'PATH':os.environ['PATH'],'DATABASE_URL':t.admin_dsn},capture_output=True,text=True)
    assert result.returncode==0
    assert result.stdout.strip()=='applied 0 data migrations'
