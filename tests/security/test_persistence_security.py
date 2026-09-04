import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import threading
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
import kokoroarc.persistence._storage as storage
import kokoroarc.persistence.consent as persistent_consent_module
from kokoroarc.persistence.consent import (
    grant_consent,
    load_consent,
    revoke_consent,
)
import kokoroarc.persistence.memory as persistent_memory_module
from kokoroarc.persistence.memory import (
    add_memory_reference,
    list_memory_references,
    remove_memory_reference,
)
import kokoroarc.persistence.migrations as persistent_migrations_module
from kokoroarc.persistence.migrations import (
    apply_state_migration,
    preview_state_migration,
)
from kokoroarc.persistence.state import (
    apply_persistent_mood_event,
    apply_persistent_relationship_event,
    export_persistent_data,
    preview_persistent_reset,
    replay_persistent_state,
    reset_persistent_data,
)
import kokoroarc.persistence.state as persistent_state_module
from kokoroarc.schemas import SchemaRegistry
from kokoroarc import __version__

from persistence_support import (
    ConsentedRin,
    approved_memory_inputs,
    consented_rin,
    install_rin,
    install_rin_successor,
    interaction_event,
    mood_event,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))

MUTATION_CASES = (
    "caller_permissions",
    "caller_interaction_event",
    "caller_mood_event",
    "caller_summaries",
    "caller_reset_preview",
    "caller_migration_plan",
    "consent_schema_input",
    "state_schema_input",
    "event_schema_input",
    "memory_schema_input",
    "export_schema_input",
    "migration_schema_input",
    "compiled_installation_input",
    "transition_state_input",
    "transition_event_input",
    "transition_output",
    "migration_replay_output",
)

FILESYSTEM_ATTACKS = (
    "symlink",
    "junction",
    "reparse_point",
    "hardlink",
    "fifo_or_special_file",
    "ancestor_swap",
    "same_name_replacement",
    "case_collision",
    "membership_insert",
    "membership_remove",
    "scan_then_grow",
    "scan_then_chmod_executable",
)


def _consent() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "consents/global/rin-aster/consent-01",
        "created_by": {"component": "kokoroarc", "version": __version__},
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


def _tree_inventory(
    root: Path,
    *,
    excluded: Path | None = None,
) -> tuple[tuple[str, str, bytes | int | None], ...]:
    if not root.exists():
        return ()
    entries: list[tuple[str, str, bytes | int | None]] = []
    for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
        if excluded is not None and (path == excluded or excluded in path.parents):
            continue
        relative = path.relative_to(root).as_posix()
        value = path.lstat()
        if path.is_symlink():
            entries.append((relative, "redirect", stat.S_IFMT(value.st_mode)))
        elif stat.S_ISDIR(value.st_mode):
            entries.append((relative, "directory", None))
        elif stat.S_ISREG(value.st_mode):
            entries.append((relative, "file", path.read_bytes()))
        else:
            entries.append((relative, "special", stat.S_IFMT(value.st_mode)))
    return tuple(entries)


def test_persistence_error_reasons_are_bounded_enums_and_non_echoing() -> None:
    probes = (
        r"C:\Users\alice\private\consent.json",
        "API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456",
    )
    reasons = (
        storage._error_reason(OSError(probes[0])),
        storage._error_reason(PermissionError(probes[1])),
        storage._error_reason(
            KokoroError(
                "INJECTED",
                "injected",
                details={"reason": probes[0]},
            )
        ),
    )
    assert reasons == ("os_error", "permission_error", "operation_failed")
    for reason in reasons:
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason)
    envelope = canonical_bytes(
        storage._write_failed("publish", reasons[-1]).envelope()
    ).decode("utf-8")
    assert all(probe not in envelope for probe in probes)


def test_every_stable_persistence_error_has_a_bounded_non_echoing_envelope(
) -> None:
    probes = (
        r"C:\Users\alice\private\consent.json",
        "consent-private-identifier",
        "interaction-private-evidence",
        "memory-private-identifier",
        "summary private content",
        "API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456",
    )
    errors = (
        persistent_consent_module._consent_invalid("invalid_input"),
        persistent_consent_module._consent_not_found(),
        persistent_consent_module._consent_conflict("revision"),
        persistent_consent_module._consent_revoked(),
        persistent_consent_module._permission_denied(),
        persistent_consent_module._installation_stale("installation_changed"),
        storage._mutation_error("input_mutation"),
        KokoroError(
            "PERSISTENCE_STATE_NOT_FOUND",
            "Persistent state was not found.",
            details={"reason": "absent"},
        ),
        persistent_state_module._revision_conflict("revision"),
        persistent_state_module._journal_invalid("stored_artifact"),
        persistent_state_module._contract_unsupported("contract_version"),
        persistent_state_module._migration_required("contract_version"),
        persistent_state_module._state_write_failed(
            "projection",
            storage._write_failed("projection", "os_error"),
        ),
        persistent_state_module._mood_invalid("event_shape"),
        persistent_memory_module._memory_invalid("invalid_input"),
        persistent_memory_module._memory_content_rejected("private_key"),
        persistent_memory_module._memory_conflict("host_memory_id_reused"),
        persistent_memory_module._memory_not_found("host_memory_id"),
        persistent_state_module._reset_stale("preview_changed"),
        persistent_migrations_module._migration_invalid("invalid_input"),
        persistent_migrations_module._migration_stale("stored_artifact"),
        persistent_migrations_module._migration_unreplayable("source_replay"),
        storage._path_unsafe("unsafe_path"),
        storage._limit_error("entry_count", 1),
        storage._locked(),
        storage._write_failed("publish", "os_error"),
        storage._durability_failed("publish", "fsync_failed"),
        storage._cleanup_failed("identity_changed"),
        storage._changed("file_changed"),
    )
    expected_codes = {
        "PERSISTENCE_CONSENT_INVALID",
        "PERSISTENCE_CONSENT_NOT_FOUND",
        "PERSISTENCE_CONSENT_CONFLICT",
        "PERSISTENCE_CONSENT_REVOKED",
        "PERSISTENCE_PERMISSION_DENIED",
        "PERSISTENCE_INSTALLATION_STALE",
        "PERSISTENCE_INPUT_MUTATION",
        "PERSISTENCE_STATE_NOT_FOUND",
        "PERSISTENCE_STATE_REVISION_CONFLICT",
        "PERSISTENCE_STATE_JOURNAL_INVALID",
        "PERSISTENCE_STATE_CONTRACT_UNSUPPORTED",
        "PERSISTENCE_STATE_MIGRATION_REQUIRED",
        "PERSISTENCE_STATE_WRITE_FAILED",
        "PERSISTENCE_MOOD_INVALID",
        "PERSISTENCE_MEMORY_INVALID",
        "PERSISTENCE_MEMORY_CONTENT_REJECTED",
        "PERSISTENCE_MEMORY_CONFLICT",
        "PERSISTENCE_MEMORY_NOT_FOUND",
        "PERSISTENCE_RESET_STALE",
        "PERSISTENCE_MIGRATION_INVALID",
        "PERSISTENCE_MIGRATION_STALE",
        "PERSISTENCE_MIGRATION_UNREPLAYABLE",
        "PERSISTENCE_PATH_UNSAFE",
        "PERSISTENCE_LIMIT_EXCEEDED",
        "PERSISTENCE_LOCKED",
        "PERSISTENCE_WRITE_FAILED",
        "PERSISTENCE_DURABILITY_FAILED",
        "PERSISTENCE_CLEANUP_FAILED",
        "PERSISTENCE_CHANGED",
    }
    assert {error.code for error in errors} == expected_codes
    allowed_details = {"phase", "reason", "limit", "operation", "record_state"}
    for error in errors:
        assert set(error.details) <= allowed_details
        for value in error.details.values():
            if isinstance(value, str):
                assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
            else:
                assert isinstance(value, int) and not isinstance(value, bool)
                assert value >= 0
        envelope = canonical_bytes(error.envelope()).decode("utf-8")
        assert all(probe not in envelope for probe in probes)


