# BOO-152 — Data-product producer contracts and lake lineage

## Next gate (verbatim)

> Verify each producer contract and lake lineage before connecting a UI to it.

Source: `solo-empire:repository-catalog/registries/system-repositories.yaml:528`
(system `data-products`, frontend `market-insights-web`, backend `platform-data`,
contract `systems/architecture/data-product-contracts-v2.yaml`).

## Contract section answered

`architecture-docs:systems/architecture/data-product-contracts-v2.yaml`, sections
`#products` (the seven frozen producers, ports 8101–8107) and `#consumers`
(the `market-insights-web` consumer, `must_match_ports`), together with
`#endpoints` and `#envelope` for the API and schema columns.

`architecture-docs` is private and this repository is public, so the contract is
**not** copied from it. The vendored copy
[`contracts/vendor/data-product-contracts-v2.yaml`](../../contracts/vendor/data-product-contracts-v2.yaml)
comes from the public `bookchaowalit/data-lake-pipelines` at `1178364b`
(sha256 `289ae5da…`, pinned in `contracts/vendor/data-product-contracts-v2.yaml.sha256`).
The canonical architecture-docs copy at `9471af55` has sha256 `7350615b…`. The
check compared the two. Their `products`, `endpoints`, `envelope` and `policy_defaults`
sections are byte-identical. The only differences are two consumer lines: one consumer id
and the portfolio consumer path. Only the canonical hash is recorded here.

## What "verified" means here

The fixture separates two kinds of lineage:

* **Static lineage (`status`)** means the following agree with each other and with the
  contract at the pinned commits:
  - the producer's `config.py` (lake source, schema, port, domain, datasets, freshness);
  - its `lake.py` registration through the shared `LakeProductContract`;
  - the lake runtime's Bronze path template and its capture/replay spec;
  - the API routes;
  - the `market-insights-web` catalog.

  Every claim is a `repo:path:line` plus the text that line must contain. You can
  re-check it with `python3 scripts/check_data_product_lineage.py --book-dev <book-dev root>`
  (it uses `git show <commit>:<path>` and is read-only).
* **Runtime lineage (`runtime_lineage_status`)** is `unverified` for every product. No
  Bronze object or `lake_lineage.json` was observed, and no API or UI was run. The
  `data/` folders at the pinned commits hold only `.gitkeep`.

## Pinned sources

| Source | Visibility | Commit | Role |
|---|---|---|---|
| bookchaowalit/architecture-docs | private | `9471af55723434fd34c746ad66fa1d4f5ebf6578` | canonical v2 contract (hash only) |
| bookchaowalit/data-lake-pipelines | public | `1178364b0c442bf8a5f6d13307a9a5e13f45cf32` | lake runtime `infra/scripts/data_lake`, public contract copy |
| bookchaowalit/market-data | public | `5c2dbd9aad7a6a6e8c8dc4472b08d1ae475f208d` | crypto, stocks, fx, defi producers |
| bookchaowalit/travel-flight-price-data | public | `083293c77341915031bc0f0eeb3f86da989e911d` | flights producer |
| bookchaowalit/marketing-seo-ranking-data | public | `85aeee703162273c3604e899c0c5f898e6603b60` | seo producer |
| bookchaowalit/tech-ai-tools-data | public | `8d557c58e3e21c3bf93049720da3c188c589d225` | ai_tools producer |
| bookchaowalit/market-insights-web | public | `cd92b36761e58b53878e0d015d04051b92c41168` | UI consumer |

The registry still lists the producer source as `solo-empire:infra/scripts/data_lake` and `data/`.
Neither exists at `solo-empire` `63efeeb0`. `infra/scripts/data_lake` was removed in `9f44f602`
(2026-10-11), and `data/` is untracked runtime state. The lake runtime now lives in
`data-lake-pipelines`. `contract.json` and `docs/CONTRACT-SURFACE.md` in this repo still cite the
old path. They are left unchanged because open PR #1 edits them.

## Lineage map (product → producer → lake → schema/freshness → UI)

The machine-readable version is [`fixtures/gates/data-product-lineage.json`](../../fixtures/gates/data-product-lineage.json).
It has 7 products and 168 evidence lines.

