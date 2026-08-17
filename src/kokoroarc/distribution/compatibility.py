"""Read-only compatibility inspection for canonical ``.karc`` containers."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Protocol, cast

from kokoroarc import __version__
from kokoroarc.distribution.archive import (
    InspectedKarcContainer,
    KarcLimits,
    _COMPILED_PATH,
    _HARD_PATH,
    _MANIFEST_PATH,
    _MEMBER_ROLES,
    _PRIVATE_PATHS,
    _PROMOTION_PATH,
    _PUBLICATION_PATH,
    _PUBLIC_PATHS,
    _REVIEW_PATH,
    _SOFT_PATH,
    _validate_manifest,
    _validate_release,
    inspect_karc_container,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes


CURRENT_FORMAT_VERSION = "1.0.0"
DEFAULT_TARGET_RUNTIME_VERSION = "0.0.0"
_SCHEMA_ROLES = {
    "compiled_pack": _COMPILED_PATH,
    "hard_validation_report": _HARD_PATH,
    "soft_evaluation_report": _SOFT_PATH,
    "review_attestation": _REVIEW_PATH,
    "promotion_record": _PROMOTION_PATH,
    "publication_readiness_report": _PUBLICATION_PATH,
}
_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_ARTIFACT_ID = re.compile(r"[a-z0-9][a-z0-9._/-]{0,191}")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_FINDING_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,95}")


class _SchemaValidator(Protocol):
    def validate(self, name: str, instance: Any) -> None: ...


class _MigrationRegistry(Protocol):
    def find_path(
        self,
        source_format_version: str,
        source_schema_versions: Mapping[str, str | None],
        target_format_version: str,
        target_schema_versions: Mapping[str, str | None],
    ) -> tuple[Any, ...]: ...


class _NoopSchemas:
    def validate(self, _name: str, _instance: Any) -> None:
        return None


def default_target_schema_versions(visibility: object) -> dict[str, str | None]:
    """Return the exact v1 schema vector for a private or public archive."""

    return {
        "compiled_pack": "1.0.0",
        "hard_validation_report": "1.0.0",
        "soft_evaluation_report": "1.0.0",
        "review_attestation": "1.0.0",
        "promotion_record": "1.0.0",
        "publication_readiness_report": (
            "1.0.0" if visibility == "public_candidate" else None
        ),
    }


def archive_schema_versions(
    container: InspectedKarcContainer,
) -> dict[str, str | None] | None:
    """Project exact member schema versions into the migration registry key."""

    result: dict[str, str | None] = {}
    for role, path in _SCHEMA_ROLES.items():
        if path not in container.documents:
            if role == "publication_readiness_report":
                result[role] = None
                continue
            return None
        value = container.documents[path].get("schema_version")
        normalized = _normalize_schema_version(value)
        if normalized is None:
            return None
        result[role] = normalized
    return result


def inspect_karc_compatibility(
    payload: bytes,
    schemas: _SchemaValidator,
    *,
    target_runtime_version: str = DEFAULT_TARGET_RUNTIME_VERSION,
    target_schema_versions: Mapping[str, str | None] | None = None,
    registry: _MigrationRegistry | None = None,
    limits: KarcLimits = KarcLimits(),
) -> dict[str, Any]:
    """Return a closed compatibility report without extracting or writing state."""

    if not isinstance(payload, bytes):
        raise _error("KARC_ARCHIVE_INVALID", "Archive payload must be bytes.")
    if _parse_semver(target_runtime_version) is None:
        raise _error(
            "KARC_COMPATIBILITY_TARGET_INVALID",
            "Target runtime version must be semantic.",
        )
    archive_hash = sha256(payload).hexdigest()
    try:
        container = inspect_karc_container(payload, limits=limits)
    except KokoroError as error:
        report = _unreadable_report(
            archive_hash,
            target_runtime_version,
            target_schema_versions,
            error.code,
        )
        _validate_report(schemas, report)
        return report

    manifest = container.manifest
    visibility = manifest.get("visibility")
    targets = _target_schemas(target_schema_versions, visibility)
    checks = {
        "archive_structure": _passing_check(),
        "manifest_schema": _manifest_schema_check(manifest, schemas),
        "member_inventory": _inventory_check(container),
        "member_integrity": _integrity_check(container),
        "runtime_version": _runtime_check(manifest, target_runtime_version),
        "schema_versions": _schema_check(container, manifest, targets),
        "release_bindings": _release_check(container, schemas),
    }
    compatible = all(check["passed"] for check in checks.values())
    actual_schemas = archive_schema_versions(container)
    migration = _migration_summary(
        manifest.get("format_version"),
        actual_schemas,
        targets,
        registry,
    )
    report = {
        "schema_version": "1.0",
        "artifact_id": f"kokoroarc/distribution/compatibility/{archive_hash}",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "archive_sha256": archive_hash,
        "manifest": _manifest_reference(container),
        "format_version": _semantic_or_none(manifest.get("format_version")),
        "namespace": _slug_or_none(manifest.get("namespace")),
        "character_id": _slug_or_none(manifest.get("character_id")),
        "character_version": _semantic_or_none(
            manifest.get("character_version")
        ),
        "source_hash": _hash_or_none(manifest.get("source_hash")),
        "compiled_hash": _hash_or_none(manifest.get("compiled_hash")),
        "visibility": (
            visibility if visibility in {"private", "public_candidate"} else None
        ),
        "trust": (
            "unsigned_local" if manifest.get("trust") == "unsigned_local" else None
        ),
        "target_runtime_version": target_runtime_version,
        "target_schema_versions": targets,
        "checks": checks,
        "migration": migration,
        "compatible": compatible,
        "installation_allowed": compatible,
    }
    _validate_report(schemas, report)
    return cast(dict[str, Any], json.loads(canonical_bytes(report)))


def _target_schemas(
    supplied: Mapping[str, str | None] | None,
    visibility: object,
) -> dict[str, str | None]:
    targets = (
        default_target_schema_versions(visibility)
        if supplied is None
        else dict(supplied)
    )
    expected = set(_SCHEMA_ROLES)
    if set(targets) != expected:
        raise _error(
            "KARC_COMPATIBILITY_TARGET_INVALID",
            "Target schema vector is incomplete.",
        )
    for role, value in targets.items():
        if value is None:
            if role != "publication_readiness_report":
                raise _error(
                    "KARC_COMPATIBILITY_TARGET_INVALID",
                    "Required target schema version is missing.",
                )
        elif _parse_semver(value) is None:
            raise _error(
                "KARC_COMPATIBILITY_TARGET_INVALID",
                "Target schema version must be semantic.",
            )
    return {key: targets[key] for key in _SCHEMA_ROLES}


def _unreadable_report(
    archive_hash: str,
    target_runtime_version: str,
    supplied_targets: Mapping[str, str | None] | None,
    reason: str,
) -> dict[str, Any]:
    targets = _target_schemas(supplied_targets, None)
    finding_code = reason if _FINDING_CODE.fullmatch(reason) else (
        "KARC_ARCHIVE_INVALID"
    )
    checks = {
        "archive_structure": _failing_check(
            finding_code,
            "Archive structure could not be inspected safely.",
            ["archive"],
        )
    }
    for name in (
        "manifest_schema",
        "member_inventory",
        "member_integrity",
        "runtime_version",
        "schema_versions",
        "release_bindings",
    ):
        checks[name] = _failing_check(
            "KARC_COMPATIBILITY_BLOCKED",
            "Compatibility check is blocked by invalid archive structure.",
            [name],
        )
    return {
        "schema_version": "1.0",
        "artifact_id": f"kokoroarc/distribution/compatibility/{archive_hash}",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "archive_sha256": archive_hash,
        "manifest": None,
        "format_version": None,
        "namespace": None,
        "character_id": None,
        "character_version": None,
        "source_hash": None,
        "compiled_hash": None,
        "visibility": None,
        "trust": None,
        "target_runtime_version": target_runtime_version,
        "target_schema_versions": targets,
        "checks": checks,
        "migration": {
            "required": True,
            "available": False,
            "target_format_version": CURRENT_FORMAT_VERSION,
            "migration_id": None,
        },
        "compatible": False,
        "installation_allowed": False,
    }


def _manifest_reference(
    container: InspectedKarcContainer,
) -> dict[str, str] | None:
    artifact_id = container.manifest.get("artifact_id")
    if not isinstance(artifact_id, str) or _ARTIFACT_ID.fullmatch(artifact_id) is None:
        return None
    return {
        "artifact_id": artifact_id,
        "sha256": sha256(container.member_payloads[_MANIFEST_PATH]).hexdigest(),
    }


def _manifest_schema_check(
    manifest: dict[str, Any], schemas: _SchemaValidator
) -> dict[str, Any]:
    payload = canonical_bytes(manifest)
    probe = json.loads(payload)
    try:
        schemas.validate("karc-manifest", probe)
    except Exception:
        return _failing_check(
            "KARC_MANIFEST_SCHEMA_UNSUPPORTED",
            "Archive manifest is not valid for the current schema.",
            ["manifest"],
        )
    if canonical_bytes(probe) != payload:
        return _failing_check(
            "KARC_MANIFEST_SCHEMA_MUTATION",
            "Manifest schema validation changed its detached input.",
            ["manifest"],
        )
    return _passing_check()


def _inventory_check(container: InspectedKarcContainer) -> dict[str, Any]:
    visibility = container.manifest.get("visibility")
    expected = (
        _PUBLIC_PATHS if visibility == "public_candidate" else _PRIVATE_PATHS
    )
    actual = tuple(container.member_payloads)
    members = container.manifest.get("members")
    expected_members = [
        {
            "path": path,
            "role": _MEMBER_ROLES[path],
            "size": len(container.member_payloads[path]),
            "sha256": sha256(container.member_payloads[path]).hexdigest(),
        }
        for path in expected[1:]
        if path in container.member_payloads
    ]
    if visibility not in {"private", "public_candidate"} or actual != expected:
        return _failing_check(
            "KARC_MEMBER_INVENTORY_INVALID",
            "Archive member inventory does not match its visibility.",
            ["manifest", "members"],
        )
    if not isinstance(members, list) or [
        (item.get("path"), item.get("role"))
        for item in members
        if isinstance(item, dict)
    ] != [(item["path"], item["role"]) for item in expected_members]:
        return _failing_check(
            "KARC_MEMBER_INVENTORY_INVALID",
            "Manifest member inventory is incomplete or unordered.",
            ["manifest", "members"],
        )
    return _passing_check()


def _integrity_check(container: InspectedKarcContainer) -> dict[str, Any]:
    members = container.manifest.get("members")
    if not isinstance(members, list):
        return _failing_check(
            "KARC_MEMBER_INTEGRITY_INVALID",
            "Manifest member hashes and sizes are unavailable.",
            ["manifest", "members"],
        )
    for index, member in enumerate(members):
        if not isinstance(member, dict) or not isinstance(member.get("path"), str):
            return _failing_check(
                "KARC_MEMBER_INTEGRITY_INVALID",
                "Manifest member entry is invalid.",
                ["manifest", "members", str(index)],
            )
        path = member["path"]
        payload = container.member_payloads.get(path)
        if payload is None or member.get("size") != len(payload) or member.get(
            "sha256"
        ) != sha256(payload).hexdigest():
            return _failing_check(
                "KARC_MEMBER_INTEGRITY_INVALID",
                "Manifest member hash or size does not match archive bytes.",
                ["manifest", "members", str(index)],
            )
    return _passing_check()


def _runtime_check(
    manifest: dict[str, Any], target_runtime_version: str
) -> dict[str, Any]:
    compatibility = manifest.get("compatibility")
    runtime = compatibility.get("runtime") if isinstance(compatibility, dict) else None
    if not isinstance(runtime, dict) or not _version_in_range(
        target_runtime_version,
        runtime.get("minimum_inclusive"),
        runtime.get("maximum_exclusive"),
    ):
        return _failing_check(
            "KARC_RUNTIME_VERSION_UNSUPPORTED",
            "Target runtime version is outside the archive range.",
            ["manifest", "compatibility", "runtime"],
        )
    return _passing_check()


def _schema_check(
    container: InspectedKarcContainer,
    manifest: dict[str, Any],
    targets: Mapping[str, str | None],
) -> dict[str, Any]:
    actual = archive_schema_versions(container)
    compatibility = manifest.get("compatibility")
    ranges = compatibility.get("schemas") if isinstance(compatibility, dict) else None
    if actual is None or not isinstance(ranges, dict):
        return _failing_check(
            "KARC_SCHEMA_VERSION_UNSUPPORTED",
            "Archive schema versions are incomplete.",
            ["manifest", "compatibility", "schemas"],
        )
    for role in _SCHEMA_ROLES:
        target = targets[role]
        member_version = actual[role]
        version_range = ranges.get(role)
        if target is None:
            if member_version is not None or version_range is not None:
                return _failing_check(
                    "KARC_SCHEMA_VERSION_UNSUPPORTED",
                    "Archive schema presence does not match the target.",
                    ["manifest", "compatibility", "schemas", role],
                )
            continue
        if (
            member_version != target
            or not isinstance(version_range, dict)
            or not _version_in_range(
                target,
                version_range.get("minimum_inclusive"),
                version_range.get("maximum_exclusive"),
            )
        ):
            return _failing_check(
                "KARC_SCHEMA_VERSION_UNSUPPORTED",
                "Archive member schema version is not current for the target.",
                ["manifest", "compatibility", "schemas", role],
            )
    return _passing_check()


def _release_check(
    container: InspectedKarcContainer,
    schemas: _SchemaValidator,
) -> dict[str, Any]:
    documents = {
        path: value
        for path, value in container.documents.items()
        if path != _MANIFEST_PATH
    }
    actual_versions = archive_schema_versions(container)
    current_versions = default_target_schema_versions(
        container.manifest.get("visibility")
    )
    release_schemas: _SchemaValidator = (
        schemas if actual_versions == current_versions else _NoopSchemas()
    )
    try:
        _validate_manifest(
            container.manifest,
            deepcopy(documents),
            container.member_payloads,
        )
        _validate_release(
            deepcopy(documents),
            container.member_payloads,
            release_schemas,
        )
    except Exception:
        return _failing_check(
            "KARC_RELEASE_BINDING_INVALID",
            "Archive release bindings do not match member bytes.",
            ["manifest"],
        )
    return _passing_check()


def _migration_summary(
    source_format: object,
    source_schemas: Mapping[str, str | None] | None,
    target_schemas: Mapping[str, str | None],
    registry: _MigrationRegistry | None,
) -> dict[str, Any]:
    if (
        source_format == CURRENT_FORMAT_VERSION
        and source_schemas is not None
        and dict(source_schemas) == dict(target_schemas)
    ):
        return {
            "required": False,
            "available": False,
            "target_format_version": None,
            "migration_id": None,
        }
    summary = {
        "required": True,
        "available": False,
        "target_format_version": CURRENT_FORMAT_VERSION,
        "migration_id": None,
    }
    if not isinstance(source_format, str) or source_schemas is None:
        return summary
    if registry is None:
        from kokoroarc.distribution.migrations import DEFAULT_MIGRATIONS

        registry = DEFAULT_MIGRATIONS
    try:
        path = registry.find_path(
            source_format,
            source_schemas,
            CURRENT_FORMAT_VERSION,
            target_schemas,
        )
    except KokoroError:
        return summary
    if not path:
        return summary
    step_ids = [str(step.step_id) for step in path]
    migration_id = (
        step_ids[0]
        if len(step_ids) == 1
        else f"karc-migration-{sha256(canonical_bytes(step_ids)).hexdigest()[:24]}"
    )
    summary["available"] = True
    summary["migration_id"] = migration_id
    return summary


def _validate_report(schemas: _SchemaValidator, report: dict[str, Any]) -> None:
    payload = canonical_bytes(report)
    probe = json.loads(payload)
    schemas.validate("pack-compatibility-report", probe)
    if canonical_bytes(probe) != payload:
        raise _error(
            "KARC_COMPATIBILITY_REPORT_INVALID",
            "Compatibility report validation mutated its detached input.",
        )


def _normalize_schema_version(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value if value.count(".") >= 2 else f"{value}.0"
    return candidate if _parse_semver(candidate) is not None else None


def _semantic_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and _parse_semver(value) else None


def _slug_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and _SLUG.fullmatch(value) else None


def _hash_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and _SHA256.fullmatch(value) else None


def _version_in_range(version: object, minimum: object, maximum: object) -> bool:
    if not all(isinstance(value, str) for value in (version, minimum, maximum)):
        return False
    if any(
        _parse_semver(cast(str, value)) is None
        for value in (version, minimum, maximum)
    ):
        return False
    return _compare_semver(cast(str, minimum), cast(str, version)) <= 0 and (
        _compare_semver(cast(str, version), cast(str, maximum)) < 0
    )


def _parse_semver(
    value: object,
) -> tuple[tuple[int, int, int], tuple[str, ...] | None] | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        return None
    match = _SEMVER.fullmatch(value)
    if match is None:
        return None
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else None
    return (
        (int(match.group(1)), int(match.group(2)), int(match.group(3))),
        prerelease,
    )


def _compare_semver(left: str, right: str) -> int:
    left_value = _parse_semver(left)
    right_value = _parse_semver(right)
    if left_value is None or right_value is None:
        raise ValueError("invalid semantic version")
    if left_value[0] != right_value[0]:
        return -1 if left_value[0] < right_value[0] else 1
    left_pre, right_pre = left_value[1], right_value[1]
    if left_pre is None or right_pre is None:
        if left_pre is right_pre:
            return 0
        return 1 if left_pre is None else -1
    for left_part, right_part in zip(left_pre, right_pre):
        if left_part == right_part:
            continue
        left_numeric = left_part.isdigit()
        right_numeric = right_part.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_part) < int(right_part) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_part < right_part else 1
    if len(left_pre) == len(right_pre):
        return 0
    return -1 if len(left_pre) < len(right_pre) else 1


def _passing_check() -> dict[str, Any]:
    return {"passed": True, "findings": []}


def _failing_check(
    code: str, message: str, path: list[str]
) -> dict[str, Any]:
    return {
        "passed": False,
        "findings": [{"code": code, "message": message, "path": path}],
    }


def _error(code: str, message: str, **details: Any) -> KokoroError:
    return KokoroError(code, message, details=details)


__all__ = [
    "CURRENT_FORMAT_VERSION",
    "DEFAULT_TARGET_RUNTIME_VERSION",
    "archive_schema_versions",
    "default_target_schema_versions",
    "inspect_karc_compatibility",
]
