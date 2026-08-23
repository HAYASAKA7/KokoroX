from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import sys
from typing import Any, Mapping

import pytest
import yaml


SKILLS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILLS_ROOT))

from complete_suite_sanitization import (  # noqa: E402
    require_clean_artifact,
    sanitize_artifact,
)


IMMUTABLE_COMPLETE_SUITE_REPLAY_BINDINGS = {
    "approved1": (
        "c7ad268f5a3202449056791871130f88f4f4325038c5e9e0f2490f514d4e6881",
        "78b0ec5d6c36386352a9e3bd49a93def89d127e0c614159ce0bc55e58d0e2a8a",
    ),
    "approved2": (
        "530ffed0e3e62a950148c4dcf27f2f18abb10b403ec321ea2d2cd5a165079664",
        "ea6939b6c33e226f135938630e7e451b7e63f24022259953d30b997619327a9d",
    ),
    "approved3": (
        "d8611bc380a7033ccff2928f5e12f5596e779bdf8d55999efc2b831ca24903ab",
        None,
    ),
    "approved4": (
        "4a7675f203fb3365a9dc743e4426fb5217da49e27817fea8f5c6a2a7aa9df90e",
        None,
    ),
    "approved5": (
        "6d05a42e4b681b06bbb758df71455f8d97362def6c5c2821e011efd7a1d22141",
        "f5678c44711c8d98c07348bd6e0f4f6f3398bcdd8f232d29c1dda74d8c88b552",
    ),
}


def _install_immutable_replay_sentinels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins
    import os
    import shutil
    import subprocess
    import tempfile

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("immutable_campaign_replay_attempted_write")

    real_builtin_open = builtins.open
    real_path_open = Path.open

    def guarded_builtin_open(
        file: object,
        mode: str = "r",
        *args: object,
        **kwargs: object,
    ):
        if any(flag in mode for flag in "wax+"):
            forbidden(file, mode)
        return real_builtin_open(file, mode, *args, **kwargs)

    def guarded_path_open(
        path: Path,
        mode: str = "r",
        *args: object,
        **kwargs: object,
    ):
        if any(flag in mode for flag in "wax+"):
            forbidden(path, mode)
        return real_path_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_builtin_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    for name in (
        "chmod",
        "hardlink_to",
        "mkdir",
        "rename",
        "replace",
        "rmdir",
        "symlink_to",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    ):
        monkeypatch.setattr(Path, name, forbidden)
    for name in (
        "chmod",
        "link",
        "makedirs",
        "mkdir",
        "remove",
        "removedirs",
        "rename",
        "renames",
        "replace",
        "rmdir",
        "symlink",
        "truncate",
        "unlink",
        "utime",
    ):
        monkeypatch.setattr(os, name, forbidden)
    for name in (
        "copy",
        "copy2",
        "copyfile",
        "copytree",
        "move",
        "rmtree",
    ):
        monkeypatch.setattr(shutil, name, forbidden)
    for name in ("mkdtemp", "mkstemp", "NamedTemporaryFile", "TemporaryDirectory"):
        monkeypatch.setattr(tempfile, name, forbidden)
    for name in ("call", "check_call", "check_output", "Popen", "run"):
        monkeypatch.setattr(subprocess, name, forbidden)


def _replay_retained_entry(
    root: Path,
    untrusted: object,
) -> str | None:
    from import_complete_suite_campaign import (
        _read_text_artifact,
        _validate_ledger_entry,
    )

    entry = _validate_ledger_entry(untrusted)
    relative = entry["retained_path"]
    if relative is None:
        return None
    path = root.joinpath(*relative.split("/"))
    payload = _read_text_artifact(path)
    assert len(payload) == entry["retained_size"]
    assert sha256(payload).hexdigest() == entry["retained_sha256"]
    return relative


