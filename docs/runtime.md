# Workspace data runtime

Status: implemented and locally verified, not deployed. Correlation:
`SHARED-INFRA-2026-10-15`. Python >=3.12, PostgreSQL >=16. This package
reuses `platform_backend_core` JWT verification, database transaction binding,
readiness, bounded HTTP lifecycle and migration runner. No copied auth/DB code.

## Installation and local launch

Install a reviewed core 0.1.0 wheel, then this package; deployed dependencies
must be immutable release artifacts, never paths inside the registry hub.
For local development, installing the sibling core editable is supported.

```bash
python -m pip install /reviewed-wheels/platform_backend_core-0.1.0-py3-none-any.whl
python -m pip install -e '.[test]'
# Operator supplies explicit environment; never discover credential files.
DATABASE_URL="$LOCAL_DDL_DSN" python -m platform_data migrate
DATABASE_URL="$LOCAL_RUNTIME_DSN" JWT_ISSUER="$ISSUER" JWT_AUDIENCE="$AUDIENCE" \
  JWT_PUBLIC_KEY="$PUBLIC_PEM" PORT=8080 python -m platform_data serve
```

Exactly one of `JWT_PUBLIC_KEY` (PEM value) or `JWT_JWKS_URL` (configured HTTPS
endpoint) is required. The latter inherits core's bounded refresh/fail-closed
behavior. The public configuration variable is not a filename to discover.
`DATABASE_URL`, `JWT_ISSUER` and `JWT_AUDIENCE` are required; `PORT` defaults
to 8080. Migration uses `DATABASE_URL` for the separately injected DDL role;
serve uses the runtime role. Never serve as a database superuser/table bypass
role. Migration errors and configuration failures do not print DSNs or tokens.

Public Python entry points:

```python
from platform_data.app import create_app
from platform_data.migrations import MIGRATIONS
from platform_backend_core import Database, TokenVerifier, MigrationRunner
MigrationRunner(explicit_ddl_dsn, namespace='data').apply(MIGRATIONS)
app = create_app(Database(runtime_dsn), configured_verifier)
```

`MIGRATIONS` is an ordered immutable release sequence. Do not edit an applied
migration: append another version. Readiness checks compare every migration
version/checksum in namespace `data` and check all six tables, using
`app.state.readiness_checks`. Database unavailability, missing history, drift
or missing tables yield generic `/readyz` 503. `/healthz` and `/metrics` come
from core. Mutation routes also fail closed with generic errors on missing DB
state. Startup does not create tables.

After explicit migrations grant runtime schema USAGE, SELECT/INSERT/UPDATE/
DELETE on `data_cache`, `data_counters`, `data_documents`,
`data_quota_policies`, `data_quota_buckets`, `data_reservations`, and SELECT
on `platform_schema_migrations`. Keep migration DDL/ownership separate.
Never grant a runtime role BYPASSRLS or superuser. All tenant tables have
workspace-first primary keys, FORCE RLS, USING and WITH CHECK.

Docker builds require an explicit `wheels/` build-context directory containing
core 0.1.0 and every transitive runtime/build wheel (including setuptools).
The Dockerfile installs offline and runs as uid/gid 10001; it performs no
migration. Build the bundle outside the service checkout, copy it as an ignored
release input, and include its immutable checksums in the release manifest.
No image publication or deployment is implied. The local server bounds HTTP
concurrency to 64, keepalive to five seconds, graceful shutdown to 30 seconds,
and disables URL access logging. Core pool defaults to eight connections per
process; budget replicas times pool maxima, including operator workers.

## Public API

All routes require `Authorization: Bearer <workspace JWT>` with the exact
scope below. Unauthenticated requests are 401; insufficient scope is 403.
Extra body fields are forbidden, including workspace IDs and caller quota
limits. Keys/policy names/idempotency keys are 1..200 characters. Validation
returns generic 422 without echoing payloads. JSON rejects non-finite numbers,
NUL strings, unencodable text and oversized values. Bodies are capped at 1 MiB.

| Method / path | Scope | Request / response |
|---|---|---|
| PUT `/v1/cache/{key}` | `cache:write` | `{value: JSON, ttl_seconds: int}` → `{key,value,expires_at}` |
| GET `/v1/cache/{key}` | `cache:read` | Live `{key,value,expires_at}`, or 404 |
| DELETE `/v1/cache/{key}` | `cache:write` | `{deleted:true}`; idempotent |
| POST `/v1/counters/{key}/increment` | `counters:write` | `{amount:int=1,window_seconds:int}` → `{key,value,window_seconds,expires_at}` |
| PUT `/v1/documents/{key}` | `documents:write` | `{text:str,metadata:object={}}` → `{key}` |
| DELETE `/v1/documents/{key}` | `documents:write` | `{deleted:true}`; idempotent |
| GET `/v1/documents?q=...&limit=20&offset=0` | `documents:read` | `{items:[{key,text,metadata}],limit,offset}` |
| PUT `/v1/quotas/{key}` | `quotas:write` | `{limit:int,window_seconds:int}` → `{key,limit,window_seconds,debt}` |
| POST `/v1/reservations` | `quotas:reserve` | `{policy:str,units:int,idempotency_key:str,ttl_seconds:int=120}` |
| POST `/v1/reservations/{id}/settle` | `quotas:settle` | `{actual_units:int}` |
| POST `/v1/reservations/{id}/release` | `quotas:settle` | `{}` |

