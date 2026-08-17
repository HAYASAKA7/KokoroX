"""Adversarial recovery boundaries for scoped ``.karc`` installation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import kokoroarc.distribution.installer as installer_module
import kokoroarc.distribution.registry as registry_module
from kokoroarc.distribution.installer import (
    install_karc_archive,
    preview_karc_install,
    recover_karc_installations,
    remove_installed_pack,
)
from kokoroarc.distribution.registry import (
    empty_installed_registry,
    load_installed_registry,
    resolve_install_scope,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import build_private_archive


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


class _CallbackSchemas:
    def __init__(self, callback: object) -> None:
        self._callback = callback
        self._calls = 0

    def validate(self, name: str, instance: Any) -> None:
        SCHEMAS.validate(name, instance)
        self._calls += 1
        self._callback(self._calls, name)  # type: ignore[operator]


class _CountingScandir:
    def __init__(self, paths: list[Path], consumed: list[int]) -> None:
        self._paths = iter(paths)
        self._consumed = consumed

    def __enter__(self) -> _CountingScandir:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def __iter__(self) -> _CountingScandir:
        return self

    def __next__(self) -> SimpleNamespace:
        path = next(self._paths)
        self._consumed[0] += 1
        return SimpleNamespace(path=str(path))


def _assert_recovery_required(function: object, *args: object) -> None:
    with pytest.raises(KokoroError) as caught:
        function(*args)  # type: ignore[operator]
    assert caught.value.code == "KARC_INSTALL_RECOVERY_REQUIRED"


def _snapshot_outside(root: Path, excluded: Path) -> dict[str, bytes | None]:
    snapshot: dict[str, bytes | None] = {}
    for path in root.rglob("*"):
        if path == excluded or excluded in path.parents:
            continue
        relative = path.relative_to(root).as_posix()
        snapshot[relative] = path.read_bytes() if path.is_file() else None
    return snapshot


def _interrupt_install(
    release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> tuple[Path, Path]:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(release))
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
    return source, data_root


def test_malformed_journal_is_preserved_without_interpreting_paths(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    journal = data_root / "registry" / "journals" / "global.json"
    journal.parent.mkdir(parents=True)
    payload = canonical_bytes({"operation": "install", "path": "../../outside"})
    journal.write_bytes(payload)

    _assert_recovery_required(recover_karc_installations, data_root, SCHEMAS)

    assert journal.read_bytes() == payload


def test_replaced_staging_identity_is_never_deleted(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, data_root = _interrupt_install(
        rin_verified_release,
        tmp_path,
        monkeypatch,
        "installation_staged",
    )
    journal_path = data_root / "registry" / "journals" / "global.json"
    journal = json.loads(journal_path.read_bytes())
    staging = data_root / Path(journal["installation_staging_relative_path"])
    displaced = staging.with_name(f"{staging.name}.displaced")
    staging.rename(displaced)
    staging.mkdir()
    sentinel = staging / "unrelated.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    _assert_recovery_required(recover_karc_installations, data_root, SCHEMAS)

    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert displaced.is_dir()
    assert journal_path.is_file()


def test_recovery_surfaces_archive_staging_cleanup_failure(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, data_root = _interrupt_install(
        rin_verified_release,
        tmp_path,
        monkeypatch,
        "installation_staged",
    )
    journal_path = data_root / "registry" / "journals" / "global.json"
    journal = json.loads(journal_path.read_bytes())
    archive_staging = data_root / Path(
        journal["archive_staging_relative_path"]
    )
    original_unlink = Path.unlink

    def deny_archive_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        if path == archive_staging:
            raise PermissionError("injected archive staging cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_archive_cleanup)

    with pytest.raises(KokoroError) as caught:
        recover_karc_installations(data_root, SCHEMAS)

    assert caught.value.code == "KARC_INSTALL_CLEANUP_FAILED"
    assert caught.value.details == {
        "phase": "archive_staging",
        "reason": "PermissionError",
    }
    assert archive_staging.is_file()
    assert journal_path.is_file()


def test_unrelated_registry_revision_blocks_recovery_without_deleting_install(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, data_root = _interrupt_install(
        rin_verified_release,
        tmp_path,
        monkeypatch,
        "installation_published",
    )
    registry = empty_installed_registry(resolve_install_scope())
    registry["revision"] = 1
    registry_path = data_root / "registry" / "global.json"
    registry_path.write_bytes(canonical_bytes(registry))
    installation = data_root / "installed" / "global" / "rin-aster" / "1.0.0"

    _assert_recovery_required(recover_karc_installations, data_root, SCHEMAS)

    assert installation.is_dir()
    assert registry_path.read_bytes() == canonical_bytes(registry)
    assert (data_root / "registry" / "journals" / "global.json").is_file()


def test_missing_visible_archive_preserves_published_installation(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, data_root = _interrupt_install(
        rin_verified_release,
        tmp_path,
        monkeypatch,
        "installation_published",
    )
    journal_path = data_root / "registry" / "journals" / "global.json"
    journal = json.loads(journal_path.read_bytes())
    archive = data_root / Path(journal["archive_relative_path"])
    archive.unlink()
    installation = data_root / Path(journal["installation_relative_path"])

    _assert_recovery_required(recover_karc_installations, data_root, SCHEMAS)

    assert installation.is_dir()
    assert journal_path.is_file()


def test_recovery_rejects_journal_aba_across_schema_callbacks(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, data_root = _interrupt_install(
        rin_verified_release,
        tmp_path,
        monkeypatch,
        "installation_staged",
    )
    journal = data_root / "registry" / "journals" / "global.json"
    displaced = journal.with_name("global.displaced.json")
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            payload = journal.read_bytes()
            journal.rename(displaced)
            journal.write_bytes(payload)
            phase = 1
        elif phase == 1:
            journal.unlink()
            displaced.rename(journal)
            phase = 2

    try:
        with pytest.raises(KokoroError) as caught:
            recover_karc_installations(
                data_root,
                _CallbackSchemas(mutate),
            )
        assert caught.value.code == "KARC_INSTALL_JOURNAL_CHANGED"
    finally:
        if journal.exists() and displaced.exists():
            journal.unlink()
            displaced.rename(journal)


def test_recovery_rejects_absent_registry_aba_across_schema_callbacks(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, data_root = _interrupt_install(
        rin_verified_release,
        tmp_path,
        monkeypatch,
        "installation_staged",
    )
    registry = data_root / "registry" / "global.json"
    changed = empty_installed_registry(resolve_install_scope())
    changed["revision"] = 9
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            registry.write_bytes(canonical_bytes(changed))
            phase = 1
        elif phase == 1:
            registry.unlink()
            phase = 2

    with pytest.raises(KokoroError) as caught:
        recover_karc_installations(
            data_root,
            _CallbackSchemas(mutate),
        )

    assert caught.value.code == "KARC_INSTALL_CONFLICT"
    assert registry.read_bytes() == canonical_bytes(changed)


def test_removal_recovery_rejects_workspace_registry_aba(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)

    def interrupt(name: str) -> None:
        if name == "removal_registry_published":
            raise RuntimeError("injected:removal_registry_published")

    monkeypatch.setattr(installer_module, "_install_failure_point", interrupt)
    with pytest.raises(RuntimeError, match="injected:removal_registry_published"):
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

    workspace = tmp_path / "other-workspace"
    workspace.mkdir()
    workspace_scope = resolve_install_scope(workspace)
    registry = (
        data_root
        / "registry"
        / "workspaces"
        / f"{workspace_scope.workspace_id}.json"
    )
    registry.parent.mkdir()
    original = empty_installed_registry(workspace_scope)
    registry.write_bytes(canonical_bytes(original))
    changed = dict(original)
    changed["revision"] = 9
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            registry.write_bytes(canonical_bytes(changed))
            phase = 1
        elif phase == 1:
            registry.write_bytes(canonical_bytes(original))
            phase = 2

    with pytest.raises(KokoroError) as caught:
        recover_karc_installations(
            data_root,
            _CallbackSchemas(mutate),
        )

    assert caught.value.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID"
    assert registry.read_bytes() == canonical_bytes(changed)


def test_hardlinked_journal_is_preserved_and_recovery_fails_closed(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, data_root = _interrupt_install(
        rin_verified_release,
        tmp_path,
        monkeypatch,
        "journal_created",
    )
    journal = data_root / "registry" / "journals" / "global.json"
    alias = tmp_path / "journal-alias.json"
    try:
        alias.hardlink_to(journal)
    except OSError as error:
        pytest.skip(f"hardlinks unavailable: {type(error).__name__}")
    payload = journal.read_bytes()

    _assert_recovery_required(recover_karc_installations, data_root, SCHEMAS)

    assert journal.read_bytes() == payload
    assert alias.read_bytes() == payload


def _default_config(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "config/global/character-default",
        "created_by": {"component": "kokoroarc", "version": "test"},
        "scope": "global",
        "workspace_id": None,
        "revision": 1,
        "binding": {
            "installation_id": plan["installation_id"],
            "namespace": "original",
            "character_id": "rin-aster",
            "character_version": "1.0.0",
            "archive_sha256": plan["archive_sha256"],
            "compiled_sha256": plan["compiled_sha256"],
        },
        "activation_policy": "explicit_only",
    }


def _session_manifest(plan: dict[str, Any], *, active: bool) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "session/removal-blocker",
        "created_by": {"component": "kokoroarc", "version": "test"},
        "session_id": "removal-blocker",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "compiled_pack_hash": plan["compiled_sha256"],
        "lifecycle_generation": "a" * 32,
        "scope": "session",
        "state_revision": 0,
        "active": active,
    }


def _migration_record(plan: dict[str, Any], *, referenced: bool) -> dict[str, Any]:
    bundle = json.loads(
        Path("tests/fixtures/standalone-contracts/private-global.json").read_bytes()
    )
    record = bundle["migration_plan"]
    record["input_archive_sha256"] = (
        plan["archive_sha256"] if referenced else "e" * 64
    )
    record["output_archive_sha256"] = "f" * 64
    return record


def _write_reference(
    data_root: Path,
    plan: dict[str, Any],
    reference_kind: str,
) -> None:
    if reference_kind == "default":
        path = data_root / "config" / "global.json"
        document = _default_config(plan)
    elif reference_kind == "session":
        path = data_root / "sessions" / "removal-blocker.json"
        document = _session_manifest(plan, active=True)
    else:
        path = data_root / "migrations" / "removal-blocker.json"
        document = _migration_record(plan, referenced=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(document))


@pytest.mark.parametrize("reference_kind", ["default", "session", "migration"])
def test_exact_references_block_removal_without_changing_storage(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    reference_kind: str,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    plan = install_karc_archive(source, data_root, SCHEMAS)
    _write_reference(data_root, plan, reference_kind)
    before = {
        path.relative_to(data_root).as_posix(): (
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in data_root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(KokoroError) as caught:
        remove_installed_pack(
            data_root,
            "original",
            "rin-aster",
            "1.0.0",
            SCHEMAS,
        )

    after = {
        path.relative_to(data_root).as_posix(): (
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in data_root.rglob("*")
        if path.is_file()
    }
    assert caught.value.code == "KARC_REMOVE_REFERENCED"
    assert after == before


def test_inactive_and_unrelated_references_do_not_block_removal(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    plan = install_karc_archive(source, data_root, SCHEMAS)
    config = _default_config(plan)
    config["binding"] = None
    references = {
        data_root / "config" / "global.json": config,
        data_root / "sessions" / "inactive.json": _session_manifest(
            plan,
            active=False,
        ),
        data_root / "migrations" / "unrelated.json": _migration_record(
            plan,
            referenced=False,
        ),
    }
    for path, document in references.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_bytes(document))

    result = remove_installed_pack(
        data_root,
        "original",
        "rin-aster",
        "1.0.0",
        SCHEMAS,
    )

    assert result["archive_removed"] is True
    assert load_installed_registry(data_root, SCHEMAS)["entries"] == {}


def test_hardlinked_reference_file_blocks_removal_as_an_unsafe_scan(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    plan = install_karc_archive(source, data_root, SCHEMAS)
    reference = data_root / "config" / "global.json"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(canonical_bytes(_default_config(plan)))
    alias = tmp_path / "default-alias.json"
    try:
        alias.hardlink_to(reference)
    except OSError as error:
        pytest.skip(f"hardlinks unavailable: {type(error).__name__}")

    with pytest.raises(KokoroError) as caught:
        remove_installed_pack(
            data_root,
            "original",
            "rin-aster",
            "1.0.0",
            SCHEMAS,
        )

    assert caught.value.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID"
    assert reference.is_file()
    assert alias.is_file()


def test_hardlinked_archive_source_is_rejected_before_storage_creation(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    alias = tmp_path / "rin-aster-alias.karc"
    try:
        alias.hardlink_to(source)
    except OSError as error:
        pytest.skip(f"hardlinks unavailable: {type(error).__name__}")
    data_root = tmp_path / "data"

    with pytest.raises(KokoroError) as caught:
        install_karc_archive(source, data_root, SCHEMAS)

    assert caught.value.code == "KARC_INSTALL_SOURCE_INVALID"
    assert not data_root.exists()


def test_archive_source_aba_across_schema_callbacks_is_rejected(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    original = build_private_archive(rin_verified_release)
    source.write_bytes(original)
    data_root = tmp_path / "data"

    def mutate(call: int, _name: str) -> None:
        if call == 1:
            source.write_bytes(b"changed-between-callbacks")
        elif call == 2:
            source.write_bytes(original)

    try:
        with pytest.raises(KokoroError) as caught:
            install_karc_archive(
                source,
                data_root,
                _CallbackSchemas(mutate),
            )
        assert caught.value.code == "KARC_INSTALL_SOURCE_CHANGED"
    finally:
        source.write_bytes(original)


def test_install_rejects_registry_aba_during_early_schema_callbacks(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    registry = data_root / "registry" / "global.json"
    registry.parent.mkdir(parents=True)
    original_document = empty_installed_registry(resolve_install_scope())
    original = canonical_bytes(original_document)
    registry.write_bytes(original)
    changed = dict(original_document)
    changed["revision"] = 9
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            registry.write_bytes(canonical_bytes(changed))
            phase = 1
        elif phase == 1:
            registry.write_bytes(original)
            phase = 2

    with pytest.raises(KokoroError) as caught:
        install_karc_archive(
            source,
            data_root,
            _CallbackSchemas(mutate),
        )

    assert caught.value.code == "KARC_INSTALL_CONFLICT"
    assert registry.read_bytes() == original
    assert not (data_root / "archives").exists()


def test_workspace_identity_aba_across_schema_callbacks_is_rejected(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    displaced = tmp_path / "workspace-displaced"
    data_root = tmp_path / "data"

    def mutate(call: int, _name: str) -> None:
        if call == 1:
            workspace.rename(displaced)
            workspace.mkdir()
        elif call == 2:
            workspace.rmdir()
            displaced.rename(workspace)

    try:
        with pytest.raises(KokoroError) as caught:
            install_karc_archive(
                source,
                data_root,
                _CallbackSchemas(mutate),
                workspace_root=workspace,
            )
        assert caught.value.code == "KARC_SCOPE_CHANGED"
    finally:
        if workspace.exists() and displaced.exists():
            workspace.rmdir()
            displaced.rename(workspace)


def test_staging_member_aba_across_schema_callbacks_is_rejected(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    changed: list[tuple[Path, bytes]] = []

    def mutate(_call: int, _name: str) -> None:
        stages = [
            path
            for path in data_root.rglob("*.staging")
            if path.is_dir() and (path / "manifest.json").is_file()
        ]
        if stages and not changed:
            target = stages[0] / "manifest.json"
            original = target.read_bytes()
            changed.append((target, original))
            target.write_bytes(b"{}")
        elif changed and changed[0][0].exists():
            changed[0][0].write_bytes(changed[0][1])

    try:
        with pytest.raises(KokoroError) as caught:
            install_karc_archive(
                source,
                data_root,
                _CallbackSchemas(mutate),
            )
        assert caught.value.code == "KARC_INSTALL_STAGING_INVALID"
    finally:
        if changed and changed[0][0].exists():
            changed[0][0].write_bytes(changed[0][1])


def test_staging_member_hardlink_is_rejected_during_validation(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    alias = tmp_path / "staging-member-alias.json"

    def mutate(_call: int, _name: str) -> None:
        stages = [
            path
            for path in data_root.rglob("*.staging")
            if path.is_dir() and (path / "manifest.json").is_file()
        ]
        if stages and not alias.exists():
            try:
                alias.hardlink_to(stages[0] / "manifest.json")
            except OSError as error:
                pytest.skip(
                    f"hardlinks unavailable: {type(error).__name__}"
                )

    try:
        with pytest.raises(KokoroError) as caught:
            install_karc_archive(
                source,
                data_root,
                _CallbackSchemas(mutate),
            )
        assert caught.value.code == "KARC_INSTALL_STAGING_INVALID"
    finally:
        if alias.exists():
            alias.unlink()


def test_install_journal_aba_across_schema_callbacks_is_rejected(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    journal = data_root / "registry" / "journals" / "global.json"
    displaced = journal.with_name("global.displaced.json")
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0 and journal.is_file():
            payload = journal.read_bytes()
            journal.rename(displaced)
            journal.write_bytes(payload)
            phase = 1
        elif phase == 1:
            journal.unlink()
            displaced.rename(journal)
            phase = 2

    try:
        with pytest.raises(KokoroError) as caught:
            install_karc_archive(
                source,
                data_root,
                _CallbackSchemas(mutate),
            )
        assert caught.value.code == "KARC_INSTALL_JOURNAL_CHANGED"
    finally:
        if journal.exists() and displaced.exists():
            journal.unlink()
            displaced.rename(journal)


def test_journal_cleanup_preserves_a_replacement_staging_file(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    journal = data_root / "registry" / "journals" / "global.json"
    displaced = tmp_path / "generated-journal-staging.json"
    replacement: list[Path] = []
    original_link = installer_module.os.link

    def replace_staging(
        source_path: object,
        destination_path: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        staging = Path(source_path)  # type: ignore[arg-type]
        destination = Path(destination_path)  # type: ignore[arg-type]
        if destination == journal and not replacement:
            staging.rename(displaced)
            staging.write_bytes(b"unrelated replacement")
            replacement.append(staging)
        original_link(source_path, destination_path, *args, **kwargs)

    monkeypatch.setattr(installer_module.os, "link", replace_staging)

    with pytest.raises(KokoroError) as caught:
        install_karc_archive(source, data_root, SCHEMAS)

    assert caught.value.code == "KARC_INSTALL_CLEANUP_FAILED"
    assert caught.value.details == {
        "phase": "journal_staging",
        "reason": "identity_changed",
    }
    assert displaced.is_file()
    assert replacement[0].read_bytes() == b"unrelated replacement"
    assert journal.read_bytes() == b"unrelated replacement"


def test_published_archive_identity_aba_is_rejected(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    displaced = tmp_path / "published-archive-displaced.karc"
    changed: list[Path] = []
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        archives = list((data_root / "archives").glob("*.karc"))
        if phase == 0 and archives:
            final = archives[0]
            payload = final.read_bytes()
            final.rename(displaced)
            final.write_bytes(payload)
            changed.append(final)
            phase = 1
        elif phase == 1:
            changed[0].unlink()
            displaced.rename(changed[0])
            phase = 2

    try:
        with pytest.raises(KokoroError) as caught:
            install_karc_archive(
                source,
                data_root,
                _CallbackSchemas(mutate),
            )
        assert caught.value.code == "KARC_INSTALL_PATH_CHANGED"
    finally:
        if changed and changed[0].exists() and displaced.exists():
            changed[0].unlink()
            displaced.rename(changed[0])


def test_published_installation_aba_during_registry_callbacks_is_rejected(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    final = data_root / "installed" / "global" / "rin-aster" / "1.0.0"
    displaced = final.with_name("1.0.0-displaced")
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0 and final.is_dir():
            final.rename(displaced)
            final.mkdir()
            phase = 1
        elif phase == 1:
            final.rmdir()
            displaced.rename(final)
            phase = 2

    try:
        with pytest.raises(KokoroError) as caught:
            install_karc_archive(
                source,
                data_root,
                _CallbackSchemas(mutate),
            )
        assert caught.value.code == "KARC_INSTALL_PATH_CHANGED"
    finally:
        if final.exists() and displaced.exists():
            final.rmdir()
            displaced.rename(final)


@pytest.mark.parametrize("value", ["con", "lpt1", "aux"])
def test_removal_rejects_portable_device_names(value: str, tmp_path: Path) -> None:
    with pytest.raises(KokoroError) as caught:
        remove_installed_pack(
            tmp_path / "data",
            value,
            "rin-aster",
            "1.0.0",
            SCHEMAS,
            dry_run=True,
        )

    assert caught.value.code == "KARC_REMOVE_IDENTITY_INVALID"
    assert not (tmp_path / "data").exists()


def test_workspace_registry_scan_stops_at_total_entry_limit(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    registries = data_root / "registry" / "workspaces"
    registries.mkdir()
    for index in range(1025):
        (registries / f".{index:064x}.lock").write_bytes(b"0")

    with pytest.raises(KokoroError) as caught:
        remove_installed_pack(
            data_root,
            "original",
            "rin-aster",
            "1.0.0",
            SCHEMAS,
            dry_run=True,
        )

    assert caught.value.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID"


def test_registry_staging_hardlink_is_rejected_before_publication(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    alias = tmp_path / "registry-staging-alias.json"

    def link_staging(name: str) -> None:
        if name != "registry_staged":
            return
        candidates = list((data_root / "registry").glob(".global.json.*.tmp"))
        assert len(candidates) == 1
        alias.hardlink_to(candidates[0])

    monkeypatch.setattr(installer_module, "_install_failure_point", link_staging)

    with pytest.raises(KokoroError) as caught:
        install_karc_archive(source, data_root, SCHEMAS)

    assert caught.value.code == "KARC_REGISTRY_CHANGED"
    assert not (data_root / "registry" / "global.json").exists()
    assert alias.is_file()


def test_registry_cleanup_never_deletes_a_replacement_staging_file(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    displaced = tmp_path / "generated-registry-staging.json"
    replacement: list[Path] = []

    def replace_staging(name: str) -> None:
        if name != "registry_staged":
            return
        candidates = list((data_root / "registry").glob(".global.json.*.tmp"))
        assert len(candidates) == 1
        staging = candidates[0]
        staging.rename(displaced)
        staging.write_bytes(b"unrelated replacement")
        replacement.append(staging)

    monkeypatch.setattr(installer_module, "_install_failure_point", replace_staging)

    with pytest.raises(KokoroError) as caught:
        install_karc_archive(source, data_root, SCHEMAS)

    assert caught.value.code == "KARC_INSTALL_CLEANUP_FAILED"
    assert caught.value.details == {
        "phase": "registry_staging",
        "reason": "identity_changed",
    }
    assert displaced.is_file()
    assert replacement[0].read_bytes() == b"unrelated replacement"


def test_dry_run_rejects_a_redirected_data_root(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    outside = tmp_path / "outside"
    outside.mkdir()
    data_root = tmp_path / "data"
    try:
        data_root.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {type(error).__name__}")

    with pytest.raises(KokoroError) as caught:
        install_karc_archive(source, data_root, SCHEMAS, dry_run=True)

    assert caught.value.code == "KARC_INSTALL_PATH_INVALID"
    assert list(outside.iterdir()) == []


def test_dry_run_always_checks_data_root_redirect_detection(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    data_root.mkdir()
    original = installer_module._is_redirect

    def redirected(path: Path, path_stat: object) -> bool:
        if path == data_root:
            return True
        return original(path, path_stat)  # type: ignore[arg-type]

    monkeypatch.setattr(installer_module, "_is_redirect", redirected)

    with pytest.raises(KokoroError) as caught:
        install_karc_archive(source, data_root, SCHEMAS, dry_run=True)

    assert caught.value.code == "KARC_INSTALL_PATH_INVALID"


def test_direct_preview_rejects_data_root_aba_across_schema_callbacks(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive = build_private_archive(rin_verified_release)
    data_root = tmp_path / "data"
    data_root.mkdir()
    displaced = tmp_path / "data-displaced"
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            data_root.rename(displaced)
            data_root.mkdir()
            phase = 1
        elif phase == 1:
            data_root.rmdir()
            displaced.rename(data_root)
            phase = 2

    try:
        with pytest.raises(KokoroError) as caught:
            preview_karc_install(
                archive,
                data_root,
                _CallbackSchemas(mutate),
            )
        assert caught.value.code == "KARC_INSTALL_PATH_CHANGED"
    finally:
        if data_root.exists() and displaced.exists():
            data_root.rmdir()
            displaced.rename(data_root)


def test_successful_workspace_install_writes_only_under_data_root(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "authorized-data"
    before = _snapshot_outside(tmp_path, data_root)

    install_karc_archive(
        source,
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )

    assert _snapshot_outside(tmp_path, data_root) == before
    assert list(workspace.iterdir()) == []


def test_failed_workspace_install_writes_only_under_data_root(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "authorized-data"
    before = _snapshot_outside(tmp_path, data_root)

    def interrupt(name: str) -> None:
        if name == "installation_staged":
            raise RuntimeError("injected:installation_staged")

    monkeypatch.setattr(installer_module, "_install_failure_point", interrupt)

    with pytest.raises(RuntimeError, match="injected:installation_staged"):
        install_karc_archive(
            source,
            data_root,
            SCHEMAS,
            workspace_root=workspace,
        )

    assert _snapshot_outside(tmp_path, data_root) == before
    assert list(workspace.iterdir()) == []


def test_removal_rejects_registry_aba_across_schema_callbacks(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    registry = data_root / "registry" / "global.json"
    original = registry.read_bytes()
    changed = json.loads(original)
    changed["revision"] += 9
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            registry.write_bytes(canonical_bytes(changed))
            phase = 1
        elif phase == 1:
            registry.write_bytes(original)
            phase = 2

    with pytest.raises(KokoroError) as caught:
        remove_installed_pack(
            data_root,
            "original",
            "rin-aster",
            "1.0.0",
            _CallbackSchemas(mutate),
        )

    assert caught.value.code == "KARC_REMOVE_CONFLICT"
    assert registry.read_bytes() == canonical_bytes(changed)
    assert (
        data_root / "installed" / "global" / "rin-aster" / "1.0.0"
    ).is_dir()


def test_removal_rejects_workspace_aba_across_schema_callbacks(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    displaced = tmp_path / "workspace-displaced"
    data_root = tmp_path / "data"
    install_karc_archive(
        source,
        data_root,
        SCHEMAS,
        workspace_root=workspace,
    )
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            workspace.rename(displaced)
            workspace.mkdir()
            phase = 1
        elif phase == 1:
            workspace.rmdir()
            displaced.rename(workspace)
            phase = 2

    try:
        with pytest.raises(KokoroError) as caught:
            remove_installed_pack(
                data_root,
                "original",
                "rin-aster",
                "1.0.0",
                _CallbackSchemas(mutate),
                workspace_root=workspace,
            )
        assert caught.value.code == "KARC_SCOPE_CHANGED"
    finally:
        if workspace.exists() and displaced.exists():
            workspace.rmdir()
            displaced.rename(workspace)


def test_removal_rejects_installed_tree_aba_across_schema_callbacks(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    plan = install_karc_archive(source, data_root, SCHEMAS)
    final = data_root / "installed" / Path(plan["relative_path"])
    displaced = final.with_name(f"{final.name}-displaced")
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            final.rename(displaced)
            final.mkdir()
            phase = 1
        elif phase == 1:
            final.rmdir()
            displaced.rename(final)
            phase = 2

    try:
        with pytest.raises(KokoroError) as caught:
            remove_installed_pack(
                data_root,
                "original",
                "rin-aster",
                "1.0.0",
                _CallbackSchemas(mutate),
            )
        assert caught.value.code == "KARC_REMOVE_PATH_CHANGED"
    finally:
        if final.exists() and displaced.exists():
            final.rmdir()
            displaced.rename(final)


def test_removal_rejects_archive_aba_during_archive_validation(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    plan = install_karc_archive(source, data_root, SCHEMAS)
    archive = data_root / "archives" / f"{plan['archive_sha256']}.karc"
    original = archive.read_bytes()
    phase = 0

    def mutate(_call: int, name: str) -> None:
        nonlocal phase
        if name == "installed-pack-registry":
            return
        if phase == 0:
            archive.write_bytes(b"changed during archive validation")
            phase = 1
        elif phase == 1:
            archive.write_bytes(original)
            phase = 2

    try:
        with pytest.raises(KokoroError) as caught:
            remove_installed_pack(
                data_root,
                "original",
                "rin-aster",
                "1.0.0",
                _CallbackSchemas(mutate),
            )
        assert caught.value.code == "KARC_REMOVE_PATH_CHANGED"
    finally:
        archive.write_bytes(original)


def test_removal_rejects_reference_aba_before_the_reference_scan(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    plan = install_karc_archive(source, data_root, SCHEMAS)
    reference = data_root / "config" / "global.json"
    reference.parent.mkdir(parents=True)
    inactive = _default_config(plan)
    inactive["binding"] = None
    original = canonical_bytes(inactive)
    reference.write_bytes(original)
    active = canonical_bytes(_default_config(plan))
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            reference.write_bytes(active)
            phase = 1
        elif phase == 1:
            reference.write_bytes(original)
            phase = 2

    with pytest.raises(KokoroError) as caught:
        remove_installed_pack(
            data_root,
            "original",
            "rin-aster",
            "1.0.0",
            _CallbackSchemas(mutate),
        )

    assert caught.value.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID"
    assert reference.read_bytes() == active


@pytest.mark.parametrize("reference_kind", ["session", "migration"])
def test_removal_rejects_directory_reference_aba_before_scan(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    reference_kind: str,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    plan = install_karc_archive(source, data_root, SCHEMAS)
    if reference_kind == "session":
        reference = data_root / "sessions" / "candidate.json"
        original = canonical_bytes(_session_manifest(plan, active=False))
        changed = canonical_bytes(_session_manifest(plan, active=True))
    else:
        reference = data_root / "migrations" / "candidate.json"
        original = canonical_bytes(_migration_record(plan, referenced=False))
        changed = canonical_bytes(_migration_record(plan, referenced=True))
    reference.parent.mkdir(parents=True)
    reference.write_bytes(original)
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            reference.write_bytes(changed)
            phase = 1
        elif phase == 1:
            reference.write_bytes(original)
            phase = 2

    with pytest.raises(KokoroError) as caught:
        remove_installed_pack(
            data_root,
            "original",
            "rin-aster",
            "1.0.0",
            _CallbackSchemas(mutate),
        )

    assert caught.value.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID"


def test_removal_rejects_workspace_registry_aba_before_archive_scan(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    workspace = tmp_path / "other-workspace"
    workspace.mkdir()
    workspace_scope = resolve_install_scope(workspace)
    registry = (
        data_root
        / "registry"
        / "workspaces"
        / f"{workspace_scope.workspace_id}.json"
    )
    registry.parent.mkdir()
    original = empty_installed_registry(workspace_scope)
    registry.write_bytes(canonical_bytes(original))
    changed = dict(original)
    changed["revision"] = 9
    phase = 0

    def mutate(_call: int, _name: str) -> None:
        nonlocal phase
        if phase == 0:
            registry.write_bytes(canonical_bytes(changed))
            phase = 1
        elif phase == 1:
            registry.write_bytes(canonical_bytes(original))
            phase = 2

    with pytest.raises(KokoroError) as caught:
        remove_installed_pack(
            data_root,
            "original",
            "rin-aster",
            "1.0.0",
            _CallbackSchemas(mutate),
        )

    assert caught.value.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID"
    assert registry.read_bytes() == canonical_bytes(changed)


@pytest.mark.parametrize(
    ("directory_name", "schema_name"),
    [
        ("sessions", "session-manifest"),
        ("migrations", "pack-migration-plan"),
    ],
)
def test_reference_scan_stops_at_limit_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory_name: str,
    schema_name: str,
) -> None:
    directory = tmp_path / directory_name
    directory.mkdir()
    first = directory / "first.json"
    second = directory / "second.json"
    first.write_bytes(b"{}")
    second.write_bytes(b"{}")
    consumed = [0]
    paths = [first, second, directory / "must-not-be-inspected.json"]

    def lazy_scandir(_path: object) -> _CountingScandir:
        return _CountingScandir(paths, consumed)

    monkeypatch.setattr(installer_module.os, "scandir", lazy_scandir)

    with pytest.raises(KokoroError) as caught:
        installer_module._read_reference_directory(
            directory,
            2,
            schema_name,
            SCHEMAS,
        )

    assert caught.value.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID"
    assert consumed == [3]


def test_workspace_registry_capture_stops_at_limit_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "workspaces"
    directory.mkdir()
    first = directory / f".{1:064x}.lock"
    second = directory / f".{2:064x}.lock"
    first.write_bytes(b"0")
    second.write_bytes(b"0")
    consumed = [0]
    paths = [first, second, directory / f".{3:064x}.lock"]

    def lazy_scandir(_path: object) -> _CountingScandir:
        return _CountingScandir(paths, consumed)

    monkeypatch.setattr(installer_module, "_MAX_WORKSPACE_REGISTRIES", 2)
    monkeypatch.setattr(installer_module.os, "scandir", lazy_scandir)

    with pytest.raises(KokoroError) as caught:
        installer_module._capture_workspace_registries(directory, None)

    assert caught.value.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID"
    assert consumed == [3]


def test_installed_tree_scan_stops_at_limit_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "installed"
    directory.mkdir()
    first = directory / "first.json"
    second = directory / "second.json"
    first.write_bytes(b"1")
    second.write_bytes(b"2")
    consumed = [0]
    paths = [first, second, directory / "must-not-be-inspected.json"]

    def lazy_scandir(_path: object) -> _CountingScandir:
        return _CountingScandir(paths, consumed)

    monkeypatch.setattr(installer_module, "_MAX_INSTALLED_ENTRIES", 2)
    monkeypatch.setattr(installer_module.os, "scandir", lazy_scandir)

    assert installer_module._installed_files(directory) is None
    assert consumed == [3]


def test_oversized_registry_is_rejected_before_json_parsing(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    registry = data_root / "registry" / "global.json"
    registry.parent.mkdir(parents=True)
    registry.write_bytes(b"0" * (registry_module._MAX_REGISTRY_BYTES + 1))

    with pytest.raises(KokoroError) as caught:
        load_installed_registry(data_root, SCHEMAS)

    assert caught.value.code == "KARC_REGISTRY_LIMIT_EXCEEDED"


def test_oversized_recovery_journal_is_preserved_and_rejected(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    journal = data_root / "registry" / "journals" / "global.json"
    journal.parent.mkdir(parents=True)
    payload = b"0" * (installer_module._MAX_JOURNAL_BYTES + 1)
    journal.write_bytes(payload)

    _assert_recovery_required(recover_karc_installations, data_root, SCHEMAS)

    assert journal.read_bytes() == payload


def test_oversized_removal_reference_is_rejected_before_validation(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "rin-aster.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    install_karc_archive(source, data_root, SCHEMAS)
    reference = data_root / "config" / "global.json"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"0" * (installer_module._MAX_REFERENCE_BYTES + 1))

    with pytest.raises(KokoroError) as caught:
        remove_installed_pack(
            data_root,
            "original",
            "rin-aster",
            "1.0.0",
            SCHEMAS,
            dry_run=True,
        )

    assert caught.value.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID"
