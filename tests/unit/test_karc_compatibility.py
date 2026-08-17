from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kokoroarc.distribution.archive import KarcLimits
from kokoroarc.distribution.compatibility import inspect_karc_compatibility
from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import (
    build_private_archive,
    make_legacy_090_archive,
    make_newer_200_archive,
    reversion_archive,
    rewrite_archive,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def test_current_archive_has_a_deterministic_installable_report(
    rin_verified_release: dict[str, Any],
) -> None:
    archive = build_private_archive(rin_verified_release)

    first = inspect_karc_compatibility(archive, SCHEMAS)
    second = inspect_karc_compatibility(archive, SCHEMAS)

    assert first == second
    SCHEMAS.validate("pack-compatibility-report", first)
    assert first["compatible"] is True
    assert first["installation_allowed"] is True
    assert all(check["passed"] for check in first["checks"].values())
    assert first["migration"] == {
        "required": False,
        "available": False,
        "target_format_version": None,
        "migration_id": None,
    }


def test_malformed_archive_returns_a_closed_noninstallable_report() -> None:
    report = inspect_karc_compatibility(b"not a zip archive", SCHEMAS)

    SCHEMAS.validate("pack-compatibility-report", report)
    assert report["compatible"] is False
    assert report["installation_allowed"] is False
    assert report["manifest"] is None
    assert report["namespace"] is None
    assert report["checks"]["archive_structure"]["passed"] is False
    assert report["checks"]["archive_structure"]["findings"][0]["code"] == (
        "KARC_ARCHIVE_INVALID"
    )


def test_newer_format_is_safe_to_inspect_but_not_installable(
    rin_verified_release: dict[str, Any],
) -> None:
    archive = make_newer_200_archive(build_private_archive(rin_verified_release))

    report = inspect_karc_compatibility(archive, SCHEMAS)

    SCHEMAS.validate("pack-compatibility-report", report)
    assert report["format_version"] == "2.0.0"
    assert report["checks"]["archive_structure"]["passed"] is True
    assert report["checks"]["manifest_schema"]["passed"] is False
    assert report["compatible"] is False
    assert report["migration"] == {
        "required": True,
        "available": False,
        "target_format_version": "1.0.0",
        "migration_id": None,
    }


def test_registered_legacy_format_reports_an_exact_migration_path(
    rin_verified_release: dict[str, Any],
) -> None:
    current = build_private_archive(rin_verified_release)
    legacy = make_legacy_090_archive(current)

    report = inspect_karc_compatibility(legacy, SCHEMAS)

    SCHEMAS.validate("pack-compatibility-report", report)
    assert report["format_version"] == "0.9.0"
    assert report["compatible"] is False
    assert report["migration"] == {
        "required": True,
        "available": True,
        "target_format_version": "1.0.0",
        "migration_id": "karc-format-0.9.0-to-1.0.0",
    }


def test_current_format_with_legacy_member_schemas_still_requires_migration(
    rin_verified_release: dict[str, Any],
) -> None:
    archive = reversion_archive(
        build_private_archive(rin_verified_release),
        format_version="1.0.0",
        document_schema_version="0.9",
        schema_version="0.9.0",
        schema_maximum="1.0.0",
    )

    report = inspect_karc_compatibility(archive, SCHEMAS)

    assert report["checks"]["schema_versions"]["passed"] is False
    assert report["compatible"] is False
    assert report["migration"] == {
        "required": True,
        "available": False,
        "target_format_version": "1.0.0",
        "migration_id": None,
    }


def test_runtime_outside_manifest_range_blocks_installation(
    rin_verified_release: dict[str, Any],
) -> None:
    archive = build_private_archive(rin_verified_release)

    report = inspect_karc_compatibility(
        archive,
        SCHEMAS,
        target_runtime_version="1.0.0",
    )

    assert report["checks"]["runtime_version"]["passed"] is False
    assert report["compatible"] is False
    assert report["installation_allowed"] is False


def test_invalid_manifest_version_range_returns_a_closed_report(
    rin_verified_release: dict[str, Any],
) -> None:
    current = build_private_archive(rin_verified_release)

    def invalidate(documents: dict[str, dict[str, Any]]) -> None:
        documents["manifest.json"]["compatibility"]["runtime"][
            "minimum_inclusive"
        ] = "not-semantic"

    report = inspect_karc_compatibility(rewrite_archive(current, invalidate), SCHEMAS)

    SCHEMAS.validate("pack-compatibility-report", report)
    assert report["compatible"] is False
    assert report["checks"]["runtime_version"]["passed"] is False
    assert report["checks"]["runtime_version"]["findings"][0]["code"] == (
        "KARC_RUNTIME_VERSION_UNSUPPORTED"
    )


def test_oversized_manifest_semver_returns_a_closed_report(
    rin_verified_release: dict[str, Any],
) -> None:
    current = build_private_archive(rin_verified_release)

    def oversize_format_version(documents: dict[str, dict[str, Any]]) -> None:
        documents["manifest.json"]["format_version"] = f"1{'0' * 5_000}.0.0"

    report = inspect_karc_compatibility(
        rewrite_archive(current, oversize_format_version),
        SCHEMAS,
    )

    SCHEMAS.validate("pack-compatibility-report", report)
    assert report["format_version"] is None
    assert report["checks"]["manifest_schema"]["passed"] is False
    assert report["compatible"] is False
    assert report["installation_allowed"] is False


def test_current_member_schema_failure_blocks_installation_even_when_rebound(
    rin_verified_release: dict[str, Any],
) -> None:
    current = build_private_archive(rin_verified_release)

    def add_unknown_field(documents: dict[str, dict[str, Any]]) -> None:
        documents["pack/compiled.json"]["archive_owned_extension"] = True

    mutated = rewrite_archive(current, add_unknown_field)
    rebound = reversion_archive(
        mutated,
        format_version="1.0.0",
        document_schema_version="1.0",
        schema_version="1.0.0",
        schema_maximum="2.0.0",
    )

    report = inspect_karc_compatibility(rebound, SCHEMAS)

    assert report["checks"]["member_integrity"]["passed"] is True
    assert report["checks"]["release_bindings"]["passed"] is False
    assert report["compatible"] is False
    assert report["installation_allowed"] is False


def test_target_semver_rejects_a_leading_zero_prerelease_identifier(
    rin_verified_release: dict[str, Any],
) -> None:
    archive = build_private_archive(rin_verified_release)

    with pytest.raises(KokoroError) as caught:
        inspect_karc_compatibility(
            archive,
            SCHEMAS,
            target_runtime_version="1.0.0-01",
        )

    assert caught.value.code == "KARC_COMPATIBILITY_TARGET_INVALID"


def test_archive_limit_failure_remains_machine_readable(
    rin_verified_release: dict[str, Any],
) -> None:
    archive = build_private_archive(rin_verified_release)
    limits = KarcLimits(max_archive_bytes=len(archive) - 1)

    report = inspect_karc_compatibility(archive, SCHEMAS, limits=limits)

    assert report["checks"]["archive_structure"]["findings"][0]["code"] == (
        "KARC_ARCHIVE_LIMIT_EXCEEDED"
    )
    assert report["compatible"] is False
