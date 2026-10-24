# platform-data — Product brief

**Slug:** `bookchaowalit-backend/platform-data`
**Updated:** 2026-10-24
**Status:** `pilot` contract plus a locally tested runtime; nothing is deployed

## Purpose

Own the Book Platform `data` boundary: the written lake contract (`contract.json`,
`contracts/vendor/data-product-contracts-v2.yaml`, `docs/CONTRACT-SURFACE.md`) and a
small PostgreSQL service for shared data primitives, so other services stop keeping
their own copies.

## What exists

- Offline contract checks (Python 3.11+, standard library): `scripts/check.py`
  validates `contract.json` against the vendored schema, `scripts/check_schema_pin.py`
  checks the schema pin, and `scripts/check_data_product_lineage.py` verifies the
  data-product lineage evidence; CI re-checks that evidence against six public
  producer/consumer repositories at pinned commits.
- The `platform_data` package (`src/platform_data/`): a FastAPI app with workspace
  cache, atomic counters, indexed document search and durable quota reservation,
  plus composite service admission (`service_admissions.py`). Tables use FORCE row
  level security keyed by the JWT `ws` claim; migrations are explicit
  (`python -m platform_data migrate`), never at startup. It builds on
  `platform-backend-core`, installed from a pinned Git commit. See `docs/runtime.md`.
- Tests: `tests/` (contract, drift, lineage) and `tests/runtime/` (API and
  admission tests against a real disposable PostgreSQL).
- CI (GitHub-hosted, public repository): contract job on Python 3.11 and 3.12,
  lineage job, the shared `ci-python` job (`uv sync --frozen`, Ruff, mypy, pytest
  with PostgreSQL under a coverage gate, wheel build) and the shared security
  workflow.

## Limits

- Not deployed: no Railway, container registry or other host runs this service, and
  no production database exists for it. The legacy `solo-empire` lake ingest and
  storage remain the live implementation.
- Lake pipeline parity, legacy state migration and production load acceptance are
  open work.
- The D8 `codex/shared-infrastructure-20261015` pull request (#1) was merged into
  `main` as `201b8b0`; it added the runtime above.

Sentry waiver: Dockerfile builds a local pilot image only; nothing is deployed, so there is no runtime to report from.
