from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any

import pytest
import yaml

from kokoroarc.errors import KokoroError
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


def test_currentness_validation_cannot_rewrite_caller_report() -> None:
    request = load_json(ORIGINAL_REQUEST)
    current = run_hard_validation(RIN_PACK, request, SCHEMAS)
    stale = deepcopy(current)
    stale["source_hash"] = "0" * 64
    original_stale = deepcopy(stale)
    replaced = False

    class MutatingSchemaProxy:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal replaced
            SCHEMAS.validate(name, instance)
            if name == "pack-hard-validation-report" and not replaced:
                instance.clear()
                instance.update(deepcopy(current))
                replaced = True

    assert (
        hard_report_is_current(
            stale,
            RIN_PACK,
            request,
            MutatingSchemaProxy(),  # type: ignore[arg-type]
        )
        is False
    )
    assert stale == original_stale


def test_currentness_rejects_caller_report_mutated_through_callback() -> None:
    request = load_json(ORIGINAL_REQUEST)
    report = run_hard_validation(RIN_PACK, request, SCHEMAS)
    original_report = deepcopy(report)
    mutated = False

    class MutatingSchemaProxy:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal mutated
            SCHEMAS.validate(name, instance)
            if name == "pack-hard-validation-report" and not mutated:
                report["source_hash"] = "0" * 64
                mutated = True

    assert (
        hard_report_is_current(
            report,
            RIN_PACK,
            request,
            MutatingSchemaProxy(),  # type: ignore[arg-type]
        )
        is False
    )
    assert report != original_report


def test_currentness_cannot_rebase_pack_during_report_schema_validation(
    tmp_path: Path,
) -> None:
    pack = copy_rin(tmp_path)
    request = load_json(ORIGINAL_REQUEST)
    behavior = pack / "behavior.yaml"
    original_bytes = behavior.read_bytes()
    changed_bytes = original_bytes + b"\n# changed before currentness run\n"
    behavior.write_bytes(changed_bytes)
    changed_report = run_hard_validation(pack, request, SCHEMAS)
    behavior.write_bytes(original_bytes)
    rebased = False

    class MutatingSchemaProxy:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal rebased
            SCHEMAS.validate(name, instance)
            if name == "pack-hard-validation-report" and not rebased:
                behavior.write_bytes(changed_bytes)
                rebased = True

    assert (
        hard_report_is_current(
            changed_report,
            pack,
            request,
            MutatingSchemaProxy(),  # type: ignore[arg-type]
        )
        is False
    )


