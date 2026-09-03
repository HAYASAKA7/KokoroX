from __future__ import annotations

from dataclasses import dataclass
import errno
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from typing import Any, Literal

from kokoroarc.distribution.installer import _rename_directory_no_replace
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.packs.loader import parse_yaml_bytes


SKILL_SUITE_NAMES = (
    "using-kokoroarc",
    "authoring-character-packs",
    "researching-characters",
    "testing-character-packs",
)

AGENT_PROFILE_NAMES = (
    "openai",
    "claude",
    "codex",
    "cursor",
    "gemini",
    "copilot",
    "kimi",
    "deepseek",
    "qwen",
    "generic",
)

_SKILL_REFERENCE_FILES = {
    "using-kokoroarc": "references/runtime-contract.md",
    "authoring-character-packs": "references/authoring-contract.md",
    "researching-characters": "references/research-contract.md",
    "testing-character-packs": "references/testing-contract.md",
}

_AGENT_PROFILE_FILES = frozenset(
    f"agents/{profile_name}.yaml" for profile_name in AGENT_PROFILE_NAMES
)

_SKILL_FILES = {
    skill_name: frozenset({"SKILL.md", reference_file} | _AGENT_PROFILE_FILES)
    for skill_name, reference_file in _SKILL_REFERENCE_FILES.items()
}
_EXPECTED_FILES = frozenset(
    f"{skill_name}/{relative}"
    for skill_name, relative_files in _SKILL_FILES.items()
    for relative in relative_files
)
_EXPECTED_DIRECTORIES = frozenset(
    directory
    for skill_name in SKILL_SUITE_NAMES
    for directory in (
        skill_name,
        f"{skill_name}/agents",
        f"{skill_name}/references",
    )
)
_ALLOWED_SKILL_METADATA = frozenset(
    {"name", "description", "license", "allowed-tools", "metadata"}
)
_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_LOCK_RETRY_DELAYS = (0.0, 0.001, 0.002, 0.004)
_LOCK_CONTENTION_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "EACCES", None),
        getattr(errno, "EAGAIN", None),
    )
    if value is not None
)
_LOCK_CONTENTION_WINERRORS = frozenset({32, 33})


@dataclass(frozen=True, slots=True)
class SkillSuiteLimits:
    max_files: int = len(_EXPECTED_FILES)
    max_file_bytes: int = 512 * 1024
    max_total_bytes: int = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int
    file_type: int
    size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _CapturedFile:
    relative: str
    payload: bytes
    identity: _FileIdentity


@dataclass(frozen=True, slots=True)
class _SuiteSnapshot:
    root: Path
    files: tuple[_CapturedFile, ...]
    source_tree_sha256: str
    skill_sha256: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True, slots=True)
class _TargetSkillState:
    name: str
    root_identity: _DirectoryIdentity | None
    files: tuple[_CapturedFile, ...] | None


@dataclass(frozen=True, slots=True)
class _StagedSkill:
    name: str
    staging: Path
    final: Path
    root_identity: _DirectoryIdentity
    directory_identities: tuple[tuple[str, _DirectoryIdentity], ...]
    file_identities: tuple[tuple[str, _FileIdentity], ...]


@dataclass(slots=True)
class _SuiteLock:
    path: Path
    descriptor: int
    identity: _FileIdentity
    held: bool = True

    def __enter__(self) -> _SuiteLock:
        return self

    def __exit__(
        self,
        _exception_type: object,
        _exception: object,
        _traceback: object,
    ) -> None:
        self.release()

    def release(self) -> None:
        if not self.held:
            return
        try:
            _unlock_descriptor(self.descriptor)
        finally:
            try:
                os.close(self.descriptor)
            except OSError:
                pass
            self.held = False


def resolve_skill_suite_source(source_root: Path | None = None) -> Path:
    return _resolve_source_snapshot(source_root, SkillSuiteLimits()).root


def preview_skill_suite_install(
    *,
    source_root: Path | None = None,
    scope: Literal["user", "repo"] = "user",
    repo_root: Path | None = None,
    skills_root: Path | None = None,
    limits: SkillSuiteLimits = SkillSuiteLimits(),
) -> dict[str, Any]:
    source = _resolve_source_snapshot(source_root, limits)
    target = _resolve_skills_root(
        scope=scope,
        repo_root=repo_root,
        skills_root=skills_root,
    )
    _reject_source_target_overlap(source.root, target)
    actions = _plan_actions(source, target, limits)
    return _result_document(
        source=source,
        target=target,
        scope=scope,
        actions=actions,
        dry_run=True,
    )


