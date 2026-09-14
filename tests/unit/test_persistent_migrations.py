from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from kokorox.errors import KokoroError
from kokorox.packs.compiler import canonical_bytes
from kokorox.persistence.consent import grant_consent
from kokorox.persistence.memory import (
    add_memory_reference,
    list_memory_references,
)
from kokorox.persistence.migrations import (
    apply_state_migration,
    preview_state_migration,
)
from kokorox.persistence.state import (
    apply_persistent_mood_event,
    apply_persistent_relationship_event,
    replay_persistent_state,
)
from kokorox.schemas import SchemaRegistry

from persistence_support import (
    ConsentedRin,
    MigrationTarget,
    approved_memory_inputs,
    consented_rin,
    install_rin_successor,
    interaction_event,
    mood_event,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def _assert_code(code: str, action: Callable[[], Any]) -> KokoroError:
    with pytest.raises(KokoroError) as caught:
        action()
    assert caught.value.code == code
    return caught.value


def _source_state(consented: ConsentedRin) -> dict[str, Any]:
    first = apply_persistent_relationship_event(
        consented.data_root,
        "rin-aster",
        interaction_event("source-event-1", 0),
        consented.consent["consent_id"],
        consented.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="source-relationship-operation-1",
    )
    second = apply_persistent_relationship_event(
        consented.data_root,
        "rin-aster",
        interaction_event("source-event-2", 1),
        consented.consent["consent_id"],
        consented.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=first["revision"],
        operation_id="source-relationship-operation-2",
    )
    mood = mood_event("source-mood-1", 0)
    mood["trigger_strength"] = "strong"
    return apply_persistent_mood_event(
        consented.data_root,
        "rin-aster",
        mood,
        consented.consent["consent_id"],
        consented.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=second["revision"],
        operation_id="source-mood-operation-1",
    )


def _target(
    consented: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
    permissions: Sequence[str] = (
        "relationship_state",
        "mood_state",
        "memory_references",
    ),
) -> MigrationTarget:
    return install_rin_successor(
        consented,
        tmp_path,
        verified_release_factory,
        permissions=permissions,
    )


def test_migrates_to_regranted_installation_and_replays_exactly(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
) -> None:
    source = _source_state(consented_rin)
    state_root = (
        consented_rin.data_root
        / "persistent-state"
        / "global"
        / "original"
        / "rin-aster"
    )
    source_generation = state_root / "generations" / source["generation_id"]
    target = _target(consented_rin, tmp_path, verified_release_factory)

    _assert_code(
        "PERSISTENCE_STATE_MIGRATION_REQUIRED",
        lambda: apply_persistent_relationship_event(
            consented_rin.data_root,
            "rin-aster",
            interaction_event("stale-event", 2),
            target.consent["consent_id"],
            target.consent["grant_revision"],
            SCHEMAS,
            expected_state_revision=source["revision"],
            operation_id="stale-operation",
        ),
    )

    plan = preview_state_migration(
        consented_rin.data_root,
        "rin-aster",
        target.consent["consent_id"],
        target.consent["grant_revision"],
        SCHEMAS,
        mood_strategy="preserve_identical_contract",
    )
    SCHEMAS.validate("state-migration-plan", plan)
    assert plan["source"]["installation"] == source["installation"]
    assert plan["target"]["installation"] == target.installation_binding
    assert plan["source"]["generation_id"] == source["generation_id"]
    assert plan["executable_code_accepted"] is False

    migrated = apply_state_migration(
        consented_rin.data_root,
        "rin-aster",
        target.consent["consent_id"],
        target.consent["grant_revision"],
        plan,
        SCHEMAS,
        mood_strategy="preserve_identical_contract",
    )
    assert migrated["installation"] == target.installation_binding
    assert migrated["consent"] == {
        "consent_id": target.consent["consent_id"],
        "grant_revision": target.consent["grant_revision"],
    }
    assert migrated["relationship"] == source["relationship"]
    assert migrated["mood"] == source["mood"]
    assert migrated["generation_id"] != source["generation_id"]
    assert source_generation.is_dir()
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == migrated

    retry = apply_state_migration(
        consented_rin.data_root,
        "rin-aster",
        target.consent["consent_id"],
        target.consent["grant_revision"],
        plan,
        SCHEMAS,
        mood_strategy="preserve_identical_contract",
    )
    assert canonical_bytes(retry) == canonical_bytes(migrated)


def test_reset_neutral_obeys_target_permissions_and_does_not_copy_memory(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
) -> None:
    source = _source_state(consented_rin)
    host_id, summary, localized = approved_memory_inputs()
    memory = add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )
    target = _target(
        consented_rin,
        tmp_path,
        verified_release_factory,
        permissions=("relationship_state",),
    )

    _assert_code(
        "PERSISTENCE_MIGRATION_INVALID",
        lambda: preview_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    plan = preview_state_migration(
        consented_rin.data_root,
        "rin-aster",
        target.consent["consent_id"],
        target.consent["grant_revision"],
        SCHEMAS,
        mood_strategy="reset_neutral",
    )
    migrated = apply_state_migration(
        consented_rin.data_root,
        "rin-aster",
        target.consent["consent_id"],
        target.consent["grant_revision"],
        plan,
        SCHEMAS,
        mood_strategy="reset_neutral",
    )
    assert migrated["relationship"] == source["relationship"]
    assert migrated["mood"] == {
        "revision": 0,
        "primary": "neutral",
        "secondary": None,
        "arousal": 0.0,
        "valence": 0.0,
        "intensity": 0.0,
        "remaining_turns": 0,
        "expires_after_turns": 0,
        "triggering_event_id": None,
        "applied_event_ids": [],
    }
    retained = list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )
    assert tuple(item.reference for item in retained) == (memory,)
    assert {
        key: retained[0].reference[key]
        for key in (
            "installation_id",
            "namespace",
            "character_id",
            "character_version",
            "archive_sha256",
            "compiled_sha256",
        )
    } == source["installation"]
    assert retained[0].active_consent_generation is False


