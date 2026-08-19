from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from typing import Any, cast

import pytest

from kokoroarc import __version__
from kokoroarc.distribution.archive import build_karc_archive
from kokoroarc.distribution.installer import install_karc_archive
from kokoroarc.packs.compiler import canonical_bytes, compile_pack
from kokoroarc.packs.loader import load_source_pack
from kokoroarc.persistence.consent import grant_consent
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import build_private_archive


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def interaction_event(
    event_id: str,
    relationship_revision: int,
    *,
    trust: float = 2.0,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": f"event/{event_id}",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "event_id": event_id,
        "turn_id": f"turn-{relationship_revision + 1}",
        "origin": "verified_task_outcome",
        "novelty_key": f"novelty-{event_id}",
        "expected_state_revision": relationship_revision,
        "evaluator_version": "interaction-v1",
        "evidence": {"kind": "test_result", "reference": "pytest"},
        "confidence": 1.0,
        "effects": {"trust": trust},
    }


def mood_event(event_id: str, mood_revision: int) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "expected_mood_revision": mood_revision,
        "primary": "pleased",
        "secondary": "focused",
        "arousal": 0.35,
        "valence": 0.4,
        "intensity": 0.42,
        "expires_after_turns": 3,
        "triggering_interaction_event_id": "event-1",
        "trigger_strength": "ordinary",
    }


def approved_memory_inputs() -> tuple[str, str, dict[str, str]]:
    summary = "The user approved concise technical explanations."
    return (
        "host-memory-preference-01",
        summary,
        {"en-US": summary},
    )


def install_rin(
    data_root: Path,
    release: dict[str, Any],
    *,
    workspace_root: Path | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    label = "workspace" if workspace_root is not None else "global"
    archive = data_root.parent / f"rin-{label}.karc"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if source_root is None:
        archive_payload = build_private_archive(release)
    else:
        evidence = release["evidence"]
        compiled = compile_pack(load_source_pack(source_root, SCHEMAS), SCHEMAS)
        archive_payload = build_karc_archive(
            compiled_pack=compiled,
            hard_validation_report=evidence["hard_report"],
            soft_evaluation_report=evidence["soft_evaluation_report"],
            review_attestation=evidence["review_attestation"],
            promotion_record=release["promotion"],
            schemas=SCHEMAS,
        )
    archive.write_bytes(archive_payload)
    return install_karc_archive(
        archive,
        data_root,
        SCHEMAS,
        workspace_root=workspace_root,
    )


@dataclass(frozen=True, slots=True)
class MigrationTarget:
    source_root: Path
    installation_payload: bytes
    consent_payload: bytes

    @property
    def installation(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.installation_payload))

    @property
    def installation_binding(self) -> dict[str, Any]:
        installation = self.installation
        namespace, character_id, character_version = installation[
            "registry_identity"
        ].split("/", maxsplit=2)
        return {
            "installation_id": installation["installation_id"],
            "namespace": namespace,
            "character_id": character_id,
            "character_version": character_version,
            "archive_sha256": installation["archive_sha256"],
            "compiled_sha256": installation["compiled_sha256"],
        }

    @property
    def consent(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.consent_payload))


def install_rin_successor(
    consented: ConsentedRin,
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
    *,
    permissions: Sequence[str] = (
        "relationship_state",
        "mood_state",
        "memory_references",
    ),
) -> MigrationTarget:
    source_root = tmp_path / "rin-aster-1.1.0"
    shutil.copytree(Path("characters/original/rin-aster"), source_root)
    manifest_path = source_root / "character.yaml"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    source_version = "character_version: 1.0.0"
    target_version = "character_version: 1.1.0"
    assert manifest_text.count(source_version) == 1
    manifest_path.write_text(
        manifest_text.replace(source_version, target_version),
        encoding="utf-8",
    )
    request = json.loads(
        Path("tests/fixtures/authoring/original-request.json").read_text(
            encoding="utf-8"
        )
    )
    request["character_version"] = "1.1.0"
    release = verified_release_factory(
        source_root,
        request,
        visibility="private",
    )
    installation = install_rin(
        consented.data_root,
        release,
        source_root=source_root,
    )
    consent = grant_consent(
        consented.data_root,
        "rin-aster",
        list(permissions),
        SCHEMAS,
        version="1.1.0",
        expected_revision=consented.consent["grant_revision"],
    )
    return MigrationTarget(
        source_root=source_root,
        installation_payload=canonical_bytes(installation),
        consent_payload=canonical_bytes(consent),
    )


@dataclass(frozen=True, slots=True)
class ConsentedRin:
    data_root: Path
    workspace_root: Path | None
    installation_payload: bytes
    consent_payload: bytes

    @property
    def installation(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.installation_payload))

    @property
    def consent(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.consent_payload))


@pytest.fixture
def consented_rin(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> ConsentedRin:
    data_root = tmp_path / "data"
    installation = install_rin(data_root, rin_verified_release)
    consent = grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state", "mood_state", "memory_references"],
        SCHEMAS,
        expected_revision=0,
    )
    return ConsentedRin(
        data_root=data_root,
        workspace_root=None,
        installation_payload=canonical_bytes(installation),
        consent_payload=canonical_bytes(consent),
    )
