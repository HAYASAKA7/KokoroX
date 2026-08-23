from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

from jsonschema import Draft202012Validator
import yaml


SKILLS_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SKILLS_ROOT.parents[1]
sys.path.insert(0, str(SKILLS_ROOT))

import run_complete_suite_campaign as runner  # noqa: E402


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
PINNED_GIT = r"C:\Program Files\Git\mingw64\bin\git.exe"
PRE_TRUST_GIT_PREFIX = (
    "--no-pager",
    "--no-optional-locks",
    "--no-replace-objects",
    "--literal-pathspecs",
    "-c",
    "core.longpaths=true",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.eol=lf",
    "-c",
    "core.safecrlf=true",
    "-c",
    "core.symlinks=false",
    "-c",
    "core.protectNTFS=true",
    "-c",
    "core.protectHFS=true",
    "-c",
    "core.hooksPath=NUL",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.useReplaceRefs=false",
    "-c",
    "core.attributesFile=NUL",
    "-c",
    "core.excludesFile=/dev/null",
    "-c",
    "commit.gpgSign=false",
    "-c",
    "tag.gpgSign=false",
    "-c",
    "credential.helper=",
    "-c",
    "credential.interactive=never",
    "-c",
    "maintenance.auto=false",
    "-c",
    "gc.auto=0",
    "-c",
    "submodule.recurse=false",
    "-c",
    "fetch.recurseSubmodules=false",
    "-c",
    "protocol.allow=never",
    "-c",
    "protocol.file.allow=never",
    "-c",
    "diff.external=",
    "-c",
    "core.pager=cat",
)
PLANNED_CAMPAIGN6_LF_PATHS = (
    "tests/skills/test_complete_suite_command_plan.py",
    "tests/skills/complete_suite_command_plan.py",
    "tests/skills/complete_suite_command_plan_decoder.ps1",
    "tests/skills/complete-suite-command-plan.schema.json",
    "tests/skills/fixtures/complete-suite-command-plan/direct-cli.json",
    "tests/skills/fixtures/complete-suite-command-plan/call-operator-cli.json",
    "tests/skills/fixtures/complete-suite-command-plan/compound-cli.json",
    "tests/skills/fixtures/complete-suite-command-plan/read-pipeline.json",
    "tests/skills/complete_suite_command_policy.py",
    "tests/skills/complete_suite_file_change_policy.py",
    "tests/skills/complete-suite-file-change-ledger.schema.json",
    "tests/skills/test_complete_suite_command_policy.py",
    "tests/skills/test_complete_suite_file_change_policy.py",
    "tests/skills/fixtures/complete-suite-file-change/original-authoring.jsonl",
    "tests/skills/fixtures/complete-suite-file-change/workspace-override.jsonl",
    "tests/skills/complete_suite_cli_binding.py",
    "tests/skills/test_complete_suite_cli_binding.py",
    "tests/skills/complete_suite_shell_preflight.py",
    "tests/skills/complete_suite_client_preflight_server.py",
    "tests/skills/complete_suite_control_plane.ps1",
    "tests/skills/complete_suite_release_python_bootstrap.py",
    "tests/skills/complete_suite_artifact_launcher.ps1",
    "tests/skills/complete_suite_artifact_writer.py",
    "tests/skills/fixtures/complete-suite-client-evaluation-templates.json",
    "tests/skills/test_complete_suite_shell_preflight.py",
    "tests/skills/test_complete_suite_artifact_writer.py",
    "tests/skills/complete_suite_windows_test_ops.py",
    "tests/integration/test_standalone_cli_workflow.py",
    "tests/security/test_authoring_security.py",
    "tests/security/test_persistence_security.py",
    "tests/security/test_research_security.py",
    "docs/superpowers/plans/2026-08-14-kokoroarc-completion.md",
)
EXISTING_CAMPAIGN6_LF_PATHS = (
    "docs/superpowers/specs/2026-08-21-kokoroarc-complete-suite-campaign-6-design.md",
    "docs/superpowers/plans/2026-08-21-kokoroarc-complete-suite-campaign-6.md",
)
REQUIRED_CURRENT_CAMPAIGN6_LF_PATHS = (
    "tests/skills/test_complete_suite_command_plan.py",
    "tests/integration/test_standalone_cli_workflow.py",
    "tests/security/test_authoring_security.py",
    "tests/security/test_persistence_security.py",
    "tests/security/test_research_security.py",
    "docs/superpowers/plans/2026-08-14-kokoroarc-completion.md",
    *EXISTING_CAMPAIGN6_LF_PATHS,
)


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
    assert document["campaign_id"] == "2026-08-20-proposed5"
    assert document["status"] == "draft_not_approved"
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
            "D:\\tmp\\kokoroarc-proposed5-wheelhouse-canonical-lf-01"
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

    assert document["user_approval"] is None

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
            "D:\\tmp\\kokoroarc-m9-task18-campaign-20260820-approved5"
        ),
        "retained_root": (
            "tests/skills/evidence/complete-suite/approved5"
        ),
    }
    assert proposed["reruns_require_fresh_approval"] is True
    assert proposed["immutable_failures"] is True
    assert proposed["disclosed_inputs"]
    assert proposed["retained_outputs"]
    assert proposed["prohibited"]


