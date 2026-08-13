from __future__ import annotations

from pathlib import Path
import os
import shutil
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.research import (
    build_research_bundle,
    load_published_research_bundle,
    publish_research_bundle,
    storage,
)
from kokoroarc.research.validation import validate_research_workspace
from kokoroarc.research.workspace import ResearchWorkspace, load_research_workspace
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def research_artifacts(
    tmp_path: Path,
    tree: str = "complete",
    source_name: str = "source",
) -> tuple[Path, ResearchWorkspace, dict[str, Any], dict[str, Any]]:
    source_root = tmp_path / source_name
    shutil.copytree(Path("tests/fixtures/research") / tree, source_root)
    workspace = load_research_workspace(source_root, SCHEMAS)
    report = validate_research_workspace(workspace, SCHEMAS)
    bundle = build_research_bundle(workspace, report)
    return source_root, workspace, report, bundle


def test_parent_fsync_failure_restores_previous_complete_research_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    published = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )
    marker_payload = b"previous complete research bundle"
    (published / "previous.txt").write_bytes(marker_payload)

    def fail_parent_sync(path: Path) -> None:
        if path == published.parent:
            raise KokoroError(
                "RESEARCH_PUBLISH_FAILED",
                "Research bundle publication failed.",
                details={"operation": "fsync_directory", "reason": "OSError"},
            )

    monkeypatch.setattr(storage, "_fsync_directory", fail_parent_sync)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_DURABILITY_FAILED"
    assert (published / "previous.txt").read_bytes() == marker_payload
    assert list(published.parent.glob(f".{published.name}.staging-*")) == []
    assert list(published.parent.glob(f".{published.name}.backup-*")) == []


def test_concurrent_same_target_publication_is_retryably_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    verification_reached = threading.Event()
    release_first = threading.Event()
    failures: list[BaseException] = []
    real_verify = storage._verify_staged
    first_call = True
    call_guard = threading.Lock()

    def pause_first_verification(*args: Any, **kwargs: Any) -> None:
        nonlocal first_call
        real_verify(*args, **kwargs)
        with call_guard:
            should_pause = first_call
            first_call = False
        if should_pause:
            verification_reached.set()
            assert release_first.wait(timeout=10)

    def first_publish() -> None:
        try:
            publish_research_bundle(
                data_root, source_root, workspace, report, bundle
            )
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(storage, "_verify_staged", pause_first_verification)
    worker = threading.Thread(target=first_publish, daemon=True)
    worker.start()
    assert verification_reached.wait(timeout=10)

    try:
        with pytest.raises(KokoroError) as caught:
            publish_research_bundle(
                data_root, source_root, workspace, report, bundle
            )
        assert caught.value.code == "RESEARCH_PUBLISH_BUSY"
        assert caught.value.retryable is True
        assert caught.value.details == {"reason": "target_locked"}
    finally:
        release_first.set()
        worker.join(timeout=10)

    assert not worker.is_alive()
    assert failures == []


def test_source_workspace_mutation_during_staging_fails_before_cutover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    real_verify = storage._verify_staged

    def mutate_after_staging(*args: Any, **kwargs: Any) -> None:
        real_verify(*args, **kwargs)
        request_path = source_root / "request.json"
        request_path.write_bytes(request_path.read_bytes() + b" ")

    monkeypatch.setattr(storage, "_verify_staged", mutate_after_staging)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_WORKSPACE_CHANGED"
    final = data_root / "research" / Path(*bundle["artifact_id"].split("/"))
    assert not final.exists()
    assert list(final.parent.glob(f".{final.name}.staging-*")) == []


@pytest.mark.parametrize("failing_stage", ["backup", "cutover"])
def test_transient_rename_failures_are_bounded_and_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_stage: str,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    published = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )
    real_replace = storage.os.replace
    failures = 0

    def transient_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal failures
        source_path = Path(source)
        destination_path = Path(destination)
        selected = (
            failing_stage == "backup" and ".backup-" in destination_path.name
        ) or (
            failing_stage == "cutover"
            and ".staging-" in source_path.name
            and destination_path == published
        )
        if selected and failures < 2:
            failures += 1
            error = PermissionError("sensitive transient rename failure")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", transient_replace)

    replaced = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )

    assert replaced == published
    assert failures == 2
    assert (published / "bundle.json").is_file()
    assert list(published.parent.glob(f".{published.name}.staging-*")) == []
    assert list(published.parent.glob(f".{published.name}.backup-*")) == []


