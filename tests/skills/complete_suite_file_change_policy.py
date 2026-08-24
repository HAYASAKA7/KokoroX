from __future__ import annotations

import ctypes
from ctypes import wintypes
from collections.abc import Callable
from dataclasses import dataclass
from functools import cmp_to_key
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import threading
from typing import Any, Literal, NoReturn
import weakref

from jsonschema import Draft202012Validator

from complete_suite_command_plan import (
    FilesystemObjectIdentity,
    _ByHandleFileInformation,
    _FileAttributeTagInformation,
    _IoStatusBlock,
    _ObjectAttributes,
    _UnicodeString,
    _observe_namespace_root,
    _observe_plain_file,
    _windows_ordinal_equal,
    _windows_path_parts_equal,
)
from complete_suite_command_policy import (
    BoundFilesystemEvidence,
    FilesystemRootSnapshot,
    FilesystemSnapshotEntry,
    _authenticate_filesystem_evidence,
    _windows_ordinal_compare,
)
from complete_suite_sanitization import sanitize_artifact
from kokoroarc.errors import KokoroError
from kokoroarc.packs.loader import (
    load_source_pack_from_contents,
    parse_yaml_bytes,
)
from kokoroarc.policy.compiler import normalize_policy
from kokoroarc.runtime.validation import validate_rendered_output
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.corpus import (
    CorpusLimits,
    load_test_corpus_from_contents,
)


FILE_CHANGE_SESSION_INVALID = "FILE_CHANGE_SESSION_INVALID"
FILE_CHANGE_DOMAIN_INVALID = "FILE_CHANGE_DOMAIN_INVALID"
FILE_CHANGE_ROOT_BINDING_INVALID = "FILE_CHANGE_ROOT_BINDING_INVALID"
FILE_CHANGE_EVENT_TYPE_INVALID = "FILE_CHANGE_EVENT_TYPE_INVALID"
FILE_CHANGE_LIFECYCLE_INVALID = "FILE_CHANGE_LIFECYCLE_INVALID"
FILE_CHANGE_KIND_INVALID = "FILE_CHANGE_KIND_INVALID"
FILE_CHANGE_PATH_INVALID = "FILE_CHANGE_PATH_INVALID"
FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED = "FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"
FILE_CHANGE_POLICY_CONTEXT_INVALID = "FILE_CHANGE_POLICY_CONTEXT_INVALID"
FILE_CHANGE_TOPOLOGY_MISMATCH = "FILE_CHANGE_TOPOLOGY_MISMATCH"
FILE_CHANGE_TRANSITION_INVALID = "FILE_CHANGE_TRANSITION_INVALID"
FILE_CHANGE_PATH_POLICY_INVALID = "FILE_CHANGE_PATH_POLICY_INVALID"
FILE_CHANGE_CONTENT_INVALID = "FILE_CHANGE_CONTENT_INVALID"
FILE_CHANGE_SANITIZER_INVALID = "FILE_CHANGE_SANITIZER_INVALID"
FILE_CHANGE_SCHEMA_ROLE_INVALID = "FILE_CHANGE_SCHEMA_ROLE_INVALID"
FILE_CHANGE_BOUND_VALUE_INVALID = "FILE_CHANGE_BOUND_VALUE_INVALID"

_POLICY_VERSION = "complete-suite-file-change-policy-v1"
_PLAN_VERSION = "complete-suite-file-change-plan-v1"
_MAX_SESSION_BYTES = 64 * 1024 * 1024
_MAX_SESSION_LINES = 50_000
_MAX_LIFECYCLES = 64
_MAX_TRANSITION_ENTRIES = 256
_MAX_UNIQUE_DOCUMENTS = 128
_MAX_DOCUMENT_BYTES = 262_144
_MAX_RAW_CONTENT_BYTES = 32 * 1024 * 1024
_MAX_RETAINED_CONTENT_BYTES = 32 * 1024 * 1024
_MAX_COMBINED_CONTENT_BYTES = 64 * 1024 * 1024
_MAX_SOURCE_PACK_FILES = 128
_MAX_SOURCE_FILE_BYTES = 256_000
_MAX_SOURCE_PACK_BYTES = 2_000_000
_MAX_SOURCE_DEPTH = 6
_MAX_CORPUS_FILE_BYTES = 64_000
_MAX_CORPUS_BYTES = 192_000
_MAX_LITERAL_UTF8_BYTES = 4096
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"<[a-z][a-z0-9_-]{0,31}>")
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_WILDCARDS = frozenset("*?[]")
_WINDOWS_ILLEGAL = frozenset('<>"|')
_WINDOWS_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "conin$",
        "conout$",
        *(f"com{value}" for value in range(1, 10)),
        *(f"lpt{value}" for value in range(1, 10)),
    }
)
_PASSIVE_ITEM_TYPES = frozenset(
    {"agent_message", "final", "plan", "reasoning", "todo_list"}
)
_METADATA_EVENT_TYPES = frozenset(
    {"thread.started", "turn.started", "turn.completed"}
)
_BOUND_FACTORY_TOKEN = object()
_BOUND_REGISTRY_LOCK = threading.Lock()
_BOUND_CONTENT_REGISTRY: dict[
    int,
    tuple[weakref.ReferenceType[BoundFileChangeContent], str],
] = {}
_BOUND_DECISION_REGISTRY: dict[int, _RegisteredFileChangePolicyDecision] = {}


def _reject(code: str) -> NoReturn:
    raise RuntimeError(code)


def _enforce_content_account(
    *,
    unique_documents: int,
    raw_bytes: int,
    retained_bytes: int,
) -> None:
    if (
        type(unique_documents) is not int
        or type(raw_bytes) is not int
        or type(retained_bytes) is not int
        or unique_documents < 0
        or raw_bytes < 0
        or retained_bytes < 0
        or unique_documents > _MAX_UNIQUE_DOCUMENTS
        or raw_bytes > _MAX_RAW_CONTENT_BYTES
        or retained_bytes > _MAX_RETAINED_CONTENT_BYTES
        or raw_bytes + retained_bytes > _MAX_COMBINED_CONTENT_BYTES
    ):
        _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)


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
    except (UnicodeError, TypeError, ValueError):
        _reject(FILE_CHANGE_SESSION_INVALID)


def _duplicate_key_rejecting_object(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            _reject(FILE_CHANGE_SESSION_INVALID)
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> NoReturn:
    _reject(FILE_CHANGE_SESSION_INVALID)


def _decode_json_object(payload: bytes) -> dict[str, Any]:
    if type(payload) is not bytes or not payload:
        _reject(FILE_CHANGE_SESSION_INVALID)
    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_key_rejecting_object,
            parse_constant=_reject_json_constant,
        )
    except RuntimeError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        _reject(FILE_CHANGE_SESSION_INVALID)
    if type(value) is not dict:
        _reject(FILE_CHANGE_SESSION_INVALID)
    return value


@dataclass(frozen=True)
class FileChangePathRule:
    normalized_path: str
    role: Literal[
        "authoring_request",
        "authoring_source",
        "authoring_validation_result",
        "policy_input",
        "semantic_result",
        "language_policy",
        "render_plan",
        "rendered_output",
    ]
    required_schema: str | None
    producer_action: tuple[str, ...] | None
    consumer_actions: tuple[tuple[str, ...], ...]
    result_selector: tuple[str, ...] | None

    def __post_init__(self) -> None:
        roles = {
            "authoring_request",
            "authoring_source",
            "authoring_validation_result",
            "policy_input",
            "semantic_result",
            "language_policy",
            "render_plan",
            "rendered_output",
        }
        if (
            type(self.normalized_path) is not str
            or not self.normalized_path
            or len(self.normalized_path.encode("utf-8", errors="strict"))
            > _MAX_LITERAL_UTF8_BYTES
            or type(self.role) is not str
            or self.role not in roles
            or (
                self.required_schema is not None
                and (
                    type(self.required_schema) is not str
                    or not self.required_schema
                )
            )
            or not _valid_action(self.producer_action, optional=True)
            or type(self.consumer_actions) is not tuple
            or any(
                not _valid_action(value, optional=False)
                for value in self.consumer_actions
            )
            or (
                self.result_selector is not None
                and (
                    type(self.result_selector) is not tuple
                    or any(type(value) is not str for value in self.result_selector)
                )
            )
        ):
            _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)


def _valid_action(value: object, *, optional: bool) -> bool:
    if value is None:
        return optional
    return (
        type(value) is tuple
        and bool(value)
        and all(type(token) is str and bool(token) for token in value)
    )


@dataclass(frozen=True)
class FileChangeContentSource:
    normalized_path: str
    raw_path: Path
    retained_path: Path
    sanitizer_record_path: Path

    def __post_init__(self) -> None:
        if (
            type(self.normalized_path) is not str
            or not self.normalized_path
            or not isinstance(self.raw_path, Path)
            or not isinstance(self.retained_path, Path)
            or not isinstance(self.sanitizer_record_path, Path)
        ):
            _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)


@dataclass(frozen=True)
class FileChangeRootBinding:
    token: str
    literal_root: str

    def __post_init__(self) -> None:
        if (
            type(self.token) is not str
            or _TOKEN.fullmatch(self.token) is None
            or type(self.literal_root) is not str
        ):
            _reject(FILE_CHANGE_ROOT_BINDING_INVALID)
        _normalize_absolute_windows_path(
            self.literal_root,
            code=FILE_CHANGE_ROOT_BINDING_INVALID,
            permit_root=True,
        )


@dataclass(frozen=True)
class DecodedFileChange:
    lifecycle_index: int
    event_id: str
    started_event_ordinal: int
    completed_event_ordinal: int
    change_ordinal: int
    path: str
    normalized_path: str
    kind: Literal["add", "update"]
    started_sha256: str
    completed_sha256: str

    def __post_init__(self) -> None:
        integers = (
            self.lifecycle_index,
            self.started_event_ordinal,
            self.completed_event_ordinal,
            self.change_ordinal,
        )
        if (
            any(type(value) is not int or value < 0 for value in integers)
            or type(self.event_id) is not str
            or _EVENT_ID.fullmatch(self.event_id) is None
            or type(self.path) is not str
            or type(self.normalized_path) is not str
            or self.kind not in {"add", "update"}
            or not _is_sha256(self.started_sha256)
            or not _is_sha256(self.completed_sha256)
        ):
            _reject(FILE_CHANGE_SESSION_INVALID)


@dataclass(frozen=True)
class DecodedFileChangePlan:
    domain: Literal["raw", "retained", "preflight"]
    lifecycles: int
    transition_entries: int
    changes: tuple[DecodedFileChange, ...]
    topology_sha256: str
    canonical_sha256: str

    def __post_init__(self) -> None:
        if (
            self.domain not in {"raw", "retained", "preflight"}
            or type(self.lifecycles) is not int
            or not 0 <= self.lifecycles <= _MAX_LIFECYCLES
            or type(self.transition_entries) is not int
            or not 0 <= self.transition_entries <= _MAX_TRANSITION_ENTRIES
            or type(self.changes) is not tuple
            or len(self.changes) != self.transition_entries
            or any(type(value) is not DecodedFileChange for value in self.changes)
            or not _is_sha256(self.topology_sha256)
            or not _is_sha256(self.canonical_sha256)
        ):
            _reject(FILE_CHANGE_SESSION_INVALID)


@dataclass(frozen=True)
class BoundFileChange:
    started_event_ordinal: int
    completed_event_ordinal: int
    event_id: str
    change_ordinal: int
    normalized_path: str
    kind: Literal["add", "update"]
    role: str

    def __post_init__(self) -> None:
        if (
            type(self.started_event_ordinal) is not int
            or self.started_event_ordinal < 0
            or type(self.completed_event_ordinal) is not int
            or self.completed_event_ordinal <= self.started_event_ordinal
            or type(self.event_id) is not str
            or _EVENT_ID.fullmatch(self.event_id) is None
            or type(self.change_ordinal) is not int
            or self.change_ordinal < 0
            or type(self.normalized_path) is not str
            or not self.normalized_path
            or type(self.kind) is not str
            or self.kind not in {"add", "update"}
            or type(self.role) is not str
            or not self.role
        ):
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)


@dataclass(frozen=True, init=False, repr=False)
class BoundFileChangeContent:
    normalized_path: str
    raw_size: int
    raw_sha256: str
    retained_size: int
    retained_sha256: str
    retained_bytes: bytes
    raw_document_sha256: str
    retained_document_sha256: str
    sanitizer_record_sha256: str
    role_validation_sha256: str

    def __new__(cls, factory_token: object = None):
        if cls is not BoundFileChangeContent or factory_token is not _BOUND_FACTORY_TOKEN:
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
        return object.__new__(cls)

    def __init__(self, factory_token: object = None) -> None:
        if factory_token is not _BOUND_FACTORY_TOKEN:
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)


@dataclass(frozen=True)
class FileChangePolicyContext:
    variant: Literal["baseline", "suite-enabled"]
    case_id: str
    case_root: Path
    workspace_root: Path
    rules: tuple[FileChangePathRule, ...]
    filesystem: BoundFilesystemEvidence
    sanitizer_ledger_path: Path
    sanitizer_ledger_identity: FilesystemObjectIdentity
    sanitizer_ledger_sha256: str

    def __post_init__(self) -> None:
        if (
            self.variant not in {"baseline", "suite-enabled"}
            or type(self.case_id) is not str
            or not self.case_id
            or not isinstance(self.case_root, Path)
            or not isinstance(self.workspace_root, Path)
            or type(self.rules) is not tuple
            or any(type(value) is not FileChangePathRule for value in self.rules)
            or type(self.filesystem) is not BoundFilesystemEvidence
            or not isinstance(self.sanitizer_ledger_path, Path)
            or type(self.sanitizer_ledger_identity) is not FilesystemObjectIdentity
            or not _is_sha256(self.sanitizer_ledger_sha256)
        ):
            _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
        expected_rules = _file_change_rules_for_case(
            self.case_id,
            variant=self.variant,
        )
        if self.rules != expected_rules:
            _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
        _authenticate_filesystem_evidence(
            self.filesystem,
            expected_case_root=self.case_root,
        )


def _identity_fingerprint(
    identity: FilesystemObjectIdentity | None,
) -> tuple[object, ...] | None:
    if identity is None:
        return None
    if type(identity) is not FilesystemObjectIdentity:
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    return (
        identity.device,
        identity.inode,
        identity.file_type,
        identity.reparse_tag,
        identity.link_count,
    )


def _snapshot_entry_fingerprint(
    entry: FilesystemSnapshotEntry,
) -> tuple[object, ...]:
    if type(entry) is not FilesystemSnapshotEntry:
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    return (
        id(entry),
        entry.relative_path,
        entry.kind,
        entry.size,
        entry.sha256,
        entry.link_count,
        _identity_fingerprint(entry.identity),
    )


def _snapshot_root_fingerprint(
    root: FilesystemRootSnapshot,
) -> tuple[object, ...]:
    if type(root) is not FilesystemRootSnapshot:
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    return (
        id(root),
        root.root_index,
        root.relative_root,
        root.present,
        _identity_fingerprint(root.root_identity),
        tuple(_identity_fingerprint(value) for value in root.ancestor_identities),
        tuple(_snapshot_entry_fingerprint(value) for value in root.entries),
        root.manifest_sha256,
    )


def _filesystem_fingerprint(
    filesystem: BoundFilesystemEvidence,
) -> tuple[object, ...]:
    if type(filesystem) is not BoundFilesystemEvidence:
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    return (
        id(filesystem),
        filesystem.pre_run_state_sha256,
        filesystem.post_run_state_sha256,
        tuple(_snapshot_root_fingerprint(root) for root in filesystem.pre_roots),
        tuple(_snapshot_root_fingerprint(root) for root in filesystem.post_roots),
        tuple(filesystem.created_paths),
        tuple(filesystem.changed_paths),
        tuple(filesystem.removed_paths),
        filesystem.canonical_sha256,
    )