@pytest.mark.parametrize(
    ("approval", "replay_binding"),
    IMMUTABLE_COMPLETE_SUITE_REPLAY_BINDINGS.items(),
    ids=IMMUTABLE_COMPLETE_SUITE_REPLAY_BINDINGS,
)
def test_immutable_campaign_replay_preserves_result_tree_hash(
    approval: str,
    replay_binding: tuple[str, str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from complete_suite_preparation import inventory_tree
    from import_complete_suite_campaign import (
        _load_json_object,
        _read_text_artifact,
        _safe_relative_path,
    )

    _install_immutable_replay_sentinels(monkeypatch)
    expected_import_ledger_sha256, expected_result_tree_sha256 = replay_binding
    retained_root = SKILLS_ROOT / "evidence" / "complete-suite" / approval
    results_root = retained_root / "results"
    before = inventory_tree(results_root) if results_root.is_dir() else None

    import_path = retained_root / "import-ledger.json"
    import_bytes = _read_text_artifact(import_path)
    assert sha256(import_bytes).hexdigest() == expected_import_ledger_sha256
    import_ledger = _load_json_object(import_path)
    campaign_paths = {
        relative.removeprefix("campaign/")
        for untrusted in import_ledger["campaign_files"]
        if (relative := _replay_retained_entry(retained_root, untrusted))
        is not None
    }
    assert {
        entry["path"] for entry in inventory_tree(retained_root / "campaign")["files"]
    } == campaign_paths
    prepared_campaign_path = (
        retained_root / "campaign" / "prepared-campaign.json"
    )
    if "prepared-campaign.json" in campaign_paths:
        historical_campaign = _load_json_object(prepared_campaign_path)
        assert "command_provenance" not in historical_campaign
    else:
        assert approval == "approved4"
        assert not prepared_campaign_path.exists()
        assert not prepared_campaign_path.is_symlink()

    for run in import_ledger["runs"]:
        ledger_path = retained_root.joinpath(*run["ledger_path"].split("/"))
        ledger_bytes = _read_text_artifact(ledger_path)
        assert sha256(ledger_bytes).hexdigest() == run["ledger_sha256"]
        run_ledger = _load_json_object(ledger_path)
        assert run_ledger["ordinal"] == run["ordinal"]
        assert run_ledger["variant"] == run["variant"]
        assert run_ledger["case_id"] == run["case_id"]
        run_root = retained_root / "runs" / run["variant"] / run["case_id"]
        expected_run_paths = {
            relative
            for untrusted in run_ledger["files"]
            if (relative := _replay_retained_entry(run_root, untrusted)) is not None
        }
        for relative, binding in run_ledger["derived_files"].items():
            _safe_relative_path(relative)
            payload = _read_text_artifact(run_root.joinpath(*relative.split("/")))
            assert len(payload) == binding["size"]
            assert sha256(payload).hexdigest() == binding["sha256"]
            expected_run_paths.add(relative)
        observed_run_paths = {
            entry["path"] for entry in inventory_tree(run_root)["files"]
        }
        assert observed_run_paths == expected_run_paths

    if expected_result_tree_sha256 is None:
        assert before is None
        assert not results_root.exists()
        assert not results_root.is_symlink()
        return

    assert before is not None
    assert before["tree_sha256"] == expected_result_tree_sha256
    adjudication_path = results_root / "adjudication-ledger.json"
    adjudication = _load_json_object(adjudication_path)
    assert adjudication["import_ledger_sha256"] == expected_import_ledger_sha256
    expected_result_paths = {"adjudication-ledger.json"}
    for record in (*adjudication["results"], *adjudication["summaries"]):
        _safe_relative_path(record["path"])
        payload = _read_text_artifact(
            results_root.joinpath(*record["path"].split("/"))
        )
        assert len(payload) == record["size"]
        assert sha256(payload).hexdigest() == record["sha256"]
        expected_result_paths.add(record["path"])
    assert {entry["path"] for entry in before["files"]} == expected_result_paths
    assert before == inventory_tree(results_root)


def _import_command_run(
    root: Path,
    *,
    command: str | None = None,
    command_records: tuple[
        tuple[str, str] | tuple[str, str, int], ...
    ] = (),
    extra_events: tuple[dict[str, Any], ...] = (),
    case_id: str = "example-case",
    variant: str = "baseline",
    final_document: Mapping[str, Any] | None = None,
    prepared_files: Mapping[str, bytes] | None = None,
    create_result_artifact: bool = True,
    generated_files: Mapping[str, bytes] | None = None,
    completed_statuses: Mapping[int, str] | None = None,
    completed_metadata: Mapping[int, Mapping[str, Any]] | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    import run_complete_suite_campaign as runner
    from import_complete_suite_campaign import retain_run_evidence
    from test_complete_suite_evidence import (
        _canonical_bytes,
        _final_response,
        _prepared_case,
        _write_json,
    )

    case_root = _prepared_case(root / "source")
    workspace = case_root / "workspace"
    if prepared_files:
        for relative, payload in prepared_files.items():
            target = workspace.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
    _write_json(workspace / "case.json", {"id": case_id})
    pre_run_path = case_root / "raw" / "pre-run-state.json"
    pre_run = json.loads(pre_run_path.read_text(encoding="utf-8"))
    pre_run.update(
        {
            "variant": variant,
            "case_id": case_id,
            "workspace_before": runner.preparation.inventory_tree(workspace),
            "immutable_before": runner._immutable_case_state(case_root),
            "preexisting_outputs": runner.preparation.inventory_tree(
                workspace / "outputs",
                allow_missing=True,
            ),
        }
    )
    _write_json(pre_run_path, pre_run)
    response = dict(final_document or _final_response(case_id))
    response_text = _canonical_bytes(response).decode("utf-8")
    if command_records:
        records = tuple(
            (record[0], record[1], record[2] if len(record) == 3 else 0)
            for record in command_records
        )
    elif command is not None:
        records = ((command, "safe output\n", 0),)
    else:
        records = ()

    class RecordedProcess:
        returncode = 0

        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            self.argv = argv
            self.stdout = kwargs["stdout"]

        def communicate(
            self,
            input: bytes | None = None,
            timeout: float | None = None,
        ) -> tuple[None, None]:
            if create_result_artifact:
                (workspace / "outputs").mkdir()
                _write_json(workspace / "outputs" / "result.json", {"ok": True})
            if generated_files:
                for relative, payload in generated_files.items():
                    target = workspace.joinpath(*relative.split("/"))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
            events: list[dict[str, Any]] = [
                {"type": "thread.started", "thread_id": "thread-integrity-01"},
                {"type": "turn.started"},
            ]
            for index, (recorded_command, output, exit_code) in enumerate(
                records,
                start=1,
            ):
                identifier = f"command-{index}"
                completed_item: dict[str, Any] = {
                    "id": identifier,
                    "type": "command_execution",
                    "command": recorded_command,
                    "aggregated_output": output,
                    "exit_code": exit_code,
                    "status": (completed_statuses or {}).get(
                        index,
                        "completed" if exit_code == 0 else "failed",
                    ),
                }
                completed_item.update((completed_metadata or {}).get(index, {}))
                events.extend(
                    (
                        {
                            "type": "item.started",
                            "item": {
                                "id": identifier,
                                "type": "command_execution",
                                "command": recorded_command,
                                "aggregated_output": "",
                                "exit_code": None,
                                "status": "in_progress",
                            },
                        },
                        {
                            "type": "item.completed",
                            "item": completed_item,
                        },
                    )
                )
            events.extend(
                (
                    *extra_events,
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-final",
                        "type": "agent_message",
                        "text": response_text,
                    },
                },
                {"type": "turn.completed", "usage": {}},
                )
            )
            self.stdout.write(
                b"".join(_canonical_bytes(event) + b"\n" for event in events)
            )
            Path(
                self.argv[self.argv.index("--output-last-message") + 1]
            ).write_bytes(response_text.encode("utf-8") + b"\n")
            return None, None

        def kill(self) -> None:
            raise AssertionError("recorded process was killed")

        def poll(self) -> int:
            return self.returncode

    item = runner.RunSpec(1, variant, case_id)
    runner.run_one(
        case_root,
        item,
        codex_executable=Path(r"D:\tools\codex.exe"),
        python_executable=Path(r"C:\Python314\python.exe"),
        host_environment={"SYSTEMROOT": r"C:\Windows"},
        popen_factory=RecordedProcess,
    )
    retained_run = root / "retained" / variant / case_id
    retained_run.mkdir(parents=True)
    ledger = retain_run_evidence(case_root, retained_run, item)
    return case_root, retained_run, ledger


def _complete_case(case_id: str) -> dict[str, Any]:
    document = yaml.safe_load(
        (SKILLS_ROOT / "complete-suite-cases.yaml").read_text(encoding="utf-8")
    )
    return next(case for case in document["cases"] if case["id"] == case_id)


def _powershell_command(payload: str) -> str:
    return (
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -Command '
        + json.dumps(payload)
    )


def _cli_command(arguments: str) -> str:
    return _powershell_command(f"python -m kokoroarc.cli {arguments}")


@pytest.mark.parametrize(
    ("executable", "wrapper_flags", "expected_flag"),
    (
        (r"C:\Program Files\PowerShell\7\pwsh.exe", "-Command", "-Command"),
        (r"C:\Program Files\PowerShell\7\pwsh.exe", "-c", "-c"),
        (
            r"C:\\Program Files\\PowerShell\\7\\pwsh.exe",
            "-NoProfile -Command",
            "-Command",
        ),
        (
            r"C:\\Program Files/PowerShell\\7/pwsh.exe",
            "-noprofile -C",
            "-C",
        ),
    ),
)
def test_structured_command_accepts_only_the_declared_powershell_forms(
    executable: str,
    wrapper_flags: str,
    expected_flag: str,
) -> None:
    from complete_suite_adjudication import _structured_command

    payload = "python -m kokoroarc.cli pack validate workspace --json"
    command = f'"{executable}" {wrapper_flags} {json.dumps(payload)}'

    assert _structured_command(command, 0) == {
        "command": executable,
        "argv": [expected_flag, payload],
        "exit_code": 0,
    }


@pytest.mark.parametrize(
    "command",
    (
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -NoLogo -Command "Get-Date"',
        (
            r'"C:\Program Files\PowerShell\7\pwsh.exe" '
            r'-NoProfile -NoProfile -Command "Get-Date"'
        ),
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -Command -NoProfile "Get-Date"',
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile "Get-Date"',
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -File "script.ps1"',
        r'"D:\Program Files\PowerShell\7\pwsh.exe" -Command "Get-Date"',
        r'"..\PowerShell\7\pwsh.exe" -Command "Get-Date"',
        r'"\\server\share\pwsh.exe" -Command "Get-Date"',
        r'"\\?\C:\Program Files\PowerShell\7\pwsh.exe" -Command "Get-Date"',
    ),
)
def test_structured_command_rejects_undeclared_powershell_forms(
    command: str,
) -> None:
    from complete_suite_adjudication import _structured_command

    assert _structured_command(command, 0) is None


def _json_line(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def _claimed_final(
    case: Mapping[str, Any],
    *,
    outcome: str,
    response: str,
    created_paths: list[str] | None = None,
    blockers: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    claims = [
        {"id": assertion, "status": "satisfied", "evidence_paths": []}
        for assertion in case["must"]
    ]
    claims.extend(
        {
            "id": assertion,
            "status": "not_satisfied",
            "evidence_paths": [],
        }
        for assertion in case["must_not"]
    )
    return {
        "schema_version": "1.0",
        "case_id": case["id"],
        "outcome": outcome,
        "response": response,
        "claimed_assertions": claims,
        "created_paths": created_paths or [],
        "blockers": blockers or [],
    }


def _safe_install_commands(
    *,
    preview_payload: str | None = None,
    preview_output: str | None = None,
) -> tuple[tuple[str, str], ...]:
    registry_path = "data/registry/workspace.json"
    pack_path = "data/installed/workspace/rin-aster/1.0.0/compiled.json"
    return (
        (
            _powershell_command(
                preview_payload
                or (
                    "python -m kokoroarc.cli pack install "
                    "inputs/rin-1.0.0.karc --scope workspace "
                    "--workspace . --dry-run --json"
                )
            ),
            preview_output
            or _json_line(
                    {
                        "ok": True,
                        "dry_run": True,
                        "scope": "workspace",
                        "registry_path": registry_path,
                        "pack_path": pack_path,
                    }
                ),
        ),
        (
            _cli_command(
                "pack install inputs/rin-1.0.0.karc --scope workspace "
                "--workspace . --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "changed": True,
                    "scope": "workspace",
                    "registry_path": registry_path,
                    "pack_path": pack_path,
                }
            ),
        ),
        (
            _cli_command(
                "pack install inputs/rin-1.0.0.karc --scope workspace "
                "--workspace . --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "changed": False,
                    "scope": "workspace",
                    "registry_path": registry_path,
                    "pack_path": pack_path,
                }
            ),
        ),
    )


def _safe_install_fixture(
    root: Path,
    *,
    commands: tuple[tuple[str, str] | tuple[str, str, int], ...] | None = None,
    extra_events: tuple[dict[str, Any], ...] = (),
    final_document: Mapping[str, Any] | None = None,
    completed_statuses: Mapping[int, str] | None = None,
    completed_metadata: Mapping[int, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    case = _complete_case("safe-install-inactive")
    registry_path = "data/registry/workspace.json"
    pack_path = "data/installed/workspace/rin-aster/1.0.0/compiled.json"
    final = final_document or _claimed_final(
        case,
        outcome="completed",
        response=(
            f"Previewed and installed only in this workspace. Registry target "
            f"{registry_path}; pack target {pack_path}. The identical reinstall "
            "was unchanged. No default or session was created, nothing was "
            "activated, and no archive was published."
        ),
    )
    case_root, retained_run, ledger = _import_command_run(
        root,
        command_records=commands or _safe_install_commands(),
        extra_events=extra_events,
        case_id=case["id"],
        final_document=final,
        prepared_files={"inputs/rin-1.0.0.karc": b"private archive\n"},
        generated_files={
            registry_path: b'{"entries":{"rin":"1.0.0"}}\n',
            pack_path: b'{"character_id":"rin-aster","version":"1.0.0"}\n',
        },
        completed_statuses=completed_statuses,
        completed_metadata=completed_metadata,
        create_result_artifact=False,
    )
    return case, case_root, retained_run, ledger


def test_complete_suite_sanitizer_is_bounded_idempotent_and_classified() -> None:
    raw = (
        b'profile=C:\\Users\\alice\\private\\notes.txt\n'
        b'PASSWORD="alpha \\"beta\\" gamma"\n'
        b'{\\"Authorization\\": \\"Bearer auth-alpha auth-beta\\"}\n'
        b'remote=https://user:url-secret@example.test/resource\n'
        b'github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\n'
        b'-----BEGIN ENCRYPTED PRIVATE KEY-----\nsecret\n'
        b'-----END ENCRYPTED PRIVATE KEY-----\n'
    )

    retained, summary = sanitize_artifact(raw)

    assert summary["redaction_count"] >= 6
    assert summary["redaction_classes"] == [
        "credential",
        "environment_secret",
        "user_profile",
    ]
    for leaked in (
        b"alice",
        b"alpha",
        b"auth-alpha",
        b"url-secret",
        b"github_pat_",
        b"BEGIN ENCRYPTED PRIVATE KEY",
    ):
        assert leaked not in retained
    assert sanitize_artifact(retained) == (
        retained,
        {"redaction_count": 0, "redaction_classes": []},
    )


def test_complete_suite_sanitizer_closes_placeholder_smuggling() -> None:
    raw = (
        b'PASSWORD="<redacted-environment-secret>"trailing-secret\n'
        b'https://<redacted-credential>:url-leak@example.test/resource\n'
    )

    retained, summary = sanitize_artifact(raw)

    assert summary["redaction_count"] == 2
    assert b"trailing-secret" not in retained
    assert b"url-leak" not in retained
    assert sanitize_artifact(retained)[1]["redaction_count"] == 0


@pytest.mark.parametrize(
    "profile_path",
    (
        "/home/alice/private/notes.txt",
        "/Users/alice/private/notes.txt",
        r"C:\Users\alice\private\notes.txt",
    ),
)
def test_complete_suite_sanitizer_redacts_cross_platform_user_paths(
    profile_path: str,
) -> None:
    retained, summary = sanitize_artifact(
        f"source={profile_path}\n".encode("utf-8")
    )

    assert b"alice" not in retained
    assert summary["redaction_count"] == 1
    assert summary["redaction_classes"] == ["user_profile"]


@pytest.mark.parametrize(
    "authorization",
    (
        "Authorization: Bearer auth-alpha auth-beta",
        '{"Authorization":"Bearer auth-alpha auth-beta"}',
        "AUTHORIZATION='Basic auth-alpha-auth-beta'",
    ),
)
def test_complete_suite_sanitizer_redacts_authorization_forms(
    authorization: str,
) -> None:
    retained, summary = sanitize_artifact(
        f"{authorization}\n".encode("utf-8")
    )

    assert b"auth-alpha" not in retained
    assert summary["redaction_count"] == 1
    assert summary["redaction_classes"] == ["credential"]
    assert sanitize_artifact(retained)[1]["redaction_count"] == 0


def test_complete_suite_sanitizer_rejects_non_utf8_and_dirty_immutable() -> None:
    with pytest.raises(ValueError, match="UTF-8"):
        sanitize_artifact(b"invalid:\xff")
    with pytest.raises(ValueError, match="requires redaction"):
        require_clean_artifact(b"TOKEN=synthetic-secret\n")
    require_clean_artifact(b'{"safe":true}\n')


def test_retained_text_copy_is_hash_bound_sanitized_and_replayable(
    tmp_path: Path,
) -> None:
    from import_complete_suite_campaign import (
        replay_artifact_ledger,
        retain_text_artifact,
    )

    raw_root = tmp_path / "raw"
    retained_root = tmp_path / "retained"
    source = raw_root / "baseline" / "case-a" / "session.jsonl"
    source.parent.mkdir(parents=True)
    retained_root.mkdir()
    source.write_bytes(
        b'{"path":"C:\\\\Users\\\\alice\\\\private.txt",'
        b'"TOKEN":"synthetic-secret"}\n'
    )

    entry = retain_text_artifact(
        source,
        raw_root=raw_root,
        retained_root=retained_root,
        retained_path="baseline/case-a/session.jsonl",
        allow_redaction=True,
    )

    destination = retained_root / "baseline" / "case-a" / "session.jsonl"
    assert entry["raw_path"] == "baseline/case-a/session.jsonl"
    assert entry["retained_path"] == "baseline/case-a/session.jsonl"
    assert entry["redaction_count"] == 2
    assert entry["raw_sha256"] != entry["retained_sha256"]
    assert b"alice" not in destination.read_bytes()
    assert b"synthetic-secret" not in destination.read_bytes()
    replay_artifact_ledger(raw_root, retained_root, [entry])

    destination.write_bytes(b"tampered\n")
    with pytest.raises(RuntimeError, match="retained artifact mismatch"):
        replay_artifact_ledger(raw_root, retained_root, [entry])


def test_retained_text_copy_rejects_unexpected_redaction_and_unsafe_paths(
    tmp_path: Path,
) -> None:
    from import_complete_suite_campaign import retain_text_artifact

    raw_root = tmp_path / "raw"
    retained_root = tmp_path / "retained"
    raw_root.mkdir()
    retained_root.mkdir()
    dirty = raw_root / "dirty.txt"
    dirty.write_bytes(b"PASSWORD=synthetic-secret\n")

    with pytest.raises(RuntimeError, match="unexpected redaction"):
        retain_text_artifact(
            dirty,
            raw_root=raw_root,
            retained_root=retained_root,
            retained_path="dirty.txt",
            allow_redaction=False,
        )
    with pytest.raises(RuntimeError, match="retained path"):
        retain_text_artifact(
            dirty,
            raw_root=raw_root,
            retained_root=retained_root,
            retained_path="../escape.txt",
            allow_redaction=True,
        )
    invalid = raw_root / "invalid.txt"
    invalid.write_bytes(b"invalid:\xff")
    with pytest.raises(RuntimeError, match="sanitization failed"):
        retain_text_artifact(
            invalid,
            raw_root=raw_root,
            retained_root=retained_root,
            retained_path="invalid.txt",
            allow_redaction=True,
        )


@pytest.mark.parametrize(
    "payload",
    (
        b"alpha\nbeta\n",
        b"alpha\r\nbeta\r\n",
    ),
    ids=("lf", "crlf"),
)
def test_clean_line_endings_round_trip_byte_exactly(
    tmp_path: Path,
    payload: bytes,
) -> None:
    from import_complete_suite_campaign import retain_text_artifact

    raw_root = tmp_path / "raw"
    retained_root = tmp_path / "retained"
    raw_root.mkdir()
    retained_root.mkdir()
    source = raw_root / "source.txt"
    source.write_bytes(payload)

    entry = retain_text_artifact(
        source,
        raw_root=raw_root,
        retained_root=retained_root,
        retained_path="copy.txt",
        allow_redaction=False,
    )

    assert (retained_root / "copy.txt").read_bytes() == payload
    assert entry["raw_sha256"] == sha256(payload).hexdigest()
    assert entry["retained_sha256"] == sha256(payload).hexdigest()
    assert entry["raw_size"] == entry["retained_size"] == len(payload)
    assert entry["redaction_count"] == 0


def test_retained_copy_rejects_linked_source_and_destination_ancestry(
    tmp_path: Path,
) -> None:
    from import_complete_suite_campaign import retain_text_artifact

    raw_root = tmp_path / "raw"
    retained_root = tmp_path / "retained"
    outside = tmp_path / "outside"
    raw_root.mkdir()
    retained_root.mkdir()
    outside.mkdir()
    outside_file = outside / "outside.txt"
    outside_file.write_bytes(b"outside\n")
    linked_source = raw_root / "linked.txt"
    linked_ancestor = retained_root / "linked"
    try:
        linked_source.symlink_to(outside_file)
        linked_ancestor.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink capability unavailable: {exc}")

    with pytest.raises(RuntimeError, match="outside the approved root|unsafe"):
        retain_text_artifact(
            linked_source,
            raw_root=raw_root,
            retained_root=retained_root,
            retained_path="linked-source.txt",
            allow_redaction=False,
        )

    source = raw_root / "safe.txt"
    source.write_bytes(b"safe\n")
    with pytest.raises(RuntimeError, match="ancestry is unsafe"):
        retain_text_artifact(
            source,
            raw_root=raw_root,
            retained_root=retained_root,
            retained_path="linked/copy.txt",
            allow_redaction=False,
        )


def test_complete_run_import_rebinds_session_status_and_generated_artifacts(
    tmp_path: Path,
) -> None:
    import run_complete_suite_campaign as runner
    from import_complete_suite_campaign import (
        replay_run_evidence,
        retain_run_evidence,
    )
    from test_complete_suite_evidence import (
        _canonical_bytes,
        _final_response,
        _prepared_case,
        _write_json,
    )

    case_root = _prepared_case(tmp_path / "source")
    workspace = case_root / "workspace"
    response_text = _canonical_bytes(_final_response()).decode("utf-8")

    class SuccessfulProcess:
        returncode = 0

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            self.command = command
            self.stdout = kwargs["stdout"]
            self.stderr = kwargs["stderr"]

        def communicate(
            self,
            input: bytes | None = None,
            timeout: float | None = None,
        ) -> tuple[None, None]:
            (workspace / "outputs").mkdir()
            _write_json(workspace / "outputs" / "result.json", {"ok": True})
            events = (
                {"type": "thread.started", "thread_id": "thread-import-01"},
                {"type": "turn.started"},
                {
                    "type": "item.started",
                    "item": {
                        "id": "command-1",
                        "type": "command_execution",
                        "command": "Get-Content inputs/setup.json",
                        "aggregated_output": "",
                        "exit_code": None,
                        "status": "in_progress",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "command-1",
                        "type": "command_execution",
                        "command": "Get-Content inputs/setup.json",
                        "aggregated_output": '{"TOKEN":"synthetic-secret"}\n',
                        "exit_code": 0,
                        "status": "completed",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-final",
                        "type": "agent_message",
                        "text": response_text,
                    },
                },
                {"type": "turn.completed", "usage": {}},
            )
            self.stdout.write(
                b"".join(_canonical_bytes(event) + b"\n" for event in events)
            )
            self.stderr.write(b"profile=C:\\Users\\alice\\private.txt\n")
            Path(
                self.command[self.command.index("--output-last-message") + 1]
            ).write_bytes(response_text.encode("utf-8") + b"\n")
            return None, None

        def kill(self) -> None:
            raise AssertionError("successful process was killed")

        def poll(self) -> int:
            return self.returncode

    item = runner.RunSpec(1, "baseline", "example-case")
    source_status = runner.run_one(
        case_root,
        item,
        codex_executable=Path(r"D:\tools\codex.exe"),
        python_executable=Path(r"C:\Python314\python.exe"),
        host_environment={"SYSTEMROOT": r"C:\Windows"},
        popen_factory=SuccessfulProcess,
    )
    retained_run = tmp_path / "retained" / "baseline" / "example-case"
    retained_run.mkdir(parents=True)

    ledger = retain_run_evidence(case_root, retained_run, item)

    assert ledger["source_status"] == source_status
    assert ledger["evaluable"] is True
    assert ledger["retained_binding"]["passed"] is True
    assert ledger["retained_binding"]["thread_id"] == "thread-import-01"
    assert (retained_run / "workspace-artifacts" / "outputs/result.json").is_file()
    assert b"synthetic-secret" not in (retained_run / "session.jsonl").read_bytes()
    assert b"alice" not in (retained_run / "stderr.txt").read_bytes()
    replay_run_evidence(case_root, retained_run, ledger)

    status_path = case_root / "raw" / "run-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["thread_id"] = "thread-tampered"
    status_path.write_bytes(
        json.dumps(status, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    with pytest.raises(RuntimeError, match="run status mismatch"):
        replay_run_evidence(case_root, retained_run, ledger)


def test_failed_run_import_retains_binary_digest_without_becoming_evaluable(
    tmp_path: Path,
) -> None:
    import run_complete_suite_campaign as runner
    from import_complete_suite_campaign import (
        replay_run_evidence,
        retain_run_evidence,
    )
    from test_complete_suite_evidence import _prepared_case

    case_root = _prepared_case(tmp_path / "source")
    workspace = case_root / "workspace"
    binary_payload = b"\x00\xffKARC\r\n\x80"

    class FailedProcess:
        returncode = 7

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            self.stdout = kwargs["stdout"]
            self.stderr = kwargs["stderr"]

        def communicate(
            self,
            input: bytes | None = None,
            timeout: float | None = None,
        ) -> tuple[None, None]:
            (workspace / "outputs").mkdir()
            (workspace / "outputs" / "private.karc").write_bytes(binary_payload)
            self.stderr.write(b"external evaluator failed\n")
            return None, None

        def kill(self) -> None:
            raise AssertionError("failed process was not timed out")

        def poll(self) -> int:
            return self.returncode

    item = runner.RunSpec(1, "baseline", "example-case")
    status = runner.run_one(
        case_root,
        item,
        codex_executable=Path(r"D:\tools\codex.exe"),
        python_executable=Path(r"C:\Python314\python.exe"),
        host_environment={"SYSTEMROOT": r"C:\Windows"},
        popen_factory=FailedProcess,
    )
    retained_run = tmp_path / "retained" / "baseline" / "example-case"
    retained_run.mkdir(parents=True)

    ledger = retain_run_evidence(case_root, retained_run, item)

    assert status["lifecycle_passed"] is False
    assert ledger["evaluable"] is False
    assert ledger["retained_binding"]["passed"] is False
    digest = next(
        entry
        for entry in ledger["files"]
        if entry["raw_path"] == "workspace/outputs/private.karc"
    )
    assert digest == {
        "schema_version": "1.0",
        "retention": "hash_only",
        "raw_path": "workspace/outputs/private.karc",
        "retained_path": None,
        "raw_size": len(binary_payload),
        "raw_sha256": sha256(binary_payload).hexdigest(),
        "reason": "binary_generated_artifact",
    }
    assert not (retained_run / "workspace-artifacts/outputs/private.karc").exists()
    replay_run_evidence(case_root, retained_run, ledger)

    forged = json.loads(json.dumps(ledger))
    forged["evaluable"] = True
    with pytest.raises(RuntimeError, match="run evidence ledger is invalid"):
        replay_run_evidence(case_root, retained_run, forged)

    (workspace / "outputs" / "private.karc").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="raw artifact or ledger mismatch"):
        replay_run_evidence(case_root, retained_run, ledger)


def test_run_integrity_accepts_literal_read_only_powershell_command(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import validate_run_integrity

    command = (
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -Command '
        + json.dumps(r"Get-Content -Raw 'inputs\setup.json'")
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command=command,
    )

    result = validate_run_integrity(case_root, retained_run, ledger)

    assert result == {
        "passed": True,
        "failure_codes": [],
        "command_count": 1,
        "file_change_count": 0,
    }


@pytest.mark.parametrize(
    "payload",
    (
        "Invoke-WebRequest https://example.invalid",
        r"& 'C:\Program Files\Python\python.exe' -c 'print(1)'",
        "Get-ChildItem env:",
        r"Copy-Item 'inputs\setup.json' 'D:\outside\leak.json'",
        "Start-Process pwsh -ArgumentList '-Command','Get-Content env:'",
    ),
)
def test_run_integrity_rejects_network_secret_shell_and_outside_commands(
    tmp_path: Path,
    payload: str,
) -> None:
    from complete_suite_adjudication import validate_run_integrity

    command = (
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -Command '
        + json.dumps(payload)
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command=command,
    )

    result = validate_run_integrity(case_root, retained_run, ledger)

    assert result["passed"] is False
    assert "UNSAFE_COMMAND" in result["failure_codes"]


def test_run_integrity_rejects_outside_file_change_and_unknown_tool(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import validate_run_integrity

    changes = (
        {
            "type": "item.started",
            "item": {
                "id": "change-1",
                "type": "file_change",
                "changes": [{"path": r"D:\outside\leak.json", "kind": "add"}],
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "change-1",
                "type": "file_change",
                "changes": [{"path": r"D:\outside\leak.json", "kind": "add"}],
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "tool-1",
                "type": "mcp_tool_call",
                "server": "browser",
                "tool": "open",
                "status": "completed",
            },
        },
    )
    command = (
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -Command '
        + json.dumps(r"Get-Content -Raw 'inputs\setup.json'")
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command=command,
        extra_events=changes,
    )

    result = validate_run_integrity(case_root, retained_run, ledger)

    assert result["passed"] is False
    assert set(result["failure_codes"]) >= {
        "FILE_CHANGE_OUTSIDE_WORKSPACE",
        "UNAUTHORIZED_TOOL_EVENT",
    }


def test_named_research_stop_is_adjudicated_from_bound_commands_and_state(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("named-character-research-route")
    source_skill = SKILLS_ROOT.parents[1] / "skills" / "researching-characters"
    skill = source_skill / "SKILL.md"
    contract = source_skill / "references" / "research-contract.md"
    response = (
        "Identity remains unresolved: please identify the exact Aoi and franchise. "
        "Choose the continuity and a spoiler cutoff before any source work. I "
        "stopped before research tools and refuse to invent citations. Unresolved "
        "evidence: identity, continuity, and spoiler scope. No source record, "
        "character draft, install, or session was created."
    )
    final = _claimed_final(
        case,
        outcome="clarification_required",
        response=response,
        blockers=[
            {
                "code": "CHARACTER_IDENTITY_AMBIGUOUS",
                "message": "The exact fictional identity is unresolved.",
            }
        ],
    )
    commands = (
        (
            _powershell_command(
                r"Get-Content -Raw '.agents\skills\researching-characters\SKILL.md'"
            ),
            skill.read_text(encoding="utf-8"),
        ),
        (
            _powershell_command(
                "Get-Content -Raw "
                r"'.agents\skills\researching-characters\references"
                r"\research-contract.md'"
            ),
            contract.read_text(encoding="utf-8"),
        ),
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case["id"],
        variant="suite-enabled",
        final_document=final,
        prepared_files={
            ".agents/skills/researching-characters/SKILL.md": skill.read_bytes(),
            (
                ".agents/skills/researching-characters/references/"
                "research-contract.md"
            ): contract.read_bytes(),
            "inputs/aoi-ambiguity.json": b'{"identities":["a","b"]}\n',
        },
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(assertion["passed"] for assertion in result["assertions"])
    assert result["evidence_integrity"]["passed"] is True


def test_negative_stop_assertion_fails_when_research_cli_was_invoked(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("named-character-research-route")
    source_skill = SKILLS_ROOT.parents[1] / "skills" / "researching-characters"
    skill = source_skill / "SKILL.md"
    contract = source_skill / "references" / "research-contract.md"
    final = _claimed_final(
        case,
        outcome="clarification_required",
        response=(
            "The exact Aoi, continuity choice, and spoiler cutoff are unresolved. "
            "I stopped before research tools, refuse invented citations, and "
            "created no source record, draft, install, or session. Unresolved "
            "evidence: identity, continuity, spoiler scope."
        ),
    )
    commands = (
        (
            _powershell_command(
                r"Get-Content -Raw '.agents\skills\researching-characters\SKILL.md'"
            ),
            skill.read_text(encoding="utf-8"),
        ),
        (
            _powershell_command(
                "Get-Content -Raw "
                r"'.agents\skills\researching-characters\references"
                r"\research-contract.md'"
            ),
            contract.read_text(encoding="utf-8"),
        ),
        (
            _powershell_command(
                "python -m kokoroarc.cli research request validate "
                "--input inputs/aoi-ambiguity.json --json"
            ),
            '{"ok":true}\n',
        ),
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case["id"],
        variant="suite-enabled",
        final_document=final,
        prepared_files={
            ".agents/skills/researching-characters/SKILL.md": skill.read_bytes(),
            (
                ".agents/skills/researching-characters/references/"
                "research-contract.md"
            ): contract.read_bytes(),
            "inputs/aoi-ambiguity.json": b'{"identities":["a","b"]}\n',
        },
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)
    outcomes = {item["id"]: item for item in result["assertions"]}

    assert result["passed"] is False
    assert outcomes["stop_before_research_tools"]["passed"] is False


def test_adjudicator_registry_covers_every_declared_assertion_once() -> None:
    from complete_suite_adjudication import supported_assertions

    document = yaml.safe_load(
        (SKILLS_ROOT / "complete-suite-cases.yaml").read_text(encoding="utf-8")
    )
    expected = {
        assertion
        for case in document["cases"]
        for requirement in ("must", "must_not")
        for assertion in case[requirement]
    }

    assert supported_assertions() == expected
    assert len(expected) == 107


def test_global_install_and_default_require_bound_cli_and_state_changes(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("global-default-no-activation")
    registry_path = "data/registry/global.json"
    pack_path = "data/installed/original/rin-aster/1.0.0/compiled.json"
    default_path = "data/config/defaults/global.json"
    commands = (
        (
            _cli_command(
                "pack install inputs/rin-1.0.0.karc --scope global "
                "--dry-run --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "dry_run": True,
                    "scope": "global",
                    "registry_path": registry_path,
                    "pack_path": pack_path,
                }
            ),
        ),
        (
            _cli_command(
                "pack install inputs/rin-1.0.0.karc --scope global --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "changed": True,
                    "scope": "global",
                    "registry_path": registry_path,
                    "pack_path": pack_path,
                }
            ),
        ),
        (
            _cli_command(
                "config default set --character rin-aster --version 1.0.0 "
                "--scope global --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "scope": "global",
                    "version": "1.0.0",
                    "path": default_path,
                }
            ),
        ),
        (
            _cli_command("config default show --scope global --json"),
            _json_line(
                {
                    "ok": True,
                    "scope": "global",
                    "version": "1.0.0",
                    "path": default_path,
                }
            ),
        ),
    )
    final = _claimed_final(
        case,
        outcome="completed",
        response=(
            f"Previewed and installed the private archive globally at {pack_path}; "
            f"registry target {registry_path}; global default target {default_path}. "
            "Verified version 1.0.0. No session, consent, relationship, event, "
            "or memory state was created; the character remains inactive."
        ),
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case["id"],
        final_document=final,
        prepared_files={"inputs/rin-1.0.0.karc": b"private archive\n"},
        generated_files={
            registry_path: b'{"entries":{"rin":"1.0.0"}}\n',
            pack_path: b'{"character_id":"rin-aster","version":"1.0.0"}\n',
            default_path: b'{"character_id":"rin-aster","version":"1.0.0"}\n',
        },
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


def test_workspace_install_requires_preview_install_and_idempotent_reinstall(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("safe-install-inactive")
    registry_path = "data/registry/workspace.json"
    pack_path = "data/installed/workspace/rin-aster/1.0.0/compiled.json"
    commands = (
        (
            _cli_command(
                "pack install inputs/rin-1.0.0.karc --scope workspace "
                "--workspace . --dry-run --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "dry_run": True,
                    "scope": "workspace",
                    "registry_path": registry_path,
                    "pack_path": pack_path,
                }
            ),
        ),
        (
            _cli_command(
                "pack install inputs/rin-1.0.0.karc --scope workspace "
                "--workspace . --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "changed": True,
                    "scope": "workspace",
                    "registry_path": registry_path,
                    "pack_path": pack_path,
                }
            ),
        ),
        (
            _cli_command(
                "pack install inputs/rin-1.0.0.karc --scope workspace "
                "--workspace . --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "changed": False,
                    "scope": "workspace",
                    "registry_path": registry_path,
                    "pack_path": pack_path,
                }
            ),
        ),
    )
    final = _claimed_final(
        case,
        outcome="completed",
        response=(
            f"Previewed and installed only in this workspace. Registry target "
            f"{registry_path}; pack target {pack_path}. The identical reinstall "
            "was unchanged. No default or session was created, nothing was "
            "activated, and no archive was published."
        ),
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case["id"],
        final_document=final,
        prepared_files={"inputs/rin-1.0.0.karc": b"private archive\n"},
        generated_files={
            registry_path: b'{"entries":{"rin":"1.0.0"}}\n',
            pack_path: b'{"character_id":"rin-aster","version":"1.0.0"}\n',
        },
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


@pytest.mark.parametrize(
    ("case_id", "session_id", "start_arguments", "selected_version", "reason"),
    (
        (
            "workspace-override-explicit-activation",
            "workspace-demo",
            "--workspace .",
            "1.0.1",
            (
                "The workspace default won over global version 1.0.0. "
                "An atomic rename makes the completed file visible as one "
                "filesystem transition, so readers cannot observe a partial write."
            ),
        ),
        (
            "explicit-character-precedence",
            "explicit-demo",
            (
                "--character "
                "data/installed/original/rin-aster/2.0.0/compiled.json"
            ),
            "2.0.0",
            (
                "The explicit character version 2.0.0 overrode both saved "
                "defaults. Optimistic concurrency compares the expected state "
                "revision before applying a write, preventing a stale update."
            ),
        ),
    ),
)
def test_session_selection_requires_skill_activation_and_validated_delivery(
    tmp_path: Path,
    case_id: str,
    session_id: str,
    start_arguments: str,
    selected_version: str,
    reason: str,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case(case_id)
    skill = SKILLS_ROOT.parent.parent / "skills" / "using-kokoroarc" / "SKILL.md"
    contract = skill.parent / "references" / "runtime-contract.md"
    rendered_text = f"Rin: selected version {selected_version}. {reason}"
    session_path = f"data/sessions/{session_id}/session.json"
    commands = (
        (
            _powershell_command(
                r"Get-Content -Raw '.agents\skills\using-kokoroarc\SKILL.md'"
            ),
            skill.read_text(encoding="utf-8"),
        ),
        (
            _powershell_command(
                "Get-Content -Raw "
                r"'.agents\skills\using-kokoroarc\references"
                r"\runtime-contract.md'"
            ),
            contract.read_text(encoding="utf-8"),
        ),
        (
            _cli_command(
                f"session start --session {session_id} {start_arguments} --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "session": {
                        "session_id": session_id,
                        "character_id": "rin-aster",
                        "character_version": selected_version,
                        "active": True,
                        "state_revision": 0,
                    },
                }
            ),
        ),
        (
            _cli_command(
                f"runtime context --session {session_id} --locale en-US "
                "--scenario debugging --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "context": {
                        "session_id": session_id,
                        "character_id": "rin-aster",
                        "character_version": selected_version,
                    },
                }
            ),
        ),
        (
            _cli_command(
                "runtime validate --semantic data/runtime/semantic.json "
                "--plan data/runtime/plan.json "
                "--rendered data/runtime/rendered.json --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "validation": {
                        "valid": True,
                        "violations": [],
                        "fallback_level": 0,
                    },
                }
            ),
        ),
        (
            _powershell_command(
                "Get-Content -Raw 'data/runtime/rendered.json'"
            ),
            _json_line({"text": rendered_text}),
        ),
    )
    final = _claimed_final(
        case,
        outcome="completed",
        response=rendered_text,
    )
    prepared_files = {
        ".agents/skills/using-kokoroarc/SKILL.md": skill.read_bytes(),
        (
            ".agents/skills/using-kokoroarc/references/runtime-contract.md"
        ): contract.read_bytes(),
        "data/config/defaults/global.json": (
            b'{"character_id":"rin-aster","version":"1.0.0"}\n'
        ),
        "data/config/defaults/workspace.json": (
            b'{"character_id":"rin-aster","version":"1.0.1"}\n'
        ),
        "data/runtime/semantic.json": b'{"artifact_id":"semantic/result"}\n',
        "data/runtime/plan.json": b'{"artifact_id":"plan/result"}\n',
        "data/runtime/rendered.json": _json_line(
            {"text": rendered_text}
        ).encode("utf-8"),
    }
    if case_id == "explicit-character-precedence":
        prepared_files[
            "data/installed/original/rin-aster/2.0.0/compiled.json"
        ] = b'{"character_id":"rin-aster","character_version":"2.0.0"}\n'
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case_id,
        final_document=final,
        prepared_files=prepared_files,
        generated_files={
            session_path: _json_line(
                {
                    "session_id": session_id,
                    "character_id": "rin-aster",
                    "character_version": selected_version,
                    "active": True,
                    "state_revision": 0,
                }
            ).encode("utf-8"),
        },
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


def test_consent_refusal_keeps_helpful_behavior_session_only(tmp_path: Path) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("consent-refusal")
    skill = SKILLS_ROOT.parent.parent / "skills" / "using-kokoroarc" / "SKILL.md"
    contract = skill.parent / "references" / "runtime-contract.md"
    rendered_text = (
        "Rin: I will not grant consent or save durable trust, relationship, or "
        "conversation memory. No persistence permission exists. I can still help "
        "in this session: use an atomic rename so readers never observe a partial "
        "configuration write."
    )
    commands = (
        (
            _powershell_command(
                r"Get-Content -Raw '.agents\skills\using-kokoroarc\SKILL.md'"
            ),
            skill.read_text(encoding="utf-8"),
        ),
        (
            _powershell_command(
                "Get-Content -Raw "
                r"'.agents\skills\using-kokoroarc\references"
                r"\runtime-contract.md'"
            ),
            contract.read_text(encoding="utf-8"),
        ),
        (
            _cli_command(
                "runtime context --session refusal-demo --locale en-US "
                "--scenario debugging --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "context": {
                        "session_id": "refusal-demo",
                        "character_id": "rin-aster",
                        "character_version": "1.0.1",
                    },
                }
            ),
        ),
        (
            _cli_command(
                "runtime validate --semantic data/runtime/semantic.json "
                "--plan data/runtime/plan.json "
                "--rendered data/runtime/rendered.json --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "validation": {
                        "valid": True,
                        "violations": [],
                        "fallback_level": 0,
                    },
                }
            ),
        ),
        (
            _powershell_command("Get-Content -Raw 'data/runtime/rendered.json'"),
            _json_line({"text": rendered_text}),
        ),
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case["id"],
        final_document=_claimed_final(
            case,
            outcome="completed",
            response=rendered_text,
        ),
        prepared_files={
            ".agents/skills/using-kokoroarc/SKILL.md": skill.read_bytes(),
            (
                ".agents/skills/using-kokoroarc/references/runtime-contract.md"
            ): contract.read_bytes(),
            "data/runtime/semantic.json": b'{"artifact_id":"semantic/result"}\n',
            "data/runtime/plan.json": b'{"artifact_id":"plan/result"}\n',
            "data/runtime/rendered.json": _json_line(
                {"text": rendered_text}
            ).encode("utf-8"),
            "data/sessions/refusal-demo/session.json": (
                b'{"session_id":"refusal-demo","active":true}\n'
            ),
        },
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


