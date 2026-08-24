from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
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
_AUTHORIZATION_ID = re.compile(r"^[0-9a-f]{32}$")
_UTC_RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?Z$"
)
_TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".yaml", ".yml"}
_IMPORT_AUTHORIZATION_FIELDS = {
    "schema_version",
    "capture_method",
    "user_event_authentication",
    "authorization_id",
    "observed_at",
    "authorization_prompt_record",
    "authorization_prompt_sha256",
    "response_text",
    "response_sha256",
    "campaign_id",
    "campaign_sha256",
    "approval_envelope_sha256",
    "provider_approval_sha256",
    "sealed_campaign_audit_record",
    "sealed_campaign_audit_sha256",
    "raw_root",
    "raw_seal_sha256",
    "raw_inventory_sha256",
    "run_count",
    "retained_root",
    "actions",
    "retry_allowed",
}
_IMPORT_AUTHORIZATION_ACTIONS = ("adjudicate", "import", "sanitize")
_IMPORT_AUTHORIZATION_ROOT_PREFIX = "kokoroarc-c6-import-authorization-"
_LEGACY_LEDGER_FIELDS = {
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
_LEDGER_FIELDS = _LEGACY_LEDGER_FIELDS | {"operation_provenance"}
_OPERATION_ARTIFACT_NAMES = (
    "command-plans.jsonl",
    "command-plan-ledger.json",
    "file-change-plans.jsonl",
    "file-change-ledger.json",
)
_LEGACY_RAW_RUN_FILES = (
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
_OPERATION_RAW_RUN_FILES = (
    ("command-plans.jsonl", None, False, False),
    ("command-plan-ledger.json", None, False, False),
    ("file-change-plans.jsonl", None, False, False),
    ("file-change-ledger.json", None, False, False),
)
_RAW_RUN_FILES = (*_LEGACY_RAW_RUN_FILES, *_OPERATION_RAW_RUN_FILES)
_LEGACY_DERIVED_FILE_NAMES = (
    "agent-final-events.jsonl",
    "agent-command-events.jsonl",
    "agent-final-session.json",
)
_DERIVED_FILE_NAMES = (
    *_LEGACY_DERIVED_FILE_NAMES,
    *_OPERATION_ARTIFACT_NAMES,
)
_RETAINED_OPERATION_PATHS = {
    "command_plans": "command-plans.jsonl",
    "command_plan_ledger": "command-plan-ledger.json",
    "file_change_plans": "file-change-plans.jsonl",
    "file_change_ledger": "file-change-ledger.json",
}


@dataclass(frozen=True, repr=False)
class ImportAuthorization:
    authorization_id: str
    observed_at: str
    authorization_prompt_record: Path
    authorization_prompt_sha256: str
    response_text: str
    response_sha256: str
    campaign_sha256: str
    approval_envelope_sha256: str
    provider_approval_sha256: str
    sealed_campaign_audit_record: Path
    sealed_campaign_audit_sha256: str
    raw_root: Path
    raw_seal_sha256: str
    raw_inventory_sha256: str
    retained_root: Path
    actions: tuple[str, ...]
    canonical_bytes: bytes
    canonical_sha256: str


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if type(key) is not str or key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _decode_canonical_json_bytes(
    payload: bytes,
    *,
    label: str,
) -> dict[str, Any]:
    if (
        type(payload) is not bytes
        or not payload.endswith(b"\n")
        or b"\r" in payload
        or len(payload) > MAX_RETAINED_TEXT_BYTES
    ):
        raise RuntimeError(f"{label} is invalid")
    try:
        value = json.loads(
            payload[:-1],
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("nonfinite JSON value")
            ),
        )
        canonical = runner.canonical_bytes(value) + b"\n"
    except (TypeError, ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise RuntimeError(f"{label} is invalid") from exc
    if type(value) is not dict or canonical != payload:
        raise RuntimeError(f"{label} is invalid")
    return value


def _require_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise RuntimeError(f"{label} is invalid")
    return value


def _require_utc_rfc3339(value: object) -> str:
    if type(value) is not str or _UTC_RFC3339.fullmatch(value) is None:
        raise RuntimeError("import authorization observation time is invalid")
    try:
        observed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise RuntimeError(
            "import authorization observation time is invalid"
        ) from exc
    if observed.tzinfo != timezone.utc:
        raise RuntimeError("import authorization observation time is invalid")
    return value


def _canonical_plain_file(value: object, *, label: str) -> Path:
    if type(value) is not str or not value:
        raise RuntimeError(f"{label} is invalid")
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeError(f"{label} is invalid")
    try:
        resolved = path.resolve(strict=True)
        if resolved != path.absolute() or path.is_symlink():
            raise RuntimeError(f"{label} is invalid")
        preparation._require_plain_directory(path.parent, label=f"{label} parent")
        if not path.is_file():
            raise RuntimeError(f"{label} is invalid")
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{label} is invalid") from exc
    return path


def _expected_path_text(path: Path) -> str:
    return str(path) if path.is_absolute() else path.as_posix()


def _expected_import_authorization_prompt(
    record: Mapping[str, Any],
) -> bytes:
    return (
        "KOKOROARC CAMPAIGN 6 IMPORT AUTHORIZATION v1\n"
        f"authorization_id={record['authorization_id']}\n"
        "campaign_id=2026-08-21-proposed6\n"
        f"campaign_sha256={record['campaign_sha256']}\n"
        "approval_envelope_sha256="
        f"{record['approval_envelope_sha256']}\n"
        "provider_approval_sha256="
        f"{record['provider_approval_sha256']}\n"
        "sealed_campaign_audit_record="
        f"{record['sealed_campaign_audit_record']}\n"
        "sealed_campaign_audit_sha256="
        f"{record['sealed_campaign_audit_sha256']}\n"
        "sealed_campaign_result_class=sealed_24_run\n"
        f"raw_root={record['raw_root']}\n"
        f"raw_seal_sha256={record['raw_seal_sha256']}\n"
        "raw_inventory_sha256="
        f"{record['raw_inventory_sha256']}\n"
        "run_count=24\n"
        f"retained_root={record['retained_root']}\n"
        "retained_root_state=absent\n"
        "actions=adjudicate,import,sanitize\n"
        "retry_allowed=false\n"
        "authorization=import sanitize adjudicate\n"
        "reply_grammar=APPROVE CAMPAIGN 6 IMPORT SANITIZE ADJUDICATE "
        "<sealed-campaign-audit-sha256> <authorization-prompt-sha256>\n"
    ).encode("utf-8")


def _validate_sealed_campaign_audit(
    path: Path,
    *,
    expected_sha256: str,
    expected_campaign_sha256: str,
    expected_envelope_sha256: str,
    expected_provider_approval_sha256: str,
    expected_raw_root: Path,
    expected_raw_seal_sha256: str,
    expected_raw_inventory_sha256: str,
    expected_retained_root: Path,
) -> None:
    payload = _read_text_artifact(path)
    if sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError("sealed campaign audit changed")
    audit = _decode_canonical_json_bytes(
        payload,
        label="sealed campaign audit",
    )
    expected = {
        "schema_version": "complete-suite-sealed-campaign-audit-v1",
        "result_class": "sealed_24_run",
        "campaign_sha256": expected_campaign_sha256,
        "approval_envelope_sha256": expected_envelope_sha256,
        "provider_approval_sha256": expected_provider_approval_sha256,
        "raw_root": _expected_path_text(expected_raw_root),
        "raw_seal_sha256": expected_raw_seal_sha256,
        "raw_inventory_sha256": expected_raw_inventory_sha256,
        "run_count": 24,
        "retained_root": _expected_path_text(expected_retained_root),
        "retained_root_state": "absent",
        "retry_allowed": False,
    }
    if any(audit.get(key) != value for key, value in expected.items()):
        raise RuntimeError("sealed campaign audit is invalid")


def _validate_import_authorization(
    record_bytes: bytes,
    *,
    expected_record_sha256: str,
    expected_import_authorization_prompt_sha256: str,
    expected_campaign_sha256: str,
    expected_envelope_sha256: str,
    expected_provider_approval_sha256: str,
    expected_sealed_campaign_audit_sha256: str,
    expected_raw_root: Path,
    expected_raw_seal_sha256: str,
    expected_raw_inventory_sha256: str,
    expected_retained_root: Path,
    require_retained_root_absent: bool,
) -> ImportAuthorization:
    expected_hashes = {
        "record": _require_sha256(
            expected_record_sha256,
            label="import authorization hash",
        ),
        "prompt": _require_sha256(
            expected_import_authorization_prompt_sha256,
            label="import authorization prompt hash",
        ),
        "campaign": _require_sha256(
            expected_campaign_sha256,
            label="approved campaign hash",
        ),
        "envelope": _require_sha256(
            expected_envelope_sha256,
            label="approval envelope hash",
        ),
        "provider": _require_sha256(
            expected_provider_approval_sha256,
            label="provider approval hash",
        ),
        "audit": _require_sha256(
            expected_sealed_campaign_audit_sha256,
            label="sealed campaign audit hash",
        ),
        "raw_seal": _require_sha256(
            expected_raw_seal_sha256,
            label="raw campaign seal hash",
        ),
        "raw_inventory": _require_sha256(
            expected_raw_inventory_sha256,
            label="raw campaign inventory hash",
        ),
    }
    if (
        not isinstance(expected_raw_root, Path)
        or not isinstance(expected_retained_root, Path)
        or not expected_raw_root.is_absolute()
    ):
        raise RuntimeError("import authorization root binding is invalid")
    try:
        raw_root = expected_raw_root.resolve(strict=True)
        if raw_root != expected_raw_root.absolute():
            raise RuntimeError("import authorization raw root is unsafe")
        preparation._require_plain_directory(raw_root, label="sealed raw root")
    except (OSError, ValueError) as exc:
        raise RuntimeError("import authorization raw root is unsafe") from exc
    if require_retained_root_absent and (
        expected_retained_root.exists() or expected_retained_root.is_symlink()
    ):
        raise RuntimeError("retained campaign root already exists")
    if not expected_retained_root.is_absolute():
        _safe_relative_path(expected_retained_root.as_posix())

    if type(record_bytes) is not bytes or sha256(record_bytes).hexdigest() != (
        expected_hashes["record"]
    ):
        raise RuntimeError("import authorization changed")
    record = _decode_canonical_json_bytes(
        record_bytes,
        label="import authorization",
    )
    if (
        set(record) != _IMPORT_AUTHORIZATION_FIELDS
        or record.get("schema_version")
        != "complete-suite-import-authorization-v2"
        or record.get("capture_method")
        != "codex-conversation-operator-attestation-v1"
        or record.get("user_event_authentication")
        != "operator-attested-not-cryptographic"
        or record.get("campaign_id") != "2026-08-21-proposed6"
        or record.get("run_count") != 24
        or type(record.get("run_count")) is not int
        or record.get("actions") != list(_IMPORT_AUTHORIZATION_ACTIONS)
        or record.get("retry_allowed") is not False
    ):
        raise RuntimeError("import authorization is invalid")
    authorization_id = record.get("authorization_id")
    if (
        type(authorization_id) is not str
        or _AUTHORIZATION_ID.fullmatch(authorization_id) is None
    ):
        raise RuntimeError("import authorization identifier is invalid")
    observed_at = _require_utc_rfc3339(record.get("observed_at"))
    for field, expected in (
        ("authorization_prompt_sha256", expected_hashes["prompt"]),
        ("campaign_sha256", expected_hashes["campaign"]),
        ("approval_envelope_sha256", expected_hashes["envelope"]),
        ("provider_approval_sha256", expected_hashes["provider"]),
        ("sealed_campaign_audit_sha256", expected_hashes["audit"]),
        ("raw_seal_sha256", expected_hashes["raw_seal"]),
        ("raw_inventory_sha256", expected_hashes["raw_inventory"]),
    ):
        if record.get(field) != expected:
            raise RuntimeError("import authorization binding is invalid")
    if (
        record.get("raw_root") != _expected_path_text(raw_root)
        or record.get("retained_root")
        != _expected_path_text(expected_retained_root)
    ):
        raise RuntimeError("import authorization root binding is invalid")

    prompt_path = _canonical_plain_file(
        record.get("authorization_prompt_record"),
        label="import authorization prompt",
    )
    expected_parent = f"{_IMPORT_AUTHORIZATION_ROOT_PREFIX}{authorization_id}"
    if (
        prompt_path.name != "import-authorization-prompt.txt"
        or prompt_path.parent.name != expected_parent
    ):
        raise RuntimeError("import authorization prompt path is invalid")
    prompt_bytes = _read_text_artifact(prompt_path)
    if (
        sha256(prompt_bytes).hexdigest() != expected_hashes["prompt"]
        or prompt_bytes != _expected_import_authorization_prompt(record)
    ):
        raise RuntimeError("import authorization prompt is invalid")

    sealed_audit_path = _canonical_plain_file(
        record.get("sealed_campaign_audit_record"),
        label="sealed campaign audit",
    )
    _validate_sealed_campaign_audit(
        sealed_audit_path,
        expected_sha256=expected_hashes["audit"],
        expected_campaign_sha256=expected_hashes["campaign"],
        expected_envelope_sha256=expected_hashes["envelope"],
        expected_provider_approval_sha256=expected_hashes["provider"],
        expected_raw_root=raw_root,
        expected_raw_seal_sha256=expected_hashes["raw_seal"],
        expected_raw_inventory_sha256=expected_hashes["raw_inventory"],
        expected_retained_root=expected_retained_root,
    )
    response = record.get("response_text")
    if type(response) is not str:
        raise RuntimeError("import authorization response is invalid")
    expected_response = (
        "APPROVE CAMPAIGN 6 IMPORT SANITIZE ADJUDICATE "
        f"{expected_hashes['audit']} {expected_hashes['prompt']}"
    )
    response_hash = sha256(response.encode("utf-8")).hexdigest()
    if (
        response != expected_response
        or record.get("response_sha256") != response_hash
    ):
        raise RuntimeError("import authorization response is invalid")
    return ImportAuthorization(
        authorization_id=authorization_id,
        observed_at=observed_at,
        authorization_prompt_record=prompt_path,
        authorization_prompt_sha256=expected_hashes["prompt"],
        response_text=response,
        response_sha256=response_hash,
        campaign_sha256=expected_hashes["campaign"],
        approval_envelope_sha256=expected_hashes["envelope"],
        provider_approval_sha256=expected_hashes["provider"],
        sealed_campaign_audit_record=sealed_audit_path,
        sealed_campaign_audit_sha256=expected_hashes["audit"],
        raw_root=raw_root,
        raw_seal_sha256=expected_hashes["raw_seal"],
        raw_inventory_sha256=expected_hashes["raw_inventory"],
        retained_root=expected_retained_root,
        actions=_IMPORT_AUTHORIZATION_ACTIONS,
        canonical_bytes=bytes(record_bytes),
        canonical_sha256=expected_hashes["record"],
    )


def validate_import_authorization(
    record_bytes: bytes,
    *,
    expected_record_sha256: str,
    expected_import_authorization_prompt_sha256: str,
    expected_campaign_sha256: str,
    expected_envelope_sha256: str,
    expected_provider_approval_sha256: str,
    expected_sealed_campaign_audit_sha256: str,
    expected_raw_root: Path,
    expected_raw_seal_sha256: str,
    expected_raw_inventory_sha256: str,
    expected_retained_root: Path,
) -> ImportAuthorization:
    return _validate_import_authorization(
        record_bytes,
        expected_record_sha256=expected_record_sha256,
        expected_import_authorization_prompt_sha256=(
            expected_import_authorization_prompt_sha256
        ),
        expected_campaign_sha256=expected_campaign_sha256,
        expected_envelope_sha256=expected_envelope_sha256,
        expected_provider_approval_sha256=expected_provider_approval_sha256,
        expected_sealed_campaign_audit_sha256=(
            expected_sealed_campaign_audit_sha256
        ),
        expected_raw_root=expected_raw_root,
        expected_raw_seal_sha256=expected_raw_seal_sha256,
        expected_raw_inventory_sha256=expected_raw_inventory_sha256,
        expected_retained_root=expected_retained_root,
        require_retained_root_absent=True,
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
    *,
    include_operation_provenance: bool,
) -> tuple[set[str], set[str], tuple[tuple[str, str | None], ...]]:
    raw_paths: set[str] = set()
    retained_paths: set[str] = set()
    ordered_paths: list[tuple[str, str | None]] = []
    raw_root = case_root / "raw"
    selected_raw_files = (
        _RAW_RUN_FILES
        if include_operation_provenance
        else _LEGACY_RAW_RUN_FILES
    )
    for raw_name, retained_name, _allow_redaction, optional in selected_raw_files:
        source = raw_root / raw_name
        if optional and not source.exists() and not source.is_symlink():
            continue
        raw_path = (PurePosixPath("raw") / raw_name).as_posix()
        raw_paths.add(raw_path)
        if retained_name is not None:
            retained_paths.add(retained_name)
        ordered_paths.append((raw_path, retained_name))
    for raw_path, retained_path in (
        ("prepared-layout.json", "prepared-layout.json"),
        ("workspace/case.json", "workspace/case.json"),
        ("workspace/inputs/setup.json", "workspace/inputs/setup.json"),
    ):
        raw_paths.add(raw_path)
        retained_paths.add(retained_path)
        ordered_paths.append((raw_path, retained_path))
    for relative in _workspace_artifact_paths(post_run):
        raw_path = (PurePosixPath("workspace") / relative).as_posix()
        retained_path: str | None = None
        raw_paths.add(raw_path)
        if relative.suffix.casefold() in _TEXT_SUFFIXES:
            retained_path = (
                PurePosixPath("workspace-artifacts") / relative
            ).as_posix()
            retained_paths.add(retained_path)
        ordered_paths.append((raw_path, retained_path))
    return raw_paths, retained_paths, tuple(ordered_paths)


def _ledger_paths(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[set[str], set[str], tuple[tuple[str, str | None], ...]]:
    raw_paths: set[str] = set()
    retained_paths: set[str] = set()
    ordered_paths: list[tuple[str, str | None]] = []
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
        ordered_paths.append((raw_path, retained_path))
    return raw_paths, retained_paths, tuple(ordered_paths)


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


def _canonical_record_sha256(value: object) -> str:
    return sha256(runner.canonical_bytes(value)).hexdigest()


def _record_fold_sha256(values: Sequence[str]) -> str:
    if any(type(value) is not str or _SHA256.fullmatch(value) is None for value in values):
        raise RuntimeError("retained operation evidence is invalid")
    return _canonical_record_sha256({"record_sha256": list(values)})


def _record_wrapper(record: Mapping[str, Any], canonical_sha256: str) -> dict[str, Any]:
    detached = json.loads(runner.canonical_bytes(record))
    if (
        type(detached) is not dict
        or type(canonical_sha256) is not str
        or _SHA256.fullmatch(canonical_sha256) is None
        or _canonical_record_sha256(detached) != canonical_sha256
    ):
        raise RuntimeError("retained operation evidence is invalid")
    return {"record": detached, "canonical_sha256": canonical_sha256}


def _capture_record(cli_binding: Any, capture: Any) -> dict[str, Any]:
    capture.__post_init__()
    return {
        "domain": capture.domain,
        "session_identity": cli_binding._identity_record(capture.session_identity),
        "started_event_ordinal": capture.started_event_ordinal,
        "completed_event_ordinal": capture.completed_event_ordinal,
        "event_id": capture.event_id,
        "event_span": {
            "start": capture.event_start,
            "end": capture.event_end,
        },
        "output_field_span": {
            "start": capture.output_field_start,
            "end": capture.output_field_end,
            "utf8_bytes": capture.output_field_utf8_bytes,
            "sha256": capture.output_field_sha256,
        },
        "output": {
            "utf8_bytes": capture.output_utf8_bytes,
            "sha256": capture.output_sha256,
        },
        "exit_code": capture.exit_code,
    }


def _filesystem_evidence_wrapper(command_policy: Any, filesystem: Any) -> dict[str, Any]:
    case_root = command_policy._authenticated_filesystem_case_root(filesystem)
    command_policy._authenticate_filesystem_evidence(
        filesystem,
        expected_case_root=case_root,
    )
    record = command_policy._filesystem_evidence_record(
        pre_run_state_sha256=filesystem.pre_run_state_sha256,
        post_run_state_sha256=filesystem.post_run_state_sha256,
        pre_roots=filesystem.pre_roots,
        post_roots=filesystem.post_roots,
        created_paths=filesystem.created_paths,
        changed_paths=filesystem.changed_paths,
        removed_paths=filesystem.removed_paths,
    )
    return _record_wrapper(record, filesystem.canonical_sha256)


def _command_policy_wrapper(command_policy: Any, pair: Any, filesystem: Any) -> dict[str, Any]:
    command_policy._authenticate_command_policy_decision(
        pair.decision,
        plan=pair.plan,
    )
    if (
        command_policy._authenticated_command_policy_filesystem(
            pair.decision,
            plan=pair.plan,
        )
        is not filesystem
    ):
        raise RuntimeError("retained command policy filesystem mismatch")
    record = command_policy._decision_canonical_record(
        plan_sha256=pair.decision.plan_sha256,
        record_class=pair.decision.record_class,
        operations=pair.decision.operations,
        topology_sha256=pair.decision.topology_sha256,
    )
    return _record_wrapper(record, pair.decision.canonical_sha256)


def _command_result_record(cli_binding: Any, result: Any) -> dict[str, Any]:
    result.__post_init__()
    try:
        retained_text = result.retained_document_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError("retained command result is invalid") from exc
    record = {
        "result": cli_binding._result_record(result),
        "retained_document_utf8": retained_text,
        "retained_document_utf8_bytes": len(result.retained_document_bytes),
        "retained_document_sha256": result.retained_document_sha256,
    }
    return {**record, "canonical_sha256": _canonical_record_sha256(record)}


def _file_change_plan_records(raw_plan: Any, retained_plan: Any) -> list[dict[str, Any]]:
    raw_plan.__post_init__()
    retained_plan.__post_init__()
    if (
        raw_plan.domain != "raw"
        or retained_plan.domain != "retained"
        or raw_plan.lifecycles != retained_plan.lifecycles
        or raw_plan.transition_entries != retained_plan.transition_entries
        or raw_plan.topology_sha256 != retained_plan.topology_sha256
    ):
        raise RuntimeError("raw and retained file-change plans differ")

    def groups(plan: Any) -> tuple[tuple[Any, ...], ...]:
        values = tuple(
            tuple(
                change
                for change in plan.changes
                if change.lifecycle_index == lifecycle_index
            )
            for lifecycle_index in range(plan.lifecycles)
        )
        if any(not group for group in values):
            raise RuntimeError("retained file-change lifecycle is invalid")
        return values

    raw_groups = groups(raw_plan)
    retained_groups = groups(retained_plan)
    records: list[dict[str, Any]] = []
    for lifecycle_index, (raw_changes, retained_changes) in enumerate(
        zip(raw_groups, retained_groups, strict=True)
    ):
        raw_first = raw_changes[0]
        retained_first = retained_changes[0]
        raw_topology = tuple(
            (change.change_ordinal, change.normalized_path, change.kind)
            for change in raw_changes
        )
        retained_topology = tuple(
            (change.change_ordinal, change.normalized_path, change.kind)
            for change in retained_changes
        )
        metadata = (
            raw_first.event_id,
            raw_first.started_event_ordinal,
            raw_first.completed_event_ordinal,
        )
        if (
            raw_topology != retained_topology
            or metadata
            != (
                retained_first.event_id,
                retained_first.started_event_ordinal,
                retained_first.completed_event_ordinal,
            )
            or any(
                (
                    change.event_id,
                    change.started_event_ordinal,
                    change.completed_event_ordinal,
                )
                != metadata
                for change in (*raw_changes, *retained_changes)
            )
        ):
            raise RuntimeError("raw and retained file-change lifecycle differs")
        changes = [
            {
                "change_ordinal": ordinal,
                "normalized_path": path,
                "kind": kind,
            }
            for ordinal, path, kind in retained_topology
        ]
        topology = {
            "lifecycle_index": lifecycle_index,
            "event_id": raw_first.event_id,
            "started_event_ordinal": raw_first.started_event_ordinal,
            "completed_event_ordinal": raw_first.completed_event_ordinal,
            "terminal_status": "completed",
            "changes": changes,
        }
        record = {
            "schema_version": "complete-suite-retained-file-change-plan-v1",
            **{name: topology[name] for name in topology if name != "changes"},
            "raw": {
                "started_item_sha256": raw_first.started_sha256,
                "completed_item_sha256": raw_first.completed_sha256,
                "changes": changes,
            },
            "retained": {
                "started_item_sha256": retained_first.started_sha256,
                "completed_item_sha256": retained_first.completed_sha256,
                "changes": changes,
            },
            "topology_sha256": _canonical_record_sha256(topology),
        }
        records.append(
            {**record, "canonical_sha256": _canonical_record_sha256(record)}
        )
    return records


def _paths_binding(paths: Sequence[str]) -> dict[str, Any]:
    values = list(paths)
    return {
        "paths": values,
        "canonical_sha256": _canonical_record_sha256({"paths": values}),
    }


def _delta_partition(filesystem: Any, file_changes: Any) -> dict[str, Any]:
    record = {
        "created": _paths_binding(filesystem.created_paths),
        "changed": _paths_binding(filesystem.changed_paths),
        "removed": _paths_binding(filesystem.removed_paths),
        "implicit_ancestors": _paths_binding(file_changes.implicit_ancestor_paths),
        "unique_final_paths": _paths_binding(file_changes.unique_final_paths),
    }
    return {**record, "canonical_sha256": _canonical_record_sha256(record)}


def _post_state_binding(
    command_policy: Any,
    filesystem: Any,
    *,
    workspace_relative_root: str,
    normalized_path: str,
) -> dict[str, Any]:
    prefix = "<workspace>\\"
    if not normalized_path.casefold().startswith(prefix.casefold()):
        raise RuntimeError("retained file-change content path is invalid")
    suffix = normalized_path[len(prefix) :]
    desired = str(PureWindowsPath(workspace_relative_root) / PureWindowsPath(suffix))
    matches: list[dict[str, Any]] = []
    for root in filesystem.post_roots:
        for entry in root.entries:
            if root.relative_root == ".":
                observed = entry.relative_path
            else:
                observed = str(
                    PureWindowsPath(root.relative_root)
                    / PureWindowsPath(entry.relative_path)
                )
            if observed.casefold() != desired.casefold():
                continue
            matches.append(
                {
                    "root_index": root.root_index,
                    "root_manifest_sha256": root.manifest_sha256,
                    "root_identity": (
                        None
                        if root.root_identity is None
                        else command_policy._identity_record(root.root_identity)
                    ),
                    "root_ancestor_identities": [
                        command_policy._identity_record(identity)
                        for identity in root.ancestor_identities
                    ],
                    "entry": command_policy._entry_record(entry),
                }
            )
    if len(matches) != 1:
        raise RuntimeError("retained file-change post-state binding is invalid")
    return matches[0]


def build_retained_operation_artifacts(
    *,
    variant: str,
    case_id: str,
    command_captures: tuple[Any, ...],
    filesystem: Any,
    session_evidence: Any,
    raw_file_change_plan: Any,
    retained_file_change_plan: Any,
    file_changes: Any,
    integrity_evidence: Any,
) -> dict[str, bytes]:
    """Serialize the four closed retained operation-provenance artifacts."""

    import complete_suite_adjudication as adjudication
    import complete_suite_cli_binding as cli_binding
    import complete_suite_command_plan as command_plan
    import complete_suite_command_policy as command_policy
    import complete_suite_file_change_policy as file_policy

    if (
        variant not in {"baseline", "suite-enabled"}
        or type(case_id) is not str
        or not case_id
        or type(command_captures) is not tuple
        or not command_captures
        or len(command_captures) > 128
        or type(session_evidence) is not cli_binding.BoundSessionCommandEvidence
        or type(filesystem) is not command_policy.BoundFilesystemEvidence
        or type(raw_file_change_plan) is not file_policy.DecodedFileChangePlan
        or type(retained_file_change_plan) is not file_policy.DecodedFileChangePlan
        or type(file_changes) is not file_policy.FileChangePolicyDecision
        or type(integrity_evidence) is not adjudication.IntegrityApprovedRunEvidence
        or file_changes.variant != variant
        or file_changes.case_id != case_id
        or integrity_evidence.commands is not session_evidence
        or integrity_evidence.file_changes_sha256 != file_changes.canonical_sha256
    ):
        raise RuntimeError("retained operation evidence inputs are invalid")
    cli_binding._authenticate_bound_session_command_evidence(session_evidence)
    provenance = cli_binding._authenticated_session_operation_provenance(
        session_evidence
    )
    if provenance.filesystem is not filesystem:
        raise RuntimeError("retained session filesystem binding mismatch")
    filesystem_wrapper = _filesystem_evidence_wrapper(command_policy, filesystem)
    origin = file_policy._authenticated_policy_decision_origin(
        file_changes,
        filesystem=filesystem,
    )
    file_policy._authenticate_decoded_file_change_plan(
        raw_file_change_plan,
        expected_domain="raw",
        expected_session_sha256=origin.raw_session_sha256,
    )
    file_policy._authenticate_decoded_file_change_plan(
        retained_file_change_plan,
        expected_domain="retained",
        expected_session_sha256=origin.retained_session_sha256,
    )
    integrity_origin = adjudication._authenticate_run_evidence(
        integrity_evidence
    )
    if (
        origin.raw_session_sha256 != provenance.raw_session_sha256
        or origin.retained_session_sha256 != provenance.retained_session_sha256
        or integrity_origin.case_id != case_id
        or integrity_origin.variant != variant
        or integrity_origin.filesystem is not filesystem
        or integrity_origin.file_changes is not file_changes
        or integrity_origin.raw_session_sha256 != provenance.raw_session_sha256
        or integrity_origin.retained_session_sha256
        != provenance.retained_session_sha256
        or len(command_captures) != len(session_evidence.commands)
        or tuple(pair.command_index for pair in command_captures)
        != tuple(range(len(command_captures)))
    ):
        raise RuntimeError("retained session provenance mismatch")
    rebound_session = cli_binding.bind_session_cli_results(
        session_evidence.session_id,
        command_captures,
        raw_session_identity=session_evidence.raw_session_identity,
        retained_session_identity=session_evidence.retained_session_identity,
    )
    rebound_provenance = cli_binding._authenticated_session_operation_provenance(
        rebound_session
    )
    if (
        rebound_session.canonical_bytes != session_evidence.canonical_bytes
        or rebound_session.canonical_sha256 != session_evidence.canonical_sha256
        or rebound_provenance.raw_session_sha256
        != provenance.raw_session_sha256
        or rebound_provenance.retained_session_sha256
        != provenance.retained_session_sha256
        or rebound_provenance.filesystem is not provenance.filesystem
        or rebound_provenance.operations != provenance.operations
    ):
        raise RuntimeError("retained session provenance mismatch")

    command_records: list[dict[str, Any]] = []
    command_lines: list[bytes] = []
    for pair, evidence in zip(
        command_captures,
        session_evidence.commands,
        strict=True,
    ):
        pair.__post_init__()
        evidence.__post_init__()
        plan_bytes = bytes(pair.plan.normalized_plan_bytes)
        command_plan.validate_retained_command_plan_bytes(
            plan_bytes,
            expected_sha256=pair.plan.normalized_plan_sha256,
        )
        if (
            pair.command_index != evidence.command_index
            or pair.plan.normalized_plan_sha256 != evidence.plan_sha256
            or pair.raw_capture.event_id != evidence.event_id
            or pair.retained_capture.event_id != evidence.event_id
            or pair.raw_capture.started_event_ordinal
            != evidence.started_event_ordinal
            or pair.retained_capture.started_event_ordinal
            != evidence.started_event_ordinal
            or pair.raw_capture.completed_event_ordinal
            != evidence.completed_event_ordinal
            or pair.retained_capture.completed_event_ordinal
            != evidence.completed_event_ordinal
            or pair.raw_capture.output_utf8_bytes
            != evidence.raw_output_utf8_bytes
            or pair.raw_capture.output_sha256 != evidence.raw_output_sha256
            or pair.retained_capture.output_utf8_bytes
            != evidence.retained_output_utf8_bytes
            or pair.retained_capture.output_sha256
            != evidence.retained_output_sha256
        ):
            raise RuntimeError("retained command evidence binding mismatch")
        policy_wrapper = _command_policy_wrapper(
            command_policy,
            pair,
            filesystem,
        )
        command_evidence = _record_wrapper(
            cli_binding._command_record(evidence),
            evidence.canonical_sha256,
        )
        record = {
            "command_index": pair.command_index,
            "plan_line_ordinal": pair.command_index,
            "plan_utf8_bytes": len(plan_bytes),
            "plan_sha256": pair.plan.normalized_plan_sha256,
            "decoder_schema_version": command_plan._DECODER_SCHEMA_VERSION,
            "policy": policy_wrapper,
            "raw_capture": _capture_record(cli_binding, pair.raw_capture),
            "retained_capture": _capture_record(
                cli_binding,
                pair.retained_capture,
            ),
            "command_evidence": command_evidence,
            "operational_document_count": len(evidence.results),
            "retained_results": [
                _command_result_record(cli_binding, result)
                for result in evidence.results
            ],
        }
        command_records.append(
            {**record, "canonical_sha256": _canonical_record_sha256(record)}
        )
        command_lines.append(plan_bytes)

    raw_identity = cli_binding._identity_record(
        session_evidence.raw_session_identity
    )
    retained_identity = cli_binding._identity_record(
        session_evidence.retained_session_identity
    )
    session_record = json.loads(session_evidence.canonical_bytes)
    command_ledger = {
        "schema_version": "complete-suite-retained-command-plan-ledger-v1",
        "variant": variant,
        "case_id": case_id,
        "session_id": session_evidence.session_id,
        "raw_session_identity": raw_identity,
        "retained_session_identity": retained_identity,
        "raw_session_sha256": provenance.raw_session_sha256,
        "retained_session_sha256": provenance.retained_session_sha256,
        "raw_bytes_consumed": session_evidence.raw_bytes_consumed,
        "retained_bytes_consumed": session_evidence.retained_bytes_consumed,
        "filesystem_evidence": filesystem_wrapper,
        "session_evidence": _record_wrapper(
            session_record,
            session_evidence.canonical_sha256,
        ),
        "records": command_records,
        "record_fold_sha256": _record_fold_sha256(
            [record["canonical_sha256"] for record in command_records]
        ),
        "retained_evidence_paths": dict(_RETAINED_OPERATION_PATHS),
    }

    file_plan_records = _file_change_plan_records(
        raw_file_change_plan,
        retained_file_change_plan,
    )
    if file_changes.transition_entries != raw_file_change_plan.transition_entries:
        raise RuntimeError("retained file-change transition count mismatch")
    decision_record = file_policy._decision_record(file_changes)
    decision_wrapper = _record_wrapper(
        decision_record,
        file_changes.canonical_sha256,
    )
    delta_partition = _delta_partition(filesystem, file_changes)
    rule_by_path = {rule.normalized_path: rule for rule in origin.rules}
    contents: list[dict[str, Any]] = []
    for content in file_changes.contents:
        file_policy._authenticate_bound_content(content)
        rule = rule_by_path.get(content.normalized_path)
        if rule is None:
            raise RuntimeError("retained file-change content policy is missing")
        try:
            retained_text = content.retained_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RuntimeError("retained file-change content is invalid") from exc
        contents.append(
            {
                "normalized_path": content.normalized_path,
                "role": rule.role,
                "raw_size": content.raw_size,
                "raw_sha256": content.raw_sha256,
                "retained_size": content.retained_size,
                "retained_sha256": content.retained_sha256,
                "retained_content_utf8": retained_text,
                "retained_content_sha256": sha256(content.retained_bytes).hexdigest(),
                "raw_document_sha256": content.raw_document_sha256,
                "retained_document_sha256": content.retained_document_sha256,
                "sanitizer_record_sha256": content.sanitizer_record_sha256,
                "role_validation_sha256": content.role_validation_sha256,
                "post_state": _post_state_binding(
                    command_policy,
                    filesystem,
                    workspace_relative_root=origin.workspace_relative_root,
                    normalized_path=content.normalized_path,
                ),
            }
        )
    contents.sort(key=lambda value: value["normalized_path"].casefold())

    operation_bindings = [
        _record_wrapper(
            adjudication._operation_binding_record(binding),
            binding.canonical_sha256,
        )
        for binding in integrity_evidence.operation_bindings
    ]
    filesystem_view = _record_wrapper(
        adjudication._filesystem_view_record(integrity_evidence.filesystem_view),
        integrity_evidence.filesystem_view.canonical_sha256,
    )
    integrity_record = json.loads(integrity_evidence.canonical_bytes)
    integrity_wrapper = {
        "record": integrity_record,
        "canonical_utf8_bytes": len(integrity_evidence.canonical_bytes),
        "canonical_sha256": integrity_evidence.canonical_sha256,
    }
    aggregate_transition = {
        "normalized_plan_sha256": file_changes.normalized_plan_sha256,
        "aggregate_transition_sha256": file_changes.aggregate_transition_sha256,
        "created_paths_sha256": delta_partition["created"]["canonical_sha256"],
        "changed_paths_sha256": delta_partition["changed"]["canonical_sha256"],
        "removed_paths_sha256": delta_partition["removed"]["canonical_sha256"],
    }
    total_operational_documents = sum(
        len(command.results) for command in session_evidence.commands
    )
    counts = {
        "lifecycles": raw_file_change_plan.lifecycles,
        "transition_entries": file_changes.transition_entries,
        "unique_files": len(file_changes.unique_final_paths),
        "raw_bytes": file_changes.raw_content_bytes,
        "retained_bytes": file_changes.retained_content_bytes,
        "combined_bytes": (
            file_changes.raw_content_bytes + file_changes.retained_content_bytes
        ),
        "operational_documents": total_operational_documents,
    }
    file_entries: list[dict[str, Any]] = []
    for entry_index, plan_record in enumerate(file_plan_records):
        normalized_paths = {
            change["normalized_path"]
            for change in plan_record["retained"]["changes"]
        }
        entry_contents = [
            value for value in contents if value["normalized_path"] in normalized_paths
        ]
        entry_operations = [
            value
            for value in operation_bindings
            if value["record"]["normalized_path"] in normalized_paths
        ]
        raw_plan_binding = {
            "started_item_sha256": plan_record["raw"]["started_item_sha256"],
            "completed_item_sha256": plan_record["raw"]["completed_item_sha256"],
            "changes": plan_record["raw"]["changes"],
        }
        retained_plan_binding = {
            "started_item_sha256": plan_record["retained"]["started_item_sha256"],
            "completed_item_sha256": plan_record["retained"]["completed_item_sha256"],
            "changes": plan_record["retained"]["changes"],
        }
        entry_record = {
            "entry_index": entry_index,
            "plan_line_ordinal": entry_index,
            "plan_sha256": sha256(runner.canonical_bytes(plan_record)).hexdigest(),
            "source_item": {
                "lifecycle_index": plan_record["lifecycle_index"],
                "event_id": plan_record["event_id"],
                "started_event_ordinal": plan_record["started_event_ordinal"],
                "completed_event_ordinal": plan_record["completed_event_ordinal"],
                "terminal_status": plan_record["terminal_status"],
                "topology_sha256": plan_record["topology_sha256"],
            },
            "raw_plan": raw_plan_binding,
            "retained_plan": retained_plan_binding,
            "policy": {
                "version": file_changes.version,
                "variant": variant,
                "case_id": case_id,
                "case_policy_sha256": origin.rule_table_sha256,
                "normalized_plan_sha256": file_changes.normalized_plan_sha256,
                "decision_sha256": file_changes.canonical_sha256,
            },
            "raw_session_identity": raw_identity,
            "retained_session_identity": retained_identity,
            "sanitizer_ledger_sha256": origin.sanitizer_ledger_sha256,
            "aggregate_transition": aggregate_transition,
            "contents": entry_contents,
            "counts": {
                "transition_entries": len(plan_record["retained"]["changes"]),
                "unique_files": len(normalized_paths),
                "raw_bytes": sum(value["raw_size"] for value in entry_contents),
                "retained_bytes": sum(
                    value["retained_size"] for value in entry_contents
                ),
            },
            "operation_bindings": entry_operations,
            "filesystem_evidence_sha256": filesystem.canonical_sha256,
            "delta_partition_sha256": delta_partition["canonical_sha256"],
            "behavioral_filesystem_view_sha256": (
                integrity_evidence.filesystem_view.canonical_sha256
            ),
            "integrity_approved_run_evidence_sha256": (
                integrity_evidence.canonical_sha256
            ),
            "retained_plan_record": plan_record,
        }
        file_entries.append(
            {
                **entry_record,
                "canonical_sha256": _canonical_record_sha256(entry_record),
            }
        )

    file_ledger = {
        "schema_version": "complete-suite-retained-file-change-ledger-v1",
        "variant": variant,
        "case_id": case_id,
        "policy_version": file_changes.version,
        "case_policy_sha256": origin.rule_table_sha256,
        "raw_session_identity": raw_identity,
        "retained_session_identity": retained_identity,
        "raw_session_sha256": origin.raw_session_sha256,
        "retained_session_sha256": origin.retained_session_sha256,
        "sanitizer_ledger_sha256": origin.sanitizer_ledger_sha256,
        "filesystem_evidence": filesystem_wrapper,
        "raw_plan_sha256": raw_file_change_plan.canonical_sha256,
        "retained_plan_sha256": retained_file_change_plan.canonical_sha256,
        "topology_sha256": raw_file_change_plan.topology_sha256,
        "normalized_plan_sha256": file_changes.normalized_plan_sha256,
        "decision": decision_wrapper,
        "aggregate_transition": aggregate_transition,
        "content_inventory_sha256": file_changes.content_inventory_sha256,
        "delta_partition": delta_partition,
        "counts": counts,
        "contents": contents,
        "entries": file_entries,
        "record_fold_sha256": _record_fold_sha256(
            [entry["canonical_sha256"] for entry in file_entries]
        ),
        "operation_bindings": operation_bindings,
        "behavioral_filesystem_view": filesystem_view,
        "integrity_approved_run_evidence": integrity_wrapper,
        "retained_evidence_paths": dict(_RETAINED_OPERATION_PATHS),
    }
    artifacts = {
        "command-plans.jsonl": b"".join(line + b"\n" for line in command_lines),
        "command-plan-ledger.json": runner.canonical_bytes(command_ledger) + b"\n",
        "file-change-plans.jsonl": b"".join(
            runner.canonical_bytes(record) + b"\n"
            for record in file_plan_records
        ),
        "file-change-ledger.json": runner.canonical_bytes(file_ledger) + b"\n",
    }
    validate_retained_operation_artifacts(artifacts)
    return artifacts


def _decode_canonical_json_lines(payload: bytes, *, label: str) -> list[dict[str, Any]]:
    if (
        type(payload) is not bytes
        or len(payload) > MAX_RETAINED_TEXT_BYTES
        or b"\r" in payload
        or (payload and not payload.endswith(b"\n"))
    ):
        raise RuntimeError(f"{label} is invalid")
    records: list[dict[str, Any]] = []
    for line in payload.splitlines():
        if not line:
            raise RuntimeError(f"{label} is invalid")
        try:
            record = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_object_keys,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    ValueError("nonfinite JSON value")
                ),
            )
        except (TypeError, ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise RuntimeError(f"{label} is invalid") from exc
        if type(record) is not dict or runner.canonical_bytes(record) != line:
            raise RuntimeError(f"{label} is invalid")
        records.append(record)
    return records


def _validate_wrapper(value: object, *, label: str) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value) != {"record", "canonical_sha256"}
        or type(value.get("record")) is not dict
        or type(value.get("canonical_sha256")) is not str
        or _SHA256.fullmatch(value["canonical_sha256"]) is None
        or _canonical_record_sha256(value["record"])
        != value["canonical_sha256"]
    ):
        raise RuntimeError(f"{label} is invalid")
    return value


