import json
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.state import store as store_module
from kokoroarc.state.store import SessionStore


HASH = "a" * 64


def expected_manifest(session_id: str = "session-1") -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": f"session/{session_id}",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "session_id": session_id,
        "character_id": "rin-aster",
        "character_version": "1.2.3",
        "compiled_pack_hash": HASH,
        "scope": "session",
        "state_revision": 0,
        "active": True,
    }


def expected_state(session_id: str = "session-1") -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": f"state/{session_id}",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "revision": 0,
        "turn_index": 0,
        "dimensions": {
            "familiarity": 0.0,
            "trust": 0.0,
            "collaboration": 0.0,
            "tension": 0.0,
        },
        "stage": "unknown",
        "applied_event_ids": [],
        "recent_novelty": {},
    }


def canonical_file(value: dict) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def test_snapshot_returns_detached_manifest_and_authoritative_state(
    tmp_path: Path,
) -> None:
    store = SessionStore(tmp_path)
    store.start("session-1", "rin-aster", "1.2.3", HASH)

    manifest, state = store.snapshot("session-1")
    manifest["active"] = False
    state["dimensions"]["trust"] = 99
    fresh_manifest, fresh_state = store.snapshot("session-1")

    assert fresh_manifest == expected_manifest()
    assert fresh_state == expected_state()


def test_snapshot_observes_completed_restart_as_one_binding(
    tmp_path: Path,
) -> None:
    store = SessionStore(tmp_path)
    store.start("session-1", "rin-aster", "1.2.3", HASH)
    store.end("session-1")
    new_hash = "b" * 64
    store.start("session-1", "rin-aster", "2.0.0", new_hash)

    manifest, state = store.snapshot("session-1")

    assert manifest["character_version"] == "2.0.0"
    assert manifest["compiled_pack_hash"] == new_hash
    assert manifest["state_revision"] == state["revision"] == 0


def test_snapshot_waits_for_the_session_advisory_lock(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.start("session-1", "rin-aster", "1.2.3", HASH)
    entered = threading.Event()

    def take_snapshot() -> tuple[dict, dict]:
        entered.set()
        return store.snapshot("session-1")

    with ThreadPoolExecutor(max_workers=1) as executor:
        with store._session_lock("session-1"):
            future = executor.submit(take_snapshot)
            assert entered.wait(timeout=1)
            assert future.done() is False

        manifest, state = future.result(timeout=1)
    assert manifest["state_revision"] == state["revision"]


def _process_start_worker(data_root: str, barrier, results) -> None:
    from kokoroarc.errors import KokoroError
    from kokoroarc.state import store as process_store_module
    from kokoroarc.state.store import SessionStore

    real_write = process_store_module._atomic_write_json

    def synchronized_write(value: dict, target: Path) -> None:
        if target.parent.name == "state":
            try:
                barrier.wait(timeout=0.75)
            except threading.BrokenBarrierError:
                pass
        real_write(value, target)

    process_store_module._atomic_write_json = synchronized_write
    try:
        SessionStore(Path(data_root)).start(
            "session-1", "rin-aster", "1.2.3", HASH
        )
    except KokoroError as error:
        results.put(("error", error.code))
    else:
        results.put(("ok", None))


def test_start_creates_exact_manifest_and_initial_state(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)

    manifest = store.start("session-1", "rin-aster", "1.2.3", HASH)

    assert manifest == expected_manifest()
    manifest_path = tmp_path / "sessions" / "session-1.json"
    state_path = tmp_path / "state" / "session-1.json"
    assert manifest_path.read_bytes() == canonical_file(expected_manifest())
    assert state_path.read_bytes() == canonical_file(expected_state())
    schemas = SchemaRegistry(Path("schemas/v1"))
    schemas.validate("session-manifest", manifest)
    schemas.validate("relationship-state", json.loads(state_path.read_bytes()))
    assert (tmp_path / "session-locks" / "session-1.lock").read_bytes() == b"\0"
    assert not list(tmp_path.rglob("*.tmp"))


def test_start_writes_state_before_publishing_active_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[tuple[str, bool]] = []
    real_write = store_module._atomic_write_json

    def observed_write(value: dict, target: Path) -> None:
        writes.append((target.parent.name, bool(value.get("active", False))))
        real_write(value, target)

    monkeypatch.setattr(store_module, "_atomic_write_json", observed_write)

    SessionStore(tmp_path).start("session-1", "rin-aster", "1.2.3", HASH)

    assert writes == [("state", False), ("sessions", True)]


def test_concurrent_starts_across_store_instances_are_serialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = threading.Barrier(2)
    real_write = store_module._atomic_write_json

    def synchronized_write(value: dict, target: Path) -> None:
        if target.parent.name == "state":
            try:
                barrier.wait(timeout=0.5)
            except threading.BrokenBarrierError:
                pass
        real_write(value, target)

    monkeypatch.setattr(store_module, "_atomic_write_json", synchronized_write)

    def start(store: SessionStore) -> tuple[str, str | None]:
        try:
            store.start("session-1", "rin-aster", "1.2.3", HASH)
        except KokoroError as error:
            return "error", error.code
        return "ok", None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(start, [SessionStore(tmp_path), SessionStore(tmp_path)])
        )

    assert sorted(results) == [
        ("error", "SESSION_ALREADY_ACTIVE"),
        ("ok", None),
    ]
    assert SessionStore(tmp_path).load("session-1") == expected_manifest()


