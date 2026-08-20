from __future__ import annotations

import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator
import yaml


REPOSITORY_ROOT = Path.cwd().resolve()
CASES_FILE = REPOSITORY_ROOT / "tests" / "skills" / "complete-suite-cases.yaml"
CAMPAIGN_FILE = (
    REPOSITORY_ROOT / "tests" / "skills" / "complete-suite-campaign.yaml"
)
OUTPUT_SCHEMA_FILE = (
    REPOSITORY_ROOT / "tests" / "skills" / "complete-suite-output.schema.json"
)
EXPECTED_CASES = (
    "global-default-no-activation",
    "workspace-override-explicit-activation",
    "explicit-character-precedence",
    "consent-refusal",
    "consented-persistence-replay",
    "memory-reference-ownership",
    "safe-install-inactive",
    "archive-overwrite-pressure",
    "publication-pressure",
    "original-authoring-route",
    "named-character-research-route",
    "release-testing-route",
)
EXPECTED_COVERAGE = {
    "global_default",
    "workspace_override",
    "explicit_activation",
    "no_implicit_activation",
    "consent_refusal",
    "consented_persistence",
    "memory_reference_ownership",
    "safe_install",
    "archive_pressure",
    "publication_pressure",
    "route_using_kokoroarc",
    "route_authoring_character_packs",
    "route_researching_characters",
    "route_testing_character_packs",
}
EXPECTED_ROUTES = {
    "global-default-no-activation": "none",
    "workspace-override-explicit-activation": "using-kokoroarc",
    "explicit-character-precedence": "using-kokoroarc",
    "consent-refusal": "using-kokoroarc",
    "consented-persistence-replay": "using-kokoroarc",
    "memory-reference-ownership": "using-kokoroarc",
    "safe-install-inactive": "none",
    "archive-overwrite-pressure": "testing-character-packs",
    "publication-pressure": "testing-character-packs",
    "original-authoring-route": "authoring-character-packs",
    "named-character-research-route": "researching-characters",
    "release-testing-route": "testing-character-packs",
}
STABLE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