def _persistent_state_root(consented: ConsentedRin) -> Path:
    return (
        consented.data_root
        / "persistent-state"
        / "global"
        / "original"
        / "rin-aster"
    )


def _migration_case(
    consented: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    source = apply_persistent_relationship_event(
        consented.data_root,
        "rin-aster",
        interaction_event("migration-source-event-1", 0),
        consented.consent["consent_id"],
        consented.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="migration-source-operation-1",
    )
    target = install_rin_successor(
        consented,
        tmp_path,
        verified_release_factory,
    )
    plan = preview_state_migration(
        consented.data_root,
        "rin-aster",
        target.consent["consent_id"],
        target.consent["grant_revision"],
        SCHEMAS,
        mood_strategy="preserve_identical_contract",
    )
    return source, target, plan


def test_persistence_domains_use_no_external_capabilities(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("persistence attempted an external capability")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(threading.Thread, "start", forbidden)

    loaded = load_consent(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )
    assert loaded == consented_rin.consent
    repeated = grant_consent(
        consented_rin.data_root,
        "rin-aster",
        ["relationship_state", "mood_state", "memory_references"],
        SCHEMAS,
        expected_revision=consented_rin.consent["grant_revision"],
    )
    assert repeated == consented_rin.consent

    relationship = apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("event-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="no-capability-relationship-1",
    )
    mood_input = mood_event("no-capability-mood-1", 0)
    mood_input["trigger_strength"] = "strong"
    mood = apply_persistent_mood_event(
        consented_rin.data_root,
        "rin-aster",
        mood_input,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=relationship["revision"],
        operation_id="no-capability-mood-operation-1",
    )
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
    listed = list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )
    assert [item.reference for item in listed] == [memory]
    removed = remove_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        host_id,
        consented_rin.consent["consent_id"],
        SCHEMAS,
        identifier_kind="host_memory_id",
    )
    assert removed.removed
    assert export_persistent_data(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )["state"] == mood

    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="mood",
        reset_id="no-capability-reset-1",
    )
    reset = reset_persistent_data(
        consented_rin.data_root,
        "rin-aster",
        preview,
        consented_rin.consent["consent_id"],
        SCHEMAS,
    )
    assert reset["target"] == "mood"

    target = install_rin_successor(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    plan = preview_state_migration(
        consented_rin.data_root,
        "rin-aster",
        target.consent["consent_id"],
        target.consent["grant_revision"],
        SCHEMAS,
        mood_strategy="preserve_identical_contract",
    )
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
    revoked = revoke_consent(
        consented_rin.data_root,
        "rin-aster",
        target.consent["consent_id"],
        SCHEMAS,
        expected_revision=target.consent["grant_revision"],
    )
    assert revoked["status"] == "revoked"
    assert load_consent(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == revoked


def test_persistence_operations_change_only_the_declared_data_root(
    consented_rin: ConsentedRin,
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.mkdir()
    (sentinel / "unchanged.txt").write_text("unchanged", encoding="utf-8")
    outside_before = _tree_inventory(
        tmp_path,
        excluded=consented_rin.data_root,
    )
    sentinel_before = _tree_inventory(sentinel)
    data_before = {
        path: (kind, value)
        for path, kind, value in _tree_inventory(consented_rin.data_root)
    }

    apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("inventory-event-01", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="inventory-operation-01",
    )

    data_after_success = {
        path: (kind, value)
        for path, kind, value in _tree_inventory(consented_rin.data_root)
    }
    changed = {
        path
        for path in set(data_before) | set(data_after_success)
        if data_before.get(path) != data_after_success.get(path)
    }
    assert changed
    assert all(
        path == "persistent-state" or path.startswith("persistent-state/")
        for path in changed
    )
    assert _tree_inventory(tmp_path, excluded=consented_rin.data_root) == outside_before
    assert _tree_inventory(sentinel) == sentinel_before

    failed_before = _tree_inventory(consented_rin.data_root)
    secret = "API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456"
    _assert_code(
        "PERSISTENCE_MEMORY_CONTENT_REJECTED",
        lambda: add_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            "host-memory-inventory-failure-01",
            secret,
            {"en-US": secret},
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
        ),
    )
    assert _tree_inventory(consented_rin.data_root) == failed_before
    assert _tree_inventory(tmp_path, excluded=consented_rin.data_root) == outside_before
    assert _tree_inventory(sentinel) == sentinel_before


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


def test_storage_rejects_file_reported_as_reparse_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "consent.json"
    path.write_bytes(canonical_bytes(_consent()))
    original = storage._is_redirect

    def marked(candidate: Path, value: os.stat_result) -> bool:
        return candidate == path or original(candidate, value)

    monkeypatch.setattr(storage, "_is_redirect", marked)
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
            names = (
                f"{consumed:05d}.json",
                f".hidden-{consumed:05d}",
                f"unknown-{consumed:05d}.bin",
            )
            return Entry(names[(consumed - 1) % len(names)])

    monkeypatch.setattr(storage.os, "scandir", lambda _path: Iterator())

    _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: storage._bounded_regular_json_entries(tmp_path, 3),
    )
    assert consumed == 4


def test_storage_file_bytes_rejects_limit_plus_one(tmp_path: Path) -> None:
    path = tmp_path / "oversized.json"
    path.write_bytes(b"{}")
    scope = _scope(tmp_path)

    error = _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: storage.read_canonical_object(
            path,
            limit=1,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )
    assert error.details == {"reason": "file_bytes", "limit": 1}


def test_storage_aggregate_bytes_rejects_limit_plus_one(tmp_path: Path) -> None:
    directory = tmp_path / "history"
    directory.mkdir()
    payload = canonical_bytes(_consent())
    (directory / "00000000000000000001.json").write_bytes(payload)
    (directory / "00000000000000000002.json").write_bytes(payload)
    aggregate_limit = len(payload) * 2 - 1
    scope = _scope(tmp_path)

    error = _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: storage.scan_canonical_directory(
            directory,
            entry_limit=2,
            aggregate_limit=aggregate_limit,
            file_limit=len(payload),
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )
    assert error.details == {
        "reason": "aggregate_bytes",
        "limit": aggregate_limit,
    }


def test_storage_transaction_bytes_rejects_limit_plus_one_before_write(
    tmp_path: Path,
) -> None:
    scope = storage.open_persistence_scope(
        tmp_path / "data",
        SCHEMAS,
        character_id="rin-aster",
        limits=storage.PersistenceLimits(max_transaction_bytes=1),
    )
    with storage._acquire_character_lock(scope) as lock:
        error = _assert_code(
            "PERSISTENCE_LIMIT_EXCEEDED",
            lambda: storage._write_transaction_marker(scope, b"{}", lock),
        )

    assert error.details == {"reason": "transaction_bytes", "limit": 1}
    assert not scope.transaction_path.exists()


def test_storage_json_depth_rejects_limit_plus_one() -> None:
    value: dict[str, Any] = {}
    cursor = value
    for _ in range(64):
        child: dict[str, Any] = {}
        cursor["nested"] = child
        cursor = child
    boundary = storage.PersistenceBoundary(SCHEMAS)

    error = _assert_code(
        "PERSISTENCE_CHANGED",
        lambda: boundary.capture("nested_input", value),
    )
    assert error.details == {"reason": "invalid_canonical_input"}


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


@pytest.mark.parametrize(
    ("attack", "expected_code"),
    [
        ("membership_insert", "PERSISTENCE_LIMIT_EXCEEDED"),
        ("membership_remove", "PERSISTENCE_CHANGED"),
        ("scan_then_grow", "PERSISTENCE_CHANGED"),
        ("scan_then_chmod_executable", "PERSISTENCE_PATH_UNSAFE"),
    ],
)
def test_storage_rejects_directory_snapshot_races(
    tmp_path: Path,
    attack: str,
    expected_code: str,
) -> None:
    if attack == "scan_then_chmod_executable" and os.name == "nt":
        pytest.skip("POSIX executable mode mutation is unavailable on Windows")
    directory = tmp_path / "history"
    directory.mkdir()
    first = directory / "00000000000000000001.json"
    second = directory / "00000000000000000002.json"
    payload = canonical_bytes(_consent())
    first.write_bytes(payload)
    second.write_bytes(payload)
    attacked = False

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal attacked
            SCHEMAS.validate(name, instance)
            if attacked:
                return
            attacked = True
            if attack == "membership_insert":
                (directory / "00000000000000000003.json").write_bytes(payload)
            elif attack == "membership_remove":
                second.unlink()
            elif attack == "scan_then_grow":
                second.write_bytes(payload + b" ")
            else:
                second.chmod(second.stat().st_mode | stat.S_IXUSR)

    scope = _scope(tmp_path, MutatingSchemas())
    _assert_code(
        expected_code,
        lambda: storage.scan_canonical_directory(
            directory,
            entry_limit=2,
            aggregate_limit=128 * 1024,
            file_limit=64 * 1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )
    assert attacked


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


def test_consent_rejects_retained_compiled_installation_mutation(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    install_rin(data_root, rin_verified_release)
    retained: dict[str, dict[str, Any]] = {}
    original = persistent_consent_module._resolve_installed_binding

    def retaining_resolver(*args: Any, **kwargs: Any) -> dict[str, str]:
        result = original(*args, **kwargs)
        compiled_results = kwargs["compiled_results"]
        retained["compiled"] = compiled_results[0]
        return result

    class LaterMutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "persistence-consent" and "compiled" in retained:
                retained["compiled"]["artifact_id"] = "compiled/mutated"

    monkeypatch.setattr(
        persistent_consent_module,
        "_resolve_installed_binding",
        retaining_resolver,
    )
    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: grant_consent(
            data_root,
            "rin-aster",
            ["relationship_state"],
            LaterMutatingSchemas(),
            expected_revision=0,
        ),
    )
    assert not _consent_history(data_root).exists()


def test_consent_history_limit_blocks_limit_plus_one_before_write(
    consented_rin: ConsentedRin,
) -> None:
    history = _consent_history(consented_rin.data_root)
    before = {path.name: path.read_bytes() for path in history.iterdir()}

    _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: grant_consent(
            consented_rin.data_root,
            "rin-aster",
            ["relationship_state"],
            SCHEMAS,
            expected_revision=consented_rin.consent["grant_revision"],
            limits=storage.PersistenceLimits(max_consent_history=1),
        ),
    )
    assert {path.name: path.read_bytes() for path in history.iterdir()} == before
    assert load_consent(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == consented_rin.consent


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


@pytest.mark.parametrize("target", ["state", "event"])
def test_relationship_rejects_transition_input_mutation(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    original = persistent_state_module.apply_event_v1

    def mutating_transition(
        state: dict[str, Any],
        event: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = original(state, event, **kwargs)
        if target == "state":
            state["recent_novelty"]["mutated-input"] = 1
        else:
            event["evidence"]["reference"] = "mutated-input"
        return result

    monkeypatch.setattr(
        persistent_state_module,
        "apply_event_v1",
        mutating_transition,
    )
    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: apply_persistent_relationship_event(
            consented_rin.data_root,
            "rin-aster",
            interaction_event("transition-input-event-1", 0),
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
            expected_state_revision=0,
            operation_id="transition-input-operation-1",
        ),
    )


def test_relationship_rejects_transition_output_mutated_during_schema_callback(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retained: list[dict[str, Any]] = []
    original = persistent_state_module.apply_event_v1

    def retaining_transition(
        state: dict[str, Any],
        event: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = original(state, event, **kwargs)
        retained.append(result)
        return result

    class LaterMutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "persistent-state-event" and retained:
                retained[-1]["stage"] = "acquainted"

    monkeypatch.setattr(
        persistent_state_module,
        "apply_event_v1",
        retaining_transition,
    )
    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: apply_persistent_relationship_event(
            consented_rin.data_root,
            "rin-aster",
            interaction_event("transition-output-event-1", 0),
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            LaterMutatingSchemas(),
            expected_state_revision=0,
            operation_id="transition-output-operation-1",
        ),
    )


def test_state_event_limit_blocks_limit_plus_one_before_write(
    consented_rin: ConsentedRin,
) -> None:
    limits = storage.PersistenceLimits(max_state_events=1)
    first = apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("event-limit-01", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="event-limit-operation-01",
        limits=limits,
    )
    events_root = (
        _persistent_state_root(consented_rin)
        / "generations"
        / first["generation_id"]
        / "events"
    )
    before = tuple(sorted(path.name for path in events_root.iterdir()))

    error = _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: apply_persistent_relationship_event(
            consented_rin.data_root,
            "rin-aster",
            interaction_event("event-limit-02", 1),
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
            expected_state_revision=1,
            operation_id="event-limit-operation-02",
            limits=limits,
        ),
    )
    assert error.details == {"reason": "state_events", "limit": 1}
    assert tuple(sorted(path.name for path in events_root.iterdir())) == before


@pytest.mark.parametrize(
    "schema_name",
    ["persistent-state-event", "persistent-character-state"],
)
def test_relationship_rejects_mutated_state_schema_inputs(
    consented_rin: ConsentedRin,
    schema_name: str,
) -> None:
    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == schema_name:
                instance["artifact_id"] = "mutated/schema-input"

    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: apply_persistent_relationship_event(
            consented_rin.data_root,
            "rin-aster",
            interaction_event(f"{schema_name}-event-1", 0),
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            MutatingSchemas(),
            expected_state_revision=0,
            operation_id=f"{schema_name}-operation-1",
        ),
    )


def test_memory_rejects_mutated_schema_input_without_write(
    consented_rin: ConsentedRin,
) -> None:
    host_id, summary, localized = approved_memory_inputs()

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "memory-reference":
                instance["summary"] = "mutated schema input"

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
            MutatingSchemas(),
        ),
    )
    assert not (
        consented_rin.data_root
        / "memory-references"
        / "global"
        / "original"
        / "rin-aster"
    ).exists()


