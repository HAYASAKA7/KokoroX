from __future__ import annotations

import os
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs import security as pack_security
from kokoroarc.packs.security import PackLimits, scan_pack


def assert_error_code(root: Path, limits: PackLimits, code: str) -> None:
    with pytest.raises(KokoroError) as raised:
        scan_pack(root, limits)
    assert raised.value.code == code


def test_pack_limits_default_entry_budget() -> None:
    assert PackLimits().max_entries == 512


def test_scan_rejects_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("The current Windows account cannot create symlinks")
    with pytest.raises(KokoroError) as raised:
        scan_pack(tmp_path, PackLimits())
    assert raised.value.code == "UNSAFE_PACK_PATH"


def test_scan_rejects_regular_file_hardlinked_outside_pack(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.yaml"
    outside.write_text("secret: true", encoding="utf-8")
    inside = tmp_path / "identity.yaml"
    try:
        os.link(outside, inside)
    except OSError:
        pytest.skip("hardlink creation is unavailable")

    with pytest.raises(KokoroError) as raised:
        scan_pack(tmp_path, PackLimits())

    assert raised.value.code == "UNSAFE_PACK_PATH"


def test_scan_rejects_oversized_file(tmp_path: Path) -> None:
    (tmp_path / "large.yaml").write_bytes(b"x" * 33)
    with pytest.raises(KokoroError) as raised:
        scan_pack(tmp_path, PackLimits(max_file_bytes=32))
    assert raised.value.code == "PACK_LIMIT_EXCEEDED"


def test_scan_returns_resolved_files_in_deterministic_order(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    second = nested / "b.yaml"
    first = tmp_path / "A.yaml"
    second.write_text("second", encoding="utf-8")
    first.write_text("first", encoding="utf-8")

    assert scan_pack(tmp_path, PackLimits()) == [first.resolve(), second.resolve()]


def test_scan_accepts_complete_rin_pack_under_default_limits() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    pack_root = (repository_root / "characters" / "original" / "rin-aster").resolve(
        strict=True
    )
    expected_relative_paths = {
        "behavior.yaml",
        "character.yaml",
        "derived-profile.yaml",
        "evidence.yaml",
        "expressions.yaml",
        "growth.yaml",
        "identity.yaml",
        "locales/en-US.yaml",
        "locales/ja-JP.yaml",
        "locales/zh-CN.yaml",
        "overrides.yaml",
        "scenarios/debugging.yaml",
        "tests/multilingual.yaml",
        "tests/negative.yaml",
        "tests/positive.yaml",
        "tests/protected-spans.yaml",
    }

    files = scan_pack(pack_root, PackLimits())

    assert len(files) == 16
    assert files == sorted(files, key=lambda path: path.as_posix())
    assert all(path.is_absolute() for path in files)
    assert all(path == path.resolve(strict=True) and path.is_file() for path in files)
    assert all(path.is_relative_to(pack_root) for path in files)
    assert {
        path.relative_to(pack_root).as_posix() for path in files
    } == expected_relative_paths


def test_file_size_limit_boundary(tmp_path: Path) -> None:
    file_path = tmp_path / "pack.yaml"
    file_path.write_bytes(b"x" * 32)
    assert scan_pack(tmp_path, PackLimits(max_file_bytes=32)) == [file_path.resolve()]

    file_path.write_bytes(b"x" * 33)
    assert_error_code(
        tmp_path, PackLimits(max_file_bytes=32), "PACK_LIMIT_EXCEEDED"
    )


def test_file_count_limit_boundary(tmp_path: Path) -> None:
    first = tmp_path / "a.yaml"
    first.write_text("a", encoding="utf-8")
    assert scan_pack(tmp_path, PackLimits(max_files=1)) == [first.resolve()]

    (tmp_path / "b.yaml").write_text("b", encoding="utf-8")
    assert_error_code(tmp_path, PackLimits(max_files=1), "PACK_LIMIT_EXCEEDED")


@pytest.mark.parametrize("entry_kind", ["file", "directory"])
def test_zero_entry_limit_allows_only_empty_root(
    tmp_path: Path, entry_kind: str
) -> None:
    assert scan_pack(tmp_path, PackLimits(max_entries=0)) == []

    child = tmp_path / "child"
    if entry_kind == "file":
        child.write_bytes(b"")
    else:
        child.mkdir()
    assert_error_code(tmp_path, PackLimits(max_entries=0), "PACK_LIMIT_EXCEEDED")


def test_total_entry_limit_boundary_counts_files_and_directories(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    nested_file = directory / "nested.yaml"
    nested_file.write_bytes(b"")
    root_file = tmp_path / "root.yaml"
    root_file.write_bytes(b"")

    assert scan_pack(tmp_path, PackLimits(max_entries=3)) == [
        nested_file.resolve(),
        root_file.resolve(),
    ]

    (tmp_path / "extra-directory").mkdir()
    assert_error_code(tmp_path, PackLimits(max_entries=3), "PACK_LIMIT_EXCEEDED")


def test_total_entry_limit_rejects_wide_directory(tmp_path: Path) -> None:
    for index in range(6):
        (tmp_path / f"directory-{index}").mkdir()

    assert_error_code(tmp_path, PackLimits(max_entries=5), "PACK_LIMIT_EXCEEDED")


def test_total_entry_limit_bounds_empty_directory_tree(tmp_path: Path) -> None:
    for index in range(3):
        parent = tmp_path / f"branch-{index}"
        parent.mkdir()
        (parent / "empty-child").mkdir()

    limits = PackLimits(
        max_entries=5,
        max_files=0,
        max_file_bytes=0,
        max_total_bytes=0,
    )
    assert_error_code(tmp_path, limits, "PACK_LIMIT_EXCEEDED")


def test_entry_limit_stops_scandir_after_first_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CountingScandir:
        def __init__(self) -> None:
            self.entries = [
                SimpleNamespace(name=f"entry-{index}") for index in range(10)
            ]
            self.index = 0
            self.next_calls = 0
            self.exited = False

        def __enter__(self) -> CountingScandir:
            return self

        def __exit__(self, *_args: object) -> None:
            self.exited = True

        def __iter__(self) -> CountingScandir:
            return self

        def __next__(self) -> SimpleNamespace:
            if self.index == len(self.entries):
                raise StopIteration
            entry = self.entries[self.index]
            self.index += 1
            self.next_calls += 1
            return entry

    iterator = CountingScandir()
    monkeypatch.setattr(os, "scandir", lambda _path: iterator)

    assert_error_code(tmp_path, PackLimits(max_entries=2), "PACK_LIMIT_EXCEEDED")
    assert iterator.next_calls == 3
    assert iterator.exited is True


def test_total_size_limit_boundary(tmp_path: Path) -> None:
    first = tmp_path / "a.yaml"
    second = tmp_path / "b.yaml"
    first.write_bytes(b"abc")
    second.write_bytes(b"de")
    assert scan_pack(tmp_path, PackLimits(max_total_bytes=5)) == [
        first.resolve(),
        second.resolve(),
    ]

    second.write_bytes(b"def")
    assert_error_code(
        tmp_path, PackLimits(max_total_bytes=5), "PACK_LIMIT_EXCEEDED"
    )


def test_depth_counts_relative_path_parts(tmp_path: Path) -> None:
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)
    file_path = nested / "pack.yaml"
    file_path.write_text("content", encoding="utf-8")

    assert scan_pack(tmp_path, PackLimits(max_depth=3)) == [file_path.resolve()]
    assert_error_code(tmp_path, PackLimits(max_depth=2), "PACK_LIMIT_EXCEEDED")


def test_zero_limits_allow_only_an_empty_root(tmp_path: Path) -> None:
    zero_limits = PackLimits(
        max_files=0,
        max_file_bytes=0,
        max_total_bytes=0,
        max_depth=0,
    )
    assert scan_pack(tmp_path, zero_limits) == []

    (tmp_path / "entry").mkdir()
    assert_error_code(tmp_path, zero_limits, "PACK_LIMIT_EXCEEDED")


def test_scan_rejects_missing_root(tmp_path: Path) -> None:
    assert_error_code(tmp_path / "missing", PackLimits(), "PACK_NOT_FOUND")


def test_scan_rejects_regular_file_as_root(tmp_path: Path) -> None:
    root_file = tmp_path / "pack.yaml"
    root_file.write_text("content", encoding="utf-8")
    assert_error_code(root_file, PackLimits(), "UNSAFE_PACK_PATH")


def test_scan_rejects_root_symlink_before_following_it(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    root_link = tmp_path / "root-link"
    try:
        root_link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"The current account cannot create directory symlinks: {exc}")

    assert_error_code(root_link, PackLimits(), "UNSAFE_PACK_PATH")


def test_scan_rejects_symlink_to_in_root_file(tmp_path: Path) -> None:
    target = tmp_path / "target.yaml"
    target.write_text("content", encoding="utf-8")
    link = tmp_path / "alias.yaml"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"The current account cannot create file symlinks: {exc}")

    assert_error_code(tmp_path, PackLimits(), "UNSAFE_PACK_PATH")


def test_scan_rejects_symlinked_directory_without_traversing_it(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.yaml").write_text("secret", encoding="utf-8")
    linked_directory = tmp_path / "linked-directory"
    try:
        linked_directory.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"The current account cannot create directory symlinks: {exc}")

    assert_error_code(tmp_path, PackLimits(), "UNSAFE_PACK_PATH")


def test_scan_rejects_root_reported_as_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pack_security, "_path_is_junction", lambda _path: True)
    assert_error_code(tmp_path, PackLimits(), "UNSAFE_PACK_PATH")


