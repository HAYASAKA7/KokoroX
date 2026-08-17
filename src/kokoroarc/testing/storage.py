"""Immutable, atomic storage for exact Character Pack promotion records."""

from __future__ import annotations

from dataclasses import dataclass
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
from typing import Any, cast

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


_BUNDLE_FILES = frozenset({"promotion.json", "review-attestation.json"})
_MAX_BUNDLE_FILE_BYTES = 1024 * 1024
_MAX_CHARACTERS = 256
_MAX_RECORDS_PER_CHARACTER = 4096
_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_STABLE_ID_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z")
_LOCK_CONTENTION_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "EACCES", None),
        getattr(errno, "EAGAIN", None),
        getattr(errno, "EWOULDBLOCK", None),
        getattr(errno, "EDEADLK", None),
    )
    if value is not None
)
_LOCK_CONTENTION_WINERRORS = frozenset({33, 36})
_RENAME_RETRY_DELAYS = (0.0, 0.001, 0.002, 0.004)
_CLEANUP_RETRY_DELAYS = (0.0, 0.001, 0.002, 0.004)
_TRANSIENT_RENAME_WINERRORS = frozenset({5, 32})
_DIRECTORY_FSYNC_UNSUPPORTED = frozenset(
    value
    for value in (
        getattr(errno, "EINVAL", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "EBADF", None),
    )
    if value is not None
)
_WINDOWS_RESERVED_DEVICE_BASENAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int
    file_type: int


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    path: Path
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True, slots=True)
class _DirectorySnapshot:
    path: Path
    identity: _DirectoryIdentity
    entries: tuple[tuple[str, _FileIdentity], ...]
    limit: int
    limit_reason: str


@dataclass(slots=True)
class _PublicationLock:
    target: Path
    path: Path
    descriptor: int
    ancestor_chain: tuple[_DirectoryIdentity, ...]
    held: bool = True

    def __enter__(self) -> _PublicationLock:
        return self

    def __exit__(self, *_exception: object) -> None:
        self.release()

    def release(self) -> None:
        if not self.held:
            return
        try:
            _unlock_descriptor(self.descriptor)
        finally:
            try:
                os.close(self.descriptor)
            except OSError:
                pass
            finally:
                self.held = False

    def owns(self, target: Path) -> bool:
        if not self.held or target != self.target:
            return False
        try:
            linked = self.path.lstat()
            opened = os.fstat(self.descriptor)
        except OSError:
            lock_matches = False
        else:
            lock_matches = _safe_lock_stats(self.path, linked, opened)
        return lock_matches and _lock_ancestor_chain_matches(self.ancestor_chain)


@dataclass(frozen=True, slots=True)
class _PublishedBundle:
    path: Path
    record: dict[str, Any]
    review: dict[str, Any]
    record_bytes: bytes
    review_bytes: bytes


@dataclass(frozen=True, slots=True)
class _PromotionScan:
    bundles: tuple[_PublishedBundle, ...]
    directory_snapshots: tuple[_DirectorySnapshot, ...]


def publish_promotion_record(
    data_root: Path,
    record: dict[str, Any],
    review_attestation: dict[str, Any],
    schemas: SchemaRegistry,
) -> Path:
    """Atomically append an immutable promotion bundle beneath the reports root."""
    root = _absolute_without_resolution(data_root)
    captured = _capture_inputs(record, review_attestation)
    record_bytes = captured["record"][1]
    review_bytes = captured["review_attestation"][1]
    record_snapshot = cast(dict[str, Any], json.loads(record_bytes))
    review_snapshot = cast(dict[str, Any], json.loads(review_bytes))
    audited_schemas = _AuditedSchemaRegistry(schemas, tuple(captured.values()))
    _validate_input_bundle(
        record_snapshot,
        review_snapshot,
        record_bytes,
        review_bytes,
        audited_schemas,
    )
    _assert_safe_identifier(record_snapshot["character_id"], "character_id")
    _assert_safe_identifier(record_snapshot["promotion_id"], "promotion_id")

    promotions_root = root / "reports" / "promotions"
    character_root = promotions_root / record_snapshot["character_id"]
    final = character_root / record_snapshot["promotion_id"]
    lock_target = promotions_root / "records"

    _validate_existing_chain(root)
    created_promotions = _create_secure_directories(promotions_root)
    _validate_existing_chain(promotions_root)
    with _acquire_publication_lock(lock_target) as publication_lock:
        _fsync_first_publication_directories(
            root,
            promotions_root,
            created_promotions,
        )
        existing_scan = _scan_existing_promotions(promotions_root, audited_schemas)
        existing = list(existing_scan.bundles)
        _require_review_id_available(
            existing,
            record_snapshot,
            record_bytes,
            review_snapshot,
            review_bytes,
        )
        _require_previous_promotion(existing, record_snapshot)
        if not publication_lock.owns(publication_lock.target):
            raise _path_unsafe("publication_lock_changed")

        if _lstat(final) is not None:
            character_chain = _capture_directory_chain(character_root)
            return _confirm_existing_bundle(
                final,
                record_bytes,
                review_bytes,
                audited_schemas,
                publication_lock,
                character_chain,
                captured,
            )

        created_character = _create_secure_directories(character_root)
        _fsync_first_publication_directories(
            promotions_root,
            character_root,
            created_character,
        )
        character_chain = _capture_directory_chain(character_root)
        _assert_publication_boundary(publication_lock, character_chain)
        return _publish_staged_bundle(
            final,
            record_bytes,
            review_bytes,
            audited_schemas,
            publication_lock,
            character_chain,
            captured,
        )


