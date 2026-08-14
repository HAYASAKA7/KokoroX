"""Safe loading and canonical binding for declarative pack test fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Mapping, cast

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.packs.loader import parse_yaml_bytes
from kokoroarc.packs.security import PackLimits, scan_pack


_FIXTURE_PATHS = (
    "tests/multilingual.yaml",
    "tests/negative.yaml",
    "tests/positive.yaml",
    "tests/protected-spans.yaml",
)
_FIXTURE_SET = frozenset(_FIXTURE_PATHS)
_IDENTIFIER = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
_LOCALE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
_StatSnapshot = tuple[int, int, int, int, int]
_PathIdentity = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class CorpusLimits:
    """Resource bounds applied while loading the four declarative fixtures."""

    max_file_bytes: int = 64_000
    max_total_bytes: int = 192_000
    max_document_depth: int = 16
    max_scalar_chars: int = 4096
    max_collection_items: int = 256
    max_total_nodes: int = 4096
    max_cases_per_file: int = 128


@dataclass(frozen=True, slots=True)
class PackTestCorpus:
    """An immutable canonical corpus bound to exact source fixture bytes."""

    root: Path
    source_hashes: Mapping[str, str]
    corpus_hash: str
    canonical_bytes: bytes

    def as_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible copy of the corpus artifact."""
        return cast(dict[str, Any], json.loads(self.canonical_bytes))

    def document(self, relative: str) -> dict[str, Any]:
        """Return a detached copy of one fixture document by its fixed path."""
        documents = cast(dict[str, dict[str, Any]], self.as_dict()["documents"])
        return documents[relative]


@dataclass(frozen=True, slots=True)
class _ReadResult:
    contents: bytes
    snapshot: _StatSnapshot
    ancestors: tuple[_StatSnapshot, ...]


def load_test_corpus(
    root: Path, limits: CorpusLimits = CorpusLimits()
) -> PackTestCorpus:
    """Load exactly four bounded YAML fixtures without executing their values."""
    _validate_limits(limits)
    safe_root = _validate_pack_root(root)
    root_chain = _path_chain_identities(safe_root)
    tests_root = safe_root / "tests"
    scan_limits = PackLimits(
        max_files=len(_FIXTURE_PATHS),
        max_file_bytes=limits.max_file_bytes,
        max_total_bytes=limits.max_total_bytes,
        max_depth=1,
        max_entries=len(_FIXTURE_PATHS),
    )
    scanned = scan_pack(tests_root, scan_limits)
    relative_files = _relative_fixture_paths(safe_root, scanned)
    if frozenset(relative_files) != _FIXTURE_SET:
        raise _invalid("fixture_set")

    reads: dict[str, _ReadResult] = {}
    fixture_contents: dict[str, bytes] = {}
    for relative in _FIXTURE_PATHS:
        target = safe_root.joinpath(*relative.split("/"))
        read_result = _read_regular(tests_root, target, limits.max_file_bytes)
        reads[relative] = read_result
        fixture_contents[relative] = read_result.contents

    corpus = _build_test_corpus(safe_root, fixture_contents, limits)

    for relative in _FIXTURE_PATHS:
        target = safe_root.joinpath(*relative.split("/"))
        try:
            final_read = _read_regular(
                tests_root, target, limits.max_file_bytes
            )
        except KokoroError:
            raise _changed("fixture") from None
        initial_read = reads[relative]
        if (
            final_read.contents != initial_read.contents
            or final_read.snapshot != initial_read.snapshot
            or final_read.ancestors != initial_read.ancestors
        ):
            raise _changed("fixture")

    try:
        final_scanned = scan_pack(tests_root, scan_limits)
        final_relative = _relative_fixture_paths(safe_root, final_scanned)
        final_root_chain = _path_chain_identities(safe_root)
    except KokoroError:
        raise _changed("tree") from None
    if (
        final_relative != relative_files
        or final_root_chain != root_chain
        or frozenset(final_relative) != _FIXTURE_SET
    ):
        raise _changed("tree")

    return corpus


def load_test_corpus_from_contents(
    root: Path,
    contents: Mapping[str, bytes],
    limits: CorpusLimits = CorpusLimits(),
) -> PackTestCorpus:
    """Build a corpus from one already-vetted immutable pack snapshot."""
    _validate_limits(limits)
    try:
        test_paths = {
            relative for relative in contents if relative.startswith("tests/")
        }
    except (TypeError, ValueError):
        raise _invalid("fixture_set") from None
    if test_paths != _FIXTURE_SET:
        raise _invalid("fixture_set")

    fixture_contents: dict[str, bytes] = {}
    total_bytes = 0
    for relative in _FIXTURE_PATHS:
        data = contents.get(relative)
        if not isinstance(data, bytes):
            raise _invalid("invalid_fixture_bytes", [relative])
        if len(data) > limits.max_file_bytes:
            raise _filesystem_limit_exceeded("max_file_bytes")
        total_bytes += len(data)
        if total_bytes > limits.max_total_bytes:
            raise _filesystem_limit_exceeded("max_total_bytes")
        fixture_contents[relative] = data
    return _build_test_corpus(Path(root), fixture_contents, limits)