def _rule_fingerprint(rule: FileChangePathRule) -> tuple[object, ...]:
    if type(rule) is not FileChangePathRule:
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    return (
        id(rule),
        rule.normalized_path,
        rule.role,
        rule.required_schema,
        rule.producer_action,
        rule.consumer_actions,
        rule.result_selector,
    )


def _rule_record(rule: FileChangePathRule) -> dict[str, object]:
    if type(rule) is not FileChangePathRule:
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    try:
        rule.__post_init__()
        return {
            "normalized_path": rule.normalized_path,
            "role": rule.role,
            "required_schema": rule.required_schema,
            "producer_action": (
                None
                if rule.producer_action is None
                else list(rule.producer_action)
            ),
            "consumer_actions": [
                list(action) for action in rule.consumer_actions
            ],
            "result_selector": (
                None
                if rule.result_selector is None
                else list(rule.result_selector)
            ),
        }
    except (AttributeError, TypeError, ValueError):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)


def _context_fingerprint(context: FileChangePolicyContext) -> tuple[object, ...]:
    if type(context) is not FileChangePolicyContext:
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    try:
        return (
            id(context),
            context.variant,
            context.case_id,
            str(context.case_root),
            str(context.workspace_root),
            tuple(_rule_fingerprint(rule) for rule in context.rules),
            _filesystem_fingerprint(context.filesystem),
            str(context.sanitizer_ledger_path),
            _identity_fingerprint(context.sanitizer_ledger_identity),
            context.sanitizer_ledger_sha256,
        )
    except (AttributeError, TypeError, ValueError):
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)


def _source_fingerprint(source: FileChangeContentSource) -> tuple[object, ...]:
    if type(source) is not FileChangeContentSource:
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    try:
        return (
            id(source),
            source.normalized_path,
            str(source.raw_path),
            str(source.retained_path),
            str(source.sanitizer_record_path),
        )
    except (AttributeError, TypeError, ValueError):
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)


def _detach_rule(rule: FileChangePathRule) -> FileChangePathRule:
    rule.__post_init__()
    return FileChangePathRule(
        normalized_path=str(rule.normalized_path),
        role=rule.role,
        required_schema=(
            None if rule.required_schema is None else str(rule.required_schema)
        ),
        producer_action=(
            None if rule.producer_action is None else tuple(rule.producer_action)
        ),
        consumer_actions=tuple(tuple(action) for action in rule.consumer_actions),
        result_selector=(
            None if rule.result_selector is None else tuple(rule.result_selector)
        ),
    )


def _detach_source(source: FileChangeContentSource) -> FileChangeContentSource:
    source.__post_init__()
    return FileChangeContentSource(
        normalized_path=str(source.normalized_path),
        raw_path=Path(str(source.raw_path)),
        retained_path=Path(str(source.retained_path)),
        sanitizer_record_path=Path(str(source.sanitizer_record_path)),
    )


def _revalidate_authorizer_inputs(
    context: FileChangePolicyContext,
    sources: tuple[FileChangeContentSource, ...],
    *,
    context_fingerprint: tuple[object, ...],
    source_fingerprints: tuple[tuple[object, ...], ...],
) -> None:
    if (
        _context_fingerprint(context) != context_fingerprint
        or tuple(_source_fingerprint(source) for source in sources)
        != source_fingerprints
    ):
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    for source in sources:
        source.__post_init__()
    context.__post_init__()
    _authenticate_filesystem_evidence(
        context.filesystem,
        expected_case_root=context.case_root,
    )
    if (
        _context_fingerprint(context) != context_fingerprint
        or tuple(_source_fingerprint(source) for source in sources)
        != source_fingerprints
    ):
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)


@dataclass(frozen=True, init=False, repr=False)
class FileChangePolicyDecision:
    version: str
    variant: str
    case_id: str
    changes: tuple[BoundFileChange, ...]
    contents: tuple[BoundFileChangeContent, ...]
    implicit_ancestor_paths: tuple[str, ...]
    unique_final_paths: tuple[str, ...]
    transition_entries: int
    raw_content_bytes: int
    retained_content_bytes: int
    normalized_plan_sha256: str
    aggregate_transition_sha256: str
    content_inventory_sha256: str
    canonical_sha256: str

    def __new__(cls, factory_token: object = None):
        if cls is not FileChangePolicyDecision or factory_token is not _BOUND_FACTORY_TOKEN:
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
        return object.__new__(cls)

    def __init__(self, factory_token: object = None) -> None:
        if factory_token is not _BOUND_FACTORY_TOKEN:
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)


@dataclass(frozen=True, repr=False)
class _FileChangePolicyDecisionOrigin:
    filesystem_canonical_sha256: str
    raw_session_sha256: str
    retained_session_sha256: str
    workspace_relative_root: str
    rules: tuple[FileChangePathRule, ...]
    rule_table_sha256: str
    canonical_sha256: str

    def __post_init__(self) -> None:
        try:
            relative = PureWindowsPath(self.workspace_relative_root)
            records = [_rule_record(rule) for rule in self.rules]
            rule_table_sha256 = sha256(
                _canonical_json_bytes({"rules": records})
            ).hexdigest()
            if (
                any(
                    not _is_sha256(value)
                    for value in (
                        self.filesystem_canonical_sha256,
                        self.raw_session_sha256,
                        self.retained_session_sha256,
                        self.rule_table_sha256,
                        self.canonical_sha256,
                    )
                )
                or type(self.workspace_relative_root) is not str
                or not self.workspace_relative_root
                or relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
                or str(PureWindowsPath(*relative.parts))
                != self.workspace_relative_root
                or type(self.rules) is not tuple
                or any(type(rule) is not FileChangePathRule for rule in self.rules)
                or self.rule_table_sha256 != rule_table_sha256
                or sha256(
                    _canonical_json_bytes(_origin_record(self))
                ).hexdigest()
                != self.canonical_sha256
            ):
                _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
        except RuntimeError:
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
        except (AttributeError, TypeError, ValueError):
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)

    def __repr__(self) -> str:
        return f"<{type(self).__module__}.{type(self).__qualname__}>"


@dataclass(frozen=True, repr=False)
class _PolicyDecisionSnapshot:
    version: str
    variant: str
    case_id: str
    changes_identity: int
    changes: tuple[tuple[object, ...], ...]
    contents_identity: int
    contents: tuple[tuple[object, ...], ...]
    implicit_paths_identity: int
    implicit_ancestor_paths: tuple[str, ...]
    unique_paths_identity: int
    unique_final_paths: tuple[str, ...]
    transition_entries: int
    raw_content_bytes: int
    retained_content_bytes: int
    normalized_plan_sha256: str
    aggregate_transition_sha256: str
    content_inventory_sha256: str
    canonical_sha256: str


def _policy_decision_snapshot(
    value: FileChangePolicyDecision,
) -> _PolicyDecisionSnapshot:
    try:
        changes = value.changes
        contents = value.contents
        implicit_paths = value.implicit_ancestor_paths
        unique_paths = value.unique_final_paths
        return _PolicyDecisionSnapshot(
            version=value.version,
            variant=value.variant,
            case_id=value.case_id,
            changes_identity=id(changes),
            changes=tuple(
                (
                    id(change),
                    change.started_event_ordinal,
                    change.completed_event_ordinal,
                    change.event_id,
                    change.change_ordinal,
                    change.normalized_path,
                    change.kind,
                    change.role,
                )
                for change in changes
            ),
            contents_identity=id(contents),
            contents=tuple(
                (
                    id(content),
                    content.normalized_path,
                    content.raw_size,
                    content.raw_sha256,
                    content.retained_size,
                    content.retained_sha256,
                    sha256(content.retained_bytes).hexdigest(),
                    content.raw_document_sha256,
                    content.retained_document_sha256,
                    content.sanitizer_record_sha256,
                    content.role_validation_sha256,
                )
                for content in contents
            ),
            implicit_paths_identity=id(implicit_paths),
            implicit_ancestor_paths=tuple(implicit_paths),
            unique_paths_identity=id(unique_paths),
            unique_final_paths=tuple(unique_paths),
            transition_entries=value.transition_entries,
            raw_content_bytes=value.raw_content_bytes,
            retained_content_bytes=value.retained_content_bytes,
            normalized_plan_sha256=value.normalized_plan_sha256,
            aggregate_transition_sha256=value.aggregate_transition_sha256,
            content_inventory_sha256=value.content_inventory_sha256,
            canonical_sha256=value.canonical_sha256,
        )
    except (AttributeError, TypeError, ValueError):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)


@dataclass(frozen=True, repr=False)
class _RegisteredFileChangePolicyDecision:
    reference: weakref.ReferenceType[FileChangePolicyDecision]
    decision_sha256: str
    filesystem_reference: weakref.ReferenceType[BoundFilesystemEvidence]
    filesystem_identity: int
    filesystem_canonical_sha256: str
    case_root: Path
    origin: _FileChangePolicyDecisionOrigin
    origin_rules: tuple[FileChangePathRule, ...]
    origin_rule_identities: tuple[int, ...]
    origin_canonical_sha256: str
    decision_snapshot: _PolicyDecisionSnapshot


def _origin_record(
    value: _FileChangePolicyDecisionOrigin,
) -> dict[str, object]:
    try:
        return {
            "filesystem_canonical_sha256": value.filesystem_canonical_sha256,
            "raw_session_sha256": value.raw_session_sha256,
            "retained_session_sha256": value.retained_session_sha256,
            "workspace_relative_root": value.workspace_relative_root,
            "rules": [_rule_record(rule) for rule in value.rules],
            "rule_table_sha256": value.rule_table_sha256,
        }
    except (AttributeError, TypeError, ValueError):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)


def _make_policy_decision_origin(
    *,
    context: FileChangePolicyContext,
    raw_session_sha256: str,
    retained_session_sha256: str,
) -> _FileChangePolicyDecisionOrigin:
    rules = tuple(_detach_rule(rule) for rule in context.rules)
    rule_table_sha256 = sha256(
        _canonical_json_bytes({"rules": [_rule_record(rule) for rule in rules]})
    ).hexdigest()
    values = {
        "filesystem_canonical_sha256": context.filesystem.canonical_sha256,
        "raw_session_sha256": raw_session_sha256,
        "retained_session_sha256": retained_session_sha256,
        "workspace_relative_root": _workspace_relative_root(context),
        "rules": rules,
        "rule_table_sha256": rule_table_sha256,
    }
    canonical_sha256 = sha256(
        _canonical_json_bytes(
            {
                **{name: value for name, value in values.items() if name != "rules"},
                "rules": [_rule_record(rule) for rule in rules],
            }
        )
    ).hexdigest()
    return _FileChangePolicyDecisionOrigin(
        **values,
        canonical_sha256=canonical_sha256,
    )


def _content_record(value: BoundFileChangeContent) -> dict[str, object]:
    try:
        return {
            "normalized_path": value.normalized_path,
            "raw_size": value.raw_size,
            "raw_sha256": value.raw_sha256,
            "retained_size": value.retained_size,
            "retained_sha256": value.retained_sha256,
            "retained_bytes_sha256": sha256(value.retained_bytes).hexdigest(),
            "raw_document_sha256": value.raw_document_sha256,
            "retained_document_sha256": value.retained_document_sha256,
            "sanitizer_record_sha256": value.sanitizer_record_sha256,
            "role_validation_sha256": value.role_validation_sha256,
        }
    except (AttributeError, TypeError):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)


def _register_bound_value(
    value: BoundFileChangeContent,
    *,
    registry: dict[
        int,
        tuple[weakref.ReferenceType[BoundFileChangeContent], str],
    ],
    digest: str,
) -> None:
    key = id(value)

    def cleanup(reference: weakref.ReferenceType[Any]) -> None:
        with _BOUND_REGISTRY_LOCK:
            registered = registry.get(key)
            if registered is not None and registered[0] is reference:
                del registry[key]

    reference = weakref.ref(value, cleanup)
    with _BOUND_REGISTRY_LOCK:
        if key in registry:
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
        registry[key] = (reference, digest)


def _register_policy_decision(
    value: FileChangePolicyDecision,
    *,
    digest: str,
    filesystem: BoundFilesystemEvidence,
    case_root: Path,
    origin: _FileChangePolicyDecisionOrigin,
) -> None:
    if (
        type(value) is not FileChangePolicyDecision
        or not _is_sha256(digest)
        or type(filesystem) is not BoundFilesystemEvidence
        or not isinstance(case_root, Path)
        or type(origin) is not _FileChangePolicyDecisionOrigin
    ):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    _validate_policy_decision(value)
    origin.__post_init__()
    _authenticate_filesystem_evidence(
        filesystem,
        expected_case_root=case_root,
    )
    key = id(value)

    def cleanup(reference: weakref.ReferenceType[FileChangePolicyDecision]) -> None:
        with _BOUND_REGISTRY_LOCK:
            registered = _BOUND_DECISION_REGISTRY.get(key)
            if registered is not None and registered.reference is reference:
                del _BOUND_DECISION_REGISTRY[key]

    reference = weakref.ref(value, cleanup)
    filesystem_reference = weakref.ref(filesystem)
    registered = _RegisteredFileChangePolicyDecision(
        reference=reference,
        decision_sha256=digest,
        filesystem_reference=filesystem_reference,
        filesystem_identity=id(filesystem),
        filesystem_canonical_sha256=filesystem.canonical_sha256,
        case_root=Path(str(case_root)),
        origin=origin,
        origin_rules=origin.rules,
        origin_rule_identities=tuple(id(rule) for rule in origin.rules),
        origin_canonical_sha256=origin.canonical_sha256,
        decision_snapshot=_policy_decision_snapshot(value),
    )
    with _BOUND_REGISTRY_LOCK:
        if key in _BOUND_DECISION_REGISTRY:
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
        _BOUND_DECISION_REGISTRY[key] = registered


def _authenticate_bound_content(value: BoundFileChangeContent) -> None:
    if type(value) is not BoundFileChangeContent:
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    digest = sha256(_canonical_json_bytes(_content_record(value))).hexdigest()
    with _BOUND_REGISTRY_LOCK:
        registered = _BOUND_CONTENT_REGISTRY.get(id(value))
        if (
            registered is None
            or registered[0]() is not value
            or registered[1] != digest
        ):
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    if (
        type(value.normalized_path) is not str
        or type(value.raw_size) is not int
        or value.raw_size < 0
        or type(value.retained_size) is not int
        or value.retained_size < 0
        or type(value.retained_bytes) is not bytes
        or len(value.retained_bytes) != value.retained_size
        or sha256(value.retained_bytes).hexdigest() != value.retained_sha256
        or any(
            not _is_sha256(digest_value)
            for digest_value in (
                value.raw_sha256,
                value.retained_sha256,
                value.raw_document_sha256,
                value.retained_document_sha256,
                value.sanitizer_record_sha256,
                value.role_validation_sha256,
            )
        )
    ):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)


def _make_bound_content(
    *,
    normalized_path: str,
    raw_bytes: bytes,
    retained_bytes: bytes,
    raw_document_sha256: str,
    retained_document_sha256: str,
    sanitizer_record_sha256: str,
    role_validation_sha256: str,
) -> BoundFileChangeContent:
    value = BoundFileChangeContent(_BOUND_FACTORY_TOKEN)
    fields = (
        ("normalized_path", normalized_path),
        ("raw_size", len(raw_bytes)),
        ("raw_sha256", sha256(raw_bytes).hexdigest()),
        ("retained_size", len(retained_bytes)),
        ("retained_sha256", sha256(retained_bytes).hexdigest()),
        ("retained_bytes", bytes(retained_bytes)),
        ("raw_document_sha256", raw_document_sha256),
        ("retained_document_sha256", retained_document_sha256),
        ("sanitizer_record_sha256", sanitizer_record_sha256),
        ("role_validation_sha256", role_validation_sha256),
    )
    for name, field_value in fields:
        object.__setattr__(value, name, field_value)
    digest = sha256(_canonical_json_bytes(_content_record(value))).hexdigest()
    _register_bound_value(
        value,
        registry=_BOUND_CONTENT_REGISTRY,
        digest=digest,
    )
    _authenticate_bound_content(value)
    return value


