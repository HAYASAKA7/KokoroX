from __future__ import annotations

import copy
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.state import store as store_module
from kokoroarc.state.store import SessionStore


HASH = "a" * 64


def event(event_id: str, revision: int, *, trust: float = 2.0) -> dict:
    return {
        "event_id": event_id,
        "novelty_key": f"novelty-{event_id}",
        "expected_state_revision": revision,
        "confidence": 1.0,
        "effects": {"trust": trust},
    }


def started_store(tmp_path: Path, session_id: str = "s1") -> SessionStore:
    store = SessionStore(tmp_path)
    store.start(session_id, "rin-aster", "1.0.0", HASH)
    return store


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_apply_is_revision_checked_idempotent_and_replayable(
    tmp_path: Path,
) -> None:
    store = started_store(tmp_path)

    first = store.apply("s1", event("e1", 0), max_delta=4.0)
    duplicate = store.apply("s1", event("e1", 0), max_delta=4.0)

    assert duplicate == first
    assert store.replay("s1") == first
    with pytest.raises(KokoroError) as raised:
        store.apply("s1", event("e2", 0), max_delta=4.0)
    assert raised.value.code == "STATE_REVISION_CONFLICT"
    assert raised.value.retryable is True
    assert raised.value.details == {"expected": 0, "actual": 1}


def test_apply_publishes_event_before_cache_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = started_store(tmp_path)
    real_write = store_module._atomic_write_json
    writes: list[tuple[str, int | None]] = []

    def record_write(value: dict, target: Path) -> None:
        writes.append((target.parent.name, value.get("revision")))
        real_write(value, target)

    monkeypatch.setattr(store_module, "_atomic_write_json", record_write)

    store.apply("s1", event("e1", 0))

    assert [area for area, _revision in writes] == ["s1", "state", "sessions"]


def test_event_commit_recovers_cache_and_manifest_on_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = started_store(tmp_path)
    real_write = store_module._atomic_write_json
    failed = False

    def fail_first_state_write(value: dict, target: Path) -> None:
        nonlocal failed
        if target.parent.name == "state" and not failed:
            failed = True
            raise OSError("private storage detail")
        real_write(value, target)

    monkeypatch.setattr(store_module, "_atomic_write_json", fail_first_state_write)
    with pytest.raises(OSError):
        store.apply("s1", event("e1", 0))

    assert len(list((tmp_path / "events" / "s1").glob("*.json"))) == 1
    assert read_json(tmp_path / "state" / "s1.json")["revision"] == 0

    recovered_manifest = store.load("s1")
    assert recovered_manifest["state_revision"] == 1
    assert read_json(tmp_path / "sessions" / "s1.json") == recovered_manifest
    assert read_json(tmp_path / "state" / "s1.json")["revision"] == 1

    recovered = store.apply("s1", event("e1", 0))

    assert recovered["revision"] == 1
    assert read_json(tmp_path / "state" / "s1.json") == recovered
    assert store.load("s1")["state_revision"] == 1


def test_truncated_journal_never_rolls_back_or_reuses_manifest_revision(
    tmp_path: Path,
) -> None:
    store = started_store(tmp_path)
    store.apply("s1", event("e1", 0))
    store.apply("s1", event("e2", 1))
    manifest_path = tmp_path / "sessions" / "s1.json"
    state_path = tmp_path / "state" / "s1.json"
    manifest_before = manifest_path.read_bytes()
    state_before = state_path.read_bytes()
    (tmp_path / "events" / "s1" / "2-e2.json").unlink()

    operations = [
        lambda: store.load("s1"),
        lambda: store.apply("s1", event("e3", 1)),
        lambda: store.replay("s1"),
    ]
    for operation in operations:
        with pytest.raises(KokoroError) as raised:
            operation()
        assert raised.value.code == "STATE_JOURNAL_INVALID"
        assert raised.value.details == {}
        assert manifest_path.read_bytes() == manifest_before
        assert state_path.read_bytes() == state_before

    assert sorted(path.name for path in (tmp_path / "events" / "s1").iterdir()) == [
        "1-e1.json"
    ]