def install_skill_suite(
    *,
    source_root: Path | None = None,
    scope: Literal["user", "repo"] = "user",
    repo_root: Path | None = None,
    skills_root: Path | None = None,
    dry_run: bool = False,
    limits: SkillSuiteLimits = SkillSuiteLimits(),
) -> dict[str, Any]:
    if dry_run:
        return preview_skill_suite_install(
            source_root=source_root,
            scope=scope,
            repo_root=repo_root,
            skills_root=skills_root,
            limits=limits,
        )
    source = _resolve_source_snapshot(source_root, limits)
    target = _resolve_skills_root(
        scope=scope,
        repo_root=repo_root,
        skills_root=skills_root,
    )
    _reject_source_target_overlap(source.root, target)
    initial_target_identity = _capture_optional_directory_identity(target)
    initial_skill_states = _capture_target_skill_states(target, limits)
    actions = _plan_actions(source, target, limits)
    _require_target_skill_states(
        target,
        limits,
        initial_skill_states,
        actions,
        phase="planning",
        require_missing=True,
    )
    created_ancestors: tuple[tuple[Path, _DirectoryIdentity], ...] = ()
    staged: list[_StagedSkill] = []
    published: list[_StagedSkill] = []
    try:
        lock_parent = _nearest_existing_directory(target.parent)
        lock_parent_identity = _capture_directory_identity(lock_parent)
        with _acquire_suite_lock(lock_parent, target) as transaction_lock:
            _require_destination_directory(
                lock_parent,
                lock_parent_identity,
                "lock acquisition",
            )
            _require_suite_lock(transaction_lock)
            created_ancestors = _ensure_directory_chain(target.parent)
            _require_initial_target_identity(target, initial_target_identity)
            target_created = (
                _ensure_directory_chain(target)
                if initial_target_identity is None
                else ()
            )
            created_ancestors = (*created_ancestors, *target_created)
            target_identity = _capture_directory_identity(target)
            _require_destination_directory(
                target,
                target_identity,
                "installation",
            )
            _require_actions_unchanged(
                source,
                target,
                limits,
                actions,
                "installation",
            )
            _require_target_skill_states(
                target,
                limits,
                initial_skill_states,
                actions,
                phase="installation",
                require_missing=True,
            )
            for name, action in actions:
                if action == "install":
                    staged.append(_stage_skill(source, target, name, limits))
            _require_source_unchanged(source, limits)
            _require_destination_directory(
                lock_parent,
                lock_parent_identity,
                "publication",
            )
            _require_destination_directory(
                target,
                target_identity,
                "publication",
            )
            _require_suite_lock(transaction_lock)
            _require_actions_unchanged(
                source,
                target,
                limits,
                actions,
                "publication",
            )
            for item in staged:
                _require_staged_skill(item, item.staging)
                published.append(item)
                _publish_skill(item)
            for item in published:
                _require_staged_skill(item, item.final)
                _require_installed_bytes(source, item.name, item.final, limits)
            _require_destination_directory(
                lock_parent,
                lock_parent_identity,
                "verification",
            )
            _require_destination_directory(
                target,
                target_identity,
                "verification",
            )
            _require_suite_lock(transaction_lock)
            _fsync_directory(target)
            _require_destination_directory(
                lock_parent,
                lock_parent_identity,
                "final verification",
            )
            _require_destination_directory(
                target,
                target_identity,
                "final verification",
            )
            _require_suite_lock(transaction_lock)
            for item in published:
                _require_staged_skill(item, item.final)
            _require_target_skill_states(
                target,
                limits,
                initial_skill_states,
                actions,
                phase="final verification",
                require_missing=False,
            )
            _require_complete_install(source, target, limits)
            _require_destination_directory(
                lock_parent,
                lock_parent_identity,
                "final verification",
            )
            _require_destination_directory(
                target,
                target_identity,
                "final verification",
            )
            _require_suite_lock(transaction_lock)
    except BaseException as error:
        cleanup_error = _rollback_transaction(staged, published)
        if cleanup_error is not None:
            raise _error(
                "SKILL_SUITE_ROLLBACK_FAILED",
                "Skill suite rollback could not remove generated directories.",
                reason=_reason(cleanup_error),
            ) from error
        _remove_created_ancestors(created_ancestors)
        if isinstance(error, KokoroError):
            raise
        raise _error(
            "SKILL_SUITE_INSTALL_FAILED",
            "The KokoroArc Skill suite could not be installed.",
            reason=type(error).__name__,
        ) from error
    return _result_document(
        source=source,
        target=target,
        scope=scope,
        actions=actions,
        dry_run=False,
    )


def _resolve_source_snapshot(
    source_root: Path | None,
    limits: SkillSuiteLimits,
) -> _SuiteSnapshot:
    _validate_limits(limits)
    if source_root is not None:
        return _capture_suite_source(Path(source_root), limits)
    candidates = _source_candidates(None)
    last_error: KokoroError | None = None
    snapshots: dict[Path, _SuiteSnapshot] = {}
    for candidate in candidates:
        try:
            snapshot = _capture_suite_source(candidate, limits)
        except KokoroError as error:
            last_error = error
            if error.code == "SKILL_SUITE_LIMIT_EXCEEDED":
                raise
        else:
            snapshots[snapshot.root] = snapshot
    if len(snapshots) == 1:
        return next(iter(snapshots.values()))
    if len(snapshots) > 1:
        raise _source_error(
            "Multiple complete KokoroArc Skill suite sources were discovered."
        )
    if last_error is not None:
        raise last_error
    raise _error(
        "SKILL_SUITE_SOURCE_INVALID",
        "The KokoroArc Skill suite source is unavailable or incomplete.",
    )


def _source_candidates(source_root: Path | None) -> tuple[Path, ...]:
    if source_root is not None:
        return (Path(source_root),)
    module = Path(__file__).absolute()
    candidates = [module.parents[2] / "share" / "kokoroarc" / "skills"]
    if module.parents[2].name.casefold() == "src":
        candidates.insert(0, module.parents[3] / "skills")
    return tuple(candidates)


def _capture_suite_source(
    candidate: Path,
    limits: SkillSuiteLimits,
) -> _SuiteSnapshot:
    root = _safe_existing_directory(candidate, source=True)
    root_identity = _capture_source_directory_identity(root)
    files = _capture_closed_tree(root, limits, source=True)
    if _capture_source_directory_identity(root) != root_identity:
        raise _source_error("Skill suite source identity changed during capture.")
    confirmed_files = _capture_closed_tree(root, limits, source=True)
    if confirmed_files != files:
        raise _source_error("Skill suite source changed during capture.")
    if _capture_source_directory_identity(root) != root_identity:
        raise _source_error("Skill suite source identity changed during capture.")
    payloads = {captured.relative: captured.payload for captured in files}
    for skill_name in SKILL_SUITE_NAMES:
        _validate_skill_metadata(skill_name, payloads)
    skill_hashes = tuple(
        (skill_name, _skill_digest(skill_name, files))
        for skill_name in SKILL_SUITE_NAMES
    )
    return _SuiteSnapshot(
        root=root,
        files=files,
        source_tree_sha256=_tree_digest(files),
        skill_sha256=skill_hashes,
    )


