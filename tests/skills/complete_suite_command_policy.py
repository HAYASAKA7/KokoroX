from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
from functools import cmp_to_key
from hashlib import sha256
import json
from pathlib import Path, PureWindowsPath
import re
import threading
from typing import Literal, NoReturn
import weakref

from complete_suite_command_plan import (
    BoundCommandPlan,
    FilesystemObjectIdentity,
    _authenticate_bound_namespaces,
    _observe_namespace_root,
    _revalidate_retained_namespaces,
    _windows_ordinal_equal,
)


COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID = (
    "COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"
)
COMMAND_POLICY_LIMIT_EXCEEDED = "COMMAND_POLICY_LIMIT_EXCEEDED"
COMMAND_POLICY_LITERAL_REQUIRED = "COMMAND_POLICY_LITERAL_REQUIRED"
COMMAND_POLICY_LITERAL_LIMIT_EXCEEDED = "COMMAND_POLICY_LITERAL_LIMIT_EXCEEDED"
COMMAND_POLICY_OPERATION_REJECTED = "COMMAND_POLICY_OPERATION_REJECTED"
COMMAND_POLICY_CONTEXT_INVALID = "COMMAND_POLICY_CONTEXT_INVALID"
COMMAND_POLICY_PLAN_INVALID = "COMMAND_POLICY_PLAN_INVALID"

FILESYSTEM_STATE_VERSION = "complete-suite-policy-filesystem-state-v1"
FILESYSTEM_FILE_TYPE_DISK = 1
COMMAND_POLICY_VERSION = "complete-suite-kokoro-command-policy-v1"
_FILESYSTEM_ROOT_FIELD = "policy_filesystem_roots"
_FILESYSTEM_ENTRY_LIMIT = 4096
_FILESYSTEM_AGGREGATE_BYTES = 64 * 1024 * 1024
_LITERAL_UTF8_LIMIT = 4096
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def _reject(code: str) -> NoReturn:
    raise RuntimeError(code)


def _is_sha256(value: object) -> bool:
    return type(value) is str and _LOWER_SHA256.fullmatch(value) is not None


def _windows_ordinal_compare(left: str, right: str) -> int:
    try:
        left_units = len(left.encode("utf-16-le", errors="strict")) // 2
        right_units = len(right.encode("utf-16-le", errors="strict")) // 2
    except UnicodeEncodeError:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    compare = kernel32.CompareStringOrdinal
    compare.argtypes = (
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.BOOL,
    )
    compare.restype = ctypes.c_int
    result = compare(left, left_units, right, right_units, True)
    if result not in (1, 2, 3):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return result - 2


def _windows_sorted(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(values, key=cmp_to_key(_windows_ordinal_compare)))


def _windows_unique(values: tuple[str, ...]) -> bool:
    ordered = _windows_sorted(values)
    return all(
        not _windows_ordinal_equal(left, right, ignore_case=True)
        for left, right in zip(ordered, ordered[1:])
    )


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        result[key] = value
    return result


def _decode_canonical_object(payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes or len(payload) > _FILESYSTEM_AGGREGATE_BYTES:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda _value: _reject(
                COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    if type(value) is not dict or _canonical_json_bytes(value) != payload:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return value


def _normalize_relative_path(value: object, *, allow_dot: bool) -> str:
    if type(value) is not str:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    if (
        not value
        or len(encoded) > _LITERAL_UTF8_LIMIT
        or any(character in value for character in ("\x00", "\r", "\n"))
        or ":" in value
    ):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    path = PureWindowsPath(value.replace("/", "\\"))
    if path.is_absolute() or path.anchor:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    parts = path.parts
    if any(part in ("", ".", "..") for part in parts):
        if not (allow_dot and value in (".", ".\\", "./")):
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        return "."
    normalized = str(path)
    if normalized != value.replace("/", "\\"):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return normalized


def _identity_from_record(value: object) -> FilesystemObjectIdentity:
    if type(value) is not dict or set(value) != {
        "device",
        "inode",
        "file_type",
        "reparse_tag",
        "link_count",
    }:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    try:
        identity = FilesystemObjectIdentity(
            device=value["device"],
            inode=value["inode"],
            file_type=value["file_type"],
            reparse_tag=value["reparse_tag"],
            link_count=value["link_count"],
        )
    except (RuntimeError, TypeError):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    if (
        identity.file_type != FILESYSTEM_FILE_TYPE_DISK
        or identity.reparse_tag != 0
        or identity.link_count != 1
    ):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return identity


def _identity_record(identity: FilesystemObjectIdentity) -> dict[str, int]:
    if type(identity) is not FilesystemObjectIdentity:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return {
        "device": identity.device,
        "file_type": identity.file_type,
        "inode": identity.inode,
        "link_count": identity.link_count,
        "reparse_tag": identity.reparse_tag,
    }


def _copy_filesystem_identity(
    identity: FilesystemObjectIdentity,
) -> FilesystemObjectIdentity:
    if type(identity) is not FilesystemObjectIdentity:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return FilesystemObjectIdentity(
        device=identity.device,
        inode=identity.inode,
        file_type=identity.file_type,
        reparse_tag=identity.reparse_tag,
        link_count=identity.link_count,
    )


@dataclass(frozen=True)
class FilesystemSnapshotEntry:
    relative_path: str
    kind: Literal["file", "directory"]
    size: int
    sha256: str | None
    link_count: int
    identity: FilesystemObjectIdentity

    def __post_init__(self) -> None:
        _normalize_relative_path(self.relative_path, allow_dot=False)
        if (
            self.kind not in ("file", "directory")
            or type(self.size) is not int
            or self.size < 0
            or type(self.link_count) is not int
            or self.link_count != 1
            or type(self.identity) is not FilesystemObjectIdentity
            or self.identity.link_count != self.link_count
            or self.identity.file_type != FILESYSTEM_FILE_TYPE_DISK
            or self.identity.reparse_tag != 0
        ):
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        if self.kind == "file":
            if not _is_sha256(self.sha256):
                _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        elif self.size != 0 or self.sha256 is not None:
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)


@dataclass(frozen=True)
class FilesystemRootSnapshot:
    root_index: int
    relative_root: str
    present: bool
    root_identity: FilesystemObjectIdentity | None
    ancestor_identities: tuple[FilesystemObjectIdentity, ...]
    entries: tuple[FilesystemSnapshotEntry, ...]
    manifest_sha256: str

    def __post_init__(self) -> None:
        _normalize_relative_path(self.relative_root, allow_dot=True)
        if (
            type(self.root_index) is not int
            or self.root_index < 0
            or type(self.present) is not bool
            or type(self.ancestor_identities) is not tuple
            or any(
                type(identity) is not FilesystemObjectIdentity
                for identity in self.ancestor_identities
            )
            or type(self.entries) is not tuple
            or any(type(entry) is not FilesystemSnapshotEntry for entry in self.entries)
            or not _is_sha256(self.manifest_sha256)
        ):
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        if self.present:
            if type(self.root_identity) is not FilesystemObjectIdentity:
                _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        elif self.root_identity is not None or self.entries:
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        paths = tuple(entry.relative_path for entry in self.entries)
        if paths != _windows_sorted(paths) or not _windows_unique(paths):
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        if sha256(_canonical_json_bytes(_root_payload(self))).hexdigest() != self.manifest_sha256:
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)


@dataclass(frozen=True)
class BoundFilesystemEvidence:
    pre_run_state_sha256: str
    post_run_state_sha256: str
    pre_roots: tuple[FilesystemRootSnapshot, ...]
    post_roots: tuple[FilesystemRootSnapshot, ...]
    created_paths: tuple[str, ...]
    changed_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]
    canonical_sha256: str

    def __post_init__(self) -> None:
        if (
            not _is_sha256(self.pre_run_state_sha256)
            or not _is_sha256(self.post_run_state_sha256)
            or not _is_sha256(self.canonical_sha256)
            or type(self.pre_roots) is not tuple
            or type(self.post_roots) is not tuple
            or any(type(root) is not FilesystemRootSnapshot for root in self.pre_roots)
            or any(type(root) is not FilesystemRootSnapshot for root in self.post_roots)
        ):
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        for values in (self.created_paths, self.changed_paths, self.removed_paths):
            if type(values) is not tuple:
                _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
            normalized = tuple(
                _normalize_relative_path(value, allow_dot=False) for value in values
            )
            if normalized != _windows_sorted(normalized):
                _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
            if not _windows_unique(normalized):
                _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        if any(
            _windows_path_equal(left, right)
            for first, second in (
                (self.created_paths, self.changed_paths),
                (self.created_paths, self.removed_paths),
                (self.changed_paths, self.removed_paths),
            )
            for left in first
            for right in second
        ):
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        if len(self.pre_roots) != len(self.post_roots) or any(
            not _windows_path_equal(pre.relative_root, post.relative_root)
            for pre, post in zip(self.pre_roots, self.post_roots, strict=True)
        ):
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        pre_flat = _build_snapshot_index(self.pre_roots)
        post_flat = _build_snapshot_index(self.post_roots)
        expected_created, expected_changed, expected_removed = _snapshot_delta(
            pre_flat, post_flat
        )
        if (
            self.created_paths != expected_created
            or self.changed_paths != expected_changed
            or self.removed_paths != expected_removed
        ):
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        record = _filesystem_evidence_record(
            pre_run_state_sha256=self.pre_run_state_sha256,
            post_run_state_sha256=self.post_run_state_sha256,
            pre_roots=self.pre_roots,
            post_roots=self.post_roots,
            created_paths=self.created_paths,
            changed_paths=self.changed_paths,
            removed_paths=self.removed_paths,
        )
        if sha256(_canonical_json_bytes(record)).hexdigest() != self.canonical_sha256:
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)


_SnapshotRecord = tuple[
    str, str, int, str | None, FilesystemObjectIdentity
]


@dataclass(frozen=True)
class _SnapshotIndex:
    records: tuple[_SnapshotRecord, ...]


@dataclass(frozen=True)
class _RegisteredFilesystemEvidence:
    reference: weakref.ReferenceType[BoundFilesystemEvidence]
    canonical_sha256: str
    case_root: str
    pre_roots: tuple[FilesystemRootSnapshot, ...]
    post_roots: tuple[FilesystemRootSnapshot, ...]
    pre_root_identities: tuple[int, ...]
    post_root_identities: tuple[int, ...]
    pre_index: _SnapshotIndex
    post_index: _SnapshotIndex


_FILESYSTEM_EVIDENCE_REGISTRY_LOCK = threading.Lock()
_FILESYSTEM_EVIDENCE_REGISTRY: dict[int, _RegisteredFilesystemEvidence] = {}


def _register_filesystem_evidence(
    evidence: BoundFilesystemEvidence,
    *,
    case_root: Path,
    pre_index: _SnapshotIndex,
    post_index: _SnapshotIndex,
) -> None:
    identifier = id(evidence)

    def cleanup(reference: weakref.ReferenceType[BoundFilesystemEvidence]) -> None:
        with _FILESYSTEM_EVIDENCE_REGISTRY_LOCK:
            current = _FILESYSTEM_EVIDENCE_REGISTRY.get(identifier)
            if current is not None and current.reference is reference:
                _FILESYSTEM_EVIDENCE_REGISTRY.pop(identifier, None)

    reference = weakref.ref(evidence, cleanup)
    with _FILESYSTEM_EVIDENCE_REGISTRY_LOCK:
        _FILESYSTEM_EVIDENCE_REGISTRY[identifier] = _RegisteredFilesystemEvidence(
            reference=reference,
            canonical_sha256=evidence.canonical_sha256,
            case_root=str(PureWindowsPath(str(case_root))),
            pre_roots=evidence.pre_roots,
            post_roots=evidence.post_roots,
            pre_root_identities=tuple(id(root) for root in evidence.pre_roots),
            post_root_identities=tuple(id(root) for root in evidence.post_roots),
            pre_index=pre_index,
            post_index=post_index,
        )


def _registered_filesystem_evidence(
    evidence: BoundFilesystemEvidence,
) -> _RegisteredFilesystemEvidence:
    with _FILESYSTEM_EVIDENCE_REGISTRY_LOCK:
        registered = _FILESYSTEM_EVIDENCE_REGISTRY.get(id(evidence))
    if (
        registered is None
        or registered.reference() is not evidence
        or registered.canonical_sha256 != evidence.canonical_sha256
        or registered.pre_roots is not evidence.pre_roots
        or registered.post_roots is not evidence.post_roots
        or registered.pre_root_identities
        != tuple(id(root) for root in evidence.pre_roots)
        or registered.post_root_identities
        != tuple(id(root) for root in evidence.post_roots)
    ):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return registered


def _registered_snapshot_index(
    evidence: BoundFilesystemEvidence,
    side: Literal["pre", "post"],
) -> _SnapshotIndex:
    if type(evidence) is not BoundFilesystemEvidence or side not in ("pre", "post"):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    registered = _registered_filesystem_evidence(evidence)
    return registered.pre_index if side == "pre" else registered.post_index


def _authenticate_filesystem_evidence(
    evidence: BoundFilesystemEvidence,
    *,
    expected_case_root: Path,
) -> None:
    if type(evidence) is not BoundFilesystemEvidence:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    if not isinstance(expected_case_root, Path) or not expected_case_root.is_absolute():
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    evidence.__post_init__()
    registered = _registered_filesystem_evidence(evidence)
    if (
        not _windows_path_equal(registered.case_root, expected_case_root)
    ):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)


@dataclass(frozen=True)
class CommandPolicyContext:
    case_id: str
    case_root: Path
    workspace_root: Path
    data_root: Path
    approved_read_roots: tuple[Path, ...]
    approved_output_roots: tuple[Path, ...]
    kokoro_shim: Path
    kokoro_shim_sha256: str
    rg_executable: Path
    rg_sha256: str
    shell_path_entries: tuple[Path, ...]
    shell_pathext: tuple[str, ...]
    shell_environment_sha256: str
    filesystem: BoundFilesystemEvidence

    def __post_init__(self) -> None:
        path_values = (
            self.case_root,
            self.workspace_root,
            self.data_root,
            self.kokoro_shim,
            self.rg_executable,
        )
        if (
            type(self.case_id) is not str
            or not self.case_id
            or any(not isinstance(value, Path) for value in path_values)
            or type(self.approved_read_roots) is not tuple
            or type(self.approved_output_roots) is not tuple
            or type(self.shell_path_entries) is not tuple
            or type(self.shell_pathext) is not tuple
            or any(not isinstance(value, Path) for value in self.approved_read_roots)
            or any(not isinstance(value, Path) for value in self.approved_output_roots)
            or any(not isinstance(value, Path) for value in self.shell_path_entries)
            or any(type(value) is not str for value in self.shell_pathext)
            or not _is_sha256(self.kokoro_shim_sha256)
            or not _is_sha256(self.rg_sha256)
            or not _is_sha256(self.shell_environment_sha256)
            or type(self.filesystem) is not BoundFilesystemEvidence
        ):
            _reject(COMMAND_POLICY_CONTEXT_INVALID)
        _authenticate_filesystem_evidence(
            self.filesystem,
            expected_case_root=self.case_root,
        )
        try:
            if (
                not self.case_root.is_absolute()
                or not self.workspace_root.is_absolute()
                or not self.data_root.is_absolute()
                or not _is_below(self.workspace_root, self.case_root)
                or not _is_below(self.data_root, self.case_root)
                or not _windows_path_equal(
                    self.data_root,
                    self.workspace_root / "data",
                )
            ):
                _reject(COMMAND_POLICY_CONTEXT_INVALID)
            relative = _case_relative(self.data_root, self)
            before = _snapshot_lookup(
                _registered_snapshot_index(self.filesystem, "pre"),
                relative,
            )
            after = _snapshot_lookup(
                _registered_snapshot_index(self.filesystem, "post"),
                relative,
            )
            if (
                before is None
                or after is None
                or before[1:] != after[1:]
                or after[1] != "directory"
            ):
                _reject(COMMAND_POLICY_CONTEXT_INVALID)
            _validate_live_snapshot_path(
                self.data_root,
                self,
                expected_kind="directory",
            )
        except RuntimeError:
            _reject(COMMAND_POLICY_CONTEXT_INVALID)


@dataclass(frozen=True)
class _AuthorizationFilesystemView:
    pre_run_state_sha256: str
    post_run_state_sha256: str
    pre_roots: tuple[FilesystemRootSnapshot, ...]
    post_roots: tuple[FilesystemRootSnapshot, ...]
    created_paths: tuple[str, ...]
    changed_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]
    canonical_sha256: str
    pre_index: _SnapshotIndex
    post_index: _SnapshotIndex


