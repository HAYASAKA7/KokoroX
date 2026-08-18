"""Unit coverage for scoped character-default selection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import kokoroarc.distribution.defaults as defaults_module
import pytest

from kokoroarc.distribution.defaults import (
    CharacterSelection,
    empty_character_default,
    load_character_default,
    resolve_character_selection,
)
from kokoroarc.distribution.registry import InstallScope, resolve_install_scope
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def _binding(name: str) -> dict[str, str]:
    digit = "1" if name == "global" else "2"
    return {
        "installation_id": f"install-{name}",
        "namespace": "original",
        "character_id": f"{name}-character",
        "character_version": "1.0.0",
        "archive_sha256": digit * 64,
        "compiled_sha256": digit * 64,
    }


def _write_config(
    data_root: Path,
    scope: InstallScope,
    config: dict[str, Any],
) -> None:
    relative = (
        Path("config/global.json")
        if scope.kind == "global"
        else Path("config/workspaces") / f"{scope.workspace_id}.json"
    )
    path = data_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(config))


def test_empty_global_default_is_canonical_and_schema_valid() -> None:
    config = empty_character_default(resolve_install_scope())

    SCHEMAS.validate("character-default-config", config)

    assert config["scope"] == "global"
    assert config["workspace_id"] is None
    assert config["revision"] == 0
    assert config["binding"] is None
    assert config["activation_policy"] == "explicit_only"


def test_empty_workspace_default_is_canonical_and_schema_valid(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = empty_character_default(resolve_install_scope(workspace))

    SCHEMAS.validate("character-default-config", config)
    assert config["scope"] == "workspace"
    assert config["workspace_id"] == resolve_install_scope(workspace).workspace_id
    assert config["artifact_id"].startswith("config/")


def test_explicit_and_session_short_circuit_lower_precedence(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "must-not-be-created"
    base = _binding("global")
    session_binding = {**base, "installation_id": "install-session"}
    explicit_binding = {**base, "installation_id": "install-explicit"}

    selected = resolve_character_selection(
        data_root,
        SCHEMAS,
        explicit_binding=explicit_binding,
        active_session_binding=session_binding,
    )

    assert isinstance(selected, CharacterSelection)
    assert selected.source == "explicit"
    assert selected.binding == explicit_binding
    assert selected.binding is not selected.binding
    assert resolve_character_selection(
        data_root,
        SCHEMAS,
        active_session_binding=session_binding,
    ).source == "active_session"
    assert resolve_character_selection(data_root, SCHEMAS).source == "none"
    assert not data_root.exists()


def test_absent_load_is_read_only(tmp_path: Path) -> None:
    data_root = tmp_path / "absent"

    loaded = load_character_default(data_root, SCHEMAS)

    assert loaded == empty_character_default(resolve_install_scope())
    assert not data_root.exists()


def test_workspace_load_uses_canonical_workspace_id(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    scope = resolve_install_scope(workspace)
    config = empty_character_default(scope)
    _write_config(data_root, scope, config)

    loaded = load_character_default(
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )

    assert loaded == config
    assert list(workspace.iterdir()) == []


def test_resolve_absent_registry_is_not_installed_and_read_only(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "absent"

    with pytest.raises(KokoroError) as raised:
        defaults_module._resolve_installed_binding(
            data_root,
            "rin-aster",
            SCHEMAS,
        )

    assert raised.value.code == "KARC_DEFAULT_NOT_INSTALLED"
    assert not data_root.exists()