def _capture_closed_tree(
    root: Path,
    limits: SkillSuiteLimits,
    *,
    source: bool,
    expected_files: frozenset[str] = _EXPECTED_FILES,
    expected_directories: frozenset[str] = _EXPECTED_DIRECTORIES,
    relative_prefix: str = "",
    inventory_conflict: bool = False,
) -> tuple[_CapturedFile, ...]:
    expected_nodes = expected_files | expected_directories
    pending = [(root, "")]
    captured: list[_CapturedFile] = []
    seen_directories: set[str] = set()
    total_bytes = 0
    while pending:
        directory, prefix = pending.pop()
        try:
            scanner = os.scandir(directory)
        except OSError as error:
            raise _tree_error(
                source,
                "Skill directory could not be scanned.",
            ) from error
        try:
            for entry in scanner:
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                normalized = relative.replace("\\", "/")
                if normalized not in expected_nodes:
                    raise _inventory_error(
                        source,
                        inventory_conflict,
                        "Skill suite contains an unknown file or directory.",
                    )
                path = Path(entry.path)
                try:
                    # Path.lstat carries the stable link count on Windows;
                    # Python's DirEntry.stat may report st_nlink as zero.
                    linked = path.lstat()
                except OSError as error:
                    raise _tree_error(
                        source,
                        "Skill path could not be inspected.",
                    ) from error
                if _is_redirect(path, linked):
                    raise _tree_error(source, "Skill path is a redirect.")
                if stat.S_ISDIR(linked.st_mode):
                    if normalized not in expected_directories:
                        raise _inventory_error(
                            source,
                            inventory_conflict,
                            "Skill path has the wrong type.",
                        )
                    seen_directories.add(normalized)
                    pending.append((path, normalized))
                    continue
                if not stat.S_ISREG(linked.st_mode):
                    raise _tree_error(source, "Skill path is not a regular file.")
                if normalized not in expected_files:
                    raise _inventory_error(
                        source,
                        inventory_conflict,
                        "Skill path has the wrong type.",
                    )
                if int(linked.st_nlink) != 1 or linked.st_mode & 0o111:
                    raise _tree_error(source, "Skill file metadata is unsafe.")
                if len(captured) >= limits.max_files:
                    raise _limit_error("max_files")
                payload, identity = _read_stable_file(
                    path,
                    linked,
                    limits.max_file_bytes,
                    source=source,
                )
                total_bytes += len(payload)
                if total_bytes > limits.max_total_bytes:
                    raise _limit_error("max_total_bytes")
                try:
                    payload.decode("utf-8")
                except UnicodeError as error:
                    raise _inventory_error(
                        source,
                        inventory_conflict,
                        "Skill file is not valid UTF-8.",
                    ) from error
                stored_relative = (
                    f"{relative_prefix}/{normalized}"
                    if relative_prefix
                    else normalized
                )
                captured.append(_CapturedFile(stored_relative, payload, identity))
        finally:
            scanner.close()
    captured_relatives = {
        item.relative.removeprefix(f"{relative_prefix}/")
        if relative_prefix
        else item.relative
        for item in captured
    }
    if captured_relatives != expected_files:
        raise _inventory_error(
            source,
            inventory_conflict,
            "Skill suite file inventory is incomplete.",
        )
    if seen_directories != expected_directories:
        raise _inventory_error(
            source,
            inventory_conflict,
            "Skill suite directory inventory is incomplete.",
        )
    return tuple(sorted(captured, key=lambda item: item.relative))


def _read_stable_file(
    path: Path,
    linked: os.stat_result,
    limit: int,
    *,
    source: bool,
) -> tuple[bytes, _FileIdentity]:
    if linked.st_size > limit:
        raise _limit_error("max_file_bytes")
    descriptor = -1
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _file_identity(linked) != _file_identity(opened):
            raise _tree_error(source, "Skill file changed before it was read.")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            payload = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        final = path.lstat()
    except KokoroError:
        raise
    except OSError as error:
        raise _tree_error(source, "Skill file could not be read safely.") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    values = (linked, opened, after, final)
    if (
        len(payload) > limit
        or len(payload) != int(opened.st_size)
        or len({_file_identity(value) for value in values}) != 1
        or any(int(value.st_nlink) != 1 for value in values)
        or any(_is_redirect(path, value) for value in (linked, final))
    ):
        raise _tree_error(source, "Skill file changed while it was read.")
    return payload, _file_identity(linked)


def _validate_skill_metadata(
    skill_name: str,
    payloads: dict[str, bytes],
) -> None:
    skill_bytes = payloads[f"{skill_name}/SKILL.md"]
    try:
        text = skill_bytes.decode("utf-8")
    except UnicodeError as error:
        raise _source_error("Skill metadata is not valid UTF-8.") from error
    lines = text.splitlines()
    if not lines or lines[0] != "---" or lines.count("---") != 2:
        raise _source_error("SKILL.md frontmatter delimiters are invalid.")
    closing = lines.index("---", 1)
    try:
        frontmatter = parse_yaml_bytes(
            ("\n".join(lines[1:closing]) + "\n").encode("utf-8")
        )
    except KokoroError as error:
        raise _source_error("SKILL.md frontmatter is invalid.") from error
    if set(frontmatter) - _ALLOWED_SKILL_METADATA:
        raise _source_error("SKILL.md frontmatter contains unknown fields.")
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if (
        not isinstance(name, str)
        or name != skill_name
        or len(name) > 64
        or _SKILL_NAME.fullmatch(name) is None
    ):
        raise _source_error("SKILL.md name does not match its directory.")
    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description) > 1024
        or "<" in description
        or ">" in description
    ):
        raise _source_error("SKILL.md description is invalid.")
    for profile_name in AGENT_PROFILE_NAMES:
        agent_path = f"{skill_name}/agents/{profile_name}.yaml"
        try:
            agent = parse_yaml_bytes(payloads[agent_path])
        except KokoroError as error:
            raise _source_error("Skill agent metadata is invalid.") from error
        interface = agent.get("interface")
        if set(agent) - {"interface", "policy", "dependencies"}:
            raise _source_error("Skill agent metadata contains unknown fields.")
        if not isinstance(interface, dict):
            raise _source_error("Skill agent interface metadata is invalid.")
        if set(interface) != {
            "display_name",
            "short_description",
            "default_prompt",
        }:
            raise _source_error("Skill agent interface metadata is invalid.")
        for field in ("display_name", "short_description", "default_prompt"):
            value = interface.get(field)
            if not isinstance(value, str) or not value.strip():
                raise _source_error("Skill agent interface metadata is invalid.")