def test_concurrent_starts_across_processes_are_serialized(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_process_start_worker,
            args=(str(tmp_path), barrier, results),
        )
        for _ in range(2)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)

    assert all(not process.is_alive() for process in processes)
    assert [process.exitcode for process in processes] == [0, 0]
    observed = sorted(results.get(timeout=2) for _ in range(2))
    assert observed == [
        ("error", "SESSION_ALREADY_ACTIVE"),
        ("ok", None),
    ]
    assert SessionStore(tmp_path).load("session-1") == expected_manifest()


def test_duplicate_active_start_rejects_without_writes_or_content_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(tmp_path)
    store.start("session-1", "rin-aster", "1.2.3", HASH)
    manifest_path = tmp_path / "sessions" / "session-1.json"
    state_path = tmp_path / "state" / "session-1.json"
    before = (manifest_path.read_bytes(), state_path.read_bytes())
    writes: list[Path] = []

    def forbidden_write(_value: dict, target: Path) -> None:
        writes.append(target)
        raise AssertionError("duplicate start attempted a write")

    monkeypatch.setattr(store_module, "_atomic_write_json", forbidden_write)

    with pytest.raises(KokoroError) as raised:
        store.start("session-1", "other-character", "9.9.9", "b" * 64)

    assert raised.value.code == "SESSION_ALREADY_ACTIVE"
    assert writes == []
    assert (manifest_path.read_bytes(), state_path.read_bytes()) == before


