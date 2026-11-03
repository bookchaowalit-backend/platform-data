# 15 — CI/CD pipeline

Status: **done** — workflow เดียว `Check` (`.github/workflows/check.yml`), GitHub-hosted (repo public). CD ไม่ได้อยู่ใน workflow

```mermaid
flowchart TD
  T1["push any branch"] --> W["workflow Check, concurrency check-ref, cancel in progress"]
  T2["pull_request"] --> W
  T3["workflow_dispatch"] --> W
  W --> J1["contract matrix 3.11, 3.12: check_schema_pin.py, scripts/check.sh"]
  W --> J2["python: reusable ci-python.yml at 87dc5e1 v1.1.1, postgres true, ruff, mypy, pytest --cov gate 86, uv build wheel"]
  W --> J3["security: reusable security.yml at 87dc5e1 v1.1.1"]
  W --> J4["lineage: checkout 6 public repos at pinned SHAs, check_data_product_lineage.py"]
  W --> J5["image: docker build --pull, import check, non-root check, no push"]
  J1 & J2 & J3 & J4 & J5 --> G{"all green"}
  G -. "not enforced: no branch protection" .-> M["merge to main locally"]
  M --> D["Operator: git archive main, railway up --ci"]
  D --> RW["Railway data-api"]
```

`scripts/check.sh` รัน `check.py`, `check_schema_pin.py`, `check_data_product_lineage.py` และ `python3 -m unittest discover -s tests` (offline; runtime tests ต้องใช้ PostgreSQL จึงรันใน job `python`). ไม่มี `needs:` ระหว่าง job — ทั้ง 5 รันขนาน

ผลจริง (`gh run list -R bookchaowalit-backend/platform-data -L 200`): 82 runs; `main` 27 success / 2 failure (`0a0035f`, `b5d87d9` 2026-10-13
หลัง rename, แก้ใน `63198ff`); branch failures เฉพาะ `fix/sentry-hardening-port` 3 และ `sentry-hardened-scrubber` 1. Workflow `Shared runtime`
เก่าเลิกใช้หลัง `201b8b0` (รวมเข้า job `python` ใน `7ba94c3`).

Sources: `.github/workflows/check.yml`, `scripts/check.sh`, `pyproject.toml`, `README.md` ("Local verification"), `gh run list` output 2026-11-03;
ops record: book-platforms-status (2026-11-03) (deploy recipe `railway up --ci` from `git archive main`).

## Open questions

- ไม่ได้อ่านเนื้อใน `platform-ci-workflows` `ci-python.yml` / `security.yml` @`87dc5e1` ใน repo นี้ — รายการ step ข้างบนมาจาก comment ใน `check.yml`
- ควรมี deploy job (หรือ Railway GitHub source + Wait for CI) แทน CLI หรือไม่?
