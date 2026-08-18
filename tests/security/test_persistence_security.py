import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
import kokoroarc.persistence._storage as storage
from kokoroarc.persistence.consent import grant_consent, load_consent
from kokoroarc.persistence.memory import (
    add_memory_reference,
    list_memory_references,
    remove_memory_reference,
)
from kokoroarc.persistence.state import (
    apply_persistent_mood_event,
    apply_persistent_relationship_event,
    replay_persistent_state,
)
from kokoroarc.schemas import SchemaRegistry

from persistence_support import (
    ConsentedRin,
    approved_memory_inputs,
    consented_rin,
    install_rin,
    interaction_event,
    mood_event,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def _consent() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "consents/global/rin-aster/consent-01",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "consent_id": "rin-aster-consent-01",
        "scope": "global",
        "workspace_id": None,
        "installation": {
            "installation_id": "original.rin-aster.1.0.0.77777777",
            "namespace": "original",
            "character_id": "rin-aster",
            "character_version": "1.0.0",
            "archive_sha256": "7" * 64,
            "compiled_sha256": "2" * 64,
        },
        "permissions": ["relationship_state"],
        "status": "active",
        "grant_revision": 1,
        "revoked_revision": None,
        "persistence_policy": "explicit_consent_only",
    }


def _scope(tmp_path: Path, schemas: Any = SCHEMAS):
    return storage.open_persistence_scope(
        tmp_path / "data",
        schemas,
        character_id="rin-aster",
    )


def _assert_code(code: str, action: Any) -> KokoroError:
    with pytest.raises(KokoroError) as caught:
        action()
    assert caught.value.code == code
    return caught.value


def _persistent_state_root(consented: ConsentedRin) -> Path:
    return (
        consented.data_root
        / "persistent-state"
        / "global"
        / "original"
        / "rin-aster"
    )


