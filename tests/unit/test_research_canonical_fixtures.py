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


def load(tree: str, path: str) -> dict:
    return json.loads((ROOT / tree / path).read_text(encoding="utf-8"))


def invalid(name: str, value: dict) -> None:
    with pytest.raises(KokoroError):
        SCHEMAS.validate(name, value)


def assembled_workspace(tree: str) -> dict:
    workspace = load(tree, "workspace.json")
    artifact = lambda record: load(tree, record["path"])
    return {
        "request": artifact(workspace["request"]),
        "sources": sorted(map(artifact, workspace["sources"]), key=lambda record: record["source_id"]),
        "claims": sorted(map(artifact, workspace["claims"]), key=lambda record: record["claim_id"]),
        "conflicts": sorted(map(artifact, workspace["conflicts"]), key=lambda record: record["conflict_id"]),
        "coverage": artifact(workspace["coverage"]),
    }

@pytest.mark.parametrize("tree", ["complete", "partial"])
def test_bundle_accepts_exact_minimal_task5_constructor(tree: str) -> None:
    bundle = load(tree, "bundle.json")
    assert not {"franchise", "aliases", "medium", "work", "adaptation"}.intersection(bundle)
    SCHEMAS.validate("research-bundle", bundle)


@pytest.mark.parametrize("tree", ["complete", "partial"])
def test_bundle_uses_production_canonical_hashes_without_terminal_newline(tree: str) -> None:
    bundle = load(tree, "bundle.json")
    assert bundle["request_hash"] == sha256(canonical_bytes(load(tree, "request.json"))).hexdigest()
    assert bundle["workspace_hash"] == sha256(canonical_bytes(assembled_workspace(tree))).hexdigest()
    assert bundle["validation_report_hash"] == sha256(canonical_bytes(load(tree, "validation-report.json"))).hexdigest()
    expected = deepcopy(bundle)
    expected.pop("bundle_hash")
    assert bundle["bundle_hash"] == sha256(canonical_bytes(expected)).hexdigest()


@pytest.mark.parametrize("timestamp", [
    "2026-02-30T25:61:61+99:99", "2026-00-01T00:00:00Z",
    "2026-13-01T00:00:00Z", "2026-04-31T00:00:00Z",
    "2026-01-01T24:00:00Z", "2026-01-01T00:60:00Z",
    "2026-01-01T00:00:61Z", "2026-01-01T00:00:00+24:00",
])
def test_source_rejects_impossible_rfc3339_timestamp(timestamp: str) -> None:
    source = load("complete", "sources/source-official-profile.json")
    source["accessed_at"] = timestamp
    invalid("research-source-record", source)


def test_bundle_embedded_source_id_rejects_windows_reserved_name() -> None:
    bundle = load("complete", "bundle.json")
    bundle["sources"][0]["source_id"] = "con"
    invalid("research-bundle", bundle)


def test_injection_conflict_has_distinct_represented_scopes() -> None:
    conflict = load("injection", "conflicts/conflict-adaptation-wording.json")
    claims = {
        load("injection", f"claims/{path.name}")["claim_id"]: load("injection", f"claims/{path.name}")
        for path in (ROOT / "injection" / "claims").glob("*.json")
    }
    claim_scopes = {(claims[claim_id]["continuity"], claims[claim_id]["timeline"]) for claim_id in conflict["claim_ids"]}
    assert len(claim_scopes) >= 2
    assert set(conflict["scopes"]) == {f"{continuity}@{timeline}" for continuity, timeline in claim_scopes}
