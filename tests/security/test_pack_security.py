from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.security import PackLimits, scan_pack


def assert_error_code(root: Path, limits: PackLimits, code: str) -> None:
    with pytest.raises(KokoroError) as raised:
        scan_pack(root, limits)
    assert raised.value.code == code


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
        ("max_files", True),
        ("max_file_bytes", False),
        ("max_total_bytes", 1.5),
        ("max_depth", "1"),
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
