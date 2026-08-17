from __future__ import annotations

from pathlib import Path
from copy import deepcopy

import pytest

import kokoroarc.distribution.registry as registry_module
from kokoroarc.distribution.registry import (
    empty_installed_registry,
    list_installed_packs,
    load_installed_registry,
    resolve_install_scope,
    write_installed_registry_cas,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def _entry(number: int = 1) -> dict[str, object]:
    archive_hash = f"{number:064x}"
    return {
        "installation_id": f"original.rin-aster.1.0.{number}.{archive_hash[:8]}",
        "archive_sha256": archive_hash,
        "manifest_sha256": f"{number + 1:064x}",
        "compiled_artifact_id": "original/rin-aster/compiled",
        "compiled_sha256": f"{number + 2:064x}",
        "visibility": "private",
        "promotion_status": "verified",
        "activation_allowed": True,
        "trust": "unsigned_local",
        "relative_path": f"global/rin-aster/1.0.{number}",
    }


def _assert_code(code: str, function: object, *args: object, **kwargs: object) -> None:
    with pytest.raises(KokoroError) as caught:
        function(*args, **kwargs)  # type: ignore[operator]
    assert caught.value.code == code


def test_global_scope_builds_the_canonical_revision_zero_registry() -> None:
    scope = resolve_install_scope()
    registry = empty_installed_registry(scope)

    assert scope.kind == "global"
    assert scope.workspace_id is None
    assert scope.installed_relative_root == "global"
    assert scope.registry_relative_path == "registry/global.json"
    assert registry == {
        "schema_version": "1.0",
        "artifact_id": "registry/global/installed-packs",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "scope": "global",
        "workspace_id": None,
        "revision": 0,
        "entries": {},
    }
    SCHEMAS.validate("installed-pack-registry", registry)


def test_workspace_scope_is_stable_and_does_not_expose_the_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    first = resolve_install_scope(workspace)
    second = resolve_install_scope(workspace)
    registry = empty_installed_registry(first)

    assert first == second
    assert first.kind == "workspace"
    assert len(first.workspace_id or "") == 64
    assert first.installed_relative_root == f"workspaces/{first.workspace_id}"
    assert first.registry_relative_path == (
        f"registry/workspaces/{first.workspace_id}.json"
    )
    assert registry["artifact_id"] == (
        f"registry/workspaces/{first.workspace_id[:8]}/installed-packs"
    )
    assert str(workspace) not in canonical_bytes(registry).decode("utf-8")
    assert list(workspace.iterdir()) == []
    SCHEMAS.validate("installed-pack-registry", registry)


def test_workspace_scope_requires_an_existing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    regular_file = tmp_path / "file"
    regular_file.write_text("not a workspace", encoding="utf-8")

    for candidate in (missing, regular_file):
        try:
            resolve_install_scope(candidate)
        except Exception as error:
            assert getattr(error, "code", None) == "KARC_SCOPE_INVALID"
        else:
            raise AssertionError("invalid workspace root was accepted")


def test_absent_registry_lists_no_entries_without_creating_data_root(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"

    assert list_installed_packs(data_root, SCHEMAS) == []
    assert not data_root.exists()


def test_registry_round_trip_is_canonical_sorted_and_detached(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    path = data_root / "registry" / "global.json"
    path.parent.mkdir(parents=True)
    registry = empty_installed_registry(resolve_install_scope())
    registry["revision"] = 2
    registry["entries"] = {
        "original/rin-aster/1.0.2": _entry(2),
        "original/rin-aster/1.0.1": _entry(1),
    }
    path.write_bytes(canonical_bytes(registry))

    loaded = load_installed_registry(data_root, SCHEMAS)
    listed = list_installed_packs(data_root, SCHEMAS)
    loaded["entries"].clear()

    assert [item["registry_identity"] for item in listed] == [
        "original/rin-aster/1.0.1",
        "original/rin-aster/1.0.2",
    ]
    assert len(load_installed_registry(data_root, SCHEMAS)["entries"]) == 2


def test_registry_rejects_noncanonical_and_over_capacity(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    path = data_root / "registry" / "global.json"
    path.parent.mkdir(parents=True)
    registry = empty_installed_registry(resolve_install_scope())
    path.write_text("{\n}\n", encoding="utf-8")

    _assert_code("KARC_REGISTRY_INVALID", load_installed_registry, data_root, SCHEMAS)

    registry["entries"] = {
        f"original/character-{number}/1.0.0": _entry(number + 1)
        for number in range(1_025)
    }
    path.write_bytes(canonical_bytes(registry))

    _assert_code(
        "KARC_REGISTRY_LIMIT_EXCEEDED",
        load_installed_registry,
        data_root,
        SCHEMAS,
    )


def test_registry_rejects_excessive_json_nesting_with_stable_error(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    path = data_root / "registry" / "global.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b'[' * 2_000 + b'0' + b']' * 2_000)

    _assert_code("KARC_REGISTRY_INVALID", load_installed_registry, data_root, SCHEMAS)


def test_registry_rejects_a_mutable_hardlink_alias(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    path = data_root / "registry" / "global.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(canonical_bytes(empty_installed_registry(resolve_install_scope())))
    alias = tmp_path / "registry-alias.json"
    try:
        alias.hardlink_to(path)
    except OSError as error:
        pytest.skip(f"hardlinks unavailable: {type(error).__name__}")

    _assert_code("KARC_REGISTRY_INVALID", load_installed_registry, data_root, SCHEMAS)

    assert alias.read_bytes() == path.read_bytes()


def test_registry_validation_mutation_is_rejected(tmp_path: Path) -> None:
    data_root = tmp_path / "data"

    class MutatingSchemas:
        def validate(self, name: str, instance: object) -> None:
            SCHEMAS.validate(name, instance)
            if name == "installed-pack-registry":
                assert isinstance(instance, dict)
                instance["revision"] = 9

    _assert_code(
        "KARC_REGISTRY_CHANGED",
        load_installed_registry,
        data_root,
        MutatingSchemas(),
    )


def test_registry_read_rejects_data_root_replacement_during_validation(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    registry_path = data_root / "registry" / "global.json"
    registry_path.parent.mkdir(parents=True)
    payload = canonical_bytes(empty_installed_registry(resolve_install_scope()))
    registry_path.write_bytes(payload)
    displaced = tmp_path / "data-displaced"

    class ReplacingSchemas:
        def validate(self, name: str, instance: object) -> None:
            SCHEMAS.validate(name, instance)
            data_root.rename(displaced)
            registry_path.parent.mkdir(parents=True)
            registry_path.write_bytes(payload)

    try:
        _assert_code(
            "KARC_REGISTRY_CHANGED",
            load_installed_registry,
            data_root,
            ReplacingSchemas(),
        )
    finally:
        if data_root.exists() and displaced.exists():
            replacement = tmp_path / "data-replacement"
            data_root.rename(replacement)
            displaced.rename(data_root)


def test_registry_read_rejects_same_byte_file_replacement_during_validation(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    registry_path = data_root / "registry" / "global.json"
    registry_path.parent.mkdir(parents=True)
    payload = canonical_bytes(empty_installed_registry(resolve_install_scope()))
    registry_path.write_bytes(payload)
    displaced = tmp_path / "registry-displaced.json"

    class ReplacingSchemas:
        def validate(self, name: str, instance: object) -> None:
            SCHEMAS.validate(name, instance)
            registry_path.rename(displaced)
            registry_path.write_bytes(payload)

    try:
        _assert_code(
            "KARC_REGISTRY_CHANGED",
            load_installed_registry,
            data_root,
            ReplacingSchemas(),
        )
    finally:
        if registry_path.exists() and displaced.exists():
            replacement = tmp_path / "registry-replacement.json"
            registry_path.rename(replacement)
            displaced.rename(registry_path)


def test_registry_read_rejects_workspace_replacement_during_validation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    displaced = tmp_path / "workspace-displaced"

    class ReplacingSchemas:
        def validate(self, name: str, instance: object) -> None:
            SCHEMAS.validate(name, instance)
            workspace.rename(displaced)
            workspace.mkdir()

    try:
        _assert_code(
            "KARC_SCOPE_CHANGED",
            load_installed_registry,
            tmp_path / "data",
            ReplacingSchemas(),
            workspace_root=workspace,
        )
    finally:
        if workspace.exists() and displaced.exists():
            workspace.rmdir()
            displaced.rename(workspace)


def test_registry_cas_publishes_one_revision_and_rejects_stale_writer(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    scope = resolve_install_scope()
    registry = empty_installed_registry(scope)
    registry["revision"] = 1
    registry["entries"] = {"original/rin-aster/1.0.1": _entry(1)}

    write_installed_registry_cas(
        data_root,
        scope,
        expected_revision=0,
        expected_sha256=None,
        registry=registry,
        schemas=SCHEMAS,
    )
    original = canonical_bytes(load_installed_registry(data_root, SCHEMAS))

    changed = deepcopy(registry)
    changed["revision"] = 1
    changed["entries"]["original/rin-aster/1.0.2"] = _entry(2)
    _assert_code(
        "KARC_REGISTRY_CONFLICT",
        write_installed_registry_cas,
        data_root,
        scope,
        expected_revision=0,
        expected_sha256=None,
        registry=changed,
        schemas=SCHEMAS,
    )

    assert canonical_bytes(load_installed_registry(data_root, SCHEMAS)) == original


def test_registry_cas_rejects_absent_registry_aba_across_callbacks(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    scope = resolve_install_scope()
    candidate = empty_installed_registry(scope)
    candidate["revision"] = 1
    registry_path = data_root / "registry" / "global.json"
    changed = empty_installed_registry(scope)
    changed["revision"] = 9
    phase = 0

    class CallbackSchemas:
        def validate(self, name: str, instance: object) -> None:
            nonlocal phase
            SCHEMAS.validate(name, instance)
            if phase == 0:
                registry_path.write_bytes(canonical_bytes(changed))
                phase = 1
            elif phase == 1:
                registry_path.unlink()
                phase = 2

    with pytest.raises(KokoroError) as caught:
        write_installed_registry_cas(
            data_root,
            scope,
            expected_revision=0,
            expected_sha256=None,
            registry=candidate,
            schemas=CallbackSchemas(),
        )

    assert caught.value.code == "KARC_REGISTRY_CONFLICT"
    assert registry_path.read_bytes() == canonical_bytes(changed)


def test_scope_lock_contention_fails_with_a_stable_error(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    scope = resolve_install_scope()
    registry = empty_installed_registry(scope)
    registry["revision"] = 1

    with registry_module._acquire_registry_lock(data_root, scope):
        _assert_code(
            "KARC_REGISTRY_LOCKED",
            write_installed_registry_cas,
            data_root,
            scope,
            expected_revision=0,
            expected_sha256=None,
            registry=registry,
            schemas=SCHEMAS,
        )