def load_published_promotion_record(
    path: Path,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    """Load and revalidate one complete immutable promotion bundle."""
    candidate = _absolute_without_resolution(path)
    bundle_root = candidate.parent if candidate.name == "promotion.json" else candidate
    try:
        bundle = _load_published_bundle(bundle_root, schemas)
        return cast(dict[str, Any], json.loads(bundle.record_bytes))
    except KokoroError as error:
        if error.code == "PACK_PROMOTION_BUNDLE_INVALID":
            raise
        raise _bundle_invalid("validation") from None
    except (OSError, RuntimeError, ValueError):
        raise _bundle_invalid("path") from None


def _capture_inputs(
    record: dict[str, Any],
    review_attestation: dict[str, Any],
) -> dict[str, tuple[Any, bytes]]:
    captured: dict[str, tuple[Any, bytes]] = {}
    for name, value in (
        ("record", record),
        ("review_attestation", review_attestation),
    ):
        try:
            captured[name] = (value, canonical_bytes(value))
        except KokoroError as error:
            raise KokoroError(
                "PACK_PROMOTION_INPUT_INVALID",
                "A promotion storage input is not canonical JSON data.",
                details={"input": name},
            ) from error
    return captured


def _validate_input_bundle(
    record: dict[str, Any],
    review: dict[str, Any],
    record_bytes: bytes,
    review_bytes: bytes,
    schemas: Any,
) -> None:
    _validate_schema(
        schemas,
        "pack-promotion-record",
        record,
        "PACK_PROMOTION_RECORD_INVALID",
    )
    _validate_schema(
        schemas,
        "pack-review-attestation",
        review,
        "PACK_PROMOTION_REVIEW_INVALID",
    )
    if (
        canonical_bytes(record) != record_bytes
        or canonical_bytes(review) != review_bytes
    ):
        raise KokoroError(
            "PACK_PROMOTION_INPUT_MUTATION",
            "A promotion storage input changed during validation.",
        )
    _validate_bundle_bindings(record, review, review_bytes)


def _validate_schema(
    schemas: Any,
    name: str,
    value: dict[str, Any],
    invalid_code: str,
) -> None:
    try:
        schemas.validate(name, json.loads(canonical_bytes(value)))
    except KokoroError as error:
        if error.code != "SCHEMA_VALIDATION_FAILED":
            raise
        raise KokoroError(
            invalid_code,
            "A promotion storage artifact does not match its closed schema.",
        ) from error


def _validate_bundle_bindings(
    record: dict[str, Any],
    review: dict[str, Any],
    review_bytes: bytes,
) -> None:
    prefix = f"{record['namespace']}/{record['character_id']}"
    identity_fields = (
        "namespace",
        "character_id",
        "character_version",
        "mode",
        "source_artifact_id",
        "source_hash",
    )
    expected_review_reference = {
        "artifact_id": review["artifact_id"],
        "sha256": sha256(review_bytes).hexdigest(),
    }
    if (
        record["artifact_id"]
        != f"{prefix}/release/promotion-{record['to_status']}"
        or review["artifact_id"] != f"{prefix}/release/review"
        or review["decision"] != "accept"
        or record["review_attestation"] != expected_review_reference
        or record["hard_report"] != review["hard_report"]
        or any(record[field] != review[field] for field in identity_fields)
    ):
        raise KokoroError(
            "PACK_PROMOTION_BINDING_MISMATCH",
            "The promotion record does not bind its exact review attestation.",
        )


def _require_review_id_available(
    existing: list[_PublishedBundle],
    record: dict[str, Any],
    record_bytes: bytes,
    review: dict[str, Any],
    review_bytes: bytes,
) -> None:
    matches = [
        bundle
        for bundle in existing
        if bundle.review["review_id"] == review["review_id"]
    ]
    if any(bundle.review_bytes != review_bytes for bundle in matches):
        raise _review_id_conflict(review["review_id"], "different_bytes")
    if any(bundle.record_bytes == record_bytes for bundle in matches):
        return
    if not matches:
        return
    if record["to_status"] == "verified":
        reviewed = [
            bundle for bundle in matches if bundle.record["to_status"] == "reviewed"
        ]
        verified = [
            bundle for bundle in matches if bundle.record["to_status"] == "verified"
        ]
        reference = record["previous_promotion"]
        if (
            len(reviewed) == 1
            and not verified
            and reference is not None
            and reviewed[0].record["artifact_id"] == reference["artifact_id"]
            and sha256(reviewed[0].record_bytes).hexdigest() == reference["sha256"]
        ):
            return
    raise _review_id_conflict(review["review_id"], "transition_reuse")


def _validate_review_history(existing: list[_PublishedBundle]) -> None:
    by_review_id: dict[str, list[_PublishedBundle]] = {}
    for bundle in existing:
        by_review_id.setdefault(bundle.review["review_id"], []).append(bundle)
    for bundles in by_review_id.values():
        if len({bundle.review_bytes for bundle in bundles}) != 1:
            raise _bundle_invalid("review_id_conflict")
        reviewed = [
            bundle for bundle in bundles if bundle.record["to_status"] == "reviewed"
        ]
        verified = [
            bundle for bundle in bundles if bundle.record["to_status"] == "verified"
        ]
        if len(reviewed) != 1 or len(verified) > 1:
            raise _bundle_invalid("review_id_transition_reuse")
        if verified:
            reference = verified[0].record["previous_promotion"]
            if (
                reference is None
                or reviewed[0].record["artifact_id"] != reference["artifact_id"]
                or sha256(reviewed[0].record_bytes).hexdigest()
                != reference["sha256"]
            ):
                raise _bundle_invalid("review_id_transition_binding")


def _require_previous_promotion(
    existing: list[_PublishedBundle],
    record: dict[str, Any],
) -> None:
    if record["to_status"] == "reviewed":
        return
    reference = record["previous_promotion"]
    matches = [
        bundle
        for bundle in existing
        if bundle.record["character_id"] == record["character_id"]
        and bundle.record["artifact_id"] == reference["artifact_id"]
        and sha256(bundle.record_bytes).hexdigest() == reference["sha256"]
    ]
    if len(matches) != 1:
        raise KokoroError(
            "PACK_PROMOTION_PREVIOUS_NOT_PUBLISHED",
            "The exact reviewed promotion has not been published.",
        )
    previous = matches[0].record
    identity_fields = (
        "namespace",
        "character_id",
        "character_version",
        "mode",
        "source_artifact_id",
        "source_hash",
        "compiled_artifact_id",
        "compiled_hash",
        "hard_report",
        "review_attestation",
    )
    if (
        previous["from_status"] != "draft"
        or previous["to_status"] != "reviewed"
        or previous["activation_allowed"] is not False
        or any(previous[field] != record[field] for field in identity_fields)
    ):
        raise KokoroError(
            "PACK_PROMOTION_PREVIOUS_MISMATCH",
            "The verified promotion does not extend the exact reviewed record.",
        )


def _scan_existing_promotions(
    promotions_root: Path,
    schemas: Any,
    *,
    validate_schemas: bool = True,
) -> _PromotionScan:
    try:
        root_snapshot = _capture_directory_snapshot(
            promotions_root,
            _MAX_CHARACTERS + 1,
            "character_count",
        )
    except OSError as error:
        raise _publish_failed("scan_existing", error) from error
    character_entries = [
        promotions_root / name
        for name, _identity in root_snapshot.entries
        if name != ".records.publish.lock"
    ]
    if len(character_entries) > _MAX_CHARACTERS:
        raise _storage_limit("character_count")

    bundles: list[_PublishedBundle] = []
    character_snapshots: list[_DirectorySnapshot] = []
    for character_root in character_entries:
        character_stat = _lstat(character_root)
        if character_stat is None:
            raise _bundle_invalid("entry_changed")
        if character_root.name.startswith("."):
            raise _bundle_invalid("layout")
        _assert_safe_identifier(character_root.name, "character_id")
        _require_safe_directory(character_root, character_stat)
        try:
            character_snapshot = _capture_directory_snapshot(
                character_root,
                _MAX_RECORDS_PER_CHARACTER,
                "record_count",
            )
        except OSError as error:
            raise _publish_failed("scan_existing", error) from error
        character_snapshots.append(character_snapshot)
        visible_entries = [
            character_root / name
            for name, _identity in character_snapshot.entries
            if not (name.startswith(".") and ".staging-" in name)
        ]
        for bundle_root in visible_entries:
            _assert_safe_identifier(bundle_root.name, "promotion_id")
            bundle = _load_published_bundle(
                bundle_root,
                schemas,
                validate_schemas=validate_schemas,
            )
            if (
                bundle.record["character_id"] != character_root.name
                or bundle.record["promotion_id"] != bundle_root.name
            ):
                raise _bundle_invalid("path_binding")
            bundles.append(bundle)

    _validate_review_history(bundles)
    result = _PromotionScan(
        bundles=tuple(bundles),
        directory_snapshots=(*character_snapshots, root_snapshot),
    )
    _assert_promotion_scan_stable(result)
    return result


def _assert_promotion_scan_stable(scan: _PromotionScan) -> None:
    if any(
        not _directory_snapshot_matches(snapshot)
        for snapshot in scan.directory_snapshots
    ):
        raise _bundle_invalid("directory_changed")


def _load_published_bundle(
    path: Path,
    schemas: Any,
    *,
    validate_schemas: bool = True,
) -> _PublishedBundle:
    try:
        _validate_existing_chain(path)
        ancestor_chain = _capture_directory_chain(path)
        initial_snapshot = _capture_directory_snapshot(
            path,
            len(_BUNDLE_FILES),
            "bundle_entry_count",
        )
        entries = [name for name, _identity in initial_snapshot.entries]
        if entries != sorted(_BUNDLE_FILES):
            raise _bundle_invalid("layout")
        initial_files = dict(initial_snapshot.entries)
        for name in _BUNDLE_FILES:
            _require_safe_regular_file(path / name)
        record_bytes, record_identity = _read_regular_bytes(
            path / "promotion.json",
            _MAX_BUNDLE_FILE_BYTES,
            "bundle",
        )
        review_bytes, review_identity = _read_regular_bytes(
            path / "review-attestation.json",
            _MAX_BUNDLE_FILE_BYTES,
            "bundle",
        )
        if (
            record_identity != initial_files["promotion.json"]
            or review_identity != initial_files["review-attestation.json"]
        ):
            raise _bundle_invalid("file_changed")
        record = _parse_canonical_document(record_bytes)
        review = _parse_canonical_document(review_bytes)
        if validate_schemas:
            _validate_schema(
                schemas,
                "pack-promotion-record",
                record,
                "PACK_PROMOTION_BUNDLE_INVALID",
            )
            _validate_schema(
                schemas,
                "pack-review-attestation",
                review,
                "PACK_PROMOTION_BUNDLE_INVALID",
            )
        _validate_loaded_bindings(record, review, review_bytes[:-1])
        _validate_existing_chain(path)
        final_snapshot = _capture_directory_snapshot(
            path,
            len(_BUNDLE_FILES),
            "bundle_entry_count",
        )
        if (
            not _directory_chain_matches(ancestor_chain)
            or final_snapshot != initial_snapshot
        ):
            raise _bundle_invalid("bundle_changed")
        return _PublishedBundle(
            path=path,
            record=record,
            review=review,
            record_bytes=record_bytes[:-1],
            review_bytes=review_bytes[:-1],
        )
    except KokoroError as error:
        if error.code == "PACK_PROMOTION_STORAGE_LIMIT":
            raise _bundle_invalid("layout") from None
        raise
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        raise _bundle_invalid("read") from None


def _validate_loaded_bindings(
    record: dict[str, Any],
    review: dict[str, Any],
    review_bytes: bytes,
) -> None:
    try:
        _validate_bundle_bindings(record, review, review_bytes)
    except KokoroError as error:
        if error.code == "PACK_PROMOTION_BINDING_MISMATCH":
            raise _bundle_invalid("binding") from None
        raise


def _require_exact_existing_bundle(
    final: Path,
    record_bytes: bytes,
    review_bytes: bytes,
    schemas: Any,
    *,
    validate_schemas: bool = True,
) -> None:
    try:
        existing = _load_published_bundle(
            final,
            schemas,
            validate_schemas=validate_schemas,
        )
    except KokoroError as error:
        if error.code == "PACK_PROMOTION_INPUT_MUTATION":
            raise
        raise KokoroError(
            "PACK_PROMOTION_CONFLICT",
            "The promotion ID already names a different or invalid record.",
            details={"promotion_id": final.name},
        ) from error
    if existing.record_bytes != record_bytes or existing.review_bytes != review_bytes:
        raise KokoroError(
            "PACK_PROMOTION_CONFLICT",
            "The promotion ID is already bound to different bytes.",
            details={"promotion_id": final.name},
        )


def _confirm_existing_bundle(
    final: Path,
    record_bytes: bytes,
    review_bytes: bytes,
    schemas: Any,
    publication_lock: _PublicationLock,
    character_chain: tuple[_DirectoryIdentity, ...],
    captured: dict[str, tuple[Any, bytes]],
    *,
    validate_schemas: bool = True,
) -> Path:
    _assert_publication_boundary(publication_lock, character_chain)
    _require_exact_existing_bundle(
        final,
        record_bytes,
        review_bytes,
        schemas,
        validate_schemas=validate_schemas,
    )
    _assert_inputs_unchanged(captured)
    _assert_publication_boundary(publication_lock, character_chain)
    try:
        _fsync_directory(final.parent)
    except (KokoroError, OSError) as error:
        raise KokoroError(
            "PACK_PROMOTION_DURABILITY_FAILED",
            "The complete promotion record could not be confirmed durable.",
            details={
                "operation": "fsync_parent",
                "reason": _error_reason(error),
                "record_state": "complete_visible",
            },
        ) from error
    _assert_publication_boundary(publication_lock, character_chain)
    latest_scan = _scan_existing_promotions(
        final.parent.parent,
        schemas,
        validate_schemas=validate_schemas,
    )
    matches = [bundle for bundle in latest_scan.bundles if bundle.path == final]
    if (
        len(matches) != 1
        or matches[0].record_bytes != record_bytes
        or matches[0].review_bytes != review_bytes
    ):
        raise KokoroError(
            "PACK_PROMOTION_CONFLICT",
            "The promotion ID is no longer bound to the exact published bytes.",
            details={"promotion_id": final.name},
        )
    _assert_inputs_unchanged(captured)
    _assert_publication_boundary(publication_lock, character_chain)
    _assert_promotion_scan_stable(latest_scan)
    return final / "promotion.json"


def _publish_staged_bundle(
    final: Path,
    record_bytes: bytes,
    review_bytes: bytes,
    schemas: Any,
    publication_lock: _PublicationLock,
    character_chain: tuple[_DirectoryIdentity, ...],
    captured: dict[str, tuple[Any, bytes]],
) -> Path:
    staging: Path | None = None
    staging_identity: _DirectoryIdentity | None = None
    try:
        try:
            staging = _create_staging(final)
        except OSError as error:
            raise _publish_failed("create_staging", error) from error
        staging_prefix = f".{final.name}.staging-"
        if staging.parent != final.parent:
            raise _path_unsafe("staging_parent_changed")
        if not staging.name.startswith(staging_prefix) or len(staging.name) == len(
            staging_prefix
        ):
            raise _path_unsafe("staging_name_changed")
        try:
            staging_identity = _capture_directory_identity(staging)
        except (KokoroError, OSError) as error:
            raise _cleanup_failed("staging_identity_unavailable") from error
        _assert_inputs_unchanged(captured)
        _assert_publication_boundary(publication_lock, character_chain)
        _validate_existing_chain(staging)
        _assert_staging_boundary(staging, staging_identity, character_chain)
        _write_canonical_file(
            staging / "promotion.json",
            json.loads(record_bytes),
            parent_identity=staging_identity,
            ancestor_chain=character_chain,
        )
        _assert_inputs_unchanged(captured)
        _assert_publication_boundary(publication_lock, character_chain)
        _assert_staging_boundary(staging, staging_identity, character_chain)
        _write_canonical_file(
            staging / "review-attestation.json",
            json.loads(review_bytes),
            parent_identity=staging_identity,
            ancestor_chain=character_chain,
        )
        _assert_inputs_unchanged(captured)
        _assert_publication_boundary(publication_lock, character_chain)
        _assert_staging_boundary(staging, staging_identity, character_chain)
        identities = _verify_staged_bundle(
            staging,
            record_bytes,
            review_bytes,
            schemas,
            expected_directory=staging_identity,
        )
        _assert_inputs_unchanged(captured)
        _assert_publication_boundary(publication_lock, character_chain)
        _assert_staging_boundary(staging, staging_identity, character_chain)
        try:
            _fsync_directory(staging)
        except (KokoroError, OSError) as error:
            raise _operation_failure("fsync_staging", error) from error
        _assert_inputs_unchanged(captured)
        _assert_publication_boundary(publication_lock, character_chain)
        _assert_staging_boundary(staging, staging_identity, character_chain)
        _verify_staged_bundle(
            staging,
            record_bytes,
            review_bytes,
            schemas,
            expected_identities=identities,
            expected_directory=staging_identity,
        )
        _assert_inputs_unchanged(captured)
        _assert_publication_boundary(publication_lock, character_chain)
        _assert_staging_boundary(staging, staging_identity, character_chain)
        record_snapshot = cast(dict[str, Any], json.loads(record_bytes))
        review_snapshot = cast(dict[str, Any], json.loads(review_bytes))
        latest_scan = _scan_existing_promotions(final.parent.parent, schemas)
        latest = list(latest_scan.bundles)
        _require_review_id_available(
            latest,
            record_snapshot,
            record_bytes,
            review_snapshot,
            review_bytes,
        )
        _require_previous_promotion(latest, record_snapshot)
        _assert_inputs_unchanged(captured)
        _assert_publication_boundary(publication_lock, character_chain)
        _assert_staging_boundary(staging, staging_identity, character_chain)
        _verify_staged_bundle(
            staging,
            record_bytes,
            review_bytes,
            schemas,
            expected_identities=identities,
            expected_directory=staging_identity,
            validate_schemas=False,
        )
        _assert_inputs_unchanged(captured)
        _assert_publication_boundary(publication_lock, character_chain)
        _assert_staging_boundary(staging, staging_identity, character_chain)
        _assert_promotion_scan_stable(latest_scan)
        if _lstat(final) is not None:
            return _confirm_existing_bundle(
                final,
                record_bytes,
                review_bytes,
                schemas,
                publication_lock,
                character_chain,
                captured,
            )
        try:
            _rename_staging(
                staging,
                final,
                staging_identity,
                character_chain,
            )
        except OSError as error:
            if _lstat(final) is not None:
                return _confirm_existing_bundle(
                    final,
                    record_bytes,
                    review_bytes,
                    schemas,
                    publication_lock,
                    character_chain,
                    captured,
                )
            raise _publish_failed("cutover", error) from error
        staging = None
        return _confirm_existing_bundle(
            final,
            record_bytes,
            review_bytes,
            schemas,
            publication_lock,
            character_chain,
            captured,
            validate_schemas=False,
        )
    except KokoroError:
        raise
    except OSError as error:
        raise _publish_failed("write", error) from error
    finally:
        if staging is not None and staging_identity is not None:
            _remove_staging(staging, staging_identity, character_chain)


def _create_staging(final: Path) -> Path:
    return Path(tempfile.mkdtemp(prefix=f".{final.name}.staging-", dir=final.parent))


def _verify_staged_bundle(
    staging: Path,
    record_bytes: bytes,
    review_bytes: bytes,
    schemas: Any,
    *,
    expected_identities: dict[str, _FileIdentity] | None = None,
    expected_directory: _DirectoryIdentity | None = None,
    validate_schemas: bool = True,
) -> dict[str, _FileIdentity]:
    try:
        initial_snapshot = _capture_directory_snapshot(
            staging,
            len(_BUNDLE_FILES),
            "staging_entry_count",
        )
        if (
            expected_directory is not None
            and initial_snapshot.identity != expected_directory
        ):
            raise _staging_invalid("directory_identity")
        if [name for name, _identity in initial_snapshot.entries] != sorted(
            _BUNDLE_FILES
        ):
            raise _staging_invalid("layout")
        payloads: dict[str, bytes] = {}
        identities: dict[str, _FileIdentity] = {}
        for name, expected in (
            ("promotion.json", record_bytes + b"\n"),
            ("review-attestation.json", review_bytes + b"\n"),
        ):
            payload, identity = _read_regular_bytes(
                staging / name,
                _MAX_BUNDLE_FILE_BYTES,
                "staging",
            )
            if payload != expected:
                raise _staging_invalid("content")
            if (
                expected_identities is not None
                and expected_identities.get(name) != identity
            ):
                raise _staging_invalid("file_identity")
            payloads[name] = payload
            identities[name] = identity
        record = _parse_canonical_document(payloads["promotion.json"])
        review = _parse_canonical_document(payloads["review-attestation.json"])
        if validate_schemas:
            _validate_schema(
                schemas,
                "pack-promotion-record",
                record,
                "PACK_PROMOTION_STAGING_INVALID",
            )
            _validate_schema(
                schemas,
                "pack-review-attestation",
                review,
                "PACK_PROMOTION_STAGING_INVALID",
            )
        try:
            _validate_bundle_bindings(record, review, review_bytes)
        except KokoroError as error:
            if error.code == "PACK_PROMOTION_BINDING_MISMATCH":
                raise _staging_invalid("binding") from None
            raise
        final_snapshot = _capture_directory_snapshot(
            staging,
            len(_BUNDLE_FILES),
            "staging_entry_count",
        )
        if final_snapshot != initial_snapshot:
            raise _staging_invalid("directory_changed")
        return identities
    except KokoroError as error:
        if error.code == "PACK_PROMOTION_STORAGE_LIMIT":
            raise _staging_invalid("layout") from None
        if error.code == "PACK_PROMOTION_BUNDLE_INVALID":
            raise _staging_invalid("directory_changed") from None
        raise
    except (OSError, RuntimeError, ValueError):
        raise _staging_invalid("read") from None


def _write_canonical_file(
    path: Path,
    value: Any,
    *,
    parent_identity: _DirectoryIdentity | None = None,
    ancestor_chain: tuple[_DirectoryIdentity, ...] = (),
) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOINHERIT", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_descriptor: int | None = None
    if parent_identity is not None:
        if (
            path.parent != parent_identity.path
            or not _directory_identity_matches(parent_identity)
            or not _directory_chain_matches(ancestor_chain)
        ):
            raise _path_unsafe("staging_directory_changed")
    if parent_identity is not None and os.name != "nt":
        if os.open not in os.supports_dir_fd:
            raise OSError(errno.ENOTSUP, "directory-relative open is unavailable")
        parent_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        parent_descriptor = os.open(path.parent, parent_flags)
        opened_parent = os.fstat(parent_descriptor)
        if (
            opened_parent.st_dev != parent_identity.device
            or opened_parent.st_ino != parent_identity.inode
            or stat.S_IFMT(opened_parent.st_mode) != parent_identity.file_type
        ):
            os.close(parent_descriptor)
            raise _path_unsafe("staging_directory_changed")
        descriptor = os.open(
            path.name,
            flags,
            0o600,
            dir_fd=parent_descriptor,
        )
    else:
        descriptor = os.open(path, flags, 0o600)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise _path_unsafe("staging_file_changed")
        payload = canonical_bytes(value) + b"\n"
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written < 1:
                raise OSError(errno.EIO, "promotion metadata write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    if parent_identity is not None and (
        not _directory_identity_matches(parent_identity)
        or not _directory_chain_matches(ancestor_chain)
    ):
        raise _path_unsafe("staging_directory_changed")


def _read_regular_bytes(
    path: Path,
    limit: int,
    context: str,
) -> tuple[bytes, _FileIdentity]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOINHERIT", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        initial = _require_safe_regular_file(path)
        identity = _file_identity(initial)
        if identity.size > limit:
            raise _read_error(context, "file_size")
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                _file_identity(opened) != identity
                or opened.st_nlink != 1
                or not os.path.samestat(initial, opened)
            ):
                raise _read_error(context, "file_identity")
            chunks: list[bytes] = []
            remaining = limit + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if remaining == 0:
                raise _read_error(context, "file_size")
            final_opened = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        final = _require_safe_regular_file(path)
        if (
            _file_identity(final_opened) != identity
            or _file_identity(final) != identity
            or not os.path.samestat(initial, final_opened)
            or not os.path.samestat(initial, final)
        ):
            raise _read_error(context, "file_identity")
        return b"".join(chunks), identity
    except KokoroError:
        raise
    except OSError:
        raise _read_error(context, "read") from None