def _resolve_skills_root(
    *,
    scope: str,
    repo_root: Path | None,
    skills_root: Path | None,
) -> Path:
    if scope not in {"user", "repo"}:
        raise _path_error("Skill suite scope must be user or repo.")
    if scope == "repo":
        if repo_root is None or skills_root is not None:
            raise _path_error("Repository scope requires only an explicit repo root.")
        lexical_repo = Path(repo_root)
        _require_clean_absolute_path(lexical_repo, "Repository root")
        resolved_repo = _safe_existing_directory(lexical_repo, source=False)
        target = resolved_repo / ".agents" / "skills"
    else:
        if repo_root is not None:
            raise _path_error("User scope does not accept a repository root.")
        if skills_root is None:
            try:
                target = Path.home() / ".agents" / "skills"
            except (OSError, RuntimeError) as error:
                raise _path_error("User home could not be resolved.") from error
        else:
            target = Path(skills_root)
            _require_clean_absolute_path(target, "User Skill root")
    try:
        absolute = target.absolute()
    except (OSError, RuntimeError, ValueError) as error:
        raise _path_error("Skill root could not be made absolute.") from error
    _validate_existing_ancestors(absolute)
    return absolute


def _safe_existing_directory(path: Path, *, source: bool) -> Path:
    absolute = path.absolute()
    try:
        linked = absolute.lstat()
    except OSError as error:
        raise _tree_error(source, "Skill directory does not exist.") from error
    if not stat.S_ISDIR(linked.st_mode) or _is_redirect(absolute, linked):
        raise _tree_error(source, "Skill directory is unsafe.")
    _validate_existing_ancestors(absolute, source=source)
    try:
        confirmed = absolute.lstat()
    except OSError as error:
        raise _tree_error(source, "Skill directory could not be confirmed.") from error
    if (
        not stat.S_ISDIR(confirmed.st_mode)
        or _is_redirect(absolute, confirmed)
        or _directory_identity(confirmed) != _directory_identity(linked)
    ):
        raise _tree_error(source, "Skill directory changed during validation.")
    return absolute


def _validate_existing_ancestors(path: Path, *, source: bool = False) -> None:
    existing: list[Path] = []
    current = path
    while True:
        try:
            current.lstat()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise _tree_error(source, "Skill path could not be inspected.") from error
        else:
            existing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for ancestor in reversed(existing):
        try:
            linked = ancestor.lstat()
        except OSError as error:
            raise _tree_error(source, "Skill path could not be inspected.") from error
        if not stat.S_ISDIR(linked.st_mode) or _is_redirect(ancestor, linked):
            raise _tree_error(source, "Skill path has an unsafe ancestor.")


def _reject_source_target_overlap(source: Path, target: Path) -> None:
    if (
        source == target
        or source.is_relative_to(target)
        or target.is_relative_to(source)
    ):
        raise _path_error("Skill source and destination must be disjoint.")


def _plan_actions(
    source: _SuiteSnapshot,
    target: Path,
    limits: SkillSuiteLimits,
) -> tuple[tuple[str, str], ...]:
    actions: list[tuple[str, str]] = []
    source_files = {item.relative: item.payload for item in source.files}
    for skill_name in SKILL_SUITE_NAMES:
        skill_target = target / skill_name
        try:
            linked = skill_target.lstat()
        except FileNotFoundError:
            actions.append((skill_name, "install"))
            continue
        except OSError as error:
            raise _path_error(
                "Installed Skill target could not be inspected."
            ) from error
        if not stat.S_ISDIR(linked.st_mode) or _is_redirect(skill_target, linked):
            raise _path_error("Installed Skill target is unsafe.")
        try:
            installed = _capture_skill_target(skill_target, skill_name, limits)
        except KokoroError as error:
            if error.code == "SKILL_SUITE_PATH_INVALID":
                raise
            raise _error(
                "SKILL_SUITE_CONFLICT",
                "An installed Skill differs from the KokoroArc suite.",
            ) from error
        prefix = f"{skill_name}/"
        expected = {
            relative.removeprefix(prefix): payload
            for relative, payload in source_files.items()
            if relative.startswith(prefix)
        }
        actual = {
            item.relative.removeprefix(prefix): item.payload for item in installed
        }
        if actual != expected:
            raise _error(
                "SKILL_SUITE_CONFLICT",
                "An installed Skill differs from the KokoroArc suite.",
            )
        actions.append((skill_name, "unchanged"))
    return tuple(actions)


def _capture_skill_target(
    root: Path,
    skill_name: str,
    limits: SkillSuiteLimits,
) -> tuple[_CapturedFile, ...]:
    try:
        return _capture_closed_tree(
            root,
            limits,
            source=False,
            expected_files=_SKILL_FILES[skill_name],
            expected_directories=frozenset({"agents", "references"}),
            relative_prefix=skill_name,
            inventory_conflict=True,
        )
    except KokoroError as error:
        if error.code == "SKILL_SUITE_LIMIT_EXCEEDED":
            raise _conflict_error() from error
        raise


def _capture_target_skill_states(
    target: Path,
    limits: SkillSuiteLimits,
) -> tuple[_TargetSkillState, ...]:
    states: list[_TargetSkillState] = []
    for skill_name in SKILL_SUITE_NAMES:
        root = target / skill_name
        linked = _lstat_optional(root)
        if linked is None:
            states.append(_TargetSkillState(skill_name, None, None))
            continue
        if not stat.S_ISDIR(linked.st_mode) or _is_redirect(root, linked):
            raise _path_error("Installed Skill target is unsafe.")
        before = _capture_directory_identity(root)
        files = _capture_skill_target(root, skill_name, limits)
        after = _capture_directory_identity(root)
        if before != after:
            raise _path_error("Installed Skill target changed during capture.")
        states.append(_TargetSkillState(skill_name, before, files))
    return tuple(states)