def test_transient_backup_cleanup_is_retried_without_false_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    published = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )
    real_rmtree = storage.shutil.rmtree
    failures = 0

    def transient_cleanup(path: str | Path, *args: Any, **kwargs: Any) -> None:
        nonlocal failures
        if ".backup-" in Path(path).name and failures < 2:
            failures += 1
            raise PermissionError("sensitive transient cleanup failure")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(storage.shutil, "rmtree", transient_cleanup)

    replaced = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )

    assert replaced == published
    assert failures == 2
    assert (published / "bundle.json").is_file()
    assert list(published.parent.glob(f".{published.name}.backup-*")) == []


def test_first_publication_directory_sync_failure_precedes_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    failure_path = data_root / "research"

    def fail_selected_directory(path: Path) -> None:
        if path == failure_path:
            raise KokoroError(
                "RESEARCH_PUBLISH_FAILED",
                "Research bundle publication failed.",
                details={"operation": "fsync_directory", "reason": "OSError"},
            )

    monkeypatch.setattr(storage, "_fsync_directory", fail_selected_directory)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_PUBLISH_FAILED"
    final = data_root / "research" / Path(*bundle["artifact_id"].split("/"))
    assert not final.exists()
    assert list(final.parent.glob(f".{final.name}.staging-*")) == []


def test_staged_file_identity_change_during_fsync_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    real_fsync = storage._fsync_directory
    changed = False

    def replace_bundle_during_fsync(path: Path) -> None:
        nonlocal changed
        if ".staging-" in path.name and not changed:
            changed = True
            bundle_path = path / "bundle.json"
            payload = bundle_path.read_bytes()
            bundle_path.unlink()
            bundle_path.write_bytes(payload)
        real_fsync(path)

    monkeypatch.setattr(storage, "_fsync_directory", replace_bundle_during_fsync)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_STAGING_INVALID"
    assert changed is True
    final = data_root / "research" / Path(*bundle["artifact_id"].split("/"))
    assert not final.exists()
    assert list(final.parent.glob(f".{final.name}.staging-*")) == []


def test_report_mutation_during_staging_breaks_hash_binding_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    real_write = storage._write_canonical_file
    mutated = False

    def mutate_report_after_bundle(path: Path, value: Any) -> None:
        nonlocal mutated
        real_write(path, value)
        if path.name == "bundle.json" and not mutated:
            mutated = True
            report["coverage_summary"]["covered"] += 1

    monkeypatch.setattr(storage, "_write_canonical_file", mutate_report_after_bundle)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_STAGING_INVALID"
    assert caught.value.details == {"reason": "hash_binding"}
    final = data_root / "research" / Path(*bundle["artifact_id"].split("/"))
    assert not final.exists()


def test_forged_bundle_is_rejected_before_storage_creation(tmp_path: Path) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    bundle["display_name"] = "Forged Name"
    unhashed = dict(bundle)
    unhashed.pop("bundle_hash")
    bundle["bundle_hash"] = storage.canonical_hash(unhashed)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_BUNDLE_MISMATCH"
    assert not data_root.exists()


def test_destination_junction_marker_is_rejected_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    data_root.mkdir()
    marked = data_root / "research"
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def is_marked(path: Path) -> bool:
        return path == marked or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", is_marked, raising=False)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "UNSAFE_RESEARCH_PATH"
    assert not list(data_root.rglob("*.staging-*"))


def test_hardlinked_publication_lock_is_rejected(
    tmp_path: Path,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    final = data_root / "research" / Path(*bundle["artifact_id"].split("/"))
    final.parent.mkdir(parents=True)
    outside = tmp_path / "outside-lock"
    outside.write_bytes(b"must remain unchanged")
    lock_path = final.parent / f".{final.name}.publish.lock"
    os.link(outside, lock_path)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "UNSAFE_RESEARCH_PATH"
    assert outside.read_bytes() == b"must remain unchanged"
    assert not final.exists()


def test_unrecoverable_rollback_retains_previous_bundle_at_reported_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    published = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )
    marker_payload = b"previous complete research bundle"
    (published / "previous.txt").write_bytes(marker_payload)
    real_replace = storage.os.replace
    calls = 0

    def fail_cutover_and_restore(source: str | Path, target: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            error = PermissionError("sensitive restore failure")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        real_replace(source, target)

    monkeypatch.setattr(storage.os, "replace", fail_cutover_and_restore)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_RECOVERY_REQUIRED"
    recovery = Path(caught.value.details["recovery_path"])
    assert recovery.parent == published.parent
    assert (recovery / "previous.txt").read_bytes() == marker_payload
    assert not published.exists()
    assert "sensitive" not in caught.value.message


def test_stale_backup_reaper_never_follows_redirect_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    published = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )
    stale = published.parent / f".{published.name}.backup-{'a' * 24}"
    stale.mkdir()
    marker = stale / "must-not-follow.txt"
    marker.write_bytes(b"outside-like data")
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def is_stale_junction(path: Path) -> bool:
        return path == stale or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", is_stale_junction, raising=False)

    assert publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    ) == published
    assert marker.read_bytes() == b"outside-like data"