def test_rejects_provenance_validator_request_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = load_json(ORIGINAL_REQUEST)
    original = deepcopy(request)
    real_validate = hard_module.validate_authoring_pack

    def mutating_validate(
        request_input: dict[str, Any],
        source_input: dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = real_validate(request_input, source_input, *args, **kwargs)
        request_input["mode"] = "dossier"
        return result

    monkeypatch.setattr(
        hard_module, "validate_authoring_pack", mutating_validate
    )

    report = run_hard_validation(RIN_PACK, request, SCHEMAS)

    assert request == original
    assert report["mode"] == "original"
    assert report["checks"]["provenance"]["passed"] is False
    assert "PACK_PROVENANCE_INPUT_MUTATION" in finding_codes(
        report, "provenance"
    )
    assert report["passed"] is False


def test_rejects_provenance_validator_source_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_validate = hard_module.validate_authoring_pack

    def mutating_validate(
        request_input: dict[str, Any],
        source_input: dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = real_validate(request_input, source_input, *args, **kwargs)
        source_input["character_id"] = "rin-mutant"
        return result

    monkeypatch.setattr(
        hard_module, "validate_authoring_pack", mutating_validate
    )

    report = run_hard_validation(
        RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS
    )

    assert report["character_id"] == "rin-aster"
    assert report["source_artifact_id"] == "original/rin-aster/source"
    assert report["checks"]["provenance"]["passed"] is False
    assert "PACK_PROVENANCE_INPUT_MUTATION" in finding_codes(
        report, "provenance"
    )
    assert report["passed"] is False


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


def test_reports_two_pass_compilation_nondeterminism_through_shared_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_compile = hard_module.compile_pack
    shared: dict[str, Any] | None = None
    calls = 0

    def aliased_compile(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls, shared
        calls += 1
        if shared is None:
            shared = real_compile(*args, **kwargs)
        else:
            shared["behavior"]["correction_style"] = "drifted shared output"
        return shared

    monkeypatch.setattr(hard_module, "compile_pack", aliased_compile)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["compile"]["passed"] is False
    assert finding_codes(report, "compile") == [
        "PACK_COMPILE_NONDETERMINISTIC",
        "PACK_COMPILE_OUTPUT_MUTATION",
    ]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_reports_compiler_input_mutation_even_when_outputs_are_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_compile = hard_module.compile_pack
    shared: dict[str, Any] | None = None

    def mutating_compile(
        source: dict[str, Any], *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        nonlocal shared
        if shared is None:
            shared = real_compile(deepcopy(source), *args, **kwargs)
        source["behavior"]["correction_style"] = "mutated compiler input"
        return shared

    monkeypatch.setattr(hard_module, "compile_pack", mutating_compile)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["compile"]["passed"] is False
    assert finding_codes(report, "compile") == ["PACK_COMPILE_INPUT_MUTATION"]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_reports_delayed_first_compiler_input_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_compile = hard_module.compile_pack
    first_input: dict[str, Any] | None = None

    def delayed_input_mutation(
        source: dict[str, Any], *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        nonlocal first_input
        if first_input is None:
            first_input = source
        else:
            first_input["behavior"]["correction_style"] = "delayed mutation"
        return real_compile(source, *args, **kwargs)

    monkeypatch.setattr(hard_module, "compile_pack", delayed_input_mutation)

    report = run_hard_validation(
        RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS
    )

    assert report["checks"]["compile"]["passed"] is False
    assert finding_codes(report, "compile") == ["PACK_COMPILE_INPUT_MUTATION"]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_reports_delayed_first_compiler_output_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_compile = hard_module.compile_pack
    first_output: dict[str, Any] | None = None

    def delayed_output_mutation(
        source: dict[str, Any], *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        nonlocal first_output
        result = real_compile(source, *args, **kwargs)
        if first_output is None:
            first_output = result
        else:
            first_output["artifact_id"] = "original/rin-aster/compiled-mutant"
        return result

    monkeypatch.setattr(hard_module, "compile_pack", delayed_output_mutation)

    report = run_hard_validation(
        RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS
    )

    assert report["compiled_artifact_id"] == "original/rin-aster/compiled"
    assert report["checks"]["compile"]["passed"] is False
    assert finding_codes(report, "compile") == [
        "PACK_COMPILE_OUTPUT_MUTATION"
    ]
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


def test_reports_runtime_validator_plan_input_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_validate = hard_module.validate_rendered_output

    def mutating_validate(
        rendered: dict[str, Any],
        semantic: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        result = real_validate(rendered, semantic, plan)
        plan["artifact_id"] = "plan/pack-hard-validation-mutant"
        return result

    monkeypatch.setattr(
        hard_module, "validate_rendered_output", mutating_validate
    )

    report = run_hard_validation(
        RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS
    )

    assert report["checks"]["protected_content"]["passed"] is False
    assert finding_codes(report, "protected_content") == [
        "PACK_PROTECTED_INPUT_MUTATION"
    ]
    assert report["passed"] is False


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


def test_reports_state_replay_drift_through_shared_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_apply = hard_module.apply_event
    shared: dict[str, Any] | None = None
    calls = 0

    def aliased_apply(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls, shared
        calls += 1
        if shared is None:
            shared = real_apply(*args, **kwargs)
        elif calls == 2:
            shared["dimensions"]["trust"] += 0.25
        return shared

    monkeypatch.setattr(hard_module, "apply_event", aliased_apply)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["state_replay"]["passed"] is False
    assert finding_codes(report, "state_replay") == [
        "PACK_STATE_INPUT_MUTATION",
        "PACK_STATE_REPLAY_DRIFT",
    ]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_reports_deterministic_but_noop_state_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def noop_apply(
        state: dict[str, Any], event: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return deepcopy(state)

    monkeypatch.setattr(hard_module, "apply_event", noop_apply)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["state_replay"]["passed"] is False
    assert finding_codes(report, "state_replay") == [
        "PACK_STATE_TRANSITION_INVALID"
    ]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_reports_state_engine_input_mutation_even_when_outputs_are_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_apply = hard_module.apply_event

    def in_place_apply(
        state: dict[str, Any], event: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        result = real_apply(state, event, **kwargs)
        state.clear()
        state.update(result)
        return state

    monkeypatch.setattr(hard_module, "apply_event", in_place_apply)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["state_replay"]["passed"] is False
    assert finding_codes(report, "state_replay") == ["PACK_STATE_INPUT_MUTATION"]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_reports_idempotent_probe_input_mutation_with_detached_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_apply = hard_module.apply_event
    calls = 0

    def mutate_idempotent_input(
        state: dict[str, Any], event: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        result = real_apply(state, event, **kwargs)
        if calls == 3:
            state["dimensions"]["trust"] += 0.25
        return result

    monkeypatch.setattr(hard_module, "apply_event", mutate_idempotent_input)

    report = run_hard_validation(RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS)

    assert report["checks"]["state_replay"]["passed"] is False
    assert finding_codes(report, "state_replay") == ["PACK_STATE_INPUT_MUTATION"]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_reports_replay_output_mutation_during_idempotent_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_apply = hard_module.apply_event
    replay_output: dict[str, Any] | None = None
    calls = 0

    def mutate_replay_output(
        state: dict[str, Any], event: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        nonlocal calls, replay_output
        calls += 1
        if calls == 3 and replay_output is not None:
            replay_output["dimensions"]["trust"] += 0.25
        result = real_apply(state, event, **kwargs)
        if calls == 2:
            replay_output = result
        return result

    monkeypatch.setattr(hard_module, "apply_event", mutate_replay_output)

    report = run_hard_validation(
        RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS
    )

    assert report["checks"]["state_replay"]["passed"] is False
    assert finding_codes(report, "state_replay") == [
        "PACK_STATE_OUTPUT_MUTATION"
    ]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_finding_limit_retains_release_blocker_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_validate = hard_module.validate_authoring_pack

    def crowded_validate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = real_validate(*args, **kwargs)
        result["advisory_findings"] = [
            {
                "code": f"AAA_ADVISORY_{index:03d}",
                "path": ["evidence", index],
                "message": f"Advisory finding {index}.",
            }
            for index in range(256)
        ]
        result["hard_failures"] = [
            {
                "code": "ZZZ_RELEASE_BLOCKER",
                "path": ["evidence"],
                "message": "Release-blocking finding.",
            }
        ]
        result["valid"] = False
        return result

    monkeypatch.setattr(hard_module, "validate_authoring_pack", crowded_validate)

    report = run_hard_validation(
        RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS
    )
    findings = report["checks"]["provenance"]["findings"]

    assert len(findings) == 256
    assert any(item["code"] == "ZZZ_RELEASE_BLOCKER" for item in findings)
    assert report["checks"]["provenance"]["passed"] is False
    assert report["passed"] is False


def test_raw_hash_inputs_have_checkout_stable_lf_policy() -> None:
    attributes = (REPOSITORY_ROOT / ".gitattributes").read_text(
        encoding="utf-8"
    ).splitlines()

    assert "characters/** text eol=lf" in attributes
    assert "tests/fixtures/** text eol=lf" in attributes


def test_reports_source_mutation_during_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_load = hard_module.assemble_source_pack_from_contents
    calls = 0

    def changed_second_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        source = real_load(*args, **kwargs)
        if calls == 2:
            source["behavior"]["correction_style"] += " changed"
        return source

    monkeypatch.setattr(
        hard_module, "assemble_source_pack_from_contents", changed_second_load
    )

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


def test_rejects_provenance_input_mutated_during_later_compile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_validate = hard_module.validate_authoring_pack
    real_compile = hard_module.compile_pack
    retained_request: dict[str, Any] | None = None

    def retaining_validate(
        request_input: dict[str, Any],
        source_input: dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        nonlocal retained_request
        retained_request = request_input
        return real_validate(request_input, source_input, *args, **kwargs)

    def late_mutating_compile(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert retained_request is not None
        retained_request["mode"] = "dossier"
        return real_compile(*args, **kwargs)

    monkeypatch.setattr(
        hard_module, "validate_authoring_pack", retaining_validate
    )
    monkeypatch.setattr(hard_module, "compile_pack", late_mutating_compile)

    report = run_hard_validation(
        RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS
    )

    assert report["mode"] == "original"
    assert report["checks"]["provenance"]["passed"] is False
    assert finding_codes(report, "provenance") == [
        "PACK_PROVENANCE_INPUT_MUTATION"
    ]
    assert report["passed"] is False


def test_rejects_compiler_output_mutated_during_protected_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_compile = hard_module.compile_pack
    real_plan = hard_module.build_render_plan
    retained_output: dict[str, Any] | None = None
    compile_calls = 0

    def retaining_compile(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal compile_calls, retained_output
        compile_calls += 1
        result = real_compile(*args, **kwargs)
        if compile_calls == 1:
            retained_output = result
        return result

    def late_mutating_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert retained_output is not None
        retained_output["artifact_id"] = "original/rin-aster/compiled-mutant"
        return real_plan(*args, **kwargs)

    monkeypatch.setattr(hard_module, "compile_pack", retaining_compile)
    monkeypatch.setattr(hard_module, "build_render_plan", late_mutating_plan)

    report = run_hard_validation(
        RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS
    )

    assert report["compiled_artifact_id"] == "original/rin-aster/compiled"
    assert report["checks"]["compile"]["passed"] is False
    assert finding_codes(report, "compile") == [
        "PACK_COMPILE_OUTPUT_MUTATION"
    ]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_rejects_protected_output_mutated_during_state_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_validate = hard_module.validate_rendered_output
    real_apply = hard_module.apply_event
    retained_validation: dict[str, Any] | None = None

    def retaining_validation(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal retained_validation
        retained_validation = real_validate(*args, **kwargs)
        return retained_validation

    def late_mutating_apply(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert retained_validation is not None
        retained_validation["valid"] = False
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(
        hard_module, "validate_rendered_output", retaining_validation
    )
    monkeypatch.setattr(hard_module, "apply_event", late_mutating_apply)

    report = run_hard_validation(
        RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS
    )

    assert report["checks"]["protected_content"]["passed"] is False
    assert finding_codes(report, "protected_content") == [
        "PACK_PROTECTED_OUTPUT_MUTATION"
    ]
    assert report["passed"] is False


def test_rejects_state_output_mutated_during_final_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_apply = hard_module.apply_event
    real_snapshot = hard_module._snapshot_pack
    retained_replay: dict[str, Any] | None = None
    apply_calls = 0
    snapshot_calls = 0

    def retaining_apply(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal apply_calls, retained_replay
        apply_calls += 1
        result = real_apply(*args, **kwargs)
        if apply_calls == 2:
            retained_replay = result
        return result

    def late_mutating_snapshot(*args: Any, **kwargs: Any) -> Any:
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 2:
            assert retained_replay is not None
            retained_replay["dimensions"]["trust"] += 0.25
        return real_snapshot(*args, **kwargs)

    monkeypatch.setattr(hard_module, "apply_event", retaining_apply)
    monkeypatch.setattr(hard_module, "_snapshot_pack", late_mutating_snapshot)

    report = run_hard_validation(
        RIN_PACK, load_json(ORIGINAL_REQUEST), SCHEMAS
    )

    assert report["checks"]["state_replay"]["passed"] is False
    assert finding_codes(report, "state_replay") == [
        "PACK_STATE_OUTPUT_MUTATION"
    ]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_rejects_state_output_mutated_during_final_report_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_apply = hard_module.apply_event
    retained_replay: dict[str, Any] | None = None
    apply_calls = 0

    def retaining_apply(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal apply_calls, retained_replay
        apply_calls += 1
        result = real_apply(*args, **kwargs)
        if apply_calls == 2:
            retained_replay = result
        return result

    class MutatingSchemaProxy:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-hard-validation-report" and retained_replay:
                retained_replay["dimensions"]["trust"] += 0.25

    monkeypatch.setattr(hard_module, "apply_event", retaining_apply)

    report = run_hard_validation(
        RIN_PACK,
        load_json(ORIGINAL_REQUEST),
        MutatingSchemaProxy(),  # type: ignore[arg-type]
    )

    assert report["checks"]["state_replay"]["passed"] is False
    assert finding_codes(report, "state_replay") == [
        "PACK_STATE_OUTPUT_MUTATION"
    ]
    assert report["deterministic"] is False
    assert report["passed"] is False


def test_rejects_pack_bytes_mutated_during_final_report_validation(
    tmp_path: Path,
) -> None:
    pack = copy_rin(tmp_path)
    behavior = pack / "behavior.yaml"
    schema_calls = 0

    class MutatingSchemaProxy:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal schema_calls
            SCHEMAS.validate(name, instance)
            if name == "pack-hard-validation-report":
                schema_calls += 1
                if schema_calls == 2:
                    behavior.write_bytes(
                        behavior.read_bytes() + b"\n# changed during final validation\n"
                    )

    request = load_json(ORIGINAL_REQUEST)
    report = run_hard_validation(
        pack,
        request,
        MutatingSchemaProxy(),  # type: ignore[arg-type]
    )

    assert schema_calls >= 2
    assert report["source_snapshot_stable"] is False
    assert report["passed"] is False
    assert hard_report_is_current(report, pack, request, SCHEMAS) is False


def test_request_schema_validation_cannot_mutate_retained_request_snapshot() -> None:
    class MutatingSchemaProxy:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "character-build-request":
                instance["mode"] = "dossier"

    report = run_hard_validation(
        RIN_PACK,
        load_json(ORIGINAL_REQUEST),
        MutatingSchemaProxy(),  # type: ignore[arg-type]
    )

    assert report["mode"] == "original"
    assert report["passed"] is True


def test_rejects_pack_mutated_during_request_schema_validation(
    tmp_path: Path,
) -> None:
    pack = copy_rin(tmp_path)
    behavior = pack / "behavior.yaml"

    class MutatingSchemaProxy:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "character-build-request":
                behavior.write_bytes(
                    behavior.read_bytes() + b"\n# changed during request validation\n"
                )

    report = run_hard_validation(
        pack,
        load_json(ORIGINAL_REQUEST),
        MutatingSchemaProxy(),  # type: ignore[arg-type]
    )

    assert report["source_snapshot_stable"] is False
    assert report["passed"] is False


def test_rejects_research_bundle_mutated_during_request_schema_validation() -> None:
    request = load_json(ORIGINAL_REQUEST)
    research_bundle = {"artifact_id": "research/example/before"}
    original_bundle = deepcopy(research_bundle)
    expected_provenance_hash = sha256(
        canonical_bytes(
            {"request": request, "research_bundle": original_bundle}
        )
    ).hexdigest()

    class MutatingSchemaProxy:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "character-build-request":
                research_bundle["artifact_id"] = "research/example/after"

    report = run_hard_validation(
        RIN_PACK,
        request,
        MutatingSchemaProxy(),  # type: ignore[arg-type]
        research_bundle=research_bundle,
    )

    assert report["check_input_hashes"]["provenance_hash"] == (
        expected_provenance_hash
    )
    assert report["source_snapshot_stable"] is False
    assert report["passed"] is False


def test_identity_probe_does_not_mask_registry_operational_errors() -> None:
    class FailingSchemaProxy:
        def validate(self, name: str, instance: Any) -> None:
            if name == "pack-hard-validation-report":
                raise KokoroError("SCHEMA_NOT_FOUND", "Registry schema is unavailable.")
            SCHEMAS.validate(name, instance)

    with pytest.raises(KokoroError) as raised:
        run_hard_validation(
            RIN_PACK,
            load_json(ORIGINAL_REQUEST),
            FailingSchemaProxy(),  # type: ignore[arg-type]
        )

    assert raised.value.code == "SCHEMA_NOT_FOUND"
    assert raised.value.message == "Registry schema is unavailable."
