# 19 — Service dependency map

Status: **done**

```mermaid
flowchart LR
  subgraph Runtime["Runtime dependencies"]
    API["data-api"]
    NEON[("Neon PostgreSQL platform-data")]
    IDP["platform-identity JWKS"]
    SEN["Sentry ingest"]
    RW["Railway platform, sleep and wake"]
  end
  subgraph Consumers["Known consumers"]
    HUB["Remote MCP hub, cell platform-data"]
    UPT["platform-uptime-worker"]
    AIG["AI gateway, planned"]
  end
  subgraph Build["Build-time"]
    CORE["platform-backend-core at 21d5f44"]
    PYPI["PyPI: fastapi via core, uvicorn, sentry-sdk, psycopg via core"]
    CIW["platform-ci-workflows at 87dc5e1"]
    LIN["6 public lineage repos at pinned SHAs"]
  end
  HUB --> API
  UPT --> API
  AIG -. "not built" .-> API
  API -- "hard: readiness fails without it" --> NEON
  API -- "hard for auth routes" --> IDP
  API -- "soft: off when SENTRY_DSN empty" --> SEN
  RW --> API
  CORE --> API
  PYPI --> API
  CIW --> CIJ["CI only"]
  LIN --> CIJ
```

| Dependency | Kind | Failure effect (from code) |
|---|---|---|
| Neon PostgreSQL | hard | `/readyz` 503; routes fail closed with generic errors |
| platform-identity JWKS | hard for `/v1/*` | token verification fails → 401 (core fail-closed) |
| Sentry | soft | no-op without DSN; send errors do not affect requests |
| platform-backend-core | build | pinned commit via `uv.lock` |
| `contract.json` `depends_on: security, observability` | declared | no runtime call to security or observability services in code |

Sources: `pyproject.toml`, `uv.lock` (core rev), `src/platform_data/*.py`, `.github/workflows/check.yml`, `contract.json`, Railway variable
names; ops record: book-platforms-status (2026-11-03) (MCP hub, uptime worker, AI gateway status).

## Open questions

- มี service อื่นใน platform ที่เรียก data-api จริง (นอก MCP hub) หรือไม่ — ไม่พบใน repo นี้
- `depends_on: security` หมายถึง audit event ในอนาคตหรือไม่? ปัจจุบันไม่มีการส่ง audit
