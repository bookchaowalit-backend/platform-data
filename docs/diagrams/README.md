# Core 22 SDLC diagram pack — platform-data

ชุดภาพ 22 รายการตาม SDLC Diagram Catalog v2 (knowledge-base `knowledge/tech/core-cs/sdlc-diagram-catalog.md`)
วาดจากโค้ดและ config ของ repo นี้ ณ `origin/main` `0e724ac` (2026-11-03) และตรวจสถานะ live 2026-11-03
(Railway API + probe `https://data-api-production-bf8a.up.railway.app`) ทุก diagram มี `Sources:` และสิ่งที่ไม่รู้อยู่ใน
"Open questions" ของไฟล์นั้น ข้อเท็จจริงด้าน hosting ที่ไม่อยู่ใน repo อ้างเป็น `ops record: book-platforms-status (2026-11-03)`

| # | Item | Status | File | Sources read |
|---|---|---|---|---|
| 01 | Business process (As-Is / To-Be) | done | [01-business-process.md](01-business-process.md) | PRODUCT.md, README.md, docs/runtime.md, docs/UPGRADE-PLAN.md, docs/CONTRACT-SURFACE.md |
| 02 | Use cases | done | [02-use-cases.md](02-use-cases.md) | src/platform_data/app.py, service_admissions.py, core http.py/auth.py |
| 03 | User (caller) flows | done | [03-user-flows.md](03-user-flows.md) | app.py, service_admissions.py, docs/runtime.md |
| 04 | Traceability (RTM) | done | [04-traceability.md](04-traceability.md) | docs/runtime.md, CONTRACT-SURFACE.md, gates/, tests/**, check.yml |
| 05 | C4 Context | done | [05-c4-context.md](05-c4-context.md) | README.md, runtime.md, _sentry.py, ops record |
| 06 | C4 Container | done | [06-c4-container.md](06-c4-container.md) | Dockerfile, __main__.py, migrations.py, Railway describe-service |
| 07 | C4 Component | done | [07-c4-component.md](07-c4-component.md) | src/platform_data/*.py, core http.py/db.py/auth.py |
| 08 | ADRs (retro-documented) | done | [08-adr/](08-adr/) — [0001](08-adr/ADR-0001-postgres-force-rls-workspace-isolation.md), [0002](08-adr/ADR-0002-shared-core-pinned-git-commit.md), [0003](08-adr/ADR-0003-durable-quota-admission-debt-freeze.md), [0004](08-adr/ADR-0004-railway-serverless-cli-deploy.md), [0005](08-adr/ADR-0005-sentry-no-free-text.md) | code, pyproject.toml, uv.lock, Railway API, git log |
| 09 | ERD | done | [09-erd.md](09-erd.md) | src/platform_data/migrations.py, core migrations.py |
| 10 | Sequences | done | [10-sequences.md](10-sequences.md) | app.py, service_admissions.py, core http.py/db.py |
| 11 | State machines | done | [11-state-machines.md](11-state-machines.md) | migrations.py CHECKs, app.py `finish`/`expire`, service_admissions.py |
| 12 | API & integrations | done | [12-api-integration.md](12-api-integration.md) | app.py, service_admissions.py, runtime.md, core http.py, live probe |
| 13 | Threat model | done | [13-threat-model.md](13-threat-model.md) | app.py, migrations.py, _sentry.py, core auth/db/http, Dockerfile, live probe |
| 14 | Backup & DR | done (backup coverage unknown) | [14-backup-dr.md](14-backup-dr.md) | runtime.md rollback section, central ADR-0002, Railway API |
| 15 | CI/CD pipeline | done | [15-cicd-pipeline.md](15-cicd-pipeline.md) | .github/workflows/check.yml, scripts/check.sh, gh run list |
| 16 | Deployment | done | [16-deployment.md](16-deployment.md) | Railway describe-service, Dockerfile, __main__.py, ops record, live probe |
| 17 | Test coverage matrix | done | [17-test-coverage-matrix.md](17-test-coverage-matrix.md) | tests/**, check.yml, pyproject.toml |
| 18 | Git & release workflow | done | [18-git-release-workflow.md](18-git-release-workflow.md) | git log, gh pr list, branch protection API, Railway list-deployments |
| 19 | Service dependency map | done | [19-service-dependency-map.md](19-service-dependency-map.md) | pyproject.toml, uv.lock, check.yml, Railway variables (names only), ops record |
| 20 | Observability | done | [20-observability.md](20-observability.md) | _sentry.py, core http.py, ops record, live /metrics |
| 21 | Incident response | done | [21-incident-response.md](21-incident-response.md) | runtime.md rollback, ops record, central ADR-0002 |
| 22 | DORA | done (recovery = cannot compute; deploy↔commit mapping inferred) | [22-dora.md](22-dora.md) | Railway list-deployments, git log, gh run list |

สรุปสถาปัตยกรรมระดับ docpack: [`DOCPACK/02-architecture.md`](../../DOCPACK/02-architecture.md) (2026-11-04)

## Reused docs (ลิงก์ ไม่คัดลอก)

- API, bounds, admission semantics, rollback: [docs/runtime.md](../runtime.md) — ใช้ใน 03, 09–12, 14, 21
- Lake compatibility interfaces: [docs/CONTRACT-SURFACE.md](../CONTRACT-SURFACE.md) — ใช้ใน 01, 04, 12
- Gate evidence BOO-152: [docs/gates/BOO-152-data-product-lineage.md](../gates/BOO-152-data-product-lineage.md) — ใช้ใน 04, 15
- Backlog: [docs/UPGRADE-PLAN.md](../UPGRADE-PLAN.md) — ใช้ใน 01
- Central (private, read-only): [ADR-0002 production baseline](https://github.com/bookchaowalit/architecture-docs/blob/main/docs/architecture/decisions/ADR-0002-production-baseline-monitoring-backups.md), [ADR-0004 TDD + SDD](https://github.com/bookchaowalit/architecture-docs/blob/main/docs/architecture/decisions/ADR-0004-tdd-sdd-standard.md), [lake-intake flow pack](https://github.com/bookchaowalit/architecture-docs/blob/main/docs/architecture/flows/lake-intake/README.md) (lake ที่ยังอยู่ใน solo-empire) — central C4/ERD/attack-path ไม่มีส่วนของ platform-data

## Key findings (2026-11-03)

- **Docs ล้าหลัง:** `PRODUCT.md` (2026-10-24), `README.md` และ `docs/runtime.md` ยังเขียนว่า "not deployed" แต่ Railway project `platform-data` / service `data-api` live ตั้งแต่ 2026-10-29 (22 deployments, ล่าสุด SUCCESS 2026-11-03 04:22 UTC), `/healthz` 200, `/readyz` 200
- Railway service ตั้ง builder `RAILPACK` ทั้งที่ repo มี `Dockerfile` สองชั้น — ไม่รู้ว่า image ที่รันจริงสร้างจากอะไร (ดู 16)
- ไม่พบ `healthcheckPath` ใน config ของ Railway service (payment ตั้ง `/healthz`, data ไม่ปรากฏ)
- `/metrics` เปิดสาธารณะโดยไม่ต้อง auth (route template + count เท่านั้น) — ดู 13
- ไม่มี caller ตัวจริงของ `/v1/service/admissions` (AI gateway ยังเป็น scaffold ตาม ops record); runtime.md บอก audience `platform-api` แต่ ops record บอก audience บริการคือ `data-api` — ต้องยืนยัน
- ไม่มี retention job: cache/counter ที่หมดอายุ, bucket และ reservation เก่าสะสมตลอด (runtime.md ระบุเป็น future requirement)
- 13 PR Sentry (#5–#18) merge + deploy ภายใน ~11 ชม. — สูงใน deployment rework rate (ดู 22)
- `main` ไม่มี branch protection / ruleset; deploy เป็น `railway up` จาก CLI จึงไม่มี CI gate บังคับ
