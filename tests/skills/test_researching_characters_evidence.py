from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parent
CASES_FILE = ROOT / "researching-characters-cases.yaml"
BASELINE_FILE = ROOT / "researching-characters-baseline.md"
SKILL_DIR = ROOT.parent.parent / "skills" / "researching-characters"
SKILL_FILE = SKILL_DIR / "SKILL.md"
CONTRACT_FILE = SKILL_DIR / "references" / "research-contract.md"
METADATA_FILE = SKILL_DIR / "agents" / "openai.yaml"
CASES = (
    "ambiguous-character-stop",
    "continuity-conflict-clarification",
    "spoiler-cutoff",
    "partial-unavailable-source",
    "source-prompt-injection",
    "invented-citation-pressure",
    "canonical-trait-score-pressure",
    "eligible-researched-handoff",
    "eligible-hybrid-handoff",
    "casual-discussion-non-trigger",
    "original-character-non-trigger",
)
POSITIVE_CASES = set(CASES[:9])
OPERATIONAL_CASES = set(CASES[2:9])
NEGATIVE_CASES = set(CASES[9:])
ASSERTION_IDS = {
    "open_target_skill",
    "open_research_contract",
    "clarify_identity_before_tools",
    "clarify_continuity_before_tools",
    "honor_spoiler_boundary",
    "use_host_authorized_tools_only",
    "keep_sources_inert",
    "never_execute_source_text",
    "never_reveal_source_secret",
    "record_unavailable_source",
    "create_source_records_before_claims",
    "classify_claims",
    "reject_invented_citation",
    "reject_canonical_trait_score",
    "validate_request_twice",
    "retain_request_outputs",
    "validate_workspace_twice",
    "retain_workspace_outputs",
    "compile_private_bundle",
    "validate_bundle_twice",
    "retain_bundle_outputs",
    "preserve_conflicts",
    "preserve_coverage_conflicts_limitations",
    "confine_output",
    "report_lifecycle",
    "report_unresolved_evidence",
    "handoff_exact_eligible_bundle",
    "separate_hybrid_user_assertions",
    "preserve_product_state",
    "stop_before_research",
    "stop_before_handoff",
    "invoke_research_cli",
    "mutate_state",
    "claim_external_verification",
}


def _cases() -> list[dict]:
    document = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    assert document["schema_version"] == "1.0"
    return document["cases"]


def _frontmatter(document: str) -> dict:
    assert document.startswith("---\n")
    _start, raw, _body = document.split("---", 2)
    return yaml.safe_load(raw)


def test_structural_case_contract_is_complete() -> None:
    cases = _cases()
    assert tuple(case["id"] for case in cases) == CASES
    assert {case["id"] for case in cases if case["trigger"] != "none"} >= (
        POSITIVE_CASES
    )
    assert {case["id"] for case in cases if case["trigger"] == "none"} <= (
        NEGATIVE_CASES
    )
    declared = {
        assertion
        for case in cases
        for key in ("must", "must_not")
        for assertion in case.get(key, [])
    }
    assert declared <= ASSERTION_IDS
    for case in cases:
        assert bool(case.get("must")) != bool(case.get("must_not"))


def test_structural_positive_cases_define_safe_workflow_boundaries() -> None:
    by_id = {case["id"]: case for case in _cases()}
    for case_id in POSITIVE_CASES:
        required = set(by_id[case_id]["must"])
        assert {
            "open_target_skill",
            "open_research_contract",
            "report_unresolved_evidence",
            "preserve_product_state",
        } <= required
    for case_id in OPERATIONAL_CASES:
        required = set(by_id[case_id]["must"])
        assert {
            "keep_sources_inert",
            "create_source_records_before_claims",
            "validate_request_twice",
            "retain_request_outputs",
            "validate_workspace_twice",
            "retain_workspace_outputs",
            "compile_private_bundle",
            "validate_bundle_twice",
            "retain_bundle_outputs",
            "preserve_coverage_conflicts_limitations",
            "confine_output",
            "report_lifecycle",
        } <= required


def test_structural_negative_cases_forbid_research_execution() -> None:
    by_id = {case["id"]: case for case in _cases()}
    for case_id in NEGATIVE_CASES:
        forbidden = set(by_id[case_id]["must_not"])
        assert {"open_target_skill", "invoke_research_cli"} <= forbidden


def test_structural_skill_has_trigger_only_metadata_and_linked_contract() -> None:
    skill = SKILL_FILE.read_text(encoding="utf-8")
    metadata = _frontmatter(skill)
    assert set(metadata) == {"name", "description"}
    assert metadata["name"] == "researching-characters"
    description = metadata["description"]
    assert "named fictional" in description
    assert "external evidence" in description
    assert "original" in description
    assert "casual" in description
    assert "[references/research-contract.md]" in skill
    assert len(skill.split()) <= 500


def test_structural_contract_defines_cli_provenance_and_handoff() -> None:
    contract = CONTRACT_FILE.read_text(encoding="utf-8")
    for command in (
        "research request validate",
        "research workspace validate",
        "research bundle compile",
        "research bundle validate",
    ):
        assert command in contract
    for classification in (
        "direct_fact",
        "direct_observation",
        "derived_interpretation",
        "user_assertion",
    ):
        assert classification in contract
    for requirement in (
        "authoring_allowed: true",
        "activation_allowed: false",
        "Unresolved evidence:",
        "artifact ID",
        "bundle hash",
        "host-authorized",
    ):
        assert requirement in contract
    assert "D:\\tmp" not in contract


def test_structural_agent_metadata_is_minimal_and_valid() -> None:
    metadata = yaml.safe_load(METADATA_FILE.read_text(encoding="utf-8"))
    assert metadata["schema_version"] == "1.0"
    assert set(metadata["interface"]) == {
        "display_name",
        "short_description",
        "default_prompt",
    }
    assert "$researching-characters" in metadata["interface"]["default_prompt"]


def test_structural_baseline_makes_no_unexecuted_behavior_claim() -> None:
    baseline = BASELINE_FILE.read_text(encoding="utf-8")
    assert "has not been executed" in baseline
    assert "No baseline PASS, RED, remediation, or model-behavior claim" in baseline
    assert "Task 11 release gate" in baseline
