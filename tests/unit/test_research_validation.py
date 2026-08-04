from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest

import kokoroarc.research.validation as research_validation
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.research.validation import validate_research_workspace
from kokoroarc.research.workspace import ResearchWorkspace, load_research_workspace
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def loaded(tree: str = "complete") -> ResearchWorkspace:
    return load_research_workspace(Path("tests/fixtures/research") / tree, SCHEMAS)


def editable(workspace: ResearchWorkspace) -> dict[str, Any]:
    return {
        "request": deepcopy(workspace.request),
        "sources": tuple(deepcopy(list(workspace.sources))),
        "claims": tuple(deepcopy(list(workspace.claims))),
        "conflicts": tuple(deepcopy(list(workspace.conflicts))),
        "coverage": deepcopy(workspace.coverage),
        "manifest": deepcopy(workspace.manifest),
    }


def changed(
    workspace: ResearchWorkspace,
    mutate: Callable[[dict[str, Any]], None],
) -> ResearchWorkspace:
    values = editable(workspace)
    mutate(values)
    return replace(workspace, **values)


def codes(report: dict[str, Any], section: str = "hard_failures") -> list[str]:
    return [item["code"] for item in report[section]]


def test_validate_complete_workspace_allows_authoring() -> None:
    report = validate_research_workspace(loaded(), SCHEMAS)

    assert report["valid"] is True
    assert report["authoring_allowed"] is True
    assert report["hard_failures"] == []
    assert report["blocking_reasons"] == []
    assert report["coverage_summary"] == {
        "blocked": 0,
        "covered": 2,
        "missing": 0,
        "partial": 0,
    }
    assert report["artifact_id"] == "research/aoi-kisaragi-fixture/validation"
    SCHEMAS.validate("research-validation-report", report)


def test_partial_workspace_is_valid_but_blocks_authoring() -> None:
    workspace = loaded("partial")
    before = editable(workspace)

    report = validate_research_workspace(workspace, SCHEMAS)

    assert report["valid"] is True
    assert report["authoring_allowed"] is False
    assert report["hard_failures"] == []
    assert report["coverage_summary"] == {
        "blocked": 1,
        "covered": 0,
        "missing": 0,
        "partial": 1,
    }
    assert report["blocking_reasons"] == [
        "Required coverage topic blocks authoring: missing-history.",
        "Unresolved conflict blocks authoring: conflict-adaptation-wording.",
    ]
    assert codes(report, "advisory_findings") == [
        "RESEARCH_CONFLICT_BLOCKING",
        "RESEARCH_COVERAGE_INCOMPLETE",
        "RESEARCH_COVERAGE_INCOMPLETE",
    ]
    assert workspace.coverage["topics"][0]["unavailable_sources"] == [
        "source-official-profile"
    ]
    assert editable(workspace) == before
    SCHEMAS.validate("research-validation-report", report)


def test_validation_is_byte_stable_and_input_non_mutating() -> None:
    workspace = loaded()
    before = editable(workspace)

    first = validate_research_workspace(workspace, SCHEMAS)
    second = validate_research_workspace(workspace, SCHEMAS)

    assert canonical_bytes(first) == canonical_bytes(second)
    assert editable(workspace) == before


def test_schema_validation_precedes_semantic_validation() -> None:
    workspace = changed(
        loaded(),
        lambda value: value["sources"][0].update(
            {"continuity": "wrong", "unknown": "not schema-valid"}
        ),
    )

    with pytest.raises(KokoroError) as raised:
        validate_research_workspace(workspace, SCHEMAS)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


def test_reports_identity_mismatch() -> None:
    workspace = changed(
        loaded(),
        lambda value: value["claims"][0].update({"subject_id": "another-subject"}),
    )

    assert "RESEARCH_IDENTITY_MISMATCH" in codes(
        validate_research_workspace(workspace, SCHEMAS)
    )