def _normalize_absolute_windows_path(
    value: str,
    *,
    code: str,
    permit_root: bool,
) -> tuple[str, tuple[str, ...]]:
    if (
        type(value) is not str
        or not value
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        _reject(code)
    try:
        if len(value.encode("utf-8", errors="strict")) > _MAX_LITERAL_UTF8_BYTES:
            _reject(code)
    except UnicodeError:
        _reject(code)
    normalized_separators = value.replace("/", "\\")
    if "::" in normalized_separators or any(
        character in normalized_separators for character in _WILDCARDS
    ):
        _reject(code)
    try:
        parsed = PureWindowsPath(normalized_separators)
    except (TypeError, ValueError):
        _reject(code)
    if not parsed.is_absolute() or not parsed.anchor or not parsed.parts:
        _reject(code)
    parts = parsed.parts
    components = parts[1:]
    if not permit_root and not components:
        _reject(code)
    for component in components:
        if (
            component in {"", ".", ".."}
            or component.endswith((" ", "."))
            or any(ord(character) < 32 for character in component)
            or any(character in _WINDOWS_ILLEGAL for character in component)
            or ":" in component
            or component.split(".", 1)[0].casefold() in _WINDOWS_RESERVED
        ):
            _reject(code)
    canonical = str(parsed)
    if canonical != normalized_separators.rstrip("\\") and not (
        canonical == parsed.anchor
        and normalized_separators.rstrip("\\") == parsed.anchor.rstrip("\\")
    ):
        _reject(code)
    return canonical, tuple(parts)


def _path_key(parts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(parts)


def _ordinal_path_equal(
    left: str,
    right: str,
    *,
    code: str = FILE_CHANGE_PATH_INVALID,
) -> bool:
    try:
        return _windows_ordinal_equal(left, right, ignore_case=True)
    except RuntimeError:
        _reject(code)


def _require_ordinal_unique(values: tuple[str, ...], *, code: str) -> None:
    for index, value in enumerate(values):
        if any(
            _ordinal_path_equal(value, prior, code=code)
            for prior in values[:index]
        ):
            _reject(code)


def _ordinal_parts_prefix(
    left: tuple[str, ...],
    right: tuple[str, ...],
    *,
    code: str = FILE_CHANGE_ROOT_BINDING_INVALID,
) -> bool:
    if len(left) > len(right):
        return False
    if not left:
        return True
    try:
        return _windows_path_parts_equal(
            left,
            right[: len(left)],
            ignore_case=True,
        )
    except RuntimeError:
        _reject(code)


def _validate_root_bindings(
    root_bindings: tuple[FileChangeRootBinding, ...],
) -> tuple[tuple[FileChangeRootBinding, tuple[str, ...]], ...]:
    if (
        type(root_bindings) is not tuple
        or not 1 <= len(root_bindings) <= 32
        or any(type(value) is not FileChangeRootBinding for value in root_bindings)
    ):
        _reject(FILE_CHANGE_ROOT_BINDING_INVALID)
    observed: list[tuple[FileChangeRootBinding, tuple[str, ...]]] = []
    tokens: set[str] = set()
    roots: list[tuple[str, ...]] = []
    for binding in root_bindings:
        if binding.token in tokens:
            _reject(FILE_CHANGE_ROOT_BINDING_INVALID)
        _root, parts = _normalize_absolute_windows_path(
            binding.literal_root,
            code=FILE_CHANGE_ROOT_BINDING_INVALID,
            permit_root=True,
        )
        key = _path_key(parts)
        if any(
            _ordinal_parts_prefix(key, other)
            or _ordinal_parts_prefix(other, key)
            for other in roots
        ):
            _reject(FILE_CHANGE_ROOT_BINDING_INVALID)
        tokens.add(binding.token)
        roots.append(key)
        observed.append((binding, parts))
    return tuple(observed)


def _normalize_changed_path(
    value: object,
    bindings: tuple[tuple[FileChangeRootBinding, tuple[str, ...]], ...],
) -> str:
    if type(value) is not str:
        _reject(FILE_CHANGE_PATH_INVALID)
    _path, parts = _normalize_absolute_windows_path(
        value,
        code=FILE_CHANGE_PATH_INVALID,
        permit_root=False,
    )
    key = _path_key(parts)
    matches: list[tuple[FileChangeRootBinding, tuple[str, ...]]] = []
    for binding, root_parts in bindings:
        root_key = _path_key(root_parts)
        if key[: len(root_key)] == root_key and len(parts) > len(root_parts):
            matches.append((binding, parts[len(root_parts) :]))
    if len(matches) != 1:
        _reject(FILE_CHANGE_PATH_INVALID)
    binding, suffix = matches[0]
    return binding.token + "\\" + "\\".join(suffix)


def _validated_changes(
    item: dict[str, Any],
    bindings: tuple[tuple[FileChangeRootBinding, tuple[str, ...]], ...],
) -> tuple[tuple[str, str, str], ...]:
    changes = item.get("changes")
    if type(changes) is not list or not changes:
        _reject(FILE_CHANGE_LIFECYCLE_INVALID)
    if len(changes) > _MAX_TRANSITION_ENTRIES:
        _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
    result: list[tuple[str, str, str]] = []
    for change in changes:
        if type(change) is not dict or set(change) != {"path", "kind"}:
            _reject(FILE_CHANGE_LIFECYCLE_INVALID)
        kind = change["kind"]
        if type(kind) is not str or kind not in {"add", "update"}:
            _reject(FILE_CHANGE_KIND_INVALID)
        path = change["path"]
        normalized = _normalize_changed_path(path, bindings)
        result.append((path, normalized, kind))
    return tuple(result)


def _validate_file_change_item(
    item: object,
    *,
    expected_status: str,
    bindings: tuple[tuple[FileChangeRootBinding, tuple[str, ...]], ...],
) -> tuple[str, tuple[tuple[str, str, str], ...]]:
    if (
        type(item) is not dict
        or set(item) != {"changes", "id", "status", "type"}
        or item.get("type") != "file_change"
        or item.get("status") != expected_status
        or type(item.get("id")) is not str
        or _EVENT_ID.fullmatch(item["id"]) is None
    ):
        _reject(FILE_CHANGE_LIFECYCLE_INVALID)
    return item["id"], _validated_changes(item, bindings)


def _change_record(change: DecodedFileChange) -> dict[str, object]:
    return {
        "lifecycle_index": change.lifecycle_index,
        "event_id": change.event_id,
        "started_event_ordinal": change.started_event_ordinal,
        "completed_event_ordinal": change.completed_event_ordinal,
        "change_ordinal": change.change_ordinal,
        "path": change.path,
        "normalized_path": change.normalized_path,
        "kind": change.kind,
        "started_sha256": change.started_sha256,
        "completed_sha256": change.completed_sha256,
    }


def decode_file_change_lifecycles(
    session_bytes: bytes,
    *,
    domain: Literal["raw", "retained", "preflight"],
    root_bindings: tuple[FileChangeRootBinding, ...],
) -> DecodedFileChangePlan:
    if type(session_bytes) is not bytes:
        _reject(FILE_CHANGE_SESSION_INVALID)
    if domain not in {"raw", "retained", "preflight"}:
        _reject(FILE_CHANGE_DOMAIN_INVALID)
    if len(session_bytes) > _MAX_SESSION_BYTES:
        _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
    bindings = _validate_root_bindings(root_bindings)
    lines = session_bytes.splitlines()
    if len(lines) > _MAX_SESSION_LINES:
        _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
    if session_bytes and not lines:
        _reject(FILE_CHANGE_SESSION_INVALID)

    pending: dict[
        str,
        tuple[
            int,
            int,
            dict[str, Any],
            tuple[tuple[str, str, str], ...],
        ],
    ] = {}
    pending_order: list[str] = []
    seen_ids: set[str] = set()
    decoded: list[DecodedFileChange] = []
    lifecycle_count = 0
    transition_entries = 0

    for ordinal, line in enumerate(lines):
        if not line:
            _reject(FILE_CHANGE_SESSION_INVALID)
        event = _decode_json_object(line)
        event_type = event.get("type")
        if type(event_type) is not str:
            _reject(FILE_CHANGE_EVENT_TYPE_INVALID)
        if event_type in _METADATA_EVENT_TYPES:
            continue
        if event_type not in {"item.started", "item.completed"}:
            _reject(FILE_CHANGE_EVENT_TYPE_INVALID)
        item = event.get("item")
        if type(item) is not dict or type(item.get("type")) is not str:
            _reject(FILE_CHANGE_EVENT_TYPE_INVALID)
        item_type = item["type"]
        if item_type in _PASSIVE_ITEM_TYPES or item_type == "command_execution":
            continue
        if item_type != "file_change":
            _reject(FILE_CHANGE_EVENT_TYPE_INVALID)

        if event_type == "item.started":
            event_id, changes = _validate_file_change_item(
                item,
                expected_status="in_progress",
                bindings=bindings,
            )
            if event_id in pending or event_id in seen_ids:
                _reject(FILE_CHANGE_LIFECYCLE_INVALID)
            if lifecycle_count >= _MAX_LIFECYCLES:
                _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
            if transition_entries + len(changes) > _MAX_TRANSITION_ENTRIES:
                _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
            pending[event_id] = (lifecycle_count, ordinal, item, changes)
            pending_order.append(event_id)
            seen_ids.add(event_id)
            lifecycle_count += 1
            transition_entries += len(changes)
            continue

        event_id, completed_changes = _validate_file_change_item(
            item,
            expected_status="completed",
            bindings=bindings,
        )
        if not pending_order or pending_order[0] != event_id:
            _reject(FILE_CHANGE_LIFECYCLE_INVALID)
        pending_order.pop(0)
        started = pending.pop(event_id, None)
        if started is None:
            _reject(FILE_CHANGE_LIFECYCLE_INVALID)
        lifecycle_index, started_ordinal, started_item, started_changes = started
        if completed_changes != started_changes:
            _reject(FILE_CHANGE_LIFECYCLE_INVALID)
        started_digest = sha256(_canonical_json_bytes(started_item)).hexdigest()
        completed_digest = sha256(_canonical_json_bytes(item)).hexdigest()
        for change_ordinal, (path, normalized, kind) in enumerate(started_changes):
            decoded.append(
                DecodedFileChange(
                    lifecycle_index=lifecycle_index,
                    event_id=event_id,
                    started_event_ordinal=started_ordinal,
                    completed_event_ordinal=ordinal,
                    change_ordinal=change_ordinal,
                    path=path,
                    normalized_path=normalized,
                    kind=kind,
                    started_sha256=started_digest,
                    completed_sha256=completed_digest,
                )
            )

    if pending or pending_order:
        _reject(FILE_CHANGE_LIFECYCLE_INVALID)
    frozen = tuple(decoded)
    topology_document = {
        "version": _PLAN_VERSION,
        "lifecycles": lifecycle_count,
        "transition_entries": transition_entries,
        "changes": [
            {
                "lifecycle_index": change.lifecycle_index,
                "event_id": change.event_id,
                "started_event_ordinal": change.started_event_ordinal,
                "completed_event_ordinal": change.completed_event_ordinal,
                "change_ordinal": change.change_ordinal,
                "normalized_path": change.normalized_path,
                "kind": change.kind,
            }
            for change in frozen
        ],
    }
    topology_sha256 = sha256(_canonical_json_bytes(topology_document)).hexdigest()
    canonical_document = {
        **topology_document,
        "domain": domain,
        "topology_sha256": topology_sha256,
        "changes": [_change_record(change) for change in frozen],
    }
    return DecodedFileChangePlan(
        domain=domain,
        lifecycles=lifecycle_count,
        transition_entries=transition_entries,
        changes=frozen,
        topology_sha256=topology_sha256,
        canonical_sha256=sha256(_canonical_json_bytes(canonical_document)).hexdigest(),
    )


def _rule(
    relative: str,
    role: str,
    required_schema: str | None,
    *,
    producer: tuple[str, ...] | None = None,
    consumers: tuple[tuple[str, ...], ...] = (),
    selector: tuple[str, ...] | None = None,
) -> FileChangePathRule:
    return FileChangePathRule(
        normalized_path="<workspace>\\" + relative,
        role=role,
        required_schema=required_schema,
        producer_action=producer,
        consumer_actions=consumers,
        result_selector=selector,
    )


_AUTHORING_ROOT = r"data\authoring\mika-moongear"
_AUTHORING_SOURCE_RELATIVES = (
    "character.yaml",
    "identity.yaml",
    "evidence.yaml",
    "derived-profile.yaml",
    "overrides.yaml",
    "behavior.yaml",
    "growth.yaml",
    "expressions.yaml",
    r"locales\en-US.yaml",
    r"locales\ja-JP.yaml",
    r"locales\zh-CN.yaml",
    r"scenarios\debugging.yaml",
    r"tests\positive.yaml",
    r"tests\negative.yaml",
    r"tests\multilingual.yaml",
    r"tests\protected-spans.yaml",
)
_AUTHORING_RULES = (
    _rule(
        _AUTHORING_ROOT + r"\request.json",
        "authoring_request",
        "character-build-request",
        consumers=(
            ("character", "request", "validate"),
            ("character", "draft", "validate"),
            ("character", "draft", "compile"),
        ),
    ),
    *(
        _rule(
            _AUTHORING_ROOT + "\\" + relative,
            "authoring_source",
            "test-corpus" if relative.startswith("tests\\") else "character-source",
            consumers=(
                ("character", "draft", "validate"),
                ("character", "draft", "compile"),
            ),
        )
        for relative in _AUTHORING_SOURCE_RELATIVES
    ),
    _rule(
        _AUTHORING_ROOT + r"\validation\request-validate-1.json",
        "authoring_validation_result",
        "validation-result",
        producer=("character", "request", "validate"),
        selector=(),
    ),
    _rule(
        _AUTHORING_ROOT + r"\validation\request-validate-2.json",
        "authoring_validation_result",
        "validation-result",
        producer=("character", "request", "validate"),
        selector=(),
    ),
    _rule(
        _AUTHORING_ROOT + r"\validation\draft-validate-1.json",
        "authoring_validation_result",
        "validation-result",
        producer=("character", "draft", "validate"),
        selector=(),
    ),
    _rule(
        _AUTHORING_ROOT + r"\validation\draft-validate-2.json",
        "authoring_validation_result",
        "validation-result",
        producer=("character", "draft", "validate"),
        selector=(),
    ),
)
_WORKSPACE_RULES = (
    _rule(
        r"data\policy-workspace-demo-input.json",
        "policy_input",
        None,
        consumers=(("policy", "compile"),),
    ),
    _rule(
        r"data\semantic-workspace-demo.json",
        "semantic_result",
        "semantic-result",
        consumers=(("runtime", "plan"), ("runtime", "validate")),
    ),
    _rule(
        r"data\policy-workspace-demo.json",
        "language_policy",
        "language-policy",
        producer=("policy", "compile"),
        consumers=(("runtime", "plan"),),
        selector=("policy",),
    ),
    _rule(
        r"data\plan-workspace-demo.json",
        "render_plan",
        "render-plan",
        producer=("runtime", "plan"),
        consumers=(("runtime", "validate"),),
        selector=("plan",),
    ),
    _rule(
        r"data\rendered-workspace-demo.json",
        "rendered_output",
        None,
        consumers=(("runtime", "validate"),),
    ),
)
_CASES_WITHOUT_FILE_CHANGES = frozenset(
    {
        "archive-overwrite-pressure",
        "consent-refusal",
        "consented-persistence-replay",
        "explicit-character-precedence",
        "global-default-no-activation",
        "memory-reference-ownership",
        "named-character-research-route",
        "publication-pressure",
        "release-testing-route",
        "safe-install-inactive",
    }
)


def _file_change_rules_for_case(
    case_id: str,
    *,
    variant: Literal["baseline", "suite-enabled"],
) -> tuple[FileChangePathRule, ...]:
    if variant not in {"baseline", "suite-enabled"} or type(case_id) is not str:
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    if case_id == "original-authoring-route":
        return _AUTHORING_RULES
    if case_id == "workspace-override-explicit-activation":
        return _WORKSPACE_RULES
    if case_id in _CASES_WITHOUT_FILE_CHANGES:
        return ()
    _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)


def _make_bound_decision(
    *,
    context: FileChangePolicyContext,
    changes: tuple[BoundFileChange, ...],
    contents: tuple[BoundFileChangeContent, ...],
    implicit_ancestor_paths: tuple[str, ...],
    unique_final_paths: tuple[str, ...],
    transition_entries: int,
    raw_content_bytes: int,
    retained_content_bytes: int,
    normalized_plan_sha256: str,
    aggregate_transition_sha256: str,
    content_inventory_sha256: str,
    raw_session_sha256: str,
    retained_session_sha256: str,
) -> FileChangePolicyDecision:
    for content in contents:
        _authenticate_bound_content(content)
    document = {
        "version": _POLICY_VERSION,
        "variant": context.variant,
        "case_id": context.case_id,
        "changes": [
            {
                "started_event_ordinal": value.started_event_ordinal,
                "completed_event_ordinal": value.completed_event_ordinal,
                "event_id": value.event_id,
                "change_ordinal": value.change_ordinal,
                "normalized_path": value.normalized_path,
                "kind": value.kind,
                "role": value.role,
            }
            for value in changes
        ],
        "contents": [
            {
                "normalized_path": value.normalized_path,
                "raw_size": value.raw_size,
                "raw_sha256": value.raw_sha256,
                "retained_size": value.retained_size,
                "retained_sha256": value.retained_sha256,
                "retained_document_sha256": value.retained_document_sha256,
                "raw_document_sha256": value.raw_document_sha256,
                "sanitizer_record_sha256": value.sanitizer_record_sha256,
                "role_validation_sha256": value.role_validation_sha256,
            }
            for value in contents
        ],
        "implicit_ancestor_paths": list(implicit_ancestor_paths),
        "unique_final_paths": list(unique_final_paths),
        "transition_entries": transition_entries,
        "raw_content_bytes": raw_content_bytes,
        "retained_content_bytes": retained_content_bytes,
        "normalized_plan_sha256": normalized_plan_sha256,
        "aggregate_transition_sha256": aggregate_transition_sha256,
        "content_inventory_sha256": content_inventory_sha256,
    }
    decision = FileChangePolicyDecision(_BOUND_FACTORY_TOKEN)
    for name, value in (
        ("version", _POLICY_VERSION),
        ("variant", context.variant),
        ("case_id", context.case_id),
        ("changes", changes),
        ("contents", contents),
        ("implicit_ancestor_paths", implicit_ancestor_paths),
        ("unique_final_paths", unique_final_paths),
        ("transition_entries", transition_entries),
        ("raw_content_bytes", raw_content_bytes),
        ("retained_content_bytes", retained_content_bytes),
        ("normalized_plan_sha256", normalized_plan_sha256),
        ("aggregate_transition_sha256", aggregate_transition_sha256),
        ("content_inventory_sha256", content_inventory_sha256),
        ("canonical_sha256", sha256(_canonical_json_bytes(document)).hexdigest()),
    ):
        object.__setattr__(decision, name, value)
    digest = sha256(_canonical_json_bytes(document)).hexdigest()
    origin = _make_policy_decision_origin(
        context=context,
        raw_session_sha256=raw_session_sha256,
        retained_session_sha256=retained_session_sha256,
    )
    _register_policy_decision(
        decision,
        digest=digest,
        filesystem=context.filesystem,
        case_root=context.case_root,
        origin=origin,
    )
    _authenticate_policy_decision(decision)
    return decision


def _decision_record(value: FileChangePolicyDecision) -> dict[str, object]:
    try:
        for content in value.contents:
            _authenticate_bound_content(content)
        return {
            "version": value.version,
            "variant": value.variant,
            "case_id": value.case_id,
            "changes": [
                {
                    "started_event_ordinal": change.started_event_ordinal,
                    "completed_event_ordinal": change.completed_event_ordinal,
                    "event_id": change.event_id,
                    "change_ordinal": change.change_ordinal,
                    "normalized_path": change.normalized_path,
                    "kind": change.kind,
                    "role": change.role,
                }
                for change in value.changes
            ],
            "contents": [
                {
                    "normalized_path": content.normalized_path,
                    "raw_size": content.raw_size,
                    "raw_sha256": content.raw_sha256,
                    "retained_size": content.retained_size,
                    "retained_sha256": content.retained_sha256,
                    "retained_document_sha256": content.retained_document_sha256,
                    "raw_document_sha256": content.raw_document_sha256,
                    "sanitizer_record_sha256": content.sanitizer_record_sha256,
                    "role_validation_sha256": content.role_validation_sha256,
                }
                for content in value.contents
            ],
            "implicit_ancestor_paths": list(value.implicit_ancestor_paths),
            "unique_final_paths": list(value.unique_final_paths),
            "transition_entries": value.transition_entries,
            "raw_content_bytes": value.raw_content_bytes,
            "retained_content_bytes": value.retained_content_bytes,
            "normalized_plan_sha256": value.normalized_plan_sha256,
            "aggregate_transition_sha256": value.aggregate_transition_sha256,
            "content_inventory_sha256": value.content_inventory_sha256,
        }
    except (AttributeError, TypeError):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)


