# 03 — User (caller) flows

Status: **done** — service ไม่มีหน้าเว็บ จึงเป็น API call flow ต่อ caller ส่วน semantics ละเอียดดู [runtime.md](../runtime.md) (reused)

## Flow A — Workspace caller: cache / counter / document

```mermaid
flowchart TD
  S["Caller has workspace JWT"] --> C{"Which primitive"}
  C -- cache --> P1["PUT /v1/cache/key value + ttl_seconds 1..86400"]
  P1 --> G1["GET /v1/cache/key"]
  G1 --> G2{"expires_at > now"}
  G2 -- yes --> R1["200 key, value, expires_at"]
  G2 -- no --> R2["404"]
  C -- counter --> I1["POST /v1/counters/key/increment amount, window_seconds"]
  I1 --> I2{"live window and window differs"}
  I2 -- yes --> R3["409 Counter window differs"]
  I2 -- no --> R4["200 key, value, window_seconds, expires_at"]
  C -- document --> D1["PUT /v1/documents/key text, metadata"]
  D1 --> D2["GET /v1/documents?q=...&limit&offset"]
  D2 --> R5["200 items ordered by key"]
```

## Flow B — Workspace caller: quota policy → reserve → settle / release

```mermaid
flowchart TD
  A["PUT /v1/quotas/key limit, window_seconds (quotas:write)"] --> A2{"existing window differs"}
  A2 -- yes --> X1["409 window immutable"]
  A2 -- no --> B["POST /v1/reservations policy, units, idempotency_key, ttl (quotas:reserve)"]
  B --> B1{"policy exists"}
  B1 -- no --> X2["503 Quota policy unavailable"]
  B1 -- yes --> B2{"same key, different payload"}
  B2 -- yes --> X3["409"]
  B2 -- no --> B3{"units <= capacity and debt = 0"}
  B3 -- no --> X4["429 Quota exhausted"]
  B3 -- yes --> B4["200 status pending, available"]
  B4 --> W["Caller does the work"]
  W --> S1["POST /v1/reservations/id/settle actual_units (quotas:settle)"]
  W --> S2["POST /v1/reservations/id/release (quotas:settle)"]
  S1 --> S3["200 settled; overrun becomes policy debt"]
  S2 --> S4["200 released, or expired with charge kept"]
```

## Flow C — Trusted service: composite admission for an AI call

```mermaid
flowchart TD
  T["Service JWT quotas:service, ws = system workspace + caller JWT ai:generate"] --> T1["POST /v1/service/admissions policy, global_policy, units, idempotency_key"]
  T1 --> T2["Mapping row committed in caller workspace"]
  T2 --> T3["Global leg reserve in system workspace"]
  T3 --> T4["Tenant leg reserve in caller workspace"]
  T4 --> T5{"both pending and unexpired"}
  T5 -- no --> F["Error: never permission to call provider"]
  T5 -- yes --> OK["200 status reserved"]
  OK --> PV["Service calls paid provider"]
  PV --> FS["POST /v1/service/admissions/id/settle actual_units"]
  PV --> FR["POST /v1/service/admissions/id/release"]
```

Sources: `src/platform_data/app.py`, `src/platform_data/service_admissions.py`, `docs/runtime.md` ("Public API",
"Admission and accounting contract", "Composite service admission extension").

## Open questions

- ไม่มี caller ตัวจริงของ Flow C (ops record: AI gateway caller ยังไม่มี) — flow นี้ทดสอบแค่ใน `tests/runtime/test_service_admissions.py`
- MCP hub ใช้ flow ไหนบ้างจริง? hub ไม่มี `quotas:reserve/settle` จึงทำ Flow B ได้ไม่ครบ
