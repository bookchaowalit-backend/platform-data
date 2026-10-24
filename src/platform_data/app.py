"""Bounded workspace APIs. PostgreSQL is the concurrency/correctness boundary."""
import json
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Path, Query
from platform_backend_core import Database, Principal, TokenVerifier, require_scope
from platform_backend_core import create_app as core_app
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .migrations import MIGRATIONS

Key = Annotated[str, Path(min_length=1, max_length=200, pattern=r'^[^\x00]+$')]
Positive = Annotated[int, Field(strict=True, ge=1, le=10**12)]
Seconds = Annotated[int, Field(strict=True, ge=1, le=86400)]

class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')


def bounded_json(value, limit):
    def validate_strings(node):
        if isinstance(node, str) and '\x00' in node:
            raise ValueError('unsupported JSON string')
        if isinstance(node, dict):
            for key, child in node.items():
                validate_strings(key)
                validate_strings(child)
        elif isinstance(node, list):
            for child in node:
                validate_strings(child)

    try:
        validate_strings(value)
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        if len(encoded.encode()) > limit:
            raise ValueError('JSON too large')
    except (TypeError, ValueError, RecursionError):
        raise ValueError('invalid or oversized JSON') from None
    return value

class CacheWrite(Body):
    value: Any
    ttl_seconds: Seconds

    @field_validator('value')
    @classmethod
    def bound(cls, value):
        return bounded_json(value, 65536)

class Increment(Body):
    amount: Positive = 1
    window_seconds: Seconds

class Document(Body):
    text: str = Field(max_length=200000)
    metadata: dict = Field(default_factory=dict)

    @field_validator('text')
    @classmethod
    def valid_text(cls, value):
        if '\x00' in value:
            raise ValueError('unsupported text')
        value.encode('utf-8')
        return value

    @field_validator('metadata')
    @classmethod
    def bound(cls, value):
        return bounded_json(value, 16384)

class Policy(Body):
    limit: Annotated[int, Field(strict=True, ge=0, le=10**12)]
    window_seconds: Annotated[int, Field(strict=True, ge=1, le=31536000)]

class Reservation(Body):
    policy: str = Field(min_length=1, max_length=200, pattern=r'^[^\x00]+$')
    units: Positive
    idempotency_key: str = Field(min_length=1, max_length=200, pattern=r'^[^\x00]+$')
    ttl_seconds: Seconds = 120

class Settlement(Body):
    actual_units: Annotated[int, Field(strict=True, ge=0, le=10**12)]


def one(conn, sql, args=()):
    with conn.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(sql, args).fetchone()


def policy_lock(conn, key):
    row=one(conn,'SELECT * FROM data_quota_policies WHERE key=%s FOR UPDATE',(key,))
    if row is None:
        raise HTTPException(503,'Quota policy unavailable')
    return row


def current_period(conn, policy):
    return one(conn,'SELECT floor(extract(epoch FROM clock_timestamp()) / %s)::bigint AS period',(policy['window_seconds'],))['period']


def available(conn, policy):
    if policy['debt']:
        return 0
    bucket=one(conn,'SELECT used FROM data_quota_buckets WHERE policy=%s AND period=%s',(policy['key'],current_period(conn,policy)))
    return max(0,policy['limit_units']-(bucket['used'] if bucket else 0))


def envelope(row, capacity):
    return dict(id=str(row['id']),status=row['status'],units=row['units'],expires_at=row['expires_at'],available=capacity)


def expire(conn, row):
    row=one(conn,"UPDATE data_reservations SET status=CASE WHEN status='pending' AND expires_at<=clock_timestamp() THEN 'expired' ELSE status END WHERE id=%s RETURNING *",(row['id'],))
    return row