def _build_test_corpus(
    root: Path,
    fixture_contents: Mapping[str, bytes],
    limits: CorpusLimits,
) -> PackTestCorpus:
    documents: dict[str, dict[str, Any]] = {}
    source_hashes: dict[str, str] = {}
    for relative in _FIXTURE_PATHS:
        data = fixture_contents[relative]
        source_hashes[relative] = sha256(data).hexdigest()
        try:
            document = parse_yaml_bytes(data)
        except KokoroError:
            raise _invalid("invalid_yaml") from None
        _enforce_resource_bounds(document, limits)
        documents[relative] = document

    _validate_documents(documents, limits)
    payload = {
        "schema_version": "1.0",
        "documents": documents,
        "source_hashes": source_hashes,
    }
    try:
        encoded = canonical_bytes(payload)
    except KokoroError:
        raise _invalid("non_canonical_data") from None
    return PackTestCorpus(
        root=root,
        source_hashes=MappingProxyType(dict(source_hashes)),
        corpus_hash=sha256(encoded).hexdigest(),
        canonical_bytes=encoded,
    )


def _validate_limits(limits: CorpusLimits) -> None:
    for field_name in (
        "max_file_bytes",
        "max_total_bytes",
        "max_document_depth",
        "max_scalar_chars",
        "max_collection_items",
        "max_total_nodes",
        "max_cases_per_file",
    ):
        value = getattr(limits, field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise KokoroError(
                "PACK_TEST_CORPUS_LIMIT_INVALID",
                "Pack test corpus limits must be positive integers.",
                details={"field": field_name},
            )


def _validate_pack_root(root: Path) -> Path:
    absolute = Path(os.path.abspath(root))
    try:
        initial = absolute.lstat()
        if not stat.S_ISDIR(initial.st_mode) or _redirect(absolute, initial):
            raise KokoroError(
                "UNSAFE_PACK_PATH", "Character pack root is unsafe."
            )
        _path_chain_identities(absolute)
        resolved = absolute.resolve(strict=True)
        final = absolute.lstat()
        resolved_stat = resolved.lstat()
        if (
            _snapshot(initial) != _snapshot(final)
            or _snapshot(initial) != _snapshot(resolved_stat)
            or _redirect(absolute, final)
            or _redirect(resolved, resolved_stat)
        ):
            raise _changed("root")
        return resolved
    except KokoroError:
        raise
    except FileNotFoundError:
        raise KokoroError(
            "PACK_NOT_FOUND", "Character pack root was not found."
        ) from None
    except (OSError, RuntimeError, ValueError):
        raise KokoroError(
            "UNSAFE_PACK_PATH", "Character pack root is unsafe."
        ) from None


def _relative_fixture_paths(root: Path, paths: list[Path]) -> tuple[str, ...]:
    try:
        return tuple(path.relative_to(root).as_posix() for path in paths)
    except ValueError:
        raise KokoroError(
            "UNSAFE_PACK_PATH", "Pack test corpus path is unsafe."
        ) from None


def _read_regular(root: Path, path: Path, max_bytes: int) -> _ReadResult:
    ancestors = _ancestor_snapshots(root, path)
    descriptor: int | None = None
    try:
        initial = path.lstat()
        if (
            not stat.S_ISREG(initial.st_mode)
            or initial.st_nlink != 1
            or _redirect(path, initial)
        ):
            raise KokoroError(
                "UNSAFE_PACK_PATH", "Pack test fixture is unsafe."
            )
        if initial.st_size > max_bytes:
            raise KokoroError(
                "PACK_LIMIT_EXCEEDED",
                "Character pack filesystem limit exceeded.",
                details={"limit": "max_file_bytes"},
            )
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or _snapshot(initial) != _snapshot(opened)
        ):
            raise _changed("fixture")

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
        raise KokoroError(
            "UNSAFE_PACK_PATH", "Pack test fixture is unsafe."
        ) from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                raise _changed("fixture") from None

    try:
        final = path.lstat()
        final_ancestors = _ancestor_snapshots(root, path)
    except KokoroError:
        raise
    except OSError:
        raise _changed("fixture") from None
    if (
        len(contents) != initial.st_size
        or len(contents) > max_bytes
        or _snapshot(initial) != _snapshot(final_opened)
        or _snapshot(initial) != _snapshot(final)
        or _redirect(path, final)
        or final_ancestors != ancestors
    ):
        raise _changed("fixture")
    return _ReadResult(contents, _snapshot(final), final_ancestors)


