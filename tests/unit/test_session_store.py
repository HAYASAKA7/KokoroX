import json
from pathlib import Path

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


def test_load_sanitizes_manifest_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(tmp_path)
    store.start("session-1", "rin-aster", "1.2.3", HASH)
    manifest_path = tmp_path / "sessions" / "session-1.json"
    real_read_bytes = Path.read_bytes

    def denied_read(path: Path) -> bytes:
        if path == manifest_path:
            raise PermissionError("secret operating-system detail")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", denied_read)

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
