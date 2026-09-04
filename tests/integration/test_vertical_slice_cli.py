from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from kokoroarc import __version__
from kokoroarc import cli as cli_module
from kokoroarc.config import Settings
from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RIN_PACK = REPOSITORY_ROOT / "characters" / "original" / "rin-aster"


def run_cli(
    data_dir: Path,
    *args: str,
    expected_returncode: int = 0,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["KOKOROX_DATA_DIR"] = str(data_dir)
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPOSITORY_ROOT,
        timeout=30,
    )
    assert completed.returncode == expected_returncode, completed.stderr
    assert completed.stderr == ""
    return json.loads(completed.stdout)


def test_vertical_slice(tmp_path: Path) -> None:
    compiled = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    session = run_cli(
        tmp_path,
        "session",
        "start",
        "--character",
        compiled["path"],
        "--session",
        "s1",
    )
    context = run_cli(
        tmp_path,
        "runtime",
        "context",
        "--session",
        "s1",
        "--locale",
        "zh-CN",
        "--scenario",
        "debugging",
    )

    assert compiled["ok"] is True
    assert session["session"]["active"] is True
    assert context["context"]["character_id"] == "rin-aster"
    assert Path(compiled["path"]).resolve().is_relative_to(tmp_path.resolve())


def write_json(path: Path, value: Any) -> Path:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def semantic_artifact() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "semantic/turn-1",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "scenario": "debugging",
        "conclusion": "The cause is clear.",
        "explanation": ["The read path is not protected."],
        "recommendations": ["Add a concurrent regression test."],
        "warnings": ["Do not trust repeated runs."],
        "immutable_spans": ["go test -race ./..."],
        "format_constraints": ["preserve_code_blocks"],
    }


def interaction_event(event_id: str, revision: int) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": f"event/{event_id}",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "event_id": event_id,
        "turn_id": f"turn-{revision + 1}",
        "origin": "verified_task_outcome",
        "novelty_key": f"novelty-{event_id}",
        "expected_state_revision": revision,
        "evaluator_version": "interaction-v1",
        "evidence": {"kind": "test_result", "reference": "pytest passed"},
        "confidence": 1.0,
        "effects": {"trust": 3.0},
    }


def compiled_session(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    compiled = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    session = run_cli(
        tmp_path,
        "session",
        "start",
        "--character",
        compiled["path"],
        "--session",
        "s1",
    )
    return compiled, session


def make_hardlink(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        pytest.skip("hardlink creation is unavailable")


def test_all_command_families_and_state_lifecycle(tmp_path: Path) -> None:
    validated = run_cli(tmp_path, "pack", "validate", str(RIN_PACK))
    first = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    second = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    assert validated["character_id"] == "rin-aster"
    assert first["path"] == second["path"]

    started = run_cli(
        tmp_path,
        "session",
        "start",
        "--character",
        first["path"],
        "--session",
        "s1",
    )
    shown = run_cli(tmp_path, "session", "show", "--session", "s1")
    assert shown["session"] == started["session"]

    policy_input = write_json(
        tmp_path / "policy-input.json",
        {"primary_language": "zh-CN", "mode": "mixed"},
    )
    policy_result = run_cli(
        tmp_path, "policy", "compile", "--input", str(policy_input)
    )
    assert policy_result["policy"]["artifact_id"] == "policy/compiled"

    semantic_path = write_json(tmp_path / "semantic.json", semantic_artifact())
    policy_path = write_json(tmp_path / "policy.json", policy_result["policy"])
    plan_result = run_cli(
        tmp_path,
        "runtime",
        "plan",
        "--semantic",
        str(semantic_path),
        "--policy",
        str(policy_path),
        "--expression-intent",
        "restrained_diagnosis",
    )
    plan = plan_result["plan"]
    plan_path = write_json(tmp_path / "plan.json", plan)
    rendered_path = write_json(
        tmp_path / "rendered.json",
        {
            "text": "The cause is clear. go test -race ./...",
            "segments": [
                {
                    key: value
                    for key, value in segment.items()
                    if key != "expression_intent"
                }
                for segment in plan["segments"]
            ],
            "switch_count": 0,
        },
    )
    validation = run_cli(
        tmp_path,
        "runtime",
        "validate",
        "--semantic",
        str(semantic_path),
        "--plan",
        str(plan_path),
        "--rendered",
        str(rendered_path),
    )
    assert validation["validation"]["schema_version"] == "1.0"

    event_path = write_json(tmp_path / "event.json", interaction_event("e1", 0))
    preview = run_cli(
        tmp_path, "state", "preview", "--session", "s1", "--event", str(event_path)
    )
    unchanged = run_cli(tmp_path, "session", "show", "--session", "s1")
    assert preview["state"]["revision"] == 1
    assert unchanged["session"]["state_revision"] == 0

    applied = run_cli(
        tmp_path, "state", "apply", "--session", "s1", "--event", str(event_path)
    )
    duplicate_preview = run_cli(
        tmp_path, "state", "preview", "--session", "s1", "--event", str(event_path)
    )
    assert applied["state"]["revision"] == 1
    assert duplicate_preview["state"] == applied["state"]

    stale_path = write_json(tmp_path / "stale.json", interaction_event("e2", 0))
    conflict = run_cli(
        tmp_path,
        "state",
        "preview",
        "--session",
        "s1",
        "--event",
        str(stale_path),
        expected_returncode=2,
    )
    assert conflict["error"]["code"] == "STATE_REVISION_CONFLICT"
    assert conflict["error"]["retryable"] is True

    ended = run_cli(tmp_path, "session", "end", "--session", "s1")
    assert ended["session"]["active"] is False
    inactive = run_cli(
        tmp_path,
        "runtime",
        "context",
        "--session",
        "s1",
        "--locale",
        "zh-CN",
        "--scenario",
        "debugging",
        expected_returncode=2,
    )
    assert inactive["error"]["code"] == "SESSION_NOT_ACTIVE"


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b'{"mode":"single","mode":"mixed"}', "INPUT_INVALID_JSON"),
        (b'{"mixing":{"min_primary_ratio":NaN}}', "INPUT_INVALID_JSON"),
        (b"\xff", "INPUT_INVALID_JSON"),
    ],
)
def test_json_inputs_are_strict_and_errors_are_sanitized(
    tmp_path: Path, payload: bytes, expected_code: str
) -> None:
    path = tmp_path / "input.json"
    path.write_bytes(payload)
    result = run_cli(
        tmp_path,
        "policy",
        "compile",
        "--input",
        str(path),
        expected_returncode=2,
    )
    assert result["error"]["code"] == expected_code
    assert result["error"]["details"] == {}
    assert str(path) not in json.dumps(result)