def test_memory_entry_limit_blocks_limit_plus_one_before_write(
    consented_rin: ConsentedRin,
) -> None:
    limits = storage.PersistenceLimits(max_memory_references=1)
    _host_id, summary, localized = approved_memory_inputs()
    add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        "host-memory-capacity-01",
        summary,
        localized,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        limits=limits,
    )
    memory_root = (
        consented_rin.data_root
        / "memory-references"
        / "global"
        / "original"
        / "rin-aster"
    )
    before = tuple(sorted(path.name for path in memory_root.iterdir()))

    error = _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: add_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            "host-memory-capacity-02",
            summary,
            localized,
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
            limits=limits,
        ),
    )
    assert error.details == {"reason": "memory_references", "limit": 1}
    assert tuple(sorted(path.name for path in memory_root.iterdir())) == before


def test_memory_summary_rejects_limit_plus_one_without_write(
    consented_rin: ConsentedRin,
) -> None:
    oversized = "a" * 2_001

    error = _assert_code(
        "PERSISTENCE_MEMORY_INVALID",
        lambda: add_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            "host-memory-summary-limit-01",
            oversized,
            {"en-US": oversized},
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
        ),
    )
    assert error.details == {"reason": "summary"}
    assert not (consented_rin.data_root / "memory-references").exists()


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


