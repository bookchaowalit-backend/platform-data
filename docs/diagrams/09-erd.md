# 09 — ERD

Status: **done**

```mermaid
erDiagram
  data_cache {
    uuid workspace_id PK
    text key PK
    jsonb value
    timestamptz expires_at
  }
  data_counters {
    uuid workspace_id PK
    text key PK
    bigint value "CHECK >= 0"
    integer window_seconds
    timestamptz expires_at
  }
  data_documents {
    uuid workspace_id PK
    text key PK
    text text
    jsonb metadata
    tsvector search "GENERATED simple, GIN index"
  }
  data_quota_policies {
    uuid workspace_id PK
    text key PK
    bigint limit_units "CHECK >= 0"
    integer window_seconds "CHECK > 0"
    bigint debt "DEFAULT 0"
  }
  data_quota_buckets {
    uuid workspace_id PK
    text policy PK
    bigint period PK
    bigint used "DEFAULT 0"
  }
  data_reservations {
    uuid workspace_id PK
    uuid id PK
    text policy FK
    bigint period FK
    bigint units "CHECK > 0"
    integer ttl_seconds
    text idempotency_key "UNIQUE per workspace"
    timestamptz expires_at
    text status
    bigint actual_units
    bigint initial_available
  }
  data_service_admissions {
    uuid workspace_id PK
    uuid id PK
    uuid service_workspace FK
    uuid service_actor
    uuid caller_actor
    text policy
    text global_policy
    bigint units
    integer ttl_seconds
    text idempotency_key "UNIQUE per workspace"
    uuid global_reservation_id FK
    uuid tenant_reservation_id FK
    text status "DEFAULT preparing"
    text operation "settle or release"
    bigint actual_units
    timestamptz expires_at
    bigint available_units
  }
  platform_schema_migrations {
    text namespace PK
    text version PK
    text checksum
    timestamptz applied_at
  }

  data_quota_policies ||--o{ data_quota_buckets : "workspace_id, policy"
  data_quota_buckets ||--o{ data_reservations : "workspace_id, policy, period"
  data_reservations |o--o{ data_service_admissions : "global leg: service_workspace, global_reservation_id"
  data_reservations |o--o{ data_service_admissions : "tenant leg: workspace_id, tenant_reservation_id"
```

Sources: `src/platform_data/migrations.py` (`001_data_primitives`, `002_service_admissions`); platform-backend-core @`21d5f44`
`migrations.py` (`platform_schema_migrations`).

## RLS / role notes

- ทั้ง 7 ตาราง `data_*`: `ENABLE` + `FORCE ROW LEVEL SECURITY`, policy `workspace_isolation` USING + WITH CHECK บน `app.workspace_id`
- `platform_schema_migrations` ไม่มี RLS (shared release metadata, ไม่มีข้อมูล tenant — comment ใน `schema_ready`)
- runtime role: USAGE schema, SELECT/INSERT/UPDATE/DELETE บน 7 ตาราง, SELECT บน migrations (runtime.md); readiness ตรวจทีละ privilege
- Index: `data_documents_search` (GIN), `data_reservations_policy (workspace_id, policy, status, expires_at)`, `data_cache_expiry (workspace_id, expires_at)`
- FK ของ global leg ชี้ข้าม workspace (`service_workspace` = system workspace) ภายใต้ RLS — row ของ reservation ถูกเขียนใน transaction ของ system workspace

## Open questions

- ชื่อ runtime role ใน Neon `platform-data` ไม่อยู่ใน repo/ops record (security ใช้ `security_runtime`)
- ไม่มี retention: ทุกตารางโตตลอด ไม่มีขนาดข้อมูลจริงให้ดู
