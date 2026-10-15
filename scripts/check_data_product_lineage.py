#!/usr/bin/env python3
"""Check the data-product lineage fixture against the frozen v2 contract (BOO-152).

``fixtures/gates/data-product-lineage.json`` maps every product in the vendored
``contracts/vendor/data-product-contracts-v2.yaml`` to its producer repository
and package, lake domain/datasets/Bronze path, schema and freshness defaults,
and the market-insights-web catalog entry, with a ``verified``/``unverified``
status. Each evidence item names a source repository, a file, a line and a
string that line must contain at the commit pinned in ``sources``.

Offline (always, used by ``scripts/check.sh``):
  * the vendored contract matches its sha256 pin;
  * every contract product is in the fixture (and no extra product is), with the
    same port, schema_version, repository and package;
  * a ``verified`` product carries pinned evidence for every required kind
    (producer, lake registration/path/ingest, schema, freshness, API, UI) and no
    open gaps; an ``unverified`` product names at least one gap;
  * the UI consumer port matches the contract consumer port map.

With ``--book-dev PATH`` (the folder that contains ``github/``; default
``$SOLO_BOOK_DEV_ROOT``) it also reads each evidence file with
``git show <commit>:<path>`` in the local checkouts and fails when the line no
longer contains the asserted text, when the vendored contract differs from the
data-lake-pipelines copy at its pinned commit, or when the canonical
architecture-docs copy no longer has the recorded sha256. Every public source
must be readable; hosted CI (``.github/workflows/check.yml`` job ``lineage``)
checks them out at the pinned commits. The private canonical contract is
optional: when it is not available locally, only its hash comparison is skipped
(reported as ``SKIP``). Read-only; it never fetches, checks out or contacts a
network service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_RELATIVE = "fixtures/gates/data-product-lineage.json"
CONTRACT_RELATIVE = "contracts/vendor/data-product-contracts-v2.yaml"
PIN_RELATIVE = f"{CONTRACT_RELATIVE}.sha256"
CONTRACT_SOURCE_PATH = "systems/architecture/data-product-contracts-v2.yaml"
UI_CONSUMER_REPOSITORY = "market-insights-web"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PIN_RE = re.compile(r"^([0-9a-f]{64})\s+\*?(\S+)\s*$")
STATUSES = ("verified", "unverified")
PRODUCT_KEYS = ("port", "schema_version", "repository", "package")
DEFAULT_REQUIRED_KINDS = (
    "producer_config",
    "lake_registration",
    "lake_path_template",
    "lake_ingest",
    "schema",
    "freshness",
    "api_routes",
    "ui_consumer",
)


# --------------------------------------------------------------------------- #
# Minimal reader for the contract's YAML subset (no third-party packages).


def _scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_scalar(part) for part in inner.split(",")] if inner else []
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if value in ("true", "false"):
        return value == "true"
    return value


def parse_contract(text: str) -> dict[str, Any]:
    """Return top-level scalars plus the ``products`` and ``consumers`` lists."""

    result: dict[str, Any] = {"products": [], "consumers": []}
    section: str | None = None
    item: dict[str, Any] | None = None
    list_key: str | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if indent == 0:
            key, _, value = line.partition(":")
            section, item, list_key = None, None, None
            if key in ("products", "consumers") and not value.strip():
                section = key
            elif value.strip():
                result[key] = _scalar(value)
            continue
        if section is None:
            continue
        if indent == 2 and line.startswith("- "):
            item = {}
            result[section].append(item)
            list_key = None
            line = line[2:]
            key, _, value = line.partition(":")
            item[key.strip()] = _scalar(value)
            continue
        if item is None:
            continue
        if line.startswith("- ") and list_key is not None:
            item[list_key].append(_scalar(line[2:]))
            continue
        key, _, value = line.partition(":")
        if value.strip():
            item[key.strip()] = _scalar(value)
            list_key = None
        else:
            list_key = key.strip()
            item[list_key] = []
    return result


# --------------------------------------------------------------------------- #


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_pin(path: Path) -> tuple[str | None, str | None]:
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeError) as exc:
        return None, f"cannot read pin file: {exc}"
    if len(lines) != 1:
        return None, "pin file must contain exactly one '<sha256>  <file>' line"
    match = PIN_RE.match(lines[0])
    if match is None:
        return None, "pin file line must be '<64 lowercase hex>  <file>'"
    if Path(match.group(2)).name != Path(CONTRACT_RELATIVE).name:
        return None, f"pin file names {match.group(2)!r}, expected {Path(CONTRACT_RELATIVE).name!r}"
    return match.group(1), None


def load_fixture(root: Path) -> dict[str, Any]:
    return json.loads((root / FIXTURE_RELATIVE).read_text(encoding="utf-8"))


def _check_evidence_item(
    errors: list[str], where: str, item: Any, sources: dict[str, Any]
) -> None:
    if not isinstance(item, dict):
        errors.append(f"{where}: evidence entry must be an object")
        return
    for key in ("kind", "claim", "repo", "path", "contains"):
        if not isinstance(item.get(key), str) or not item[key].strip():
            errors.append(f"{where}: evidence is missing {key!r}")
    line = item.get("line")
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        errors.append(f"{where}: evidence line must be a positive integer")
    repo = item.get("repo")
    if isinstance(repo, str) and repo not in sources:
        errors.append(f"{where}: evidence repo {repo!r} is not pinned in sources")
    elif isinstance(repo, str) and sources[repo].get("visibility") != "public":
        errors.append(f"{where}: evidence must come from a public source that hosted CI can read")


def validate(root: Path = ROOT) -> list[str]:
    """Offline checks: pin, contract coverage, and evidence rules."""

    errors: list[str] = []
    contract_path = root / CONTRACT_RELATIVE
    for relative in (CONTRACT_RELATIVE, PIN_RELATIVE, FIXTURE_RELATIVE):
        if not (root / relative).is_file():
            errors.append(f"{relative} is missing")
    if errors:
        return errors

    contract_bytes = contract_path.read_bytes()
    pinned, pin_error = read_pin(root / PIN_RELATIVE)
    if pin_error:
        errors.append(f"{PIN_RELATIVE}: {pin_error}")
    elif sha256_bytes(contract_bytes) != pinned:
        errors.append(
            f"{CONTRACT_RELATIVE} sha256 {sha256_bytes(contract_bytes)[:12]} does not match pin "
            f"{pinned[:12]}; re-vendor the contract and update the lineage fixture together"
        )

    try:
        fixture = load_fixture(root)
    except (OSError, ValueError) as exc:
        return errors + [f"{FIXTURE_RELATIVE}: cannot parse: {exc}"]

    contract = parse_contract(contract_bytes.decode("utf-8"))
    if fixture.get("contract", {}).get("freeze_id") != contract.get("freeze_id"):
        errors.append(
            f"fixture freeze_id {fixture.get('contract', {}).get('freeze_id')!r} != "
            f"contract freeze_id {contract.get('freeze_id')!r}"
        )
    vendored_from = fixture.get("contract", {}).get("vendored_from", {})
    if pinned and vendored_from.get("sha256") != pinned:
        errors.append("fixture contract.vendored_from.sha256 does not match the vendored contract pin")

    sources = fixture.get("sources")
    if not isinstance(sources, dict) or not sources:
        return errors + ["fixture sources must pin at least one repository"]
    for name, source in sources.items():
        if not isinstance(source, dict) or not SHA_RE.match(str(source.get("commit", ""))):
            errors.append(f"sources.{name}: commit must be a full 40-hex sha")
        if not isinstance(source, dict):
            continue
        if source.get("visibility") not in ("public", "private"):
            errors.append(f"sources.{name}: visibility must be 'public' or 'private'")
        if source.get("visibility") == "private":
            # This repository is public: record a private source by name and commit only.
            if "checkout" in source:
                errors.append(f"sources.{name}: private source must not record a checkout path")
        elif not str(source.get("checkout", "")).startswith("github/"):
            errors.append(f"sources.{name}: checkout must be a path under the Book Dev github/ folder")

    required_kinds = fixture.get("required_evidence_kinds_for_verified")
    if not isinstance(required_kinds, list) or not set(DEFAULT_REQUIRED_KINDS) <= set(required_kinds):
        errors.append(
            "required_evidence_kinds_for_verified must include " + ", ".join(DEFAULT_REQUIRED_KINDS)
        )
        required_kinds = list(DEFAULT_REQUIRED_KINDS)

    products = fixture.get("products")
    if not isinstance(products, list):
        return errors + ["fixture products must be a list"]
    by_id: dict[str, dict[str, Any]] = {}
    for product in products:
        pid = product.get("id") if isinstance(product, dict) else None
        if not isinstance(pid, str):
            errors.append("fixture product without an id")
            continue
        if pid in by_id:
            errors.append(f"fixture lists product {pid!r} twice")
        by_id[pid] = product

    contract_ids = [p.get("id") for p in contract["products"]]
    if not contract_ids:
        errors.append(f"{CONTRACT_RELATIVE}: no products parsed")
    for missing in [pid for pid in contract_ids if pid not in by_id]:
        errors.append(f"contract product {missing!r} is missing from the lineage fixture")
    for extra in [pid for pid in by_id if pid not in contract_ids]:
        errors.append(f"fixture product {extra!r} is not in the v2 contract")

    ui_ports: set[int] = set()
    ui_consumer_found = False
    for consumer in contract["consumers"]:
        if str(consumer.get("path", "")).endswith(f"/{UI_CONSUMER_REPOSITORY}"):
            ui_consumer_found = True
            ui_ports = {int(p) for p in consumer.get("must_match_ports", [])}
    if not ui_consumer_found:
        errors.append(f"contract has no consumer at .../{UI_CONSUMER_REPOSITORY}")

    for spec in contract["products"]:
        pid = spec.get("id")
        product = by_id.get(pid)
        if product is None:
            continue
        where = f"product {pid}"
        declared = product.get("contract", {})
        for key in PRODUCT_KEYS:
            if declared.get(key) != spec.get(key):
                errors.append(
                    f"{where}: fixture contract.{key} {declared.get(key)!r} != v2 contract {spec.get(key)!r}"
                )
        status = product.get("status")
        if status not in STATUSES:
            errors.append(f"{where}: status must be one of {STATUSES}, got {status!r}")
        ui = product.get("ui_consumer", {})
        if ui.get("repository") != UI_CONSUMER_REPOSITORY:
            errors.append(f"{where}: ui_consumer.repository must be {UI_CONSUMER_REPOSITORY}")
        if ui.get("base_url") != f"http://127.0.0.1:{spec.get('port')}":
            errors.append(f"{where}: ui_consumer.base_url does not use contract port {spec.get('port')}")
        if ui_consumer_found and spec.get("port") not in ui_ports:
            errors.append(f"{where}: port {spec.get('port')} is not in the UI consumer must_match_ports")

        evidence = product.get("evidence")
        if not isinstance(evidence, list):
            errors.append(f"{where}: evidence must be a list")
            evidence = []
        for index, item in enumerate(evidence):
            _check_evidence_item(errors, f"{where} evidence[{index}]", item, sources)
        gaps = product.get("gaps")
        if not isinstance(gaps, list) or not all(isinstance(g, str) and g.strip() for g in gaps):
            errors.append(f"{where}: gaps must be a list of non-empty strings")
            gaps = []

        if status == "verified":
            kinds = {item.get("kind") for item in evidence if isinstance(item, dict)}
            for kind in required_kinds:
                if kind not in kinds:
                    errors.append(f"{where}: marked verified but has no {kind!r} evidence")
            producer = product.get("producer", {})
            if producer.get("source") not in sources or not producer.get("package_dir"):
                errors.append(f"{where}: marked verified but producer source/package_dir is not pinned")
            lake = product.get("lake", {})
            datasets = lake.get("datasets")
            if not lake.get("domain") or not isinstance(datasets, list) or not datasets:
                errors.append(f"{where}: marked verified but lake domain/datasets are empty")
            bronze = str(lake.get("bronze_path", ""))
            if not bronze.startswith(f"bronze/domain={lake.get('domain')}/dataset=") or (
                f"source={spec.get('repository')}/" not in bronze
            ):
                errors.append(f"{where}: marked verified but bronze_path does not match domain/source")
            if lake.get("records_dataset") not in (datasets or []):
                errors.append(f"{where}: records_dataset is not one of the registered datasets")
            if not product.get("freshness", {}).get("stale_after_hours_default"):
                errors.append(f"{where}: marked verified but has no freshness default")
            if gaps:
                errors.append(f"{where}: marked verified but still lists gaps")
            if any(isinstance(i, dict) and i.get("kind") == "lineage_gap" for i in evidence):
                errors.append(f"{where}: marked verified but carries lineage_gap evidence")
        elif status == "unverified" and not gaps:
            errors.append(f"{where}: marked unverified without naming a gap")
    return errors


# --------------------------------------------------------------------------- #
# Source verification against local checkouts at the pinned commits.


def git_show(checkout: Path, commit: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(checkout), "show", f"{commit}:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _private_checkouts(book_dev: Path, name: str, source: dict[str, Any]) -> list[Path]:
    """Candidate local checkouts of a private source (never recorded in the fixture)."""

    found = []
    github = book_dev / "github"
    if github.is_dir():
        for owner in sorted(p for p in github.iterdir() if p.is_dir()):
            for candidate in (owner / "private" / name, owner / name):
                if candidate.is_dir():
                    found.append(candidate)
    return found


def verify_sources(root: Path, book_dev: Path, skipped: list[str] | None = None) -> list[str]:
    """Read every evidence line at its pinned commit in the checkouts under ``book_dev``.

    Public sources must be readable (hosted CI checks them out at their pinned
    commits). The private canonical contract is optional: when it is not
    available, only its hash/products comparison is skipped and reported in
    ``skipped``.
    """

    fixture = load_fixture(root)
    sources: dict[str, Any] = fixture["sources"]
    errors: list[str] = []
    if skipped is None:
        skipped = []
    cache: dict[tuple[str, str], list[str] | None] = {}

    def lines_of(repo: str, path: str) -> list[str] | None:
        key = (repo, path)
        if key not in cache:
            source = sources[repo]
            blob = git_show(book_dev / source["checkout"], source["commit"], path)
            cache[key] = None if blob is None else blob.decode("utf-8", "replace").splitlines()
        return cache[key]

    for product in fixture["products"]:
        for item in product.get("evidence", []):
            repo, path, line = item["repo"], item["path"], item["line"]
            lines = lines_of(repo, path)
            where = f"product {product['id']} {item['kind']} {repo}:{path}:{line}"
            if lines is None:
                errors.append(f"{where}: not readable at {sources[repo]['commit'][:12]} (checkout or commit missing)")
            elif line > len(lines) or item["contains"] not in lines[line - 1]:
                errors.append(f"{where}: line does not contain {item['contains']!r}")

    contract = fixture.get("contract", {})
    vendored = (root / CONTRACT_RELATIVE).read_bytes()
    origin = contract.get("vendored_from", {})
    if sources.get(origin.get("source"), {}).get("visibility") != "public":
        errors.append("contract.vendored_from must name a public source")
    elif origin.get("source") in sources:
        source = sources[origin["source"]]
        upstream = git_show(book_dev / source["checkout"], source["commit"], origin.get("path", ""))
        if upstream is None:
            errors.append(f"vendored contract source {origin['source']} not readable at {source['commit'][:12]}")
        elif upstream != vendored:
            errors.append(f"{CONTRACT_RELATIVE} differs from {origin['source']}:{origin.get('path')} at {source['commit'][:12]}")
    canonical = contract.get("canonical", {})
    if canonical.get("source") in sources:
        source = sources[canonical["source"]]
        blob = None
        for checkout in _private_checkouts(book_dev, canonical["source"], source):
            blob = git_show(checkout, source["commit"], canonical.get("path", ""))
            if blob is not None:
                break
        if blob is None:
            skipped.append(
                f"canonical contract {canonical['source']}@{source['commit'][:12]} not available; "
                "skipped only its sha256/products comparison"
            )
        else:
            if sha256_bytes(blob) != canonical.get("sha256"):
                errors.append(f"canonical contract sha256 {sha256_bytes(blob)[:12]} != recorded {str(canonical.get('sha256'))[:12]}")
            if parse_contract(blob.decode("utf-8"))["products"] != parse_contract(vendored.decode("utf-8"))["products"]:
                errors.append("canonical contract products differ from the vendored copy")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default=str(ROOT), help="platform repository root")
    parser.add_argument(
        "--book-dev",
        default=os.environ.get("SOLO_BOOK_DEV_ROOT"),
        help="folder containing github/ with local checkouts (default: $SOLO_BOOK_DEV_ROOT)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    errors = validate(root)
    skipped: list[str] = []
    if not errors and args.book_dev:
        errors = verify_sources(root, Path(args.book_dev).expanduser().resolve(), skipped)
    for message in skipped:
        print(f"SKIP: {message}")
    if errors:
        for message in errors:
            print(f"FAIL: {message}")
        return 1
    fixture = load_fixture(root)
    counts = {status: sum(1 for p in fixture["products"] if p["status"] == status) for status in STATUSES}
    evidence = sum(len(p["evidence"]) for p in fixture["products"])
    scope = f"and {evidence} evidence lines at pinned commits" if args.book_dev else "(offline; pass --book-dev to read evidence lines)"
    print(
        f"OK: {FIXTURE_RELATIVE} covers {len(fixture['products'])} v2 products "
        f"({counts['verified']} verified, {counts['unverified']} unverified) {scope}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