def test_load_maps_lock_timeout_to_retryable_state_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = started_store(tmp_path)
    monkeypatch.setattr(store_module, "_SESSION_LOCK_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(
        store_module, "_try_acquire_os_file_lock", lambda _handle: False
    )

    with pytest.raises(KokoroError) as raised:
        store.load("s1")

    assert raised.value.code == "STATE_BUSY"
    assert raised.value.retryable is True
    assert raised.value.details == {}


def test_replay_maps_lock_timeout_to_retryable_state_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = started_store(tmp_path)
    monkeypatch.setattr(store_module, "_SESSION_LOCK_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(
        store_module, "_try_acquire_os_file_lock", lambda _handle: False
    )

    with pytest.raises(KokoroError) as raised:
        store.replay("s1")

    assert raised.value.code == "STATE_BUSY"
    assert raised.value.retryable is True
    assert raised.value.details == {}


def test_apply_repairs_corrupt_cache_even_when_manifest_revision_matches(
    tmp_path: Path,
) -> None:
    store = started_store(tmp_path)
    expected = store.apply("s1", event("e1", 0))
    (tmp_path / "state" / "s1.json").write_bytes(b'{"revision":NaN}')

    duplicate = store.apply("s1", event("e1", 0))

    assert duplicate == expected
    assert read_json(tmp_path / "state" / "s1.json") == expected


def test_replay_persists_and_uses_non_default_transition_parameters(
    tmp_path: Path,
) -> None:
    store = started_store(tmp_path)
    original = event("e1", 0, trust=4.0)

    applied = store.apply("s1", original, max_delta=1.25, repetition_window=5)
    record = read_json(next((tmp_path / "events" / "s1").glob("*.json")))

    assert applied["dimensions"]["trust"] == 1.25
    assert record["transition"] == {
        "algorithm": "relationship-v1",
        "max_delta": 1.25,
        "repetition_window": 5,
    }
    assert store.replay("s1") == applied


def test_replay_uses_frozen_v1_algorithm_not_current_delegate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = started_store(tmp_path)
    expected = store.apply("s1", event("e1", 0))
    current_apply = store_module.apply_event

    def changed_current_algorithm(*args, **kwargs) -> dict:
        changed = current_apply(*args, **kwargs)
        changed["dimensions"]["trust"] = 99.0
        return changed

    monkeypatch.setattr(store_module, "apply_event", changed_current_algorithm)

    assert store.replay("s1") == expected


@pytest.mark.parametrize("algorithm", [None, "relationship-v2"])
def test_replay_rejects_missing_or_unsupported_transition_algorithm(
    tmp_path: Path, algorithm: str | None
) -> None:
    store = started_store(tmp_path)
    store.apply("s1", event("e1", 0))
    record_path = next((tmp_path / "events" / "s1").glob("*.json"))
    record = read_json(record_path)
    if algorithm is None:
        record["transition"].pop("algorithm", None)
    else:
        record["transition"]["algorithm"] = algorithm
    store_module._atomic_write_json(record, record_path)

    with pytest.raises(KokoroError) as raised:
        store.replay("s1")

    assert raised.value.code == "STATE_JOURNAL_INVALID"
    assert raised.value.details == {}


