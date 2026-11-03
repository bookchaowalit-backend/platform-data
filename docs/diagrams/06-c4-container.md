# 06 — C4 Container

Status: **done**

```mermaid
C4Container
  title Containers: platform-data
  Person(owner, "Operator")
  System_Ext(callers, "Callers", "MCP hub, platform services")
  System_Ext(identity, "platform-identity JWKS")
  System_Ext(sentry, "Sentry")
  Container_Boundary(rw, "Railway project platform-data, asia-southeast1, sleep on") {
    Container(api, "data-api", "Python 3.12, FastAPI, uvicorn", "python -m platform_data serve, port 8080, concurrency 64")
  }
  Container(mig, "migrate one-off", "Same package", "python -m platform_data migrate with DDL role")
  ContainerDb(pg, "Neon PostgreSQL", "PostgreSQL >=16", "7 data_* tables + platform_schema_migrations, FORCE RLS")

  Rel(callers, api, "HTTPS JSON, Bearer JWT")
  Rel(api, identity, "JWKS fetch")
  Rel(api, pg, "psycopg pool max 8, runtime role")
  Rel(mig, pg, "DDL, namespace data")
  Rel(owner, mig, "runs explicitly")
  Rel(api, sentry, "sentry-sdk, before_send scrub")
```

Sources: `Dockerfile` (CMD, `PORT=8080`, UID 65532), `src/platform_data/__main__.py` (`serve` / `migrate`, uvicorn limits),
`src/platform_data/migrations.py`, platform-backend-core @`21d5f44` `db.py` (pool `max_size=8`), `pyproject.toml`;
Railway describe-service (service `data-api`, region `asia-southeast1-eqsg3a`, `sleepApplication: true`, 1 replica).

## Open questions

- migrate one-off รันที่ไหนจริง (local กับ owner DSN หรือ Railway command override)? repo ไม่มี script/สคริปต์ release
- Neon region/compute size ไม่อยู่ใน repo หรือ ops record