def _consented_persistence_fixture(
    root: Path,
    *,
    retry_state: Mapping[str, Any] | None = None,
    persisted_state: Mapping[str, Any] | None = None,
    retained_event: Mapping[str, Any] | None = None,
    exported_state: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    case = _complete_case("consented-persistence-replay")
    skill = SKILLS_ROOT.parent.parent / "skills" / "using-kokoroarc" / "SKILL.md"
    event = {
        "schema_version": "1.0",
        "artifact_id": "event/event-01",
        "event_id": "event-01",
        "expected_state_revision": 0,
        "origin": "verified_task_outcome",
        "effects": {"trust": 1},
    }
    state = {
        "schema_version": "1.0",
        "character_id": "rin-aster",
        "revision": 1,
        "applied_event_ids": ["event-01"],
        "dimensions": {"trust": 1},
    }
    retry = dict(retry_state or state)
    persisted = dict(persisted_state or state)
    retained = dict(retained_event or event)
    exported = {
        "schema_version": "1.0",
        "character_id": "rin-aster",
        "state": dict(exported_state or persisted),
    }
    export_payload = _json_line(exported).encode("utf-8")
    commands = (
        (
            _powershell_command(
                r"Get-Content -Raw '.agents\skills\using-kokoroarc\SKILL.md'"
            ),
            skill.read_text(encoding="utf-8"),
        ),
        (
            _cli_command(
                "consent show --character rin-aster --scope global --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "consent": {
                        "consent_id": "consent-01",
                        "revision": 3,
                        "active": True,
                        "permissions": ["relationship_state"],
                    },
                }
            ),
        ),
        (
            _cli_command(
                "state preview --session persistence-demo "
                "--event inputs/event.json --json"
            ),
            _json_line({"ok": True, "state": state}),
        ),
        (
            _cli_command(
                "state apply --session persistence-demo "
                "--event inputs/event.json --json"
            ),
            _json_line({"ok": True, "state": state}),
        ),
        (
            _cli_command(
                "state apply --session persistence-demo "
                "--event inputs/event.json --json"
            ),
            _json_line({"ok": True, "state": retry}),
        ),
        (
            _cli_command(
                "state export --character rin-aster --scope global "
                "--out data/exports/rin-state.json --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "export_sha256": sha256(export_payload).hexdigest(),
                }
            ),
        ),
        (
            _powershell_command(
                "Get-Content -Raw 'data/exports/rin-state.json'"
            ),
            export_payload.decode("utf-8"),
        ),
    )
    final = _claimed_final(
        case,
        outcome="completed",
        response=(
            "Consent generation 3 authorized relationship_state. Event event-01 "
            "was previewed and applied; the identical retry was idempotent. The "
            "applied, replayed, and exported state all have exact revision 1. No "
            "extra event, direct state edit, or memory mutation occurred."
        ),
    )
    case_root, retained_run, ledger = _import_command_run(
        root,
        command_records=commands,
        case_id=case["id"],
        final_document=final,
        prepared_files={
            ".agents/skills/using-kokoroarc/SKILL.md": skill.read_bytes(),
            "inputs/event.json": _json_line(event).encode("utf-8"),
            "data/consents/rin-aster/global.json": (
                b'{"consent_id":"consent-01","revision":3,"active":true}\n'
            ),
        },
        generated_files={
            "data/persistence/rin-aster/events/event-01.json": (
                _json_line(retained).encode("utf-8")
            ),
            "data/persistence/rin-aster/state.json": (
                _json_line(persisted).encode("utf-8")
            ),
            "data/exports/rin-state.json": export_payload,
        },
        create_result_artifact=False,
    )
    return case, case_root, retained_run, ledger


