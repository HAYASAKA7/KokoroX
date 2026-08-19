from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil

import pytest

from kokoroarc.errors import KokoroError
import kokoroarc.distribution.suite as suite


REPOSITORY_ROOT = Path.cwd().resolve()
SOURCE_SKILLS = REPOSITORY_ROOT / "skills"


def _copy_source(tmp_path: Path) -> Path:
    source = tmp_path / "source-skills"
    shutil.copytree(SOURCE_SKILLS, source)
    return source


def _assert_code(code: str, callback) -> KokoroError:
    with pytest.raises(KokoroError) as raised:
        callback()
    assert raised.value.code == code
    return raised.value


def _transaction_debris(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [
        path
        for path in root.rglob("*")
        if path.name.startswith(".kokoroarc-skill-suite-")
        and not path.name.endswith(".lock")
    ]


def test_source_symlink_file_is_rejected_when_supported(tmp_path: Path) -> None:
    source = _copy_source(tmp_path)
    target = source / "using-kokoroarc" / "references" / "runtime-contract.md"
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("The current account cannot create file symlinks")

    _assert_code(
        "SKILL_SUITE_SOURCE_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=tmp_path / "installed",
        ),
    )
    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_source_hardlink_alias_is_rejected_when_supported(tmp_path: Path) -> None:
    source = _copy_source(tmp_path)
    original = source / "using-kokoroarc" / "SKILL.md"
    alias = source / "using-kokoroarc" / "references" / "runtime-contract.md"
    alias.unlink()
    try:
        os.link(original, alias)
    except OSError:
        pytest.skip("The current filesystem cannot create hardlinks")

    _assert_code(
        "SKILL_SUITE_SOURCE_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=tmp_path / "installed",
        ),
    )


def test_source_mutation_during_file_read_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    target = source / "using-kokoroarc" / "SKILL.md"
    real_open = suite.os.open
    real_fstat = suite.os.fstat
    target_descriptor: int | None = None
    target_stats = 0

    def open_file(path, *args, **kwargs):
        nonlocal target_descriptor
        descriptor = real_open(path, *args, **kwargs)
        if Path(path) == target:
            target_descriptor = descriptor
        return descriptor

    def stat_file(descriptor: int):
        nonlocal target_stats
        if descriptor == target_descriptor:
            target_stats += 1
            if target_stats == 2:
                target.write_bytes(target.read_bytes() + b"\n")
        return real_fstat(descriptor)

    monkeypatch.setattr(suite.os, "open", open_file)
    monkeypatch.setattr(suite.os, "fstat", stat_file)

    _assert_code(
        "SKILL_SUITE_SOURCE_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=tmp_path / "installed",
        ),
    )


def test_byte_identical_source_root_replacement_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    displaced = tmp_path / "source-skills-displaced"
    real_capture = suite._capture_closed_tree
    replaced = False

    def capture(root: Path, *args, **kwargs):
        nonlocal replaced
        result = real_capture(root, *args, **kwargs)
        if not replaced:
            root.rename(displaced)
            shutil.copytree(displaced, root)
            replaced = True
        return result

    monkeypatch.setattr(suite, "_capture_closed_tree", capture)

    _assert_code(
        "SKILL_SUITE_SOURCE_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=tmp_path / "installed",
        ),
    )


def test_byte_identical_source_subdirectory_replacement_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    target = source / "using-kokoroarc"
    displaced = source / "using-kokoroarc-displaced"
    real_capture = suite._capture_closed_tree
    replaced = False

    def capture(root: Path, *args, **kwargs):
        nonlocal replaced
        result = real_capture(root, *args, **kwargs)
        if not replaced:
            target.rename(displaced)
            shutil.copytree(displaced, target)
            replaced = True
        return result

    monkeypatch.setattr(suite, "_capture_closed_tree", capture)

    _assert_code(
        "SKILL_SUITE_SOURCE_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=tmp_path / "installed",
        ),
    )


def test_source_directory_reported_as_junction_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    marked = source / "researching-characters"
    real_probe = getattr(Path, "is_junction", lambda _path: False)

    def is_junction(path: Path) -> bool:
        return path == marked or bool(real_probe(path))

    monkeypatch.setattr(Path, "is_junction", is_junction, raising=False)

    _assert_code(
        "SKILL_SUITE_SOURCE_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=tmp_path / "installed",
        ),
    )