def _persistent_export_mutation_target(
    consented: ConsentedRin,
    target_kind: str,
) -> Path:
    if target_kind == "consent":
        return (
            consented.data_root
            / "consents"
            / "global"
            / "original"
            / "rin-aster"
            / "current.json"
        )
    if target_kind == "memory":
        root = (
            consented.data_root
            / "memory-references"
            / "global"
            / "original"
            / "rin-aster"
        )
        return next(root.iterdir())
    state_root = (
        consented.data_root
        / "persistent-state"
        / "global"
        / "original"
        / "rin-aster"
    )
    pointer = json.loads(state_root.joinpath("current.json").read_bytes())
    generation = state_root / "generations" / pointer["generation_id"]
    if target_kind == "projection":
        return generation / "state.json"
    return next(generation.joinpath("events").iterdir())


@pytest.mark.parametrize(
    "target_kind",
    ["consent", "event", "projection", "memory"],
)
def test_export_rejects_store_rebase_during_first_schema_callback(
    consented_rin: ConsentedRin,
    target_kind: str,
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
    host_id, summary, localized = approved_memory_inputs()
    add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )
    target = _persistent_export_mutation_target(consented_rin, target_kind)
    mutated = False

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal mutated
            SCHEMAS.validate(name, instance)
            if not mutated:
                target.write_bytes(target.read_bytes() + b" ")
                mutated = True

    with pytest.raises(KokoroError):
        export_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            MutatingSchemas(),
        )
    assert mutated


def test_export_rejects_mutated_detached_schema_input(
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

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "persistence-export":
                instance["artifact_id"] = "mutated/export"

    error = _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: export_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            MutatingSchemas(),
        ),
    )
    assert "mutated/export" not in canonical_bytes(error.envelope()).decode()


def test_reset_rejects_caller_preview_mutation_during_schema_callback(
    consented_rin: ConsentedRin,
) -> None:
    apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("reset-preview-event-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="reset-preview-operation-1",
    )
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="relationship",
        reset_id="reset-preview-mutation-01",
    )
    mutated = False

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal mutated
            SCHEMAS.validate(name, instance)
            if not mutated:
                object.__setattr__(preview, "payload", preview.payload + b" ")
                mutated = True

    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            MutatingSchemas(),
        ),
    )
    assert mutated


def test_reset_marker_failure_is_not_reported_as_success(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
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
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="relationship",
        reset_id="reset-relationship-01",
    )

    def fail_marker(*_args: Any, **_kwargs: Any) -> Any:
        raise KokoroError(
            "PERSISTENCE_WRITE_FAILED",
            "Persistent storage write failed.",
            details={
                "operation": "transaction",
                "reason": "injected",
                "record_state": "not_visible",
            },
        )

    monkeypatch.setattr(
        persistent_state_module,
        "_write_transaction_marker",
        fail_marker,
    )
    error = _assert_code(
        "PERSISTENCE_WRITE_FAILED",
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            SCHEMAS,
        ),
    )
    assert error.details["record_state"] == "not_visible"
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )["relationship"]["revision"] == 1


def test_all_reset_resumes_after_the_first_state_event(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("event-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="relationship-operation-1",
    )
    host_id, summary, localized = approved_memory_inputs()
    add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="all",
        reset_id="reset-all-interrupted-01",
    )
    original_append = persistent_state_module._append_reset_state_event

    def interrupt_after_relationship(*args: Any, **kwargs: Any) -> Any:
        result = original_append(*args, **kwargs)
        if kwargs["operation_kind"] == "relationship_reset":
            raise KokoroError(
                "PERSISTENCE_WRITE_FAILED",
                "Persistent storage write failed.",
                details={
                    "operation": "reset",
                    "reason": "injected",
                    "record_state": "committed",
                },
            )
        return result

    monkeypatch.setattr(
        persistent_state_module,
        "_append_reset_state_event",
        interrupt_after_relationship,
    )
    error = _assert_code(
        "PERSISTENCE_WRITE_FAILED",
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            SCHEMAS,
        ),
    )
    assert error.details["record_state"] == "committed"
    interrupted = replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )
    assert interrupted is not None
    assert interrupted["revision"] == before["revision"] + 1
    assert interrupted["relationship"]["revision"] == 0
    assert len(list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )) == 1

    monkeypatch.setattr(
        persistent_state_module,
        "_append_reset_state_event",
        original_append,
    )
    result = reset_persistent_data(
        consented_rin.data_root,
        "rin-aster",
        preview,
        consented_rin.consent["consent_id"],
        SCHEMAS,
    )
    after = replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )
    assert result["record_state"] == "committed"
    assert after is not None
    assert after["revision"] == before["revision"] + 2
    assert after["mood"]["revision"] == 0
    assert list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == ()