def test_reports_continuity_mismatch() -> None:
    workspace = changed(
        loaded(),
        lambda value: value["sources"][0].update({"continuity": "other"}),
    )

    assert "RESEARCH_CONTINUITY_MISMATCH" in codes(
        validate_research_workspace(workspace, SCHEMAS)
    )


def test_reports_timeline_violation() -> None:
    workspace = changed(
        loaded(),
        lambda value: value["claims"][0].update({"timeline": "episode-02"}),
    )

    assert "RESEARCH_TIMELINE_VIOLATION" in codes(
        validate_research_workspace(workspace, SCHEMAS)
    )


def test_reports_spoiler_scope_violation() -> None:
    workspace = changed(
        loaded(),
        lambda value: value["sources"][0].update(
            {"spoiler_scope": "through episode-12"}
        ),
    )

    assert "RESEARCH_SPOILER_SCOPE_VIOLATION" in codes(
        validate_research_workspace(workspace, SCHEMAS)
    )


def test_reports_duplicate_id() -> None:
    def duplicate(value: dict[str, Any]) -> None:
        value["claims"] = (*value["claims"], deepcopy(value["claims"][0]))

    assert "RESEARCH_DUPLICATE_ID" in codes(
        validate_research_workspace(changed(loaded(), duplicate), SCHEMAS)
    )


def test_reports_dangling_reference() -> None:
    workspace = changed(
        loaded(),
        lambda value: value["claims"][0].update(
            {"source_ids": ["missing-source"]}
        ),
    )

    assert "RESEARCH_DANGLING_REFERENCE" in codes(
        validate_research_workspace(workspace, SCHEMAS)
    )


def test_reports_circular_derivation() -> None:
    def circular(value: dict[str, Any]) -> None:
        first, second = value["claims"]
        first.update(
            {
                "classification": "derived_interpretation",
                "support": "indirect",
                "source_ids": [],
                "supporting_claim_ids": [second["claim_id"]],
                "derivation_rationale": "Derived from the other scoped claim.",
            }
        )
        second.update(
            {
                "classification": "derived_interpretation",
                "support": "indirect",
                "source_ids": [],
                "supporting_claim_ids": [first["claim_id"]],
                "derivation_rationale": "Derived from the other scoped claim.",
            }
        )

    assert "RESEARCH_CIRCULAR_DERIVATION" in codes(
        validate_research_workspace(changed(loaded(), circular), SCHEMAS)
    )


def test_deep_acyclic_derivation_graph_is_bounded_without_recursion() -> None:
    claims = tuple(
        {
            "claim_id": f"claim-{index:04d}",
            "supporting_claim_ids": (
                [] if index == 1023 else [f"claim-{index + 1:04d}"]
            ),
        }
        for index in range(1024)
    )
    indexed = {claim["claim_id"]: claim for claim in claims}
    findings: list[dict[str, Any]] = []

    research_validation._validate_derivation_graph(claims, indexed, findings)

    assert findings == []


def test_reports_direct_claim_without_usable_source_support() -> None:
    workspace = changed(
        loaded(),
        lambda value: value["claims"][0].update({"support": "unsupported"}),
    )

    assert "RESEARCH_SOURCE_SUPPORT_REQUIRED" in codes(
        validate_research_workspace(workspace, SCHEMAS)
    )


def test_unavailable_source_cannot_support_a_direct_claim() -> None:
    def unavailable(value: dict[str, Any]) -> None:
        source = value["sources"][0]
        source.update(
            {
                "availability": "unavailable",
                "limitations": ["The retained source is unavailable."],
            }
        )
        value["coverage"]["topics"][0]["unavailable_sources"] = [
            source["source_id"]
        ]

    report = validate_research_workspace(changed(loaded(), unavailable), SCHEMAS)

    assert "RESEARCH_SOURCE_SUPPORT_REQUIRED" in codes(report)


