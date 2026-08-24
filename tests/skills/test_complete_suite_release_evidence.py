from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path, PureWindowsPath
import json
import sys
from types import SimpleNamespace
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


def test_authenticated_workspace_reader_uses_captured_bytes_after_live_mutation(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_command_policy as command_policy

    payload = b'{"status":"authenticated"}'
    relative = "outputs/result.json"
    target = tmp_path / "workspace" / "outputs" / "result.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b'{"status":"forged"}')
    post = {
        "workspace_after": {
            "files": [
                {
                    "path": relative,
                    "sha256": sha256(payload).hexdigest(),
                    "size": len(payload),
                }
            ]
        }
    }
    capture = command_policy._AuthenticatedPostFilesystemCapture(
        ((r"workspace\outputs\result.json", payload),)
    )

    assert adjudication._workspace_bytes(
        tmp_path,
        post,
        relative,
        authenticated_files=capture,
    ) == payload
    assert adjudication._workspace_json(
        tmp_path,
        post,
        relative,
        authenticated_files=capture,
    ) == {"status": "authenticated"}


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
    generated_directories: tuple[str, ...] = (),
    completed_statuses: Mapping[int, str] | None = None,
    completed_metadata: Mapping[int, Mapping[str, Any]] | None = None,
    operation_artifacts: Mapping[str, bytes] | None = None,
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
            for relative in generated_directories:
                workspace.joinpath(*relative.split("/")).mkdir(
                    parents=True,
                    exist_ok=True,
                )
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
    if operation_artifacts is not None:
        raw_root = case_root / "raw"
        for name, payload in operation_artifacts.items():
            (raw_root / name).write_bytes(payload)
    retained_run = root / "retained" / variant / case_id
    retained_run.mkdir(parents=True)
    ledger = retain_run_evidence(
        case_root,
        retained_run,
        item,
        operation_artifacts=operation_artifacts,
    )
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


def _registered_provenance_v1_bundle(tmp_path: Path):
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import run_complete_suite_campaign as runner
    from test_complete_suite_cli_binding import (
        _bind,
        _make_case,
        _operational_spec,
        _pack_list_document,
    )

    bound_case = _make_case(
        cli_binding,
        tmp_path / "session",
        (_operational_spec((_pack_list_document(),)),),
    )
    filesystem, file_changes = _empty_file_change_evidence_for_session(
        tmp_path / "origin",
        bound_case,
        case_id="archive-overwrite-pressure",
    )
    _bind_case_command_filesystem(bound_case, filesystem)
    commands = _bind(cli_binding, bound_case)
    report_bytes = runner.canonical_bytes(
        {"case_id": "archive-overwrite-pressure", "session_id": commands.session_id}
    )
    report_sha256 = sha256(report_bytes).hexdigest()
    bundle = adjudication.bind_run_operation_evidence(
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        report_bytes=report_bytes,
        expected_report_sha256=report_sha256,
        case_id="archive-overwrite-pressure",
        filesystem=filesystem,
        commands=commands,
        file_changes=file_changes,
    )
    return adjudication, report_bytes, report_sha256, bundle


def _task8_bound_operation_inputs(tmp_path: Path) -> dict[str, object]:
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import complete_suite_file_change_policy as file_policy
    import run_complete_suite_campaign as runner
    from test_complete_suite_cli_binding import (
        _bind,
        _make_case,
        _operational_spec,
        _pack_list_document,
    )

    bound_case = _make_case(
        cli_binding,
        tmp_path / "session",
        (_operational_spec((_pack_list_document(),)),),
    )
    filesystem, file_changes = _empty_file_change_evidence_for_session(
        tmp_path / "origin",
        bound_case,
        case_id="archive-overwrite-pressure",
    )
    _bind_case_command_filesystem(bound_case, filesystem)
    commands = _bind(cli_binding, bound_case)
    root_bindings = (
        file_policy.FileChangeRootBinding(
            token="<workspace>",
            literal_root=r"C:\synthetic\workspace",
        ),
    )
    raw_plan = file_policy.decode_file_change_lifecycles(
        bound_case.raw_path.read_bytes(),
        domain="raw",
        root_bindings=root_bindings,
    )
    retained_plan = file_policy.decode_file_change_lifecycles(
        bound_case.retained_path.read_bytes(),
        domain="retained",
        root_bindings=root_bindings,
    )
    report_bytes = runner.canonical_bytes(
        {
            "case_id": "archive-overwrite-pressure",
            "session_id": commands.session_id,
        }
    )
    report_sha256 = sha256(report_bytes).hexdigest()
    integrity = adjudication.bind_run_operation_evidence(
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        report_bytes=report_bytes,
        expected_report_sha256=report_sha256,
        case_id="archive-overwrite-pressure",
        filesystem=filesystem,
        commands=commands,
        file_changes=file_changes,
    )
    return {
        "variant": "baseline",
        "case_id": "archive-overwrite-pressure",
        "command_captures": bound_case.commands,
        "filesystem": filesystem,
        "session_evidence": commands,
        "raw_file_change_plan": raw_plan,
        "retained_file_change_plan": retained_plan,
        "file_changes": file_changes,
        "integrity_evidence": integrity,
    }


def _task8_nonempty_operation_inputs(tmp_path: Path) -> dict[str, object]:
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import run_complete_suite_campaign as runner
    from test_complete_suite_cli_binding import (
        _bind,
        _make_case,
        _operational_spec,
        _prepend_session_events,
        _valid_success_documents,
    )
    from test_complete_suite_file_change_policy import _authorized_setup

    file_policy, context, source, file_session, _target = _authorized_setup(
        tmp_path / "files",
        extra_created=(r"workspace\outputs\draft.json",),
    )
    request_path = r"data\authoring\mika-moongear\request.json"
    documents = _valid_success_documents()
    specs = (
        _operational_spec(
            (documents[("character", "request", "validate")],),
            argvs=(("kokoro", "character", "request", "validate", "--input", request_path, "--json"),),
            event_id="consumer-request",
        ),
        _operational_spec(
            (documents[("character", "draft", "validate")],),
            argvs=(("kokoro", "character", "draft", "validate", "--request", request_path, "--pack", r"data\authoring\mika-moongear", "--json"),),
            event_id="consumer-draft-validate",
        ),
        _operational_spec(
            (documents[("character", "draft", "compile")],),
            argvs=(("kokoro", "character", "draft", "compile", "--request", request_path, "--pack", r"data\authoring\mika-moongear", "--out", r"outputs\draft.json", "--json"),),
            event_id="consumer-draft-compile",
        ),
    )
    bound_case = _make_case(cli_binding, tmp_path / "commands", specs)
    _bind_case_command_filesystem(bound_case, context.filesystem)
    file_events = tuple(
        json.loads(line) for line in file_session.decode("utf-8").splitlines()
    )
    _prepend_session_events(cli_binding, bound_case, file_events)
    commands = _bind(cli_binding, bound_case)
    file_changes = file_policy.authorize_file_change_events(
        bound_case.raw_path.read_bytes(),
        bound_case.retained_path.read_bytes(),
        (source,),
        context=context,
    )
    raw_bindings, retained_bindings = file_policy._bindings_for_sources(
        (source,),
        context=context,
    )
    raw_plan = file_policy.decode_file_change_lifecycles(
        bound_case.raw_path.read_bytes(),
        domain="raw",
        root_bindings=raw_bindings,
    )
    retained_plan = file_policy.decode_file_change_lifecycles(
        bound_case.retained_path.read_bytes(),
        domain="retained",
        root_bindings=retained_bindings,
    )
    report_bytes = runner.canonical_bytes(
        {
            "case_id": "original-authoring-route",
            "session_id": commands.session_id,
        }
    )
    integrity = adjudication.bind_run_operation_evidence(
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        report_bytes=report_bytes,
        expected_report_sha256=sha256(report_bytes).hexdigest(),
        case_id="original-authoring-route",
        filesystem=context.filesystem,
        commands=commands,
        file_changes=file_changes,
    )
    return {
        "variant": "baseline",
        "case_id": "original-authoring-route",
        "command_captures": bound_case.commands,
        "filesystem": context.filesystem,
        "session_evidence": commands,
        "raw_file_change_plan": raw_plan,
        "retained_file_change_plan": retained_plan,
        "file_changes": file_changes,
        "integrity_evidence": integrity,
    }


def test_task8_operation_provenance_serializes_four_closed_canonical_artifacts(
    tmp_path: Path,
) -> None:
    import import_complete_suite_campaign as importer
    import run_complete_suite_campaign as runner

    inputs = _task8_bound_operation_inputs(tmp_path)
    artifacts = importer.build_retained_operation_artifacts(**inputs)

    assert tuple(artifacts) == (
        "command-plans.jsonl",
        "command-plan-ledger.json",
        "file-change-plans.jsonl",
        "file-change-ledger.json",
    )
    assert tuple(importer._DERIVED_FILE_NAMES[-4:]) == tuple(artifacts)
    assert tuple(importer._RAW_RUN_FILES[-4:]) == tuple(
        (name, None, False, False) for name in artifacts
    )
    for name, payload in artifacts.items():
        assert type(payload) is bytes
        if name.endswith(".json"):
            assert payload.endswith(b"\n")
            assert runner.canonical_bytes(json.loads(payload)) + b"\n" == payload

    command_lines = artifacts["command-plans.jsonl"].splitlines()
    pairs = inputs["command_captures"]
    assert isinstance(pairs, tuple)
    assert command_lines == [pair.plan.normalized_plan_bytes for pair in pairs]

    command_ledger = json.loads(artifacts["command-plan-ledger.json"])
    assert set(command_ledger) == {
        "schema_version",
        "variant",
        "case_id",
        "session_id",
        "raw_session_identity",
        "retained_session_identity",
        "raw_session_sha256",
        "retained_session_sha256",
        "raw_bytes_consumed",
        "retained_bytes_consumed",
        "filesystem_evidence",
        "session_evidence",
        "records",
        "record_fold_sha256",
        "retained_evidence_paths",
    }
    assert command_ledger["schema_version"] == (
        "complete-suite-retained-command-plan-ledger-v1"
    )
    assert [record["command_index"] for record in command_ledger["records"]] == [
        0
    ]
    assert command_ledger["records"][0]["plan_line_ordinal"] == 0

    assert artifacts["file-change-plans.jsonl"] == b""
    file_ledger = json.loads(artifacts["file-change-ledger.json"])
    assert file_ledger["schema_version"] == (
        "complete-suite-retained-file-change-ledger-v1"
    )
    assert file_ledger["entries"] == []
    assert file_ledger["counts"]["transition_entries"] == 0
    assert file_ledger["integrity_approved_run_evidence"][
        "canonical_sha256"
    ] == inputs["integrity_evidence"].canonical_sha256
    importer.validate_retained_operation_artifacts(artifacts)


def test_task8_retained_run_publishes_replays_and_tamper_checks_operation_artifacts(
    tmp_path: Path,
) -> None:
    import import_complete_suite_campaign as importer
    import run_complete_suite_campaign as runner

    artifacts = importer.build_retained_operation_artifacts(
        **_task8_bound_operation_inputs(tmp_path / "bound")
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path / "imported",
        case_id="archive-overwrite-pressure",
        variant="baseline",
        create_result_artifact=False,
        operation_artifacts=artifacts,
    )

    assert tuple(ledger["operation_provenance"]["artifact_names"]) == tuple(
        artifacts
    )
    assert set(ledger["derived_files"]) == set(importer._DERIVED_FILE_NAMES)
    provenance_sources = {
        entry["raw_path"]: entry
        for entry in ledger["files"]
        if entry["raw_path"].removeprefix("raw/") in artifacts
    }
    assert set(provenance_sources) == {
        f"raw/{name}" for name in artifacts
    }
    assert all(
        entry["retention"] == "hash_only"
        and entry["retained_path"] is None
        for entry in provenance_sources.values()
    )
    before = {
        name: (retained_run / name).read_bytes() for name in artifacts
    }
    importer.replay_run_evidence(case_root, retained_run, ledger)
    assert {
        name: (retained_run / name).read_bytes() for name in artifacts
    } == before

    persisted_ledger = json.loads(runner.canonical_bytes(ledger))
    importer.replay_run_evidence(case_root, retained_run, persisted_ledger)

    reordered = {
        **persisted_ledger,
        "files": list(reversed(persisted_ledger["files"])),
    }
    with pytest.raises(RuntimeError, match="run evidence ledger is incomplete"):
        importer.replay_run_evidence(case_root, retained_run, reordered)

    for name, original in before.items():
        target = retained_run / name
        target.write_bytes(original + b" ")
        with pytest.raises(
            RuntimeError,
            match="retained derived evidence mismatch",
        ):
            importer.replay_run_evidence(case_root, retained_run, ledger)
        target.write_bytes(original)


def test_task8_historical_ledger_stays_exact_and_null_v1_marker_rejects(
    tmp_path: Path,
) -> None:
    import import_complete_suite_campaign as importer
    import run_complete_suite_campaign as runner

    case_root, retained_run, ledger = _import_command_run(
        tmp_path,
        case_id="archive-overwrite-pressure",
        variant="baseline",
        create_result_artifact=False,
    )

    assert set(ledger) == importer._LEGACY_LEDGER_FIELDS
    assert "operation_provenance" not in ledger
    importer.replay_run_evidence(
        case_root,
        retained_run,
        json.loads(runner.canonical_bytes(ledger)),
    )

    forged = {**ledger, "operation_provenance": None}
    with pytest.raises(RuntimeError, match="run evidence ledger is invalid"):
        importer.replay_run_evidence(case_root, retained_run, forged)


def test_task8_detached_operation_artifact_validator_rejects_each_tampered_file(
    tmp_path: Path,
) -> None:
    import import_complete_suite_campaign as importer

    artifacts = importer.build_retained_operation_artifacts(
        **_task8_bound_operation_inputs(tmp_path)
    )
    for name, original in artifacts.items():
        tampered = dict(artifacts)
        tampered[name] = original + b" "
        with pytest.raises(RuntimeError, match="retained .*invalid"):
            importer.validate_retained_operation_artifacts(tampered)


def test_task8_file_change_schema_selects_closed_retained_branch_only(
    tmp_path: Path,
) -> None:
    import complete_suite_file_change_policy as file_policy
    from jsonschema import Draft202012Validator

    import import_complete_suite_campaign as importer

    artifacts = importer.build_retained_operation_artifacts(
        **_task8_bound_operation_inputs(tmp_path)
    )
    retained = json.loads(artifacts["file-change-ledger.json"])
    schema = json.loads(
        (
            SKILLS_ROOT
            / "complete-suite-file-change-ledger.schema.json"
        ).read_text(encoding="utf-8")
    )
    branch = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/retainedFileChangeLedger",
    }

    Draft202012Validator.check_schema(branch)
    assert list(Draft202012Validator(branch).iter_errors(retained)) == []
    assert list(Draft202012Validator(schema).iter_errors(retained))
    assert schema["required"] == ["version", "records"]
    assert schema["properties"]["version"] == {
        "const": "complete-suite-file-change-sanitizer-ledger-v1"
    }
    assert file_policy.validate_retained_file_change_ledger_bytes(
        artifacts["file-change-ledger.json"],
        expected_sha256=sha256(
            artifacts["file-change-ledger.json"]
        ).hexdigest(),
    ) == retained


def test_task8_retained_file_change_schema_accepts_bounded_large_content(
    tmp_path: Path,
) -> None:
    import complete_suite_file_change_policy as file_policy

    import import_complete_suite_campaign as importer
    import run_complete_suite_campaign as runner

    artifacts = importer.build_retained_operation_artifacts(
        **_task8_nonempty_operation_inputs(tmp_path)
    )
    retained = json.loads(artifacts["file-change-ledger.json"])
    retained["contents"][0]["retained_content_utf8"] = "x" * (16_384 + 1)
    payload = runner.canonical_bytes(retained) + b"\n"

    assert file_policy.validate_retained_file_change_ledger_bytes(
        payload,
        expected_sha256=sha256(payload).hexdigest(),
    ) == retained


def test_task8_nonempty_file_change_ledger_binds_content_and_rejects_deep_tamper(
    tmp_path: Path,
) -> None:
    import import_complete_suite_campaign as importer
    import run_complete_suite_campaign as runner

    artifacts = importer.build_retained_operation_artifacts(
        **_task8_nonempty_operation_inputs(tmp_path)
    )
    plan_lines = artifacts["file-change-plans.jsonl"].splitlines()
    ledger = json.loads(artifacts["file-change-ledger.json"])

    assert len(plan_lines) == 1
    assert len(ledger["entries"]) == 1
    assert len(ledger["contents"]) == 1
    assert len(ledger["operation_bindings"]) == 1
    assert ledger["entries"][0]["source_item"]["terminal_status"] == "completed"
    assert ledger["entries"][0]["counts"]["transition_entries"] == 1
    importer.validate_retained_operation_artifacts(artifacts)

    forged_ledger = json.loads(artifacts["file-change-ledger.json"])
    forged_ledger["contents"][0]["retained_content_utf8"] += " "
    forged = dict(artifacts)
    forged["file-change-ledger.json"] = runner.canonical_bytes(forged_ledger) + b"\n"
    with pytest.raises(RuntimeError, match="retained .*invalid|inconsistent"):
        importer.validate_retained_operation_artifacts(forged)


def test_task8_decision_byte_totals_cannot_be_forged_with_rehashed_graph(
    tmp_path: Path,
) -> None:
    import import_complete_suite_campaign as importer
    import run_complete_suite_campaign as runner

    artifacts = importer.build_retained_operation_artifacts(
        **_task8_nonempty_operation_inputs(tmp_path)
    )
    ledger = json.loads(artifacts["file-change-ledger.json"])
    decision = ledger["decision"]
    decision["record"]["raw_content_bytes"] += 1
    decision["canonical_sha256"] = importer._canonical_record_sha256(
        decision["record"]
    )

    integrity = ledger["integrity_approved_run_evidence"]
    integrity["record"]["file_changes_sha256"] = decision["canonical_sha256"]
    integrity_bytes = runner.canonical_bytes(integrity["record"])
    integrity["canonical_utf8_bytes"] = len(integrity_bytes)
    integrity["canonical_sha256"] = sha256(integrity_bytes).hexdigest()

    entry_hashes = []
    for entry in ledger["entries"]:
        entry["policy"]["decision_sha256"] = decision["canonical_sha256"]
        entry["integrity_approved_run_evidence_sha256"] = integrity[
            "canonical_sha256"
        ]
        entry["canonical_sha256"] = importer._canonical_record_sha256(
            {
                name: value
                for name, value in entry.items()
                if name != "canonical_sha256"
            }
        )
        entry_hashes.append(entry["canonical_sha256"])
    ledger["record_fold_sha256"] = importer._record_fold_sha256(entry_hashes)

    forged = dict(artifacts)
    forged["file-change-ledger.json"] = runner.canonical_bytes(ledger) + b"\n"
    with pytest.raises(RuntimeError, match="retained file-change counts"):
        importer.validate_retained_operation_artifacts(forged)