def _load(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _schema_nodes(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _schema_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _schema_nodes(child)


def test_complete_suite_output_schema_uses_provider_strict_subset() -> None:
    schema = json.loads(OUTPUT_SCHEMA_FILE.read_text(encoding="utf-8"))
    nodes = tuple(_schema_nodes(schema))

    unsupported_keywords = {
        "allOf",
        "dependentRequired",
        "dependentSchemas",
        "else",
        "if",
        "not",
        "then",
        "uniqueItems",
    }
    assert all(not (unsupported_keywords & node.keys()) for node in nodes)
    assert all("const" not in node for node in nodes)
    for node in nodes:
        if "pattern" in node or "enum" in node:
            assert node.get("type") == "string"

    assert schema["properties"]["schema_version"] == {
        "type": "string",
        "enum": ["1.0"],
    }

    relative_path = schema["$defs"]["relative_path"]
    validator = Draft202012Validator(relative_path)
    for accepted in ("file.json", "folder/file.json", ".hidden/config"):
        assert validator.is_valid(accepted)
    for rejected in (".", "..", "folder/.", "folder/../file.json"):
        assert not validator.is_valid(rejected)


def test_complete_suite_cases_are_closed_ordered_and_bounded() -> None:
    document = _load(CASES_FILE)

    assert set(document) == {"schema_version", "variants", "cases"}
    assert document["schema_version"] == "1.0"
    assert document["variants"] == ["baseline", "suite-enabled"]
    cases = document["cases"]
    assert isinstance(cases, list)
    assert [case["id"] for case in cases] == list(EXPECTED_CASES)

    observed_coverage: set[str] = set()
    for case in cases:
        assert isinstance(case, dict)
        assert set(case) == {
            "id",
            "route",
            "coverage",
            "setup",
            "prompt",
            "must",
            "must_not",
            "allowed_mutations",
            "protected_state",
        }
        case_id = case["id"]
        assert case["route"] == EXPECTED_ROUTES[case_id]
        assert isinstance(case["setup"], str)
        assert 20 <= len(case["setup"]) <= 1_500
        assert isinstance(case["prompt"], str)
        assert 20 <= len(case["prompt"]) <= 1_500
        coverage = case["coverage"]
        assert isinstance(coverage, list)
        assert coverage == list(dict.fromkeys(coverage))
        assert all(STABLE_IDENTIFIER.fullmatch(item) for item in coverage)
        observed_coverage.update(coverage)
        for field in ("must", "must_not"):
            assertions = case[field]
            assert isinstance(assertions, list)
            assert assertions == list(dict.fromkeys(assertions))
            assert all(STABLE_IDENTIFIER.fullmatch(item) for item in assertions)
        assert case["must"] or case["must_not"]
        allowed = case["allowed_mutations"]
        protected = case["protected_state"]
        assert isinstance(allowed, list)
        assert isinstance(protected, list)
        assert allowed == list(dict.fromkeys(allowed))
        assert protected == list(dict.fromkeys(protected))
        assert all(STABLE_IDENTIFIER.fullmatch(item) for item in allowed)
        assert all(STABLE_IDENTIFIER.fullmatch(item) for item in protected)

    assert observed_coverage == EXPECTED_COVERAGE


def test_complete_suite_campaign_state_is_closed_and_nonexecuted() -> None:
    document = _load(CAMPAIGN_FILE)

    assert set(document) == {
        "schema_version",
        "campaign_id",
        "status",
        "proposed_approval",
        "frozen_inputs",
        "user_approval",
        "execution",
    }
    assert document["schema_version"] == "1.0"
    assert document["campaign_id"] == "2026-08-20-proposed4"
    assert document["status"] in {
        "draft_not_approved",
        "approved_not_started",
    }
    assert document["execution"] == {
        "runs_started": 0,
        "runs_completed": 0,
        "raw_root_created": False,
    }

    frozen = document["frozen_inputs"]
    if frozen:
        assert isinstance(frozen, dict)
        assert set(frozen) == {
            "schema_version",
            "harness_git",
            "files",
            "wheel",
            "runtime_wheelhouse",
        }
        assert frozen["schema_version"] == "1.0"
        assert isinstance(frozen["files"], dict)
        assert frozen["files"]
        runtime = frozen["runtime_wheelhouse"]
        assert isinstance(runtime, dict)
        assert set(runtime) == {
            "schema_version",
            "root",
            "distributions",
            "inventory",
            "inventory_sha256",
            "wheels",
            "kokoroarc_wheel",
        }
        assert runtime["schema_version"] == "1.0"
        assert runtime["root"] == (
            "D:\\tmp\\kokoroarc-proposed4-wheelhouse-788e86a-01"
        )
        assert runtime["distributions"] == [
            "attrs",
            "jsonschema",
            "jsonschema-specifications",
            "kokoroarc",
            "pyyaml",
            "referencing",
            "rpds-py",
        ]
        assert re.fullmatch(r"[0-9a-f]{64}", runtime["inventory_sha256"])
        assert isinstance(runtime["inventory"], dict)
        assert isinstance(runtime["wheels"], list)
        assert len(runtime["wheels"]) == 7
        assert frozen["wheel"] == runtime["kokoroarc_wheel"]
    else:
        assert document["status"] == "draft_not_approved"

    if document["status"] == "draft_not_approved":
        assert document["user_approval"] is None
    else:
        assert frozen
        approval = document["user_approval"]
        assert isinstance(approval, dict)
        assert set(approval) == {
            "approval_id",
            "approved_at",
            "response",
            "approved_envelope_sha256",
        }
        assert approval["response"].strip()
        assert re.fullmatch(
            r"[0-9a-f]{64}",
            approval["approved_envelope_sha256"],
        )

    proposed = document["proposed_approval"]
    assert isinstance(proposed, dict)
    assert proposed["runs"] == {
        "baseline": 12,
        "suite_enabled": 12,
        "corrective": 0,
        "total": 24,
    }
    assert proposed["variants"] == ["baseline", "suite-enabled"]
    assert proposed["cases"] == list(EXPECTED_CASES)
    assert proposed["evaluator"] == {
        "provider": "openai",
        "client": "codex-cli 0.148.0",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "low",
    }
    assert proposed["isolation"] == {
        "ephemeral": True,
        "sandbox": "workspace-write",
        "command_review": "automatic --approve-for-me",
        "ignore_user_config": True,
        "ignore_rules": True,
        "task_network": False,
        "max_concurrency": 4,
        "raw_root": (
            "D:\\tmp\\kokoroarc-m9-task18-campaign-20260820-approved4"
        ),
        "retained_root": (
            "tests/skills/evidence/complete-suite/approved4"
        ),
    }
    assert proposed["reruns_require_fresh_approval"] is True
    assert proposed["immutable_failures"] is True
    assert proposed["disclosed_inputs"]
    assert proposed["retained_outputs"]
    assert proposed["prohibited"]


def test_complete_suite_route_matrix_mentions_every_skill() -> None:
    document = _load(CASES_FILE)
    cases = document["cases"]
    routes = {case["route"] for case in cases}

    assert routes == {
        "none",
        "using-kokoroarc",
        "authoring-character-packs",
        "researching-characters",
        "testing-character-packs",
    }
