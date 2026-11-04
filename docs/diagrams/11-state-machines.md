# 11 — State machines

Status: **done**

## `data_reservations.status`

```mermaid
stateDiagram-v2
  [*] --> pending: reserve, units charged
  pending --> settled: settle actual_units
  pending --> released: release before expires_at, refund
  pending --> expired: lazy expire on settle, release or replay after expires_at
  expired --> settled: late settle reconciles actual (allowed even after a release, test_expiry_stays_charged_and_late_settlement)
  expired --> expired: release, no refund
  settled --> settled: same actual repeats
  released --> released: duplicate release
  settled --> [*]
  released --> [*]
```

ข้อห้าม: settle หลัง released หรือ actual ต่าง = 409; release หลัง settled = 409 (`finish`).

## `data_service_admissions.status` (+ `operation`)

```mermaid
stateDiagram-v2
  [*] --> preparing: mapping inserted
  preparing --> pending: both legs pending, API shows reserved
  preparing --> preparing: partial failure, retry same key
  pending --> settled: operation settle, both legs finalized
  pending --> released: operation release, both legs released
  pending --> expired: release after earliest expiry, no refund, available 0
  pending --> expired: release where a leg returns expired
  expired --> settled: late settle, only if operation is None (a stored release intent returns 409)
  settled --> [*]
  released --> [*]
```

`preparing` + settle/release = 503; reserve replay หลังมี `operation` = 409.

## Quota policy debt

```mermaid
stateDiagram-v2
  [*] --> open: PUT quotas, debt 0
  open --> frozen: settle overrun, debt > 0
  frozen --> frozen: limit update keeps debt, new window keeps debt
  frozen --> open: operator data repair only, no API
```

Sources: `src/platform_data/migrations.py` (CHECK constraints), `src/platform_data/app.py` (`expire`, `finish`, `available`),
`src/platform_data/service_admissions.py` (`reserve`, `finish`, `response`), `docs/runtime.md`.

## Open questions

- ขั้นตอน operator "explicit reviewed data repair" สำหรับล้าง debt ไม่มี runbook/สคริปต์ใน repo
