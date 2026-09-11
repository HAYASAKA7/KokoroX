from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil

import pytest

from kokorox.distribution import suite as suite_module
from kokorox.distribution.suite import (
    SKILL_SUITE_NAMES,
    install_skill_suite,
    remove_skill_suite,
)
from kokorox.errors import KokoroError


REPOSITORY_ROOT = Path.cwd().resolve()
SOURCE_SKILLS = REPOSITORY_ROOT / "skills"


def _copy_source(tmp_path: Path) -> Path:
    source = tmp_path / "source-skills"
    shutil.copytree(SOURCE_SKILLS, source)
    return source


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _tree_times(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (
            int(path.stat().st_mtime_ns),
            int(path.stat().st_ctime_ns),
        )
        for path in root.rglob("*")
    }


def _assert_no_transaction_debris(skills_root: Path) -> None:
    if not skills_root.exists():
        return
    assert not [
        path
        for path in skills_root.rglob("*")
        if path.name.startswith(".kokorox-skill-suite-")
    ]


def _coordination_lock(parent: Path, skills_root: Path) -> Path:
    token = sha256(
        os.path.normcase(str(skills_root)).encode("utf-8")
    ).hexdigest()[:16]
    return parent / f".kokorox-skill-suite-{token}.lock"


def test_installs_the_complete_suite_into_an_explicit_user_root(
    tmp_path: Path,
) -> None:
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "fake-home" / ".agents" / "skills"

    result = install_skill_suite(
        source_root=source,
        skills_root=skills_root,
    )

    assert result["scope"] == "user"
    assert result["dry_run"] is False
    assert result["will_write"] is True
    assert [entry["action"] for entry in result["skills"]] == [
        "install",
        "install",
        "install",
        "install",
    ]
    assert _tree_bytes(skills_root) == _tree_bytes(source)
    lock = _coordination_lock(tmp_path, skills_root)
    assert lock.read_bytes() == b"0"
    _assert_no_transaction_debris(skills_root)


def test_installs_the_complete_suite_into_an_explicit_repo_root(
    tmp_path: Path,
) -> None:
    source = _copy_source(tmp_path)
    repo_root = tmp_path / "consumer-repo"
    repo_root.mkdir()

    result = install_skill_suite(
        source_root=source,
        scope="repo",
        repo_root=repo_root,
    )

    skills_root = repo_root / ".agents" / "skills"
    assert result["scope"] == "repo"
    assert result["skills_root"] == str(skills_root.resolve(strict=True))
    assert _tree_bytes(skills_root) == _tree_bytes(source)
    lock = _coordination_lock(repo_root, skills_root)
    assert lock.read_bytes() == b"0"
    _assert_no_transaction_debris(skills_root)


def test_identical_reinstall_is_a_byte_and_metadata_noop(tmp_path: Path) -> None:
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    install_skill_suite(source_root=source, skills_root=skills_root)
    before_bytes = _tree_bytes(skills_root)
    before_times = _tree_times(skills_root)
    lock = _coordination_lock(tmp_path, skills_root)
    before_lock = lock.stat()

    result = install_skill_suite(source_root=source, skills_root=skills_root)

    assert {entry["action"] for entry in result["skills"]} == {"unchanged"}
    assert result["will_write"] is False
    assert result["dry_run"] is False
    assert _tree_bytes(skills_root) == before_bytes
    assert _tree_times(skills_root) == before_times
    after_lock = lock.stat()
    assert lock.read_bytes() == b"0"
    assert (after_lock.st_mtime_ns, after_lock.st_ctime_ns) == (
        before_lock.st_mtime_ns,
        before_lock.st_ctime_ns,
    )
    _assert_no_transaction_debris(skills_root)


def test_mixed_install_preserves_identical_skills(tmp_path: Path) -> None:
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    skills_root.mkdir()
    for name in SKILL_SUITE_NAMES[:2]:
        shutil.copytree(source / name, skills_root / name)
    before = {
        name: _tree_times(skills_root / name) for name in SKILL_SUITE_NAMES[:2]
    }

    result = install_skill_suite(source_root=source, skills_root=skills_root)

    assert [entry["action"] for entry in result["skills"]] == [
        "unchanged",
        "unchanged",
        "install",
        "install",
    ]
    assert _tree_bytes(skills_root) == _tree_bytes(source)
    assert {
        name: _tree_times(skills_root / name) for name in SKILL_SUITE_NAMES[:2]
    } == before
    _assert_no_transaction_debris(skills_root)


def test_conflict_preflight_publishes_nothing(tmp_path: Path) -> None:
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    skills_root.mkdir()
    conflicting = skills_root / "testing-character-packs"
    shutil.copytree(source / "testing-character-packs", conflicting)
    (conflicting / "SKILL.md").write_text("different\n", encoding="utf-8")

    with pytest.raises(Exception) as raised:
        install_skill_suite(source_root=source, skills_root=skills_root)

    assert getattr(raised.value, "code", None) == "SKILL_SUITE_CONFLICT"
    assert {entry.name for entry in skills_root.iterdir()} == {
        "testing-character-packs"
    }
    assert (conflicting / "SKILL.md").read_text(encoding="utf-8") == (
        "different\n"
    )
    _assert_no_transaction_debris(skills_root)