def test_inactive_session_can_restart_and_resets_state(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.start("session-1", "rin-aster", "1.2.3", HASH)
    store.end("session-1")
    state_path = tmp_path / "state" / "session-1.json"
    changed_state = expected_state()
    changed_state["revision"] = 8
    changed_state["turn_index"] = 9
    changed_state["dimensions"]["trust"] = 72.0
    state_path.write_bytes(canonical_file(changed_state))

    restarted = store.start("session-1", "rin-aster", "1.2.3", HASH)

    assert restarted == expected_manifest()
    assert state_path.read_bytes() == canonical_file(expected_state())


def test_load_and_end_have_explicit_idempotent_lifecycle(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    active = store.start("session-1", "rin-aster", "1.2.3", HASH)
    state_path = tmp_path / "state" / "session-1.json"
    state_before = state_path.read_bytes()

    assert store.load("session-1") == active
    ended = store.end("session-1")
    ended_again = store.end("session-1")

    assert ended == {**active, "active": False}
    assert ended_again == ended
    assert {
        key: value for key, value in ended.items() if key != "active"
    } == {key: value for key, value in active.items() if key != "active"}
    assert state_path.read_bytes() == state_before


@pytest.mark.parametrize("operation", ["load", "end"])
def test_absent_session_has_stable_not_found_error(
    tmp_path: Path, operation: str
) -> None:
    store = SessionStore(tmp_path)

    with pytest.raises(KokoroError) as raised:
        getattr(store, operation)("missing-session")

    assert raised.value.code == "SESSION_NOT_FOUND"


@pytest.mark.parametrize(
    "contents",
    [b"\xff", b"{", b"[]"],
    ids=["invalid-utf8", "malformed-json", "non-object"],
)
def test_load_sanitizes_malformed_manifest_data(
    tmp_path: Path, contents: bytes
) -> None:
    manifest_path = tmp_path / "sessions" / "session-1.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(contents)

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).load("session-1")

    assert raised.value.code == "SESSION_DATA_INVALID"
    assert raised.value.details == {}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document.pop("active"),
        lambda document: document.update({"unknown": True}),
        lambda document: document.update({"schema_version": "2.0"}),
        lambda document: document.update({"artifact_id": "session/other"}),
        lambda document: document.update({"created_by": []}),
        lambda document: document["created_by"].update({"unknown": True}),
        lambda document: document["created_by"].update({"component": "other"}),
        lambda document: document["created_by"].update({"version": ""}),
        lambda document: document["created_by"].update({"version": "v" * 65}),
        lambda document: document.update({"session_id": "other"}),
        lambda document: document.update({"character_id": "Invalid"}),
        lambda document: document.update({"character_version": "1.2.3-01"}),
        lambda document: document.update({"compiled_pack_hash": "A" * 64}),
        lambda document: document.update({"scope": "global"}),
        lambda document: document.update({"state_revision": True}),
        lambda document: document.update({"state_revision": -1}),
        lambda document: document.update({"active": 1}),
    ],
    ids=[
        "missing-field",
        "unknown-field",
        "schema-version",
        "artifact-binding",
        "created-by-object",
        "created-by-extra",
        "created-by-component",
        "created-by-empty-version",
        "created-by-long-version",
        "session-binding",
        "character-id",
        "character-version",
        "compiled-pack-hash",
        "scope",
        "boolean-state-revision",
        "negative-state-revision",
        "non-boolean-active",
    ],
)
def test_load_rejects_corrupt_parseable_manifest(
    tmp_path: Path, mutation
) -> None:
    manifest_path = tmp_path / "sessions" / "session-1.json"
    manifest_path.parent.mkdir(parents=True)
    document = expected_manifest()
    mutation(document)
    manifest_path.write_bytes(canonical_file(document))

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).load("session-1")

    assert raised.value.code == "SESSION_DATA_INVALID"
    assert raised.value.details == {}


def test_load_accepts_manifest_created_by_an_older_runtime(tmp_path: Path) -> None:
    manifest_path = tmp_path / "sessions" / "session-1.json"
    manifest_path.parent.mkdir(parents=True)
    document = expected_manifest()
    document["created_by"]["version"] = "0.0.0-older"
    manifest_path.write_bytes(canonical_file(document))

    assert SessionStore(tmp_path).load("session-1") == document


@pytest.mark.parametrize(
    "contents",
    [
        canonical_file(expected_manifest()).replace(
            b'"active":true', b'"active":true,"active":false'
        ),
        canonical_file(expected_manifest()).replace(
            b'"state_revision":0', b'"state_revision":NaN'
        ),
        canonical_file(expected_manifest()).replace(
            b'"state_revision":0', b'"state_revision":Infinity'
        ),
        canonical_file(expected_manifest()).replace(
            b'"version":"0.0.0.dev0"', b'"version":"\\ud800"'
        ),
    ],
    ids=["duplicate-key", "nan", "infinity", "unpaired-surrogate"],
)
def test_load_rejects_non_strict_json_manifest(
    tmp_path: Path, contents: bytes
) -> None:
    manifest_path = tmp_path / "sessions" / "session-1.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(contents)

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).load("session-1")

    assert raised.value.code == "SESSION_DATA_INVALID"
    assert raised.value.details == {}