def test_oversize_json_is_rejected_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    result = run_cli(
        tmp_path,
        "policy",
        "compile",
        "--input",
        str(path),
        expected_returncode=2,
    )
    assert result["error"]["code"] == "INPUT_TOO_LARGE"


def test_external_json_rejects_directory_before_open(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path,
        "policy",
        "compile",
        "--input",
        str(tmp_path),
        expected_returncode=2,
    )
    assert result["error"]["code"] == "INPUT_PATH_UNSAFE"


def test_external_json_rejects_symlink_before_open(tmp_path: Path) -> None:
    target = write_json(tmp_path / "target.json", {})
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    result = run_cli(
        tmp_path,
        "policy",
        "compile",
        "--input",
        str(link),
        expected_returncode=2,
    )
    assert result["error"]["code"] == "INPUT_PATH_UNSAFE"


def test_external_json_rejects_fifo_before_open(tmp_path: Path) -> None:
    make_fifo = getattr(os, "mkfifo", None)
    if make_fifo is None:
        pytest.skip("FIFO creation is unavailable")
    fifo = tmp_path / "input.fifo"
    make_fifo(fifo)

    result = run_cli(
        tmp_path,
        "policy",
        "compile",
        "--input",
        str(fifo),
        expected_returncode=2,
    )
    assert result["error"]["code"] == "INPUT_PATH_UNSAFE"


@pytest.mark.skipif(os.name != "nt", reason="Windows device namespace")
def test_external_json_rejects_windows_nul_before_open(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path,
        "policy",
        "compile",
        "--input",
        "NUL",
        expected_returncode=2,
    )
    assert result["error"]["code"] == "INPUT_PATH_UNSAFE"