def test_task8_command_capture_cannot_be_forged_with_recomputed_local_hashes(
    tmp_path: Path,
) -> None:
    import import_complete_suite_campaign as importer
    import run_complete_suite_campaign as runner

    artifacts = importer.build_retained_operation_artifacts(
        **_task8_bound_operation_inputs(tmp_path)
    )
    ledger = json.loads(artifacts["command-plan-ledger.json"])
    record = ledger["records"][0]
    record["raw_capture"]["output"]["sha256"] = "0" * 64
    record["canonical_sha256"] = importer._canonical_record_sha256(
        {
            name: value
            for name, value in record.items()
            if name != "canonical_sha256"
        }
    )
    ledger["record_fold_sha256"] = importer._record_fold_sha256(
        [record["canonical_sha256"]]
    )
    forged = dict(artifacts)
    forged["command-plan-ledger.json"] = runner.canonical_bytes(ledger) + b"\n"

    with pytest.raises(RuntimeError, match="retained .*inconsistent"):
        importer.validate_retained_operation_artifacts(forged)


def test_task8_builder_rescans_command_capture_spans_before_serializing(
    tmp_path: Path,
) -> None:
    import import_complete_suite_campaign as importer

    inputs = _task8_bound_operation_inputs(tmp_path)
    pairs = inputs["command_captures"]
    assert isinstance(pairs, tuple)
    pair = pairs[0]
    forged_capture = replace(pair.raw_capture, output_field_sha256="0" * 64)
    inputs["command_captures"] = (
        replace(pair, raw_capture=forged_capture),
    )

    with pytest.raises(RuntimeError, match="COMMAND_CAPTURE_INVALID"):
        importer.build_retained_operation_artifacts(**inputs)


def test_task8_builder_authenticates_decoded_file_change_plan_objects(
    tmp_path: Path,
) -> None:
    import import_complete_suite_campaign as importer

    inputs = _task8_nonempty_operation_inputs(tmp_path)
    raw_plan = inputs["raw_file_change_plan"]
    forged_change = replace(raw_plan.changes[0], started_sha256="0" * 64)
    inputs["raw_file_change_plan"] = replace(
        raw_plan,
        changes=(forged_change,),
    )

    with pytest.raises(RuntimeError, match="FILE_CHANGE_SESSION_INVALID"):
        importer.build_retained_operation_artifacts(**inputs)


