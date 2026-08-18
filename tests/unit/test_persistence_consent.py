from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from kokoroarc.distribution.registry import resolve_install_scope
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.persistence._storage import open_persistence_scope
from kokoroarc.persistence.consent import (
    _require_active_consent,
    grant_consent,
    load_consent,
    revoke_consent,
)

from persistence_support import ConsentedRin, SCHEMAS, consented_rin, install_rin


def _assert_code(code: str, action: Callable[[], Any]) -> KokoroError:
    with pytest.raises(KokoroError) as caught:
        action()
    assert caught.value.code == code
    return caught.value


def _consent_root(
    data_root: Path,
    *,
    workspace_root: Path | None = None,
) -> Path:
    scope = open_persistence_scope(
        data_root,
        SCHEMAS,
        character_id="rin-aster",
        workspace_root=workspace_root,
    )
    return scope.character_root("consents")


def _history_payloads(root: Path) -> list[bytes]:
    history = root / "history"
    if not history.exists():
        return []
    return [path.read_bytes() for path in sorted(history.iterdir())]


def test_absent_consent_load_is_read_only(tmp_path: Path) -> None:
    data_root = tmp_path / "absent-data"

    assert load_consent(data_root, "rin-aster", SCHEMAS) is None
    assert not data_root.exists()