def test_nonzero_relationship_requires_target_relationship_permission(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
) -> None:
    _source_state(consented_rin)
    target = _target(
        consented_rin,
        tmp_path,
        verified_release_factory,
        permissions=("mood_state",),
    )

    _assert_code(
        "PERSISTENCE_MIGRATION_INVALID",
        lambda: preview_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )


def test_a_regrant_on_the_same_installation_continues_retained_state(
    consented_rin: ConsentedRin,
) -> None:
    """Adding a permission stranded every durable session: migration refused it."""

    data_root = consented_rin.data_root
    first = apply_persistent_relationship_event(
        data_root,
        "rin-aster",
        interaction_event("before-regrant", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="before-regrant-operation",
    )
    regranted = grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state", "memory_references"],
        SCHEMAS,
        expected_revision=consented_rin.consent["grant_revision"],
    )
    assert regranted["grant_revision"] > consented_rin.consent["grant_revision"]

    second = apply_persistent_relationship_event(
        data_root,
        "rin-aster",
        interaction_event("after-regrant", 1),
        regranted["consent_id"],
        regranted["grant_revision"],
        SCHEMAS,
        expected_state_revision=first["revision"],
        operation_id="after-regrant-operation",
    )

    assert second["relationship"]["revision"] == 2
    assert second["consent"] == {
        "consent_id": regranted["consent_id"],
        "grant_revision": regranted["grant_revision"],
    }
    assert replay_persistent_state(data_root, "rin-aster", SCHEMAS) == second


def test_a_state_written_under_a_later_grant_cannot_go_back(
    consented_rin: ConsentedRin,
) -> None:
    from kokorox.persistence.state import _consent_continues

    held = {"consent_id": "consent-a", "grant_revision": 3}

    assert _consent_continues(held, {"consent_id": "consent-a", "grant_revision": 3})
    assert _consent_continues(held, {"consent_id": "consent-a", "grant_revision": 4})
    assert not _consent_continues(held, {"consent_id": "consent-a", "grant_revision": 2})
    assert not _consent_continues(held, {"consent_id": "consent-b", "grant_revision": 4})
    assert not _consent_continues(held, {"consent_id": "consent-a", "grant_revision": True})
