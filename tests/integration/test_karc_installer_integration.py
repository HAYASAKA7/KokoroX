"""Integration coverage for scoped transactional ``.karc`` installation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import kokoroarc.distribution.installer as installer_module
from kokoroarc.distribution.archive import inspect_karc_container
from kokoroarc.distribution.installer import (
    install_karc_archive,
    recover_karc_installations,
    remove_installed_pack,
)
from kokoroarc.distribution.registry import load_installed_registry
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import build_private_archive


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def _assert_installed_members(
    data_root: Path,
    relative_path: str,
    archive: bytes,
) -> None:
    container = inspect_karc_container(archive)
    installation = data_root / "installed" / Path(relative_path)
    actual = {
        path.relative_to(installation).as_posix(): path.read_bytes()
        for path in installation.rglob("*")
        if path.is_file()
    }

    assert actual == container.member_payloads


def test_global_install_publishes_exact_closed_bytes_and_is_idempotent(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive = build_private_archive(rin_verified_release)
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(archive)
    source_before = (source.stat().st_mtime_ns, source.read_bytes())
    data_root = tmp_path / "data"

    applied = install_karc_archive(source, data_root, SCHEMAS)

    assert applied["scope"] == "global"
    assert applied["registry_revision_before"] == 0
    assert applied["registry_revision_after"] == 1
    assert applied["idempotent"] is False
    assert applied["will_write"] is True
    assert applied["activates_character"] is False
    _assert_installed_members(data_root, applied["relative_path"], archive)
    archive_path = data_root / "archives" / f"{applied['archive_sha256']}.karc"
    assert archive_path.read_bytes() == archive

    registry = load_installed_registry(data_root, SCHEMAS)
    registry_path = data_root / "registry" / "global.json"
    assert registry["revision"] == 1
    assert registry_path.read_bytes() == canonical_bytes(registry)
    assert set(registry["entries"]) == {applied["registry_identity"]}
    assert not list((data_root / "registry" / "journals").glob("*.json"))
    assert not (data_root / "config").exists()
    assert not (data_root / "sessions").exists()
    assert (source.stat().st_mtime_ns, source.read_bytes()) == source_before

    before = {
        path.relative_to(data_root).as_posix(): (
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in data_root.rglob("*")
        if path.is_file()
    }
    repeated = install_karc_archive(source, data_root, SCHEMAS)
    after = {
        path.relative_to(data_root).as_posix(): (
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in data_root.rglob("*")
        if path.is_file()
    }

    assert repeated["registry_revision_before"] == 1
    assert repeated["registry_revision_after"] == 1
    assert repeated["idempotent"] is True
    assert repeated["will_write"] is False
    assert after == before


def test_workspace_install_is_scoped_without_writing_the_workspace(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive = build_private_archive(rin_verified_release)
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(archive)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "data"

    applied = install_karc_archive(
        source,
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )

    workspace_id = applied["workspace_id"]
    assert applied["scope"] == "workspace"
    assert len(workspace_id) == 64
    assert applied["relative_path"] == (
        f"workspaces/{workspace_id}/rin-aster/1.0.0"
    )
    _assert_installed_members(data_root, applied["relative_path"], archive)
    registry_path = data_root / "registry" / "workspaces" / f"{workspace_id}.json"
    assert registry_path.is_file()
    assert list(workspace.iterdir()) == []


def test_install_dry_run_is_read_only(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive = build_private_archive(rin_verified_release)
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(archive)
    source_before = (source.stat().st_mtime_ns, source.read_bytes())
    data_root = tmp_path / "data"

    plan = install_karc_archive(
        source,
        data_root,
        SCHEMAS,
        dry_run=True,
    )

    assert plan["will_write"] is True
    assert plan["activates_character"] is False
    assert not data_root.exists()
    assert (source.stat().st_mtime_ns, source.read_bytes()) == source_before


def _storage_snapshot(data_root: Path) -> dict[str, bytes]:
    if not data_root.exists():
        return {}
    return {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file()
    }


def test_absent_recovery_is_a_read_only_deterministic_noop(tmp_path: Path) -> None:
    data_root = tmp_path / "data"

    first = recover_karc_installations(data_root, SCHEMAS)
    second = recover_karc_installations(data_root, SCHEMAS)

    assert first == second == {
        "schema_version": "1.0",
        "operation": "recover",
        "scope": "global",
        "workspace_id": None,
        "recovered": False,
        "prior_phase": None,
        "final_phase": None,
        "registry_revision": 0,
        "actions": [],
    }
    assert not data_root.exists()


@pytest.mark.parametrize(
    "boundary,rolls_back",
    [
        ("journal_created", True),
        ("archive_staged", True),
        ("installation_staged", True),
        ("archive_published", False),
        ("archive_phase_recorded", False),
        ("installation_published", False),
        ("installation_phase_recorded", False),
        ("registry_staged", False),
        ("registry_published", False),
        ("registry_phase_recorded", False),
        ("cleanup_complete", False),
    ],
)
def test_every_install_boundary_recovers_once_then_becomes_a_noop(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    rolls_back: bool,
) -> None:
    archive = build_private_archive(rin_verified_release)
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(archive)
    data_root = tmp_path / "data"

    def interrupt(name: str) -> None:
        if name == boundary:
            raise RuntimeError(f"injected:{name}")

    monkeypatch.setattr(installer_module, "_install_failure_point", interrupt)
    with pytest.raises(RuntimeError, match=f"injected:{boundary}"):
        install_karc_archive(source, data_root, SCHEMAS)
    monkeypatch.setattr(
        installer_module,
        "_install_failure_point",
        lambda _name: None,
    )

    first = recover_karc_installations(data_root, SCHEMAS)
    after_first = _storage_snapshot(data_root)
    second = recover_karc_installations(data_root, SCHEMAS)
    after_second = _storage_snapshot(data_root)
    registry = load_installed_registry(data_root, SCHEMAS)

    if boundary == "cleanup_complete":
        assert first["recovered"] is False
    else:
        assert first["recovered"] is True
    if rolls_back:
        assert first["final_phase"] == "rolled_back"
        assert registry["revision"] == 0
        assert not (data_root / "installed" / "global" / "rin-aster" / "1.0.0").exists()
    else:
        assert first["final_phase"] in {"registry_published", None}
        assert registry["revision"] == 1
        assert set(registry["entries"]) == {"original/rin-aster/1.0.0"}
    assert second["recovered"] is False
    assert second["actions"] == []
    assert after_second == after_first
    assert not list((data_root / "registry" / "journals").glob("*.json"))


def test_removal_is_scope_local_and_deletes_archive_after_final_reference(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive = build_private_archive(rin_verified_release)
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(archive)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "data"
    global_install = install_karc_archive(source, data_root, SCHEMAS)
    workspace_install = install_karc_archive(
        source,
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )
    archive_path = data_root / "archives" / f"{global_install['archive_sha256']}.karc"

    global_removal = remove_installed_pack(
        data_root,
        "original",
        "rin-aster",
        "1.0.0",
        SCHEMAS,
    )

    assert global_removal["operation"] == "remove"
    assert global_removal["scope"] == "global"
    assert global_removal["registry_revision_before"] == 1
    assert global_removal["registry_revision_after"] == 2
    assert global_removal["archive_removed"] is False
    assert global_removal["will_write"] is True
    assert global_removal["activates_character"] is False
    assert not (
        data_root / "installed" / Path(global_install["relative_path"])
    ).exists()
    assert (
        data_root / "installed" / Path(workspace_install["relative_path"])
    ).is_dir()
    assert archive_path.read_bytes() == archive
    assert load_installed_registry(data_root, SCHEMAS)["revision"] == 2
    workspace_registry = load_installed_registry(
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )
    assert workspace_registry["revision"] == 1

    workspace_removal = remove_installed_pack(
        data_root,
        "original",
        "rin-aster",
        "1.0.0",
        SCHEMAS,
        workspace_root=workspace,
    )

    assert workspace_removal["scope"] == "workspace"
    assert workspace_removal["registry_revision_before"] == 1
    assert workspace_removal["registry_revision_after"] == 2
    assert workspace_removal["archive_removed"] is True
    assert not archive_path.exists()
    assert load_installed_registry(
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )["entries"] == {}


@pytest.mark.parametrize(
    "boundary",
    [
        "removal_registry_published",
        "removal_installation_renamed",
        "removal_tree_cleaned",
        "removal_archive_cleaned",
        "removal_cleanup_complete",
    ],
)
def test_every_removal_boundary_recovers_without_restoring_missing_bytes(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    plan = install_karc_archive(source, data_root, SCHEMAS)

    def interrupt(name: str) -> None:
        if name == boundary:
            raise RuntimeError(f"injected:{name}")

    monkeypatch.setattr(installer_module, "_install_failure_point", interrupt)
    with pytest.raises(RuntimeError, match=f"injected:{boundary}"):
        remove_installed_pack(
            data_root,
            "original",
            "rin-aster",
            "1.0.0",
            SCHEMAS,
        )
    monkeypatch.setattr(
        installer_module,
        "_install_failure_point",
        lambda _name: None,
    )

    first = recover_karc_installations(data_root, SCHEMAS)
    after_first = _storage_snapshot(data_root)
    second = recover_karc_installations(data_root, SCHEMAS)
    after_second = _storage_snapshot(data_root)
    registry = load_installed_registry(data_root, SCHEMAS)

    if boundary == "removal_cleanup_complete":
        assert first["recovered"] is False
    else:
        assert first["recovered"] is True
        assert first["final_phase"] == "installation_removed"
    assert registry["revision"] == 2
    assert registry["entries"] == {}
    assert not (data_root / "installed" / Path(plan["relative_path"])).exists()
    assert not (data_root / "archives" / f"{plan['archive_sha256']}.karc").exists()
    assert second["recovered"] is False
    assert after_second == after_first
