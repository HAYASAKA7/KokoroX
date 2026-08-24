from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import codecs
import json
import math
import os
from pathlib import Path, PurePath, PureWindowsPath
import re
import stat
import threading
from typing import Any, BinaryIO, Literal, NoReturn
import weakref

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    import msvcrt

from complete_suite_command_plan import (
    BoundCommandPlan,
    _authenticate_bound_namespaces,
    _observe_namespace_root,
    _windows_path_parts_equal,
)
if os.name == "nt":
    from complete_suite_command_plan import (
        _ByHandleFileInformation,
        _FileAttributeTagInformation,
        _IoStatusBlock,
        _ObjectAttributes,
        _UnicodeString,
    )
from complete_suite_command_policy import (
    ApprovedOperation,
    BoundFilesystemEvidence,
    CommandPolicyDecision,
    _CLI_ACTIONS,
    _authenticate_command_policy_decision,
    _authenticated_command_policy_filesystem,
)


COMMAND_CAPTURE_INVALID = "COMMAND_CAPTURE_INVALID"
COMMAND_OUTPUT_LIMIT_EXCEEDED = "COMMAND_OUTPUT_LIMIT_EXCEEDED"
COMMAND_JSON_INVALID = "COMMAND_JSON_INVALID"
COMMAND_JSON_COUNT_MISMATCH = "COMMAND_JSON_COUNT_MISMATCH"
COMMAND_RESULT_INCONSISTENT = "COMMAND_RESULT_INCONSISTENT"

_SESSION_EVIDENCE_VERSION = "complete-suite-session-command-evidence-v1"
_READ_CHUNK_BYTES = 64 * 1024
_DOCUMENT_LIMIT_BYTES = 4 * 1024 * 1024
_SESSION_OUTPUT_LIMIT_BYTES = 64 * 1024 * 1024
_DOCUMENTS_PER_COMMAND_LIMIT = 128
_METADATA_STRING_LIMIT_BYTES = 2 * 1024 * 1024
_JSON_DEPTH_LIMIT = 128
_JSON_CONTAINER_ITEM_LIMIT = 4096
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SEMANTIC_ID = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
_SLUG_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_REGISTRY_IDENTITY = re.compile(
    r"[a-z0-9]+(?:-[a-z0-9]+)*/"
    r"[a-z0-9]+(?:-[a-z0-9]+)*/"
    + _SEMVER.pattern
)
_STABLE_ID = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_REGISTRY_ARTIFACT_ID = re.compile(r"[a-z0-9][a-z0-9._/-]{0,191}")
_REGISTRY_RELATIVE_PATH = re.compile(
    r"(?!/)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*//)"
    r"[a-z0-9][a-z0-9._/-]*"
)
_DECLARED_OUTPUT_ACTIONS = frozenset(
    {
        ("pack", "export"),
        ("pack", "test"),
        ("pack", "soft-eval"),
        ("pack", "promote"),
        ("pack", "publication-check"),
        ("state", "export"),
    }
)
_RESULT_PATH_OUTPUT_ACTIONS = _DECLARED_OUTPUT_ACTIONS - {("state", "export")}
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
_FROZEN_SCHEMA_SHA256 = {
    "character-build-request": "1cc10c813db024c75e1d3ec121cff2eef0f8833c5b359085f8e0b0c2a15b25bd",
    "build-validation-report": "b9377fd1b976ee711501ab16ca82ad4e17e3fe4a0108da39e8e10b59430930f0",
    "research-request": "bd63f8a94251f5c73ba7add737b3576f2361a2a99b7ea7036081d896241fa8bb",
    "research-validation-report": "1225fec1b0ca3abf6eaf1177cc585bb4c2ba479f31b92830daa04686f032e413",
    "research-conflict": "71aa00af7deab3a1bd656747dfaa2ff653f94c943a183983ea145ef216f2bf33",
    "character-default-config": "702c114dc3b5a01395d2ee93ab9000d778ac160b4b886f85e0491f3e9204b884",
    "session-manifest": "12a4414a48be4b80f4691e6a9f82bed76610c5a84898459a1f9fe801cb83bdf9",
    "persistence-consent": "bf5644d75a15748a524a6b0052edaceceb0537a3aca95e6b8c05c17ca7758b3d",
    "relationship-state": "74185dca91692efcf23aed84e95a3794637764ea4670bd4e7823aa35be646f6d",
    "memory-reference": "0654a1267ea916d29666a4046636593ece0dd9dcac78b83267156e048afd9a5e",
    "language-policy": "5c9cb46463bb23e8eceef0a92a22f67a9d87d3b491f3d76b1156b29776c1af33",
    "render-plan": "2d0cde54679013bddcfe004730dc686249a8eb98fed33b8d2df2928a928c5188",
    "validation-result": "93f875a69cb1f1f19ff723d3783ac6768e53ffecd3ca89a9b1fb4cd79e56f475",
}
_FROZEN_SCHEMA_BYTES_LIMIT = 64 * 1024
_FROZEN_SCHEMA_VALIDATORS: dict[str, Draft202012Validator] = {}
_FROZEN_SCHEMA_LOCK = threading.Lock()
_JSON_WHITESPACE = frozenset((0x20, 0x09, 0x0A, 0x0D))
_COMMAND_ITEM_FIELDS = frozenset(
    {"aggregated_output", "command", "exit_code", "id", "status", "type"}
)
_RESEARCH_BUNDLE_SUMMARY_FIELDS = frozenset(
    {
        "activation_allowed",
        "artifact_id",
        "authoring_allowed",
        "blocking_reasons",
        "build_status",
        "bundle_hash",
        "conflicts",
        "coverage_summary",
        "limitations",
        "request_hash",
        "validation_report_hash",
        "visibility",
        "workspace_hash",
    }
)
_SUCCESS_TOP_LEVEL_KEYS: dict[
    tuple[str, ...], tuple[frozenset[str], ...]
] = {
    ("pack", "validate"): (
        frozenset({"ok", "artifact_id", "character_id", "character_version"}),
    ),
    ("pack", "compile"): (
        frozenset(
            {
                "ok",
                "path",
                "character_id",
                "character_version",
                "source_hash",
                "artifact_id",
            }
        ),
    ),
    ("pack", "install"): (
        frozenset({"ok", "dry_run", "plan", "activates_character"}),
    ),
    ("pack", "list"): (
        frozenset(
            {"ok", "scope", "workspace_id", "installed", "activates_character"}
        ),
    ),
    ("pack", "export"): (
        frozenset({"ok", "path", "archive_sha256", "visibility"}),
    ),
    ("pack", "test"): (
        frozenset(
            {
                "ok",
                "path",
                "artifact_id",
                "passed",
                "source_hash",
                "compiled_hash",
                "report_hash",
            }
        ),
    ),
    ("pack", "soft-eval"): (
        frozenset({"ok", "path", "artifact_id", "passed", "report_hash"}),
    ),
    ("pack", "promote"): (
        frozenset(
            {
                "ok",
                "path",
                "bundle_path",
                "artifact_id",
                "promotion_id",
                "to_status",
                "activation_allowed",
                "record_hash",
            }
        ),
    ),
    ("pack", "publication-check"): (
        frozenset(
            {
                "ok",
                "path",
                "artifact_id",
                "ready_for_private_export",
                "ready_for_publication",
                "blockers",
                "report_hash",
            }
        ),
    ),
    ("character", "request", "validate"): (frozenset({"ok", "request"}),),
    ("character", "draft", "validate"): (
        frozenset({"ok", "valid", "validation_report"}),
    ),
    ("character", "draft", "compile"): (
        frozenset(
            {
                "ok",
                "path",
                "artifact_id",
                "request_hash",
                "source_pack_hash",
                "validation_report_hash",
                "build_status",
                "visibility",
                "activation_allowed",
                "validation_report",
            }
        ),
    ),
    ("research", "request", "validate"): (frozenset({"ok", "request"}),),
    ("research", "workspace", "validate"): (
        frozenset({"ok", "valid", "workspace_hash", "validation_report"}),
    ),
    ("research", "bundle", "compile"): (
        frozenset({"ok", "path"}) | _RESEARCH_BUNDLE_SUMMARY_FIELDS,
    ),
    ("research", "bundle", "validate"): (
        frozenset({"ok", "valid"}) | _RESEARCH_BUNDLE_SUMMARY_FIELDS,
    ),
    ("config", "default", "set"): (
        frozenset({"ok", "default", "activates_character"}),
    ),
    ("config", "default", "show"): (
        frozenset({"ok", "default", "activates_character"}),
    ),
    ("session", "start"): (frozenset({"ok", "session"}),),
    ("session", "show"): (frozenset({"ok", "session"}),),
    ("consent", "show"): (frozenset({"ok", "consent"}),),
    ("state", "preview"): (frozenset({"ok", "state"}),),
    ("state", "apply"): (frozenset({"ok", "state"}),),
    ("state", "export"): (frozenset({"ok", "export_sha256"}),),
    ("memory", "add"): (frozenset({"ok", "memory_reference"}),),
    ("memory", "list"): (frozenset({"ok", "memory_references"}),),
    ("memory", "remove"): (
        frozenset({"ok", "dry_run", "plan"}),
        frozenset({"ok", "dry_run", "result"}),
    ),
    ("policy", "compile"): (frozenset({"ok", "policy"}),),
    ("runtime", "context"): (frozenset({"ok", "context"}),),
    ("runtime", "plan"): (frozenset({"ok", "plan"}),),
    ("runtime", "validate"): (frozenset({"ok", "validation"}),),
}
_SUCCESS_FIELD_TYPES: dict[
    tuple[str, ...], dict[str, tuple[type, ...]]
] = {
    ("pack", "validate"): {
        "ok": (bool,), "artifact_id": (str,), "character_id": (str,),
        "character_version": (str,),
    },
    ("pack", "compile"): {
        "ok": (bool,), "path": (str,), "character_id": (str,),
        "character_version": (str,), "source_hash": (str,),
        "artifact_id": (str,),
    },
    ("pack", "install"): {
        "ok": (bool,), "dry_run": (bool,), "plan": (dict,),
        "activates_character": (bool,),
    },
    ("pack", "list"): {
        "ok": (bool,), "scope": (str,), "workspace_id": (str, type(None)),
        "installed": (list,), "activates_character": (bool,),
    },
    ("pack", "export"): {
        "ok": (bool,), "path": (str,), "archive_sha256": (str,),
        "visibility": (str,),
    },
    ("pack", "test"): {
        "ok": (bool,), "path": (str,), "artifact_id": (str,),
        "passed": (bool,), "source_hash": (str,),
        "compiled_hash": (str, type(None)),
        "report_hash": (str,),
    },
    ("pack", "soft-eval"): {
        "ok": (bool,), "path": (str,), "artifact_id": (str,),
        "passed": (bool,), "report_hash": (str,),
    },
    ("pack", "promote"): {
        "ok": (bool,), "path": (str,), "bundle_path": (str,),
        "artifact_id": (str,), "promotion_id": (str,), "to_status": (str,),
        "activation_allowed": (bool,), "record_hash": (str,),
    },
    ("pack", "publication-check"): {
        "ok": (bool,), "path": (str,), "artifact_id": (str,),
        "ready_for_private_export": (bool,), "ready_for_publication": (bool,),
        "blockers": (list,), "report_hash": (str,),
    },
    ("character", "request", "validate"): {"ok": (bool,), "request": (dict,)},
    ("character", "draft", "validate"): {
        "ok": (bool,), "valid": (bool,), "validation_report": (dict,),
    },
    ("character", "draft", "compile"): {
        "ok": (bool,), "path": (str,), "artifact_id": (str,),
        "request_hash": (str,), "source_pack_hash": (str,),
        "validation_report_hash": (str,), "build_status": (str,),
        "visibility": (str,), "activation_allowed": (bool,),
        "validation_report": (dict,),
    },
    ("research", "request", "validate"): {"ok": (bool,), "request": (dict,)},
    ("research", "workspace", "validate"): {
        "ok": (bool,), "valid": (bool,), "workspace_hash": (str,),
        "validation_report": (dict,),
    },
    ("research", "bundle", "compile"): {
        "ok": (bool,), "path": (str,), "artifact_id": (str,),
        "request_hash": (str,), "workspace_hash": (str,),
        "validation_report_hash": (str,), "bundle_hash": (str,),
        "build_status": (str,), "visibility": (str,),
        "activation_allowed": (bool,), "authoring_allowed": (bool,),
        "coverage_summary": (dict,), "conflicts": (list,),
        "limitations": (list,), "blocking_reasons": (list,),
    },
    ("research", "bundle", "validate"): {
        "ok": (bool,), "valid": (bool,), "artifact_id": (str,),
        "request_hash": (str,), "workspace_hash": (str,),
        "validation_report_hash": (str,), "bundle_hash": (str,),
        "build_status": (str,), "visibility": (str,),
        "activation_allowed": (bool,), "authoring_allowed": (bool,),
        "coverage_summary": (dict,), "conflicts": (list,),
        "limitations": (list,), "blocking_reasons": (list,),
    },
    ("config", "default", "set"): {
        "ok": (bool,), "default": (dict,), "activates_character": (bool,),
    },
    ("config", "default", "show"): {
        "ok": (bool,), "default": (dict,), "activates_character": (bool,),
    },
    ("session", "start"): {"ok": (bool,), "session": (dict,)},
    ("session", "show"): {"ok": (bool,), "session": (dict, type(None))},
    ("consent", "show"): {"ok": (bool,), "consent": (dict, type(None))},
    ("state", "preview"): {"ok": (bool,), "state": (dict,)},
    ("state", "apply"): {"ok": (bool,), "state": (dict,)},
    ("state", "export"): {"ok": (bool,), "export_sha256": (str,)},
    ("memory", "add"): {"ok": (bool,), "memory_reference": (dict,)},
    ("memory", "list"): {"ok": (bool,), "memory_references": (list,)},
    ("memory", "remove"): {
        "ok": (bool,), "dry_run": (bool,), "plan": (dict,), "result": (dict,),
    },
    ("policy", "compile"): {"ok": (bool,), "policy": (dict,)},
    ("runtime", "context"): {"ok": (bool,), "context": (dict,)},
    ("runtime", "plan"): {"ok": (bool,), "plan": (dict,)},
    ("runtime", "validate"): {"ok": (bool,), "validation": (dict,)},
}


@dataclass(frozen=True, slots=True, repr=False)
class _SelectedValueProvenance:
    selector: tuple[str, ...]
    raw_sha256: str
    retained_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.selector) is not tuple
            or self.selector not in ((), ("policy",), ("plan",))
            or not _is_sha256(self.raw_sha256)
            or not _is_sha256(self.retained_sha256)
        ):
            _reject(COMMAND_CAPTURE_INVALID)


