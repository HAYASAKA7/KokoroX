import os
from pathlib import Path
import stat
import subprocess
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
import kokoroarc.persistence._storage as storage
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
