from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kokoroarc.distribution.archive import load_karc_archive
from kokoroarc.distribution.migrations import apply_karc_migration
from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import build_private_archive, make_legacy_090_archive


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def _assert_code(code: str, function: Any, **kwargs: Any) -> None:
    with pytest.raises(KokoroError) as caught:
        function(**kwargs)
    assert caught.value.code == code


def test_apply_writes_a_new_archive_without_touching_input(
    rin_verified_release: dict[str, Any], tmp_path: Path
) -> None:
    legacy = make_legacy_090_archive(build_private_archive(rin_verified_release))
    source = tmp_path / "rin-legacy.karc"
    target = tmp_path / "rin-current.karc"
    source.write_bytes(legacy)

    plan = apply_karc_migration(
        input_path=source,
        output_path=target,
        target_format_version="1.0.0",
        schemas=SCHEMAS,
    )

    assert source.read_bytes() == legacy
    assert target.is_file()
    assert plan["mode"] == "applied"
    assert load_karc_archive(target.read_bytes(), SCHEMAS).manifest[
        "format_version"
    ] == "1.0.0"


def test_apply_never_overwrites_input_or_existing_output(
    rin_verified_release: dict[str, Any], tmp_path: Path
) -> None:
    legacy = make_legacy_090_archive(build_private_archive(rin_verified_release))
    source = tmp_path / "rin-legacy.karc"
    existing = tmp_path / "existing.karc"
    source.write_bytes(legacy)
    existing.write_bytes(b"keep me")

    _assert_code(
        "MIGRATION_OUTPUT_CONFLICT",
        apply_karc_migration,
        input_path=source,
        output_path=source,
        target_format_version="1.0.0",
        schemas=SCHEMAS,
    )
    _assert_code(
        "MIGRATION_OUTPUT_EXISTS",
        apply_karc_migration,
        input_path=source,
        output_path=existing,
        target_format_version="1.0.0",
        schemas=SCHEMAS,
    )
    assert source.read_bytes() == legacy
    assert existing.read_bytes() == b"keep me"


def test_apply_rejects_an_absent_input(tmp_path: Path) -> None:
    _assert_code(
        "MIGRATION_INPUT_NOT_FOUND",
        apply_karc_migration,
        input_path=tmp_path / "missing.karc",
        output_path=tmp_path / "output.karc",
        target_format_version="1.0.0",
        schemas=SCHEMAS,
    )


def test_apply_validates_the_applied_plan_before_publishing(
    rin_verified_release: dict[str, Any], tmp_path: Path
) -> None:
    legacy = make_legacy_090_archive(build_private_archive(rin_verified_release))
    source = tmp_path / "rin-legacy.karc"
    target = tmp_path / "rin-current.karc"
    source.write_bytes(legacy)

    class RejectAppliedPlan:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-migration-plan" and instance["mode"] == "applied":
                raise KokoroError("SCHEMA_VALIDATION_FAILED", "rejected")

    _assert_code(
        "MIGRATION_OUTPUT_INVALID",
        apply_karc_migration,
        input_path=source,
        output_path=target,
        target_format_version="1.0.0",
        schemas=RejectAppliedPlan(),
    )
    assert source.read_bytes() == legacy
    assert not target.exists()
