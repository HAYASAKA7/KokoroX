import hashlib
import json
from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def fixture(tree: str, path: str) -> dict:
    return json.loads(
        (Path("tests/fixtures/research") / tree / path).read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    "schema_name,path",
    [
        ("research-request", "request.json"),
        ("research-workspace", "workspace.json"),
        ("research-source-record", "sources/source-official-profile.json"),
        ("research-claim", "claims/claim-role.json"),
        ("research-conflict", "conflicts/conflict-adaptation-wording.json"),
        ("research-coverage", "coverage.json"),
    ],
)
def test_complete_research_artifacts_are_schema_valid(schema_name: str, path: str) -> None:
    SCHEMAS.validate(schema_name, fixture("complete", path))


@pytest.mark.parametrize("tree", ["partial", "injection"])
def test_partial_and_injection_artifacts_are_schema_valid(tree: str) -> None:
    for schema_name, path in (
        ("research-request", "request.json"),
        ("research-workspace", "workspace.json"),
        ("research-source-record", "sources/source-official-profile.json"),
        ("research-claim", "claims/claim-role.json"),
        ("research-conflict", "conflicts/conflict-adaptation-wording.json"),
        ("research-coverage", "coverage.json"),
    ):
        SCHEMAS.validate(schema_name, fixture(tree, path))


def test_complete_workspace_digests_match_referenced_file_bytes() -> None:
    root = Path("tests/fixtures/research/complete")
    workspace = fixture("complete", "workspace.json")
    records = [workspace["request"], *workspace["sources"], *workspace["claims"], *workspace["conflicts"], workspace["coverage"]]
    for record in records:
        assert hashlib.sha256((root / record["path"]).read_bytes()).hexdigest() == record["sha256"]


def invalid(schema_name: str, document: dict) -> None:
    with pytest.raises(KokoroError) as raised:
        SCHEMAS.validate(schema_name, document)
    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


def test_closed_request_rejects_unknown_field_and_public_visibility() -> None:
    request = fixture("complete", "request.json")
    request["unknown"] = True
    invalid("research-request", request)
    request = fixture("complete", "request.json")
    request["requested_visibility"] = "public"
    invalid("research-request", request)


@pytest.mark.parametrize(
    "schema_name,path,field,value",
    [
        ("research-source-record", "sources/source-official-profile.json", "locator", "file:///C:/secret"),
        ("research-source-record", "sources/source-official-profile.json", "content_sha256", "A" * 64),
        ("research-source-record", "sources/source-official-profile.json", "source_id", "aux"),
        ("research-claim", "claims/claim-role.json", "classification", "canonical_score"),
        ("research-conflict", "conflicts/conflict-adaptation-wording.json", "kind", "majority_wins"),
        ("research-workspace", "workspace.json", "artifact_id", "lpt1"),
    ],
)
def test_research_schemas_reject_invalid_values(
    schema_name: str, path: str, field: str, value: str
) -> None:
    document = fixture("complete", path)
    document[field] = value
    invalid(schema_name, document)


@pytest.mark.parametrize(
    "classification,source_ids,supporting_claim_ids,rationale,accepted",
    [
        ("direct_fact", [], [], None, False),
        ("direct_observation", ["source-official-profile"], [], None, True),
        ("derived_interpretation", [], [], None, False),
        ("derived_interpretation", [], ["claim-role"], "Inference from the role claim.", True),
        ("user_assertion", ["source-official-profile"], [], None, False),
    ],
)
def test_claim_conditional_evidence_rules(
    classification: str, source_ids: list[str], supporting_claim_ids: list[str], rationale: str | None, accepted: bool
) -> None:
    claim = fixture("complete", "claims/claim-role.json")
    claim.update({"classification": classification, "source_ids": source_ids, "supporting_claim_ids": supporting_claim_ids})
    if rationale is None:
        claim.pop("rationale", None)
    else:
        claim["rationale"] = rationale
    if accepted:
        SCHEMAS.validate("research-claim", claim)
    else:
        invalid("research-claim", claim)


@pytest.mark.parametrize(
    "status,selected_claim_ids,rationale,accepted",
    [
        ("resolved_with_rationale", [], None, False),
        ("resolved_with_rationale", ["claim-role"], "The official profile is selected.", True),
        ("scope_separated", [], None, False),
        ("scope_separated", [], "Each wording applies to a separate adaptation.", True),
    ],
)
def test_conflict_conditional_resolution_rules(
    status: str, selected_claim_ids: list[str], rationale: str | None, accepted: bool
) -> None:
    conflict = fixture("complete", "conflicts/conflict-adaptation-wording.json")
    conflict["status"] = status
    conflict["selected_claim_ids"] = selected_claim_ids
    if rationale is None:
        conflict.pop("resolution_rationale", None)
    else:
        conflict["resolution_rationale"] = rationale
    if accepted:
        SCHEMAS.validate("research-conflict", conflict)
    else:
        invalid("research-conflict", conflict)


def test_report_and_bundle_lifecycle_conditions() -> None:
    report = valid_report()
    SCHEMAS.validate("research-validation-report", report)
    report.update({"valid": False, "authoring_allowed": True})
    invalid("research-validation-report", report)
    bundle = valid_bundle()
    SCHEMAS.validate("research-bundle", bundle)
    bundle["activation_allowed"] = True
    invalid("research-bundle", bundle)


def test_request_and_source_bounds_are_enforced() -> None:
    request = fixture("complete", "request.json")
    request["questions"] = ["q"] * 129
    invalid("research-request", request)
    source = fixture("complete", "sources/source-official-profile.json")
    source["excerpts"] = ["x"] * 65
    invalid("research-source-record", source)


def valid_report() -> dict:
    return {
        "schema_version": "1.0", "artifact_id": "research/aoi-kisaragi-fixture/validation",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "hard_findings": [], "advisory_findings": [],
        "coverage_summary": {"covered": 2, "partial": 0, "missing": 0, "blocked": 0},
        "blocking_reasons": [], "valid": True, "authoring_allowed": True,
    }


def valid_bundle() -> dict:
    return {
        "schema_version": "1.0", "artifact_id": "research/aoi-kisaragi-fixture/bundle",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "build_status": "research", "visibility": "private", "activation_allowed": False, "authoring_allowed": True,
        "identity": {"subject_id": "aoi-kisaragi-fixture", "franchise": "fixture-arc"},
        "scope": {"continuity": "fixture-primary", "timeline_cutoff": "episode-01", "spoiler_scope": "episode-01 only"},
        "request_hash": "a" * 64, "workspace_hash": "b" * 64, "validation_report_hash": "c" * 64,
        "source_records": [{"source_id": "source-official-profile"}], "claims": [{"claim_id": "claim-role"}],
        "conflicts": [{"conflict_id": "conflict-adaptation-wording"}],
        "coverage": {"artifact_id": "research/aoi-kisaragi-fixture/coverage"},
        "limitations": [], "blocking_reasons": [], "bundle_hash": "d" * 64,
    }