def test_different_target_publication_does_not_share_target_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete = research_artifacts(tmp_path, "complete", "source-complete")
    partial = research_artifacts(tmp_path, "partial", "source-partial")
    data_root = tmp_path / "data"
    complete_final_name = complete[3]["artifact_id"].split("/")[-1]
    first_staged = threading.Event()
    release_first = threading.Event()
    failures: list[BaseException] = []
    real_verify = storage._verify_staged

    def pause_complete(*args: Any, **kwargs: Any) -> Any:
        identities = real_verify(*args, **kwargs)
        staging = Path(args[0])
        if staging.name.startswith(f".{complete_final_name}.staging-"):
            first_staged.set()
            assert release_first.wait(timeout=10)
        return identities

    def publish_complete() -> None:
        try:
            publish_research_bundle(data_root, *complete)
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(storage, "_verify_staged", pause_complete)
    worker = threading.Thread(target=publish_complete, daemon=True)
    worker.start()
    assert first_staged.wait(timeout=10)

    try:
        partial_path = publish_research_bundle(data_root, *partial)
        assert partial_path.name == partial[3]["artifact_id"].split("/")[-1]
    finally:
        release_first.set()
        worker.join(timeout=10)

    assert not worker.is_alive()
    assert failures == []


def test_loader_rejects_file_identity_change_after_that_file_was_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    published = publish_research_bundle(
        tmp_path / "data", source_root, workspace, report, bundle
    )
    real_read = storage._read_published_document
    changed = False

    def replace_request_after_read(root: Path, path: Path) -> dict[str, Any]:
        nonlocal changed
        document = real_read(root, path)
        if path.name == "request.json" and not changed:
            changed = True
            payload = path.read_bytes()
            path.unlink()
            path.write_bytes(payload)
        return document

    monkeypatch.setattr(storage, "_read_published_document", replace_request_after_read)

    with pytest.raises(KokoroError) as caught:
        load_published_research_bundle(published, SCHEMAS)

    assert caught.value.code == "RESEARCH_BUNDLE_INVALID"
    assert changed is True


def test_loader_rejects_hardlinked_bundle_file(tmp_path: Path) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    published = publish_research_bundle(
        tmp_path / "data", source_root, workspace, report, bundle
    )
    outside = tmp_path / "outside-bundle-link"
    os.link(published / "bundle.json", outside)

    with pytest.raises(KokoroError) as caught:
        load_published_research_bundle(published, SCHEMAS)

    assert caught.value.code == "RESEARCH_BUNDLE_INVALID"
    assert outside.read_bytes() == (published / "bundle.json").read_bytes()


def test_schema_invalid_bundle_mutation_during_staging_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    real_write = storage._write_canonical_file
    mutated = False

    def mutate_before_bundle_write(path: Path, value: Any) -> None:
        nonlocal mutated
        if path.name == "bundle.json" and not mutated:
            mutated = True
            value["visibility"] = "public"
            unhashed = dict(value)
            unhashed.pop("bundle_hash")
            value["bundle_hash"] = storage.canonical_hash(unhashed)
        real_write(path, value)

    monkeypatch.setattr(storage, "_write_canonical_file", mutate_before_bundle_write)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_STAGING_INVALID"
    assert caught.value.details == {"reason": "schema"}
    final = data_root / "research" / Path(*bundle["artifact_id"].split("/"))
    assert not final.exists()


def test_recoverable_staging_failure_uses_no_follow_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"

    def fail_verification(staging: Path, *_args: Any, **_kwargs: Any) -> Any:
        (staging / "unexpected.txt").write_bytes(b"inert")
        raise KokoroError(
            "RESEARCH_STAGING_INVALID",
            "Research bundle publication failed.",
            details={"reason": "injected"},
        )

    monkeypatch.setattr(storage, "_verify_staged", fail_verification)
    monkeypatch.setattr(
        storage.shutil,
        "rmtree",
        lambda *_args, **_kwargs: pytest.fail(
            "staging cleanup must not delegate to generic tree traversal"
        ),
    )

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_STAGING_INVALID"
    final = data_root / "research" / Path(*bundle["artifact_id"].split("/"))
    assert list(final.parent.glob(f".{final.name}.staging-*")) == []