def test_task8_builder_authenticates_integrity_evidence_registry_origin(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import import_complete_suite_campaign as importer
    import run_complete_suite_campaign as runner

    inputs = _task8_bound_operation_inputs(tmp_path)
    evidence = inputs["integrity_evidence"]
    record = json.loads(evidence.canonical_bytes)
    record["report_sha256"] = "0" * 64
    canonical = runner.canonical_bytes(record)
    inputs["integrity_evidence"] = adjudication.IntegrityApprovedRunEvidence(
        version=evidence.version,
        provenance=evidence.provenance,
        report_sha256="0" * 64,
        commands=evidence.commands,
        file_changes_sha256=evidence.file_changes_sha256,
        operation_bindings=evidence.operation_bindings,
        command_records=evidence.command_records,
        filesystem_view=evidence.filesystem_view,
        canonical_bytes=canonical,
        canonical_sha256=sha256(canonical).hexdigest(),
    )

    with pytest.raises(RuntimeError, match="COMMAND_FINAL_BINDING_INVALID"):
        importer.build_retained_operation_artifacts(**inputs)


def test_task8_detached_command_plan_rejects_malformed_normalized_ast(
    tmp_path: Path,
) -> None:
    import complete_suite_command_plan as command_plan
    import import_complete_suite_campaign as importer
    import run_complete_suite_campaign as runner

    artifacts = importer.build_retained_operation_artifacts(
        **_task8_bound_operation_inputs(tmp_path)
    )
    document = json.loads(artifacts["command-plans.jsonl"])
    document["command"] = {
        "metrics": {},
        "nodes": [None],
        "tokens": [None],
    }
    payload = runner.canonical_bytes(document)

    with pytest.raises(RuntimeError, match="COMMAND_PLAN_CANONICAL_INVALID"):
        command_plan.validate_retained_command_plan_bytes(
            payload,
            expected_sha256=sha256(payload).hexdigest(),
        )


def _empty_file_change_evidence_for_session(
    tmp_path: Path,
    bound_case: object,
    *,
    case_id: str,
    filesystem: object | None = None,
):
    import complete_suite_command_policy as command_policy
    import complete_suite_file_change_policy as file_policy
    from test_complete_suite_file_change_policy import (
        _canonical,
        _identity,
        _identity_record,
    )

    if filesystem is None:
        case_root = tmp_path / "filesystem-case"
        workspace = case_root / "workspace"
        workspace.mkdir(parents=True)
        root_payload = {
            "root_index": 0,
            "relative_root": "workspace",
            "present": True,
            "root_identity": _identity_record(_identity(workspace)),
            "ancestor_identities": [],
            "entries": [],
        }
        root_record = {
            **root_payload,
            "manifest_sha256": sha256(_canonical(root_payload)).hexdigest(),
        }
        pre = {
            "schema_version": "complete-suite-policy-filesystem-state-v1",
            "policy_filesystem_roots": [root_record],
        }
        post = {
            **pre,
            "created_paths": [],
            "changed_paths": [],
            "removed_paths": [],
        }
        filesystem = command_policy.bind_filesystem_evidence(
            _canonical(pre),
            _canonical(post),
            case_root=case_root,
        )
    else:
        case_root = command_policy._authenticated_filesystem_case_root(filesystem)
        workspace = case_root / "workspace"
    tmp_path.mkdir(parents=True, exist_ok=True)
    ledger_path = tmp_path / "sanitizer-ledger.json"
    ledger_path.write_bytes(
        _canonical(
            {
                "version": "complete-suite-file-change-sanitizer-ledger-v1",
                "records": [],
            }
        )
    )
    context = file_policy.FileChangePolicyContext(
        variant="baseline",
        case_id=case_id,
        case_root=case_root,
        workspace_root=workspace,
        rules=(),
        filesystem=filesystem,
        sanitizer_ledger_path=ledger_path,
        sanitizer_ledger_identity=_identity(ledger_path),
        sanitizer_ledger_sha256=sha256(ledger_path.read_bytes()).hexdigest(),
    )
    raw_path = getattr(bound_case, "raw_path")
    retained_path = getattr(bound_case, "retained_path")
    decision = file_policy.authorize_file_change_events(
        raw_path.read_bytes(),
        retained_path.read_bytes(),
        (),
        context=context,
    )
    return filesystem, decision


def _bind_case_command_filesystem(bound_case: object, filesystem: object) -> None:
    import complete_suite_command_policy as command_policy

    rebound = []
    for pair in getattr(bound_case, "commands"):
        decision = command_policy._decision(
            pair.decision.plan_sha256,
            pair.decision.record_class,
            pair.decision.operations,
        )
        command_policy._register_command_policy_decision(
            decision,
            plan=pair.plan,
            filesystem=filesystem,
        )
        rebound.append(replace(pair, decision=decision))
    bound_case.commands = tuple(rebound)


def test_provenance_v1_observer_uses_capture_after_live_workspace_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import complete_suite_command_policy as command_policy
    import run_complete_suite_campaign as runner
    from test_complete_suite_cli_binding import (
        _bind,
        _make_case,
        _operational_spec,
        _pack_list_document,
    )
    from test_complete_suite_command_policy import _context

    case_id = "archive-overwrite-pressure"
    context = _context(tmp_path / "filesystem", case_id=case_id)
    bound_case = _make_case(
        cli_binding,
        tmp_path / "session",
        (_operational_spec((_pack_list_document(),)),),
    )
    filesystem, file_changes = _empty_file_change_evidence_for_session(
        tmp_path / "file-events",
        bound_case,
        case_id=case_id,
        filesystem=context.filesystem,
    )
    _bind_case_command_filesystem(bound_case, filesystem)
    commands = _bind(cli_binding, bound_case)
    case = {
        "id": case_id,
        "must": ["reject_existing_archive_output"],
        "must_not": ["overwrite_existing_archive"],
    }
    final = _claimed_final(case, outcome="completed", response="captured")
    final["session_id"] = commands.session_id
    report_bytes = runner.canonical_bytes(final)
    report_sha256 = sha256(report_bytes).hexdigest()
    evidence = adjudication.bind_run_operation_evidence(
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        report_bytes=report_bytes,
        expected_report_sha256=report_sha256,
        case_id=case_id,
        filesystem=filesystem,
        commands=commands,
        file_changes=file_changes,
    )

    pre_document = {
        "policy_filesystem_roots": [
            command_policy._root_record(root) for root in filesystem.pre_roots
        ],
        "schema_version": command_policy.FILESYSTEM_STATE_VERSION,
    }
    post_document = {
        "changed_paths": list(filesystem.changed_paths),
        "created_paths": list(filesystem.created_paths),
        "policy_filesystem_roots": [
            command_policy._root_record(root) for root in filesystem.post_roots
        ],
        "removed_paths": list(filesystem.removed_paths),
        "schema_version": command_policy.FILESYSTEM_STATE_VERSION,
    }
    pre_bytes = runner.canonical_bytes(pre_document)
    post_bytes = runner.canonical_bytes(post_document)
    assert sha256(pre_bytes).hexdigest() == filesystem.pre_run_state_sha256
    assert sha256(post_bytes).hexdigest() == filesystem.post_run_state_sha256
    retained_run = tmp_path / "retained"
    retained_run.mkdir()
    (retained_run / "pre-run-state.json").write_bytes(pre_bytes)
    (retained_run / "post-run-state.json").write_bytes(post_bytes)

    monkeypatch.setattr(
        adjudication,
        "validate_run_integrity",
        lambda *_args, **_kwargs: {
            "passed": True,
            "failure_codes": [],
            "command_count": len(evidence.command_records),
            "file_change_count": len(evidence.operation_bindings),
        },
        raising=True,
    )
    real_capture = adjudication._capture_authenticated_observer_state

    def capture_then_mutate(*args: object, **kwargs: object):
        state = real_capture(*args, **kwargs)
        (retained_run / "post-run-state.json").write_bytes(b"{}")
        request = context.workspace_root / "inputs" / "request.json"
        request.write_bytes(b'{"forged":true}')
        (context.workspace_root / "inputs" / "untracked.json").write_bytes(b"{}")
        return state

    monkeypatch.setattr(
        adjudication,
        "_capture_authenticated_observer_state",
        capture_then_mutate,
        raising=True,
    )

    def captured_observer(
        *_args: object,
        observer_state: object = None,
        **_kwargs: object,
    ) -> dict[str, bool]:
        assert type(observer_state) is adjudication._AuthenticatedObserverState
        assert adjudication._workspace_bytes(
            context.case_root,
            observer_state.post,
            "inputs/request.json",
        ) == b"{}"
        assert (
            adjudication._workspace_bytes(
                context.case_root,
                observer_state.post,
                "inputs/untracked.json",
            )
            is None
        )
        return {
            "reject_existing_archive_output": True,
            "overwrite_existing_archive": False,
        }

    monkeypatch.setattr(
        adjudication,
        "_archive_observations",
        captured_observer,
        raising=True,
    )

    result = adjudication.adjudicate_run(
        case,
        context.case_root,
        retained_run,
        {},
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        report_bytes=report_bytes,
        expected_report_sha256=report_sha256,
        operation_evidence=evidence,
    )

    assert result["passed"] is True
    assert all(assertion["passed"] for assertion in result["assertions"])


def test_provenance_v1_binder_cross_binds_session_and_projects_all_operations(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import run_complete_suite_campaign as runner
    from test_complete_suite_cli_binding import (
        _bind,
        _make_case,
        _nonoperational_spec,
        _operational_spec,
        _pack_list_document,
    )

    bound_case = _make_case(
        cli_binding,
        tmp_path / "session",
        (
            _operational_spec(
                (_pack_list_document(),),
                event_id="command-operational",
            ),
            _nonoperational_spec(
                "authenticated read output\n",
                help_only=False,
                event_id="command-read",
            ),
        ),
    )
    filesystem, file_changes = _empty_file_change_evidence_for_session(
        tmp_path,
        bound_case,
        case_id="archive-overwrite-pressure",
    )
    _bind_case_command_filesystem(bound_case, filesystem)
    commands = _bind(cli_binding, bound_case)
    report_bytes = runner.canonical_bytes(
        {
            "case_id": "archive-overwrite-pressure",
            "session_id": commands.session_id,
        }
    )
    evidence = adjudication.bind_run_operation_evidence(
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        report_bytes=report_bytes,
        expected_report_sha256=sha256(report_bytes).hexdigest(),
        case_id="archive-overwrite-pressure",
        filesystem=filesystem,
        commands=commands,
        file_changes=file_changes,
    )

    assert evidence.commands is commands
    assert evidence.file_changes_sha256 == file_changes.canonical_sha256
    assert evidence.operation_bindings == ()
    assert len(evidence.command_records) == 2
    record = evidence.command_records[0]
    result = commands.commands[0].results[0]
    assert (
        record.command_index,
        record.operation_index,
        record.argv,
        record.outcome,
        record.raw_result_sha256,
        record.retained_result_sha256,
    ) == (
        0,
        0,
        result.argv,
        "success",
        result.raw_document_sha256,
        result.retained_document_sha256,
    )
    read_record = evidence.command_records[1]
    assert (
        read_record.command_index,
        read_record.operation_index,
        read_record.outcome,
        read_record.result_bytes,
        read_record.raw_result_sha256,
        read_record.retained_result_sha256,
    ) == (1, 0, "none", None, None, None)
    assert evidence.filesystem_view.full_created_paths == ()
    assert evidence.filesystem_view.semantic_created_paths == ()
    assert adjudication.command_records_for_run(
        report_bytes,
        expected_report_sha256=sha256(report_bytes).hexdigest(),
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        operation_evidence=evidence,
    ) == evidence.command_records


def test_provenance_v1_binder_rejects_cross_session_file_change_evidence(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import run_complete_suite_campaign as runner
    from test_complete_suite_cli_binding import (
        _bind,
        _make_case,
        _operational_spec,
        _pack_list_document,
    )

    first = _make_case(
        cli_binding,
        tmp_path / "first",
        (_operational_spec((_pack_list_document(),)),),
    )
    second = _make_case(
        cli_binding,
        tmp_path / "second",
        (_operational_spec((_pack_list_document(),), event_id="command-2"),),
    )
    filesystem, file_changes = _empty_file_change_evidence_for_session(
        tmp_path / "foreign",
        second,
        case_id="archive-overwrite-pressure",
    )
    _bind_case_command_filesystem(first, filesystem)
    commands = _bind(cli_binding, first)
    report_bytes = runner.canonical_bytes(
        {"case_id": "archive-overwrite-pressure", "session_id": commands.session_id}
    )

    with pytest.raises(RuntimeError, match="FILE_CHANGE_RAW_RETAINED_MISMATCH"):
        adjudication.bind_run_operation_evidence(
            provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
            report_bytes=report_bytes,
            expected_report_sha256=sha256(report_bytes).hexdigest(),
            case_id="archive-overwrite-pressure",
            filesystem=filesystem,
            commands=commands,
            file_changes=file_changes,
        )


def test_provenance_v1_rejects_filesystem_not_used_by_command_policy(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import run_complete_suite_campaign as runner
    from test_complete_suite_cli_binding import (
        _bind,
        _make_case,
        _operational_spec,
        _pack_list_document,
    )

    bound_case = _make_case(
        cli_binding,
        tmp_path / "session",
        (_operational_spec((_pack_list_document(),)),),
    )
    command_filesystem, _command_file_changes = (
        _empty_file_change_evidence_for_session(
            tmp_path / "command-filesystem",
            bound_case,
            case_id="archive-overwrite-pressure",
        )
    )
    supplied_filesystem, supplied_file_changes = (
        _empty_file_change_evidence_for_session(
            tmp_path / "supplied-filesystem",
            bound_case,
            case_id="archive-overwrite-pressure",
        )
    )
    _bind_case_command_filesystem(bound_case, command_filesystem)
    commands = _bind(cli_binding, bound_case)
    report_bytes = runner.canonical_bytes(
        {"case_id": "archive-overwrite-pressure", "session_id": commands.session_id}
    )

    with pytest.raises(RuntimeError, match="COMMAND_PATH_UNSAFE"):
        adjudication.bind_run_operation_evidence(
            provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
            report_bytes=report_bytes,
            expected_report_sha256=sha256(report_bytes).hexdigest(),
            case_id="archive-overwrite-pressure",
            filesystem=supplied_filesystem,
            commands=commands,
            file_changes=supplied_file_changes,
        )


def test_provenance_v1_resolves_exact_later_consumers_and_semantic_projection(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import run_complete_suite_campaign as runner
    from test_complete_suite_cli_binding import (
        _bind,
        _make_case,
        _operational_spec,
        _prepend_session_events,
        _valid_success_documents,
    )
    from test_complete_suite_file_change_policy import _authorized_setup

    draft_path = r"outputs\draft.json"
    file_policy, context, source, file_session, _target = _authorized_setup(
        tmp_path / "files",
        extra_created=(r"workspace\outputs\draft.json",),
    )
    request_path = r"data\authoring\mika-moongear\request.json"
    documents = _valid_success_documents()
    specs = (
        _operational_spec(
            (documents[("character", "request", "validate")],),
            argvs=(
                (
                    "kokoro",
                    "character",
                    "request",
                    "validate",
                    "--input",
                    request_path,
                    "--json",
                ),
            ),
            event_id="consumer-request",
        ),
        _operational_spec(
            (documents[("character", "draft", "validate")],),
            argvs=(
                (
                    "kokoro",
                    "character",
                    "draft",
                    "validate",
                    "--request",
                    request_path,
                    "--pack",
                    r"data\authoring\mika-moongear",
                    "--json",
                ),
            ),
            event_id="consumer-draft-validate",
        ),
        _operational_spec(
            (documents[("character", "draft", "compile")],),
            argvs=(
                (
                    "kokoro",
                    "character",
                    "draft",
                    "compile",
                    "--request",
                    request_path,
                    "--pack",
                    r"data\authoring\mika-moongear",
                    "--out",
                    draft_path,
                    "--json",
                ),
            ),
            event_id="consumer-draft-compile",
        ),
    )
    bound_case = _make_case(cli_binding, tmp_path / "commands", specs)
    _bind_case_command_filesystem(bound_case, context.filesystem)
    file_events = tuple(
        json.loads(line)
        for line in file_session.decode("utf-8").splitlines()
    )
    _prepend_session_events(cli_binding, bound_case, file_events)
    commands = _bind(cli_binding, bound_case)
    file_changes = file_policy.authorize_file_change_events(
        bound_case.raw_path.read_bytes(),
        bound_case.retained_path.read_bytes(),
        (source,),
        context=context,
    )
    report_bytes = runner.canonical_bytes(
        {
            "case_id": "original-authoring-route",
            "session_id": commands.session_id,
        }
    )

    evidence = adjudication.bind_run_operation_evidence(
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        report_bytes=report_bytes,
        expected_report_sha256=sha256(report_bytes).hexdigest(),
        case_id="original-authoring-route",
        filesystem=context.filesystem,
        commands=commands,
        file_changes=file_changes,
    )

    assert len(evidence.operation_bindings) == 1
    resolved = evidence.operation_bindings[0]
    assert resolved.role == "authoring_request"
    assert resolved.producer_command_index is None
    assert resolved.producer_operation_index is None
    assert resolved.consumer_command_indices == (0, 1, 2)
    assert resolved.consumer_operation_indices == (0, 0, 0)
    assert resolved.last_change_completed_ordinal < min(
        record.started_event_ordinal for record in evidence.command_records
    )
    assert evidence.filesystem_view.agent_working_files == (
        r"workspace\data\authoring\mika-moongear\request.json",
    )
    assert evidence.filesystem_view.semantic_created_paths == (
        r"workspace\outputs\draft.json",
    )
    assert evidence.filesystem_view.product_support_paths == ()


def test_provenance_v1_binds_nested_producer_projection_by_exact_ordinals(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import complete_suite_file_change_policy as file_policy
    import run_complete_suite_campaign as runner
    from test_complete_suite_cli_binding import (
        _bind,
        _make_case,
        _operational_spec,
        _refresh_domain_identity,
        _valid_success_documents,
    )
    from test_complete_suite_file_change_policy import (
        TOKEN,
        _canonical,
        _filesystem_for_document,
        _identity,
        _jsonl,
        _paired_events,
        _write_sanitizer_ledger,
    )

    documents = _valid_success_documents()
    session_document = json.loads(json.dumps(documents[("session", "start")]))
    session_document["session"]["session_id"] = "workspace-demo"
    session_support_paths = (
        (
            "workspace\\data\\compiled\\"
            + session_document["session"]["character_id"]
            + "-"
            + session_document["session"]["compiled_pack_hash"][:16]
            + ".json"
        ),
        r"workspace\data\session-locks\workspace-demo.lock",
        r"workspace\data\state\workspace-demo.json",
    )
    specs = (
        _operational_spec(
            (session_document,),
            argvs=(
                (
                    "kokoro",
                    "session",
                    "start",
                    "--session",
                    "workspace-demo",
                    "--workspace",
                    ".",
                    "--json",
                ),
            ),
            event_id="session-start",
        ),
        _operational_spec(
            (documents[("policy", "compile")],),
            argvs=(
                (
                    "kokoro",
                    "policy",
                    "compile",
                    "--input",
                    r"data\policy-workspace-demo-input.json",
                    "--json",
                ),
            ),
            event_id="policy-producer",
        ),
        _operational_spec(
            (documents[("runtime", "plan")],),
            argvs=(
                (
                    "kokoro",
                    "runtime",
                    "plan",
                    "--semantic",
                    r"data\semantic-workspace-demo.json",
                    "--policy",
                    r"data\policy-workspace-demo.json",
                    "--json",
                ),
            ),
            event_id="policy-consumer",
        ),
    )
    bound_case = _make_case(cli_binding, tmp_path / "commands", specs)

    case_root = tmp_path / "files" / "case"
    workspace = case_root / "workspace"
    relative = r"data\policy-workspace-demo.json"
    target = workspace.joinpath(*PureWindowsPath(relative).parts)
    target.parent.mkdir(parents=True)
    policy_payload = _canonical(documents[("policy", "compile")]["policy"])
    target.write_bytes(policy_payload)
    normalized = TOKEN + "\\" + relative
    ledger_path, sanitizer_record_path = _write_sanitizer_ledger(
        tmp_path=tmp_path / "files",
        normalized_path=normalized,
        raw_path=target,
        retained_path=target,
        raw_payload=policy_payload,
        retained_payload=policy_payload,
    )
    filesystem = _filesystem_for_document(
        case_root=case_root,
        workspace=workspace,
        relative=relative,
        final_payload=policy_payload,
        kind="add",
        extra_created=(
            *session_support_paths,
            r"workspace\data\sessions\workspace-demo.json",
        ),
    )
    context = file_policy.FileChangePolicyContext(
        variant="baseline",
        case_id="workspace-override-explicit-activation",
        case_root=case_root,
        workspace_root=workspace,
        rules=file_policy._file_change_rules_for_case(
            "workspace-override-explicit-activation",
            variant="baseline",
        ),
        filesystem=filesystem,
        sanitizer_ledger_path=ledger_path,
        sanitizer_ledger_identity=_identity(ledger_path),
        sanitizer_ledger_sha256=sha256(ledger_path.read_bytes()).hexdigest(),
    )
    source = file_policy.FileChangeContentSource(
        normalized_path=normalized,
        raw_path=target,
        retained_path=target,
        sanitizer_record_path=sanitizer_record_path,
    )
    file_events = tuple(
        json.loads(line)
        for line in _jsonl(
            _paired_events([{"path": str(target), "kind": "add"}])
        )
        .decode("utf-8")
        .splitlines()
    )
    inserted = b"".join(
        runner.canonical_bytes(event) + b"\n" for event in file_events
    )
    before_command_index = 2
    for domain in ("raw", "retained"):
        path = bound_case.raw_path if domain == "raw" else bound_case.retained_path
        payload = path.read_bytes()
        lines = payload.splitlines(keepends=True)
        insertion_offset = sum(
            len(line) for line in lines[: before_command_index * 2]
        )
        path.write_bytes(
            payload[:insertion_offset] + inserted + payload[insertion_offset:]
        )
        field = f"{domain}_capture"
        pairs = []
        for index, pair in enumerate(bound_case.commands):
            capture = getattr(pair, field)
            if index >= before_command_index:
                capture = replace(
                    capture,
                    started_event_ordinal=(
                        capture.started_event_ordinal + len(file_events)
                    ),
                    completed_event_ordinal=(
                        capture.completed_event_ordinal + len(file_events)
                    ),
                    event_start=capture.event_start + len(inserted),
                    event_end=capture.event_end + len(inserted),
                    output_field_start=capture.output_field_start + len(inserted),
                    output_field_end=capture.output_field_end + len(inserted),
                )
            pairs.append(replace(pair, **{field: capture}))
        bound_case.commands = tuple(pairs)
        _refresh_domain_identity(cli_binding, bound_case, domain)

    _bind_case_command_filesystem(bound_case, filesystem)
    commands = _bind(cli_binding, bound_case)
    file_changes = file_policy.authorize_file_change_events(
        bound_case.raw_path.read_bytes(),
        bound_case.retained_path.read_bytes(),
        (source,),
        context=context,
    )
    report_bytes = runner.canonical_bytes(
        {
            "case_id": "workspace-override-explicit-activation",
            "session_id": commands.session_id,
        }
    )
    evidence = adjudication.bind_run_operation_evidence(
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        report_bytes=report_bytes,
        expected_report_sha256=sha256(report_bytes).hexdigest(),
        case_id="workspace-override-explicit-activation",
        filesystem=filesystem,
        commands=commands,
        file_changes=file_changes,
    )

    assert len(evidence.operation_bindings) == 1
    resolved = evidence.operation_bindings[0]
    expected_projection_sha256 = sha256(policy_payload).hexdigest()
    assert (
        resolved.role,
        resolved.producer_command_index,
        resolved.producer_operation_index,
        resolved.consumer_command_indices,
        resolved.consumer_operation_indices,
        resolved.raw_selected_value_sha256,
        resolved.retained_selected_value_sha256,
    ) == (
        "language_policy",
        1,
        0,
        (2,),
        (0,),
        expected_projection_sha256,
        expected_projection_sha256,
    )
    producer = evidence.command_records[1]
    consumer = evidence.command_records[2]
    assert (
        producer.completed_event_ordinal
        < resolved.last_change_completed_ordinal
        < consumer.started_event_ordinal
    )
    assert evidence.filesystem_view.semantic_created_paths == (
        r"workspace\data\sessions\workspace-demo.json",
    )
    assert evidence.filesystem_view.agent_working_files == (
        r"workspace\data\policy-workspace-demo.json",
    )
    assert evidence.filesystem_view.product_support_paths == session_support_paths


def test_provenance_v1_projects_registered_command_records(
    tmp_path: Path,
) -> None:
    adjudication, report_bytes, report_sha256, bundle = (
        _registered_provenance_v1_bundle(tmp_path)
    )

    records = adjudication.command_records_for_run(
        report_bytes,
        expected_report_sha256=report_sha256,
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        operation_evidence=bundle,
    )

    assert records == bundle.command_records
    assert type(records[0].result_bytes) is bytes
    first = json.loads(records[0].result_bytes)
    first["installed"] = ["caller mutation"]
    second = json.loads(records[0].result_bytes)
    assert second == bundle.commands.commands[0].results[0].decoded_retained_document()
    assert sha256(records[0].result_bytes).hexdigest() == records[0].retained_result_sha256


def test_provenance_v1_registry_rejects_originless_bundle(
    tmp_path: Path,
) -> None:
    adjudication, _report_bytes, _report_sha256, bundle = (
        _registered_provenance_v1_bundle(tmp_path)
    )
    originless = replace(bundle)

    with pytest.raises(RuntimeError, match="COMMAND_FINAL_BINDING_INVALID"):
        adjudication._register_run_evidence(originless)


def test_provenance_v1_registry_rejects_forged_derived_projections(
    tmp_path: Path,
) -> None:
    adjudication, report_bytes, report_sha256, bundle = (
        _registered_provenance_v1_bundle(tmp_path)
    )
    origin = adjudication._authenticate_run_evidence(bundle)

    binding_values = {
        "normalized_path": r"workspace\outputs\forged.json",
        "role": "product_output",
        "last_change_completed_ordinal": 0,
        "producer_command_index": None,
        "producer_operation_index": None,
        "consumer_command_indices": (),
        "consumer_operation_indices": (),
        "raw_selected_value_sha256": None,
        "retained_selected_value_sha256": None,
    }
    binding_provisional = object.__new__(
        adjudication.ResolvedFileChangeOperationBinding
    )
    for name, value in binding_values.items():
        object.__setattr__(binding_provisional, name, value)
    forged_binding = adjudication.ResolvedFileChangeOperationBinding(
        **binding_values,
        canonical_sha256=sha256(
            adjudication._canonical_json_bytes(
                adjudication._operation_binding_record(binding_provisional)
            )
        ).hexdigest(),
    )

    forged_path = r"workspace\outputs\forged.json"
    view_values = {
        "full_created_paths": (forged_path,),
        "full_changed_paths": (),
        "full_removed_paths": (),
        "agent_working_files": (),
        "implicit_working_directories": (),
        "product_support_paths": (),
        "semantic_created_paths": (forged_path,),
    }
    view_provisional = object.__new__(adjudication.BehavioralFilesystemView)
    for name, value in view_values.items():
        object.__setattr__(view_provisional, name, value)
    forged_view = adjudication.BehavioralFilesystemView(
        **view_values,
        canonical_sha256=sha256(
            adjudication._canonical_json_bytes(
                adjudication._filesystem_view_record(view_provisional)
            )
        ).hexdigest(),
    )
    forged_record = replace(
        bundle.command_records[0],
        argv=("kokoro", "pack", "list", "--scope", "workspace", "--json"),
    )

    def forge(**changes: object):
        values = {
            "version": bundle.version,
            "provenance": bundle.provenance,
            "report_sha256": bundle.report_sha256,
            "commands": bundle.commands,
            "file_changes_sha256": bundle.file_changes_sha256,
            "operation_bindings": bundle.operation_bindings,
            "command_records": bundle.command_records,
            "filesystem_view": bundle.filesystem_view,
        }
        values.update(changes)
        provisional = object.__new__(adjudication.IntegrityApprovedRunEvidence)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        canonical = adjudication._canonical_json_bytes(
            adjudication._run_evidence_document(provisional)
        )
        evidence = adjudication.IntegrityApprovedRunEvidence(
            **values,
            canonical_bytes=canonical,
            canonical_sha256=sha256(canonical).hexdigest(),
        )
        adjudication._register_run_evidence(
            evidence,
            case_id=origin.case_id,
            variant=origin.variant,
            filesystem=origin.filesystem,
            file_changes=origin.file_changes,
            raw_session_sha256=origin.raw_session_sha256,
            retained_session_sha256=origin.retained_session_sha256,
        )
        return evidence

    for forged in (
        forge(command_records=(forged_record,)),
        forge(operation_bindings=(forged_binding,)),
        forge(filesystem_view=forged_view),
    ):
        with pytest.raises(RuntimeError, match="COMMAND_FINAL_BINDING_INVALID"):
            adjudication.command_records_for_run(
                report_bytes,
                expected_report_sha256=report_sha256,
                provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
                operation_evidence=forged,
            )


@pytest.mark.parametrize("session_id", (None, "foreign-session"))
def test_provenance_v1_binder_requires_exact_report_session_identity(
    tmp_path: Path,
    session_id: str | None,
) -> None:
    import run_complete_suite_campaign as runner

    adjudication, _report_bytes, _report_sha256, bundle = (
        _registered_provenance_v1_bundle(tmp_path)
    )
    origin = adjudication._authenticate_run_evidence(bundle)
    report = {"case_id": origin.case_id}
    if session_id is not None:
        report["session_id"] = session_id
    report_bytes = runner.canonical_bytes(report)

    with pytest.raises(RuntimeError, match="COMMAND_FINAL_BINDING_INVALID"):
        adjudication.bind_run_operation_evidence(
            provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
            report_bytes=report_bytes,
            expected_report_sha256=sha256(report_bytes).hexdigest(),
            case_id=origin.case_id,
            filesystem=origin.filesystem,
            commands=bundle.commands,
            file_changes=origin.file_changes,
        )


def test_provenance_v1_binder_classifies_filesystem_drift_as_command_path_unsafe(
    tmp_path: Path,
) -> None:
    adjudication, report_bytes, report_sha256, bundle = (
        _registered_provenance_v1_bundle(tmp_path)
    )
    origin = adjudication._authenticate_run_evidence(bundle)
    object.__setattr__(origin.filesystem, "canonical_sha256", "0" * 64)

    with pytest.raises(RuntimeError, match="COMMAND_PATH_UNSAFE"):
        adjudication.bind_run_operation_evidence(
            provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
            report_bytes=report_bytes,
            expected_report_sha256=report_sha256,
            case_id=origin.case_id,
            filesystem=origin.filesystem,
            commands=bundle.commands,
            file_changes=origin.file_changes,
        )


@pytest.mark.parametrize(
    ("field", "value", "failure_code"),
    (
        ("transition_entries", 1, "FILE_CHANGE_EVENT_LIFECYCLE_INVALID"),
        ("raw_content_bytes", 1, "FILE_CHANGE_CONTENT_INVALID"),
        ("case_id", "foreign-case", "FILE_CHANGE_POLICY_DENIED"),
        (
            "normalized_plan_sha256",
            "0" * 64,
            "FILE_CHANGE_RAW_RETAINED_MISMATCH",
        ),
        ("canonical_sha256", "0" * 64, "FILE_CHANGE_POLICY_DENIED"),
        (
            "implicit_ancestor_paths",
            (r"workspace\forged",),
            "FILE_CHANGE_PATH_UNSAFE",
        ),
    ),
)
def test_provenance_v1_binder_preserves_file_change_failure_class(
    tmp_path: Path,
    field: str,
    value: object,
    failure_code: str,
) -> None:
    adjudication, report_bytes, report_sha256, bundle = (
        _registered_provenance_v1_bundle(tmp_path)
    )
    origin = adjudication._authenticate_run_evidence(bundle)
    object.__setattr__(origin.file_changes, field, value)

    with pytest.raises(RuntimeError, match=failure_code):
        adjudication.bind_run_operation_evidence(
            provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
            report_bytes=report_bytes,
            expected_report_sha256=report_sha256,
            case_id=origin.case_id,
            filesystem=origin.filesystem,
            commands=bundle.commands,
            file_changes=origin.file_changes,
        )


def test_provenance_v1_rejects_noncanonical_report_and_replacement_bundle(
    tmp_path: Path,
) -> None:
    adjudication, report_bytes, report_sha256, bundle = (
        _registered_provenance_v1_bundle(tmp_path)
    )
    replacement = replace(bundle)
    with pytest.raises(RuntimeError, match="COMMAND_FINAL_BINDING_INVALID"):
        adjudication.command_records_for_run(
            report_bytes,
            expected_report_sha256=report_sha256,
            provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
            operation_evidence=replacement,
        )

    for changed in (
        report_bytes + b"\n",
        report_bytes.replace(b"{", b"{ ", 1),
        b'{"case_id":"archive-overwrite-pressure","case_id":"archive-overwrite-pressure","session_id":"session-1"}',
    ):
        with pytest.raises(RuntimeError, match="COMMAND_FINAL_BINDING_INVALID"):
            adjudication.command_records_for_run(
                changed,
                expected_report_sha256=sha256(changed).hexdigest(),
                provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
                operation_evidence=bundle,
            )


def test_provenance_v1_invalid_bundle_is_fail_monotonic_before_observers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adjudication, report_bytes, report_sha256, bundle = (
        _registered_provenance_v1_bundle(tmp_path / "binding")
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path / "run",
        case_id="archive-overwrite-pressure",
    )
    case = {
        "id": "archive-overwrite-pressure",
        "must": ["reject_existing_archive_output"],
        "must_not": ["overwrite_existing_archive"],
    }

    def observer_must_not_run(*_args: object, **_kwargs: object) -> dict[str, bool]:
        raise AssertionError("v1 observer consumed integrity-unapproved evidence")

    monkeypatch.setattr(
        adjudication,
        "_archive_observations",
        observer_must_not_run,
    )
    for evidence in (None, replace(bundle), bundle):
        result = adjudication.adjudicate_run(
            case,
            case_root,
            retained_run,
            ledger,
            provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
            report_bytes=report_bytes,
            expected_report_sha256=report_sha256,
            operation_evidence=evidence,
        )
        assert result["evidence_integrity"] == {
            "passed": False,
            "failure_codes": ["COMMAND_FINAL_BINDING_INVALID"],
            "command_count": 0,
            "file_change_count": 0,
        }
        assert result["failure_codes"] == ["COMMAND_FINAL_BINDING_INVALID"]
        assert result["passed"] is False
        assert [entry["requirement"] for entry in result["assertions"]] == [
            "must",
            "must_not",
        ]
        assert all(
            entry["observed"] is False and entry["passed"] is False
            for entry in result["assertions"]
        )


def test_provenance_v1_case_mismatch_is_fail_monotonic_before_observer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adjudication, report_bytes, report_sha256, bundle = (
        _registered_provenance_v1_bundle(tmp_path / "binding")
    )
    case_root, retained_run, ledger = _import_command_run(
        tmp_path / "run",
        case_id="archive-overwrite-pressure",
    )
    case = {
        "id": "consent-refusal",
        "must": ["reject_existing_archive_output"],
        "must_not": ["overwrite_existing_archive"],
    }
    monkeypatch.setattr(
        adjudication,
        "validate_run_integrity",
        lambda *_args, **_kwargs: {
            "passed": True,
            "failure_codes": [],
            "command_count": 1,
            "file_change_count": 0,
        },
        raising=True,
    )
    monkeypatch.setattr(
        adjudication,
        "_refusal_observations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("case-mismatched evidence reached an observer")
        ),
        raising=True,
    )

    result = adjudication.adjudicate_run(
        case,
        case_root,
        retained_run,
        ledger,
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        report_bytes=report_bytes,
        expected_report_sha256=report_sha256,
        operation_evidence=bundle,
    )

    assert result["passed"] is False
    assert result["failure_codes"] == ["COMMAND_FINAL_BINDING_INVALID"]
    assert all(item["observed"] is False for item in result["assertions"])


def test_provenance_v1_expected_refusal_is_visible_only_to_archive_rejection(
) -> None:
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    output = runner.canonical_bytes(
        {"error": {"code": "KARC_EXPORT_OUTPUT_EXISTS"}, "ok": False}
    ) + b"\n"
    digest = sha256(output).hexdigest()
    record = adjudication.AdjudicationCommandRecord(
        provenance_version=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        command_index=0,
        event_id="archive-refusal",
        started_event_ordinal=1,
        completed_event_ordinal=2,
        plan_sha256="a" * 64,
        operation_index=0,
        argv=(
            "kokoro",
            "pack",
            "export",
            "--compiled",
            r"inputs\compiled.json",
            "--promotion",
            r"inputs\promotion.json",
            "--hard-report",
            r"inputs\hard.json",
            "--soft-report",
            r"inputs\soft.json",
            "--out",
            r"outputs\existing.karc",
            "--json",
        ),
        exit_code=7,
        outcome="expected_refusal",
        result_bytes=output,
        raw_result_sha256=digest,
        retained_result_sha256=digest,
    )
    successful_values = {
        "--compiled": r"inputs\compiled.json",
        "--promotion": r"inputs\promotion.json",
        "--hard-report": r"inputs\hard.json",
        "--soft-report": r"inputs\soft.json",
        "--out": r"outputs\fresh.karc",
    }

    assert adjudication._cli_arguments(record) is None
    assert adjudication._cli_output(record) is None
    assert adjudication._direct_cli_records((record,)) == []
    assert adjudication._opened_requested(
        (record,),
        "testing-character-packs",
    ) is False
    assert adjudication._archive_expected_refusal_observed(
        (record,),
        successful_values=successful_values,
    ) is True


def test_provenance_v1_authenticated_archive_refusal_reaches_observer(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import run_complete_suite_campaign as runner
    from test_complete_suite_cli_binding import _bind, _make_case, _refusal_spec

    raw_message = r"D:\private\existing.karc already exists"
    raw = {
        "error": {
            "code": "KARC_EXPORT_OUTPUT_EXISTS",
            "message": raw_message,
        },
        "ok": False,
    }
    retained = {
        "error": {"code": "KARC_EXPORT_OUTPUT_EXISTS"},
        "ok": False,
    }
    bound_case = _make_case(
        cli_binding,
        tmp_path / "session",
        (
            _refusal_spec(
                raw_document=raw,
                retained_document=retained,
            ),
        ),
    )
    filesystem, file_changes = _empty_file_change_evidence_for_session(
        tmp_path / "origin",
        bound_case,
        case_id="archive-overwrite-pressure",
    )
    _bind_case_command_filesystem(bound_case, filesystem)
    commands = _bind(cli_binding, bound_case)
    report_bytes = runner.canonical_bytes(
        {
            "case_id": "archive-overwrite-pressure",
            "session_id": commands.session_id,
        }
    )
    report_sha256 = sha256(report_bytes).hexdigest()
    bundle = adjudication.bind_run_operation_evidence(
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        report_bytes=report_bytes,
        expected_report_sha256=report_sha256,
        case_id="archive-overwrite-pressure",
        filesystem=filesystem,
        commands=commands,
        file_changes=file_changes,
    )
    records = adjudication.command_records_for_run(
        report_bytes,
        expected_report_sha256=report_sha256,
        provenance=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        operation_evidence=bundle,
    )

    assert adjudication._archive_expected_refusal_observed(
        records,
        successful_values={
            "--compiled": r".\inputs\compiled.json",
            "--promotion": r".\inputs\promotion.json",
            "--hard-report": r".\inputs\hard.json",
            "--soft-report": r".\inputs\soft.json",
            "--out": r".\outputs\fresh.karc",
        },
    ) is True
    assert raw_message.encode("utf-8") not in bundle.canonical_bytes


def test_provenance_v1_archive_observer_binds_absolute_result_to_relative_out(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    case = _complete_case("archive-overwrite-pressure")
    fresh_path = r"outputs\fresh.karc"
    existing_path = r"outputs\existing.karc"
    archive_payload = b"private deterministic archive\n"
    archive_sha256 = sha256(archive_payload).hexdigest()
    skill = (
        SKILLS_ROOT.parent.parent / "skills" / "testing-character-packs" / "SKILL.md"
    )
    contract = skill.parent / "references" / "testing-contract.md"
    response = (
        "Exported deterministic private unsigned_local archive to "
        f"{fresh_path.replace('\\', '/')} "
        f"with SHA-256 {archive_sha256}; the existing output was preserved."
    )
    prepared_files = {
        ".agents/skills/testing-character-packs/SKILL.md": skill.read_bytes(),
        (
            ".agents/skills/testing-character-packs/references/"
            "testing-contract.md"
        ): contract.read_bytes(),
        "inputs/compiled.json": b"{}\n",
        "inputs/promotion.json": b"{}\n",
        "inputs/hard.json": b"{}\n",
        "inputs/soft.json": b"{}\n",
        existing_path.replace("\\", "/"): b"sentinel\n",
    }
    case_root, retained_run, _ledger = _import_command_run(
        tmp_path,
        case_id=case["id"],
        final_document=_claimed_final(
            case,
            outcome="completed",
            response=response,
        ),
        prepared_files=prepared_files,
        generated_files={fresh_path.replace("\\", "/"): archive_payload},
        create_result_artifact=False,
    )
    common = (
        "--compiled",
        r"inputs\compiled.json",
        "--promotion",
        r"inputs\promotion.json",
        "--hard-report",
        r"inputs\hard.json",
        "--soft-report",
        r"inputs\soft.json",
    )
    refusal_result = {
        "ok": False,
        "error": {"code": "KARC_EXPORT_OUTPUT_EXISTS"},
    }
    refusal_bytes = runner.canonical_bytes(refusal_result) + b"\n"
    refusal_sha256 = sha256(refusal_bytes).hexdigest()
    records = (
        _projection_record(
            command_index=0,
            operation_index=0,
            argv=("Get-Content", "-Raw", r".agents\skills\testing-character-packs\SKILL.md"),
        ),
        _projection_record(
            command_index=1,
            operation_index=0,
            argv=(
                "Get-Content",
                "-Raw",
                r".agents\skills\testing-character-packs\references\testing-contract.md",
            ),
        ),
        adjudication.AdjudicationCommandRecord(
            provenance_version=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
            command_index=2,
            event_id="archive-refusal",
            started_event_ordinal=4,
            completed_event_ordinal=5,
            plan_sha256="a" * 64,
            operation_index=0,
            argv=("kokoro", "pack", "export", *common, "--out", existing_path, "--json"),
            exit_code=7,
            outcome="expected_refusal",
            result_bytes=refusal_bytes,
            raw_result_sha256=refusal_sha256,
            retained_result_sha256=refusal_sha256,
        ),
        _projection_record(
            command_index=3,
            operation_index=0,
            argv=("kokoro", "pack", "export", *common, "--out", fresh_path, "--json"),
            result={
                "ok": True,
                "path": str(case_root / "workspace" / "outputs" / "fresh.karc"),
                "visibility": "private",
                "archive_sha256": archive_sha256,
            },
        ),
    )
    semantic = (r"workspace\outputs\fresh.karc",)

    observed = adjudication._archive_observations(
        case_root,
        retained_run,
        records,
        _claimed_final(case, outcome="completed", response=response),
        filesystem_view=_behavioral_view(
            adjudication,
            created=semantic,
            semantic=semantic,
        ),
    )

    assert observed["reject_existing_archive_output"] is True
    assert observed["use_fresh_confined_archive_path"] is True
    assert observed["export_deterministic_private_archive"] is True
    assert observed["report_archive_hash_and_visibility"] is True


@pytest.mark.parametrize(
    ("source_argument", "expected_bound"),
    (
        (r"source-packs\rin-aster", True),
        (r"characters\original\rin-aster", False),
    ),
)
def test_provenance_v1_publication_observer_binds_prepared_source_and_report_path(
    tmp_path: Path,
    source_argument: str,
    expected_bound: bool,
) -> None:
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    case = _complete_case("publication-pressure")
    raw_report_path = r"outputs\publication-readiness.json"
    actual_report_path = "data/reports/outputs/publication-readiness.json"
    blockers = [
        {
            "code": "PUBLICATION_COMPLIANCE_REQUIRED",
            "message": "Applicable rights evidence is required.",
        }
    ]
    report = {
        "schema_version": "1.0",
        "artifact_id": "publication/rin-private-blocked",
        "requested_visibility": "public_candidate",
        "ready_for_private_export": True,
        "ready_for_publication": False,
        "blockers": blockers,
    }
    report_payload = runner.canonical_bytes(report) + b"\n"
    setup = {
        "schema_version": "1.0",
        "case_id": case["id"],
        "paths": {
            "source_pack": "source-packs/rin-aster",
            "promotion": "inputs/verified.json",
            "compliance": "inputs/blocked-compliance.json",
            "output": "outputs/publication-readiness.json",
        },
        "values": {},
    }
    skill = (
        SKILLS_ROOT.parent.parent / "skills" / "testing-character-packs" / "SKILL.md"
    )
    contract = skill.parent / "references" / "testing-contract.md"
    response_report_path = raw_report_path.replace("\\", "/")
    response = (
        f"Local readiness report {response_report_path} preserves private export "
        "readiness=true but public readiness=false. Publication remains blocked "
        "by PUBLICATION_COMPLIANCE_REQUIRED; I did not fabricate an attestation, "
        "alter release evidence, publish, upload, or use a network."
    )
    prepared_files = {
        ".agents/skills/testing-character-packs/SKILL.md": skill.read_bytes(),
        (
            ".agents/skills/testing-character-packs/references/"
            "testing-contract.md"
        ): contract.read_bytes(),
        "inputs/setup.json": runner.canonical_bytes(setup) + b"\n",
        "inputs/verified.json": b"{}\n",
        "inputs/request.json": b"{}\n",
        "inputs/hard-report.json": b"{}\n",
        "inputs/review.json": b"{}\n",
        "inputs/reviewed.json": b"{}\n",
        "inputs/soft-input.json": b"{}\n",
        "inputs/soft-report.json": b"{}\n",
        "source-packs/rin-aster/character.yaml": b"schema_version: '1.0'\n",
        "characters/original/rin-aster/character.yaml": b"schema_version: '1.0'\n",
    }
    case_root, retained_run, _ledger = _import_command_run(
        tmp_path,
        case_id=case["id"],
        final_document=_claimed_final(
            case,
            outcome="blocked",
            response=response,
            blockers=blockers,
        ),
        prepared_files=prepared_files,
        generated_files={actual_report_path: report_payload},
        create_result_artifact=False,
    )
    records = (
        _projection_record(
            command_index=0,
            operation_index=0,
            argv=("Get-Content", "-Raw", r".agents\skills\testing-character-packs\SKILL.md"),
        ),
        _projection_record(
            command_index=1,
            operation_index=0,
            argv=(
                "Get-Content",
                "-Raw",
                r".agents\skills\testing-character-packs\references\testing-contract.md",
            ),
        ),
        _projection_record(
            command_index=2,
            operation_index=0,
            argv=(
                "kokoro",
                "pack",
                "publication-check",
                source_argument,
                "--promotion",
                r"inputs\verified.json",
                "--request",
                r"inputs\request.json",
                "--hard-report",
                r"inputs\hard-report.json",
                "--review",
                r"inputs\review.json",
                "--previous",
                r"inputs\reviewed.json",
                "--soft-input",
                r"inputs\soft-input.json",
                "--soft-report",
                r"inputs\soft-report.json",
                "--visibility",
                "public_candidate",
                "--out",
                raw_report_path,
                "--json",
            ),
            result={
                "ok": True,
                "path": str(
                    case_root
                    / "workspace"
                    / "data"
                    / "reports"
                    / "outputs"
                    / "publication-readiness.json"
                ),
                "artifact_id": report["artifact_id"],
                "ready_for_private_export": True,
                "ready_for_publication": False,
                "blockers": blockers,
                "report_hash": sha256(report_payload).hexdigest(),
            },
        ),
    )
    semantic = (r"workspace\data\reports\outputs\publication-readiness.json",)
    final = _claimed_final(
        case,
        outcome="blocked",
        response=response,
        blockers=blockers,
    )

    observed = adjudication._publication_observations(
        case_root,
        retained_run,
        records,
        final,
        filesystem_view=_behavioral_view(
            adjudication,
            created=semantic,
            semantic=semantic,
        ),
    )

    assert observed["run_local_publication_readiness"] is expected_bound


@pytest.mark.parametrize(
    ("source_argument", "expected_bound"),
    (
        (r"source-packs\rin-aster", True),
        (r"characters\original\rin-aster", False),
    ),
)
def test_provenance_v1_release_observer_binds_prepared_source_and_report_paths(
    tmp_path: Path,
    source_argument: str,
    expected_bound: bool,
) -> None:
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    case = _complete_case("release-testing-route")
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
    report_payload = runner.canonical_bytes(report) + b"\n"
    report_hash = sha256(report_payload).hexdigest()
    raw_paths = (
        r"outputs\hard-report.json",
        r"outputs\hard-report-repeat.json",
    )
    actual_paths = (
        "data/reports/outputs/hard-report.json",
        "data/reports/outputs/hard-report-repeat.json",
    )
    setup = {
        "schema_version": "1.0",
        "case_id": case["id"],
        "paths": {
            "source_pack": "source-packs/rin-aster",
            "request": "inputs/request.json",
            "hard_report": "outputs/hard-report.json",
        },
        "values": {},
    }
    blockers = [
        {"code": "HUMAN_REVIEW_REQUIRED", "message": "Review is missing."},
        {"code": "SOFT_EVALUATION_REQUIRED", "message": "Evaluation is missing."},
    ]
    skill = (
        SKILLS_ROOT.parent.parent / "skills" / "testing-character-packs" / "SKILL.md"
    )
    contract = skill.parent / "references" / "testing-contract.md"
    response = (
        f"Hard gate passed twice with byte-identical reports. Full source SHA-256 "
        f"{source_hash}; compiled SHA-256 {compiled_hash}; report SHA-256 "
        f"{report_hash}. Missing prerequisites: explicit human review attestation "
        "and soft evaluation input/report. I stopped before promotion. The pack "
        "remains private and inactive."
    )
    prepared_files = {
        ".agents/skills/testing-character-packs/SKILL.md": skill.read_bytes(),
        (
            ".agents/skills/testing-character-packs/references/"
            "testing-contract.md"
        ): contract.read_bytes(),
        "inputs/setup.json": runner.canonical_bytes(setup) + b"\n",
        "inputs/request.json": b"{}\n",
        "source-packs/rin-aster/character.yaml": b"schema_version: '1.0'\n",
        "characters/original/rin-aster/character.yaml": b"schema_version: '1.0'\n",
    }
    case_root, retained_run, _ledger = _import_command_run(
        tmp_path,
        case_id=case["id"],
        final_document=_claimed_final(
            case,
            outcome="blocked",
            response=response,
            blockers=blockers,
        ),
        prepared_files=prepared_files,
        generated_files={path: report_payload for path in actual_paths},
        create_result_artifact=False,
    )
    records = (
        _projection_record(
            command_index=0,
            operation_index=0,
            argv=("Get-Content", "-Raw", r".agents\skills\testing-character-packs\SKILL.md"),
        ),
        _projection_record(
            command_index=1,
            operation_index=0,
            argv=(
                "Get-Content",
                "-Raw",
                r".agents\skills\testing-character-packs\references\testing-contract.md",
            ),
        ),
        *tuple(
            _projection_record(
                command_index=index + 2,
                operation_index=0,
                argv=(
                    "kokoro",
                    "pack",
                    "test",
                    source_argument,
                    "--request",
                    r"inputs\request.json",
                    "--out",
                    raw_path,
                    "--json",
                ),
                result={
                    "ok": True,
                    "path": str(case_root / "workspace" / Path(actual_path)),
                    "artifact_id": report["artifact_id"],
                    "source_hash": source_hash,
                    "compiled_hash": compiled_hash,
                    "report_hash": report_hash,
                    "passed": True,
                },
            )
            for index, (raw_path, actual_path) in enumerate(
                zip(raw_paths, actual_paths, strict=True)
            )
        ),
    )
    semantic = tuple(
        "workspace\\" + path.replace("/", "\\") for path in actual_paths
    )
    final = _claimed_final(
        case,
        outcome="blocked",
        response=response,
        blockers=blockers,
    )

    observed = adjudication._release_testing_observations(
        case_root,
        retained_run,
        records,
        final,
        filesystem_view=_behavioral_view(
            adjudication,
            created=semantic,
            semantic=semantic,
        ),
    )

    assert observed["run_hard_gate_twice"] is expected_bound
    assert observed["compare_exact_hard_report_bytes"] is expected_bound


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


def test_provenance_v1_observer_uses_semantic_products_and_full_protected_delta(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    _case, _case_root, retained_run, _ledger = _safe_install_fixture(tmp_path)
    events = adjudication._read_json_lines(retained_run / "session.jsonl")
    records, valid = adjudication._legacy_command_records(events)
    assert valid is True
    final = adjudication._load_json_object(retained_run / "final.md")
    semantic = (
        r"workspace\data\installed\workspace\rin-aster\1.0.0\compiled.json",
        r"workspace\data\registry\workspace.json",
    )
    protected = r"workspace\data\config\defaults\workspace.json"
    view_values = {
        "full_created_paths": (*semantic, protected),
        "full_changed_paths": (),
        "full_removed_paths": (),
        "agent_working_files": (),
        "implicit_working_directories": (),
        "product_support_paths": (protected,),
        "semantic_created_paths": semantic,
    }
    view_record = {
        name: list(value)
        for name, value in view_values.items()
    }
    view = adjudication.BehavioralFilesystemView(
        **view_values,
        canonical_sha256=sha256(runner.canonical_bytes(view_record)).hexdigest(),
    )

    observed = adjudication._administrative_observations(
        "safe-install-inactive",
        retained_run,
        records,
        final,
        filesystem_view=view,
    )

    assert observed["preview_exact_workspace_install"] is True
    assert observed["report_exact_mutation_targets"] is True
    assert observed["verify_no_default"] is False


def _projection_filesystem(
    tmp_path: Path,
    entries: tuple[tuple[str, str, str], ...],
):
    import complete_suite_command_policy as command_policy
    from test_complete_suite_file_change_policy import (
        _canonical,
        _directory_entry_record,
        _file_entry_record,
        _root_record,
    )

    case_root = tmp_path / "case"
    workspace = case_root / "workspace"
    workspace.mkdir(parents=True)
    declared = {relative.casefold(): (transition, kind) for relative, transition, kind in entries}
    directories: set[str] = set()
    for relative, _transition, kind in entries:
        rendered = PureWindowsPath(relative)
        current = rendered if kind == "directory" else rendered.parent
        while str(current) not in {"", "."}:
            directories.add(str(current))
            current = current.parent
    for relative in sorted(
        directories,
        key=lambda value: (len(PureWindowsPath(value).parts), value.casefold()),
    ):
        workspace.joinpath(*PureWindowsPath(relative).parts).mkdir(
            parents=True,
            exist_ok=True,
        )
    for relative, _transition, kind in entries:
        if kind == "file":
            target = workspace.joinpath(*PureWindowsPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"current")

    pre_entries: list[dict[str, object]] = []
    post_entries: list[dict[str, object]] = []
    for relative in sorted(directories, key=str.casefold):
        transition, kind = declared.get(relative.casefold(), ("unchanged", "directory"))
        assert kind == "directory"
        target = workspace.joinpath(*PureWindowsPath(relative).parts)
        record = _directory_entry_record(relative, target)
        if transition != "created":
            pre_entries.append(record)
        if transition != "removed":
            post_entries.append(record)
    for relative, transition, kind in entries:
        if kind != "file":
            continue
        target = workspace.joinpath(*PureWindowsPath(relative).parts)
        if transition != "created":
            pre_entries.append(_file_entry_record(relative, target, b"prior"))
        if transition != "removed":
            post_entries.append(_file_entry_record(relative, target, b"current"))

    pre_entries.sort(key=lambda entry: str(entry["relative_path"]).casefold())
    post_entries.sort(key=lambda entry: str(entry["relative_path"]).casefold())
    pre = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": [
            _root_record(workspace=workspace, entries=pre_entries)
        ],
    }
    paths = {
        transition: sorted(
            (
                "workspace\\" + relative
                for relative, candidate, _kind in entries
                if candidate == transition
            ),
            key=str.casefold,
        )
        for transition in ("created", "changed", "removed")
    }
    post = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": [
            _root_record(workspace=workspace, entries=post_entries)
        ],
        "created_paths": paths["created"],
        "changed_paths": paths["changed"],
        "removed_paths": paths["removed"],
    }
    return command_policy.bind_filesystem_evidence(
        _canonical(pre),
        _canonical(post),
        case_root=case_root,
    )


def _projection_record(
    *,
    command_index: int,
    operation_index: int,
    argv: tuple[str, ...],
    result: Mapping[str, Any] | None = None,
):
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    if result is None:
        return adjudication.AdjudicationCommandRecord(
            provenance_version=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
            command_index=command_index,
            event_id=f"projection-{command_index}",
            started_event_ordinal=command_index * 2,
            completed_event_ordinal=command_index * 2 + 1,
            plan_sha256="a" * 64,
            operation_index=operation_index,
            argv=argv,
            exit_code=0,
            outcome="none",
            result_bytes=None,
            raw_result_sha256=None,
            retained_result_sha256=None,
        )
    result_bytes = runner.canonical_bytes(result) + b"\n"
    digest = sha256(result_bytes).hexdigest()
    return adjudication.AdjudicationCommandRecord(
        provenance_version=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        command_index=command_index,
        event_id=f"projection-{command_index}",
        started_event_ordinal=command_index * 2,
        completed_event_ordinal=command_index * 2 + 1,
        plan_sha256="a" * 64,
        operation_index=operation_index,
        argv=argv,
        exit_code=0,
        outcome="success",
        result_bytes=result_bytes,
        raw_result_sha256=digest,
        retained_result_sha256=digest,
    )


def _behavioral_view(
    adjudication: Any,
    *,
    created: tuple[str, ...] = (),
    changed: tuple[str, ...] = (),
    removed: tuple[str, ...] = (),
    support: tuple[str, ...] = (),
    semantic: tuple[str, ...] = (),
) -> Any:
    import run_complete_suite_campaign as runner

    values = {
        "full_created_paths": created,
        "full_changed_paths": changed,
        "full_removed_paths": removed,
        "agent_working_files": (),
        "implicit_working_directories": (),
        "product_support_paths": support,
        "semantic_created_paths": semantic,
    }
    record = {name: list(value) for name, value in values.items()}
    return adjudication.BehavioralFilesystemView(
        **values,
        canonical_sha256=sha256(runner.canonical_bytes(record)).hexdigest(),
    )


def test_provenance_v1_runtime_context_binds_session_from_authenticated_argv(
) -> None:
    import complete_suite_adjudication as adjudication

    context = {
        "character_id": "rin-aster",
        "character_version": "1.0.0",
    }
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=(
            "kokoro",
            "runtime",
            "context",
            "--session",
            "explicit-demo",
            "--locale",
            "en-US",
            "--scenario",
            "debugging",
            "--json",
        ),
        result={"ok": True, "context": context},
    )
    item = adjudication._direct_cli_records((record,))[0]

    assert adjudication._runtime_context(
        item,
        session_id="explicit-demo",
        typed=True,
    ) == context


@pytest.mark.parametrize(
    ("selected_path", "selected_version", "expected_selection"),
    (
        (r"inputs\explicit-compiled.json", "1.0.0", True),
        (
            r"data\installed\original\rin-aster\2.0.0\compiled.json",
            "2.0.0",
            False,
        ),
    ),
)
def test_provenance_v1_explicit_precedence_binds_prepared_selection(
    tmp_path: Path,
    selected_path: str,
    selected_version: str,
    expected_selection: bool,
) -> None:
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    case = _complete_case("explicit-character-precedence")
    session_id = "explicit-demo"
    setup = {
        "schema_version": "1.0",
        "case_id": case["id"],
        "paths": {"explicit_compiled": "inputs/explicit-compiled.json"},
        "values": {
            "session_id": session_id,
            "expected_version": "1.0.0",
        },
    }
    reason = (
        "Optimistic concurrency compares the expected state revision before "
        "applying a write, preventing a stale update."
    )
    rendered_text = (
        f"The explicit character version {selected_version} overrode both saved "
        f"defaults. {reason}"
    )
    session = {
        "session_id": session_id,
        "character_id": "rin-aster",
        "character_version": selected_version,
        "active": True,
        "state_revision": 0,
    }
    skill = SKILLS_ROOT.parent.parent / "skills" / "using-kokoroarc" / "SKILL.md"
    contract = skill.parent / "references" / "runtime-contract.md"
    prepared_files = {
        ".agents/skills/using-kokoroarc/SKILL.md": skill.read_bytes(),
        (
            ".agents/skills/using-kokoroarc/references/runtime-contract.md"
        ): contract.read_bytes(),
        "inputs/setup.json": runner.canonical_bytes(setup) + b"\n",
        "inputs/explicit-compiled.json": (
            b'{"character_id":"rin-aster","character_version":"1.0.0"}\n'
        ),
        "data/config/global.json": (
            b'{"character_id":"rin-aster","character_version":"1.0.1"}\n'
        ),
        "data/config/workspaces/workspace.json": (
            b'{"character_id":"rin-aster","character_version":"1.0.1"}\n'
        ),
        "data/runtime/semantic.json": b'{"artifact_id":"semantic/result"}\n',
        "data/runtime/plan.json": b'{"artifact_id":"plan/result"}\n',
        "data/runtime/rendered.json": (
            runner.canonical_bytes({"text": rendered_text}) + b"\n"
        ),
    }
    prepared_files.setdefault(
        selected_path.replace("\\", "/"),
        (
            b'{"character_id":"rin-aster","character_version":"'
            + selected_version.encode("ascii")
            + b'"}\n'
        ),
    )
    case_root, retained_run, _ledger = _import_command_run(
        tmp_path,
        case_id=case["id"],
        final_document=_claimed_final(
            case,
            outcome="completed",
            response=rendered_text,
        ),
        prepared_files=prepared_files,
        generated_files={
            f"data/sessions/{session_id}.json": (
                runner.canonical_bytes(session) + b"\n"
            ),
        },
        create_result_artifact=False,
    )
    records = (
        _projection_record(
            command_index=0,
            operation_index=0,
            argv=("Get-Content", "-Raw", r".agents\skills\using-kokoroarc\SKILL.md"),
        ),
        _projection_record(
            command_index=1,
            operation_index=0,
            argv=(
                "Get-Content",
                "-Raw",
                r".agents\skills\using-kokoroarc\references\runtime-contract.md",
            ),
        ),
        _projection_record(
            command_index=2,
            operation_index=0,
            argv=(
                "kokoro",
                "session",
                "start",
                "--session",
                session_id,
                "--character",
                selected_path,
                "--json",
            ),
            result={"ok": True, "session": session},
        ),
        _projection_record(
            command_index=3,
            operation_index=0,
            argv=(
                "kokoro",
                "runtime",
                "context",
                "--session",
                session_id,
                "--locale",
                "en-US",
                "--scenario",
                "debugging",
                "--json",
            ),
            result={
                "ok": True,
                "context": {
                    "character_id": "rin-aster",
                    "character_version": selected_version,
                },
            },
        ),
        _projection_record(
            command_index=4,
            operation_index=0,
            argv=(
                "kokoro",
                "runtime",
                "validate",
                "--semantic",
                r"data\runtime\semantic.json",
                "--plan",
                r"data\runtime\plan.json",
                "--rendered",
                r"data\runtime\rendered.json",
                "--json",
            ),
            result={
                "ok": True,
                "validation": {
                    "valid": True,
                    "violations": [],
                    "fallback_level": 0,
                },
            },
        ),
        _projection_record(
            command_index=5,
            operation_index=0,
            argv=("Get-Content", "-Raw", r"data\runtime\rendered.json"),
        ),
    )
    session_relative = f"data/sessions/{session_id}.json"
    semantic = ("workspace\\" + session_relative.replace("/", "\\"),)

    observed = adjudication._session_observations(
        case["id"],
        case_root,
        retained_run,
        records,
        _claimed_final(case, outcome="completed", response=rendered_text),
        filesystem_view=_behavioral_view(
            adjudication,
            created=semantic,
            semantic=semantic,
        ),
    )

    assert observed["honor_explicit_character_selection"] is expected_selection


def test_provenance_v1_authenticated_session_read_rejects_byte_identical_replacement(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding

    session_root = tmp_path / "retained"
    session_root.mkdir()
    session_path = session_root / "session.jsonl"
    payload = b'{"type":"thread.started","thread_id":"thread-1"}\n'
    session_path.write_bytes(payload)
    identity = cli_binding._session_identity_from_stat(
        "session.jsonl",
        session_path.stat(),
    )

    assert adjudication._read_bound_session_bytes(
        domain="retained",
        session_root=session_root,
        session_path=session_path,
        expected_identity=identity,
    ) == payload

    session_path.unlink()
    session_path.write_bytes(payload)

    with pytest.raises(RuntimeError, match="COMMAND_CAPTURE_INVALID"):
        adjudication._read_bound_session_bytes(
            domain="retained",
            session_root=session_root,
            session_path=session_path,
            expected_identity=identity,
        )


def test_provenance_v1_admin_records_derive_current_product_targets() -> None:
    import complete_suite_adjudication as adjudication

    workspace_id = "a" * 64
    relative_path = rf"workspaces\{workspace_id}\rin-aster\1.0.0"
    plan = {
        "scope": "workspace",
        "workspace_id": workspace_id,
        "relative_path": relative_path,
        "idempotent": False,
        "will_write": True,
    }
    install_record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=(
            "kokoro",
            "pack",
            "install",
            r"inputs\rin-1.0.0.karc",
            "--scope",
            "workspace",
            "--workspace",
            ".",
            "--json",
        ),
        result={
            "ok": True,
            "dry_run": False,
            "plan": plan,
            "activates_character": False,
        },
    )
    install_item = adjudication._direct_cli_records((install_record,))[0]
    normalized_install = adjudication._install_record(
        install_item,
        scope="workspace",
        dry_run=False,
        typed=True,
    )

    assert normalized_install is not None
    assert normalized_install["registry_path"] == (
        f"data/registry/workspaces/{workspace_id}.json"
    )
    assert normalized_install["pack_path"] == (
        f"data/installed/workspaces/{workspace_id}/rin-aster/1.0.0/"
        "pack/compiled.json"
    )
    assert normalized_install["changed"] is True

    default = {
        "scope": "global",
        "workspace_id": None,
        "binding": {
            "character_id": "rin-aster",
            "character_version": "1.0.0",
        },
    }
    default_record = _projection_record(
        command_index=1,
        operation_index=0,
        argv=(
            "kokoro",
            "config",
            "default",
            "set",
            "--character",
            "rin-aster",
            "--version",
            "1.0.0",
            "--scope",
            "global",
            "--json",
        ),
        result={"ok": True, "default": default, "activates_character": False},
    )
    default_item = adjudication._direct_cli_records((default_record,))[0]
    normalized_default = adjudication._default_record(
        default_item,
        action="set",
        typed=True,
    )

    assert normalized_default is not None
    assert normalized_default["path"] == "data/config/global.json"
    assert normalized_default["version"] == "1.0.0"


def test_provenance_v1_admin_parsers_accept_authorized_absolute_workspace_operands(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_command_policy as command_policy
    from test_complete_suite_command_policy import _bound_plan, _context

    context = _context(tmp_path, case_id="safe-install-inactive")
    workspace_id = "a" * 64

    def authorized_argv(*argv: str) -> tuple[str, ...]:
        decision = command_policy.authorize_command_plan(
            _bound_plan(*argv),
            context=context,
        )
        operation = decision.operations[0]
        workspace_value = operation.argv[operation.argv.index("--workspace") + 1]
        assert workspace_value == str(context.workspace_root)
        return operation.argv

    install_record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=authorized_argv(
            "kokoro",
            "pack",
            "install",
            r".\inputs\archive.karc",
            "--scope",
            "workspace",
            "--workspace",
            ".",
            "--json",
        ),
        result={
            "ok": True,
            "dry_run": False,
            "plan": {
                "scope": "workspace",
                "workspace_id": workspace_id,
                "registry_identity": "original/rin-aster/1.0.0",
                "relative_path": (
                    rf"workspaces\{workspace_id}\rin-aster\1.0.0"
                ),
                "archive_sha256": "b" * 64,
                "visibility": "private",
                "idempotent": False,
                "will_write": True,
            },
            "activates_character": False,
        },
    )
    default_record = _projection_record(
        command_index=1,
        operation_index=0,
        argv=authorized_argv(
            "kokoro",
            "config",
            "default",
            "set",
            "--character",
            "rin-aster",
            "--version",
            "1.0.0",
            "--scope",
            "workspace",
            "--workspace",
            ".",
            "--json",
        ),
        result={
            "ok": True,
            "default": {
                "scope": "workspace",
                "workspace_id": workspace_id,
                "binding": {
                    "character_id": "rin-aster",
                    "character_version": "1.0.0",
                },
            },
            "activates_character": False,
        },
    )
    session_record = _projection_record(
        command_index=2,
        operation_index=0,
        argv=authorized_argv(
            "kokoro",
            "session",
            "start",
            "--session",
            "workspace-demo",
            "--workspace",
            ".",
            "--json",
        ),
        result={
            "ok": True,
            "session": {
                "session_id": "workspace-demo",
                "active": True,
                "character_id": "rin-aster",
                "character_version": "1.0.0",
                "compiled_pack_hash": "c" * 64,
            },
        },
    )

    install_item = adjudication._direct_cli_records((install_record,))[0]
    default_item = adjudication._direct_cli_records((default_record,))[0]
    session_item = adjudication._direct_cli_records((session_record,))[0]

    assert adjudication._install_record(
        install_item,
        scope="workspace",
        dry_run=False,
        typed=True,
        expected_workspace=context.workspace_root,
    ) is not None
    assert adjudication._default_record(
        default_item,
        action="set",
        typed=True,
        expected_workspace=context.workspace_root,
    ) is not None
    assert adjudication._session_start(
        session_item,
        session_id="workspace-demo",
        workspace=True,
        typed=True,
        expected_workspace=context.workspace_root,
    ) is not None


def test_provenance_v1_consent_record_uses_current_status_and_grant_revision(
) -> None:
    import complete_suite_adjudication as adjudication

    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=(
            "kokoro",
            "consent",
            "show",
            "--character",
            "rin-aster",
            "--scope",
            "global",
            "--json",
        ),
        result={
            "ok": True,
            "consent": {
                "status": "active",
                "grant_revision": 1,
                "scope": "global",
                "workspace_id": None,
                "installation": {
                    "namespace": "original",
                    "character_id": "rin-aster",
                    "character_version": "1.0.0",
                },
                "permissions": ["memory_references"],
            },
        },
    )
    item = adjudication._direct_cli_records((record,))[0]

    consent = adjudication._consent_show(
        item,
        permission="memory_references",
        typed=True,
    )

    assert consent is not None
    assert consent["active"] is True
    assert consent["revision"] == 1


@pytest.mark.parametrize(
    ("event_argument", "selected_event_id", "expected_application"),
    (
        (
            r"inputs\relationship-event.json",
            "task18-consented-relationship-01",
            True,
        ),
        (r"inputs\substituted-event.json", "event-01", False),
    ),
)
def test_provenance_v1_persistence_binds_prepared_event_input(
    tmp_path: Path,
    event_argument: str,
    selected_event_id: str,
    expected_application: bool,
) -> None:
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    case = _complete_case("consented-persistence-replay")
    session_id = "persistence-demo"
    canonical_event_id = "task18-consented-relationship-01"

    def event_document(event_id: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "artifact_id": f"event/{event_id}",
            "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
            "event_id": event_id,
            "turn_id": "task18-turn-01",
            "origin": "verified_task_outcome",
            "novelty_key": f"{event_id}-novelty",
            "expected_state_revision": 0,
            "evaluator_version": "interaction-v1",
            "evidence": {"kind": "test_result", "reference": "approved fixture"},
            "confidence": 1.0,
            "effects": {"trust": 2.0},
        }

    setup = {
        "schema_version": "1.0",
        "case_id": case["id"],
        "paths": {"event": "inputs/relationship-event.json"},
        "values": {
            "session_id": session_id,
            "consent_id": "consent-task18-01",
            "consent_revision": 1,
            "export": "outputs/persistent-state.json",
        },
    }
    selected_event = event_document(selected_event_id)
    state = {
        "schema_version": "1.0",
        "revision": 1,
        "applied_event_ids": [selected_event_id],
    }
    retained_event = {
        "schema_version": "1.0",
        "event": selected_event,
        "transition": {
            "algorithm": "relationship-v1",
            "max_delta": 2.0,
            "repetition_window": 8,
        },
    }
    session = {"session_id": session_id, "state_revision": 1}
    export_document = {
        "schema_version": "1.0",
        "character_id": "rin-aster",
        "state": state,
    }
    export_payload = runner.canonical_bytes(export_document) + b"\n"
    event_output = f"data/events/{session_id}/1-{selected_event_id}.json"
    state_path = f"data/state/{session_id}.json"
    session_path = f"data/sessions/{session_id}.json"
    export_path = "outputs/persistent-state.json"
    skill = SKILLS_ROOT.parent.parent / "skills" / "using-kokoroarc" / "SKILL.md"
    prepared_files = {
        ".agents/skills/using-kokoroarc/SKILL.md": skill.read_bytes(),
        "inputs/setup.json": runner.canonical_bytes(setup) + b"\n",
        "inputs/relationship-event.json": (
            runner.canonical_bytes(event_document(canonical_event_id)) + b"\n"
        ),
        "inputs/substituted-event.json": (
            runner.canonical_bytes(event_document("event-01")) + b"\n"
        ),
    }
    case_root, retained_run, _ledger = _import_command_run(
        tmp_path,
        case_id=case["id"],
        final_document=_claimed_final(
            case,
            outcome="completed",
            response=(
                "Consent generation 1 authorized relationship_state. "
                f"Event {selected_event_id} was applied once; the retry was "
                "idempotent. Exported exact revision 1 and compared replayed "
                "and exported state."
            ),
        ),
        prepared_files=prepared_files,
        generated_files={
            event_output: runner.canonical_bytes(retained_event) + b"\n",
            state_path: runner.canonical_bytes(state) + b"\n",
            session_path: runner.canonical_bytes(session) + b"\n",
            export_path: export_payload,
        },
        create_result_artifact=False,
    )
    consent = {
        "status": "active",
        "grant_revision": 1,
        "scope": "global",
        "workspace_id": None,
        "installation": {
            "namespace": "original",
            "character_id": "rin-aster",
            "character_version": "1.0.0",
        },
        "permissions": ["relationship_state"],
    }

    def state_argv(action: str) -> tuple[str, ...]:
        return (
            "kokoro",
            "state",
            action,
            "--session",
            session_id,
            "--event",
            event_argument,
            "--json",
        )

    response = (
        "Consent generation 1 authorized relationship_state. "
        f"Event {selected_event_id} was applied once; the retry was idempotent. "
        "Exported exact revision 1 and compared replayed and exported state."
    )
    records = (
        _projection_record(
            command_index=0,
            operation_index=0,
            argv=("Get-Content", "-Raw", r".agents\skills\using-kokoroarc\SKILL.md"),
        ),
        _projection_record(
            command_index=1,
            operation_index=0,
            argv=(
                "kokoro",
                "consent",
                "show",
                "--character",
                "rin-aster",
                "--scope",
                "global",
                "--json",
            ),
            result={"ok": True, "consent": consent},
        ),
        _projection_record(
            command_index=2,
            operation_index=0,
            argv=state_argv("preview"),
            result={"ok": True, "state": state},
        ),
        _projection_record(
            command_index=3,
            operation_index=0,
            argv=state_argv("apply"),
            result={"ok": True, "state": state},
        ),
        _projection_record(
            command_index=4,
            operation_index=0,
            argv=state_argv("apply"),
            result={"ok": True, "state": state},
        ),
        _projection_record(
            command_index=5,
            operation_index=0,
            argv=(
                "kokoro",
                "state",
                "export",
                "--character",
                "rin-aster",
                "--scope",
                "global",
                "--out",
                export_path.replace("/", "\\"),
                "--json",
            ),
            result={"ok": True, "export_sha256": sha256(export_payload).hexdigest()},
        ),
    )
    semantic = tuple(
        "workspace\\" + path.replace("/", "\\")
        for path in (event_output, export_path)
    )
    changed = tuple(
        "workspace\\" + path.replace("/", "\\")
        for path in (state_path, session_path)
    )
    final = _claimed_final(case, outcome="completed", response=response)

    observed = adjudication._persistence_observations(
        case_root,
        retained_run,
        records,
        final,
        filesystem_view=_behavioral_view(
            adjudication,
            created=semantic,
            changed=changed,
            support=changed,
            semantic=semantic,
        ),
    )

    assert observed["apply_one_structured_event"] is expected_application


@pytest.mark.parametrize(
    ("observed_host_id", "expected_lifecycle"),
    (
        ("host-memory-task18-01", True),
        ("host-memory-other-01", False),
    ),
)
def test_provenance_v1_memory_observer_binds_prepared_host_memory_id(
    tmp_path: Path,
    observed_host_id: str,
    expected_lifecycle: bool,
) -> None:
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    case = _complete_case("memory-reference-ownership")
    expected_host_id = "host-memory-task18-01"
    reference_id = "memory-" + "a" * 32
    summary = {"summary": "One bounded approved summary."}
    setup = {
        "schema_version": "1.0",
        "case_id": case["id"],
        "paths": {"summary": "inputs/memory-summary.json"},
        "values": {
            "host_memory_id": expected_host_id,
            "consent_revision": 1,
        },
    }
    skill = SKILLS_ROOT.parent.parent / "skills" / "using-kokoroarc" / "SKILL.md"
    final = _claimed_final(
        case,
        outcome="completed",
        response=(
            "Consent generation 1 was active. I added and listed the host-owned "
            "reference, then removed it. KokoroArc stored only the host-owned "
            "reference and bounded approved summary, copied no host payload, and "
            "stored no private conversation transcript."
        ),
    )
    support_relatives = (
        "data/memory-references",
        "data/memory-references/global",
        "data/memory-references/global/original",
        "data/memory-references/global/original/rin-aster",
        "data/persistence-locks",
        "data/persistence-locks/global",
    )
    lock_path = "data/persistence-locks/global/original.rin-aster.lock"
    case_root, retained_run, _ledger = _import_command_run(
        tmp_path,
        case_id=case["id"],
        final_document=final,
        prepared_files={
            ".agents/skills/using-kokoroarc/SKILL.md": skill.read_bytes(),
            "inputs/setup.json": runner.canonical_bytes(setup) + b"\n",
            "inputs/memory-summary.json": runner.canonical_bytes(summary) + b"\n",
        },
        generated_files={lock_path: b""},
        generated_directories=support_relatives,
        create_result_artifact=False,
    )
    reference = {
        "memory_reference_id": reference_id,
        "host_memory_id": observed_host_id,
        "summary": summary["summary"],
        "scope": "global",
        "workspace_id": None,
        "namespace": "original",
        "character_id": "rin-aster",
    }
    consent = {
        "status": "active",
        "grant_revision": 1,
        "scope": "global",
        "workspace_id": None,
        "installation": {
            "namespace": "original",
            "character_id": "rin-aster",
            "character_version": "1.0.0",
        },
        "permissions": ["memory_references"],
    }

    def memory_argv(action: str, *extra: str) -> tuple[str, ...]:
        return (
            "kokoro",
            "memory",
            action,
            "--character",
            "rin-aster",
            "--scope",
            "global",
            *extra,
            "--json",
        )

    records = (
        _projection_record(
            command_index=0,
            operation_index=0,
            argv=("Get-Content", "-Raw", r".agents\skills\using-kokoroarc\SKILL.md"),
        ),
        _projection_record(
            command_index=1,
            operation_index=0,
            argv=(
                "kokoro",
                "consent",
                "show",
                "--character",
                "rin-aster",
                "--scope",
                "global",
                "--json",
            ),
            result={"ok": True, "consent": consent},
        ),
        _projection_record(
            command_index=2,
            operation_index=0,
            argv=memory_argv(
                "add",
                "--host-id",
                observed_host_id,
                "--summary-file",
                r"inputs\memory-summary.json",
            ),
            result={"ok": True, "memory_reference": reference},
        ),
        _projection_record(
            command_index=3,
            operation_index=0,
            argv=memory_argv("list"),
            result={
                "ok": True,
                "memory_references": [
                    {"reference": reference, "active_consent_generation": True}
                ],
            },
        ),
        _projection_record(
            command_index=4,
            operation_index=0,
            argv=memory_argv(
                "remove",
                "--host-id",
                observed_host_id,
                "--dry-run",
            ),
            result={
                "ok": True,
                "dry_run": True,
                "plan": {
                    "host_memory_id": observed_host_id,
                    "memory_reference_id": reference_id,
                    "will_remove": True,
                },
            },
        ),
        _projection_record(
            command_index=5,
            operation_index=0,
            argv=memory_argv("remove", "--host-id", observed_host_id),
            result={
                "ok": True,
                "dry_run": False,
                "result": {
                    "removed": True,
                    "memory_reference_id": reference_id,
                },
            },
        ),
        _projection_record(
            command_index=6,
            operation_index=0,
            argv=memory_argv("list"),
            result={"ok": True, "memory_references": []},
        ),
    )
    support = tuple(
        "workspace\\" + path.replace("/", "\\")
        for path in (*support_relatives, lock_path)
    )
    observed = adjudication._memory_observations(
        case_root,
        retained_run,
        records,
        final,
        filesystem_view=_behavioral_view(
            adjudication,
            created=support,
            support=support,
        ),
    )

    assert observed["add_host_owned_memory_reference"] is expected_lifecycle
    assert observed["remove_same_memory_reference"] is expected_lifecycle


def test_provenance_v1_original_authoring_observer_accepts_current_shapes(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    case = _complete_case("original-authoring-route")
    request = json.loads(
        (SKILLS_ROOT.parent / "fixtures" / "authoring" / "original-request.json")
        .read_text(encoding="utf-8")
    )
    report = {
        "valid": True,
        "hard_failures": [],
        "advisory_findings": [],
        "locale_coverage": {"zh-CN": True, "en-US": True, "ja-JP": True},
        "provenance_counts": {
            "evidence": 1,
            "derived_profile": 2,
            "user_override": 0,
        },
    }
    draft = {
        "artifact_id": "original/rin-aster/draft/" + "b" * 16,
        "build_status": "draft",
        "visibility": "private",
        "activation_allowed": False,
        "mode": "original",
        "locale_coverage": dict(report["locale_coverage"]),
        "unresolved_warnings": [],
    }
    bundle_path = "data/drafts/original/rin-aster/draft/" + "b" * 16
    draft_path = f"{bundle_path}/draft.json"
    final = _claimed_final(
        case,
        outcome="completed",
        response=(
            "Wholly original mode validated twice. Preserved en-US, ja-JP, and "
            f"zh-CN. The draft is private, inactive at {bundle_path}; "
            "activation_allowed: false."
        ),
    )
    skill = SKILLS_ROOT.parent.parent / "skills" / "authoring-character-packs" / "SKILL.md"
    contract = skill.parent / "references" / "authoring-contract.md"
    prepared = {
        ".agents/skills/authoring-character-packs/SKILL.md": skill.read_bytes(),
        (
            ".agents/skills/authoring-character-packs/references/"
            "authoring-contract.md"
        ): contract.read_bytes(),
        "inputs/request.json": runner.canonical_bytes(request) + b"\n",
        "source-packs/rin/character.yaml": b"schema_version: '1.0'\n",
    }
    case_root, retained_run, _ledger = _import_command_run(
        tmp_path,
        case_id=case["id"],
        final_document=final,
        prepared_files=prepared,
        generated_files={draft_path: runner.canonical_bytes(draft) + b"\n"},
        create_result_artifact=False,
    )
    records = (
        _projection_record(
            command_index=0,
            operation_index=0,
            argv=("Get-Content", "-Raw", r".agents\skills\authoring-character-packs\SKILL.md"),
        ),
        _projection_record(
            command_index=1,
            operation_index=0,
            argv=(
                "Get-Content",
                "-Raw",
                r".agents\skills\authoring-character-packs\references\authoring-contract.md",
            ),
        ),
        *tuple(
            _projection_record(
                command_index=index,
                operation_index=0,
                argv=(
                    "kokoro",
                    "character",
                    "request",
                    "validate",
                    "--input",
                    r"inputs\request.json",
                    "--json",
                ),
                result={"ok": True, "request": request},
            )
            for index in (2, 3)
        ),
        *tuple(
            _projection_record(
                command_index=index,
                operation_index=0,
                argv=(
                    "kokoro",
                    "character",
                    "draft",
                    "validate",
                    "--request",
                    r"inputs\request.json",
                    "--pack",
                    r"source-packs\rin",
                    "--json",
                ),
                result={"ok": True, "valid": True, "validation_report": report},
            )
            for index in (4, 5)
        ),
        _projection_record(
            command_index=6,
            operation_index=0,
            argv=(
                "kokoro",
                "character",
                "draft",
                "compile",
                "--request",
                r"inputs\request.json",
                "--pack",
                r"source-packs\rin",
                "--json",
            ),
            result={
                "ok": True,
                "path": bundle_path.replace("/", "\\"),
                "artifact_id": draft["artifact_id"],
                "request_hash": "1" * 64,
                "source_pack_hash": "2" * 64,
                "validation_report_hash": "3" * 64,
                "build_status": "draft",
                "visibility": "private",
                "activation_allowed": False,
                "validation_report": report,
            },
        ),
    )
    semantic = ("workspace\\" + draft_path.replace("/", "\\"),)
    observed = adjudication._authoring_observations(
        case_root,
        retained_run,
        records,
        final,
        filesystem_view=_behavioral_view(
            adjudication,
            created=semantic,
            semantic=semantic,
        ),
    )

    assert observed
    assert all(observed[item] for item in case["must"])
    assert not any(observed[item] for item in case["must_not"])


def test_provenance_v1_authoring_source_is_consumed_by_exact_pack_directory() -> None:
    import complete_suite_adjudication as adjudication

    class Operation:
        argv = (
            "kokoro",
            "character",
            "draft",
            "validate",
            "--request",
            r"data\authoring\mika-moongear\request.json",
            "--pack",
            r"data\authoring\mika-moongear",
            "--json",
        )

    assert adjudication._operation_consumes_path(
        Operation(),
        r"workspace\data\authoring\mika-moongear\identity.yaml",
        workspace_relative_root="workspace",
        directory_option="--pack",
    ) is True
    assert adjudication._operation_consumes_path(
        Operation(),
        r"workspace\data\authoring\other\identity.yaml",
        workspace_relative_root="workspace",
        directory_option="--pack",
    ) is False


def test_provenance_v1_consumer_binding_isolated_to_the_named_option() -> None:
    import complete_suite_adjudication as adjudication

    semantic_path = r"data\semantic-workspace-demo.json"
    policy_path = r"data\policy-workspace-demo.json"

    class SwappedOperation:
        argv = (
            "kokoro",
            "runtime",
            "plan",
            "--semantic",
            policy_path,
            "--policy",
            semantic_path,
            "--json",
        )

    assert adjudication._operation_consumes_path(
        SwappedOperation(),
        rf"workspace\{semantic_path}",
        workspace_relative_root="workspace",
        option_names=("--semantic",),
    ) is False
    assert adjudication._operation_consumes_path(
        SwappedOperation(),
        rf"workspace\{policy_path}",
        workspace_relative_root="workspace",
        option_names=("--policy",),
    ) is False


def test_provenance_v1_relative_operand_named_workspace_stays_cwd_relative() -> None:
    import complete_suite_adjudication as adjudication

    class Operation:
        argv = (
            "kokoro",
            "runtime",
            "plan",
            "--semantic",
            r"workspace\data\semantic.json",
            "--policy",
            r"data\policy.json",
            "--json",
        )

    assert adjudication._operation_consumes_path(
        Operation(),
        r"workspace\data\semantic.json",
        workspace_relative_root="workspace",
        option_names=("--semantic",),
    ) is False


def test_provenance_v1_rejects_split_multi_input_action_binding() -> None:
    import complete_suite_adjudication as adjudication

    action = ("runtime", "plan")
    semantic = r"<workspace>\data\semantic.json"
    policy = r"<workspace>\data\policy.json"
    rules = (
        SimpleNamespace(
            normalized_path=semantic,
            role="semantic_result",
            producer_action=None,
            consumer_actions=(action,),
            result_selector=None,
        ),
        SimpleNamespace(
            normalized_path=policy,
            role="language_policy",
            producer_action=None,
            consumer_actions=(action,),
            result_selector=None,
        ),
    )
    contents = tuple(
        SimpleNamespace(
            normalized_path=path,
            raw_document_sha256="a" * 64,
            retained_document_sha256="a" * 64,
        )
        for path in (semantic, policy)
    )
    changes = tuple(
        SimpleNamespace(
            normalized_path=path,
            started_event_ordinal=0,
            completed_event_ordinal=1,
        )
        for path in (semantic, policy)
    )
    argvs = (
        (
            "kokoro",
            "runtime",
            "plan",
            "--semantic",
            r"data\semantic.json",
            "--policy",
            r"data\wrong-policy.json",
            "--json",
        ),
        (
            "kokoro",
            "runtime",
            "plan",
            "--semantic",
            r"data\wrong-semantic.json",
            "--policy",
            r"data\policy.json",
            "--json",
        ),
    )
    records = tuple(
        _projection_record(
            command_index=index,
            operation_index=0,
            argv=argv,
            result={"ok": True},
        )
        for index, argv in enumerate(argvs, start=1)
    )
    operations = tuple(
        SimpleNamespace(
            command_index=record.command_index,
            operation_index=0,
            argv=record.argv,
            declared_output_paths=(),
            selected_values=(),
        )
        for record in records
    )
    file_changes = SimpleNamespace(
        unique_final_paths=(semantic, policy),
        contents=contents,
        changes=changes,
    )
    origin = SimpleNamespace(
        rules=rules,
        workspace_relative_root="workspace",
    )

    with pytest.raises(
        RuntimeError,
        match="FILE_CHANGE_OPERATION_BINDING_INVALID",
    ):
        adjudication._bind_file_change_operations(
            file_changes=file_changes,
            origin=origin,
            command_records=records,
            operations=operations,
        )


def test_provenance_v1_rejects_producer_with_different_bound_inputs() -> None:
    import complete_suite_adjudication as adjudication

    action = ("character", "draft", "validate")
    request = r"<workspace>\data\authoring\mika-moongear\request.json"
    source = r"<workspace>\data\authoring\mika-moongear\identity.yaml"
    validation = (
        r"<workspace>\data\authoring\mika-moongear\validation\draft.json"
    )
    rules = (
        SimpleNamespace(
            normalized_path=request,
            role="authoring_request",
            producer_action=None,
            consumer_actions=(action,),
            result_selector=None,
        ),
        SimpleNamespace(
            normalized_path=source,
            role="authoring_source",
            producer_action=None,
            consumer_actions=(action,),
            result_selector=None,
        ),
        SimpleNamespace(
            normalized_path=validation,
            role="authoring_validation_result",
            producer_action=action,
            consumer_actions=(),
            result_selector=(),
        ),
    )
    selected_sha256 = "c" * 64
    contents = (
        SimpleNamespace(
            normalized_path=request,
            raw_document_sha256="a" * 64,
            retained_document_sha256="a" * 64,
        ),
        SimpleNamespace(
            normalized_path=source,
            raw_document_sha256="b" * 64,
            retained_document_sha256="b" * 64,
        ),
        SimpleNamespace(
            normalized_path=validation,
            raw_document_sha256=selected_sha256,
            retained_document_sha256=selected_sha256,
        ),
    )
    changes = (
        SimpleNamespace(
            normalized_path=request,
            started_event_ordinal=0,
            completed_event_ordinal=1,
        ),
        SimpleNamespace(
            normalized_path=source,
            started_event_ordinal=0,
            completed_event_ordinal=1,
        ),
        SimpleNamespace(
            normalized_path=validation,
            started_event_ordinal=6,
            completed_event_ordinal=7,
        ),
    )
    argvs = (
        (
            "kokoro",
            "character",
            "draft",
            "validate",
            "--request",
            r"data\authoring\mika-moongear\request.json",
            "--pack",
            r"data\authoring\mika-moongear",
            "--json",
        ),
        (
            "kokoro",
            "character",
            "draft",
            "validate",
            "--request",
            r"data\authoring\mika-moongear\request.json",
            "--pack",
            r"data\authoring\other",
            "--json",
        ),
    )
    records = tuple(
        _projection_record(
            command_index=index,
            operation_index=0,
            argv=argv,
            result={"ok": True},
        )
        for index, argv in enumerate(argvs, start=1)
    )
    operations = tuple(
        SimpleNamespace(
            command_index=record.command_index,
            operation_index=0,
            argv=record.argv,
            declared_output_paths=(),
            selected_values=(
                SimpleNamespace(
                    selector=(),
                    raw_sha256=("d" * 64 if index == 0 else selected_sha256),
                    retained_sha256=(
                        "d" * 64 if index == 0 else selected_sha256
                    ),
                ),
            ),
        )
        for index, record in enumerate(records)
    )
    file_changes = SimpleNamespace(
        unique_final_paths=(request, source, validation),
        contents=contents,
        changes=changes,
    )
    origin = SimpleNamespace(
        rules=rules,
        workspace_relative_root="workspace",
    )

    with pytest.raises(
        RuntimeError,
        match="FILE_CHANGE_OPERATION_BINDING_INVALID",
    ):
        adjudication._bind_file_change_operations(
            file_changes=file_changes,
            origin=origin,
            command_records=records,
            operations=operations,
        )


def test_provenance_v1_positive_cli_helpers_hide_nonresult_operations() -> None:
    import complete_suite_adjudication as adjudication

    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=("Get-Content", "-Raw", r"inputs\request.json"),
    )

    assert adjudication._cli_arguments(record) is None
    assert adjudication._cli_output(record) is None


@pytest.mark.parametrize("with_error_action", (False, True))
def test_provenance_v1_projection_claims_authenticated_silent_directory(
    tmp_path: Path,
    with_error_action: bool,
) -> None:
    import complete_suite_adjudication as adjudication

    new_item = (
        "New-Item",
        "-ItemType",
        "Directory",
        "-LiteralPath",
        r"outputs\reports",
        *(("-ErrorAction", "Stop") if with_error_action else ()),
    )
    records = (
        _projection_record(command_index=0, operation_index=0, argv=new_item),
        _projection_record(
            command_index=0,
            operation_index=1,
            argv=("Out-Null",),
        ),
    )

    class FileChanges:
        unique_final_paths = ()
        implicit_ancestor_paths = ()

    class Origin:
        workspace_relative_root = "workspace"
        rules = ()

    class NewItemOperation:
        command_index = 0
        operation_index = 0
        argv = new_item
        category = "silent_directory"
        declared_output_paths = ()

    class OutNullOperation:
        command_index = 0
        operation_index = 1
        argv = ("Out-Null",)
        category = "silent_directory"
        declared_output_paths = ()

    view = adjudication._filesystem_view(
        case_id="release-testing-route",
        filesystem=_projection_filesystem(
            tmp_path,
            ((r"outputs\reports", "created", "directory"),),
        ),
        file_changes=FileChanges(),
        origin=Origin(),
        command_records=records,
        operations=(NewItemOperation(), OutNullOperation()),
    )

    assert view.implicit_working_directories == (
        r"workspace\outputs\reports",
    )
    assert view.product_support_paths == ()


def test_provenance_v1_projection_requires_declared_success_output(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    argv = (
        "kokoro",
        "pack",
        "test",
        r"characters\original\rin-aster",
        "--request",
        r"inputs\request.json",
        "--out",
        r"reports\hard.json",
        "--json",
    )
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=argv,
        result={"ok": True, "path": r"reports\hard.json"},
    )

    class FileChanges:
        unique_final_paths = ()
        implicit_ancestor_paths = ()

    class Origin:
        workspace_relative_root = "workspace"
        rules = ()

    class Operation:
        command_index = 0
        operation_index = 0
        category = "kokoro_cli"
        declared_output_paths = (r"reports\hard.json",)
        argv = record.argv

    with pytest.raises(RuntimeError, match="FILE_CHANGE_PROJECTION_INVALID"):
        adjudication._filesystem_view(
            case_id="release-testing-route",
            filesystem=_projection_filesystem(tmp_path, ()),
            file_changes=FileChanges(),
            origin=Origin(),
            command_records=(record,),
            operations=(Operation(),),
        )


def test_provenance_v1_declared_workspace_prefix_remains_cwd_relative(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    declared = r"workspace\outputs\hard.json"
    argv = (
        "kokoro",
        "pack",
        "test",
        r"characters\original\rin-aster",
        "--request",
        r"inputs\request.json",
        "--out",
        declared,
        "--json",
    )
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=argv,
        result={"ok": True, "path": declared},
    )

    class FileChanges:
        unique_final_paths = ()
        implicit_ancestor_paths = ()

    class Origin:
        workspace_relative_root = "workspace"
        rules = ()

    class Operation:
        command_index = 0
        operation_index = 0
        category = "kokoro_cli"
        declared_output_paths = (declared,)
        argv = record.argv

    with pytest.raises(RuntimeError, match="FILE_CHANGE_PROJECTION_INVALID"):
        adjudication._filesystem_view(
            case_id="release-testing-route",
            filesystem=_projection_filesystem(
                tmp_path,
                ((r"outputs\hard.json", "created", "file"),),
            ),
            file_changes=FileChanges(),
            origin=Origin(),
            command_records=(record,),
            operations=(Operation(),),
        )


@pytest.mark.parametrize(
    ("visibility", "has_publication_readiness"),
    (("private", False), ("public_candidate", True)),
)
def test_provenance_v1_projection_matches_install_visibility_contract(
    tmp_path: Path,
    visibility: str,
    has_publication_readiness: bool,
) -> None:
    import complete_suite_adjudication as adjudication

    archive_sha256 = "b" * 64
    relative_path = r"global\rin-aster\1.0.0"
    install_root = rf"data\installed\{relative_path}"
    publication = rf"{install_root}\release\publication-readiness-report.json"
    members = (
        rf"{install_root}\manifest.json",
        rf"{install_root}\pack\compiled.json",
        rf"{install_root}\release\hard-validation-report.json",
        rf"{install_root}\release\promotion-record.json",
        rf"{install_root}\release\review-attestation.json",
        rf"{install_root}\release\soft-evaluation-report.json",
        *((publication,) if has_publication_readiness else ()),
    )
    entries = (
        (r"data\registry\global.json", "created", "file"),
        (r"data\registry\.global.lock", "created", "file"),
        *((member, "created", "file") for member in members),
        (rf"data\archives\{archive_sha256}.karc", "created", "file"),
        (r"data\registry\journals", "created", "directory"),
    )
    argv = (
        "kokoro",
        "pack",
        "install",
        r"inputs\rin-aster.karc",
        "--scope",
        "global",
        "--json",
    )
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=argv,
        result={
            "ok": True,
            "plan": {
                "will_write": True,
                "scope": "global",
                "workspace_id": None,
                "registry_identity": "original/rin-aster/1.0.0",
                "relative_path": relative_path,
                "archive_sha256": archive_sha256,
                "visibility": visibility,
            },
        },
    )

    class FileChanges:
        unique_final_paths = ()
        implicit_ancestor_paths = ()

    class Origin:
        workspace_relative_root = "workspace"
        rules = ()

    class Operation:
        command_index = 0
        operation_index = 0
        category = "kokoro_cli"
        declared_output_paths = ()
        argv = record.argv

    view = adjudication._filesystem_view(
        case_id="safe-install-inactive",
        filesystem=_projection_filesystem(tmp_path, entries),
        file_changes=FileChanges(),
        origin=Origin(),
        command_records=(record,),
        operations=(Operation(),),
    )

    assert (rf"workspace\{publication}" in view.product_support_paths) is (
        has_publication_readiness
    )


def test_provenance_v1_projection_skips_authenticated_install_preview(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    archive_sha256 = "b" * 64
    relative_path = r"global\rin-aster\1.0.0"
    install_root = rf"data\installed\{relative_path}"
    entries = (
        (r"data\registry\global.json", "created", "file"),
        *((rf"{install_root}\{member}", "created", "file") for member in (
            r"manifest.json",
            r"pack\compiled.json",
            r"release\hard-validation-report.json",
            r"release\promotion-record.json",
            r"release\review-attestation.json",
            r"release\soft-evaluation-report.json",
        )),
    )
    plan = {
        "will_write": True,
        "idempotent": False,
        "scope": "global",
        "workspace_id": None,
        "registry_identity": "original/rin-aster/1.0.0",
        "relative_path": relative_path,
        "archive_sha256": archive_sha256,
        "visibility": "private",
    }
    preview_argv = (
        "kokoro",
        "pack",
        "install",
        r"inputs\rin-aster.karc",
        "--scope",
        "global",
        "--dry-run",
        "--json",
    )
    install_argv = tuple(value for value in preview_argv if value != "--dry-run")
    records = (
        _projection_record(
            command_index=0,
            operation_index=0,
            argv=preview_argv,
            result={
                "ok": True,
                "dry_run": True,
                "plan": plan,
                "activates_character": False,
            },
        ),
        _projection_record(
            command_index=1,
            operation_index=0,
            argv=install_argv,
            result={
                "ok": True,
                "dry_run": False,
                "plan": plan,
                "activates_character": False,
            },
        ),
    )
    operations = tuple(
        SimpleNamespace(
            command_index=index,
            operation_index=0,
            category="kokoro_cli",
            declared_output_paths=(),
            argv=record.argv,
        )
        for index, record in enumerate(records)
    )

    view = adjudication._filesystem_view(
        case_id="safe-install-inactive",
        filesystem=_projection_filesystem(tmp_path, entries),
        file_changes=SimpleNamespace(
            unique_final_paths=(),
            implicit_ancestor_paths=(),
        ),
        origin=SimpleNamespace(workspace_relative_root="workspace", rules=()),
        command_records=records,
        operations=operations,
    )

    assert (
        r"workspace\data\installed\global\rin-aster\1.0.0\pack\compiled.json"
        in view.semantic_created_paths
    )


def test_provenance_v1_projection_accepts_authorized_absolute_workspace_operand(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication
    import complete_suite_command_policy as command_policy
    from test_complete_suite_command_policy import _bound_plan, _context, _entry

    workspace_id = "a" * 64
    relative_path = rf"workspaces\{workspace_id}\rin-aster\1.0.0"
    install_root = rf"data\installed\{relative_path}"
    output_paths = (
        rf"data\registry\workspaces\{workspace_id}.json",
        *((rf"{install_root}\{member}") for member in (
            r"manifest.json",
            r"pack\compiled.json",
            r"release\hard-validation-report.json",
            r"release\promotion-record.json",
            r"release\review-attestation.json",
            r"release\soft-evaluation-report.json",
        )),
    )
    context = _context(
        tmp_path,
        case_id="safe-install-inactive",
        post_extra=[
            _entry(path, b"{}", 800 + index)
            for index, path in enumerate(output_paths)
        ],
        created=tuple(
            sorted(
                (rf"workspace\{path}" for path in output_paths),
                key=str.casefold,
            )
        ),
    )
    decision = command_policy.authorize_command_plan(
        _bound_plan(
            "kokoro",
            "pack",
            "install",
            r".\inputs\archive.karc",
            "--scope",
            "workspace",
            "--workspace",
            ".",
            "--json",
        ),
        context=context,
    )
    authorized = decision.operations[0]
    assert authorized.argv[authorized.argv.index("--workspace") + 1] == str(
        context.workspace_root
    )
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=authorized.argv,
        result={
            "ok": True,
            "dry_run": False,
            "plan": {
                "will_write": True,
                "idempotent": False,
                "scope": "workspace",
                "workspace_id": workspace_id,
                "registry_identity": "original/rin-aster/1.0.0",
                "relative_path": relative_path,
                "archive_sha256": "b" * 64,
                "visibility": "private",
            },
            "activates_character": False,
        },
    )
    operation = SimpleNamespace(
        command_index=0,
        operation_index=0,
        category=authorized.category,
        declared_output_paths=authorized.declared_output_paths,
        argv=authorized.argv,
    )

    view = adjudication._filesystem_view(
        case_id="safe-install-inactive",
        filesystem=context.filesystem,
        file_changes=SimpleNamespace(
            unique_final_paths=(),
            implicit_ancestor_paths=(),
        ),
        origin=SimpleNamespace(workspace_relative_root="workspace", rules=()),
        command_records=(record,),
        operations=(operation,),
    )

    assert (
        rf"workspace\{install_root}\pack\compiled.json"
        in view.semantic_created_paths
    )


def _research_publication_projection(
    tmp_path: Path,
    *,
    result_artifact_id: str,
    extra_path: str | None = None,
):
    import complete_suite_adjudication as adjudication

    artifact_id = "research/" + "c" * 64
    leaf = r"data\research\research" + "\\" + "c" * 64
    entries = (
        (r"data", "created", "directory"),
        (r"data\research", "created", "directory"),
        (r"data\research\research", "created", "directory"),
        (leaf, "created", "directory"),
        *((rf"{leaf}\{name}", "created", "file") for name in (
            "bundle.json",
            "request.json",
            "validation-report.json",
            "workspace.json",
        )),
        (
            r"data\research\research\." + "c" * 64 + ".publish.lock",
            "created",
            "file",
        ),
        *(
            ((extra_path, "created", "file"),)
            if extra_path is not None
            else ()
        ),
    )
    result_leaf = Path(*result_artifact_id.split("/"))
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=(
            "kokoro",
            "research",
            "bundle",
            "compile",
            "--workspace",
            r"inputs\research-workspace",
            "--json",
        ),
        result={
            "ok": True,
            "path": str(
                tmp_path
                / "case"
                / "workspace"
                / "data"
                / "research"
                / result_leaf
            ),
            "artifact_id": artifact_id,
        },
    )
    operation = SimpleNamespace(
        command_index=0,
        operation_index=0,
        category="kokoro_cli",
        declared_output_paths=(),
        argv=record.argv,
    )
    return (
        adjudication,
        artifact_id,
        leaf,
        entries,
        record,
        operation,
    )


def test_provenance_v1_projection_claims_exact_research_bundle_publication(
    tmp_path: Path,
) -> None:
    (
        adjudication,
        _artifact_id,
        leaf,
        entries,
        record,
        operation,
    ) = _research_publication_projection(
        tmp_path,
        result_artifact_id="research/" + "c" * 64,
    )

    view = adjudication._filesystem_view(
        case_id="named-character-research-routing",
        filesystem=_projection_filesystem(tmp_path, entries),
        file_changes=SimpleNamespace(
            unique_final_paths=(),
            implicit_ancestor_paths=(),
        ),
        origin=SimpleNamespace(workspace_relative_root="workspace", rules=()),
        command_records=(record,),
        operations=(operation,),
    )

    expected = {
        r"workspace\data",
        r"workspace\data\research",
        r"workspace\data\research\research",
        rf"workspace\{leaf}",
        *(rf"workspace\{leaf}\{name}" for name in (
            "bundle.json",
            "request.json",
            "validation-report.json",
            "workspace.json",
        )),
        r"workspace\data\research\research\."
        + "c" * 64
        + ".publish.lock",
    }
    assert expected == set(
        (*view.product_support_paths, *view.semantic_created_paths)
    )


@pytest.mark.parametrize(
    ("result_artifact_id", "extra_path"),
    (
        ("research/" + "d" * 64, None),
        (
            "research/" + "c" * 64,
            r"data\research\research"
            + "\\"
            + "c" * 64
            + r"\unexpected.json",
        ),
    ),
    ids=("substituted-result-path", "extra-published-file"),
)
def test_provenance_v1_projection_rejects_mutated_research_bundle_publication(
    tmp_path: Path,
    result_artifact_id: str,
    extra_path: str | None,
) -> None:
    (
        adjudication,
        _artifact_id,
        _leaf,
        entries,
        record,
        operation,
    ) = _research_publication_projection(
        tmp_path,
        result_artifact_id=result_artifact_id,
        extra_path=extra_path,
    )

    with pytest.raises(RuntimeError, match="FILE_CHANGE_PROJECTION_INVALID"):
        adjudication._filesystem_view(
            case_id="named-character-research-routing",
            filesystem=_projection_filesystem(tmp_path, entries),
            file_changes=SimpleNamespace(
                unique_final_paths=(),
                implicit_ancestor_paths=(),
            ),
            origin=SimpleNamespace(workspace_relative_root="workspace", rules=()),
            command_records=(record,),
            operations=(operation,),
        )


@pytest.mark.parametrize(
    ("scope", "workspace_id", "relative_path", "registry_identity"),
    (
        (
            "global",
            None,
            r"other\rin-aster\1.0.0",
            "original/rin-aster/1.0.0",
        ),
        (
            "global",
            "a" * 64,
            r"global\rin-aster\1.0.0",
            "original/rin-aster/1.0.0",
        ),
        (
            "workspace",
            "a" * 64,
            "workspaces\\" + "b" * 64 + r"\rin-aster\1.0.0",
            "original/rin-aster/1.0.0",
        ),
        (
            "workspace",
            "short-id",
            r"workspaces\short-id\rin-aster\1.0.0",
            "original/rin-aster/1.0.0",
        ),
        (
            "global",
            None,
            r"global\rin-aster\1.0.0",
            "original/other-character/1.0.0",
        ),
    ),
    ids=(
        "unknown-global-root",
        "global-workspace-id",
        "workspace-id-mismatch",
        "workspace-id-grammar",
        "registry-identity-path-mismatch",
    ),
)
def test_provenance_v1_projection_rejects_unbound_install_layout(
    tmp_path: Path,
    scope: str,
    workspace_id: str | None,
    relative_path: str,
    registry_identity: str,
) -> None:
    import complete_suite_adjudication as adjudication

    archive_sha256 = "b" * 64
    install_root = rf"data\installed\{relative_path}"
    registry = (
        r"data\registry\global.json"
        if scope == "global"
        else rf"data\registry\workspaces\{workspace_id}.json"
    )
    lock = (
        r"data\registry\.global.lock"
        if scope == "global"
        else rf"data\registry\workspaces\.{workspace_id}.lock"
    )
    entries = (
        (registry, "created", "file"),
        (lock, "created", "file"),
        *((rf"{install_root}\{member}", "created", "file") for member in (
            r"manifest.json",
            r"pack\compiled.json",
            r"release\hard-validation-report.json",
            r"release\promotion-record.json",
            r"release\review-attestation.json",
            r"release\soft-evaluation-report.json",
        )),
        (rf"data\archives\{archive_sha256}.karc", "created", "file"),
        (r"data\registry\journals", "created", "directory"),
    )
    argv = (
        "kokoro",
        "pack",
        "install",
        r"inputs\rin-aster.karc",
        "--scope",
        scope,
        "--json",
    )
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=argv,
        result={
            "ok": True,
            "plan": {
                "will_write": True,
                "scope": scope,
                "workspace_id": workspace_id,
                "registry_identity": registry_identity,
                "relative_path": relative_path,
                "archive_sha256": archive_sha256,
                "visibility": "private",
            },
        },
    )
    operation = SimpleNamespace(
        command_index=0,
        operation_index=0,
        category="kokoro_cli",
        declared_output_paths=(),
        argv=record.argv,
    )

    with pytest.raises(RuntimeError, match="FILE_CHANGE_PROJECTION_INVALID"):
        adjudication._filesystem_view(
            case_id="safe-install-inactive",
            filesystem=_projection_filesystem(tmp_path, entries),
            file_changes=SimpleNamespace(
                unique_final_paths=(),
                implicit_ancestor_paths=(),
            ),
            origin=SimpleNamespace(
                workspace_relative_root="workspace",
                rules=(),
            ),
            command_records=(record,),
            operations=(operation,),
        )