def test_reports_invalid_derived_claim_semantics() -> None:
    def invalid_derivation(value: dict[str, Any]) -> None:
        claim = value["claims"][0]
        claim.update(
            {
                "classification": "derived_interpretation",
                "support": "direct",
                "source_ids": [],
                "supporting_claim_ids": [value["claims"][1]["claim_id"]],
                "derivation_rationale": "Derived from the role claim.",
            }
        )

    assert "RESEARCH_DERIVATION_REQUIRED" in codes(
        validate_research_workspace(changed(loaded(), invalid_derivation), SCHEMAS)
    )


def test_reports_user_assertion_relabelled_as_external_evidence() -> None:
    def relabel(value: dict[str, Any]) -> None:
        value["request"]["user_assertions"] = [value["claims"][0]["statement"]]

    assert "RESEARCH_USER_ASSERTION_RELABELLED" in codes(
        validate_research_workspace(changed(loaded(), relabel), SCHEMAS)
    )


def test_user_supplied_source_cannot_be_relabelled_as_direct_canon() -> None:
    workspace = changed(
        loaded(),
        lambda value: value["sources"][0].update({"category": "user_supplied"}),
    )

    assert "RESEARCH_USER_ASSERTION_RELABELLED" in codes(
        validate_research_workspace(workspace, SCHEMAS)
    )


def test_prohibits_structured_normalized_trait_but_allows_in_world_quantity() -> None:
    def measured(kind: str) -> ResearchWorkspace:
        def add_measurement(value: dict[str, Any]) -> None:
            measurement: dict[str, Any] = {
                "kind": kind,
                "value": 10 if kind == "in_world_quantity" else 0.9,
                "unit": "years" if kind == "in_world_quantity" else "ratio",
            }
            if kind == "normalized_trait":
                measurement["trait_name"] = "patience"
            value["claims"][0]["measurement"] = measurement
            value["claims"][0]["statement"] = (
                "She waited 10 years."
                if kind == "in_world_quantity"
                else "Patience is scored for downstream calibration."
            )

        return changed(loaded(), add_measurement)

    allowed = validate_research_workspace(measured("in_world_quantity"), SCHEMAS)
    prohibited = validate_research_workspace(measured("normalized_trait"), SCHEMAS)

    assert "RESEARCH_CANONICAL_TRAIT_SCORE_PROHIBITED" not in codes(allowed)
    assert "RESEARCH_CANONICAL_TRAIT_SCORE_PROHIBITED" in codes(prohibited)


def test_unresolved_conflict_is_structurally_valid_but_blocks_authoring() -> None:
    def unresolved(value: dict[str, Any]) -> None:
        conflict = value["conflicts"][0]
        conflict.update({"status": "unresolved", "selected_claim_ids": []})
        conflict.pop("resolution_rationale")

    report = validate_research_workspace(changed(loaded(), unresolved), SCHEMAS)

    assert report["valid"] is True
    assert report["authoring_allowed"] is False
    assert "RESEARCH_CONFLICT_BLOCKING" in codes(report, "advisory_findings")


def test_scope_separation_must_match_distinct_claim_scopes() -> None:
    workspace = changed(
        loaded(),
        lambda value: value["conflicts"][0].update(
            {"scopes": ["fixture-primary@episode-01"]}
        ),
    )

    assert "RESEARCH_CONTINUITY_MISMATCH" in codes(
        validate_research_workspace(workspace, SCHEMAS)
    )


def test_conflict_and_coverage_references_must_resolve() -> None:
    def dangling(value: dict[str, Any]) -> None:
        value["conflicts"][0]["selected_claim_ids"] = ["missing-claim"]
        value["coverage"]["topics"][0]["supporting_claim_ids"] = [
            "missing-claim"
        ]
        value["coverage"]["topics"][0]["unavailable_sources"] = [
            "missing-source"
        ]

    report = validate_research_workspace(changed(loaded(), dangling), SCHEMAS)

    dangling_findings = [
        item
        for item in report["hard_failures"]
        if item["code"] == "RESEARCH_DANGLING_REFERENCE"
    ]
    assert {tuple(item["path"][:2]) for item in dangling_findings} == {
        ("conflicts", 0),
        ("coverage", "topics"),
    }


