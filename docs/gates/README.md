# Gate evidence

System-gate evidence for this platform boundary. Each document names the gate,
the contract section it answers, the pinned sources, the gaps, and the owner
decision. The decision is marked PROPOSED until the owner accepts it, then
ACCEPTED with its date.

| Issue | Gate | Evidence | Fixture | Check |
|---|---|---|---|---|
| BOO-152 | Verify each producer contract and lake lineage before connecting a UI to it. Decision ACCEPTED 2026-10-16: UI connects to crypto, stocks, fx and defi only. | [BOO-152-data-product-lineage.md](BOO-152-data-product-lineage.md) | [`fixtures/gates/data-product-lineage.json`](../../fixtures/gates/data-product-lineage.json) | `python3 scripts/check_data_product_lineage.py` (run by `scripts/check.sh`) |
