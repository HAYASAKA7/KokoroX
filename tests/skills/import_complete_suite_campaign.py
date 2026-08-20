from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence


SKILLS_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SKILLS_ROOT.parents[1]
sys.path.insert(0, str(SKILLS_ROOT))

import complete_suite_preparation as preparation  # noqa: E402
from complete_suite_sanitization import sanitize_artifact  # noqa: E402
import run_complete_suite_campaign as runner  # noqa: E402


MAX_RETAINED_TEXT_BYTES = 64 * 1024 * 1024
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_WINDOWS_RESERVED_SEGMENTS = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".yaml", ".yml"}
_LEDGER_FIELDS = {
    "case_id",
    "derived_files",
    "evaluable",
    "files",
    "ordinal",
    "retained_binding",
    "schema_version",
    "source_binding",
    "source_status",
    "variant",
}
_RAW_RUN_FILES = (
    ("prompt.md", "prompt.md", False, False),
    (
        "complete-suite-output.schema.json",
        "complete-suite-output.schema.json",
        False,
        False,
    ),
    ("pre-run-state.json", "pre-run-state.json", False, False),
    ("launch-started.json", "launch-started.json", False, False),
    ("command.json", "command.json", False, False),
    ("launch-private.json", "launch-private.json", True, False),
    ("session.jsonl", "session.jsonl", True, False),
    ("stderr.txt", "stderr.txt", True, False),
    ("final.md", "final.md", True, True),
    (
        "agent-final-events.jsonl",
        "source-agent-final-events.jsonl",
        True,
        False,
    ),
    (
        "agent-command-events.jsonl",
        "source-agent-command-events.jsonl",
        True,
        False,
    ),
    (
        "agent-final-session.json",
        "source-agent-final-session.json",
        False,
        False,
    ),
    ("post-run-state.json", "post-run-state.json", False, False),
    ("run-status.json", "run-status.json", False, False),
)
_DERIVED_FILE_NAMES = (
    "agent-final-events.jsonl",
    "agent-command-events.jsonl",
    "agent-final-session.json",
)


def _safe_relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError("retained path is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_SEGMENTS
            or _SAFE_SEGMENT.fullmatch(part) is None
            for part in path.parts
        )
    ):
        raise RuntimeError("retained path is invalid")
    return path


def _require_plain_ancestry(root: Path, target: Path) -> None:
    try:
        preparation._require_plain_directory(root, label="artifact root")
        relative = target.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RuntimeError("artifact path is outside its root") from exc
    current = root
    for part in relative.parts[:-1]:
        current /= part
        try:
            preparation._require_plain_directory(current, label="artifact ancestor")
        except (OSError, ValueError) as exc:
            raise RuntimeError("artifact ancestry is unsafe") from exc


def _raw_relative_path(raw_root: Path, source: Path) -> str:
    try:
        root = raw_root.resolve(strict=True)
        target = source.resolve(strict=True)
        relative = target.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RuntimeError("raw artifact is outside the approved root") from exc
    _require_plain_ancestry(root, target)
    normalized = relative.as_posix()
    _safe_relative_path(normalized)
    if source.is_symlink() or target != source.absolute():
        raise RuntimeError("raw artifact is unsafe")
    return normalized