def test_incomplete_required_coverage_blocks_authoring() -> None:
    def blocked(value: dict[str, Any]) -> None:
        topic = value["coverage"]["topics"][0]
        topic.update(
            {
                "status": "blocked",
                "supporting_claim_ids": [],
                "missing_evidence": ["No permitted evidence covers this topic."],
                "blocks_authoring": True,
            }
        )
        value["coverage"]["blocks_authoring"] = True

    report = validate_research_workspace(changed(loaded(), blocked), SCHEMAS)

    assert report["valid"] is True
    assert report["authoring_allowed"] is False
    assert "RESEARCH_COVERAGE_INCOMPLETE" in codes(report, "advisory_findings")


def test_missing_required_coverage_topic_is_a_hard_failure() -> None:
    def missing(value: dict[str, Any]) -> None:
        value["coverage"]["topics"] = value["coverage"]["topics"][:1]

    report = validate_research_workspace(changed(loaded(), missing), SCHEMAS)

    assert "RESEARCH_COVERAGE_INCOMPLETE" in codes(report)
    assert report["valid"] is False


def test_unavailable_source_requires_a_retained_limitation() -> None:
    def remove_limitation(value: dict[str, Any]) -> None:
        value["sources"][0].update(
            {"availability": "unavailable", "limitations": []}
        )
        value["coverage"]["topics"][0]["unavailable_sources"] = [
            value["sources"][0]["source_id"]
        ]

    report = validate_research_workspace(
        changed(loaded(), remove_limitation), SCHEMAS
    )

    assert "RESEARCH_COVERAGE_INCOMPLETE" in codes(report)


def test_repeated_dangling_references_are_deduplicated_for_report_schema() -> None:
    def dangling(value: dict[str, Any]) -> None:
        value["claims"][0]["source_ids"] = ["missing-a", "missing-b"]

    report = validate_research_workspace(changed(loaded(), dangling), SCHEMAS)

    matching = [
        item
        for item in report["hard_failures"]
        if item["code"] == "RESEARCH_DANGLING_REFERENCE"
        and item["path"] == ["claims", 0, "source_ids"]
    ]
    assert len(matching) == 1
    SCHEMAS.validate("research-validation-report", report)


def test_blocking_reasons_are_sorted_and_bounded() -> None:
    def many_unresolved(value: dict[str, Any]) -> None:
        template = value["conflicts"][0]
        conflicts = []
        for index in range(140):
            conflict = deepcopy(template)
            conflict.update(
                {
                    "artifact_id": f"research/aoi-kisaragi-fixture/conflict-{index}",
                    "conflict_id": f"conflict-{index}",
                    "status": "unresolved",
                    "selected_claim_ids": [],
                }
            )
            conflict.pop("resolution_rationale")
            conflicts.append(conflict)
        value["conflicts"] = tuple(conflicts)

    report = validate_research_workspace(changed(loaded(), many_unresolved), SCHEMAS)

    assert len(report["blocking_reasons"]) == 128
    assert report["blocking_reasons"] == sorted(report["blocking_reasons"])
    assert report["authoring_allowed"] is False
    SCHEMAS.validate("research-validation-report", report)


def test_findings_are_sorted_bounded_and_schema_valid() -> None:
    def many_duplicates(value: dict[str, Any]) -> None:
        original = value["claims"][0]
        value["claims"] = tuple(deepcopy(original) for _ in range(300))

    report = validate_research_workspace(changed(loaded(), many_duplicates), SCHEMAS)

    assert len(report["hard_failures"]) == 256
    assert report["hard_failures"] == sorted(
        report["hard_failures"],
        key=lambda item: (
            item["code"],
            canonical_bytes(item["path"]),
            item["message"],
        ),
    )
    SCHEMAS.validate("research-validation-report", report)