def _require_target_skill_states(
    target: Path,
    limits: SkillSuiteLimits,
    expected: tuple[_TargetSkillState, ...],
    actions: tuple[tuple[str, str], ...],
    *,
    phase: str,
    require_missing: bool,
) -> None:
    try:
        current = _capture_target_skill_states(target, limits)
    except KokoroError as error:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            f"The Skill destination changed during {phase}.",
            reason=error.code,
        ) from error
    expected_by_name = {state.name: state for state in expected}
    current_by_name = {state.name: state for state in current}
    for skill_name, action in actions:
        if action == "unchanged":
            matches = current_by_name[skill_name] == expected_by_name[skill_name]
        else:
            matches = (
                not require_missing
                or current_by_name[skill_name].root_identity is None
            )
        if not matches:
            raise _error(
                "SKILL_SUITE_DESTINATION_CHANGED",
                f"The Skill destination changed during {phase}.",
            )


def _nearest_existing_directory(path: Path) -> Path:
    current = path
    while True:
        try:
            linked = current.lstat()
        except FileNotFoundError:
            if current.parent == current:
                raise _path_error("No existing Skill destination ancestor exists.")
            current = current.parent
            continue
        except OSError as error:
            raise _path_error(
                "Skill destination ancestry could not be inspected."
            ) from error
        if not stat.S_ISDIR(linked.st_mode) or _is_redirect(current, linked):
            raise _path_error("Skill destination ancestry is unsafe.")
        return current


def _ensure_directory_chain(
    path: Path,
) -> tuple[tuple[Path, _DirectoryIdentity], ...]:
    missing: list[Path] = []
    current = path
    while True:
        try:
            linked = current.lstat()
        except FileNotFoundError:
            missing.append(current)
            if current.parent == current:
                raise _path_error("Skill destination has no safe existing ancestor.")
            current = current.parent
            continue
        except OSError as error:
            raise _path_error("Skill destination could not be inspected.") from error
        if not stat.S_ISDIR(linked.st_mode) or _is_redirect(current, linked):
            raise _path_error("Skill destination ancestry is unsafe.")
        break
    created: list[tuple[Path, _DirectoryIdentity]] = []
    try:
        for directory in reversed(missing):
            os.mkdir(directory, 0o700)
            identity = _capture_directory_identity(directory)
            created.append((directory, identity))
            _fsync_directory(directory.parent)
    except (KokoroError, OSError) as error:
        try:
            _remove_created_ancestors(tuple(created))
        except KokoroError as cleanup_error:
            raise _error(
                "SKILL_SUITE_CLEANUP_FAILED",
                "Skill destination setup could not be rolled back.",
                reason=_reason(cleanup_error),
            ) from error
        if isinstance(error, KokoroError):
            raise
        raise _path_error("Skill destination could not be created safely.") from error
    return tuple(created)


def _acquire_suite_lock(parent: Path, target: Path) -> _SuiteLock:
    token = sha256(os.path.normcase(str(target)).encode("utf-8")).hexdigest()[:16]
    path = parent / f".kokoroarc-skill-suite-{token}.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags, 0o600)
        linked = path.lstat()
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(linked.st_mode)
            or _is_redirect(path, linked)
            or int(linked.st_nlink) != 1
            or _file_identity(linked) != _file_identity(opened)
        ):
            raise _path_error("Skill suite lock is not a stable regular file.")
        if opened.st_size == 0:
            os.write(descriptor, b"0")
            os.fsync(descriptor)
        elif opened.st_size == 1:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.read(descriptor, 2) != b"0":
                raise _path_error("Skill suite lock has invalid contents.")
        else:
            raise _path_error("Skill suite lock has invalid contents.")
        for delay in (*_LOCK_RETRY_DELAYS, None):
            try:
                _lock_descriptor(descriptor)
                break
            except OSError as error:
                if not _is_lock_contention(error) or delay is None:
                    raise _error(
                        "SKILL_SUITE_INSTALL_FAILED",
                        "The Skill suite destination is locked.",
                        reason="lock_contention",
                    ) from error
                time.sleep(delay)
        final = path.lstat()
        opened = os.fstat(descriptor)
        if (
            _file_identity(final) != _file_identity(opened)
            or int(final.st_nlink) != 1
        ):
            raise _path_error("Skill suite lock changed during acquisition.")
        return _SuiteLock(path, descriptor, _file_identity(final))
    except KokoroError:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError as error:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise _error(
            "SKILL_SUITE_INSTALL_FAILED",
            "The Skill suite transaction lock could not be acquired.",
            reason=type(error).__name__,
        ) from error


def _stage_skill(
    source: _SuiteSnapshot,
    target: Path,
    skill_name: str,
    limits: SkillSuiteLimits,
) -> _StagedSkill:
    try:
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".kokoroarc-skill-suite-{skill_name}-",
                dir=target,
            )
        )
    except OSError as error:
        raise _error(
            "SKILL_SUITE_INSTALL_FAILED",
            "Skill staging directory could not be created.",
            reason=_reason(error),
        ) from error
    try:
        root_identity = _capture_directory_identity(staging)
    except KokoroError as error:
        raise _error(
            "SKILL_SUITE_CLEANUP_FAILED",
            "Skill staging identity could not be retained safely.",
            reason="staging_identity_unavailable",
        ) from error
    directory_identities: list[tuple[str, _DirectoryIdentity]] = []
    file_identities: list[tuple[str, _FileIdentity]] = []
    partial = _StagedSkill(
        skill_name,
        staging,
        target / skill_name,
        root_identity,
        (),
        (),
    )
    try:
        for relative in ("agents", "references"):
            directory = staging / relative
            os.mkdir(directory, 0o700)
            identity = _capture_directory_identity(directory)
            directory_identities.append((relative, identity))
        prefix = f"{skill_name}/"
        for captured in source.files:
            if not captured.relative.startswith(prefix):
                continue
            relative = captured.relative.removeprefix(prefix)
            identity = _write_exclusive_file(staging / relative, captured.payload)
            file_identities.append((relative, identity))
        for relative, _identity in reversed(directory_identities):
            _fsync_directory(staging / relative)
        _fsync_directory(staging)
        partial = _StagedSkill(
            skill_name,
            staging,
            target / skill_name,
            root_identity,
            tuple(directory_identities),
            tuple(file_identities),
        )
        _require_staged_skill(partial, staging)
        _require_installed_bytes(source, skill_name, staging, limits)
        return partial
    except BaseException as error:
        partial = _StagedSkill(
            skill_name,
            staging,
            target / skill_name,
            root_identity,
            tuple(directory_identities),
            tuple(file_identities),
        )
        try:
            _remove_identity_tree(partial, staging)
        except KokoroError as cleanup_error:
            raise _error(
                "SKILL_SUITE_CLEANUP_FAILED",
                "Invalid Skill staging could not be removed.",
                reason=_reason(cleanup_error),
            ) from error
        if isinstance(error, KokoroError):
            raise
        raise _error(
            "SKILL_SUITE_INSTALL_FAILED",
            "Skill staging bytes could not be written.",
            reason=type(error).__name__,
        ) from error