def create_app(database: Database, verifier: TokenVerifier, *, system_workspace: UUID | None = None):
    if system_workspace is not None and not isinstance(system_workspace, UUID):
        raise ValueError("system_workspace must be a UUID")
    app=core_app('platform-data',database,verifier,max_body_bytes=1048576)

    def schema_ready():
        with database.transaction(UUID(int=0)) as conn:
            # Shared migration history contains release metadata, never tenant data.
            history = dict(conn.execute('SELECT version,checksum FROM platform_schema_migrations WHERE namespace=%s', ('data',)).fetchall())
            expected = {migration.version: migration.checksum for migration in MIGRATIONS}
            tables = ('data_cache', 'data_counters', 'data_documents', 'data_quota_policies', 'data_quota_buckets', 'data_reservations', 'data_service_admissions')
            if history != expected:
                return False
            for table in tables:
                if not one(conn, 'SELECT to_regclass(%s) IS NOT NULL AS ok', ('public.' + table,))['ok']:
                    return False
                for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
                    if not one(conn, 'SELECT has_table_privilege(%s,%s) AS ok', ('public.' + table, privilege))['ok']:
                        return False
            return one(conn, "SELECT has_schema_privilege('public','USAGE') AS ok")['ok']
    app.state.readiness_checks['data_schema']=schema_ready

    @app.put('/v1/cache/{key}')
    def cache_put(key: Key, body: CacheWrite, p: Principal=Depends(require_scope('cache:write'))):
        with database.transaction(p.workspace) as conn:
            return one(conn,"INSERT INTO data_cache VALUES(%s,%s,%s,clock_timestamp()+%s*interval '1 second') ON CONFLICT(workspace_id,key) DO UPDATE SET value=excluded.value,expires_at=excluded.expires_at RETURNING key,value,expires_at",(p.workspace,key,Jsonb(body.value),body.ttl_seconds))

    @app.get('/v1/cache/{key}')
    def cache_get(key: Key,p: Principal=Depends(require_scope('cache:read'))):
        with database.transaction(p.workspace) as conn:
            row=one(conn,'SELECT key,value,expires_at FROM data_cache WHERE key=%s AND expires_at>clock_timestamp()',(key,))
            if row is None:
                raise HTTPException(404,'Cache entry not found')
            return row

    @app.delete('/v1/cache/{key}')
    def cache_delete(key: Key,p: Principal=Depends(require_scope('cache:write'))):
        with database.transaction(p.workspace) as conn:
            conn.execute('DELETE FROM data_cache WHERE key=%s',(key,))
        return {'deleted':True}

    @app.post('/v1/counters/{key}/increment')
    def increment(key: Key,body: Increment,p: Principal=Depends(require_scope('counters:write'))):
        with database.transaction(p.workspace) as conn:
            row=one(conn,"""INSERT INTO data_counters VALUES(%s,%s,%s,%s,statement_timestamp()+%s*interval '1 second')
            ON CONFLICT(workspace_id,key) DO UPDATE SET
            value=CASE WHEN data_counters.expires_at<=statement_timestamp() THEN excluded.value ELSE data_counters.value+excluded.value END,
            window_seconds=CASE WHEN data_counters.expires_at<=statement_timestamp() THEN excluded.window_seconds ELSE data_counters.window_seconds END,
            expires_at=CASE WHEN data_counters.expires_at<=statement_timestamp() THEN excluded.expires_at ELSE data_counters.expires_at END
            RETURNING key,value,window_seconds,expires_at""",(p.workspace,key,body.amount,body.window_seconds,body.window_seconds))
            if row['window_seconds']!=body.window_seconds:
                raise HTTPException(409,'Counter window differs')
            return row

    @app.put('/v1/documents/{key}')
    def document_put(key: Key,body: Document,p: Principal=Depends(require_scope('documents:write'))):
        with database.transaction(p.workspace) as conn:
            conn.execute('INSERT INTO data_documents(workspace_id,key,text,metadata) VALUES(%s,%s,%s,%s) ON CONFLICT(workspace_id,key) DO UPDATE SET text=excluded.text,metadata=excluded.metadata',(p.workspace,key,body.text,Jsonb(body.metadata)))
        return {'key':key}

    @app.delete('/v1/documents/{key}')
    def document_delete(key: Key,p: Principal=Depends(require_scope('documents:write'))):
        with database.transaction(p.workspace) as conn:
            conn.execute('DELETE FROM data_documents WHERE key=%s',(key,))
        return {'deleted':True}

    @app.get('/v1/documents')
    def search(q: Annotated[str,Query(min_length=1,max_length=512,pattern=r'^[^\x00]+$')],limit: Annotated[int,Query(ge=1,le=100)]=20,offset: Annotated[int,Query(ge=0,le=10000)]=0,p: Principal=Depends(require_scope('documents:read'))):
        with database.transaction(p.workspace) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                rows=cursor.execute("SELECT key,text,metadata FROM data_documents WHERE search @@ plainto_tsquery('simple',%s) ORDER BY key LIMIT %s OFFSET %s",(q,limit,offset)).fetchall()
                return {'items':rows,'limit':limit,'offset':offset}

    @app.put('/v1/quotas/{key}')
    def quota_put(key: Key,body: Policy,p: Principal=Depends(require_scope('quotas:write'))):
        with database.transaction(p.workspace) as conn:
            row=one(conn,'INSERT INTO data_quota_policies(workspace_id,key,limit_units,window_seconds) VALUES(%s,%s,%s,%s) ON CONFLICT(workspace_id,key) DO UPDATE SET limit_units=excluded.limit_units RETURNING *',(p.workspace,key,body.limit,body.window_seconds))
            if row['window_seconds']!=body.window_seconds:
                raise HTTPException(409,'Existing quota window is immutable')
            return {'key':key,'limit':row['limit_units'],'window_seconds':row['window_seconds'],'debt':row['debt']}

    @app.post('/v1/reservations')
    def reserve(body: Reservation,p: Principal=Depends(require_scope('quotas:reserve'))):
        with database.transaction(p.workspace) as conn:
            # Serialize the idempotency key even across different policies.
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(p.workspace)+':'+body.idempotency_key,))
            existing=one(conn,'SELECT * FROM data_reservations WHERE idempotency_key=%s',(body.idempotency_key,))
            if existing and (existing['policy'],existing['units'],existing['ttl_seconds'])!=(body.policy,body.units,body.ttl_seconds):
                raise HTTPException(409,'Idempotency payload differs')
            policy=policy_lock(conn,body.policy)
            if existing:
                row=expire(conn,existing)
                return envelope(row,row['initial_available'] if row['status']=='pending' else available(conn,policy))
            period=current_period(conn,policy)
            conn.execute('INSERT INTO data_quota_buckets(workspace_id,policy,period) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(p.workspace,body.policy,period))
            bucket=one(conn,'SELECT used FROM data_quota_buckets WHERE policy=%s AND period=%s FOR UPDATE',(body.policy,period))
            capacity=max(0,policy['limit_units']-bucket['used']) if policy['debt']==0 else 0
            if body.units>capacity:
                raise HTTPException(429,'Quota exhausted')
            conn.execute('UPDATE data_quota_buckets SET used=used+%s WHERE policy=%s AND period=%s',(body.units,body.policy,period))
            row=one(conn,"""INSERT INTO data_reservations(workspace_id,id,policy,period,units,ttl_seconds,idempotency_key,expires_at,status,initial_available)
            VALUES(%s,%s,%s,%s,%s,%s,%s,clock_timestamp()+%s*interval '1 second','pending',%s) RETURNING *""",(p.workspace,uuid4(),body.policy,period,body.units,body.ttl_seconds,body.idempotency_key,body.ttl_seconds,capacity-body.units))
            return envelope(row,capacity-body.units)

    def finish(id, actual, release, p):
        with database.transaction(p.workspace) as conn:
            row=one(conn,'SELECT * FROM data_reservations WHERE id=%s',(id,))
            if row is None:
                raise HTTPException(404,'Reservation not found')
            policy=policy_lock(conn,row['policy'])
            row=expire(conn,row)
            if release and row['status']=='expired':
                return envelope(row,available(conn,policy))
            target='released' if release else 'settled'
            if row['status'] in ('settled','released'):
                if row['status']!=target or row['actual_units']!=actual:
                    raise HTTPException(409,'Reservation already finalized differently')
                return envelope(row,available(conn,policy))
            bucket=one(conn,'UPDATE data_quota_buckets SET used=used+%s WHERE policy=%s AND period=%s RETURNING used',(actual-row['units'],row['policy'],row['period']))
            debt=max(0,bucket['used']-policy['limit_units'])
            # Debt never disappears with window rollover or policy edits.
            policy=one(conn,'UPDATE data_quota_policies SET debt=greatest(debt,%s) WHERE key=%s RETURNING *',(debt,row['policy']))
            row=one(conn,'UPDATE data_reservations SET status=%s,actual_units=%s WHERE id=%s RETURNING *',(target,actual,id))
            return envelope(row,available(conn,policy))

    @app.post('/v1/reservations/{id}/settle')
    def settle(id: UUID,body: Settlement,p: Principal=Depends(require_scope('quotas:settle'))):
        return finish(id,body.actual_units,False,p)

    @app.post('/v1/reservations/{id}/release')
    def release(id: UUID,body: Body,p: Principal=Depends(require_scope('quotas:settle'))):
        return finish(id,0,True,p)

    from .service_admissions import register_service_admissions
    register_service_admissions(app, database, verifier, reserve, finish, system_workspace)
    return app
