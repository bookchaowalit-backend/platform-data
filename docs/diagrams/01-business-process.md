# 01 — Business process (As-Is / To-Be)

Status: **done**

platform-data เป็น backend platform service ไม่มี UI "ธุรกิจ" ของมันคือให้บริการ data primitive ร่วม (cache, counter,
document search, quota admission) ให้ service อื่นใช้แทนการเก็บสำเนาของตัวเอง และถือ lake contract เดิมไว้
([PRODUCT.md](../../PRODUCT.md))

## As-Is (จากโค้ดวันนี้)

```mermaid
flowchart LR
  subgraph Caller["Calling service or owner tool"]
    A1["Get token from platform-identity"]
    A2["Call data-api with Bearer JWT"]
  end
  subgraph DataAPI["data-api (platform_data)"]
    B1["Verify RS256 JWT, exact scope"]
    B2["Bind ws claim to app.workspace_id"]
    B3{"Route"}
    B4["Cache put/get/delete"]
    B5["Counter increment"]
    B6["Document upsert/delete/search"]
    B7["Quota policy put"]
    B8["Reserve / settle / release"]
    B9["Composite service admission"]
  end
  subgraph PG["Neon PostgreSQL (FORCE RLS)"]
    C1[("data_* tables")]
  end
  subgraph Ops["Operator"]
    O1["python -m platform_data migrate (DDL role)"]
    O2["railway up from git archive"]
  end
  A1 --> A2 --> B1 --> B2 --> B3
  B3 --> B4 & B5 & B6 & B7 & B8 & B9
  B4 & B5 & B6 & B7 & B8 & B9 --> C1
  O1 --> C1
  O2 --> DataAPI
  L["Lake ingest (landing/bronze/manifest)"] -. "still in solo-empire, not served here" .- DataAPI
```

Sources: `src/platform_data/app.py`, `src/platform_data/service_admissions.py`, `src/platform_data/__main__.py`,
`docs/CONTRACT-SURFACE.md`, `README.md`; ops record: book-platforms-status (2026-11-03) for identity issuer and deploy recipe.

ข้อสังเกต As-Is:
- lake interfaces (`data.cli.ingest`, `data.object-store.*`) มีสถานะ `current-in-solo-empire` — repo นี้ไม่ได้ serve
- migrate ทำแยกด้วย DDL role, startup ไม่ migrate (`__main__.py`)

## To-Be (จาก PRODUCT.md / UPGRADE-PLAN.md / runtime.md เท่านั้น)

```mermaid
flowchart LR
  P1["Lake pipeline parity: bronze parity, schema versioning, replay evidence"] --> P2["Compatibility adapter + shadow parity"]
  P2 --> P3["Cutover lake interfaces to platform-data"]
  P3 --> P4["Rollback plan kept"]
  Q1["AI gateway calls service admissions before paid provider"] --> Q2["Reconcile ambiguous provider outcomes"]
  R1["Operator-owned bounded retention job"] --> R2["Old buckets, reservations, expired cache pruned"]
```

Sources: `contract.json` (`migration`, `migration_gates`), `PRODUCT.md` (Limits), `docs/UPGRADE-PLAN.md` (Backlog P0–P2),
`docs/runtime.md` ("Admission and accounting contract", "Composite service admission extension").

## Open questions

- ใครเป็น consumer ตัวจริงของ cache/counter/document ใน production ตอนนี้? (ops record ระบุแค่ MCP hub cell `platform-data`)
- To-Be ของ lake cutover มีกำหนดเวลาหรือ owner decision หรือยัง? UPGRADE-PLAN ไม่ระบุวัน
- `docs/UPGRADE-PLAN.md` P2 "Add a health endpoint" — มีแล้วจาก core (`/healthz`, `/readyz`) ควรปิดรายการนี้หรือไม่
