import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
ROOT = Path("tests/fixtures/research")


def load(tree: str, path: str) -> dict:
    return json.loads((ROOT / tree / path).read_text(encoding="utf-8"))



def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def invalid(schema_name: str, document: dict) -> None:
    with pytest.raises(KokoroError) as raised:
        SCHEMAS.validate(schema_name, document)
    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


def test_request_uses_public_flat_identity_and_scope_contract() -> None:
    request = load("complete", "request.json")
    assert request["namespace"] == "research"
    assert request["character_id"] == "aoi-kisaragi-fixture"
    assert request["display_name"] == "Aoi Kisaragi Fixture"
    assert request["research_questions"]
    assert request["required_coverage_topics"] == ["role", "behavior"]
    assert "subject" not in request and "scope" not in request


@pytest.mark.parametrize(
    "locator",
    [
        "https://user:pass@evidence.fixture-arc.example/aoi",
        "kokoro-evidence:fixture/../../secret",
    ],
)
def test_source_locator_rejects_credentials_and_logical_traversal(locator: str) -> None:
    source = load("complete", "sources/source-official-profile.json")
    source["locator"] = locator
    invalid("research-source-record", source)


def test_source_requires_explicit_rfc3339_access_time() -> None:
    source = load("complete", "sources/source-official-profile.json")
    source["accessed_at"] = "not-rfc3339"
    invalid("research-source-record", source)


@pytest.mark.parametrize("path", ["sources/con.json", "claims/../claim-role.json", "C:/secret.json", "//host/share.json", "sources/name:stream.json"])
def test_workspace_rejects_device_and_non_relative_reference_paths(path: str) -> None:
    workspace = load("complete", "workspace.json")
    workspace["sources"][0]["path"] = path
    invalid("research-workspace", workspace)


def test_claim_requires_exact_derivation_rationale_field() -> None:
    claim = load("complete", "claims/claim-role.json")
    claim.update({"classification": "derived_interpretation", "source_ids": [], "supporting_claim_ids": ["claim-behavior"], "derivation_rationale": "Derived from the observed response."})
    SCHEMAS.validate("research-claim", claim)
    claim["rationale"] = claim.pop("derivation_rationale")
    invalid("research-claim", claim)


def test_conflict_statuses_have_exact_selection_and_rationale_rules() -> None:
    conflict = load("complete", "conflicts/conflict-adaptation-wording.json")
    conflict.update({"status": "unresolved", "selected_claim_ids": ["claim-role"]})
    invalid("research-conflict", conflict)
    conflict["selected_claim_ids"] = []
    conflict.pop("resolution_rationale")
    SCHEMAS.validate("research-conflict", conflict)
    conflict.update({"status": "scope_separated", "selected_claim_ids": []})
    invalid("research-conflict", conflict)


def test_coverage_requires_per_topic_authoring_gate() -> None:
    coverage = load("complete", "coverage.json")
    coverage["topics"][0].pop("blocks_authoring")
    invalid("research-coverage", coverage)


def test_bundle_embeds_typed_records_and_flat_contract() -> None:
    bundle = load("complete", "bundle.json")
    assert bundle["character_id"] == "aoi-kisaragi-fixture"
    assert bundle["sources"][1] == load("complete", "sources/source-official-profile.json")
    assert bundle["claims"][0] == load("complete", "claims/claim-behavior.json")
    wrong = deepcopy(bundle)
    wrong["sources"][0] = wrong["claims"][0]
    invalid("research-bundle", wrong)


@pytest.mark.parametrize("tree", ["complete", "partial"])
def test_reports_and_bundles_are_schema_valid(tree: str) -> None:
    SCHEMAS.validate("research-validation-report", load(tree, "validation-report.json"))
    SCHEMAS.validate("research-bundle", load(tree, "bundle.json"))


@pytest.mark.parametrize("tree", ["complete", "partial", "injection"])
def test_workspace_digests_and_conflict_references_are_exact(tree: str) -> None:
    workspace = load(tree, "workspace.json")
    records = [workspace["request"], *workspace["sources"], *workspace["claims"], *workspace["conflicts"], workspace["coverage"]]
    for record in records:
        assert hashlib.sha256((ROOT / tree / record["path"]).read_bytes()).hexdigest() == record["sha256"]
    claim_ids = {load(tree, record["path"])["claim_id"] for record in workspace["claims"]}
    for record in workspace["conflicts"]:
        conflict = load(tree, record["path"])
        assert set(conflict["claim_ids"]).issubset(claim_ids)


@pytest.mark.parametrize("tree", ["complete", "partial"])
def test_bundle_hashes_use_canonical_fixture_identities(tree: str) -> None:
    bundle = load(tree, "bundle.json")
    request = load(tree, "request.json")
    workspace = load(tree, "workspace.json")
    report = load(tree, "validation-report.json")
    canonical_workspace = {
        "request": load(tree, workspace["request"]["path"]),
        "sources": sorted([load(tree, item["path"]) for item in workspace["sources"]], key=lambda item: item["source_id"]),
        "claims": sorted([load(tree, item["path"]) for item in workspace["claims"]], key=lambda item: item["claim_id"]),
        "conflicts": sorted([load(tree, item["path"]) for item in workspace["conflicts"]], key=lambda item: item["conflict_id"]),
        "coverage": load(tree, workspace["coverage"]["path"]),
    }
    assert bundle["request_hash"] == digest(request)
    assert bundle["workspace_hash"] == digest(canonical_workspace)
    assert bundle["validation_report_hash"] == digest(report)
    unhashed = deepcopy(bundle)
    unhashed.pop("bundle_hash")
    assert bundle["bundle_hash"] == digest(unhashed)
