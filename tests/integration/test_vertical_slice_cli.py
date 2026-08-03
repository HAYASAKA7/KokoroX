from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from kokoroarc import __version__

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RIN_PACK = REPOSITORY_ROOT / "characters" / "original" / "rin-aster"


def run_cli(
    data_dir: Path,
    *args: str,
    expected_returncode: int = 0,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["KOKOROARC_DATA_DIR"] = str(data_dir)
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