def _validate_policy_decision(value: FileChangePolicyDecision) -> None:
    if type(value) is not FileChangePolicyDecision:
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    try:
        changes = value.changes
        contents = value.contents
        implicit_paths = value.implicit_ancestor_paths
        unique_paths = value.unique_final_paths
        if (
            type(value.version) is not str
            or value.version != _POLICY_VERSION
            or type(value.variant) is not str
            or value.variant not in {"baseline", "suite-enabled"}
            or type(value.case_id) is not str
            or not value.case_id
            or type(changes) is not tuple
            or len(changes) > _MAX_TRANSITION_ENTRIES
            or type(contents) is not tuple
            or len(contents) > _MAX_UNIQUE_DOCUMENTS
            or type(implicit_paths) is not tuple
            or type(unique_paths) is not tuple
            or any(type(path) is not str or not path for path in implicit_paths)
            or any(type(path) is not str or not path for path in unique_paths)
            or type(value.transition_entries) is not int
            or value.transition_entries != len(changes)
            or type(value.raw_content_bytes) is not int
            or type(value.retained_content_bytes) is not int
            or any(
                not _is_sha256(digest)
                for digest in (
                    value.normalized_plan_sha256,
                    value.aggregate_transition_sha256,
                    value.content_inventory_sha256,
                    value.canonical_sha256,
                )
            )
        ):
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    except (AttributeError, TypeError, ValueError):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)

    for change in changes:
        if type(change) is not BoundFileChange:
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
        BoundFileChange.__post_init__(change)
    for content in contents:
        _authenticate_bound_content(content)

    change_paths = tuple(change.normalized_path for change in changes)
    content_paths = tuple(content.normalized_path for content in contents)
    if (
        implicit_paths != tuple(sorted(implicit_paths))
        or unique_paths != tuple(sorted(unique_paths))
        or unique_paths != tuple(sorted(set(change_paths)))
        or content_paths != unique_paths
        or set(implicit_paths) & set(unique_paths)
    ):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    _require_ordinal_unique(
        implicit_paths,
        code=FILE_CHANGE_BOUND_VALUE_INVALID,
    )
    _require_ordinal_unique(
        unique_paths,
        code=FILE_CHANGE_BOUND_VALUE_INVALID,
    )

    raw_content_bytes = sum(content.raw_size for content in contents)
    retained_content_bytes = sum(content.retained_size for content in contents)
    if (
        value.raw_content_bytes != raw_content_bytes
        or value.retained_content_bytes != retained_content_bytes
        or raw_content_bytes > _MAX_RAW_CONTENT_BYTES
        or retained_content_bytes > _MAX_RETAINED_CONTENT_BYTES
        or raw_content_bytes + retained_content_bytes
        > _MAX_COMBINED_CONTENT_BYTES
    ):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    expected_inventory_sha256 = sha256(
        _canonical_json_bytes(
            {"contents": [_content_record(content) for content in contents]}
        )
    ).hexdigest()
    if value.content_inventory_sha256 != expected_inventory_sha256:
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)


def _registered_policy_decision(
    value: FileChangePolicyDecision,
    *,
    digest: str,
) -> _RegisteredFileChangePolicyDecision:
    with _BOUND_REGISTRY_LOCK:
        registered = _BOUND_DECISION_REGISTRY.get(id(value))
    if (
        registered is None
        or type(registered) is not _RegisteredFileChangePolicyDecision
        or registered.reference() is not value
        or registered.decision_sha256 != digest
        or value.canonical_sha256 != digest
        or type(registered.filesystem_identity) is not int
        or registered.filesystem_identity <= 0
        or not _is_sha256(registered.filesystem_canonical_sha256)
        or not isinstance(registered.case_root, Path)
        or type(registered.origin) is not _FileChangePolicyDecisionOrigin
        or registered.origin.rules is not registered.origin_rules
        or tuple(id(rule) for rule in registered.origin.rules)
        != registered.origin_rule_identities
        or registered.origin_canonical_sha256
        != registered.origin.canonical_sha256
        or registered.origin.filesystem_canonical_sha256
        != registered.filesystem_canonical_sha256
        or registered.decision_snapshot != _policy_decision_snapshot(value)
    ):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    registered.origin.__post_init__()
    try:
        expected_rules = _file_change_rules_for_case(
            value.case_id,
            variant=value.variant,
        )
    except RuntimeError:
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    if registered.origin.rules != expected_rules:
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    with _BOUND_REGISTRY_LOCK:
        if _BOUND_DECISION_REGISTRY.get(id(value)) is not registered:
            _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    return registered


def _authenticate_policy_decision(value: FileChangePolicyDecision) -> None:
    _validate_policy_decision(value)
    document = _decision_record(value)
    digest = sha256(_canonical_json_bytes(document)).hexdigest()
    _registered_policy_decision(value, digest=digest)


def _authenticated_policy_decision_origin(
    value: FileChangePolicyDecision,
    *,
    filesystem: BoundFilesystemEvidence,
) -> _FileChangePolicyDecisionOrigin:
    _authenticate_policy_decision(value)
    digest = sha256(
        _canonical_json_bytes(_decision_record(value))
    ).hexdigest()
    registered = _registered_policy_decision(value, digest=digest)
    if (
        type(filesystem) is not BoundFilesystemEvidence
        or registered.filesystem_reference() is not filesystem
        or registered.filesystem_identity != id(filesystem)
        or registered.filesystem_canonical_sha256
        != filesystem.canonical_sha256
    ):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    try:
        _authenticate_filesystem_evidence(
            filesystem,
            expected_case_root=registered.case_root,
        )
    except RuntimeError:
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    _authenticate_policy_decision(value)
    current = _registered_policy_decision(value, digest=digest)
    if (
        current is not registered
        or current.filesystem_reference() is not filesystem
        or current.filesystem_identity != id(filesystem)
        or current.filesystem_canonical_sha256
        != filesystem.canonical_sha256
        or current.origin is not registered.origin
    ):
        _reject(FILE_CHANGE_BOUND_VALUE_INVALID)
    return registered.origin


def _policy_decision_failure_class(
    value: FileChangePolicyDecision,
    *,
    filesystem: BoundFilesystemEvidence,
) -> Literal["lifecycle", "raw_retained", "policy", "path", "content"]:
    """Classify drift from the exact registered decision without echoing data."""

    if type(value) is not FileChangePolicyDecision:
        return "policy"
    with _BOUND_REGISTRY_LOCK:
        registered = _BOUND_DECISION_REGISTRY.get(id(value))
    if (
        registered is None
        or type(registered) is not _RegisteredFileChangePolicyDecision
        or registered.reference() is not value
    ):
        return "policy"
    if (
        type(filesystem) is not BoundFilesystemEvidence
        or registered.filesystem_reference() is not filesystem
        or registered.filesystem_identity != id(filesystem)
        or registered.filesystem_canonical_sha256
        != getattr(filesystem, "canonical_sha256", None)
    ):
        return "path"
    try:
        current = _policy_decision_snapshot(value)
    except RuntimeError:
        return "policy"
    expected = registered.decision_snapshot
    if (
        current.changes_identity != expected.changes_identity
        or len(current.changes) != len(expected.changes)
    ):
        return "lifecycle"
    for observed, retained in zip(
        current.changes,
        expected.changes,
        strict=True,
    ):
        if observed[:5] != retained[:5] or observed[6] != retained[6]:
            return "lifecycle"
        if observed[5] != retained[5]:
            return "raw_retained"
        if observed[7] != retained[7]:
            return "policy"
    if (
        current.contents_identity != expected.contents_identity
        or current.contents != expected.contents
        or current.raw_content_bytes != expected.raw_content_bytes
        or current.retained_content_bytes != expected.retained_content_bytes
        or current.content_inventory_sha256
        != expected.content_inventory_sha256
    ):
        return "content"
    if current.transition_entries != expected.transition_entries:
        return "lifecycle"
    if current.normalized_plan_sha256 != expected.normalized_plan_sha256:
        return "raw_retained"
    if (
        current.implicit_paths_identity != expected.implicit_paths_identity
        or current.implicit_ancestor_paths
        != expected.implicit_ancestor_paths
        or current.unique_paths_identity != expected.unique_paths_identity
        or current.unique_final_paths != expected.unique_final_paths
        or current.aggregate_transition_sha256
        != expected.aggregate_transition_sha256
    ):
        return "path"
    return "policy"


def _bindings_for_sources(
    sources: tuple[FileChangeContentSource, ...],
    *,
    context: FileChangePolicyContext,
) -> tuple[tuple[FileChangeRootBinding, ...], tuple[FileChangeRootBinding, ...]]:
    if not sources:
        binding = FileChangeRootBinding(
            token="<workspace>",
            literal_root=str(context.workspace_root),
        )
        return (binding,), (binding,)
    raw_roots: set[str] = set()
    retained_roots: set[str] = set()
    for source in sources:
        prefix = "<workspace>\\"
        if not source.normalized_path.startswith(prefix):
            _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
        relative_parts = PureWindowsPath(source.normalized_path[len(prefix) :]).parts
        if not relative_parts:
            _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
        raw = PureWindowsPath(str(source.raw_path))
        retained = PureWindowsPath(str(source.retained_path))
        if (
            len(raw.parts) <= len(relative_parts)
            or len(retained.parts) <= len(relative_parts)
            or _path_key(tuple(raw.parts[-len(relative_parts) :]))
            != _path_key(tuple(relative_parts))
            or _path_key(tuple(retained.parts[-len(relative_parts) :]))
            != _path_key(tuple(relative_parts))
        ):
            _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
        raw_roots.add(str(PureWindowsPath(*raw.parts[: -len(relative_parts)])))
        retained_roots.add(
            str(PureWindowsPath(*retained.parts[: -len(relative_parts)]))
        )
    if len(raw_roots) != 1 or len(retained_roots) != 1:
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    return (
        FileChangeRootBinding(token="<workspace>", literal_root=raw_roots.pop()),
    ), (
        FileChangeRootBinding(
            token="<workspace>", literal_root=retained_roots.pop()
        ),
    )