def _read_text_artifact(path: Path) -> bytes:
    try:
        return preparation._read_plain_bytes(
            path,
            max_bytes=MAX_RETAINED_TEXT_BYTES,
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("raw artifact is unavailable or unsafe") from exc


def _sanitized_entry(
    raw: bytes,
    *,
    raw_path: str,
    retained_path: str,
    allow_redaction: bool,
) -> tuple[bytes, dict[str, Any]]:
    try:
        retained, summary = sanitize_artifact(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("artifact sanitization failed") from exc
    redaction_count = summary.get("redaction_count")
    redaction_classes = summary.get("redaction_classes")
    if (
        not isinstance(redaction_count, int)
        or isinstance(redaction_count, bool)
        or redaction_count < 0
        or not isinstance(redaction_classes, list)
        or not all(isinstance(item, str) and item for item in redaction_classes)
    ):
        raise RuntimeError("artifact sanitization summary is invalid")
    if redaction_count and not allow_redaction:
        raise RuntimeError("unexpected redaction in immutable artifact")
    return retained, {
        "schema_version": "1.0",
        "retention": "sanitized_text_copy",
        "raw_path": raw_path,
        "retained_path": retained_path,
        "raw_size": len(raw),
        "retained_size": len(retained),
        "raw_sha256": sha256(raw).hexdigest(),
        "retained_sha256": sha256(retained).hexdigest(),
        "redaction_allowed": allow_redaction,
        "redaction_count": redaction_count,
        "redaction_classes": redaction_classes,
    }


def _create_plain_parents(root: Path, relative: PurePosixPath) -> Path:
    try:
        preparation._require_plain_directory(root, label="retained root")
    except (OSError, ValueError) as exc:
        raise RuntimeError("retained root is unavailable or unsafe") from exc
    current = root
    for part in relative.parts[:-1]:
        current /= part
        if current.exists() or current.is_symlink():
            try:
                preparation._require_plain_directory(
                    current,
                    label="retained artifact ancestor",
                )
            except (OSError, ValueError) as exc:
                raise RuntimeError("retained artifact ancestry is unsafe") from exc
        else:
            current.mkdir()
            preparation._require_plain_directory(
                current,
                label="retained artifact ancestor",
            )
    return root.joinpath(*relative.parts)


def retain_text_artifact(
    source: Path,
    *,
    raw_root: Path,
    retained_root: Path,
    retained_path: str,
    allow_redaction: bool,
) -> dict[str, Any]:
    relative = _safe_relative_path(retained_path)
    raw_path = _raw_relative_path(raw_root, source)
    raw = _read_text_artifact(source)
    retained, entry = _sanitized_entry(
        raw,
        raw_path=raw_path,
        retained_path=relative.as_posix(),
        allow_redaction=allow_redaction,
    )
    destination = _create_plain_parents(retained_root, relative)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("retained artifact already exists")
    destination.write_bytes(retained)
    if _read_text_artifact(destination) != retained:
        raise RuntimeError("retained artifact changed while it was written")
    return entry


def retain_digest_artifact(
    source: Path,
    *,
    raw_root: Path,
) -> dict[str, Any]:
    raw_path = _raw_relative_path(raw_root, source)
    raw = _read_text_artifact(source)
    return {
        "schema_version": "1.0",
        "retention": "hash_only",
        "raw_path": raw_path,
        "retained_path": None,
        "raw_size": len(raw),
        "raw_sha256": sha256(raw).hexdigest(),
        "reason": "binary_generated_artifact",
    }


def _validate_ledger_entry(entry: object) -> dict[str, Any]:
    if isinstance(entry, dict) and entry.get("retention") == "hash_only":
        fields = {
            "schema_version",
            "retention",
            "raw_path",
            "retained_path",
            "raw_size",
            "raw_sha256",
            "reason",
        }
        if (
            set(entry) != fields
            or entry.get("schema_version") != "1.0"
            or entry.get("retained_path") is not None
            or entry.get("reason") != "binary_generated_artifact"
            or not isinstance(entry.get("raw_size"), int)
            or isinstance(entry.get("raw_size"), bool)
            or entry["raw_size"] < 0
            or not isinstance(entry.get("raw_sha256"), str)
            or _SHA256.fullmatch(entry["raw_sha256"]) is None
        ):
            raise RuntimeError("artifact ledger entry is invalid")
        _safe_relative_path(entry.get("raw_path"))
        return dict(entry)
    fields = {
        "schema_version",
        "retention",
        "raw_path",
        "retained_path",
        "raw_size",
        "retained_size",
        "raw_sha256",
        "retained_sha256",
        "redaction_allowed",
        "redaction_count",
        "redaction_classes",
    }
    if not isinstance(entry, dict) or set(entry) != fields:
        raise RuntimeError("artifact ledger entry is invalid")
    if (
        entry.get("schema_version") != "1.0"
        or entry.get("retention") != "sanitized_text_copy"
        or not isinstance(entry.get("redaction_allowed"), bool)
    ):
        raise RuntimeError("artifact ledger entry is invalid")
    for key in ("raw_size", "retained_size", "redaction_count"):
        value = entry.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuntimeError("artifact ledger entry is invalid")
    for key in ("raw_sha256", "retained_sha256"):
        value = entry.get(key)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise RuntimeError("artifact ledger entry is invalid")
    classes = entry.get("redaction_classes")
    if (
        not isinstance(classes, list)
        or classes != sorted(set(classes))
        or not all(isinstance(item, str) and item for item in classes)
    ):
        raise RuntimeError("artifact ledger entry is invalid")
    _safe_relative_path(entry.get("raw_path"))
    _safe_relative_path(entry.get("retained_path"))
    return dict(entry)


def replay_artifact_ledger(
    raw_root: Path,
    retained_root: Path,
    entries: Sequence[Mapping[str, Any]],
) -> None:
    seen_raw: set[str] = set()
    seen_retained: set[str] = set()
    for untrusted in entries:
        entry = _validate_ledger_entry(untrusted)
        raw_path = entry["raw_path"]
        retained_path = entry["retained_path"]
        if raw_path in seen_raw or (
            retained_path is not None and retained_path in seen_retained
        ):
            raise RuntimeError("artifact ledger contains a duplicate path")
        seen_raw.add(raw_path)
        if retained_path is not None:
            seen_retained.add(retained_path)
        source = raw_root.joinpath(*PurePosixPath(raw_path).parts)
        if entry["retention"] == "hash_only":
            observed_raw_path = _raw_relative_path(raw_root, source)
            raw = _read_text_artifact(source)
            expected = {
                "schema_version": "1.0",
                "retention": "hash_only",
                "raw_path": observed_raw_path,
                "retained_path": None,
                "raw_size": len(raw),
                "raw_sha256": sha256(raw).hexdigest(),
                "reason": "binary_generated_artifact",
            }
            if expected != entry:
                raise RuntimeError("raw artifact or ledger mismatch")
            continue
        assert isinstance(retained_path, str)
        destination = retained_root.joinpath(*PurePosixPath(retained_path).parts)
        observed_raw_path = _raw_relative_path(raw_root, source)
        raw = _read_text_artifact(source)
        retained, expected = _sanitized_entry(
            raw,
            raw_path=observed_raw_path,
            retained_path=retained_path,
            allow_redaction=entry["redaction_allowed"],
        )
        if expected != entry:
            raise RuntimeError("raw artifact or ledger mismatch")
        try:
            _require_plain_ancestry(retained_root.resolve(strict=True), destination)
            observed_retained = _read_text_artifact(destination)
        except RuntimeError as exc:
            raise RuntimeError("retained artifact mismatch") from exc
        if observed_retained != retained:
            raise RuntimeError("retained artifact mismatch")


def _load_json_object(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value

    try:
        value = json.loads(
            _read_text_artifact(path),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("run evidence JSON is invalid") from exc
    if not isinstance(value, dict):
        raise RuntimeError("run evidence JSON is invalid")
    return value


def _matches_artifact_record(path: Path, value: object) -> bool:
    if value is None:
        return not path.exists() and not path.is_symlink()
    if not isinstance(value, dict) or set(value) != {"size", "sha256"}:
        return False
    try:
        payload = _read_text_artifact(path)
    except RuntimeError:
        return False
    return value == {
        "size": len(payload),
        "sha256": sha256(payload).hexdigest(),
    }


def _validate_source_status(
    case_root: Path,
    item: runner.RunSpec,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = case_root / "raw"
    status = _load_json_object(raw / "run-status.json")
    if (
        status.get("schema_version") != "1.0"
        or status.get("ordinal") != item.ordinal
        or status.get("variant") != item.variant
        or status.get("case_id") != item.case_id
    ):
        raise RuntimeError("run status identity mismatch")
    for field, name in (
        ("session", "session.jsonl"),
        ("stderr", "stderr.txt"),
        ("final", "final.md"),
    ):
        if not _matches_artifact_record(raw / name, status.get(field)):
            raise RuntimeError("run status artifact mismatch")
    for field, name in (
        ("command_sha256", "command.json"),
        ("private_launch_sha256", "launch-private.json"),
        ("final_binding_sha256", "agent-final-session.json"),
        ("post_run_state_sha256", "post-run-state.json"),
    ):
        try:
            observed = sha256(_read_text_artifact(raw / name)).hexdigest()
        except RuntimeError as exc:
            raise RuntimeError("run status artifact mismatch") from exc
        if status.get(field) != observed:
            raise RuntimeError("run status artifact mismatch")
    source_binding = _load_json_object(raw / "agent-final-session.json")
    if status.get("thread_id") != source_binding.get("thread_id"):
        raise RuntimeError("run status final binding mismatch")
    if status.get("lifecycle_passed") is True and (
        status.get("exit_code") != 0
        or status.get("timed_out") is not False
        or status.get("process_completed") is not True
        or status.get("failure_codes") != []
        or source_binding.get("passed") is not True
    ):
        raise RuntimeError("passing run status is contradictory")
    return status, source_binding


def _workspace_artifact_entries(
    case_root: Path,
    retained_run: Path,
    post_run: Mapping[str, Any],
) -> list[dict[str, Any]]:
    workspace = case_root / "workspace"
    paths = _workspace_artifact_paths(post_run)
    entries: list[dict[str, Any]] = []
    for relative in paths:
        source = workspace.joinpath(*relative.parts)
        if source.suffix.casefold() in _TEXT_SUFFIXES:
            entries.append(
                retain_text_artifact(
                    source,
                    raw_root=case_root,
                    retained_root=retained_run,
                    retained_path=(
                        PurePosixPath("workspace-artifacts") / relative
                    ).as_posix(),
                    allow_redaction=True,
                )
            )
        else:
            entries.append(retain_digest_artifact(source, raw_root=case_root))
    return entries


def _workspace_artifact_paths(
    post_run: Mapping[str, Any],
) -> list[PurePosixPath]:
    values = [
        *(post_run.get("created_paths") or []),
        *(post_run.get("changed_paths") or []),
    ]
    if (
        len(values) > 512
        or not all(isinstance(value, str) for value in values)
        or len(set(values)) != len(values)
    ):
        raise RuntimeError("generated artifact path set is invalid")
    return [_safe_relative_path(value) for value in sorted(values)]


def _expected_ledger_paths(
    case_root: Path,
    post_run: Mapping[str, Any],
) -> tuple[set[str], set[str]]:
    raw_paths: set[str] = set()
    retained_paths: set[str] = set()
    raw_root = case_root / "raw"
    for raw_name, retained_name, _allow_redaction, optional in _RAW_RUN_FILES:
        source = raw_root / raw_name
        if optional and not source.exists() and not source.is_symlink():
            continue
        raw_paths.add((PurePosixPath("raw") / raw_name).as_posix())
        retained_paths.add(retained_name)
    for raw_path, retained_path in (
        ("prepared-layout.json", "prepared-layout.json"),
        ("workspace/case.json", "workspace/case.json"),
        ("workspace/inputs/setup.json", "workspace/inputs/setup.json"),
    ):
        raw_paths.add(raw_path)
        retained_paths.add(retained_path)
    for relative in _workspace_artifact_paths(post_run):
        raw_paths.add((PurePosixPath("workspace") / relative).as_posix())
        if relative.suffix.casefold() in _TEXT_SUFFIXES:
            retained_paths.add(
                (PurePosixPath("workspace-artifacts") / relative).as_posix()
            )
    return raw_paths, retained_paths


def _ledger_paths(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[set[str], set[str]]:
    raw_paths: set[str] = set()
    retained_paths: set[str] = set()
    for untrusted in entries:
        entry = _validate_ledger_entry(untrusted)
        raw_path = entry["raw_path"]
        retained_path = entry["retained_path"]
        if raw_path in raw_paths or (
            retained_path is not None and retained_path in retained_paths
        ):
            raise RuntimeError("artifact ledger contains a duplicate path")
        raw_paths.add(raw_path)
        if retained_path is not None:
            retained_paths.add(retained_path)
    return raw_paths, retained_paths


def _retained_file_paths(retained_run: Path) -> set[str]:
    try:
        inventory = preparation.inventory_tree(retained_run)
    except (OSError, ValueError) as exc:
        raise RuntimeError("retained artifact inventory is unsafe") from exc
    files = inventory.get("files")
    if not isinstance(files, list) or not all(
        isinstance(entry, dict) and isinstance(entry.get("path"), str)
        for entry in files
    ):
        raise RuntimeError("retained artifact inventory is invalid")
    return {entry["path"] for entry in files}


def _raw_run_file_paths(raw_root: Path) -> set[str]:
    try:
        inventory = preparation.inventory_tree(raw_root)
    except (OSError, ValueError) as exc:
        raise RuntimeError("raw artifact inventory is unsafe") from exc
    files = inventory.get("files")
    if not isinstance(files, list) or not all(
        isinstance(entry, dict) and isinstance(entry.get("path"), str)
        for entry in files
    ):
        raise RuntimeError("raw artifact inventory is invalid")
    return {
        (PurePosixPath("raw") / entry["path"]).as_posix()
        for entry in files
    }


def _derived_records(root: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for name in _DERIVED_FILE_NAMES:
        payload = _read_text_artifact(root / name)
        records[name] = {
            "size": len(payload),
            "sha256": sha256(payload).hexdigest(),
        }
    return records


def retain_run_evidence(
    case_root: Path,
    retained_run: Path,
    item: runner.RunSpec,
) -> dict[str, Any]:
    try:
        preparation._require_plain_directory(case_root, label="case root")
        preparation._require_plain_directory(retained_run, label="retained run root")
    except (OSError, ValueError) as exc:
        raise RuntimeError("run evidence root is unavailable or unsafe") from exc
    if tuple(retained_run.iterdir()):
        raise RuntimeError("retained run root is not empty")
    status, source_binding = _validate_source_status(case_root, item)
    raw = case_root / "raw"
    entries: list[dict[str, Any]] = []
    for raw_name, retained_name, allow_redaction, optional in _RAW_RUN_FILES:
        source = raw / raw_name
        if optional and not source.exists() and not source.is_symlink():
            continue
        entries.append(
            retain_text_artifact(
                source,
                raw_root=case_root,
                retained_root=retained_run,
                retained_path=retained_name,
                allow_redaction=allow_redaction,
            )
        )
    for source, retained_name in (
        (case_root / "prepared-layout.json", "prepared-layout.json"),
        (case_root / "workspace" / "case.json", "workspace/case.json"),
        (
            case_root / "workspace" / "inputs" / "setup.json",
            "workspace/inputs/setup.json",
        ),
    ):
        entries.append(
            retain_text_artifact(
                source,
                raw_root=case_root,
                retained_root=retained_run,
                retained_path=retained_name,
                allow_redaction=False,
            )
        )
    post_run = _load_json_object(raw / "post-run-state.json")
    entries.extend(_workspace_artifact_entries(case_root, retained_run, post_run))
    final_path = retained_run / "final.md"
    if final_path.is_file():
        retained_binding = runner.bind_session_evidence(
            retained_run,
            expected_case_id=item.case_id,
            output_schema_file=(
                retained_run / "complete-suite-output.schema.json"
            ),
        )
    else:
        retained_binding = runner._failed_session_binding(
            retained_run,
            "NO_FINAL_OUTPUT",
        )
    if status.get("lifecycle_passed") is True and (
        retained_binding.get("passed") is not True
        or retained_binding.get("thread_id") != status.get("thread_id")
    ):
        raise RuntimeError("retained final binding mismatch")
    return {
        "schema_version": "1.0",
        "ordinal": item.ordinal,
        "variant": item.variant,
        "case_id": item.case_id,
        "source_status": status,
        "source_binding": source_binding,
        "evaluable": status.get("lifecycle_passed") is True,
        "retained_binding": retained_binding,
        "derived_files": _derived_records(retained_run),
        "files": entries,
    }


def replay_run_evidence(
    case_root: Path,
    retained_run: Path,
    ledger: Mapping[str, Any],
) -> None:
    if (
        not isinstance(ledger, Mapping)
        or set(ledger) != _LEDGER_FIELDS
        or ledger.get("schema_version") != "1.0"
        or not isinstance(ledger.get("ordinal"), int)
        or isinstance(ledger.get("ordinal"), bool)
        or ledger["ordinal"] < 1
        or ledger.get("variant") not in {"baseline", "suite-enabled"}
        or not isinstance(ledger.get("case_id"), str)
        or not ledger["case_id"]
        or not isinstance(ledger.get("evaluable"), bool)
    ):
        raise RuntimeError("run evidence ledger is invalid")
    try:
        item = runner.RunSpec(
            ordinal=int(ledger["ordinal"]),
            variant=str(ledger["variant"]),
            case_id=str(ledger["case_id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("run evidence ledger is invalid") from exc
    raw_root = case_root / "raw"
    raw_status = _load_json_object(raw_root / "run-status.json")
    if raw_status != ledger.get("source_status"):
        raise RuntimeError("run status mismatch")
    if ledger["evaluable"] is not (raw_status.get("lifecycle_passed") is True):
        raise RuntimeError("run evidence ledger is invalid")
    raw_binding = _load_json_object(raw_root / "agent-final-session.json")
    if raw_binding != ledger.get("source_binding"):
        raise RuntimeError("source final binding mismatch")
    status, source_binding = _validate_source_status(case_root, item)
    assert status == raw_status
    assert source_binding == raw_binding
    files = ledger.get("files")
    if not isinstance(files, list):
        raise RuntimeError("run evidence ledger is invalid")
    post_run = _load_json_object(raw_root / "post-run-state.json")
    expected_raw, expected_retained = _expected_ledger_paths(case_root, post_run)
    observed_raw, observed_retained = _ledger_paths(files)
    if (
        observed_raw != expected_raw
        or observed_retained != expected_retained
        or _raw_run_file_paths(raw_root)
        != {path for path in expected_raw if path.startswith("raw/")}
        or _retained_file_paths(retained_run)
        != expected_retained | set(_DERIVED_FILE_NAMES)
    ):
        raise RuntimeError("run evidence ledger is incomplete")
    replay_artifact_ledger(case_root, retained_run, files)
    observed_derived = _derived_records(retained_run)
    if observed_derived != ledger.get("derived_files"):
        raise RuntimeError("retained derived evidence mismatch")
    with tempfile.TemporaryDirectory(
        prefix=".complete-suite-rebind-",
        dir=retained_run.parent,
    ) as temporary:
        scratch = Path(temporary)
        for name in (
            "session.jsonl",
            "complete-suite-output.schema.json",
        ):
            (scratch / name).write_bytes(_read_text_artifact(retained_run / name))
        retained_final = retained_run / "final.md"
        if retained_final.exists() or retained_final.is_symlink():
            (scratch / "final.md").write_bytes(_read_text_artifact(retained_final))
            expected_binding = runner.bind_session_evidence(
                scratch,
                expected_case_id=item.case_id,
                output_schema_file=scratch / "complete-suite-output.schema.json",
            )
        else:
            expected_binding = runner._failed_session_binding(
                scratch,
                "NO_FINAL_OUTPUT",
            )
        if (
            expected_binding != ledger.get("retained_binding")
            or _derived_records(scratch) != observed_derived
        ):
            raise RuntimeError("retained final binding mismatch")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(runner.canonical_bytes(value) + b"\n")


def _preparation_failure(ledger: Mapping[str, Any]) -> dict[str, Any] | None:
    failure = ledger.get("failure")
    if failure is None:
        return None
    if (
        not isinstance(failure, dict)
        or set(failure)
        != {
            "schema_version",
            "phase",
            "code",
            "error_type",
            "retry_allowed",
        }
        or failure.get("schema_version") != "1.0"
        or failure.get("phase") != "preparation"
        or failure.get("code") != "CAMPAIGN_PREPARATION_FAILED"
        or not isinstance(failure.get("error_type"), str)
        or re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]{0,127}",
            failure["error_type"],
        )
        is None
        or failure.get("retry_allowed") is not False
    ):
        raise RuntimeError("sealed campaign preparation failure is invalid")
    return dict(failure)


def _campaign_artifact_names(
    ledger: Mapping[str, Any],
) -> tuple[str, ...]:
    if _preparation_failure(ledger) is not None:
        return (
            "approval.json",
            "campaign-failure.json",
            "campaign-ledger.json",
            "campaign-completion.json",
            "COMPLETED",
        )
    return (
        "approval.json",
        "prepared-campaign.json",
        "campaign-ledger.json",
        "campaign-completion.json",
        "COMPLETED",
    )


def _validate_preparation_snapshot(
    raw_root: Path,
    ledger: Mapping[str, Any],
) -> None:
    snapshot = ledger.get("failure_snapshot")
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "file_count",
        "total_bytes",
        "tree_sha256",
        "files",
    }:
        raise RuntimeError("sealed preparation snapshot is invalid")
    files = snapshot.get("files")
    if (
        not isinstance(files, list)
        or not all(
            isinstance(entry, dict)
            and set(entry) == {"path", "size", "sha256"}
            and isinstance(entry.get("path"), str)
            and isinstance(entry.get("size"), int)
            and not isinstance(entry.get("size"), bool)
            and entry["size"] >= 0
            and isinstance(entry.get("sha256"), str)
            and _SHA256.fullmatch(entry["sha256"]) is not None
            for entry in files
        )
    ):
        raise RuntimeError("sealed preparation snapshot is invalid")
    paths = [entry["path"] for entry in files]
    sealing_paths = {
        "campaign-failure.json",
        "campaign-ledger.json",
        "campaign-completion.json",
        "COMPLETED",
    }
    if (
        paths != sorted(paths)
        or len(set(paths)) != len(paths)
        or "approval.json" not in paths
        or set(paths) & sealing_paths
    ):
        raise RuntimeError("sealed preparation snapshot is invalid")
    expected_snapshot = {
        "file_count": len(files),
        "total_bytes": sum(entry["size"] for entry in files),
        "tree_sha256": sha256(preparation.canonical_bytes(files)).hexdigest(),
        "files": files,
    }
    if snapshot != expected_snapshot:
        raise RuntimeError("sealed preparation snapshot is invalid")
    observed = preparation.inventory_tree(raw_root)
    observed_files = observed.get("files")
    if not isinstance(observed_files, list):
        raise RuntimeError("sealed preparation snapshot changed")
    observed_by_path = {
        entry["path"]: entry
        for entry in observed_files
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    snapshot_by_path = {entry["path"]: entry for entry in files}
    if (
        len(observed_by_path) != len(observed_files)
        or set(observed_by_path) != set(snapshot_by_path) | sealing_paths
        or any(
            observed_by_path.get(path) != entry
            for path, entry in snapshot_by_path.items()
        )
    ):
        raise RuntimeError("sealed preparation snapshot changed")


def _validate_sealed_campaign(
    raw_root: Path,
    paths: runner.HarnessPaths,
    *,
    approved_campaign_sha256: str,
    required_frozen_paths: Sequence[str],
    observed_git: Mapping[str, str],
) -> tuple[
    dict[str, Any],
    tuple[dict[str, Any], ...],
    tuple[runner.RunSpec, ...],
    dict[str, Any],
]:
    campaign_payload = runner._read_bytes(
        paths.campaign_file,
        max_bytes=preparation.MAX_FILE_BYTES,
    )
    if sha256(campaign_payload).hexdigest() != approved_campaign_sha256:
        raise RuntimeError("approved campaign hash does not match")
    campaign = runner._load_yaml_object(paths.campaign_file)
    if campaign.get("status") != "approved_not_started":
        raise RuntimeError("campaign is not approved for import")
    envelope_hash = runner.approval_envelope_sha256(campaign)
    runner._validate_user_approval(campaign, envelope_hash)
    proposed = runner._validate_proposed_policy(campaign.get("proposed_approval"))
    frozen = campaign.get("frozen_inputs")
    if not isinstance(frozen, dict):
        raise RuntimeError("frozen approval inputs are invalid")
    harness = frozen.get("harness_git")
    if not isinstance(harness, dict) or dict(observed_git) != harness:
        raise RuntimeError("frozen git identity is invalid")
    runner.verify_frozen_files(
        paths.repository_root,
        frozen.get("files"),
        required_paths=required_frozen_paths,
    )
    cases = runner._load_cases(paths.cases_file)
    plan = runner.build_run_plan(campaign, cases)
    isolation = proposed["isolation"]
    expected_raw = Path(str(isolation["raw_root"]))
    if raw_root != expected_raw or not raw_root.is_absolute():
        raise RuntimeError("sealed campaign root does not match approval")
    try:
        preparation._require_plain_directory(raw_root, label="raw campaign root")
    except (OSError, ValueError) as exc:
        raise RuntimeError("sealed campaign root is unavailable or unsafe") from exc
    approval = _load_json_object(raw_root / "approval.json")
    ledger_path = raw_root / "campaign-ledger.json"
    completion_path = raw_root / "campaign-completion.json"
    ledger = _load_json_object(ledger_path)
    completion = _load_json_object(completion_path)
    ledger_hash = sha256(_read_text_artifact(ledger_path)).hexdigest()
    completed_marker = _read_text_artifact(raw_root / "COMPLETED")
    preparation_failure = _preparation_failure(ledger)
    if (
        approval.get("campaign_sha256") != approved_campaign_sha256
        or approval.get("approval_envelope_sha256") != envelope_hash
        or ledger.get("campaign_sha256") != approved_campaign_sha256
        or ledger.get("approval_envelope_sha256") != envelope_hash
        or ledger.get("sealed") is not True
        or ledger.get("runs_authorized") != 24
        or completion.get("campaign_sha256") != approved_campaign_sha256
        or completion.get("approval_envelope_sha256") != envelope_hash
        or completion.get("campaign_ledger_sha256") != ledger_hash
        or completed_marker != ledger_hash.encode("ascii") + b"\n"
    ):
        raise RuntimeError("sealed campaign binding is invalid")
    if preparation_failure is not None:
        _validate_preparation_snapshot(raw_root, ledger)
        if (
            ledger.get("runs_started") != 0
            or ledger.get("runs_completed") != 0
            or completion.get("runs_started") != 0
            or completion.get("runs_completed") != 0
            or not _matches_artifact_record(
                raw_root / "campaign-failure.json",
                ledger.get("failure_artifact"),
            )
            or (raw_root / "prepared-campaign.json").exists()
            or (raw_root / "prepared-campaign.json").is_symlink()
            or (raw_root / "runs").exists()
            or (raw_root / "runs").is_symlink()
        ):
            raise RuntimeError("sealed preparation failure binding is invalid")
    elif (
        ledger.get("failure_artifact") is not None
        or (raw_root / "campaign-failure.json").exists()
        or (raw_root / "campaign-failure.json").is_symlink()
    ):
        raise RuntimeError("sealed campaign failure binding is invalid")
    runs = ledger.get("runs")
    if not isinstance(runs, list) or len(runs) != len(plan):
        raise RuntimeError("sealed campaign run ledger is invalid")
    for item, record in zip(plan, runs, strict=True):
        if (
            not isinstance(record, dict)
            or record.get("ordinal") != item.ordinal
            or record.get("variant") != item.variant
            or record.get("case_id") != item.case_id
        ):
            raise RuntimeError("sealed campaign run ledger is invalid")
        status_path = (
            raw_root
            / "runs"
            / item.variant
            / item.case_id
            / "raw"
            / "run-status.json"
        )
        recorded_status = record.get("run_status")
        recorded_artifact = record.get("run_status_artifact")
        if recorded_status is None:
            if (
                recorded_artifact is not None
                or status_path.exists()
                or status_path.is_symlink()
            ):
                raise RuntimeError("sealed campaign run status changed")
            continue
        if not _matches_artifact_record(
            status_path,
            recorded_artifact,
        ):
            raise RuntimeError("sealed campaign run status changed")
        if _load_json_object(status_path) != recorded_status:
            raise RuntimeError("sealed campaign run status changed")
    return campaign, cases, plan, ledger


def _retained_root(
    campaign: Mapping[str, Any],
    repository_root: Path,
) -> Path:
    proposed = campaign.get("proposed_approval")
    isolation = proposed.get("isolation") if isinstance(proposed, dict) else None
    value = isolation.get("retained_root") if isinstance(isolation, dict) else None
    relative = _safe_relative_path(value)
    target = repository_root.joinpath(*relative.parts)
    try:
        if target.resolve(strict=False).parent != target.parent.resolve(strict=False):
            raise RuntimeError("retained campaign root is unsafe")
    except OSError as exc:
        raise RuntimeError("retained campaign root is unsafe") from exc
    return target


def _remove_generated_import_root(root: Path, parent: Path) -> None:
    if not root.exists() and not root.is_symlink():
        return
    try:
        resolved_parent = parent.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
        resolved_root.relative_to(resolved_parent)
        if not root.name.startswith(".complete-suite-import-"):
            raise RuntimeError("generated import root name is invalid")
        preparation._require_plain_directory(root, label="generated import root")
    except (OSError, ValueError) as exc:
        raise RuntimeError("generated import root cleanup is unsafe") from exc
    shutil.rmtree(root)


def import_campaign(
    raw_root: Path,
    *,
    paths: runner.HarnessPaths | None = None,
    retained_repository_root: Path | None = None,
    approved_campaign_sha256: str,
    required_frozen_paths: Sequence[str] | None = None,
    observed_git: Mapping[str, str] | None = None,
    retain_factory: Callable[..., dict[str, Any]] | None = None,
    replay_factory: Callable[..., None] | None = None,
) -> Path:
    selected = runner.default_paths() if paths is None else paths
    required = (
        runner.approval_bound_paths(selected)
        if required_frozen_paths is None
        else tuple(required_frozen_paths)
    )
    if observed_git is None:
        campaign = runner._load_yaml_object(selected.campaign_file)
        frozen = campaign.get("frozen_inputs")
        harness = frozen.get("harness_git") if isinstance(frozen, dict) else None
        if not isinstance(harness, dict):
            raise RuntimeError("frozen git identity is invalid")
        observed = runner._git_identity(
            selected.repository_root,
            str(harness.get("commit", "")),
        )
        runner._require_clean_worktree(selected.repository_root)
    else:
        observed = dict(observed_git)
    campaign, _cases, plan, raw_ledger = _validate_sealed_campaign(
        raw_root,
        selected,
        approved_campaign_sha256=approved_campaign_sha256,
        required_frozen_paths=required,
        observed_git=observed,
    )
    retained_repository = (
        selected.repository_root
        if retained_repository_root is None
        else retained_repository_root
    )
    try:
        preparation._require_plain_directory(
            retained_repository,
            label="retained repository root",
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("retained repository root is unsafe") from exc
    retained_root = _retained_root(campaign, retained_repository)
    if retained_root.exists() or retained_root.is_symlink():
        raise RuntimeError("retained campaign root already exists")
    retained_parent = retained_root.parent
    retained_parent.mkdir(parents=True, exist_ok=True)
    try:
        preparation._require_plain_directory(
            retained_parent,
            label="retained campaign parent",
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("retained campaign parent is unsafe") from exc
    scratch = Path(
        tempfile.mkdtemp(
            prefix=".complete-suite-import-",
            dir=retained_parent,
        )
    )
    retain = retain_run_evidence if retain_factory is None else retain_factory
    replay = replay_run_evidence if replay_factory is None else replay_factory
    try:
        campaign_names = _campaign_artifact_names(raw_ledger)
        campaign_entries = [
            retain_text_artifact(
                raw_root / name,
                raw_root=raw_root,
                retained_root=scratch,
                retained_path=f"campaign/{name}",
                allow_redaction=False,
            )
            for name in campaign_names
        ]
        run_entries: list[dict[str, Any]] = []
        preparation_failure = _preparation_failure(raw_ledger)
        if preparation_failure is None:
            for item in plan:
                case_root = raw_root / "runs" / item.variant / item.case_id
                retained_run = scratch / "runs" / item.variant / item.case_id
                retained_run.mkdir(parents=True)
                ledger = retain(case_root, retained_run, item)
                replay(case_root, retained_run, ledger)
                ledger_path = (
                    scratch / "ledgers" / item.variant / f"{item.case_id}.json"
                )
                _write_json(ledger_path, ledger)
                run_entries.append(
                    {
                        "ordinal": item.ordinal,
                        "variant": item.variant,
                        "case_id": item.case_id,
                        "ledger_path": (
                            f"ledgers/{item.variant}/{item.case_id}.json"
                        ),
                        "ledger_sha256": sha256(
                            ledger_path.read_bytes()
                        ).hexdigest(),
                        "evaluable": ledger.get("evaluable") is True,
                    }
                )
        import_ledger = {
            "schema_version": "1.0",
            "campaign_sha256": approved_campaign_sha256,
            "approval_envelope_sha256": runner.approval_envelope_sha256(campaign),
            "raw_campaign_ledger_sha256": sha256(
                (raw_root / "campaign-ledger.json").read_bytes()
            ).hexdigest(),
            "raw_deviations": raw_ledger.get("deviations"),
            "campaign_files": campaign_entries,
            "run_count": len(run_entries),
            "runs": run_entries,
        }
        if preparation_failure is not None:
            import_ledger["failure"] = preparation_failure
            import_ledger["runs_authorized"] = len(plan)
        _write_json(scratch / "import-ledger.json", import_ledger)
        if retained_root.exists() or retained_root.is_symlink():
            raise RuntimeError("retained campaign root already exists")
        scratch.rename(retained_root)
    except BaseException:
        _remove_generated_import_root(scratch, retained_parent)
        raise
    return retained_root


def _require_import_layout(
    retained_root: Path,
    plan: Sequence[runner.RunSpec],
    *,
    preparation_failed: bool = False,
) -> None:
    try:
        preparation._require_plain_directory(
            retained_root,
            label="retained campaign root",
        )
        root_entries = {entry.name for entry in retained_root.iterdir()}
    except (OSError, ValueError) as exc:
        raise RuntimeError("retained campaign root is unavailable or unsafe") from exc
    if preparation_failed:
        if root_entries != {"campaign", "import-ledger.json"}:
            raise RuntimeError("retained campaign layout is invalid")
        try:
            preparation._require_plain_directory(
                retained_root / "campaign",
                label="retained campaign root",
            )
            campaign_files = {
                entry.name for entry in (retained_root / "campaign").iterdir()
            }
        except (OSError, ValueError) as exc:
            raise RuntimeError("retained campaign layout is invalid") from exc
        if campaign_files != {
            "approval.json",
            "campaign-failure.json",
            "campaign-ledger.json",
            "campaign-completion.json",
            "COMPLETED",
        }:
            raise RuntimeError("retained campaign layout is invalid")
        return
    if root_entries - {"campaign", "import-ledger.json", "ledgers", "results", "runs"}:
        raise RuntimeError("retained campaign layout is invalid")
    for name in ("campaign", "ledgers", "runs"):
        try:
            preparation._require_plain_directory(
                retained_root / name,
                label=f"retained {name} root",
            )
        except (OSError, ValueError) as exc:
            raise RuntimeError("retained campaign layout is invalid") from exc
    expected_campaign_files = {
        "approval.json",
        "prepared-campaign.json",
        "campaign-ledger.json",
        "campaign-completion.json",
        "COMPLETED",
    }
    try:
        campaign_files = {
            entry.name for entry in (retained_root / "campaign").iterdir()
        }
    except OSError as exc:
        raise RuntimeError("retained campaign layout is invalid") from exc
    if campaign_files != expected_campaign_files:
        raise RuntimeError("retained campaign layout is invalid")
    expected_cases = {
        variant: {item.case_id for item in plan if item.variant == variant}
        for variant in ("baseline", "suite-enabled")
    }
    for parent_name in ("ledgers", "runs"):
        parent = retained_root / parent_name
        try:
            variants = {entry.name for entry in parent.iterdir()}
        except OSError as exc:
            raise RuntimeError("retained campaign layout is invalid") from exc
        if variants != set(expected_cases):
            raise RuntimeError("retained campaign layout is invalid")
        for variant, case_ids in expected_cases.items():
            variant_root = parent / variant
            try:
                preparation._require_plain_directory(
                    variant_root,
                    label="retained variant root",
                )
                entries = {entry.name for entry in variant_root.iterdir()}
            except (OSError, ValueError) as exc:
                raise RuntimeError("retained campaign layout is invalid") from exc
            expected = (
                {f"{case_id}.json" for case_id in case_ids}
                if parent_name == "ledgers"
                else case_ids
            )
            if entries != expected:
                raise RuntimeError("retained campaign layout is invalid")


def _require_confined_worktree(
    repository_root: Path,
    retained_root: Path,
) -> None:
    try:
        repository = repository_root.resolve(strict=True)
        retained = retained_root.resolve(strict=True)
        relative = retained.relative_to(repository).as_posix().rstrip("/")
        preparation._require_plain_directory(
            retained,
            label="retained campaign root",
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("retained campaign root is unsafe") from exc
    try:
        completed = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            cwd=repository,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("campaign worktree status is unavailable") from exc
    if completed.returncode != 0 or completed.stderr:
        raise RuntimeError("campaign worktree status is unavailable")
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise RuntimeError("campaign worktree status is invalid")
        status = record[:2]
        if b"R" in status or b"C" in status:
            raise RuntimeError(
                "campaign worktree changed outside retained campaign root"
            )
        try:
            path = record[3:].decode("utf-8").replace("\\", "/").rstrip("/")
        except UnicodeDecodeError as exc:
            raise RuntimeError("campaign worktree status is invalid") from exc
        if path != relative and not path.startswith(relative + "/"):
            raise RuntimeError(
                "campaign worktree changed outside retained campaign root"
            )


def replay_campaign_import(
    raw_root: Path,
    retained_root: Path,
    *,
    paths: runner.HarnessPaths | None = None,
    retained_repository_root: Path | None = None,
    approved_campaign_sha256: str,
    required_frozen_paths: Sequence[str] | None = None,
    observed_git: Mapping[str, str] | None = None,
    replay_factory: Callable[..., None] | None = None,
) -> tuple[
    dict[str, Any],
    tuple[dict[str, Any], ...],
    tuple[runner.RunSpec, ...],
    tuple[dict[str, Any], ...],
    dict[str, Any],
]:
    selected = runner.default_paths() if paths is None else paths
    required = (
        runner.approval_bound_paths(selected)
        if required_frozen_paths is None
        else tuple(required_frozen_paths)
    )
    require_confined_status = observed_git is None
    if require_confined_status:
        campaign = runner._load_yaml_object(selected.campaign_file)
        frozen = campaign.get("frozen_inputs")
        harness = frozen.get("harness_git") if isinstance(frozen, dict) else None
        if not isinstance(harness, dict):
            raise RuntimeError("frozen git identity is invalid")
        observed = runner._git_identity(
            selected.repository_root,
            str(harness.get("commit", "")),
        )
    else:
        observed = dict(observed_git)
    campaign, cases, plan, raw_ledger = _validate_sealed_campaign(
        raw_root,
        selected,
        approved_campaign_sha256=approved_campaign_sha256,
        required_frozen_paths=required,
        observed_git=observed,
    )
    retained_repository = (
        selected.repository_root
        if retained_repository_root is None
        else retained_repository_root
    )
    try:
        preparation._require_plain_directory(
            retained_repository,
            label="retained repository root",
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("retained repository root is unsafe") from exc
    if retained_root != _retained_root(campaign, retained_repository):
        raise RuntimeError("retained campaign root does not match approval")
    if require_confined_status:
        _require_confined_worktree(retained_repository, retained_root)
    preparation_failure = _preparation_failure(raw_ledger)
    _require_import_layout(
        retained_root,
        plan,
        preparation_failed=preparation_failure is not None,
    )
    import_path = retained_root / "import-ledger.json"
    import_bytes = _read_text_artifact(import_path)
    import_ledger = _load_json_object(import_path)
    expected_fields = {
        "schema_version",
        "campaign_sha256",
        "approval_envelope_sha256",
        "raw_campaign_ledger_sha256",
        "raw_deviations",
        "campaign_files",
        "run_count",
        "runs",
    }
    if preparation_failure is not None:
        expected_fields |= {"failure", "runs_authorized"}
    campaign_files = import_ledger.get("campaign_files")
    runs = import_ledger.get("runs")
    raw_ledger_hash = sha256(
        _read_text_artifact(raw_root / "campaign-ledger.json")
    ).hexdigest()
    if (
        set(import_ledger) != expected_fields
        or import_ledger.get("schema_version") != "1.0"
        or import_ledger.get("campaign_sha256") != approved_campaign_sha256
        or import_ledger.get("approval_envelope_sha256")
        != runner.approval_envelope_sha256(campaign)
        or import_ledger.get("raw_campaign_ledger_sha256") != raw_ledger_hash
        or import_ledger.get("raw_deviations") != raw_ledger.get("deviations")
        or import_ledger.get("run_count")
        != (0 if preparation_failure is not None else len(plan))
        or not isinstance(campaign_files, list)
        or not isinstance(runs, list)
        or len(runs) != (0 if preparation_failure is not None else len(plan))
        or (
            preparation_failure is not None
            and (
                import_ledger.get("failure") != preparation_failure
                or import_ledger.get("runs_authorized") != len(plan)
            )
        )
    ):
        raise RuntimeError("campaign import ledger is invalid")
    expected_campaign_paths = {
        f"campaign/{name}"
        for name in _campaign_artifact_names(raw_ledger)
    }
    expected_campaign_raw = {
        path.removeprefix("campaign/") for path in expected_campaign_paths
    }
    campaign_raw, campaign_retained = _ledger_paths(campaign_files)
    if (
        campaign_raw != expected_campaign_raw
        or campaign_retained != expected_campaign_paths
    ):
        raise RuntimeError("campaign import ledger is invalid")
    replay_artifact_ledger(raw_root, retained_root, campaign_files)
    if preparation_failure is not None:
        if _read_text_artifact(import_path) != import_bytes:
            raise RuntimeError("campaign import ledger changed")
        return campaign, cases, plan, (), import_ledger
    replay = replay_run_evidence if replay_factory is None else replay_factory
    ledgers: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item, untrusted in zip(plan, runs, strict=True):
        expected_path = f"ledgers/{item.variant}/{item.case_id}.json"
        if (
            not isinstance(untrusted, dict)
            or set(untrusted)
            != {
                "ordinal",
                "variant",
                "case_id",
                "ledger_path",
                "ledger_sha256",
                "evaluable",
            }
            or untrusted.get("ordinal") != item.ordinal
            or untrusted.get("variant") != item.variant
            or untrusted.get("case_id") != item.case_id
            or untrusted.get("ledger_path") != expected_path
            or not isinstance(untrusted.get("evaluable"), bool)
            or expected_path in seen_paths
        ):
            raise RuntimeError("campaign import run ledger is invalid")
        seen_paths.add(expected_path)
        ledger_path = retained_root.joinpath(*PurePosixPath(expected_path).parts)
        ledger_bytes = _read_text_artifact(ledger_path)
        if untrusted.get("ledger_sha256") != sha256(ledger_bytes).hexdigest():
            raise RuntimeError("campaign import run ledger changed")
        ledger = _load_json_object(ledger_path)
        if (
            ledger.get("ordinal") != item.ordinal
            or ledger.get("variant") != item.variant
            or ledger.get("case_id") != item.case_id
            or ledger.get("evaluable") is not untrusted["evaluable"]
        ):
            raise RuntimeError("campaign import run ledger is invalid")
        replay(
            raw_root / "runs" / item.variant / item.case_id,
            retained_root / "runs" / item.variant / item.case_id,
            ledger,
        )
        if _read_text_artifact(ledger_path) != ledger_bytes:
            raise RuntimeError("campaign import run ledger changed")
        ledgers.append(ledger)
    if _read_text_artifact(import_path) != import_bytes:
        raise RuntimeError("campaign import ledger changed")
    return campaign, cases, plan, tuple(ledgers), import_ledger


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_root", type=Path)
    parser.add_argument("--approved-campaign-sha256", required=True)
    args = parser.parse_args()
    import_campaign(
        args.raw_root,
        approved_campaign_sha256=args.approved_campaign_sha256,
    )


if __name__ == "__main__":
    main()