def test_scan_rejects_entry_reported_as_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "entry.yaml").write_bytes(b"")
    calls = 0

    def report_second_path_as_junction(_path: Path) -> bool:
        nonlocal calls
        calls += 1
        return calls == 2

    monkeypatch.setattr(pack_security, "_path_is_junction", report_second_path_as_junction)
    assert_error_code(tmp_path, PackLimits(), "UNSAFE_PACK_PATH")


def test_junction_detection_failure_is_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny_junction_check(_path: Path) -> bool:
        raise OSError("sensitive operating system detail")

    monkeypatch.setattr(Path, "is_junction", deny_junction_check, raising=False)

    with pytest.raises(KokoroError) as raised:
        scan_pack(tmp_path, PackLimits())
    assert raised.value.code == "PACK_SCAN_FAILED"
    assert raised.value.details == {"path": str(tmp_path), "reason": "OSError"}
    assert "sensitive operating system detail" not in raised.value.message
    assert "sensitive operating system detail" not in repr(raised.value.details)


def test_scan_rejects_entry_with_windows_reparse_attribute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "entry.yaml").write_bytes(b"")
    reparse_flag = 0x400
    fake_stat = SimpleNamespace(
        st_mode=stat.S_IFREG,
        st_size=0,
        st_file_attributes=reparse_flag,
    )
    monkeypatch.setattr(
        pack_security.stat,
        "FILE_ATTRIBUTE_REPARSE_POINT",
        reparse_flag,
        raising=False,
    )
    monkeypatch.setattr(pack_security, "_entry_stat", lambda _entry, _path: fake_stat)

    assert_error_code(tmp_path, PackLimits(), "UNSAFE_PACK_PATH")


