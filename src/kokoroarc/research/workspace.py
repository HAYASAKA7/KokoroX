"""Confined loading for explicit character-research workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
from types import MappingProxyType
from typing import Any, Mapping, cast

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


_REFERENCE_SECTIONS = (
    ("request", "research-request"),
    ("sources", "research-source-record"),
    ("claims", "research-claim"),
    ("conflicts", "research-conflict"),
    ("coverage", "research-coverage"),
)
_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "conin$",
        "conout$",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)
# Task 1 keeps expected later-stage artifacts beside the workspace fixtures.
# They are inert sidecars and are still included in closed-tree safety snapshots.
_ALLOWED_UNREFERENCED = frozenset({"bundle.json", "validation-report.json"})
_StatSnapshot = tuple[int, int, int, int, int]
_PathIdentity = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class _ReadResult:
    contents: bytes
    snapshot: _StatSnapshot
    ancestors: tuple[_StatSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ResearchWorkspace:
    root: Path
    request: dict[str, Any]
    sources: tuple[dict[str, Any], ...]
    claims: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, Any], ...]
    coverage: dict[str, Any]
    manifest: dict[str, Any]
    file_hashes: Mapping[str, str]
    workspace_hash: str


@dataclass(frozen=True, slots=True)
class ResearchLimits:
    max_files: int = 1024
    max_file_bytes: int = 4 * 1024 * 1024
    max_total_bytes: int = 32 * 1024 * 1024


def load_research_workspace(
    root: Path, schemas: SchemaRegistry, limits: ResearchLimits = ResearchLimits()
) -> ResearchWorkspace:
    """Load a manifest-defined workspace without following untrusted paths."""
    _validate_limits(limits)
    safe_root = _validate_root(root)
    root_chain = _path_chain_identities(safe_root)
    manifest_read = _read_regular(safe_root, safe_root / "workspace.json", limits)
    manifest_bytes = manifest_read.contents
    manifest = _parse_json(manifest_bytes, "manifest")
    _validate_schema(schemas, "research-workspace", manifest, "manifest")

    references = _references(cast(dict[str, Any], manifest))
    scanned = _scan_closed_tree(safe_root, limits)
    permitted = {"workspace.json", *_ALLOWED_UNREFERENCED, *references}
    if set(scanned) - permitted:
        raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "unexpected_file")

    file_hashes: dict[str, str] = {"workspace.json": sha256(manifest_bytes).hexdigest()}
    file_snapshots: dict[str, _ReadResult] = {"workspace.json": manifest_read}
    documents: dict[str, list[dict[str, Any]] | dict[str, Any]] = {}
    for section, schema_name in _REFERENCE_SECTIONS:
        entries = _section_entries(cast(dict[str, Any], manifest), section)
        loaded: list[dict[str, Any]] = []
        for entry in entries:
            relative = cast(str, entry["path"])
            read_result = _read_regular(
                safe_root, safe_root.joinpath(*relative.split("/")), limits
            )
            contents = read_result.contents
            actual_hash = sha256(contents).hexdigest()
            if actual_hash != entry["sha256"]:
                raise _workspace_error(
                    "RESEARCH_WORKSPACE_DIGEST_MISMATCH", "digest_mismatch"
                )
            document = _parse_json(contents, "artifact")
            _validate_schema(schemas, schema_name, document, "artifact")
            file_hashes[relative] = actual_hash
            file_snapshots[relative] = read_result
            loaded.append(cast(dict[str, Any], document))
        documents[section] = loaded[0] if section in {"request", "coverage"} else loaded

    request = cast(dict[str, Any], documents["request"])
    coverage = cast(dict[str, Any], documents["coverage"])
    sources = tuple(
        sorted(
            cast(list[dict[str, Any]], documents["sources"]),
            key=lambda item: item["source_id"],
        )
    )
    claims = tuple(
        sorted(
            cast(list[dict[str, Any]], documents["claims"]),
            key=lambda item: item["claim_id"],
        )
    )
    conflicts = tuple(
        sorted(
            cast(list[dict[str, Any]], documents["conflicts"]),
            key=lambda item: item["conflict_id"],
        )
    )
    for relative, expected_hash in file_hashes.items():
        try:
            final_read = _read_regular(
                safe_root, safe_root.joinpath(*relative.split("/")), limits
            )
        except KokoroError:
            raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "file") from None
        initial_read = file_snapshots[relative]
        if (
            sha256(final_read.contents).hexdigest() != expected_hash
            or final_read.snapshot != initial_read.snapshot
            or final_read.ancestors != initial_read.ancestors
        ):
            raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "file")
    assembled = {
        "request": request,
        "sources": list(sources),
        "claims": list(claims),
        "conflicts": list(conflicts),
        "coverage": coverage,
    }
    workspace_hash = sha256(canonical_bytes(assembled)).hexdigest()
    _verify_closed_tree_unchanged(
        safe_root,
        limits,
        initial_tree=scanned,
        initial_root_chain=root_chain,
    )
    return ResearchWorkspace(
        root=safe_root,
        request=request,
        sources=sources,
        claims=claims,
        conflicts=conflicts,
        coverage=coverage,
        manifest=cast(dict[str, Any], manifest),
        file_hashes=MappingProxyType(file_hashes),
        workspace_hash=workspace_hash,
    )


def _validate_limits(limits: ResearchLimits) -> None:
    for field in ("max_files", "max_file_bytes", "max_total_bytes"):
        value = getattr(limits, field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise _workspace_error("RESEARCH_WORKSPACE_LIMIT_INVALID", field)


def _validate_root(root: Path) -> Path:
    absolute_root = Path(os.path.abspath(root))
    try:
        root_stat = absolute_root.lstat()
    except FileNotFoundError:
        raise _workspace_error("RESEARCH_WORKSPACE_NOT_FOUND", "root") from None
    except (OSError, ValueError):
        raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "root") from None
    try:
        if not stat.S_ISDIR(root_stat.st_mode) or _redirect(absolute_root, root_stat):
            raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "root")
        _path_chain_identities(absolute_root)
        safe_root = absolute_root.resolve(strict=True)
        final_stat = absolute_root.lstat()
        resolved_stat = safe_root.lstat()
        if (
            _snapshot(root_stat) != _snapshot(final_stat)
            or _snapshot(root_stat) != _snapshot(resolved_stat)
            or _redirect(absolute_root, final_stat)
            or _redirect(safe_root, resolved_stat)
        ):
            raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "root")
        return safe_root
    except KokoroError:
        raise
    except FileNotFoundError:
        raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "root") from None
    except (OSError, RuntimeError, ValueError):
        raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "root") from None


def _references(manifest: dict[str, Any]) -> set[str]:
    references: set[str] = set()
    normalized: set[str] = set()
    for section, _schema in _REFERENCE_SECTIONS:
        for entry in _section_entries(manifest, section):
            relative = entry.get("path")
            if not isinstance(relative, str) or not _safe_relative_path(relative):
                raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "reference")
            key = relative.casefold()
            if key in normalized:
                raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "duplicate_reference")
            references.add(relative)
            normalized.add(key)
    return references


def _section_entries(manifest: dict[str, Any], section: str) -> list[dict[str, Any]]:
    value = manifest[section]
    entries = value if isinstance(value, list) else [value]
    return [cast(dict[str, Any], entry) for entry in entries]


def _safe_relative_path(value: str) -> bool:
    if not value or "\\" in value or "\x00" in value or ":" in value or value != value.strip():
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root:
        return False
    parts = value.split("/")
    if any(not part or part in {".", ".."} or _unsafe_component(part) for part in parts):
        return False
    return value == posix.as_posix() and value.endswith(".json")


def _unsafe_component(component: str) -> bool:
    stem = component[:-5] if component.casefold().endswith(".json") else component
    if (
        stem.endswith((".", " "))
        or component.endswith((".", " "))
        or any(ord(character) < 32 or character in '*?"<>|' for character in component)
    ):
        return True
    return component.split(".", 1)[0].rstrip(" ").casefold() in _RESERVED


def _scan_closed_tree(
    root: Path, limits: ResearchLimits
) -> dict[str, _StatSnapshot]:
    files: dict[str, _StatSnapshot] = {}
    total_bytes = 0
    directories = [root]
    while directories:
        directory = directories.pop()
        _assert_safe_directory(directory)
        try:
            entries = sorted(list(os.scandir(directory)), key=lambda entry: entry.name)
        except OSError:
            raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "scan") from None
        for entry in entries:
            path = Path(entry.path)
            try:
                path_stat = path.lstat()
            except OSError:
                raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "scan") from None
            if _redirect(path, path_stat):
                raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "redirect")
            if stat.S_ISDIR(path_stat.st_mode):
                directories.append(path)
                continue
            if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
                raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "entry")
            relative = path.relative_to(root).as_posix()
            if not _safe_relative_path(relative):
                raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "entry")
            files[relative] = _snapshot(path_stat)
            if len(files) > limits.max_files:
                raise _limit_error("max_files")
            if path_stat.st_size > limits.max_file_bytes:
                raise _limit_error("max_file_bytes")
            total_bytes += path_stat.st_size
            if total_bytes > limits.max_total_bytes:
                raise _limit_error("max_total_bytes")
    return dict(sorted(files.items()))


def _verify_closed_tree_unchanged(
    root: Path,
    limits: ResearchLimits,
    *,
    initial_tree: Mapping[str, _StatSnapshot],
    initial_root_chain: tuple[_PathIdentity, ...],
) -> None:
    try:
        final_tree = _scan_closed_tree(root, limits)
        final_root_chain = _path_chain_identities(root)
    except KokoroError:
        raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "tree") from None
    if final_tree != initial_tree or final_root_chain != initial_root_chain:
        raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "tree")


def _assert_safe_directory(path: Path) -> None:
    try:
        path_stat = path.lstat()
    except OSError:
        raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "directory") from None
    if not stat.S_ISDIR(path_stat.st_mode) or _redirect(path, path_stat):
        raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "directory")


def _read_regular(root: Path, path: Path, limits: ResearchLimits) -> _ReadResult:
    ancestors = _ancestor_identities(root, path)
    try:
        initial = path.lstat()
        if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1 or _redirect(path, initial):
            raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "file")
        if initial.st_size > limits.max_file_bytes:
            raise _limit_error("max_file_bytes")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
    except KokoroError:
        raise
    except OSError:
        raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "file") from None
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or _snapshot(initial) != _snapshot(opened)
        ):
            raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "file")
        chunks: list[bytes] = []
        remaining = initial.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        contents = b"".join(chunks)
        final_opened = os.fstat(descriptor)
    except KokoroError:
        raise
    except OSError:
        raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "file") from None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "file") from None
    try:
        final = path.lstat()
    except OSError:
        raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "file") from None
    final_ancestors = _ancestor_identities(root, path)
    if (
        len(contents) != initial.st_size
        or len(contents) > limits.max_file_bytes
        or _snapshot(initial) != _snapshot(final_opened)
        or _snapshot(initial) != _snapshot(final)
        or _redirect(path, final)
        or final.st_size != initial.st_size
        or final_ancestors != ancestors
    ):
        raise _workspace_error("RESEARCH_WORKSPACE_CHANGED", "file")
    return _ReadResult(
        contents=contents,
        snapshot=_snapshot(final),
        ancestors=final_ancestors,
    )


def _ancestor_identities(root: Path, path: Path) -> tuple[_StatSnapshot, ...]:
    try:
        relative = path.relative_to(root)
        current = root
        identities = []
        for _part in relative.parts[:-1]:
            path_stat = current.lstat()
            if not stat.S_ISDIR(path_stat.st_mode) or _redirect(current, path_stat):
                raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "ancestor")
            identities.append(_snapshot(path_stat))
            current = current / _part
        path_stat = current.lstat()
        if not stat.S_ISDIR(path_stat.st_mode) or _redirect(current, path_stat):
            raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "ancestor")
        identities.append(_snapshot(path_stat))
        return tuple(identities)
    except KokoroError:
        raise
    except (OSError, ValueError):
        raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "ancestor") from None


def _path_chain_identities(path: Path) -> tuple[_PathIdentity, ...]:
    try:
        absolute = Path(os.path.abspath(path))
        parts = absolute.parts
        if not parts:
            raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "ancestor")
        current = Path(parts[0])
        identities: list[_PathIdentity] = []
        for part in (None, *parts[1:]):
            if part is not None:
                current /= part
            path_stat = current.lstat()
            if not stat.S_ISDIR(path_stat.st_mode) or _redirect(current, path_stat):
                raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "ancestor")
            identities.append(
                (
                    path_stat.st_dev,
                    path_stat.st_ino,
                    stat.S_IFMT(path_stat.st_mode),
                )
            )
        return tuple(identities)
    except KokoroError:
        raise
    except (OSError, ValueError):
        raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "ancestor") from None


def _snapshot(path_stat: os.stat_result) -> _StatSnapshot:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        stat.S_IFMT(path_stat.st_mode),
        path_stat.st_size,
        path_stat.st_mtime_ns,
    )


def _redirect(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    junction = getattr(path, "is_junction", None)
    try:
        return bool(attributes & reparse) or bool(junction and junction())
    except OSError:
        raise _workspace_error("RESEARCH_WORKSPACE_UNSAFE", "redirect") from None


def _parse_json(contents: bytes, stage: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise _workspace_error("RESEARCH_WORKSPACE_INVALID", stage) from None
    if not isinstance(value, dict):
        raise _workspace_error("RESEARCH_WORKSPACE_INVALID", stage)
    return cast(dict[str, Any], value)


def _validate_schema(
    schemas: SchemaRegistry,
    name: str,
    value: dict[str, Any],
    stage: str,
) -> None:
    try:
        schemas.validate(name, value)
    except KokoroError as error:
        if error.code != "SCHEMA_VALIDATION_FAILED":
            raise
        raise _workspace_error("RESEARCH_WORKSPACE_INVALID", stage) from None


def _workspace_error(code: str, reason: str) -> KokoroError:
    return KokoroError(
        code,
        "Research workspace could not be loaded.",
        details={"reason": reason},
    )


def _limit_error(limit: str) -> KokoroError:
    return KokoroError(
        "RESEARCH_WORKSPACE_LIMIT_EXCEEDED",
        "Research workspace filesystem limit exceeded.",
        details={"limit": limit},
    )