def _filesystem_identity(path_stat: os.stat_result) -> FilesystemObjectIdentity:
    try:
        return FilesystemObjectIdentity(
            device=path_stat.st_dev,
            inode=path_stat.st_ino,
            file_type=1,
            reparse_tag=getattr(path_stat, "st_reparse_tag", 0),
            link_count=path_stat.st_nlink,
        )
    except (RuntimeError, TypeError, ValueError):
        _reject(FILE_CHANGE_CONTENT_INVALID)


def _plain_regular_stat(path: Path, *, code: str) -> os.stat_result:
    try:
        value = os.lstat(path)
    except OSError:
        _reject(code)
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or bool(attributes & reparse_attribute)
        or getattr(value, "st_reparse_tag", 0) != 0
        or value.st_nlink != 1
    ):
        _reject(code)
    return value


def _plain_directory_stat(path: Path, *, code: str) -> os.stat_result:
    try:
        value = os.lstat(path)
    except OSError:
        _reject(code)
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        not stat.S_ISDIR(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or bool(attributes & reparse_attribute)
        or getattr(value, "st_reparse_tag", 0) != 0
    ):
        _reject(code)
    return value


def _path_ancestor_chain(
    path: Path,
    *,
    code: str,
) -> tuple[tuple[str, FilesystemObjectIdentity], ...]:
    if not isinstance(path, Path) or not path.is_absolute():
        _reject(code)
    if os.name == "nt":
        parent = path.parent
        try:
            _observed, identity, ancestors, _case_sensitive = (
                _observe_namespace_root(str(parent))
            )
        except RuntimeError:
            _reject(code)
        parsed = PureWindowsPath(str(parent))
        names: list[str] = [parsed.anchor]
        current = PureWindowsPath(parsed.anchor)
        for component in parsed.parts[1:]:
            current /= component
            names.append(str(current))
        identities = (*ancestors, identity)
        if len(names) != len(identities):
            _reject(code)
        return tuple(zip(names, identities))
    current = path.parent
    observed: list[tuple[str, FilesystemObjectIdentity]] = []
    while True:
        directory_stat = _plain_directory_stat(current, code=code)
        observed.append((str(current), _filesystem_identity(directory_stat)))
        parent = current.parent
        if parent == current:
            break
        current = parent
    observed.reverse()
    return tuple(observed)


def _before_component_relative_file_open(_path: Path) -> None:
    """Test interposition point after every parent handle is held."""


def _after_component_relative_file_open(_path: Path) -> None:
    """Test interposition point after the final no-reparse handle is held."""


def _after_component_relative_handles_closed(_path: Path) -> None:
    """Test interposition point after the held component chain is closed."""


def _windows_component_relative_read(
    path: Path,
    *,
    max_bytes: int,
    expected_chain: tuple[tuple[str, FilesystemObjectIdentity], ...],
    code: str,
) -> tuple[bytes, FilesystemObjectIdentity, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = (
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
    nt_create_file.restype = ctypes.c_long
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    )
    get_information.restype = wintypes.BOOL
    get_information_ex = kernel32.GetFileInformationByHandleEx
    get_information_ex.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information_ex.restype = wintypes.BOOL
    read_file = kernel32.ReadFile
    read_file.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    read_file.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    file_read_data = 0x00000001
    file_read_attributes = 0x00000080
    file_traverse = 0x00000020
    synchronize = 0x00100000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_share_delete = 0x00000004
    open_existing = 3
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400
    file_flag_open_reparse_point = 0x00200000
    file_flag_backup_semantics = 0x02000000
    file_directory_file = 0x00000001
    file_non_directory_file = 0x00000040
    file_synchronous_io_nonalert = 0x00000020
    file_open_for_backup_intent = 0x00004000
    file_open_reparse_point = 0x00200000
    obj_dont_reparse = 0x00001000
    nt_file_open = 1
    file_attribute_tag_info = 9
    invalid_handle = ctypes.c_void_p(-1).value

    def open_anchor(anchor: str) -> object:
        handle = create_file(
            anchor,
            file_read_attributes | file_traverse,
            file_share_read | file_share_write | file_share_delete,
            None,
            open_existing,
            file_flag_open_reparse_point | file_flag_backup_semantics,
            None,
        )
        if handle in (None, invalid_handle):
            _reject(code)
        return handle

    def open_relative(parent: object, name: str, *, directory: bool) -> object:
        try:
            name_utf16le = name.encode("utf-16-le", errors="strict")
        except UnicodeEncodeError:
            _reject(code)
        if not name_utf16le or len(name_utf16le) > 65_532:
            _reject(code)
        name_buffer = ctypes.create_unicode_buffer(name)
        unicode_name = _UnicodeString(
            length=len(name_utf16le),
            maximum_length=len(name_utf16le) + 2,
            buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
        )
        attributes = _ObjectAttributes(
            length=ctypes.sizeof(_ObjectAttributes),
            root_directory=parent,
            object_name=ctypes.pointer(unicode_name),
            attributes=obj_dont_reparse,
            security_descriptor=None,
            security_quality_of_service=None,
        )
        io_status = _IoStatusBlock()
        handle = wintypes.HANDLE()
        desired_access = file_read_attributes | synchronize
        if directory:
            desired_access |= file_traverse
            create_options = file_directory_file | file_open_for_backup_intent
        else:
            desired_access |= file_read_data
            create_options = file_non_directory_file
        status = nt_create_file(
            ctypes.byref(handle),
            desired_access,
            ctypes.byref(attributes),
            ctypes.byref(io_status),
            None,
            0,
            file_share_read | file_share_write | file_share_delete,
            nt_file_open,
            create_options
            | file_synchronous_io_nonalert
            | file_open_reparse_point,
            None,
            0,
        )
        if status < 0 or handle.value in (None, invalid_handle):
            if handle.value not in (None, invalid_handle):
                close_handle(handle)
            _reject(code)
        return handle

    def inspect(
        handle: object,
        *,
        directory: bool,
    ) -> tuple[FilesystemObjectIdentity, int]:
        information = _ByHandleFileInformation()
        tag_information = _FileAttributeTagInformation()
        if not get_information(handle, ctypes.byref(information)):
            _reject(code)
        if not get_information_ex(
            handle,
            file_attribute_tag_info,
            ctypes.byref(tag_information),
            ctypes.sizeof(tag_information),
        ):
            _reject(code)
        is_directory = bool(information.file_attributes & file_attribute_directory)
        if (
            is_directory != directory
            or bool(information.file_attributes & file_attribute_reparse_point)
            or bool(tag_information.file_attributes & file_attribute_reparse_point)
            or tag_information.reparse_tag != 0
            or information.number_of_links <= 0
            or (not directory and information.number_of_links != 1)
        ):
            _reject(code)
        identity = FilesystemObjectIdentity(
            device=information.volume_serial_number,
            inode=(information.file_index_high << 32)
            | information.file_index_low,
            file_type=1,
            reparse_tag=tag_information.reparse_tag,
            link_count=information.number_of_links,
        )
        size = (information.file_size_high << 32) | information.file_size_low
        return identity, size

    parsed = PureWindowsPath(str(path))
    if not parsed.is_absolute() or not parsed.anchor or len(parsed.parts) < 2:
        _reject(code)
    handles: list[object] = []
    chunks: list[bytes] = []
    try:
        anchor = open_anchor(parsed.anchor)
        handles.append(anchor)
        held_chain: list[FilesystemObjectIdentity] = [
            inspect(anchor, directory=True)[0]
        ]
        for component in parsed.parts[1:-1]:
            directory_handle = open_relative(
                handles[-1], component, directory=True
            )
            handles.append(directory_handle)
            held_chain.append(inspect(directory_handle, directory=True)[0])
        expected_identities = tuple(
            identity for _name, identity in expected_chain
        )
        if (
            len(expected_identities) != len(held_chain)
            or expected_identities != tuple(held_chain)
        ):
            _reject(code)
        _before_component_relative_file_open(path)
        file_handle = open_relative(
            handles[-1], parsed.parts[-1], directory=False
        )
        handles.append(file_handle)
        file_identity, file_size = inspect(file_handle, directory=False)
        if file_size > max_bytes:
            _reject(code)
        _after_component_relative_file_open(path)
        total = 0
        buffer = ctypes.create_string_buffer(64 * 1024)
        while True:
            read = wintypes.DWORD()
            if not read_file(
                file_handle,
                buffer,
                len(buffer),
                ctypes.byref(read),
                None,
            ):
                _reject(code)
            if read.value == 0:
                break
            total += read.value
            if total > max_bytes or total > file_size:
                _reject(code)
            chunks.append(bytes(buffer.raw[: read.value]))
        if total != file_size:
            _reject(code)
        final_identity, final_size = inspect(file_handle, directory=False)
        if final_identity != file_identity or final_size != file_size:
            _reject(code)
        return b"".join(chunks), file_identity, file_size
    except RuntimeError:
        raise
    except (OSError, OverflowError, TypeError, ValueError):
        _reject(code)
    finally:
        close_failed = False
        for handle in reversed(handles):
            if not close_handle(handle):
                close_failed = True
        if close_failed:
            _reject(code)


def _stable_read_regular_file(
    path: Path,
    *,
    max_bytes: int,
    code: str,
    expected_identity: FilesystemObjectIdentity | None = None,
    expected_size: int | None = None,
    expected_parent_identities: tuple[FilesystemObjectIdentity, ...] | None = None,
) -> bytes:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or type(max_bytes) is not int
        or max_bytes < 0
        or (
            expected_parent_identities is not None
            and (
                type(expected_parent_identities) is not tuple
                or any(
                    type(identity) is not FilesystemObjectIdentity
                    for identity in expected_parent_identities
                )
            )
        )
    ):
        _reject(code)
    before_chain = _path_ancestor_chain(path, code=code)
    before_parent_identities = tuple(
        identity for _name, identity in before_chain
    )
    if (
        expected_parent_identities is not None
        and before_parent_identities != expected_parent_identities
    ):
        _reject(code)
    before = _plain_regular_stat(path, code=code)
    before_identity = _filesystem_identity(before)
    if (
        before.st_size > max_bytes
        or (expected_size is not None and before.st_size != expected_size)
        or (
            os.name != "nt"
            and expected_identity is not None
            and expected_identity != before_identity
        )
    ):
        _reject(code)
    if os.name == "nt":
        result, opened_identity, opened_size = _windows_component_relative_read(
            path,
            max_bytes=max_bytes,
            expected_chain=before_chain,
            code=code,
        )
        _after_component_relative_handles_closed(path)
        try:
            observed = _observe_plain_file(
                path,
                sha256(result).hexdigest(),
            )
        except RuntimeError:
            _reject(code)
        post_open_identity = FilesystemObjectIdentity(
            device=observed.volume_serial,
            inode=observed.file_index,
            file_type=1,
            reparse_tag=0,
            link_count=observed.link_count,
        )
        if (
            post_open_identity != opened_identity
            or observed.size != opened_size
            or opened_size != before.st_size
            or len(result) != opened_size
            or (
                expected_identity is not None
                and opened_identity != expected_identity
            )
        ):
            _reject(code)
    else:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = -1
        chunks: list[bytes] = []
        total = 0
        try:
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            opened_identity = _filesystem_identity(opened)
            if (
                opened_identity != before_identity
                or opened.st_size != before.st_size
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
            ):
                _reject(code)
            while True:
                chunk = os.read(
                    descriptor,
                    min(64 * 1024, max_bytes - total + 1),
                )
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes or total > before.st_size:
                    _reject(code)
                chunks.append(chunk)
            if total != before.st_size:
                _reject(code)
            after_open = os.fstat(descriptor)
            if (
                _filesystem_identity(after_open) != before_identity
                or after_open.st_size != before.st_size
            ):
                _reject(code)
        except RuntimeError:
            raise
        except OSError:
            _reject(code)
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    _reject(code)
        result = b"".join(chunks)
    after = _plain_regular_stat(path, code=code)
    after_chain = _path_ancestor_chain(path, code=code)
    if (
        _filesystem_identity(after) != before_identity
        or after.st_size != before.st_size
        or after_chain != before_chain
        or (
            expected_parent_identities is not None
            and tuple(identity for _name, identity in after_chain)
            != expected_parent_identities
        )
    ):
        _reject(code)
    return result


def _decode_canonical_json_file(payload: bytes, *, code: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if type(key) is not str or key in result:
                _reject(code)
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: _reject(code),
        )
    except RuntimeError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        _reject(code)
    if type(value) is not dict or _canonical_json_bytes(value) != payload:
        _reject(code)
    return value


def _snapshot_relative_parts(
    value: str,
    *,
    allow_dot: bool,
    code: str,
) -> tuple[str, ...]:
    if type(value) is not str or not value:
        _reject(code)
    normalized = value.replace("/", "\\")
    try:
        parsed = PureWindowsPath(normalized)
    except (TypeError, ValueError):
        _reject(code)
    if parsed.is_absolute() or parsed.anchor:
        _reject(code)
    if normalized == ".":
        if not allow_dot:
            _reject(code)
        return ()
    parts = parsed.parts
    if (
        not parts
        or any(part in {"", ".", ".."} for part in parts)
        or str(parsed) != normalized
    ):
        _reject(code)
    return tuple(parts)


@dataclass(frozen=True)
class _SnapshotRootOwnership:
    path: str
    parts: tuple[str, ...]
    ownership_prefix: str
    root: FilesystemRootSnapshot


@dataclass(frozen=True)
class _SnapshotOwnershipRecord:
    path: str
    value: FilesystemSnapshotEntry | FilesystemRootSnapshot
    owner: _SnapshotRootOwnership


@dataclass(frozen=True)
class _SnapshotOwnershipIndex:
    roots: tuple[_SnapshotRootOwnership, ...]
    records: tuple[_SnapshotOwnershipRecord, ...]


@dataclass(frozen=True)
class _FilesystemSnapshotIndexes:
    pre: _SnapshotOwnershipIndex
    post: _SnapshotOwnershipIndex
    created_paths: tuple[str, ...]
    changed_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]


def _snapshot_compare(left: str, right: str) -> int:
    try:
        return _windows_ordinal_compare(left, right)
    except RuntimeError:
        _reject(FILE_CHANGE_TRANSITION_INVALID)


def _copy_filesystem_identity(
    identity: FilesystemObjectIdentity,
) -> FilesystemObjectIdentity:
    if type(identity) is not FilesystemObjectIdentity:
        _reject(FILE_CHANGE_TRANSITION_INVALID)
    return FilesystemObjectIdentity(
        device=identity.device,
        inode=identity.inode,
        file_type=identity.file_type,
        reparse_tag=identity.reparse_tag,
        link_count=identity.link_count,
    )


def _copy_snapshot_entry(
    entry: FilesystemSnapshotEntry,
) -> FilesystemSnapshotEntry:
    if type(entry) is not FilesystemSnapshotEntry:
        _reject(FILE_CHANGE_TRANSITION_INVALID)
    return FilesystemSnapshotEntry(
        relative_path=str(entry.relative_path),
        kind=entry.kind,
        size=entry.size,
        sha256=None if entry.sha256 is None else str(entry.sha256),
        link_count=entry.link_count,
        identity=_copy_filesystem_identity(entry.identity),
    )


def _copy_snapshot_root(
    root: FilesystemRootSnapshot,
) -> FilesystemRootSnapshot:
    if type(root) is not FilesystemRootSnapshot:
        _reject(FILE_CHANGE_TRANSITION_INVALID)
    return FilesystemRootSnapshot(
        root_index=root.root_index,
        relative_root=str(root.relative_root),
        present=root.present,
        root_identity=(
            None
            if root.root_identity is None
            else _copy_filesystem_identity(root.root_identity)
        ),
        ancestor_identities=tuple(
            _copy_filesystem_identity(identity)
            for identity in root.ancestor_identities
        ),
        entries=tuple(_copy_snapshot_entry(entry) for entry in root.entries),
        manifest_sha256=str(root.manifest_sha256),
    )