def _parse_canonical_document(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(value, dict) or payload != canonical_bytes(value) + b"\n":
            raise ValueError("not canonical JSON")
        return value
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, KokoroError):
        raise _bundle_invalid("canonical_json") from None


def _unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in items:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = member
    return value


def _assert_inputs_unchanged(
    captured: dict[str, tuple[Any, bytes]],
) -> None:
    if any(
        not _canonical_matches(value, payload)
        for value, payload in captured.values()
    ):
        raise KokoroError(
            "PACK_PROMOTION_INPUT_MUTATION",
            "A caller-owned promotion storage input changed during publication.",
        )


def _canonical_matches(value: Any, expected: bytes) -> bool:
    try:
        return canonical_bytes(value) == expected
    except KokoroError:
        return False


class _AuditedSchemaRegistry:
    def __init__(
        self,
        delegate: SchemaRegistry,
        captured: tuple[tuple[Any, bytes], ...],
    ) -> None:
        self._delegate = delegate
        self._captured = captured

    def validate(self, name: str, instance: Any) -> None:
        try:
            self._delegate.validate(name, instance)
        finally:
            if any(
                not _canonical_matches(value, payload)
                for value, payload in self._captured
            ):
                raise KokoroError(
                    "PACK_PROMOTION_INPUT_MUTATION",
                    "A caller-owned promotion storage input changed during validation.",
                )


