"""Exact-version, host-registered migrations for canonical ``.karc`` archives."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, cast

from kokoroarc import __version__
from kokoroarc.distribution.archive import (
    InspectedKarcContainer,
    KarcLimits,
    _COMPILED_PATH,
    _HARD_PATH,
    _MANIFEST_PATH,
    _MEMBER_ROLES,
    _PROMOTION_PATH,
    _PUBLICATION_PATH,
    _REVIEW_PATH,
    _SCHEMA_RANGE,
    _SOFT_PATH,
    _write_archive,
    inspect_karc_container,
    load_karc_archive,
)
from kokoroarc.distribution.compatibility import (
    CURRENT_FORMAT_VERSION,
    _compare_semver,
    _parse_semver,
    archive_schema_versions,
    default_target_schema_versions,
    inspect_karc_compatibility,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes


_MIGRATION_STEP_ID = "karc-format-0.9.0-to-1.0.0"
_SCHEMA_KEYS = tuple(default_target_schema_versions("private"))


class _SchemaValidator(Protocol):
    def validate(self, name: str, instance: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class MigrationStep:
    """One pure transform between two exact format/schema states."""

    step_id: str
    source_format_version: str
    target_format_version: str
    source_schema_versions: Mapping[str, str | None]
    target_schema_versions: Mapping[str, str | None]
    transform: Callable[[bytes], bytes]

    def __post_init__(self) -> None:
        if (
            not self.step_id
            or _parse_semver(self.source_format_version) is None
            or _parse_semver(self.target_format_version) is None
            or not callable(self.transform)
        ):
            raise ValueError("MigrationStep metadata is invalid")
        source = _schema_vector(self.source_schema_versions)
        target = _schema_vector(self.target_schema_versions)
        object.__setattr__(self, "source_schema_versions", MappingProxyType(source))
        object.__setattr__(self, "target_schema_versions", MappingProxyType(target))


@dataclass(frozen=True, slots=True)
class MigrationPreview:
    """Deterministic preview output and its validated compatibility reports."""

    output_archive: bytes
    plan: dict[str, Any]
    compatibility_before: dict[str, Any]
    compatibility_after: dict[str, Any]


class MigrationRegistry:
    """Immutable graph of exact, built-in migration steps."""

    def __init__(self, steps: tuple[MigrationStep, ...]) -> None:
        ordered = tuple(sorted(steps, key=_step_sort_key))
        keys = [_edge_key(step) for step in ordered]
        if len(keys) != len(set(keys)):
            raise ValueError("Migration registry contains a duplicate exact edge")
        self._steps = ordered

    def describe(self) -> dict[str, Any]:
        return {
            "steps": [
                {
                    "step_id": step.step_id,
                    "source_format_version": step.source_format_version,
                    "target_format_version": step.target_format_version,
                    "source_schema_versions": dict(step.source_schema_versions),
                    "target_schema_versions": dict(step.target_schema_versions),
                }
                for step in self._steps
            ]
        }

    def find_path(
        self,
        source_format_version: str,
        source_schema_versions: Mapping[str, str | None],
        target_format_version: str,
        target_schema_versions: Mapping[str, str | None],
    ) -> tuple[MigrationStep, ...]:
        source = _state_key(source_format_version, source_schema_versions)
        target = _state_key(target_format_version, target_schema_versions)
        cycle_seen = False

        def visit(
            state: tuple[str, tuple[tuple[str, str | None], ...]],
            path: tuple[MigrationStep, ...],
            ancestors: frozenset[tuple[str, tuple[tuple[str, str | None], ...]]],
        ) -> tuple[MigrationStep, ...] | None:
            nonlocal cycle_seen
            if state == target:
                return path
            if len(path) >= 64:
                cycle_seen = True
                return None
            outgoing = [
                step for step in self._steps if _source_state(step) == state
            ]
            for step in outgoing:
                next_state = _target_state(step)
                if next_state in ancestors:
                    cycle_seen = True
                    continue
                result = visit(
                    next_state,
                    (*path, step),
                    ancestors | {next_state},
                )
                if result is not None:
                    return result
            return None

        result = visit(source, (), frozenset({source}))
        if result is not None and result:
            return result
        if cycle_seen:
            raise _error(
                "MIGRATION_CYCLE",
                "Migration registry path contains a cycle.",
            )
        raise _error(
            "MIGRATION_UNAVAILABLE",
            "No registered migration path matches the exact archive versions.",
        )


def _legacy_schema_vector(public: bool) -> dict[str, str | None]:
    return {
        "compiled_pack": "0.9.0",
        "hard_validation_report": "0.9.0",
        "soft_evaluation_report": "0.9.0",
        "review_attestation": "0.9.0",
        "promotion_record": "0.9.0",
        "publication_readiness_report": "0.9.0" if public else None,
    }


def preview_karc_migration(
    payload: bytes,
    target_format_version: str,
    schemas: _SchemaValidator,
    *,
    registry: MigrationRegistry | None = None,
    limits: KarcLimits = KarcLimits(),
) -> MigrationPreview:
    """Preview a deterministic registered migration without writing files."""

    if registry is None:
        registry = DEFAULT_MIGRATIONS
    if not isinstance(payload, bytes):
        raise _error("MIGRATION_INPUT_INVALID", "Migration input must be bytes.")
    if _parse_semver(target_format_version) is None:
        raise _error(
            "MIGRATION_UNAVAILABLE", "Migration target version is invalid."
        )
    source = _inspect_input(payload, limits)
    source_format = source.manifest.get("format_version")
    source_schemas = archive_schema_versions(source)
    if not isinstance(source_format, str) or source_schemas is None:
        raise _error(
            "MIGRATION_INPUT_INVALID",
            "Migration input does not declare exact source versions.",
        )
    if _parse_semver(source_format) is None:
        raise _error(
            "MIGRATION_INPUT_INVALID",
            "Migration input format version is invalid.",
        )
    if _compare_semver(source_format, target_format_version) > 0:
        raise _error(
            "MIGRATION_DOWNGRADE_UNSUPPORTED",
            "Archive downgrades are not supported.",
        )
    target_schemas = default_target_schema_versions(
        source.manifest.get("visibility")
    )
    steps = registry.find_path(
        source_format,
        source_schemas,
        target_format_version,
        target_schemas,
    )
    compatibility_before = inspect_karc_compatibility(
        payload,
        schemas,
        target_schema_versions=target_schemas,
        registry=registry,
        limits=limits,
    )
    required_input_checks = (
        "archive_structure",
        "member_inventory",
        "member_integrity",
        "runtime_version",
        "release_bindings",
    )
    failed_input_checks = [
        name
        for name in required_input_checks
        if compatibility_before["checks"][name]["passed"] is not True
    ]
    if failed_input_checks:
        raise _error(
            "MIGRATION_INPUT_INVALID",
            "Migration input failed required integrity checks.",
            checks=failed_input_checks,
        )
    output = payload
    current = source
    original_identity = _identity(current)
    for step in steps:
        if _state_key(
            cast(str, current.manifest.get("format_version")),
            cast(Mapping[str, str | None], archive_schema_versions(current)),
        ) != _source_state(step):
            raise _error(
                "MIGRATION_OUTPUT_INVALID",
                "Migration step source state does not match its input.",
                step_id=step.step_id,
            )
        try:
            candidate = step.transform(output)
        except Exception as error:
            raise _error(
                "MIGRATION_OUTPUT_INVALID",
                "Migration transform failed.",
                step_id=step.step_id,
                reason=type(error).__name__,
            ) from error
        if not isinstance(candidate, bytes):
            raise _error(
                "MIGRATION_OUTPUT_INVALID",
                "Migration transform did not return archive bytes.",
                step_id=step.step_id,
            )
        next_container = _inspect_output(candidate, limits)
        if _identity(next_container) != original_identity:
            raise _error(
                "MIGRATION_IDENTITY_CHANGED",
                "Migration changed protected character identity.",
                step_id=step.step_id,
            )
        next_schemas = archive_schema_versions(next_container)
        next_format = next_container.manifest.get("format_version")
        if (
            not isinstance(next_format, str)
            or next_schemas is None
            or _state_key(next_format, next_schemas) != _target_state(step)
        ):
            raise _error(
                "MIGRATION_OUTPUT_INVALID",
                "Migration output does not match the registered target state.",
                step_id=step.step_id,
            )
        output = candidate
        current = next_container

    try:
        load_karc_archive(output, schemas, limits=limits)
    except Exception as error:
        raise _error(
            "MIGRATION_OUTPUT_INVALID",
            "Migration output is not a current canonical archive.",
            reason=_reason(error),
        ) from error
    compatibility_after = inspect_karc_compatibility(
        output,
        schemas,
        target_schema_versions=target_schemas,
        registry=registry,
        limits=limits,
    )
    if compatibility_after.get("compatible") is not True:
        raise _error(
            "MIGRATION_OUTPUT_INVALID",
            "Migration output is not compatible with the target.",
        )
    plan = _migration_plan(
        source,
        current,
        payload,
        output,
        source_schemas,
        target_schemas,
        steps,
        compatibility_before,
        compatibility_after,
        mode="preview",
    )
    _validate_plan(schemas, plan)
    return MigrationPreview(
        output_archive=bytes(output),
        plan=_detached(plan),
        compatibility_before=_detached(compatibility_before),
        compatibility_after=_detached(compatibility_after),
    )


def apply_karc_migration(
    *,
    input_path: Path,
    output_path: Path,
    target_format_version: str,
    schemas: _SchemaValidator,
    registry: MigrationRegistry | None = None,
    limits: KarcLimits = KarcLimits(),
) -> dict[str, Any]:
    """Write a migrated archive to a new caller-selected path, never overwrite."""

    if registry is None:
        registry = DEFAULT_MIGRATIONS
    source = _absolute_path(input_path)
    target = _absolute_path(output_path)
    if _same_path(source, target):
        raise _error(
            "MIGRATION_OUTPUT_CONFLICT",
            "Migration output must differ from its input.",
        )
    if _lstat(target) is not None:
        raise _error(
            "MIGRATION_OUTPUT_EXISTS",
            "Migration output already exists.",
        )
    payload, source_identity = _read_input(source, limits)
    preview = preview_karc_migration(
        payload,
        target_format_version,
        schemas,
        registry=registry,
        limits=limits,
    )
    applied = deepcopy(preview.plan)
    applied["mode"] = "applied"
    _validate_plan(schemas, applied)
    parent_stat = _safe_parent(target)
    if not _source_is_unchanged(source, source_identity, payload):
        raise _error(
            "MIGRATION_INPUT_CHANGED",
            "Migration input changed during preview.",
    )
    _write_new_archive(target, preview.output_archive, parent_stat)
    return _detached(applied)


def _migrate_090_to_100(payload: bytes) -> bytes:
    container = inspect_karc_container(payload)
    documents = deepcopy(container.documents)
    manifest = documents.pop(_MANIFEST_PATH)
    compiled = documents[_COMPILED_PATH]
    hard = documents[_HARD_PATH]
    promotion = documents[_PROMOTION_PATH]
    review = documents[_REVIEW_PATH]
    soft = documents[_SOFT_PATH]
    publication = documents.get(_PUBLICATION_PATH)

    for document in documents.values():
        document["schema_version"] = "1.0"
    compiled_hash = _document_hash(compiled)
    for document in (hard, promotion, soft):
        document["compiled_hash"] = compiled_hash
    if publication is not None:
        publication["compiled_hash"] = compiled_hash

    hard_reference = _reference(hard)
    review["hard_report"] = hard_reference
    promotion["hard_report"] = hard_reference
    promotion["review_attestation"] = _reference(review)
    promotion["soft_evaluation_report"] = _reference(soft)
    if publication is not None:
        publication["promotion"] = _reference(promotion)

    manifest["format_version"] = CURRENT_FORMAT_VERSION
    manifest["archive_id"] = (
        f"{manifest['namespace']}.{manifest['character_id']}.{compiled_hash[:16]}"
    )
    manifest["compiled_hash"] = compiled_hash
    manifest["hard_validation_report"] = _reference(hard)
    manifest["soft_evaluation_report"] = _reference(soft)
    manifest["review_attestation"] = _reference(review)
    manifest["promotion_record"] = _reference(promotion)
    manifest["publication_readiness_report"] = (
        _reference(publication) if publication is not None else None
    )
    ranges = cast(dict[str, Any], manifest["compatibility"])["schemas"]
    for role in _SCHEMA_KEYS:
        ranges[role] = dict(_SCHEMA_RANGE) if role != (
            "publication_readiness_report"
        ) or publication is not None else None
    member_payloads = {
        path: canonical_bytes(document)
        for path, document in documents.items()
    }
    manifest["members"] = [
        {
            "path": path,
            "role": _MEMBER_ROLES[path],
            "size": len(member_payloads[path]),
            "sha256": sha256(member_payloads[path]).hexdigest(),
        }
        for path in sorted(documents)
    ]
    return _write_archive(
        {_MANIFEST_PATH: canonical_bytes(manifest), **member_payloads}
    )


def _migration_plan(
    source: InspectedKarcContainer,
    target: InspectedKarcContainer,
    input_payload: bytes,
    output_payload: bytes,
    source_schemas: Mapping[str, str | None],
    target_schemas: Mapping[str, str | None],
    steps: tuple[MigrationStep, ...],
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    step_ids = [step.step_id for step in steps]
    migration_id = (
        step_ids[0]
        if len(step_ids) == 1
        else f"karc-migration-{sha256(canonical_bytes(step_ids)).hexdigest()[:24]}"
    )
    manifest = source.manifest
    return {
        "schema_version": "1.0",
        "artifact_id": (
            f"{manifest['namespace']}/{manifest['character_id']}"
            "/distribution/migration-plan"
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "migration_id": migration_id,
        "namespace": manifest["namespace"],
        "character_id": manifest["character_id"],
        "character_version": manifest["character_version"],
        "input_archive_sha256": sha256(input_payload).hexdigest(),
        "output_archive_sha256": sha256(output_payload).hexdigest(),
        "source_format_version": manifest["format_version"],
        "target_format_version": target.manifest["format_version"],
        "source_schema_versions": dict(source_schemas),
        "target_schema_versions": dict(target_schemas),
        "registry_step_ids": step_ids,
        "changes": _changes(source.documents, target.documents),
        "compatibility_before": _reference(before),
        "compatibility_after": _reference(after),
        "state_migration_required": False,
        "state_migration_plan": None,
        "mode": mode,
        "archive_code_accepted": False,
    }


def _changes(before: Any, after: Any) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    def walk(left: Any, right: Any, segments: tuple[str, ...]) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                path = (*segments, str(key))
                if key not in left:
                    changes.append(_change("add", path, None, right[key]))
                elif key not in right:
                    changes.append(_change("remove", path, left[key], None))
                else:
                    walk(left[key], right[key], path)
            return
        if left != right:
            changes.append(_change("replace", segments, left, right))

    walk(before, after, ())
    return sorted(changes, key=lambda item: item["path"])


def _change(
    operation: str,
    segments: tuple[str, ...],
    before: Any,
    after: Any,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "path": "/" + "/".join(_pointer(segment) for segment in segments),
        "before_sha256": (
            None if operation == "add" else sha256(canonical_bytes(before)).hexdigest()
        ),
        "after_sha256": (
            None
            if operation == "remove"
            else sha256(canonical_bytes(after)).hexdigest()
        ),
    }


def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _validate_plan(schemas: _SchemaValidator, plan: dict[str, Any]) -> None:
    payload = canonical_bytes(plan)
    probe = json.loads(payload)
    try:
        schemas.validate("pack-migration-plan", probe)
    except Exception as error:
        raise _error(
            "MIGRATION_OUTPUT_INVALID",
            "Migration plan failed schema validation.",
            reason=_reason(error),
        ) from error
    if canonical_bytes(probe) != payload:
        raise _error(
            "MIGRATION_OUTPUT_INVALID",
            "Migration plan validation mutated its detached input.",
        )


def _inspect_input(payload: bytes, limits: KarcLimits) -> InspectedKarcContainer:
    try:
        return inspect_karc_container(payload, limits=limits)
    except Exception as error:
        raise _error(
            "MIGRATION_INPUT_INVALID",
            "Migration input is not a safe canonical archive.",
            reason=_reason(error),
        ) from error


def _inspect_output(payload: bytes, limits: KarcLimits) -> InspectedKarcContainer:
    try:
        return inspect_karc_container(payload, limits=limits)
    except Exception as error:
        raise _error(
            "MIGRATION_OUTPUT_INVALID",
            "Migration output is not a safe canonical archive.",
            reason=_reason(error),
        ) from error


def _identity(container: InspectedKarcContainer) -> tuple[Any, ...]:
    return tuple(
        container.manifest.get(field)
        for field in (
            "namespace",
            "character_id",
            "character_version",
            "source_artifact_id",
            "source_hash",
        )
    )


def _reference(value: dict[str, Any] | None) -> dict[str, str]:
    if value is None:
        raise ValueError("artifact reference value is required")
    return {
        "artifact_id": cast(str, value["artifact_id"]),
        "sha256": _document_hash(value),
    }


def _document_hash(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _schema_vector(
    value: Mapping[str, str | None],
) -> dict[str, str | None]:
    result = dict(value)
    if set(result) != set(_SCHEMA_KEYS):
        raise ValueError("Migration schema vector is incomplete")
    for role in _SCHEMA_KEYS:
        version = result[role]
        if version is None:
            if role != "publication_readiness_report":
                raise ValueError("Required migration schema version is missing")
        elif _parse_semver(version) is None:
            raise ValueError("Migration schema version is invalid")
    return {key: result[key] for key in _SCHEMA_KEYS}


def _state_key(
    format_version: str,
    schema_versions: Mapping[str, str | None],
) -> tuple[str, tuple[tuple[str, str | None], ...]]:
    return (format_version, tuple(_schema_vector(schema_versions).items()))


def _source_state(
    step: MigrationStep,
) -> tuple[str, tuple[tuple[str, str | None], ...]]:
    return _state_key(step.source_format_version, step.source_schema_versions)


def _target_state(
    step: MigrationStep,
) -> tuple[str, tuple[tuple[str, str | None], ...]]:
    return _state_key(step.target_format_version, step.target_schema_versions)


def _edge_key(step: MigrationStep) -> tuple[Any, ...]:
    return (_source_state(step), _target_state(step))


def _step_sort_key(step: MigrationStep) -> tuple[Any, ...]:
    return (
        step.source_format_version,
        tuple(
            (key, value or "")
            for key, value in step.source_schema_versions.items()
        ),
        step.target_format_version,
        tuple(
            (key, value or "")
            for key, value in step.target_schema_versions.items()
        ),
        step.step_id,
    )


def _absolute_path(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (OSError, TypeError, ValueError) as error:
        raise _error(
            "MIGRATION_PATH_INVALID", "Migration path is invalid."
        ) from error


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _error(
            "MIGRATION_PATH_INVALID", "Migration path cannot be inspected."
        ) from error


def _read_input(
    path: Path, limits: KarcLimits
) -> tuple[bytes, tuple[int, int, int, int, int]]:
    path_stat = _lstat(path)
    if path_stat is None:
        raise _error(
            "MIGRATION_INPUT_NOT_FOUND", "Migration input does not exist."
        )
    if not stat.S_ISREG(path_stat.st_mode) or stat.S_ISLNK(path_stat.st_mode):
        raise _error(
            "MIGRATION_INPUT_INVALID",
            "Migration input must be a regular non-link file.",
        )
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            payload = handle.read(limits.max_archive_bytes + 1)
            if handle.read(1):
                payload += b"x"
            after = os.fstat(handle.fileno())
    except OSError as error:
        raise _error(
            "MIGRATION_INPUT_INVALID", "Migration input could not be read."
        ) from error
    if len(payload) > limits.max_archive_bytes:
        raise _error(
            "MIGRATION_INPUT_INVALID", "Migration input exceeds the byte limit."
        )
    identities = (
        _stat_identity(path_stat),
        _stat_identity(opened),
        _stat_identity(after),
    )
    if len(set(identities)) != 1 or not _source_is_unchanged(
        path, identities[0], payload
    ):
        raise _error(
            "MIGRATION_INPUT_CHANGED", "Migration input changed while read."
        )
    return payload, identities[0]


def _source_is_unchanged(
    path: Path,
    identity: tuple[int, int, int, int, int],
    payload: bytes,
) -> bool:
    try:
        before = _lstat(path)
        if before is None or _stat_identity(before) != identity:
            return False
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            candidate = handle.read(len(payload) + 1)
            after = os.fstat(handle.fileno())
        final = _lstat(path)
    except OSError:
        return False
    return (
        final is not None
        and _stat_identity(opened) == identity
        and _stat_identity(after) == identity
        and _stat_identity(final) == identity
        and candidate == payload
    )


def _safe_parent(
    target: Path,
) -> tuple[tuple[Path, tuple[int, int, int]], ...]:
    chain: list[tuple[Path, tuple[int, int, int]]] = []
    for directory in reversed((target.parent, *target.parent.parents)):
        directory_stat = _lstat(directory)
        if (
            directory_stat is None
            or not stat.S_ISDIR(directory_stat.st_mode)
            or _is_redirect(directory, directory_stat)
        ):
            raise _error(
                "MIGRATION_PATH_INVALID",
                "Migration output ancestry must contain regular directories.",
            )
        chain.append((directory, _directory_identity(directory_stat)))
    return tuple(chain)


def _write_new_archive(
    target: Path,
    payload: bytes,
    parent_boundary: tuple[tuple[Path, tuple[int, int, int]], ...],
) -> None:
    descriptor = -1
    staging: Path | None = None
    try:
        descriptor, raw_staging = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        staging = Path(raw_staging)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if not _directory_boundary_matches(parent_boundary):
            raise _error(
                "MIGRATION_PATH_INVALID",
                "Migration output ancestry changed before publication.",
            )
        if _lstat(target) is not None:
            raise _error(
                "MIGRATION_OUTPUT_EXISTS",
                "Migration output appeared before publication.",
            )
        os.link(staging, target)
    except FileExistsError as error:
        raise _error(
            "MIGRATION_OUTPUT_EXISTS", "Migration output already exists."
        ) from error
    except KokoroError:
        raise
    except OSError as error:
        raise _error(
            "MIGRATION_OUTPUT_WRITE_FAILED",
            "Migration output could not be written atomically.",
            reason=type(error).__name__,
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if staging is not None:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                pass


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (int(value.st_dev), int(value.st_ino), stat.S_IFMT(value.st_mode))


def _directory_boundary_matches(
    boundary: tuple[tuple[Path, tuple[int, int, int]], ...],
) -> bool:
    for directory, expected in boundary:
        current = _lstat(directory)
        if (
            current is None
            or not stat.S_ISDIR(current.st_mode)
            or _is_redirect(directory, current)
            or _directory_identity(current) != expected
        ):
            return False
    return True


def _is_redirect(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    probe = getattr(path, "is_junction", None)
    if probe is None:
        return False
    try:
        return bool(probe())
    except OSError as error:
        raise _error(
            "MIGRATION_PATH_INVALID",
            "Migration path redirection could not be inspected.",
        ) from error


def _detached(value: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(canonical_bytes(value)))


def _reason(error: BaseException) -> str:
    return error.code if isinstance(error, KokoroError) else type(error).__name__


def _error(code: str, message: str, **details: Any) -> KokoroError:
    return KokoroError(code, message, details=details)


DEFAULT_MIGRATIONS = MigrationRegistry(
    (
        MigrationStep(
            step_id=_MIGRATION_STEP_ID,
            source_format_version="0.9.0",
            target_format_version=CURRENT_FORMAT_VERSION,
            source_schema_versions=_legacy_schema_vector(False),
            target_schema_versions=default_target_schema_versions("private"),
            transform=_migrate_090_to_100,
        ),
        MigrationStep(
            step_id=_MIGRATION_STEP_ID,
            source_format_version="0.9.0",
            target_format_version=CURRENT_FORMAT_VERSION,
            source_schema_versions=_legacy_schema_vector(True),
            target_schema_versions=default_target_schema_versions(
                "public_candidate"
            ),
            transform=_migrate_090_to_100,
        ),
    )
)


__all__ = [
    "DEFAULT_MIGRATIONS",
    "MigrationPreview",
    "MigrationRegistry",
    "MigrationStep",
    "apply_karc_migration",
    "preview_karc_migration",
]
