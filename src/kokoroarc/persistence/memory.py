"""Explicit host-approved persistent memory references."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterator, Literal, Mapping, Sequence, cast

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.persistence._storage import (
    ArtifactSnapshot,
    PersistenceBoundary,
    PersistenceLimits,
    PersistenceLock,
    PersistenceScope,
    SchemaValidator,
    _absolute_path,
    _absent_file_audit,
    _acquire_character_lock,
    _assert_directory_chain,
    _atomic_rename_noreplace,
    _bounded_cleanup_entries,
    _capture_directory_chain,
    _capture_directory_identity,
    _cleanup_failed,
    _directory_identity_matches,
    _file_identity,
    _fsync_directory,
    _lstat,
    _publish_new_file,
    _read_regular_file,
    _require_safe_regular_file,
    open_persistence_scope,
    scan_canonical_directory,
    validate_and_finalize,
)
from kokoroarc.persistence.consent import (
    ActiveConsent,
    _load_consent_state,
    _require_active_consent,
)


_STABLE_ID = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z")
_MEMORY_ID = re.compile(r"memory-[a-f0-9]{32}\Z")
_LOCALES = frozenset({"zh-CN", "en-US", "ja-JP"})
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|token|password|passwd|"
    r"secret|client[_-]?secret)\s*[:=]\s*[^\s,;]+"
)
_AUTHORIZATION = re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+")
_PRIVATE_KEY = re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----")
_CREDENTIAL_URL = re.compile(
    r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@"
)
_WINDOWS_PATH = re.compile(
    r"(?i)(?:^|[\s(\[{'\"=:])(?:[a-z]:[\\/]|\\\\[^\\\s]+\\)"
)
_POSIX_PATH = re.compile(
    r"(?:^|[\s(\[{'\"=:])/(?:Users|home|root|tmp|var|etc|mnt|srv|"
    r"data|opt|usr|private)(?:/|\b)"
)
_FILE_URI = re.compile(r"(?i)\bfile:(?:/{2,3}|\\{2,3})")
_ROLE_LINE = re.compile(
    r"(?im)^\s*(?:system|developer|user|assistant|tool)\s*:\s*\S"
)
_PROMPT_LOG = re.compile(
    r"(?i)(?:<\|im_(?:start|end)\|>|begin\s+prompt\s+log|"
    r"end\s+prompt\s+log|prompt\s+transcript)"
)
_TOOL_DUMP = re.compile(
    r"(?im)(?:\"tool_call_id\"\s*:|\"role\"\s*:\s*\"tool\"|"
    r"^\s*tool\s+result\s*:)"
)


@dataclass(frozen=True, slots=True)
class MemoryReferenceView:
    """Detached reference bytes plus current consent-generation status."""

    payload: bytes
    active_consent_generation: bool

    @property
    def reference(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.payload))


@dataclass(frozen=True, slots=True)
class MemoryRemovalResult:
    """Result of one explicit memory-reference removal."""

    removed: bool
    memory_reference_id: str | None


@dataclass(frozen=True, slots=True)
class _AuditedSchemas:
    schemas: SchemaValidator
    boundary: PersistenceBoundary

    def validate(self, name: str, instance: Any) -> None:
        try:
            self.schemas.validate(name, instance)
        finally:
            self.boundary.assert_clean()


def add_memory_reference(
    data_root: Path,
    character_id: str,
    host_memory_id: str,
    summary: str,
    localized_summaries: Mapping[str, str],
    consent_id: str,
    consent_revision: int,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    """Persist one explicit host-approved reference without host content."""

    return _memory_domain(
        lambda: _add_memory_reference(
            data_root,
            character_id,
            host_memory_id,
            summary,
            localized_summaries,
            consent_id,
            consent_revision,
            schemas,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def list_memory_references(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> Sequence[MemoryReferenceView]:
    """List deterministic detached references without creating storage."""

    return _memory_domain(
        lambda: _list_memory_references(
            data_root,
            character_id,
            schemas,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def remove_memory_reference(
    data_root: Path,
    character_id: str,
    identifier: str,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    identifier_kind: Literal["host_memory_id", "memory_reference_id"],
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> MemoryRemovalResult:
    """Remove one exact reference, including after consent revocation."""

    return _memory_domain(
        lambda: _remove_memory_reference(
            data_root,
            character_id,
            identifier,
            consent_id,
            schemas,
            identifier_kind=identifier_kind,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def _add_memory_reference(
    data_root: Path,
    character_id: str,
    host_memory_id: str,
    summary: str,
    localized_summaries: Mapping[str, str],
    consent_id: str,
    consent_revision: int,
    schemas: SchemaValidator,
    *,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> dict[str, Any]:
    _require_stable_id(host_memory_id, "host_memory_id")
    _require_revision(consent_revision)
    if not isinstance(consent_id, str):
        raise _memory_invalid("consent_id")
    captured_workspace = _capture_workspace_root(workspace_root)
    scope = open_persistence_scope(
        data_root,
        schemas,
        namespace=namespace,
        character_id=character_id,
        workspace_root=captured_workspace,
        limits=limits,
    )
    localized = _capture_localized_summaries(
        scope.boundary,
        localized_summaries,
    )
    _reject_unsafe_memory_content(summary, localized)
    _validate_approved_content(summary, localized)

    with _acquire_character_lock(scope) as lock, _audit_failures(
        scope.boundary
    ):
        references = _scan_memory_references(scope)
        active = _require_active_consent(
            scope.root,
            character_id,
            consent_id,
            consent_revision,
            "memory_references",
            _AuditedSchemas(schemas, scope.boundary),
            namespace=namespace,
            workspace_root=captured_workspace,
            limits=limits,
        )
        active.assert_clean()
        expected = _build_reference(
            scope,
            active,
            host_memory_id,
            summary,
            localized,
        )
        payload = canonical_bytes(expected)
        if len(payload) > limits.max_memory_bytes:
            raise _memory_invalid("memory_bytes")
        expected = validate_and_finalize(
            "memory-reference",
            expected,
            scope.boundary,
        )
        payload = canonical_bytes(expected)
        existing = _find_host_reference(references, host_memory_id)
        if existing is not None:
            if existing.payload != payload:
                raise _memory_conflict("host_memory_id_reused")
            active.assert_clean()
            lock.assert_owned()
            scope.boundary.assert_clean()
            return cast(dict[str, Any], json.loads(payload))
        if len(references) >= limits.max_memory_references:
            raise _memory_limit(limits.max_memory_references)
        active.assert_clean()
        lock.assert_owned()
        _drop_memory_audits(scope)
        target = _memory_root(scope) / f"{expected['memory_reference_id']}.json"
        _publish_new_file(scope, target, payload, lock)

        confirmed_scope = _fresh_scope(scope, captured_workspace)
        confirmed = _scan_memory_references(confirmed_scope)
        match = _find_host_reference(confirmed, host_memory_id)
        if match is None or match.payload != payload:
            raise _memory_invalid("publication_confirmation")
        confirmed_scope.boundary.assert_clean()
        active.assert_clean()
        lock.assert_owned()
        scope.boundary.assert_clean()
        return cast(dict[str, Any], json.loads(payload))


def _list_memory_references(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> tuple[MemoryReferenceView, ...]:
    captured_workspace = _capture_workspace_root(workspace_root)
    scope = open_persistence_scope(
        data_root,
        schemas,
        namespace=namespace,
        character_id=character_id,
        workspace_root=captured_workspace,
        limits=limits,
    )
    with _audit_failures(scope.boundary):
        references = _scan_memory_references(scope)
        consent_state = _load_consent_state(scope)
        current = None if consent_state is None else consent_state.current.value
        views = tuple(
            MemoryReferenceView(
                payload=snapshot.payload,
                active_consent_generation=_is_active_generation(
                    snapshot.value,
                    current,
                ),
            )
            for snapshot in references
        )
        scope.boundary.assert_clean()
        return views


def _remove_memory_reference(
    data_root: Path,
    character_id: str,
    identifier: str,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    identifier_kind: str,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> MemoryRemovalResult:
    _require_stable_id(identifier, "identifier")
    if identifier_kind not in {"host_memory_id", "memory_reference_id"}:
        raise _memory_invalid("identifier_kind")
    if identifier_kind == "memory_reference_id" and not _MEMORY_ID.fullmatch(
        identifier
    ):
        raise _memory_invalid("memory_reference_id")
    if not isinstance(consent_id, str):
        raise _memory_invalid("consent_id")
    captured_workspace = _capture_workspace_root(workspace_root)
    scope = open_persistence_scope(
        data_root,
        schemas,
        namespace=namespace,
        character_id=character_id,
        workspace_root=captured_workspace,
        limits=limits,
    )
    with _acquire_character_lock(scope) as lock, _audit_failures(
        scope.boundary
    ):
        references = _scan_memory_references(scope)
        consent_state = _load_consent_state(scope)
        if consent_state is None:
            raise _memory_not_found("consent_absent")
        current = consent_state.current.value
        if current["consent_id"] != consent_id:
            raise _memory_conflict("consent_id")
        selected = _select_reference(
            references,
            identifier,
            identifier_kind,
        )
        if selected is None:
            if identifier_kind == "host_memory_id":
                raise _memory_not_found("host_memory_id")
            lock.assert_owned()
            scope.boundary.assert_clean()
            return MemoryRemovalResult(False, None)
        if selected.value["consent_id"] != consent_id:
            raise _memory_conflict("reference_consent")
        lock.assert_owned()
        _drop_memory_audits(scope)
        _unlink_reference(selected, scope, lock)

        confirmed_scope = _fresh_scope(scope, captured_workspace)
        confirmed = _scan_memory_references(confirmed_scope)
        if any(item.path.name == selected.path.name for item in confirmed):
            raise _memory_invalid("removal_confirmation")
        confirmed_scope.boundary.assert_clean()
        lock.assert_owned()
        scope.boundary.assert_clean()
        return MemoryRemovalResult(
            True,
            cast(str, selected.value["memory_reference_id"]),
        )


def _capture_localized_summaries(
    boundary: PersistenceBoundary,
    value: Mapping[str, str],
) -> dict[str, Any]:
    captured = _bounded_mapping(value)
    payload = canonical_bytes(captured)

    def audit() -> None:
        try:
            matches = canonical_bytes(_bounded_mapping(value)) == payload
        except (KokoroError, TypeError, ValueError, UnicodeError):
            matches = False
        if not matches:
            boundary.fail("localized_summaries")

    boundary.audits["input:localized_summaries"] = audit
    return cast(dict[str, Any], json.loads(payload))


def _bounded_mapping(value: Mapping[str, str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _memory_invalid("localized_summaries")
    result: dict[str, Any] = {}
    try:
        for key, item in value.items():
            if len(result) >= 4:
                raise _memory_invalid("localized_summaries")
            result[key] = item
    except KokoroError:
        raise
    except Exception as error:
        raise _memory_invalid("localized_summaries") from error
    return result


def _validate_approved_content(
    summary: str,
    localized: dict[str, Any],
) -> None:
    if not _valid_summary(summary):
        raise _memory_invalid("summary")
    if (
        not localized
        or set(localized) - _LOCALES
        or any(not _valid_summary(value) for value in localized.values())
    ):
        raise _memory_invalid("localized_summaries")


def _valid_summary(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 2_000
        and bool(value.strip())
    )


def _reject_unsafe_memory_content(
    summary: Any,
    localized: dict[str, Any],
) -> None:
    values: list[str] = []
    if isinstance(summary, str):
        values.append(summary)
    for key, value in localized.items():
        if isinstance(key, str):
            values.append(key)
        if isinstance(value, str):
            values.append(value)
    for value in values:
        reason = _unsafe_content_reason(value)
        if reason is not None:
            raise _memory_content_rejected(reason)


def _unsafe_content_reason(value: str) -> str | None:
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        return "control_character"
    detectors = (
        ("credential_assignment", _CREDENTIAL_ASSIGNMENT),
        ("authorization", _AUTHORIZATION),
        ("private_key", _PRIVATE_KEY),
        ("credential_url", _CREDENTIAL_URL),
        ("windows_path", _WINDOWS_PATH),
        ("posix_path", _POSIX_PATH),
        ("file_uri", _FILE_URI),
        ("prompt_log", _PROMPT_LOG),
        ("tool_dump", _TOOL_DUMP),
    )
    for reason, pattern in detectors:
        if pattern.search(value) is not None:
            return reason
    if len(_ROLE_LINE.findall(value)) >= 2:
        return "transcript"
    return None


def _build_reference(
    scope: PersistenceScope,
    active: ActiveConsent,
    host_memory_id: str,
    summary: str,
    localized: dict[str, Any],
) -> dict[str, Any]:
    ordered_localized = {
        locale: localized[locale] for locale in sorted(localized)
    }
    content = {
        "host_memory_id": host_memory_id,
        "summary": summary,
        "localized_summaries": ordered_localized,
    }
    reference_id = _memory_reference_id(scope, host_memory_id)
    binding = active.binding
    consent = active.consent
    return {
        "schema_version": "1.0",
        "artifact_id": _artifact_id(reference_id),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "memory_reference_id": reference_id,
        "source_kind": "host_approved_reference",
        "host_memory_id": host_memory_id,
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "installation_id": binding["installation_id"],
        "namespace": binding["namespace"],
        "character_id": binding["character_id"],
        "character_version": binding["character_version"],
        "archive_sha256": binding["archive_sha256"],
        "compiled_sha256": binding["compiled_sha256"],
        "consent_id": consent["consent_id"],
        "consent_revision": consent["grant_revision"],
        "permission": "memory_references",
        "summary": summary,
        "localized_summaries": ordered_localized,
        "content_hash": sha256(canonical_bytes(content)).hexdigest(),
        "embedded_content": False,
        "canonical_fact_authority": False,
    }


def _scan_memory_references(
    scope: PersistenceScope,
) -> tuple[ArtifactSnapshot, ...]:
    root = _memory_root(scope)
    if _lstat(root) is None:
        scope.boundary.audits[f"absent:{root}"] = _absent_file_audit(root)
        scope.boundary.assert_clean()
        return ()
    snapshots = tuple(
        scan_canonical_directory(
            root,
            entry_limit=scope.limits.max_memory_references,
            aggregate_limit=scope.limits.max_journal_bytes,
            file_limit=scope.limits.max_memory_bytes,
            schema_name="memory-reference",
            boundary=scope.boundary,
        )
    )
    for snapshot in snapshots:
        _require_reference_binding(scope, snapshot)
    return snapshots


def _require_reference_binding(
    scope: PersistenceScope,
    snapshot: ArtifactSnapshot,
) -> None:
    value = snapshot.value
    host_memory_id = cast(str, value["host_memory_id"])
    reference_id = _memory_reference_id(scope, host_memory_id)
    content = {
        "host_memory_id": host_memory_id,
        "summary": value["summary"],
        "localized_summaries": {
            locale: value["localized_summaries"][locale]
            for locale in sorted(value["localized_summaries"])
        },
    }
    expected = {
        "memory_reference_id": reference_id,
        "artifact_id": _artifact_id(reference_id),
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "namespace": scope.key.namespace,
        "character_id": scope.key.character_id,
        "content_hash": sha256(canonical_bytes(content)).hexdigest(),
        "file_name": f"{reference_id}.json",
    }
    actual = {
        "memory_reference_id": value["memory_reference_id"],
        "artifact_id": value["artifact_id"],
        "scope": value["scope"],
        "workspace_id": value["workspace_id"],
        "namespace": value["namespace"],
        "character_id": value["character_id"],
        "content_hash": value["content_hash"],
        "file_name": snapshot.path.name,
    }
    if actual != expected:
        raise _memory_invalid("reference_binding")


def _find_host_reference(
    references: tuple[ArtifactSnapshot, ...],
    host_memory_id: str,
) -> ArtifactSnapshot | None:
    matches = [
        item
        for item in references
        if item.value["host_memory_id"] == host_memory_id
    ]
    if len(matches) > 1:
        raise _memory_invalid("duplicate_host_memory_id")
    return None if not matches else matches[0]


def _select_reference(
    references: tuple[ArtifactSnapshot, ...],
    identifier: str,
    identifier_kind: str,
) -> ArtifactSnapshot | None:
    matches = [
        item
        for item in references
        if item.value[identifier_kind] == identifier
    ]
    if len(matches) > 1:
        raise _memory_invalid("duplicate_identifier")
    return None if not matches else matches[0]


def _is_active_generation(
    reference: dict[str, Any],
    current: dict[str, Any] | None,
) -> bool:
    if (
        current is None
        or current["status"] != "active"
        or "memory_references" not in current["permissions"]
        or reference["consent_id"] != current["consent_id"]
        or reference["consent_revision"] != current["grant_revision"]
    ):
        return False
    binding = current["installation"]
    return all(
        reference[field] == binding[field]
        for field in (
            "installation_id",
            "namespace",
            "character_id",
            "character_version",
            "archive_sha256",
            "compiled_sha256",
        )
    )


def _unlink_reference(
    snapshot: ArtifactSnapshot,
    scope: PersistenceScope,
    lock: PersistenceLock,
) -> None:
    root = _memory_root(scope)
    if snapshot.path.parent != root:
        raise _memory_invalid("reference_path")
    parent_chain = _capture_directory_chain(root)
    captured = _read_regular_file(
        snapshot.path,
        limit=scope.limits.max_memory_bytes,
        optional=False,
    )
    assert captured is not None
    payload, identity = captured
    if payload != snapshot.payload or identity != snapshot.identity:
        raise _memory_invalid("reference_changed")
    current = _require_safe_regular_file(snapshot.path)
    if _file_identity(current) != snapshot.identity:
        raise _memory_invalid("reference_changed")
    lock.assert_owned()
    _assert_directory_chain(parent_chain, "memory_parent_changed")
    try:
        snapshot.path.unlink()
        _fsync_directory(root)
    except OSError as error:
        raise _memory_invalid("remove_failed") from error
    _assert_directory_chain(parent_chain, "memory_parent_changed")
    if _lstat(snapshot.path) is not None:
        raise _memory_invalid("remove_confirmation")
    lock.assert_owned()


def _memory_reference_id(scope: PersistenceScope, host_memory_id: str) -> str:
    identity = {
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "namespace": scope.key.namespace,
        "character_id": scope.key.character_id,
        "host_memory_id": host_memory_id,
    }
    return "memory-" + sha256(canonical_bytes(identity)).hexdigest()[:32]


def _artifact_id(reference_id: str) -> str:
    return f"memory-references/{reference_id}"


def _memory_root(scope: PersistenceScope) -> Path:
    return scope.character_root("memory-references")


def _memory_collection_sha256(
    references: tuple[ArtifactSnapshot, ...],
) -> str:
    return sha256(
        canonical_bytes([reference.value for reference in references])
    ).hexdigest()


def _memory_reset_cleanup_path(
    scope: PersistenceScope,
    reset_id: str,
) -> Path:
    digest = sha256(canonical_bytes(reset_id)).hexdigest()[:32]
    root = _memory_root(scope)
    return root.with_name(f".{scope.key.character_id}.reset-{digest}")


def _cutover_memory_reset(
    scope: PersistenceScope,
    *,
    reset_id: str,
    expected_root_present: bool,
    expected_ids: tuple[str, ...],
    expected_sha256: str,
    expected_directory_identity: Mapping[str, int] | None,
    expected_references: tuple[tuple[str, str], ...],
    lock: PersistenceLock,
) -> Path | None:
    root = _memory_root(scope)
    cleanup = _memory_reset_cleanup_path(scope, reset_id)
    root_present = _lstat(root) is not None
    cleanup_present = _lstat(cleanup) is not None
    if not expected_root_present:
        if (
            root_present
            or cleanup_present
            or expected_directory_identity is not None
            or expected_references
        ):
            raise _memory_reset_stale("memory_membership")
        return None
    if expected_directory_identity is None:
        raise _memory_reset_stale("memory_directory_identity")
    if root_present and cleanup_present:
        raise _memory_reset_stale("memory_cutover_ambiguous")
    if not root_present and not cleanup_present:
        raise _memory_reset_stale("memory_collection_missing")
    if cleanup_present:
        _require_memory_directory_identity(
            cleanup,
            expected_directory_identity,
        )
        _validate_reset_memory_directory(
            scope,
            cleanup,
            expected_ids,
            expected_sha256,
            expected_references=expected_references,
            allow_subset=False,
        )
        try:
            _fsync_directory(root.parent)
        except OSError as error:
            raise _memory_reset_durability_failed() from error
        return cleanup

    _require_memory_directory_identity(root, expected_directory_identity)
    references = _validate_reset_memory_directory(
        scope,
        root,
        expected_ids,
        expected_sha256,
        expected_references=expected_references,
        allow_subset=False,
    )
    identity = _capture_directory_identity(root)
    ancestry = _capture_directory_chain(root.parent)
    lock.assert_owned()
    _assert_directory_chain(ancestry, "memory_parent_changed")
    try:
        _atomic_rename_noreplace(root, cleanup)
    except KokoroError:
        raise
    except OSError as error:
        raise _memory_reset_stale("memory_cutover") from error
    try:
        _fsync_directory(root.parent)
    except OSError as error:
        raise _memory_reset_durability_failed() from error
    renamed = _capture_directory_identity(cleanup)
    if (
        _lstat(root) is not None
        or (
            renamed.device,
            renamed.inode,
            renamed.file_type,
        )
        != (
            identity.device,
            identity.inode,
            identity.file_type,
        )
    ):
        raise _memory_reset_stale("memory_cutover_confirmation")
    _require_memory_directory_identity(cleanup, expected_directory_identity)
    _assert_directory_chain(ancestry, "memory_parent_changed")
    _validate_reset_memory_directory(
        scope,
        cleanup,
        tuple(
            cast(str, reference.value["memory_reference_id"])
            for reference in references
        ),
        expected_sha256,
        expected_references=expected_references,
        allow_subset=False,
    )
    lock.assert_owned()
    return cleanup


def _cleanup_memory_reset(
    scope: PersistenceScope,
    *,
    reset_id: str,
    expected_ids: tuple[str, ...],
    expected_sha256: str,
    expected_directory_identity: Mapping[str, int] | None,
    expected_references: tuple[tuple[str, str], ...],
    lock: PersistenceLock,
) -> None:
    root = _memory_root(scope)
    cleanup = _memory_reset_cleanup_path(scope, reset_id)
    if _lstat(cleanup) is None:
        if _lstat(root) is None:
            try:
                _fsync_directory(cleanup.parent)
            except OSError as error:
                raise _memory_reset_durability_failed() from error
            return
        raise _cleanup_failed(
            "memory_cleanup_missing",
            record_state="unknown",
        )
    if expected_directory_identity is None:
        raise _cleanup_failed(
            "memory_cleanup_identity",
            record_state="unknown",
        )
    _require_memory_directory_identity(
        cleanup,
        expected_directory_identity,
        cleanup=True,
    )
    references = _validate_reset_memory_directory(
        scope,
        cleanup,
        expected_ids,
        expected_sha256,
        expected_references=expected_references,
        allow_subset=True,
    )
    identity = _capture_directory_identity(cleanup)
    ancestry = _capture_directory_chain(cleanup.parent)
    entries = _bounded_cleanup_entries(
        cleanup,
        scope.limits.max_memory_references,
    )
    by_name = {reference.path.name: reference for reference in references}
    try:
        for entry in entries:
            reference = by_name.get(entry.name)
            if reference is None:
                raise _cleanup_failed(
                    "memory_cleanup_membership",
                    record_state="committed",
                )
            linked = _require_safe_regular_file(entry)
            if (
                _file_identity(linked) != reference.identity
                or not _directory_identity_matches(identity)
            ):
                raise _cleanup_failed(
                    "memory_cleanup_identity",
                    record_state="committed",
                )
            lock.assert_owned()
            entry.unlink()
        if not _directory_identity_matches(identity):
            raise _cleanup_failed(
                "memory_cleanup_identity",
                record_state="committed",
            )
        _fsync_directory(cleanup)
        cleanup.rmdir()
        _fsync_directory(cleanup.parent)
    except KokoroError:
        raise
    except OSError as error:
        raise _cleanup_failed(
            "memory_cleanup_io",
            record_state="committed",
        ) from error
    _assert_directory_chain(ancestry, "memory_parent_changed")
    if _lstat(root) is not None or _lstat(cleanup) is not None:
        raise _cleanup_failed(
            "memory_cleanup_confirmation",
            record_state="unknown",
        )
    lock.assert_owned()


def _validate_reset_memory_directory(
    scope: PersistenceScope,
    root: Path,
    expected_ids: tuple[str, ...],
    expected_sha256: str,
    *,
    expected_references: tuple[tuple[str, str], ...],
    allow_subset: bool,
) -> tuple[ArtifactSnapshot, ...]:
    boundary = PersistenceBoundary(scope.boundary.schemas)
    snapshots = tuple(
        scan_canonical_directory(
            root,
            entry_limit=scope.limits.max_memory_references,
            aggregate_limit=scope.limits.max_journal_bytes,
            file_limit=scope.limits.max_memory_bytes,
            schema_name="memory-reference",
            boundary=boundary,
        )
    )
    local_scope = PersistenceScope(
        root=scope.root,
        key=scope.key,
        boundary=boundary,
        limits=scope.limits,
    )
    for snapshot in snapshots:
        _require_reference_binding(local_scope, snapshot)
    actual_ids = tuple(
        cast(str, snapshot.value["memory_reference_id"])
        for snapshot in snapshots
    )
    expected_by_id = dict(expected_references)
    actual_bindings = tuple(
        (
            cast(str, snapshot.value["memory_reference_id"]),
            sha256(snapshot.payload).hexdigest(),
        )
        for snapshot in snapshots
    )
    if allow_subset:
        matches = all(
            expected_by_id.get(reference_id) == payload_sha256
            for reference_id, payload_sha256 in actual_bindings
        )
    else:
        matches = (
            actual_ids == expected_ids
            and actual_bindings == expected_references
            and _memory_collection_sha256(snapshots) == expected_sha256
        )
    if not matches:
        raise _memory_reset_stale("memory_membership")
    boundary.assert_clean()
    return snapshots


def _require_memory_directory_identity(
    path: Path,
    expected: Mapping[str, int],
    *,
    cleanup: bool = False,
) -> None:
    try:
        actual = _capture_directory_identity(path)
    except KokoroError as error:
        if cleanup:
            raise _cleanup_failed(
                "memory_cleanup_identity",
                record_state="unknown",
            ) from error
        raise _memory_reset_stale("memory_directory_identity") from error
    matches = (
        actual.device == expected.get("device")
        and actual.inode == expected.get("inode")
        and actual.file_type == expected.get("file_type")
    )
    if matches:
        return
    if cleanup:
        raise _cleanup_failed(
            "memory_cleanup_identity",
            record_state="unknown",
        )
    raise _memory_reset_stale("memory_directory_identity")


def _memory_reset_stale(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_RESET_STALE",
        "Persistent reset preview is stale.",
        retryable=True,
        details={"reason": reason},
    )


def _memory_reset_durability_failed() -> KokoroError:
    return KokoroError(
        "PERSISTENCE_DURABILITY_FAILED",
        "Persistent memory reset durability could not be confirmed.",
        details={
            "operation": "memory_cutover",
            "reason": "fsync_failed",
            "record_state": "committed",
        },
    )


def _fresh_scope(
    scope: PersistenceScope,
    workspace_root: Path | None,
) -> PersistenceScope:
    return open_persistence_scope(
        scope.root,
        _AuditedSchemas(scope.boundary.schemas, scope.boundary),
        namespace=scope.key.namespace,
        character_id=scope.key.character_id,
        workspace_root=workspace_root,
        limits=scope.limits,
    )


def _drop_memory_audits(scope: PersistenceScope) -> None:
    prefix = str(_memory_root(scope)).casefold()
    for name in tuple(scope.boundary.audits):
        if prefix in name.casefold():
            scope.boundary.audits.pop(name, None)


def _capture_workspace_root(workspace_root: Path | None) -> Path | None:
    return None if workspace_root is None else _absolute_path(workspace_root)


@contextmanager
def _audit_failures(boundary: PersistenceBoundary) -> Iterator[None]:
    try:
        yield
    except BaseException:
        boundary.assert_clean()
        raise


def _require_stable_id(value: Any, reason: str) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or _STABLE_ID.fullmatch(value) is None
    ):
        raise _memory_invalid(reason)


def _require_revision(value: Any) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 10_000
    ):
        raise _memory_invalid("consent_revision")


def _memory_domain(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except KokoroError as error:
        if error.code == "PERSISTENCE_CHANGED":
            raise _memory_invalid("stored_reference") from error
        raise
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        raise _memory_invalid("invalid_input") from error
    except Exception as error:
        raise _memory_invalid("callback_failure") from error


def _memory_invalid(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_MEMORY_INVALID",
        "Persistent memory reference is invalid.",
        details={"reason": reason},
    )


def _memory_content_rejected(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_MEMORY_CONTENT_REJECTED",
        "Persistent memory summary content was rejected.",
        details={"reason": reason},
    )


def _memory_conflict(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_MEMORY_CONFLICT",
        "Persistent memory reference conflicts with retained data.",
        retryable=True,
        details={"reason": reason},
    )


def _memory_not_found(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_MEMORY_NOT_FOUND",
        "Persistent memory reference was not found.",
        details={"reason": reason},
    )


def _memory_limit(limit: int) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_LIMIT_EXCEEDED",
        "Persistent storage limit was exceeded.",
        details={"reason": "memory_references", "limit": limit},
    )


__all__ = [
    "MemoryReferenceView",
    "MemoryRemovalResult",
    "add_memory_reference",
    "list_memory_references",
    "remove_memory_reference",
]