def _write_exclusive_file(path: Path, payload: bytes) -> _FileIdentity:
    descriptor = -1
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        linked = path.lstat()
    except OSError as error:
        raise _error(
            "SKILL_SUITE_INSTALL_FAILED",
            "A Skill staging file could not be written.",
            reason=type(error).__name__,
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not stat.S_ISREG(linked.st_mode) or int(linked.st_nlink) != 1:
        raise _error(
            "SKILL_SUITE_INSTALL_FAILED",
            "A Skill staging file has unsafe metadata.",
        )
    return _file_identity(linked)


def _publish_skill(item: _StagedSkill) -> None:
    try:
        _rename_directory_no_replace(item.staging, item.final)
        _fsync_directory(item.final.parent)
    except KokoroError as error:
        if error.code == "KARC_INSTALL_CONFLICT":
            raise _error(
                "SKILL_SUITE_DESTINATION_CHANGED",
                "A Skill target appeared before atomic publication.",
            ) from error
        raise _error(
            "SKILL_SUITE_INSTALL_FAILED",
            "A Skill directory could not be published atomically.",
            reason=error.code,
        ) from error
    except OSError as error:
        raise _error(
            "SKILL_SUITE_INSTALL_FAILED",
            "A Skill directory could not be published atomically.",
            reason=type(error).__name__,
        ) from error


def _require_installed_bytes(
    source: _SuiteSnapshot,
    skill_name: str,
    root: Path,
    limits: SkillSuiteLimits,
) -> None:
    installed = _capture_skill_target(root, skill_name, limits)
    prefix = f"{skill_name}/"
    expected = {
        item.relative.removeprefix(prefix): item.payload
        for item in source.files
        if item.relative.startswith(prefix)
    }
    actual = {
        item.relative.removeprefix(prefix): item.payload for item in installed
    }
    if actual != expected:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            "Installed Skill bytes do not match the captured source.",
        )


def _require_complete_install(
    source: _SuiteSnapshot,
    target: Path,
    limits: SkillSuiteLimits,
) -> None:
    first = _capture_complete_install(source, target, limits)
    second = _capture_complete_install(source, target, limits)
    if first != second:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            "Installed Skill identities changed during final verification.",
        )


def _capture_complete_install(
    source: _SuiteSnapshot,
    target: Path,
    limits: SkillSuiteLimits,
) -> tuple[tuple[str, _DirectoryIdentity, tuple[_CapturedFile, ...]], ...]:
    source_files = {item.relative: item.payload for item in source.files}
    captured: list[
        tuple[str, _DirectoryIdentity, tuple[_CapturedFile, ...]]
    ] = []
    for skill_name in SKILL_SUITE_NAMES:
        root = target / skill_name
        try:
            before = _capture_directory_identity(root)
            installed = _capture_skill_target(root, skill_name, limits)
            after = _capture_directory_identity(root)
        except KokoroError as error:
            raise _error(
                "SKILL_SUITE_DESTINATION_CHANGED",
                "Installed Skill could not be verified safely.",
                reason=error.code,
            ) from error
        if before != after:
            raise _error(
                "SKILL_SUITE_DESTINATION_CHANGED",
                "Installed Skill identity changed during final verification.",
            )
        prefix = f"{skill_name}/"
        expected = {
            relative.removeprefix(prefix): payload
            for relative, payload in source_files.items()
            if relative.startswith(prefix)
        }
        actual = {
            item.relative.removeprefix(prefix): item.payload
            for item in installed
        }
        if actual != expected:
            raise _error(
                "SKILL_SUITE_DESTINATION_CHANGED",
                "Installed Skill bytes do not match the captured source.",
            )
        captured.append((skill_name, before, installed))
    return tuple(captured)


def _require_staged_skill(item: _StagedSkill, root: Path) -> None:
    if _capture_directory_identity(root) != item.root_identity:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            "Generated Skill directory identity changed.",
        )
    for relative, expected in item.directory_identities:
        if _capture_directory_identity(root / relative) != expected:
            raise _error(
                "SKILL_SUITE_DESTINATION_CHANGED",
                "Generated Skill directory identity changed.",
            )
    for relative, expected in item.file_identities:
        try:
            linked = (root / relative).lstat()
        except OSError as error:
            raise _error(
                "SKILL_SUITE_DESTINATION_CHANGED",
                "Generated Skill file identity could not be confirmed.",
            ) from error
        if _file_identity(linked) != expected or int(linked.st_nlink) != 1:
            raise _error(
                "SKILL_SUITE_DESTINATION_CHANGED",
                "Generated Skill file identity changed.",
            )


def _rollback_transaction(
    staged: list[_StagedSkill],
    published: list[_StagedSkill],
) -> BaseException | None:
    published_names = {item.name for item in published}
    first_error: BaseException | None = None
    for item in reversed(staged):
        try:
            _remove_transaction_item(
                item,
                allow_final=item.name in published_names,
            )
        except BaseException as error:
            if first_error is None:
                first_error = error
    return first_error