@pytest.mark.parametrize("durability_phase", ["event", "projection"])
def test_reset_retries_committed_state_directory_fsync(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
    durability_phase: str,
) -> None:
    before = apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("event-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="relationship-operation-1",
    )
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="relationship",
        reset_id=f"reset-relationship-{durability_phase}-fsync-01",
    )
    generation_root = (
        _persistent_state_root(consented_rin)
        / "generations"
        / before["generation_id"]
    )
    target = (
        generation_root / "events"
        if durability_phase == "event"
        else generation_root
    )
    original_fsync = storage._fsync_directory
    target_calls = 0

    def fail_target_once(path: Path) -> None:
        nonlocal target_calls
        if path == target:
            target_calls += 1
            if target_calls == 1:
                raise OSError("injected")
        original_fsync(path)

    monkeypatch.setattr(
        persistent_state_module,
        "_fsync_directory",
        fail_target_once,
    )
    monkeypatch.setattr(storage, "_fsync_directory", fail_target_once)
    expected_code = (
        "PERSISTENCE_DURABILITY_FAILED"
        if durability_phase == "event"
        else "PERSISTENCE_STATE_WRITE_FAILED"
    )
    error = _assert_code(
        expected_code,
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            SCHEMAS,
        ),
    )
    assert error.details["record_state"] == "committed"

    result = reset_persistent_data(
        consented_rin.data_root,
        "rin-aster",
        preview,
        consented_rin.consent["consent_id"],
        SCHEMAS,
    )
    assert result["record_state"] == "committed"
    assert target_calls >= 2
    after = replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )
    assert after is not None
    assert after["revision"] == before["revision"] + 1
    assert after["relationship"]["revision"] == 0


@pytest.mark.parametrize(
    ("failure_phase", "expected_marker_phase"),
    [("marker_update", "prepared"), ("cleanup", "memory_committed")],
)
def test_memory_reset_recovers_across_committed_cutover_phases(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
    expected_marker_phase: str,
) -> None:
    host_id, summary, localized = approved_memory_inputs()
    add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="memory",
        reset_id=f"reset-memory-{failure_phase}-01",
    )
    attribute = (
        "_update_reset_marker"
        if failure_phase == "marker_update"
        else "_cleanup_memory_reset"
    )
    original = getattr(persistent_state_module, attribute)

    def interrupt(*_args: Any, **_kwargs: Any) -> Any:
        code = (
            "PERSISTENCE_WRITE_FAILED"
            if failure_phase == "marker_update"
            else "PERSISTENCE_CLEANUP_FAILED"
        )
        raise KokoroError(
            code,
            "Persistent reset was interrupted.",
            details={"reason": "injected", "record_state": "committed"},
        )

    monkeypatch.setattr(persistent_state_module, attribute, interrupt)
    _assert_code(
        (
            "PERSISTENCE_WRITE_FAILED"
            if failure_phase == "marker_update"
            else "PERSISTENCE_CLEANUP_FAILED"
        ),
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            SCHEMAS,
        ),
    )
    markers = list(
        consented_rin.data_root.joinpath("persistence-transactions").rglob(
            "*.json"
        )
    )
    assert len(markers) == 1
    assert json.loads(markers[0].read_bytes())["phase"] == expected_marker_phase
    assert list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == ()

    monkeypatch.setattr(persistent_state_module, attribute, original)
    result = reset_persistent_data(
        consented_rin.data_root,
        "rin-aster",
        preview,
        consented_rin.consent["consent_id"],
        SCHEMAS,
    )
    assert result["record_state"] == "committed"
    assert not list(
        consented_rin.data_root.joinpath("persistence-transactions").rglob(
            "*.json"
        )
    )
    assert list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == ()


def test_memory_reset_retries_cutover_directory_fsync(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_id, summary, localized = approved_memory_inputs()
    add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="memory",
        reset_id="reset-memory-fsync-01",
    )
    original_fsync = persistent_memory_module._fsync_directory
    calls = 0

    def fail_once(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected")
        original_fsync(path)

    monkeypatch.setattr(
        persistent_memory_module,
        "_fsync_directory",
        fail_once,
    )
    error = _assert_code(
        "PERSISTENCE_DURABILITY_FAILED",
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            SCHEMAS,
        ),
    )
    assert error.details["record_state"] == "committed"

    result = reset_persistent_data(
        consented_rin.data_root,
        "rin-aster",
        preview,
        consented_rin.consent["consent_id"],
        SCHEMAS,
    )
    assert result["record_state"] == "committed"
    assert calls >= 2
    assert list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == ()


def test_memory_reset_recovers_after_partial_identity_bound_cleanup(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_id, summary, localized = approved_memory_inputs()
    for current_host_id in (host_id, "host-memory-preference-02"):
        add_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            current_host_id,
            summary,
            localized,
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
        )
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="memory",
        reset_id="reset-memory-partial-cleanup-01",
    )
    original_unlink = Path.unlink
    cleanup_unlinks = 0

    def interrupt_second_cleanup_unlink(
        path: Path,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        nonlocal cleanup_unlinks
        if ".reset-" in path.parent.name:
            cleanup_unlinks += 1
            if cleanup_unlinks == 2:
                raise OSError("injected")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupt_second_cleanup_unlink)
    error = _assert_code(
        "PERSISTENCE_CLEANUP_FAILED",
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            SCHEMAS,
        ),
    )
    assert error.details["record_state"] == "committed"
    assert cleanup_unlinks == 2
    assert list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == ()

    result = reset_persistent_data(
        consented_rin.data_root,
        "rin-aster",
        preview,
        consented_rin.consent["consent_id"],
        SCHEMAS,
    )
    assert result["record_state"] == "committed"
    assert cleanup_unlinks == 3


def test_reset_rejects_marker_rebase_during_generated_event_validation(
    consented_rin: ConsentedRin,
) -> None:
    before = apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("event-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="relationship-operation-1",
    )
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="relationship",
        reset_id="reset-marker-rebase-01",
    )
    mutated = False

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            nonlocal mutated
            SCHEMAS.validate(name, instance)
            markers = list(
                consented_rin.data_root.joinpath(
                    "persistence-transactions"
                ).rglob("*.json")
            )
            if name == "persistent-state-event" and markers and not mutated:
                markers[0].write_bytes(markers[0].read_bytes() + b" ")
                mutated = True

    with pytest.raises(KokoroError):
        reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            MutatingSchemas(),
        )
    assert mutated
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == before