def test_staging_creation_failure_is_sanitized_and_precise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PermissionError("sensitive staging path failure")
        ),
    )

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_PUBLISH_FAILED"
    assert caught.value.details == {
        "operation": "create_staging",
        "reason": "PermissionError",
    }
    assert "sensitive" not in caught.value.message
    assert not list(data_root.rglob("*.staging-*"))


def test_staged_directory_fsync_failure_is_sanitized_and_precise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    real_fsync = storage._fsync_directory

    def fail_staging_fsync(path: Path) -> None:
        if ".staging-" in path.name:
            raise PermissionError("sensitive staged fsync failure")
        real_fsync(path)

    monkeypatch.setattr(storage, "_fsync_directory", fail_staging_fsync)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_PUBLISH_FAILED"
    assert caught.value.details == {
        "operation": "fsync_staging",
        "reason": "PermissionError",
    }
    assert "sensitive" not in caught.value.message
    final = data_root / "research" / Path(*bundle["artifact_id"].split("/"))
    assert not final.exists()
    assert list(final.parent.glob(f".{final.name}.staging-*")) == []


def test_directory_fsync_permission_failure_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage.os, "name", "posix")
    monkeypatch.setattr(
        storage.os,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PermissionError("sensitive directory fsync failure")
        ),
    )

    with pytest.raises(KokoroError) as caught:
        storage._fsync_directory(tmp_path)

    assert caught.value.code == "RESEARCH_PUBLISH_FAILED"
    assert caught.value.details == {
        "operation": "fsync_directory",
        "reason": "PermissionError",
    }
    assert "sensitive" not in caught.value.message


def test_lock_ancestor_identity_change_before_cutover_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    final = data_root / "research" / Path(*bundle["artifact_id"].split("/"))
    ancestor = final.parents[2]
    real_lstat = Path.lstat
    real_verify = storage._verify_staged
    armed = False

    def changed_ancestor(path: Path) -> Any:
        path_stat = real_lstat(path)
        if armed and path == ancestor:
            return SimpleNamespace(
                st_mode=path_stat.st_mode,
                st_dev=path_stat.st_dev,
                st_ino=path_stat.st_ino + 1,
                st_size=path_stat.st_size,
                st_mtime_ns=path_stat.st_mtime_ns,
                st_nlink=path_stat.st_nlink,
                st_file_attributes=getattr(path_stat, "st_file_attributes", 0) or 0,
            )
        return path_stat

    def arm_after_verification(*args: Any, **kwargs: Any) -> Any:
        nonlocal armed
        identities = real_verify(*args, **kwargs)
        armed = True
        return identities

    monkeypatch.setattr(Path, "lstat", changed_ancestor)
    monkeypatch.setattr(storage, "_verify_staged", arm_after_verification)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "UNSAFE_RESEARCH_PATH"
    assert caught.value.details == {"reason": "publication_lock_changed"}
    assert not final.exists()


def test_metadata_write_failure_preserves_previous_bundle_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    published = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )
    marker_payload = b"previous complete research bundle"
    (published / "previous.txt").write_bytes(marker_payload)
    monkeypatch.setattr(
        storage,
        "_write_canonical_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PermissionError("sensitive metadata write failure")
        ),
    )

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_PUBLISH_FAILED"
    assert caught.value.details == {
        "operation": "write",
        "reason": "PermissionError",
    }
    assert "sensitive" not in caught.value.message
    assert (published / "previous.txt").read_bytes() == marker_payload
    assert list(published.parent.glob(f".{published.name}.staging-*")) == []


def test_permanent_cutover_failure_restores_previous_complete_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, workspace, report, bundle = research_artifacts(tmp_path)
    data_root = tmp_path / "data"
    published = publish_research_bundle(
        data_root, source_root, workspace, report, bundle
    )
    marker_payload = b"previous complete research bundle"
    (published / "previous.txt").write_bytes(marker_payload)
    real_replace = storage.os.replace

    def fail_cutover(source: str | Path, target: str | Path) -> None:
        if ".staging-" in Path(source).name and Path(target) == published:
            raise OSError("sensitive permanent cutover failure")
        real_replace(source, target)

    monkeypatch.setattr(storage.os, "replace", fail_cutover)

    with pytest.raises(KokoroError) as caught:
        publish_research_bundle(data_root, source_root, workspace, report, bundle)

    assert caught.value.code == "RESEARCH_PUBLISH_FAILED"
    assert caught.value.details == {"operation": "replace", "reason": "OSError"}
    assert "sensitive" not in caught.value.message
    assert (published / "previous.txt").read_bytes() == marker_payload
    assert list(published.parent.glob(f".{published.name}.staging-*")) == []
    assert list(published.parent.glob(f".{published.name}.backup-*")) == []