def _ancestor_snapshots(root: Path, path: Path) -> tuple[_StatSnapshot, ...]:
    try:
        relative = path.relative_to(root)
        current = root
        snapshots: list[_StatSnapshot] = []
        for part in (None, *relative.parts[:-1]):
            if part is not None:
                current /= part
            current_stat = current.lstat()
            if not stat.S_ISDIR(current_stat.st_mode) or _redirect(
                current, current_stat
            ):
                raise KokoroError(
                    "UNSAFE_PACK_PATH", "Pack test fixture ancestor is unsafe."
                )
            snapshots.append(_snapshot(current_stat))
        return tuple(snapshots)
    except KokoroError:
        raise
    except (OSError, ValueError):
        raise KokoroError(
            "UNSAFE_PACK_PATH", "Pack test fixture ancestor is unsafe."
        ) from None


def _path_chain_identities(path: Path) -> tuple[_PathIdentity, ...]:
    try:
        absolute = Path(os.path.abspath(path))
        parts = absolute.parts
        if not parts:
            raise ValueError("empty path")
        current = Path(parts[0])
        identities: list[_PathIdentity] = []
        for part in (None, *parts[1:]):
            if part is not None:
                current /= part
            current_stat = current.lstat()
            if not stat.S_ISDIR(current_stat.st_mode) or _redirect(
                current, current_stat
            ):
                raise KokoroError(
                    "UNSAFE_PACK_PATH", "Character pack ancestor is unsafe."
                )
            identities.append(
                (
                    current_stat.st_dev,
                    current_stat.st_ino,
                    stat.S_IFMT(current_stat.st_mode),
                )
            )
        return tuple(identities)
    except KokoroError:
        raise
    except (OSError, ValueError):
        raise KokoroError(
            "UNSAFE_PACK_PATH", "Character pack ancestor is unsafe."
        ) from None


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
        raise KokoroError(
            "UNSAFE_PACK_PATH", "Pack test corpus path is unsafe."
        ) from None


def _enforce_resource_bounds(value: Any, limits: CorpusLimits) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > limits.max_total_nodes:
            raise _limit_exceeded("max_total_nodes")
        if depth > limits.max_document_depth:
            raise _limit_exceeded("max_document_depth")
        if isinstance(item, str):
            if len(item) > limits.max_scalar_chars:
                raise _limit_exceeded("max_scalar_chars")
        elif isinstance(item, dict):
            if len(item) > limits.max_collection_items:
                raise _limit_exceeded("max_collection_items")
            stack.extend((key, depth + 1) for key in item)
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if len(item) > limits.max_collection_items:
                raise _limit_exceeded("max_collection_items")
            stack.extend((child, depth + 1) for child in item)
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise _invalid("invalid_scalar")


def _validate_documents(
    documents: Mapping[str, dict[str, Any]], limits: CorpusLimits
) -> None:
    _validate_multilingual(documents["tests/multilingual.yaml"])
    _validate_cases(
        documents["tests/negative.yaml"],
        relative="tests/negative.yaml",
        behavior_key="forbidden_behavior",
        final_key="safe_alternative",
        limits=limits,
    )
    _validate_cases(
        documents["tests/positive.yaml"],
        relative="tests/positive.yaml",
        behavior_key="expected_behavior",
        final_key="expected_locales",
        limits=limits,
    )
    _validate_protected_spans(documents["tests/protected-spans.yaml"])


def _validate_multilingual(document: Any) -> None:
    relative = "tests/multilingual.yaml"
    mapping = _mapping(
        document,
        {"intent", "semantic_key", "expected_locales"},
        [relative],
    )
    _identifier(mapping["intent"], [relative, "intent"])
    _identifier(mapping["semantic_key"], [relative, "semantic_key"])
    _locale_list(mapping["expected_locales"], [relative, "expected_locales"])