def _validate_paths_binding(value: object, *, label: str) -> list[str]:
    if (
        type(value) is not dict
        or set(value) != {"paths", "canonical_sha256"}
        or type(value.get("paths")) is not list
        or any(type(path) is not str or not path for path in value["paths"])
        or value.get("canonical_sha256")
        != _canonical_record_sha256({"paths": value["paths"]})
    ):
        raise RuntimeError(f"{label} is invalid")
    return list(value["paths"])


def _validate_retained_content_record(value: object) -> dict[str, Any]:
    if type(value) is not dict or type(value.get("retained_content_utf8")) is not str:
        raise RuntimeError("retained file-change content is invalid")
    retained_bytes = value["retained_content_utf8"].encode("utf-8")
    retained_sha256 = sha256(retained_bytes).hexdigest()
    post_state = value.get("post_state")
    entry = post_state.get("entry") if type(post_state) is dict else None
    if (
        value.get("retained_size") != len(retained_bytes)
        or value.get("retained_sha256") != retained_sha256
        or value.get("retained_content_sha256") != retained_sha256
        or type(entry) is not dict
        or entry.get("kind") != "file"
        or entry.get("size") != len(retained_bytes)
        or entry.get("sha256") != retained_sha256
    ):
        raise RuntimeError("retained file-change content is inconsistent")
    return {
        "normalized_path": value.get("normalized_path"),
        "raw_size": value.get("raw_size"),
        "raw_sha256": value.get("raw_sha256"),
        "retained_size": value.get("retained_size"),
        "retained_sha256": value.get("retained_sha256"),
        "retained_bytes_sha256": value.get("retained_content_sha256"),
        "raw_document_sha256": value.get("raw_document_sha256"),
        "retained_document_sha256": value.get("retained_document_sha256"),
        "sanitizer_record_sha256": value.get("sanitizer_record_sha256"),
        "role_validation_sha256": value.get("role_validation_sha256"),
    }


