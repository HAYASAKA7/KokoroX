from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import kokoroarc.distribution.migrations as migrations
from kokoroarc.distribution.migrations import apply_karc_migration
from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import build_private_archive, make_legacy_090_archive


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def _legacy_release(release: dict[str, Any]) -> bytes:
    return make_legacy_090_archive(build_private_archive(release))


def _assert_code(code: str, function: Any, **kwargs: Any) -> None:
    with pytest.raises(KokoroError) as caught:
        function(**kwargs)
    assert caught.value.code == code


def test_apply_rejects_a_symlink_input_without_touching_target(
    rin_verified_release: dict[str, Any], tmp_path: Path
) -> None:
    real = tmp_path / "real.karc"
    alias = tmp_path / "alias.karc"
    target = tmp_path / "current.karc"
    real.write_bytes(_legacy_release(rin_verified_release))
    try:
        alias.symlink_to(real.name)
    except OSError as error:
        pytest.skip(f"File symlinks are unavailable: {error}")

    _assert_code(
        "MIGRATION_INPUT_INVALID",
        apply_karc_migration,
        input_path=alias,
        output_path=target,
        target_format_version="1.0.0",
        schemas=SCHEMAS,
    )
    assert not target.exists()


def test_apply_rejects_a_junction_marked_output_parent(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.karc"
    output_parent = tmp_path / "marked-parent"
    target = output_parent / "current.karc"
    output_parent.mkdir()
    source.write_bytes(_legacy_release(rin_verified_release))
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def marked(path: Path) -> bool:
        return path == output_parent or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", marked, raising=False)

    _assert_code(
        "MIGRATION_PATH_INVALID",
        apply_karc_migration,
        input_path=source,
        output_path=target,
        target_format_version="1.0.0",
        schemas=SCHEMAS,
    )
    assert not target.exists()


def test_atomic_output_conflict_preserves_winner_and_cleans_staging(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.karc"
    target = tmp_path / "current.karc"
    source.write_bytes(_legacy_release(rin_verified_release))

    def lose_race(_staging: Path, destination: Path) -> None:
        Path(destination).write_bytes(b"winner")
        raise FileExistsError

    monkeypatch.setattr(migrations.os, "link", lose_race)

    _assert_code(
        "MIGRATION_OUTPUT_EXISTS",
        apply_karc_migration,
        input_path=source,
        output_path=target,
        target_format_version="1.0.0",
        schemas=SCHEMAS,
    )
    assert target.read_bytes() == b"winner"
    assert list(tmp_path.glob(".current.karc.*.tmp")) == []


def test_apply_rechecks_source_with_bounded_handle_reads(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.karc"
    target = tmp_path / "current.karc"
    source.write_bytes(_legacy_release(rin_verified_release))
    real_read_bytes = Path.read_bytes

    def reject_unbounded_source_read(path: Path) -> bytes:
        if path == source:
            raise AssertionError("source must be rechecked with a bounded handle read")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_unbounded_source_read)

    plan = apply_karc_migration(
        input_path=source,
        output_path=target,
        target_format_version="1.0.0",
        schemas=SCHEMAS,
    )

    assert plan["mode"] == "applied"
    assert target.is_file()
