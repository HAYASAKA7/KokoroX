from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.persistence._storage import PersistenceLimits
from kokoroarc.persistence.consent import grant_consent, revoke_consent
from kokoroarc.persistence.memory import (
    add_memory_reference,
    list_memory_references,
    remove_memory_reference,
)

from persistence_support import (
    ConsentedRin,
    SCHEMAS,
    approved_memory_inputs,
    consented_rin,
    install_rin,
)


def _assert_code(code: str, action: Callable[[], Any]) -> KokoroError:
    with pytest.raises(KokoroError) as caught:
        action()
    assert caught.value.code == code
    return caught.value


def _memory_root(
    data_root: Path,
    *,
    workspace_id: str | None = None,
) -> Path:
    if workspace_id is None:
        scope_parts = ("global",)
    else:
        scope_parts = ("workspaces", workspace_id)
    return data_root.joinpath(
        "memory-references",
        *scope_parts,
        "original",
        "rin-aster",
    )


def _add(
    consented: ConsentedRin,
    *,
    host_memory_id: str = "host-memory-preference-01",
    summary: str = "The user approved concise technical explanations.",
    localized_summaries: dict[str, str] | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    localized = (
        {"en-US": summary}
        if localized_summaries is None
        else localized_summaries
    )
    return add_memory_reference(
        consented.data_root,
        "rin-aster",
        host_memory_id,
        summary,
        localized,
        consented.consent["consent_id"],
        consented.consent["grant_revision"],
        SCHEMAS,
        workspace_root=consented.workspace_root,
        limits=limits,
    )


def test_absent_memory_list_is_read_only(tmp_path: Path) -> None:
    data_root = tmp_path / "absent-data"

    assert list_memory_references(data_root, "rin-aster", SCHEMAS) == ()
    assert not data_root.exists()


def test_add_list_and_remove_reference_never_embeds_host_memory(
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
    repeated = add_memory_reference(
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
    assert repeated == added
    assert [item.reference for item in listed] == [added]
    assert listed[0].active_consent_generation is True
    assert "content" not in added

    removed = remove_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        added["memory_reference_id"],
        consented_rin.consent["consent_id"],
        SCHEMAS,
        identifier_kind="memory_reference_id",
    )
    assert removed.removed is True
    assert removed.memory_reference_id == added["memory_reference_id"]
    assert list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == ()


def test_memory_id_content_hash_locale_order_and_returns_are_deterministic(
    consented_rin: ConsentedRin,
) -> None:
    localized = MappingProxyType(
        {
            "zh-CN": "用户批准了简洁的技术说明。",
            "ja-JP": "簡潔な技術説明をユーザーが承認しました。",
            "en-US": "The user approved concise technical explanations.",
        }
    )
    summary = "The user approved concise technical explanations."
    added = add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        "host-memory-preference-01",
        summary,
        localized,
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )
    content = {
        "host_memory_id": "host-memory-preference-01",
        "summary": summary,
        "localized_summaries": {
            locale: localized[locale] for locale in sorted(localized)
        },
    }
    identity = {
        "scope": "global",
        "workspace_id": None,
        "namespace": "original",
        "character_id": "rin-aster",
        "host_memory_id": "host-memory-preference-01",
    }

    assert added["content_hash"] == sha256(canonical_bytes(content)).hexdigest()
    assert added["memory_reference_id"] == (
        "memory-" + sha256(canonical_bytes(identity)).hexdigest()[:32]
    )
    assert list(added["localized_summaries"]) == ["en-US", "ja-JP", "zh-CN"]
    assert added["embedded_content"] is False
    assert added["canonical_fact_authority"] is False

    added["summary"] = "caller mutation"
    first_view = list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )[0]
    first = first_view.reference
    second = first_view.reference
    first["summary"] = "view mutation"
    assert second["summary"] == summary


def test_memory_reused_host_id_requires_exact_approved_bytes(
    consented_rin: ConsentedRin,
) -> None:
    _add(consented_rin)

    _assert_code(
        "PERSISTENCE_MEMORY_CONFLICT",
        lambda: _add(
            consented_rin,
            summary="The user approved detailed technical explanations.",
        ),
    )
    assert len(list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )) == 1


