from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
from typing import Any

import pytest
import yaml

from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing import hard as hard_module
from kokoroarc.testing.hard import hard_report_is_current, run_hard_validation


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = SchemaRegistry(REPOSITORY_ROOT / "schemas" / "v1")
RIN_PACK = REPOSITORY_ROOT / "characters" / "original" / "rin-aster"
ORIGINAL_REQUEST = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "authoring" / "original-request.json"
)
EXPECTED_REPORT = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "pack-hard-validation"
    / "rin-report.json"
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes())


def copy_rin(tmp_path: Path) -> Path:
    target = tmp_path / "rin"
    shutil.copytree(RIN_PACK, target)
    return target


def finding_codes(report: dict[str, Any], check: str) -> list[str]:
    return [finding["code"] for finding in report["checks"][check]["findings"]]


def test_runs_real_rin_hard_gates_as_one_exact_canonical_report() -> None:
    request = load_json(ORIGINAL_REQUEST)
    expected = load_json(EXPECTED_REPORT)

    first = run_hard_validation(RIN_PACK, request, SCHEMAS)
    second = run_hard_validation(RIN_PACK, request, SCHEMAS)

    assert first == expected
    assert canonical_bytes(first) == canonical_bytes(expected)
    assert canonical_bytes(second) == canonical_bytes(first)
    assert all(check["passed"] for check in first["checks"].values())
    assert first["passed"] is True
    assert first["source_snapshot_stable"] is True
    assert first["deterministic"] is True
    assert "timestamp" not in canonical_bytes(first).decode("utf-8")
    SCHEMAS.validate("pack-hard-validation-report", first)
    assert hard_report_is_current(first, RIN_PACK, request, SCHEMAS) is True