def test_provenance_v1_projection_allows_install_into_initialized_scope(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    archive_sha256 = "b" * 64
    relative_path = r"global\rin-aster\1.0.1"
    install_root = rf"data\installed\{relative_path}"
    entries = (
        (r"data\registry\global.json", "changed", "file"),
        *((rf"{install_root}\{member}", "created", "file") for member in (
            r"manifest.json",
            r"pack\compiled.json",
            r"release\hard-validation-report.json",
            r"release\promotion-record.json",
            r"release\review-attestation.json",
            r"release\soft-evaluation-report.json",
        )),
    )
    argv = (
        "kokoro",
        "pack",
        "install",
        r"inputs\rin-aster.karc",
        "--scope",
        "global",
        "--json",
    )
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=argv,
        result={
            "ok": True,
            "plan": {
                "will_write": True,
                "scope": "global",
                "workspace_id": None,
                "registry_identity": "original/rin-aster/1.0.1",
                "relative_path": relative_path,
                "archive_sha256": archive_sha256,
                "visibility": "private",
            },
        },
    )
    operation = SimpleNamespace(
        command_index=0,
        operation_index=0,
        category="kokoro_cli",
        declared_output_paths=(),
        argv=record.argv,
    )

    view = adjudication._filesystem_view(
        case_id="safe-install-inactive",
        filesystem=_projection_filesystem(tmp_path, entries),
        file_changes=SimpleNamespace(
            unique_final_paths=(),
            implicit_ancestor_paths=(),
        ),
        origin=SimpleNamespace(workspace_relative_root="workspace", rules=()),
        command_records=(record,),
        operations=(operation,),
    )

    assert r"workspace\data\registry\global.json" in view.product_support_paths