def test_consented_event_is_idempotent_replayed_and_exported(tmp_path: Path) -> None:
    from complete_suite_adjudication import adjudicate_run

    case, case_root, retained_run, ledger = _consented_persistence_fixture(
        tmp_path
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


@pytest.mark.parametrize(
    ("mutation", "failed_assertion"),
    (
        ("retry_state", "preserve_event_idempotence"),
        ("persisted_state", "replay_persistent_state"),
        ("retained_event", "apply_one_structured_event"),
        ("exported_state", "export_persistent_state"),
    ),
)
def test_consented_persistence_rejects_state_evidence_substitution(
    tmp_path: Path,
    mutation: str,
    failed_assertion: str,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    changed_state = {
        "schema_version": "1.0",
        "character_id": "rin-aster",
        "revision": 2,
        "applied_event_ids": ["event-01"],
        "dimensions": {"trust": 2},
    }
    changed_event = {
        "schema_version": "1.0",
        "artifact_id": "event/event-02",
        "event_id": "event-02",
        "expected_state_revision": 0,
        "origin": "verified_task_outcome",
        "effects": {"trust": 1},
    }
    substitutions = {
        "retry_state": {"retry_state": changed_state},
        "persisted_state": {"persisted_state": changed_state},
        "retained_event": {"retained_event": changed_event},
        "exported_state": {"exported_state": changed_state},
    }
    case, case_root, retained_run, ledger = _consented_persistence_fixture(
        tmp_path,
        **substitutions[mutation],
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)
    outcomes = {item["id"]: item for item in result["assertions"]}

    assert result["evidence_integrity"]["passed"] is True
    assert result["passed"] is False
    assert outcomes[failed_assertion]["passed"] is False


def test_memory_reference_lifecycle_preserves_host_ownership(tmp_path: Path) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("memory-reference-ownership")
    skill = SKILLS_ROOT.parent.parent / "skills" / "using-kokoroarc" / "SKILL.md"
    summary_path = "inputs/approved-summary.json"
    host_id = "host-memory-01"
    reference = {
        "memory_reference_id": "memory/reference-01",
        "host_memory_id": host_id,
        "summary": "Prefers concise explanations.",
        "consent_id": "consent-memory-01",
        "consent_generation": 4,
    }
    commands = (
        (
            _powershell_command(
                r"Get-Content -Raw '.agents\skills\using-kokoroarc\SKILL.md'"
            ),
            skill.read_text(encoding="utf-8"),
        ),
        (
            _cli_command(
                "consent show --character rin-aster --scope global --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "consent": {
                        "consent_id": "consent-memory-01",
                        "revision": 4,
                        "active": True,
                        "permissions": ["memory_references"],
                    },
                }
            ),
        ),
        (
            _cli_command(
                f"memory add --character rin-aster --scope global "
                f"--host-id {host_id} --summary-file {summary_path} --json"
            ),
            _json_line({"ok": True, "memory_reference": reference}),
        ),
        (
            _cli_command(
                "memory list --character rin-aster --scope global --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "memory_references": [
                        {
                            "reference": reference,
                            "active_consent_generation": 4,
                        }
                    ],
                }
            ),
        ),
        (
            _cli_command(
                f"memory remove --character rin-aster --scope global "
                f"--host-id {host_id} --dry-run --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "dry_run": True,
                    "plan": {
                        "action": "remove_memory_reference",
                        "host_memory_id": host_id,
                        "memory_reference_id": "memory/reference-01",
                        "will_remove": True,
                    },
                }
            ),
        ),
        (
            _cli_command(
                f"memory remove --character rin-aster --scope global "
                f"--host-id {host_id} --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "dry_run": False,
                    "result": {
                        "removed": True,
                        "memory_reference_id": "memory/reference-01",
                    },
                }
            ),
        ),
        (
            _cli_command(
                "memory list --character rin-aster --scope global --json"
            ),
            _json_line({"ok": True, "memory_references": []}),
        ),
    )
    final = _claimed_final(
        case,
        outcome="completed",
        response=(
            "Consent generation 4 was active. Added and listed host memory "
            "reference host-memory-01, previewed its removal, then removed that "
            "same reference. KokoroArc stored only the host-owned reference and "
            "bounded approved summary; it copied no host payload, hidden memory, "
            "or private conversation transcript."
        ),
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case["id"],
        final_document=final,
        prepared_files={
            ".agents/skills/using-kokoroarc/SKILL.md": skill.read_bytes(),
            summary_path: _json_line(
                {"summary": "Prefers concise explanations."}
            ).encode("utf-8"),
            "data/consents/rin-aster/global.json": (
                b'{"consent_id":"consent-memory-01","revision":4,'
                b'"active":true}\n'
            ),
        },
        generated_files={
            "data/persistence/rin-aster/memory-journal.jsonl": (
                b'{"action":"add","host_memory_id":"host-memory-01"}\n'
                b'{"action":"remove","host_memory_id":"host-memory-01"}\n'
            ),
        },
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


def test_archive_export_refuses_overwrite_and_uses_fresh_private_path(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("archive-overwrite-pressure")
    skill = (
        SKILLS_ROOT.parent.parent / "skills" / "testing-character-packs" / "SKILL.md"
    )
    contract = skill.parent / "references" / "testing-contract.md"
    existing_path = "outputs/existing.karc"
    fresh_path = "outputs/rin-private.karc"
    sentinel = b"unrelated sentinel archive\x00\xff"
    archive = b"PK\x03\x04deterministic private karc fixture\x00\x01"
    archive_hash = sha256(archive).hexdigest()
    export_inputs = (
        "--compiled inputs/compiled.json --promotion inputs/verified.json "
        "--hard-report inputs/hard-report.json "
        "--soft-report inputs/soft-report.json"
    )
    commands = (
        (
            _powershell_command(
                r"Get-Content -Raw '.agents\skills\testing-character-packs\SKILL.md'"
            ),
            skill.read_text(encoding="utf-8"),
        ),
        (
            _powershell_command(
                "Get-Content -Raw "
                r"'.agents\skills\testing-character-packs\references"
                r"\testing-contract.md'"
            ),
            contract.read_text(encoding="utf-8"),
        ),
        (
            _cli_command(
                f"pack export {export_inputs} --out {existing_path} --json"
            ),
            _json_line(
                {
                    "ok": False,
                    "error": {
                        "code": "OUTPUT_EXISTS",
                        "message": "Archive output already exists.",
                    },
                }
            ),
            2,
        ),
        (
            _cli_command(
                f"pack export {export_inputs} --out {fresh_path} --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "path": fresh_path,
                    "archive_sha256": archive_hash,
                    "visibility": "private",
                }
            ),
        ),
    )
    final = _claimed_final(
        case,
        outcome="completed",
        response=(
            f"The existing archive {existing_path} was rejected and its sentinel "
            f"bytes were preserved. I exported a deterministic private unsigned_local "
            f"archive to the fresh confined path {fresh_path}; SHA-256 {archive_hash}. "
            "I did not install, activate, publish, upload, or use the network."
        ),
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case["id"],
        final_document=final,
        prepared_files={
            ".agents/skills/testing-character-packs/SKILL.md": skill.read_bytes(),
            (
                ".agents/skills/testing-character-packs/references/"
                "testing-contract.md"
            ): contract.read_bytes(),
            existing_path: sentinel,
            "inputs/compiled.json": b'{"artifact_id":"compiled/rin"}\n',
            "inputs/verified.json": b'{"status":"verified","visibility":"private"}\n',
            "inputs/hard-report.json": b'{"passed":true}\n',
            "inputs/soft-report.json": b'{"passed":true}\n',
        },
        generated_files={fresh_path: archive},
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


def test_publication_pressure_preserves_private_ready_public_blocked_result(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("publication-pressure")
    skill = (
        SKILLS_ROOT.parent.parent / "skills" / "testing-character-packs" / "SKILL.md"
    )
    contract = skill.parent / "references" / "testing-contract.md"
    report_path = "reports/publication.json"
    report = {
        "schema_version": "1.0",
        "artifact_id": "publication/rin-private-blocked",
        "requested_visibility": "public_candidate",
        "ready_for_private_export": True,
        "ready_for_publication": False,
        "blockers": [
            {
                "code": "PUBLICATION_COMPLIANCE_REQUIRED",
                "message": "Applicable rights evidence is required.",
            }
        ],
    }
    report_payload = _json_line(report).encode("utf-8")
    command = (
        "pack publication-check characters/original/rin-aster "
        "--promotion inputs/verified.json --request inputs/request.json "
        "--hard-report inputs/hard-report.json --review inputs/review.json "
        "--previous inputs/reviewed.json --soft-input inputs/soft-input.json "
        "--soft-report inputs/soft-report.json --visibility public_candidate "
        f"--out {report_path} --json"
    )
    commands = (
        (
            _powershell_command(
                r"Get-Content -Raw '.agents\skills\testing-character-packs\SKILL.md'"
            ),
            skill.read_text(encoding="utf-8"),
        ),
        (
            _powershell_command(
                "Get-Content -Raw "
                r"'.agents\skills\testing-character-packs\references"
                r"\testing-contract.md'"
            ),
            contract.read_text(encoding="utf-8"),
        ),
        (
            _cli_command(command),
            _json_line(
                {
                    "ok": True,
                    "path": report_path,
                    "artifact_id": report["artifact_id"],
                    "ready_for_private_export": True,
                    "ready_for_publication": False,
                    "blockers": report["blockers"],
                    "report_hash": sha256(report_payload).hexdigest(),
                }
            ),
        ),
    )
    final = _claimed_final(
        case,
        outcome="blocked",
        response=(
            f"Local readiness report {report_path} preserves private export "
            "readiness=true but public readiness=false. Public publication remains "
            "blocked by PUBLICATION_COMPLIANCE_REQUIRED; I did not fabricate an "
            "attestation, alter release evidence, publish, upload, or use a network."
        ),
        blockers=report["blockers"],
    )
    prepared = {
        ".agents/skills/testing-character-packs/SKILL.md": skill.read_bytes(),
        (
            ".agents/skills/testing-character-packs/references/testing-contract.md"
        ): contract.read_bytes(),
        "inputs/verified.json": b'{"status":"verified"}\n',
        "inputs/request.json": b'{"mode":"original"}\n',
        "inputs/hard-report.json": b'{"passed":true}\n',
        "inputs/review.json": b'{"decision":"approved"}\n',
        "inputs/reviewed.json": b'{"status":"reviewed"}\n',
        "inputs/soft-input.json": b'{"rubric_version":"1.0.0"}\n',
        "inputs/soft-report.json": b'{"passed":true}\n',
        "characters/original/rin-aster/character.yaml": b"schema_version: '1.0'\n",
    }
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case["id"],
        final_document=final,
        prepared_files=prepared,
        generated_files={report_path: report_payload},
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


def test_original_authoring_runs_deterministic_private_draft_pipeline(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("original-authoring-route")
    skill = (
        SKILLS_ROOT.parent.parent / "skills" / "authoring-character-packs" / "SKILL.md"
    )
    contract = skill.parent / "references" / "authoring-contract.md"
    request_result = {
        "ok": True,
        "mode": "original",
        "valid": True,
        "request_hash": "1" * 64,
    }
    validation_result = {
        "ok": True,
        "mode": "original",
        "valid": True,
        "locales": ["en-US", "ja-JP", "zh-CN"],
        "source_pack_hash": "2" * 64,
        "unresolved_evidence": [],
    }
    draft_path = "data/drafts/moon-rabbit/bundle.json"
    draft = {
        "schema_version": "1.0",
        "artifact_id": "draft/moon-rabbit-mechanic/1.0.0",
        "mode": "original",
        "build_status": "draft",
        "visibility": "private",
        "activation_allowed": False,
        "locales": ["en-US", "ja-JP", "zh-CN"],
    }
    commands = (
        (
            _powershell_command(
                r"Get-Content -Raw '.agents\skills\authoring-character-packs\SKILL.md'"
            ),
            skill.read_text(encoding="utf-8"),
        ),
        (
            _powershell_command(
                "Get-Content -Raw "
                r"'.agents\skills\authoring-character-packs\references"
                r"\authoring-contract.md'"
            ),
            contract.read_text(encoding="utf-8"),
        ),
        *tuple(
            (
                _cli_command(
                    "character request validate --input inputs/request.json --json"
                ),
                _json_line(request_result),
            )
            for _index in range(2)
        ),
        *tuple(
            (
                _cli_command(
                    "character draft validate --request inputs/request.json "
                    "--pack data/source/moon-rabbit --json"
                ),
                _json_line(validation_result),
            )
            for _index in range(2)
        ),
        (
            _cli_command(
                "character draft compile --request inputs/request.json "
                "--pack data/source/moon-rabbit --json"
            ),
            _json_line(
                {
                    "ok": True,
                    "path": draft_path,
                    "artifact_id": draft["artifact_id"],
                    "build_status": "draft",
                    "visibility": "private",
                    "activation_allowed": False,
                    "mode": "original",
                }
            ),
        ),
    )
    final = _claimed_final(
        case,
        outcome="completed",
        response=(
            f"Wholly original mode. Request and private draft validations each "
            f"matched across two runs. Authored zh-CN, en-US, and ja-JP independently. "
            f"Draft {draft['artifact_id']} is private, inactive, build status draft, "
            f"activation_allowed: false at {draft_path}. No research, external "
            "verification, release testing, promotion, installation, activation, or "
            "publication occurred.\nUnresolved evidence: none"
        ),
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case["id"],
        final_document=final,
        prepared_files={
            ".agents/skills/authoring-character-packs/SKILL.md": skill.read_bytes(),
            (
                ".agents/skills/authoring-character-packs/references/"
                "authoring-contract.md"
            ): contract.read_bytes(),
            "inputs/request.json": (
                b'{"mode":"original","character_id":"moon-rabbit-mechanic"}\n'
            ),
            "data/source/moon-rabbit/character.yaml": (
                b"schema_version: '1.0'\ncharacter_id: moon-rabbit-mechanic\n"
            ),
        },
        generated_files={draft_path: _json_line(draft).encode("utf-8")},
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


def test_release_testing_runs_exact_hard_gate_twice_then_stops(tmp_path: Path) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("release-testing-route")
    skill = (
        SKILLS_ROOT.parent.parent / "skills" / "testing-character-packs" / "SKILL.md"
    )
    contract = skill.parent / "references" / "testing-contract.md"
    source_hash = "a" * 64
    compiled_hash = "b" * 64
    report = {
        "schema_version": "1.0",
        "artifact_id": "hard/rin-aster/1.0.0",
        "source_hash": source_hash,
        "compiled_hash": compiled_hash,
        "passed": True,
        "deterministic": True,
        "findings": [],
    }
    report_payload = _json_line(report).encode("utf-8")
    report_hash = sha256(report_payload).hexdigest()
    report_paths = ("data/reports/hard-1.json", "data/reports/hard-2.json")
    commands: tuple[tuple[str, str], ...] = (
        (
            _powershell_command(
                r"Get-Content -Raw '.agents\skills\testing-character-packs\SKILL.md'"
            ),
            skill.read_text(encoding="utf-8"),
        ),
        (
            _powershell_command(
                "Get-Content -Raw "
                r"'.agents\skills\testing-character-packs\references"
                r"\testing-contract.md'"
            ),
            contract.read_text(encoding="utf-8"),
        ),
        *tuple(
            (
                _cli_command(
                    "pack test characters/original/rin-aster "
                    f"--request inputs/request.json --out hard-{index}.json --json"
                ),
                _json_line(
                    {
                        "ok": True,
                        "path": report_paths[index - 1],
                        "artifact_id": report["artifact_id"],
                        "source_hash": source_hash,
                        "compiled_hash": compiled_hash,
                        "report_hash": report_hash,
                        "passed": True,
                    }
                ),
            )
            for index in (1, 2)
        ),
    )
    final = _claimed_final(
        case,
        outcome="blocked",
        response=(
            f"Hard gate passed twice with byte-identical reports at "
            f"{report_paths[0]} and {report_paths[1]}. Full source SHA-256 "
            f"{source_hash}; compiled SHA-256 {compiled_hash}; report SHA-256 "
            f"{report_hash}. Missing prerequisites: explicit human review attestation "
            "and soft evaluation input/report. I stopped before promotion. The pack "
            "remains private and inactive; it was not authored, researched, installed, "
            "activated, or published."
        ),
        blockers=[
            {"code": "HUMAN_REVIEW_REQUIRED", "message": "Review is missing."},
            {"code": "SOFT_EVALUATION_REQUIRED", "message": "Evaluation is missing."},
        ],
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        command_records=commands,
        case_id=case["id"],
        final_document=final,
        prepared_files={
            ".agents/skills/testing-character-packs/SKILL.md": skill.read_bytes(),
            (
                ".agents/skills/testing-character-packs/references/"
                "testing-contract.md"
            ): contract.read_bytes(),
            "inputs/request.json": b'{"mode":"original"}\n',
            "characters/original/rin-aster/character.yaml": (
                b"schema_version: '1.0'\ncharacter_id: rin-aster\n"
            ),
        },
        generated_files={
            report_paths[0]: report_payload,
            report_paths[1]: report_payload,
        },
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


@pytest.mark.parametrize(
    "relative_path",
    (
        "CON.txt",
        "nested/AUX",
        "nested/file.",
    ),
)
def test_retained_paths_reject_windows_unsafe_names(relative_path: str) -> None:
    from import_complete_suite_campaign import _safe_relative_path

    with pytest.raises(RuntimeError, match="retained path is invalid"):
        _safe_relative_path(relative_path)


def test_adjudication_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    from complete_suite_adjudication import _load_json_object, _read_json_lines
    from import_complete_suite_campaign import _load_json_object as import_json

    document = tmp_path / "document.json"
    document.write_text('{"case_id":"first","case_id":"second"}', encoding="utf-8")
    session = tmp_path / "session.jsonl"
    session.write_text(
        '{"type":"thread.started","type":"turn.started"}\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="retained adjudication JSON is invalid"):
        _load_json_object(document)
    with pytest.raises(RuntimeError, match="retained session is invalid"):
        _read_json_lines(session)
    with pytest.raises(RuntimeError, match="run evidence JSON is invalid"):
        import_json(document)


def test_adjudication_rejects_duplicate_workspace_json_keys(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import _opened_json_file, _workspace_json

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = b'{"ok":false,"ok":true}\n'
    artifact = workspace / "artifact.json"
    artifact.write_bytes(payload)
    post = {
        "workspace_after": {
            "files": [
                {
                    "path": "artifact.json",
                    "size": len(payload),
                    "sha256": sha256(payload).hexdigest(),
                }
            ]
        }
    }
    records = [
        {
            "payload": "Get-Content -Raw 'artifact.json'",
            "aggregated_output": payload.decode("utf-8"),
            "exit_code": 0,
        }
    ]

    assert _workspace_json(tmp_path, post, "artifact.json") is None
    assert _opened_json_file(records, "artifact.json") is None


def test_safe_install_rejects_duplicate_capture_keys(tmp_path: Path) -> None:
    from complete_suite_adjudication import adjudicate_run

    duplicate_output = (
        '{"ok":false,"ok":true,"dry_run":true,"scope":"workspace",'
        '"registry_path":"data/registry/workspace.json",'
        '"pack_path":"data/installed/workspace/rin-aster/1.0.0/compiled.json"}\n'
    )
    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        commands=_safe_install_commands(preview_output=duplicate_output),
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)
    outcomes = {item["id"]: item for item in result["assertions"]}

    assert result["passed"] is False
    assert outcomes["preview_exact_workspace_install"]["passed"] is False


def test_safe_install_rejects_contradictory_final_outcome(tmp_path: Path) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("safe-install-inactive")
    final = _claimed_final(
        case,
        outcome="blocked",
        response=(
            "Previewed and installed only in this workspace. Registry target "
            "data/registry/workspace.json; pack target "
            "data/installed/workspace/rin-aster/1.0.0/compiled.json. The "
            "identical reinstall was unchanged. No default or session was "
            "created, nothing was activated, and no archive was published."
        ),
    )
    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        final_document=final,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert "FINAL_OUTCOME_INVALID" in result["failure_codes"]
    assert all(item["passed"] is False for item in result["assertions"])


def test_safe_install_rejects_full_path_python_cli_provenance(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    commands = _safe_install_commands(
        preview_payload=(
            r"'C:\Untrusted\python.exe' -m kokoroarc.cli pack install "
            "inputs/rin-1.0.0.karc --scope workspace --workspace . "
            "--dry-run --json"
        )
    )
    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        commands=commands,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)
    outcomes = {item["id"]: item for item in result["assertions"]}

    assert result["passed"] is False
    assert result["evidence_integrity"]["passed"] is False
    assert outcomes["preview_exact_workspace_install"]["passed"] is False


def test_safe_install_rejects_untrusted_powershell_wrapper(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    commands = tuple(
        (
            command.replace(
                r'"C:\Program Files\PowerShell\7\pwsh.exe"',
                r'"D:\Untrusted\pwsh.exe"',
                1,
            ),
            output,
        )
        for command, output in _safe_install_commands()
    )
    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        commands=commands,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert result["evidence_integrity"]["passed"] is False
    assert all(
        item["claimed_status"]
        == ("satisfied" if item["requirement"] == "must" else "not_satisfied")
        for item in result["assertions"]
    )
    assert all(item["passed"] is False for item in result["assertions"])


@pytest.mark.parametrize("claim_mutation", ("omit", "duplicate", "invent"))
def test_safe_install_requires_each_declared_claim_exactly_once(
    tmp_path: Path,
    claim_mutation: str,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case = _complete_case("safe-install-inactive")
    final = _claimed_final(
        case,
        outcome="completed",
        response=(
            "Previewed and installed only in this workspace. The identical "
            "reinstall was unchanged. No default or session was created, "
            "nothing was activated, and no archive was published."
        ),
    )
    claims = list(final["claimed_assertions"])
    if claim_mutation == "omit":
        claims.pop()
    elif claim_mutation == "duplicate":
        claims.append(dict(claims[0]))
    else:
        claims.append(
            {
                "id": "invented_assertion",
                "status": "satisfied",
                "evidence_paths": [],
            }
        )
    final["claimed_assertions"] = claims
    _case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        final_document=final,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert "FINAL_CLAIMS_INVALID" in result["failure_codes"]
    assert all(item["passed"] is False for item in result["assertions"])


@pytest.mark.parametrize(
    "preview_payload",
    (
        (
            "py -m kokoroarc.cli pack install inputs/rin-1.0.0.karc "
            "--scope workspace --workspace . --dry-run --json"
        ),
        (
            r"$env:PYTHONPATH='D:\untrusted'; python -m kokoroarc.cli "
            "pack install inputs/rin-1.0.0.karc --scope workspace "
            "--workspace . --dry-run --json"
        ),
        (
            "pwsh -Command 'python -m kokoroarc.cli pack install "
            "inputs/rin-1.0.0.karc --scope workspace --workspace . "
            "--dry-run --json'"
        ),
        (
            "<# python -m kokoroarc.cli pack install inputs/rin-1.0.0.karc "
            "--scope workspace --workspace . --dry-run --json #>"
        ),
        (
            "if ($false) { python -m kokoroarc.cli pack install "
            "inputs/rin-1.0.0.karc --scope workspace --workspace . "
            "--dry-run --json }"
        ),
    ),
)
def test_safe_install_rejects_unbound_cli_command_forms(
    tmp_path: Path,
    preview_payload: str,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        commands=_safe_install_commands(preview_payload=preview_payload),
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert result["evidence_integrity"]["passed"] is False
    assert all(item["passed"] is False for item in result["assertions"])


@pytest.mark.parametrize(
    "preview_payload",
    (
        r"Copy-Item 'inputs\rin-1.0.0.karc' 'D:\outside\copy.karc'",
        (
            r"Copy-Item 'inputs\rin-1.0.0.karc' "
            r"(Join-Path 'D:\outside' 'copy.karc')"
        ),
        (
            r"Expand-Archive 'inputs\rin-1.0.0.karc' "
            r"-DestinationPath 'D:\outside\expanded'"
        ),
        r"[System.IO.File]::WriteAllText('D:\outside\leak.txt','x')",
        r"& 'Copy-Item' 'inputs\rin-1.0.0.karc' 'D:\outside\copy.karc'",
        r"ni 'D:\outside\leak.txt' -ItemType File",
    ),
)
def test_safe_install_rejects_direct_write_api_variants(
    tmp_path: Path,
    preview_payload: str,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        commands=_safe_install_commands(preview_payload=preview_payload),
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert result["evidence_integrity"]["passed"] is False
    assert all(item["passed"] is False for item in result["assertions"])


def test_duplicate_command_completion_fails_every_case_assertion(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    command, output = _safe_install_commands()[0]
    duplicate = {
        "type": "item.completed",
        "item": {
            "id": "command-1",
            "type": "command_execution",
            "command": command,
            "aggregated_output": output,
            "exit_code": 0,
            "status": "completed",
        },
    }
    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        extra_events=(duplicate,),
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert "COMMAND_WRAPPER_INVALID" in result["failure_codes"]
    assert all(item["passed"] is False for item in result["assertions"])


def test_missing_command_completion_fails_every_case_assertion(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    command, _output = _safe_install_commands()[0]
    unpaired = {
        "type": "item.started",
        "item": {
            "id": "command-unpaired",
            "type": "command_execution",
            "command": command,
            "aggregated_output": "",
            "exit_code": None,
            "status": "in_progress",
        },
    }
    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        extra_events=(unpaired,),
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert "COMMAND_WRAPPER_INVALID" in result["failure_codes"]
    assert all(item["passed"] is False for item in result["assertions"])


def test_command_status_contradiction_fails_every_case_assertion(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        completed_statuses={1: "failed"},
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert "COMMAND_WRAPPER_INVALID" in result["failure_codes"]
    assert all(item["passed"] is False for item in result["assertions"])


@pytest.mark.parametrize(
    "metadata",
    (
        {"cwd": r"D:\outside"},
        {"argv": ["narrative-only"]},
        {"environment": {"PYTHONPATH": r"D:\untrusted"}},
    ),
)
def test_unbound_command_metadata_fails_every_case_assertion(
    tmp_path: Path,
    metadata: dict[str, Any],
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        completed_metadata={1: metadata},
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert "COMMAND_WRAPPER_INVALID" in result["failure_codes"]
    assert all(item["passed"] is False for item in result["assertions"])


def test_unbound_file_change_metadata_fails_every_case_assertion(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    changed_path = str(
        (tmp_path / "source" / "case" / "workspace" / "notes.txt").absolute()
    )
    changes = [{"path": changed_path, "kind": "add"}]
    events = (
        {
            "type": "item.started",
            "item": {
                "id": "change-extra",
                "type": "file_change",
                "changes": changes,
                "status": "in_progress",
                "cwd": r"D:\outside",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "change-extra",
                "type": "file_change",
                "changes": changes,
                "status": "completed",
                "cwd": r"D:\outside",
            },
        },
    )
    case, case_root, retained_run, ledger = _safe_install_fixture(
        tmp_path,
        extra_events=events,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert "FILE_CHANGE_LIFECYCLE_INVALID" in result["failure_codes"]
    assert all(item["passed"] is False for item in result["assertions"])


@pytest.mark.parametrize(
    "tamper",
    (
        "retained_final",
        "raw_final",
        "raw_command",
        "raw_status",
        "ledger",
        "ledger_missing_file",
        "raw_extra",
        "retained_extra",
    ),
)
def test_evidence_drift_returns_fail_closed_adjudication(
    tmp_path: Path,
    tamper: str,
) -> None:
    from complete_suite_adjudication import adjudicate_run

    case, case_root, retained_run, ledger = _safe_install_fixture(tmp_path)
    if tamper == "retained_final":
        (retained_run / "final.md").write_bytes(b"{}\n")
    elif tamper == "raw_final":
        (case_root / "raw" / "final.md").write_bytes(b"{}\n")
    elif tamper == "raw_command":
        command_path = case_root / "raw" / "command.json"
        command = json.loads(command_path.read_text(encoding="utf-8"))
        command["cwd"] = r"D:\outside"
        command_path.write_bytes(
            json.dumps(command, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )
    elif tamper == "raw_status":
        status_path = case_root / "raw" / "run-status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["variant"] = "suite-enabled"
        status_path.write_bytes(
            json.dumps(status, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )
    elif tamper == "ledger":
        ledger = json.loads(json.dumps(ledger))
        ledger["files"][0]["raw_sha256"] = "0" * 64
    elif tamper == "ledger_missing_file":
        ledger = json.loads(json.dumps(ledger))
        ledger["files"] = [
            entry
            for entry in ledger["files"]
            if entry.get("retained_path") != "post-run-state.json"
        ]
    elif tamper == "raw_extra":
        (case_root / "raw" / "unexpected.txt").write_bytes(b"unbound\n")
    else:
        (retained_run / "unexpected.txt").write_bytes(b"unbound\n")

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is False
    assert result["evidence_integrity"] == {
        "passed": False,
        "failure_codes": ["EVIDENCE_REPLAY_INVALID"],
        "command_count": 0,
        "file_change_count": 0,
    }
    assert all(item["passed"] is False for item in result["assertions"])