def _absolute_without_resolution(path: Path) -> Path:
    try:
        return Path(os.path.abspath(path))
    except (OSError, RuntimeError, ValueError) as error:
        raise _path_unsafe("path_cannot_be_canonicalized") from error


def _bounded_entries(
    path: Path,
    limit: int,
    limit_reason: str,
) -> tuple[Path, ...]:
    entries: list[Path] = []
    with os.scandir(path) as iterator:
        for entry in iterator:
            entries.append(path / entry.name)
            if len(entries) > limit:
                raise _storage_limit(limit_reason)
    return tuple(sorted(entries, key=lambda entry: entry.name))


def _capture_directory_identity(path: Path) -> _DirectoryIdentity:
    path_stat = _require_safe_directory(path)
    return _DirectoryIdentity(
        path=path,
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        file_type=stat.S_IFMT(path_stat.st_mode),
    )


def _capture_directory_chain(path: Path) -> tuple[_DirectoryIdentity, ...]:
    identities: list[_DirectoryIdentity] = []
    try:
        for component in reversed((path, *path.parents)):
            identities.append(_capture_directory_identity(component))
    except KokoroError:
        raise
    except OSError as error:
        raise _publish_failed("inspect_directory_ancestor", error) from error
    return tuple(identities)


def _directory_identity_matches(identity: _DirectoryIdentity) -> bool:
    try:
        current = identity.path.lstat()
    except OSError:
        return False
    return (
        not _is_redirect(identity.path, current)
        and stat.S_ISDIR(current.st_mode)
        and current.st_dev == identity.device
        and current.st_ino == identity.inode
        and stat.S_IFMT(current.st_mode) == identity.file_type
    )