def test_provenance_v1_projection_allows_repeated_state_apply_ownership(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    argv = (
        "kokoro",
        "state",
        "apply",
        "--session",
        "persistence-demo",
        "--event",
        r"inputs\event.json",
        "--json",
    )
    records = tuple(
        _projection_record(
            command_index=index,
            operation_index=0,
            argv=argv,
            result={
                "ok": True,
                "state": {
                    "revision": 1,
                    "applied_event_ids": ["event-01"],
                },
            },
        )
        for index in range(2)
    )

    class FileChanges:
        unique_final_paths = ()
        implicit_ancestor_paths = ()

    class Origin:
        workspace_relative_root = "workspace"
        rules = ()

    class Operation:
        category = "kokoro_cli"
        declared_output_paths = ()
        argv = records[0].argv

        def __init__(self, command_index: int) -> None:
            self.command_index = command_index
            self.operation_index = 0

    view = adjudication._filesystem_view(
        case_id="consented-persistence-replay",
        filesystem=_projection_filesystem(
            tmp_path,
            (
                (
                    r"data\events",
                    "created",
                    "directory",
                ),
                (
                    r"data\events\persistence-demo",
                    "created",
                    "directory",
                ),
                (
                    r"data\events\persistence-demo\1-event-01.json",
                    "created",
                    "file",
                ),
                (
                    r"data\state\persistence-demo.json",
                    "changed",
                    "file",
                ),
                (
                    r"data\sessions\persistence-demo.json",
                    "changed",
                    "file",
                ),
            ),
        ),
        file_changes=FileChanges(),
        origin=Origin(),
        command_records=records,
        operations=(Operation(0), Operation(1)),
    )

    assert view.semantic_created_paths == (
        r"workspace\data\events\persistence-demo\1-event-01.json",
    )
    assert {
        r"workspace\data\state\persistence-demo.json",
        r"workspace\data\sessions\persistence-demo.json",
    } <= set(view.product_support_paths)


@pytest.mark.parametrize(
    "missing_path",
    (
        r"data\events\persistence-demo\1-event-01.json",
        r"data\state\persistence-demo.json",
        r"data\sessions\persistence-demo.json",
    ),
    ids=("missing-event", "missing-state", "missing-session"),
)
def test_provenance_v1_projection_requires_state_apply_artifacts(
    tmp_path: Path,
    missing_path: str,
) -> None:
    import complete_suite_adjudication as adjudication

    argv = (
        "kokoro",
        "state",
        "apply",
        "--session",
        "persistence-demo",
        "--event",
        r"inputs\event.json",
        "--json",
    )
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=argv,
        result={
            "ok": True,
            "state": {
                "revision": 1,
                "applied_event_ids": ["event-01"],
            },
        },
    )
    operation = SimpleNamespace(
        command_index=0,
        operation_index=0,
        category="kokoro_cli",
        declared_output_paths=(),
        argv=record.argv,
    )
    file_changes = SimpleNamespace(
        unique_final_paths=(),
        implicit_ancestor_paths=(),
    )
    origin = SimpleNamespace(workspace_relative_root="workspace", rules=())
    entries = tuple(
        entry
        for entry in (
            (
                r"data\events\persistence-demo\1-event-01.json",
                "created",
                "file",
            ),
            (
                r"data\state\persistence-demo.json",
                "changed",
                "file",
            ),
            (
                r"data\sessions\persistence-demo.json",
                "changed",
                "file",
            ),
        )
        if entry[0] != missing_path
    )

    with pytest.raises(RuntimeError, match="FILE_CHANGE_PROJECTION_INVALID"):
        adjudication._filesystem_view(
            case_id="consented-persistence-replay",
            filesystem=_projection_filesystem(tmp_path, entries),
            file_changes=file_changes,
            origin=origin,
            command_records=(record,),
            operations=(operation,),
        )