| Product | Producer (repo:package) | Lake domain / datasets | Bronze path (records) | Ingest into lake | Schema / freshness | UI (`market-insights-web`) | Status |
|---|---|---|---|---|---|---|---|
| crypto :8101 | market-data:`sources/crypto/src/book_crypto` (config.py:14, lake.py:77) | `market` / crypto_prices, crypto_trending, crypto_ohlcv, crypto_funding | `bronze/domain=market/dataset=crypto_prices/schema_version=1/…/source=book-crypto-data/` | `run_market_capture.py:66` (`0 */4 * * *`), replay `ingest_scraping_captures.py:62` | crypto.v1, bronze v1, stale after 24h (config.py:64) | catalog.ts:6 | **verified** (static) |
| stocks :8102 | market-data:`sources/stock/src/book_stock` (config.py:14, lake.py:68) | `market` / stock_prices, stock_history | `…/domain=market/dataset=stock_prices/…/source=book-stock-data/` | `run_market_capture.py:75` (`0 8 * * *`), replay `:84` | stock.v1, 24h (config.py:59) | catalog.ts:15 | **verified** (static) |
| fx :8103 | market-data:`sources/fx/src/book_fx` (config.py:14, lake.py:68) | `market` / exchange_rates, exchange_history | `…/domain=market/dataset=exchange_rates/…/source=book-fx-data/` | `run_market_capture.py:84` (`0 */6 * * *`), replay `:106` | fx.v1, 24h (config.py:58) | catalog.ts:24 | **verified** (static) |
| defi :8104 | market-data:`sources/defi/src/book_defi` (config.py:14, lake.py:77) | `market` / defi_yields, defi_yields_history | `…/domain=market/dataset=defi_yields/…/source=book-defi-data/` | `run_market_capture.py:93` (`0 7 * * *`), replay `:128` | defi.v1, 24h (config.py:63) | catalog.ts:33 | **verified** (static) |
| flights :8105 | travel-flight-price-data:`src/book_flight` (config.py:14, lake.py:74) | `travel` / flight_prices, flight_prices_history | `…/domain=travel/dataset=flight_prices/…/source=book-flight-data/` | replay only, `ingest_scraping_captures.py:150` (reads `private/…` path) | flight.v1, 24h (config.py:64) | catalog.ts:42 | **unverified** |
| seo :8106 | marketing-seo-ranking-data:`src/book_seo` (config.py:14, lake.py:69) | `seo` / seo_rankings, seo_rankings_history | `…/domain=seo/dataset=seo_rankings/…/source=book-seo-data/` | `run_seo_capture.py:172` (workspace `private/…` at :56), replay `:171` | seo.v1, 24h (config.py:66) | catalog.ts:51 | **unverified** |
| ai_tools :8107 | tech-ai-tools-data:`src/book_ai_tools` (config.py:14, lake.py:70) | `ai-tools` / ai_tools, ai_tools_history | `…/domain=ai-tools/dataset=ai_tools/…/source=book-ai-tools-data/` | replay only, `ingest_scraping_captures.py:193` (reads `private/…` path) | ai_tools.v1, 24h (config.py:62) | catalog.ts:60 | **unverified** |

Notes on the map:

* All seven products build the Bronze path from one template:
  `bronze/domain={domain}/dataset={dataset}/schema_version=…/ingest_date=…/source=…`.
  It is in `data-lake-pipelines:infra/scripts/data_lake/product_adapter.py:203`.
* Every API route is wired as `"/v1/records"` / `"/v1/history"` in `api.py`.
  `POST /v1/refresh` is off by default (`ALLOW_REFRESH` defaults to `False` in each `config.py`).
* The contract's `repository` names (`book-*-data`) are the lake `source` ids (`REPO_NAME`),
  not the current GitHub repository names. The GitHub repositories were renamed or
  folded into `market-data` (see `REPO-NAMING-PROPOSAL-2026-10-12.md`).
* Crypto history is a history-flagged replay into the `crypto_prices` dataset
  (`ingest_scraping_captures.py:66-76`), and `store.load_history` reads that same dataset.
  It has no separate history dataset. The code is consistent; this is recorded so a
  reader does not expect one.

### Cross-check with the producers' own guard