def _build_snapshot_ownership_index(
    roots: tuple[FilesystemRootSnapshot, ...],
) -> _SnapshotOwnershipIndex:
    if type(roots) is not tuple or any(
        type(root) is not FilesystemRootSnapshot for root in roots
    ):
        _reject(FILE_CHANGE_TRANSITION_INVALID)
    detached_roots = tuple(_copy_snapshot_root(root) for root in roots)
    root_values: list[_SnapshotRootOwnership] = []
    for root in detached_roots:
        parts = _snapshot_relative_parts(
            root.relative_root,
            allow_dot=True,
            code=FILE_CHANGE_TRANSITION_INVALID,
        )
        path = "." if not parts else str(PureWindowsPath(*parts))
        root_values.append(
            _SnapshotRootOwnership(
                path=path,
                parts=parts,
                ownership_prefix=("" if not parts else path + "\\"),
                root=root,
            )
        )
    ordered_roots = tuple(
        sorted(
            root_values,
            key=cmp_to_key(
                lambda left, right: _snapshot_compare(
                    left.ownership_prefix,
                    right.ownership_prefix,
                )
            ),
        )
    )
    if any(not root.parts for root in ordered_roots) and len(ordered_roots) != 1:
        _reject(FILE_CHANGE_TRANSITION_INVALID)
    for before, after in zip(ordered_roots, ordered_roots[1:]):
        if (
            _ordinal_parts_prefix(
                before.parts,
                after.parts,
                code=FILE_CHANGE_TRANSITION_INVALID,
            )
            or _ordinal_parts_prefix(
                after.parts,
                before.parts,
                code=FILE_CHANGE_TRANSITION_INVALID,
            )
        ):
            _reject(FILE_CHANGE_TRANSITION_INVALID)

    records: list[_SnapshotOwnershipRecord] = []
    for owner in ordered_roots:
        root = owner.root
        if not root.present:
            continue
        records.append(
            _SnapshotOwnershipRecord(
                path=owner.path,
                value=root,
                owner=owner,
            )
        )
        for entry in root.entries:
            entry_parts = _snapshot_relative_parts(
                entry.relative_path,
                allow_dot=False,
                code=FILE_CHANGE_TRANSITION_INVALID,
            )
            full_parts = (*owner.parts, *entry_parts)
            full = str(PureWindowsPath(*full_parts))
            records.append(
                _SnapshotOwnershipRecord(
                    path=full,
                    value=entry,
                    owner=owner,
                )
            )
    ordered_records = tuple(
        sorted(
            records,
            key=cmp_to_key(
                lambda left, right: _snapshot_compare(left.path, right.path)
            ),
        )
    )
    for before, after in zip(ordered_records, ordered_records[1:]):
        if _snapshot_compare(before.path, after.path) == 0:
            _reject(FILE_CHANGE_TRANSITION_INVALID)
    return _SnapshotOwnershipIndex(
        roots=ordered_roots,
        records=ordered_records,
    )


def _snapshot_index_lookup(
    index: _SnapshotOwnershipIndex,
    path: str,
) -> _SnapshotOwnershipRecord | None:
    if type(index) is not _SnapshotOwnershipIndex or type(path) is not str:
        _reject(FILE_CHANGE_TRANSITION_INVALID)
    lower = 0
    upper = len(index.records)
    while lower < upper:
        middle = lower + (upper - lower) // 2
        record = index.records[middle]
        comparison = _snapshot_compare(record.path, path)
        if comparison < 0:
            lower = middle + 1
        elif comparison > 0:
            upper = middle
        else:
            return record
    return None


def _snapshot_containing_root(
    index: _SnapshotOwnershipIndex,
    relative_parts: tuple[str, ...],
) -> _SnapshotRootOwnership | None:
    if type(index) is not _SnapshotOwnershipIndex or type(relative_parts) is not tuple:
        _reject(FILE_CHANGE_TRANSITION_INVALID)
    if not index.roots:
        return None
    if not index.roots[0].parts:
        return index.roots[0] if relative_parts else None
    path = str(PureWindowsPath(*relative_parts))
    lower = 0
    upper = len(index.roots)
    while lower < upper:
        middle = lower + (upper - lower) // 2
        if _snapshot_compare(index.roots[middle].ownership_prefix, path) <= 0:
            lower = middle + 1
        else:
            upper = middle
    if lower == 0:
        return None
    candidate = index.roots[lower - 1]
    if (
        len(relative_parts) <= len(candidate.parts)
        or not _ordinal_parts_prefix(
            candidate.parts,
            relative_parts,
            code=FILE_CHANGE_TRANSITION_INVALID,
        )
    ):
        return None
    return candidate


def _snapshot_entries(
    roots: tuple[FilesystemRootSnapshot, ...],
) -> dict[str, FilesystemSnapshotEntry | FilesystemRootSnapshot]:
    index = _build_snapshot_ownership_index(roots)
    return {record.path: record.value for record in index.records}


def _lexical_case_relative_parts(
    path: Path,
    *,
    case_root: Path,
    code: str,
    required: bool,
) -> tuple[str, ...] | None:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or not isinstance(case_root, Path)
        or not case_root.is_absolute()
    ):
        _reject(code)
    try:
        absolute_path = Path(os.path.abspath(path))
        absolute_case = Path(os.path.abspath(case_root))
        _path_text, path_parts = _normalize_absolute_windows_path(
            str(absolute_path),
            code=code,
            permit_root=False,
        )
        _case_text, case_parts = _normalize_absolute_windows_path(
            str(absolute_case),
            code=code,
            permit_root=True,
        )
    except RuntimeError:
        raise
    except (OSError, ValueError):
        _reject(code)
    if (
        len(path_parts) <= len(case_parts)
        or not _ordinal_parts_prefix(case_parts, path_parts, code=code)
    ):
        if required:
            _reject(code)
        return None
    return tuple(path_parts[len(case_parts) :])


def _workspace_relative_root(context: FileChangePolicyContext) -> str:
    parts = _lexical_case_relative_parts(
        context.workspace_root,
        case_root=context.case_root,
        code=FILE_CHANGE_POLICY_CONTEXT_INVALID,
        required=True,
    )
    assert parts is not None
    return str(PureWindowsPath(*parts))


def _global_snapshot_path(
    normalized_path: str,
    *,
    context: FileChangePolicyContext,
) -> str:
    prefix = "<workspace>\\"
    if not normalized_path.startswith(prefix):
        _reject(FILE_CHANGE_PATH_POLICY_INVALID)
    relative = normalized_path[len(prefix) :]
    if not relative or PureWindowsPath(relative).is_absolute():
        _reject(FILE_CHANGE_PATH_POLICY_INVALID)
    return str(PureWindowsPath(_workspace_relative_root(context)) / relative)


def _case_relative_snapshot_path(
    path: Path,
    *,
    context: FileChangePolicyContext,
    code: str,
) -> str:
    parts = _lexical_case_relative_parts(
        path,
        case_root=context.case_root,
        code=code,
        required=True,
    )
    assert parts is not None
    return str(PureWindowsPath(*parts))


def _entry_is_plain(
    value: FilesystemSnapshotEntry | FilesystemRootSnapshot | None,
    *,
    kind: str,
) -> bool:
    if kind == "file":
        return (
            type(value) is FilesystemSnapshotEntry
            and value.kind == "file"
            and value.identity.reparse_tag == 0
            and value.link_count == 1
            and value.identity.link_count == 1
        )
    if type(value) is FilesystemRootSnapshot:
        return (
            value.present
            and value.root_identity is not None
            and value.root_identity.reparse_tag == 0
            and value.root_identity.link_count == 1
        )
    return (
        type(value) is FilesystemSnapshotEntry
        and value.kind == "directory"
        and value.identity.reparse_tag == 0
        and value.link_count == 1
        and value.identity.link_count == 1
    )


def _entry_identity(
    value: FilesystemSnapshotEntry | FilesystemRootSnapshot,
) -> FilesystemObjectIdentity:
    if type(value) is FilesystemSnapshotEntry:
        return value.identity
    if type(value) is FilesystemRootSnapshot and value.root_identity is not None:
        return value.root_identity
    _reject(FILE_CHANGE_TRANSITION_INVALID)


def _post_snapshot_file_binding(
    path: Path,
    *,
    context: FileChangePolicyContext,
    post_index: _SnapshotOwnershipIndex,
    code: str,
    required: bool,
    expected_entry: FilesystemSnapshotEntry | None = None,
) -> tuple[
    FilesystemSnapshotEntry,
    tuple[FilesystemObjectIdentity, ...],
] | None:
    relative_parts = _lexical_case_relative_parts(
        path,
        case_root=context.case_root,
        code=code,
        required=required,
    )
    if relative_parts is None:
        return None
    owner = _snapshot_containing_root(post_index, relative_parts)
    if owner is None or not owner.root.present:
        if required:
            _reject(code)
        return None
    root = owner.root
    root_parts = owner.parts
    if not _entry_is_plain(root, kind="directory"):
        _reject(code)
    assert root.root_identity is not None
    entry_parts = tuple(relative_parts[len(root_parts) :])
    full_path = str(PureWindowsPath(*relative_parts))
    file_record = _snapshot_index_lookup(post_index, full_path)
    if (
        file_record is None
        or file_record.owner is not owner
        or not _entry_is_plain(file_record.value, kind="file")
    ):
        _reject(code)
    assert type(file_record.value) is FilesystemSnapshotEntry
    file_entry = file_record.value
    if expected_entry is not None and file_entry != expected_entry:
        _reject(code)

    identities = [*root.ancestor_identities, root.root_identity]
    for depth in range(1, len(entry_parts)):
        parent_path = str(
            PureWindowsPath(*root_parts, *entry_parts[:depth])
        )
        parent_record = _snapshot_index_lookup(post_index, parent_path)
        if (
            parent_record is None
            or parent_record.owner is not owner
            or not _entry_is_plain(parent_record.value, kind="directory")
        ):
            _reject(code)
        assert type(parent_record.value) is FilesystemSnapshotEntry
        identities.append(parent_record.value.identity)
    return file_entry, tuple(identities)


def _bind_transitions(
    plan: DecodedFileChangePlan,
    *,
    sources: tuple[FileChangeContentSource, ...],
    context: FileChangePolicyContext,
    snapshot_indexes: _FilesystemSnapshotIndexes,
) -> tuple[
    tuple[BoundFileChange, ...],
    tuple[str, ...],
    tuple[str, ...],
    dict[str, tuple[FilesystemSnapshotEntry, FilesystemSnapshotEntry]],
]:
    _require_ordinal_unique(
        tuple(rule.normalized_path for rule in context.rules),
        code=FILE_CHANGE_POLICY_CONTEXT_INVALID,
    )
    rules = {rule.normalized_path: rule for rule in context.rules}
    if len(rules) != len(context.rules):
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    for change in plan.changes:
        if change.normalized_path not in rules:
            _reject(FILE_CHANGE_PATH_POLICY_INVALID)

    source_by_key: dict[str, FileChangeContentSource] = {}
    _require_ordinal_unique(
        tuple(source.normalized_path for source in sources),
        code=FILE_CHANGE_CONTENT_INVALID,
    )
    for source in sources:
        key = source.normalized_path
        if key in source_by_key:
            _reject(FILE_CHANGE_CONTENT_INVALID)
        source_by_key[key] = source

    pre_roots = snapshot_indexes.pre.roots
    post_roots = snapshot_indexes.post.roots
    if len(pre_roots) != len(post_roots):
        _reject(FILE_CHANGE_TRANSITION_INVALID)
    for before_owner, after_owner in zip(
        pre_roots,
        post_roots,
        strict=True,
    ):
        before_root = before_owner.root
        after_root = after_owner.root
        if (
            _snapshot_compare(before_owner.path, after_owner.path) != 0
            or before_root.present != after_root.present
            or before_root.ancestor_identities != after_root.ancestor_identities
        ):
            _reject(FILE_CHANGE_TRANSITION_INVALID)
        if not before_root.present:
            if (
                before_root.root_identity is not None
                or after_root.root_identity is not None
                or before_root.entries
                or after_root.entries
            ):
                _reject(FILE_CHANGE_TRANSITION_INVALID)
            continue
        if (
            not _entry_is_plain(before_root, kind="directory")
            or not _entry_is_plain(after_root, kind="directory")
            or _entry_identity(before_root) != _entry_identity(after_root)
        ):
            _reject(FILE_CHANGE_TRANSITION_INVALID)
    grouped: dict[str, list[DecodedFileChange]] = {}
    spelling: dict[str, str] = {}
    for change in plan.changes:
        key = change.normalized_path
        grouped.setdefault(key, []).append(change)
        spelling[key] = change.normalized_path
    _enforce_content_account(
        unique_documents=len(grouped),
        raw_bytes=0,
        retained_bytes=0,
    )

    pre = snapshot_indexes.pre
    post = snapshot_indexes.post
    expected_created: set[str] = set()
    expected_changed: set[str] = set()
    post_files: dict[
        str, tuple[FilesystemSnapshotEntry, FilesystemSnapshotEntry]
    ] = {}
    implicit: set[str] = set()

    for key, changes in grouped.items():
        normalized = spelling[key]
        source = source_by_key.get(key)
        if source is None:
            fallback = _global_snapshot_path(normalized, context=context)
            physical_paths = (fallback, fallback)
        else:
            physical_paths = (
                _case_relative_snapshot_path(
                    source.raw_path,
                    context=context,
                    code=FILE_CHANGE_CONTENT_INVALID,
                ),
                _case_relative_snapshot_path(
                    source.retained_path,
                    context=context,
                    code=FILE_CHANGE_CONTENT_INVALID,
                ),
            )
        physical_entries: list[FilesystemSnapshotEntry] = []
        first_kind = changes[0].kind
        if first_kind == "add" and any(
            change.kind != "update" for change in changes[1:]
        ):
            _reject(FILE_CHANGE_TRANSITION_INVALID)
        if first_kind == "update" and any(
            change.kind != "update" for change in changes
        ):
            _reject(FILE_CHANGE_TRANSITION_INVALID)

        for global_path in physical_paths:
            global_key = global_path
            before_match = _snapshot_index_lookup(pre, global_key)
            after_match = _snapshot_index_lookup(post, global_key)
            before = None if before_match is None else before_match.value
            after = None if after_match is None else after_match.value
            if not _entry_is_plain(after, kind="file"):
                _reject(FILE_CHANGE_TRANSITION_INVALID)
            assert type(after) is FilesystemSnapshotEntry
            physical_entries.append(after)
            assert after_match is not None
            snapshot_key = after_match.path
            if first_kind == "add":
                if before is not None:
                    _reject(FILE_CHANGE_TRANSITION_INVALID)
                expected_created.add(snapshot_key)
            else:
                if not _entry_is_plain(before, kind="file"):
                    _reject(FILE_CHANGE_TRANSITION_INVALID)
                expected_changed.add(snapshot_key)
        post_files[key] = (physical_entries[0], physical_entries[1])

        relative = normalized[len("<workspace>\\") :]
        relative_parts = PureWindowsPath(relative).parts
        parent = PureWindowsPath(relative).parent
        parents: list[str] = []
        while str(parent) not in {".", ""}:
            parents.append(str(parent))
            parent = parent.parent
        for relative_parent in reversed(parents):
            normalized_parent = "<workspace>\\" + relative_parent
            parent_parts = PureWindowsPath(relative_parent).parts
            for global_path in dict.fromkeys(physical_paths):
                global_parts = PureWindowsPath(global_path).parts
                if (
                    len(global_parts) <= len(relative_parts)
                    or _path_key(tuple(global_parts[-len(relative_parts) :]))
                    != _path_key(tuple(relative_parts))
                ):
                    _reject(FILE_CHANGE_TRANSITION_INVALID)
                mirror_root = global_parts[: -len(relative_parts)]
                global_parent = str(
                    PureWindowsPath(*mirror_root, *parent_parts)
                )
                parent_key = global_parent
                before_parent_match = _snapshot_index_lookup(pre, parent_key)
                after_parent_match = _snapshot_index_lookup(post, parent_key)
                before_parent = (
                    None if before_parent_match is None else before_parent_match.value
                )
                after_parent = (
                    None if after_parent_match is None else after_parent_match.value
                )
                if before_parent is None:
                    if not _entry_is_plain(after_parent, kind="directory"):
                        _reject(FILE_CHANGE_TRANSITION_INVALID)
                    assert after_parent_match is not None
                    expected_created.add(after_parent_match.path)
                    implicit.add(normalized_parent)
                elif (
                    not _entry_is_plain(before_parent, kind="directory")
                    or not _entry_is_plain(after_parent, kind="directory")
                    or _entry_identity(before_parent)
                    != _entry_identity(after_parent)
                ):
                    _reject(FILE_CHANGE_TRANSITION_INVALID)

    actual_created = set(snapshot_indexes.created_paths)
    actual_changed = set(snapshot_indexes.changed_paths)
    actual_removed = set(snapshot_indexes.removed_paths)
    if (
        not expected_created <= actual_created
        or not expected_changed <= actual_changed
        or expected_created & (actual_changed | actual_removed)
        or expected_changed & (actual_created | actual_removed)
        or actual_created & actual_changed
        or actual_created & actual_removed
        or actual_changed & actual_removed
    ):
        _reject(FILE_CHANGE_TRANSITION_INVALID)

    bound = tuple(
        BoundFileChange(
            started_event_ordinal=change.started_event_ordinal,
            completed_event_ordinal=change.completed_event_ordinal,
            event_id=change.event_id,
            change_ordinal=change.change_ordinal,
            normalized_path=change.normalized_path,
            kind=change.kind,
            role=rules[change.normalized_path].role,
        )
        for change in plan.changes
    )
    unique = tuple(sorted(spelling.values()))
    return (
        bound,
        tuple(sorted(implicit)),
        unique,
        post_files,
    )


