from __future__ import annotations

from copy import deepcopy
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
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/build-validation",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
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
        lambda report: report.pop("artifact_id"),
        lambda report: report["locale_coverage"].__setitem__("en-US", None),
        lambda report: report.pop("provenance_counts"),
    ],
)
def test_malformed_valid_report_is_schema_rejected_before_scan_or_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
) -> None:
    request, _source, report, draft = artifacts
    mutation(report)
    monkeypatch.setattr(
        storage,
        "scan_pack",
        lambda *args, **kwargs: pytest.fail("scan must not run"),
    )
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: pytest.fail("staging must not be created"),
    )

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"
    assert caught.value.details["schema"] == "build-validation-report"
    assert not (tmp_path / "data").exists()


def test_malformed_request_is_schema_rejected_before_scan_or_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _source, report, draft = artifacts
    request["intended_use_cases"] = []
    draft["request_hash"] = storage.sha256(storage.canonical_bytes(request)).hexdigest()
    monkeypatch.setattr(
        storage,
        "scan_pack",
        lambda *args, **kwargs: pytest.fail("scan must not run"),
    )
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: pytest.fail("staging must not be created"),
    )

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"
    assert caught.value.details["schema"] == "character-build-request"
    assert not (tmp_path / "data").exists()


def test_malformed_draft_is_schema_rejected_before_scan_or_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _source, report, draft = artifacts
    draft = deepcopy(draft)
    draft["locale_coverage"]["ja-JP"] = None
    monkeypatch.setattr(
        storage,
        "scan_pack",
        lambda *args, **kwargs: pytest.fail("scan must not run"),
    )
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: pytest.fail("staging must not be created"),
    )

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"
    assert caught.value.details["schema"] == "character-draft"
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "mutation,expected_code",
    [
        (
            lambda draft: draft.__setitem__("artifact_id", "../escape"),
            "SCHEMA_VALIDATION_FAILED",
        ),
        (
            lambda draft: draft.__setitem__("visibility", "public"),
            "SCHEMA_VALIDATION_FAILED",
        ),
        (
            lambda draft: draft.__setitem__("activation_allowed", True),
            "SCHEMA_VALIDATION_FAILED",
        ),
        (
            lambda draft: draft["bundle_references"].__setitem__(
                "request", "../request.json"
            ),
            "SCHEMA_VALIDATION_FAILED",
        ),
        (
            lambda draft: draft.__setitem__("request_hash", "0" * 64),
            "INVALID_DRAFT_DATA",
        ),
    ],
)
def test_tampered_or_traversing_draft_metadata_fails_before_writes(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    mutation: Any,
    expected_code: str,
) -> None:
    mutation(artifacts[3])

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == expected_code
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


def test_transient_rollback_failures_restore_previous_complete_draft(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    marker = published / "previous.txt"
    marker.write_bytes(b"complete previous draft")
    real_replace = storage.os.replace
    calls = 0

    def fail_cutover_then_rollback_transiently(
        source: str | Path, destination: str | Path
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("cutover failed")
        if calls in {3, 4}:
            error = PermissionError("transient rollback race")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_cutover_then_rollback_transiently)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "DRAFT_PUBLISH_FAILED"
    assert marker.read_bytes() == b"complete previous draft"
    assert list(published.parent.glob(f".{published.name}.*-*")) == []


@pytest.mark.parametrize("failing_stage", ["backup", "cutover"])
def test_transient_rename_failures_are_retried_to_successful_publication(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    failing_stage: str,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    real_replace = storage.os.replace
    failures = 0

    def fail_selected_stage_transiently(
        source: str | Path, destination: str | Path
    ) -> None:
        nonlocal failures
        source_path = Path(source)
        destination_path = Path(destination)
        is_selected = (
            failing_stage == "backup" and ".backup-" in destination_path.name
        ) or (
            failing_stage == "cutover"
            and ".staging-" in source_path.name
            and destination_path == published
        )
        if is_selected and failures < 2:
            failures += 1
            error = PermissionError("transient rename race")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_selected_stage_transiently)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    replaced = _publish(tmp_path, source_root, artifacts)

    assert replaced == published
    assert failures == 2
    assert (published / "draft.json").is_file()
    assert list(published.parent.glob(f".{published.name}.*-*")) == []


def test_unrecoverable_rollback_preserves_only_good_copy_at_known_backup(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    (published / "previous.txt").write_bytes(b"complete previous draft")
    real_replace = storage.os.replace
    calls = 0

    def fail_cutover_and_restore(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            error = PermissionError("sensitive restore failure")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_cutover_and_restore)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "DRAFT_RESTORE_FAILED"
    backup = Path(caught.value.details["backup_path"])
    assert backup.parent == published.parent
    assert backup.name.startswith(f".{published.name}.backup-")
    assert (backup / "previous.txt").read_bytes() == b"complete previous draft"
    assert not published.exists()
    assert "sensitive" not in caught.value.message
    assert calls == 11


def test_transient_backup_cleanup_failure_is_retried_without_failing_publish(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    real_rmtree = storage.shutil.rmtree
    calls = 0

    def transient_cleanup(path: str | Path, *args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise PermissionError("transient cleanup race")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(storage.shutil, "rmtree", transient_cleanup)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    replaced = _publish(tmp_path, source_root, artifacts)

    assert replaced == published
    assert (published / "draft.json").is_file()
    assert list(published.parent.glob(f".{published.name}.backup-*")) == []


def test_stale_backup_reaping_never_follows_redirects(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    stale = published.parent / f".{published.name}.backup-{'a' * 24}"
    stale.mkdir()
    marker = stale / "must-not-follow.txt"
    marker.write_bytes(b"outside-like data")
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)
    real_rmtree = storage.shutil.rmtree

    def mark_stale_as_junction(path: Path) -> bool:
        return path == stale or bool(real_is_junction(path))

    def reject_redirect_cleanup(path: str | Path, *args: Any, **kwargs: Any) -> None:
        assert Path(path) != stale
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_junction", mark_stale_as_junction, raising=False)
    monkeypatch.setattr(storage.shutil, "rmtree", reject_redirect_cleanup)

    replaced = _publish(tmp_path, source_root, artifacts)

    assert replaced == published
    assert marker.read_bytes() == b"outside-like data"


def test_permanent_backup_cleanup_does_not_report_complete_publish_as_failure(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    real_rmtree = storage.shutil.rmtree
    monkeypatch.setattr(
        storage.shutil,
        "rmtree",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("busy")),
    )
    replaced = _publish(tmp_path, source_root, artifacts)
    assert replaced == published
    backups = list(published.parent.glob(f".{published.name}.backup-*"))
    assert len(backups) == 1

    monkeypatch.setattr(storage.shutil, "rmtree", real_rmtree)
    _publish(tmp_path, source_root, artifacts)

    assert list(published.parent.glob(f".{published.name}.backup-*")) == []


def test_staging_creation_failure_is_sanitized_without_residue(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = PermissionError("sensitive staging failure")
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: (_ for _ in ()).throw(expected),
    )

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "DRAFT_PUBLISH_FAILED"
    assert caught.value.details == {
        "operation": "create_staging",
        "reason": "PermissionError",
    }
    assert "sensitive" not in caught.value.message
    assert not list((tmp_path / "data").rglob("*.staging-*"))


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