def _remove_transaction_item(item: _StagedSkill, *, allow_final: bool) -> None:
    staging_exists = _lstat_optional(item.staging) is not None
    final_exists = _lstat_optional(item.final) is not None
    staging_matches = staging_exists and _directory_identity_matches(
        item.staging,
        item.root_identity,
    )
    final_matches = final_exists and _directory_identity_matches(
        item.final,
        item.root_identity,
    )
    if staging_matches and final_matches:
        raise _cleanup_error("Generated Skill exists at two paths.")
    if staging_matches:
        _remove_identity_tree(item, item.staging)
    elif final_matches:
        if not allow_final:
            raise _cleanup_error("Unexpected published Skill cannot be removed.")
        _remove_identity_tree(item, item.final)
    elif staging_exists or final_exists:
        raise _cleanup_error("Generated Skill identity could not be located.")
    else:
        raise _cleanup_error("Generated Skill directory disappeared before cleanup.")


def _directory_identity_matches(
    path: Path,
    expected: _DirectoryIdentity,
) -> bool:
    try:
        return _capture_directory_identity(path) == expected
    except KokoroError:
        return False


def _remove_identity_tree(item: _StagedSkill, root: Path) -> None:
    _require_cleanup_identity(item, root)
    try:
        for relative, expected in reversed(item.file_identities):
            path = root / relative
            linked = path.lstat()
            if _file_identity(linked) != expected or int(linked.st_nlink) != 1:
                raise _cleanup_error("Generated Skill file changed before cleanup.")
            path.unlink()
        for relative, expected in sorted(
            item.directory_identities,
            key=lambda value: len(Path(value[0]).parts),
            reverse=True,
        ):
            path = root / relative
            if _capture_directory_identity(path) != expected:
                raise _cleanup_error(
                    "Generated Skill directory changed before cleanup."
                )
            os.rmdir(path)
        if _capture_directory_identity(root) != item.root_identity:
            raise _cleanup_error("Generated Skill root changed before cleanup.")
        os.rmdir(root)
        _fsync_directory(root.parent)
    except KokoroError:
        raise
    except OSError as error:
        raise _cleanup_error(
            "Generated Skill directory could not be removed.",
            reason=type(error).__name__,
        ) from error


def _require_cleanup_identity(item: _StagedSkill, root: Path) -> None:
    if _capture_directory_identity(root) != item.root_identity:
        raise _cleanup_error("Generated Skill root identity changed.")
    expected_files = {relative for relative, _identity in item.file_identities}
    expected_directories = {
        relative for relative, _identity in item.directory_identities
    }
    actual_files, actual_directories = _bounded_relative_nodes(
        root,
        len(expected_files) + len(expected_directories) + 1,
    )
    if actual_files != expected_files or actual_directories != expected_directories:
        raise _cleanup_error("Generated Skill tree changed before cleanup.")
    _require_staged_skill(item, root)


def _bounded_relative_nodes(
    root: Path,
    limit: int,
) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    pending = [(root, "")]
    count = 0
    while pending:
        directory, prefix = pending.pop()
        try:
            scanner = os.scandir(directory)
        except OSError as error:
            raise _cleanup_error(
                "Generated Skill tree could not be scanned."
            ) from error
        try:
            for entry in scanner:
                count += 1
                if count > limit:
                    raise _cleanup_error("Generated Skill tree contains extra nodes.")
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                path = Path(entry.path)
                linked = path.lstat()
                if _is_redirect(path, linked):
                    raise _cleanup_error("Generated Skill tree contains a redirect.")
                if stat.S_ISDIR(linked.st_mode):
                    directories.add(relative)
                    pending.append((path, relative))
                elif stat.S_ISREG(linked.st_mode):
                    files.add(relative)
                else:
                    raise _cleanup_error(
                        "Generated Skill tree contains an unsafe node."
                    )
        finally:
            scanner.close()
    return files, directories


def _remove_created_ancestors(
    created: tuple[tuple[Path, _DirectoryIdentity], ...],
) -> None:
    for path, expected in reversed(created):
        try:
            if _capture_directory_identity(path) != expected:
                raise _cleanup_error("Created destination directory changed.")
            os.rmdir(path)
            _fsync_directory(path.parent)
        except FileNotFoundError:
            continue
        except KokoroError:
            raise
        except OSError as error:
            if error.errno in {errno.EEXIST, errno.ENOTEMPTY} or getattr(
                error,
                "winerror",
                None,
            ) == 145:
                break
            raise _cleanup_error(
                "Created destination directory could not be removed.",
                reason=type(error).__name__,
            ) from error


def _capture_directory_identity(path: Path) -> _DirectoryIdentity:
    try:
        linked = path.lstat()
    except OSError as error:
        raise _path_error("Skill directory identity could not be captured.") from error
    if not stat.S_ISDIR(linked.st_mode) or _is_redirect(path, linked):
        raise _path_error("Skill directory identity is unsafe.")
    return _directory_identity(linked)


def _capture_optional_directory_identity(
    path: Path,
) -> _DirectoryIdentity | None:
    linked = _lstat_optional(path)
    if linked is None:
        return None
    if not stat.S_ISDIR(linked.st_mode) or _is_redirect(path, linked):
        raise _path_error("Skill directory identity is unsafe.")
    return _directory_identity(linked)


def _require_initial_target_identity(
    target: Path,
    expected: _DirectoryIdentity | None,
) -> None:
    if expected is not None:
        _require_destination_directory(target, expected, "lock acquisition")
        return
    try:
        current = _lstat_optional(target)
    except KokoroError as error:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            "The Skill destination changed during lock acquisition.",
            reason=error.code,
        ) from error
    if current is not None:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            "The Skill destination appeared during lock acquisition.",
        )


def _capture_source_directory_identity(path: Path) -> _DirectoryIdentity:
    try:
        return _capture_directory_identity(path)
    except KokoroError as error:
        raise _source_error("Skill suite source identity is unsafe.") from error


def _snapshots_match(first: _SuiteSnapshot, second: _SuiteSnapshot) -> bool:
    return first == second


def _require_source_unchanged(
    source: _SuiteSnapshot,
    limits: SkillSuiteLimits,
) -> None:
    try:
        current = _capture_suite_source(source.root, limits)
    except KokoroError as error:
        raise _error(
            "SKILL_SUITE_SOURCE_CHANGED",
            "The Skill suite source became invalid before installation.",
            reason=error.code,
        ) from error
    if not _snapshots_match(source, current):
        raise _error(
            "SKILL_SUITE_SOURCE_CHANGED",
            "The Skill suite source changed before installation.",
        )