Cache JSON is at most 64 KiB serialized UTF-8, TTL is 1..86400 seconds.
GET never extends expiration. PUT explicitly replaces content and TTL; DELETE
and last PUT wins semantics are appropriate for a cache. Counter increments
are positive integers <=10^12, atomically shared in PostgreSQL; first update
starts a fixed 1..86400-second window, later increments preserve expiration.
A changed window during a live window returns 409; expiration permits reset.
Counts use bigint; overflow rolls back with a generic server failure.
Counters are count primitives, not the quota admission API.

Documents accept at most 200000 characters and 16 KiB metadata. Search query
is 1..512 characters; limit 1..100, offset 0..10000. Stable key ordering makes
pagination deterministic for an unchanged dataset. PostgreSQL generated
`tsvector` and GIN index use `simple` configuration, with parameterized
`plainto_tsquery`; punctuation is plain input, never executable query syntax.
This is full-text lexeme matching, not Thai linguistic segmentation or
substring search. Trigram extensions are not required or enabled.

## Admission and accounting contract

Reserve, settle and release return exactly this envelope (HTTP 200):

```json
{"id":"UUID","status":"pending","units":4,"expires_at":"RFC3339 timestamp","available":6}
```

`units` remains the original estimate; actual usage is stored internally.
Statuses are `pending`, `expired`, `settled`, `released`. All timestamps and
windows use database time. Units and limits are integers <=10^12, never floats;
limit may be zero, reservation units must be positive, actual units may be zero.
Policy window is 1..31536000 seconds, reservation TTL 1..86400 seconds.
The trusted policy writer chooses limits; a reserve caller cannot supply them.
Absent policy returns 503; exhausted capacity or outstanding debt returns 429;
unknown or cross-workspace reservation returns 404; changed idempotency
payload/finalization returns 409.

Policy creation/update serializes through its PostgreSQL row. Updating a limit
preserves all usage and debt; the window is immutable after creation (409 on a
change). Buckets use fixed UTC epoch windows. Each workspace/policy row is
locked for reserve/settle/release; an advisory transaction lock also serializes
idempotency keys across policy names. These are database locks across all
connections and processes. Reserved units charge the bucket immediately.
A duplicated key with identical policy/units/TTL returns the same reservation;
changed policy, units or TTL is 409. Pending replay preserves its original
`available` snapshot; settlement/release/expired replay returns current capacity.
Use each new admission response, never a replay snapshot, to assess new capacity.

Successful settle changes original bucket usage by `actual - reserved`, exactly
once. Same actual repeats safely; changed actual or release-after-settle is 409.
Release before expiry refunds once; duplicate release is safe. Settling a
released reservation returns 409. TTL expiry never silently refunds potentially
paid provider usage: expired pending reservations remain fully charged.
Release after expiry returns `expired` and preserves the charge. Late settle
is allowed to reconcile the actual usage once; expiry is materialized lazily
on a duplicate/finalization request, without requiring a background process.

Actual usage above the estimate is always recorded even when it exceeds the
policy capacity. Any observed bucket overrun creates persistent policy `debt`
(the maximum recorded excess), which blocks every later admission, including
new windows. Limit updates never erase this marker. There is deliberately no
untrusted debt-reset API. A trusted operator must reconcile accounting, retain
an audit of the decision and apply an explicit reviewed data repair before
clearing debt. Actual charges remain in reservation/bucket records. This
conservative freeze favors a hard ceiling over automatic forgiveness.

Pending reservations survive API/process restarts. Windows reset admission
capacity according to the policy, while historical reservations remain
settleable against their original buckets. Old buckets/reservations and expired
cache/counter records are retained: an operator-owned bounded retention job
is a future release requirement. Do not delete admission history or reuse
idempotency keys without an explicit retention/reconciliation policy.

## Local acceptance record — 2026-10-15

The initial 10 runtime tests failed explicitly because the service package did
not exist. The next round produced three direct RED failures for missing
migration-history readiness, unsupported PostgreSQL NUL text, and missing CLI.
They then passed after focused implementation. Tests use the installed service,
real JWT verification and unique PostgreSQL databases with NOSUPERUSER,
NOBYPASSRLS runtime roles. No provider, paid request, real message, deployment,
production cutover or legacy lake state movement was performed.

Local evidence: Python 3.14 and rootless PostgreSQL 18; the supported
Python 3.12/PostgreSQL 16 target and Docker image were not exercised locally.
Final checks: `bash scripts/check.sh` passed all 36 original tests and the
contract/schema pin checks; `python -m pytest -q` with the explicit local DSN
passed 55 tests (19 runtime, 36 original), no skips. Four spawned processes
admitted exactly 13/40 requests against a 13-unit policy; threaded tests
admitted exactly 10/30 and observed 40 distinct atomic counter increments.
Concurrent duplicate finalization, expiry, debt across window rollover,
isolation, migration drift, CLI migration replay and API recreation passed.
One upstream Starlette/httpx deprecation warning remains. Editable install,
wheel build and import from an isolated target passed. An initial wheel command
using `--no-build-isolation` failed because the local environment had no
setuptools; the normal isolated build passed. Docker's explicit bundle installs
setuptools before its offline no-isolation build. No Docker build is claimed.

## Staged rollback and reconciliation

Before enabling consumers, retain the previous image, immutable wheel bundle,
release manifest and a tested database backup. Stop new admissions and disable
the explicitly configured consumer adapter before rolling the service image
back. Do not drop tables, run destructive down migrations, erase reservations
or switch consumers to process-local counters while requests remain in flight.
A rollback version must understand the applied schema/checksums; otherwise keep
the service stopped and recover into a fresh database for operator review.
Reconcile pending/expired usage against provider records before releasing any
charge. Production activation, debt repair and destructive restore require a
separate reviewed operator action; no such action was performed here.