def test_approval_bound_checkout_policy_is_explicit_and_current_bytes_are_lf(
    monkeypatch,
) -> None:
    approval_bound_paths = runner.approval_bound_paths()
    assert len(approval_bound_paths) == 141
    assert approval_bound_paths == tuple(sorted(set(approval_bound_paths)))
    assert len(PLANNED_CAMPAIGN6_LF_PATHS) == 32
    assert len(set(PLANNED_CAMPAIGN6_LF_PATHS)) == 32

    calls: list[tuple[list[str], dict[str, object]]] = []
    real_run = subprocess.run

    def recorded_run(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recorded_run)
    expected_argv = [
        PINNED_GIT,
        *PRE_TRUST_GIT_PREFIX,
        "check-attr",
        "text",
        "eol",
        "--",
        *PLANNED_CAMPAIGN6_LF_PATHS,
    ]
    result = subprocess.run(
        expected_argv,
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert result.returncode == 0
    assert result.stderr == b""
    assert calls == [
        (
            expected_argv,
            {
                "cwd": REPOSITORY_ROOT,
                "check": False,
                "capture_output": True,
                "text": False,
            },
        )
    ]
    assert "input" not in calls[0][1]
    attributes: dict[str, dict[str, str]] = {}
    for line in result.stdout.decode("utf-8", errors="strict").splitlines():
        relative, attribute, value = line.split(": ", maxsplit=2)
        attributes.setdefault(relative, {})[attribute] = value

    assert set(attributes) == set(PLANNED_CAMPAIGN6_LF_PATHS)
    policy_failures = {
        relative: attributes[relative]
        for relative in PLANNED_CAMPAIGN6_LF_PATHS
        if attributes[relative] != {"text": "set", "eol": "lf"}
    }
    assert policy_failures == {}
    current_paths = dict.fromkeys(
        (
            *approval_bound_paths,
            *PLANNED_CAMPAIGN6_LF_PATHS,
            *EXISTING_CAMPAIGN6_LF_PATHS,
        )
    )
    for relative in current_paths:
        path = REPOSITORY_ROOT.joinpath(*relative.split("/"))
        if (
            relative in approval_bound_paths
            or relative in REQUIRED_CURRENT_CAMPAIGN6_LF_PATHS
        ):
            raw = runner._read_bytes(
                path,
                max_bytes=runner.preparation.MAX_FILE_BYTES,
            )
        elif path.exists() or path.is_symlink():
            raw = runner._read_bytes(
                path,
                max_bytes=runner.preparation.MAX_FILE_BYTES,
            )
        else:
            continue
        assert b"\r\n" not in raw, relative
        assert b"\r" not in raw, relative
        assert b"\x00" not in raw, relative


def test_frozen_inputs_keep_lf_checkout_attributes() -> None:
    relative_paths = runner.approval_bound_paths()
    expected_argv = [
        PINNED_GIT,
        *PRE_TRUST_GIT_PREFIX,
        "check-attr",
        "text",
        "eol",
        "--",
        *relative_paths,
    ]
    result = subprocess.run(
        expected_argv,
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert result.returncode == 0
    assert result.stderr == b""
    attributes: dict[str, dict[str, str]] = {}
    for line in result.stdout.decode("utf-8", errors="strict").splitlines():
        relative, attribute, value = line.split(": ", maxsplit=2)
        attributes.setdefault(relative, {})[attribute] = value
    assert set(attributes) == set(relative_paths)
    for relative in relative_paths:
        assert attributes[relative] == {"text": "set", "eol": "lf"}


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
