from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.distribution.archive import inspect_karc_container
from kokoroarc.distribution.installer import preview_karc_install
from kokoroarc.distribution.registry import (
    empty_installed_registry,
    resolve_install_scope,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import build_private_archive, build_public_archive


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def _assert_code(code: str, function: object, *args: object, **kwargs: object) -> None:
    with pytest.raises(KokoroError) as caught:
        function(*args, **kwargs)  # type: ignore[operator]
    assert caught.value.code == code


def _registry_entry(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "installation_id": plan["installation_id"],
        "archive_sha256": plan["archive_sha256"],
        "manifest_sha256": plan["manifest_sha256"],
        "compiled_artifact_id": plan["compiled_artifact_id"],
        "compiled_sha256": plan["compiled_sha256"],
        "visibility": plan["visibility"],
        "promotion_status": "verified",
        "activation_allowed": True,
        "trust": "unsigned_local",
        "relative_path": plan["relative_path"],
    }


def _write_existing_installation(
    data_root: Path,
    archive: bytes,
    plan: dict[str, Any],
) -> None:
    container = inspect_karc_container(archive)
    install_root = data_root / "installed" / Path(plan["relative_path"])
    for relative, payload in container.member_payloads.items():
        target = install_root / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    archive_path = data_root / "archives" / f"{plan['archive_sha256']}.karc"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive)
    registry = empty_installed_registry(resolve_install_scope())
    registry["revision"] = 1
    registry["entries"] = {plan["registry_identity"]: _registry_entry(plan)}
    registry_path = data_root / "registry" / "global.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_bytes(canonical_bytes(registry))


def test_preview_is_deterministic_read_only_and_never_activates(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive = build_private_archive(rin_verified_release)
    data_root = tmp_path / "data"

    first = preview_karc_install(archive, data_root, SCHEMAS)
    second = preview_karc_install(archive, data_root, SCHEMAS)

    assert first == second
    assert first["schema_version"] == "1.0"
    assert first["operation"] == "install"
    assert first["scope"] == "global"
    assert first["workspace_id"] is None
    assert first["registry_identity"] == "original/rin-aster/1.0.0"
    assert first["installation_id"].startswith("original.rin-aster.1.0.0.")
    assert first["relative_path"] == "global/rin-aster/1.0.0"
    assert first["registry_revision_before"] == 0
    assert first["registry_revision_after"] == 1
    assert first["idempotent"] is False
    assert first["will_write"] is True
    assert first["activates_character"] is False
    assert first["visibility"] == "private"
    assert not data_root.exists()


def test_workspace_preview_is_stable_and_writes_nowhere(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive = build_private_archive(rin_verified_release)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "data"

    plan = preview_karc_install(
        archive,
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )

    assert plan["scope"] == "workspace"
    assert len(plan["workspace_id"]) == 64
    assert plan["relative_path"] == (
        f"workspaces/{plan['workspace_id']}/rin-aster/1.0.0"
    )
    assert list(workspace.iterdir()) == []
    assert not data_root.exists()


def test_public_archive_preview_preserves_public_visibility(
    rin_public_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    plan = preview_karc_install(
        build_public_archive(rin_public_verified_release),
        tmp_path / "data",
        SCHEMAS,
    )

    assert plan["visibility"] == "public_candidate"
    assert plan["will_write"] is True
    assert plan["activates_character"] is False


def test_preview_rejects_invalid_archive_without_creating_storage(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"

    _assert_code(
        "KARC_INSTALL_ARCHIVE_INVALID",
        preview_karc_install,
        b"not a karc archive",
        data_root,
        SCHEMAS,
    )
    assert not data_root.exists()


def test_preview_rejects_same_identity_with_different_archive_bytes(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive = build_private_archive(rin_verified_release)
    data_root = tmp_path / "data"
    plan = preview_karc_install(archive, data_root, SCHEMAS)
    registry = empty_installed_registry(resolve_install_scope())
    conflicting = _registry_entry(plan)
    conflicting["archive_sha256"] = "f" * 64
    conflicting["installation_id"] = "original.rin-aster.1.0.0.ffffffff"
    registry["revision"] = 1
    registry["entries"] = {plan["registry_identity"]: conflicting}
    registry_path = data_root / "registry" / "global.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_bytes(canonical_bytes(registry))
    before = registry_path.read_bytes()

    _assert_code(
        "KARC_INSTALL_CONFLICT",
        preview_karc_install,
        archive,
        data_root,
        SCHEMAS,
    )
    assert registry_path.read_bytes() == before


def test_exact_existing_installation_is_a_read_only_idempotent_preview(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive = build_private_archive(rin_verified_release)
    data_root = tmp_path / "data"
    initial = preview_karc_install(archive, data_root, SCHEMAS)
    _write_existing_installation(data_root, archive, initial)
    before = {
        path.relative_to(data_root).as_posix(): (
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in data_root.rglob("*")
        if path.is_file()
    }

    repeated = preview_karc_install(archive, data_root, SCHEMAS)
    after = {
        path.relative_to(data_root).as_posix(): (
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in data_root.rglob("*")
        if path.is_file()
    }

    assert repeated == {
        **deepcopy(initial),
        "registry_revision_before": 1,
        "registry_revision_after": 1,
        "idempotent": True,
        "will_write": False,
    }
    assert after == before
