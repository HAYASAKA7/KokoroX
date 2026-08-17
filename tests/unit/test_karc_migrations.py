from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.distribution.archive import load_karc_archive
from kokoroarc.distribution.migrations import (
    DEFAULT_MIGRATIONS,
    MigrationRegistry,
    MigrationStep,
    preview_karc_migration,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import (
    add_archive_code,
    build_private_archive,
    build_public_archive,
    make_legacy_090_archive,
    rewrite_archive,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
PRIVATE_090 = {
    "compiled_pack": "0.9.0",
    "hard_validation_report": "0.9.0",
    "soft_evaluation_report": "0.9.0",
    "review_attestation": "0.9.0",
    "promotion_record": "0.9.0",
    "publication_readiness_report": None,
}
PRIVATE_100 = {
    **{key: "1.0.0" for key in PRIVATE_090 if key != "publication_readiness_report"},
    "publication_readiness_report": None,
}


def _assert_code(code: str, function: Any, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(KokoroError) as caught:
        function(*args, **kwargs)
    assert caught.value.code == code


def test_preview_is_deterministic_hash_bound_and_loadable(
    rin_verified_release: dict[str, Any],
) -> None:
    current = build_private_archive(rin_verified_release)
    legacy = make_legacy_090_archive(current)

    first = preview_karc_migration(legacy, "1.0.0", SCHEMAS)
    second = preview_karc_migration(legacy, "1.0.0", SCHEMAS)
    loaded = load_karc_archive(first.output_archive, SCHEMAS)

    assert first == second
    assert first.output_archive == current
    assert first.plan["mode"] == "preview"
    assert first.plan["source_format_version"] == "0.9.0"
    assert first.plan["target_format_version"] == "1.0.0"
    assert first.plan["registry_step_ids"] == [
        "karc-format-0.9.0-to-1.0.0"
    ]
    assert first.plan["changes"] == sorted(
        first.plan["changes"], key=lambda change: change["path"]
    )
    assert first.plan["state_migration_required"] is False
    assert first.plan["archive_code_accepted"] is False
    assert first.compatibility_before["compatible"] is False
    assert first.compatibility_after["compatible"] is True
    assert loaded.manifest["format_version"] == "1.0.0"
    SCHEMAS.validate("pack-migration-plan", first.plan)


def test_preview_does_not_mutate_registry_or_input_objects(
    rin_verified_release: dict[str, Any],
) -> None:
    legacy = make_legacy_090_archive(build_private_archive(rin_verified_release))
    before = canonical_bytes(DEFAULT_MIGRATIONS.describe())

    preview_karc_migration(legacy, "1.0.0", SCHEMAS)

    assert canonical_bytes(DEFAULT_MIGRATIONS.describe()) == before


def test_public_archive_uses_the_exact_registered_public_schema_vector(
    rin_public_verified_release: dict[str, Any],
) -> None:
    current = build_public_archive(rin_public_verified_release)
    legacy = make_legacy_090_archive(current)

    preview = preview_karc_migration(legacy, "1.0.0", SCHEMAS)

    assert preview.output_archive == current
    assert preview.plan["source_schema_versions"][
        "publication_readiness_report"
    ] == "0.9.0"
    assert preview.plan["target_schema_versions"][
        "publication_readiness_report"
    ] == "1.0.0"


def test_unregistered_path_and_downgrade_fail_closed(
    rin_verified_release: dict[str, Any],
) -> None:
    current = build_private_archive(rin_verified_release)
    legacy = make_legacy_090_archive(current)

    _assert_code(
        "MIGRATION_UNAVAILABLE",
        preview_karc_migration,
        legacy,
        "1.1.0",
        SCHEMAS,
    )
    _assert_code(
        "MIGRATION_DOWNGRADE_UNSUPPORTED",
        preview_karc_migration,
        current,
        "0.9.0",
        SCHEMAS,
    )


def test_registry_cycle_is_rejected(
    rin_verified_release: dict[str, Any],
) -> None:
    legacy = make_legacy_090_archive(build_private_archive(rin_verified_release))
    step_down = MigrationStep(
        step_id="cycle-down",
        source_format_version="0.9.0",
        target_format_version="0.8.0",
        source_schema_versions=PRIVATE_090,
        target_schema_versions=PRIVATE_090,
        transform=lambda payload: payload,
    )
    step_up = MigrationStep(
        step_id="cycle-up",
        source_format_version="0.8.0",
        target_format_version="0.9.0",
        source_schema_versions=PRIVATE_090,
        target_schema_versions=PRIVATE_090,
        transform=lambda payload: payload,
    )
    registry = MigrationRegistry((step_down, step_up))

    _assert_code(
        "MIGRATION_CYCLE",
        preview_karc_migration,
        legacy,
        "1.0.0",
        SCHEMAS,
        registry=registry,
    )


def test_migration_rejects_changed_identity_and_noncanonical_output(
    rin_verified_release: dict[str, Any],
) -> None:
    current = build_private_archive(rin_verified_release)
    legacy = make_legacy_090_archive(current)
    valid_output = preview_karc_migration(legacy, "1.0.0", SCHEMAS).output_archive

    def changed_identity(_: bytes) -> bytes:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["manifest.json"]["character_id"] = "other-character"

        return rewrite_archive(valid_output, mutate)

    changed = MigrationRegistry(
        (
            MigrationStep(
                step_id="changed-identity",
                source_format_version="0.9.0",
                target_format_version="1.0.0",
                source_schema_versions=deepcopy(PRIVATE_090),
                target_schema_versions=deepcopy(PRIVATE_100),
                transform=changed_identity,
            ),
        )
    )
    noncanonical = MigrationRegistry(
        (
            MigrationStep(
                step_id="noncanonical-output",
                source_format_version="0.9.0",
                target_format_version="1.0.0",
                source_schema_versions=deepcopy(PRIVATE_090),
                target_schema_versions=deepcopy(PRIVATE_100),
                transform=lambda _: b"not a canonical archive",
            ),
        )
    )

    _assert_code(
        "MIGRATION_IDENTITY_CHANGED",
        preview_karc_migration,
        legacy,
        "1.0.0",
        SCHEMAS,
        registry=changed,
    )
    _assert_code(
        "MIGRATION_OUTPUT_INVALID",
        preview_karc_migration,
        legacy,
        "1.0.0",
        SCHEMAS,
        registry=noncanonical,
    )


def test_archive_provided_migration_code_is_never_accepted(
    rin_verified_release: dict[str, Any],
) -> None:
    legacy = make_legacy_090_archive(build_private_archive(rin_verified_release))

    _assert_code(
        "MIGRATION_INPUT_INVALID",
        preview_karc_migration,
        add_archive_code(legacy),
        "1.0.0",
        SCHEMAS,
    )


def test_migration_never_repairs_a_stale_input_member_hash(
    rin_verified_release: dict[str, Any],
) -> None:
    legacy = make_legacy_090_archive(build_private_archive(rin_verified_release))

    def mutate_without_rebinding(documents: dict[str, dict[str, Any]]) -> None:
        documents["pack/compiled.json"]["behavior"]["correction_style"] = (
            "quiet"
        )

    stale = rewrite_archive(legacy, mutate_without_rebinding)

    _assert_code(
        "MIGRATION_INPUT_INVALID",
        preview_karc_migration,
        stale,
        "1.0.0",
        SCHEMAS,
    )
