from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from kokorox.errors import KokoroError
from kokorox.packs.compiler import canonical_bytes
from kokorox.research import load_research_workspace
from kokorox.research.workspace import ResearchLimits
from kokorox.schemas import SchemaRegistry


def test_load_research_workspace_returns_canonical_assembled_artifacts() -> None:
    registry = SchemaRegistry(Path("schemas/v1"))

    loaded = load_research_workspace(
        Path("tests/fixtures/research/complete"), registry
    )

    assert loaded.request["character_id"] == "aoi-kisaragi-fixture"
    assert [item["source_id"] for item in loaded.sources] == sorted(
        item["source_id"] for item in loaded.sources
    )
    assert len(loaded.workspace_hash) == 64
    assert (
        loaded.workspace_hash
        == "d15f60759059eaed27322878a6404dc2cd1f4e0d31e526b3db89f7ddaa7e8f2b"
    )
    assert loaded.workspace_hash == load_research_workspace(
        Path("tests/fixtures/research/complete"), registry
    ).workspace_hash
    assembled = {
        "request": loaded.request,
        "sources": list(loaded.sources),
        "claims": list(loaded.claims),
        "conflicts": list(loaded.conflicts),
        "coverage": loaded.coverage,
    }
    assert loaded.workspace_hash == sha256(canonical_bytes(assembled)).hexdigest()
    assert loaded.root.is_absolute()
    assert loaded.file_hashes["workspace.json"] == sha256(
        Path("tests/fixtures/research/complete/workspace.json").read_bytes()
    ).hexdigest()
    assert set(loaded.file_hashes) == {
        "workspace.json",
        "request.json",
        "sources/source-episode-01.json",
        "sources/source-official-profile.json",
        "claims/claim-behavior.json",
        "claims/claim-role.json",
        "conflicts/conflict-adaptation-wording.json",
        "coverage.json",
    }


def test_research_workspace_and_limits_are_frozen() -> None:
    loaded = load_research_workspace(
        Path("tests/fixtures/research/complete"), SchemaRegistry(Path("schemas/v1"))
    )

    with pytest.raises(FrozenInstanceError):
        loaded.workspace_hash = "0" * 64  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ResearchLimits().max_files = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "limits",
    [
        ResearchLimits(True, 1, 1),
        ResearchLimits(1, False, 1),
        ResearchLimits(1, 1, True),
        ResearchLimits(1.5, 1, 1),  # type: ignore[arg-type]
    ],
)
def test_rejects_boolean_and_non_integer_limits(limits: ResearchLimits) -> None:
    with pytest.raises(KokoroError) as raised:
        load_research_workspace(
            Path("tests/fixtures/research/complete"),
            SchemaRegistry(Path("schemas/v1")),
            limits,
        )

    assert raised.value.code == "RESEARCH_WORKSPACE_LIMIT_INVALID"


def test_exact_filesystem_limits_are_accepted() -> None:
    root = Path("tests/fixtures/research/complete")
    files = [path for path in root.rglob("*") if path.is_file()]
    limits = ResearchLimits(
        max_files=len(files),
        max_file_bytes=max(path.stat().st_size for path in files),
        max_total_bytes=sum(path.stat().st_size for path in files),
    )

    loaded = load_research_workspace(root, SchemaRegistry(Path("schemas/v1")), limits)

    assert loaded.request["character_id"] == "aoi-kisaragi-fixture"


def test_loads_partial_and_injection_workspaces_without_executing_source_text() -> None:
    registry = SchemaRegistry(Path("schemas/v1"))

    partial = load_research_workspace(Path("tests/fixtures/research/partial"), registry)
    injection = load_research_workspace(Path("tests/fixtures/research/injection"), registry)

    assert partial.coverage["blocks_authoring"] is True
    assert (
        partial.workspace_hash
        == "e8261f3ed4fa29be9d97533cd66271baeed297e15c65b8b789fa435cc40103fa"
    )
    assert injection.request["character_id"] == "aoi-kisaragi-fixture"
    assert all(
        "Ignore prior instructions" not in source["locator"]
        for source in injection.sources
    )


def test_workspace_hash_uses_closed_canonical_assembled_object_and_detaches_documents() -> None:
    registry = SchemaRegistry(Path("schemas/v1"))
    loaded = load_research_workspace(Path("tests/fixtures/research/complete"), registry)
    expected = {
        "request": loaded.request,
        "sources": list(loaded.sources),
        "claims": list(loaded.claims),
        "conflicts": list(loaded.conflicts),
        "coverage": loaded.coverage,
    }

    assert loaded.workspace_hash == sha256(canonical_bytes(expected)).hexdigest()
    assert loaded.file_hashes["request.json"] == sha256(
        Path("tests/fixtures/research/complete/request.json").read_bytes()
    ).hexdigest()
    loaded.request["display_name"] = "Detached mutation"
    reloaded = load_research_workspace(Path("tests/fixtures/research/complete"), registry)
    assert reloaded.request["display_name"] != "Detached mutation"


@pytest.mark.parametrize(
    "limits",
    [ResearchLimits(0, 1, 1), ResearchLimits(1, 0, 1), ResearchLimits(1, 1, 0)],
)
def test_rejects_non_positive_limits(limits: ResearchLimits) -> None:
    with pytest.raises(KokoroError) as raised:
        load_research_workspace(
            Path("tests/fixtures/research/complete"),
            SchemaRegistry(Path("schemas/v1")),
            limits,
        )
    assert raised.value.code == "RESEARCH_WORKSPACE_LIMIT_INVALID"