def test_storage_rejects_symlinked_canonical_file(tmp_path: Path) -> None:
    target = tmp_path / "outside.json"
    target.write_bytes(canonical_bytes(_consent()))
    linked = tmp_path / "linked.json"
    try:
        linked.symlink_to(target)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")

    scope = _scope(tmp_path)
    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: storage.read_canonical_object(
            linked,
            limit=64 * 1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_storage_rejects_hardlinked_canonical_file(tmp_path: Path) -> None:
    target = tmp_path / "outside.json"
    target.write_bytes(canonical_bytes(_consent()))
    linked = tmp_path / "linked.json"
    try:
        os.link(target, linked)
    except OSError:
        pytest.skip("hardlinks are unavailable on this platform")

    scope = _scope(tmp_path)
    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: storage.read_canonical_object(
            linked,
            limit=64 * 1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_storage_rejects_directory_reported_as_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "history"
    directory.mkdir()
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def marked(path: Path) -> bool:
        return path == directory or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", marked, raising=False)
    scope = _scope(tmp_path)
    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: storage.scan_canonical_directory(
            directory,
            entry_limit=4,
            aggregate_limit=1024,
            file_limit=1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_storage_rejects_real_windows_junction_when_supported(
    tmp_path: Path,
) -> None:
    if os.name != "nt" or not hasattr(Path, "is_junction"):
        pytest.skip("Windows junctions are unavailable on this platform")
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = tmp_path / "history"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("The current account cannot create directory junctions")

    scope = _scope(tmp_path)
    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: storage.scan_canonical_directory(
            junction,
            entry_limit=4,
            aggregate_limit=1024,
            file_limit=1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_storage_rejects_special_file_when_supported(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    path = tmp_path / "event.json"
    try:
        os.mkfifo(path)
    except OSError:
        pytest.skip("The current filesystem cannot create a FIFO")

    scope = _scope(tmp_path)
    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: storage.read_canonical_object(
            path,
            limit=1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_storage_direct_scandir_stops_at_limit_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumed = 0

    class Entry:
        def __init__(self, name: str) -> None:
            self.name = name

        def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
            raise AssertionError("entry stat must not run after the limit is exceeded")

    class Iterator:
        def __enter__(self) -> "Iterator":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def __iter__(self) -> "Iterator":
            return self

        def __next__(self) -> Entry:
            nonlocal consumed
            if consumed >= 10_000:
                raise StopIteration
            consumed += 1
            return Entry(f"{consumed:05d}.json")

    monkeypatch.setattr(storage.os, "scandir", lambda _path: Iterator())

    _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: storage._bounded_regular_json_entries(tmp_path, 3),
    )
    assert consumed == 4


def test_storage_rejects_case_colliding_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Entry:
        def __init__(self, name: str) -> None:
            self.name = name

        def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
            raise AssertionError("case collision must fail before stat")

    class Iterator:
        def __enter__(self) -> "Iterator":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def __iter__(self):
            return iter((Entry("A.json"), Entry("a.json")))

    monkeypatch.setattr(storage.os, "scandir", lambda _path: Iterator())

    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: storage._bounded_regular_json_entries(tmp_path, 3),
    )


def test_storage_detects_file_change_during_schema_callback(
    tmp_path: Path,
) -> None:
    path = tmp_path / "consent.json"
    original = canonical_bytes(_consent())
    changed = _consent()
    changed["grant_revision"] = 2
    path.write_bytes(original)

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            path.write_bytes(canonical_bytes(changed))

    scope = _scope(tmp_path, MutatingSchemas())
    _assert_code(
        "PERSISTENCE_CHANGED",
        lambda: storage.read_canonical_object(
            path,
            limit=64 * 1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_storage_detects_ancestor_replacement_during_callback(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    path = data_root / "consent.json"
    path.write_bytes(canonical_bytes(_consent()))
    displaced = tmp_path / "data-displaced"

    class ReplacingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            data_root.rename(displaced)
            data_root.mkdir()

    scope = storage.open_persistence_scope(
        data_root,
        ReplacingSchemas(),
        character_id="rin-aster",
    )
    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: storage.read_canonical_object(
            path,
            limit=64 * 1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_storage_lock_replacement_invalidates_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(tmp_path)
    with storage._acquire_character_lock(scope) as lock:
        replacement = lock.path.with_suffix(".replacement")
        replacement.write_bytes(b"replacement")
        original_lstat = Path.lstat

        def replaced_identity(path: Path) -> os.stat_result:
            if path == lock.path:
                return original_lstat(replacement)
            return original_lstat(path)

        monkeypatch.setattr(Path, "lstat", replaced_identity)

        assert not lock.owns()
        _assert_code("PERSISTENCE_PATH_UNSAFE", lock.assert_owned)


def test_storage_staging_cleanup_refuses_same_name_replacement(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "staging-parent"
    parent.mkdir()
    staging = storage._create_identified_staging(parent, "state")
    displaced = parent / "displaced"
    staging.path.rename(displaced)
    staging.path.mkdir()
    sentinel = staging.path / "unrelated.txt"
    sentinel.write_text("unrelated", encoding="utf-8")

    _assert_code(
        "PERSISTENCE_CLEANUP_FAILED",
        lambda: storage._cleanup_identified_staging(staging),
    )
    assert displaced.exists()
    assert sentinel.read_text(encoding="utf-8") == "unrelated"


def test_storage_new_publication_is_no_overwrite(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    target = scope.character_root("consents") / "current.json"
    first = canonical_bytes(_consent())
    changed = _consent()
    changed["grant_revision"] = 2
    second = canonical_bytes(changed)

    with storage._acquire_character_lock(scope) as lock:
        storage._publish_new_file(scope, target, first, lock)
        _assert_code(
            "PERSISTENCE_WRITE_FAILED",
            lambda: storage._publish_new_file(scope, target, second, lock),
        )

    assert target.read_bytes() == first


def test_storage_projection_replace_is_exact_and_durable(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    target = scope.character_root("persistent-state") / "current.json"
    first = canonical_bytes({"revision": 1})
    second = canonical_bytes({"revision": 2})

    with storage._acquire_character_lock(scope) as lock:
        storage._replace_file(scope, target, first, lock)
        storage._replace_file(scope, target, second, lock)

    assert target.read_bytes() == second


def test_storage_transaction_marker_is_single_and_exact(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    marker = canonical_bytes({"operation": "reset", "phase": "prepared"})
    changed = canonical_bytes({"operation": "reset", "phase": "committed"})

    with storage._acquire_character_lock(scope) as lock:
        snapshot = storage._write_transaction_marker(scope, marker, lock)
        repeated = storage._write_transaction_marker(scope, marker, lock)
        assert repeated.payload == snapshot.payload
        _assert_code(
            "PERSISTENCE_WRITE_FAILED",
            lambda: storage._write_transaction_marker(scope, changed, lock),
        )
        outcome = storage._remove_transaction_marker(scope, snapshot, lock)

    assert outcome == "not_visible"
    assert not snapshot.path.exists()


def test_storage_rejects_executable_file_mode_when_observable(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX executable mode is unavailable on Windows")
    path = tmp_path / "consent.json"
    path.write_bytes(canonical_bytes(_consent()))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    scope = _scope(tmp_path)

    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: storage.read_canonical_object(
            path,
            limit=64 * 1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_consent_rejects_retained_schema_instance_mutation_without_history(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    install_rin(data_root, rin_verified_release)

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "persistence-consent":
                instance["permissions"] = ["memory_references"]

    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: grant_consent(
            data_root,
            "rin-aster",
            ["relationship_state"],
            MutatingSchemas(),
            expected_revision=0,
        ),
    )
    assert not _consent_history(data_root).exists()


def test_consent_rejects_caller_permission_mutation_without_history(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    install_rin(data_root, rin_verified_release)
    permissions = ["relationship_state"]
    mutated = False

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal mutated
            SCHEMAS.validate(name, instance)
            if not mutated:
                permissions.append("mood_state")
                mutated = True

    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: grant_consent(
            data_root,
            "rin-aster",
            permissions,
            MutatingSchemas(),
            expected_revision=0,
        ),
    )
    assert not _consent_history(data_root).exists()


def test_consent_rejects_aba_before_caller_input_can_be_restored(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    install_rin(data_root, rin_verified_release)
    permissions = ["relationship_state"]
    phase = 0

    class AbaSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal phase
            SCHEMAS.validate(name, instance)
            if phase == 0:
                permissions.append("mood_state")
                phase = 1
            elif phase == 1:
                permissions.pop()
                phase = 2

    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: grant_consent(
            data_root,
            "rin-aster",
            permissions,
            AbaSchemas(),
            expected_revision=0,
        ),
    )
    assert phase == 1
    assert not _consent_history(data_root).exists()


def test_consent_rejects_registry_change_during_callback_without_history(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    install_rin(data_root, rin_verified_release)
    registry = data_root / "registry" / "global.json"
    changed = False

    class ReplacingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal changed
            SCHEMAS.validate(name, instance)
            if not changed:
                registry.write_bytes(registry.read_bytes() + b"\n")
                changed = True

    _assert_code(
        "PERSISTENCE_INSTALLATION_STALE",
        lambda: grant_consent(
            data_root,
            "rin-aster",
            ["relationship_state"],
            ReplacingSchemas(),
            expected_revision=0,
        ),
    )
    assert not _consent_history(data_root).exists()


def test_consent_captures_relative_workspace_before_schema_callback(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    rebound = tmp_path / "rebound"
    workspace.mkdir()
    rebound.mkdir()
    install_rin(data_root, rin_verified_release, workspace_root=workspace)
    granted = grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        workspace_root=workspace,
        expected_revision=0,
    )
    changed = False

    class CwdChangingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal changed
            SCHEMAS.validate(name, instance)
            if name == "persistence-consent" and not changed:
                monkeypatch.chdir(rebound)
                changed = True

    monkeypatch.chdir(tmp_path)
    loaded = load_consent(
        data_root,
        "rin-aster",
        CwdChangingSchemas(),
        workspace_root=Path("workspace"),
    )

    assert changed
    assert loaded == granted


def test_relationship_rejects_caller_event_aba_across_consent_callbacks(
    consented_rin: ConsentedRin,
) -> None:
    event = interaction_event("event-1", 0)
    original = canonical_bytes(event)
    phase = 0

    class AbaSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal phase
            SCHEMAS.validate(name, instance)
            if name != "persistence-consent":
                return
            phase += 1
            if phase == 1:
                event["effects"]["trust"] = 3.0
            elif phase == 2:
                event.clear()
                event.update(json.loads(original))

    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: apply_persistent_relationship_event(
            consented_rin.data_root,
            "rin-aster",
            event,
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            AbaSchemas(),
            expected_state_revision=0,
            operation_id="relationship-operation-1",
        ),
    )
    assert phase == 1
    assert not _persistent_state_root(consented_rin).exists()


def test_mood_rejects_caller_event_aba_across_consent_callbacks(
    consented_rin: ConsentedRin,
) -> None:
    event = mood_event("mood-event-1", 0)
    event["trigger_strength"] = "strong"
    original = canonical_bytes(event)
    phase = 0

    class AbaSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal phase
            SCHEMAS.validate(name, instance)
            if name != "persistence-consent":
                return
            phase += 1
            if phase == 1:
                event["intensity"] = 0.2
            elif phase == 2:
                event.clear()
                event.update(json.loads(original))

    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: apply_persistent_mood_event(
            consented_rin.data_root,
            "rin-aster",
            event,
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            AbaSchemas(),
            expected_state_revision=0,
            operation_id="mood-operation-1",
        ),
    )
    assert phase == 1
    assert not _persistent_state_root(consented_rin).exists()


@pytest.mark.parametrize(
    "secret_value",
    [
        "API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456",
        "Authorization: Bearer bearer-secret-value-123456",
        "-----BEGIN PRIVATE KEY-----\nprivate-key-body\n-----END PRIVATE KEY-----",
        r"C:\Users\alice\private\memory.txt",
        "/home/alice/private/memory.txt",
        "file:///home/alice/private/memory.txt",
        "approved preference\x07hidden payload",
        "User: retain this\nAssistant: stored\nUser: confirm",
        "BEGIN PROMPT LOG\nsystem prompt\nEND PROMPT LOG",
        '{"role":"tool","tool_call_id":"secret-call","content":"dump"}',
        "https://alice:private-password@example.com/memory",
    ],
)
def test_memory_detector_rejects_without_echo_or_write(
    consented_rin: ConsentedRin,
    secret_value: str,
) -> None:
    memory_root = (
        consented_rin.data_root
        / "memory-references"
        / "global"
        / "original"
        / "rin-aster"
    )
    with pytest.raises(KokoroError) as raised:
        add_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            "host-memory-security-probe",
            secret_value,
            {"en-US": secret_value},
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
        )

    envelope = canonical_bytes(raised.value.envelope()).decode("utf-8")
    assert raised.value.code == "PERSISTENCE_MEMORY_CONTENT_REJECTED"
    assert secret_value not in envelope
    assert not memory_root.exists()


def test_memory_detector_rejects_malicious_localized_mapping_key(
    consented_rin: ConsentedRin,
) -> None:
    secret_key = "API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456"

    error = _assert_code(
        "PERSISTENCE_MEMORY_CONTENT_REJECTED",
        lambda: add_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            "host-memory-security-probe",
            "A safe approved summary.",
            {secret_key: "A safe approved summary."},
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
        ),
    )
    assert secret_key not in canonical_bytes(error.envelope()).decode("utf-8")


def test_memory_detector_accepts_bounded_safe_summary_controls(
    consented_rin: ConsentedRin,
) -> None:
    controls = [
        "Preference: concise technical explanations.",
        "Use https://example.com/docs?topic=memory as public documentation.",
        'The user discussed the short phrase "Alice: hello" as an example.',
        "ユーザーは簡潔な説明を承認しました。",
    ]

    for index, summary in enumerate(controls, start=1):
        added = add_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            f"host-memory-safe-{index}",
            summary,
            {"en-US": summary},
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
        )
        assert added["summary"] == summary


def test_memory_rejects_localized_summary_aba_without_write(
    consented_rin: ConsentedRin,
) -> None:
    host_id, summary, localized = approved_memory_inputs()
    original = canonical_bytes(localized)
    phase = 0

    class AbaSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal phase
            SCHEMAS.validate(name, instance)
            if name != "persistence-consent":
                return
            phase += 1
            if phase == 1:
                localized["en-US"] = "changed"
            elif phase == 2:
                localized.clear()
                localized.update(json.loads(original))

    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: add_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            host_id,
            summary,
            localized,
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            AbaSchemas(),
        ),
    )
    assert phase == 1
    memory_root = consented_rin.data_root / "memory-references"
    assert not memory_root.exists()


def test_memory_list_rejects_membership_rebase_during_consent_callback(
    consented_rin: ConsentedRin,
) -> None:
    host_id, summary, localized = approved_memory_inputs()
    added = add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )
    target = (
        consented_rin.data_root
        / "memory-references"
        / "global"
        / "original"
        / "rin-aster"
        / f"{added['memory_reference_id']}.json"
    )
    removed = False

    class RemovingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal removed
            SCHEMAS.validate(name, instance)
            if name == "persistence-consent" and not removed:
                target.unlink()
                removed = True

    _assert_code(
        "PERSISTENCE_MEMORY_INVALID",
        lambda: list_memory_references(
            consented_rin.data_root,
            "rin-aster",
            RemovingSchemas(),
        ),
    )
    assert removed


def test_memory_remove_refuses_hardlinked_replacement(
    consented_rin: ConsentedRin,
) -> None:
    host_id, summary, localized = approved_memory_inputs()
    added = add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )
    target = (
        consented_rin.data_root
        / "memory-references"
        / "global"
        / "original"
        / "rin-aster"
        / f"{added['memory_reference_id']}.json"
    )
    outside = consented_rin.data_root.parent / "outside-memory.json"
    target.replace(outside)
    try:
        os.link(outside, target)
    except OSError:
        outside.replace(target)
        pytest.skip("hardlinks are unavailable on this platform")

    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: remove_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            added["memory_reference_id"],
            consented_rin.consent["consent_id"],
            SCHEMAS,
            identifier_kind="memory_reference_id",
        ),
    )
    assert outside.exists()
    assert target.exists()


def test_relationship_replay_rejects_canonical_event_hash_tampering(
    consented_rin: ConsentedRin,
) -> None:
    apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("event-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="relationship-operation-1",
    )
    state_root = _persistent_state_root(consented_rin)
    pointer = json.loads(state_root.joinpath("current.json").read_bytes())
    events = (
        state_root
        / "generations"
        / pointer["generation_id"]
        / "events"
    )
    event_path = next(events.iterdir())
    record = json.loads(event_path.read_bytes())
    record["payload"]["max_delta"] = 1.0
    event_path.write_bytes(canonical_bytes(record))

    _assert_code(
        "PERSISTENCE_STATE_JOURNAL_INVALID",
        lambda: replay_persistent_state(
            consented_rin.data_root,
            "rin-aster",
            SCHEMAS,
        ),
    )


def test_relationship_repair_never_overwrites_symlinked_projection(
    consented_rin: ConsentedRin,
) -> None:
    apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("event-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="relationship-operation-1",
    )
    state_root = _persistent_state_root(consented_rin)
    pointer = json.loads(state_root.joinpath("current.json").read_bytes())
    projection = (
        state_root
        / "generations"
        / pointer["generation_id"]
        / "state.json"
    )
    outside = consented_rin.data_root.parent / "outside-state.json"
    projection.replace(outside)
    try:
        projection.symlink_to(outside)
    except OSError:
        outside.replace(projection)
        pytest.skip("file symlinks are unavailable on this platform")

    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: apply_persistent_relationship_event(
            consented_rin.data_root,
            "rin-aster",
            interaction_event("event-2", 1),
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
            expected_state_revision=1,
            operation_id="relationship-operation-2",
        ),
    )
    assert outside.exists()


def test_relationship_captures_relative_data_root_before_schema_callback(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    rebound = tmp_path / "rebound"
    rebound.mkdir()
    install_rin(data_root, rin_verified_release)
    consent = grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        expected_revision=0,
    )
    changed = False

    class CwdChangingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal changed
            SCHEMAS.validate(name, instance)
            if name == "interaction-event" and not changed:
                monkeypatch.chdir(rebound)
                changed = True

    monkeypatch.chdir(tmp_path)
    state = apply_persistent_relationship_event(
        Path("data"),
        "rin-aster",
        interaction_event("event-1", 0),
        consent["consent_id"],
        consent["grant_revision"],
        CwdChangingSchemas(),
        expected_state_revision=0,
        operation_id="relationship-operation-1",
    )

    assert changed
    assert state["revision"] == 1
    assert data_root.joinpath(
        "persistent-state",
        "global",
        "original",
        "rin-aster",
    ).exists()
    assert not rebound.joinpath("data").exists()


def _consent_history(data_root: Path) -> Path:
    return (
        data_root
        / "consents"
        / "global"
        / "original"
        / "rin-aster"
        / "history"
    )