def test_load_accepts_manifest_at_exact_byte_limit(tmp_path: Path) -> None:
    contents = canonical_file(expected_manifest())
    contents += b" " * (store_module.SESSION_MANIFEST_MAX_BYTES - len(contents))
    manifest_path = tmp_path / "sessions" / "session-1.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(contents)

    assert len(contents) == store_module.SESSION_MANIFEST_MAX_BYTES
    assert SessionStore(tmp_path).load("session-1") == expected_manifest()


def test_load_rejects_oversized_manifest_before_json_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "sessions" / "session-1.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(b" " * (store_module.SESSION_MANIFEST_MAX_BYTES + 1))
    monkeypatch.setattr(
        store_module.json,
        "loads",
        lambda *_args, **_kwargs: pytest.fail("oversized JSON was parsed"),
    )

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).load("session-1")

    assert raised.value.code == "SESSION_DATA_INVALID"
    assert raised.value.details == {}


def test_load_sanitizes_deeply_nested_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "sessions" / "session-1.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(b"[" * 2000 + b"]" * 2000)

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).load("session-1")

    assert raised.value.code == "SESSION_DATA_INVALID"
    assert "recursion" not in str(raised.value).lower()
    assert raised.value.details == {}


def test_load_sanitizes_manifest_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(tmp_path)
    store.start("session-1", "rin-aster", "1.2.3", HASH)
    manifest_path = tmp_path / "sessions" / "session-1.json"
    real_open = Path.open

    def denied_open(path: Path, *args, **kwargs):
        if path == manifest_path:
            raise PermissionError("secret operating-system detail")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)

    with pytest.raises(KokoroError) as raised:
        store.load("session-1")

    assert raised.value.code == "SESSION_READ_FAILED"
    assert "secret" not in str(raised.value)
    assert "secret" not in json.dumps(raised.value.envelope())


@pytest.mark.parametrize(
    "session_id",
    [
        True,
        "",
        "Upper",
        "a" * 129,
        "../escape",
        "a/b",
        "a\\b",
        "a\nb",
        "-leading",
        "trailing-",
        "double--hyphen",
        "con",
        "prn",
        "aux",
        "nul",
        "com1",
        "com9",
        "lpt1",
        "lpt9",
    ],
)
def test_start_rejects_unsafe_session_ids_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_id: object
) -> None:
    writes: list[Path] = []
    monkeypatch.setattr(
        store_module,
        "_atomic_write_json",
        lambda _value, target: writes.append(target),
    )

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).start(session_id, "rin-aster", "1.2.3", HASH)

    assert raised.value.code == "INVALID_SESSION_ID"
    assert writes == []
    assert not tmp_path.joinpath("sessions").exists()
    assert not tmp_path.joinpath("state").exists()


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("character_id", True, "INVALID_CHARACTER_ID"),
        ("character_id", "Upper", "INVALID_CHARACTER_ID"),
        ("character_id", "a" * 65, "INVALID_CHARACTER_ID"),
        ("character_version", True, "INVALID_CHARACTER_VERSION"),
        ("character_version", "1.2", "INVALID_CHARACTER_VERSION"),
        ("character_version", "01.2.3", "INVALID_CHARACTER_VERSION"),
        ("character_version", "1.2.3-01", "INVALID_CHARACTER_VERSION"),
        ("character_version", "1.2.3-alpha.01", "INVALID_CHARACTER_VERSION"),
        ("character_version", "1.2.3-", "INVALID_CHARACTER_VERSION"),
        ("character_version", "1.2.3-alpha.", "INVALID_CHARACTER_VERSION"),
        ("character_version", "1.2.3+", "INVALID_CHARACTER_VERSION"),
        ("character_version", "1.2.3+build.", "INVALID_CHARACTER_VERSION"),
        ("compiled_pack_hash", True, "INVALID_COMPILED_PACK_HASH"),
        ("compiled_pack_hash", "A" * 64, "INVALID_COMPILED_PACK_HASH"),
        ("compiled_pack_hash", "a" * 63, "INVALID_COMPILED_PACK_HASH"),
    ],
)
def test_start_rejects_invalid_inputs_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    code: str,
) -> None:
    arguments: dict[str, object] = {
        "session_id": "session-1",
        "character_id": "rin-aster",
        "character_version": "1.2.3",
        "compiled_pack_hash": HASH,
    }
    arguments[field] = value
    writes: list[Path] = []
    monkeypatch.setattr(
        store_module,
        "_atomic_write_json",
        lambda _document, target: writes.append(target),
    )

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).start(**arguments)

    assert raised.value.code == code
    assert writes == []
    assert not tmp_path.joinpath("sessions").exists()
    assert not tmp_path.joinpath("state").exists()