@dataclass(frozen=True)
class _CommandPolicyContextView:
    case_id: str
    case_root: Path
    workspace_root: Path
    data_root: Path
    approved_read_roots: tuple[Path, ...]
    approved_output_roots: tuple[Path, ...]
    kokoro_shim: Path
    kokoro_shim_sha256: str
    rg_executable: Path
    rg_sha256: str
    shell_path_entries: tuple[Path, ...]
    shell_pathext: tuple[str, ...]
    shell_environment_sha256: str
    filesystem: _AuthorizationFilesystemView


def _copy_snapshot_entry(entry: FilesystemSnapshotEntry) -> FilesystemSnapshotEntry:
    return FilesystemSnapshotEntry(
        relative_path=entry.relative_path,
        kind=entry.kind,
        size=entry.size,
        sha256=entry.sha256,
        link_count=entry.link_count,
        identity=_copy_filesystem_identity(entry.identity),
    )


def _copy_root_snapshot(root: FilesystemRootSnapshot) -> FilesystemRootSnapshot:
    return FilesystemRootSnapshot(
        root_index=root.root_index,
        relative_root=root.relative_root,
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
        manifest_sha256=root.manifest_sha256,
    )


def _copy_snapshot_index(index: _SnapshotIndex) -> _SnapshotIndex:
    if type(index) is not _SnapshotIndex:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return _SnapshotIndex(
        tuple(
            (
                relative_path,
                kind,
                size,
                digest,
                _copy_filesystem_identity(identity),
            )
            for relative_path, kind, size, digest, identity in index.records
        )
    )


def _authorization_filesystem_view(
    evidence: BoundFilesystemEvidence,
) -> _AuthorizationFilesystemView:
    return _AuthorizationFilesystemView(
        pre_run_state_sha256=evidence.pre_run_state_sha256,
        post_run_state_sha256=evidence.post_run_state_sha256,
        pre_roots=tuple(_copy_root_snapshot(root) for root in evidence.pre_roots),
        post_roots=tuple(_copy_root_snapshot(root) for root in evidence.post_roots),
        created_paths=tuple(path for path in evidence.created_paths),
        changed_paths=tuple(path for path in evidence.changed_paths),
        removed_paths=tuple(path for path in evidence.removed_paths),
        canonical_sha256=evidence.canonical_sha256,
        pre_index=_copy_snapshot_index(
            _registered_snapshot_index(evidence, "pre")
        ),
        post_index=_copy_snapshot_index(
            _registered_snapshot_index(evidence, "post")
        ),
    )


def _authorization_context_view(
    context: CommandPolicyContext,
) -> _CommandPolicyContextView:
    return _CommandPolicyContextView(
        case_id=context.case_id,
        case_root=Path(str(context.case_root)),
        workspace_root=Path(str(context.workspace_root)),
        data_root=Path(str(context.data_root)),
        approved_read_roots=tuple(
            Path(str(root)) for root in context.approved_read_roots
        ),
        approved_output_roots=tuple(
            Path(str(root)) for root in context.approved_output_roots
        ),
        kokoro_shim=Path(str(context.kokoro_shim)),
        kokoro_shim_sha256=context.kokoro_shim_sha256,
        rg_executable=Path(str(context.rg_executable)),
        rg_sha256=context.rg_sha256,
        shell_path_entries=tuple(
            Path(str(root)) for root in context.shell_path_entries
        ),
        shell_pathext=tuple(value for value in context.shell_pathext),
        shell_environment_sha256=context.shell_environment_sha256,
        filesystem=_authorization_filesystem_view(context.filesystem),
    )


def _context_snapshot_index(
    context: CommandPolicyContext | _CommandPolicyContextView,
    side: Literal["pre", "post"],
) -> _SnapshotIndex:
    if side not in ("pre", "post"):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    if type(context) is _CommandPolicyContextView:
        return (
            context.filesystem.pre_index
            if side == "pre"
            else context.filesystem.post_index
        )
    return _registered_snapshot_index(context.filesystem, side)


def _identity_authorization_fingerprint(
    identity: FilesystemObjectIdentity,
) -> tuple[object, ...]:
    return (
        id(identity),
        identity.device,
        identity.inode,
        identity.file_type,
        identity.reparse_tag,
        identity.link_count,
    )


def _root_authorization_fingerprint(
    root: FilesystemRootSnapshot,
) -> tuple[object, ...]:
    return (
        id(root),
        root.root_index,
        root.relative_root,
        root.present,
        None
        if root.root_identity is None
        else _identity_authorization_fingerprint(root.root_identity),
        id(root.ancestor_identities),
        tuple(
            _identity_authorization_fingerprint(identity)
            for identity in root.ancestor_identities
        ),
        id(root.entries),
        tuple(
            (
                id(entry),
                entry.relative_path,
                entry.kind,
                entry.size,
                entry.sha256,
                entry.link_count,
                _identity_authorization_fingerprint(entry.identity),
            )
            for entry in root.entries
        ),
        root.manifest_sha256,
    )


def _filesystem_authorization_fingerprint(
    evidence: BoundFilesystemEvidence,
) -> tuple[object, ...]:
    return (
        id(evidence),
        evidence.pre_run_state_sha256,
        evidence.post_run_state_sha256,
        id(evidence.pre_roots),
        tuple(_root_authorization_fingerprint(root) for root in evidence.pre_roots),
        id(evidence.post_roots),
        tuple(_root_authorization_fingerprint(root) for root in evidence.post_roots),
        id(evidence.created_paths),
        tuple(evidence.created_paths),
        id(evidence.changed_paths),
        tuple(evidence.changed_paths),
        id(evidence.removed_paths),
        tuple(evidence.removed_paths),
        evidence.canonical_sha256,
    )


def _namespace_authorization_fingerprint(namespace: object) -> tuple[object, ...]:
    return (
        id(namespace),
        _path_authorization_fingerprint(namespace.raw_root),
        _path_authorization_fingerprint(namespace.retained_root),
        namespace.label,
        _identity_authorization_fingerprint(namespace.raw_identity),
        _identity_authorization_fingerprint(namespace.retained_identity),
        id(namespace.raw_ancestor_identities),
        tuple(
            _identity_authorization_fingerprint(identity)
            for identity in namespace.raw_ancestor_identities
        ),
        id(namespace.retained_ancestor_identities),
        tuple(
            _identity_authorization_fingerprint(identity)
            for identity in namespace.retained_ancestor_identities
        ),
        namespace.raw_case_sensitive,
        namespace.retained_case_sensitive,
        namespace.canonical_sha256,
    )


def _plan_authorization_fingerprint(plan: BoundCommandPlan) -> tuple[object, ...]:
    return (
        id(plan),
        plan.version,
        id(plan.raw_rendered_utf8_bytes),
        plan.raw_rendered_utf8_bytes,
        plan.raw_rendered_sha256,
        id(plan.retained_rendered_utf8_bytes),
        plan.retained_rendered_utf8_bytes,
        plan.retained_rendered_sha256,
        id(plan.raw_payload_field_utf8_bytes),
        plan.raw_payload_field_utf8_bytes,
        plan.raw_payload_field_sha256,
        id(plan.raw_payload_utf8_bytes),
        plan.raw_payload_utf8_bytes,
        plan.raw_payload_sha256,
        id(plan.retained_payload_field_utf8_bytes),
        plan.retained_payload_field_utf8_bytes,
        plan.retained_payload_field_sha256,
        id(plan.retained_payload_utf8_bytes),
        plan.retained_payload_utf8_bytes,
        plan.retained_payload_sha256,
        id(plan.namespaces),
        tuple(
            _namespace_authorization_fingerprint(namespace)
            for namespace in plan.namespaces
        ),
        plan.namespace_manifest_sha256,
        plan.normalized_plan_sha256,
        id(plan.normalized_plan_bytes),
        plan.normalized_plan_bytes,
    )


def _path_authorization_fingerprint(path: Path) -> tuple[object, ...]:
    return id(path), type(path), str(path)


def _path_tuple_authorization_fingerprint(
    values: tuple[Path, ...],
) -> tuple[object, ...]:
    return id(values), tuple(_path_authorization_fingerprint(value) for value in values)


def _context_authorization_fingerprint(
    context: CommandPolicyContext,
) -> tuple[object, ...]:
    return (
        id(context),
        context.case_id,
        _path_authorization_fingerprint(context.case_root),
        _path_authorization_fingerprint(context.workspace_root),
        _path_authorization_fingerprint(context.data_root),
        _path_tuple_authorization_fingerprint(context.approved_read_roots),
        _path_tuple_authorization_fingerprint(context.approved_output_roots),
        _path_authorization_fingerprint(context.kokoro_shim),
        context.kokoro_shim_sha256,
        _path_authorization_fingerprint(context.rg_executable),
        context.rg_sha256,
        _path_tuple_authorization_fingerprint(context.shell_path_entries),
        id(context.shell_pathext),
        tuple(context.shell_pathext),
        context.shell_environment_sha256,
        _filesystem_authorization_fingerprint(context.filesystem),
    )


@dataclass(frozen=True)
class ApprovedOperation:
    index: int
    statement_index: int
    pipeline_index: int | None
    category: Literal["kokoro_cli", "read_only", "silent_directory"]
    argv: tuple[str, ...]
    operational_json: bool
    expected_outcome: Literal["success", "expected_refusal", "none"]
    declared_output_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.index) is not int
            or self.index < 0
            or type(self.statement_index) is not int
            or self.statement_index < 0
            or (
                self.pipeline_index is not None
                and (type(self.pipeline_index) is not int or self.pipeline_index < 0)
            )
            or self.category not in ("kokoro_cli", "read_only", "silent_directory")
            or type(self.argv) is not tuple
            or not self.argv
            or any(type(value) is not str for value in self.argv)
            or type(self.operational_json) is not bool
            or self.expected_outcome not in ("success", "expected_refusal", "none")
            or type(self.declared_output_paths) is not tuple
            or any(type(value) is not str for value in self.declared_output_paths)
        ):
            _reject(COMMAND_POLICY_PLAN_INVALID)
        if self.category == "kokoro_cli":
            if self.operational_json:
                if self.expected_outcome not in ("success", "expected_refusal"):
                    _reject(COMMAND_POLICY_PLAN_INVALID)
            elif self.expected_outcome != "none" or self.declared_output_paths:
                _reject(COMMAND_POLICY_PLAN_INVALID)
        elif (
            self.operational_json
            or self.expected_outcome != "none"
            or self.declared_output_paths
        ):
            _reject(COMMAND_POLICY_PLAN_INVALID)


@dataclass(frozen=True)
class CommandPolicyDecision:
    version: str
    plan_sha256: str
    record_class: Literal[
        "operational_json", "read_only_pipeline", "help_discovery"
    ]
    operations: tuple[ApprovedOperation, ...]
    topology_sha256: str
    canonical_sha256: str

    def __post_init__(self) -> None:
        if (
            self.version != COMMAND_POLICY_VERSION
            or not _is_sha256(self.plan_sha256)
            or self.record_class
            not in ("operational_json", "read_only_pipeline", "help_discovery")
            or type(self.operations) is not tuple
            or any(type(value) is not ApprovedOperation for value in self.operations)
            or not _is_sha256(self.topology_sha256)
            or not _is_sha256(self.canonical_sha256)
        ):
            _reject(COMMAND_POLICY_PLAN_INVALID)
        if tuple(operation.index for operation in self.operations) != tuple(
            range(len(self.operations))
        ):
            _reject(COMMAND_POLICY_PLAN_INVALID)
        if not self.operations:
            _reject(COMMAND_POLICY_PLAN_INVALID)
        if self.record_class == "operational_json":
            if not any(operation.operational_json for operation in self.operations):
                _reject(COMMAND_POLICY_PLAN_INVALID)
        elif self.record_class == "read_only_pipeline":
            if any(
                operation.category != "read_only" or operation.operational_json
                for operation in self.operations
            ):
                _reject(COMMAND_POLICY_PLAN_INVALID)
        elif (
            len(self.operations) != 1
            or self.operations[0].category != "kokoro_cli"
            or self.operations[0].operational_json
        ):
            _reject(COMMAND_POLICY_PLAN_INVALID)
        expected_topology = sha256(
            _canonical_json_bytes(
                _decision_topology_record(self.record_class, self.operations)
            )
        ).hexdigest()
        if expected_topology != self.topology_sha256:
            _reject(COMMAND_POLICY_PLAN_INVALID)
        expected_canonical = sha256(
            _canonical_json_bytes(
                _decision_canonical_record(
                    plan_sha256=self.plan_sha256,
                    record_class=self.record_class,
                    operations=self.operations,
                    topology_sha256=self.topology_sha256,
                )
            )
        ).hexdigest()
        if expected_canonical != self.canonical_sha256:
            _reject(COMMAND_POLICY_PLAN_INVALID)


def _operation_record(operation: ApprovedOperation) -> dict[str, object]:
    return {
        "argv": list(operation.argv),
        "category": operation.category,
        "declared_output_paths": list(operation.declared_output_paths),
        "expected_outcome": operation.expected_outcome,
        "index": operation.index,
        "operational_json": operation.operational_json,
        "pipeline_index": operation.pipeline_index,
        "statement_index": operation.statement_index,
    }


def _decision_topology_record(
    record_class: str,
    operations: tuple[ApprovedOperation, ...],
) -> dict[str, object]:
    return {
        "operations": [
            {
                "category": operation.category,
                "index": operation.index,
                "pipeline_index": operation.pipeline_index,
                "statement_index": operation.statement_index,
            }
            for operation in operations
        ],
        "record_class": record_class,
        "version": COMMAND_POLICY_VERSION,
    }


def _decision_canonical_record(
    *,
    plan_sha256: str,
    record_class: str,
    operations: tuple[ApprovedOperation, ...],
    topology_sha256: str,
) -> dict[str, object]:
    return {
        "operations": [_operation_record(operation) for operation in operations],
        "plan_sha256": plan_sha256,
        "record_class": record_class,
        "topology_sha256": topology_sha256,
        "version": COMMAND_POLICY_VERSION,
    }


def _entry_record(entry: FilesystemSnapshotEntry) -> dict[str, object]:
    return {
        "identity": _identity_record(entry.identity),
        "kind": entry.kind,
        "link_count": entry.link_count,
        "relative_path": entry.relative_path,
        "sha256": entry.sha256,
        "size": entry.size,
    }


def _root_payload(root: FilesystemRootSnapshot) -> dict[str, object]:
    return {
        "ancestor_identities": [
            _identity_record(identity) for identity in root.ancestor_identities
        ],
        "entries": [_entry_record(entry) for entry in root.entries],
        "present": root.present,
        "relative_root": root.relative_root,
        "root_identity": (
            None if root.root_identity is None else _identity_record(root.root_identity)
        ),
        "root_index": root.root_index,
    }


def _root_record(root: FilesystemRootSnapshot) -> dict[str, object]:
    return {**_root_payload(root), "manifest_sha256": root.manifest_sha256}


def _filesystem_evidence_record(
    *,
    pre_run_state_sha256: str,
    post_run_state_sha256: str,
    pre_roots: tuple[FilesystemRootSnapshot, ...],
    post_roots: tuple[FilesystemRootSnapshot, ...],
    created_paths: tuple[str, ...],
    changed_paths: tuple[str, ...],
    removed_paths: tuple[str, ...],
) -> dict[str, object]:
    return {
        "changed_paths": list(changed_paths),
        "created_paths": list(created_paths),
        "post_roots": [_root_record(root) for root in post_roots],
        "post_run_state_sha256": post_run_state_sha256,
        "pre_roots": [_root_record(root) for root in pre_roots],
        "pre_run_state_sha256": pre_run_state_sha256,
        "removed_paths": list(removed_paths),
        "version": FILESYSTEM_STATE_VERSION,
    }


def _snapshot_entry(value: object) -> FilesystemSnapshotEntry:
    if type(value) is not dict or set(value) != {
        "identity",
        "kind",
        "link_count",
        "relative_path",
        "sha256",
        "size",
    }:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return FilesystemSnapshotEntry(
        relative_path=_normalize_relative_path(value["relative_path"], allow_dot=False),
        kind=value["kind"],
        size=value["size"],
        sha256=value["sha256"],
        link_count=value["link_count"],
        identity=_identity_from_record(value["identity"]),
    )