def _directory_chain_matches(
    identities: tuple[_DirectoryIdentity, ...],
) -> bool:
    return all(_directory_identity_matches(identity) for identity in identities)


def _capture_directory_snapshot(
    path: Path,
    limit: int,
    limit_reason: str,
) -> _DirectorySnapshot:
    identity = _capture_directory_identity(path)
    entries = _snapshot_entries(path, limit, limit_reason)
    confirmed_entries = _snapshot_entries(path, limit, limit_reason)
    if entries != confirmed_entries or not _directory_identity_matches(identity):
        raise _bundle_invalid("directory_changed")
    return _DirectorySnapshot(
        path=path,
        identity=identity,
        entries=entries,
        limit=limit,
        limit_reason=limit_reason,
    )


def _snapshot_entries(
    path: Path,
    limit: int,
    limit_reason: str,
) -> tuple[tuple[str, _FileIdentity], ...]:
    snapshots: list[tuple[str, _FileIdentity]] = []
    for entry in _bounded_entries(path, limit, limit_reason):
        try:
            entry_stat = entry.lstat()
        except FileNotFoundError:
            raise _bundle_invalid("entry_changed") from None
        snapshots.append((entry.name, _file_identity(entry_stat)))
    return tuple(snapshots)


def _directory_snapshot_matches(snapshot: _DirectorySnapshot) -> bool:
    current = _capture_directory_snapshot(
        snapshot.path,
        snapshot.limit,
        snapshot.limit_reason,
    )
    return current == snapshot


