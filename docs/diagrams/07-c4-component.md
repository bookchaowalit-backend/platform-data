# 07 — C4 Component

Status: **done**

```mermaid
C4Component
  title Components inside data-api
  Container_Boundary(api, "data-api process") {
    Component(main, "__main__.main", "argparse", "serve or migrate; env config; uvicorn bounds")
    Component(init, "package __init__", "Python", "Calls init_sentry at import")
    Component(sentryc, "_sentry", "sentry-sdk", "init_sentry, _scrub_event, CaptureErrors, capture")
    Component(core, "platform_backend_core.create_app", "FastAPI", "_Boundary middleware, /healthz /readyz /metrics, 422 handler")
    Component(auth, "TokenVerifier + require_scope", "PyJWT RS256", "Principal actor, workspace, scopes")
    Component(db, "Database", "psycopg_pool", "transaction(ws) sets app.workspace_id")
    Component(app, "app.create_app", "FastAPI routes", "cache, counters, documents, quotas, reservations, schema_ready")
    Component(sa, "service_admissions", "FastAPI routes", "pair(), composite reserve and finish")
    Component(mig, "migrations.MIGRATIONS", "SQL", "001_data_primitives, 002_service_admissions")
  }
  ContainerDb(pg, "Neon PostgreSQL")

  Rel(main, app, "create_app(Database, TokenVerifier, system_workspace)")
  Rel(main, mig, "MigrationRunner(namespace data).apply")
  Rel(app, core, "core_app(platform-data, max_body 1 MiB)")
  Rel(app, sentryc, "CaptureErrors innermost middleware")
  Rel(app, auth, "Depends(require_scope)")
  Rel(app, db, "database.transaction(p.workspace)")
  Rel(sa, app, "reuses reserve and finish as legs")
  Rel(sa, auth, "verifier.verify(X-Workspace-Authorization)")
  Rel(db, pg, "SQL")
```

Sources: `src/platform_data/__init__.py`, `__main__.py`, `_sentry.py`, `app.py`, `service_admissions.py`, `migrations.py`;
platform-backend-core @`21d5f44` `http.py`, `auth.py`, `db.py`, `migrations.py` (installed copy pinned by `uv.lock`).

## Open questions

- ไม่มี
