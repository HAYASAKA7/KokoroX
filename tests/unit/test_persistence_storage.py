from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.persistence._storage import (
    PersistenceKey,
    PersistenceLimits,
    open_persistence_scope,
    read_canonical_object,
    scan_canonical_directory,
)
from kokoroarc.schemas import SchemaRegistry


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
        "permissions": [
            "relationship_state",
            "mood_state",
            "memory_references",
        ],
        "status": "active",
        "grant_revision": 1,
        "revoked_revision": None,
        "persistence_policy": "explicit_consent_only",
    }


def _scope(tmp_path: Path, schemas: Any = SCHEMAS):
    return open_persistence_scope(
        tmp_path / "data",
        schemas,
        character_id="rin-aster",
    )


def _write_consent(path: Path) -> bytes:
    payload = canonical_bytes(_consent())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _assert_code(code: str, action: Any) -> None:
    with pytest.raises(KokoroError) as caught:
        action()
    assert caught.value.code == code


def test_absent_scope_open_is_read_only(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    scope = open_persistence_scope(
        root,
        SCHEMAS,
        character_id="rin-aster",
    )
    assert scope.key == PersistenceKey(
        scope="global",
        workspace_id=None,
        namespace="original",
        character_id="rin-aster",
    )
    assert scope.root == root.absolute()
    assert not root.exists()


def test_storage_limits_are_frozen_and_bounded() -> None:
    limits = PersistenceLimits()
    assert limits.max_consent_bytes == 64 * 1024
    assert limits.max_state_bytes == 4 * 1024 * 1024
    assert limits.max_event_bytes == 16 * 1024
    assert limits.max_memory_bytes == 16 * 1024
    assert limits.max_transaction_bytes == 128 * 1024
    assert limits.max_consent_history == 1024
    assert limits.max_state_generations == 64
    assert limits.max_state_events == 10_000
    assert limits.max_memory_references == 1024
    assert limits.max_journal_bytes == 64 * 1024 * 1024
    with pytest.raises(FrozenInstanceError):
        limits.max_state_events = 1  # type: ignore[misc]


def test_global_and_workspace_scopes_are_isolated_and_read_only(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    before = workspace.stat()
    data_root = tmp_path / "data"

    global_scope = open_persistence_scope(
        data_root,
        SCHEMAS,
        character_id="rin-aster",
    )
    workspace_scope = open_persistence_scope(
        data_root,
        SCHEMAS,
        character_id="rin-aster",
        workspace_root=workspace,
    )

    assert global_scope.key.scope_parts == ("global",)
    assert workspace_scope.key.scope_parts == (
        "workspaces",
        workspace_scope.key.workspace_id,
    )
    assert global_scope.character_root("consents") != (
        workspace_scope.character_root("consents")
    )
    assert not data_root.exists()
    after = workspace.stat()
    assert (before.st_dev, before.st_ino, before.st_mtime_ns) == (
        after.st_dev,
        after.st_ino,
        after.st_mtime_ns,
    )


@pytest.mark.parametrize(
    "namespace,character_id",
    [
        ("../original", "rin-aster"),
        ("Original", "rin-aster"),
        ("original", "../rin-aster"),
        ("original", "CON"),
        ("original", "rin_aster"),
    ],
)
def test_scope_rejects_unsafe_storage_segments(
    tmp_path: Path, namespace: str, character_id: str
) -> None:
    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: open_persistence_scope(
            tmp_path / "data",
            SCHEMAS,
            namespace=namespace,
            character_id=character_id,
        ),
    )


def test_read_canonical_object_returns_detached_snapshot(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    path = tmp_path / "consent.json"
    payload = _write_consent(path)

    snapshot = read_canonical_object(
        path,
        limit=len(payload),
        schema_name="persistence-consent",
        boundary=scope.boundary,
    )

    assert snapshot is not None
    assert snapshot.path == path
    assert snapshot.payload == payload
    assert snapshot.value == _consent()
    snapshot.value["status"] = "revoked"
    assert snapshot.payload == payload
    scope.boundary.assert_clean()


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema_version":"1.0","schema_version":"1.0"}',
        b'{"value":NaN}',
        b"\xff",
        b'{ "value": 1 }',
        b"[]",
    ],
    ids=["duplicate-key", "nan", "invalid-utf8", "noncanonical", "non-object"],
)
def test_read_canonical_object_rejects_invalid_storage_json(
    tmp_path: Path, payload: bytes
) -> None:
    scope = _scope(tmp_path)
    path = tmp_path / "invalid.json"
    path.write_bytes(payload)

    _assert_code(
        "PERSISTENCE_CHANGED",
        lambda: read_canonical_object(
            path,
            limit=1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_read_canonical_object_stops_at_limit_plus_one(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    path = tmp_path / "oversized.json"
    path.write_bytes(b"x" * 17)

    _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: read_canonical_object(
            path,
            limit=16,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_optional_absence_is_read_only_and_audited(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    path = tmp_path / "missing" / "consent.json"

    result = read_canonical_object(
        path,
        limit=1024,
        schema_name="persistence-consent",
        boundary=scope.boundary,
        optional=True,
    )
    assert result is None
    assert not path.parent.exists()

    _write_consent(path)
    _assert_code("PERSISTENCE_CHANGED", scope.boundary.assert_clean)


def test_scan_canonical_directory_is_sorted_and_bounded(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    directory = tmp_path / "history"
    first = _consent()
    first["grant_revision"] = 1
    second = _consent()
    second["grant_revision"] = 2
    second["artifact_id"] = "consents/global/rin-aster/consent-02"
    (directory / "placeholder").parent.mkdir(parents=True)
    (directory / "0002.json").write_bytes(canonical_bytes(second))
    (directory / "0001.json").write_bytes(canonical_bytes(first))

    snapshots = scan_canonical_directory(
        directory,
        entry_limit=2,
        aggregate_limit=128 * 1024,
        file_limit=64 * 1024,
        schema_name="persistence-consent",
        boundary=scope.boundary,
    )

    assert [snapshot.path.name for snapshot in snapshots] == [
        "0001.json",
        "0002.json",
    ]
    scope.boundary.assert_clean()


def test_scan_canonical_directory_rejects_aggregate_overflow(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    directory = tmp_path / "history"
    first = _write_consent(directory / "0001.json")
    second = _write_consent(directory / "0002.json")

    _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: scan_canonical_directory(
            directory,
            entry_limit=2,
            aggregate_limit=len(first) + len(second) - 1,
            file_limit=64 * 1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


@pytest.mark.parametrize("unsafe_name", ["note.txt", "entry.JSON", ".hidden.json"])
def test_scan_canonical_directory_rejects_unsafe_suffixes(
    tmp_path: Path, unsafe_name: str
) -> None:
    scope = _scope(tmp_path)
    directory = tmp_path / "history"
    directory.mkdir()
    (directory / unsafe_name).write_bytes(b"{}")

    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: scan_canonical_directory(
            directory,
            entry_limit=4,
            aggregate_limit=1024,
            file_limit=1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_scan_canonical_directory_rejects_mixed_node_types(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    directory = tmp_path / "history"
    (directory / "nested.json").mkdir(parents=True)

    _assert_code(
        "PERSISTENCE_PATH_UNSAFE",
        lambda: scan_canonical_directory(
            directory,
            entry_limit=4,
            aggregate_limit=1024,
            file_limit=1024,
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )


def test_storage_boundary_detects_mutation_and_stays_failed(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    caller = {"permissions": ["relationship_state"]}
    scope.boundary.capture("caller_permissions", caller)
    caller["permissions"].append("mood_state")

    _assert_code("PERSISTENCE_INPUT_MUTATION", scope.boundary.assert_clean)
    caller["permissions"] = ["relationship_state"]
    _assert_code("PERSISTENCE_INPUT_MUTATION", scope.boundary.assert_clean)


def test_storage_boundary_detects_schema_input_mutation(tmp_path: Path) -> None:
    class MutatingSchemas:
        def validate(self, _name: str, instance: Any) -> None:
            instance["status"] = "revoked"

    scope = _scope(tmp_path, MutatingSchemas())
    path = tmp_path / "consent.json"
    payload = _write_consent(path)

    _assert_code(
        "PERSISTENCE_INPUT_MUTATION",
        lambda: read_canonical_object(
            path,
            limit=len(payload),
            schema_name="persistence-consent",
            boundary=scope.boundary,
        ),
    )