def test_scan_rejects_windows_junction(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junctions are unavailable on this platform")
    if not hasattr(Path, "is_junction"):
        pytest.skip("This Python version cannot identify Windows junctions")
    pytest.skip("The Python standard library has no safe junction creation API")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("max_files", -1),
        ("max_file_bytes", -1),
        ("max_total_bytes", -1),
        ("max_depth", -1),
        ("max_entries", -1),
        ("max_files", True),
        ("max_file_bytes", False),
        ("max_total_bytes", 1.5),
        ("max_depth", "1"),
        ("max_entries", True),
    ],
)
def test_scan_rejects_invalid_limits(
    tmp_path: Path, field_name: str, value: object
) -> None:
    limits = replace(PackLimits(), **{field_name: value})
    assert_error_code(tmp_path, limits, "PACK_LIMIT_INVALID")


def test_scan_rejects_unsupported_filesystem_entry(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("The platform has no portable FIFO creation API")
    fifo = tmp_path / "pipe"
    try:
        os.mkfifo(fifo)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"The platform cannot create a FIFO fixture: {exc}")

    assert_error_code(tmp_path, PackLimits(), "UNSAFE_PACK_PATH")


@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_scan_wraps_scandir_filesystem_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[OSError],
) -> None:
    resolved_root = tmp_path.resolve()

    def deny_scan(_path: Path) -> None:
        raise error_type("sensitive operating system detail")

    monkeypatch.setattr(os, "scandir", deny_scan)

    with pytest.raises(KokoroError) as raised:
        scan_pack(tmp_path, PackLimits())
    assert raised.value.code == "PACK_SCAN_FAILED"
    assert raised.value.details == {
        "path": str(resolved_root),
        "reason": error_type.__name__,
    }
    assert "sensitive operating system detail" not in raised.value.message
    assert "sensitive operating system detail" not in repr(raised.value.details)
