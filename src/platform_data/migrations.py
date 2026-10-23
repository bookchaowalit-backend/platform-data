"""Immutable explicit migrations, applied through the shared runtime."""
from platform_backend_core import Migration

_TABLES = '''
CREATE TABLE data_cache (
 workspace_id uuid NOT NULL, key text NOT NULL, value jsonb NOT NULL,
 expires_at timestamptz NOT NULL, PRIMARY KEY(workspace_id,key));
CREATE TABLE data_counters (
 workspace_id uuid NOT NULL, key text NOT NULL, value bigint NOT NULL CHECK(value>=0),
 window_seconds integer NOT NULL, expires_at timestamptz NOT NULL,
 PRIMARY KEY(workspace_id,key));
CREATE TABLE data_documents (
 workspace_id uuid NOT NULL, key text NOT NULL, text text NOT NULL, metadata jsonb NOT NULL,
 search tsvector GENERATED ALWAYS AS (to_tsvector('simple',text)) STORED,
 PRIMARY KEY(workspace_id,key));
CREATE INDEX data_documents_search ON data_documents USING gin(search);
CREATE TABLE data_quota_policies (
 workspace_id uuid NOT NULL, key text NOT NULL, limit_units bigint NOT NULL CHECK(limit_units>=0),
 window_seconds integer NOT NULL CHECK(window_seconds>0), debt bigint NOT NULL DEFAULT 0 CHECK(debt>=0),
 PRIMARY KEY(workspace_id,key));
CREATE TABLE data_quota_buckets (
 workspace_id uuid NOT NULL, policy text NOT NULL, period bigint NOT NULL,
 used bigint NOT NULL DEFAULT 0 CHECK(used>=0), PRIMARY KEY(workspace_id,policy,period),
 FOREIGN KEY(workspace_id,policy) REFERENCES data_quota_policies(workspace_id,key));
CREATE TABLE data_reservations (
 workspace_id uuid NOT NULL, id uuid NOT NULL, policy text NOT NULL,
 period bigint NOT NULL, units bigint NOT NULL CHECK(units>0), ttl_seconds integer NOT NULL,
 idempotency_key text NOT NULL, expires_at timestamptz NOT NULL,
 status text NOT NULL CHECK(status IN ('pending','expired','settled','released')),
 actual_units bigint CHECK(actual_units>=0), initial_available bigint NOT NULL,
 PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,idempotency_key),
 FOREIGN KEY(workspace_id,policy,period) REFERENCES data_quota_buckets(workspace_id,policy,period));
CREATE INDEX data_reservations_policy ON data_reservations(workspace_id,policy,status,expires_at);
CREATE INDEX data_cache_expiry ON data_cache(workspace_id,expires_at);
'''
_RLS = ''.join(f'''
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_isolation ON {table}
USING (workspace_id = nullif(current_setting('app.workspace_id',true),'')::uuid)
WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id',true),'')::uuid);
''' for table in ('data_cache','data_counters','data_documents','data_quota_policies','data_quota_buckets','data_reservations'))
MIGRATIONS = (Migration('001_data_primitives', _TABLES + _RLS),)

_SERVICE_ADMISSIONS = '''
CREATE TABLE data_service_admissions (
 workspace_id uuid NOT NULL, id uuid NOT NULL,
 service_workspace uuid NOT NULL, service_actor uuid NOT NULL, caller_actor uuid NOT NULL,
 policy text NOT NULL, global_policy text NOT NULL,
 units bigint NOT NULL CHECK(units>0), ttl_seconds integer NOT NULL,
 idempotency_key text NOT NULL,
 global_reservation_id uuid, tenant_reservation_id uuid,
 status text NOT NULL DEFAULT 'preparing'
 CHECK(status IN ('preparing','pending','expired','settled','released')),
 operation text CHECK(operation IN ('settle','release')),
 actual_units bigint CHECK(actual_units>=0),
 expires_at timestamptz, available_units bigint,
 PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,idempotency_key),
 FOREIGN KEY(service_workspace,global_reservation_id) REFERENCES data_reservations(workspace_id,id),
 FOREIGN KEY(workspace_id,tenant_reservation_id) REFERENCES data_reservations(workspace_id,id));
ALTER TABLE data_service_admissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_service_admissions FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_isolation ON data_service_admissions
USING (workspace_id = nullif(current_setting('app.workspace_id',true),'')::uuid)
WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id',true),'')::uuid);
'''
# Migration 001 remains byte-for-byte unchanged; upgrades append immutable history.
MIGRATIONS += (Migration('002_service_admissions', _SERVICE_ADMISSIONS),)