@pytest.mark.parametrize(
    "version",
    ["1.2.3-0", "1.2.3-alpha.0", "1.2.3-01a", "1.2.3+01"],
)
def test_start_accepts_strict_semver_representatives(
    tmp_path: Path, version: str
) -> None:
    manifest = SessionStore(tmp_path).start(
        "session-1", "rin-aster", version, HASH
    )

    assert manifest["character_version"] == version


def test_start_accepts_all_input_boundaries(tmp_path: Path) -> None:
    session_id = "a" * 128
    character_id = "b" * 64
    version = "0.0.0-alpha.1+build-5"

    manifest = SessionStore(tmp_path).start(
        session_id, character_id, version, "f" * 64
    )

    assert manifest["session_id"] == session_id
    assert manifest["character_id"] == character_id
    assert manifest["character_version"] == version


@pytest.mark.parametrize("directory", ["sessions", "state"])
def test_start_rejects_symlinked_storage_directory(
    tmp_path: Path, directory: str
) -> None:
    outside = tmp_path.parent / f"outside-{tmp_path.name}-{directory}"
    outside.mkdir(exist_ok=True)
    redirect = tmp_path / directory
    tmp_path.mkdir(exist_ok=True)
    try:
        redirect.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("The current account cannot create directory symlinks")

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).start("session-1", "rin-aster", "1.2.3", HASH)

    assert raised.value.code == "SESSION_PATH_UNSAFE"
    assert not list(outside.iterdir())


def test_start_rejects_directory_reported_as_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "sessions").mkdir()
    monkeypatch.setattr(
        store_module,
        "_path_is_redirect",
        lambda path: path.name == "sessions",
    )

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).start("session-1", "rin-aster", "1.2.3", HASH)

    assert raised.value.code == "SESSION_PATH_UNSAFE"


def test_path_redirect_detection_covers_junction_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "is_symlink", lambda _path: False)
    monkeypatch.setattr(Path, "is_junction", lambda _path: True, raising=False)

    assert store_module._path_is_redirect(tmp_path / "candidate") is True


def test_path_redirect_detection_covers_reparse_attribute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reparse_flag = 0x400
    fake_stat = SimpleNamespace(st_file_attributes=reparse_flag)
    monkeypatch.setattr(Path, "is_symlink", lambda _path: False)
    monkeypatch.setattr(Path, "is_junction", lambda _path: False, raising=False)
    monkeypatch.setattr(
        Path,
        "stat",
        lambda _path, *, follow_symlinks=True: fake_stat,
    )
    monkeypatch.setattr(
        store_module.stat,
        "FILE_ATTRIBUTE_REPARSE_POINT",
        reparse_flag,
        raising=False,
    )

    assert store_module._path_is_redirect(tmp_path / "candidate") is True


@pytest.mark.parametrize("redirect_kind", ["directory", "target"])
def test_start_rejects_redirected_session_lock_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    redirect_kind: str,
) -> None:
    writes: list[Path] = []
    real_redirect_check = store_module._path_is_redirect

    def lock_path_is_redirect(path: Path) -> bool:
        if redirect_kind == "directory" and path.name == "session-locks":
            return True
        if (
            redirect_kind == "target"
            and path.parent.name == "session-locks"
            and path.suffix == ".lock"
        ):
            return True
        return real_redirect_check(path)

    monkeypatch.setattr(store_module, "_path_is_redirect", lock_path_is_redirect)
    monkeypatch.setattr(
        store_module,
        "_atomic_write_json",
        lambda _document, target: writes.append(target),
    )

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).start("session-1", "rin-aster", "1.2.3", HASH)

    assert raised.value.code == "SESSION_PATH_UNSAFE"
    assert writes == []