def test_public_error_mapper_strips_secret_values_and_paths(
    tmp_path: Path,
) -> None:
    secret = f"secret-{tmp_path.name}"
    policy = write_json(
        tmp_path / f"{secret}.json",
        {"primary_language": secret},
    )
    result = run_cli(
        tmp_path,
        "policy",
        "compile",
        "--input",
        str(policy),
        expected_returncode=2,
    )
    serialized = json.dumps(result, ensure_ascii=False)
    assert result["error"]["code"] == "INVALID_LANGUAGE_POLICY"
    assert result["error"]["details"] == {}
    assert secret not in serialized
    assert str(tmp_path) not in serialized

    missing = run_cli(
        tmp_path,
        "pack",
        "validate",
        str(tmp_path / secret / "pack"),
        expected_returncode=2,
    )
    serialized_missing = json.dumps(missing, ensure_ascii=False)
    assert missing["error"]["code"] == "PACK_NOT_FOUND"
    assert missing["error"]["details"] == {}
    assert secret not in serialized_missing
    assert str(tmp_path) not in serialized_missing

    semantic = semantic_artifact()
    semantic["scenario"] = secret
    semantic_path = write_json(tmp_path / "semantic-secret.json", semantic)
    policy_input = write_json(tmp_path / "policy-safe.json", {})
    policy = run_cli(
        tmp_path, "policy", "compile", "--input", str(policy_input)
    )["policy"]
    policy_path = write_json(tmp_path / "policy-compiled.json", policy)
    invalid_schema = run_cli(
        tmp_path,
        "runtime",
        "plan",
        "--semantic",
        str(semantic_path),
        "--policy",
        str(policy_path),
        expected_returncode=2,
    )
    serialized_schema = json.dumps(invalid_schema, ensure_ascii=False)
    assert invalid_schema["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert invalid_schema["error"]["details"] == {}
    assert secret not in serialized_schema
    assert str(tmp_path) not in serialized_schema


def test_session_start_rejects_compiled_path_outside_data_root(
    tmp_path: Path,
) -> None:
    compiled = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    outside = tmp_path.parent / "outside-compiled.json"
    shutil.copyfile(compiled["path"], outside)
    result = run_cli(
        tmp_path,
        "session",
        "start",
        "--character",
        str(outside),
        "--session",
        "s1",
        expected_returncode=2,
    )
    assert result["error"]["code"] == "COMPILED_PATH_UNSAFE"


def test_session_start_rejects_compiled_file_with_external_hardlink(
    tmp_path: Path,
) -> None:
    compiled = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    target = Path(compiled["path"])
    outside = tmp_path.parent / f"{tmp_path.name}-compiled.json"
    make_hardlink(target, outside)

    result = run_cli(
        tmp_path,
        "session",
        "start",
        "--character",
        str(target),
        "--session",
        "s1",
        expected_returncode=2,
    )

    assert result["error"]["code"] == "COMPILED_PATH_UNSAFE"


def test_runtime_scan_rejects_compiled_candidate_with_external_hardlink(
    tmp_path: Path,
) -> None:
    compiled, _session = compiled_session(tmp_path)
    target = Path(compiled["path"])
    outside = tmp_path.parent / f"{tmp_path.name}-scan.json"
    make_hardlink(target, outside)

    result = run_cli(
        tmp_path,
        "runtime",
        "context",
        "--session",
        "s1",
        "--locale",
        "zh-CN",
        "--scenario",
        "debugging",
        expected_returncode=2,
    )

    assert result["error"]["code"] == "COMPILED_PATH_UNSAFE"


def test_pack_compile_rejects_preexisting_hardlinked_target(
    tmp_path: Path,
) -> None:
    compiled = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    target = Path(compiled["path"])
    outside = tmp_path.parent / f"{tmp_path.name}-compile.json"
    make_hardlink(target, outside)
    before = outside.read_bytes()

    result = run_cli(
        tmp_path,
        "pack",
        "compile",
        str(RIN_PACK),
        expected_returncode=2,
    )

    assert result["error"]["code"] == "COMPILED_PATH_UNSAFE"
    assert outside.read_bytes() == before


def test_pack_compile_rejects_special_existing_target(tmp_path: Path) -> None:
    compiled = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    target = Path(compiled["path"])
    target.unlink()
    target.mkdir()

    result = run_cli(
        tmp_path,
        "pack",
        "compile",
        str(RIN_PACK),
        expected_returncode=2,
    )

    assert result["error"]["code"] == "COMPILED_PATH_UNSAFE"
    assert target.is_dir()


def test_runtime_context_reports_zero_and_multiple_hash_matches(
    tmp_path: Path,
) -> None:
    compiled, _session = compiled_session(tmp_path)
    compiled_path = Path(compiled["path"])
    contents = compiled_path.read_bytes()
    compiled_path.unlink()
    compiled_path.parent.rmdir()
    missing = run_cli(
        tmp_path,
        "runtime",
        "context",
        "--session",
        "s1",
        "--locale",
        "zh-CN",
        "--scenario",
        "debugging",
        expected_returncode=2,
    )
    assert missing["error"]["code"] == "COMPILED_PACK_NOT_FOUND"

    compiled_path.parent.mkdir()
    compiled_path.write_bytes(contents)
    (compiled_path.parent / "duplicate.json").write_bytes(contents)
    ambiguous = run_cli(
        tmp_path,
        "runtime",
        "context",
        "--session",
        "s1",
        "--locale",
        "zh-CN",
        "--scenario",
        "debugging",
        expected_returncode=2,
    )
    assert ambiguous["error"]["code"] == "COMPILED_PACK_AMBIGUOUS"


def test_runtime_context_bounds_compiled_directory_before_parsing(
    tmp_path: Path,
) -> None:
    compiled, _session = compiled_session(tmp_path)
    Path(compiled["path"]).unlink()
    compiled_dir = tmp_path / "compiled"
    for index in range(257):
        (compiled_dir / f"attacker-{index:03}.json").write_bytes(b"{")

    result = run_cli(
        tmp_path,
        "runtime",
        "context",
        "--session",
        "s1",
        "--locale",
        "zh-CN",
        "--scenario",
        "debugging",
        expected_returncode=2,
    )

    assert result["error"]["code"] == "COMPILED_SCAN_LIMIT"


def test_session_start_rejects_corrupt_compiled_json(tmp_path: Path) -> None:
    compiled = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    Path(compiled["path"]).write_bytes(b'{"source_hash":NaN}')
    result = run_cli(
        tmp_path,
        "session",
        "start",
        "--character",
        compiled["path"],
        "--session",
        "s1",
        expected_returncode=2,
    )
    assert result["error"]["code"] == "INPUT_INVALID_JSON"
    assert result["error"]["details"] == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_id", "original/other-character/compiled"),
        ("character_id", "other-character"),
    ],
)
def test_session_start_rejects_compiled_identity_mismatch(
    tmp_path: Path, field: str, value: str
) -> None:
    compiled = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    path = Path(compiled["path"])
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact[field] = value
    write_json(path, artifact)

    result = run_cli(
        tmp_path,
        "session",
        "start",
        "--character",
        str(path),
        "--session",
        "s1",
        expected_returncode=2,
    )

    assert result["error"]["code"] == "COMPILED_IDENTITY_MISMATCH"