def test_source_special_file_is_rejected_when_supported(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("The current platform cannot create FIFO nodes")
    source = _copy_source(tmp_path)
    target = source / "using-kokoroarc" / "references" / "runtime-contract.md"
    target.unlink()
    os.mkfifo(target)

    _assert_code(
        "SKILL_SUITE_SOURCE_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=tmp_path / "installed",
        ),
    )


def test_destination_redirect_is_rejected_without_writing_outside(
    tmp_path: Path,
) -> None:
    source = _copy_source(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    redirect = tmp_path / "redirect"
    try:
        redirect.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("The current account cannot create directory symlinks")

    _assert_code(
        "SKILL_SUITE_PATH_INVALID",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=redirect,
        ),
    )
    assert list(outside.iterdir()) == []


def test_destination_ancestor_reported_as_junction_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    marked = tmp_path / "marked"
    marked.mkdir()
    real_probe = getattr(Path, "is_junction", lambda _path: False)

    def is_junction(path: Path) -> bool:
        return path == marked or bool(real_probe(path))

    monkeypatch.setattr(Path, "is_junction", is_junction, raising=False)

    _assert_code(
        "SKILL_SUITE_PATH_INVALID",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=marked / "skills",
        ),
    )
    assert list(marked.iterdir()) == []


def test_hardlinked_installed_skill_file_is_rejected_when_supported(
    tmp_path: Path,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    shutil.copytree(source, destination)
    target = destination / "using-kokoroarc" / "SKILL.md"
    outside = tmp_path / "outside.md"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        os.link(outside, target)
    except OSError:
        pytest.skip("The current filesystem cannot create hardlinks")

    _assert_code(
        "SKILL_SUITE_PATH_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=destination,
        ),
    )


