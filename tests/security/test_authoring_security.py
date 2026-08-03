from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.authoring import storage
from kokoroarc.authoring.drafts import build_character_draft
from kokoroarc.authoring.storage import publish_draft_bundle
from kokoroarc.errors import KokoroError


@pytest.fixture
def artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    request = {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/build-request",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "mode": "original",
        "namespace": "original",
        "character_id": "rin-aster",
        "display_name": "Rin Aster",
        "character_version": "1.0.0",
        "requested_locales": ["zh-CN", "en-US", "ja-JP"],
        "intended_use_cases": ["collaboration"],
        "user_constraints": ["Stay grounded."],
        "inputs": [{"type": "creative_brief", "content": "Original."}],
        "requested_visibility": "private",
    }
    source = {
        "namespace": "original",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
    }
    report = {
        "hard_failures": [],
        "advisory_findings": [],
        "locale_coverage": {"zh-CN": True, "en-US": True, "ja-JP": True},
        "provenance_counts": {
            "evidence": 0,
            "derived_profile": 0,
            "user_override": 0,
        },
        "valid": True,
    }
    return request, source, report, build_character_draft(request, source, report)


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    (root / "character.yaml").write_bytes(b"name: Rin\n")
    return root


def _publish(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> Path:
    request, _source, report, draft = artifacts
    return publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)


def test_invalid_report_is_rejected_before_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _source, report, draft = artifacts
    report["valid"] = False
    report["hard_failures"] = [
        {"code": "FAIL", "path": [], "message": "hard failure"}
    ]
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: pytest.fail("staging must not be created"),
    )

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "AUTHORING_VALIDATION_FAILED"
    assert caught.value.details == {"reason": "hard_failures"}
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda draft: draft.__setitem__("artifact_id", "../escape"),
        lambda draft: draft.__setitem__("visibility", "public"),
        lambda draft: draft.__setitem__("activation_allowed", True),
        lambda draft: draft["bundle_references"].__setitem__("request", "../request.json"),
        lambda draft: draft.__setitem__("request_hash", "0" * 64),
    ],
)
def test_tampered_or_traversing_draft_metadata_fails_before_writes(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    mutation: Any,
) -> None:
    mutation(artifacts[3])

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "INVALID_DRAFT_DATA"
    assert not (tmp_path / "data").exists()


def test_destination_redirect_component_is_rejected(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    data_root = tmp_path / "data"
    data_root.mkdir()
    redirect = data_root / "drafts"
    try:
        redirect.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"The current account cannot create directory symlinks: {exc}")
    request, _source, report, draft = artifacts

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(data_root, source_root, request, draft, report)

    assert caught.value.code == "UNSAFE_DRAFT_PATH"
    assert not any(outside.iterdir())


def test_destination_junction_component_is_rejected_without_capability_dependency(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def mark_drafts_as_junction(path: Path) -> bool:
        return path.name == "drafts" or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", mark_drafts_as_junction, raising=False)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "UNSAFE_DRAFT_PATH"
    assert caught.value.details["reason"] == "junction"


def test_source_symlink_is_rejected_without_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    target = source_root / "target.yaml"
    target.write_bytes(b"safe: true\n")
    try:
        (source_root / "alias.yaml").symlink_to(target)
    except OSError as exc:
        pytest.skip(f"The current account cannot create file symlinks: {exc}")

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "UNSAFE_PACK_PATH"
    assert not (tmp_path / "data").exists()


def test_source_hardlink_is_rejected_without_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    try:
        os.link(source_root / "character.yaml", source_root / "alias.yaml")
    except OSError as exc:
        pytest.skip(f"Hardlink creation is unavailable: {exc}")

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "UNSAFE_PACK_PATH"
    assert not (tmp_path / "data").exists()


def test_source_mutation_during_copy_fails_closed_and_cleans_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_copy = storage._copy_scanned_file
    mutated = False

    def mutate_after_copy(*args: Any, **kwargs: Any) -> Any:
        nonlocal mutated
        result = real_copy(*args, **kwargs)
        if not mutated:
            mutated = True
            (source_root / "character.yaml").write_bytes(b"name: Eve\n")
        return result

    monkeypatch.setattr(storage, "_copy_scanned_file", mutate_after_copy)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "AUTHORING_SOURCE_CHANGED"
    assert not list((tmp_path / "data").rglob("*.staging-*"))
    assert not list((tmp_path / "data").rglob("draft.json"))


@pytest.mark.parametrize("failing_call", [1, 2])
def test_replace_failure_preserves_previous_draft_and_removes_residue(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    failing_call: int,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    marker = published / "previous.txt"
    marker.write_bytes(b"complete previous draft")
    real_replace = storage.os.replace
    calls = 0

    def fail_new_publish(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == failing_call:
            raise OSError("sensitive operating system detail")
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_new_publish)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "DRAFT_PUBLISH_FAILED"
    assert caught.value.details == {"operation": "replace", "reason": "OSError"}
    assert "sensitive" not in caught.value.message
    assert marker.read_bytes() == b"complete previous draft"
    assert list(published.parent.glob(f".{published.name}.*-*")) == []


def test_unsupported_source_entry_fails_closed(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("The platform has no portable FIFO creation API")
    try:
        os.mkfifo(source_root / "pipe")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"The platform cannot create a FIFO fixture: {exc}")

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "UNSAFE_PACK_PATH"
