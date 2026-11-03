# 10 — Sequences

Status: **done** — 3 path สำคัญ

## 1. Authenticated request (any `/v1/*` route), e.g. cache GET

```mermaid
sequenceDiagram
  participant C as Caller
  participant B as core _Boundary
  participant E as CaptureErrors
  participant R as Route cache_get
  participant V as TokenVerifier
  participant J as identity JWKS
  participant P as Neon PostgreSQL
  C->>B: GET /v1/cache/key, Authorization Bearer
  B->>B: body cap 1 MiB, timeout 30 s
  B->>E: forward
  E->>R: forward
  R->>V: require_scope cache:read
  V->>J: fetch keys when needed
  V-->>R: Principal actor, workspace, scopes
  R->>P: BEGIN, set_config app.workspace_id
  R->>P: SELECT key,value,expires_at WHERE key AND expires_at > now
  P-->>R: row or none
  R-->>C: 200 or 404
  Note over B: logs route template, status, correlation id only
```

## 2. Reserve → settle (single workspace)

```mermaid
sequenceDiagram
  participant C as Caller
  participant A as data-api reserve and finish
  participant P as PostgreSQL
  C->>A: POST /v1/reservations policy, units, idempotency_key, ttl
  A->>P: pg_advisory_xact_lock(ws + key)
  A->>P: SELECT reservation by idempotency_key
  A->>P: SELECT policy FOR UPDATE
  alt no policy
    A-->>C: 503
  end
  A->>P: INSERT bucket ON CONFLICT DO NOTHING, SELECT used FOR UPDATE
  alt units > capacity or debt
    A-->>C: 429
  end
  A->>P: UPDATE bucket used += units, INSERT reservation pending
  A-->>C: 200 id, pending, units, expires_at, available
  C->>A: POST /v1/reservations/id/settle actual_units
  A->>P: SELECT reservation, policy FOR UPDATE, lazy expire
  A->>P: UPDATE bucket used += actual - units
  A->>P: UPDATE policy debt = greatest(debt, used - limit)
  A->>P: UPDATE reservation settled
  A-->>C: 200 settled
```

## 3. Composite service admission

```mermaid
sequenceDiagram
  participant S as Trusted service
  participant A as service_admissions
  participant L as reserve leg
  participant P as PostgreSQL
  S->>A: POST /v1/service/admissions, Authorization service JWT, X-Workspace-Authorization caller JWT
  A->>A: quotas:service, ws == system workspace, caller has ai:generate
  A->>P: tx caller ws: INSERT mapping ON CONFLICT DO NOTHING, check actor and payload
  A->>L: global leg key service:global:mapping_id as service principal
  L->>P: tx system ws: reserve
  A->>P: tx caller ws: set global_reservation_id
  A->>L: tenant leg key service:tenant:mapping_id as caller principal
  L->>P: tx caller ws: reserve
  A->>P: tx caller ws: FOR UPDATE, status pending, min expires_at, min available
  A-->>S: 200 status reserved
```

Sources: `src/platform_data/app.py`, `src/platform_data/service_admissions.py`, `src/platform_data/_sentry.py`;
platform-backend-core @`21d5f44` `http.py` (`_Boundary`, `require_scope`), `auth.py`, `db.py`.

## Open questions

- ไม่มี