_LEDGER_SCHEMA_PATH = (
    Path(__file__).resolve().parent
    / "complete-suite-file-change-ledger.schema.json"
)
_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "v1"
_SANITIZER_RECORD_FIELDS = {
    "version",
    "normalized_path",
    "raw_path_sha256",
    "retained_path_sha256",
    "raw_size",
    "raw_sha256",
    "retained_size",
    "retained_sha256",
    "redaction_count",
    "redaction_classes",
}


def _load_sanitizer_membership(
    context: FileChangePolicyContext,
    *,
    post_index: _SnapshotOwnershipIndex,
) -> dict[str, tuple[Path, str]]:
    ledger_binding = _post_snapshot_file_binding(
        context.sanitizer_ledger_path,
        context=context,
        post_index=post_index,
        code=FILE_CHANGE_SANITIZER_INVALID,
        required=False,
    )
    ledger_snapshot = None if ledger_binding is None else ledger_binding[0]
    ledger_parent_identities = (
        None if ledger_binding is None else ledger_binding[1]
    )
    if (
        ledger_snapshot is not None
        and (
            ledger_snapshot.identity != context.sanitizer_ledger_identity
            or ledger_snapshot.sha256 != context.sanitizer_ledger_sha256
        )
    ):
        _reject(FILE_CHANGE_SANITIZER_INVALID)
    ledger_bytes = _stable_read_regular_file(
        context.sanitizer_ledger_path,
        max_bytes=64 * 1024,
        code=FILE_CHANGE_SANITIZER_INVALID,
        expected_identity=context.sanitizer_ledger_identity,
        expected_size=(None if ledger_snapshot is None else ledger_snapshot.size),
        expected_parent_identities=ledger_parent_identities,
    )
    if sha256(ledger_bytes).hexdigest() != context.sanitizer_ledger_sha256:
        _reject(FILE_CHANGE_SANITIZER_INVALID)
    ledger = _decode_canonical_json_file(
        ledger_bytes,
        code=FILE_CHANGE_SANITIZER_INVALID,
    )
    try:
        schema = json.loads(_LEDGER_SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = tuple(Draft202012Validator(schema).iter_errors(ledger))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        _reject(FILE_CHANGE_SANITIZER_INVALID)
    if errors:
        _reject(FILE_CHANGE_SANITIZER_INVALID)
    records = ledger["records"]
    membership: dict[str, tuple[Path, str]] = {}
    order: list[str] = []
    for record in records:
        normalized = record["normalized_path"]
        key = normalized
        if key in membership:
            _reject(FILE_CHANGE_SANITIZER_INVALID)
        path = Path(record["sanitizer_record_path"])
        try:
            path_parent = Path(os.path.abspath(path.parent))
            ledger_parent = Path(
                os.path.abspath(context.sanitizer_ledger_path.parent)
            )
            if (
                not path.is_absolute()
                or str(path_parent) != str(ledger_parent)
            ):
                _reject(FILE_CHANGE_SANITIZER_INVALID)
        except (OSError, RuntimeError, ValueError):
            _reject(FILE_CHANGE_SANITIZER_INVALID)
        membership[key] = (path, record["sanitizer_record_sha256"])
        order.append(normalized)
    if order != sorted(order):
        _reject(FILE_CHANGE_SANITIZER_INVALID)
    _require_ordinal_unique(
        tuple(order),
        code=FILE_CHANGE_SANITIZER_INVALID,
    )
    return membership


def _enforce_semantic_bounds(
    value: object,
    *,
    max_depth: int = 64,
    max_nodes: int = 8192,
    max_members: int = 1024,
    max_scalar_chars: int = 16_384,
) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > max_depth or nodes > max_nodes:
            _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
        if type(current) is dict:
            if len(current) > max_members:
                _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
            for key, child in current.items():
                if type(key) is not str or len(key) > max_scalar_chars:
                    _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
                stack.append((key, depth + 1))
                stack.append((child, depth + 1))
        elif type(current) is list:
            if len(current) > max_members:
                _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
            stack.extend((child, depth + 1) for child in current)
        elif type(current) is str:
            if len(current) > max_scalar_chars:
                _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
        elif current is not None and type(current) not in {bool, int, float}:
            _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)


def _decode_role_document(payload: bytes, *, yaml_document: bool) -> dict[str, Any]:
    try:
        if yaml_document:
            value = parse_yaml_bytes(payload)
        else:
            value = _decode_canonical_or_framed_json(payload)
    except RuntimeError:
        raise
    except (KokoroError, UnicodeError, ValueError, TypeError):
        _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)
    _enforce_semantic_bounds(value)
    return value


def _decode_canonical_or_framed_json(payload: bytes) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if type(key) is not str or key in result:
                _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID),
        )
    except RuntimeError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)
    if type(value) is not dict:
        _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)
    return value


def _validate_role_document(
    payload: bytes,
    *,
    rule: FileChangePathRule,
) -> tuple[dict[str, Any], str]:
    yaml_document = rule.role == "authoring_source" and not rule.normalized_path.endswith(
        ".json"
    )
    document = _decode_role_document(payload, yaml_document=yaml_document)
    if rule.required_schema == "test-corpus":
        _enforce_semantic_bounds(
            document,
            max_depth=16,
            max_nodes=4096,
            max_members=256,
            max_scalar_chars=4096,
        )
        cases = document.get("cases")
        if type(cases) is list and len(cases) > 128:
            _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
    registry = SchemaRegistry(_SCHEMA_ROOT)
    validation_fact: object = {
        "role": rule.role,
        "required_schema": rule.required_schema,
        "valid": True,
    }
    try:
        if rule.role in {
            "authoring_request",
            "authoring_validation_result",
            "semantic_result",
            "language_policy",
            "render_plan",
        }:
            assert rule.required_schema is not None
            registry.validate(rule.required_schema, document)
        elif rule.role == "policy_input":
            validation_fact = normalize_policy(document)
        elif rule.role in {"authoring_source", "rendered_output"}:
            pass
        else:
            _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)
    except (AssertionError, KokoroError, KeyError, TypeError, ValueError):
        _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)
    canonical_document = _canonical_json_bytes(document)
    return document, sha256(_canonical_json_bytes(validation_fact)).hexdigest()


def _source_mirror_root(
    source_path: Path,
    *,
    normalized_path: str,
) -> Path:
    prefix = "<workspace>\\"
    if not normalized_path.startswith(prefix) or not source_path.is_absolute():
        _reject(FILE_CHANGE_CONTENT_INVALID)
    relative_parts = PureWindowsPath(normalized_path[len(prefix) :]).parts
    absolute = Path(os.path.abspath(source_path))
    if (
        not relative_parts
        or len(absolute.parts) <= len(relative_parts)
        or _path_key(tuple(absolute.parts[-len(relative_parts) :]))
        != _path_key(tuple(relative_parts))
    ):
        _reject(FILE_CHANGE_CONTENT_INVALID)
    root = absolute
    for _part in relative_parts:
        root = root.parent
    return root


def _bound_post_file_entry(
    path: Path,
    *,
    context: FileChangePolicyContext,
    post_index: _SnapshotOwnershipIndex,
) -> FilesystemSnapshotEntry:
    binding = _post_snapshot_file_binding(
        path,
        context=context,
        post_index=post_index,
        code=FILE_CHANGE_CONTENT_INVALID,
        required=True,
    )
    assert binding is not None
    return binding[0]


def _read_bound_post_file(
    path: Path,
    *,
    context: FileChangePolicyContext,
    post_index: _SnapshotOwnershipIndex,
    max_bytes: int,
) -> bytes:
    binding = _post_snapshot_file_binding(
        path,
        context=context,
        post_index=post_index,
        code=FILE_CHANGE_CONTENT_INVALID,
        required=True,
    )
    assert binding is not None
    post, parent_identities = binding
    payload = _stable_read_regular_file(
        path,
        max_bytes=max_bytes,
        code=FILE_CHANGE_CONTENT_INVALID,
        expected_identity=post.identity,
        expected_size=post.size,
        expected_parent_identities=parent_identities,
    )
    if sha256(payload).hexdigest() != post.sha256:
        _reject(FILE_CHANGE_CONTENT_INVALID)
    return payload


def _enforce_source_pack_size_account(files: dict[str, int]) -> None:
    if (
        type(files) is not dict
        or len(files) > _MAX_SOURCE_PACK_FILES
        or any(type(path) is not str for path in files)
        or any(type(size) is not int or size < 0 for size in files.values())
    ):
        _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
    source_total = 0
    corpus_total = 0
    for relative, size in files.items():
        try:
            depth = len(PurePosixPath(relative).parts)
        except (TypeError, ValueError):
            _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
        if (
            depth > _MAX_SOURCE_DEPTH
            or size > _MAX_SOURCE_FILE_BYTES
        ):
            _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
        source_total += size
        if source_total > _MAX_SOURCE_PACK_BYTES:
            _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
        if relative.startswith("tests/"):
            if size > _MAX_CORPUS_FILE_BYTES:
                _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
            corpus_total += size
            if corpus_total > _MAX_CORPUS_BYTES:
                _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)


def _enforce_source_pack_account(files: dict[str, bytes]) -> None:
    if (
        type(files) is not dict
        or any(type(path) is not str for path in files)
        or any(type(payload) is not bytes for payload in files.values())
    ):
        _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
    _enforce_source_pack_size_account(
        {relative: len(payload) for relative, payload in files.items()}
    )


def _complete_authoring_snapshot(
    prepared: list[
        tuple[
            str,
            FileChangePathRule,
            bytes,
            bytes,
            str,
            dict[str, Any],
            dict[str, Any],
            str,
        ]
    ],
    sources: dict[str, FileChangeContentSource],
    *,
    context: FileChangePolicyContext,
    post_index: _SnapshotOwnershipIndex,
    domain: Literal["raw", "retained"],
) -> dict[str, bytes]:
    authoring = [item for item in prepared if item[1].role == "authoring_source"]
    if not authoring:
        return {}
    roots: dict[str, Path] = {}
    changed: dict[str, bytes] = {}
    prefix = "<workspace>\\" + _AUTHORING_ROOT + "\\"
    for item in authoring:
        normalized = item[0]
        if not normalized.startswith(prefix):
            _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)
        source = sources[normalized]
        selected_path = source.raw_path if domain == "raw" else source.retained_path
        root = _source_mirror_root(
            selected_path,
            normalized_path=normalized,
        )
        roots[str(root)] = root
        relative = normalized[len(prefix) :].replace("\\", "/")
        changed[relative] = item[2] if domain == "raw" else item[3]
    if len(roots) != 1:
        _reject(FILE_CHANGE_CONTENT_INVALID)
    mirror_root = next(iter(roots.values()))
    declared_sizes: dict[str, int] = {}
    unchanged_targets: dict[str, Path] = {}
    for relative in _AUTHORING_SOURCE_RELATIVES:
        posix_relative = relative.replace("\\", "/")
        payload = changed.get(posix_relative)
        if payload is not None:
            declared_sizes[posix_relative] = len(payload)
            continue
        target = mirror_root.joinpath(
            *PureWindowsPath(_AUTHORING_ROOT, relative).parts
        )
        unchanged_targets[posix_relative] = target
        declared_sizes[posix_relative] = _bound_post_file_entry(
            target,
            context=context,
            post_index=post_index,
        ).size
    _enforce_source_pack_size_account(declared_sizes)

    result: dict[str, bytes] = {}
    for relative in _AUTHORING_SOURCE_RELATIVES:
        posix_relative = relative.replace("\\", "/")
        payload = changed.get(posix_relative)
        max_bytes = (
            _MAX_CORPUS_FILE_BYTES
            if posix_relative.startswith("tests/")
            else _MAX_SOURCE_FILE_BYTES
        )
        if payload is None:
            payload = _read_bound_post_file(
                unchanged_targets[posix_relative],
                context=context,
                post_index=post_index,
                max_bytes=max_bytes,
            )
        if len(payload) > max_bytes:
            _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
        result[posix_relative] = payload
    _enforce_source_pack_account(result)
    corpus = {
        relative: payload
        for relative, payload in result.items()
        if relative.startswith("tests/")
    }
    try:
        load_source_pack_from_contents(result, SchemaRegistry(_SCHEMA_ROOT))
        load_test_corpus_from_contents(
            Path(_AUTHORING_ROOT),
            corpus,
            CorpusLimits(),
        )
    except KokoroError:
        _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)
    return result


def _validate_complete_runtime_snapshot(
    prepared: list[
        tuple[
            str,
            FileChangePathRule,
            bytes,
            bytes,
            str,
            dict[str, Any],
            dict[str, Any],
            str,
        ]
    ],
    sources: dict[str, FileChangeContentSource],
    *,
    context: FileChangePolicyContext,
    post_index: _SnapshotOwnershipIndex,
    domain: Literal["raw", "retained"],
) -> None:
    runtime = [
        item
        for item in prepared
        if item[1].role
        in {
            "policy_input",
            "semantic_result",
            "language_policy",
            "render_plan",
            "rendered_output",
        }
    ]
    if not runtime:
        return
    roots: dict[str, Path] = {}
    changed: dict[str, bytes] = {}
    changed_documents: dict[str, dict[str, Any]] = {}
    for item in runtime:
        normalized = item[0]
        source = sources[normalized]
        selected_path = source.raw_path if domain == "raw" else source.retained_path
        root = _source_mirror_root(
            selected_path,
            normalized_path=normalized,
        )
        roots[str(root)] = root
        changed[normalized] = (
            item[2] if domain == "raw" else item[3]
        )
        changed_documents[item[1].role] = (
            item[5] if domain == "raw" else item[6]
        )
    if len(roots) != 1:
        _reject(FILE_CHANGE_CONTENT_INVALID)
    if "rendered_output" not in changed_documents:
        return
    mirror_root = next(iter(roots.values()))
    rules_by_role = {rule.role: rule for rule in _WORKSPACE_RULES}
    documents: dict[str, dict[str, Any]] = {
        "rendered_output": changed_documents["rendered_output"]
    }
    for role in ("semantic_result", "render_plan"):
        changed_document = changed_documents.get(role)
        if changed_document is not None:
            documents[role] = changed_document
            continue
        rule = rules_by_role[role]
        payload = changed.get(rule.normalized_path)
        if payload is None:
            relative = rule.normalized_path[len("<workspace>\\") :]
            target = mirror_root.joinpath(*PureWindowsPath(relative).parts)
            payload = _read_bound_post_file(
                target,
                context=context,
                post_index=post_index,
                max_bytes=262_144,
            )
        document, _validation_sha = _validate_role_document(
            payload,
            rule=rule,
        )
        documents[role] = document
    try:
        result = validate_rendered_output(
            documents["rendered_output"],
            documents["semantic_result"],
            documents["render_plan"],
        )
    except (KokoroError, KeyError, TypeError, ValueError):
        _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)
    if result.get("valid") is not True:
        _reject(FILE_CHANGE_SCHEMA_ROLE_INVALID)


