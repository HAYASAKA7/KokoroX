"""Integration coverage for scoped installed character defaults."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import kokoroarc.distribution.defaults as defaults_module
import pytest
from kokoroarc.distribution.defaults import (
    clear_character_default,
    empty_character_default,
    resolve_character_selection,
    set_character_default,
)
from kokoroarc.distribution.installer import (
    install_karc_archive,
    remove_installed_pack,
)
from kokoroarc.distribution.registry import (
    InstallScope,
    load_installed_registry,
    resolve_install_scope,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import build_private_archive


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RIN_PACK = REPOSITORY_ROOT / "characters" / "original" / "rin-aster"


def _run_cli(data_root: Path, *arguments: str) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["KOKOROX_DATA_DIR"] = str(data_root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments, "--json"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout
    assert completed.stderr == ""
    return json.loads(completed.stdout)


def _run_cli_error(data_root: Path, *arguments: str) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["KOKOROX_DATA_DIR"] = str(data_root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments, "--json"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 2
    assert completed.stderr == ""
    return json.loads(completed.stdout)


def _install_rin(
    release: dict[str, Any],
    data_root: Path,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    source = data_root.parent / (
        "rin-workspace.karc" if workspace_root is not None else "rin-global.karc"
    )
    source.write_bytes(build_private_archive(release))
    return install_karc_archive(
        source,
        data_root,
        SCHEMAS,
        workspace_root=workspace_root,
    )


def _write_default(
    data_root: Path,
    scope: InstallScope,
    binding: dict[str, str] | None,
    *,
    revision: int = 1,
) -> None:
    config = empty_character_default(scope)
    config["revision"] = revision
    config["binding"] = binding
    target = (
        data_root / "config" / "global.json"
        if scope.kind == "global"
        else data_root
        / "config"
        / "workspaces"
        / f"{scope.workspace_id}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_bytes(config))


def test_resolve_unique_installed_binding(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    plan = _install_rin(rin_verified_release, data_root)

    binding = defaults_module._resolve_installed_binding(
        data_root,
        "rin-aster",
        SCHEMAS,
        namespace="original",
    )

    assert binding == {
        "installation_id": plan["installation_id"],
        "namespace": "original",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "archive_sha256": plan["archive_sha256"],
        "compiled_sha256": plan["compiled_sha256"],
    }


def test_global_config_resolves_only_the_exact_installed_binding(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _install_rin(rin_verified_release, data_root)
    binding = defaults_module._resolve_installed_binding(
        data_root,
        "rin-aster",
        SCHEMAS,
    )
    config = empty_character_default(resolve_install_scope())
    config["revision"] = 1
    config["binding"] = binding
    target = data_root / "config" / "global.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(canonical_bytes(config))

    selection = resolve_character_selection(data_root, SCHEMAS)

    assert selection.source == "global_default"
    assert selection.binding == binding


def test_resolve_rejects_replaced_archive_as_stale(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    plan = _install_rin(rin_verified_release, data_root)
    archive_path = data_root / "archives" / f"{plan['archive_sha256']}.karc"
    archive_path.write_bytes(b"not-a-karc")

    with pytest.raises(KokoroError) as raised:
        defaults_module._resolve_installed_binding(
            data_root,
            "rin-aster",
            SCHEMAS,
        )

    assert raised.value.code == "KARC_DEFAULT_STALE"


def test_workspace_override_null_fallback_and_stale_fail_closed(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _install_rin(rin_verified_release, data_root)
    _install_rin(
        rin_verified_release,
        data_root,
        workspace_root=workspace,
    )
    global_binding = defaults_module._resolve_installed_binding(
        data_root,
        "rin-aster",
        SCHEMAS,
    )
    workspace_binding = defaults_module._resolve_installed_binding(
        data_root,
        "rin-aster",
        SCHEMAS,
        workspace_root=workspace,
    )
    global_scope = resolve_install_scope()
    workspace_scope = resolve_install_scope(workspace)
    _write_default(data_root, global_scope, global_binding)
    _write_default(data_root, workspace_scope, workspace_binding)

    selected = resolve_character_selection(
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )
    assert selected.source == "workspace_default"

    _write_default(data_root, workspace_scope, None, revision=2)
    selected = resolve_character_selection(
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )
    assert selected.source == "global_default"

    stale = {**workspace_binding, "archive_sha256": "0" * 64}
    _write_default(data_root, workspace_scope, stale, revision=3)
    with pytest.raises(KokoroError) as raised:
        resolve_character_selection(
            data_root,
            SCHEMAS,
            workspace_root=workspace,
        )
    assert raised.value.code == "KARC_DEFAULT_STALE"


def test_omitted_version_is_ambiguous_but_exact_version_resolves(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _install_rin(rin_verified_release, data_root)
    registry = load_installed_registry(data_root, SCHEMAS)
    original = registry["entries"]["original/rin-aster/1.0.0"]
    registry["entries"]["original/rin-aster/2.0.0"] = dict(original)
    registry["revision"] += 1
    registry_path = data_root / "registry" / "global.json"
    registry_path.write_bytes(canonical_bytes(registry))

    with pytest.raises(KokoroError) as raised:
        defaults_module._resolve_installed_binding(
            data_root,
            "rin-aster",
            SCHEMAS,
        )
    assert raised.value.code == "KARC_DEFAULT_AMBIGUOUS"

    exact = defaults_module._resolve_installed_binding(
        data_root,
        "rin-aster",
        SCHEMAS,
        version="1.0.0",
    )
    assert exact["character_version"] == "1.0.0"


def test_set_repeat_clear_repeat_has_exact_revisions(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    plan = _install_rin(rin_verified_release, data_root)

    first = set_character_default(data_root, "rin-aster", SCHEMAS)
    repeated = set_character_default(data_root, "rin-aster", SCHEMAS)
    cleared = clear_character_default(data_root, SCHEMAS)
    cleared_again = clear_character_default(data_root, SCHEMAS)

    assert first["revision"] == 1
    assert first["binding"]["installation_id"] == plan["installation_id"]
    assert repeated == first
    assert cleared["revision"] == 2
    assert cleared["binding"] is None
    assert cleared_again == cleared
    assert not (data_root / "sessions").exists()
    assert not (data_root / "state").exists()
    assert not (data_root / "events").exists()


def test_default_blocks_removal_until_cleared(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _install_rin(rin_verified_release, data_root)
    set_character_default(data_root, "rin-aster", SCHEMAS)

    with pytest.raises(KokoroError) as raised:
        remove_installed_pack(
            data_root,
            "original",
            "rin-aster",
            "1.0.0",
            SCHEMAS,
        )

    assert raised.value.code == "KARC_REMOVE_REFERENCED"
    assert raised.value.details == {"references": ["default"]}

    clear_character_default(data_root, SCHEMAS)
    removed = remove_installed_pack(
        data_root,
        "original",
        "rin-aster",
        "1.0.0",
        SCHEMAS,
    )
    assert removed["archive_removed"] is True


def test_workspace_set_clear_has_independent_revisions_and_no_workspace_writes(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = _install_rin(
        rin_verified_release,
        data_root,
        workspace_root=workspace,
    )

    first = set_character_default(
        data_root,
        "rin-aster",
        SCHEMAS,
        workspace_root=workspace,
    )
    repeated = set_character_default(
        data_root,
        "rin-aster",
        SCHEMAS,
        workspace_root=workspace,
    )
    cleared = clear_character_default(
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )
    cleared_again = clear_character_default(
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )

    assert first["scope"] == "workspace"
    assert first["revision"] == 1
    assert first["binding"]["installation_id"] == plan["installation_id"]
    assert repeated == first
    assert cleared["revision"] == 2
    assert cleared["binding"] is None
    assert cleared_again == cleared
    assert list(workspace.iterdir()) == []


def test_config_default_cli_global_workflow_is_explicit_only(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    plan = _install_rin(rin_verified_release, data_root)

    first = _run_cli(
        data_root,
        "config",
        "default",
        "set",
        "--character",
        "rin-aster",
    )
    shown = _run_cli(data_root, "config", "default", "show")
    repeated = _run_cli(
        data_root,
        "config",
        "default",
        "set",
        "--character",
        "rin-aster",
    )
    cleared = _run_cli(data_root, "config", "default", "clear")

    assert first["ok"] is True
    assert first["activates_character"] is False
    assert first["default"]["revision"] == 1
    assert first["default"]["binding"]["installation_id"] == plan[
        "installation_id"
    ]
    assert shown == first
    assert repeated == first
    assert cleared["default"]["revision"] == 2
    assert cleared["default"]["binding"] is None
    assert cleared["activates_character"] is False
    assert not (data_root / "sessions").exists()
    assert not (data_root / "state").exists()
    assert not (data_root / "events").exists()


def test_load_selected_compiled_revalidates_the_default_installation(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _install_rin(rin_verified_release, data_root)
    set_character_default(data_root, "rin-aster", SCHEMAS)
    selection = resolve_character_selection(data_root, SCHEMAS)

    compiled = defaults_module.load_selected_compiled(
        data_root,
        selection,
        SCHEMAS,
    )

    SCHEMAS.validate("compiled-pack", compiled)
    assert selection.source == "global_default"
    assert compiled["character_id"] == "rin-aster"
    assert compiled["character_version"] == "1.0.0"


def test_workspace_then_global_default_starts_only_explicit_sessions(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _install_rin(rin_verified_release, data_root)
    _install_rin(
        rin_verified_release,
        data_root,
        workspace_root=workspace,
    )

    global_default = _run_cli(
        data_root,
        "config",
        "default",
        "set",
        "--character",
        "rin-aster",
    )
    workspace_default = _run_cli(
        data_root,
        "config",
        "default",
        "set",
        "--character",
        "rin-aster",
        "--scope",
        "workspace",
        "--workspace",
        str(workspace),
    )
    assert global_default["activates_character"] is False
    assert workspace_default["activates_character"] is False
    assert not (data_root / "sessions").exists()

    workspace_session = _run_cli(
        data_root,
        "session",
        "start",
        "--session",
        "s-workspace",
        "--workspace",
        str(workspace),
    )
    _run_cli(
        data_root,
        "config",
        "default",
        "clear",
        "--scope",
        "workspace",
        "--workspace",
        str(workspace),
    )
    global_session = _run_cli(
        data_root,
        "session",
        "start",
        "--session",
        "s-global",
    )
    workspace_context = _run_cli(
        data_root,
        "runtime",
        "context",
        "--session",
        "s-workspace",
        "--locale",
        "zh-CN",
        "--scenario",
        "debugging",
    )
    global_context = _run_cli(
        data_root,
        "runtime",
        "context",
        "--session",
        "s-global",
        "--locale",
        "zh-CN",
        "--scenario",
        "debugging",
    )

    assert workspace_session["session"]["character_id"] == "rin-aster"
    assert global_session["session"]["character_id"] == "rin-aster"
    assert workspace_context["context"]["character_id"] == "rin-aster"
    assert global_context["context"]["character_id"] == "rin-aster"


def test_session_start_without_character_or_default_is_read_only(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "must-not-be-created"

    result = _run_cli_error(
        data_root,
        "session",
        "start",
        "--session",
        "no-default",
    )

    assert result["error"]["code"] == "KARC_DEFAULT_NOT_CONFIGURED"
    assert not data_root.exists()


def test_explicit_session_start_ignores_a_malformed_default(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    compiled = _run_cli(data_root, "pack", "compile", str(RIN_PACK))
    default_path = data_root / "config" / "global.json"
    default_path.parent.mkdir(parents=True)
    default_path.write_bytes(b"not-json")

    started = _run_cli(
        data_root,
        "session",
        "start",
        "--character",
        compiled["path"],
        "--session",
        "explicit-path",
    )

    assert started["session"]["active"] is True
    assert started["session"]["character_id"] == "rin-aster"
    assert default_path.read_bytes() == b"not-json"
