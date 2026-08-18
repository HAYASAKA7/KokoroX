"""Security boundaries for scoped character defaults."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import pytest

import kokoroarc.cli as cli_module
import kokoroarc.distribution.defaults as defaults_module
from kokoroarc.config import Settings
from kokoroarc.distribution.defaults import (
    clear_character_default,
    empty_character_default,
    load_character_default,
    set_character_default,
)
from kokoroarc.distribution.installer import install_karc_archive
from kokoroarc.distribution.registry import resolve_install_scope
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import build_private_archive


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


class _ReplacingSchemas:
    def __init__(self, target: Path) -> None:
        self._target = target

    def validate(self, name: str, instance: Any) -> None:
        SCHEMAS.validate(name, instance)
        replacement = self._target.with_suffix(".replacement")
        replacement.write_bytes(self._target.read_bytes())
        os.replace(replacement, self._target)


class _ReplacingInstalledSchemas:
    def __init__(self, target: Path) -> None:
        self._target = target
        self._replaced = False

    def validate(self, name: str, instance: Any) -> None:
        SCHEMAS.validate(name, instance)
        if self._replaced:
            return
        self._replaced = True
        replacement = self._target.with_suffix(".replacement")
        replacement.write_bytes(self._target.read_bytes())
        os.replace(replacement, self._target)


class _ReplacingWriterSchemas:
    def __init__(self, target: Path) -> None:
        self._target = target
        self._config_calls = 0

    def validate(self, name: str, instance: Any) -> None:
        SCHEMAS.validate(name, instance)
        if name != "character-default-config":
            return
        self._config_calls += 1
        if self._config_calls != 2:
            return
        replacement = self._target.with_suffix(".replacement")
        replacement.write_bytes(self._target.read_bytes())
        os.replace(replacement, self._target)


class _ReplacingProjectionSchemas:
    def __init__(self, target: Path) -> None:
        self._target = target
        self.replaced = False

    def validate(self, name: str, instance: Any) -> None:
        SCHEMAS.validate(name, instance)
        if self.replaced or name != "compiled-pack" or not self._target.exists():
            return
        replacement = self._target.with_suffix(".replacement")
        replacement.write_bytes(self._target.read_bytes())
        os.replace(replacement, self._target)
        self.replaced = True


def test_load_rejects_same_byte_config_replacement_during_schema_callback(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    target = data_root / "config" / "global.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(
        canonical_bytes(empty_character_default(resolve_install_scope()))
    )

    with pytest.raises(KokoroError) as raised:
        load_character_default(data_root, _ReplacingSchemas(target))

    assert raised.value.code == "KARC_DEFAULT_INPUT_MUTATION"


def test_load_normalizes_deep_json_parser_failure(tmp_path: Path) -> None:
    target = tmp_path / "data" / "config" / "global.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(
        b'{"nested":'
        + (b'[' * 1_100)
        + b'0'
        + (b']' * 1_100)
        + b'}'
    )

    with pytest.raises(KokoroError) as raised:
        load_character_default(tmp_path / "data", SCHEMAS)

    assert raised.value.code == "KARC_DEFAULT_CONFIG_INVALID"


def test_resolver_rejects_member_rebase_at_first_schema_callback(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    installed = install_karc_archive(source, data_root, SCHEMAS)
    compiled = (
        data_root
        / "installed"
        / Path(installed["relative_path"])
        / "pack"
        / "compiled.json"
    )

    with pytest.raises(KokoroError) as raised:
        defaults_module._resolve_installed_binding(
            data_root,
            "rin-aster",
            _ReplacingInstalledSchemas(compiled),
        )

    assert raised.value.code == "KARC_DEFAULT_INPUT_MUTATION"


def test_first_set_never_overwrites_config_appearing_at_cutover(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    target = data_root / "config" / "global.json"
    competing = empty_character_default(resolve_install_scope())
    competing["revision"] = 9
    competing_bytes = canonical_bytes(competing)
    real_link = os.link
    called = False

    def appear_then_link(source_path: Path, target_path: Path) -> None:
        nonlocal called
        called = True
        Path(target_path).write_bytes(competing_bytes)
        real_link(source_path, target_path)

    monkeypatch.setattr(defaults_module.os, "link", appear_then_link)

    with pytest.raises(KokoroError) as raised:
        set_character_default(data_root, "rin-aster", SCHEMAS)

    assert called is True
    assert raised.value.code == "KARC_DEFAULT_CONFLICT"
    assert target.read_bytes() == competing_bytes


def test_set_rejects_installed_member_replacement_after_cutover(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    installed = install_karc_archive(source, data_root, SCHEMAS)
    compiled = (
        data_root
        / "installed"
        / Path(installed["relative_path"])
        / "pack"
        / "compiled.json"
    )
    real_publish = defaults_module._publish_config

    def publish_then_replace(*args: Any, **kwargs: Any) -> None:
        real_publish(*args, **kwargs)
        replacement = compiled.with_suffix(".replacement")
        replacement.write_bytes(compiled.read_bytes())
        os.replace(replacement, compiled)

    monkeypatch.setattr(
        defaults_module,
        "_publish_config",
        publish_then_replace,
    )

    with pytest.raises(KokoroError) as raised:
        set_character_default(data_root, "rin-aster", SCHEMAS)

    assert raised.value.code in {
        "KARC_DEFAULT_INPUT_MUTATION",
        "KARC_DEFAULT_STALE",
    }


def test_set_rechecks_staging_identity_immediately_before_cutover(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    target = data_root / "config" / "global.json"
    real_require = defaults_module._require_write_boundary
    replaced = False

    def replace_staging_after_boundary(*args: Any) -> None:
        nonlocal replaced
        real_require(*args)
        if replaced:
            return
        staging_files = list(
            target.parent.glob(f".{target.name}.staging-*")
        )
        if not staging_files:
            return
        staging = staging_files[0]
        replacement = staging.with_suffix(".replacement")
        replacement.write_bytes(staging.read_bytes())
        os.replace(replacement, staging)
        replaced = True

    monkeypatch.setattr(
        defaults_module,
        "_require_write_boundary",
        replace_staging_after_boundary,
    )

    with pytest.raises(KokoroError) as raised:
        set_character_default(data_root, "rin-aster", SCHEMAS)

    assert replaced is True
    assert raised.value.code == "KARC_DEFAULT_CLEANUP_FAILED"
    assert not target.exists()
    assert len(list(target.parent.glob(f".{target.name}.staging-*"))) == 1


def test_writer_rejects_same_byte_config_replacement_during_callback(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    target = data_root / "config" / "global.json"
    target.parent.mkdir(parents=True)
    initial = empty_character_default(resolve_install_scope())
    initial_bytes = canonical_bytes(initial)
    target.write_bytes(initial_bytes)

    with pytest.raises(KokoroError) as raised:
        set_character_default(
            data_root,
            "rin-aster",
            _ReplacingWriterSchemas(target),
        )

    assert raised.value.code in {
        "KARC_DEFAULT_CONFLICT",
        "KARC_DEFAULT_INPUT_MUTATION",
    }
    assert target.read_bytes() == initial_bytes


def test_parent_fsync_failure_is_retried_before_idempotent_success(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    target = data_root / "config" / "global.json"
    real_fsync = defaults_module._fsync_directory
    failures = 0

    def fail_visible_parent(path: Path) -> None:
        nonlocal failures
        if Path(path) == target.parent and target.exists():
            failures += 1
            raise KokoroError(
                "KARC_DEFAULT_DURABILITY_FAILED",
                "Character default durability could not be confirmed.",
            )
        real_fsync(path)

    monkeypatch.setattr(
        defaults_module,
        "_fsync_directory",
        fail_visible_parent,
    )

    with pytest.raises(KokoroError) as first_error:
        set_character_default(data_root, "rin-aster", SCHEMAS)
    assert first_error.value.code == "KARC_DEFAULT_DURABILITY_FAILED"
    assert target.exists()

    with pytest.raises(KokoroError) as retry_error:
        set_character_default(data_root, "rin-aster", SCHEMAS)
    assert retry_error.value.code == "KARC_DEFAULT_DURABILITY_FAILED"
    assert failures == 2

    monkeypatch.setattr(defaults_module, "_fsync_directory", real_fsync)
    recovered = set_character_default(data_root, "rin-aster", SCHEMAS)
    assert recovered["revision"] == 1


def test_replace_failure_preserves_old_config_and_removes_staging(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    current = set_character_default(data_root, "rin-aster", SCHEMAS)
    target = data_root / "config" / "global.json"
    current_bytes = canonical_bytes(current)
    real_replace = os.replace

    def fail_target_replace(source_path: Path, target_path: Path) -> None:
        if Path(target_path) == target:
            raise PermissionError("injected replace failure")
        real_replace(source_path, target_path)

    monkeypatch.setattr(defaults_module.os, "replace", fail_target_replace)

    with pytest.raises(KokoroError) as raised:
        clear_character_default(data_root, SCHEMAS)

    assert raised.value.code == "KARC_DEFAULT_WRITE_FAILED"
    assert target.read_bytes() == current_bytes
    assert list(target.parent.glob(f".{target.name}.staging-*")) == []


def test_same_scope_lock_contention_fails_without_writing(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    current = set_character_default(data_root, "rin-aster", SCHEMAS)
    target = data_root / "config" / "global.json"
    scope = resolve_install_scope()

    with defaults_module._acquire_config_lock(target.parent, scope):
        with pytest.raises(KokoroError) as raised:
            clear_character_default(data_root, SCHEMAS)

    assert raised.value.code == "KARC_DEFAULT_LOCKED"
    assert target.read_bytes() == canonical_bytes(current)


def test_clear_rechecks_existing_config_identity_before_cutover(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    current = set_character_default(data_root, "rin-aster", SCHEMAS)
    target = data_root / "config" / "global.json"
    current_bytes = canonical_bytes(current)
    real_require = defaults_module._require_write_boundary
    replaced = False

    def replace_config_after_boundary(*args: Any) -> None:
        nonlocal replaced
        real_require(*args)
        if replaced or not list(
            target.parent.glob(f".{target.name}.staging-*")
        ):
            return
        replacement = target.with_suffix(".replacement")
        replacement.write_bytes(target.read_bytes())
        os.replace(replacement, target)
        replaced = True

    monkeypatch.setattr(
        defaults_module,
        "_require_write_boundary",
        replace_config_after_boundary,
    )

    with pytest.raises(KokoroError) as raised:
        clear_character_default(data_root, SCHEMAS)

    assert replaced is True
    assert raised.value.code == "KARC_DEFAULT_CONFLICT"
    assert target.read_bytes() == current_bytes
    assert list(target.parent.glob(f".{target.name}.staging-*")) == []


def test_cleanup_failure_is_not_hidden_by_replace_failure(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    current = set_character_default(data_root, "rin-aster", SCHEMAS)
    target = data_root / "config" / "global.json"
    current_bytes = canonical_bytes(current)
    real_replace = os.replace
    real_unlink = Path.unlink

    def fail_target_replace(source_path: Path, target_path: Path) -> None:
        if Path(target_path) == target:
            raise PermissionError("injected replace failure")
        real_replace(source_path, target_path)

    def fail_staging_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.name.startswith(f".{target.name}.staging-"):
            raise PermissionError("injected cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(defaults_module.os, "replace", fail_target_replace)
    monkeypatch.setattr(Path, "unlink", fail_staging_unlink)

    with pytest.raises(KokoroError) as raised:
        clear_character_default(data_root, SCHEMAS)

    assert raised.value.code == "KARC_DEFAULT_CLEANUP_FAILED"
    assert target.read_bytes() == current_bytes
    assert len(list(target.parent.glob(f".{target.name}.staging-*"))) == 1


def test_session_start_rejects_projection_replacement_during_validation(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    set_character_default(data_root, "rin-aster", SCHEMAS)
    selection = defaults_module.resolve_character_selection(data_root, SCHEMAS)
    compiled = defaults_module.load_selected_compiled(
        data_root,
        selection,
        SCHEMAS,
    )
    target = (
        data_root
        / "compiled"
        / f"rin-aster-{compiled['source_hash'][:16]}.json"
    )
    replacing = _ReplacingProjectionSchemas(target)
    settings = Settings(data_dir=data_root, schema_dir=Path("schemas/v1"))
    arguments = argparse.Namespace(
        character=None,
        session="projection-replaced",
        workspace=None,
    )

    with pytest.raises(KokoroError) as raised:
        cli_module._handle_session_start(arguments, settings, replacing)

    assert replacing.replaced is True
    assert raised.value.code in {
        "KARC_DEFAULT_INPUT_MUTATION",
        "COMPILED_PATH_UNSAFE",
    }
    assert not (data_root / "sessions").exists()


def test_session_start_rejects_source_replacement_during_projection_write(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    installed = install_karc_archive(source, data_root, SCHEMAS)
    set_character_default(data_root, "rin-aster", SCHEMAS)
    installed_compiled = (
        data_root
        / "installed"
        / Path(installed["relative_path"])
        / "pack"
        / "compiled.json"
    )
    real_write = cli_module._write_projection_staging
    replaced = False

    def write_then_replace(
        target: Path,
        payload: bytes,
        node: tuple[int, int, int],
    ) -> None:
        nonlocal replaced
        real_write(target, payload, node)
        replacement = installed_compiled.with_suffix(".replacement")
        replacement.write_bytes(installed_compiled.read_bytes())
        os.replace(replacement, installed_compiled)
        replaced = True

    monkeypatch.setattr(
        cli_module,
        "_write_projection_staging",
        write_then_replace,
    )
    settings = Settings(data_dir=data_root, schema_dir=Path("schemas/v1"))
    arguments = argparse.Namespace(
        character=None,
        session="source-replaced",
        workspace=None,
    )

    with pytest.raises(KokoroError) as raised:
        cli_module._handle_session_start(arguments, settings, SCHEMAS)

    assert replaced is True
    assert raised.value.code in {
        "KARC_DEFAULT_INPUT_MUTATION",
        "KARC_DEFAULT_STALE",
    }
    assert not (data_root / "sessions").exists()


def test_session_start_rejects_projection_replacement_at_write_boundary(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    set_character_default(data_root, "rin-aster", SCHEMAS)
    real_write = cli_module._write_projection_staging
    replaced = False

    def write_then_replace(
        target: Path,
        payload: bytes,
        node: tuple[int, int, int],
    ) -> None:
        nonlocal replaced
        real_write(target, payload, node)
        replacement = target.with_suffix(".replacement")
        replacement.write_bytes(target.read_bytes())
        os.replace(replacement, target)
        replaced = True

    monkeypatch.setattr(
        cli_module,
        "_write_projection_staging",
        write_then_replace,
    )
    settings = Settings(data_dir=data_root, schema_dir=Path("schemas/v1"))
    arguments = argparse.Namespace(
        character=None,
        session="projection-write-replaced",
        workspace=None,
    )

    with pytest.raises(KokoroError) as raised:
        cli_module._handle_session_start(arguments, settings, SCHEMAS)

    assert replaced is True
    assert raised.value.code in {
        "KARC_DEFAULT_INPUT_MUTATION",
        "COMPILED_PATH_UNSAFE",
        "COMPILED_WRITE_FAILED",
    }
    assert not (data_root / "sessions").exists()