def test_apply_does_not_mutate_minimal_or_full_event(tmp_path: Path) -> None:
    store = started_store(tmp_path)
    minimal = event("e1", 0)
    minimal_before = copy.deepcopy(minimal)

    store.apply("s1", minimal)

    assert minimal == minimal_before

    full = {
        "schema_version": "1.0",
        "artifact_id": "event/e2",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "event_id": "e2",
        "turn_id": "turn-2",
        "origin": "verified_task_outcome",
        "novelty_key": "novelty-e2",
        "expected_state_revision": 1,
        "evaluator_version": "interaction-v1",
        "evidence": {"kind": "test_result", "reference": "pytest-2"},
        "confidence": 1.0,
        "effects": {"collaboration": 1.0},
    }
    full_before = copy.deepcopy(full)

    store.apply("s1", full)

    assert full == full_before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(extra=True),
        lambda value: value.pop("effects"),
        lambda value: value.update(event_id="Upper"),
        lambda value: value.update(expected_state_revision=True),
        lambda value: value.update(confidence=float("nan")),
        lambda value: value.update(confidence=1.1),
        lambda value: value.update(effects={}),
        lambda value: value.update(effects={"unknown": 1.0}),
        lambda value: value.update(effects={"trust": float("inf")}),
        lambda value: value.update(effects={"trust": 4.1}),
    ],
)
def test_apply_rejects_invalid_events_without_writes(
    tmp_path: Path, mutate
) -> None:
    store = started_store(tmp_path)
    candidate = event("e1", 0)
    mutate(candidate)

    with pytest.raises(KokoroError) as raised:
        store.apply("s1", candidate)

    assert raised.value.code == "INVALID_EVENT"
    assert raised.value.details == {}
    assert not (tmp_path / "events").exists()


@pytest.mark.parametrize(
    ("max_delta", "repetition_window"),
    [(True, 3), (float("inf"), 3), (-0.1, 3), (4.1, 3), (4.0, True), (4.0, 0)],
)
def test_apply_rejects_invalid_transition_configuration(
    tmp_path: Path, max_delta: object, repetition_window: object
) -> None:
    store = started_store(tmp_path)

    with pytest.raises(KokoroError) as raised:
        store.apply(
            "s1",
            event("e1", 0),
            max_delta=max_delta,
            repetition_window=repetition_window,
        )

    assert raised.value.code == "INVALID_EVENT"
    assert not (tmp_path / "events").exists()


def test_apply_requires_an_active_session(tmp_path: Path) -> None:
    store = started_store(tmp_path)
    store.end("s1")

    with pytest.raises(KokoroError) as raised:
        store.apply("s1", event("e1", 0))

    assert raised.value.code == "SESSION_NOT_ACTIVE"
    assert not (tmp_path / "events").exists()


def test_apply_maps_only_lock_timeout_to_retryable_state_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = started_store(tmp_path)
    monkeypatch.setattr(store_module, "_SESSION_LOCK_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(
        store_module, "_try_acquire_os_file_lock", lambda _handle: False
    )

    with pytest.raises(KokoroError) as raised:
        store.apply("s1", event("e1", 0))

    assert raised.value.code == "STATE_BUSY"
    assert raised.value.retryable is True
    assert raised.value.details == {}


def test_cross_instance_concurrent_apply_serializes_revision_check(
    tmp_path: Path,
) -> None:
    started_store(tmp_path)
    first_store = SessionStore(tmp_path)
    second_store = SessionStore(tmp_path)

    def apply_one(store: SessionStore, event_id: str) -> tuple[str, int | str]:
        try:
            return ("ok", store.apply("s1", event(event_id, 0))["revision"])
        except KokoroError as error:
            return (error.code, error.details["actual"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda pair: apply_one(*pair),
                [(first_store, "e1"), (second_store, "e2")],
            )
        )

    assert sorted(results) == [("STATE_REVISION_CONFLICT", 1), ("ok", 1)]


def test_cross_process_apply_uses_the_persistent_advisory_lock(
    tmp_path: Path,
) -> None:
    started_store(tmp_path)
    worker = """
import json, sys
from kokoroarc.errors import KokoroError
from kokoroarc.state.store import SessionStore
event_id = sys.argv[2]
event = {
    'event_id': event_id,
    'novelty_key': 'novelty-' + event_id,
    'expected_state_revision': 0,
    'confidence': 1.0,
    'effects': {'trust': 1.0},
}
try:
    state = SessionStore(sys.argv[1]).apply('s1', event)
    print(json.dumps({'code': 'ok', 'actual': state['revision']}))
except KokoroError as error:
    print(json.dumps({'code': error.code, 'actual': error.details.get('actual')}))
"""

    def run_worker(event_id: str) -> dict:
        completed = subprocess.run(
            [sys.executable, "-c", worker, str(tmp_path), event_id],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return json.loads(completed.stdout)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run_worker, ["e1", "e2"]))

    assert sorted(results, key=lambda item: item["code"]) == [
        {"code": "STATE_REVISION_CONFLICT", "actual": 1},
        {"code": "ok", "actual": 1},
    ]


