"""Tests for scripts/check_data_product_lineage.py (BOO-152 lineage gate)."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lineage = _load("platform_data_product_lineage", "scripts/check_data_product_lineage.py")

EXTRA_PRODUCT = """  - id: weather
    port: 8111
    schema_version: weather.v1
    repository: book-weather-data
    path: projects/product/engineering/book-dev/github/bookchaowalit/public/book-products/weather
    package: book_weather
    role: domain_source
consumers:
"""


class _RepoCopy(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name) / "repo"
        for relative in (lineage.FIXTURE_RELATIVE, lineage.CONTRACT_RELATIVE, lineage.PIN_RELATIVE):
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, self.root / relative)
        self.fixture = json.loads((self.root / lineage.FIXTURE_RELATIVE).read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self._temp.cleanup()

    def write_fixture(self) -> None:
        (self.root / lineage.FIXTURE_RELATIVE).write_text(json.dumps(self.fixture), encoding="utf-8")

    def write_contract(self, text: str, repin: bool = True) -> None:
        path = self.root / lineage.CONTRACT_RELATIVE
        path.write_text(text, encoding="utf-8")
        if repin:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            (self.root / lineage.PIN_RELATIVE).write_text(f"{digest}  {path.name}\n", encoding="utf-8")
            self.fixture["contract"]["vendored_from"]["sha256"] = digest
            self.write_fixture()

    def product(self, pid: str) -> dict:
        return next(p for p in self.fixture["products"] if p["id"] == pid)


class ContractParsingTests(unittest.TestCase):
    def test_parses_seven_frozen_products_and_consumer_ports(self) -> None:
        contract = lineage.parse_contract((ROOT / lineage.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
        self.assertEqual(contract["freeze_id"], "data-product-contracts-v2")
        self.assertEqual(
            [(p["id"], p["port"], p["schema_version"]) for p in contract["products"]],
            [
                ("crypto", 8101, "crypto.v1"),
                ("stocks", 8102, "stock.v1"),
                ("fx", 8103, "fx.v1"),
                ("defi", 8104, "defi.v1"),
                ("flights", 8105, "flight.v1"),
                ("seo", 8106, "seo.v1"),
                ("ai_tools", 8107, "ai_tools.v1"),
            ],
        )
        ui = [c for c in contract["consumers"] if c["path"].endswith("/market-insights-web")]
        self.assertEqual(len(ui), 1)
        self.assertEqual(ui[0]["must_match_ports"], list(range(8101, 8108)))
        self.assertEqual(ui[0]["catalog_files"], ["src/data-products/catalog.ts", "js/data-products-browser.js"])


class RepositoryFixtureTests(unittest.TestCase):
    def test_repository_fixture_is_valid(self) -> None:
        self.assertEqual(lineage.validate(ROOT), [])

    def test_vendored_contract_matches_pin(self) -> None:
        digest = hashlib.sha256((ROOT / lineage.CONTRACT_RELATIVE).read_bytes()).hexdigest()
        self.assertEqual(lineage.read_pin(ROOT / lineage.PIN_RELATIVE), (digest, None))

    def test_statuses_reflect_the_recorded_gaps(self) -> None:
        fixture = lineage.load_fixture(ROOT)
        status = {p["id"]: p["status"] for p in fixture["products"]}
        self.assertEqual(
            status,
            {
                "crypto": "verified",
                "stocks": "verified",
                "fx": "verified",
                "defi": "verified",
                "flights": "unverified",
                "seo": "unverified",
                "ai_tools": "unverified",
            },
        )
        # Static verification only: nothing claims runtime lake lineage.
        self.assertEqual({p["runtime_lineage_status"] for p in fixture["products"]}, {"unverified"})

    def test_main_reports_ok(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(lineage.main([str(ROOT)]), 0)
        self.assertIn("7 v2 products (4 verified, 3 unverified)", out.getvalue())


class ContractCoverageTests(_RepoCopy):
    def test_product_missing_from_fixture_fails(self) -> None:
        self.fixture["products"] = [p for p in self.fixture["products"] if p["id"] != "fx"]
        self.write_fixture()
        self.assertIn("contract product 'fx' is missing from the lineage fixture", lineage.validate(self.root))

    def test_new_contract_product_without_fixture_entry_fails(self) -> None:
        text = (self.root / lineage.CONTRACT_RELATIVE).read_text(encoding="utf-8")
        self.write_contract(text.replace("consumers:\n", EXTRA_PRODUCT, 1))
        self.assertEqual(
            lineage.validate(self.root),
            ["contract product 'weather' is missing from the lineage fixture"],
        )

    def test_edited_contract_without_repin_fails(self) -> None:
        text = (self.root / lineage.CONTRACT_RELATIVE).read_text(encoding="utf-8")
        self.write_contract(text.replace("port: 8103", "port: 8199"), repin=False)
        errors = lineage.validate(self.root)
        self.assertTrue(any("does not match pin" in e for e in errors), errors)
        self.assertTrue(any("fixture contract.port 8103 != v2 contract 8199" in e for e in errors), errors)

    def test_fixture_product_not_in_contract_fails(self) -> None:
        extra = copy.deepcopy(self.product("fx"))
        extra["id"] = "retired_synthesis"
        self.fixture["products"].append(extra)
        self.write_fixture()
        self.assertIn("fixture product 'retired_synthesis' is not in the v2 contract", lineage.validate(self.root))

    def test_schema_version_drift_fails(self) -> None:
        self.product("seo")["contract"]["schema_version"] = "seo.v2"
        self.write_fixture()
        self.assertTrue(any("product seo: fixture contract.schema_version" in e for e in lineage.validate(self.root)))


class VerifiedEvidenceTests(_RepoCopy):
    def test_verified_without_producer_evidence_fails(self) -> None:
        crypto = self.product("crypto")
        crypto["evidence"] = [e for e in crypto["evidence"] if e["kind"] != "producer_config"]
        self.write_fixture()
        self.assertIn("product crypto: marked verified but has no 'producer_config' evidence", lineage.validate(self.root))

    def test_verified_without_lake_lineage_evidence_fails(self) -> None:
        stocks = self.product("stocks")
        stocks["evidence"] = [e for e in stocks["evidence"] if not e["kind"].startswith("lake_")]
        self.write_fixture()
        errors = lineage.validate(self.root)
        for kind in ("lake_registration", "lake_path_template", "lake_ingest"):
            self.assertIn(f"product stocks: marked verified but has no {kind!r} evidence", errors)

    def test_verified_without_lake_datasets_fails(self) -> None:
        self.product("defi")["lake"]["datasets"] = []
        self.write_fixture()
        self.assertIn("product defi: marked verified but lake domain/datasets are empty", lineage.validate(self.root))

    def test_promoting_gapped_product_to_verified_fails(self) -> None:
        self.product("flights")["status"] = "verified"
        self.write_fixture()
        errors = lineage.validate(self.root)
        self.assertIn("product flights: marked verified but still lists gaps", errors)
        self.assertIn("product flights: marked verified but carries lineage_gap evidence", errors)

    def test_unverified_without_gap_fails(self) -> None:
        self.product("seo")["gaps"] = []
        self.write_fixture()
        self.assertIn("product seo: marked unverified without naming a gap", lineage.validate(self.root))

    def test_evidence_from_unpinned_repository_fails(self) -> None:
        self.product("fx")["evidence"][0]["repo"] = "some-other-repo"
        self.write_fixture()
        self.assertTrue(any("is not pinned in sources" in e for e in lineage.validate(self.root)))

    def test_short_commit_pin_fails(self) -> None:
        self.fixture["sources"]["market-data"]["commit"] = "5c2dbd9"
        self.write_fixture()
        self.assertIn("sources.market-data: commit must be a full 40-hex sha", lineage.validate(self.root))

    def test_ui_port_drift_fails(self) -> None:
        self.product("crypto")["ui_consumer"]["base_url"] = "http://127.0.0.1:9999"
        self.write_fixture()
        self.assertIn("product crypto: ui_consumer.base_url does not use contract port 8101", lineage.validate(self.root))


@unittest.skipIf(shutil.which("git") is None, "git is required for source verification tests")
class SourceVerificationTests(_RepoCopy):
    """Run verify_sources against a synthetic git checkout (no network)."""

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.checkout), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout.strip()

    def setUp(self) -> None:
        super().setUp()
        self.book_dev = Path(self._temp.name) / "book-dev"
        self.checkout = self.book_dev / "github" / "synthetic" / "producer"
        (self.checkout / "src" / "book_synth").mkdir(parents=True)
        (self.checkout / "systems" / "architecture").mkdir(parents=True)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        self.git("config", "commit.gpgsign", "false")
        config = self.checkout / "src" / "book_synth" / "config.py"
        config.write_text('SCHEMA_VERSION = "synth.v1"\nLAKE_DOMAIN = "market"\n', encoding="utf-8")
        shutil.copyfile(
            self.root / lineage.CONTRACT_RELATIVE,
            self.checkout / "systems" / "architecture" / "data-product-contracts-v2.yaml",
        )
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "synthetic producer")
        commit = self.git("rev-parse", "HEAD")
        source = {"github": "synthetic/producer", "commit": commit, "checkout": "github/synthetic/producer"}
        self.fixture["sources"] = {"synthetic": source}
        self.fixture["contract"]["vendored_from"]["source"] = "synthetic"
        self.fixture["contract"]["canonical"]["source"] = "absent"
        evidence = {"kind": "lake_registration", "claim": "domain", "repo": "synthetic",
                    "path": "src/book_synth/config.py", "line": 2, "contains": 'LAKE_DOMAIN = "market"'}
        for product in self.fixture["products"]:
            product["evidence"] = [dict(evidence)]
        self.write_fixture()
        config.write_text('SCHEMA_VERSION = "synth.v1"\nLAKE_DOMAIN = "travel"\n', encoding="utf-8")
        self.git("commit", "-q", "-am", "later drift that the pinned commit must not see")

    def test_evidence_lines_match_pinned_commit(self) -> None:
        self.assertEqual(lineage.verify_sources(self.root, self.book_dev), [])

    def test_evidence_line_drift_fails(self) -> None:
        for product in self.fixture["products"]:
            product["evidence"][0]["contains"] = 'LAKE_DOMAIN = "travel"'
        self.write_fixture()
        errors = lineage.verify_sources(self.root, self.book_dev)
        self.assertEqual(len(errors), 7)
        self.assertTrue(all("line does not contain" in e for e in errors), errors)

    def test_missing_pinned_commit_fails(self) -> None:
        self.fixture["sources"]["synthetic"]["commit"] = "0" * 40
        self.write_fixture()
        errors = lineage.verify_sources(self.root, self.book_dev)
        self.assertTrue(any("not readable" in e for e in errors), errors)

    def test_vendored_contract_differs_from_pinned_source_fails(self) -> None:
        path = self.root / lineage.CONTRACT_RELATIVE
        path.write_bytes(path.read_bytes() + b"# local edit\n")
        errors = lineage.verify_sources(self.root, self.book_dev)
        self.assertTrue(any("differs from synthetic" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