@pytest.mark.parametrize("wrong_field", ["character", "version"])
def test_runtime_context_rejects_matching_hash_with_wrong_identity(
    tmp_path: Path, wrong_field: str
) -> None:
    compiled, _session = compiled_session(tmp_path)
    path = Path(compiled["path"])
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if wrong_field == "character":
        artifact["character_id"] = "other-character"
        artifact["artifact_id"] = "original/other-character/compiled"
    else:
        artifact["character_version"] = "9.9.9"
    write_json(path, artifact)

    result = run_cli(
        tmp_path,
        "runtime",
        "context",
        "--session",
        "s1",
        "--locale",
        "zh-CN",
        "--scenario",
        "debugging",
        expected_returncode=2,
    )

    assert result["error"]["code"] == "COMPILED_IDENTITY_MISMATCH"


def test_state_apply_detects_restart_between_growth_lookup_and_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _compiled, _session = compiled_session(tmp_path)
    event_path = write_json(tmp_path / "event.json", interaction_event("e1", 0))
    settings = Settings.from_env({"KOKOROX_DATA_DIR": str(tmp_path)})
    schemas = SchemaRegistry(settings.schema_dir)
    real_lookup = cli_module._active_compiled_and_state

    def restart_after_lookup(settings_value, schemas_value, session_id):
        result = real_lookup(settings_value, schemas_value, session_id)
        store = result[0]
        manifest = result[1]
        store.end(session_id)
        store.start(
            session_id,
            manifest["character_id"],
            manifest["character_version"],
            manifest["compiled_pack_hash"],
        )
        return result

    monkeypatch.setattr(
        cli_module, "_active_compiled_and_state", restart_after_lookup
    )
    args = argparse.Namespace(session="s1", event=str(event_path))

    with pytest.raises(KokoroError) as raised:
        cli_module._handle_state_apply(args, settings, schemas)

    assert raised.value.code == "SESSION_CHANGED"
    assert raised.value.retryable is True
    assert result_revision(tmp_path, "s1") == 0


def result_revision(data_root: Path, session_id: str) -> int:
    return cli_module.SessionStore(data_root).replay(session_id)["revision"]


def test_session_start_rejects_redirected_compiled_file(tmp_path: Path) -> None:
    compiled = run_cli(tmp_path, "pack", "compile", str(RIN_PACK))
    link = Path(compiled["path"]).parent / "redirect.json"
    try:
        link.symlink_to(Path(compiled["path"]))
    except OSError:
        pytest.skip("symlink creation is unavailable")
    result = run_cli(
        tmp_path,
        "session",
        "start",
        "--character",
        str(link),
        "--session",
        "s1",
        expected_returncode=2,
    )
    assert result["error"]["code"] == "COMPILED_PATH_UNSAFE"