def test_orchestrates_existing_compiler_render_validator_and_state_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"compile": 0, "plan": 0, "validate": 0, "state": 0}
    real_compile = hard_module.compile_pack
    real_plan = hard_module.build_render_plan
    real_validate = hard_module.validate_rendered_output
    real_apply = hard_module.apply_event

    def observed_compile(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls["compile"] += 1
        return real_compile(*args, **kwargs)

    def observed_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls["plan"] += 1
        return real_plan(*args, **kwargs)

    def observed_validate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls["validate"] += 1
        return real_validate(*args, **kwargs)

    def observed_apply(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls["state"] += 1
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(hard_module, "compile_pack", observed_compile)
    monkeypatch.setattr(hard_module, "build_render_plan", observed_plan)
    monkeypatch.setattr(hard_module, "validate_rendered_output", observed_validate)
    monkeypatch.setattr(hard_module, "apply_event", observed_apply)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["passed"] is True
    assert calls == {"compile": 2, "plan": 1, "validate": 1, "state": 3}


def test_changed_fixture_bytes_invalidate_report_reuse(tmp_path: Path) -> None:
    pack = copy_rin(tmp_path)
    request = load_json(ORIGINAL_REQUEST)
    report = run_hard_validation(pack, request, SCHEMAS)
    positive = pack / "tests" / "positive.yaml"
    positive.write_text(
        positive.read_text(encoding="utf-8") + "# reviewed again\n",
        encoding="utf-8",
    )

    replacement = run_hard_validation(pack, request, SCHEMAS)

    assert replacement["source_hash"] == report["source_hash"]
    assert replacement["corpus_hash"] != report["corpus_hash"]
    assert canonical_bytes(replacement) != canonical_bytes(report)
    assert hard_report_is_current(report, pack, request, SCHEMAS) is False
    assert hard_report_is_current(replacement, pack, request, SCHEMAS) is True


def test_comment_only_source_bytes_invalidate_report_reuse(tmp_path: Path) -> None:
    pack = copy_rin(tmp_path)
    request = load_json(ORIGINAL_REQUEST)
    report = run_hard_validation(pack, request, SCHEMAS)
    behavior = pack / "behavior.yaml"
    behavior.write_text(
        behavior.read_text(encoding="utf-8") + "# byte-only review note\n",
        encoding="utf-8",
    )

    replacement = run_hard_validation(pack, request, SCHEMAS)

    assert replacement["source_hash"] == report["source_hash"]
    assert replacement["corpus_hash"] == report["corpus_hash"]
    assert (
        replacement["check_input_hashes"]["source_tree_hash"]
        != report["check_input_hashes"]["source_tree_hash"]
    )
    assert hard_report_is_current(report, pack, request, SCHEMAS) is False
    assert hard_report_is_current(replacement, pack, request, SCHEMAS) is True


def test_identical_pack_bytes_have_location_independent_report_hashes(
    tmp_path: Path,
) -> None:
    first_pack = copy_rin(tmp_path / "first")
    second_pack = copy_rin(tmp_path / "second")
    request = load_json(ORIGINAL_REQUEST)

    first = run_hard_validation(first_pack, request, SCHEMAS)
    second = run_hard_validation(second_pack, request, SCHEMAS)

    assert first == second
    assert (
        first["check_input_hashes"]["source_tree_hash"]
        == second["check_input_hashes"]["source_tree_hash"]
    )


def test_request_context_change_invalidates_report_reuse() -> None:
    request = load_json(ORIGINAL_REQUEST)
    report = run_hard_validation(RIN_PACK, request, SCHEMAS)
    changed = deepcopy(request)
    changed["intended_use_cases"].append("release evaluation")

    replacement = run_hard_validation(RIN_PACK, changed, SCHEMAS)

    assert replacement["source_hash"] == report["source_hash"]
    assert replacement["compiled_hash"] == report["compiled_hash"]
    assert replacement["corpus_hash"] == report["corpus_hash"]
    assert (
        replacement["check_input_hashes"]["request_hash"]
        != report["check_input_hashes"]["request_hash"]
    )
    assert hard_report_is_current(report, RIN_PACK, changed, SCHEMAS) is False


def test_reports_cross_artifact_provenance_failures_without_guessing_mode() -> None:
    request = load_json(
        REPOSITORY_ROOT
        / "tests"
        / "fixtures"
        / "authoring"
        / "dossier-request.json"
    )

    report = run_hard_validation(RIN_PACK, request, SCHEMAS)

    assert report["mode"] == "dossier"
    assert report["visibility"] == "private"
    assert report["checks"]["provenance"]["passed"] is False
    assert "AUTHORING_DOSSIER_ORIGINAL_PROVENANCE_PROHIBITED" in finding_codes(
        report, "provenance"
    )
    assert report["passed"] is False
    SCHEMAS.validate("pack-hard-validation-report", report)


def test_reports_two_pass_compilation_nondeterminism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_compile = hard_module.compile_pack
    calls = 0

    def drifting_compile(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        compiled = real_compile(*args, **kwargs)
        if calls == 2:
            compiled["behavior"]["correction_style"] = "drifted output"
        return compiled

    monkeypatch.setattr(hard_module, "compile_pack", drifting_compile)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["compile"]["passed"] is False
    assert finding_codes(report, "compile") == ["PACK_COMPILE_NONDETERMINISTIC"]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_reports_missing_source_locale_coverage(tmp_path: Path) -> None:
    pack = copy_rin(tmp_path)
    expressions_path = pack / "expressions.yaml"
    expressions = yaml.safe_load(expressions_path.read_text(encoding="utf-8"))
    expression_name = sorted(expressions)[0]
    del expressions[expression_name]["ja-JP"]
    expressions_path.write_text(
        yaml.safe_dump(expressions, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    report = run_hard_validation(pack, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["locale_coverage"]["passed"] is False
    assert "AUTHORING_LOCALE_MISSING" in finding_codes(report, "locale_coverage")
    assert report["passed"] is False


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("intent", "unknown_intent", "PACK_TEST_INTENT_MISSING"),
        ("semantic_key", "unknown_key", "PACK_TEST_SEMANTIC_KEY_UNKNOWN"),
        ("expected_locales", ["en-US"], "PACK_TEST_LOCALE_COVERAGE_MISSING"),
    ],
)
def test_reports_multilingual_fixture_coverage_gaps(
    tmp_path: Path, field: str, value: Any, expected_code: str
) -> None:
    pack = copy_rin(tmp_path)
    path = pack / "tests" / "multilingual.yaml"
    fixture = yaml.safe_load(path.read_text(encoding="utf-8"))
    fixture[field] = value
    path.write_text(
        yaml.safe_dump(fixture, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    report = run_hard_validation(pack, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["locale_coverage"]["passed"] is False
    assert expected_code in finding_codes(report, "locale_coverage")


def test_reports_protected_span_and_warning_pipeline_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_plan = hard_module.build_render_plan

    def incomplete_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
        plan = real_plan(*args, **kwargs)
        plan["protected_spans"] = plan["protected_spans"][:-1]
        plan["segments"] = [
            segment for segment in plan["segments"] if segment["channel"] != "warnings"
        ]
        return plan

    monkeypatch.setattr(hard_module, "build_render_plan", incomplete_plan)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["protected_content"]["passed"] is False
    assert finding_codes(report, "protected_content") == [
        "PACK_PROTECTED_SPAN_MISMATCH",
        "PACK_REQUIRED_WARNING_MISSING",
        "PACK_RUNTIME_VALIDATION_FAILED",
    ]


def test_reports_state_replay_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    real_apply = hard_module.apply_event
    calls = 0

    def drifting_apply(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        result = real_apply(*args, **kwargs)
        if calls == 2:
            result["dimensions"]["trust"] += 0.25
        return result

    monkeypatch.setattr(hard_module, "apply_event", drifting_apply)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["state_replay"]["passed"] is False
    assert finding_codes(report, "state_replay") == ["PACK_STATE_REPLAY_DRIFT"]
    assert report["deterministic"] is False


def test_reports_source_mutation_during_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_load = hard_module.load_source_pack
    calls = 0

    def changed_second_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        source = real_load(*args, **kwargs)
        if calls == 2:
            source["behavior"]["correction_style"] += " changed"
        return source

    monkeypatch.setattr(hard_module, "load_source_pack", changed_second_load)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["source_snapshot_stable"] is False
    assert report["passed"] is False
    assert hard_report_is_current(report, RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS) is False


def test_reports_comment_only_filesystem_mutation_during_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = copy_rin(tmp_path)
    target = pack / "behavior.yaml"
    real_plan = hard_module.build_render_plan

    def mutate_after_planning(*args: Any, **kwargs: Any) -> dict[str, Any]:
        plan = real_plan(*args, **kwargs)
        target.write_text(
            target.read_text(encoding="utf-8") + "# changed during run\n",
            encoding="utf-8",
        )
        return plan

    monkeypatch.setattr(hard_module, "build_render_plan", mutate_after_planning)

    report = run_hard_validation(pack, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["source_snapshot_stable"] is False
    assert report["passed"] is False


def test_inputs_and_returned_report_are_not_mutated_or_aliased() -> None:
    request = load_json(ORIGINAL_REQUEST)
    original = deepcopy(request)
    report = run_hard_validation(RIN_PACK, request, SCHEMAS)

    report["checks"]["source_schema"]["passed"] = False
    replacement = run_hard_validation(RIN_PACK, request, SCHEMAS)

    assert request == original
    assert replacement["checks"]["source_schema"]["passed"] is True