def _require_destination_directory(
    path: Path,
    expected: _DirectoryIdentity,
    phase: str,
) -> None:
    try:
        _validate_existing_ancestors(path)
        current = _capture_directory_identity(path)
    except KokoroError as error:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            f"The Skill destination changed during {phase}.",
            reason=error.code,
        ) from error
    if current != expected:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            f"The Skill destination changed during {phase}.",
        )


def _require_suite_lock(lock: _SuiteLock) -> None:
    try:
        linked = lock.path.lstat()
        opened = os.fstat(lock.descriptor)
    except OSError as error:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            "The Skill suite transaction lock changed.",
        ) from error
    if (
        not stat.S_ISREG(linked.st_mode)
        or _is_redirect(lock.path, linked)
        or int(linked.st_nlink) != 1
        or _file_identity(linked) != lock.identity
        or _file_identity(opened) != lock.identity
    ):
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            "The Skill suite transaction lock changed.",
        )


def _require_actions_unchanged(
    source: _SuiteSnapshot,
    target: Path,
    limits: SkillSuiteLimits,
    expected: tuple[tuple[str, str], ...],
    phase: str,
) -> None:
    try:
        current = _plan_actions(source, target, limits)
    except KokoroError as error:
        if error.code in {
            "SKILL_SUITE_CONFLICT",
            "SKILL_SUITE_LIMIT_EXCEEDED",
            "SKILL_SUITE_PATH_INVALID",
        }:
            raise _error(
                "SKILL_SUITE_DESTINATION_CHANGED",
                f"The Skill destination changed before {phase}.",
                reason=error.code,
            ) from error
        raise
    if current != expected:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            f"The Skill destination changed before {phase}.",
        )


def _require_clean_absolute_path(path: Path, label: str) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise _path_error(f"{label} must be an unambiguous absolute path.")


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _path_error("Skill path could not be inspected.") from error


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_descriptor(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        pass


def _is_lock_contention(error: OSError) -> bool:
    return (
        error.errno in _LOCK_CONTENTION_ERRNOS
        or getattr(error, "winerror", None) in _LOCK_CONTENTION_WINERRORS
    )


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = -1
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _result_document(
    *,
    source: _SuiteSnapshot,
    target: Path,
    scope: str,
    actions: tuple[tuple[str, str], ...],
    dry_run: bool,
) -> dict[str, Any]:
    hashes = dict(source.skill_sha256)
    return {
        "artifact_id": "kokoroarc/skill-suite/install-plan",
        "version": "1.0.0",
        "scope": scope,
        "skills_root": str(target),
        "source_tree_sha256": source.source_tree_sha256,
        "skills": [
            {
                "name": name,
                "source_sha256": hashes[name],
                "target": str(target / name),
                "action": action,
            }
            for name, action in actions
        ],
        "dry_run": dry_run,
        "will_write": any(action == "install" for _, action in actions),
    }


def _skill_digest(skill_name: str, files: tuple[_CapturedFile, ...]) -> str:
    prefix = f"{skill_name}/"
    manifest = [
        {
            "path": item.relative.removeprefix(prefix),
            "size": len(item.payload),
            "sha256": sha256(item.payload).hexdigest(),
        }
        for item in files
        if item.relative.startswith(prefix)
    ]
    return sha256(canonical_bytes(manifest)).hexdigest()


def _tree_digest(files: tuple[_CapturedFile, ...]) -> str:
    manifest = [
        {
            "path": item.relative,
            "size": len(item.payload),
            "sha256": sha256(item.payload).hexdigest(),
        }
        for item in files
    ]
    return sha256(canonical_bytes(manifest)).hexdigest()


def _validate_limits(limits: SkillSuiteLimits) -> None:
    for value in (
        limits.max_files,
        limits.max_file_bytes,
        limits.max_total_bytes,
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise _limit_error("invalid_limits")


def _file_identity(value: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
        int(value.st_dev),
        int(value.st_ino),
        stat.S_IFMT(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _directory_identity(value: os.stat_result) -> _DirectoryIdentity:
    return _DirectoryIdentity(
        int(value.st_dev),
        int(value.st_ino),
        stat.S_IFMT(value.st_mode),
    )


def _is_redirect(path: Path, linked: os.stat_result) -> bool:
    if stat.S_ISLNK(linked.st_mode):
        return True
    probe = getattr(path, "is_junction", None)
    if probe is None:
        return False
    try:
        return bool(probe())
    except OSError:
        return True


def _tree_error(source: bool, message: str) -> KokoroError:
    return _source_error(message) if source else _path_error(message)


def _inventory_error(
    source: bool,
    inventory_conflict: bool,
    message: str,
) -> KokoroError:
    if source:
        return _source_error(message)
    if inventory_conflict:
        return _conflict_error()
    return _path_error(message)


def _source_error(message: str) -> KokoroError:
    return _error("SKILL_SUITE_SOURCE_INVALID", message)


def _path_error(message: str) -> KokoroError:
    return _error("SKILL_SUITE_PATH_INVALID", message)


def _conflict_error() -> KokoroError:
    return _error(
        "SKILL_SUITE_CONFLICT",
        "An installed Skill differs from the KokoroArc suite.",
    )


def _limit_error(limit: str) -> KokoroError:
    return _error(
        "SKILL_SUITE_LIMIT_EXCEEDED",
        "The KokoroArc Skill suite exceeds its configured limits.",
        limit=limit,
    )


def _cleanup_error(message: str, **details: Any) -> KokoroError:
    return _error("SKILL_SUITE_CLEANUP_FAILED", message, **details)


def _reason(error: BaseException) -> str:
    return error.code if isinstance(error, KokoroError) else type(error).__name__


def _error(code: str, message: str, **details: Any) -> KokoroError:
    return KokoroError(
        code=code,
        message=message,
        retryable=False,
        details=details,
    )