@pytest.mark.parametrize(
    "kind",
    [
        "invalid-json", "duplicate-key", "nonfinite", "oversize", "gap",
        "unknown-name", "duplicate-revision", "duplicate-id", "unknown-field",
    ],
)
def test_replay_rejects_corrupt_journal_deterministically(
    tmp_path: Path, kind: str
) -> None:
    store = started_store(tmp_path)
    store.apply("s1", event("e1", 0))
    journal = tmp_path / "events" / "s1"
    first = next(journal.glob("*.json"))
    if kind == "invalid-json":
        first.write_bytes(b'{"event":')
    elif kind == "duplicate-key":
        first.write_bytes(b'{"schema_version":"1.0","schema_version":"1.0"}')
    elif kind == "nonfinite":
        first.write_bytes(b'{"schema_version":"1.0","event":NaN}')
    elif kind == "oversize":
        first.write_bytes(b" " * (store_module.EVENT_RECORD_MAX_BYTES + 1))
    elif kind == "gap":
        first.rename(journal / "2-e1.json")
    elif kind == "unknown-name":
        (journal / "notes.txt").write_text("private path", encoding="utf-8")
    elif kind == "duplicate-revision":
        (journal / "1-e2.json").write_bytes(first.read_bytes())
    elif kind == "duplicate-id":
        second = read_json(first)
        second["event"]["expected_state_revision"] = 1
        store_module._atomic_write_json(second, journal / "2-e1.json")
    else:
        record = read_json(first)
        record["private"] = True
        store_module._atomic_write_json(record, first)

    with pytest.raises(KokoroError) as raised:
        store.replay("s1")

    assert raised.value.code == "STATE_JOURNAL_INVALID"
    assert raised.value.details == {}
    assert "private" not in str(raised.value)


def test_event_record_accepts_exact_per_record_byte_limit(tmp_path: Path) -> None:
    assert store_module.EVENT_RECORD_MAX_BYTES == 8 * 1024
    store = started_store(tmp_path)
    expected = store.apply("s1", event("e1", 0))
    record_path = next((tmp_path / "events" / "s1").glob("*.json"))
    contents = record_path.read_bytes()
    record_path.write_bytes(
        contents
        + b" " * (store_module.EVENT_RECORD_MAX_BYTES - len(contents))
    )

    assert record_path.stat().st_size == store_module.EVENT_RECORD_MAX_BYTES
    assert store.replay("s1") == expected


def test_maximal_valid_full_event_fits_per_record_byte_limit(
    tmp_path: Path,
) -> None:
    store = started_store(tmp_path)
    event_id = "e" * 128
    maximal_event = {
        "schema_version": "1.0",
        "artifact_id": f"event/{event_id}",
        "created_by": {"component": "kokoroarc", "version": "v" * 64},
        "event_id": event_id,
        "turn_id": "t" * 128,
        "origin": "verified_task_outcome",
        "novelty_key": "n" * 128,
        "expected_state_revision": 0,
        "evaluator_version": "v" * 128,
        "evidence": {"kind": "tool_result", "reference": "r" * 512},
        "confidence": 1.0,
        "effects": {
            "familiarity": 4.0,
            "trust": 4.0,
            "collaboration": 4.0,
            "tension": 4.0,
        },
    }

    expected = store.apply("s1", maximal_event)
    record_path = next((tmp_path / "events" / "s1").glob("*.json"))

    assert record_path.stat().st_size <= store_module.EVENT_RECORD_MAX_BYTES
    assert store.replay("s1") == expected