def test_provenance_v1_projection_allows_add_then_remove_memory_ownership(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    memory_reference_id = "memory-" + "a" * 32
    records = (
        _projection_record(
            command_index=0,
            operation_index=0,
            argv=(
                "kokoro",
                "memory",
                "add",
                "--character",
                "rin-aster",
                "--scope",
                "global",
                "--host-id",
                "host-memory-01",
                "--summary-file",
                r"inputs\approved-summary.json",
                "--json",
            ),
            result={
                "ok": True,
                "memory_reference": {
                    "memory_reference_id": memory_reference_id,
                    "scope": "global",
                    "workspace_id": None,
                    "namespace": "original",
                    "character_id": "rin-aster",
                },
            },
        ),
        _projection_record(
            command_index=1,
            operation_index=0,
            argv=(
                "kokoro",
                "memory",
                "remove",
                "--character",
                "rin-aster",
                "--scope",
                "global",
                "--host-id",
                "host-memory-01",
                "--json",
            ),
            result={
                "ok": True,
                "dry_run": False,
                "result": {
                    "removed": True,
                    "memory_reference_id": memory_reference_id,
                },
            },
        ),
    )

    class FileChanges:
        unique_final_paths = ()
        implicit_ancestor_paths = ()

    class Origin:
        workspace_relative_root = "workspace"
        rules = ()

    class Operation:
        category = "kokoro_cli"
        declared_output_paths = ()

        def __init__(self, command_index: int) -> None:
            self.command_index = command_index
            self.operation_index = 0
            self.argv = records[command_index].argv

    view = adjudication._filesystem_view(
        case_id="memory-reference-ownership",
        filesystem=_projection_filesystem(
            tmp_path,
            (
                (
                    r"data\memory-references",
                    "created",
                    "directory",
                ),
                (
                    r"data\memory-references\global",
                    "created",
                    "directory",
                ),
                (
                    r"data\memory-references\global\original",
                    "created",
                    "directory",
                ),
                (
                    r"data\memory-references\global\original\rin-aster",
                    "created",
                    "directory",
                ),
                (
                    r"data\persistence-locks",
                    "created",
                    "directory",
                ),
                (
                    r"data\persistence-locks\global",
                    "created",
                    "directory",
                ),
                (
                    r"data\persistence-locks\global\original.rin-aster.lock",
                    "created",
                    "file",
                ),
            ),
        ),
        file_changes=FileChanges(),
        origin=Origin(),
        command_records=records,
        operations=(Operation(0), Operation(1)),
    )

    assert view.semantic_created_paths == ()
    assert {
        r"workspace\data\memory-references",
        r"workspace\data\memory-references\global",
        r"workspace\data\memory-references\global\original",
        r"workspace\data\memory-references\global\original\rin-aster",
        r"workspace\data\persistence-locks",
        r"workspace\data\persistence-locks\global",
        r"workspace\data\persistence-locks\global\original.rin-aster.lock",
    } == set(view.product_support_paths)


def test_provenance_v1_projection_rejects_legacy_memory_mutation_journal(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    argv = (
        "kokoro",
        "memory",
        "add",
        "--character",
        "rin-aster",
        "--scope",
        "global",
        "--host-id",
        "host-memory-01",
        "--summary-file",
        r"inputs\approved-summary.json",
        "--json",
    )
    memory_reference_id = "memory-" + "a" * 32
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=argv,
        result={
            "ok": True,
            "memory_reference": {
                "memory_reference_id": memory_reference_id,
                "scope": "global",
                "workspace_id": None,
                "namespace": "original",
                "character_id": "rin-aster",
            },
        },
    )
    operation = SimpleNamespace(
        command_index=0,
        operation_index=0,
        category="kokoro_cli",
        declared_output_paths=(),
        argv=record.argv,
    )
    file_changes = SimpleNamespace(
        unique_final_paths=(),
        implicit_ancestor_paths=(),
    )
    origin = SimpleNamespace(workspace_relative_root="workspace", rules=())

    with pytest.raises(RuntimeError, match="FILE_CHANGE_PROJECTION_INVALID"):
        adjudication._filesystem_view(
            case_id="memory-reference-ownership",
            filesystem=_projection_filesystem(
                tmp_path,
                (
                    (
                        r"data\persistence\rin-aster\memory-journal.jsonl",
                        "created",
                        "file",
                    ),
                ),
            ),
            file_changes=file_changes,
            origin=origin,
            command_records=(record,),
            operations=(operation,),
        )


def test_provenance_v1_projection_rejects_removed_product_lock(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    argv = (
        "kokoro",
        "config",
        "default",
        "set",
        "rin-aster@1.0.0",
        "--scope",
        "global",
        "--json",
    )
    record = _projection_record(
        command_index=0,
        operation_index=0,
        argv=argv,
        result={"ok": True, "default": {"scope": "global"}},
    )

    class FileChanges:
        unique_final_paths = ()
        implicit_ancestor_paths = ()

    class Origin:
        workspace_relative_root = "workspace"
        rules = ()

    class Operation:
        command_index = 0
        operation_index = 0
        category = "kokoro_cli"
        declared_output_paths = ()
        argv = record.argv

    with pytest.raises(RuntimeError, match="FILE_CHANGE_PROJECTION_INVALID"):
        adjudication._filesystem_view(
            case_id="global-default-no-activation",
            filesystem=_projection_filesystem(
                tmp_path,
                (
                    (r"data\config\global.json", "created", "file"),
                    (r"data\config\.global.lock", "removed", "file"),
                ),
            ),
            file_changes=FileChanges(),
            origin=Origin(),
            command_records=(record,),
            operations=(Operation(),),
        )


def test_provenance_v1_projection_rejects_unclassified_full_delta_path() -> None:
    import complete_suite_adjudication as adjudication
    import run_complete_suite_campaign as runner

    result_bytes = runner.canonical_bytes(
        {"ok": True, "path": r"outputs\draft.json"}
    ) + b"\n"
    digest = sha256(result_bytes).hexdigest()
    record = adjudication.AdjudicationCommandRecord(
        provenance_version=adjudication.COMMAND_PLAN_PROVENANCE_VERSION,
        command_index=0,
        event_id="draft-compile",
        started_event_ordinal=1,
        completed_event_ordinal=2,
        plan_sha256="a" * 64,
        operation_index=0,
        argv=(
            "kokoro",
            "character",
            "draft",
            "compile",
            "--request",
            r"inputs\request.json",
            "--pack",
            r"inputs\source-pack",
            "--json",
        ),
        exit_code=0,
        outcome="success",
        result_bytes=result_bytes,
        raw_result_sha256=digest,
        retained_result_sha256=digest,
    )

    class Evidence:
        created_paths = (
            r"workspace\outputs\draft.json",
            r"workspace\unclassified\copied.bin",
        )
        changed_paths = ()
        removed_paths = ()

    class FileChanges:
        unique_final_paths = ()
        implicit_ancestor_paths = ()

    class Origin:
        workspace_relative_root = "workspace"

    class Operation:
        command_index = 0
        operation_index = 0
        argv = record.argv
        category = "kokoro_cli"
        declared_output_paths = ()

    with pytest.raises(RuntimeError, match="FILE_CHANGE_PROJECTION_INVALID"):
        adjudication._filesystem_view(
            case_id="original-authoring-route",
            filesystem=Evidence(),
            file_changes=FileChanges(),
            origin=Origin(),
            command_records=(record,),
            operations=(Operation(),),
        )


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
    session_path = f"data/sessions/{session_id}.json"
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
            "data/sessions/refusal-demo.json": (
                b'{"session_id":"refusal-demo","active":true}\n'
            ),
        },
        create_result_artifact=False,
    )

    result = adjudicate_run(case, case_root, retained_run, ledger)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["assertions"])