def _validate_cases(
    document: Any,
    *,
    relative: str,
    behavior_key: str,
    final_key: str,
    limits: CorpusLimits,
) -> None:
    mapping = _mapping(document, {"scenario", "cases"}, [relative])
    _identifier(mapping["scenario"], [relative, "scenario"])
    cases = _list(mapping["cases"], [relative, "cases"])
    if not cases or len(cases) > limits.max_cases_per_file:
        raise _limit_exceeded("max_cases_per_file")
    case_ids: set[str] = set()
    for index, value in enumerate(cases):
        path: list[str | int] = [relative, "cases", index]
        case = _mapping(
            value,
            {"case_id", "user_need", behavior_key, final_key},
            path,
        )
        case_id = _identifier(case["case_id"], [*path, "case_id"])
        if case_id in case_ids:
            raise _invalid("duplicate_case_id", [*path, "case_id"])
        case_ids.add(case_id)
        _text(case["user_need"], [*path, "user_need"])
        _identifier_list(case[behavior_key], [*path, behavior_key])
        if final_key == "safe_alternative":
            _text(case[final_key], [*path, final_key])
        else:
            _locale_mapping(case[final_key], [*path, final_key])


def _validate_protected_spans(document: Any) -> None:
    relative = "tests/protected-spans.yaml"
    mapping = _mapping(
        document,
        {"immutable_spans", "required_warning_id"},
        [relative],
    )
    spans = _list(mapping["immutable_spans"], [relative, "immutable_spans"])
    if not spans:
        raise _invalid("empty_collection", [relative, "immutable_spans"])
    seen: set[str] = set()
    for index, value in enumerate(spans):
        text = _text(value, [relative, "immutable_spans", index])
        if text in seen:
            raise _invalid(
                "duplicate_value", [relative, "immutable_spans", index]
            )
        seen.add(text)
    _identifier(
        mapping["required_warning_id"], [relative, "required_warning_id"]
    )


def _mapping(
    value: Any, expected: set[str], path: list[str | int]
) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise _invalid("invalid_type", path)
    actual = set(value)
    if actual - expected:
        raise _invalid("unknown_keys", path)
    if expected - actual:
        raise _invalid("missing_keys", path)
    return cast(dict[str, Any], value)


def _list(value: Any, path: list[str | int]) -> list[Any]:
    if not isinstance(value, list):
        raise _invalid("invalid_type", path)
    return value


def _text(value: Any, path: list[str | int]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid("invalid_text", path)
    return value


def _identifier(value: Any, path: list[str | int]) -> str:
    text = _text(value, path)
    if _IDENTIFIER.fullmatch(text) is None:
        raise _invalid("invalid_identifier", path)
    return text


def _identifier_list(value: Any, path: list[str | int]) -> None:
    items = _list(value, path)
    if not items:
        raise _invalid("empty_collection", path)
    seen: set[str] = set()
    for index, item in enumerate(items):
        identifier = _identifier(item, [*path, index])
        if identifier in seen:
            raise _invalid("duplicate_value", [*path, index])
        seen.add(identifier)


def _locale_list(value: Any, path: list[str | int]) -> None:
    items = _list(value, path)
    if not items:
        raise _invalid("empty_collection", path)
    seen: set[str] = set()
    for index, item in enumerate(items):
        locale = _locale(item, [*path, index])
        folded = locale.casefold()
        if folded in seen:
            raise _invalid("duplicate_value", [*path, index])
        seen.add(folded)


def _locale_mapping(value: Any, path: list[str | int]) -> None:
    if not isinstance(value, dict) or not value:
        raise _invalid("invalid_type", path)
    seen: set[str] = set()
    for key, item in value.items():
        locale = _locale(key, [*path, "locale"])
        folded = locale.casefold()
        if folded in seen:
            raise _invalid("duplicate_value", [*path, "locale"])
        seen.add(folded)
        _text(item, [*path, locale])


def _locale(value: Any, path: list[str | int]) -> str:
    text = _text(value, path)
    if _LOCALE.fullmatch(text) is None:
        raise _invalid("invalid_locale", path)
    return text


def _invalid(
    reason: str, path: list[str | int] | None = None
) -> KokoroError:
    details: dict[str, Any] = {"reason": reason}
    if path is not None:
        details["path"] = path
    return KokoroError(
        "INVALID_PACK_TEST_CORPUS",
        "Character pack test corpus is invalid.",
        details=details,
    )


def _changed(reason: str) -> KokoroError:
    return KokoroError(
        "PACK_TEST_CORPUS_CHANGED",
        "Character pack test corpus changed while it was being loaded.",
        details={"reason": reason},
    )


def _limit_exceeded(limit: str) -> KokoroError:
    return KokoroError(
        "PACK_TEST_CORPUS_LIMIT_EXCEEDED",
        "Character pack test corpus data limit exceeded.",
        details={"limit": limit},
    )


def _filesystem_limit_exceeded(limit: str) -> KokoroError:
    return KokoroError(
        "PACK_LIMIT_EXCEEDED",
        "Character pack filesystem limit exceeded.",
        details={"limit": limit},
    )