def test_journal_aggregate_byte_limit_accepts_exact_and_rejects_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = started_store(tmp_path)
    store.apply("s1", event("e1", 0))
    expected = store.apply("s1", event("e2", 1))
    journal = tmp_path / "events" / "s1"
    total_bytes = sum(path.stat().st_size for path in journal.glob("*.json"))

    monkeypatch.setattr(store_module, "JOURNAL_MAX_BYTES", total_bytes)
    assert store.replay("s1") == expected

    monkeypatch.setattr(store_module, "JOURNAL_MAX_BYTES", total_bytes - 1)
    with pytest.raises(KokoroError) as raised:
        store.replay("s1")

    assert raised.value.code == "STATE_JOURNAL_INVALID"
    assert raised.value.details == {}


def test_replay_rejects_redirected_journal_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = started_store(tmp_path)
    store.apply("s1", event("e1", 0))
    real_check = store_module._path_is_redirect

    def event_path_is_redirect(path: Path) -> bool:
        return path.parent.name == "s1" and path.suffix == ".json" or real_check(path)

    monkeypatch.setattr(store_module, "_path_is_redirect", event_path_is_redirect)

    with pytest.raises(KokoroError) as raised:
        store.replay("s1")

    assert raised.value.code == "SESSION_PATH_UNSAFE"


def test_replay_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = started_store(tmp_path)
    expected = store.apply("s1", event("e1", 0))
    monkeypatch.setattr(
        store_module,
        "_atomic_write_json",
        lambda _value, _target: pytest.fail("replay attempted to write"),
    )

    assert store.replay("s1") == expected


def test_restart_archives_history_and_starts_a_fresh_lifecycle(
    tmp_path: Path,
) -> None:
    store = started_store(tmp_path)
    store.apply("s1", event("e1", 0))
    store.end("s1")

    restarted = store.start("s1", "rin-aster", "1.0.0", HASH)

    assert restarted["state_revision"] == 0
    replayed = store.replay("s1")
    assert replayed["revision"] == 0
    assert replayed["applied_event_ids"] == []
    archived = list((tmp_path / "event-archives").glob("s1-*"))
    assert len(archived) == 1
    assert len(list(archived[0].glob("*.json"))) == 1