def test_grant_replace_revoke_regrant_has_exact_lifecycle_revisions(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    install_rin(root, rin_verified_release)

    first = grant_consent(
        root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        expected_revision=0,
    )
    repeated = grant_consent(
        root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        expected_revision=1,
    )
    replaced = grant_consent(
        root,
        "rin-aster",
        ["relationship_state", "mood_state"],
        SCHEMAS,
        expected_revision=1,
    )
    revoked = revoke_consent(
        root,
        "rin-aster",
        first["consent_id"],
        SCHEMAS,
        expected_revision=2,
    )
    regranted = grant_consent(
        root,
        "rin-aster",
        ["memory_references"],
        SCHEMAS,
        expected_revision=3,
    )

    assert repeated == first
    assert replaced["grant_revision"] == 2
    assert replaced["permissions"] == ["relationship_state", "mood_state"]
    assert revoked["grant_revision"] == 2
    assert revoked["revoked_revision"] == 3
    assert regranted["grant_revision"] == 4
    assert regranted["consent_id"] == first["consent_id"]
    assert regranted["permissions"] == ["memory_references"]
    assert load_consent(root, "rin-aster", SCHEMAS) == regranted

    consent_root = _consent_root(root)
    history = _history_payloads(consent_root)
    assert len(history) == 4
    assert consent_root.joinpath("current.json").read_bytes() == canonical_bytes(
        regranted
    )
    assert [
        (
            value["grant_revision"],
            value["revoked_revision"],
            value["status"],
        )
        for value in map(json.loads, history)
    ] == [
        (1, None, "active"),
        (2, None, "active"),
        (2, 3, "revoked"),
        (4, None, "active"),
    ]


def test_consent_id_is_stable_scope_character_digest(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    install_rin(root, rin_verified_release)

    granted = grant_consent(
        root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        expected_revision=0,
    )
    identity = {
        "scope": "global",
        "workspace_id": None,
        "namespace": "original",
        "character_id": "rin-aster",
    }

    assert granted["consent_id"] == (
        f"consent-{sha256(canonical_bytes(identity)).hexdigest()[:32]}"
    )


def test_grant_normalizes_permission_order_and_same_set_is_idempotent(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    install_rin(root, rin_verified_release)

    first = grant_consent(
        root,
        "rin-aster",
        ["memory_references", "mood_state", "relationship_state"],
        SCHEMAS,
        expected_revision=0,
    )
    repeated = grant_consent(
        root,
        "rin-aster",
        ["mood_state", "relationship_state", "memory_references"],
        SCHEMAS,
        expected_revision=1,
    )

    assert first["permissions"] == [
        "relationship_state",
        "mood_state",
        "memory_references",
    ]
    assert repeated == first
    assert len(_history_payloads(_consent_root(root))) == 1


@pytest.mark.parametrize(
    "permissions",
    [
        [],
        ["relationship_state", "relationship_state"],
        ["relationship_state", "unknown_permission"],
    ],
)
def test_grant_rejects_invalid_permission_sets_without_history(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    permissions: list[str],
) -> None:
    root = tmp_path / "data"
    install_rin(root, rin_verified_release)

    _assert_code(
        "PERSISTENCE_CONSENT_INVALID",
        lambda: grant_consent(
            root,
            "rin-aster",
            permissions,
            SCHEMAS,
            expected_revision=0,
        ),
    )
    assert not _consent_root(root).exists()


def test_grant_requires_exact_expected_revision(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    install_rin(root, rin_verified_release)
    grant_consent(
        root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        expected_revision=0,
    )

    _assert_code(
        "PERSISTENCE_CONSENT_CONFLICT",
        lambda: grant_consent(
            root,
            "rin-aster",
            ["mood_state"],
            SCHEMAS,
            expected_revision=0,
        ),
    )
    assert len(_history_payloads(_consent_root(root))) == 1


def test_revoke_requires_matching_id_and_is_idempotent(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    install_rin(root, rin_verified_release)
    granted = grant_consent(
        root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        expected_revision=0,
    )

    _assert_code(
        "PERSISTENCE_CONSENT_CONFLICT",
        lambda: revoke_consent(
            root,
            "rin-aster",
            "consent-wrong",
            SCHEMAS,
            expected_revision=1,
        ),
    )
    revoked = revoke_consent(
        root,
        "rin-aster",
        granted["consent_id"],
        SCHEMAS,
        expected_revision=1,
    )
    repeated = revoke_consent(
        root,
        "rin-aster",
        granted["consent_id"],
        SCHEMAS,
        expected_revision=2,
    )

    assert repeated == revoked
    assert len(_history_payloads(_consent_root(root))) == 2


def test_explicit_installation_version_and_ambiguous_omission(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    explicit_root = tmp_path / "explicit" / "data"
    installed = install_rin(explicit_root, rin_verified_release)
    granted = grant_consent(
        explicit_root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        version="1.0.0",
        expected_revision=0,
    )
    assert granted["installation"]["installation_id"] == installed[
        "installation_id"
    ]

    ambiguous_root = tmp_path / "ambiguous" / "data"
    install_rin(ambiguous_root, rin_verified_release)
    registry_path = ambiguous_root.joinpath(
        *resolve_install_scope().registry_relative_path.split("/")
    )
    registry = json.loads(registry_path.read_bytes())
    entry = registry["entries"]["original/rin-aster/1.0.0"]
    registry["entries"]["original/rin-aster/1.1.0"] = json.loads(
        canonical_bytes(entry)
    )
    registry["revision"] += 1
    registry_path.write_bytes(canonical_bytes(registry))

    _assert_code(
        "PERSISTENCE_INSTALLATION_STALE",
        lambda: grant_consent(
            ambiguous_root,
            "rin-aster",
            ["relationship_state"],
            SCHEMAS,
            expected_revision=0,
        ),
    )


def test_global_and_workspace_consents_are_isolated(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install_rin(data_root, rin_verified_release)
    install_rin(data_root, rin_verified_release, workspace_root=workspace)

    global_consent = grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        expected_revision=0,
    )
    workspace_consent = grant_consent(
        data_root,
        "rin-aster",
        ["memory_references"],
        SCHEMAS,
        workspace_root=workspace,
        expected_revision=0,
    )

    assert load_consent(data_root, "rin-aster", SCHEMAS) == global_consent
    assert (
        load_consent(
            data_root,
            "rin-aster",
            SCHEMAS,
            workspace_root=workspace,
        )
        == workspace_consent
    )
    assert global_consent["consent_id"] != workspace_consent["consent_id"]
    assert workspace_consent["scope"] == "workspace"


def test_active_consent_returns_exact_detached_binding(
    consented_rin: ConsentedRin,
) -> None:
    consent = consented_rin.consent
    active = _require_active_consent(
        consented_rin.data_root,
        "rin-aster",
        consent["consent_id"],
        consent["grant_revision"],
        "relationship_state",
        SCHEMAS,
    )

    assert active.consent == consent
    assert active.consent_payload == consented_rin.consent_payload
    assert active.binding == consent["installation"]
    assert active.compiled["character_id"] == "rin-aster"
    assert canonical_bytes(active.compiled) == active.compiled_payload
    assert active.permission == "relationship_state"
    active.consent["permissions"].clear()
    active.assert_clean()


@pytest.mark.parametrize(
    ("consent_id", "revision", "permission", "code"),
    [
        ("consent-wrong", 1, "relationship_state", "PERSISTENCE_CONSENT_CONFLICT"),
        (None, 99, "relationship_state", "PERSISTENCE_CONSENT_CONFLICT"),
        (None, 1, "unknown", "PERSISTENCE_PERMISSION_DENIED"),
    ],
)
def test_active_consent_rejects_wrong_binding_or_permission(
    consented_rin: ConsentedRin,
    consent_id: str | None,
    revision: int,
    permission: str,
    code: str,
) -> None:
    consent = consented_rin.consent

    _assert_code(
        code,
        lambda: _require_active_consent(
            consented_rin.data_root,
            "rin-aster",
            consent["consent_id"] if consent_id is None else consent_id,
            revision,
            permission,
            SCHEMAS,
        ),
    )


def test_active_consent_rejects_absent_wrong_scope_and_character(
    consented_rin: ConsentedRin,
    tmp_path: Path,
) -> None:
    consent = consented_rin.consent
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    for character_id, workspace_root in (
        ("other-character", None),
        ("rin-aster", workspace),
    ):
        _assert_code(
            "PERSISTENCE_CONSENT_NOT_FOUND",
            lambda character_id=character_id, workspace_root=workspace_root: (
                _require_active_consent(
                    consented_rin.data_root,
                    character_id,
                    consent["consent_id"],
                    consent["grant_revision"],
                    "relationship_state",
                    SCHEMAS,
                    workspace_root=workspace_root,
                )
            ),
        )


def test_active_consent_rejects_revoked_consent(
    consented_rin: ConsentedRin,
) -> None:
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
        lambda: _require_active_consent(
            consented_rin.data_root,
            "rin-aster",
            consent["consent_id"],
            consent["grant_revision"],
            "relationship_state",
            SCHEMAS,
        ),
    )


def test_active_consent_rejects_permission_not_in_grant(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    install_rin(data_root, rin_verified_release)
    consent = grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        expected_revision=0,
    )

    _assert_code(
        "PERSISTENCE_PERMISSION_DENIED",
        lambda: _require_active_consent(
            data_root,
            "rin-aster",
            consent["consent_id"],
            consent["grant_revision"],
            "mood_state",
            SCHEMAS,
        ),
    )


@pytest.mark.parametrize(
    "changed_member",
    ["registry", "compiled", "installed-tree"],
)
def test_active_consent_detects_changed_installation_bytes(
    consented_rin: ConsentedRin,
    changed_member: str,
) -> None:
    consent = consented_rin.consent
    active = _require_active_consent(
        consented_rin.data_root,
        "rin-aster",
        consent["consent_id"],
        consent["grant_revision"],
        "relationship_state",
        SCHEMAS,
    )
    registry_path = consented_rin.data_root.joinpath(
        *resolve_install_scope().registry_relative_path.split("/")
    )
    registry = json.loads(registry_path.read_bytes())
    entry = registry["entries"]["original/rin-aster/1.0.0"]
    installed_root = (
        consented_rin.data_root / "installed" / entry["relative_path"]
    )
    changed_path = {
        "registry": registry_path,
        "compiled": installed_root / "pack" / "compiled.json",
        "installed-tree": (
            installed_root / "release" / "review-attestation.json"
        ),
    }[changed_member]
    changed_path.write_bytes(changed_path.read_bytes() + b"\n")

    _assert_code("PERSISTENCE_INSTALLATION_STALE", active.assert_clean)


def test_active_consent_detects_uninstalled_archive(
    consented_rin: ConsentedRin,
) -> None:
    consent = consented_rin.consent
    archive = (
        consented_rin.data_root
        / "archives"
        / f"{consent['installation']['archive_sha256']}.karc"
    )
    archive.rename(archive.with_suffix(".displaced"))

    _assert_code(
        "PERSISTENCE_INSTALLATION_STALE",
        lambda: _require_active_consent(
            consented_rin.data_root,
            "rin-aster",
            consent["consent_id"],
            consent["grant_revision"],
            "relationship_state",
            SCHEMAS,
        ),
    )


def test_active_consent_detects_changed_consent_bytes(
    consented_rin: ConsentedRin,
) -> None:
    consent = consented_rin.consent
    active = _require_active_consent(
        consented_rin.data_root,
        "rin-aster",
        consent["consent_id"],
        consent["grant_revision"],
        "relationship_state",
        SCHEMAS,
    )
    current = _consent_root(consented_rin.data_root) / "current.json"
    current.write_bytes(current.read_bytes() + b"\n")

    _assert_code("PERSISTENCE_CONSENT_INVALID", active.assert_clean)
