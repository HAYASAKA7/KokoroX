from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Callable

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.persistence._storage import PersistenceLimits
from kokoroarc.persistence.consent import grant_consent, revoke_consent
from kokoroarc.persistence.state import (
    apply_persistent_relationship_event,
    load_persistent_state,
    replay_persistent_state,
)
from kokoroarc.state import transitions
import kokoroarc.persistence.state as persistent_state_module

from persistence_support import (
    ConsentedRin,
    SCHEMAS,
    consented_rin,
    install_rin,
    interaction_event,
)


def _assert_code(code: str, action: Callable[[], Any]) -> KokoroError:
    with pytest.raises(KokoroError) as caught:
        action()
    assert caught.value.code == code
    return caught.value


def _state_root(consented: ConsentedRin) -> Path:
    return (
        consented.data_root
        / "persistent-state"
        / "global"
        / "original"
        / "rin-aster"
    )


def _generation_root(consented: ConsentedRin) -> Path:
    root = _state_root(consented)
    pointer = json.loads(root.joinpath("current.json").read_bytes())
    return root / "generations" / pointer["generation_id"]


def _apply(
    consented: ConsentedRin,
    event_id: str,
    revision: int,
    *,
    operation_id: str | None = None,
    trust: float = 2.0,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    return apply_persistent_relationship_event(
        consented.data_root,
        "rin-aster",
        interaction_event(event_id, revision, trust=trust),
        consented.consent["consent_id"],
        consented.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=revision,
        operation_id=operation_id or f"relationship-operation-{revision + 1}",
        limits=limits,
    )


def _process_relationship_apply(
    arguments: tuple[Path, str, int, int],
) -> tuple[str, int | str]:
    data_root, consent_id, consent_revision, index = arguments
    try:
        result = apply_persistent_relationship_event(
            data_root,
            "rin-aster",
            interaction_event(f"event-{index}", 0),
            consent_id,
            consent_revision,
            SCHEMAS,
            expected_state_revision=0,
            operation_id=f"relationship-operation-{index}",
        )
        return "ok", result["revision"]
    except KokoroError as error:
        return "error", error.code


def test_absent_persistent_state_load_and_replay_are_read_only(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "absent-data"

    assert load_persistent_state(data_root, "rin-aster", SCHEMAS) is None
    assert replay_persistent_state(data_root, "rin-aster", SCHEMAS) is None
    assert not data_root.exists()


def test_relationship_apply_is_outer_cas_idempotent_and_replayable(
    consented_rin: ConsentedRin,
) -> None:
    first = _apply(consented_rin, "event-1", 0)
    duplicate = _apply(consented_rin, "event-1", 0)

    assert first["revision"] == 1
    assert first["relationship"]["revision"] == 1
    assert first["relationship"]["dimensions"]["trust"] == 2.0
    assert duplicate == first
    assert duplicate is not first
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == first
    assert load_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == first


def test_relationship_accepts_the_declared_generic_mapping_input(
    consented_rin: ConsentedRin,
) -> None:
    event = MappingProxyType(interaction_event("event-1", 0))

    state = apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        event,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="relationship-operation-1",
    )

    assert state["revision"] == 1
    assert load_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == state


def test_relationship_write_requires_its_exact_permission(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    install_rin(data_root, rin_verified_release)
    consent = grant_consent(
        data_root,
        "rin-aster",
        ["mood_state"],
        SCHEMAS,
        expected_revision=0,
    )

    _assert_code(
        "PERSISTENCE_PERMISSION_DENIED",
        lambda: apply_persistent_relationship_event(
            data_root,
            "rin-aster",
            interaction_event("event-1", 0),
            consent["consent_id"],
            consent["grant_revision"],
            SCHEMAS,
            expected_state_revision=0,
            operation_id="relationship-operation-1",
        ),
    )


def test_revoked_consent_blocks_relationship_write(
    consented_rin: ConsentedRin,
) -> None:
    persisted = _apply(consented_rin, "event-1", 0)
    consent = consented_rin.consent
    revoke_consent(
        consented_rin.data_root,
        "rin-aster",
        consent["consent_id"],
        SCHEMAS,
        expected_revision=consent["grant_revision"],
    )

    _assert_code(
        "PERSISTENCE_CONSENT_REVOKED",
        lambda: _apply(consented_rin, "event-2", 1),
    )
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == persisted


def test_workspace_relationship_state_is_isolated_from_global_scope(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    install_rin(
        data_root,
        rin_verified_release,
        workspace_root=workspace_root,
    )
    consent = grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        workspace_root=workspace_root,
        expected_revision=0,
    )

    state = apply_persistent_relationship_event(
        data_root,
        "rin-aster",
        interaction_event("event-1", 0),
        consent["consent_id"],
        consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="relationship-operation-1",
        workspace_root=workspace_root,
    )

    assert state["scope"] == "workspace"
    assert state["workspace_id"] is not None
    assert load_persistent_state(data_root, "rin-aster", SCHEMAS) is None
    assert load_persistent_state(
        data_root,
        "rin-aster",
        SCHEMAS,
        workspace_root=workspace_root,
    ) == state


def test_outer_and_embedded_relationship_revisions_are_independent_cas(
    consented_rin: ConsentedRin,
) -> None:
    _assert_code(
        "PERSISTENCE_STATE_REVISION_CONFLICT",
        lambda: apply_persistent_relationship_event(
            consented_rin.data_root,
            "rin-aster",
            interaction_event("event-1", 1),
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
            expected_state_revision=0,
            operation_id="relationship-operation-1",
        ),
    )

    _apply(consented_rin, "event-1", 0)
    _assert_code(
        "PERSISTENCE_STATE_REVISION_CONFLICT",
        lambda: apply_persistent_relationship_event(
            consented_rin.data_root,
            "rin-aster",
            interaction_event("event-2", 1),
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
            expected_state_revision=0,
            operation_id="relationship-operation-2",
        ),
    )


def test_reused_operation_or_event_id_requires_exact_input_bytes(
    consented_rin: ConsentedRin,
) -> None:
    _apply(consented_rin, "event-1", 0)

    _assert_code(
        "PERSISTENCE_STATE_REVISION_CONFLICT",
        lambda: _apply(consented_rin, "event-1", 0, trust=3.0),
    )
    _assert_code(
        "PERSISTENCE_STATE_REVISION_CONFLICT",
        lambda: _apply(
            consented_rin,
            "event-1",
            1,
            operation_id="relationship-operation-2",
            trust=3.0,
        ),
    )


def test_journal_records_exact_compiled_growth_parameters(
    consented_rin: ConsentedRin,
) -> None:
    _apply(consented_rin, "event-1", 0)
    event_file = next(_generation_root(consented_rin).joinpath("events").iterdir())
    record = json.loads(event_file.read_bytes())

    assert record["payload"]["max_delta"] == 4.0
    assert record["payload"]["repetition_window"] == 3


def test_replay_dispatches_frozen_relationship_v1(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _apply(consented_rin, "event-1", 0)

    def forbidden_current_alias(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("replay must not use the current transition alias")

    monkeypatch.setattr(transitions, "apply_event", forbidden_current_alias)

    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == expected


def test_replay_rejects_event_gap_and_duplicate_revision(
    consented_rin: ConsentedRin,
) -> None:
    _apply(consented_rin, "event-1", 0)
    _apply(consented_rin, "event-2", 1)
    events = sorted(_generation_root(consented_rin).joinpath("events").iterdir())
    first_payload = events[0].read_bytes()
    events[0].unlink()

    _assert_code(
        "PERSISTENCE_STATE_JOURNAL_INVALID",
        lambda: replay_persistent_state(
            consented_rin.data_root,
            "rin-aster",
            SCHEMAS,
        ),
    )

    events[0].write_bytes(first_payload)
    duplicate = events[0].with_name("0000000002-" + "f" * 32 + ".json")
    duplicate.write_bytes(first_payload)
    _assert_code(
        "PERSISTENCE_STATE_JOURNAL_INVALID",
        lambda: replay_persistent_state(
            consented_rin.data_root,
            "rin-aster",
            SCHEMAS,
        ),
    )


def test_locked_apply_repairs_stale_projection_before_next_event(
    consented_rin: ConsentedRin,
) -> None:
    first = _apply(consented_rin, "event-1", 0)
    projection = _generation_root(consented_rin) / "state.json"
    stale = deepcopy(first)
    stale["relationship"]["dimensions"]["trust"] = 0.0
    projection.write_bytes(canonical_bytes(stale))

    _assert_code(
        "PERSISTENCE_STATE_JOURNAL_INVALID",
        lambda: replay_persistent_state(
            consented_rin.data_root,
            "rin-aster",
            SCHEMAS,
        ),
    )

    second = _apply(consented_rin, "event-2", 1)
    assert second["revision"] == 2
    assert second["relationship"]["dimensions"]["trust"] == 4.0
    assert json.loads(projection.read_bytes()) == second


def test_read_only_replay_reconstructs_but_does_not_write_missing_projection(
    consented_rin: ConsentedRin,
) -> None:
    first = _apply(consented_rin, "event-1", 0)
    projection = _generation_root(consented_rin) / "state.json"
    projection.unlink()

    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == first
    assert not projection.exists()

    second = _apply(consented_rin, "event-2", 1)
    assert json.loads(projection.read_bytes()) == second


def test_event_capacity_is_enforced_before_publication(
    consented_rin: ConsentedRin,
) -> None:
    limits = PersistenceLimits(max_state_events=1)
    _apply(consented_rin, "event-1", 0, limits=limits)

    _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: _apply(consented_rin, "event-2", 1, limits=limits),
    )
    assert len(list(_generation_root(consented_rin).joinpath("events").iterdir())) == 1


def test_event_names_are_fixed_width_digests_not_caller_ids(
    consented_rin: ConsentedRin,
) -> None:
    operation_id = "private-operation-description"
    _apply(
        consented_rin,
        "private-event-description",
        0,
        operation_id=operation_id,
    )
    names = [
        path.name
        for path in _generation_root(consented_rin).joinpath("events").iterdir()
    ]

    assert len(names) == 1
    assert re.fullmatch(r"0000000001-[a-f0-9]{32}\.json", names[0])
    assert operation_id not in names[0]
    assert "private-event-description" not in names[0]


@pytest.mark.parametrize("writer_name", ["_write_projection", "_write_pointer"])
def test_committed_event_is_repaired_after_projection_or_pointer_failure(
    consented_rin: ConsentedRin,
    monkeypatch: pytest.MonkeyPatch,
    writer_name: str,
) -> None:
    real_write = getattr(persistent_state_module, writer_name)
    failed = False

    def fail_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal failed
        if not failed:
            failed = True
            raise KokoroError(
                "PERSISTENCE_WRITE_FAILED",
                "injected projection failure",
            )
        return real_write(*args, **kwargs)

    monkeypatch.setattr(persistent_state_module, writer_name, fail_once)
    error = _assert_code(
        "PERSISTENCE_STATE_WRITE_FAILED",
        lambda: _apply(consented_rin, "event-1", 0),
    )
    assert error.details["record_state"] == "committed"

    second = _apply(consented_rin, "event-2", 1)
    assert second["revision"] == 2
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == second


def test_concurrent_process_relationship_cas_allows_only_one_revision(
    consented_rin: ConsentedRin,
) -> None:
    consent = consented_rin.consent
    arguments = [
        (
            consented_rin.data_root,
            consent["consent_id"],
            consent["grant_revision"],
            index,
        )
        for index in (1, 2)
    ]
    with ProcessPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(_process_relationship_apply, arguments))

    assert outcomes.count(("ok", 1)) == 1
    assert sum(item[0] == "error" for item in outcomes) == 1
    assert outcomes[0][1] in {
        1,
        "PERSISTENCE_LOCKED",
        "PERSISTENCE_STATE_REVISION_CONFLICT",
    }
    assert outcomes[1][1] in {
        1,
        "PERSISTENCE_LOCKED",
        "PERSISTENCE_STATE_REVISION_CONFLICT",
    }
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )["revision"] == 1