def test_memory_permission_and_exact_consent_revision_are_required(
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
    host_id, summary, localized = approved_memory_inputs()

    def add(consent_id: str, revision: int) -> dict[str, Any]:
        return add_memory_reference(
            data_root,
            "rin-aster",
            host_id,
            summary,
            localized,
            consent_id,
            revision,
            SCHEMAS,
        )

    _assert_code(
        "PERSISTENCE_CONSENT_CONFLICT",
        lambda: add("wrong-consent", consent["grant_revision"]),
    )
    _assert_code(
        "PERSISTENCE_CONSENT_CONFLICT",
        lambda: add(consent["consent_id"], 2),
    )
    _assert_code(
        "PERSISTENCE_PERMISSION_DENIED",
        lambda: add(consent["consent_id"], consent["grant_revision"]),
    )
    assert not _memory_root(data_root).exists()


def test_revocation_blocks_add_but_list_and_remove_remain_available(
    consented_rin: ConsentedRin,
) -> None:
    added = _add(consented_rin)
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
        lambda: _add(
            consented_rin,
            host_memory_id="host-memory-preference-02",
        ),
    )
    listed = list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )
    assert len(listed) == 1
    assert listed[0].active_consent_generation is False

    removed = remove_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        added["host_memory_id"],
        consent["consent_id"],
        SCHEMAS,
        identifier_kind="host_memory_id",
    )
    assert removed.removed is True
    assert removed.memory_reference_id == added["memory_reference_id"]


def test_memory_remove_missing_semantics_are_identifier_specific(
    consented_rin: ConsentedRin,
) -> None:
    consent_id = consented_rin.consent["consent_id"]

    absent = remove_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        "memory-11111111111111111111111111111111",
        consent_id,
        SCHEMAS,
        identifier_kind="memory_reference_id",
    )
    assert absent.removed is False
    assert absent.memory_reference_id is None
    _assert_code(
        "PERSISTENCE_MEMORY_NOT_FOUND",
        lambda: remove_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            "host-memory-absent",
            consent_id,
            SCHEMAS,
            identifier_kind="host_memory_id",
        ),
    )


def test_memory_capacity_is_checked_before_second_publication(
    consented_rin: ConsentedRin,
) -> None:
    limits = PersistenceLimits(max_memory_references=1)
    _add(consented_rin, limits=limits)

    _assert_code(
        "PERSISTENCE_LIMIT_EXCEEDED",
        lambda: _add(
            consented_rin,
            host_memory_id="host-memory-preference-02",
            limits=limits,
        ),
    )
    assert len(list(_memory_root(consented_rin.data_root).iterdir())) == 1


def test_global_and_workspace_memory_references_are_isolated(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    install_rin(data_root, rin_verified_release)
    install_rin(
        data_root,
        rin_verified_release,
        workspace_root=workspace_root,
    )
    global_consent = grant_consent(
        data_root,
        "rin-aster",
        ["memory_references"],
        SCHEMAS,
        expected_revision=0,
    )
    workspace_consent = grant_consent(
        data_root,
        "rin-aster",
        ["memory_references"],
        SCHEMAS,
        workspace_root=workspace_root,
        expected_revision=0,
    )
    host_id, summary, localized = approved_memory_inputs()
    global_reference = add_memory_reference(
        data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        global_consent["consent_id"],
        global_consent["grant_revision"],
        SCHEMAS,
    )
    workspace_reference = add_memory_reference(
        data_root,
        "rin-aster",
        host_id,
        summary,
        localized,
        workspace_consent["consent_id"],
        workspace_consent["grant_revision"],
        SCHEMAS,
        workspace_root=workspace_root,
    )

    assert global_reference["memory_reference_id"] != (
        workspace_reference["memory_reference_id"]
    )
    assert [view.reference for view in list_memory_references(
        data_root,
        "rin-aster",
        SCHEMAS,
    )] == [global_reference]
    assert [view.reference for view in list_memory_references(
        data_root,
        "rin-aster",
        SCHEMAS,
        workspace_root=workspace_root,
    )] == [workspace_reference]