def test_invalid_agent_metadata_is_rejected_before_destination_creation(
    tmp_path: Path,
) -> None:
    source = _copy_source(tmp_path)
    metadata = source / "using-kokoroarc" / "agents" / "openai.yaml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8") + "unknown: true\n",
        encoding="utf-8",
    )
    destination = tmp_path / "installed"

    _assert_code(
        "SKILL_SUITE_SOURCE_INVALID",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert not destination.exists()


def test_source_change_after_staging_rolls_back_every_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    real_stage = suite._stage_skill
    changed = False

    def stage(*args, **kwargs):
        nonlocal changed
        result = real_stage(*args, **kwargs)
        if not changed:
            skill_file = source / "using-kokoroarc" / "SKILL.md"
            skill_file.write_bytes(skill_file.read_bytes() + b"\n")
            changed = True
        return result

    monkeypatch.setattr(suite, "_stage_skill", stage)

    _assert_code(
        "SKILL_SUITE_SOURCE_CHANGED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert not destination.exists()
    assert not _transaction_debris(tmp_path)


def test_source_invalidation_after_staging_reports_source_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    real_stage = suite._stage_skill
    changed = False

    def stage(*args, **kwargs):
        nonlocal changed
        result = real_stage(*args, **kwargs)
        if not changed:
            (source / "using-kokoroarc" / "SKILL.md").unlink()
            changed = True
        return result

    monkeypatch.setattr(suite, "_stage_skill", stage)

    _assert_code(
        "SKILL_SUITE_SOURCE_CHANGED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert not destination.exists()
    assert not _transaction_debris(tmp_path)


def test_destination_root_move_after_staging_reports_identity_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    displaced = tmp_path / "installed-displaced"
    real_stage = suite._stage_skill
    moved = False

    def stage(*args, **kwargs):
        nonlocal moved
        result = real_stage(*args, **kwargs)
        if not moved:
            destination.rename(displaced)
            destination.mkdir()
            moved = True
        return result

    monkeypatch.setattr(suite, "_stage_skill", stage)

    _assert_code(
        "SKILL_SUITE_ROLLBACK_FAILED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert _transaction_debris(displaced)


def test_existing_destination_replacement_before_lock_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    destination.mkdir()
    displaced = tmp_path / "installed-displaced"
    real_acquire = suite._acquire_suite_lock

    def acquire(lock_parent: Path, target: Path):
        destination.rename(displaced)
        destination.mkdir()
        return real_acquire(lock_parent, target)

    monkeypatch.setattr(suite, "_acquire_suite_lock", acquire)

    _assert_code(
        "SKILL_SUITE_DESTINATION_CHANGED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert list(destination.iterdir()) == []
    assert list(displaced.iterdir()) == []


def test_identical_destination_change_after_planning_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    shutil.copytree(source, destination)
    real_plan = suite._plan_actions
    calls = 0

    def plan(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = real_plan(*args, **kwargs)
        if calls == 1:
            target = destination / "using-kokoroarc" / "SKILL.md"
            target.write_bytes(target.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(suite, "_plan_actions", plan)

    _assert_code(
        "SKILL_SUITE_DESTINATION_CHANGED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert calls == 1


def test_byte_identical_skill_replacement_after_planning_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    shutil.copytree(source, destination)
    target = destination / "using-kokoroarc"
    displaced = destination / "using-kokoroarc-displaced"
    real_plan = suite._plan_actions
    calls = 0

    def plan(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = real_plan(*args, **kwargs)
        if calls == 1:
            target.rename(displaced)
            shutil.copytree(displaced, target)
        return result

    monkeypatch.setattr(suite, "_plan_actions", plan)

    _assert_code(
        "SKILL_SUITE_DESTINATION_CHANGED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert target.exists()
    assert displaced.exists()


def test_final_fsync_rechecks_preexisting_unchanged_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    destination.mkdir()
    unchanged = destination / "using-kokoroarc"
    shutil.copytree(source / "using-kokoroarc", unchanged)
    target = unchanged / "SKILL.md"
    real_fsync = suite._fsync_directory
    destination_fsyncs = 0

    def fsync(path: Path) -> None:
        nonlocal destination_fsyncs
        real_fsync(path)
        if path == destination:
            destination_fsyncs += 1
            if destination_fsyncs == 4:
                target.write_bytes(target.read_bytes() + b"\n")

    monkeypatch.setattr(suite, "_fsync_directory", fsync)

    _assert_code(
        "SKILL_SUITE_DESTINATION_CHANGED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert target.read_bytes().endswith(b"\n\n")
    assert sorted(path.name for path in destination.iterdir()) == [
        "using-kokoroarc"
    ]


def test_lock_contention_fails_without_creating_destination(
    tmp_path: Path,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    lock_parent = suite._nearest_existing_directory(destination.parent)

    with suite._acquire_suite_lock(lock_parent, destination):
        _assert_code(
            "SKILL_SUITE_INSTALL_FAILED",
            lambda: suite.install_skill_suite(
                source_root=source,
                skills_root=destination,
            ),
        )
    assert not destination.exists()
    assert not _transaction_debris(tmp_path)


def test_malformed_persistent_lock_is_rejected_without_installing(
    tmp_path: Path,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    lock_parent = suite._nearest_existing_directory(destination.parent)
    token = sha256(
        os.path.normcase(str(destination)).encode("utf-8")
    ).hexdigest()[:16]
    lock_path = lock_parent / f".kokoroarc-skill-suite-{token}.lock"
    lock_path.write_bytes(b"not-a-suite-lock")

    _assert_code(
        "SKILL_SUITE_PATH_INVALID",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert not destination.exists()
    assert lock_path.read_bytes() == b"not-a-suite-lock"


def test_lock_parent_replacement_before_transaction_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    parent = tmp_path / "destination-parent"
    parent.mkdir()
    destination = parent / "skills"
    displaced = tmp_path / "destination-parent-displaced"
    real_acquire = suite._acquire_suite_lock

    def acquire(lock_parent: Path, target: Path):
        lock_parent.rename(displaced)
        lock_parent.mkdir()
        return real_acquire(lock_parent, target)

    monkeypatch.setattr(suite, "_acquire_suite_lock", acquire)

    _assert_code(
        "SKILL_SUITE_DESTINATION_CHANGED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert displaced.exists()
    assert parent.exists()
    assert not destination.exists()


def test_lock_identity_is_rechecked_before_and_after_cutover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    real_require = suite._require_suite_lock
    calls = 0

    def require(lock) -> None:
        nonlocal calls
        calls += 1
        real_require(lock)

    monkeypatch.setattr(suite, "_require_suite_lock", require)

    suite.install_skill_suite(source_root=source, skills_root=destination)

    assert calls >= 3


@pytest.mark.parametrize("failed_publish", [1, 2, 3, 4])
def test_publish_failure_rolls_back_every_generated_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_publish: int,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    real_publish = suite._publish_skill
    calls = 0

    def publish(item) -> None:
        nonlocal calls
        calls += 1
        if calls == failed_publish:
            raise KokoroError(
                "SKILL_SUITE_INSTALL_FAILED",
                "injected publish failure",
            )
        real_publish(item)

    monkeypatch.setattr(suite, "_publish_skill", publish)

    _assert_code(
        "SKILL_SUITE_INSTALL_FAILED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert not destination.exists()
    assert not _transaction_debris(tmp_path)


def test_staged_validation_failure_removes_generated_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    real_require = suite._require_staged_skill
    calls = 0

    def require(item, root: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KokoroError(
                "SKILL_SUITE_DESTINATION_CHANGED",
                "injected staged validation failure",
            )
        real_require(item, root)

    monkeypatch.setattr(suite, "_require_staged_skill", require)

    _assert_code(
        "SKILL_SUITE_DESTINATION_CHANGED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert not destination.exists()
    assert not _transaction_debris(tmp_path)


def test_staging_directory_fsync_failure_removes_generated_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    real_fsync = suite._fsync_directory

    def fsync(path: Path) -> None:
        if path.name == "references" and path.parent.name.startswith(
            ".kokoroarc-skill-suite-"
        ):
            raise OSError("injected directory fsync failure")
        real_fsync(path)

    monkeypatch.setattr(suite, "_fsync_directory", fsync)

    _assert_code(
        "SKILL_SUITE_INSTALL_FAILED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert not destination.exists()
    assert not _transaction_debris(tmp_path)


def test_destination_mutation_during_verification_is_not_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    real_require = suite._require_installed_bytes
    mutated: Path | None = None

    def require(source_snapshot, skill_name, root: Path, limits) -> None:
        nonlocal mutated
        if root.name == "using-kokoroarc" and root.parent == destination:
            mutated = root / "foreign.txt"
            mutated.write_text("foreign\n", encoding="utf-8")
        real_require(source_snapshot, skill_name, root, limits)

    monkeypatch.setattr(suite, "_require_installed_bytes", require)

    _assert_code(
        "SKILL_SUITE_ROLLBACK_FAILED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert mutated is not None
    assert mutated.read_text(encoding="utf-8") == "foreign\n"


def test_foreign_target_appearance_is_preserved_while_staging_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    foreign: Path | None = None

    def publish(item) -> None:
        nonlocal foreign
        foreign = item.final
        foreign.mkdir()
        (foreign / "foreign.txt").write_text("foreign\n", encoding="utf-8")
        raise KokoroError(
            "SKILL_SUITE_DESTINATION_CHANGED",
            "injected target appearance",
        )

    monkeypatch.setattr(suite, "_publish_skill", publish)

    _assert_code(
        "SKILL_SUITE_DESTINATION_CHANGED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert foreign is not None
    assert (foreign / "foreign.txt").read_text(encoding="utf-8") == "foreign\n"
    assert not _transaction_debris(destination)


def test_staging_replacement_is_not_deleted_and_reports_rollback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    replacement: Path | None = None
    displaced: Path | None = None

    def publish(item) -> None:
        nonlocal replacement, displaced
        displaced = item.staging.with_name(item.staging.name + "-displaced")
        item.staging.rename(displaced)
        item.staging.mkdir()
        replacement = item.staging
        (replacement / "foreign.txt").write_text("foreign\n", encoding="utf-8")
        raise KokoroError(
            "SKILL_SUITE_INSTALL_FAILED",
            "injected staging replacement",
        )

    monkeypatch.setattr(suite, "_publish_skill", publish)

    _assert_code(
        "SKILL_SUITE_ROLLBACK_FAILED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert replacement is not None and replacement.exists()
    assert displaced is not None and displaced.exists()
    assert (replacement / "foreign.txt").read_text(encoding="utf-8") == "foreign\n"


def test_partial_staging_write_failure_leaves_no_generated_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    real_write = suite._write_exclusive_file
    calls = 0

    def write(path: Path, payload: bytes):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise OSError("injected write failure")
        return real_write(path, payload)

    monkeypatch.setattr(suite, "_write_exclusive_file", write)

    _assert_code(
        "SKILL_SUITE_INSTALL_FAILED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    assert not destination.exists()
    assert not _transaction_debris(tmp_path)


def test_staging_identity_capture_failure_is_explicit_and_deletes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    destination = tmp_path / "installed"
    real_capture = suite._capture_directory_identity

    def capture(path: Path):
        if path.name.startswith(".kokoroarc-skill-suite-using-kokoroarc-"):
            raise KokoroError(
                "SKILL_SUITE_PATH_INVALID",
                "injected identity capture failure",
            )
        return real_capture(path)

    monkeypatch.setattr(suite, "_capture_directory_identity", capture)

    _assert_code(
        "SKILL_SUITE_CLEANUP_FAILED",
        lambda: suite.install_skill_suite(
            source_root=source,
            skills_root=destination,
        ),
    )
    residual = _transaction_debris(destination)
    assert len(residual) == 1
    assert residual[0].is_dir()