def test_start_sanitizes_os_lock_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        store_module,
        "_acquire_os_file_lock",
        lambda _handle: (_ for _ in ()).throw(
            PermissionError("secret operating-system detail")
        ),
    )

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).start("session-1", "rin-aster", "1.2.3", HASH)

    assert raised.value.code == "SESSION_LOCK_FAILED"
    assert "secret" not in str(raised.value)
    assert raised.value.details == {}


def test_start_has_bounded_os_lock_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "_SESSION_LOCK_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(
        store_module,
        "_try_acquire_os_file_lock",
        lambda _handle: False,
    )

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).start("session-1", "rin-aster", "1.2.3", HASH)

    assert raised.value.code == "SESSION_LOCK_TIMEOUT"
    assert raised.value.retryable is True
    assert raised.value.details == {}


def test_load_rejects_in_root_manifest_file_symlink(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.start("session-1", "rin-aster", "1.2.3", HASH)
    sessions = tmp_path / "sessions"
    target = sessions / "other.json"
    target.write_bytes(canonical_file(expected_manifest()))
    redirect = sessions / "session-1.json"
    redirect.unlink()
    try:
        redirect.symlink_to(target)
    except OSError:
        pytest.skip("The current account cannot create file symlinks")

    with pytest.raises(KokoroError) as raised:
        store.load("session-1")

    assert raised.value.code == "SESSION_PATH_UNSAFE"


@pytest.mark.parametrize("area", ["sessions", "state"])
def test_start_rejects_final_target_reported_as_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, area: str
) -> None:
    writes: list[Path] = []
    real_redirect_check = store_module._path_is_redirect

    def target_is_redirect(path: Path) -> bool:
        if path.name == "session-1.json" and path.parent.name == area:
            return True
        return real_redirect_check(path)

    monkeypatch.setattr(store_module, "_path_is_redirect", target_is_redirect)
    monkeypatch.setattr(
        store_module,
        "_atomic_write_json",
        lambda _document, target: writes.append(target),
    )

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).start("session-1", "rin-aster", "1.2.3", HASH)

    assert raised.value.code == "SESSION_PATH_UNSAFE"
    assert writes == []


def test_atomic_write_failure_preserves_existing_file_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "manifest.json"
    target.write_bytes(b"previous\n")
    expected = PermissionError("replace denied")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise expected

    monkeypatch.setattr("kokoroarc.packs.compiler.os.replace", fail_replace)

    with pytest.raises(PermissionError) as raised:
        store_module._atomic_write_json({"new": True}, target)

    assert raised.value is expected
    assert target.read_bytes() == b"previous\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_manifest_publish_failure_never_exposes_active_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = store_module._atomic_write_json
    expected = OSError("publish failure")

    def fail_manifest(value: dict, target: Path) -> None:
        if target.parent.name == "sessions":
            raise expected
        real_write(value, target)

    monkeypatch.setattr(store_module, "_atomic_write_json", fail_manifest)

    with pytest.raises(OSError) as raised:
        SessionStore(tmp_path).start("session-1", "rin-aster", "1.2.3", HASH)

    assert raised.value is expected
    assert (tmp_path / "state" / "session-1.json").is_file()
    assert not (tmp_path / "sessions" / "session-1.json").exists()
    assert not list(tmp_path.rglob("*.tmp"))


def test_returned_and_loaded_manifests_are_independent(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    returned = store.start("session-1", "rin-aster", "1.2.3", HASH)
    returned["created_by"]["component"] = "changed"
    returned["active"] = False

    first_load = store.load("session-1")
    first_load["created_by"]["component"] = "also-changed"

    second_load = store.load("session-1")
    assert second_load == expected_manifest()
    assert returned is not first_load
    assert first_load is not second_load