def _assert_publication_boundary(
    publication_lock: _PublicationLock,
    character_chain: tuple[_DirectoryIdentity, ...],
) -> None:
    if not publication_lock.owns(publication_lock.target):
        raise _path_unsafe("publication_lock_changed")
    if not _directory_chain_matches(character_chain):
        raise _path_unsafe("character_directory_changed")


def _assert_staging_boundary(
    staging: Path,
    staging_identity: _DirectoryIdentity,
    character_chain: tuple[_DirectoryIdentity, ...],
) -> None:
    if (
        not character_chain
        or staging.parent != character_chain[-1].path
        or not _directory_chain_matches(character_chain)
        or not _directory_identity_matches(staging_identity)
    ):
        raise _path_unsafe("staging_directory_changed")


def _assert_safe_identifier(value: Any, field: str) -> None:
    pattern = _SLUG_PATTERN if field == "character_id" else _STABLE_ID_PATTERN
    if (
        not isinstance(value, str)
        or pattern.fullmatch(value) is None
        or _reserved_device_name(value)
    ):
        raise _path_unsafe(f"unsafe_{field}")


def _reserved_device_name(value: str) -> bool:
    return value.split(".", 1)[0].lower() in _WINDOWS_RESERVED_DEVICE_BASENAMES


def _validate_existing_chain(path: Path) -> None:
    for component in reversed((path, *path.parents)):
        component_stat = _lstat(component)
        if component_stat is None:
            continue
        _require_safe_directory(component, component_stat)


def _create_secure_directories(path: Path) -> tuple[Path, ...]:
    created: list[Path] = []
    for component in reversed((path, *path.parents)):
        component_stat = _lstat(component)
        if component_stat is not None:
            _require_safe_directory(component, component_stat)
            continue
        try:
            component.mkdir()
            created.append(component)
        except FileExistsError:
            pass
        except OSError as error:
            raise _publish_failed("mkdir", error) from error
        _require_safe_directory(component)
    return tuple(created)


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _publish_failed("inspect_destination", error) from error