@pytest.mark.parametrize(
    ("failure_boundary", "recover_with", "restart_committed"),
    [
        ("marker", "load", False),
        ("archive", "load", False),
        ("state", "start", True),
        ("manifest", "load", False),
        ("cleanup", "load", True),
        ("none", "load", True),
    ],
)
def test_restart_intent_recovers_each_commit_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_boundary: str,
    recover_with: str,
    restart_committed: bool,
) -> None:
    store = started_store(tmp_path)
    old_state = store.apply("s1", event("e1", 0))
    old_manifest = store.end("s1")
    real_write = store_module._atomic_write_json
    real_replace = store_module.os.replace
    real_unlink = Path.unlink
    failed = False

    def maybe_fail_write(value: dict, target: Path) -> None:
        nonlocal failed
        boundary = None
        if target.parent.name == "restart-intents":
            boundary = "marker"
        elif target.parent.name == "state":
            boundary = "state"
        elif target.parent.name == "sessions" and value.get("active") is True:
            boundary = "manifest"
        if boundary == failure_boundary and not failed:
            failed = True
            raise OSError(f"injected {boundary} failure")
        real_write(value, target)

    def maybe_fail_replace(source: Path, target: Path) -> None:
        nonlocal failed
        if (
            failure_boundary == "archive"
            and not failed
            and source.parent.name == "events"
            and target.parent.name == "event-archives"
        ):
            failed = True
            raise OSError("injected archive failure")
        real_replace(source, target)

    def maybe_fail_unlink(path: Path, *args, **kwargs) -> None:
        nonlocal failed
        if (
            failure_boundary == "cleanup"
            and not failed
            and path.parent.name == "restart-intents"
        ):
            failed = True
            raise OSError("injected cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(store_module, "_atomic_write_json", maybe_fail_write)
    monkeypatch.setattr(store_module.os, "replace", maybe_fail_replace)
    monkeypatch.setattr(Path, "unlink", maybe_fail_unlink)

    if failure_boundary == "none":
        store.start("s1", "rin-aster", "1.0.0", HASH)
    else:
        with pytest.raises((KokoroError, OSError)):
            store.start("s1", "rin-aster", "1.0.0", HASH)
        assert failed is True

    fresh_store = SessionStore(tmp_path)
    if recover_with == "start":
        recovered_manifest = fresh_store.start(
            "s1", "rin-aster", "1.0.0", HASH
        )
    else:
        recovered_manifest = fresh_store.load("s1")

    assert not (tmp_path / "restart-intents" / "s1.json").exists()
    assert read_json(tmp_path / "state" / "s1.json")["revision"] == (
        0 if restart_committed else old_state["revision"]
    )
    assert recovered_manifest["active"] is restart_committed
    assert recovered_manifest["state_revision"] == (
        0 if restart_committed else old_manifest["state_revision"]
    )
    assert len(list((tmp_path / "event-archives").glob("s1-*"))) == (
        1 if restart_committed else 0
    )
    current_events = tmp_path / "events" / "s1"
    assert len(list(current_events.glob("*.json"))) == (
        0 if restart_committed else 1
    )


def test_corrupt_restart_intent_is_rejected_without_moving_history(
    tmp_path: Path,
) -> None:
    store = started_store(tmp_path)
    store.apply("s1", event("e1", 0))
    store.end("s1")
    journal_before = next((tmp_path / "events" / "s1").glob("*.json")).read_bytes()
    marker = tmp_path / "restart-intents" / "s1.json"
    marker.parent.mkdir()
    marker.write_bytes(b'{"schema_version":"1.0","private":true}')

    for operation in (
        lambda: store.load("s1"),
        lambda: store.start("s1", "rin-aster", "1.0.0", HASH),
        lambda: store.apply("s1", event("e2", 1)),
    ):
        with pytest.raises(KokoroError) as raised:
            operation()
        assert raised.value.code == "SESSION_RESTART_INVALID"
        assert raised.value.details == {}
        assert "private" not in str(raised.value)

    assert next((tmp_path / "events" / "s1").glob("*.json")).read_bytes() == journal_before
    assert not (tmp_path / "event-archives").exists()


def test_restart_recovery_sanitizes_inconsistent_current_journal_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = started_store(tmp_path)
    store.apply("s1", event("e1", 0))
    store.end("s1")
    real_write = store_module._atomic_write_json
    failed = False

    def fail_new_state(value: dict, target: Path) -> None:
        nonlocal failed
        if target.parent.name == "state" and not failed:
            failed = True
            raise OSError("injected state failure")
        real_write(value, target)

    monkeypatch.setattr(store_module, "_atomic_write_json", fail_new_state)
    with pytest.raises(OSError):
        store.start("s1", "rin-aster", "1.0.0", HASH)
    current = tmp_path / "events" / "s1"
    current.write_text("private path", encoding="utf-8")

    with pytest.raises(KokoroError) as raised:
        SessionStore(tmp_path).load("s1")

    assert raised.value.code == "SESSION_RESTART_INVALID"
    assert raised.value.details == {}
    assert "private" not in str(raised.value)
    assert current.is_file()
    assert (tmp_path / "event-archives" / "s1-1").is_dir()
    assert (tmp_path / "restart-intents" / "s1.json").is_file()


def test_end_recovers_committed_restart_before_deactivation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = started_store(tmp_path)
    store.apply("s1", event("e1", 0))
    store.end("s1")
    real_unlink = Path.unlink
    failed = False

    def fail_intent_cleanup(path: Path, *args, **kwargs) -> None:
        nonlocal failed
        if path.parent.name == "restart-intents" and not failed:
            failed = True
            raise OSError("injected cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_intent_cleanup)
    with pytest.raises(KokoroError):
        store.start("s1", "rin-aster", "1.0.0", HASH)

    ended = SessionStore(tmp_path).end("s1")

    assert ended["active"] is False
    assert ended["state_revision"] == 0
    assert not (tmp_path / "restart-intents" / "s1.json").exists()
    assert SessionStore(tmp_path).load("s1") == ended
    assert (tmp_path / "event-archives" / "s1-1").is_dir()
