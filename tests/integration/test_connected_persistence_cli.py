from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any, Callable

import pytest

import kokorox.cli as cli
from kokorox.distribution import remove_installed_pack
from kokorox.persistence.state import (
    apply_persistent_relationship_event,
    replay_persistent_state,
)
from kokorox.schemas import SchemaRegistry

from persistence_support import (
    ConsentedRin,
    consented_rin,
    install_rin,
    install_rin_successor,
    interaction_event,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
__all__ = ["consented_rin"]


@pytest.fixture
def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Callable[..., tuple[int, dict[str, Any]]]:
    def invoke(data_root: Path, *arguments: str) -> tuple[int, dict[str, Any]]:
        monkeypatch.setenv("KOKOROX_DATA_DIR", str(data_root))
        code = cli.main([*arguments, "--json"])
        captured = capsys.readouterr()
        assert captured.err == ""
        return code, json.loads(captured.out)

    return invoke


def _ok(result: tuple[int, dict[str, Any]]) -> dict[str, Any]:
    code, body = result
    assert code == 0, body
    return body


def _event_file(tmp_path: Path, event_id: str, revision: int) -> str:
    path = tmp_path / f"{event_id}.json"
    path.write_text(json.dumps(interaction_event(event_id, revision)), encoding="utf-8")
    return str(path)


def _context(run: Callable[..., Any], data_root: Path, session: str) -> tuple[int, dict[str, Any]]:
    return run(
        data_root,
        "runtime",
        "context",
        "--session",
        session,
        "--locale",
        "zh-CN",
        "--scenario",
        "debugging",
    )


def test_a_consented_session_continues_where_the_last_one_left_off(
    consented_rin: ConsentedRin,
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    """Granted, applied, and gone: the next session started at trust 0."""

    data_root = consented_rin.data_root
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster"))

    first = _ok(run(data_root, "session", "start", "--session", "per1"))
    assert first["relationship_state"] == "durable"
    event = _event_file(tmp_path, "durable-event-1", 0)
    applied = _ok(run(data_root, "state", "apply", "--session", "per1", "--event", event))
    assert applied["relationship_state"] == "durable"
    assert applied["state"]["revision"] == 1
    trust = applied["state"]["dimensions"]["trust"]
    assert trust > 0
    # The same event again is recorded once, as a session-local apply would be.
    again = _ok(run(data_root, "state", "apply", "--session", "per1", "--event", event))
    assert again["state"] == applied["state"]
    _ok(run(data_root, "session", "end", "--session", "per1"))

    _ok(run(data_root, "session", "start", "--session", "per2"))
    context = _ok(_context(run, data_root, "per2"))

    assert context["relationship_state"] == "durable"
    assert context["context"]["state"]["revision"] == 1
    assert context["context"]["state"]["dimensions"]["trust"] == trust
    retained = replay_persistent_state(data_root, "rin-aster", SCHEMAS)
    assert retained is not None
    assert retained["relationship"] == applied["state"]


def test_without_consent_a_session_keeps_its_state_to_itself(
    rin_verified_release: dict[str, Any],
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    install_rin(data_root, rin_verified_release)
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster"))

    started = _ok(run(data_root, "session", "start", "--session", "local"))
    applied = _ok(
        run(
            data_root,
            "state",
            "apply",
            "--session",
            "local",
            "--event",
            _event_file(tmp_path, "local-event-1", 0),
        )
    )

    assert started["relationship_state"] == "session"
    assert applied["state"]["revision"] == 1
    assert "relationship_state" not in applied
    assert replay_persistent_state(data_root, "rin-aster", SCHEMAS) is None
    binding = json.loads((data_root / "session-bindings" / "local.json").read_text(encoding="utf-8"))
    assert binding["relationship_state"] == "session"
    assert binding["resolved_from"] == "global_default"


def test_revoking_consent_lets_a_running_session_keep_answering(
    consented_rin: ConsentedRin,
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    data_root = consented_rin.data_root
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster"))
    _ok(run(data_root, "session", "start", "--session", "revoked"))
    _ok(run(data_root, "consent", "revoke", "--character", "rin-aster"))

    code, body = run(
        data_root,
        "state",
        "apply",
        "--session",
        "revoked",
        "--event",
        _event_file(tmp_path, "revoked-event-1", 0),
    )

    assert code == 0, body
    assert body["relationship_state"] == "session"
    assert [item["cause"] for item in body["advisories"]] == ["PERSISTENCE_CONSENT_REVOKED"]
    assert body["state"]["revision"] == 1
    context = _ok(_context(run, data_root, "revoked"))
    assert context["relationship_state"] == "session"
    assert context["context"]["state"]["revision"] == 1
    assert context["advisories"][0]["code"] == "PERSISTENCE_SESSION_DEGRADED"
    assert replay_persistent_state(data_root, "rin-aster", SCHEMAS) is None


def test_an_upgrade_migrates_retained_state_through_the_cli(
    consented_rin: ConsentedRin,
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
) -> None:
    """The refusal named a migration no command could perform."""

    data_root = consented_rin.data_root
    source = apply_persistent_relationship_event(
        data_root,
        "rin-aster",
        interaction_event("before-upgrade-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="before-upgrade-operation-1",
    )
    install_rin_successor(consented_rin, tmp_path, verified_release_factory)
    _ok(
        run(
            data_root,
            "config",
            "default",
            "set",
            "--character",
            "rin-aster",
            "--version",
            "1.1.0",
        )
    )
    started = _ok(run(data_root, "session", "start", "--session", "upgraded"))
    # Bound to the upgrade, but its retained state needs migrating first.
    assert started["relationship_state"] == "session"
    assert [(item["code"], item.get("cause")) for item in started["advisories"]] == [
        ("SESSION_WORKSPACE_NOT_CONSULTED", None),
        ("PERSISTENCE_SESSION_DEGRADED", "PERSISTENCE_STATE_MIGRATION_REQUIRED"),
    ]

    degraded = _ok(_context(run, data_root, "upgraded"))
    assert degraded["relationship_state"] == "session"
    assert [item["cause"] for item in degraded["advisories"]] == [
        "PERSISTENCE_STATE_MIGRATION_REQUIRED"
    ]

    preview = _ok(
        run(
            data_root,
            "state",
            "migrate",
            "--character",
            "rin-aster",
            "--mood-strategy",
            "preserve_identical_contract",
            "--dry-run",
        )
    )
    assert preview["dry_run"] is True
    SCHEMAS.validate("state-migration-plan", preview["plan"])
    migrated = _ok(
        run(
            data_root,
            "state",
            "migrate",
            "--character",
            "rin-aster",
            "--mood-strategy",
            "preserve_identical_contract",
        )
    )
    assert migrated["plan"] == preview["plan"]
    assert migrated["state"]["relationship"] == source["relationship"]

    context = _ok(_context(run, data_root, "upgraded"))
    assert context["context"]["state"]["revision"] == source["relationship"]["revision"]


def test_a_compiled_path_session_never_reaches_retained_state(
    consented_rin: ConsentedRin,
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    data_root = consented_rin.data_root
    compiled = _ok(run(data_root, "pack", "compile", "characters/original/rin-aster"))

    started = _ok(
        run(
            data_root,
            "session",
            "start",
            "--character",
            compiled["path"],
            "--session",
            "compiled",
        )
    )

    assert started["relationship_state"] == "session"


def test_a_consent_for_a_removed_version_never_blocks_a_new_session(
    consented_rin: ConsentedRin,
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
) -> None:
    """Revoke, remove 1.0.0, install 1.1.0: starting a session must still work."""

    data_root = consented_rin.data_root
    _ok(run(data_root, "consent", "revoke", "--character", "rin-aster"))
    remove_installed_pack(data_root, "original", "rin-aster", "1.0.0", SCHEMAS)
    source_root = tmp_path / "rin-aster-1.1.0"
    shutil.copytree(Path("characters/original/rin-aster"), source_root)
    manifest = source_root / "character.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "character_version: 1.0.0", "character_version: 1.1.0"
        ),
        encoding="utf-8",
    )
    request = json.loads(
        Path("tests/fixtures/authoring/original-request.json").read_text(encoding="utf-8")
    )
    request["character_version"] = "1.1.0"
    install_rin(
        data_root,
        verified_release_factory(source_root, request, visibility="private"),
        source_root=source_root,
    )
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster"))

    started = _ok(run(data_root, "session", "start", "--session", "after-removal"))

    assert started["relationship_state"] == "session"
    assert [item["code"] for item in started["advisories"]] == [
        "SESSION_WORKSPACE_NOT_CONSULTED",
        "PERSISTENCE_CONSENT_OTHER_INSTALLATION",
    ]


def test_a_workspace_consent_continues_a_workspace_session(
    rin_verified_release: dict[str, Any],
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install_rin(data_root, rin_verified_release, workspace_root=workspace)
    scope = ("--workspace", str(workspace))
    _ok(
        run(
            data_root,
            "consent",
            "grant",
            "--character",
            "rin-aster",
            "--scope",
            "workspace",
            *scope,
            "--permissions",
            "relationship_state",
        )
    )
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster", *scope))

    started = _ok(run(data_root, "session", "start", "--session", "ws1", *scope))
    event = _event_file(tmp_path, "workspace-event-1", 0)
    preview = _ok(run(data_root, "state", "preview", "--session", "ws1", "--event", event))
    applied = _ok(run(data_root, "state", "apply", "--session", "ws1", "--event", event))
    _ok(run(data_root, "session", "end", "--session", "ws1"))
    _ok(run(data_root, "session", "start", "--session", "ws2", *scope))
    context = _ok(_context(run, data_root, "ws2"))

    assert started["resolved_from"] == "workspace_default"
    assert started["relationship_state"] == "durable"
    assert preview["relationship_state"] == "durable"
    assert preview["state"] == applied["state"]
    assert context["context"]["state"]["revision"] == 1
    retained = replay_persistent_state(
        data_root, "rin-aster", SCHEMAS, workspace_root=workspace
    )
    assert retained is not None
    assert retained["relationship"] == applied["state"]


def _grant(run: Callable[..., Any], data_root: Path, permissions: str) -> dict[str, Any]:
    return _ok(
        run(
            data_root,
            "consent",
            "grant",
            "--character",
            "rin-aster",
            "--scope",
            "global",
            "--permissions",
            permissions,
        )
    )


def test_adding_a_permission_keeps_the_character_s_memory(
    consented_rin: ConsentedRin,
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    """The README's own way to add a permission left every durable session mute."""

    data_root = consented_rin.data_root
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster"))
    _ok(run(data_root, "session", "start", "--session", "w1"))
    applied = _ok(
        run(
            data_root,
            "state",
            "apply",
            "--session",
            "w1",
            "--event",
            _event_file(tmp_path, "regrant-event-1", 0),
        )
    )
    _ok(run(data_root, "session", "end", "--session", "w1"))
    _grant(run, data_root, "relationship_state,memory_references")

    _ok(run(data_root, "session", "start", "--session", "w2"))
    context = _ok(_context(run, data_root, "w2"))
    second = _ok(
        run(
            data_root,
            "state",
            "apply",
            "--session",
            "w2",
            "--event",
            _event_file(tmp_path, "regrant-event-2", 1),
        )
    )

    assert context["relationship_state"] == "durable"
    assert context["context"]["state"]["revision"] == 1
    assert context["context"]["state"]["dimensions"] == applied["state"]["dimensions"]
    assert second["state"]["revision"] == 2


def test_granting_again_after_a_revoke_reattaches_retained_state(
    consented_rin: ConsentedRin,
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    data_root = consented_rin.data_root
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster"))
    _ok(run(data_root, "session", "start", "--session", "r1"))
    _ok(
        run(
            data_root,
            "state",
            "apply",
            "--session",
            "r1",
            "--event",
            _event_file(tmp_path, "reattach-event-1", 0),
        )
    )
    _ok(run(data_root, "session", "end", "--session", "r1"))
    _ok(run(data_root, "consent", "revoke", "--character", "rin-aster"))
    _grant(run, data_root, "relationship_state")

    _ok(run(data_root, "session", "start", "--session", "r2"))
    context = _ok(_context(run, data_root, "r2"))

    assert context["relationship_state"] == "durable"
    assert context["context"]["state"]["revision"] == 1


def test_a_newer_version_granted_mid_session_leaves_the_session_answering(
    consented_rin: ConsentedRin,
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
) -> None:
    data_root = consented_rin.data_root
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster"))
    _ok(run(data_root, "session", "start", "--session", "live-old"))
    install_rin_successor(consented_rin, tmp_path, verified_release_factory)

    context = _ok(_context(run, data_root, "live-old"))

    assert context["relationship_state"] == "session"
    assert [item["cause"] for item in context["advisories"]] == [
        "PERSISTENCE_INSTALLATION_STALE"
    ]


def test_a_workspace_alone_scopes_a_grant_and_session_show_reports_durable_state(
    rin_verified_release: dict[str, Any],
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install_rin(data_root, rin_verified_release, workspace_root=workspace)
    scope = ("--workspace", str(workspace))
    granted = _ok(
        run(
            data_root,
            "consent",
            "grant",
            "--character",
            "rin-aster",
            *scope,
            "--permissions",
            "relationship_state",
        )
    )
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster", *scope))
    started = _ok(run(data_root, "session", "start", "--session", "shown", *scope))
    _ok(
        run(
            data_root,
            "state",
            "apply",
            "--session",
            "shown",
            "--event",
            _event_file(tmp_path, "shown-event-1", 0),
        )
    )

    shown = _ok(run(data_root, "session", "show", "--session", "shown"))

    assert granted["consent"]["scope"] == "workspace"
    assert started["source_hash"] == started["session"]["compiled_pack_hash"]
    assert shown["session"]["state_revision"] == 0
    assert shown["relationship_state"] == "durable"
    assert shown["relationship_revision"] == 1


def test_an_export_with_no_consent_says_nothing_was_granted(
    rin_verified_release: dict[str, Any],
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    install_rin(data_root, rin_verified_release)

    code, body = run(
        data_root,
        "state",
        "export",
        "--character",
        "rin-aster",
        "--out",
        str(tmp_path / "export.json"),
    )

    assert code != 0
    assert body["error"]["code"] == "PERSISTENCE_CONSENT_NOT_FOUND"


def test_removal_is_not_blocked_by_sessions_of_other_installations(
    rin_verified_release: dict[str, Any],
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    """Another workspace's session and a compiled-path session blocked a removal."""

    data_root = tmp_path / "data"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    install_rin(data_root, rin_verified_release, workspace_root=first)
    shutil.copy(data_root.parent / "rin-workspace.karc", tmp_path / "rin-second.karc")
    _ok(run(data_root, "pack", "install", str(tmp_path / "rin-second.karc"), "--workspace", str(second)))
    for workspace in (first, second):
        _ok(run(data_root, "config", "default", "set", "--character", "rin-aster", "--workspace", str(workspace)))
    _ok(run(data_root, "session", "start", "--session", "in-second", "--workspace", str(second)))
    compiled = _ok(run(data_root, "pack", "compile", "characters/original/rin-aster"))
    _ok(run(data_root, "session", "start", "--character", compiled["path"], "--session", "from-path"))
    for workspace in (first, second):
        _ok(run(data_root, "config", "default", "clear", "--workspace", str(workspace)))

    removed = _ok(
        run(
            data_root,
            "pack",
            "remove",
            "rin-aster",
            "--version",
            "1.0.0",
            "--workspace",
            str(first),
        )
    )
    code, blocked = run(
        data_root,
        "pack",
        "remove",
        "rin-aster",
        "--version",
        "1.0.0",
        "--workspace",
        str(second),
    )

    assert removed["ok"] is True
    assert code != 0
    assert blocked["error"]["details"]["sessions"] == ["in-second"]


def test_a_session_that_wrote_while_degraded_keeps_its_events_after_a_regrant(
    consented_rin: ConsentedRin,
    run: Callable[..., tuple[int, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    """After the regrant the session jumped back to retained state and the event was gone."""

    data_root = consented_rin.data_root
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster"))
    _ok(run(data_root, "session", "start", "--session", "kept"))
    _ok(run(data_root, "consent", "revoke", "--character", "rin-aster"))
    degraded = _ok(
        run(
            data_root,
            "state",
            "apply",
            "--session",
            "kept",
            "--event",
            _event_file(tmp_path, "kept-event-1", 0),
        )
    )
    _grant(run, data_root, "relationship_state")

    context = _ok(_context(run, data_root, "kept"))

    assert degraded["relationship_state"] == "session"
    assert context["relationship_state"] == "session"
    assert context["context"]["state"]["revision"] == 1
    assert [item["cause"] for item in context["advisories"]] == ["SESSION_EVENTS_KEPT"]
    fresh = _ok(run(data_root, "session", "start", "--session", "after-kept"))
    assert fresh["relationship_state"] == "durable"


def test_a_session_that_wrote_nothing_while_degraded_reconnects(
    consented_rin: ConsentedRin,
    run: Callable[..., tuple[int, dict[str, Any]]],
) -> None:
    data_root = consented_rin.data_root
    _ok(run(data_root, "config", "default", "set", "--character", "rin-aster"))
    _ok(run(data_root, "session", "start", "--session", "quiet"))
    _ok(run(data_root, "consent", "revoke", "--character", "rin-aster"))
    assert _ok(_context(run, data_root, "quiet"))["relationship_state"] == "session"
    _grant(run, data_root, "relationship_state")

    context = _ok(_context(run, data_root, "quiet"))

    assert context["relationship_state"] == "durable"
    assert context["advisories"] == []
