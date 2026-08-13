from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.research import (
    build_research_bundle,
    load_published_research_bundle,
    publish_research_bundle,
    storage,
)
from kokoroarc.research.validation import validate_research_workspace
from kokoroarc.research.workspace import load_research_workspace
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
PROTECTED_ROOTS = (
    "drafts",
    "compiled",
    "installed",
    "public",
    "sessions",
    "state",
    "events",
    "workspaces",
    "config",
)


def published_bundle(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source_root = Path("tests/fixtures/research/complete")
    workspace = load_research_workspace(source_root, SCHEMAS)
    report = validate_research_workspace(workspace, SCHEMAS)
    bundle = build_research_bundle(workspace, report)
    published = publish_research_bundle(
        tmp_path / "data", source_root, workspace, report, bundle
    )
    return published, bundle


def test_publish_research_bundle_is_confined_complete_and_repeatable(
    tmp_path: Path,
) -> None:
    source_root = Path("tests/fixtures/research/complete")
    workspace = load_research_workspace(source_root, SCHEMAS)
    report = validate_research_workspace(workspace, SCHEMAS)
    bundle = build_research_bundle(workspace, report)
    data_root = tmp_path / "data"

    first = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )
    second = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )

    assert first == second
    assert first == data_root / "research" / Path(*bundle["artifact_id"].split("/"))
    assert first.is_relative_to((data_root / "research").resolve())
    assert sorted(path.name for path in first.iterdir()) == [
        "bundle.json",
        "request.json",
        "validation-report.json",
        "workspace.json",
    ]
    assert (first / "request.json").read_bytes() == (
        canonical_bytes(workspace.request) + b"\n"
    )
    assert (first / "validation-report.json").read_bytes() == (
        canonical_bytes(report) + b"\n"
    )
    assert (first / "bundle.json").read_bytes() == canonical_bytes(bundle) + b"\n"
    assert not any((data_root / name).exists() for name in PROTECTED_ROOTS)


def test_load_published_research_bundle_revalidates_hash_bound_files(
    tmp_path: Path,
) -> None:
    published, bundle = published_bundle(tmp_path)

    loaded = load_published_research_bundle(published, SCHEMAS)

    assert loaded == bundle
    assert loaded is not bundle


@pytest.mark.parametrize(
    ("filename", "member", "replacement"),
    [
        ("request.json", "display_name", "Changed Request"),
        ("validation-report.json", "artifact_id", "research/changed/report"),
        ("workspace.json", "coverage", {}),
        ("bundle.json", "display_name", "Changed Bundle"),
    ],
)
def test_load_published_research_bundle_rejects_hash_bound_tampering(
    tmp_path: Path,
    filename: str,
    member: str,
    replacement: object,
) -> None:
    published, _bundle = published_bundle(tmp_path)
    path = published / filename
    document = deepcopy(__import__("json").loads(path.read_bytes()))
    document[member] = replacement
    path.write_bytes(canonical_bytes(document) + b"\n")

    with pytest.raises(KokoroError) as caught:
        load_published_research_bundle(published, SCHEMAS)

    assert caught.value.code == "RESEARCH_BUNDLE_INVALID"


def test_publish_fsyncs_same_parent_staging_before_cutover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = Path("tests/fixtures/research/complete")
    workspace = load_research_workspace(source_root, SCHEMAS)
    report = validate_research_workspace(workspace, SCHEMAS)
    bundle = build_research_bundle(workspace, report)
    synced: list[Path] = []
    monkeypatch.setattr(storage, "_fsync_directory", synced.append)

    published = publish_research_bundle(
        tmp_path / "data", source_root, workspace, report, bundle
    )

    staging_syncs = [path for path in synced if ".staging-" in path.name]
    assert len(staging_syncs) == 1
    assert staging_syncs[0].parent == published.parent
    assert synced[-1] == published.parent


def test_safe_partial_research_bundle_remains_private_and_loadable(
    tmp_path: Path,
) -> None:
    source_root = Path("tests/fixtures/research/partial")
    workspace = load_research_workspace(source_root, SCHEMAS)
    report = validate_research_workspace(workspace, SCHEMAS)
    bundle = build_research_bundle(workspace, report)

    published = publish_research_bundle(
        tmp_path / "data", source_root, workspace, report, bundle
    )
    loaded = load_published_research_bundle(published, SCHEMAS)

    assert loaded == bundle
    assert loaded["visibility"] == "private"
    assert loaded["activation_allowed"] is False
    assert loaded["authoring_allowed"] is False
    assert loaded["blocking_reasons"]