The fixture was not the only check. The existing
`data-lake-pipelines:infra/scripts/utils/data_product_contract_guard.py` was run at the pinned
commits in two disposable staged workspaces. One copied the producers to their real
checkout layout. The other copied them to the paths the contract declares. Results:

* **Real layout:** `producer missing` for flights, seo and ai_tools (the contract declares
  them under `private/…`). The other four producers and the `market-insights-web` catalog
  produced no failures.
* **Declared layout:** all seven producers and `market-insights-web` pass. The remaining
  failures are outside this gate: the portfolio consumer checkout is absent locally, and the
  Track B `book-job-data` checkout is not staged.

## Gaps

1. **Wrong producer path for flights, seo and ai_tools (blocks `verified`).**
   - The v2 contract `path` points at `github/bookchaowalit/private/…` (contract lines 85-105).
   - So do `run_data_product_stack.py:53-55` and `ingest_scraping_captures.py:150-205`.
   - So does `run_seo_capture.py:56`.
   - The repositories are public and checked out under `public/`, so lake replay and the
     local stack cannot resolve the sources.
2. **No scheduled capture for flights and ai_tools.** Bronze is fed only by the replay
   importer. Freshness therefore depends on someone running a manual replay.
3. **Runtime lineage not observed for any product.** No Bronze objects, manifests or
   `lake_lineage.json` were checked, so freshness (24h `stale` threshold) is unproven at runtime.
4. **Stale source path in the registry.** The registry and this repo's `contract.json` still
   name `solo-empire:infra/scripts/data_lake`, which was removed. The runtime is
   `data-lake-pipelines`.
5. **Contract copies have diverged.** The `consumers` block differs between architecture-docs
   (canonical) and data-lake-pipelines (public copy).
6. **`market-insights-web` lists two products that are not in v2:** `news` :8108 and
   `discovery` :8110. Their own contracts are `news-data-contract-v1.yaml` and
   `discovery-data-contract-v1.yaml`. This gate does not cover them.
7. **Not checked.** The second v2 consumer (`portfolio-*-web`) is not in this gate's scope and
   was not checked out locally.

## What PR #1 (`codex/shared-infrastructure-20261015`) would add

PR #1 adds:

* a PostgreSQL runtime package, `src/platform_data` (cache, counters, search, quota
  admission);
* a Dockerfile and a runtime workflow;
* a rewrite of `README.md`, `contract.json`, `docs/CONTRACT-SURFACE.md`, `docs/UPGRADE-PLAN.md`
  and `scripts/check.py`.

It does not touch lake lineage. This change edits none of those files. It only adds new files
and one line in `scripts/check.sh`, so the two should merge cleanly. Because PR #1 rewrites
`README.md`, the link to this document lives in [`docs/gates/README.md`](README.md) instead.

## Owner decision — PROPOSED, NOT ACCEPTED

The owner needs to decide on the following. Nothing below has been accepted or acted on.

1. Allow `market-insights-web` to connect to **crypto, stocks, fx and defi** only, at the
   pinned commits, on the basis of static lineage. Each of these UI connections should show
   `stale` when data is older than 24h until runtime lineage has been checked (gap 3).
2. Keep **flights, seo and ai_tools** disconnected until gap 1 is fixed. That fix is either a
   v3 contract freeze with `public/…` paths plus a matching update to `data-lake-pipelines`, or
   a decision to move those repositories back to `private/`. After the fix, re-run
   `check_data_product_lineage.py --book-dev` and the producer guard.
3. Before switching any of these products from `unverified` to `verified` in the fixture,
   record runtime evidence from a disposable lake: one Bronze commit manifest per dataset and
   one `lake_lineage.json`.
4. Pick one canonical consumers block for the v2 contract (gap 5). Update the registry
   `source_paths` to `data-lake-pipelines` (gap 4).

No status change, runtime move, cutover or UI connection is made or approved by this change.

## Reproduce

```bash
bash scripts/check.sh                                   # offline: pin, coverage, evidence rules, unit tests
python3 scripts/check_data_product_lineage.py --book-dev \
  /home/bookchaowalit/solo-empire/projects/product/engineering/book-dev   # reads 168 evidence lines via git show
```