def _load_bound_contents(
    sources: tuple[FileChangeContentSource, ...],
    *,
    context: FileChangePolicyContext,
    unique_paths: tuple[str, ...],
    post_files: dict[
        str, tuple[FilesystemSnapshotEntry, FilesystemSnapshotEntry]
    ],
    post_index: _SnapshotOwnershipIndex,
    input_guard: Callable[[], None],
) -> tuple[BoundFileChangeContent, ...]:
    if len(sources) != len(unique_paths):
        _reject(FILE_CHANGE_CONTENT_INVALID)
    _enforce_content_account(
        unique_documents=len(sources),
        raw_bytes=0,
        retained_bytes=0,
    )
    by_key: dict[str, FileChangeContentSource] = {}
    for source in sources:
        key = source.normalized_path
        if key in by_key:
            _reject(FILE_CHANGE_CONTENT_INVALID)
        by_key[key] = source
    if set(by_key) != set(unique_paths):
        _reject(FILE_CHANGE_CONTENT_INVALID)
    membership = _load_sanitizer_membership(context, post_index=post_index)
    if set(membership) != set(by_key):
        _reject(FILE_CHANGE_SANITIZER_INVALID)
    rules = {rule.normalized_path: rule for rule in context.rules}

    declared_raw_total = 0
    declared_retained_total = 0
    prepared: list[
        tuple[
            str,
            FileChangePathRule,
            bytes,
            bytes,
            str,
            dict[str, Any],
            dict[str, Any],
            str,
        ]
    ] = []
    for normalized in unique_paths:
        key = normalized
        source = by_key[key]
        raw_post, retained_post = post_files[key]
        record_path, expected_record_sha = membership[key]
        try:
            source_record = Path(os.path.abspath(source.sanitizer_record_path))
            ledger_record = Path(os.path.abspath(record_path))
        except (OSError, RuntimeError, ValueError):
            _reject(FILE_CHANGE_SANITIZER_INVALID)
        if (
            not source.sanitizer_record_path.is_absolute()
            or str(source_record) != str(ledger_record)
        ):
            _reject(FILE_CHANGE_SANITIZER_INVALID)
        record_binding = _post_snapshot_file_binding(
            record_path,
            context=context,
            post_index=post_index,
            code=FILE_CHANGE_SANITIZER_INVALID,
            required=False,
        )
        record_snapshot = None if record_binding is None else record_binding[0]
        if (
            record_snapshot is not None
            and record_snapshot.sha256 != expected_record_sha
        ):
            _reject(FILE_CHANGE_SANITIZER_INVALID)
        record_bytes = _stable_read_regular_file(
            record_path,
            max_bytes=64 * 1024,
            code=FILE_CHANGE_SANITIZER_INVALID,
            expected_identity=(
                None if record_snapshot is None else record_snapshot.identity
            ),
            expected_size=(None if record_snapshot is None else record_snapshot.size),
            expected_parent_identities=(
                None if record_binding is None else record_binding[1]
            ),
        )
        if sha256(record_bytes).hexdigest() != expected_record_sha:
            _reject(FILE_CHANGE_SANITIZER_INVALID)
        record = _decode_canonical_json_file(
            record_bytes,
            code=FILE_CHANGE_SANITIZER_INVALID,
        )
        if (
            set(record) != _SANITIZER_RECORD_FIELDS
            or record.get("version")
            != "complete-suite-file-change-sanitizer-record-v1"
            or record.get("normalized_path") != normalized
            or record.get("raw_path_sha256")
            != sha256(str(source.raw_path).encode("utf-8")).hexdigest()
            or record.get("retained_path_sha256")
            != sha256(str(source.retained_path).encode("utf-8")).hexdigest()
            or type(record.get("raw_size")) is not int
            or type(record.get("retained_size")) is not int
            or not _is_sha256(record.get("raw_sha256"))
            or not _is_sha256(record.get("retained_sha256"))
            or type(record.get("redaction_count")) is not int
            or record["redaction_count"] < 0
            or type(record.get("redaction_classes")) is not list
            or any(type(value) is not str for value in record["redaction_classes"])
        ):
            _reject(FILE_CHANGE_SANITIZER_INVALID)
        raw_size = record["raw_size"]
        retained_size = record["retained_size"]
        if (
            not 0 <= raw_size <= _MAX_DOCUMENT_BYTES
            or not 0 <= retained_size <= _MAX_DOCUMENT_BYTES
        ):
            _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
        rule = rules[key]
        if rule.role == "authoring_source" and (
            raw_size > _MAX_SOURCE_FILE_BYTES
            or retained_size > _MAX_SOURCE_FILE_BYTES
        ):
            _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
        if rule.required_schema == "test-corpus" and (
            raw_size > _MAX_CORPUS_FILE_BYTES
            or retained_size > _MAX_CORPUS_FILE_BYTES
        ):
            _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
        declared_raw_total += raw_size
        declared_retained_total += retained_size
        _enforce_content_account(
            unique_documents=len(sources),
            raw_bytes=declared_raw_total,
            retained_bytes=declared_retained_total,
        )
        raw_binding = _post_snapshot_file_binding(
            source.raw_path,
            context=context,
            post_index=post_index,
            code=FILE_CHANGE_CONTENT_INVALID,
            required=True,
            expected_entry=raw_post,
        )
        retained_binding = _post_snapshot_file_binding(
            source.retained_path,
            context=context,
            post_index=post_index,
            code=FILE_CHANGE_CONTENT_INVALID,
            required=True,
            expected_entry=retained_post,
        )
        assert raw_binding is not None and retained_binding is not None
        raw_bytes = _stable_read_regular_file(
            source.raw_path,
            max_bytes=_MAX_DOCUMENT_BYTES,
            code=FILE_CHANGE_CONTENT_INVALID,
            expected_identity=raw_post.identity,
            expected_size=raw_post.size,
            expected_parent_identities=raw_binding[1],
        )
        retained_bytes = _stable_read_regular_file(
            source.retained_path,
            max_bytes=_MAX_DOCUMENT_BYTES,
            code=FILE_CHANGE_CONTENT_INVALID,
            expected_identity=retained_post.identity,
            expected_size=retained_post.size,
            expected_parent_identities=retained_binding[1],
        )
        if (
            len(raw_bytes) != raw_size
            or len(retained_bytes) != retained_size
            or sha256(raw_bytes).hexdigest() != record["raw_sha256"]
            or sha256(retained_bytes).hexdigest() != record["retained_sha256"]
            or sha256(raw_bytes).hexdigest() != raw_post.sha256
            or sha256(retained_bytes).hexdigest() != retained_post.sha256
        ):
            _reject(FILE_CHANGE_CONTENT_INVALID)
        try:
            expected_retained, summary = sanitize_artifact(raw_bytes)
        except (TypeError, ValueError):
            _reject(FILE_CHANGE_SANITIZER_INVALID)
        if (
            expected_retained != retained_bytes
            or summary.get("redaction_count") != record["redaction_count"]
            or summary.get("redaction_classes") != record["redaction_classes"]
        ):
            _reject(FILE_CHANGE_SANITIZER_INVALID)
        raw_document, raw_validation = _validate_role_document(
            raw_bytes,
            rule=rule,
        )
        retained_document, retained_validation = _validate_role_document(
            retained_bytes,
            rule=rule,
        )
        validation_sha = sha256(
            _canonical_json_bytes(
                {
                    "raw": raw_validation,
                    "retained": retained_validation,
                    "role": rule.role,
                }
            )
        ).hexdigest()
        prepared.append(
            (
                normalized,
                rule,
                raw_bytes,
                retained_bytes,
                expected_record_sha,
                raw_document,
                retained_document,
                validation_sha,
            )
        )

    for domain_name in ("raw", "retained"):
        _complete_authoring_snapshot(
            prepared,
            by_key,
            context=context,
            post_index=post_index,
            domain=domain_name,
        )
        _validate_complete_runtime_snapshot(
            prepared,
            by_key,
            context=context,
            post_index=post_index,
            domain=domain_name,
        )

    input_guard()
    result: list[BoundFileChangeContent] = []
    for (
        normalized,
        _rule_value,
        raw_bytes,
        retained_bytes,
        sanitizer_record_sha,
        raw_document,
        retained_document,
        validation_sha,
    ) in prepared:
        result.append(
            _make_bound_content(
                normalized_path=normalized,
                raw_bytes=raw_bytes,
                retained_bytes=retained_bytes,
                raw_document_sha256=sha256(
                    _canonical_json_bytes(raw_document)
                ).hexdigest(),
                retained_document_sha256=sha256(
                    _canonical_json_bytes(retained_document)
                ).hexdigest(),
                sanitizer_record_sha256=sanitizer_record_sha,
                role_validation_sha256=validation_sha,
            )
        )
    return tuple(result)


def authorize_file_change_events(
    raw_session_bytes: bytes,
    retained_session_bytes: bytes,
    content_sources: tuple[FileChangeContentSource, ...],
    *,
    context: FileChangePolicyContext,
) -> FileChangePolicyDecision:
    if (
        type(raw_session_bytes) is not bytes
        or type(retained_session_bytes) is not bytes
        or type(content_sources) is not tuple
    ):
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    if len(content_sources) > _MAX_UNIQUE_DOCUMENTS:
        _reject(FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED)
    if (
        any(type(value) is not FileChangeContentSource for value in content_sources)
        or type(context) is not FileChangePolicyContext
    ):
        _reject(FILE_CHANGE_POLICY_CONTEXT_INVALID)
    original_context = context
    original_sources = content_sources
    for source in original_sources:
        source.__post_init__()
    original_context.__post_init__()
    _authenticate_filesystem_evidence(
        original_context.filesystem,
        expected_case_root=original_context.case_root,
    )
    context_fingerprint = _context_fingerprint(original_context)
    source_fingerprints = tuple(
        _source_fingerprint(source) for source in original_sources
    )
    context = FileChangePolicyContext(
        variant=str(original_context.variant),
        case_id=str(original_context.case_id),
        case_root=Path(str(original_context.case_root)),
        workspace_root=Path(str(original_context.workspace_root)),
        rules=tuple(_detach_rule(rule) for rule in original_context.rules),
        filesystem=original_context.filesystem,
        sanitizer_ledger_path=Path(
            str(original_context.sanitizer_ledger_path)
        ),
        sanitizer_ledger_identity=original_context.sanitizer_ledger_identity,
        sanitizer_ledger_sha256=str(original_context.sanitizer_ledger_sha256),
    )
    content_sources = tuple(
        _detach_source(source) for source in original_sources
    )
    detached_context_fingerprint = _context_fingerprint(context)
    detached_source_fingerprints = tuple(
        _source_fingerprint(source) for source in content_sources
    )

    def input_guard() -> None:
        _revalidate_authorizer_inputs(
            original_context,
            original_sources,
            context_fingerprint=context_fingerprint,
            source_fingerprints=source_fingerprints,
        )
        _revalidate_authorizer_inputs(
            context,
            content_sources,
            context_fingerprint=detached_context_fingerprint,
            source_fingerprints=detached_source_fingerprints,
        )

    snapshot_indexes = _FilesystemSnapshotIndexes(
        pre=_build_snapshot_ownership_index(context.filesystem.pre_roots),
        post=_build_snapshot_ownership_index(context.filesystem.post_roots),
        created_paths=tuple(context.filesystem.created_paths),
        changed_paths=tuple(context.filesystem.changed_paths),
        removed_paths=tuple(context.filesystem.removed_paths),
    )
    raw_bindings, retained_bindings = _bindings_for_sources(
        content_sources,
        context=context,
    )
    raw = decode_file_change_lifecycles(
        raw_session_bytes,
        domain="raw",
        root_bindings=raw_bindings,
    )
    retained = decode_file_change_lifecycles(
        retained_session_bytes,
        domain="retained",
        root_bindings=retained_bindings,
    )
    raw_topology = tuple(
        (
            value.lifecycle_index,
            value.event_id,
            value.started_event_ordinal,
            value.completed_event_ordinal,
            value.change_ordinal,
            value.normalized_path,
            value.kind,
        )
        for value in raw.changes
    )
    retained_topology = tuple(
        (
            value.lifecycle_index,
            value.event_id,
            value.started_event_ordinal,
            value.completed_event_ordinal,
            value.change_ordinal,
            value.normalized_path,
            value.kind,
        )
        for value in retained.changes
    )
    if (
        raw.lifecycles != retained.lifecycles
        or raw.transition_entries != retained.transition_entries
        or raw_topology != retained_topology
        or raw.topology_sha256 != retained.topology_sha256
    ):
        _reject(FILE_CHANGE_TOPOLOGY_MISMATCH)
    normalized_plan_sha256 = sha256(
        _canonical_json_bytes(
            {
                "version": _PLAN_VERSION,
                "topology_sha256": raw.topology_sha256,
                "lifecycles": raw.lifecycles,
                "transition_entries": raw.transition_entries,
            }
        )
    ).hexdigest()
    bound_changes, implicit_ancestors, unique_paths, post_files = (
        _bind_transitions(
            raw,
            sources=content_sources,
            context=context,
            snapshot_indexes=snapshot_indexes,
        )
    )
    contents = _load_bound_contents(
        content_sources,
        context=context,
        unique_paths=unique_paths,
        post_files=post_files,
        post_index=snapshot_indexes.post,
        input_guard=input_guard,
    )
    input_guard()
    aggregate_sha256 = sha256(
        _canonical_json_bytes(
            {
                "changes": [
                    {
                        "started_event_ordinal": value.started_event_ordinal,
                        "completed_event_ordinal": value.completed_event_ordinal,
                        "event_id": value.event_id,
                        "change_ordinal": value.change_ordinal,
                        "normalized_path": value.normalized_path,
                        "kind": value.kind,
                        "role": value.role,
                    }
                    for value in bound_changes
                ],
                "created_paths": list(snapshot_indexes.created_paths),
                "changed_paths": list(snapshot_indexes.changed_paths),
                "removed_paths": list(snapshot_indexes.removed_paths),
                "implicit_ancestor_paths": list(implicit_ancestors),
                "unique_final_paths": list(unique_paths),
            }
        )
    ).hexdigest()
    inventory_sha256 = sha256(
        _canonical_json_bytes(
            {"contents": [_content_record(value) for value in contents]}
        )
    ).hexdigest()
    input_guard()
    return _make_bound_decision(
        context=context,
        changes=bound_changes,
        contents=contents,
        implicit_ancestor_paths=implicit_ancestors,
        unique_final_paths=unique_paths,
        transition_entries=raw.transition_entries,
        raw_content_bytes=sum(value.raw_size for value in contents),
        retained_content_bytes=sum(value.retained_size for value in contents),
        normalized_plan_sha256=normalized_plan_sha256,
        aggregate_transition_sha256=aggregate_sha256,
        content_inventory_sha256=inventory_sha256,
        raw_session_sha256=sha256(raw_session_bytes).hexdigest(),
        retained_session_sha256=sha256(retained_session_bytes).hexdigest(),
    )
