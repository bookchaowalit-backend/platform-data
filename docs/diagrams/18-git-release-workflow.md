# 18 — Git & release workflow

Status: **done**

```mermaid
gitGraph
  commit id: "da67bc4 scaffold"
  commit id: "73ba4f7 license"
  commit id: "8b62af6 BOO-152 PR2"
  commit id: "fba0a77 BOO-152 PR3"
  branch codex-shared-infra
  commit id: "8ecf228 runtime"
  commit id: "b6b6543 composite"
  checkout main
  merge codex-shared-infra id: "201b8b0 merge"
  commit id: "7ba94c3 ci uv"
  branch build-hygiene
  commit id: "1cb0537"
  checkout main
  merge build-hygiene id: "f2ce348 deploy 1"
  branch sentry
  commit id: "988d86c"
  checkout main
  merge sentry id: "3d336a4 deploys 5-8"
  branch fix-sentry-prs
  commit id: "PR5 to PR18"
  checkout main
  merge fix-sentry-prs id: "0e724ac deploy 22"
```

```mermaid
flowchart LR
  B["feature branch"] --> PR["PR on GitHub, CI Check runs"]
  PR --> ML["merge locally into main and push"]
  ML --> CI["Check on main"]
  ML --> DEP["Operator: git archive main, railway up --ci"]
  DEP --> RW["Railway deployment, no commit SHA in meta"]
  CI -. "not a gate for DEP" .-> DEP
```

ข้อเท็จจริงจาก git/gh:
- `main` ไม่มี branch protection (`gh api .../branches/main/protection` → 404) และไม่มี ruleset
- PR 18 รายการ: merged 16, open 1 (#4 `sentry-hardened-scrubber`, ถูก supersede), closed 1 (#1 — แต่ runtime เข้าทาง merge `201b8b0` ของ branch rebased)
- บาง merge ไม่ผ่าน PR (`3d336a4`, `0bf19a5`, `174ebf0`, `f2ce348` เป็น local merge ของ branch)
- deploy เกิดภายใน 0–3 นาทีหลัง merge (22 deploys; ดูการจับคู่ใน 22)

Sources: `git log origin/main`, `gh pr list --state all`, `gh api repos/bookchaowalit-backend/platform-data/branches/main/protection`,
`gh api .../rulesets`, Railway list-deployments; ops record: book-platforms-status (2026-11-03) (deploy recipe).

## Open questions

- ควรเปิด branch protection / required checks สำหรับ `main` หรือไม่ (repo public, owner คนเดียว)?
- PR #4 ค้างเปิด — ปิดได้หรือไม่