def test_removal_takes_exactly_the_suite_and_leaves_the_root(
    tmp_path: Path,
) -> None:
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    install_skill_suite(source_root=source, skills_root=skills_root)
    other = skills_root / "someone-elses-skill"
    other.mkdir()
    (other / "SKILL.md").write_text("not ours\n", encoding="utf-8")

    result = remove_skill_suite(source_root=source, skills_root=skills_root)

    assert result["artifact_id"] == "kokorox/skill-suite/removal-plan"
    assert result["dry_run"] is False
    assert result["will_write"] is True
    assert [entry["action"] for entry in result["skills"]] == ["remove"] * 4
    assert {entry.name for entry in skills_root.iterdir()} == {
        "someone-elses-skill"
    }
    assert (other / "SKILL.md").read_text(encoding="utf-8") == "not ours\n"
    assert _coordination_lock(tmp_path, skills_root).read_bytes() == b"0"
    _assert_no_transaction_debris(skills_root)

    # The round trip closes: what removal left behind installs cleanly.
    reinstalled = install_skill_suite(source_root=source, skills_root=skills_root)
    assert [entry["action"] for entry in reinstalled["skills"]] == ["install"] * 4


def test_removing_a_suite_that_is_not_there_changes_nothing(
    tmp_path: Path,
) -> None:
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"

    result = remove_skill_suite(source_root=source, skills_root=skills_root)

    assert [entry["action"] for entry in result["skills"]] == ["absent"] * 4
    assert result["will_write"] is False
    assert not skills_root.exists()
    assert not _coordination_lock(tmp_path, skills_root).exists()


def test_an_edited_skill_refuses_removal_and_nothing_is_taken(
    tmp_path: Path,
) -> None:
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    install_skill_suite(source_root=source, skills_root=skills_root)
    edited = skills_root / "testing-character-packs" / "SKILL.md"
    edited.write_text("my own notes\n", encoding="utf-8")
    before = _tree_bytes(skills_root)

    with pytest.raises(Exception) as raised:
        remove_skill_suite(source_root=source, skills_root=skills_root)

    assert getattr(raised.value, "code", None) == "SKILL_SUITE_REMOVE_CONFLICT"
    assert _tree_bytes(skills_root) == before
    _assert_no_transaction_debris(skills_root)


def test_a_file_added_inside_a_skill_refuses_removal(tmp_path: Path) -> None:
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    install_skill_suite(source_root=source, skills_root=skills_root)
    (skills_root / "using-kokorox" / "notes.md").write_text(
        "mine\n", encoding="utf-8"
    )
    before = _tree_bytes(skills_root)

    with pytest.raises(Exception) as raised:
        remove_skill_suite(source_root=source, skills_root=skills_root)

    assert getattr(raised.value, "code", None) == "SKILL_SUITE_REMOVE_CONFLICT"
    assert _tree_bytes(skills_root) == before
    _assert_no_transaction_debris(skills_root)


def test_removal_dry_run_is_a_byte_and_metadata_noop(tmp_path: Path) -> None:
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    install_skill_suite(source_root=source, skills_root=skills_root)
    before_bytes = _tree_bytes(skills_root)
    before_times = _tree_times(skills_root)

    result = remove_skill_suite(
        source_root=source,
        skills_root=skills_root,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["will_write"] is True
    assert [entry["action"] for entry in result["skills"]] == ["remove"] * 4
    assert _tree_bytes(skills_root) == before_bytes
    assert _tree_times(skills_root) == before_times


def test_a_partial_install_loses_only_what_is_there(tmp_path: Path) -> None:
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    skills_root.mkdir()
    for name in SKILL_SUITE_NAMES[:2]:
        shutil.copytree(source / name, skills_root / name)

    result = remove_skill_suite(source_root=source, skills_root=skills_root)

    assert [entry["action"] for entry in result["skills"]] == [
        "remove",
        "remove",
        "absent",
        "absent",
    ]
    assert list(skills_root.iterdir()) == []
    _assert_no_transaction_debris(skills_root)


def test_a_failure_while_moving_puts_every_skill_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-or-nothing holds until deletion starts: nothing is half removed."""

    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    install_skill_suite(source_root=source, skills_root=skills_root)
    before = _tree_bytes(skills_root)
    real_rename = suite_module._rename_directory_no_replace
    calls = 0

    def failing_third_move(staging: Path, final: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KokoroError(
                "KARC_INSTALL_WRITE_FAILED", "simulated rename failure"
            )
        real_rename(staging, final)

    monkeypatch.setattr(
        suite_module, "_rename_directory_no_replace", failing_third_move
    )

    with pytest.raises(Exception) as raised:
        remove_skill_suite(source_root=source, skills_root=skills_root)

    assert getattr(raised.value, "code", None) == "SKILL_SUITE_REMOVE_FAILED"
    assert _tree_bytes(skills_root) == before
    _assert_no_transaction_debris(skills_root)


def test_removes_a_repository_scope_install(tmp_path: Path) -> None:
    source = _copy_source(tmp_path)
    repo_root = tmp_path / "consumer-repo"
    repo_root.mkdir()
    install_skill_suite(source_root=source, scope="repo", repo_root=repo_root)

    result = remove_skill_suite(
        source_root=source,
        scope="repo",
        repo_root=repo_root,
    )

    skills_root = repo_root / ".agents" / "skills"
    assert result["scope"] == "repo"
    assert [entry["action"] for entry in result["skills"]] == ["remove"] * 4
    assert skills_root.is_dir()
    assert list(skills_root.iterdir()) == []