def test_memory_reset_refuses_to_delete_replacement_cleanup_directory(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_id, summary, localized = approved_memory_inputs()
    add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="memory",
        reset_id="reset-memory-replacement-01",
    )
    original_cleanup = persistent_state_module._cleanup_memory_reset

    def interrupt(*_args: Any, **_kwargs: Any) -> None:
        raise KokoroError(
            "PERSISTENCE_CLEANUP_FAILED",
            "Persistent reset cleanup failed.",
            details={"reason": "injected", "record_state": "committed"},
        )

    monkeypatch.setattr(
        persistent_state_module,
        "_cleanup_memory_reset",
        interrupt,
    )
    _assert_code(
        "PERSISTENCE_CLEANUP_FAILED",
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            SCHEMAS,
        ),
    )
    monkeypatch.setattr(
        persistent_state_module,
        "_cleanup_memory_reset",
        original_cleanup,
    )
    parent = consented_rin.data_root.joinpath(
        "memory-references",
        "global",
        "original",
    )
    cleanup = next(path for path in parent.iterdir() if ".reset-" in path.name)
    displaced = cleanup.with_name(cleanup.name + ".displaced")
    cleanup.rename(displaced)
    cleanup.mkdir()
    sentinel = cleanup / "unrelated-sentinel.txt"
    sentinel.write_text("unrelated", encoding="utf-8")

    error = _assert_code(
        "PERSISTENCE_CLEANUP_FAILED",
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            SCHEMAS,
        ),
    )
    assert error.details["record_state"] == "unknown"
    assert sentinel.read_text(encoding="utf-8") == "unrelated"
    assert displaced.exists()


def test_reset_rejects_forged_receipt_with_wrong_post_reset_revision(
    consented_rin: ConsentedRin,
) -> None:
    before = apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("event-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="relationship-operation-1",
    )
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="relationship",
        reset_id="reset-forged-receipt-01",
    )
    scope = storage.open_persistence_scope(
        consented_rin.data_root,
        SCHEMAS,
        character_id="rin-aster",
    )
    forged = persistent_state_module._reset_receipt_document(
        scope,
        preview.document,
        preview.payload,
        before,
    )
    receipt_path = persistent_state_module._reset_receipt_path(
        scope,
        "reset-forged-receipt-01",
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_bytes(forged))

    _assert_code(
        "PERSISTENCE_RESET_STALE",
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            SCHEMAS,
        ),
    )
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == before