def _require_safe_directory(
    path: Path,
    path_stat: os.stat_result | None = None,
) -> os.stat_result:
    try:
        current = path.lstat() if path_stat is None else path_stat
    except OSError as error:
        raise _publish_failed("inspect_destination", error) from error
    if _is_redirect(path, current) or not stat.S_ISDIR(current.st_mode):
        raise _path_unsafe("unsafe_directory")
    return current


def _require_safe_regular_file(path: Path) -> os.stat_result:
    try:
        current = path.lstat()
    except OSError as error:
        raise _bundle_invalid("missing_file") from error
    if (
        _is_redirect(path, current)
        or not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
    ):
        raise _bundle_invalid("unsafe_file")
    return current


def _is_redirect(path: Path, path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    is_junction = getattr(path, "is_junction", None)
    try:
        junction = bool(is_junction()) if is_junction is not None else False
    except OSError:
        return True
    return (
        stat.S_ISLNK(path_stat.st_mode)
        or junction
        or bool(attributes & reparse_flag)
    )


def _file_identity(path_stat: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        size=path_stat.st_size,
        modified_ns=path_stat.st_mtime_ns,
        file_type=stat.S_IFMT(path_stat.st_mode),
    )


def _acquire_publication_lock(target: Path) -> _PublicationLock:
    path = target.parent / f".{target.name}.publish.lock"
    ancestor_chain = _capture_lock_ancestor_chain(target.parent)
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOINHERIT", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        linked = path.lstat()
        opened = os.fstat(descriptor)
        if not _safe_lock_stats(path, linked, opened):
            raise _path_unsafe("publication_lock")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        if os.name == "nt" and opened.st_size < 1:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.write(descriptor, b"\0") != 1:
                raise OSError(errno.EIO, "publication lock initialization failed")
            os.fsync(descriptor)
        try:
            _lock_descriptor(descriptor)
        except OSError as error:
            if _is_lock_contention(error):
                raise _publication_busy() from error
            raise
        linked = path.lstat()
        opened = os.fstat(descriptor)
        if (
            not _safe_lock_stats(path, linked, opened)
            or not _lock_ancestor_chain_matches(ancestor_chain)
        ):
            raise _path_unsafe("publication_lock_changed")
        lock = _PublicationLock(target, path, descriptor, ancestor_chain)
        descriptor = None
        return lock
    except KokoroError:
        raise
    except OSError as error:
        raise _publish_failed("lock", error) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _safe_lock_stats(
    path: Path,
    linked: os.stat_result,
    opened: os.stat_result,
) -> bool:
    return (
        not _is_redirect(path, linked)
        and stat.S_ISREG(linked.st_mode)
        and stat.S_ISREG(opened.st_mode)
        and linked.st_nlink == 1
        and opened.st_nlink == 1
        and os.path.samestat(linked, opened)
    )


def _capture_lock_ancestor_chain(path: Path) -> tuple[_DirectoryIdentity, ...]:
    identities: list[_DirectoryIdentity] = []
    try:
        for component in reversed((path, *path.parents)):
            component_stat = component.lstat()
            if _is_redirect(component, component_stat) or not stat.S_ISDIR(
                component_stat.st_mode
            ):
                raise _path_unsafe("publication_lock_ancestor")
            identities.append(
                _DirectoryIdentity(
                    path=component,
                    device=component_stat.st_dev,
                    inode=component_stat.st_ino,
                    file_type=stat.S_IFMT(component_stat.st_mode),
                )
            )
    except KokoroError:
        raise
    except OSError as error:
        raise _publish_failed("inspect_lock_ancestor", error) from error
    return tuple(identities)


def _lock_ancestor_chain_matches(
    identities: tuple[_DirectoryIdentity, ...],
) -> bool:
    matches = True
    for identity in identities:
        try:
            current = identity.path.lstat()
        except OSError:
            matches = False
            continue
        if (
            _is_redirect(identity.path, current)
            or not stat.S_ISDIR(current.st_mode)
            or current.st_dev != identity.device
            or current.st_ino != identity.inode
            or stat.S_IFMT(current.st_mode) != identity.file_type
        ):
            matches = False
    return matches


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_descriptor(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        pass


def _is_lock_contention(error: OSError) -> bool:
    return (
        error.errno in _LOCK_CONTENTION_ERRNOS
        or getattr(error, "winerror", None) in _LOCK_CONTENTION_WINERRORS
    )


def _rename_staging(
    staging: Path,
    final: Path,
    staging_identity: _DirectoryIdentity | None = None,
    character_chain: tuple[_DirectoryIdentity, ...] = (),
) -> None:
    attempts = len(_RENAME_RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            _atomic_rename_noreplace(
                staging,
                final,
                staging_identity,
                character_chain,
            )
            return
        except PermissionError as error:
            if (
                os.name != "nt"
                or getattr(error, "winerror", None) not in _TRANSIENT_RENAME_WINERRORS
                or attempt == attempts - 1
            ):
                raise
            time.sleep(_RENAME_RETRY_DELAYS[attempt])


def _atomic_rename_noreplace(
    staging: Path,
    final: Path,
    staging_identity: _DirectoryIdentity | None = None,
    character_chain: tuple[_DirectoryIdentity, ...] = (),
) -> None:
    if staging.parent != final.parent:
        raise OSError(errno.EXDEV, "atomic cutover requires one parent directory")
    if staging_identity is not None and (
        staging != staging_identity.path
        or not _directory_identity_matches(staging_identity)
        or not _directory_chain_matches(character_chain)
    ):
        raise _path_unsafe("staging_directory_changed")
    if os.name == "nt":
        os.rename(staging, final)
        return

    import ctypes

    source = os.fsencode(staging.name)
    destination = os.fsencode(final.name)
    library = ctypes.CDLL(None, use_errno=True)
    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_descriptor = os.open(staging.parent, parent_flags)
    try:
        if staging_identity is not None:
            opened_parent = os.fstat(parent_descriptor)
            expected_parent = character_chain[-1]
            if (
                opened_parent.st_dev != expected_parent.device
                or opened_parent.st_ino != expected_parent.inode
                or stat.S_IFMT(opened_parent.st_mode) != expected_parent.file_type
            ):
                raise _path_unsafe("character_directory_changed")
        if sys.platform.startswith("linux"):
            renameat2 = getattr(library, "renameat2", None)
            if renameat2 is None:
                raise OSError(
                    errno.ENOTSUP,
                    "atomic no-replace rename is unavailable",
                )
            renameat2.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            renameat2.restype = ctypes.c_int
            result = renameat2(
                parent_descriptor,
                source,
                parent_descriptor,
                destination,
                1,
            )
        elif sys.platform == "darwin":
            renameatx_np = getattr(library, "renameatx_np", None)
            if renameatx_np is None:
                raise OSError(
                    errno.ENOTSUP,
                    "atomic no-replace rename is unavailable",
                )
            renameatx_np.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            renameatx_np.restype = ctypes.c_int
            result = renameatx_np(
                parent_descriptor,
                source,
                parent_descriptor,
                destination,
                0x00000004,
            )
        else:
            raise OSError(
                errno.ENOTSUP,
                "atomic no-replace rename is unavailable",
            )
    finally:
        os.close(parent_descriptor)
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number), final)
    raise OSError(error_number, os.strerror(error_number), final)


def _fsync_first_publication_directories(
    root: Path,
    target: Path,
    created: tuple[Path, ...],
) -> None:
    directories = [root]
    current = root
    for part in target.relative_to(root).parts:
        current /= part
        directories.append(current)
    allowed = set(directories)
    if any(path not in allowed for path in created):
        raise _path_unsafe("created_directory_escaped")
    for directory in directories:
        _fsync_directory(directory)
        _fsync_directory(directory.parent)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        if error.errno not in _DIRECTORY_FSYNC_UNSUPPORTED:
            raise _publish_failed("fsync_directory", error) from error


def _remove_staging(
    staging: Path,
    expected_identity: _DirectoryIdentity,
    character_chain: tuple[_DirectoryIdentity, ...],
) -> None:
    last_error: OSError | None = None
    for attempt in range(len(_CLEANUP_RETRY_DELAYS) + 1):
        if (
            staging.parent != character_chain[-1].path
            or not _directory_chain_matches(character_chain)
            or not _directory_identity_matches(expected_identity)
        ):
            raise _cleanup_failed("staging_identity_changed")
        try:
            _remove_entry_no_follow(staging, expected_identity)
            return
        except FileNotFoundError:
            return
        except KokoroError:
            raise
        except OSError as error:
            last_error = error
            if attempt == len(_CLEANUP_RETRY_DELAYS):
                break
            time.sleep(_CLEANUP_RETRY_DELAYS[attempt])
    assert last_error is not None
    raise _cleanup_failed(_error_reason(last_error)) from last_error


def _remove_entry_no_follow(
    path: Path,
    expected_identity: _DirectoryIdentity,
) -> None:
    if not _directory_identity_matches(expected_identity):
        raise _cleanup_failed("staging_identity_changed")
    try:
        children = _bounded_entries(
            path,
            len(_BUNDLE_FILES),
            "staging_cleanup_entry_count",
        )
    except KokoroError as error:
        if error.code == "PACK_PROMOTION_STORAGE_LIMIT":
            raise _cleanup_failed("unexpected_layout") from None
        raise
    for child in children:
        if child.name not in _BUNDLE_FILES:
            raise _cleanup_failed("unexpected_layout")
        child_stat = child.lstat()
        if (
            _is_redirect(child, child_stat)
            or not stat.S_ISREG(child_stat.st_mode)
            or child_stat.st_nlink != 1
        ):
            raise _cleanup_failed("unsafe_entry")
        if not _directory_identity_matches(expected_identity):
            raise _cleanup_failed("staging_identity_changed")
        child.unlink()
    if not _directory_identity_matches(expected_identity):
        raise _cleanup_failed("staging_identity_changed")
    path.rmdir()


def _error_reason(error: BaseException) -> str:
    if isinstance(error, KokoroError):
        return str(error.details.get("reason", error.code))
    return type(error).__name__


def _operation_failure(operation: str, error: BaseException) -> KokoroError:
    return KokoroError(
        "PACK_PROMOTION_PUBLISH_FAILED",
        "Promotion record publication failed.",
        details={"operation": operation, "reason": _error_reason(error)},
    )


def _publish_failed(operation: str, error: OSError) -> KokoroError:
    return _operation_failure(operation, error)


def _publication_busy() -> KokoroError:
    return KokoroError(
        "PACK_PROMOTION_BUSY",
        "Another promotion publication is already in progress.",
        retryable=True,
        details={"reason": "reports_locked"},
    )


def _path_unsafe(reason: str) -> KokoroError:
    return KokoroError(
        "PACK_PROMOTION_PATH_UNSAFE",
        "The promotion destination contains an unsafe filesystem path.",
        details={"reason": reason},
    )


def _bundle_invalid(reason: str) -> KokoroError:
    return KokoroError(
        "PACK_PROMOTION_BUNDLE_INVALID",
        "The published promotion bundle is invalid.",
        details={"reason": reason},
    )


def _staging_invalid(reason: str) -> KokoroError:
    return KokoroError(
        "PACK_PROMOTION_STAGING_INVALID",
        "Promotion staging failed final validation.",
        details={"reason": reason},
    )


def _cleanup_failed(reason: str) -> KokoroError:
    return KokoroError(
        "PACK_PROMOTION_CLEANUP_FAILED",
        "Promotion staging cleanup could not be completed safely.",
        details={"reason": reason, "record_state": "not_visible"},
    )


def _review_id_conflict(review_id: str, reason: str) -> KokoroError:
    return KokoroError(
        "PACK_PROMOTION_REVIEW_ID_CONFLICT",
        "The review ID is already bound outside its matching transition.",
        details={"review_id": review_id, "reason": reason},
    )


def _read_error(context: str, reason: str) -> KokoroError:
    return _staging_invalid(reason) if context == "staging" else _bundle_invalid(reason)


def _storage_limit(reason: str) -> KokoroError:
    return KokoroError(
        "PACK_PROMOTION_STORAGE_LIMIT",
        "The promotion report store exceeds its bounded layout.",
        details={"reason": reason},
    )


__all__ = ["load_published_promotion_record", "publish_promotion_record"]
