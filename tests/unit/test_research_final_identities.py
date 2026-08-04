from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


ROOT = Path("tests/fixtures/research")
SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def load(tree: str, relative: str) -> dict:
    return json.loads((ROOT / tree / relative).read_text(encoding="utf-8"))


def assembled(tree: str) -> dict:
    manifest = load(tree, "workspace.json")
    records = lambda key: [load(tree, entry["path"]) for entry in manifest[key]]
    return {
        "request": load(tree, manifest["request"]["path"]),
        "sources": sorted(records("sources"), key=lambda record: record["source_id"]),
        "claims": sorted(records("claims"), key=lambda record: record["claim_id"]),
        "conflicts": sorted(records("conflicts"), key=lambda record: record["conflict_id"]),
        "coverage": load(tree, manifest["coverage"]["path"]),
    }


@pytest.mark.parametrize("tree", ["complete", "partial"])
def test_bundle_workspace_hashes_artifact_contents_not_manifest_entries(tree: str) -> None:
    bundle = load(tree, "bundle.json")
    assert bundle["workspace_hash"] == sha256(canonical_bytes(assembled(tree))).hexdigest()


@pytest.mark.parametrize(
    "timestamp,accepted",
    [
        ("2024-02-29T00:00:00Z", True), ("2000-02-29T00:00:00Z", True),
        ("2025-02-29T00:00:00Z", False), ("1900-02-29T00:00:00Z", False),
        ("2026-02-30T25:61:61+99:99", False),
    ],
)
def test_standalone_source_enforces_leap_year_calendar(timestamp: str, accepted: bool) -> None:
    source = load("complete", "sources/source-official-profile.json")
    source["accessed_at"] = timestamp
    if accepted:
        SCHEMAS.validate("research-source-record", source)
    else:
        with pytest.raises(KokoroError):
            SCHEMAS.validate("research-source-record", source)


@pytest.mark.parametrize(
    "timestamp,accepted",
    [
        ("2024-02-29T00:00:00Z", True), ("2000-02-29T00:00:00Z", True),
        ("2025-02-29T00:00:00Z", False), ("1900-02-29T00:00:00Z", False),
        ("2026-02-30T25:61:61+99:99", False),
    ],
)
def test_embedded_source_enforces_same_calendar(timestamp: str, accepted: bool) -> None:
    bundle = load("complete", "bundle.json")
    bundle["sources"][0]["accessed_at"] = timestamp
    if accepted:
        SCHEMAS.validate("research-bundle", bundle)
    else:
        with pytest.raises(KokoroError):
            SCHEMAS.validate("research-bundle", bundle)
