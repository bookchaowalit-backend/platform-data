# platform-data

Workspace cache, atomic counters, indexed document search and durable quota
admission, installed independently as `platform_data`. Python >=3.12 and
PostgreSQL >=16. Correlation: `SHARED-INFRA-2026-10-15`.

## Scope

This repository owns shared data primitives and the existing lake contract.
The new PostgreSQL runtime is locally tested; production activation, lake
pipeline parity and legacy state migration remain separate work. Legacy
`solo-empire` lake ingest/storage interfaces remain documented and unchanged.

## Boundary

- Owner: `bookchaowalit-backend`
- Repository: `platform-data`
- Target remote: `https://github.com/bookchaowalit-backend/platform-data.git`
- Contract: `book-platform.contract.v1`
- Status: `pilot`
- Runtime package: `src/platform_data`; service-owned PostgreSQL tables
- Dependencies: installed `platform-backend-core==0.1.0`, security, observability

Only versioned APIs cross service boundaries. This service has no runtime
hub imports, legacy lake writer, provider SDK, credential discovery or paid
service calls. Signed JWT `ws` is the only workspace authority. Composite service admission
verifies a separate caller JWT and charges both global and tenant policies;
see the runtime guide for explicit `PLATFORM_SYSTEM_WORKSPACE_ID` setup.

## Local verification

The original dependency-free Python 3.11+ contract checks remain available:

```bash
bash scripts/check.sh
```

Runtime tests require Python >=3.12, an installed core 0.1.0 artifact, and an
explicit disposable local PostgreSQL admin DSN. They create unique databases
and unprivileged runtime roles; missing `PLATFORM_TEST_DSN` fails, never skips.

```bash
python -m pip install -e '.[test]'
PLATFORM_TEST_DSN="$LOCAL_DISPOSABLE_ADMIN_DSN" python -m pytest -q
```

The schema and sha256 pin are unchanged. `scripts/check_schema_pin.py
--canonical ../platform-backend-core` also compares the sibling canonical
copy. Registry alignment may differ until the parent integrates pilot metadata;
no registry state is read by the runtime.

See [API and runbook](docs/runtime.md) for installation, migration, exact
quota semantics and the local evidence record. [Contract surface](docs/CONTRACT-SURFACE.md)
retains the lake compatibility interfaces.

## Migration gate

Migrations run explicitly with a separate DDL role; startup never migrates.
Missing/drifted migrations yield readiness 503. All seven tenant tables use
FORCE RLS with USING/WITH CHECK and workspace-leading primary indexes.
Runtime roles must be NOSUPERUSER NOBYPASSRLS. Independent replicas coordinate
through PostgreSQL locks and persistent reservations. This evidence does not
constitute production load acceptance or a lake cutover. No deployment or push
was performed in this local implementation.