@dataclass(frozen=True, slots=True, repr=False)
class _OperationProvenance:
    command_index: int
    operation_index: int
    argv: tuple[str, ...]
    category: Literal["kokoro_cli", "read_only", "silent_directory"]
    outcome: Literal["success", "expected_refusal", "none"]
    declared_output_paths: tuple[str, ...]
    selected_values: tuple[_SelectedValueProvenance, ...]

    def __post_init__(self) -> None:
        if (
            type(self.command_index) is not int
            or self.command_index < 0
            or type(self.operation_index) is not int
            or self.operation_index < 0
            or type(self.argv) is not tuple
            or not self.argv
            or any(type(value) is not str for value in self.argv)
            or self.category not in ("kokoro_cli", "read_only", "silent_directory")
            or self.outcome not in ("success", "expected_refusal", "none")
            or type(self.declared_output_paths) is not tuple
            or any(type(value) is not str for value in self.declared_output_paths)
            or type(self.selected_values) is not tuple
            or any(
                type(value) is not _SelectedValueProvenance
                for value in self.selected_values
            )
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        for value in self.selected_values:
            value.__post_init__()
        selectors = tuple(value.selector for value in self.selected_values)
        if (
            selectors != tuple(sorted(set(selectors)))
            or (self.outcome == "none") != (not self.selected_values)
            or (
                self.category != "kokoro_cli"
                and (self.outcome != "none" or self.declared_output_paths)
            )
        ):
            _reject(COMMAND_CAPTURE_INVALID)


@dataclass(frozen=True, slots=True, repr=False)
class _SessionOperationProvenance:
    raw_session_sha256: str
    retained_session_sha256: str
    filesystem: BoundFilesystemEvidence | None
    operations: tuple[_OperationProvenance, ...]

    def __post_init__(self) -> None:
        if (
            not _is_sha256(self.raw_session_sha256)
            or not _is_sha256(self.retained_session_sha256)
            or (
                self.filesystem is not None
                and type(self.filesystem) is not BoundFilesystemEvidence
            )
            or type(self.operations) is not tuple
            or not self.operations
            or any(
                type(value) is not _OperationProvenance
                for value in self.operations
            )
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        for operation in self.operations:
            operation.__post_init__()
        indices = tuple(
            (operation.command_index, operation.operation_index)
            for operation in self.operations
        )
        if indices != tuple(sorted(set(indices))):
            _reject(COMMAND_CAPTURE_INVALID)


_BOUND_SESSION_REGISTRY_LOCK = threading.Lock()
_BOUND_SESSION_REGISTRY: dict[
    int,
    tuple[
        weakref.ReferenceType[BoundSessionCommandEvidence],
        str,
        _SessionOperationProvenance,
    ],
] = {}


def _reject(code: str) -> NoReturn:
    raise RuntimeError(code)


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (OverflowError, TypeError, ValueError, UnicodeError):
        _reject(COMMAND_JSON_INVALID)


def _identity_record(identity: SessionFileIdentity) -> dict[str, object]:
    return {
        "relative_path": identity.relative_path,
        "device": identity.device,
        "inode": identity.inode,
        "size": identity.size,
        "modified_ns": identity.modified_ns,
        "file_type": identity.file_type,
        "link_count": identity.link_count,
    }


def _detach_session_identity(identity: SessionFileIdentity) -> SessionFileIdentity:
    if type(identity) is not SessionFileIdentity:
        _reject(COMMAND_CAPTURE_INVALID)
    identity.__post_init__()
    return SessionFileIdentity(**_identity_record(identity))


@dataclass(frozen=True)
class SessionFileIdentity:
    relative_path: str
    device: int
    inode: int
    size: int
    modified_ns: int
    file_type: int
    link_count: int

    def __post_init__(self) -> None:
        integers = (
            self.device,
            self.inode,
            self.size,
            self.modified_ns,
            self.file_type,
            self.link_count,
        )
        if (
            type(self.relative_path) is not str
            or not self.relative_path
            or "\x00" in self.relative_path
            or "\r" in self.relative_path
            or "\n" in self.relative_path
            or any(type(value) is not int or value < 0 for value in integers)
            or self.file_type == 0
            or self.link_count == 0
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        path = PureWindowsPath(self.relative_path)
        invalid_part = any(
            not part
            or part.endswith((" ", "."))
            or any(character in '<>:"|?*' or ord(character) < 32 for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
            for part in path.parts
        )
        if (
            path.is_absolute()
            or path.anchor
            or not path.parts
            or any(part in ("", ".", "..") for part in path.parts)
            or invalid_part
            or str(path) != self.relative_path
        ):
            _reject(COMMAND_CAPTURE_INVALID)


@dataclass(frozen=True)
class CompletedOutputCapture:
    domain: Literal["raw", "retained"]
    session_root: Path
    session_path: Path
    started_event_ordinal: int
    completed_event_ordinal: int
    event_id: str
    event_start: int
    event_end: int
    output_field_start: int
    output_field_end: int
    exit_code: int
    output_field_utf8_bytes: int
    output_field_sha256: str
    output_utf8_bytes: int
    output_sha256: str
    session_identity: SessionFileIdentity

    def __post_init__(self) -> None:
        offsets = (
            self.started_event_ordinal,
            self.completed_event_ordinal,
            self.event_start,
            self.event_end,
            self.output_field_start,
            self.output_field_end,
            self.output_field_utf8_bytes,
            self.output_utf8_bytes,
        )
        if (
            self.domain not in ("raw", "retained")
            or not isinstance(self.session_root, Path)
            or not isinstance(self.session_path, Path)
            or any(type(value) is not int or value < 0 for value in offsets)
            or self.completed_event_ordinal <= self.started_event_ordinal
            or self.event_end <= self.event_start
            or self.output_field_start < self.event_start
            or self.output_field_end <= self.output_field_start
            or self.output_field_end > self.event_end
            or type(self.event_id) is not str
            or _EVENT_ID.fullmatch(self.event_id) is None
            or type(self.exit_code) is not int
            or not _is_sha256(self.output_field_sha256)
            or not _is_sha256(self.output_sha256)
            or type(self.session_identity) is not SessionFileIdentity
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        self.session_identity.__post_init__()


@dataclass(frozen=True, repr=False)
class BoundCliResult:
    operation_index: int
    argv: tuple[str, ...]
    raw_document_sha256: str
    retained_document_bytes: bytes
    retained_document_sha256: str
    exit_code: int
    outcome: Literal["success", "expected_refusal"]

    def __post_init__(self) -> None:
        if (
            type(self.operation_index) is not int
            or self.operation_index < 0
            or type(self.argv) is not tuple
            or not self.argv
            or any(type(value) is not str for value in self.argv)
            or not _is_sha256(self.raw_document_sha256)
            or type(self.retained_document_bytes) is not bytes
            or not self.retained_document_bytes.endswith(b"\n")
            or len(self.retained_document_bytes) > _DOCUMENT_LIMIT_BYTES + 1
            or not _is_sha256(self.retained_document_sha256)
            or sha256(self.retained_document_bytes).hexdigest()
            != self.retained_document_sha256
            or type(self.exit_code) is not int
            or self.outcome not in ("success", "expected_refusal")
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        value = _decode_document(self.retained_document_bytes[:-1])
        if _canonical_json_bytes(value) + b"\n" != self.retained_document_bytes:
            _reject(COMMAND_CAPTURE_INVALID)

    def decoded_retained_document(self) -> dict[str, Any]:
        """Return a fresh detached view of the retained canonical result."""

        return _decode_document(bytes(self.retained_document_bytes[:-1]))


@dataclass(frozen=True)
class CommandCapturePair:
    command_index: int
    plan: BoundCommandPlan
    decision: CommandPolicyDecision
    raw_capture: CompletedOutputCapture
    retained_capture: CompletedOutputCapture

    def __post_init__(self) -> None:
        if (
            type(self.command_index) is not int
            or self.command_index < 0
            or type(self.plan) is not BoundCommandPlan
            or type(self.decision) is not CommandPolicyDecision
            or type(self.raw_capture) is not CompletedOutputCapture
            or type(self.retained_capture) is not CompletedOutputCapture
            or self.raw_capture.domain != "raw"
            or self.retained_capture.domain != "retained"
        ):
            _reject(COMMAND_CAPTURE_INVALID)


@dataclass(frozen=True, repr=False)
class BoundCommandEvidence:
    command_index: int
    event_id: str
    started_event_ordinal: int
    completed_event_ordinal: int
    plan_sha256: str
    namespace_manifest_sha256: str
    decision_sha256: str
    record_class: str
    raw_output_utf8_bytes: int
    raw_output_sha256: str
    retained_output_utf8_bytes: int
    retained_output_sha256: str
    results: tuple[BoundCliResult, ...]
    canonical_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.command_index) is not int
            or self.command_index < 0
            or type(self.event_id) is not str
            or _EVENT_ID.fullmatch(self.event_id) is None
            or type(self.started_event_ordinal) is not int
            or self.started_event_ordinal < 0
            or type(self.completed_event_ordinal) is not int
            or self.completed_event_ordinal <= self.started_event_ordinal
            or any(
                not _is_sha256(value)
                for value in (
                    self.plan_sha256,
                    self.namespace_manifest_sha256,
                    self.decision_sha256,
                    self.raw_output_sha256,
                    self.retained_output_sha256,
                    self.canonical_sha256,
                )
            )
            or self.record_class
            not in ("operational_json", "read_only_pipeline", "help_discovery")
            or type(self.raw_output_utf8_bytes) is not int
            or self.raw_output_utf8_bytes < 0
            or type(self.retained_output_utf8_bytes) is not int
            or self.retained_output_utf8_bytes < 0
            or type(self.results) is not tuple
            or any(type(value) is not BoundCliResult for value in self.results)
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        for result in self.results:
            result.__post_init__()
        if tuple(result.operation_index for result in self.results) != tuple(
            sorted({result.operation_index for result in self.results})
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        if sha256(_canonical_json_bytes(_command_record(self))).hexdigest() != (
            self.canonical_sha256
        ):
            _reject(COMMAND_CAPTURE_INVALID)


@dataclass(frozen=True, repr=False)
class BoundSessionCommandEvidence:
    version: Literal["complete-suite-session-command-evidence-v1"]
    session_id: str
    raw_session_identity: SessionFileIdentity
    retained_session_identity: SessionFileIdentity
    commands: tuple[BoundCommandEvidence, ...]
    raw_bytes_consumed: int
    retained_bytes_consumed: int
    canonical_bytes: bytes
    canonical_sha256: str

    def __post_init__(self) -> None:
        if (
            self.version != _SESSION_EVIDENCE_VERSION
            or type(self.session_id) is not str
            or _SESSION_ID.fullmatch(self.session_id) is None
            or type(self.raw_session_identity) is not SessionFileIdentity
            or type(self.retained_session_identity) is not SessionFileIdentity
            or type(self.commands) is not tuple
            or not self.commands
            or any(type(value) is not BoundCommandEvidence for value in self.commands)
            or type(self.raw_bytes_consumed) is not int
            or not 0 <= self.raw_bytes_consumed <= _SESSION_OUTPUT_LIMIT_BYTES
            or type(self.retained_bytes_consumed) is not int
            or not 0 <= self.retained_bytes_consumed <= _SESSION_OUTPUT_LIMIT_BYTES
            or type(self.canonical_bytes) is not bytes
            or not _is_sha256(self.canonical_sha256)
            or sha256(self.canonical_bytes).hexdigest() != self.canonical_sha256
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        self.raw_session_identity.__post_init__()
        self.retained_session_identity.__post_init__()
        for command in self.commands:
            command.__post_init__()
        if tuple(command.command_index for command in self.commands) != tuple(
            range(len(self.commands))
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        if self.raw_bytes_consumed != sum(
            command.raw_output_utf8_bytes for command in self.commands
        ) or self.retained_bytes_consumed != sum(
            command.retained_output_utf8_bytes for command in self.commands
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        expected = _session_record(
            session_id=self.session_id,
            raw_identity=self.raw_session_identity,
            retained_identity=self.retained_session_identity,
            commands=self.commands,
            raw_bytes=self.raw_bytes_consumed,
            retained_bytes=self.retained_bytes_consumed,
        )
        if _canonical_json_bytes(expected) != self.canonical_bytes:
            _reject(COMMAND_CAPTURE_INVALID)


def _result_record(result: BoundCliResult) -> dict[str, object]:
    return {
        "operation_index": result.operation_index,
        "argv": list(result.argv),
        "raw_document_sha256": result.raw_document_sha256,
        "retained_document_sha256": result.retained_document_sha256,
        "exit_code": result.exit_code,
        "outcome": result.outcome,
    }


def _command_record(command: BoundCommandEvidence) -> dict[str, object]:
    return {
        "command_index": command.command_index,
        "event_id": command.event_id,
        "started_event_ordinal": command.started_event_ordinal,
        "completed_event_ordinal": command.completed_event_ordinal,
        "plan_sha256": command.plan_sha256,
        "namespace_manifest_sha256": command.namespace_manifest_sha256,
        "decision_sha256": command.decision_sha256,
        "record_class": command.record_class,
        "raw_output": {
            "utf8_bytes": command.raw_output_utf8_bytes,
            "sha256": command.raw_output_sha256,
        },
        "retained_output": {
            "utf8_bytes": command.retained_output_utf8_bytes,
            "sha256": command.retained_output_sha256,
        },
        "results": [_result_record(result) for result in command.results],
    }


def _session_record(
    *,
    session_id: str,
    raw_identity: SessionFileIdentity,
    retained_identity: SessionFileIdentity,
    commands: tuple[BoundCommandEvidence, ...],
    raw_bytes: int,
    retained_bytes: int,
) -> dict[str, object]:
    return {
        "version": _SESSION_EVIDENCE_VERSION,
        "session_id": session_id,
        "raw_session_identity": _identity_record(raw_identity),
        "retained_session_identity": _identity_record(retained_identity),
        "commands": [
            {**_command_record(command), "canonical_sha256": command.canonical_sha256}
            for command in commands
        ],
        "raw_bytes_consumed": raw_bytes,
        "retained_bytes_consumed": retained_bytes,
    }


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            _reject(COMMAND_JSON_INVALID)
        result[key] = value
    return result


def _decode_document(payload: bytes | bytearray) -> dict[str, Any]:
    if type(payload) not in (bytes, bytearray) or len(payload) > _DOCUMENT_LIMIT_BYTES:
        _reject(COMMAND_JSON_INVALID)
    try:
        text = payload.decode("utf-8", errors="strict")
        decoder = json.JSONDecoder(
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda _value: _reject(COMMAND_JSON_INVALID),
        )
        value, end = decoder.raw_decode(text)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        _reject(COMMAND_JSON_INVALID)
    if end != len(text) or type(value) is not dict:
        _reject(COMMAND_JSON_INVALID)
    return value


def _stat_has_reparse(value: os.stat_result) -> bool:
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_attribute) or bool(
        getattr(value, "st_reparse_tag", 0)
    )


def _stat_fingerprint(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(stat.S_IFMT(value.st_mode)),
        int(value.st_nlink),
        int(getattr(value, "st_file_attributes", 0)),
        int(getattr(value, "st_reparse_tag", 0)),
    )


def _frozen_schema_validator(name: str) -> Draft202012Validator:
    expected_sha256 = _FROZEN_SCHEMA_SHA256.get(name)
    if expected_sha256 is None:
        _reject(COMMAND_RESULT_INCONSISTENT)
    with _FROZEN_SCHEMA_LOCK:
        existing = _FROZEN_SCHEMA_VALIDATORS.get(name)
        if existing is not None:
            return existing
        path = Path(__file__).resolve().parents[2] / "schemas" / "v1" / f"{name}.schema.json"
        try:
            before = os.lstat(path)
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_ISLNK(before.st_mode)
                or _stat_has_reparse(before)
                or before.st_nlink != 1
                or before.st_size > _FROZEN_SCHEMA_BYTES_LIMIT
            ):
                _reject(COMMAND_RESULT_INCONSISTENT)
            with open(path, "rb") as stream:
                opened = os.fstat(stream.fileno())
                payload = stream.read(_FROZEN_SCHEMA_BYTES_LIMIT + 1)
                if stream.read(1):
                    _reject(COMMAND_RESULT_INCONSISTENT)
            after = os.lstat(path)
        except RuntimeError:
            raise
        except OSError:
            _reject(COMMAND_RESULT_INCONSISTENT)
        if (
            len(payload) > _FROZEN_SCHEMA_BYTES_LIMIT
            or _stat_fingerprint(before) != _stat_fingerprint(opened)
            or _stat_fingerprint(opened) != _stat_fingerprint(after)
            or sha256(payload).hexdigest() != expected_sha256
        ):
            _reject(COMMAND_RESULT_INCONSISTENT)
        try:
            schema = json.loads(
                payload.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=lambda _value: _reject(COMMAND_RESULT_INCONSISTENT),
            )
            if type(schema) is not dict:
                _reject(COMMAND_RESULT_INCONSISTENT)
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
        except RuntimeError:
            raise
        except (UnicodeError, json.JSONDecodeError, SchemaError, TypeError, ValueError):
            _reject(COMMAND_RESULT_INCONSISTENT)
        _FROZEN_SCHEMA_VALIDATORS[name] = validator
        return validator


def _validate_frozen_schema(name: str, value: object) -> None:
    try:
        if next(_frozen_schema_validator(name).iter_errors(value), None) is not None:
            _reject(COMMAND_RESULT_INCONSISTENT)
    except RuntimeError:
        raise
    except Exception:
        _reject(COMMAND_RESULT_INCONSISTENT)


def _session_identity_from_stat(
    relative_path: str,
    value: os.stat_result,
) -> SessionFileIdentity:
    return SessionFileIdentity(
        relative_path=relative_path,
        device=int(value.st_dev),
        inode=int(value.st_ino),
        size=int(value.st_size),
        modified_ns=int(value.st_mtime_ns),
        file_type=1 if os.name == "nt" else int(stat.S_IFMT(value.st_mode)),
        link_count=int(value.st_nlink),
    )


def _directory_chain(path: Path) -> tuple[tuple[str, tuple[int, ...]], ...]:
    if not isinstance(path, Path) or not path.is_absolute():
        _reject(COMMAND_CAPTURE_INVALID)
    parts = path.parts
    if not parts:
        _reject(COMMAND_CAPTURE_INVALID)
    current = Path(parts[0])
    result: list[tuple[str, tuple[int, ...]]] = []
    for part in parts[1:]:
        current /= part
        try:
            observed = os.lstat(current)
        except OSError:
            _reject(COMMAND_CAPTURE_INVALID)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or _stat_has_reparse(observed)
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        result.append((str(current), _stat_fingerprint(observed)))
    if not result:
        try:
            observed = os.lstat(current)
        except OSError:
            _reject(COMMAND_CAPTURE_INVALID)
        if not stat.S_ISDIR(observed.st_mode) or _stat_has_reparse(observed):
            _reject(COMMAND_CAPTURE_INVALID)
        result.append((str(current), _stat_fingerprint(observed)))
    return tuple(result)


def _observe_windows_directory(path: Path) -> tuple[object, ...] | None:
    if os.name != "nt":
        return None
    try:
        observed = _observe_namespace_root(str(path))
    except Exception:
        _reject(COMMAND_CAPTURE_INVALID)
    return observed


@dataclass(frozen=True)
class _WindowsHandleSnapshot:
    device: int
    inode: int
    size: int
    attributes: int
    reparse_tag: int
    link_count: int
    final_path: str

    def directory_identity(self) -> tuple[int, ...]:
        return (
            self.device,
            self.inode,
            1,
            self.reparse_tag,
            self.link_count,
        )


class _WindowsNativeApi:
    _FILE_READ_DATA = 0x00000001
    _FILE_READ_ATTRIBUTES = 0x00000080
    _FILE_TRAVERSE = 0x00000020
    _SYNCHRONIZE = 0x00100000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _OPEN_EXISTING = 3
    _FILE_OPEN = 1
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_DIRECTORY_FILE = 0x00000001
    _FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
    _FILE_NON_DIRECTORY_FILE = 0x00000040
    _FILE_OPEN_FOR_BACKUP_INTENT = 0x00004000
    _FILE_OPEN_REPARSE_POINT = 0x00200000
    _OBJ_DONT_REPARSE = 0x00001000
    _FILE_ATTRIBUTE_TAG_INFO = 9

    def __init__(self) -> None:
        if os.name != "nt":
            _reject(COMMAND_CAPTURE_INVALID)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        self._create_file = kernel32.CreateFileW
        self._create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        self._create_file.restype = wintypes.HANDLE
        self._nt_create_file = ntdll.NtCreateFile
        self._nt_create_file.argtypes = (
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            ctypes.POINTER(_ObjectAttributes),
            ctypes.POINTER(_IoStatusBlock),
            wintypes.LPVOID,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.LPVOID,
            wintypes.ULONG,
        )
        self._nt_create_file.restype = ctypes.c_long
        self._get_information = kernel32.GetFileInformationByHandle
        self._get_information.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(_ByHandleFileInformation),
        )
        self._get_information.restype = wintypes.BOOL
        self._get_information_ex = kernel32.GetFileInformationByHandleEx
        self._get_information_ex.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        self._get_information_ex.restype = wintypes.BOOL
        self._get_final_path = kernel32.GetFinalPathNameByHandleW
        self._get_final_path.argtypes = (
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        self._get_final_path.restype = wintypes.DWORD
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = (wintypes.HANDLE,)
        self._close_handle.restype = wintypes.BOOL
        self.invalid_handle = ctypes.c_void_p(-1).value

    def open_anchor(self, anchor: str) -> object:
        handle = self._create_file(
            anchor,
            self._FILE_READ_ATTRIBUTES | self._FILE_TRAVERSE,
            self._FILE_SHARE_READ | self._FILE_SHARE_WRITE | self._FILE_SHARE_DELETE,
            None,
            self._OPEN_EXISTING,
            self._FILE_FLAG_OPEN_REPARSE_POINT | self._FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if handle in (None, self.invalid_handle):
            _reject(COMMAND_CAPTURE_INVALID)
        return handle

    def open_relative(
        self,
        parent: object,
        component: str,
        *,
        directory: bool,
    ) -> object:
        try:
            encoded = component.encode("utf-16-le", errors="strict")
        except UnicodeEncodeError:
            _reject(COMMAND_CAPTURE_INVALID)
        if not encoded or len(encoded) > 65532 or "\\" in component or "/" in component:
            _reject(COMMAND_CAPTURE_INVALID)
        name_buffer = ctypes.create_unicode_buffer(component)
        unicode_name = _UnicodeString(
            length=len(encoded),
            maximum_length=len(encoded) + 2,
            buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
        )
        attributes = _ObjectAttributes(
            length=ctypes.sizeof(_ObjectAttributes),
            root_directory=parent,
            object_name=ctypes.pointer(unicode_name),
            attributes=self._OBJ_DONT_REPARSE,
            security_descriptor=None,
            security_quality_of_service=None,
        )
        io_status = _IoStatusBlock()
        handle = wintypes.HANDLE()
        desired = self._FILE_READ_ATTRIBUTES | self._SYNCHRONIZE
        options = self._FILE_SYNCHRONOUS_IO_NONALERT | self._FILE_OPEN_REPARSE_POINT
        if directory:
            desired |= self._FILE_TRAVERSE
            options |= self._FILE_DIRECTORY_FILE | self._FILE_OPEN_FOR_BACKUP_INTENT
        else:
            desired |= self._FILE_READ_DATA
            options |= self._FILE_NON_DIRECTORY_FILE
        status = self._nt_create_file(
            ctypes.byref(handle),
            desired,
            ctypes.byref(attributes),
            ctypes.byref(io_status),
            None,
            0,
            self._FILE_SHARE_READ | self._FILE_SHARE_WRITE | self._FILE_SHARE_DELETE,
            self._FILE_OPEN,
            options,
            None,
            0,
        )
        if status < 0 or handle.value in (None, self.invalid_handle):
            if handle.value not in (None, self.invalid_handle):
                self.close(handle)
            _reject(COMMAND_CAPTURE_INVALID)
        return handle

    def snapshot(self, handle: object, *, directory: bool) -> _WindowsHandleSnapshot:
        information = _ByHandleFileInformation()
        tag_information = _FileAttributeTagInformation()
        if not self._get_information(handle, ctypes.byref(information)):
            _reject(COMMAND_CAPTURE_INVALID)
        if not self._get_information_ex(
            handle,
            self._FILE_ATTRIBUTE_TAG_INFO,
            ctypes.byref(tag_information),
            ctypes.sizeof(tag_information),
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        attributes = int(information.file_attributes)
        tag_attributes = int(tag_information.file_attributes)
        is_directory = bool(attributes & self._FILE_ATTRIBUTE_DIRECTORY)
        if (
            is_directory is not directory
            or bool(tag_attributes & self._FILE_ATTRIBUTE_DIRECTORY) is not directory
            or attributes & self._FILE_ATTRIBUTE_REPARSE_POINT
            or tag_attributes & self._FILE_ATTRIBUTE_REPARSE_POINT
            or int(tag_information.reparse_tag) != 0
            or int(information.number_of_links) <= 0
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        final_size = self._get_final_path(handle, None, 0, 0)
        if final_size <= 0 or final_size > 32767:
            _reject(COMMAND_CAPTURE_INVALID)
        final_buffer = ctypes.create_unicode_buffer(final_size + 1)
        final_length = self._get_final_path(
            handle,
            final_buffer,
            len(final_buffer),
            0,
        )
        if final_length <= 0 or final_length >= len(final_buffer):
            _reject(COMMAND_CAPTURE_INVALID)
        final_path = final_buffer.value
        if final_path.startswith("\\\\?\\UNC\\"):
            final_path = "\\\\" + final_path[8:]
        elif final_path.startswith("\\\\?\\"):
            final_path = final_path[4:]
        return _WindowsHandleSnapshot(
            device=int(information.volume_serial_number),
            inode=(int(information.file_index_high) << 32)
            | int(information.file_index_low),
            size=(int(information.file_size_high) << 32)
            | int(information.file_size_low),
            attributes=attributes,
            reparse_tag=int(tag_information.reparse_tag),
            link_count=int(information.number_of_links),
            final_path=str(PureWindowsPath(final_path)),
        )

    def close(self, handle: object) -> bool:
        return bool(self._close_handle(handle))


class _HeldWindowsSessionFile:
    def __init__(
        self,
        *,
        root: Path,
        path: Path,
        root_observation: tuple[object, ...],
        parent_observation: tuple[object, ...],
    ) -> None:
        self.api = _WindowsNativeApi()
        self.handles: list[object] = []
        self.directory_snapshots: list[_WindowsHandleSnapshot] = []
        self.stream: BinaryIO | None = None
        self.final_snapshot: _WindowsHandleSnapshot | None = None
        self.closed = False
        self.root = root
        self.path = path
        self.root_observation = root_observation
        self.parent_observation = parent_observation
        try:
            parts = PureWindowsPath(path).parts
            root_parts = PureWindowsPath(root).parts
            parent_parts = PureWindowsPath(path.parent).parts
            if (
                not parts
                or not root_parts
                or len(root_parts) > len(parent_parts)
                or tuple(part.casefold() for part in parent_parts[: len(root_parts)])
                != tuple(part.casefold() for part in root_parts)
            ):
                _reject(COMMAND_CAPTURE_INVALID)
            anchor = self.api.open_anchor(PureWindowsPath(path).anchor)
            self.handles.append(anchor)
            self.directory_snapshots.append(
                self.api.snapshot(anchor, directory=True)
            )
            for component in parts[1:-1]:
                handle = self.api.open_relative(
                    self.handles[-1],
                    component,
                    directory=True,
                )
                self.handles.append(handle)
                self.directory_snapshots.append(
                    self.api.snapshot(handle, directory=True)
                )
            self._validate_observation_prefixes()
        except Exception:
            self.close()
            raise

    @staticmethod
    def _observation_identities(
        observation: tuple[object, ...],
    ) -> tuple[tuple[int, ...], ...]:
        if len(observation) != 4:
            _reject(COMMAND_CAPTURE_INVALID)
        root_identity = observation[1]
        ancestors = observation[2]
        try:
            identities = (*ancestors, root_identity)
            return tuple(
                (
                    identity.device,
                    identity.inode,
                    identity.file_type,
                    identity.reparse_tag,
                    identity.link_count,
                )
                for identity in identities
            )
        except (AttributeError, TypeError):
            _reject(COMMAND_CAPTURE_INVALID)

    def _validate_observation_prefixes(self) -> None:
        native = tuple(
            snapshot.directory_identity() for snapshot in self.directory_snapshots
        )
        expected_parent = self._observation_identities(self.parent_observation)
        expected_root = self._observation_identities(self.root_observation)
        if native != expected_parent or native[: len(expected_root)] != expected_root:
            _reject(COMMAND_CAPTURE_INVALID)

    def validate_lexical_namespace(self) -> None:
        self._validate_observation_prefixes()
        if (
            _observe_windows_directory(self.root) != self.root_observation
            or _observe_windows_directory(self.path.parent)
            != self.parent_observation
        ):
            _reject(COMMAND_CAPTURE_INVALID)

    def open_final(self, expected_identity: SessionFileIdentity) -> BinaryIO:
        if self.closed or self.stream is not None or not self.handles:
            _reject(COMMAND_CAPTURE_INVALID)
        handle: object | None = None
        descriptor = -1
        try:
            handle = self.api.open_relative(
                self.handles[-1],
                PureWindowsPath(self.path).name,
                directory=False,
            )
            snapshot = self.api.snapshot(handle, directory=False)
            if (
                snapshot.link_count != 1
                or snapshot.size != expected_identity.size
                or PureWindowsPath(snapshot.final_path) != PureWindowsPath(self.path)
            ):
                _reject(COMMAND_CAPTURE_INVALID)
            descriptor = msvcrt.open_osfhandle(
                int(handle.value),
                os.O_RDONLY | os.O_BINARY,
            )
            handle = None
            self.stream = os.fdopen(descriptor, "rb", buffering=0, closefd=True)
            descriptor = -1
            self.final_snapshot = snapshot
            return self.stream
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            if handle is not None:
                self.api.close(handle)
            raise

    def revalidate(self) -> None:
        if self.closed or self.stream is None or self.final_snapshot is None:
            _reject(COMMAND_CAPTURE_INVALID)
        current_directories = tuple(
            self.api.snapshot(handle, directory=True) for handle in self.handles
        )
        borrowed = wintypes.HANDLE(msvcrt.get_osfhandle(self.stream.fileno()))
        current_final = self.api.snapshot(borrowed, directory=False)
        if (
            current_directories != tuple(self.directory_snapshots)
            or current_final != self.final_snapshot
        ):
            _reject(COMMAND_CAPTURE_INVALID)

    def close(self) -> bool:
        if self.closed:
            return True
        failed = False
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                failed = True
            self.stream = None
        for handle in reversed(self.handles):
            try:
                if not self.api.close(handle):
                    failed = True
            except Exception:
                failed = True
        self.handles.clear()
        self.closed = True
        return not failed


def _normalize_session_location(
    session_root: Path,
    session_path: Path,
    identity: SessionFileIdentity,
) -> tuple[Path, Path, str]:
    if (
        not isinstance(session_root, Path)
        or not isinstance(session_path, Path)
        or not session_root.is_absolute()
        or not session_path.is_absolute()
    ):
        _reject(COMMAND_CAPTURE_INVALID)
    try:
        root = Path(os.path.abspath(str(session_root)))
        path = Path(os.path.abspath(str(session_path)))
        if root != session_root or path != session_path or path == root:
            _reject(COMMAND_CAPTURE_INVALID)
        relative = path.relative_to(root)
    except (OSError, TypeError, ValueError):
        _reject(COMMAND_CAPTURE_INVALID)
    relative_parts = relative.parts
    if not relative_parts or any(part in ("", ".", "..") for part in relative_parts):
        _reject(COMMAND_CAPTURE_INVALID)
    relative_text = str(PureWindowsPath(*relative_parts))
    if relative_text != identity.relative_path:
        _reject(COMMAND_CAPTURE_INVALID)
    return root, path, relative_text


def _before_session_file_open(
    _domain: Literal["raw", "retained"],
    _session_root: Path,
    _session_path: Path,
) -> None:
    """Test interposition point after the no-follow lexical precheck."""


def _after_session_file_open(
    _domain: Literal["raw", "retained"],
    _session_root: Path,
    _session_path: Path,
) -> None:
    """Test interposition point after the final file handle is held."""


def _before_session_file_recheck(
    _domain: Literal["raw", "retained"],
    _session_root: Path,
    _session_path: Path,
) -> None:
    """Test interposition point before final handle and namespace checks."""


def _open_session_binary(path: Path) -> BinaryIO:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        stream = os.fdopen(descriptor, "rb", buffering=0)
        descriptor = -1
        return stream
    except OSError:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _reject(COMMAND_CAPTURE_INVALID)


class _SessionReader:
    def __init__(
        self,
        *,
        domain: Literal["raw", "retained"],
        session_root: Path,
        session_path: Path,
        expected_identity: SessionFileIdentity,
    ) -> None:
        if domain not in ("raw", "retained") or type(expected_identity) is not SessionFileIdentity:
            _reject(COMMAND_CAPTURE_INVALID)
        expected_identity.__post_init__()
        root, path, relative = _normalize_session_location(
            session_root,
            session_path,
            expected_identity,
        )
        self.domain = domain
        self.session_root = root
        self.session_path = path
        self.expected_identity = expected_identity
        self._root_chain = _directory_chain(root)
        self._parent_chain = _directory_chain(path.parent)
        self._windows_root = _observe_windows_directory(root)
        self._windows_parent = _observe_windows_directory(path.parent)
        self._held_windows: _HeldWindowsSessionFile | None = None
        try:
            before = os.lstat(path)
        except OSError:
            _reject(COMMAND_CAPTURE_INVALID)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or _stat_has_reparse(before)
            or before.st_nlink != 1
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        before_identity = _session_identity_from_stat(relative, before)
        if before_identity != expected_identity:
            _reject(COMMAND_CAPTURE_INVALID)
        self._closed = True
        try:
            if os.name == "nt":
                if self._windows_root is None or self._windows_parent is None:
                    _reject(COMMAND_CAPTURE_INVALID)
                self._held_windows = _HeldWindowsSessionFile(
                    root=root,
                    path=path,
                    root_observation=self._windows_root,
                    parent_observation=self._windows_parent,
                )
            _before_session_file_open(domain, root, path)
            if self._held_windows is not None:
                self._held_windows.validate_lexical_namespace()
                self._stream = self._held_windows.open_final(expected_identity)
            else:
                self._stream = _open_session_binary(path)
            self._closed = False
            opened = os.fstat(self._stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or _stat_has_reparse(opened)
                or opened.st_nlink != 1
                or _session_identity_from_stat(relative, opened) != expected_identity
            ):
                _reject(COMMAND_CAPTURE_INVALID)
            self._opened_fingerprint = _stat_fingerprint(opened)
            self.size = expected_identity.size
            self._source_offset = 0
            self._source_sha256 = sha256()
            _after_session_file_open(domain, root, path)
        except Exception:
            try:
                if self._held_windows is not None:
                    self._held_windows.close()
                elif hasattr(self, "_stream"):
                    self._stream.close()
            finally:
                self._closed = True
            raise

    def read(self, size: int) -> bytes:
        if self._closed or type(size) is not int or not 0 < size <= _READ_CHUNK_BYTES:
            _reject(COMMAND_CAPTURE_INVALID)
        try:
            data = self._stream.read(size)
        except OSError:
            _reject(COMMAND_CAPTURE_INVALID)
        if type(data) is not bytes or len(data) > size:
            _reject(COMMAND_CAPTURE_INVALID)
        return data

    def seek(self, offset: int) -> None:
        if self._closed or type(offset) is not int or not 0 <= offset <= self.size:
            _reject(COMMAND_CAPTURE_INVALID)
        try:
            observed = self._stream.seek(offset, os.SEEK_SET)
        except OSError:
            _reject(COMMAND_CAPTURE_INVALID)
        if observed != offset:
            _reject(COMMAND_CAPTURE_INVALID)

    def feed_source(self, offset: int, value: bytes) -> None:
        if (
            self._closed
            or type(offset) is not int
            or offset != self._source_offset
            or type(value) is not bytes
            or not value
            or self._source_offset > self.size - len(value)
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        self._source_sha256.update(value)
        self._source_offset += len(value)

    @property
    def source_sha256(self) -> str:
        if self._closed or self._source_offset != self.size:
            _reject(COMMAND_CAPTURE_INVALID)
        return self._source_sha256.hexdigest()

    def close(self) -> None:
        if self._closed:
            return
        try:
            _before_session_file_recheck(
                self.domain,
                self.session_root,
                self.session_path,
            )
            try:
                opened = os.fstat(self._stream.fileno())
            except OSError:
                _reject(COMMAND_CAPTURE_INVALID)
            if _stat_fingerprint(opened) != self._opened_fingerprint:
                _reject(COMMAND_CAPTURE_INVALID)
            if self._held_windows is not None:
                self._held_windows.revalidate()
        finally:
            close_ok = True
            try:
                if self._held_windows is not None:
                    close_ok = self._held_windows.close()
                else:
                    self._stream.close()
            except OSError:
                close_ok = False
            self._closed = True
            if not close_ok:
                _reject(COMMAND_CAPTURE_INVALID)
        try:
            after = os.lstat(self.session_path)
        except OSError:
            _reject(COMMAND_CAPTURE_INVALID)
        if (
            _stat_fingerprint(after) != self._opened_fingerprint
            or _directory_chain(self.session_root) != self._root_chain
            or _directory_chain(self.session_path.parent) != self._parent_chain
            or _observe_windows_directory(self.session_root) != self._windows_root
            or _observe_windows_directory(self.session_path.parent)
            != self._windows_parent
        ):
            _reject(COMMAND_CAPTURE_INVALID)

    def __enter__(self) -> _SessionReader:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


_STRING_SPECIAL = re.compile(rb'["\\\x00-\x1f]')
_DISCARDED = object()


class _RangeCursor:
    def __init__(
        self,
        reader: _SessionReader,
        start: int,
        end: int,
        *,
        stop_at_lf: bool = False,
    ) -> None:
        if (
            type(start) is not int
            or type(end) is not int
            or start < 0
            or end <= start
            or end > reader.size
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        reader.seek(start)
        self.reader = reader
        self.start = start
        self.end = end
        self.absolute = start
        self._buffer = b""
        self._position = 0
        self._stop_at_lf = stop_at_lf
        self._line_terminated = False
        self._line_finished = False

    def _fill(self) -> bool:
        if self._position < len(self._buffer):
            return True
        if self.absolute >= self.end:
            self._buffer = b""
            self._position = 0
            return False
        requested = min(_READ_CHUNK_BYTES, self.end - self.absolute)
        self._buffer = self.reader.read(requested)
        self._position = 0
        if not self._buffer or len(self._buffer) > requested:
            _reject(COMMAND_CAPTURE_INVALID)
        if self._stop_at_lf:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                self.end = self.absolute + newline
                self._buffer = self._buffer[:newline]
                self._line_terminated = True
                if not self._buffer:
                    return False
        return True

    def peek_byte(self) -> int:
        if not self._fill():
            _reject(COMMAND_JSON_INVALID)
        return self._buffer[self._position]

    def read_byte(self) -> int:
        value = self.peek_byte()
        self.reader.feed_source(self.absolute, bytes((value,)))
        self._position += 1
        self.absolute += 1
        return value

    def read_exact(self, size: int) -> bytes:
        if type(size) is not int or size < 0:
            _reject(COMMAND_JSON_INVALID)
        result = bytearray()
        while len(result) < size:
            if not self._fill():
                _reject(COMMAND_JSON_INVALID)
            available = min(
                size - len(result),
                len(self._buffer) - self._position,
            )
            chunk = self._buffer[self._position : self._position + available]
            self.reader.feed_source(self.absolute, chunk)
            result.extend(chunk)
            self._position += available
            self.absolute += available
        return bytes(result)

    def take_string_plain_run(self) -> tuple[bytes, int | None]:
        if not self._fill():
            _reject(COMMAND_JSON_INVALID)
        match = _STRING_SPECIAL.search(self._buffer, self._position)
        if match is None:
            run = self._buffer[self._position :]
            self.reader.feed_source(self.absolute, run)
            self.absolute += len(run)
            self._position = len(self._buffer)
            return run, None
        special_index = match.start()
        run = self._buffer[self._position : special_index]
        if run:
            self.reader.feed_source(self.absolute, run)
        self.absolute += len(run)
        self._position = special_index
        return run, self._buffer[special_index]

    def skip_whitespace(self) -> None:
        while self.absolute < self.end:
            value = self.peek_byte()
            if value not in _JSON_WHITESPACE:
                return
            self.read_byte()

    def finish_line(self) -> bool:
        if not self._stop_at_lf or self._line_finished:
            _reject(COMMAND_CAPTURE_INVALID)
        if self._position < len(self._buffer):
            return False
        has_more = self._fill()
        valid = (
            not has_more
            and self._line_terminated
            and self.absolute == self.end
        )
        if valid:
            self.reader.feed_source(self.end, b"\n")
            self._line_finished = True
        return valid


class _DomainBudget:
    def __init__(self) -> None:
        self.consumed = 0

    def consume(self, size: int) -> None:
        if (
            type(size) is not int
            or size < 0
            or self.consumed > _SESSION_OUTPUT_LIMIT_BYTES - size
        ):
            _reject(COMMAND_OUTPUT_LIMIT_EXCEEDED)
        self.consumed += size


class _HashSink:
    def __init__(self) -> None:
        self.length = 0
        self._sha256 = sha256()

    def feed(self, value: bytes) -> None:
        if type(value) is not bytes:
            _reject(COMMAND_JSON_INVALID)
        self.length += len(value)
        self._sha256.update(value)

    @property
    def digest(self) -> str:
        return self._sha256.hexdigest()


class _EmptyOutputSink(_HashSink):
    def feed(self, value: bytes) -> None:
        if value:
            _reject(COMMAND_CAPTURE_INVALID)
        super().feed(value)


class _ValueSink(_HashSink):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit
        self.value = bytearray()

    def feed(self, value: bytes) -> None:
        if self.length > self.limit - len(value):
            _reject(COMMAND_CAPTURE_INVALID)
        super().feed(value)
        self.value.extend(value)


@dataclass(frozen=True, slots=True)
class _NamespaceSelectorPath:
    namespace: str
    suffix: tuple[str, ...]


@dataclass(frozen=True)
class _ParsedDocument:
    canonical_sha256: str
    canonical_bytes: bytes | None
    selected_value_hashes: tuple[tuple[tuple[str, ...], str], ...]
    shape_sha256: str
    selector_sha256: str
    selector_paths: tuple[_NamespaceSelectorPath, ...]
    top_level_keys: tuple[str, ...]
    ok: object
    error_keys: tuple[str, ...] | None
    error_code: object
    error_message_is_string: bool
    error_retryable: object
    error_details_is_dict: bool


def _json_shape(value: object, *, depth: int = 0) -> object:
    if depth > _JSON_DEPTH_LIMIT:
        _reject(COMMAND_JSON_INVALID)
    if type(value) is dict:
        return {
            "object": [
                [key, _json_shape(item, depth=depth + 1)]
                for key, item in sorted(value.items())
            ]
        }
    if type(value) is list:
        return {"array": [_json_shape(item, depth=depth + 1) for item in value]}
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if type(value) is str:
        return "string"
    _reject(COMMAND_JSON_INVALID)


def _selector_fingerprint(
    value: object,
) -> tuple[str, tuple[_NamespaceSelectorPath, ...]]:
    digest = sha256()
    namespace_paths: list[_NamespaceSelectorPath] = []

    def feed(marker: bytes, payload: bytes = b"") -> None:
        digest.update(marker)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)

    def visit(item: object, *, depth: int) -> None:
        if depth > _JSON_DEPTH_LIMIT:
            _reject(COMMAND_JSON_INVALID)
        if type(item) is _NamespaceSelectorPath:
            if (
                type(item.namespace) is not str
                or type(item.suffix) is not tuple
                or any(type(part) is not str for part in item.suffix)
            ):
                _reject(COMMAND_JSON_INVALID)
            feed(b"P")
            namespace_paths.append(item)
            return
        if isinstance(item, dict):
            if any(type(key) is not str for key in item):
                _reject(COMMAND_JSON_INVALID)
            feed(b"D", len(item).to_bytes(8, "big"))
            for key in sorted(item):
                feed(b"K", key.encode("utf-8", errors="strict"))
                visit(item[key], depth=depth + 1)
            return
        if type(item) is list:
            feed(b"L", len(item).to_bytes(8, "big"))
            for child in item:
                visit(child, depth=depth + 1)
            return
        if item is None:
            feed(b"N")
            return
        if type(item) is bool:
            feed(b"B", b"1" if item else b"0")
            return
        if type(item) is int:
            feed(b"I", str(item).encode("ascii"))
            return
        if type(item) is float:
            if not math.isfinite(item):
                _reject(COMMAND_JSON_INVALID)
            normalized = b"0" if item == 0.0 else _canonical_json_bytes(item)
            feed(b"F", normalized)
            return
        if type(item) is str:
            try:
                encoded = item.encode("utf-8", errors="strict")
            except UnicodeError:
                _reject(COMMAND_JSON_INVALID)
            feed(b"S", encoded)
            return
        _reject(COMMAND_JSON_INVALID)

    visit(value, depth=0)
    return digest.hexdigest(), tuple(namespace_paths)


def _selector_paths_equivalent(
    left: tuple[_NamespaceSelectorPath, ...],
    right: tuple[_NamespaceSelectorPath, ...],
    *,
    plan: BoundCommandPlan,
) -> bool:
    if len(left) != len(right):
        return False
    for left_path, right_path in zip(left, right, strict=True):
        if (
            type(left_path) is not _NamespaceSelectorPath
            or type(right_path) is not _NamespaceSelectorPath
            or left_path.namespace != right_path.namespace
        ):
            return False
        matching_namespaces = tuple(
            namespace
            for namespace in plan.namespaces
            if namespace.label == left_path.namespace
        )
        if len(matching_namespaces) != 1:
            return False
        namespace = matching_namespaces[0]
        if not _windows_path_parts_equal(
            left_path.suffix,
            right_path.suffix,
            ignore_case=(
                not namespace.raw_case_sensitive
                and not namespace.retained_case_sensitive
            ),
        ):
            return False
    return True


def _operation_action(operation: ApprovedOperation) -> tuple[str, ...]:
    if type(operation) is not ApprovedOperation:
        _reject(COMMAND_RESULT_INCONSISTENT)
    matches = tuple(
        action
        for action in _CLI_ACTIONS
        if len(operation.argv) > len(action)
        and tuple(value.casefold() for value in operation.argv[1 : len(action) + 1])
        == action
    )
    if len(matches) != 1:
        _reject(COMMAND_RESULT_INCONSISTENT)
    return matches[0]


def _namespace_selector(
    value: str,
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
) -> object:
    rendered = value.replace("/", "\\")
    candidate = PureWindowsPath(rendered)
    if not candidate.is_absolute():
        if not _safe_relative_result_path(value):
            _reject(COMMAND_RESULT_INCONSISTENT)
        return value
    if rendered.startswith(("\\\\?\\", "\\??\\")):
        _reject(COMMAND_RESULT_INCONSISTENT)
    if any(
        not part
        or part in (".", "..")
        or part.endswith((" ", "."))
        or any(character in '<>:"|?*' or ord(character) < 32 for character in part)
        or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        for part in candidate.parts[1:]
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)
    candidate_parts = tuple(candidate.parts)
    matches: list[tuple[object, tuple[str, ...]]] = []
    for namespace in plan.namespaces:
        root_text = (
            namespace.raw_root if domain == "raw" else namespace.retained_root
        )
        root_parts = tuple(PureWindowsPath(root_text).parts)
        if len(candidate_parts) < len(root_parts):
            continue
        insensitive = (
            not namespace.raw_case_sensitive
            and not namespace.retained_case_sensitive
        )
        try:
            prefix_matches = _windows_path_parts_equal(
                candidate_parts[: len(root_parts)],
                root_parts,
                ignore_case=insensitive,
            )
        except RuntimeError:
            _reject(COMMAND_RESULT_INCONSISTENT)
        if not prefix_matches:
            continue
        matches.append((namespace, candidate_parts[len(root_parts) :]))
    if len(matches) != 1:
        _reject(COMMAND_RESULT_INCONSISTENT)
    namespace, suffix = matches[0]
    return _NamespaceSelectorPath(
        namespace=namespace.label,
        suffix=tuple(suffix),
    )


def _validate_operation_output_contract(
    operation: ApprovedOperation,
    action: tuple[str, ...],
    value: dict[str, Any],
    *,
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
) -> None:
    declared_outputs = operation.declared_output_paths
    if action in _DECLARED_OUTPUT_ACTIONS:
        if len(declared_outputs) != 1:
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif declared_outputs:
        _reject(COMMAND_RESULT_INCONSISTENT)
    else:
        return

    declared = declared_outputs[0]
    if not _safe_relative_result_path(declared):
        _reject(COMMAND_RESULT_INCONSISTENT)
    if action not in _RESULT_PATH_OUTPUT_ACTIONS:
        return

    result_selector = _namespace_selector(value["path"], plan, domain)
    declared_parts = tuple(
        PureWindowsPath(declared.replace("/", "\\")).parts
    )
    if type(result_selector) is str:
        result_parts = tuple(
            PureWindowsPath(result_selector.replace("/", "\\")).parts
        )
        ignore_case = False
    elif type(result_selector) is _NamespaceSelectorPath:
        result_parts = result_selector.suffix
        matching_namespaces = tuple(
            namespace
            for namespace in plan.namespaces
            if namespace.label == result_selector.namespace
        )
        if len(matching_namespaces) != 1:
            _reject(COMMAND_RESULT_INCONSISTENT)
        namespace = matching_namespaces[0]
        ignore_case = (
            not namespace.raw_case_sensitive
            and not namespace.retained_case_sensitive
        )
    else:
        _reject(COMMAND_RESULT_INCONSISTENT)
    try:
        matches = _windows_path_parts_equal(
            result_parts,
            declared_parts,
            ignore_case=ignore_case,
        )
    except RuntimeError:
        _reject(COMMAND_RESULT_INCONSISTENT)
    if not matches:
        _reject(COMMAND_RESULT_INCONSISTENT)


def _selector_tree(
    value: object,
    *,
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
    omitted_paths: frozenset[tuple[str, ...]] = frozenset(),
    namespace_paths: frozenset[tuple[str, ...]] = frozenset(),
    string_shape_only: bool = False,
    stable_string_keys: frozenset[str] = frozenset(),
    parent_key: str | None = None,
    current_path: tuple[str, ...] = (),
    depth: int = 0,
) -> object:
    if depth > _JSON_DEPTH_LIMIT:
        _reject(COMMAND_JSON_INVALID)
    if type(value) is dict:
        result: dict[str, object] = {}
        for key, item in sorted(value.items()):
            child_path = current_path + (key,)
            if child_path in omitted_paths:
                continue
            result[key] = _selector_tree(
                item,
                plan=plan,
                domain=domain,
                omitted_paths=omitted_paths,
                namespace_paths=namespace_paths,
                string_shape_only=string_shape_only,
                stable_string_keys=stable_string_keys,
                parent_key=key,
                current_path=child_path,
                depth=depth + 1,
            )
        return result
    if type(value) is list:
        return [
            _selector_tree(
                item,
                plan=plan,
                domain=domain,
                omitted_paths=omitted_paths,
                namespace_paths=namespace_paths,
                string_shape_only=string_shape_only,
                stable_string_keys=stable_string_keys,
                parent_key=parent_key,
                current_path=current_path + ("*",),
                depth=depth + 1,
            )
            for item in value
        ]
    if type(value) is str:
        if current_path in namespace_paths:
            return _namespace_selector(value, plan, domain)
        if string_shape_only and parent_key not in stable_string_keys:
            return {"value_type": "string"}
        return value
    if value is None or type(value) in (bool, int, float):
        return value
    _reject(COMMAND_JSON_INVALID)


def _selected_mapping(
    value: object,
    keys: tuple[str, ...],
    *,
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
) -> dict[str, object]:
    if type(value) is not dict:
        _reject(COMMAND_RESULT_INCONSISTENT)
    return {
        key: _selector_tree(value[key], plan=plan, domain=domain)
        for key in keys
        if key in value
    }


def _character_request_selector(
    value: dict[str, Any],
    *,
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
) -> object:
    request = value.get("request")
    if type(request) is not dict:
        _reject(COMMAND_RESULT_INCONSISTENT)
    selected = _selected_mapping(
        request,
        (
            "schema_version",
            "artifact_id",
            "created_by",
            "mode",
            "namespace",
            "character_id",
            "character_version",
            "requested_locales",
            "requested_visibility",
        ),
        plan=plan,
        domain=domain,
    )
    inputs = request.get("inputs")
    if type(inputs) is not list:
        _reject(COMMAND_RESULT_INCONSISTENT)
    selected["inputs"] = [
        _selected_mapping(
            item,
            ("type", "artifact_id", "sha256"),
            plan=plan,
            domain=domain,
        )
        for item in inputs
    ]
    return {"ok": value.get("ok", _DISCARDED), "request": selected}


def _research_request_selector(
    value: dict[str, Any],
    *,
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
) -> object:
    return {
        "ok": value.get("ok", _DISCARDED),
        "request": _selected_mapping(
            value.get("request"),
            (
                "schema_version",
                "artifact_id",
                "created_by",
                "namespace",
                "character_id",
                "medium",
                "work",
                "adaptation",
                "continuity",
                "timeline_cutoff",
                "required_coverage_topics",
                "requested_visibility",
            ),
            plan=plan,
            domain=domain,
        ),
    }


def _runtime_plan_selector(
    value: dict[str, Any],
    *,
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
) -> object:
    projected = _selector_tree(value, plan=plan, domain=domain)
    if type(projected) is not dict:
        _reject(COMMAND_RESULT_INCONSISTENT)
    render_plan = projected.get("plan")
    source_plan = value.get("plan")
    if type(render_plan) is not dict or type(source_plan) is not dict:
        _reject(COMMAND_RESULT_INCONSISTENT)
    protected = source_plan.get("protected_spans")
    if type(protected) is not list:
        _reject(COMMAND_RESULT_INCONSISTENT)
    render_plan["protected_spans"] = [
        {"value_type": "string"} for _item in protected
    ]
    return projected


def _has_exact_keys(
    value: object,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> bool:
    return (
        type(value) is dict
        and required.issubset(value)
        and frozenset(value).issubset(required | optional)
    )


def _nonempty_string(value: object, maximum: int = 4096) -> bool:
    return type(value) is str and 0 < len(value) <= maximum


def _safe_relative_result_path(value: object) -> bool:
    if type(value) is not str or not value or "\x00" in value:
        return False
    path = PureWindowsPath(value.replace("/", "\\"))
    return (
        not path.is_absolute()
        and not path.anchor
        and bool(path.parts)
        and all(
            part not in ("", ".", "..")
            and not part.endswith((" ", "."))
            and not any(character in '<>:"|?*' or ord(character) < 32 for character in part)
            and part.split(".", 1)[0].casefold() not in _WINDOWS_RESERVED_NAMES
            for part in path.parts
        )
    )


def _matches_registry_identity(value: object) -> bool:
    return (
        type(value) is str
        and 7 <= len(value) <= 194
        and _REGISTRY_IDENTITY.fullmatch(value) is not None
    )


def _matches_stable_id(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= 128
        and _STABLE_ID.fullmatch(value) is not None
    )


def _matches_registry_artifact_id(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= 192
        and _REGISTRY_ARTIFACT_ID.fullmatch(value) is not None
    )


def _matches_registry_relative_path(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= 512
        and _REGISTRY_RELATIVE_PATH.fullmatch(value) is not None
    )


def _validate_install_plan(value: object) -> None:
    keys = frozenset(
        {
            "schema_version", "operation", "scope", "workspace_id",
            "registry_identity", "installation_id", "archive_sha256",
            "manifest_sha256", "compiled_artifact_id", "compiled_sha256",
            "visibility", "relative_path", "registry_revision_before",
            "registry_revision_after", "idempotent", "will_write",
            "activates_character",
        }
    )
    if not _has_exact_keys(value, keys) or type(value) is not dict:
        _reject(COMMAND_RESULT_INCONSISTENT)
    before = value["registry_revision_before"]
    after = value["registry_revision_after"]
    if (
        value["schema_version"] != "1.0"
        or value["operation"] != "install"
        or value["scope"] not in ("global", "workspace")
        or (
            value["workspace_id"] is not None
            if value["scope"] == "global"
            else not _is_sha256(value["workspace_id"])
        )
        or not _matches_registry_identity(value["registry_identity"])
        or not _matches_stable_id(value["installation_id"])
        or not _matches_registry_artifact_id(value["compiled_artifact_id"])
        or not _is_sha256(value["archive_sha256"])
        or not _is_sha256(value["manifest_sha256"])
        or not _is_sha256(value["compiled_sha256"])
        or value["visibility"] not in ("private", "public_candidate")
        or not _matches_registry_relative_path(value["relative_path"])
        or type(before) is not int
        or before < 0
        or type(after) is not int
        or after < 0
        or type(value["idempotent"]) is not bool
        or type(value["will_write"]) is not bool
        or value["activates_character"] is not False
        or (
            value["idempotent"]
            and (after != before or value["will_write"] is not False)
        )
        or (
            not value["idempotent"]
            and (after != before + 1 or value["will_write"] is not True)
        )
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)


def _validate_installed_entry(value: object) -> None:
    keys = frozenset(
        {
            "registry_identity", "installation_id", "archive_sha256",
            "manifest_sha256", "compiled_artifact_id", "compiled_sha256",
            "visibility", "promotion_status", "activation_allowed", "trust",
            "relative_path",
        }
    )
    if not _has_exact_keys(value, keys) or type(value) is not dict:
        _reject(COMMAND_RESULT_INCONSISTENT)
    if (
        not _matches_registry_identity(value["registry_identity"])
        or not _matches_stable_id(value["installation_id"])
        or not _matches_registry_artifact_id(value["compiled_artifact_id"])
        or any(
            not _is_sha256(value[field])
            for field in ("archive_sha256", "manifest_sha256", "compiled_sha256")
        )
        or value["visibility"] not in ("private", "public_candidate")
        or value["promotion_status"] != "verified"
        or value["activation_allowed"] is not True
        or value["trust"] != "unsigned_local"
        or not _matches_registry_relative_path(value["relative_path"])
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)


def _validate_publication_result(value: dict[str, Any]) -> None:
    blockers = value["blockers"]
    if type(blockers) is not list or len(blockers) > 256:
        _reject(COMMAND_RESULT_INCONSISTENT)
    seen: set[bytes] = set()
    for blocker in blockers:
        if not _has_exact_keys(
            blocker,
            frozenset({"severity", "code", "path", "message"}),
        ) or type(blocker) is not dict:
            _reject(COMMAND_RESULT_INCONSISTENT)
        path = blocker["path"]
        if (
            blocker["severity"] != "error"
            or type(blocker["code"]) is not str
            or re.fullmatch(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*", blocker["code"])
            is None
            or type(path) is not list
            or len(path) > 32
            or any(
                not (
                    (type(item) is int and 0 <= item <= 1_000_000)
                    or (
                        _nonempty_string(item, 128)
                        and re.fullmatch(r"[A-Za-z0-9._-]+", item) is not None
                    )
                )
                for item in path
            )
            or not _nonempty_string(blocker["message"], 1000)
            or any(ord(character) < 32 or ord(character) == 127 for character in blocker["message"])
        ):
            _reject(COMMAND_RESULT_INCONSISTENT)
        canonical = _canonical_json_bytes(blocker)
        if canonical in seen:
            _reject(COMMAND_RESULT_INCONSISTENT)
        seen.add(canonical)
    private_ready = value["ready_for_private_export"]
    public_ready = value["ready_for_publication"]
    if (
        (public_ready and (not private_ready or blockers))
        or (not private_ready and (public_ready or not blockers))
        or (not blockers and not private_ready)
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)


def _validate_research_conflict(value: object) -> None:
    _validate_frozen_schema("research-conflict", value)
    if type(value) is not dict or not set(value["selected_claim_ids"]).issubset(
        value["claim_ids"]
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)


def _validate_research_bundle_result(value: dict[str, Any]) -> None:
    coverage = value["coverage_summary"]
    if (
        value["build_status"] != "research"
        or value["visibility"] != "private"
        or value["activation_allowed"] is not False
        or not _has_exact_keys(
            coverage,
            frozenset({"covered", "partial", "missing", "blocked"}),
        )
        or type(coverage) is not dict
        or any(type(item) is not int or item < 0 for item in coverage.values())
        or sum(coverage.values()) > 128
        or type(value["conflicts"]) is not list
        or len(value["conflicts"]) > 256
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)
    seen_conflicts: set[bytes] = set()
    seen_conflict_ids: set[str] = set()
    for conflict in value["conflicts"]:
        _validate_research_conflict(conflict)
        canonical = _canonical_json_bytes(conflict)
        conflict_id = conflict["conflict_id"]
        if canonical in seen_conflicts or conflict_id in seen_conflict_ids:
            _reject(COMMAND_RESULT_INCONSISTENT)
        seen_conflicts.add(canonical)
        seen_conflict_ids.add(conflict_id)
    for field in ("limitations", "blocking_reasons"):
        items = value[field]
        if (
            type(items) is not list
            or len(items) > 128
            or any(not _nonempty_string(item, 2000) for item in items)
            or len(set(items)) != len(items)
        ):
            _reject(COMMAND_RESULT_INCONSISTENT)
    if value["authoring_allowed"] and value["blocking_reasons"]:
        _reject(COMMAND_RESULT_INCONSISTENT)


def _valid_runtime_context(value: object) -> bool:
    if not _has_exact_keys(
        value,
        frozenset(
            {
                "character_id", "character_version", "identity",
                "effective_profile", "locales", "scenarios", "expressions",
                "growth", "state",
            }
        ),
    ) or type(value) is not dict:
        return False
    identity = value["identity"]
    profile = value["effective_profile"]
    locales = value["locales"]
    scenarios = value["scenarios"]
    expressions = value["expressions"]
    growth = value["growth"]
    state = value["state"]
    if (
        not _nonempty_string(value["character_id"], 64)
        or _SLUG_ID.fullmatch(value["character_id"]) is None
        or not _nonempty_string(value["character_version"], 64)
        or _SEMVER.fullmatch(value["character_version"]) is None
        or type(identity) is not dict
        or "display_name" not in identity
        or not frozenset(identity).issubset(
            {"display_name", "declared_age", "role", "worldview", "non_negotiables"}
        )
        or not _nonempty_string(identity["display_name"], 256)
        or any(
            field in identity and not _nonempty_string(identity[field], 256)
            for field in ("declared_age", "role")
        )
        or any(
            field in identity
            and (
                type(identity[field]) is not list
                or not 1 <= len(identity[field]) <= 32
                or any(not _nonempty_string(item, 256) for item in identity[field])
                or len(set(identity[field])) != len(identity[field])
            )
            for field in ("worldview", "non_negotiables")
        )
        or type(profile) is not dict
        or not 1 <= len(profile) <= 256
        or any(
            type(key) is not str
            or len(key) > 128
            or _SEMANTIC_ID.fullmatch(key) is None
            for key in profile
        )
        or any(
            type(item) not in (int, float)
            or (type(item) is float and not math.isfinite(item))
            or not 0 <= item <= 1
            for item in profile.values()
        )
        or type(locales) is not dict
        or len(locales) != 1
        or not set(locales).issubset({"zh-CN", "en-US", "ja-JP"})
        or type(scenarios) is not dict
        or len(scenarios) != 1
        or any(
            type(key) is not str
            or len(key) > 128
            or _SEMANTIC_ID.fullmatch(key) is None
            for key in scenarios
        )
        or type(expressions) is not dict
        or len(expressions) > 256
        or not _has_exact_keys(growth, frozenset({"dimensions"}))
        or type(growth) is not dict
        or type(growth["dimensions"]) is not list
        or not 1 <= len(growth["dimensions"]) <= 4
        or any(
            item not in {"familiarity", "trust", "collaboration", "tension"}
            for item in growth["dimensions"]
        )
        or len(set(growth["dimensions"])) != len(growth["dimensions"])
        or not _has_exact_keys(state, frozenset({"revision", "stage", "dimensions"}))
        or type(state) is not dict
        or type(state["revision"]) is not int
        or state["revision"] < 0
        or state["stage"] not in {"unknown", "acquainted", "familiar", "trusted"}
        or type(state["dimensions"]) is not dict
        or set(state["dimensions"]) != set(growth["dimensions"])
        or any(
            type(item) not in (int, float)
            or (type(item) is float and not math.isfinite(item))
            or not 0 <= item <= 100
            for item in state["dimensions"].values()
        )
    ):
        return False
    locale_name, locale_config = next(iter(locales.items()))
    if (
        type(locale_config) is not dict
        or not frozenset(locale_config).issubset(
            {"register", "sentence_length", "technical_terms", "addressing", "politeness"}
        )
    ):
        return False
    for key in ("register", "sentence_length", "technical_terms"):
        if key in locale_config and not _nonempty_string(locale_config[key], 256):
            return False
    for key in ("addressing", "politeness"):
        stage_map = locale_config.get(key)
        if stage_map is not None and (
            type(stage_map) is not dict
            or not set(stage_map).issubset({"unknown", "acquainted", "familiar", "trusted"})
            or any(
                item is not None
                and (
                    type(item) is not str
                    or len(item) > 128
                )
                for item in stage_map.values()
            )
        ):
            return False
    scenario = next(iter(scenarios.values()))
    if (
        type(scenario) is not dict
        or not set(scenario).issubset(
            {"first_action", "hypothesis_style", "correction_style", "reassurance", "intensity_cap"}
        )
        or any(
            key in scenario and not _nonempty_string(scenario[key], 256)
            for key in ("first_action", "hypothesis_style", "correction_style", "reassurance")
        )
        or (
            "intensity_cap" in scenario
            and scenario["intensity_cap"]
            not in {"neutral", "subtle", "balanced", "immersive", "performance"}
        )
    ):
        return False
    for intent, selection in expressions.items():
        if (
            type(intent) is not str
            or len(intent) > 128
            or _SEMANTIC_ID.fullmatch(intent) is None
            or not _has_exact_keys(selection, frozenset({locale_name}))
            or type(selection) is not dict
            or type(selection[locale_name]) is not list
            or not 1 <= len(selection[locale_name]) <= 32
            or any(not _nonempty_string(item, 500) for item in selection[locale_name])
        ):
            return False
    return True


_RUNTIME_VIOLATION_CODES = frozenset(
    {
        "ARTIFACT_SUFFIX_MISMATCH", "CHANNEL_MISMATCH",
        "DUPLICATE_RENDERED_SEGMENT_ID", "DUPLICATE_SEGMENT_ID",
        "INVALID_IMMUTABLE_SPANS", "INVALID_MAX_SWITCHES", "INVALID_PLAN",
        "INVALID_PLANNED_SEGMENT", "INVALID_PLANNED_SEGMENTS",
        "INVALID_RENDERED_SEGMENT", "INVALID_RENDERED_SEGMENTS",
        "INVALID_RENDERED_TEXT", "INVALID_RENDERED", "INVALID_SEMANTIC",
        "INVALID_SWITCH_COUNT", "INVALID_WARNINGS", "LANGUAGE_MISMATCH",
        "MISSING_PROTECTED_SPAN", "MISSING_SEGMENT", "MISSING_SEMANTIC_KEY",
        "MISSING_SEMANTIC_ROUTE", "MISSING_WARNING", "PROTECTED_SPAN_MISMATCH",
        "TOO_MANY_SWITCHES", "UNEXPECTED_SEGMENT_ID", "UNEXPECTED_SEMANTIC_KEY",
    }
)


def _validate_runtime_plan(value: object) -> None:
    _validate_frozen_schema("render-plan", value)
    if type(value) is not dict:
        _reject(COMMAND_RESULT_INCONSISTENT)
    segments = value["segments"]
    routes = ("conclusion", "explanation", "recommendations", "warnings")
    channel_for = {
        "conclusion": "character_dialogue",
        "explanation": "technical_explanation",
        "recommendations": "recommendations",
        "warnings": "warnings",
    }
    observed_routes: list[str] = []
    if not 1 <= len(segments) <= 4 or not value["artifact_id"].startswith("plan/"):
        _reject(COMMAND_RESULT_INCONSISTENT)
    for index, segment in enumerate(segments, start=1):
        if (
            segment["id"] != f"s{index}"
            or len(segment["semantic_keys"]) != 1
            or segment["channel"] != channel_for[segment["semantic_keys"][0]]
            or (
                "expression_intent" in segment
                and segment["channel"] != "character_dialogue"
            )
        ):
            _reject(COMMAND_RESULT_INCONSISTENT)
        observed_routes.append(segment["semantic_keys"][0])
    if observed_routes != [route for route in routes if route in observed_routes]:
        _reject(COMMAND_RESULT_INCONSISTENT)


def _validate_runtime_validation(value: object) -> None:
    _validate_frozen_schema("validation-result", value)
    if type(value) is not dict:
        _reject(COMMAND_RESULT_INCONSISTENT)
    valid = value["valid"]
    violations = value["violations"]
    if (
        (valid and (violations or value["fallback_level"] is not None))
        or (not valid and (not violations or value["fallback_level"] != 0))
        or any(
            type(item) is not dict
            or item.get("code") not in _RUNTIME_VIOLATION_CODES
            or not _nonempty_string(item.get("message"), 4000)
            for item in violations
        )
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)


def _validate_memory_remove(value: dict[str, Any]) -> None:
    if value["dry_run"]:
        plan = value.get("plan")
        if not _has_exact_keys(
            plan,
            frozenset({"action", "host_memory_id", "memory_reference_id", "will_remove"}),
        ) or type(plan) is not dict or (
            plan["action"] != "remove_memory_reference"
            or not _nonempty_string(plan["host_memory_id"], 128)
            or not _nonempty_string(plan["memory_reference_id"], 128)
            or plan["will_remove"] is not True
        ):
            _reject(COMMAND_RESULT_INCONSISTENT)
    else:
        result = value.get("result")
        if not _has_exact_keys(
            result,
            frozenset({"removed", "memory_reference_id"}),
        ) or type(result) is not dict or (
            result["removed"] is not True
            or not _nonempty_string(result["memory_reference_id"], 128)
        ):
            _reject(COMMAND_RESULT_INCONSISTENT)


def _validate_success_nested_contract(
    action: tuple[str, ...],
    value: dict[str, Any],
) -> None:
    schema_fields: dict[tuple[str, ...], tuple[str, str]] = {
        ("character", "request", "validate"): ("request", "character-build-request"),
        ("character", "draft", "validate"): ("validation_report", "build-validation-report"),
        ("character", "draft", "compile"): ("validation_report", "build-validation-report"),
        ("research", "request", "validate"): ("request", "research-request"),
        ("research", "workspace", "validate"): ("validation_report", "research-validation-report"),
        ("config", "default", "set"): ("default", "character-default-config"),
        ("config", "default", "show"): ("default", "character-default-config"),
        ("session", "start"): ("session", "session-manifest"),
        ("state", "preview"): ("state", "relationship-state"),
        ("state", "apply"): ("state", "relationship-state"),
        ("memory", "add"): ("memory_reference", "memory-reference"),
        ("policy", "compile"): ("policy", "language-policy"),
    }
    schema_binding = schema_fields.get(action)
    if schema_binding is not None:
        field, schema_name = schema_binding
        _validate_frozen_schema(schema_name, value[field])
    if action == ("pack", "install"):
        _validate_install_plan(value["plan"])
        if value["activates_character"] is not False:
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("pack", "list"):
        if len(value["installed"]) > 1024 or value["activates_character"] is not False:
            _reject(COMMAND_RESULT_INCONSISTENT)
        for item in value["installed"]:
            _validate_installed_entry(item)
    elif action == ("pack", "test"):
        if value["passed"] and not _is_sha256(value["compiled_hash"]):
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("pack", "promote"):
        if value["activation_allowed"] is not (value["to_status"] == "verified"):
            _reject(COMMAND_RESULT_INCONSISTENT)
        path = PureWindowsPath(value["path"])
        if PureWindowsPath(value["bundle_path"]) != path.parent:
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("pack", "publication-check"):
        _validate_publication_result(value)
    elif action == ("character", "draft", "validate"):
        if value["valid"] is not value["validation_report"]["valid"]:
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("character", "draft", "compile"):
        if (
            value["validation_report"]["valid"] is not True
            or value["build_status"] != "draft"
            or value["visibility"] != "private"
            or value["activation_allowed"] is not False
        ):
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("research", "workspace", "validate"):
        if value["valid"] is not value["validation_report"]["valid"]:
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action in (
        ("research", "bundle", "compile"),
        ("research", "bundle", "validate"),
    ):
        _validate_research_bundle_result(value)
        if action[-1] == "validate" and value["valid"] is not True:
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("config", "default", "set"):
        if value["default"]["binding"] is None or value["activates_character"] is not False:
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("config", "default", "show"):
        if value["activates_character"] is not False:
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("session", "start"):
        session = value["session"]
        if session["active"] is not True or session["state_revision"] != 0 or session["scope"] != "session":
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("session", "show") and value["session"] is not None:
        _validate_frozen_schema("session-manifest", value["session"])
    elif action == ("consent", "show") and value["consent"] is not None:
        _validate_frozen_schema("persistence-consent", value["consent"])
    elif action == ("memory", "list"):
        if len(value["memory_references"]) > 1024:
            _reject(COMMAND_RESULT_INCONSISTENT)
        for item in value["memory_references"]:
            if not _has_exact_keys(
                item,
                frozenset({"reference", "active_consent_generation"}),
            ) or type(item) is not dict or type(item["active_consent_generation"]) is not bool:
                _reject(COMMAND_RESULT_INCONSISTENT)
            _validate_frozen_schema("memory-reference", item["reference"])
    elif action == ("memory", "remove"):
        _validate_memory_remove(value)
    elif action == ("runtime", "context"):
        if not _valid_runtime_context(value["context"]):
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("runtime", "plan"):
        _validate_runtime_plan(value["plan"])
    elif action == ("runtime", "validate"):
        _validate_runtime_validation(value["validation"])


def _validate_success_field_types(
    action: tuple[str, ...],
    value: dict[str, Any],
) -> None:
    field_types = _SUCCESS_FIELD_TYPES.get(action)
    if field_types is None or any(
        key not in field_types or type(item) not in field_types[key]
        for key, item in value.items()
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)
    if value.get("ok") is not True:
        _reject(COMMAND_RESULT_INCONSISTENT)
    bounded_string_fields: dict[tuple[str, ...], tuple[str, ...]] = {
        ("pack", "validate"): (
            "artifact_id", "character_id", "character_version",
        ),
        ("pack", "compile"): (
            "artifact_id", "character_id", "character_version",
        ),
        ("pack", "test"): ("artifact_id",),
        ("pack", "soft-eval"): ("artifact_id",),
        ("pack", "promote"): ("artifact_id", "promotion_id"),
        ("pack", "publication-check"): ("artifact_id",),
        ("character", "draft", "compile"): ("artifact_id",),
        ("research", "bundle", "compile"): ("artifact_id",),
        ("research", "bundle", "validate"): ("artifact_id",),
    }
    if any(
        not _nonempty_string(value[field], 256)
        for field in bounded_string_fields.get(action, ())
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)

    if action == ("pack", "list"):
        scope = value["scope"]
        workspace_id = value["workspace_id"]
        if scope not in ("global", "workspace") or (
            (scope == "global" and workspace_id is not None)
            or (scope == "workspace" and not _is_sha256(workspace_id))
        ):
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("pack", "promote") and value["to_status"] not in (
        "reviewed",
        "verified",
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("pack", "export"):
        if value["visibility"] not in ("private", "public_candidate"):
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action == ("character", "draft", "compile"):
        if value["visibility"] != "private":
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif action in (
        ("research", "bundle", "compile"),
        ("research", "bundle", "validate"),
    ):
        if value["visibility"] != "private":
            _reject(COMMAND_RESULT_INCONSISTENT)

    hash_fields = tuple(
        item
        for key, item in value.items()
        if key.endswith("_hash") or key.endswith("_sha256")
    )
    if any(
        item is not None and not _is_sha256(item)
        for item in hash_fields
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)
    _validate_success_nested_contract(action, value)


def _success_selector_projection(
    operation: ApprovedOperation,
    value: dict[str, Any],
    *,
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
) -> object:
    action = _operation_action(operation)
    expected_keys = _SUCCESS_TOP_LEVEL_KEYS.get(action)
    if expected_keys is None or frozenset(value) not in expected_keys:
        _reject(COMMAND_RESULT_INCONSISTENT)
    _validate_success_field_types(action, value)
    _validate_operation_output_contract(
        operation,
        action,
        value,
        plan=plan,
        domain=domain,
    )
    if action == ("character", "request", "validate"):
        return _character_request_selector(value, plan=plan, domain=domain)
    if action == ("research", "request", "validate"):
        return _research_request_selector(value, plan=plan, domain=domain)
    if action == ("runtime", "context"):
        return _selector_tree(
            value,
            plan=plan,
            domain=domain,
            string_shape_only=True,
            stable_string_keys=frozenset(
                {"character_id", "character_version", "stage"}
            ),
        )
    if action == ("runtime", "plan"):
        return _runtime_plan_selector(value, plan=plan, domain=domain)

    finding_message_paths = frozenset(
        {
            ("validation_report", "hard_failures", "*", "message"),
            ("validation_report", "advisory_findings", "*", "message"),
        }
    )
    omitted_by_action: dict[
        tuple[str, ...], frozenset[tuple[str, ...]]
    ] = {
        ("pack", "publication-check"): frozenset(
            {("blockers", "*", "message")}
        ),
        ("character", "draft", "validate"): finding_message_paths,
        ("character", "draft", "compile"): finding_message_paths,
        ("research", "workspace", "validate"): frozenset(
            finding_message_paths
            | {("validation_report", "blocking_reasons")}
        ),
        ("research", "bundle", "compile"): frozenset(
            {
                ("limitations",),
                ("blocking_reasons",),
                ("conflicts", "*", "scopes"),
                ("conflicts", "*", "resolution_rationale"),
            }
        ),
        ("research", "bundle", "validate"): frozenset(
            {
                ("limitations",),
                ("blocking_reasons",),
                ("conflicts", "*", "scopes"),
                ("conflicts", "*", "resolution_rationale"),
            }
        ),
        ("memory", "add"): frozenset(
            {
                ("memory_reference", "summary"),
                ("memory_reference", "localized_summaries"),
            }
        ),
        ("memory", "list"): frozenset(
            {
                ("memory_references", "*", "reference", "summary"),
                (
                    "memory_references", "*", "reference",
                    "localized_summaries",
                ),
            }
        ),
        ("runtime", "validate"): frozenset(
            {
                ("validation", "violations", "*", "message"),
                (
                    "validation", "violations", "*", "details",
                    "protected_span",
                ),
            }
        ),
    }
    namespace_paths_by_action: dict[
        tuple[str, ...], frozenset[tuple[str, ...]]
    ] = {
        ("pack", "compile"): frozenset({("path",)}),
        ("pack", "export"): frozenset({("path",)}),
        ("pack", "test"): frozenset({("path",)}),
        ("pack", "soft-eval"): frozenset({("path",)}),
        ("pack", "promote"): frozenset({("path",), ("bundle_path",)}),
        ("pack", "publication-check"): frozenset({("path",)}),
        ("character", "draft", "compile"): frozenset({("path",)}),
        ("research", "bundle", "compile"): frozenset({("path",)}),
    }
    return _selector_tree(
        value,
        plan=plan,
        domain=domain,
        omitted_paths=omitted_by_action.get(action, frozenset()),
        namespace_paths=namespace_paths_by_action.get(action, frozenset()),
    )


def _summarize_document(
    value: dict[str, Any],
    canonical: bytes,
    *,
    operation: ApprovedOperation,
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
    retain: bool,
) -> _ParsedDocument:
    error = value.get("error")
    error_keys: tuple[str, ...] | None = None
    error_code: object = None
    message_is_string = False
    retryable: object = None
    details_is_dict = False
    if type(error) is dict:
        error_keys = tuple(sorted(error))
        error_code = error.get("code")
        message_is_string = type(error.get("message")) is str
        retryable = error.get("retryable")
        details_is_dict = type(error.get("details")) is dict
    selector = (
        _success_selector_projection(
            operation,
            value,
            plan=plan,
            domain=domain,
        )
        if operation.expected_outcome == "success"
        else {"expected_outcome": "expected_refusal"}
    )
    selector_sha256, selector_paths = _selector_fingerprint(selector)
    selected_value_hashes: list[tuple[tuple[str, ...], str]] = [
        ((), sha256(canonical).hexdigest())
    ]
    if operation.expected_outcome == "success":
        member_by_action = {
            ("policy", "compile"): "policy",
            ("runtime", "plan"): "plan",
        }
        member = member_by_action.get(_operation_action(operation))
        if member is not None:
            if member not in value:
                _reject(COMMAND_RESULT_INCONSISTENT)
            selected_value_hashes.append(
                (
                    (member,),
                    sha256(_canonical_json_bytes(value[member])).hexdigest(),
                )
            )
    retained_bytes = canonical + b"\n" if retain else None
    return _ParsedDocument(
        canonical_sha256=sha256(
            retained_bytes if retained_bytes is not None else canonical
        ).hexdigest(),
        canonical_bytes=retained_bytes,
        selected_value_hashes=tuple(selected_value_hashes),
        shape_sha256=sha256(_canonical_json_bytes(_json_shape(value))).hexdigest(),
        selector_sha256=selector_sha256,
        selector_paths=selector_paths,
        top_level_keys=tuple(sorted(value)),
        ok=value.get("ok", _DISCARDED),
        error_keys=error_keys,
        error_code=error_code,
        error_message_is_string=message_is_string,
        error_retryable=retryable,
        error_details_is_dict=details_is_dict,
    )


def _note_decoder_buffer_size(_size: int) -> None:
    """Test observation seam for the largest retained document buffer."""


class _OutputCollector(_HashSink):
    def __init__(self, budget: _DomainBudget) -> None:
        super().__init__()
        self.budget = budget
        self._prefix = bytearray()

    def feed(self, value: bytes) -> None:
        self.budget.consume(len(value))
        if len(self._prefix) < 3:
            self._prefix.extend(value[: 3 - len(self._prefix)])
            if len(self._prefix) == 3 and bytes(self._prefix) == b"\xef\xbb\xbf":
                _reject(COMMAND_JSON_INVALID)
        super().feed(value)


class _TextOutputCollector(_OutputCollector):
    def feed(self, value: bytes) -> None:
        if self.length > _DOCUMENT_LIMIT_BYTES - len(value):
            _reject(COMMAND_OUTPUT_LIMIT_EXCEEDED)
        super().feed(value)

    def finish(self) -> tuple[_ParsedDocument, ...]:
        return ()


class _JsonOutputCollector(_OutputCollector):
    def __init__(
        self,
        budget: _DomainBudget,
        *,
        operations: tuple[ApprovedOperation, ...],
        plan: BoundCommandPlan,
        domain: Literal["raw", "retained"],
        retain: bool,
    ) -> None:
        super().__init__(budget)
        expected_documents = len(operations)
        if not 0 < expected_documents <= _DOCUMENTS_PER_COMMAND_LIMIT:
            _reject(COMMAND_JSON_COUNT_MISMATCH)
        self.expected_documents = expected_documents
        self.operations = operations
        self.plan = plan
        self.domain = domain
        self.retain = retain
        self.documents: list[_ParsedDocument] = []
        self._document: bytearray | None = None
        self._stack: list[int] = []
        self._in_string = False
        self._escaped = False
        self._seen_digests: set[str] = set()

    def _start_document(self, value: int) -> None:
        if value != 0x7B:
            _reject(COMMAND_JSON_INVALID)
        self._document = bytearray((value,))
        self._stack = [0x7D]
        self._in_string = False
        self._escaped = False

    def _append_document_byte(self, value: int) -> None:
        document = self._document
        if document is None:
            _reject(COMMAND_JSON_INVALID)
        if len(document) >= _DOCUMENT_LIMIT_BYTES:
            _reject(COMMAND_OUTPUT_LIMIT_EXCEEDED)
        document.append(value)
        _note_decoder_buffer_size(len(document))
        if self._in_string:
            if self._escaped:
                self._escaped = False
            elif value == 0x5C:
                self._escaped = True
            elif value == 0x22:
                self._in_string = False
            return
        if value == 0x22:
            self._in_string = True
            return
        if value == 0x7B:
            self._stack.append(0x7D)
        elif value == 0x5B:
            self._stack.append(0x5D)
        elif value in (0x7D, 0x5D):
            if not self._stack or self._stack[-1] != value:
                _reject(COMMAND_JSON_INVALID)
            self._stack.pop()
            if not self._stack:
                self._complete_document()
        if len(self._stack) > _JSON_DEPTH_LIMIT:
            _reject(COMMAND_JSON_INVALID)

    def _complete_document(self) -> None:
        document = self._document
        if document is None:
            _reject(COMMAND_JSON_INVALID)
        if len(self.documents) >= self.expected_documents:
            _reject(COMMAND_JSON_COUNT_MISMATCH)
        _note_decoder_buffer_size(len(document))
        self._document = None
        value = _decode_document(document)
        del document
        canonical = _canonical_json_bytes(value)
        digest = sha256(canonical).hexdigest()
        if digest in self._seen_digests:
            _reject(COMMAND_JSON_INVALID)
        self._seen_digests.add(digest)
        self.documents.append(
            _summarize_document(
                value,
                canonical,
                operation=self.operations[len(self.documents)],
                plan=self.plan,
                domain=self.domain,
                retain=self.retain,
            )
        )
        if len(self.documents) > self.expected_documents:
            _reject(COMMAND_JSON_COUNT_MISMATCH)
        self._stack = []
        self._in_string = False
        self._escaped = False

    def feed(self, value: bytes) -> None:
        super().feed(value)
        for byte in value:
            if self._document is None:
                if byte in _JSON_WHITESPACE:
                    continue
                self._start_document(byte)
                continue
            self._append_document_byte(byte)

    def finish(self) -> tuple[_ParsedDocument, ...]:
        if self._document is not None or len(self.documents) != self.expected_documents:
            _reject(COMMAND_JSON_COUNT_MISMATCH)
        return tuple(self.documents)


@dataclass(frozen=True)
class _StreamedString:
    field_start: int
    field_end: int
    field_utf8_bytes: int
    field_sha256: str
    output_utf8_bytes: int
    output_sha256: str
    value: str | None


def _emit_json_escape(
    cursor: _RangeCursor,
    raw_hash: Any,
    sink: _HashSink,
) -> None:
    escape = cursor.read_byte()
    raw_hash.update(bytes((escape,)))
    simple = {
        0x22: b'"',
        0x5C: b"\\",
        0x2F: b"/",
        0x62: b"\b",
        0x66: b"\f",
        0x6E: b"\n",
        0x72: b"\r",
        0x74: b"\t",
    }
    if escape in simple:
        sink.feed(simple[escape])
        return
    if escape != 0x75:
        _reject(COMMAND_JSON_INVALID)
    digits = cursor.read_exact(4)
    raw_hash.update(digits)
    try:
        first = int(digits.decode("ascii"), 16)
    except (UnicodeError, ValueError):
        _reject(COMMAND_JSON_INVALID)
    if 0xDC00 <= first <= 0xDFFF:
        _reject(COMMAND_JSON_INVALID)
    if 0xD800 <= first <= 0xDBFF:
        pair_prefix = cursor.read_exact(2)
        raw_hash.update(pair_prefix)
        if pair_prefix != b"\\u":
            _reject(COMMAND_JSON_INVALID)
        pair_digits = cursor.read_exact(4)
        raw_hash.update(pair_digits)
        try:
            second = int(pair_digits.decode("ascii"), 16)
        except (UnicodeError, ValueError):
            _reject(COMMAND_JSON_INVALID)
        if not 0xDC00 <= second <= 0xDFFF:
            _reject(COMMAND_JSON_INVALID)
        scalar = 0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00)
    else:
        scalar = first
    try:
        sink.feed(chr(scalar).encode("utf-8", errors="strict"))
    except UnicodeError:
        _reject(COMMAND_JSON_INVALID)


def _parse_json_string(
    cursor: _RangeCursor,
    *,
    sink: _HashSink,
    retain_value: bool,
) -> _StreamedString:
    field_start = cursor.absolute
    if cursor.read_byte() != 0x22:
        _reject(COMMAND_JSON_INVALID)
    raw_hash = sha256()
    raw_hash.update(b'"')
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    while True:
        run, special = cursor.take_string_plain_run()
        if run:
            raw_hash.update(run)
            try:
                decoder.decode(run, final=False)
            except UnicodeError:
                _reject(COMMAND_JSON_INVALID)
            sink.feed(run)
        if special is None:
            continue
        if special < 0x20:
            _reject(COMMAND_JSON_INVALID)
        if special == 0x22:
            try:
                decoder.decode(b"", final=True)
            except UnicodeError:
                _reject(COMMAND_JSON_INVALID)
            cursor.read_byte()
            raw_hash.update(b'"')
            break
        if special != 0x5C:
            _reject(COMMAND_JSON_INVALID)
        try:
            decoder.decode(b"", final=True)
        except UnicodeError:
            _reject(COMMAND_JSON_INVALID)
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        cursor.read_byte()
        raw_hash.update(b"\\")
        _emit_json_escape(cursor, raw_hash, sink)
    field_end = cursor.absolute
    value: str | None = None
    if retain_value:
        if type(sink) is not _ValueSink:
            _reject(COMMAND_JSON_INVALID)
        try:
            value = bytes(sink.value).decode("utf-8", errors="strict")
        except UnicodeError:
            _reject(COMMAND_JSON_INVALID)
    return _StreamedString(
        field_start=field_start,
        field_end=field_end,
        field_utf8_bytes=field_end - field_start,
        field_sha256=raw_hash.hexdigest(),
        output_utf8_bytes=sink.length,
        output_sha256=sink.digest,
        value=value,
    )


_KEPT_PATHS = frozenset(
    {
        ("type",),
        ("thread_id",),
        ("item",),
        ("item", "id"),
        ("item", "type"),
        ("item", "command"),
        ("item", "aggregated_output"),
        ("item", "exit_code"),
        ("item", "status"),
    }
)


def _parse_number(cursor: _RangeCursor) -> int | float:
    token = bytearray()
    allowed = frozenset(b"-+0123456789.eE")
    while cursor.absolute < cursor.end and cursor.peek_byte() in allowed:
        if len(token) >= 256:
            _reject(COMMAND_JSON_INVALID)
        token.append(cursor.read_byte())
    try:
        value = json.loads(bytes(token).decode("ascii"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        _reject(COMMAND_JSON_INVALID)
    if type(value) not in (int, float):
        _reject(COMMAND_JSON_INVALID)
    return value


def _parse_json_value(
    cursor: _RangeCursor,
    *,
    path: tuple[str, ...],
    retain: bool,
    output_sink: _HashSink | None,
    output_holder: list[_StreamedString],
    depth: int,
) -> object:
    if depth > _JSON_DEPTH_LIMIT:
        _reject(COMMAND_JSON_INVALID)
    cursor.skip_whitespace()
    value = cursor.peek_byte()
    if value == 0x7B:
        cursor.read_byte()
        result: dict[str, object] = {}
        keys: set[str] = set()
        cursor.skip_whitespace()
        if cursor.peek_byte() == 0x7D:
            cursor.read_byte()
            return result if retain else _DISCARDED
        while True:
            key_sink = _ValueSink(1024)
            key_token = _parse_json_string(
                cursor,
                sink=key_sink,
                retain_value=True,
            )
            key = key_token.value
            if key is None or key in keys:
                _reject(COMMAND_JSON_INVALID)
            keys.add(key)
            if len(keys) > _JSON_CONTAINER_ITEM_LIMIT:
                _reject(COMMAND_JSON_INVALID)
            cursor.skip_whitespace()
            if cursor.read_byte() != 0x3A:
                _reject(COMMAND_JSON_INVALID)
            child_path = (*path, key)
            child_retain = child_path in _KEPT_PATHS
            if child_path == ("item", "aggregated_output"):
                cursor.skip_whitespace()
                sink = output_sink if output_sink is not None else _HashSink()
                streamed = _parse_json_string(
                    cursor,
                    sink=sink,
                    retain_value=False,
                )
                output_holder.append(streamed)
                child = streamed
            else:
                child = _parse_json_value(
                    cursor,
                    path=child_path,
                    retain=child_retain,
                    output_sink=output_sink,
                    output_holder=output_holder,
                    depth=depth + 1,
                )
            if retain:
                result[key] = child
            cursor.skip_whitespace()
            delimiter = cursor.read_byte()
            if delimiter == 0x7D:
                break
            if delimiter != 0x2C:
                _reject(COMMAND_JSON_INVALID)
            cursor.skip_whitespace()
        return result if retain else _DISCARDED
    if value == 0x5B:
        cursor.read_byte()
        result_list: list[object] = []
        count = 0
        cursor.skip_whitespace()
        if cursor.peek_byte() == 0x5D:
            cursor.read_byte()
            return result_list if retain else _DISCARDED
        while True:
            item = _parse_json_value(
                cursor,
                path=path,
                retain=retain,
                output_sink=output_sink,
                output_holder=output_holder,
                depth=depth + 1,
            )
            count += 1
            if count > _JSON_CONTAINER_ITEM_LIMIT:
                _reject(COMMAND_JSON_INVALID)
            if retain:
                result_list.append(item)
            cursor.skip_whitespace()
            delimiter = cursor.read_byte()
            if delimiter == 0x5D:
                break
            if delimiter != 0x2C:
                _reject(COMMAND_JSON_INVALID)
            cursor.skip_whitespace()
        return result_list if retain else _DISCARDED
    if value == 0x22:
        sink: _HashSink = (
            _ValueSink(_METADATA_STRING_LIMIT_BYTES) if retain else _HashSink()
        )
        parsed = _parse_json_string(cursor, sink=sink, retain_value=retain)
        return parsed.value if retain else _DISCARDED
    if value in b"-0123456789":
        number = _parse_number(cursor)
        return number if retain else _DISCARDED
    for literal, decoded in ((b"true", True), (b"false", False), (b"null", None)):
        if value == literal[0]:
            if cursor.read_exact(len(literal)) != literal:
                _reject(COMMAND_JSON_INVALID)
            return decoded if retain else _DISCARDED
    _reject(COMMAND_JSON_INVALID)


def _parse_event_line(
    reader: _SessionReader,
    start: int,
    *,
    output_sink: _HashSink | None,
) -> tuple[dict[str, object], _StreamedString | None, int]:
    cursor = _RangeCursor(
        reader,
        start,
        reader.size,
        stop_at_lf=True,
    )
    if cursor.peek_byte() != 0x7B:
        _reject(COMMAND_CAPTURE_INVALID)
    output_holder: list[_StreamedString] = []
    value = _parse_json_value(
        cursor,
        path=(),
        retain=True,
        output_sink=output_sink,
        output_holder=output_holder,
        depth=0,
    )
    if (
        not cursor.finish_line()
        or type(value) is not dict
        or len(output_holder) > 1
    ):
        _reject(COMMAND_CAPTURE_INVALID)
    return value, output_holder[0] if output_holder else None, cursor.end


@dataclass(frozen=True)
class _DomainCommand:
    event_id: str
    started_event_ordinal: int
    completed_event_ordinal: int
    exit_code: int
    output_utf8_bytes: int
    output_sha256: str
    documents: tuple[_ParsedDocument, ...]


def _operational_operations(
    decision: CommandPolicyDecision,
) -> tuple[ApprovedOperation, ...]:
    try:
        return tuple(
            operation
            for operation in decision.operations
            if operation.category == "kokoro_cli" and operation.operational_json
        )
    except (AttributeError, TypeError):
        _reject(COMMAND_CAPTURE_INVALID)


def _expected_rendered_binding(
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
) -> tuple[int, str]:
    if domain == "raw":
        return plan.raw_rendered_utf8_bytes, plan.raw_rendered_sha256
    return plan.retained_rendered_utf8_bytes, plan.retained_rendered_sha256


def _validate_event_command(
    command: object,
    *,
    plan: BoundCommandPlan,
    domain: Literal["raw", "retained"],
) -> str:
    if type(command) is not str or not command:
        _reject(COMMAND_CAPTURE_INVALID)
    try:
        encoded = command.encode("utf-8", errors="strict")
    except UnicodeError:
        _reject(COMMAND_CAPTURE_INVALID)
    expected_size, expected_digest = _expected_rendered_binding(plan, domain)
    if len(encoded) != expected_size or sha256(encoded).hexdigest() != expected_digest:
        _reject(COMMAND_CAPTURE_INVALID)
    return command


def _validate_completed_capture(
    capture: CompletedOutputCapture,
    *,
    identity: SessionFileIdentity,
    ordinal: int,
    line_span: tuple[int, int],
    item: dict[str, object],
    output: _StreamedString,
) -> None:
    if (
        capture.session_identity != identity
        or capture.completed_event_ordinal != ordinal
        or (capture.event_start, capture.event_end) != line_span
        or capture.event_id != item.get("id")
        or capture.exit_code != item.get("exit_code")
        or capture.output_field_start != output.field_start
        or capture.output_field_end != output.field_end
        or capture.output_field_utf8_bytes != output.field_utf8_bytes
        or capture.output_field_sha256 != output.field_sha256
        or capture.output_utf8_bytes != output.output_utf8_bytes
        or capture.output_sha256 != output.output_sha256
    ):
        _reject(COMMAND_CAPTURE_INVALID)


def _scan_domain(
    reader: _SessionReader,
    pairs: tuple[CommandCapturePair, ...],
    *,
    domain: Literal["raw", "retained"],
    session_id: str,
    identity: SessionFileIdentity,
    budget: _DomainBudget,
) -> tuple[_DomainCommand, ...]:
    by_started: dict[int, CommandCapturePair] = {}
    by_completed: dict[int, CommandCapturePair] = {}
    for pair in pairs:
        capture = pair.raw_capture if domain == "raw" else pair.retained_capture
        if (
            capture.domain != domain
            or capture.session_root != reader.session_root
            or capture.session_path != reader.session_path
            or capture.session_identity != identity
            or capture.started_event_ordinal in by_started
            or capture.completed_event_ordinal in by_completed
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        by_started[capture.started_event_ordinal] = pair
        by_completed[capture.completed_event_ordinal] = pair

    pending: dict[str, tuple[int, str, int]] = {}
    completed: dict[int, _DomainCommand] = {}
    thread_ids: list[str] = []
    next_line_start = 0
    event_count = 0
    while next_line_start < reader.size:
        ordinal = event_count
        pair = by_completed.get(ordinal)
        collector: _OutputCollector | None = None
        if pair is not None:
            operations = _operational_operations(pair.decision)
            count = len(operations)
            collector = (
                _TextOutputCollector(budget)
                if count == 0
                else _JsonOutputCollector(
                    budget,
                    operations=operations,
                    plan=pair.plan,
                    domain=domain,
                    retain=domain == "retained",
                )
            )
        event, output, line_end = _parse_event_line(
            reader,
            next_line_start,
            output_sink=collector if collector is not None else _EmptyOutputSink(),
        )
        line_span = (next_line_start, line_end)
        next_line_start = line_end + 1
        event_count += 1
        event_type = event.get("type")
        if event_type == "thread.started":
            if set(event) != {"type", "thread_id"} or type(event.get("thread_id")) is not str:
                _reject(COMMAND_CAPTURE_INVALID)
            thread_ids.append(event["thread_id"])
            continue
        item = event.get("item")
        if (
            type(item) is dict
            and item.get("type") == "command_execution"
            and event_type not in ("item.started", "item.completed")
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        if event_type not in ("item.started", "item.completed"):
            continue
        if type(item) is not dict or item.get("type") != "command_execution":
            continue
        if set(event) != {"type", "item"} or set(item) != _COMMAND_ITEM_FIELDS:
            _reject(COMMAND_CAPTURE_INVALID)
        event_id = item.get("id")
        if type(event_id) is not str or _EVENT_ID.fullmatch(event_id) is None:
            _reject(COMMAND_CAPTURE_INVALID)
        expected_pair = (
            by_started.get(ordinal)
            if event_type == "item.started"
            else by_completed.get(ordinal)
        )
        if expected_pair is None:
            _reject(COMMAND_CAPTURE_INVALID)
        capture = (
            expected_pair.raw_capture
            if domain == "raw"
            else expected_pair.retained_capture
        )
        command = _validate_event_command(
            item.get("command"),
            plan=expected_pair.plan,
            domain=domain,
        )
        if output is None:
            _reject(COMMAND_CAPTURE_INVALID)
        if event_type == "item.started":
            if (
                item.get("aggregated_output") is not output
                or output.output_utf8_bytes != 0
                or item.get("exit_code") is not None
                or item.get("status") != "in_progress"
                or event_id in pending
                or capture.event_id != event_id
                or capture.started_event_ordinal != ordinal
            ):
                _reject(COMMAND_CAPTURE_INVALID)
            pending[event_id] = (ordinal, command, expected_pair.command_index)
            continue
        exit_code = item.get("exit_code")
        if (
            type(exit_code) is not int
            or item.get("status") != ("completed" if exit_code == 0 else "failed")
            or item.get("aggregated_output") is not output
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        started = pending.pop(event_id, None)
        if (
            started is None
            or started
            != (capture.started_event_ordinal, command, expected_pair.command_index)
            or expected_pair.command_index in completed
            or collector is None
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        _validate_completed_capture(
            capture,
            identity=identity,
            ordinal=ordinal,
            line_span=line_span,
            item=item,
            output=output,
        )
        completed[expected_pair.command_index] = _DomainCommand(
            event_id=event_id,
            started_event_ordinal=started[0],
            completed_event_ordinal=ordinal,
            exit_code=exit_code,
            output_utf8_bytes=collector.length,
            output_sha256=collector.digest,
            documents=collector.finish(),
        )
    if event_count == 0 or next_line_start != reader.size:
        _reject(COMMAND_CAPTURE_INVALID)
    session_bound = thread_ids == [session_id] or (
        not thread_ids and reader.session_root.name == session_id
    )
    if (
        pending
        or not session_bound
        or tuple(sorted(completed)) != tuple(range(len(pairs)))
    ):
        _reject(COMMAND_CAPTURE_INVALID)
    return tuple(completed[index] for index in range(len(pairs)))


def _capture_fingerprint(capture: CompletedOutputCapture) -> tuple[object, ...]:
    if type(capture) is not CompletedOutputCapture:
        _reject(COMMAND_CAPTURE_INVALID)
    identity = capture.session_identity
    return (
        id(capture),
        capture.domain,
        str(capture.session_root),
        str(capture.session_path),
        capture.started_event_ordinal,
        capture.completed_event_ordinal,
        capture.event_id,
        capture.event_start,
        capture.event_end,
        capture.output_field_start,
        capture.output_field_end,
        capture.exit_code,
        capture.output_field_utf8_bytes,
        capture.output_field_sha256,
        capture.output_utf8_bytes,
        capture.output_sha256,
        id(identity),
        tuple(_identity_record(identity).values()),
    )


def _pair_fingerprint(pair: CommandCapturePair) -> tuple[object, ...]:
    if type(pair) is not CommandCapturePair:
        _reject(COMMAND_CAPTURE_INVALID)
    return (
        id(pair),
        pair.command_index,
        id(pair.plan),
        pair.plan.normalized_plan_sha256,
        pair.plan.namespace_manifest_sha256,
        id(pair.decision),
        pair.decision.canonical_sha256,
        _capture_fingerprint(pair.raw_capture),
        _capture_fingerprint(pair.retained_capture),
    )


def _validate_preflight(
    session_id: str,
    commands: tuple[CommandCapturePair, ...],
    *,
    raw_session_identity: SessionFileIdentity,
    retained_session_identity: SessionFileIdentity,
) -> tuple[tuple[object, ...], ...]:
    if (
        type(session_id) is not str
        or _SESSION_ID.fullmatch(session_id) is None
        or type(commands) is not tuple
        or not commands
        or type(raw_session_identity) is not SessionFileIdentity
        or type(retained_session_identity) is not SessionFileIdentity
    ):
        _reject(COMMAND_CAPTURE_INVALID)
    raw_session_identity.__post_init__()
    retained_session_identity.__post_init__()
    if raw_session_identity == retained_session_identity:
        _reject(COMMAND_CAPTURE_INVALID)

    fingerprints: list[tuple[object, ...]] = []
    raw_location: tuple[Path, Path] | None = None
    retained_location: tuple[Path, Path] | None = None
    seen_pairs: set[int] = set()
    seen_captures: set[int] = set()
    previous_completed = -1
    for index, pair in enumerate(commands):
        if type(pair) is not CommandCapturePair or id(pair) in seen_pairs:
            _reject(COMMAND_CAPTURE_INVALID)
        seen_pairs.add(id(pair))
        pair.__post_init__()
        if pair.command_index != index:
            _reject(COMMAND_CAPTURE_INVALID)
        try:
            pair.plan.__post_init__()
            _authenticate_bound_namespaces(pair.plan.namespaces)
            _authenticate_command_policy_decision(pair.decision, plan=pair.plan)
        except RuntimeError:
            raise
        except Exception:
            _reject(COMMAND_CAPTURE_INVALID)
        operations = _operational_operations(pair.decision)
        if len(operations) > _DOCUMENTS_PER_COMMAND_LIMIT:
            _reject(COMMAND_OUTPUT_LIMIT_EXCEEDED)
        if operations and pair.decision.record_class != "operational_json":
            _reject(COMMAND_CAPTURE_INVALID)
        if not operations and pair.decision.record_class not in (
            "read_only_pipeline",
            "help_discovery",
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        raw = pair.raw_capture
        retained = pair.retained_capture
        for capture in (raw, retained):
            if id(capture) in seen_captures:
                _reject(COMMAND_CAPTURE_INVALID)
            seen_captures.add(id(capture))
            capture.__post_init__()
        if (
            raw.session_identity != raw_session_identity
            or retained.session_identity != retained_session_identity
            or raw.event_id != retained.event_id
            or raw.started_event_ordinal != retained.started_event_ordinal
            or raw.completed_event_ordinal != retained.completed_event_ordinal
            or raw.exit_code != retained.exit_code
            or raw.started_event_ordinal <= previous_completed
            or raw.event_end <= raw.event_start
            or retained.event_end <= retained.event_start
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        previous_completed = raw.completed_event_ordinal
        current_raw_location = (raw.session_root, raw.session_path)
        current_retained_location = (retained.session_root, retained.session_path)
        if raw_location is None:
            raw_location = current_raw_location
            retained_location = current_retained_location
        elif (
            current_raw_location != raw_location
            or current_retained_location != retained_location
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        fingerprints.append(_pair_fingerprint(pair))
    if raw_location is None or retained_location is None or raw_location == retained_location:
        _reject(COMMAND_CAPTURE_INVALID)
    return tuple(fingerprints)


def _validate_inputs_unchanged(
    commands: tuple[CommandCapturePair, ...],
    fingerprints: tuple[tuple[object, ...], ...],
) -> None:
    try:
        current = tuple(_pair_fingerprint(pair) for pair in commands)
    except Exception:
        _reject(COMMAND_CAPTURE_INVALID)
    if current != fingerprints:
        _reject(COMMAND_CAPTURE_INVALID)
    for pair in commands:
        try:
            pair.plan.__post_init__()
            _authenticate_bound_namespaces(pair.plan.namespaces)
            _authenticate_command_policy_decision(pair.decision, plan=pair.plan)
        except RuntimeError:
            raise
        except Exception:
            _reject(COMMAND_CAPTURE_INVALID)


def _validate_refusal_document(
    document: _ParsedDocument,
    *,
    domain: Literal["raw", "retained"],
) -> None:
    expected_error_keys = (
        {("code",), ("code", "message")}
        if domain == "raw"
        else {("code",)}
    )
    if (
        document.top_level_keys != ("error", "ok")
        or document.ok is not False
        or document.error_keys not in expected_error_keys
        or document.error_code != "KARC_EXPORT_OUTPUT_EXISTS"
        or (
            document.error_keys == ("code", "message")
            and not document.error_message_is_string
        )
    ):
        _reject(COMMAND_RESULT_INCONSISTENT)


def _is_frozen_expected_refusal_operation(operation: ApprovedOperation) -> bool:
    if (
        type(operation) is not ApprovedOperation
        or operation.category != "kokoro_cli"
        or operation.operational_json is not True
        or operation.expected_outcome != "expected_refusal"
        or len(operation.argv) < 4
        or tuple(value.casefold() for value in operation.argv[1:3])
        != ("pack", "export")
        or len(operation.declared_output_paths) != 1
    ):
        return False
    declared = PureWindowsPath(operation.declared_output_paths[0])
    if (
        declared.is_absolute()
        or declared.anchor
        or tuple(part.casefold() for part in declared.parts)
        != ("outputs", "existing.karc")
    ):
        return False
    out_positions = tuple(
        index
        for index, value in enumerate(operation.argv)
        if value.casefold() == "--out"
    )
    if len(out_positions) != 1 or out_positions[0] + 1 >= len(operation.argv):
        return False
    rendered_output = PureWindowsPath(operation.argv[out_positions[0] + 1])
    return (
        not rendered_output.is_absolute()
        and not rendered_output.anchor
        and tuple(part.casefold() for part in rendered_output.parts)
        == ("outputs", "existing.karc")
    )


def _bound_results_for_command(
    pair: CommandCapturePair,
    raw: _DomainCommand,
    retained: _DomainCommand,
) -> tuple[BoundCliResult, ...]:
    operations = _operational_operations(pair.decision)
    if (
        raw.event_id != retained.event_id
        or raw.started_event_ordinal != retained.started_event_ordinal
        or raw.completed_event_ordinal != retained.completed_event_ordinal
        or raw.exit_code != retained.exit_code
        or len(raw.documents) != len(operations)
        or len(retained.documents) != len(operations)
    ):
        _reject(COMMAND_JSON_COUNT_MISMATCH)
    if not operations:
        if raw.exit_code != 0:
            _reject(COMMAND_RESULT_INCONSISTENT)
        return ()
    refusals = tuple(
        operation
        for operation in operations
        if operation.expected_outcome == "expected_refusal"
    )
    if refusals:
        if len(operations) != 1 or len(refusals) != 1 or raw.exit_code == 0:
            _reject(COMMAND_RESULT_INCONSISTENT)
    elif raw.exit_code != 0:
        _reject(COMMAND_RESULT_INCONSISTENT)

    results: list[BoundCliResult] = []
    for operation, raw_document, retained_document in zip(
        operations,
        raw.documents,
        retained.documents,
    ):
        if (
            raw_document.top_level_keys != retained_document.top_level_keys
            or raw_document.ok is not retained_document.ok
            or retained_document.canonical_bytes is None
        ):
            _reject(COMMAND_RESULT_INCONSISTENT)
        if operation.expected_outcome == "success":
            try:
                selectors_match = (
                    raw_document.selector_sha256
                    == retained_document.selector_sha256
                    and _selector_paths_equivalent(
                        raw_document.selector_paths,
                        retained_document.selector_paths,
                        plan=pair.plan,
                    )
                )
            except RuntimeError:
                _reject(COMMAND_RESULT_INCONSISTENT)
            if (
                raw.exit_code != 0
                or raw_document.shape_sha256 != retained_document.shape_sha256
                or not selectors_match
                or raw_document.ok is not True
                or retained_document.ok is not True
                or "error" in raw_document.top_level_keys
            ):
                _reject(COMMAND_RESULT_INCONSISTENT)
            outcome: Literal["success", "expected_refusal"] = "success"
        elif operation.expected_outcome == "expected_refusal":
            if not _is_frozen_expected_refusal_operation(operation):
                _reject(COMMAND_RESULT_INCONSISTENT)
            _validate_refusal_document(raw_document, domain="raw")
            _validate_refusal_document(retained_document, domain="retained")
            outcome = "expected_refusal"
        else:
            _reject(COMMAND_RESULT_INCONSISTENT)
        results.append(
            BoundCliResult(
                operation_index=operation.index,
                argv=tuple(operation.argv),
                raw_document_sha256=raw_document.canonical_sha256,
                retained_document_bytes=retained_document.canonical_bytes,
                retained_document_sha256=retained_document.canonical_sha256,
                exit_code=raw.exit_code,
                outcome=outcome,
            )
        )
    return tuple(results)


def _make_command_evidence(
    pair: CommandCapturePair,
    raw: _DomainCommand,
    retained: _DomainCommand,
) -> BoundCommandEvidence:
    results = _bound_results_for_command(pair, raw, retained)
    base = {
        "command_index": pair.command_index,
        "event_id": raw.event_id,
        "started_event_ordinal": raw.started_event_ordinal,
        "completed_event_ordinal": raw.completed_event_ordinal,
        "plan_sha256": pair.plan.normalized_plan_sha256,
        "namespace_manifest_sha256": pair.plan.namespace_manifest_sha256,
        "decision_sha256": pair.decision.canonical_sha256,
        "record_class": pair.decision.record_class,
        "raw_output": {
            "utf8_bytes": raw.output_utf8_bytes,
            "sha256": raw.output_sha256,
        },
        "retained_output": {
            "utf8_bytes": retained.output_utf8_bytes,
            "sha256": retained.output_sha256,
        },
        "results": [_result_record(result) for result in results],
    }
    return BoundCommandEvidence(
        command_index=pair.command_index,
        event_id=raw.event_id,
        started_event_ordinal=raw.started_event_ordinal,
        completed_event_ordinal=raw.completed_event_ordinal,
        plan_sha256=pair.plan.normalized_plan_sha256,
        namespace_manifest_sha256=pair.plan.namespace_manifest_sha256,
        decision_sha256=pair.decision.canonical_sha256,
        record_class=pair.decision.record_class,
        raw_output_utf8_bytes=raw.output_utf8_bytes,
        raw_output_sha256=raw.output_sha256,
        retained_output_utf8_bytes=retained.output_utf8_bytes,
        retained_output_sha256=retained.output_sha256,
        results=results,
        canonical_sha256=sha256(_canonical_json_bytes(base)).hexdigest(),
    )


def _make_operation_provenance_for_command(
    pair: CommandCapturePair,
    raw: _DomainCommand,
    retained: _DomainCommand,
    evidence: BoundCommandEvidence,
) -> tuple[_OperationProvenance, ...]:
    operational = _operational_operations(pair.decision)
    if (
        len(raw.documents) != len(operational)
        or len(retained.documents) != len(operational)
    ):
        _reject(COMMAND_JSON_COUNT_MISMATCH)
    results = {result.operation_index: result for result in evidence.results}
    documents = {
        operation.index: (raw_document, retained_document)
        for operation, raw_document, retained_document in zip(
            operational,
            raw.documents,
            retained.documents,
            strict=True,
        )
    }
    values: list[_OperationProvenance] = []
    for operation in pair.decision.operations:
        if operation.operational_json:
            result = results.get(operation.index)
            document_pair = documents.get(operation.index)
            if (
                result is None
                or document_pair is None
                or result.argv != operation.argv
            ):
                _reject(COMMAND_RESULT_INCONSISTENT)
            raw_document, retained_document = document_pair
            raw_hashes = raw_document.selected_value_hashes
            retained_hashes = retained_document.selected_value_hashes
            if tuple(selector for selector, _digest in raw_hashes) != tuple(
                selector for selector, _digest in retained_hashes
            ):
                _reject(COMMAND_RESULT_INCONSISTENT)
            selected_values = tuple(
                _SelectedValueProvenance(
                    selector=tuple(list(raw_selector)),
                    raw_sha256=raw_sha256,
                    retained_sha256=retained_sha256,
                )
                for (raw_selector, raw_sha256), (
                    _retained_selector,
                    retained_sha256,
                ) in zip(raw_hashes, retained_hashes, strict=True)
            )
            outcome: Literal["success", "expected_refusal", "none"] = result.outcome
        else:
            if operation.index in results or operation.index in documents:
                _reject(COMMAND_RESULT_INCONSISTENT)
            selected_values = ()
            outcome = "none"
        values.append(
            _OperationProvenance(
                command_index=pair.command_index,
                operation_index=operation.index,
                argv=tuple(list(operation.argv)),
                category=operation.category,
                outcome=outcome,
                declared_output_paths=tuple(list(operation.declared_output_paths)),
                selected_values=selected_values,
            )
        )
    return tuple(values)


def _detach_session_operation_provenance(
    value: _SessionOperationProvenance,
) -> _SessionOperationProvenance:
    if type(value) is not _SessionOperationProvenance:
        _reject(COMMAND_CAPTURE_INVALID)
    value.__post_init__()
    detached = _SessionOperationProvenance(
        raw_session_sha256=value.raw_session_sha256,
        retained_session_sha256=value.retained_session_sha256,
        filesystem=value.filesystem,
        operations=tuple(
            _OperationProvenance(
                command_index=operation.command_index,
                operation_index=operation.operation_index,
                argv=tuple(list(operation.argv)),
                category=operation.category,
                outcome=operation.outcome,
                declared_output_paths=tuple(list(operation.declared_output_paths)),
                selected_values=tuple(
                    _SelectedValueProvenance(
                        selector=tuple(list(selected.selector)),
                        raw_sha256=selected.raw_sha256,
                        retained_sha256=selected.retained_sha256,
                    )
                    for selected in operation.selected_values
                ),
            )
            for operation in value.operations
        ),
    )
    detached.__post_init__()
    return detached


def _register_bound_session(
    value: BoundSessionCommandEvidence,
    provenance: _SessionOperationProvenance,
) -> None:
    if type(provenance) is not _SessionOperationProvenance:
        _reject(COMMAND_CAPTURE_INVALID)
    trusted_provenance = _detach_session_operation_provenance(provenance)
    key = id(value)

    def cleanup(reference: weakref.ReferenceType[BoundSessionCommandEvidence]) -> None:
        with _BOUND_SESSION_REGISTRY_LOCK:
            registered = _BOUND_SESSION_REGISTRY.get(key)
            if registered is not None and registered[0] is reference:
                del _BOUND_SESSION_REGISTRY[key]

    reference = weakref.ref(value, cleanup)
    with _BOUND_SESSION_REGISTRY_LOCK:
        if key in _BOUND_SESSION_REGISTRY:
            _reject(COMMAND_CAPTURE_INVALID)
        _BOUND_SESSION_REGISTRY[key] = (
            reference,
            value.canonical_sha256,
            trusted_provenance,
        )


def _registered_session_operation_provenance(
    value: BoundSessionCommandEvidence,
) -> _SessionOperationProvenance:
    if type(value) is not BoundSessionCommandEvidence:
        _reject(COMMAND_CAPTURE_INVALID)
    value.__post_init__()
    with _BOUND_SESSION_REGISTRY_LOCK:
        registered = _BOUND_SESSION_REGISTRY.get(id(value))
        if (
            registered is None
            or registered[0]() is not value
            or registered[1] != value.canonical_sha256
        ):
            _reject(COMMAND_CAPTURE_INVALID)
        provenance = registered[2]
    provenance.__post_init__()
    return provenance


def _authenticate_bound_session_command_evidence(
    value: BoundSessionCommandEvidence,
) -> None:
    _registered_session_operation_provenance(value)


def _authenticated_session_operation_provenance(
    value: BoundSessionCommandEvidence,
) -> _SessionOperationProvenance:
    """Return fresh compact metadata for an exact authenticated evidence object."""

    return _detach_session_operation_provenance(
        _registered_session_operation_provenance(value)
    )


def _authorized_session_filesystem(
    commands: tuple[CommandCapturePair, ...],
) -> BoundFilesystemEvidence | None:
    filesystems = tuple(
        _authenticated_command_policy_filesystem(
            pair.decision,
            plan=pair.plan,
        )
        for pair in commands
    )
    present = tuple(value for value in filesystems if value is not None)
    if not present:
        return None
    selected = present[0]
    if len(present) != len(filesystems) or any(
        value is not selected for value in present
    ):
        _reject(COMMAND_CAPTURE_INVALID)
    return selected


def bind_session_cli_results(
    session_id: str,
    commands: tuple[CommandCapturePair, ...],
    *,
    raw_session_identity: SessionFileIdentity,
    retained_session_identity: SessionFileIdentity,
) -> BoundSessionCommandEvidence:
    raw_identity_snapshot = _detach_session_identity(raw_session_identity)
    retained_identity_snapshot = _detach_session_identity(retained_session_identity)
    fingerprints = _validate_preflight(
        session_id,
        commands,
        raw_session_identity=raw_session_identity,
        retained_session_identity=retained_session_identity,
    )
    filesystem = _authorized_session_filesystem(commands)
    first = commands[0]
    raw_budget = _DomainBudget()
    retained_budget = _DomainBudget()
    with _SessionReader(
        domain="raw",
        session_root=first.raw_capture.session_root,
        session_path=first.raw_capture.session_path,
        expected_identity=raw_identity_snapshot,
    ) as raw_reader, _SessionReader(
        domain="retained",
        session_root=first.retained_capture.session_root,
        session_path=first.retained_capture.session_path,
        expected_identity=retained_identity_snapshot,
    ) as retained_reader:
        raw_commands = _scan_domain(
            raw_reader,
            commands,
            domain="raw",
            session_id=session_id,
            identity=raw_identity_snapshot,
            budget=raw_budget,
        )
        retained_commands = _scan_domain(
            retained_reader,
            commands,
            domain="retained",
            session_id=session_id,
            identity=retained_identity_snapshot,
            budget=retained_budget,
        )
        raw_session_sha256 = raw_reader.source_sha256
        retained_session_sha256 = retained_reader.source_sha256
    _validate_inputs_unchanged(commands, fingerprints)
    if _authorized_session_filesystem(commands) is not filesystem:
        _reject(COMMAND_CAPTURE_INVALID)
    if (
        _detach_session_identity(raw_session_identity) != raw_identity_snapshot
        or _detach_session_identity(retained_session_identity)
        != retained_identity_snapshot
    ):
        _reject(COMMAND_CAPTURE_INVALID)
    evidence_commands = tuple(
        _make_command_evidence(pair, raw, retained)
        for pair, raw, retained in zip(commands, raw_commands, retained_commands)
    )
    document = _session_record(
        session_id=session_id,
        raw_identity=raw_identity_snapshot,
        retained_identity=retained_identity_snapshot,
        commands=evidence_commands,
        raw_bytes=raw_budget.consumed,
        retained_bytes=retained_budget.consumed,
    )
    canonical = _canonical_json_bytes(document)
    result = BoundSessionCommandEvidence(
        version=_SESSION_EVIDENCE_VERSION,
        session_id=session_id,
        raw_session_identity=raw_identity_snapshot,
        retained_session_identity=retained_identity_snapshot,
        commands=evidence_commands,
        raw_bytes_consumed=raw_budget.consumed,
        retained_bytes_consumed=retained_budget.consumed,
        canonical_bytes=canonical,
        canonical_sha256=sha256(canonical).hexdigest(),
    )
    operation_provenance = _SessionOperationProvenance(
        raw_session_sha256=raw_session_sha256,
        retained_session_sha256=retained_session_sha256,
        filesystem=filesystem,
        operations=tuple(
            operation
            for pair, raw, retained, evidence in zip(
                commands,
                raw_commands,
                retained_commands,
                evidence_commands,
                strict=True,
            )
            for operation in _make_operation_provenance_for_command(
                pair,
                raw,
                retained,
                evidence,
            )
        ),
    )
    _register_bound_session(result, operation_provenance)
    _authenticate_bound_session_command_evidence(result)
    return result
