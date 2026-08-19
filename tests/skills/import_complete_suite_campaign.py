from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from typing import Any, Mapping, Sequence


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_root", type=Path)
    parser.parse_args()
    raise SystemExit("complete-suite import requires an approved sealed campaign")


if __name__ == "__main__":
    main()
