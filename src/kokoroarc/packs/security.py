from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from kokoroarc.errors import KokoroError


@dataclass(frozen=True, slots=True)
class PackLimits:
    max_files: int = 128
    max_file_bytes: int = 256_000
    max_total_bytes: int = 2_000_000
    max_depth: int = 6
    max_entries: int = 512


def scan_pack(root: Path, limits: PackLimits) -> list[Path]:
    """Perform a bounded, no-follow pre-scan of a character-pack directory."""
    _validate_limits(limits)
    resolved_root = _validate_root(root)

    files: list[Path] = []
    file_count = 0
    total_bytes = 0
    entry_count = 0
    directories = [resolved_root]

    while directories:
        directory = directories.pop()
        entries, observed_entries = _read_directory(
            directory, limits.max_entries - entry_count
        )
        entry_count += observed_entries
        child_directories: list[Path] = []

        for entry in entries:
            path = Path(entry.path)
            if _entry_is_symlink(entry):
                raise _unsafe_path(path, "symlink")
            if _path_is_junction(path):
                raise _unsafe_path(path, "junction")

            entry_stat = _entry_stat(entry, path)
            if _is_reparse_point(entry_stat):
                raise _unsafe_path(path, "reparse point")

            depth = len(path.relative_to(resolved_root).parts)
            if depth > limits.max_depth:
                raise _limit_exceeded("max_depth")

            resolved_path = _resolve_entry(path)
            if not resolved_path.is_relative_to(resolved_root):
                raise _unsafe_path(path, "outside pack root")

            if stat.S_ISDIR(entry_stat.st_mode):
                child_directories.append(resolved_path)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                raise _unsafe_path(path, "unsupported entry type")

            size = entry_stat.st_size
            if size > limits.max_file_bytes:
                raise _limit_exceeded("max_file_bytes")

            file_count += 1
            if file_count > limits.max_files:
                raise _limit_exceeded("max_files")

            total_bytes += size
            if total_bytes > limits.max_total_bytes:
                raise _limit_exceeded("max_total_bytes")
            files.append(resolved_path)

        directories.extend(reversed(child_directories))

    return sorted(files, key=lambda path: path.as_posix())


def _validate_limits(limits: PackLimits) -> None:
    for field_name in (
        "max_files",
        "max_file_bytes",
        "max_total_bytes",
        "max_depth",
        "max_entries",
    ):
        value = getattr(limits, field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise KokoroError(
                "PACK_LIMIT_INVALID",
                "Pack limits must be non-negative integers.",
                details={"field": field_name},
            )


def _validate_root(root: Path) -> Path:
    try:
        root_stat = root.lstat()
    except FileNotFoundError as exc:
        raise KokoroError(
            "PACK_NOT_FOUND",
            "Character pack root was not found.",
            details={"path": str(root)},
        ) from exc
    except OSError as exc:
        raise _scan_failed(root, exc) from exc

    if stat.S_ISLNK(root_stat.st_mode):
        raise _unsafe_path(root, "symlink root")
    if _path_is_junction(root) or _is_reparse_point(root_stat):
        raise _unsafe_path(root, "junction or reparse root")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise _unsafe_path(root, "root is not a directory")

    try:
        return root.resolve(strict=True)
    except OSError as exc:
        raise _scan_failed(root, exc) from exc


def _read_directory(
    directory: Path, remaining_entries: int
) -> tuple[list[os.DirEntry[str]], int]:
    entries: list[os.DirEntry[str]] = []
    observed_entries = 0
    try:
        with os.scandir(directory) as iterator:
            for entry in iterator:
                observed_entries += 1
                if observed_entries > remaining_entries:
                    raise _limit_exceeded("max_entries")
                entries.append(entry)
    except OSError as exc:
        raise _scan_failed(directory, exc) from exc
    return sorted(entries, key=lambda entry: entry.name), observed_entries


def _entry_is_symlink(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_symlink()
    except OSError as exc:
        raise _scan_failed(Path(entry.path), exc) from exc


def _entry_stat(entry: os.DirEntry[str], path: Path) -> os.stat_result:
    try:
        return entry.stat(follow_symlinks=False)
    except OSError as exc:
        raise _scan_failed(path, exc) from exc


def _path_is_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    if is_junction is None:
        return False
    try:
        return bool(is_junction())
    except OSError as exc:
        raise _scan_failed(path, exc) from exc


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _resolve_entry(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise _scan_failed(path, exc) from exc


def _limit_exceeded(limit: str) -> KokoroError:
    return KokoroError(
        "PACK_LIMIT_EXCEEDED",
        "Character pack filesystem limit exceeded.",
        details={"limit": limit},
    )


def _unsafe_path(path: Path, reason: str) -> KokoroError:
    return KokoroError(
        "UNSAFE_PACK_PATH",
        "Character pack contains an unsafe filesystem path.",
        details={"path": str(path), "reason": reason},
    )


def _scan_failed(path: Path, error: OSError) -> KokoroError:
    return KokoroError(
        "PACK_SCAN_FAILED",
        "Character pack filesystem scan failed.",
        details={"path": str(path), "reason": type(error).__name__},
    )