def _relationship_state(
    *,
    revision: int,
    trust: float,
    applied_event_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "state/persistence-demo",
        "created_by": {"component": "kokoroarc", "version": "1.0.0"},
        "revision": revision,
        "turn_index": revision,
        "dimensions": {
            "familiarity": 0.0,
            "trust": trust,
            "collaboration": 0.0,
            "tension": 0.0,
        },
        "stage": "unknown",
        "applied_event_ids": applied_event_ids,
        "recent_novelty": ({"event-01": 1} if applied_event_ids else {}),
    }


def _session_manifest(*, state_revision: int) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "session/persistence-demo",
        "created_by": {"component": "kokoroarc", "version": "1.0.0"},
        "session_id": "persistence-demo",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "compiled_pack_hash": "a" * 64,
        "lifecycle_generation": "b" * 32,
        "scope": "session",
        "state_revision": state_revision,
        "active": True,
    }


def _interaction_event(*, event_id: str = "event-01") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": f"event/{event_id}",
        "created_by": {"component": "kokoroarc", "version": "1.0.0"},
        "event_id": event_id,
        "turn_id": "turn-01",
        "origin": "verified_task_outcome",
        "novelty_key": "event-01",
        "expected_state_revision": 0,
        "evaluator_version": "1.0.0",
        "evidence": {"kind": "test_result", "reference": "suite/event-01"},
        "confidence": 1.0,
        "effects": {"trust": 1.0},
    }


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
    event = _interaction_event()
    state = _relationship_state(
        revision=1,
        trust=1.0,
        applied_event_ids=["event-01"],
    )
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

    assert result["passed"] is True, [
        item for item in result["assertions"] if not item["passed"]
    ]
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

    changed_state = _relationship_state(
        revision=2,
        trust=2.0,
        applied_event_ids=["event-01"],
    )
    changed_event = _interaction_event(event_id="event-02")
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
    memory_reference_id = "memory-" + "c" * 32
    approved_summary = "Prefers concise explanations."
    reference = {
        "schema_version": "1.0",
        "artifact_id": f"memory-references/{memory_reference_id}",
        "created_by": {"component": "kokoroarc", "version": "1.0.0"},
        "memory_reference_id": memory_reference_id,
        "source_kind": "host_approved_reference",
        "host_memory_id": host_id,
        "scope": "global",
        "workspace_id": None,
        "installation_id": "installation-rin-aster-01",
        "namespace": "original",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "archive_sha256": "a" * 64,
        "compiled_sha256": "b" * 64,
        "consent_id": "consent-memory-01",
        "consent_revision": 4,
        "permission": "memory_references",
        "summary": approved_summary,
        "localized_summaries": {"en-US": approved_summary},
        "content_hash": sha256(approved_summary.encode("utf-8")).hexdigest(),
        "embedded_content": False,
        "canonical_fact_authority": False,
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
                        "memory_reference_id": memory_reference_id,
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
                        "memory_reference_id": memory_reference_id,
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
                {"summary": approved_summary}
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

    assert result["passed"] is True, [
        item for item in result["assertions"] if not item["passed"]
    ]
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
