from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from kokoroarc.distribution import (
    install_karc_archive,
    load_installed_registry,
    remove_installed_pack,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
import kokoroarc.persistence as persistence
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.state import SessionStore

from karc_test_support import build_private_archive
from persistence_support import (
    approved_memory_inputs,
    interaction_event,
    mood_event,
)


REPOSITORY_ROOT = Path.cwd().resolve()
SCHEMAS = SchemaRegistry(Path("schemas/v1"))
PERSISTENCE_ROOTS = {
    "consents",
    "memory-references",
    "persistence-locks",
    "persistence-transactions",
    "persistent-state",
}
STABLE_PERSISTENCE_API = (
    "grant_consent",
    "load_consent",
    "revoke_consent",
    "MemoryReferenceView",
    "MemoryRemovalResult",
    "add_memory_reference",
    "list_memory_references",
    "remove_memory_reference",
    "apply_state_migration",
    "preview_state_migration",
    "PersistentResetPreview",
    "advance_persistent_mood_turn",
    "apply_persistent_mood_event",
    "apply_persistent_relationship_event",
    "export_persistent_data",
    "load_persistent_state",
    "preview_persistent_reset",
    "replay_persistent_state",
    "reset_persistent_data",
)


def _assert_code(code: str, action: Any) -> KokoroError:
    with pytest.raises(KokoroError) as raised:
        action()
    assert raised.value.code == code
    return raised.value


def _install_verified_rin(
    release: dict[str, Any],
    data_root: Path,
    archive_path: Path,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    archive_path.write_bytes(build_private_archive(release))
    return install_karc_archive(
        archive_path,
        data_root,
        SCHEMAS,
        workspace_root=workspace_root,
    )


def _assert_no_persistence_roots(data_root: Path) -> None:
    assert not any((data_root / name).exists() for name in PERSISTENCE_ROOTS)


def _fresh_process_replay(
    data_root: Path,
    working_directory: Path,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys\n"
                "from pathlib import Path\n"
                "from kokoroarc.config import resolve_schema_dir\n"
                "from kokoroarc.persistence import replay_persistent_state\n"
                "from kokoroarc.schemas import SchemaRegistry\n"
                "workspace = None if sys.argv[2] == '-' else Path(sys.argv[2])\n"
                "result = replay_persistent_state(\n"
                "    Path(sys.argv[1]), 'rin-aster',\n"
                "    SchemaRegistry(resolve_schema_dir()),\n"
                "    workspace_root=workspace,\n"
                ")\n"
                "print(json.dumps(result, sort_keys=True, separators=(',', ':')))\n"
            ),
            str(data_root),
            "-" if workspace_root is None else str(workspace_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        cwd=working_directory,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)


def _exercise_persistent_lifecycle(
    data_root: Path,
    installation: dict[str, Any],
    process_root: Path,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    grant = persistence.grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state", "mood_state", "memory_references"],
        SCHEMAS,
        workspace_root=workspace_root,
        expected_revision=0,
    )
    relationship = persistence.apply_persistent_relationship_event(
        data_root,
        "rin-aster",
        interaction_event("workflow-relationship-01", 0),
        grant["consent_id"],
        grant["grant_revision"],
        SCHEMAS,
        workspace_root=workspace_root,
        expected_state_revision=0,
        operation_id="workflow-relationship-operation-01",
    )
    mood_input = mood_event("workflow-mood-01", 0)
    mood_input["trigger_strength"] = "strong"
    state = persistence.apply_persistent_mood_event(
        data_root,
        "rin-aster",
        mood_input,
        grant["consent_id"],
        grant["grant_revision"],
        SCHEMAS,
        workspace_root=workspace_root,
        expected_state_revision=relationship["revision"],
        operation_id="workflow-mood-operation-01",
    )
    host_id, summary, localized = approved_memory_inputs()
    memory = persistence.add_memory_reference(
        data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        grant["consent_id"],
        grant["grant_revision"],
        SCHEMAS,
        workspace_root=workspace_root,
    )

    assert _fresh_process_replay(
        data_root,
        process_root,
        workspace_root=workspace_root,
    ) == state
    exported = persistence.export_persistent_data(
        data_root,
        "rin-aster",
        SCHEMAS,
        workspace_root=workspace_root,
    )
    SCHEMAS.validate("persistence-export", exported)
    assert exported["consent"] == grant
    assert exported["state"] == state
    assert exported["memory_references"] == [memory]
    assert exported["memory_count"] == 1

    revoked = persistence.revoke_consent(
        data_root,
        "rin-aster",
        grant["consent_id"],
        SCHEMAS,
        workspace_root=workspace_root,
        expected_revision=grant["grant_revision"],
    )
    _assert_code(
        "PERSISTENCE_CONSENT_REVOKED",
        lambda: persistence.apply_persistent_relationship_event(
            data_root,
            "rin-aster",
            interaction_event("workflow-revoked-relationship-01", 1),
            grant["consent_id"],
            revoked["grant_revision"],
            SCHEMAS,
            workspace_root=workspace_root,
            expected_state_revision=state["revision"],
            operation_id="workflow-revoked-relationship-operation-01",
        ),
    )
    revoked_mood = mood_event("workflow-revoked-mood-01", 1)
    revoked_mood["trigger_strength"] = "strong"
    _assert_code(
        "PERSISTENCE_CONSENT_REVOKED",
        lambda: persistence.apply_persistent_mood_event(
            data_root,
            "rin-aster",
            revoked_mood,
            grant["consent_id"],
            revoked["grant_revision"],
            SCHEMAS,
            workspace_root=workspace_root,
            expected_state_revision=state["revision"],
            operation_id="workflow-revoked-mood-operation-01",
        ),
    )
    _assert_code(
        "PERSISTENCE_CONSENT_REVOKED",
        lambda: persistence.add_memory_reference(
            data_root,
            "rin-aster",
            "host-memory-revoked-write-01",
            summary,
            localized,
            grant["consent_id"],
            revoked["grant_revision"],
            SCHEMAS,
            workspace_root=workspace_root,
        ),
    )

    relationship_reset = persistence.preview_persistent_reset(
        data_root,
        "rin-aster",
        grant["consent_id"],
        SCHEMAS,
        workspace_root=workspace_root,
        target="relationship",
        reset_id="workflow-reset-relationship-01",
    )
    persistence.reset_persistent_data(
        data_root,
        "rin-aster",
        relationship_reset,
        grant["consent_id"],
        SCHEMAS,
        workspace_root=workspace_root,
    )
    mood_reset = persistence.preview_persistent_reset(
        data_root,
        "rin-aster",
        grant["consent_id"],
        SCHEMAS,
        workspace_root=workspace_root,
        target="mood",
        reset_id="workflow-reset-mood-01",
    )
    persistence.reset_persistent_data(
        data_root,
        "rin-aster",
        mood_reset,
        grant["consent_id"],
        SCHEMAS,
        workspace_root=workspace_root,
    )
    removed_memory = persistence.remove_memory_reference(
        data_root,
        "rin-aster",
        host_id,
        grant["consent_id"],
        SCHEMAS,
        workspace_root=workspace_root,
        identifier_kind="host_memory_id",
    )
    assert removed_memory.removed
    reset_state = persistence.replay_persistent_state(
        data_root,
        "rin-aster",
        SCHEMAS,
        workspace_root=workspace_root,
    )
    assert reset_state is not None
    assert reset_state["relationship"]["revision"] == 0
    assert reset_state["mood"]["revision"] == 0
    assert persistence.list_memory_references(
        data_root,
        "rin-aster",
        SCHEMAS,
        workspace_root=workspace_root,
    ) == ()

    removal = remove_installed_pack(
        data_root,
        "original",
        "rin-aster",
        "1.0.0",
        SCHEMAS,
        workspace_root=workspace_root,
    )
    installed_path = data_root / "installed" / Path(installation["relative_path"])
    assert removal["will_write"] is True
    assert not installed_path.exists()
    return {"grant": grant, "revoked": revoked, "removal": removal}


def test_stable_persistence_api_exports_exact_public_surface() -> None:
    assert tuple(persistence.__all__) == STABLE_PERSISTENCE_API
    for name in STABLE_PERSISTENCE_API:
        assert callable(getattr(persistence, name))


def test_global_persistence_workflow_survives_a_fresh_process_and_removes(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    installation = _install_verified_rin(
        rin_verified_release,
        data_root,
        tmp_path / "rin-global.karc",
    )
    _assert_no_persistence_roots(data_root)
    process_root = tmp_path / "fresh-process"
    process_root.mkdir()

    result = _exercise_persistent_lifecycle(
        data_root,
        installation,
        process_root,
    )

    assert result["grant"]["scope"] == "global"
    assert result["revoked"]["status"] == "revoked"
    assert load_installed_registry(data_root, SCHEMAS)["entries"] == {}


def test_workspace_persistence_workflow_leaves_global_scope_unchanged(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    global_installation = _install_verified_rin(
        rin_verified_release,
        data_root,
        tmp_path / "rin-global.karc",
    )
    global_consent = persistence.grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state", "mood_state", "memory_references"],
        SCHEMAS,
        expected_revision=0,
    )
    global_registry_before = canonical_bytes(
        load_installed_registry(data_root, SCHEMAS)
    )
    global_consent_before = canonical_bytes(global_consent)
    workspace_installation = _install_verified_rin(
        rin_verified_release,
        data_root,
        tmp_path / "rin-workspace.karc",
        workspace_root=workspace_root,
    )
    process_root = tmp_path / "fresh-process"
    process_root.mkdir()

    result = _exercise_persistent_lifecycle(
        data_root,
        workspace_installation,
        process_root,
        workspace_root=workspace_root,
    )

    assert result["grant"]["scope"] == "workspace"
    assert canonical_bytes(load_installed_registry(data_root, SCHEMAS)) == (
        global_registry_before
    )
    assert canonical_bytes(
        persistence.load_consent(data_root, "rin-aster", SCHEMAS)
    ) == global_consent_before
    global_path = data_root / "installed" / Path(
        global_installation["relative_path"]
    )
    assert global_path.is_dir()


def test_session_store_never_calls_or_creates_persistent_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("SessionStore called a persistence API")

    for name in STABLE_PERSISTENCE_API:
        monkeypatch.setattr(persistence, name, forbidden, raising=False)
    data_root = tmp_path / "session-data"
    store = SessionStore(data_root)
    started = store.start("session-01", "rin-aster", "1.0.0", "a" * 64)
    state = store.apply(
        "session-01",
        interaction_event("session-event-01", 0),
        expected_character_id="rin-aster",
        expected_character_version="1.0.0",
        expected_compiled_pack_hash="a" * 64,
        expected_lifecycle_generation=started["lifecycle_generation"],
    )
    ended = store.end("session-01")

    assert state["revision"] == 1
    assert ended["active"] is False
    assert {path.name for path in data_root.iterdir()} <= {
        "events",
        "session-locks",
        "sessions",
        "state",
    }
    _assert_no_persistence_roots(data_root)
