"""Explicit-consent persistent character state and storage primitives."""

from kokoroarc.persistence.consent import (
    grant_consent,
    load_consent,
    revoke_consent,
)
from kokoroarc.persistence.memory import (
    MemoryReferenceView,
    MemoryRemovalResult,
    add_memory_reference,
    list_memory_references,
    remove_memory_reference,
)
from kokoroarc.persistence.migrations import (
    apply_state_migration,
    preview_state_migration,
)
from kokoroarc.persistence.state import (
    PersistentResetPreview,
    advance_persistent_mood_turn,
    apply_persistent_mood_event,
    apply_persistent_relationship_event,
    export_persistent_data,
    load_persistent_state,
    preview_persistent_reset,
    replay_persistent_state,
    reset_persistent_data,
)

__all__ = [
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
]