def _snapshot_root(value: object) -> FilesystemRootSnapshot:
    if type(value) is not dict or set(value) != {
        "ancestor_identities",
        "entries",
        "manifest_sha256",
        "present",
        "relative_root",
        "root_identity",
        "root_index",
    }:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    entries_value = value["entries"]
    ancestors_value = value["ancestor_identities"]
    if type(entries_value) is not list or type(ancestors_value) is not list:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    if len(entries_value) > _FILESYSTEM_ENTRY_LIMIT:
        _reject(COMMAND_POLICY_LIMIT_EXCEEDED)
    entries = tuple(_snapshot_entry(entry) for entry in entries_value)
    paths = tuple(entry.relative_path for entry in entries)
    if paths != _windows_sorted(paths):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    if not _windows_unique(paths):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    ancestors = tuple(_identity_from_record(item) for item in ancestors_value)
    root_identity = (
        None
        if value["root_identity"] is None
        else _identity_from_record(value["root_identity"])
    )
    root = FilesystemRootSnapshot(
        root_index=value["root_index"],
        relative_root=_normalize_relative_path(value["relative_root"], allow_dot=True),
        present=value["present"],
        root_identity=root_identity,
        ancestor_identities=ancestors,
        entries=entries,
        manifest_sha256=value["manifest_sha256"],
    )
    if sha256(_canonical_json_bytes(_root_payload(root))).hexdigest() != root.manifest_sha256:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return root


def _snapshot_roots(document: dict[str, object]) -> tuple[FilesystemRootSnapshot, ...]:
    raw_roots = document.get(_FILESYSTEM_ROOT_FIELD)
    if type(raw_roots) is not list:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    roots = tuple(_snapshot_root(value) for value in raw_roots)
    if len(roots) > _FILESYSTEM_ENTRY_LIMIT:
        _reject(COMMAND_POLICY_LIMIT_EXCEEDED)
    if tuple(root.root_index for root in roots) != tuple(range(len(roots))):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    relative_roots = tuple(root.relative_root for root in roots)
    if (
        relative_roots != _windows_sorted(relative_roots)
        or not _windows_unique(relative_roots)
    ):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    total_bytes = sum(
        entry.size
        for root in roots
        for entry in root.entries
        if entry.kind == "file"
    )
    if total_bytes > _FILESYSTEM_AGGREGATE_BYTES:
        _reject(COMMAND_POLICY_LIMIT_EXCEEDED)
    return roots


def _build_snapshot_index(
    roots: tuple[FilesystemRootSnapshot, ...],
) -> _SnapshotIndex:
    if type(roots) is not tuple or any(
        type(root) is not FilesystemRootSnapshot for root in roots
    ):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    records: list[_SnapshotRecord] = []
    maximum_records = len(roots) * (_FILESYSTEM_ENTRY_LIMIT + 1)
    for root in roots:
        if not root.present:
            continue
        root_path = root.relative_root
        if type(root.root_identity) is not FilesystemObjectIdentity:
            _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
        values: tuple[_SnapshotRecord, ...] = (
            (
                root_path,
                "directory",
                0,
                None,
                _copy_filesystem_identity(root.root_identity),
            ),
            *(
            (
                str(PureWindowsPath(root_path) / entry.relative_path)
                if root_path != "."
                else entry.relative_path,
                entry.kind,
                entry.size,
                entry.sha256,
                _copy_filesystem_identity(entry.identity),
            )
            for entry in root.entries
            ),
        )
        if len(records) + len(values) > maximum_records:
            _reject(COMMAND_POLICY_LIMIT_EXCEEDED)
        records.extend(values)
    ordered = sorted(
        records,
        key=cmp_to_key(
            lambda left, right: _windows_ordinal_compare(left[0], right[0])
        ),
    )
    merged: list[_SnapshotRecord] = []
    for record in ordered:
        if merged and _windows_ordinal_compare(merged[-1][0], record[0]) == 0:
            if merged[-1][1:] != record[1:]:
                _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
            continue
        merged.append(record)
    return _SnapshotIndex(tuple(merged))


def _snapshot_lookup(
    inventory: _SnapshotIndex,
    path: str,
) -> _SnapshotRecord | None:
    if type(inventory) is not _SnapshotIndex or type(path) is not str:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    lower = 0
    upper = len(inventory.records)
    while lower < upper:
        middle = lower + (upper - lower) // 2
        record = inventory.records[middle]
        comparison = _windows_ordinal_compare(record[0], path)
        if comparison < 0:
            lower = middle + 1
        elif comparison > 0:
            upper = middle
        else:
            return record
    return None