def validate_retained_operation_artifacts(
    artifacts: Mapping[str, bytes],
) -> None:
    """Validate detached canonical operation artifacts and their hash graph."""

    import complete_suite_command_plan as command_plan
    import complete_suite_file_change_policy as file_policy

    if (
        type(artifacts) is not dict
        or tuple(artifacts) != _OPERATION_ARTIFACT_NAMES
        or any(type(value) is not bytes for value in artifacts.values())
    ):
        raise RuntimeError("retained operation artifacts are invalid")
    command_lines = _decode_canonical_json_lines(
        artifacts["command-plans.jsonl"],
        label="retained command plans",
    )
    file_lines = _decode_canonical_json_lines(
        artifacts["file-change-plans.jsonl"],
        label="retained file-change plans",
    )
    command_ledger = _decode_canonical_json_bytes(
        artifacts["command-plan-ledger.json"],
        label="retained command-plan ledger",
    )
    file_ledger = _decode_canonical_json_bytes(
        artifacts["file-change-ledger.json"],
        label="retained file-change ledger",
    )
    if file_policy.validate_retained_file_change_ledger_bytes(
        artifacts["file-change-ledger.json"],
        expected_sha256=sha256(
            artifacts["file-change-ledger.json"]
        ).hexdigest(),
    ) != file_ledger:
        raise RuntimeError("retained file-change ledger is invalid")
    command_fields = {
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
    if (
        set(command_ledger) != command_fields
        or command_ledger.get("schema_version")
        != "complete-suite-retained-command-plan-ledger-v1"
        or command_ledger.get("variant") not in {"baseline", "suite-enabled"}
        or type(command_ledger.get("case_id")) is not str
        or not command_ledger["case_id"]
        or type(command_ledger.get("session_id")) is not str
        or not command_ledger["session_id"]
        or type(command_ledger.get("records")) is not list
        or command_ledger.get("retained_evidence_paths")
        != _RETAINED_OPERATION_PATHS
        or len(command_lines) != len(command_ledger["records"])
        or not command_lines
    ):
        raise RuntimeError("retained command-plan ledger is invalid")
    filesystem_wrapper = _validate_wrapper(
        command_ledger["filesystem_evidence"],
        label="retained filesystem evidence",
    )
    session_wrapper = _validate_wrapper(
        command_ledger["session_evidence"],
        label="retained session evidence",
    )
    session_record = session_wrapper["record"]
    if (
        session_record.get("session_id") != command_ledger["session_id"]
        or session_record.get("raw_session_identity")
        != command_ledger["raw_session_identity"]
        or session_record.get("retained_session_identity")
        != command_ledger["retained_session_identity"]
        or session_record.get("raw_bytes_consumed")
        != command_ledger["raw_bytes_consumed"]
        or session_record.get("retained_bytes_consumed")
        != command_ledger["retained_bytes_consumed"]
    ):
        raise RuntimeError("retained session evidence is inconsistent")
    command_record_fields = {
        "command_index",
        "plan_line_ordinal",
        "plan_utf8_bytes",
        "plan_sha256",
        "decoder_schema_version",
        "policy",
        "raw_capture",
        "retained_capture",
        "command_evidence",
        "operational_document_count",
        "retained_results",
        "canonical_sha256",
    }
    command_hashes: list[str] = []
    for index, (line, record) in enumerate(
        zip(command_lines, command_ledger["records"], strict=True)
    ):
        if (
            type(record) is not dict
            or set(record) != command_record_fields
            or record.get("command_index") != index
            or record.get("plan_line_ordinal") != index
            or record.get("plan_utf8_bytes") != len(
                runner.canonical_bytes(line)
            )
            or record.get("plan_sha256")
            != sha256(runner.canonical_bytes(line)).hexdigest()
            or record.get("decoder_schema_version")
            != command_plan._DECODER_SCHEMA_VERSION
            or type(record.get("retained_results")) is not list
            or record.get("operational_document_count")
            != len(record["retained_results"])
        ):
            raise RuntimeError("retained command-plan record is invalid")
        line_bytes = runner.canonical_bytes(line)
        command_plan.validate_retained_command_plan_bytes(
            line_bytes,
            expected_sha256=record["plan_sha256"],
        )
        _validate_wrapper(record["policy"], label="retained command policy")
        evidence = _validate_wrapper(
            record["command_evidence"],
            label="retained command evidence",
        )
        if (
            evidence["record"].get("command_index") != index
            or evidence["record"].get("plan_sha256") != record["plan_sha256"]
        ):
            raise RuntimeError("retained command evidence is inconsistent")
        policy = record["policy"]
        policy_record = policy["record"]
        if (
            policy_record.get("plan_sha256") != record["plan_sha256"]
            or policy_record.get("record_class")
            != evidence["record"].get("record_class")
            or policy["canonical_sha256"]
            != evidence["record"].get("decision_sha256")
            or line.get("namespace_manifest_sha256")
            != evidence["record"].get("namespace_manifest_sha256")
        ):
            raise RuntimeError("retained command policy is inconsistent")

        def capture_is_valid(
            capture: object,
            *,
            domain: str,
            expected_identity: object,
            expected_output: object,
        ) -> bool:
            if (
                type(capture) is not dict
                or set(capture)
                != {
                    "domain",
                    "session_identity",
                    "started_event_ordinal",
                    "completed_event_ordinal",
                    "event_id",
                    "event_span",
                    "output_field_span",
                    "output",
                    "exit_code",
                }
                or capture.get("domain") != domain
                or capture.get("session_identity") != expected_identity
                or capture.get("started_event_ordinal")
                != evidence["record"].get("started_event_ordinal")
                or capture.get("completed_event_ordinal")
                != evidence["record"].get("completed_event_ordinal")
                or capture.get("event_id") != evidence["record"].get("event_id")
                or capture.get("output") != expected_output
                or type(capture.get("exit_code")) is not int
            ):
                return False
            event_span = capture.get("event_span")
            field_span = capture.get("output_field_span")
            if (
                type(event_span) is not dict
                or set(event_span) != {"start", "end"}
                or type(field_span) is not dict
                or set(field_span) != {
                    "start",
                    "end",
                    "utf8_bytes",
                    "sha256",
                }
                or any(
                    type(value) is not int or value < 0
                    for value in (*event_span.values(), *field_span.values())
                    if not isinstance(value, str)
                )
                or event_span["end"] <= event_span["start"]
                or field_span["start"] < event_span["start"]
                or field_span["end"] <= field_span["start"]
                or field_span["end"] > event_span["end"]
                or field_span["utf8_bytes"]
                != field_span["end"] - field_span["start"]
                or type(field_span["sha256"]) is not str
                or _SHA256.fullmatch(field_span["sha256"]) is None
            ):
                return False
            return True

        raw_capture = record["raw_capture"]
        retained_capture = record["retained_capture"]
        if (
            not capture_is_valid(
                raw_capture,
                domain="raw",
                expected_identity=command_ledger["raw_session_identity"],
                expected_output=evidence["record"].get("raw_output"),
            )
            or not capture_is_valid(
                retained_capture,
                domain="retained",
                expected_identity=command_ledger[
                    "retained_session_identity"
                ],
                expected_output=evidence["record"].get("retained_output"),
            )
            or raw_capture["exit_code"] != retained_capture["exit_code"]
        ):
            raise RuntimeError("retained command capture is inconsistent")
        for result in record["retained_results"]:
            if (
                type(result) is not dict
                or set(result)
                != {
                    "result",
                    "retained_document_utf8",
                    "retained_document_utf8_bytes",
                    "retained_document_sha256",
                    "canonical_sha256",
                }
                or type(result.get("result")) is not dict
                or type(result.get("retained_document_utf8")) is not str
            ):
                raise RuntimeError("retained command result is invalid")
            result_bytes = result["retained_document_utf8"].encode("utf-8")
            result_without_hash = {
                name: value
                for name, value in result.items()
                if name != "canonical_sha256"
            }
            if (
                result.get("retained_document_utf8_bytes") != len(result_bytes)
                or result.get("retained_document_sha256")
                != sha256(result_bytes).hexdigest()
                or result["result"].get("retained_document_sha256")
                != result["retained_document_sha256"]
                or result.get("canonical_sha256")
                != _canonical_record_sha256(result_without_hash)
            ):
                raise RuntimeError("retained command result is inconsistent")
            if result["result"].get("exit_code") != retained_capture["exit_code"]:
                raise RuntimeError("retained command result is inconsistent")
        if [
            result["result"] for result in record["retained_results"]
        ] != evidence["record"].get("results"):
            raise RuntimeError("retained command results are inconsistent")
        record_without_hash = {
            name: value for name, value in record.items() if name != "canonical_sha256"
        }
        if record.get("canonical_sha256") != _canonical_record_sha256(
            record_without_hash
        ):
            raise RuntimeError("retained command-plan record hash is invalid")
        command_hashes.append(record["canonical_sha256"])
    if (
        command_ledger.get("record_fold_sha256")
        != _record_fold_sha256(command_hashes)
        or session_record.get("commands")
        != [
            {
                **record["command_evidence"]["record"],
                "canonical_sha256": record["command_evidence"][
                    "canonical_sha256"
                ],
            }
            for record in command_ledger["records"]
        ]
    ):
        raise RuntimeError("retained command-plan fold is invalid")

    file_fields = {
        "schema_version",
        "variant",
        "case_id",
        "policy_version",
        "case_policy_sha256",
        "raw_session_identity",
        "retained_session_identity",
        "raw_session_sha256",
        "retained_session_sha256",
        "sanitizer_ledger_sha256",
        "filesystem_evidence",
        "raw_plan_sha256",
        "retained_plan_sha256",
        "topology_sha256",
        "normalized_plan_sha256",
        "decision",
        "aggregate_transition",
        "content_inventory_sha256",
        "delta_partition",
        "counts",
        "contents",
        "entries",
        "record_fold_sha256",
        "operation_bindings",
        "behavioral_filesystem_view",
        "integrity_approved_run_evidence",
        "retained_evidence_paths",
    }
    if (
        set(file_ledger) != file_fields
        or file_ledger.get("schema_version")
        != "complete-suite-retained-file-change-ledger-v1"
        or file_ledger.get("variant") != command_ledger["variant"]
        or file_ledger.get("case_id") != command_ledger["case_id"]
        or file_ledger.get("raw_session_identity")
        != command_ledger["raw_session_identity"]
        or file_ledger.get("retained_session_identity")
        != command_ledger["retained_session_identity"]
        or file_ledger.get("raw_session_sha256")
        != command_ledger["raw_session_sha256"]
        or file_ledger.get("retained_session_sha256")
        != command_ledger["retained_session_sha256"]
        or file_ledger.get("filesystem_evidence") != filesystem_wrapper
        or file_ledger.get("retained_evidence_paths")
        != _RETAINED_OPERATION_PATHS
        or type(file_ledger.get("entries")) is not list
        or len(file_ledger["entries"]) != len(file_lines)
        or type(file_ledger.get("counts")) is not dict
        or file_ledger["counts"].get("lifecycles") != len(file_lines)
    ):
        raise RuntimeError("retained file-change ledger is invalid")
    decision_wrapper = _validate_wrapper(
        file_ledger["decision"],
        label="retained file-change decision",
    )
    view_wrapper = _validate_wrapper(
        file_ledger["behavioral_filesystem_view"],
        label="retained behavioral filesystem view",
    )
    operation_wrappers = file_ledger.get("operation_bindings", [])
    if type(operation_wrappers) is not list:
        raise RuntimeError("retained operation bindings are invalid")
    for binding in operation_wrappers:
        _validate_wrapper(binding, label="retained operation binding")

    decision_record = decision_wrapper["record"]
    contents = file_ledger.get("contents")
    if type(contents) is not list:
        raise RuntimeError("retained file-change contents are invalid")
    inventory_records = [
        _validate_retained_content_record(content) for content in contents
    ]
    content_paths = [record["normalized_path"] for record in inventory_records]
    if (
        any(type(path) is not str or not path for path in content_paths)
        or content_paths != sorted(content_paths, key=str.casefold)
        or len({path.casefold() for path in content_paths}) != len(content_paths)
        or file_ledger.get("content_inventory_sha256")
        != _canonical_record_sha256({"contents": inventory_records})
    ):
        raise RuntimeError("retained file-change content inventory is invalid")
    decision_content_projection = [
        {
            "normalized_path": content.get("normalized_path"),
            "raw_size": content.get("raw_size"),
            "raw_sha256": content.get("raw_sha256"),
            "retained_size": content.get("retained_size"),
            "retained_sha256": content.get("retained_sha256"),
            "retained_document_sha256": content.get(
                "retained_document_sha256"
            ),
            "raw_document_sha256": content.get("raw_document_sha256"),
            "sanitizer_record_sha256": content.get(
                "sanitizer_record_sha256"
            ),
            "role_validation_sha256": content.get("role_validation_sha256"),
        }
        for content in contents
    ]
    if decision_record.get("contents") != decision_content_projection:
        raise RuntimeError("retained file-change decision content is inconsistent")

    delta = file_ledger.get("delta_partition")
    if type(delta) is not dict or set(delta) != {
        "created",
        "changed",
        "removed",
        "implicit_ancestors",
        "unique_final_paths",
        "canonical_sha256",
    }:
        raise RuntimeError("retained file-change delta partition is invalid")
    delta_without_hash = {
        name: value for name, value in delta.items() if name != "canonical_sha256"
    }
    if delta.get("canonical_sha256") != _canonical_record_sha256(
        delta_without_hash
    ):
        raise RuntimeError("retained file-change delta partition is invalid")
    created_paths = _validate_paths_binding(
        delta["created"], label="retained created paths"
    )
    changed_paths = _validate_paths_binding(
        delta["changed"], label="retained changed paths"
    )
    removed_paths = _validate_paths_binding(
        delta["removed"], label="retained removed paths"
    )
    implicit_paths = _validate_paths_binding(
        delta["implicit_ancestors"], label="retained implicit ancestors"
    )
    unique_paths = _validate_paths_binding(
        delta["unique_final_paths"], label="retained unique final paths"
    )
    filesystem_record = filesystem_wrapper["record"]
    if (
        created_paths != filesystem_record.get("created_paths")
        or changed_paths != filesystem_record.get("changed_paths")
        or removed_paths != filesystem_record.get("removed_paths")
        or implicit_paths != decision_record.get("implicit_ancestor_paths")
        or unique_paths != decision_record.get("unique_final_paths")
        or unique_paths != content_paths
    ):
        raise RuntimeError("retained file-change delta partition is inconsistent")

    flattened_changes: list[dict[str, Any]] = []
    for lifecycle_index, line in enumerate(file_lines):
        raw_domain = line.get("raw")
        retained_domain = line.get("retained")
        if (
            type(raw_domain) is not dict
            or type(retained_domain) is not dict
            or raw_domain.get("changes") != retained_domain.get("changes")
        ):
            raise RuntimeError("retained file-change topology is invalid")
        topology = {
            "lifecycle_index": lifecycle_index,
            "event_id": line.get("event_id"),
            "started_event_ordinal": line.get("started_event_ordinal"),
            "completed_event_ordinal": line.get("completed_event_ordinal"),
            "terminal_status": line.get("terminal_status"),
            "changes": retained_domain["changes"],
        }
        if line.get("topology_sha256") != _canonical_record_sha256(topology):
            raise RuntimeError("retained file-change topology is invalid")
        for change in retained_domain["changes"]:
            flattened_changes.append(
                {
                    "lifecycle_index": lifecycle_index,
                    "event_id": line.get("event_id"),
                    "started_event_ordinal": line.get(
                        "started_event_ordinal"
                    ),
                    "completed_event_ordinal": line.get(
                        "completed_event_ordinal"
                    ),
                    "change_ordinal": change.get("change_ordinal"),
                    "normalized_path": change.get("normalized_path"),
                    "kind": change.get("kind"),
                }
            )
    global_topology = {
        "version": "complete-suite-file-change-plan-v1",
        "lifecycles": len(file_lines),
        "transition_entries": len(flattened_changes),
        "changes": flattened_changes,
    }
    decision_change_projection = [
        {
            "started_event_ordinal": change["started_event_ordinal"],
            "completed_event_ordinal": change["completed_event_ordinal"],
            "event_id": change["event_id"],
            "change_ordinal": change["change_ordinal"],
            "normalized_path": change["normalized_path"],
            "kind": change["kind"],
        }
        for change in flattened_changes
    ]
    observed_decision_changes = [
        {name: change.get(name) for name in projection}
        for change, projection in zip(
            decision_record.get("changes", []),
            decision_change_projection,
            strict=True,
        )
    ] if len(decision_record.get("changes", [])) == len(
        decision_change_projection
    ) else []
    if (
        file_ledger.get("topology_sha256")
        != _canonical_record_sha256(global_topology)
        or observed_decision_changes != decision_change_projection
        or file_ledger.get("policy_version") != decision_record.get("version")
        or file_ledger.get("variant") != decision_record.get("variant")
        or file_ledger.get("case_id") != decision_record.get("case_id")
        or file_ledger.get("normalized_plan_sha256")
        != decision_record.get("normalized_plan_sha256")
        or file_ledger.get("content_inventory_sha256")
        != decision_record.get("content_inventory_sha256")
    ):
        raise RuntimeError("retained file-change decision is inconsistent")

    aggregate = file_ledger.get("aggregate_transition")
    expected_aggregate = {
        "normalized_plan_sha256": decision_record.get(
            "normalized_plan_sha256"
        ),
        "aggregate_transition_sha256": decision_record.get(
            "aggregate_transition_sha256"
        ),
        "created_paths_sha256": delta["created"]["canonical_sha256"],
        "changed_paths_sha256": delta["changed"]["canonical_sha256"],
        "removed_paths_sha256": delta["removed"]["canonical_sha256"],
    }
    counts = file_ledger["counts"]
    if (
        aggregate != expected_aggregate
        or counts.get("transition_entries") != len(flattened_changes)
        or counts.get("transition_entries")
        != decision_record.get("transition_entries")
        or counts.get("unique_files") != len(contents)
        or counts.get("raw_bytes")
        != decision_record.get("raw_content_bytes")
        or counts.get("retained_bytes")
        != decision_record.get("retained_content_bytes")
        or counts.get("raw_bytes")
        != sum(content["raw_size"] for content in contents)
        or counts.get("retained_bytes")
        != sum(content["retained_size"] for content in contents)
        or counts.get("combined_bytes")
        != counts.get("raw_bytes") + counts.get("retained_bytes")
        or counts.get("operational_documents")
        != sum(
            record["operational_document_count"]
            for record in command_ledger["records"]
        )
    ):
        raise RuntimeError("retained file-change counts are inconsistent")
    integrity = file_ledger.get("integrity_approved_run_evidence")
    if (
        type(integrity) is not dict
        or set(integrity) != {
            "record",
            "canonical_utf8_bytes",
            "canonical_sha256",
        }
        or type(integrity.get("record")) is not dict
    ):
        raise RuntimeError("retained integrity-approved evidence is invalid")
    integrity_bytes = runner.canonical_bytes(integrity["record"])
    if (
        integrity.get("canonical_utf8_bytes") != len(integrity_bytes)
        or integrity.get("canonical_sha256")
        != sha256(integrity_bytes).hexdigest()
        or integrity["record"].get("commands_sha256")
        != session_wrapper["canonical_sha256"]
        or integrity["record"].get("file_changes_sha256")
        != file_ledger["decision"]["canonical_sha256"]
        or integrity["record"].get("operation_bindings")
        != [
            {
                **binding["record"],
                "canonical_sha256": binding["canonical_sha256"],
            }
            for binding in operation_wrappers
        ]
        or integrity["record"].get("filesystem_view")
        != {
            **view_wrapper["record"],
            "canonical_sha256": view_wrapper["canonical_sha256"],
        }
    ):
        raise RuntimeError("retained integrity-approved evidence is inconsistent")
    file_hashes: list[str] = []
    for index, (line, entry) in enumerate(
        zip(file_lines, file_ledger["entries"], strict=True)
    ):
        line_bytes = runner.canonical_bytes(line)
        if (
            type(entry) is not dict
            or entry.get("entry_index") != index
            or entry.get("plan_line_ordinal") != index
            or entry.get("plan_sha256") != sha256(line_bytes).hexdigest()
            or entry.get("retained_plan_record") != line
            or line.get("lifecycle_index") != index
            or line.get("canonical_sha256")
            != _canonical_record_sha256(
                {name: value for name, value in line.items() if name != "canonical_sha256"}
            )
        ):
            raise RuntimeError("retained file-change entry is invalid")
        normalized_paths = {
            change["normalized_path"]
            for change in line["retained"]["changes"]
        }
        expected_entry_contents = [
            content
            for content in contents
            if content["normalized_path"] in normalized_paths
        ]
        expected_entry_bindings = [
            binding
            for binding in operation_wrappers
            if binding["record"]["normalized_path"] in normalized_paths
        ]
        source_item = {
            "lifecycle_index": line["lifecycle_index"],
            "event_id": line["event_id"],
            "started_event_ordinal": line["started_event_ordinal"],
            "completed_event_ordinal": line["completed_event_ordinal"],
            "terminal_status": line["terminal_status"],
            "topology_sha256": line["topology_sha256"],
        }
        expected_policy = {
            "version": file_ledger["policy_version"],
            "variant": file_ledger["variant"],
            "case_id": file_ledger["case_id"],
            "case_policy_sha256": file_ledger["case_policy_sha256"],
            "normalized_plan_sha256": file_ledger["normalized_plan_sha256"],
            "decision_sha256": decision_wrapper["canonical_sha256"],
        }
        expected_entry_counts = {
            "transition_entries": len(line["retained"]["changes"]),
            "unique_files": len(normalized_paths),
            "raw_bytes": sum(
                content["raw_size"] for content in expected_entry_contents
            ),
            "retained_bytes": sum(
                content["retained_size"] for content in expected_entry_contents
            ),
        }
        if (
            entry.get("source_item") != source_item
            or entry.get("raw_plan") != line["raw"]
            or entry.get("retained_plan") != line["retained"]
            or entry.get("policy") != expected_policy
            or entry.get("raw_session_identity")
            != file_ledger["raw_session_identity"]
            or entry.get("retained_session_identity")
            != file_ledger["retained_session_identity"]
            or entry.get("sanitizer_ledger_sha256")
            != file_ledger["sanitizer_ledger_sha256"]
            or entry.get("aggregate_transition") != aggregate
            or entry.get("contents") != expected_entry_contents
            or entry.get("counts") != expected_entry_counts
            or entry.get("operation_bindings") != expected_entry_bindings
            or entry.get("filesystem_evidence_sha256")
            != filesystem_wrapper["canonical_sha256"]
            or entry.get("delta_partition_sha256")
            != delta["canonical_sha256"]
            or entry.get("behavioral_filesystem_view_sha256")
            != view_wrapper["canonical_sha256"]
            or entry.get("integrity_approved_run_evidence_sha256")
            != integrity["canonical_sha256"]
        ):
            raise RuntimeError("retained file-change entry is inconsistent")
        entry_without_hash = {
            name: value for name, value in entry.items() if name != "canonical_sha256"
        }
        if entry.get("canonical_sha256") != _canonical_record_sha256(
            entry_without_hash
        ):
            raise RuntimeError("retained file-change entry hash is invalid")
        file_hashes.append(entry["canonical_sha256"])
    if file_ledger.get("record_fold_sha256") != _record_fold_sha256(file_hashes):
        raise RuntimeError("retained file-change fold is invalid")


def _canonical_operation_artifacts(
    artifacts: Mapping[str, bytes],
) -> dict[str, bytes]:
    validate_retained_operation_artifacts(artifacts)
    command_lines = _decode_canonical_json_lines(
        artifacts["command-plans.jsonl"],
        label="retained command plans",
    )
    file_lines = _decode_canonical_json_lines(
        artifacts["file-change-plans.jsonl"],
        label="retained file-change plans",
    )
    command_ledger = _decode_canonical_json_bytes(
        artifacts["command-plan-ledger.json"],
        label="retained command-plan ledger",
    )
    file_ledger = _decode_canonical_json_bytes(
        artifacts["file-change-ledger.json"],
        label="retained file-change ledger",
    )
    regenerated = {
        "command-plans.jsonl": b"".join(
            runner.canonical_bytes(record) + b"\n" for record in command_lines
        ),
        "command-plan-ledger.json": runner.canonical_bytes(command_ledger) + b"\n",
        "file-change-plans.jsonl": b"".join(
            runner.canonical_bytes(record) + b"\n" for record in file_lines
        ),
        "file-change-ledger.json": runner.canonical_bytes(file_ledger) + b"\n",
    }
    if regenerated != artifacts:
        raise RuntimeError("retained operation artifacts are not reproducible")
    return regenerated


def _operation_provenance_manifest(
    artifacts: Mapping[str, bytes],
) -> dict[str, Any]:
    canonical = _canonical_operation_artifacts(artifacts)
    record = {
        "schema_version": "complete-suite-retained-operation-provenance-v1",
        "artifact_names": list(_OPERATION_ARTIFACT_NAMES),
        "artifacts": {
            name: {
                "size": len(canonical[name]),
                "sha256": sha256(canonical[name]).hexdigest(),
            }
            for name in sorted(_OPERATION_ARTIFACT_NAMES)
        },
    }
    return {**record, "canonical_sha256": _canonical_record_sha256(record)}


def _validate_operation_provenance_manifest(
    value: object,
    artifacts: Mapping[str, bytes],
) -> None:
    if (
        type(value) is not dict
        or set(value)
        != {
            "schema_version",
            "artifact_names",
            "artifacts",
            "canonical_sha256",
        }
        or value.get("schema_version")
        != "complete-suite-retained-operation-provenance-v1"
        or value.get("artifact_names") != list(_OPERATION_ARTIFACT_NAMES)
        or type(value.get("artifacts")) is not dict
        or tuple(value["artifacts"]) != tuple(sorted(_OPERATION_ARTIFACT_NAMES))
    ):
        raise RuntimeError("retained operation provenance manifest is invalid")
    record = {
        name: item for name, item in value.items() if name != "canonical_sha256"
    }
    if value.get("canonical_sha256") != _canonical_record_sha256(record):
        raise RuntimeError("retained operation provenance manifest is invalid")
    expected = _operation_provenance_manifest(artifacts)
    if value != expected:
        raise RuntimeError("retained operation provenance manifest mismatch")


def _publish_operation_artifacts(
    retained_run: Path,
    artifacts: Mapping[str, bytes],
) -> dict[str, Any]:
    canonical = _canonical_operation_artifacts(artifacts)
    command_ledger = _decode_canonical_json_bytes(
        canonical["command-plan-ledger.json"],
        label="retained command-plan ledger",
    )
    file_ledger = _decode_canonical_json_bytes(
        canonical["file-change-ledger.json"],
        label="retained file-change ledger",
    )
    if (
        command_ledger.get("case_id") != file_ledger.get("case_id")
        or command_ledger.get("variant") != file_ledger.get("variant")
    ):
        raise RuntimeError("retained operation artifact run binding mismatch")
    for name in _OPERATION_ARTIFACT_NAMES:
        destination = retained_run / name
        try:
            _require_plain_ancestry(retained_run.resolve(strict=True), destination)
            with destination.open("xb") as stream:
                stream.write(canonical[name])
                stream.flush()
                os.fsync(stream.fileno())
        except (OSError, ValueError) as exc:
            raise RuntimeError("retained operation artifact publication failed") from exc
    observed = {
        name: _read_text_artifact(retained_run / name)
        for name in _OPERATION_ARTIFACT_NAMES
    }
    if observed != canonical:
        raise RuntimeError("retained operation artifact publication mismatch")
    return _operation_provenance_manifest(observed)


def _read_operation_artifacts(root: Path) -> dict[str, bytes]:
    return {
        name: _read_text_artifact(root / name)
        for name in _OPERATION_ARTIFACT_NAMES
    }


def _derived_records(root: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    operation_presence = tuple(
        (root / name).exists() or (root / name).is_symlink()
        for name in _OPERATION_ARTIFACT_NAMES
    )
    if any(operation_presence) and not all(operation_presence):
        raise RuntimeError("retained operation artifact inventory is incomplete")
    selected = (
        _DERIVED_FILE_NAMES
        if all(operation_presence)
        else _LEGACY_DERIVED_FILE_NAMES
    )
    for name in sorted(selected):
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
    *,
    operation_artifacts: Mapping[str, bytes] | None = None,
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
    raw_operation_presence = tuple(
        (raw / name).exists() or (raw / name).is_symlink()
        for name in _OPERATION_ARTIFACT_NAMES
    )
    if any(raw_operation_presence) and not all(raw_operation_presence):
        raise RuntimeError("operation provenance source inventory is incomplete")
    canonical_operation_artifacts: dict[str, bytes] | None = None
    if operation_artifacts is None:
        if any(raw_operation_presence):
            raise RuntimeError("operation provenance source was not bound")
        selected_raw_files = _LEGACY_RAW_RUN_FILES
    else:
        if type(operation_artifacts) is not dict:
            raise RuntimeError("retained operation artifacts are invalid")
        if not all(raw_operation_presence):
            raise RuntimeError("operation provenance source unavailable")
        canonical_operation_artifacts = _canonical_operation_artifacts(
            operation_artifacts
        )
        if _read_operation_artifacts(raw) != canonical_operation_artifacts:
            raise RuntimeError("operation provenance source mismatch")
        command_ledger = _decode_canonical_json_bytes(
            canonical_operation_artifacts["command-plan-ledger.json"],
            label="retained command-plan ledger",
        )
        if (
            command_ledger.get("case_id") != item.case_id
            or command_ledger.get("variant") != item.variant
        ):
            raise RuntimeError("retained operation artifact run binding mismatch")
        selected_raw_files = _RAW_RUN_FILES
    entries: list[dict[str, Any]] = []
    for raw_name, retained_name, allow_redaction, optional in selected_raw_files:
        source = raw / raw_name
        if optional and not source.exists() and not source.is_symlink():
            continue
        if retained_name is None:
            entries.append(retain_digest_artifact(source, raw_root=case_root))
        else:
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
    operation_provenance: dict[str, Any] | None = None
    if canonical_operation_artifacts is not None:
        operation_provenance = _publish_operation_artifacts(
            retained_run,
            canonical_operation_artifacts,
        )
    ledger = {
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
    if operation_provenance is not None:
        ledger["operation_provenance"] = operation_provenance
    return ledger


def replay_run_evidence(
    case_root: Path,
    retained_run: Path,
    ledger: Mapping[str, Any],
) -> None:
    ledger_fields = set(ledger) if isinstance(ledger, Mapping) else set()
    if (
        not isinstance(ledger, Mapping)
        or ledger_fields not in (_LEDGER_FIELDS, _LEGACY_LEDGER_FIELDS)
        or ledger.get("schema_version") != "1.0"
        or not isinstance(ledger.get("ordinal"), int)
        or isinstance(ledger.get("ordinal"), bool)
        or ledger["ordinal"] < 1
        or ledger.get("variant") not in {"baseline", "suite-enabled"}
        or not isinstance(ledger.get("case_id"), str)
        or not ledger["case_id"]
        or not isinstance(ledger.get("evaluable"), bool)
        or (
            ledger_fields == _LEDGER_FIELDS
            and type(ledger.get("operation_provenance")) is not dict
        )
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
    operation_provenance = (
        ledger.get("operation_provenance")
        if ledger_fields == _LEDGER_FIELDS
        else None
    )
    post_run = _load_json_object(raw_root / "post-run-state.json")
    expected_raw, expected_retained, expected_order = _expected_ledger_paths(
        case_root,
        post_run,
        include_operation_provenance=operation_provenance is not None,
    )
    observed_raw, observed_retained, observed_order = _ledger_paths(files)
    expected_derived_names = tuple(
        sorted(
            _DERIVED_FILE_NAMES
            if operation_provenance is not None
            else _LEGACY_DERIVED_FILE_NAMES
        )
    )
    declared_derived = ledger.get("derived_files")
    if (
        type(declared_derived) is not dict
        or tuple(declared_derived) != expected_derived_names
        or observed_raw != expected_raw
        or observed_retained != expected_retained
        or observed_order != expected_order
        or _raw_run_file_paths(raw_root)
        != {path for path in expected_raw if path.startswith("raw/")}
        or _retained_file_paths(retained_run)
        != expected_retained | set(expected_derived_names)
    ):
        raise RuntimeError("run evidence ledger is incomplete")
    replay_artifact_ledger(case_root, retained_run, files)
    observed_derived = _derived_records(retained_run)
    if observed_derived != ledger.get("derived_files"):
        raise RuntimeError("retained derived evidence mismatch")
    operation_artifacts: dict[str, bytes] | None = None
    if operation_provenance is not None:
        operation_artifacts = _read_operation_artifacts(retained_run)
        try:
            if _read_operation_artifacts(raw_root) != operation_artifacts:
                raise RuntimeError("operation provenance source mismatch")
            _validate_operation_provenance_manifest(
                operation_provenance,
                operation_artifacts,
            )
        except RuntimeError as exc:
            raise RuntimeError("retained derived evidence mismatch") from exc
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
        if operation_artifacts is not None:
            regenerated = _canonical_operation_artifacts(operation_artifacts)
            for name in _OPERATION_ARTIFACT_NAMES:
                (scratch / name).write_bytes(regenerated[name])
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


def _validate_import_authorization_arguments(
    campaign: Mapping[str, Any],
    raw_root: Path,
    retained_root: Path,
    *,
    approved_campaign_sha256: str,
    import_authorization: Path | None,
    expected_import_authorization_sha256: str | None,
    expected_import_authorization_prompt_sha256: str | None,
    sealed_campaign_audit: Path | None,
    expected_sealed_campaign_audit_sha256: str | None,
    approved_envelope_sha256: str | None,
    provider_approval_sha256: str | None,
    expected_raw_seal_sha256: str | None,
    expected_raw_inventory_sha256: str | None,
    expected_retained_root: Path | None,
    require_retained_root_absent: bool = True,
) -> ImportAuthorization | None:
    arguments = (
        import_authorization,
        expected_import_authorization_sha256,
        expected_import_authorization_prompt_sha256,
        sealed_campaign_audit,
        expected_sealed_campaign_audit_sha256,
        approved_envelope_sha256,
        provider_approval_sha256,
        expected_raw_seal_sha256,
        expected_raw_inventory_sha256,
        expected_retained_root,
    )
    required = campaign.get("campaign_id") == "2026-08-21-proposed6"
    if all(value is None for value in arguments):
        if required:
            raise RuntimeError("import authorization is required")
        return None
    if any(value is None for value in arguments):
        raise RuntimeError("import authorization arguments are incomplete")
    if (
        not isinstance(import_authorization, Path)
        or not isinstance(sealed_campaign_audit, Path)
        or not isinstance(expected_retained_root, Path)
        or type(expected_import_authorization_sha256) is not str
        or type(expected_import_authorization_prompt_sha256) is not str
        or type(expected_sealed_campaign_audit_sha256) is not str
        or type(approved_envelope_sha256) is not str
        or type(provider_approval_sha256) is not str
        or type(expected_raw_seal_sha256) is not str
        or type(expected_raw_inventory_sha256) is not str
    ):
        raise RuntimeError("import authorization arguments are invalid")
    proposed = campaign.get("proposed_approval")
    isolation = proposed.get("isolation") if isinstance(proposed, dict) else None
    campaign_retained_root = _safe_relative_path(
        isolation.get("retained_root") if isinstance(isolation, dict) else None
    )
    if expected_retained_root.is_absolute():
        authorization_retained_root = expected_retained_root
        retained_root_matches = (
            not required
            and expected_retained_root.absolute() == retained_root.absolute()
        )
    else:
        try:
            expected_relative_root = _safe_relative_path(
                expected_retained_root.as_posix()
            )
        except RuntimeError:
            expected_relative_root = PurePosixPath(".")
        authorization_retained_root = expected_retained_root
        retained_root_matches = expected_relative_root == campaign_retained_root
    if (
        not retained_root_matches
        or approved_envelope_sha256 != runner.approval_envelope_sha256(campaign)
    ):
        raise RuntimeError("import authorization arguments are invalid")
    if require_retained_root_absent and (
        retained_root.exists() or retained_root.is_symlink()
    ):
        raise RuntimeError("retained root state does not match authorization")
    authorization_path = _canonical_plain_file(
        str(import_authorization),
        label="import authorization record",
    )
    sealed_audit_path = _canonical_plain_file(
        str(sealed_campaign_audit),
        label="sealed campaign audit",
    )
    authorization = _validate_import_authorization(
        _read_text_artifact(authorization_path),
        expected_record_sha256=expected_import_authorization_sha256,
        expected_import_authorization_prompt_sha256=(
            expected_import_authorization_prompt_sha256
        ),
        expected_campaign_sha256=approved_campaign_sha256,
        expected_envelope_sha256=approved_envelope_sha256,
        expected_provider_approval_sha256=provider_approval_sha256,
        expected_sealed_campaign_audit_sha256=(
            expected_sealed_campaign_audit_sha256
        ),
        expected_raw_root=raw_root,
        expected_raw_seal_sha256=expected_raw_seal_sha256,
        expected_raw_inventory_sha256=expected_raw_inventory_sha256,
        expected_retained_root=authorization_retained_root,
        require_retained_root_absent=False,
    )
    if (
        authorization_path.parent
        != authorization.authorization_prompt_record.parent
        or sealed_audit_path != authorization.sealed_campaign_audit_record
    ):
        raise RuntimeError("import authorization arguments are invalid")
    return authorization


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
    import_authorization: Path | None = None,
    expected_import_authorization_sha256: str | None = None,
    expected_import_authorization_prompt_sha256: str | None = None,
    sealed_campaign_audit: Path | None = None,
    expected_sealed_campaign_audit_sha256: str | None = None,
    approved_envelope_sha256: str | None = None,
    provider_approval_sha256: str | None = None,
    expected_raw_seal_sha256: str | None = None,
    expected_raw_inventory_sha256: str | None = None,
    expected_retained_root: Path | None = None,
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
    _authorization = _validate_import_authorization_arguments(
        campaign,
        raw_root,
        retained_root,
        approved_campaign_sha256=approved_campaign_sha256,
        import_authorization=import_authorization,
        expected_import_authorization_sha256=(
            expected_import_authorization_sha256
        ),
        expected_import_authorization_prompt_sha256=(
            expected_import_authorization_prompt_sha256
        ),
        sealed_campaign_audit=sealed_campaign_audit,
        expected_sealed_campaign_audit_sha256=(
            expected_sealed_campaign_audit_sha256
        ),
        approved_envelope_sha256=approved_envelope_sha256,
        provider_approval_sha256=provider_approval_sha256,
        expected_raw_seal_sha256=expected_raw_seal_sha256,
        expected_raw_inventory_sha256=expected_raw_inventory_sha256,
        expected_retained_root=expected_retained_root,
    )
    if _authorization is not None:
        raise RuntimeError("operation provenance source unavailable")
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
        if _authorization is not None:
            import_ledger["import_authorization_sha256"] = (
                _authorization.canonical_sha256
            )
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
    import_authorization: Path | None = None,
    expected_import_authorization_sha256: str | None = None,
    expected_import_authorization_prompt_sha256: str | None = None,
    sealed_campaign_audit: Path | None = None,
    expected_sealed_campaign_audit_sha256: str | None = None,
    approved_envelope_sha256: str | None = None,
    provider_approval_sha256: str | None = None,
    expected_raw_seal_sha256: str | None = None,
    expected_raw_inventory_sha256: str | None = None,
    expected_retained_root: Path | None = None,
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
    authorization = _validate_import_authorization_arguments(
        campaign,
        raw_root,
        retained_root,
        approved_campaign_sha256=approved_campaign_sha256,
        import_authorization=import_authorization,
        expected_import_authorization_sha256=(
            expected_import_authorization_sha256
        ),
        expected_import_authorization_prompt_sha256=(
            expected_import_authorization_prompt_sha256
        ),
        sealed_campaign_audit=sealed_campaign_audit,
        expected_sealed_campaign_audit_sha256=(
            expected_sealed_campaign_audit_sha256
        ),
        approved_envelope_sha256=approved_envelope_sha256,
        provider_approval_sha256=provider_approval_sha256,
        expected_raw_seal_sha256=expected_raw_seal_sha256,
        expected_raw_inventory_sha256=expected_raw_inventory_sha256,
        expected_retained_root=expected_retained_root,
        require_retained_root_absent=False,
    )
    if authorization is not None and replay_factory is not None:
        raise RuntimeError(
            "authorized operation provenance replay callback is unavailable"
        )
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
    if authorization is not None:
        expected_fields.add("import_authorization_sha256")
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
        or (
            authorization is not None
            and import_ledger.get("import_authorization_sha256")
            != authorization.canonical_sha256
        )
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
    campaign_raw, campaign_retained, _campaign_order = _ledger_paths(
        campaign_files
    )
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
    parser.add_argument("--expected-retained-root", type=Path, required=True)
    parser.add_argument("--import-authorization", type=Path, required=True)
    parser.add_argument(
        "--expected-import-authorization-sha256",
        required=True,
    )
    parser.add_argument(
        "--expected-import-authorization-prompt-sha256",
        required=True,
    )
    parser.add_argument("--sealed-campaign-audit", type=Path, required=True)
    parser.add_argument(
        "--expected-sealed-campaign-audit-sha256",
        required=True,
    )
    parser.add_argument("--approved-campaign-sha256", required=True)
    parser.add_argument("--approved-envelope-sha256", required=True)
    parser.add_argument("--provider-approval-sha256", required=True)
    parser.add_argument("--expected-raw-seal-sha256", required=True)
    parser.add_argument("--expected-raw-inventory-sha256", required=True)
    args = parser.parse_args()
    import_campaign(
        args.raw_root,
        expected_retained_root=args.expected_retained_root,
        import_authorization=args.import_authorization,
        expected_import_authorization_sha256=(
            args.expected_import_authorization_sha256
        ),
        expected_import_authorization_prompt_sha256=(
            args.expected_import_authorization_prompt_sha256
        ),
        sealed_campaign_audit=args.sealed_campaign_audit,
        expected_sealed_campaign_audit_sha256=(
            args.expected_sealed_campaign_audit_sha256
        ),
        approved_campaign_sha256=args.approved_campaign_sha256,
        approved_envelope_sha256=args.approved_envelope_sha256,
        provider_approval_sha256=args.provider_approval_sha256,
        expected_raw_seal_sha256=args.expected_raw_seal_sha256,
        expected_raw_inventory_sha256=args.expected_raw_inventory_sha256,
    )


if __name__ == "__main__":
    main()
