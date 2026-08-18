from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, cast

import pytest

from kokoroarc.distribution.installer import install_karc_archive
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.persistence.consent import grant_consent
from kokoroarc.schemas import SchemaRegistry

from karc_test_support import build_private_archive


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def install_rin(
    data_root: Path,
    release: dict[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    label = "workspace" if workspace_root is not None else "global"
    archive = data_root.parent / f"rin-{label}.karc"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(build_private_archive(release))
    return install_karc_archive(
        archive,
        data_root,
        SCHEMAS,
        workspace_root=workspace_root,
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