def _snapshot_delta(
    pre: _SnapshotIndex,
    post: _SnapshotIndex,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if type(pre) is not _SnapshotIndex or type(post) is not _SnapshotIndex:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    created: list[str] = []
    changed: list[str] = []
    removed: list[str] = []
    pre_index = 0
    post_index = 0
    while pre_index < len(pre.records) and post_index < len(post.records):
        before = pre.records[pre_index]
        after = post.records[post_index]
        comparison = _windows_ordinal_compare(before[0], after[0])
        if comparison < 0:
            removed.append(before[0])
            pre_index += 1
        elif comparison > 0:
            created.append(after[0])
            post_index += 1
        else:
            if before[1:] != after[1:]:
                changed.append(after[0])
            pre_index += 1
            post_index += 1
    removed.extend(record[0] for record in pre.records[pre_index:])
    created.extend(record[0] for record in post.records[post_index:])
    return tuple(created), tuple(changed), tuple(removed)


def _declared_delta(document: dict[str, object], name: str) -> tuple[str, ...]:
    value = document.get(name)
    if type(value) is not list:
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    normalized = tuple(
        _normalize_relative_path(item, allow_dot=False) for item in value
    )
    if normalized != _windows_sorted(normalized) or not _windows_unique(normalized):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    return normalized


def bind_filesystem_evidence(
    pre_run_state_bytes: bytes,
    post_run_state_bytes: bytes,
    *,
    case_root: Path,
) -> BoundFilesystemEvidence:
    if not isinstance(case_root, Path) or not case_root.is_absolute():
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    pre_document = _decode_canonical_object(pre_run_state_bytes)
    post_document = _decode_canonical_object(post_run_state_bytes)
    if (
        set(pre_document) != {"schema_version", _FILESYSTEM_ROOT_FIELD}
        or set(post_document)
        != {
            "schema_version",
            _FILESYSTEM_ROOT_FIELD,
            "created_paths",
            "changed_paths",
            "removed_paths",
        }
        or
        pre_document.get("schema_version") != FILESYSTEM_STATE_VERSION
        or post_document.get("schema_version") != FILESYSTEM_STATE_VERSION
    ):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    pre_roots = _snapshot_roots(pre_document)
    post_roots = _snapshot_roots(post_document)
    if len(pre_roots) != len(post_roots) or any(
        not _windows_path_equal(pre.relative_root, post.relative_root)
        for pre, post in zip(pre_roots, post_roots, strict=True)
    ):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    pre_flat = _build_snapshot_index(pre_roots)
    post_flat = _build_snapshot_index(post_roots)
    created, changed, removed = _snapshot_delta(pre_flat, post_flat)
    if (
        _declared_delta(post_document, "created_paths") != created
        or _declared_delta(post_document, "changed_paths") != changed
        or _declared_delta(post_document, "removed_paths") != removed
    ):
        _reject(COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID)
    canonical_record = _filesystem_evidence_record(
        pre_run_state_sha256=sha256(pre_run_state_bytes).hexdigest(),
        post_run_state_sha256=sha256(post_run_state_bytes).hexdigest(),
        pre_roots=pre_roots,
        post_roots=post_roots,
        created_paths=created,
        changed_paths=changed,
        removed_paths=removed,
    )
    evidence = BoundFilesystemEvidence(
        pre_run_state_sha256=sha256(pre_run_state_bytes).hexdigest(),
        post_run_state_sha256=sha256(post_run_state_bytes).hexdigest(),
        pre_roots=pre_roots,
        post_roots=post_roots,
        created_paths=created,
        changed_paths=changed,
        removed_paths=removed,
        canonical_sha256=sha256(_canonical_json_bytes(canonical_record)).hexdigest(),
    )
    _register_filesystem_evidence(
        evidence,
        case_root=case_root,
        pre_index=pre_flat,
        post_index=post_flat,
    )
    return evidence


def _decode_plan_object(payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes or len(payload) > 4 * 1024 * 1024:
        _reject(COMMAND_POLICY_PLAN_INVALID)
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda _value: _reject(COMMAND_POLICY_PLAN_INVALID),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _reject(COMMAND_POLICY_PLAN_INVALID)
    if type(value) is not dict:
        _reject(COMMAND_POLICY_PLAN_INVALID)
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError):
        _reject(COMMAND_POLICY_PLAN_INVALID)
    if canonical != payload:
        _reject(COMMAND_POLICY_PLAN_INVALID)
    return value


def _bounded_literal(value: object) -> str:
    if type(value) is not str:
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    if len(encoded) > _LITERAL_UTF8_LIMIT:
        _reject(COMMAND_POLICY_LITERAL_LIMIT_EXCEEDED)
    if any(character in value for character in ("\x00", "\r", "\n")):
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    return value


def _normalized_literal_value(
    literal: object,
    *,
    namespaces: object,
) -> str:
    if type(literal) is not dict:
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    if set(literal) == {"kind", "namespace", "suffix"}:
        if (
            literal.get("kind") != "path"
            or type(literal.get("namespace")) is not str
            or type(literal.get("suffix")) is not list
            or any(type(part) is not str for part in literal["suffix"])
            or type(namespaces) is not list
        ):
            _reject(COMMAND_POLICY_LITERAL_REQUIRED)
        matches = [
            item
            for item in namespaces
            if type(item) is dict and item.get("label") == literal["namespace"]
        ]
        if len(matches) != 1 or type(matches[0].get("retained_root")) is not str:
            _reject(COMMAND_POLICY_LITERAL_REQUIRED)
        suffix = literal["suffix"]
        if any(
            not part or part in (".", "..") or "\\" in part or "/" in part
            for part in suffix
        ):
            _reject(COMMAND_POLICY_LITERAL_REQUIRED)
        result = str(PureWindowsPath(matches[0]["retained_root"], *suffix))
        return _bounded_literal(result)
    if set(literal) != {"kind", "sha256", "utf8_bytes", "value"}:
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    kind = literal.get("kind")
    value = _bounded_literal(literal.get("value"))
    encoded = value.encode("utf-8", errors="strict")
    if (
        kind not in ("bare", "single_quoted", "double_quoted")
        or literal.get("utf8_bytes") != len(encoded)
        or literal.get("sha256") != sha256(encoded).hexdigest()
    ):
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    return value


def _command_segments(tokens: object) -> tuple[tuple[dict[str, object], ...], ...]:
    if type(tokens) is not list:
        _reject(COMMAND_POLICY_PLAN_INVALID)
    segments: list[tuple[dict[str, object], ...]] = []
    current: list[dict[str, object]] = []
    for expected_index, token in enumerate(tokens):
        if type(token) is not dict:
            _reject(COMMAND_POLICY_PLAN_INVALID)
        kind = token.get("kind")
        text = token.get("text")
        path_text = (
            kind == "StringLiteral"
            and type(text) is dict
            and text == token.get("literal")
            and set(text) == {"kind", "namespace", "suffix"}
            and text.get("kind") == "path"
            and type(text.get("namespace")) is str
            and type(text.get("suffix")) is list
            and all(
                type(part) is str
                and bool(part)
                and part not in (".", "..")
                and "\\" not in part
                and "/" not in part
                for part in text["suffix"]
            )
        )
        if (
            set(token) != {"flags", "index", "kind", "literal", "text"}
            or token.get("index") != expected_index
            or type(kind) is not str
            or (type(text) is not str and not path_text)
        ):
            _reject(COMMAND_POLICY_PLAN_INVALID)
        if kind in ("Comment", "LineContinuation"):
            continue
        if kind in ("Pipe", "Semi", "NewLine", "EndOfInput"):
            if current:
                segments.append(tuple(current))
                current = []
            continue
        current.append(token)
    if current:
        segments.append(tuple(current))
    return tuple(segments)


def _literal_command(
    plan_bytes: bytes,
    command_node_index: int,
) -> tuple[tuple[str, ...], Literal["none", "call"]]:
    document = _decode_plan_object(plan_bytes)
    command = document.get("command")
    if type(command) is not dict or set(command) != {"metrics", "nodes", "tokens"}:
        _reject(COMMAND_POLICY_PLAN_INVALID)
    nodes = command["nodes"]
    if (
        type(nodes) is not list
        or type(command_node_index) is not int
        or command_node_index < 0
        or command_node_index >= len(nodes)
    ):
        _reject(COMMAND_POLICY_PLAN_INVALID)
    for expected_index, node in enumerate(nodes):
        if (
            type(node) is not dict
            or set(node) != {
                "ast_type",
                "child_indices",
                "index",
                "invocation_operator",
                "literal",
                "parent_index",
                "role",
            }
            or node.get("index") != expected_index
            or type(node.get("child_indices")) is not list
        ):
            _reject(COMMAND_POLICY_PLAN_INVALID)
    node = nodes[command_node_index]
    if node.get("ast_type") != "CommandAst" or node.get("role") != "command":
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    parent_index = node.get("parent_index")
    if (
        type(parent_index) is not int
        or parent_index < 0
        or parent_index >= command_node_index
        or parent_index >= len(nodes)
    ):
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    pipeline = nodes[parent_index]
    named_index = pipeline.get("parent_index")
    if (
        pipeline.get("ast_type") != "PipelineAst"
        or pipeline.get("role") != "pipeline"
        or type(named_index) is not int
        or named_index < 0
        or named_index >= len(nodes)
    ):
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    named = nodes[named_index]
    root_index = named.get("parent_index")
    if (
        named.get("ast_type") != "NamedBlockAst"
        or type(root_index) is not int
        or root_index != 0
        or nodes[0].get("ast_type") != "ScriptBlockAst"
        or nodes[0].get("parent_index") is not None
    ):
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    operator = node.get("invocation_operator")
    if operator not in ("none", "call"):
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    command_indices = [
        index
        for index, candidate in enumerate(nodes)
        if candidate.get("ast_type") == "CommandAst"
    ]
    if command_node_index not in command_indices:
        _reject(COMMAND_POLICY_PLAN_INVALID)
    segments = _command_segments(command["tokens"])
    if len(segments) != len(command_indices):
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    segment = list(segments[command_indices.index(command_node_index)])
    has_call_token = bool(segment and segment[0].get("kind") == "Ampersand")
    if has_call_token:
        segment.pop(0)
    if has_call_token != (operator == "call") or not segment:
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    argv: list[str] = []
    namespaces = document.get("namespaces")
    for token in segment:
        kind = token["kind"]
        literal = token["literal"]
        if kind == "Parameter":
            if literal is not None:
                _reject(COMMAND_POLICY_LITERAL_REQUIRED)
            value = _bounded_literal(token["text"])
        elif kind in ("Identifier", "Generic"):
            if literal is None:
                value = _bounded_literal(token["text"])
                if not value or any(character.isspace() for character in value):
                    _reject(COMMAND_POLICY_LITERAL_REQUIRED)
            else:
                value = _normalized_literal_value(literal, namespaces=namespaces)
        elif kind in ("StringLiteral", "Number"):
            value = _normalized_literal_value(literal, namespaces=namespaces)
        else:
            _reject(COMMAND_POLICY_LITERAL_REQUIRED)
        argv.append(value)
    child_indices = node["child_indices"]
    if len(child_indices) != len(argv):
        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    allowed_children = {
        "CommandParameterAst",
        "ConstantExpressionAst",
        "StringConstantExpressionAst",
    }
    for child_index in child_indices:
        if (
            type(child_index) is not int
            or child_index < 0
            or child_index <= command_node_index
            or child_index >= len(nodes)
            or nodes[child_index].get("parent_index") != command_node_index
            or nodes[child_index].get("ast_type") not in allowed_children
            or nodes[child_index].get("child_indices") != []
        ):
            _reject(COMMAND_POLICY_LITERAL_REQUIRED)
    return tuple(argv), operator


def _literal_argv(plan_bytes: bytes, command_node_index: int) -> tuple[str, ...]:
    return _literal_command(plan_bytes, command_node_index)[0]


def _path_parts(value: Path | str) -> tuple[str, ...]:
    return PureWindowsPath(str(value)).parts


def _windows_path_equal(left: Path | str, right: Path | str) -> bool:
    left_parts = _path_parts(left)
    right_parts = _path_parts(right)
    return len(left_parts) == len(right_parts) and all(
        _windows_ordinal_equal(left_part, right_part, ignore_case=True)
        for left_part, right_part in zip(left_parts, right_parts, strict=True)
    )


def _is_below(candidate: Path | str, root: Path | str) -> bool:
    candidate_parts = _path_parts(candidate)
    root_parts = _path_parts(root)
    return (
        len(candidate_parts) >= len(root_parts)
        and all(
            _windows_ordinal_equal(candidate_part, root_part, ignore_case=True)
            for candidate_part, root_part in zip(
                candidate_parts[: len(root_parts)], root_parts, strict=True
            )
        )
    )


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = (
        ("file_attributes", wintypes.DWORD),
        ("creation_time_low", wintypes.DWORD),
        ("creation_time_high", wintypes.DWORD),
        ("last_access_time_low", wintypes.DWORD),
        ("last_access_time_high", wintypes.DWORD),
        ("last_write_time_low", wintypes.DWORD),
        ("last_write_time_high", wintypes.DWORD),
        ("volume_serial_number", wintypes.DWORD),
        ("file_size_high", wintypes.DWORD),
        ("file_size_low", wintypes.DWORD),
        ("number_of_links", wintypes.DWORD),
        ("file_index_high", wintypes.DWORD),
        ("file_index_low", wintypes.DWORD),
    )


class _FileAttributeTagInformation(ctypes.Structure):
    _fields_ = (
        ("file_attributes", wintypes.DWORD),
        ("reparse_tag", wintypes.DWORD),
    )


class _UnicodeString(ctypes.Structure):
    _fields_ = (
        ("length", wintypes.USHORT),
        ("maximum_length", wintypes.USHORT),
        ("buffer", wintypes.LPWSTR),
    )


class _ObjectAttributes(ctypes.Structure):
    _fields_ = (
        ("length", wintypes.ULONG),
        ("root_directory", wintypes.HANDLE),
        ("object_name", ctypes.POINTER(_UnicodeString)),
        ("attributes", wintypes.ULONG),
        ("security_descriptor", wintypes.LPVOID),
        ("security_quality_of_service", wintypes.LPVOID),
    )


class _IoStatusBlock(ctypes.Structure):
    _fields_ = (
        ("status", wintypes.LPVOID),
        ("information", ctypes.c_size_t),
    )


class _FileIdBothDirectoryInformation(ctypes.Structure):
    _fields_ = (
        ("next_entry_offset", wintypes.DWORD),
        ("file_index", wintypes.DWORD),
        ("creation_time", ctypes.c_int64),
        ("last_access_time", ctypes.c_int64),
        ("last_write_time", ctypes.c_int64),
        ("change_time", ctypes.c_int64),
        ("end_of_file", ctypes.c_int64),
        ("allocation_size", ctypes.c_int64),
        ("file_attributes", wintypes.DWORD),
        ("file_name_length", wintypes.DWORD),
        ("ea_size", wintypes.DWORD),
        ("short_name_length", ctypes.c_byte),
        ("short_name", wintypes.WCHAR * 12),
        ("file_id", ctypes.c_int64),
        ("file_name", wintypes.WCHAR * 1),
    )


@dataclass(frozen=True)
class _LiveHandleObservation:
    identity: FilesystemObjectIdentity
    kind: Literal["file", "directory"]
    size: int


def _query_live_handle(handle: int, expected_path: Path) -> _LiveHandleObservation:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    information = _ByHandleFileInformation()
    tag_information = _FileAttributeTagInformation()
    if not get_information(handle, ctypes.byref(information)) or not get_information_ex(
        handle,
        9,
        ctypes.byref(tag_information),
        ctypes.sizeof(tag_information),
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    reparse = 0x400
    directory = 0x10
    kind: Literal["file", "directory"] = (
        "directory" if information.file_attributes & directory else "file"
    )
    if (
        information.file_attributes & reparse
        or tag_information.file_attributes & reparse
        or tag_information.reparse_tag != 0
        or information.number_of_links <= 0
        or (kind == "file" and information.number_of_links != 1)
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    final_size = get_final_path(handle, None, 0, 0)
    if final_size <= 0 or final_size > 32767:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    final_buffer = ctypes.create_unicode_buffer(final_size + 1)
    final_length = get_final_path(handle, final_buffer, len(final_buffer), 0)
    if final_length <= 0 or final_length >= len(final_buffer):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    observed_path = final_buffer.value
    if observed_path.startswith("\\\\?\\UNC\\"):
        observed_path = "\\\\" + observed_path[8:]
    elif observed_path.startswith("\\\\?\\"):
        observed_path = observed_path[4:]
    if not _windows_path_equal(observed_path, expected_path):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    size = (information.file_size_high << 32) | information.file_size_low
    if kind == "directory":
        size = 0
    return _LiveHandleObservation(
        identity=FilesystemObjectIdentity(
            device=information.volume_serial_number,
            inode=(information.file_index_high << 32) | information.file_index_low,
            file_type=FILESYSTEM_FILE_TYPE_DISK,
            reparse_tag=tag_information.reparse_tag,
            link_count=information.number_of_links,
        ),
        kind=kind,
        size=size,
    )


def _open_live_handle(
    path: Path,
    *,
    read_content: bool,
) -> tuple[int, _LiveHandleObservation]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    access = 0x80 | (0x80000000 if read_content else 0)
    handle = create_file(
        str(path),
        access,
        0x1 | 0x2 | 0x4,
        None,
        3,
        0x00200000 | 0x02000000,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    handle_value = getattr(handle, "value", handle)
    if handle_value in (None, invalid_handle):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    handle_int = int(handle_value)
    try:
        observation = _query_live_handle(handle_int, path)
    except BaseException:
        close_handle(handle_int)
        raise
    return handle_int, observation


def _close_live_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not close_handle(handle):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)


def _observe_live_identity(path: Path) -> FilesystemObjectIdentity:
    handle, observation = _open_live_handle(path, read_content=False)
    try:
        return observation.identity
    finally:
        _close_live_handle(handle)


def _before_component_relative_final_open(_path: Path) -> None:
    """Test interposition point after every parent handle is held."""


def _after_component_relative_final_open(_path: Path) -> None:
    """Test interposition point after the final no-reparse handle is held."""


def _before_component_relative_directory_enumeration(_path: Path) -> None:
    """Test interposition point while the complete parent chain is held."""


def _before_component_relative_directory_membership_revalidation(
    _path: Path,
) -> None:
    """Test interposition point before the held directory is scanned again."""


def _retain_direct_scan_path(retained: list[str], relative: str) -> None:
    if len(retained) >= _FILESYSTEM_ENTRY_LIMIT:
        _reject(COMMAND_POLICY_LIMIT_EXCEEDED)
    retained.append(relative)


def _containing_root_snapshot(
    roots: tuple[FilesystemRootSnapshot, ...],
    candidate: Path,
    context: CommandPolicyContext,
    *,
    permit_absent: bool,
) -> FilesystemRootSnapshot:
    matches = tuple(
        (
            len(PureWindowsPath(root.relative_root).parts),
            root,
        )
        for root in roots
        if (root.present or permit_absent)
        and _is_below(
            candidate,
            context.case_root.joinpath(
                *PureWindowsPath(root.relative_root).parts
            ),
        )
    )
    if not matches:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    longest = max(length for length, _root in matches)
    selected = tuple(root for length, root in matches if length == longest)
    if len(selected) != 1:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return selected[0]


def _expected_live_parent_identities(
    candidate: Path,
    context: CommandPolicyContext,
    *,
    allow_created: bool,
) -> tuple[FilesystemObjectIdentity, ...]:
    pre = _context_snapshot_index(context, "pre")
    post = _context_snapshot_index(context, "post")
    pre_root = _containing_root_snapshot(
        context.filesystem.pre_roots,
        candidate,
        context,
        permit_absent=allow_created,
    )
    post_root = _containing_root_snapshot(
        context.filesystem.post_roots,
        candidate,
        context,
        permit_absent=False,
    )
    if (
        not _windows_path_equal(
            pre_root.relative_root, post_root.relative_root
        )
        or pre_root.ancestor_identities != post_root.ancestor_identities
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    root_created = any(
        _windows_path_equal(path, post_root.relative_root)
        for path in context.filesystem.created_paths
    )
    if pre_root.present:
        if pre_root.root_identity != post_root.root_identity:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
    elif not allow_created or not root_created:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    expected = list(post_root.ancestor_identities)
    root_path = context.case_root.joinpath(
        *PureWindowsPath(post_root.relative_root).parts
    )
    parent = candidate.parent
    if not _is_below(parent, root_path):
        return tuple(expected)
    current = root_path
    while True:
        relative = _case_relative(current, context)
        before = _snapshot_lookup(pre, relative)
        after = _snapshot_lookup(post, relative)
        created = any(
            _windows_path_equal(path, relative)
            for path in context.filesystem.created_paths
        )
        if after is None or after[1] != "directory" or (
            before is None and not (allow_created and created)
        ) or (
            before is not None and before[1:] != after[1:]
        ):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        expected.append(after[4])
        if _windows_path_equal(current, parent):
            break
        suffix = PureWindowsPath(str(parent)).parts[
            len(PureWindowsPath(str(root_path)).parts) :
        ]
        consumed = len(expected) - len(post_root.ancestor_identities) - 1
        if consumed >= len(suffix):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        current = current / suffix[consumed]
    return tuple(expected)


def _component_relative_live_observation(
    candidate: Path,
    context: CommandPolicyContext,
    *,
    expected_record: _SnapshotRecord | None,
    expected_sha256: str | None,
    allow_created_ancestors: bool,
    allow_missing: bool,
    scan_paths: list[str] | None = None,
) -> tuple[_LiveHandleObservation, str | None] | None:
    parsed = PureWindowsPath(str(candidate))
    if not parsed.is_absolute() or not parsed.anchor or len(parsed.parts) < 2:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    parent_identities = _expected_live_parent_identities(
        candidate,
        context,
        allow_created=allow_created_ancestors,
    )
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
    read_file = kernel32.ReadFile
    read_file.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    read_file.restype = wintypes.BOOL
    get_information_ex = kernel32.GetFileInformationByHandleEx
    get_information_ex.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information_ex.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    file_read_data = 0x00000001
    file_read_attributes = 0x00000080
    file_traverse = 0x00000020
    synchronize = 0x00100000
    share = 0x00000001 | 0x00000002 | 0x00000004
    file_flag_open_reparse_point = 0x00200000
    file_flag_backup_semantics = 0x02000000
    file_directory_file = 0x00000001
    file_non_directory_file = 0x00000040
    file_synchronous_io_nonalert = 0x00000020
    file_open_for_backup_intent = 0x00004000
    file_open_reparse_point = 0x00200000
    obj_dont_reparse = 0x00001000
    invalid_handle = ctypes.c_void_p(-1).value
    missing_statuses = {0xC000000F, 0xC0000034, 0xC000003A}
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400
    error_no_more_files = 18
    directory_information_class = 10
    directory_restart_information_class = 11

    def open_anchor(anchor: str) -> object:
        handle = create_file(
            anchor,
            file_read_attributes | file_traverse,
            share,
            None,
            3,
            file_flag_open_reparse_point | file_flag_backup_semantics,
            None,
        )
        value = getattr(handle, "value", handle)
        if value in (None, invalid_handle):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        return handle

    def open_relative(
        parent: object,
        name: str,
        *,
        kind: Literal["file", "directory"] | None,
        permit_missing: bool,
    ) -> object | None:
        try:
            encoded = name.encode("utf-16-le", errors="strict")
        except UnicodeEncodeError:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        if not encoded or len(encoded) > 65_532:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        name_buffer = ctypes.create_unicode_buffer(name)
        unicode_name = _UnicodeString(
            length=len(encoded),
            maximum_length=len(encoded) + 2,
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
        create_options = file_synchronous_io_nonalert | file_open_reparse_point
        if kind == "directory":
            desired_access |= file_traverse | file_read_data
            create_options |= file_directory_file | file_open_for_backup_intent
        elif kind == "file":
            desired_access |= file_read_data
            create_options |= file_non_directory_file
        status = nt_create_file(
            ctypes.byref(handle),
            desired_access,
            ctypes.byref(attributes),
            ctypes.byref(io_status),
            None,
            0,
            share,
            1,
            create_options,
            None,
            0,
        )
        if status < 0:
            if handle.value not in (None, invalid_handle):
                close_handle(handle)
            if permit_missing and (status & 0xFFFFFFFF) in missing_statuses:
                return None
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        if handle.value in (None, invalid_handle):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        return handle

    def read_expected_file(
        handle: object,
        path: Path,
        observation: _LiveHandleObservation,
        record: tuple[
            str, str, int, str | None, FilesystemObjectIdentity
        ],
    ) -> str:
        if observation.kind != "file" or record[3] is None:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        digest = sha256()
        total = 0
        buffer = ctypes.create_string_buffer(64 * 1024)
        while total < observation.size:
            amount = wintypes.DWORD()
            if not read_file(
                handle,
                buffer,
                min(len(buffer), observation.size - total),
                ctypes.byref(amount),
                None,
            ) or amount.value == 0:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            total += amount.value
            digest.update(buffer.raw[: amount.value])
        amount = wintypes.DWORD()
        if not read_file(
            handle,
            buffer,
            1,
            ctypes.byref(amount),
            None,
        ) or amount.value != 0:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        value = digest.hexdigest()
        if value != record[3] or _query_live_handle(handle, path) != observation:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        return value

    def scan_directory(
        directory_handle: object,
        directory_path: Path,
        directory_record: _SnapshotRecord,
        inventory: _SnapshotIndex,
        retained_paths: list[str],
        *,
        restart: bool,
    ) -> None:
        if restart:
            _before_component_relative_directory_membership_revalidation(
                directory_path
            )
        else:
            _before_component_relative_directory_enumeration(directory_path)
        current = _query_live_handle(directory_handle, directory_path)
        if (
            current.kind != "directory"
            or current.identity != directory_record[4]
            or directory_record[2] != 0
            or directory_record[3] is not None
        ):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        query_count = 0
        while True:
            query_count += 1
            if query_count > _FILESYSTEM_ENTRY_LIMIT + 1:
                _reject(COMMAND_POLICY_LIMIT_EXCEEDED)
            buffer = ctypes.create_string_buffer(64 * 1024)
            ctypes.set_last_error(0)
            if not get_information_ex(
                directory_handle,
                directory_restart_information_class
                if restart and query_count == 1
                else directory_information_class,
                buffer,
                len(buffer),
            ):
                if ctypes.get_last_error() == error_no_more_files:
                    break
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            offset = 0
            while True:
                header_size = _FileIdBothDirectoryInformation.file_name.offset
                if offset < 0 or offset + header_size > len(buffer):
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
                information = _FileIdBothDirectoryInformation.from_buffer(
                    buffer, offset
                )
                name_bytes = int(information.file_name_length)
                if (
                    name_bytes <= 0
                    or name_bytes % 2
                    or offset + header_size + name_bytes > len(buffer)
                ):
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
                try:
                    name = ctypes.string_at(
                        ctypes.addressof(buffer) + offset + header_size,
                        name_bytes,
                    ).decode("utf-16-le", errors="strict")
                except UnicodeDecodeError:
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
                if name not in (".", ".."):
                    if (
                        information.file_attributes
                        & file_attribute_reparse_point
                    ):
                        _reject(COMMAND_POLICY_OPERATION_REJECTED)
                    child_path = directory_path / name
                    relative = _case_relative(child_path, context)
                    if any(
                        _windows_path_equal(relative, observed)
                        for observed in retained_paths
                    ):
                        _reject(COMMAND_POLICY_OPERATION_REJECTED)
                    _retain_direct_scan_path(retained_paths, relative)
                    record = _snapshot_lookup(inventory, relative)
                    if record is None:
                        _reject(COMMAND_POLICY_OPERATION_REJECTED)
                    kind: Literal["file", "directory"] = (
                        "directory"
                        if information.file_attributes
                        & file_attribute_directory
                        else "file"
                    )
                    if kind != record[1]:
                        _reject(COMMAND_POLICY_OPERATION_REJECTED)
                    child_handle = open_relative(
                        directory_handle,
                        name,
                        kind=kind,
                        permit_missing=False,
                    )
                    if child_handle is None:
                        _reject(COMMAND_POLICY_OPERATION_REJECTED)
                    handles.append(child_handle)
                    try:
                        observed = _query_live_handle(child_handle, child_path)
                        if (
                            observed.kind != kind
                            or observed.size != record[2]
                            or observed.identity != record[4]
                        ):
                            _reject(COMMAND_POLICY_OPERATION_REJECTED)
                        if kind == "file":
                            read_expected_file(
                                child_handle, child_path, observed, record
                            )
                        else:
                            scan_directory(
                                child_handle,
                                child_path,
                                record,
                                inventory,
                                retained_paths,
                                restart=restart,
                            )
                        if _query_live_handle(child_handle, child_path) != observed:
                            _reject(COMMAND_POLICY_OPERATION_REJECTED)
                    finally:
                        closing_handle = handles.pop()
                        if closing_handle is not child_handle:
                            _reject(COMMAND_POLICY_OPERATION_REJECTED)
                        if not close_handle(closing_handle):
                            _reject(COMMAND_POLICY_OPERATION_REJECTED)
                    if (
                        _query_live_handle(directory_handle, directory_path)
                        != current
                    ):
                        _reject(COMMAND_POLICY_OPERATION_REJECTED)
                next_offset = int(information.next_entry_offset)
                if next_offset == 0:
                    break
                if next_offset % 8 or next_offset <= 0:
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
                offset += next_offset

    handles: list[object] = []
    parent_paths: list[Path] = []
    digest_value: str | None = None
    result: _LiveHandleObservation | None = None
    try:
        current = Path(parsed.anchor)
        anchor = open_anchor(parsed.anchor)
        handles.append(anchor)
        parent_paths.append(current)
        anchor_observation = _query_live_handle(anchor, current)
        if anchor_observation.kind != "directory":
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        for component in parsed.parts[1:-1]:
            current /= component
            handle = open_relative(
                handles[-1], component, kind="directory", permit_missing=False
            )
            if handle is None:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            handles.append(handle)
            parent_paths.append(current)
            if _query_live_handle(handle, current).kind != "directory":
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
        if len(parent_identities) != len(handles) or any(
            _query_live_handle(handle, path).identity != expected
            for handle, path, expected in zip(
                handles, parent_paths, parent_identities, strict=True
            )
        ):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        _before_component_relative_final_open(candidate)
        expected_kind = (
            None
            if expected_record is None
            else expected_record[1]
        )
        final_handle = open_relative(
            handles[-1],
            parsed.parts[-1],
            kind=expected_kind,
            permit_missing=allow_missing,
        )
        if final_handle is None:
            for handle, path, expected in zip(
                handles, parent_paths, parent_identities, strict=True
            ):
                if _query_live_handle(handle, path).identity != expected:
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
            return None
        handles.append(final_handle)
        result = _query_live_handle(final_handle, candidate)
        _after_component_relative_final_open(candidate)
        if expected_record is not None:
            if (
                result.kind != expected_record[1]
                or result.size != expected_record[2]
                or result.identity != expected_record[4]
            ):
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            if result.kind == "file":
                digest_value = read_expected_file(
                    final_handle, candidate, result, expected_record
                )
                if (
                    expected_sha256 is not None
                    and digest_value != expected_sha256
                ):
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
            else:
                if expected_record[3] is not None or expected_sha256 is not None:
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
                if scan_paths is not None:
                    inventory = _context_snapshot_index(context, "post")
                    scan_directory(
                        final_handle,
                        candidate,
                        expected_record,
                        inventory,
                        scan_paths,
                        restart=False,
                    )
                    revalidated_paths: list[str] = []
                    scan_directory(
                        final_handle,
                        candidate,
                        expected_record,
                        inventory,
                        revalidated_paths,
                        restart=True,
                    )
                    observed_order = _windows_sorted(tuple(scan_paths))
                    revalidated_order = _windows_sorted(
                        tuple(revalidated_paths)
                    )
                    if len(observed_order) != len(revalidated_order) or any(
                        not _windows_path_equal(before, after)
                        for before, after in zip(
                            observed_order,
                            revalidated_order,
                            strict=True,
                        )
                    ):
                        _reject(COMMAND_POLICY_OPERATION_REJECTED)
        elif expected_sha256 is not None:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        if _query_live_handle(final_handle, candidate) != result:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        for handle, path, expected in zip(
            handles[:-1], parent_paths, parent_identities, strict=True
        ):
            if _query_live_handle(handle, path).identity != expected:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
        return result, digest_value
    except RecursionError:
        _reject(COMMAND_POLICY_LIMIT_EXCEEDED)
    except RuntimeError:
        raise
    except (OSError, OverflowError, TypeError, ValueError):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    finally:
        close_failed = False
        for handle in reversed(handles):
            if not close_handle(handle):
                close_failed = True
        if close_failed:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)


def _validate_live_snapshot_path(
    candidate: Path,
    context: CommandPolicyContext,
    *,
    expected_kind: Literal["file", "directory"] | None,
    expected_sha256: str | None = None,
    allow_created_ancestors: bool = False,
) -> _SnapshotRecord:
    relative = _case_relative(candidate, context)
    record = _snapshot_lookup(
        _context_snapshot_index(context, "post"), relative
    )
    if record is None:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    observed = _component_relative_live_observation(
        candidate,
        context,
        expected_record=record,
        expected_sha256=expected_sha256,
        allow_created_ancestors=allow_created_ancestors,
        allow_missing=False,
    )
    if observed is None or (
        expected_kind is not None and observed[0].kind != expected_kind
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return record


def _normalize_operand_path(value: str, context: CommandPolicyContext) -> Path:
    value = _bounded_literal(value)
    if (
        not value
        or any(character in value for character in ("*", "?", "[", "]"))
        or "::" in value
        or value.startswith(("\\\\?\\", "\\??\\"))
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    pure = PureWindowsPath(value.replace("/", "\\"))
    if any(part in ("", "..") for part in pure.parts):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    if pure.is_absolute():
        candidate = Path(str(pure))
    elif pure.drive or pure.anchor:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    else:
        candidate = context.workspace_root.joinpath(*pure.parts)
    if not _is_below(candidate, context.case_root):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return candidate


def _case_relative(candidate: Path, context: CommandPolicyContext) -> str:
    candidate_parts = PureWindowsPath(str(candidate)).parts
    case_parts = PureWindowsPath(str(context.case_root)).parts
    if len(candidate_parts) < len(case_parts) or not all(
        _windows_ordinal_equal(candidate_part, case_part, ignore_case=True)
        for candidate_part, case_part in zip(
            candidate_parts[: len(case_parts)], case_parts, strict=True
        )
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    suffix = candidate_parts[len(case_parts) :]
    if not suffix:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return str(PureWindowsPath(*suffix))


def _workspace_relative(candidate: Path, context: CommandPolicyContext) -> str:
    candidate_parts = PureWindowsPath(str(candidate)).parts
    workspace_parts = PureWindowsPath(str(context.workspace_root)).parts
    if len(candidate_parts) < len(workspace_parts) or not all(
        _windows_ordinal_equal(candidate_part, workspace_part, ignore_case=True)
        for candidate_part, workspace_part in zip(
            candidate_parts[: len(workspace_parts)], workspace_parts, strict=True
        )
    ):
        return _case_relative(candidate, context)
    suffix = candidate_parts[len(workspace_parts) :]
    return "." if not suffix else str(PureWindowsPath(*suffix))


def _bind_path_operand(
    value: str,
    context: CommandPolicyContext,
    *,
    path_class: Literal["read_file", "read_directory", "read_any", "output"],
    allow_existing_output: bool = False,
) -> str:
    candidate = _normalize_operand_path(value, context)
    approved_roots = (
        context.approved_output_roots
        if path_class == "output"
        else context.approved_read_roots
    )
    if not any(_is_below(candidate, root) for root in approved_roots):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    relative = _case_relative(candidate, context)
    pre = _context_snapshot_index(context, "pre")
    post = _context_snapshot_index(context, "post")
    before = _snapshot_lookup(pre, relative)
    after = _snapshot_lookup(post, relative)
    if path_class.startswith("read"):
        created = any(
            _windows_path_equal(path, relative)
            for path in context.filesystem.created_paths
        )
        if after is None or (
            before is None and not created
        ) or (
            before is not None and before[1:] != after[1:]
        ):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        expected_kind = {
            "read_file": "file",
            "read_directory": "directory",
            "read_any": None,
        }[path_class]
        if expected_kind is not None and after[1] != expected_kind:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        _validate_live_snapshot_path(
            candidate,
            context,
            expected_kind=expected_kind,
            allow_created_ancestors=created,
        )
    else:
        created = any(
            _windows_path_equal(path, relative)
            for path in context.filesystem.created_paths
        )
        if before is not None:
            if (
                not allow_existing_output
                or after is None
                or before[1:] != after[1:]
                or after[1] != "file"
                or created
            ):
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
        elif after is None or after[1] != "file" or not created:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        parent = str(PureWindowsPath(relative).parent)
        parent_entry = _snapshot_lookup(post, parent)
        if parent_entry is None or parent_entry[1] != "directory":
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        _validate_live_snapshot_path(
            candidate,
            context,
            expected_kind="file",
            allow_created_ancestors=True,
        )
    return _workspace_relative(candidate, context)


def _consume_path(
    argv: tuple[str, ...],
    cursor: int,
    context: CommandPolicyContext,
    *,
    path_class: Literal["read_file", "read_directory", "read_any"],
) -> tuple[str, int]:
    if cursor >= len(argv):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    if _matches(argv[cursor], "-LiteralPath"):
        cursor += 1
        if cursor >= len(argv):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
    elif argv[cursor].startswith("-"):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    value = _bind_path_operand(argv[cursor], context, path_class=path_class)
    return value, cursor + 1


def _matches(value: str, canonical: str) -> bool:
    try:
        return _windows_ordinal_equal(value, canonical, ignore_case=True)
    except RuntimeError:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)


def _error_action(
    argv: tuple[str, ...], cursor: int, result: list[str]
) -> int:
    if cursor < len(argv) and _matches(argv[cursor], "-ErrorAction"):
        if cursor + 1 >= len(argv) or argv[cursor + 1] != "Stop":
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        result.extend(("-ErrorAction", "Stop"))
        return cursor + 2
    return cursor


_PROJECTION_PROPERTIES = frozenset(
    {"Name", "Length", "Hash", "Path", "FullName", "LastWriteTimeUtc"}
)


def _canonical_property(value: str) -> str:
    matches = [item for item in _PROJECTION_PROPERTIES if _matches(value, item)]
    if len(matches) != 1:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return matches[0]


def _read_subtree_count(path: str, context: CommandPolicyContext) -> int:
    candidate = _normalize_operand_path(path, context)
    inventory = _context_snapshot_index(context, "post")
    root_record = _snapshot_lookup(
        inventory,
        _case_relative(candidate, context),
    )
    if root_record is None or root_record[1] != "directory":
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    expected = tuple(
        record[0]
        for record in inventory.records
        if _is_below(
            context.case_root.joinpath(*PureWindowsPath(record[0]).parts),
            candidate,
        )
        and not _windows_path_equal(
            context.case_root.joinpath(*PureWindowsPath(record[0]).parts),
            candidate,
        )
    )
    observed: list[str] = []
    result = _component_relative_live_observation(
        candidate,
        context,
        expected_record=root_record,
        expected_sha256=None,
        allow_created_ancestors=False,
        allow_missing=False,
        scan_paths=observed,
    )
    if result is None:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    if len(observed) != len(expected) or any(
        not any(_windows_path_equal(actual, planned) for actual in observed)
        for planned in expected
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return len(observed)


def _resolve_frozen_executable(
    name: str,
    expected_path: Path,
    expected_sha256: str,
    context: CommandPolicyContext,
) -> None:
    _bind_shell_fact(context)
    expected_pathext = (".COM", ".EXE", ".BAT", ".CMD")
    if len(context.shell_pathext) != len(expected_pathext) or not all(
        _matches(value, expected)
        for value, expected in zip(
            context.shell_pathext, expected_pathext, strict=True
        )
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    pre = _context_snapshot_index(context, "pre")
    post = _context_snapshot_index(context, "post")
    pre_matches: list[str] = []
    matches: list[str] = []
    live_matches: list[str] = []
    for directory in context.shell_path_entries:
        for extension in (".com", ".exe", ".bat", ".cmd"):
            candidate = directory / f"{name}{extension}"
            relative = _case_relative(candidate, context)
            pre_entry = _snapshot_lookup(pre, relative)
            if pre_entry is not None:
                if pre_entry[1] != "file":
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
                pre_matches.append(relative)
            entry = _snapshot_lookup(post, relative)
            if entry is not None:
                if entry[1] != "file":
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
                matches.append(relative)
            observed = _component_relative_live_observation(
                candidate,
                context,
                expected_record=entry,
                expected_sha256=(
                    expected_sha256
                    if _windows_path_equal(candidate, expected_path)
                    else None
                ),
                allow_created_ancestors=False,
                allow_missing=entry is None,
            )
            if entry is None:
                if observed is not None:
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
            elif observed is None:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            else:
                live_matches.append(relative)
    expected_relative = _case_relative(expected_path, context)
    before = _snapshot_lookup(pre, expected_relative)
    after = _snapshot_lookup(post, expected_relative)
    if (
        len(pre_matches) != 1
        or len(matches) != 1
        or len(live_matches) != 1
        or not _windows_path_equal(pre_matches[0], expected_relative)
        or not _windows_path_equal(matches[0], expected_relative)
        or not _windows_path_equal(live_matches[0], expected_relative)
        or before is None
        or after is None
        or before[1:] != after[1:]
        or after[1] != "file"
        or after[3] != expected_sha256
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)


def _safe_glob(value: str) -> str:
    value = _bounded_literal(value)
    if not value or any(character in value for character in ("\x00", "\r", "\n")):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    pure = PureWindowsPath(value.replace("/", "\\"))
    if pure.is_absolute() or pure.drive or any(part == ".." for part in pure.parts):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return value


def _rg_positional_literal(value: str) -> str:
    value = _bounded_literal(value)
    if value.startswith("-"):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return value


def _authorize_read_only(
    argv: tuple[str, ...], context: CommandPolicyContext
) -> tuple[str, ...]:
    if not argv:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    command = next(
        (
            canonical
            for canonical in (
                "Get-Content",
                "Test-Path",
                "Get-FileHash",
                "Get-ChildItem",
                "Select-Object",
                "Sort-Object",
                "rg",
            )
            if _matches(argv[0], canonical)
        ),
        None,
    )
    if command == "Get-Content":
        path, cursor = _consume_path(argv, 1, context, path_class="read_file")
        result = ["Get-Content"]
        if _matches(argv[1], "-LiteralPath"):
            result.extend(("-LiteralPath", path))
        else:
            result.append(path)
        if cursor < len(argv) and _matches(argv[cursor], "-Raw"):
            result.append("-Raw")
            cursor += 1
        cursor = _error_action(argv, cursor, result)
        if cursor != len(argv):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        return tuple(result)
    if command == "Test-Path":
        path, cursor = _consume_path(argv, 1, context, path_class="read_any")
        result = ["Test-Path"]
        if _matches(argv[1], "-LiteralPath"):
            result.extend(("-LiteralPath", path))
        else:
            result.append(path)
        if cursor < len(argv) and _matches(argv[cursor], "-PathType"):
            if cursor + 1 >= len(argv) or argv[cursor + 1] not in ("Leaf", "Container"):
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            result.extend(("-PathType", argv[cursor + 1]))
            cursor += 2
        cursor = _error_action(argv, cursor, result)
        if cursor != len(argv):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        return tuple(result)
    if command == "Get-FileHash":
        path, cursor = _consume_path(argv, 1, context, path_class="read_file")
        result = ["Get-FileHash"]
        if _matches(argv[1], "-LiteralPath"):
            result.extend(("-LiteralPath", path))
        else:
            result.append(path)
        if cursor < len(argv) and _matches(argv[cursor], "-Algorithm"):
            if cursor + 1 >= len(argv) or argv[cursor + 1] != "SHA256":
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            result.extend(("-Algorithm", "SHA256"))
            cursor += 2
        cursor = _error_action(argv, cursor, result)
        if cursor != len(argv):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        return tuple(result)
    if command == "Get-ChildItem":
        raw_path = argv[2] if len(argv) > 2 and _matches(argv[1], "-LiteralPath") else argv[1] if len(argv) > 1 else ""
        path, cursor = _consume_path(argv, 1, context, path_class="read_directory")
        result = ["Get-ChildItem"]
        if _matches(argv[1], "-LiteralPath"):
            result.extend(("-LiteralPath", path))
        else:
            result.append(path)
        if cursor < len(argv) and (
            _matches(argv[cursor], "-File")
            or _matches(argv[cursor], "-Directory")
        ):
            result.append("-File" if _matches(argv[cursor], "-File") else "-Directory")
            cursor += 1
        if cursor < len(argv) and _matches(argv[cursor], "-Name"):
            result.append("-Name")
            cursor += 1
        recursive = False
        if cursor < len(argv) and _matches(argv[cursor], "-Recurse"):
            result.append("-Recurse")
            cursor += 1
            recursive = True
        elif cursor < len(argv) and _matches(argv[cursor], "-Depth"):
            if cursor + 1 >= len(argv):
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            try:
                depth = int(argv[cursor + 1], 10)
            except ValueError:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            if str(depth) != argv[cursor + 1] or not 0 <= depth <= 8:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            result.extend(("-Depth", str(depth)))
            cursor += 2
            recursive = True
        cursor = _error_action(argv, cursor, result)
        if cursor != len(argv):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        if recursive:
            _read_subtree_count(raw_path, context)
        return tuple(result)
    if command == "Select-Object":
        if len(argv) != 3:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        option = next(
            (
                canonical
                for canonical in ("-First", "-Last", "-Property")
                if _matches(argv[1], canonical)
            ),
            None,
        )
        if option in ("-First", "-Last"):
            try:
                count = int(argv[2], 10)
            except ValueError:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            if str(count) != argv[2] or not 1 <= count <= 256:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            return ("Select-Object", option, str(count))
        if option == "-Property":
            return ("Select-Object", "-Property", _canonical_property(argv[2]))
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    if command == "Sort-Object":
        cursor = 1
        result = ["Sort-Object"]
        if cursor < len(argv) and _matches(argv[cursor], "-Property"):
            if cursor + 1 >= len(argv):
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            result.extend(("-Property", _canonical_property(argv[cursor + 1])))
            cursor += 2
        if cursor < len(argv) and _matches(argv[cursor], "-Unique"):
            result.append("-Unique")
            cursor += 1
        if cursor != len(argv):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        return tuple(result)
    if command == "rg":
        if len(argv) < 5:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        if (
            _matches(argv[1], "--files")
            and _matches(argv[2], "--color")
            and argv[3] == "never"
        ):
            cursor = 4
            result = ["rg", "--files", "--color", "never"]
            globs = 0
            while cursor + 1 < len(argv) and _matches(argv[cursor], "--glob"):
                globs += 1
                if globs > 16:
                    _reject(COMMAND_POLICY_LIMIT_EXCEEDED)
                result.extend(("--glob", _safe_glob(argv[cursor + 1])))
                cursor += 2
            if cursor != len(argv) - 1:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            raw_path = _rg_positional_literal(argv[cursor])
            _resolve_frozen_executable(
                "rg", context.rg_executable, context.rg_sha256, context
            )
            result.append(_bind_path_operand(raw_path, context, path_class="read_directory"))
            _read_subtree_count(raw_path, context)
            return tuple(result)
        if not (
            _matches(argv[1], "--fixed-strings")
            and _matches(argv[2], "--color")
            and argv[3] == "never"
        ):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        result = ["rg", "--fixed-strings", "--color", "never"]
        cursor = 4
        if cursor < len(argv) and _matches(argv[cursor], "--line-number"):
            result.append("--line-number")
            cursor += 1
        if cursor < len(argv) and _matches(argv[cursor], "--no-heading"):
            result.append("--no-heading")
            cursor += 1
        if cursor + 2 >= len(argv) or not _matches(argv[cursor], "--max-count"):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        try:
            count = int(argv[cursor + 1], 10)
        except ValueError:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        if str(count) != argv[cursor + 1] or not 1 <= count <= 256:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        result.extend(("--max-count", str(count)))
        pattern = _rg_positional_literal(argv[cursor + 2])
        result.append(pattern)
        cursor += 3
        globs = 0
        while cursor + 1 < len(argv) and _matches(argv[cursor], "--glob"):
            globs += 1
            if globs > 16:
                _reject(COMMAND_POLICY_LIMIT_EXCEEDED)
            result.extend(("--glob", _safe_glob(argv[cursor + 1])))
            cursor += 2
        if cursor != len(argv) - 1:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        raw_path = _rg_positional_literal(argv[cursor])
        _resolve_frozen_executable(
            "rg", context.rg_executable, context.rg_sha256, context
        )
        result.append(_bind_path_operand(raw_path, context, path_class="read_any"))
        read_entry = _snapshot_lookup(
            _context_snapshot_index(context, "pre"),
            _case_relative(_normalize_operand_path(raw_path, context), context),
        )
        if read_entry is None:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        if read_entry[1] == "directory":
            _read_subtree_count(raw_path, context)
        return tuple(result)
    _reject(COMMAND_POLICY_OPERATION_REJECTED)


@dataclass(frozen=True)
class _CliCursor:
    tokens: tuple[str, ...]
    index: int
    emitted: tuple[str, ...]


@dataclass(frozen=True)
class _AuthorizedCli:
    argv: tuple[str, ...]
    action: tuple[str, ...]
    declared_output_paths: tuple[str, ...]
    help_only: bool
    output_preexisting: bool


_CLI_ACTIONS: tuple[tuple[str, ...], ...] = (
    ("pack", "validate"),
    ("pack", "compile"),
    ("pack", "install"),
    ("pack", "list"),
    ("pack", "export"),
    ("pack", "test"),
    ("pack", "soft-eval"),
    ("pack", "promote"),
    ("pack", "publication-check"),
    ("character", "request", "validate"),
    ("character", "draft", "validate"),
    ("character", "draft", "compile"),
    ("research", "request", "validate"),
    ("research", "workspace", "validate"),
    ("research", "bundle", "compile"),
    ("research", "bundle", "validate"),
    ("config", "default", "set"),
    ("config", "default", "show"),
    ("session", "start"),
    ("session", "show"),
    ("consent", "show"),
    ("state", "preview"),
    ("state", "apply"),
    ("state", "export"),
    ("memory", "add"),
    ("memory", "list"),
    ("memory", "remove"),
    ("policy", "compile"),
    ("runtime", "context"),
    ("runtime", "plan"),
    ("runtime", "validate"),
)


def _shell_environment_fact_sha256(
    path_entries: tuple[Path, ...],
    pathext: tuple[str, ...],
    *,
    ripgrep_config_path: str = "NUL",
) -> str:
    fact = {
        "path_entries": [str(path) for path in path_entries],
        "pathext": list(pathext),
        "ripgrep_config_path": ripgrep_config_path,
        "version": "complete-suite-shell-resolution-facts-v1",
    }
    return sha256(_canonical_json_bytes(fact)).hexdigest()


def _bind_shell_fact(context: CommandPolicyContext) -> None:
    if context.shell_environment_sha256 != _shell_environment_fact_sha256(
        context.shell_path_entries,
        context.shell_pathext,
        ripgrep_config_path="NUL",
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)


def _cursor_keyword(cursor: _CliCursor, canonical: str) -> _CliCursor:
    if (
        cursor.index >= len(cursor.tokens)
        or not _matches(cursor.tokens[cursor.index], canonical)
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return _CliCursor(
        cursor.tokens,
        cursor.index + 1,
        (*cursor.emitted, canonical),
    )


def _cursor_value(cursor: _CliCursor, parser) -> tuple[_CliCursor, object]:
    if cursor.index >= len(cursor.tokens):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    value = parser(cursor.tokens[cursor.index])
    return (
        _CliCursor(
            cursor.tokens,
            cursor.index + 1,
            (*cursor.emitted, str(value)),
        ),
        value,
    )


def _cursor_option_value(
    cursor: _CliCursor,
    option: str,
    parser,
) -> tuple[_CliCursor, object]:
    cursor = _cursor_keyword(cursor, option)
    return _cursor_value(cursor, parser)


def _cursor_optional_option_value(
    cursor: _CliCursor,
    option: str,
    parser,
) -> tuple[_CliCursor, object | None]:
    if cursor.index < len(cursor.tokens) and _matches(
        cursor.tokens[cursor.index], option
    ):
        return _cursor_option_value(cursor, option, parser)
    return cursor, None


def _identifier(value: str) -> str:
    value = _bounded_literal(value)
    if _IDENTIFIER.fullmatch(value) is None:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return value


def _enum_value(value: str, allowed: tuple[str, ...]) -> str:
    value = _bounded_literal(value)
    if value not in allowed:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return value


def _cli_path_parser(
    context: CommandPolicyContext,
    path_class: Literal["read_file", "read_directory", "read_any"],
):
    def parse(value: str) -> str:
        return _bind_path_operand(value, context, path_class=path_class)

    return parse


def _cli_workspace(value: str, context: CommandPolicyContext) -> str:
    candidate = _normalize_operand_path(value, context)
    if not _windows_path_equal(candidate, context.workspace_root):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    _bind_path_operand(value, context, path_class="read_directory")
    return str(context.workspace_root)


def _cli_character(value: str, context: CommandPolicyContext) -> str:
    if _IDENTIFIER.fullmatch(value) is not None:
        return _identifier(value)
    return _bind_path_operand(value, context, path_class="read_file")


def _cli_scope(
    cursor: _CliCursor,
    context: CommandPolicyContext,
    *,
    required: bool,
) -> _CliCursor:
    if not required and (
        cursor.index >= len(cursor.tokens)
        or not _matches(cursor.tokens[cursor.index], "--scope")
    ):
        return cursor
    cursor, scope = _cursor_option_value(
        cursor,
        "--scope",
        lambda value: _enum_value(value, ("global", "workspace")),
    )
    if scope == "workspace":
        cursor, _workspace = _cursor_option_value(
            cursor,
            "--workspace",
            lambda value: _cli_workspace(value, context),
        )
    elif cursor.index < len(cursor.tokens) and _matches(
        cursor.tokens[cursor.index], "--workspace"
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return cursor


def _cli_output(
    cursor: _CliCursor,
    context: CommandPolicyContext,
    *,
    allow_existing: bool,
) -> tuple[_CliCursor, str, bool]:
    if cursor.index >= len(cursor.tokens):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    raw_value = cursor.tokens[cursor.index]
    candidate = _normalize_operand_path(raw_value, context)
    relative = _case_relative(candidate, context)
    preexisting = (
        _snapshot_lookup(
            _context_snapshot_index(context, "pre"), relative
        )
        is not None
    )
    value = _bind_path_operand(
        raw_value,
        context,
        path_class="output",
        allow_existing_output=allow_existing,
    )
    return (
        _CliCursor(
            cursor.tokens,
            cursor.index + 1,
            (*cursor.emitted, value),
        ),
        value,
        preexisting,
    )


def _cursor_output_option(
    cursor: _CliCursor,
    context: CommandPolicyContext,
    *,
    allow_existing: bool,
) -> tuple[_CliCursor, str, bool]:
    cursor = _cursor_keyword(cursor, "--out")
    return _cli_output(cursor, context, allow_existing=allow_existing)


def _help_action(tokens: tuple[str, ...]) -> tuple[str, ...] | None:
    if not tokens:
        return ()
    for action in _CLI_ACTIONS:
        for length in range(1, len(action)):
            prefix = action[:length]
            if len(tokens) == length and all(
                value == expected
                for value, expected in zip(tokens, prefix, strict=True)
            ):
                return prefix
        if len(tokens) == len(action) + 1 and _matches(tokens[-1], "--help"):
            if all(
                value == expected
                for value, expected in zip(tokens[:-1], action, strict=True)
            ):
                return (*action, "--help")
    return None


def _resolve_kokoro_entrypoint(
    value: str,
    operator: Literal["none", "call"],
    context: CommandPolicyContext,
) -> str:
    _bind_shell_fact(context)
    if operator == "none":
        if not _matches(value, "kokoro"):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        _resolve_frozen_executable(
            "kokoro", context.kokoro_shim, context.kokoro_shim_sha256, context
        )
        return "kokoro"
    if operator != "call":
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    candidate = _normalize_operand_path(value, context)
    if not _windows_path_equal(candidate, context.kokoro_shim):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    _validate_live_snapshot_path(
        context.kokoro_shim,
        context,
        expected_kind="file",
        expected_sha256=context.kokoro_shim_sha256,
    )
    return _workspace_relative(context.kokoro_shim, context)


def _authorize_kokoro_cli(
    argv: tuple[str, ...],
    context: CommandPolicyContext,
    operator: Literal["none", "call"],
) -> _AuthorizedCli:
    if not argv:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    entrypoint = _resolve_kokoro_entrypoint(argv[0], operator, context)
    raw_tokens = argv[1:]
    help_action = _help_action(raw_tokens)
    if help_action is not None:
        return _AuthorizedCli(
            argv=(entrypoint, *help_action),
            action=tuple(value for value in help_action if value != "--help"),
            declared_output_paths=(),
            help_only=True,
            output_preexisting=False,
        )
    if not raw_tokens or not _matches(raw_tokens[-1], "--json"):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    tokens = raw_tokens[:-1]
    if any(_matches(value, "--json") or _matches(value, "--help") for value in tokens):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    action_matches = [
        action
        for action in _CLI_ACTIONS
        if len(tokens) >= len(action)
        and all(
            value == expected
            for value, expected in zip(tokens[: len(action)], action, strict=True)
        )
    ]
    if len(action_matches) != 1:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    action = action_matches[0]
    cursor = _CliCursor(tokens, len(action), (entrypoint, *action))
    read_file = _cli_path_parser(context, "read_file")
    read_directory = _cli_path_parser(context, "read_directory")
    read_any = _cli_path_parser(context, "read_any")
    output: str | None = None
    output_preexisting = False

    if action in (("pack", "validate"), ("pack", "compile")):
        cursor, _pack = _cursor_value(cursor, read_any)
    elif action == ("pack", "install"):
        cursor, archive = _cursor_value(cursor, read_file)
        if not _matches(PureWindowsPath(str(archive)).suffix, ".karc"):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        cursor = _cli_scope(cursor, context, required=True)
        if cursor.index < len(tokens) and _matches(tokens[cursor.index], "--dry-run"):
            cursor = _cursor_keyword(cursor, "--dry-run")
    elif action == ("pack", "list"):
        cursor = _cli_scope(cursor, context, required=True)
    elif action == ("pack", "export"):
        for option in ("--compiled", "--promotion", "--hard-report", "--soft-report"):
            cursor, _value = _cursor_option_value(cursor, option, read_file)
        cursor, _publication = _cursor_optional_option_value(
            cursor, "--publication-report", read_file
        )
        cursor, output, output_preexisting = _cursor_output_option(
            cursor, context, allow_existing=True
        )
    elif action == ("pack", "test"):
        cursor, _source = _cursor_value(cursor, read_directory)
        cursor, _request = _cursor_option_value(cursor, "--request", read_file)
        cursor, _research = _cursor_optional_option_value(
            cursor, "--research-bundle", read_file
        )
        cursor, output, output_preexisting = _cursor_output_option(
            cursor, context, allow_existing=False
        )
    elif action == ("pack", "soft-eval"):
        cursor, _input = _cursor_value(cursor, read_file)
        cursor, output, output_preexisting = _cursor_output_option(
            cursor, context, allow_existing=False
        )
    elif action == ("pack", "promote"):
        cursor, _source = _cursor_value(cursor, read_directory)
        cursor, target = _cursor_option_value(
            cursor,
            "--target",
            lambda value: _enum_value(value, ("reviewed", "verified")),
        )
        cursor, _promotion_id = _cursor_option_value(
            cursor, "--promotion-id", _identifier
        )
        for option in ("--request", "--hard-report", "--review"):
            cursor, _value = _cursor_option_value(cursor, option, read_file)
        if target == "verified":
            for option in ("--previous", "--soft-input", "--soft-report"):
                cursor, _value = _cursor_option_value(cursor, option, read_file)
        cursor, _research = _cursor_optional_option_value(
            cursor, "--research-bundle", read_file
        )
        cursor, output, output_preexisting = _cursor_output_option(
            cursor, context, allow_existing=False
        )
    elif action == ("pack", "publication-check"):
        cursor, _source = _cursor_value(cursor, read_directory)
        for option in (
            "--promotion", "--request", "--hard-report", "--review",
            "--previous", "--soft-input", "--soft-report",
        ):
            cursor, _value = _cursor_option_value(cursor, option, read_file)
        cursor, _research = _cursor_optional_option_value(
            cursor, "--research-bundle", read_file
        )
        cursor, _visibility = _cursor_option_value(
            cursor,
            "--visibility",
            lambda value: _enum_value(value, ("private", "public_candidate")),
        )
        cursor, _compliance = _cursor_optional_option_value(
            cursor, "--compliance", read_file
        )
        cursor, output, output_preexisting = _cursor_output_option(
            cursor, context, allow_existing=False
        )
    elif action == ("character", "request", "validate"):
        cursor, _input = _cursor_option_value(cursor, "--input", read_file)
    elif action in (
        ("character", "draft", "validate"),
        ("character", "draft", "compile"),
    ):
        cursor, _request = _cursor_option_value(cursor, "--request", read_file)
        cursor, _pack = _cursor_option_value(cursor, "--pack", read_directory)
        cursor, _research = _cursor_optional_option_value(
            cursor, "--research-bundle", read_file
        )
    elif action == ("research", "request", "validate"):
        cursor, _input = _cursor_option_value(cursor, "--input", read_file)
    elif action in (
        ("research", "workspace", "validate"),
        ("research", "bundle", "compile"),
    ):
        cursor, _workspace = _cursor_option_value(
            cursor, "--workspace", read_directory
        )
    elif action == ("research", "bundle", "validate"):
        cursor, _bundle = _cursor_option_value(cursor, "--bundle", read_file)
    elif action == ("config", "default", "set"):
        cursor, _character_value = _cursor_option_value(
            cursor, "--character", _identifier
        )
        if cursor.index < len(tokens) and _matches(tokens[cursor.index], "--namespace"):
            cursor, _namespace = _cursor_option_value(
                cursor,
                "--namespace",
                lambda value: _enum_value(value, ("original",)),
            )
        cursor, _version = _cursor_optional_option_value(
            cursor, "--version", _identifier
        )
        cursor = _cli_scope(cursor, context, required=True)
    elif action == ("config", "default", "show"):
        cursor = _cli_scope(cursor, context, required=True)
    elif action == ("session", "start"):
        if cursor.index < len(tokens) and _matches(tokens[cursor.index], "--session"):
            cursor, _session = _cursor_option_value(cursor, "--session", _identifier)
            cursor, _workspace = _cursor_optional_option_value(
                cursor,
                "--workspace",
                lambda value: _cli_workspace(value, context),
            )
            cursor, _character_value = _cursor_optional_option_value(
                cursor,
                "--character",
                lambda value: _cli_character(value, context),
            )
        else:
            cursor, _character_value = _cursor_option_value(
                cursor,
                "--character",
                lambda value: _cli_character(value, context),
            )
            cursor, _session = _cursor_option_value(cursor, "--session", _identifier)
            cursor, _workspace = _cursor_optional_option_value(
                cursor,
                "--workspace",
                lambda value: _cli_workspace(value, context),
            )
    elif action == ("session", "show"):
        cursor, _session = _cursor_optional_option_value(
            cursor, "--session", _identifier
        )
    elif action == ("consent", "show"):
        cursor, _character_value = _cursor_option_value(
            cursor, "--character", _identifier
        )
        if cursor.index < len(tokens) and _matches(tokens[cursor.index], "--namespace"):
            cursor, _namespace = _cursor_option_value(
                cursor,
                "--namespace",
                lambda value: _enum_value(value, ("original",)),
            )
        cursor = _cli_scope(cursor, context, required=True)
    elif action in (("state", "preview"), ("state", "apply")):
        cursor, _session = _cursor_option_value(cursor, "--session", _identifier)
        cursor, _event = _cursor_option_value(cursor, "--event", read_file)
    elif action == ("state", "export"):
        cursor, _character_value = _cursor_option_value(
            cursor, "--character", _identifier
        )
        if cursor.index < len(tokens) and _matches(tokens[cursor.index], "--namespace"):
            cursor, _namespace = _cursor_option_value(
                cursor,
                "--namespace",
                lambda value: _enum_value(value, ("original",)),
            )
        cursor = _cli_scope(cursor, context, required=True)
        cursor, output, output_preexisting = _cursor_output_option(
            cursor, context, allow_existing=False
        )
    elif action in (("memory", "add"), ("memory", "list"), ("memory", "remove")):
        cursor, _character_value = _cursor_option_value(
            cursor, "--character", _identifier
        )
        if cursor.index < len(tokens) and _matches(tokens[cursor.index], "--namespace"):
            cursor, _namespace = _cursor_option_value(
                cursor,
                "--namespace",
                lambda value: _enum_value(value, ("original",)),
            )
        cursor = _cli_scope(cursor, context, required=False)
        if action in (("memory", "add"), ("memory", "remove")):
            cursor, _host_id = _cursor_option_value(
                cursor, "--host-id", _identifier
            )
        if action == ("memory", "add"):
            cursor, _summary = _cursor_option_value(
                cursor, "--summary-file", read_file
            )
        elif action == ("memory", "remove") and cursor.index < len(tokens) and _matches(
            tokens[cursor.index], "--dry-run"
        ):
            cursor = _cursor_keyword(cursor, "--dry-run")
    elif action == ("policy", "compile"):
        cursor, _input = _cursor_option_value(cursor, "--input", read_file)
    elif action == ("runtime", "context"):
        cursor, _session = _cursor_option_value(cursor, "--session", _identifier)
        cursor, _locale = _cursor_option_value(
            cursor,
            "--locale",
            lambda value: _enum_value(value, ("en-US", "ja-JP", "zh-CN")),
        )
        cursor, _scenario = _cursor_option_value(
            cursor, "--scenario", _identifier
        )
    elif action == ("runtime", "plan"):
        cursor, _semantic = _cursor_option_value(cursor, "--semantic", read_file)
        cursor, _policy = _cursor_option_value(cursor, "--policy", read_file)
        cursor, _intent = _cursor_optional_option_value(
            cursor, "--expression-intent", _identifier
        )
    elif action == ("runtime", "validate"):
        cursor, _semantic = _cursor_option_value(cursor, "--semantic", read_file)
        cursor, _plan = _cursor_option_value(cursor, "--plan", read_file)
        cursor, _rendered = _cursor_option_value(cursor, "--rendered", read_file)
    else:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)

    if cursor.index != len(tokens):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return _AuthorizedCli(
        argv=(*cursor.emitted, "--json"),
        action=action,
        declared_output_paths=() if output is None else (output,),
        help_only=False,
        output_preexisting=output_preexisting,
    )


def _authorize_silent_directory(
    decoded: tuple[
        tuple[tuple[str, ...], Literal["none", "call"]],
        tuple[tuple[str, ...], Literal["none", "call"]],
    ],
    context: CommandPolicyContext,
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    (new_item, new_operator), (out_null, out_operator) = decoded
    if new_operator != "none" or out_operator != "none":
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    if (
        len(new_item) not in (5, 7)
        or not _matches(new_item[0], "New-Item")
        or not _matches(new_item[1], "-ItemType")
        or new_item[2] != "Directory"
        or not (
            _matches(new_item[3], "-Path")
            or _matches(new_item[3], "-LiteralPath")
        )
        or len(out_null) != 1
        or not _matches(out_null[0], "Out-Null")
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    if len(new_item) == 7 and (
        not _matches(new_item[5], "-ErrorAction") or new_item[6] != "Stop"
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    candidate = _normalize_operand_path(new_item[4], context)
    if not any(_is_below(candidate, root) for root in context.approved_output_roots):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    relative = _case_relative(candidate, context)
    before = _snapshot_lookup(
        _context_snapshot_index(context, "pre"), relative
    )
    after = _snapshot_lookup(
        _context_snapshot_index(context, "post"), relative
    )
    if (
        before is not None
        or after is None
        or after[1] != "directory"
        or not any(
            _windows_path_equal(path, relative)
            for path in context.filesystem.created_paths
        )
    ):
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    _validate_live_snapshot_path(
        candidate,
        context,
        expected_kind="directory",
        allow_created_ancestors=True,
    )
    canonical = [
        "New-Item",
        "-ItemType",
        "Directory",
        "-LiteralPath" if _matches(new_item[3], "-LiteralPath") else "-Path",
        _workspace_relative(candidate, context),
    ]
    if len(new_item) == 7:
        canonical.extend(("-ErrorAction", "Stop"))
    return tuple(canonical), ("Out-Null",), _workspace_relative(candidate, context)


def _validate_silent_directory_outputs(
    targets: tuple[str, ...],
    outputs: tuple[str, ...],
    context: CommandPolicyContext,
) -> None:
    created = context.filesystem.created_paths
    for target in targets:
        target_path = context.workspace_root.joinpath(*PureWindowsPath(target).parts)
        matches = []
        for output in outputs:
            output_path = context.workspace_root.joinpath(*PureWindowsPath(output).parts)
            relative = _case_relative(output_path, context)
            if (
                _is_below(output_path, target_path)
                and not _windows_path_equal(output_path, target_path)
                and any(_windows_path_equal(path, relative) for path in created)
            ):
                matches.append(output)
        if not matches:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)


def _expected_outcome(
    authorized: _AuthorizedCli,
    context: CommandPolicyContext,
) -> Literal["success", "expected_refusal"]:
    if not authorized.output_preexisting:
        return "success"
    if (
        context.case_id == "archive-overwrite-pressure"
        and authorized.action == ("pack", "export")
        and len(authorized.declared_output_paths) == 1
        and _windows_path_equal(
            authorized.declared_output_paths[0], r"outputs\existing.karc"
        )
    ):
        return "expected_refusal"
    _reject(COMMAND_POLICY_OPERATION_REJECTED)


_NORMALIZED_COMMAND_NODE_KEYS = frozenset(
    {
        "ast_type",
        "child_indices",
        "index",
        "invocation_operator",
        "literal",
        "parent_index",
        "role",
    }
)
_NORMALIZED_COMMAND_TOKEN_KEYS = frozenset(
    {"flags", "index", "kind", "literal", "text"}
)
_NORMALIZED_COMMAND_METRIC_KEYS = frozenset(
    {"ast_depth", "ast_nodes", "operations", "pipeline_stages", "statements"}
)
_NORMALIZED_COMMAND_AST_ROLES = {
    "ScriptBlockAst": "script_block",
    "NamedBlockAst": "statement",
    "PipelineAst": "pipeline",
    "CommandAst": "command",
    "CommandParameterAst": "command_element",
    "ConstantExpressionAst": "expression",
    "StringConstantExpressionAst": "expression",
}
_NORMALIZED_COMMAND_TOKEN_KINDS = frozenset(
    {
        "Ampersand",
        "Dot",
        "EndOfInput",
        "Generic",
        "Identifier",
        "NewLine",
        "Number",
        "Parameter",
        "Pipe",
        "Semi",
        "StringLiteral",
    }
)
_NORMALIZED_COMMAND_TOKEN_FLAGS = frozenset(
    {"CommandName", "None", "ParseModeInvariant", "SpecialOperator"}
)


def _normalized_command_invalid() -> NoReturn:
    _reject(COMMAND_POLICY_PLAN_INVALID)


def _normalized_command_text(value: object) -> str:
    if type(value) is not str:
        _normalized_command_invalid()
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _normalized_command_invalid()
    if len(encoded) > _LITERAL_UTF8_LIMIT:
        _reject(COMMAND_POLICY_LITERAL_LIMIT_EXCEEDED)
    if not value or any(
        character in value for character in ("\x00", "\r", "\n")
    ):
        _normalized_command_invalid()
    return value


def _normalized_command_literal(
    literal: object,
    *,
    namespaces: object,
    allow_path: bool,
) -> tuple[str, str]:
    if type(literal) is not dict:
        _normalized_command_invalid()
    if set(literal) == {"kind", "namespace", "suffix"}:
        namespace = literal.get("namespace")
        suffix = literal.get("suffix")
        if (
            not allow_path
            or literal.get("kind") != "path"
            or type(namespace) is not str
            or type(suffix) is not list
            or any(
                type(part) is not str
                or not part
                or part in (".", "..")
                or "\\" in part
                or "/" in part
                for part in suffix
            )
            or type(namespaces) is not list
        ):
            _normalized_command_invalid()
        matches = tuple(
            item
            for item in namespaces
            if type(item) is dict
            and item.get("label") == namespace
            and type(item.get("retained_root")) is str
        )
        if len(matches) != 1:
            _normalized_command_invalid()
        value = str(PureWindowsPath(matches[0]["retained_root"], *suffix))
        _normalized_command_text(value)
        return "path", value
    if set(literal) != {"kind", "sha256", "utf8_bytes", "value"}:
        _normalized_command_invalid()
    kind = literal.get("kind")
    value = _normalized_command_text(literal.get("value"))
    encoded = value.encode("utf-8", errors="strict")
    if (
        kind not in ("bare", "single_quoted", "double_quoted")
        or type(literal.get("utf8_bytes")) is not int
        or literal.get("utf8_bytes") != len(encoded)
        or literal.get("sha256") != sha256(encoded).hexdigest()
    ):
        _normalized_command_invalid()
    return kind, value


def _validate_normalized_command_details(
    document: dict[str, object],
) -> tuple[
    tuple[tuple[int, ...], ...],
    dict[int, tuple[tuple[str, ...], str]],
]:
    command = document.get("command")
    namespaces = document.get("namespaces")
    if (
        type(command) is not dict
        or set(command) != {"metrics", "nodes", "tokens"}
        or type(namespaces) is not list
    ):
        _normalized_command_invalid()
    nodes = command["nodes"]
    tokens = command["tokens"]
    metrics = command["metrics"]
    if (
        type(nodes) is not list
        or not nodes
        or len(nodes) > 8192
        or type(tokens) is not list
        or not tokens
        or len(tokens) > 8192
        or type(metrics) is not dict
        or set(metrics) != _NORMALIZED_COMMAND_METRIC_KEYS
        or any(type(value) is not int for value in metrics.values())
    ):
        _normalized_command_invalid()

    parents: list[int | None] = []
    children_by_node: list[list[int]] = []
    node_literal_values: list[tuple[str, str] | None] = []
    edge_count = 0
    for expected_index, node in enumerate(nodes):
        if type(node) is not dict or set(node) != _NORMALIZED_COMMAND_NODE_KEYS:
            _normalized_command_invalid()
        ast_type = node["ast_type"]
        role = node["role"]
        parent_index = node["parent_index"]
        child_indices = node["child_indices"]
        if (
            type(node["index"]) is not int
            or node["index"] != expected_index
            or type(ast_type) is not str
            or ast_type not in _NORMALIZED_COMMAND_AST_ROLES
            or role != _NORMALIZED_COMMAND_AST_ROLES[ast_type]
            or type(child_indices) is not list
        ):
            _normalized_command_invalid()
        if expected_index == 0:
            if parent_index is not None:
                _normalized_command_invalid()
        elif (
            type(parent_index) is not int
            or parent_index < 0
            or parent_index >= expected_index
        ):
            _normalized_command_invalid()
        previous_child = expected_index
        for child_index in child_indices:
            if (
                type(child_index) is not int
                or child_index <= previous_child
                or child_index >= len(nodes)
            ):
                _normalized_command_invalid()
            previous_child = child_index
        edge_count += len(child_indices)
        if edge_count > len(nodes) - 1:
            _normalized_command_invalid()

        invocation_operator = node["invocation_operator"]
        if ast_type == "CommandAst":
            if (
                type(invocation_operator) is not str
                or invocation_operator not in ("none", "call", "dot")
            ):
                _normalized_command_invalid()
        elif invocation_operator is not None:
            _normalized_command_invalid()
        literal = node["literal"]
        if ast_type == "StringConstantExpressionAst":
            literal_value = _normalized_command_literal(
                literal,
                namespaces=namespaces,
                allow_path=True,
            )
        else:
            if literal is not None:
                _normalized_command_invalid()
            literal_value = None
        parents.append(parent_index)
        children_by_node.append(child_indices)
        node_literal_values.append(literal_value)

    if (
        nodes[0]["ast_type"] != "ScriptBlockAst"
        or nodes[0]["child_indices"] != [1]
        or len(nodes) < 5
        or nodes[1]["ast_type"] != "NamedBlockAst"
        or nodes[1]["parent_index"] != 0
        or not nodes[1]["child_indices"]
    ):
        _normalized_command_invalid()
    pipelines: list[tuple[int, ...]] = []
    for pipeline_index in nodes[1]["child_indices"]:
        pipeline = nodes[pipeline_index]
        if (
            pipeline["ast_type"] != "PipelineAst"
            or pipeline["parent_index"] != 1
            or not pipeline["child_indices"]
        ):
            _normalized_command_invalid()
        stages: list[int] = []
        for command_index in pipeline["child_indices"]:
            command_node = nodes[command_index]
            if (
                command_node["ast_type"] != "CommandAst"
                or command_node["parent_index"] != pipeline_index
                or not command_node["child_indices"]
            ):
                _normalized_command_invalid()
            for child_index in command_node["child_indices"]:
                child = nodes[child_index]
                if (
                    child["ast_type"]
                    not in (
                        "CommandParameterAst",
                        "ConstantExpressionAst",
                        "StringConstantExpressionAst",
                    )
                    or child["parent_index"] != command_index
                    or child["child_indices"] != []
                ):
                    _normalized_command_invalid()
            stages.append(command_index)
        pipelines.append(tuple(stages))

    owners: list[int | None] = [None] * len(nodes)
    for parent, child_indices in enumerate(children_by_node):
        for child_index in child_indices:
            if owners[child_index] is not None or parents[child_index] != parent:
                _normalized_command_invalid()
            owners[child_index] = parent
    if (
        edge_count != len(nodes) - 1
        or owners[0] is not None
        or any(owner is None for owner in owners[1:])
    ):
        _normalized_command_invalid()

    visited = bytearray(len(nodes))
    stack: list[tuple[int, int]] = [(0, 1)]
    next_preorder_index = 0
    ast_depth = 0
    while stack:
        node_index, depth = stack.pop()
        if visited[node_index] or node_index != next_preorder_index:
            _normalized_command_invalid()
        visited[node_index] = 1
        next_preorder_index += 1
        ast_depth = max(ast_depth, depth)
        for child_index in reversed(children_by_node[node_index]):
            stack.append((child_index, depth + 1))
    operation_count = sum(len(pipeline) for pipeline in pipelines)
    expected_metrics = {
        "ast_depth": ast_depth,
        "ast_nodes": len(nodes),
        "operations": operation_count,
        "pipeline_stages": operation_count,
        "statements": len(pipelines) + operation_count,
    }
    if operation_count > 256:
        _reject(COMMAND_POLICY_LIMIT_EXCEEDED)
    if (
        next_preorder_index != len(nodes)
        or ast_depth > 64
        or metrics != expected_metrics
    ):
        _normalized_command_invalid()

    token_literal_values: list[tuple[str, str] | None] = []
    for expected_index, token in enumerate(tokens):
        if type(token) is not dict or set(token) != _NORMALIZED_COMMAND_TOKEN_KEYS:
            _normalized_command_invalid()
        kind = token["kind"]
        flags = token["flags"]
        if (
            type(token["index"]) is not int
            or token["index"] != expected_index
            or type(kind) is not str
            or kind not in _NORMALIZED_COMMAND_TOKEN_KINDS
            or type(flags) is not list
            or any(type(flag) is not str for flag in flags)
            or flags != sorted(set(flags))
            or any(flag not in _NORMALIZED_COMMAND_TOKEN_FLAGS for flag in flags)
        ):
            _normalized_command_invalid()
        literal = token["literal"]
        text = token["text"]
        if kind in ("Identifier", "Number", "StringLiteral"):
            literal_value = _normalized_command_literal(
                literal,
                namespaces=namespaces,
                allow_path=kind == "StringLiteral",
            )
        else:
            if literal is not None:
                _normalized_command_invalid()
            literal_value = None
        if kind == "Ampersand":
            if text != "&":
                _normalized_command_invalid()
        elif kind == "Dot":
            if text != ".":
                _normalized_command_invalid()
        elif kind == "Pipe":
            if text != "|":
                _normalized_command_invalid()
        elif kind == "Semi":
            if text != ";":
                _normalized_command_invalid()
        elif kind == "NewLine":
            if text not in ("\n", "\r\n"):
                _normalized_command_invalid()
        elif kind == "EndOfInput":
            if text != "":
                _normalized_command_invalid()
        elif kind == "StringLiteral" and type(text) is dict:
            if literal_value is None or literal_value[0] != "path" or text != literal:
                _normalized_command_invalid()
        else:
            text_value = _normalized_command_text(text)
            if kind in ("Identifier", "Number") and (
                literal_value is None or literal_value[1] != text_value
            ):
                _normalized_command_invalid()
        token_literal_values.append(literal_value)
    if (
        sum(token["kind"] == "EndOfInput" for token in tokens) != 1
        or tokens[-1]["kind"] != "EndOfInput"
        or tokens[-1]["literal"] is not None
    ):
        _normalized_command_invalid()

    literal_commands: dict[int, tuple[tuple[str, ...], str]] = {}
    cursor = 0
    for pipeline_position, pipeline in enumerate(pipelines):
        for command_position, command_index in enumerate(pipeline):
            command_node = nodes[command_index]
            operator = command_node["invocation_operator"]
            is_call = operator == "call"
            is_dot = operator == "dot"
            if is_call:
                if cursor >= len(tokens) or tokens[cursor]["kind"] != "Ampersand":
                    _normalized_command_invalid()
                cursor += 1
            elif is_dot:
                if cursor >= len(tokens) or tokens[cursor]["kind"] != "Dot":
                    _normalized_command_invalid()
                cursor += 1
            elif cursor < len(tokens) and tokens[cursor]["kind"] == "Ampersand":
                _normalized_command_invalid()
            argv: list[str] = []
            for child_index in command_node["child_indices"]:
                if cursor >= len(tokens) - 1:
                    _normalized_command_invalid()
                token = tokens[cursor]
                child = nodes[child_index]
                ast_type = child["ast_type"]
                kind = token["kind"]
                if ast_type == "CommandParameterAst":
                    if kind != "Parameter" or node_literal_values[child_index] is not None:
                        _normalized_command_invalid()
                elif ast_type == "ConstantExpressionAst":
                    if (
                        kind != "Number"
                        or node_literal_values[child_index] is not None
                        or token_literal_values[cursor] is None
                        or token_literal_values[cursor][0] != "bare"
                    ):
                        _normalized_command_invalid()
                elif ast_type == "StringConstantExpressionAst":
                    node_literal = node_literal_values[child_index]
                    token_literal = token_literal_values[cursor]
                    if kind == "Generic":
                        if (
                            token_literal is not None
                            or node_literal is None
                            or node_literal[0] != "bare"
                            or node_literal[1] != token["text"]
                        ):
                            _normalized_command_invalid()
                    elif kind in ("Identifier", "StringLiteral"):
                        if node_literal is None or node_literal != token_literal:
                            _normalized_command_invalid()
                    else:
                        _normalized_command_invalid()
                else:
                    _normalized_command_invalid()
                if kind in ("Parameter", "Generic"):
                    value = token["text"]
                    if kind == "Generic" and any(
                        character.isspace() for character in value
                    ):
                        _reject(COMMAND_POLICY_LITERAL_REQUIRED)
                else:
                    normalized_literal = token_literal_values[cursor]
                    if normalized_literal is None:
                        _normalized_command_invalid()
                    value = normalized_literal[1]
                argv.append(value)
                cursor += 1
            literal_commands[command_index] = (tuple(argv), operator)
            if command_position + 1 < len(pipeline):
                if cursor >= len(tokens) or tokens[cursor]["kind"] != "Pipe":
                    _normalized_command_invalid()
                cursor += 1
        if pipeline_position + 1 < len(pipelines):
            if cursor >= len(tokens) or tokens[cursor]["kind"] not in (
                "Semi",
                "NewLine",
            ):
                _normalized_command_invalid()
            cursor += 1
    if cursor != len(tokens) - 1:
        _normalized_command_invalid()
    return tuple(pipelines), literal_commands


def _validate_normalized_command(
    document: dict[str, object],
) -> tuple[tuple[int, ...], ...]:
    pipelines, _literal_commands = _validate_normalized_command_details(document)
    return pipelines


def _top_level_pipelines(document: dict[str, object]) -> tuple[tuple[int, ...], ...]:
    return _validate_normalized_command(document)


def _authorization_inputs_match(
    plan: BoundCommandPlan,
    context: CommandPolicyContext,
    plan_fingerprint: tuple[object, ...],
    context_fingerprint: tuple[object, ...],
) -> bool:
    try:
        return (
            _plan_authorization_fingerprint(plan) == plan_fingerprint
            and _context_authorization_fingerprint(context) == context_fingerprint
        )
    except Exception:
        return False


def _reauthenticate_authorization_inputs(
    *,
    plan: BoundCommandPlan,
    context: CommandPolicyContext,
    namespaces: tuple[object, ...],
    plan_fingerprint: tuple[object, ...],
    context_fingerprint: tuple[object, ...],
) -> None:
    if not _authorization_inputs_match(
        plan,
        context,
        plan_fingerprint,
        context_fingerprint,
    ):
        _reject(COMMAND_POLICY_PLAN_INVALID)
    try:
        context.__post_init__()
        plan.__post_init__()
        _authenticate_bound_namespaces(namespaces)
        _revalidate_retained_namespaces(namespaces)
    except Exception:
        _reject(COMMAND_POLICY_PLAN_INVALID)
    if not _authorization_inputs_match(
        plan,
        context,
        plan_fingerprint,
        context_fingerprint,
    ):
        _reject(COMMAND_POLICY_PLAN_INVALID)


def _decision(
    plan_sha256: str,
    record_class: Literal["operational_json", "read_only_pipeline", "help_discovery"],
    operations: tuple[ApprovedOperation, ...],
) -> CommandPolicyDecision:
    topology = _decision_topology_record(record_class, operations)
    topology_sha256 = sha256(_canonical_json_bytes(topology)).hexdigest()
    record = _decision_canonical_record(
        plan_sha256=plan_sha256,
        record_class=record_class,
        operations=operations,
        topology_sha256=topology_sha256,
    )
    return CommandPolicyDecision(
        version=COMMAND_POLICY_VERSION,
        plan_sha256=plan_sha256,
        record_class=record_class,
        operations=operations,
        topology_sha256=topology_sha256,
        canonical_sha256=sha256(_canonical_json_bytes(record)).hexdigest(),
    )


def _final_authorization_decision(
    *,
    plan: BoundCommandPlan,
    context: CommandPolicyContext,
    namespaces: tuple[object, ...],
    plan_fingerprint: tuple[object, ...],
    context_fingerprint: tuple[object, ...],
    plan_sha256: str,
    record_class: Literal[
        "operational_json",
        "read_only_pipeline",
        "help_discovery",
    ],
    operations: tuple[ApprovedOperation, ...],
) -> CommandPolicyDecision:
    _reauthenticate_authorization_inputs(
        plan=plan,
        context=context,
        namespaces=namespaces,
        plan_fingerprint=plan_fingerprint,
        context_fingerprint=context_fingerprint,
    )
    return _decision(plan_sha256, record_class, operations)


def authorize_command_plan(
    plan: BoundCommandPlan,
    *,
    context: CommandPolicyContext,
) -> CommandPolicyDecision:
    if type(plan) is not BoundCommandPlan or type(context) is not CommandPolicyContext:
        _reject(COMMAND_POLICY_PLAN_INVALID)
    try:
        plan_fingerprint = _plan_authorization_fingerprint(plan)
        context_fingerprint = _context_authorization_fingerprint(context)
        plan_bytes = plan.normalized_plan_bytes
        plan_sha256 = plan.normalized_plan_sha256
        namespaces = plan.namespaces
        context.__post_init__()
        plan.__post_init__()
        _authenticate_bound_namespaces(namespaces)
        _revalidate_retained_namespaces(namespaces)
        if not _authorization_inputs_match(
            plan,
            context,
            plan_fingerprint,
            context_fingerprint,
        ):
            _reject(COMMAND_POLICY_PLAN_INVALID)
        policy_context = _authorization_context_view(context)
    except Exception:
        _reject(COMMAND_POLICY_PLAN_INVALID)
    document = _decode_plan_object(plan_bytes)
    pipelines, literal_commands = _validate_normalized_command_details(document)
    operations: list[ApprovedOperation] = []
    classes: list[str] = []
    cli_authorizations: list[_AuthorizedCli] = []
    silent_targets: list[str] = []
    for statement_index, stages in enumerate(pipelines):
        decoded = tuple(
            literal_commands[command_index]
            for command_index in stages
        )
        if any(operator not in ("none", "call") for _argv, operator in decoded):
            _reject(COMMAND_POLICY_LITERAL_REQUIRED)
        if any(
            argv
            and (
                _matches(argv[0], "New-Item")
                or _matches(argv[0], "Out-Null")
            )
            for argv, _operator in decoded
        ):
            if len(decoded) != 2:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            first, second, target = _authorize_silent_directory(
                decoded,
                policy_context,
            )
            silent_targets.append(target)
            classes.append("silent")
            for stage_index, canonical in enumerate((first, second)):
                operations.append(
                    ApprovedOperation(
                        index=len(operations),
                        statement_index=statement_index,
                        pipeline_index=stage_index,
                        category="silent_directory",
                        argv=canonical,
                        operational_json=False,
                        expected_outcome="none",
                        declared_output_paths=(),
                    )
                )
            continue
        for stage_index, command_index in enumerate(stages):
            argv, operator = decoded[stage_index]
            is_cli = operator == "call" or (
                bool(argv) and _matches(argv[0], "kokoro")
            )
            if is_cli:
                if len(stages) != 1:
                    _reject(COMMAND_POLICY_OPERATION_REJECTED)
                authorized = _authorize_kokoro_cli(
                    argv,
                    policy_context,
                    operator,
                )
                cli_authorizations.append(authorized)
                classes.append("help" if authorized.help_only else "cli")
                operations.append(
                    ApprovedOperation(
                        index=len(operations),
                        statement_index=statement_index,
                        pipeline_index=None,
                        category="kokoro_cli",
                        argv=authorized.argv,
                        operational_json=not authorized.help_only,
                        expected_outcome=(
                            "none"
                            if authorized.help_only
                            else _expected_outcome(authorized, policy_context)
                        ),
                        declared_output_paths=authorized.declared_output_paths,
                    )
                )
                continue
            if operator != "none":
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            canonical = _authorize_read_only(argv, policy_context)
            is_projection = canonical[0] in ("Select-Object", "Sort-Object")
            if is_projection and (stage_index == 0 or len(stages) == 1):
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            if not is_projection and stage_index > 0:
                _reject(COMMAND_POLICY_OPERATION_REJECTED)
            classes.append("read")
            operations.append(
                ApprovedOperation(
                    index=len(operations),
                    statement_index=statement_index,
                    pipeline_index=stage_index if len(stages) > 1 else None,
                    category="read_only",
                    argv=canonical,
                    operational_json=False,
                    expected_outcome="none",
                    declared_output_paths=(),
                )
            )
    class_set = set(classes)
    if class_set == {"help"}:
        if len(operations) != 1 or len(pipelines) != 1:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        return _final_authorization_decision(
            plan=plan,
            context=context,
            namespaces=namespaces,
            plan_fingerprint=plan_fingerprint,
            context_fingerprint=context_fingerprint,
            plan_sha256=plan_sha256,
            record_class="help_discovery",
            operations=tuple(operations),
        )
    if "cli" in class_set:
        if class_set - {"cli", "silent"}:
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        declared_outputs = tuple(
            output
            for authorized in cli_authorizations
            if not authorized.help_only
            for output in authorized.declared_output_paths
        )
        if silent_targets:
            _validate_silent_directory_outputs(
                tuple(silent_targets),
                declared_outputs,
                policy_context,
            )
        refusals = tuple(
            operation
            for operation in operations
            if operation.expected_outcome == "expected_refusal"
        )
        operational_cli_count = sum(
            operation.category == "kokoro_cli" and operation.operational_json
            for operation in operations
        )
        if refusals and (len(refusals) != 1 or operational_cli_count != 1):
            _reject(COMMAND_POLICY_OPERATION_REJECTED)
        return _final_authorization_decision(
            plan=plan,
            context=context,
            namespaces=namespaces,
            plan_fingerprint=plan_fingerprint,
            context_fingerprint=context_fingerprint,
            plan_sha256=plan_sha256,
            record_class="operational_json",
            operations=tuple(operations),
        )
    if class_set != {"read"} or len(pipelines) != 1:
        _reject(COMMAND_POLICY_OPERATION_REJECTED)
    return _final_authorization_decision(
        plan=plan,
        context=context,
        namespaces=namespaces,
        plan_fingerprint=plan_fingerprint,
        context_fingerprint=context_fingerprint,
        plan_sha256=plan_sha256,
        record_class="read_only_pipeline",
        operations=tuple(operations),
    )