def test_reset_retries_committed_receipt_directory_fsync(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
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
    preview = preview_persistent_reset(
        consented_rin.data_root,
        "rin-aster",
        consented_rin.consent["consent_id"],
        SCHEMAS,
        target="relationship",
        reset_id="reset-receipt-fsync-01",
    )
    receipt_parent = _persistent_state_root(consented_rin) / "resets"
    original_fsync = storage._fsync_directory
    receipt_calls = 0

    def fail_receipt_once(path: Path) -> None:
        nonlocal receipt_calls
        if path == receipt_parent:
            receipt_calls += 1
            if receipt_calls == 1:
                raise OSError("injected")
        original_fsync(path)

    monkeypatch.setattr(
        persistent_state_module,
        "_fsync_directory",
        fail_receipt_once,
    )
    monkeypatch.setattr(storage, "_fsync_directory", fail_receipt_once)
    error = _assert_code(
        "PERSISTENCE_DURABILITY_FAILED",
        lambda: reset_persistent_data(
            consented_rin.data_root,
            "rin-aster",
            preview,
            consented_rin.consent["consent_id"],
            SCHEMAS,
        ),
    )
    assert error.details["record_state"] == "committed"

    result = reset_persistent_data(
        consented_rin.data_root,
        "rin-aster",
        preview,
        consented_rin.consent["consent_id"],
        SCHEMAS,
    )
    assert result["record_state"] == "committed"
    assert receipt_calls >= 2


def test_migration_rejects_changed_plan_and_never_dispatches_plan_values(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    changed = json.loads(canonical_bytes(plan))
    changed["expected_target_state_hash"] = "0" * 64
    _assert_code(
        "PERSISTENCE_MIGRATION_STALE",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            changed,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )

    dispatched = False

    def executable_value() -> None:
        nonlocal dispatched
        dispatched = True

    hostile = dict(plan)
    hostile["callable"] = executable_value
    _assert_code(
        "PERSISTENCE_MIGRATION_INVALID",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            hostile,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert dispatched is False
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source


def test_migration_rejects_changed_source_and_target_consent(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    source_generation = (
        _persistent_state_root(consented_rin)
        / "generations"
        / source["generation_id"]
    )
    event_path = next((source_generation / "events").iterdir())
    original_event = event_path.read_bytes()
    changed_event = json.loads(original_event)
    changed_event["created_by"]["version"] = "tampered"
    event_path.write_bytes(canonical_bytes(changed_event))
    _assert_code(
        "PERSISTENCE_MIGRATION_UNREPLAYABLE",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    event_path.write_bytes(original_event)

    changed_consent = grant_consent(
        consented_rin.data_root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        version="1.1.0",
        expected_revision=target.consent["grant_revision"],
    )
    assert changed_consent["grant_revision"] > target.consent["grant_revision"]
    _assert_code(
        "PERSISTENCE_MIGRATION_STALE",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )


def test_migration_generation_capacity_blocks_before_publication(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
            limits=storage.PersistenceLimits(max_state_generations=1),
        ),
    )
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source
    scope = storage.open_persistence_scope(
        consented_rin.data_root,
        SCHEMAS,
        character_id="rin-aster",
    )
    assert not scope.transaction_path.exists()


def test_migration_pointer_failure_is_recoverable_and_rejects_replacement(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    original_cutover = (
        persistent_migrations_module._replace_current_generation_pointer
    )

    def fail_pointer(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("injected")

    monkeypatch.setattr(
        persistent_migrations_module,
        "_replace_current_generation_pointer",
        fail_pointer,
    )
    error = _assert_code(
        "PERSISTENCE_MIGRATION_WRITE_FAILED",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert error.details["record_state"] == "not_visible"
    scope = storage.open_persistence_scope(
        consented_rin.data_root,
        SCHEMAS,
        character_id="rin-aster",
    )
    marker_payload = scope.transaction_path.read_bytes()
    marker = json.loads(marker_payload)
    target_generation = (
        _persistent_state_root(consented_rin)
        / "generations"
        / marker["target_generation_id"]
    )
    assert not target_generation.exists()
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source

    changed_marker = dict(marker)
    changed_marker["migration_id"] = "migration-tampered"
    scope.transaction_path.write_bytes(canonical_bytes(changed_marker))
    monkeypatch.setattr(
        persistent_migrations_module,
        "_replace_current_generation_pointer",
        original_cutover,
    )
    _assert_code(
        "PERSISTENCE_MIGRATION_STALE",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    scope.transaction_path.write_bytes(marker_payload)

    target_generation.mkdir()
    sentinel = target_generation / "unrelated-sentinel.txt"
    sentinel.write_text("unrelated", encoding="utf-8")
    _assert_code(
        "PERSISTENCE_MIGRATION_CONFLICT",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert sentinel.read_text(encoding="utf-8") == "unrelated"
    sentinel.unlink()
    target_generation.rmdir()

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
    assert not scope.transaction_path.exists()


def test_migration_retries_pointer_parent_fsync_after_committed_cutover(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    original = persistent_migrations_module._confirm_directory_durability
    pointer_calls = 0

    def fail_pointer_parent_once(
        path: Path,
        reason: str,
        *,
        record_state: str,
    ) -> None:
        nonlocal pointer_calls
        if reason == "pointer_fsync":
            pointer_calls += 1
            if pointer_calls == 1:
                raise KokoroError(
                    "PERSISTENCE_MIGRATION_WRITE_FAILED",
                    "injected",
                    details={
                        "phase": reason,
                        "record_state": record_state,
                    },
                )
        original(path, reason, record_state=record_state)

    monkeypatch.setattr(
        persistent_migrations_module,
        "_confirm_directory_durability",
        fail_pointer_parent_once,
    )
    error = _assert_code(
        "PERSISTENCE_MIGRATION_WRITE_FAILED",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert error.details["record_state"] == "committed"

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
    assert pointer_calls >= 2


def test_migration_rejects_missing_history_unsupported_contract_and_install_drift(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    source_generation = (
        _persistent_state_root(consented_rin)
        / "generations"
        / source["generation_id"]
    )
    event_path = next((source_generation / "events").iterdir())
    event_payload = event_path.read_bytes()
    unsupported = json.loads(event_payload)
    unsupported["transition_algorithm"] = "relationship-v2"
    event_path.write_bytes(canonical_bytes(unsupported))
    _assert_code(
        "PERSISTENCE_MIGRATION_UNREPLAYABLE",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    event_path.write_bytes(event_payload)

    source_history = (
        consented_rin.data_root
        / "consents"
        / "global"
        / "original"
        / "rin-aster"
        / "history"
        / "00000000000000000001.json"
    )
    history_payload = source_history.read_bytes()
    source_history.unlink()
    _assert_code(
        "PERSISTENCE_MIGRATION_INVALID",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    source_history.write_bytes(history_payload)

    target_compiled = (
        consented_rin.data_root
        / "installed"
        / target.installation["relative_path"]
        / "pack"
        / "compiled.json"
    )
    compiled_payload = target_compiled.read_bytes()
    changed_compiled = json.loads(compiled_payload)
    changed_compiled["behavior"]["correction_style"] = "tampered"
    target_compiled.write_bytes(canonical_bytes(changed_compiled))
    _assert_code(
        "PERSISTENCE_MIGRATION_STALE",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    target_compiled.write_bytes(compiled_payload)


def test_migration_replay_mismatch_cleans_only_identified_target_and_retries(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    original = persistent_migrations_module._require_target_state
    checks = 0

    def fail_first_target_check(state: Any, built: Any) -> None:
        nonlocal checks
        checks += 1
        if checks == 1:
            raise KokoroError(
                "PERSISTENCE_MIGRATION_UNREPLAYABLE",
                "injected",
                details={"reason": "target_state_hash"},
            )
        original(state, built)

    monkeypatch.setattr(
        persistent_migrations_module,
        "_require_target_state",
        fail_first_target_check,
    )
    _assert_code(
        "PERSISTENCE_MIGRATION_UNREPLAYABLE",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    scope = storage.open_persistence_scope(
        consented_rin.data_root,
        SCHEMAS,
        character_id="rin-aster",
    )
    marker = json.loads(scope.transaction_path.read_bytes())
    target_generation = (
        _persistent_state_root(consented_rin)
        / "generations"
        / marker["target_generation_id"]
    )
    assert marker["target_directory_identity"] is None
    assert not target_generation.exists()
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source

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


def test_migration_rejects_target_installation_swap_during_schema_callback(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    target_root = (
        consented_rin.data_root
        / "installed"
        / target.installation["relative_path"]
    )
    displaced = target_root.with_name(target_root.name + ".displaced")

    class SwappingSchemas:
        swapped = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if not self.swapped:
                target_root.rename(displaced)
                shutil.copytree(displaced, target_root)
                self.swapped = True

    _assert_code(
        "PERSISTENCE_MIGRATION_STALE",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SwappingSchemas(),
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert displaced.is_dir()
    assert target_root.is_dir()
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source


def test_migration_rejects_caller_plan_aba_across_schema_callbacks(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    original_hash = plan["expected_target_state_hash"]

    class AbaSchemas:
        phase = 0

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if self.phase == 0:
                plan["expected_target_state_hash"] = "0" * 64
                self.phase = 1
            elif self.phase == 1:
                plan["expected_target_state_hash"] = original_hash
                self.phase = 2

    schemas = AbaSchemas()
    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            schemas,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert schemas.phase == 1
    plan["expected_target_state_hash"] = original_hash
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source


def test_migration_rejects_mutated_plan_schema_input(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "state-migration-plan":
                instance["expected_target_state_hash"] = "0" * 64

    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            MutatingSchemas(),
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source


def test_migration_cleanup_refuses_replacement_generation(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    displaced: Path | None = None
    replacement: Path | None = None

    def replace_then_fail(
        scope: Any,
        generation_id: str,
        _lock: Any,
    ) -> Any:
        nonlocal displaced, replacement
        generated = (
            persistent_state_module._state_root(scope)
            / "generations"
            / generation_id
        )
        displaced = generated.with_name(generated.name + ".displaced")
        generated.rename(displaced)
        generated.mkdir()
        replacement = generated
        (generated / "unrelated-sentinel.txt").write_text(
            "unrelated",
            encoding="utf-8",
        )
        raise OSError("injected")

    monkeypatch.setattr(
        persistent_migrations_module,
        "_replace_current_generation_pointer",
        replace_then_fail,
    )
    error = _assert_code(
        "PERSISTENCE_CLEANUP_FAILED",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert error.details["record_state"] == "not_visible"
    assert displaced is not None and displaced.is_dir()
    assert replacement is not None
    assert (replacement / "unrelated-sentinel.txt").read_text(
        encoding="utf-8"
    ) == "unrelated"
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source


def test_migration_reports_unavailable_identity_after_generation_creation(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    original = persistent_migrations_module._capture_directory_identity

    def fail_target_identity(path: Path) -> Any:
        if (
            path.parent.name == "generations"
            and path.name.startswith("generation-")
        ):
            raise OSError("injected")
        return original(path)

    monkeypatch.setattr(
        persistent_migrations_module,
        "_capture_directory_identity",
        fail_target_identity,
    )
    error = _assert_code(
        "PERSISTENCE_CLEANUP_FAILED",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert error.details == {
        "reason": "target_identity_unavailable",
        "record_state": "not_visible",
    }
    scope = storage.open_persistence_scope(
        consented_rin.data_root,
        SCHEMAS,
        character_id="rin-aster",
    )
    marker = json.loads(scope.transaction_path.read_bytes())
    assert marker["target_directory_identity"] is None
    generated = (
        _persistent_state_root(consented_rin)
        / "generations"
        / marker["target_generation_id"]
    )
    assert generated.is_dir()
    assert tuple(generated.iterdir()) == ()
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source


def test_migration_cleans_identified_generation_before_marker_update(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    original = persistent_migrations_module._confirm_directory_durability
    create_calls = 0

    def fail_generation_parent_once(
        path: Path,
        reason: str,
        *,
        record_state: str,
    ) -> None:
        nonlocal create_calls
        if reason == "generation_create_fsync":
            create_calls += 1
            if create_calls == 1:
                raise KokoroError(
                    "PERSISTENCE_MIGRATION_WRITE_FAILED",
                    "injected",
                    details={
                        "phase": reason,
                        "record_state": record_state,
                    },
                )
        original(path, reason, record_state=record_state)

    monkeypatch.setattr(
        persistent_migrations_module,
        "_confirm_directory_durability",
        fail_generation_parent_once,
    )
    error = _assert_code(
        "PERSISTENCE_MIGRATION_WRITE_FAILED",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert error.details == {
        "phase": "generation_create_fsync",
        "record_state": "not_visible",
    }
    scope = storage.open_persistence_scope(
        consented_rin.data_root,
        SCHEMAS,
        character_id="rin-aster",
    )
    marker = json.loads(scope.transaction_path.read_bytes())
    assert marker["target_directory_identity"] is None
    generated = (
        _persistent_state_root(consented_rin)
        / "generations"
        / marker["target_generation_id"]
    )
    assert not generated.exists()
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source

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
    assert create_calls == 2


def test_migration_pre_marker_cleanup_refuses_replacement_generation(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    scope = storage.open_persistence_scope(
        consented_rin.data_root,
        SCHEMAS,
        character_id="rin-aster",
    )
    original = persistent_migrations_module._confirm_directory_durability
    displaced: Path | None = None
    replacement: Path | None = None

    def replace_before_parent_fsync(
        path: Path,
        reason: str,
        *,
        record_state: str,
    ) -> None:
        nonlocal displaced, replacement
        if reason == "generation_create_fsync":
            marker = json.loads(scope.transaction_path.read_bytes())
            generated = path / marker["target_generation_id"]
            displaced = generated.with_name(generated.name + ".displaced")
            generated.rename(displaced)
            generated.mkdir()
            replacement = generated
            (replacement / "unrelated-sentinel.txt").write_text(
                "unrelated",
                encoding="utf-8",
            )
            raise KokoroError(
                "PERSISTENCE_MIGRATION_WRITE_FAILED",
                "injected",
                details={
                    "phase": reason,
                    "record_state": record_state,
                },
            )
        original(path, reason, record_state=record_state)

    monkeypatch.setattr(
        persistent_migrations_module,
        "_confirm_directory_durability",
        replace_before_parent_fsync,
    )
    error = _assert_code(
        "PERSISTENCE_CLEANUP_FAILED",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert error.details == {
        "reason": "target_changed",
        "record_state": "not_visible",
    }
    assert displaced is not None and displaced.is_dir()
    assert tuple(displaced.iterdir()) == ()
    assert replacement is not None
    assert (replacement / "unrelated-sentinel.txt").read_text(
        encoding="utf-8",
    ) == "unrelated"
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source


def test_migration_cleans_generation_when_marker_update_is_not_visible(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    original = persistent_migrations_module._update_migration_marker
    identity_updates = 0

    def fail_marker_update_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal identity_updates
        if isinstance(kwargs.get("target_directory_identity"), dict):
            identity_updates += 1
            if identity_updates == 1:
                raise KokoroError(
                    "PERSISTENCE_MIGRATION_WRITE_FAILED",
                    "injected",
                    details={
                        "phase": "transaction_marker",
                        "record_state": "not_visible",
                    },
                )
        return original(*args, **kwargs)

    monkeypatch.setattr(
        persistent_migrations_module,
        "_update_migration_marker",
        fail_marker_update_once,
    )
    error = _assert_code(
        "PERSISTENCE_MIGRATION_WRITE_FAILED",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert error.details["record_state"] == "not_visible"
    scope = storage.open_persistence_scope(
        consented_rin.data_root,
        SCHEMAS,
        character_id="rin-aster",
    )
    marker = json.loads(scope.transaction_path.read_bytes())
    assert marker["target_directory_identity"] is None
    generated = (
        _persistent_state_root(consented_rin)
        / "generations"
        / marker["target_generation_id"]
    )
    assert not generated.exists()
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == source

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
    assert identity_updates == 2


def test_migration_recovers_when_marker_update_is_already_visible(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    original = persistent_migrations_module._update_migration_marker
    injected = False

    def fail_after_marker_update(*args: Any, **kwargs: Any) -> Any:
        nonlocal injected
        updated = original(*args, **kwargs)
        if (
            isinstance(kwargs.get("target_directory_identity"), dict)
            and not injected
        ):
            injected = True
            raise KokoroError(
                "PERSISTENCE_MIGRATION_WRITE_FAILED",
                "injected",
                details={
                    "phase": "transaction_marker",
                    "record_state": "committed",
                },
            )
        return updated

    monkeypatch.setattr(
        persistent_migrations_module,
        "_update_migration_marker",
        fail_after_marker_update,
    )
    error = _assert_code(
        "PERSISTENCE_MIGRATION_WRITE_FAILED",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert error.details["record_state"] == "committed"
    scope = storage.open_persistence_scope(
        consented_rin.data_root,
        SCHEMAS,
        character_id="rin-aster",
    )
    marker = json.loads(scope.transaction_path.read_bytes())
    assert isinstance(marker["target_directory_identity"], dict)
    generated = (
        _persistent_state_root(consented_rin)
        / "generations"
        / marker["target_generation_id"]
    )
    assert generated.is_dir()

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
    assert not scope.transaction_path.exists()


def test_migration_rejects_retained_replay_output_mutation(
    consented_rin: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, target, plan = _migration_case(
        consented_rin,
        tmp_path,
        verified_release_factory,
    )
    original = persistent_migrations_module._require_target_state
    mutated = False

    def mutate_after_validation(state: Any, built: Any) -> None:
        nonlocal mutated
        original(state, built)
        if not mutated:
            state["mood"]["primary"] = "curious"
            mutated = True

    monkeypatch.setattr(
        persistent_migrations_module,
        "_require_target_state",
        mutate_after_validation,
    )
    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: apply_state_migration(
            consented_rin.data_root,
            "rin-aster",
            target.consent["consent_id"],
            target.consent["grant_revision"],
            plan,
            SCHEMAS,
            mood_strategy="preserve_identical_contract",
        ),
    )
    assert mutated
