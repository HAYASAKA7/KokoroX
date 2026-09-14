from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import re
import secrets
import site
import stat
import sysconfig
import tempfile
import time
from typing import Any, Literal

from kokorox import __version__
from kokorox.distribution.installer import _rename_directory_no_replace
from kokorox.bounded_read import read_at_most
from kokorox.errors import KokoroError
from kokorox.packs.compiler import canonical_bytes
from kokorox.packs.loader import parse_yaml_bytes


SKILL_SUITE_NAMES = (
    "using-kokorox",
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
    "using-kokorox": "references/runtime-contract.md",
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
# Install records what it wrote beside the Skills, so a later KokoroX can prove
# an installed Skill is an unmodified earlier version and replace or remove it.
_RECEIPT_NAME = ".kokorox-skill-suite.json"
_RECEIPT_ARTIFACT_ID = "kokorox/skill-suite/receipt"
_RECEIPT_MAX_BYTES = 64 * 1024
_RECEIPT_FILE = re.compile(
    r"(?:(?:agents|references)/)?[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z"
)
_RECEIPT_DIRECTORIES = frozenset({"agents", "references"})
_SHA256_HEX = re.compile(r"[a-f0-9]{64}\Z")
# Suites installed by a release that predates receipts carry none. Each release's
# Skills are recognised by the digest of the tree it shipped, so the first
# upgrade from one needs no receipt either. The inventory is frozen here rather
# than read from `_SKILL_FILES`, so changing today's file list cannot change
# what a past release is recognised by. Computed from the `v0.1.0` and `v0.2.0`
# tags with `_skill_digest`; `skills/**` is pinned to LF, so one digest covers
# every platform an install was made on.
_RELEASED_AGENT_PROFILES = (
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
_RELEASED_SKILL_FILES = {
    skill_name: frozenset(
        {
            "SKILL.md",
            reference_file,
            *(f"agents/{profile}.yaml" for profile in _RELEASED_AGENT_PROFILES),
        }
    )
    for skill_name, reference_file in (
        ("using-kokorox", "references/runtime-contract.md"),
        ("authoring-character-packs", "references/authoring-contract.md"),
        ("researching-characters", "references/research-contract.md"),
        ("testing-character-packs", "references/testing-contract.md"),
    )
}
_KNOWN_RELEASE_DIGESTS = {
    "0.1.0": {
        "using-kokorox": "92e7108838792d9fc5ed93e0bf66a56fdf27c32af3d2c818acb3bfa8fccb8fea",
        "authoring-character-packs": (
            "9ed55cb7a201ae89de10c826e5ea21345f473c68d20ad2206279108e98b300eb"
        ),
        "researching-characters": (
            "eb0f6652c40a7ba49e17b727373eb92f8443778ce4c0d91aaeb6a90c47839f5f"
        ),
        "testing-character-packs": (
            "4044b0e550ab6f9057086c6c020b11dbcde57e88f5fea43c3139df0d48e723cd"
        ),
    },
    "0.2.0": {
        "using-kokorox": "f80e832f6b4a8f88ce38267e3b4965249d96baff29f7edb7a7912e96a07c1415",
        "authoring-character-packs": (
            "5d1d3c63e0c467debb19387a69c01b81fd14f8e2036401179b335591962c36e9"
        ),
        "researching-characters": (
            "b38ea44e2ec5e78ff754d1fce19b7d7dcdde6449a01b20606d05a8c33677f273"
        ),
        "testing-character-packs": (
            "4044b0e550ab6f9057086c6c020b11dbcde57e88f5fea43c3139df0d48e723cd"
        ),
    },
}


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


@dataclass(frozen=True, slots=True)
class _ReceiptSkill:
    """One Skill as an earlier install wrote it: its tree digest and files."""

    sha256: str
    files: frozenset[str]


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
    replace: bool = False,
    limits: SkillSuiteLimits = SkillSuiteLimits(),
) -> dict[str, Any]:
    source = _resolve_source_snapshot(source_root, limits)
    target = _resolve_skills_root(
        scope=scope,
        repo_root=repo_root,
        skills_root=skills_root,
    )
    _reject_source_target_overlap(source.root, target)
    actions = _plan_actions(
        source,
        target,
        limits,
        receipt=_read_receipt(target),
        replace=replace,
    )
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
    replace: bool = False,
    limits: SkillSuiteLimits = SkillSuiteLimits(),
) -> dict[str, Any]:
    """Install the suite, or bring an earlier installed version up to date.

    A Skill already byte-identical to the source is left alone and a missing
    one is installed. A Skill that differs is replaced only with `replace` and
    only when the receipt an earlier install wrote proves it is that version,
    unmodified; anything else refuses the whole install. Replaced Skills are
    moved aside before the new ones are published and deleted only after the
    new tree verifies, so a failure puts every one of them back.
    """

    if dry_run:
        return preview_skill_suite_install(
            source_root=source_root,
            scope=scope,
            repo_root=repo_root,
            skills_root=skills_root,
            replace=replace,
            limits=limits,
        )
    source = _resolve_source_snapshot(source_root, limits)
    target = _resolve_skills_root(
        scope=scope,
        repo_root=repo_root,
        skills_root=skills_root,
    )
    _reject_source_target_overlap(source.root, target)
    # Read once: every later re-plan proves ownership against the same record,
    # so a receipt swapped mid-transaction cannot widen what may be replaced.
    receipt = _read_receipt(target)
    previous_receipt = _receipt_payload_on_disk(target)
    initial_target_identity = _capture_optional_directory_identity(target)
    initial_skill_states = _capture_target_skill_states(target, limits, receipt)
    actions = _plan_actions(
        source,
        target,
        limits,
        receipt=receipt,
        replace=replace,
    )

    def planner(
        snapshot: _SuiteSnapshot,
        root: Path,
        bounds: SkillSuiteLimits,
    ) -> tuple[tuple[str, str], ...]:
        return _plan_actions(
            snapshot,
            root,
            bounds,
            receipt=receipt,
            replace=replace,
        )

    _require_target_skill_states(
        target,
        limits,
        initial_skill_states,
        actions,
        phase="planning",
        require_missing=True,
        receipt=receipt,
    )
    created_ancestors: tuple[tuple[Path, _DirectoryIdentity], ...] = ()
    staged: list[_StagedSkill] = []
    published: list[_StagedSkill] = []
    moved: list[_StagedSkill] = []
    receipt_written = False
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
                planner=planner,
            )
            _require_target_skill_states(
                target,
                limits,
                initial_skill_states,
                actions,
                phase="installation",
                require_missing=True,
                receipt=receipt,
            )
            for name, action in actions:
                if action in {"install", "replace"}:
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
                planner=planner,
            )
            states = {state.name: state for state in initial_skill_states}
            for name, action in actions:
                if action == "replace":
                    moved.append(_move_skill_aside(target, states[name]))
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
                receipt=receipt,
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
            if any(action in {"install", "replace"} for _, action in actions):
                # The receipt records what this install wrote. A no-op install
                # writes nothing at all, receipt included.
                receipt_written = True
                _write_receipt(target, _receipt_payload(source))
            _require_suite_lock(transaction_lock)
    except BaseException as error:
        cleanup_error = _rollback_transaction(staged, published)
        if cleanup_error is not None:
            raise _error(
                "SKILL_SUITE_ROLLBACK_FAILED",
                "Skill suite rollback could not remove generated directories.",
                reason=_reason(cleanup_error),
            ) from error
        # Nothing replaced has been deleted yet, so every earlier version goes
        # back, and so does the receipt that proves it.
        restore_error = _restore_moved_skills(moved)
        if restore_error is None and receipt_written:
            restore_error = _restore_receipt(target, previous_receipt)
        if restore_error is not None:
            raise _error(
                "SKILL_SUITE_RESTORE_FAILED",
                "Skill suite installation could not put replaced Skills back.",
                reason=_reason(restore_error),
            ) from error
        _remove_created_ancestors(created_ancestors)
        if isinstance(error, KokoroError):
            raise
        raise _error(
            "SKILL_SUITE_INSTALL_FAILED",
            "The KokoroX Skill suite could not be installed.",
            reason=type(error).__name__,
        ) from error
    # The new suite is published, verified, and receipted. Deleting what it
    # replaced is the one step that cannot be undone, so it runs only now; a
    # failure here leaves the new suite in place and says what is left over.
    first_error: BaseException | None = None
    for item in moved:
        try:
            _remove_identity_tree(item, item.staging)
        except BaseException as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise _error(
            "SKILL_SUITE_REPLACED_NOT_DELETED",
            "The new suite is installed, but a replaced Skill could not be "
            "deleted.",
            reason=_reason(first_error),
        ) from first_error
    return _result_document(
        source=source,
        target=target,
        scope=scope,
        actions=actions,
        dry_run=False,
    )


def remove_skill_suite(
    *,
    source_root: Path | None = None,
    scope: Literal["user", "repo"] = "user",
    repo_root: Path | None = None,
    skills_root: Path | None = None,
    dry_run: bool = False,
    limits: SkillSuiteLimits = SkillSuiteLimits(),
) -> dict[str, Any]:
    """Remove the installed suite, and only what can be proven to be it.

    A Skill is removed when its tree is byte identical to the suite source, or
    to the version the receipt of an earlier install records -- so after an
    upgrade the previous suite can still be removed. An edited Skill, a user
    file inside one, or a version nothing proves refuses the whole removal and
    removes nothing. The Skills root itself always stays; other Skills may
    live there.

    Every Skill to remove is moved aside before any is deleted, so a failure
    while moving puts all of them back.
    """

    source = _resolve_source_snapshot(source_root, limits)
    target = _resolve_skills_root(
        scope=scope,
        repo_root=repo_root,
        skills_root=skills_root,
    )
    _reject_source_target_overlap(source.root, target)
    receipt = _read_receipt(target)
    actions = _plan_removal(source, target, limits, receipt=receipt)

    def planner(
        snapshot: _SuiteSnapshot,
        root: Path,
        bounds: SkillSuiteLimits,
    ) -> tuple[tuple[str, str], ...]:
        return _plan_removal(snapshot, root, bounds, receipt=receipt)

    if dry_run or not any(action == "remove" for _, action in actions):
        return _result_document(
            source=source,
            target=target,
            scope=scope,
            actions=actions,
            dry_run=dry_run,
            kind="removal",
        )
    initial_skill_states = _capture_target_skill_states(target, limits, receipt)
    # A Skill being removed must stay exactly as captured, and one that was
    # absent must stay absent -- the install guard, read for this direction.
    guarded = tuple(
        (name, "unchanged" if action == "remove" else "install")
        for name, action in actions
    )
    moved: list[_StagedSkill] = []
    removed: list[str] = []
    deleting: str | None = None
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
            target_identity = _capture_directory_identity(target)
            _require_actions_unchanged(
                source,
                target,
                limits,
                actions,
                "removal",
                planner=planner,
            )
            _require_target_skill_states(
                target,
                limits,
                initial_skill_states,
                guarded,
                phase="removal",
                require_missing=True,
                receipt=receipt,
            )
            states = {state.name: state for state in initial_skill_states}
            for name, action in actions:
                if action == "remove":
                    moved.append(_move_skill_aside(target, states[name]))
            _require_destination_directory(target, target_identity, "removal")
            _require_suite_lock(transaction_lock)
            for item in moved:
                deleting = item.name
                _remove_identity_tree(item, item.staging)
                removed.append(item.name)
                deleting = None
            _fsync_directory(target)
            _require_destination_directory(
                target,
                target_identity,
                "final verification",
            )
            _require_suite_lock(transaction_lock)
            for item in moved:
                if _lstat_optional(item.final) is not None:
                    raise _error(
                        "SKILL_SUITE_DESTINATION_CHANGED",
                        "A removed Skill reappeared during removal.",
                    )
    except BaseException as error:
        # A tomb whose deletion had begun cannot be put back whole; every
        # other one that was moved but not deleted goes back where it was.
        intact = [
            item
            for item in moved
            if item.name not in removed and item.name != deleting
        ]
        restore_error = _restore_moved_skills(intact)
        if restore_error is not None:
            raise _error(
                "SKILL_SUITE_RESTORE_FAILED",
                "Skill suite removal could not put moved Skills back.",
                reason=_reason(restore_error),
            ) from error
        if isinstance(error, KokoroError):
            raise
        raise _error(
            "SKILL_SUITE_REMOVE_FAILED",
            "The KokoroX Skill suite could not be removed.",
            reason=type(error).__name__,
        ) from error
    # With every suite Skill gone the receipt proves nothing further. A copy
    # that cannot be deleted is harmless -- it only ever vouches for exact bytes
    # -- so it is left rather than turning a finished removal into a failure.
    _discard_receipt(target)
    return _result_document(
        source=source,
        target=target,
        scope=scope,
        actions=actions,
        dry_run=False,
        kind="removal",
    )


def _move_skill_aside(target: Path, state: _TargetSkillState) -> _StagedSkill:
    """Rename one installed Skill to a tomb beside it, identities recorded.

    A rename keeps device and inode, so identities captured before the move
    still name the same tree after it. That is what lets the tomb be deleted,
    or put back, only while it is provably unchanged.
    """

    if state.root_identity is None or state.files is None:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            "A Skill to remove disappeared during removal.",
        )
    final = target / state.name
    prefix = f"{state.name}/"
    try:
        record = _StagedSkill(
            state.name,
            final,
            final,
            state.root_identity,
            tuple(
                (relative, _capture_directory_identity(final / relative))
                for relative in ("agents", "references")
            ),
            tuple(
                (item.relative.removeprefix(prefix), item.identity)
                for item in state.files
            ),
        )
        _require_cleanup_identity(record, final)
    except KokoroError as error:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            "A Skill to remove changed before it could be moved.",
            reason=error.code,
        ) from error
    tomb = target / (
        f".kokorox-skill-suite-{state.name}-removing-{secrets.token_hex(8)}"
    )
    try:
        _rename_directory_no_replace(final, tomb)
        _fsync_directory(target)
    except KokoroError as error:
        if error.code == "KARC_INSTALL_CONFLICT":
            raise _error(
                "SKILL_SUITE_DESTINATION_CHANGED",
                "A removal path appeared before the Skill could be moved.",
            ) from error
        raise _error(
            "SKILL_SUITE_REMOVE_FAILED",
            "A Skill directory could not be moved aside.",
            reason=error.code,
        ) from error
    moved = replace(record, staging=tomb)
    _require_staged_skill(moved, tomb)
    return moved


def _restore_moved_skills(items: list[_StagedSkill]) -> BaseException | None:
    """Put every moved-aside Skill back; return the first failure, if any."""

    first_error: BaseException | None = None
    for item in reversed(items):
        try:
            _require_staged_skill(item, item.staging)
            _rename_directory_no_replace(item.staging, item.final)
            _fsync_directory(item.final.parent)
        except BaseException as error:
            if first_error is None:
                first_error = error
    return first_error


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
    # Two sources and no source need opposite remedies -- drop one, or install
    # one -- so they cannot share a code. `SKILL_SUITE_SOURCE_INVALID` keeps
    # its literal meaning: a source was found and is not usable.
    if len(snapshots) > 1:
        raise _error(
            "SKILL_SUITE_SOURCE_AMBIGUOUS",
            "Multiple complete KokoroX Skill suite sources were discovered; "
            "name one with --source.",
            sources=len(snapshots),
        )
    # Discovery either produced a usable source or it did not. Whether some
    # candidate path existed and failed to capture is internal detail: the
    # caller has no usable source either way and the remedy is the same, so
    # the reason rides along rather than changing the code.
    # `SKILL_SUITE_SOURCE_INVALID` stays for a source the caller *named*.
    raise _error(
        "SKILL_SUITE_SOURCE_MISSING",
        "No KokoroX Skill suite source was found; name one with --source.",
        **({"reason": last_error.code} if last_error is not None else {}),
    )


def _data_roots() -> tuple[Path, ...]:
    """Return every base a wheel may place its data files under.

    A wheel installs Skill data files into the install scheme's ``data``
    directory, not beside the package in site-packages. Which directory that
    is depends on the scheme: a normal environment install uses the prefix, a
    ``pip install --user`` uses the per-user base, and macOS framework builds
    use a different layout again. ``sysconfig`` is the authority for the active
    scheme, so ask it first and keep the prefixes as fallbacks.
    """

    roots: list[Path] = []

    def add(value: object) -> None:
        if isinstance(value, str) and value:
            root = Path(value)
            if root not in roots:
                roots.append(root)

    add(sysconfig.get_path("data"))
    for scheme in sysconfig.get_scheme_names():
        try:
            add(sysconfig.get_path("data", scheme))
        except (KeyError, ValueError):
            continue
    add(sys.prefix)
    add(sys.base_prefix)
    add(getattr(site, "USER_BASE", None))
    return tuple(roots)


def _source_candidates(source_root: Path | None) -> tuple[Path, ...]:
    if source_root is not None:
        return (Path(source_root),)
    module = Path(__file__).absolute()
    relative = Path("share") / "kokorox" / "skills"
    candidates = [module.parents[2] / relative]
    candidates.extend(root / relative for root in _data_roots())
    if module.parents[2].name.casefold() == "src":
        candidates.insert(0, module.parents[3] / "skills")
    seen: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.append(candidate)
    return tuple(seen)


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
            payload = read_at_most(handle, limit + 1)
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


def _classify_installed(
    source: _SuiteSnapshot,
    target: Path,
    limits: SkillSuiteLimits,
    receipt: dict[str, _ReceiptSkill] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return each suite Skill's state in the target.

    `missing`, `identical` -- byte for byte the source -- or `predecessor`:
    byte for byte an earlier version, as the receipt of an earlier install or
    a known release records it. A present Skill that is none of these raises
    `SKILL_SUITE_CONFLICT` when a receipt vouches for a different tree -- it
    changed after install -- and `SKILL_SUITE_RECEIPT_MISSING` when nothing
    vouches for it at all. Install and removal share this so they agree on
    what counts as the suite's own tree; neither acts on one it cannot prove.
    """

    states: list[tuple[str, str]] = []
    source_files = {item.relative: item.payload for item in source.files}
    recorded = {} if receipt is None else receipt
    for skill_name in SKILL_SUITE_NAMES:
        skill_target = target / skill_name
        try:
            linked = skill_target.lstat()
        except FileNotFoundError:
            states.append((skill_name, "missing"))
            continue
        except OSError as error:
            raise _path_error(
                "Installed Skill target could not be inspected."
            ) from error
        if not stat.S_ISDIR(linked.st_mode) or _is_redirect(skill_target, linked):
            raise _path_error("Installed Skill target is unsafe.")
        if _matches_source(source_files, skill_target, skill_name, limits):
            states.append((skill_name, "identical"))
        elif (
            _matching_predecessor(
                skill_target, skill_name, recorded.get(skill_name), limits
            )
            is not None
        ):
            states.append((skill_name, "predecessor"))
        elif skill_name in recorded:
            raise _conflict_error()
        else:
            raise _receipt_missing_error()
    return tuple(states)


def _predecessor_records(
    skill_name: str,
    receipt_record: _ReceiptSkill | None,
) -> tuple[_ReceiptSkill, ...]:
    """The earlier trees a Skill may prove itself against, receipt first."""

    records: list[_ReceiptSkill] = [] if receipt_record is None else [receipt_record]
    for digests in _KNOWN_RELEASE_DIGESTS.values():
        release = _ReceiptSkill(
            digests[skill_name], _RELEASED_SKILL_FILES[skill_name]
        )
        if release not in records:
            records.append(release)
    return tuple(records)


def _matching_predecessor(
    skill_target: Path,
    skill_name: str,
    receipt_record: _ReceiptSkill | None,
    limits: SkillSuiteLimits,
) -> _ReceiptSkill | None:
    for record in _predecessor_records(skill_name, receipt_record):
        if _matches_receipt(record, skill_target, skill_name, limits):
            return record
    return None


def _matches_source(
    source_files: dict[str, bytes],
    skill_target: Path,
    skill_name: str,
    limits: SkillSuiteLimits,
) -> bool:
    try:
        installed = _capture_skill_target(skill_target, skill_name, limits)
    except KokoroError as error:
        if error.code == "SKILL_SUITE_PATH_INVALID":
            raise
        return False
    prefix = f"{skill_name}/"
    expected = {
        relative.removeprefix(prefix): payload
        for relative, payload in source_files.items()
        if relative.startswith(prefix)
    }
    actual = {item.relative.removeprefix(prefix): item.payload for item in installed}
    return actual == expected


def _matches_receipt(
    recorded: _ReceiptSkill,
    skill_target: Path,
    skill_name: str,
    limits: SkillSuiteLimits,
) -> bool:
    """Whether a Skill is exactly the tree an earlier install recorded.

    Captured against the recorded inventory rather than today's, so a version
    with a different file list can still be recognised -- and then compared by
    digest over every path, size, and byte.
    """

    try:
        installed = _capture_recorded_skill(skill_target, skill_name, recorded, limits)
    except KokoroError as error:
        if error.code == "SKILL_SUITE_PATH_INVALID":
            raise
        return False
    return _skill_digest(skill_name, installed) == recorded.sha256


def _capture_recorded_skill(
    root: Path,
    skill_name: str,
    recorded: _ReceiptSkill,
    limits: SkillSuiteLimits,
) -> tuple[_CapturedFile, ...]:
    try:
        return _capture_closed_tree(
            root,
            limits,
            source=False,
            expected_files=recorded.files,
            expected_directories=_RECEIPT_DIRECTORIES,
            relative_prefix=skill_name,
            inventory_conflict=True,
        )
    except KokoroError as error:
        if error.code == "SKILL_SUITE_LIMIT_EXCEEDED":
            raise _conflict_error() from error
        raise


def _plan_actions(
    source: _SuiteSnapshot,
    target: Path,
    limits: SkillSuiteLimits,
    *,
    receipt: dict[str, _ReceiptSkill] | None = None,
    replace: bool = False,
) -> tuple[tuple[str, str], ...]:
    actions: list[tuple[str, str]] = []
    for name, state in _classify_installed(source, target, limits, receipt):
        if state == "identical":
            actions.append((name, "unchanged"))
        elif state == "missing":
            actions.append((name, "install"))
        elif replace:
            actions.append((name, "replace"))
        else:
            raise _error(
                "SKILL_SUITE_REPLACE_REQUIRED",
                "An installed Skill is an earlier KokoroX suite version; install "
                "with replace to update it.",
            )
    return tuple(actions)


def _plan_removal(
    source: _SuiteSnapshot,
    target: Path,
    limits: SkillSuiteLimits,
    *,
    receipt: dict[str, _ReceiptSkill] | None = None,
) -> tuple[tuple[str, str], ...]:
    try:
        classified = _classify_installed(source, target, limits, receipt)
    except KokoroError as error:
        if error.code not in {"SKILL_SUITE_CONFLICT", "SKILL_SUITE_RECEIPT_MISSING"}:
            raise
        raise _error(
            "SKILL_SUITE_REMOVE_CONFLICT",
            "An installed Skill differs from the suite source; nothing was "
            "removed.",
        ) from error
    return tuple(
        (name, "absent" if state == "missing" else "remove")
        for name, state in classified
    )


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
    receipt: dict[str, _ReceiptSkill] | None = None,
) -> tuple[_TargetSkillState, ...]:
    states: list[_TargetSkillState] = []
    recorded = {} if receipt is None else receipt
    for skill_name in SKILL_SUITE_NAMES:
        root = target / skill_name
        linked = _lstat_optional(root)
        if linked is None:
            states.append(_TargetSkillState(skill_name, None, None))
            continue
        if not stat.S_ISDIR(linked.st_mode) or _is_redirect(root, linked):
            raise _path_error("Installed Skill target is unsafe.")
        before = _capture_directory_identity(root)
        try:
            files = _capture_skill_target(root, skill_name, limits)
        except KokoroError as error:
            # An earlier version may carry a different file list; the record
            # that proves it -- its receipt or a known release -- says which.
            if error.code != "SKILL_SUITE_CONFLICT":
                raise
            record = _matching_predecessor(
                root, skill_name, recorded.get(skill_name), limits
            )
            if record is None:
                raise
            files = _capture_recorded_skill(root, skill_name, record, limits)
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
    receipt: dict[str, _ReceiptSkill] | None = None,
) -> None:
    try:
        current = _capture_target_skill_states(target, limits, receipt)
    except KokoroError as error:
        raise _error(
            "SKILL_SUITE_DESTINATION_CHANGED",
            f"The Skill destination changed during {phase}.",
            reason=error.code,
        ) from error
    expected_by_name = {state.name: state for state in expected}
    current_by_name = {state.name: state for state in current}
    for skill_name, action in actions:
        # A Skill to be replaced must stay exactly as captured until it is
        # moved aside; once the new tree is published it is checked like any
        # other install.
        if action == "unchanged" or (action == "replace" and require_missing):
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
    path = parent / f".kokorox-skill-suite-{token}.lock"
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
                prefix=f".kokorox-skill-suite-{skill_name}-",
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
    *,
    planner: Callable[
        [_SuiteSnapshot, Path, SkillSuiteLimits], tuple[tuple[str, str], ...]
    ] = _plan_actions,
) -> None:
    try:
        current = planner(source, target, limits)
    except KokoroError as error:
        if error.code in {
            "SKILL_SUITE_CONFLICT",
            "SKILL_SUITE_REMOVE_CONFLICT",
            "SKILL_SUITE_REPLACE_REQUIRED",
            "SKILL_SUITE_RECEIPT_MISSING",
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
    kind: Literal["install", "removal"] = "install",
) -> dict[str, Any]:
    hashes = dict(source.skill_sha256)
    return {
        "artifact_id": f"kokorox/skill-suite/{kind}-plan",
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
        "will_write": any(
            action in {"install", "remove", "replace"} for _, action in actions
        ),
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


def _read_receipt(target: Path) -> dict[str, _ReceiptSkill]:
    """Return the Skills an earlier install recorded, or nothing unproven.

    A receipt only ever widens ownership to an exact earlier version -- a Skill
    must still match a recorded digest over every path, size, and byte -- so a
    missing, unreadable, or malformed receipt counts as absent rather than as
    an error, and ownership falls back to the current source alone.
    """

    payload = _receipt_payload_on_disk(target)
    if payload is None:
        return {}
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError):
        return {}
    return _parse_receipt(value)


def _receipt_payload_on_disk(target: Path) -> bytes | None:
    path = target / _RECEIPT_NAME
    try:
        linked = path.lstat()
    except OSError:
        return None
    if (
        not stat.S_ISREG(linked.st_mode)
        or _is_redirect(path, linked)
        or int(linked.st_nlink) != 1
    ):
        return None
    try:
        payload, _identity = _read_stable_file(
            path,
            linked,
            _RECEIPT_MAX_BYTES,
            source=False,
        )
    except KokoroError:
        return None
    return payload


def _parse_receipt(value: Any) -> dict[str, _ReceiptSkill]:
    if (
        not isinstance(value, dict)
        or set(value)
        != {"schema_version", "artifact_id", "created_by", "source_tree_sha256", "skills"}
        or value["schema_version"] != "1.0"
        or value["artifact_id"] != _RECEIPT_ARTIFACT_ID
        or not isinstance(value["created_by"], dict)
        or not isinstance(value["source_tree_sha256"], str)
        or _SHA256_HEX.fullmatch(value["source_tree_sha256"]) is None
        or not isinstance(value["skills"], list)
        or len(value["skills"]) > len(SKILL_SUITE_NAMES)
    ):
        return {}
    parsed: dict[str, _ReceiptSkill] = {}
    for item in value["skills"]:
        if not isinstance(item, dict) or set(item) != {"name", "sha256", "files"}:
            return {}
        name, digest, files = item["name"], item["sha256"], item["files"]
        if (
            not isinstance(name, str)
            or name not in SKILL_SUITE_NAMES
            or name in parsed
            or not isinstance(digest, str)
            or _SHA256_HEX.fullmatch(digest) is None
            or not isinstance(files, list)
            or not 0 < len(files) <= len(_EXPECTED_FILES)
            or len(set(map(str, files))) != len(files)
            or not all(
                isinstance(entry, str) and _RECEIPT_FILE.fullmatch(entry) is not None
                for entry in files
            )
            or {entry.split("/", 1)[0] for entry in files if "/" in entry}
            != _RECEIPT_DIRECTORIES
        ):
            return {}
        parsed[name] = _ReceiptSkill(digest, frozenset(files))
    return parsed


def _receipt_payload(source: _SuiteSnapshot) -> bytes:
    files: dict[str, list[str]] = {name: [] for name in SKILL_SUITE_NAMES}
    for item in source.files:
        skill_name, _, relative = item.relative.partition("/")
        if skill_name in files:
            files[skill_name].append(relative)
    hashes = dict(source.skill_sha256)
    receipt = {
        "schema_version": "1.0",
        "artifact_id": _RECEIPT_ARTIFACT_ID,
        "created_by": {"component": "kokorox", "version": __version__},
        "source_tree_sha256": source.source_tree_sha256,
        "skills": [
            {"name": name, "sha256": hashes[name], "files": sorted(files[name])}
            for name in SKILL_SUITE_NAMES
        ],
    }
    return canonical_bytes(receipt) + b"\n"


def _write_receipt(target: Path, payload: bytes) -> None:
    staging = target / f".kokorox-skill-suite-receipt-{secrets.token_hex(8)}.tmp"
    _write_exclusive_file(staging, payload)
    try:
        os.replace(staging, target / _RECEIPT_NAME)
    except OSError as error:
        try:
            staging.unlink()
        except OSError:
            # The replace failure below is the one to report; a stray temp
            # file is harmless and carries only the receipt that failed.
            pass
        raise _error(
            "SKILL_SUITE_INSTALL_FAILED",
            "The Skill suite receipt could not be written.",
            reason=_reason(error),
        ) from error
    _fsync_directory(target)


def _restore_receipt(target: Path, previous: bytes | None) -> BaseException | None:
    """Put the receipt back as it was before this install; return any failure."""

    try:
        if previous is None:
            _discard_receipt(target, strict=True)
        else:
            _write_receipt(target, previous)
    except BaseException as error:
        return error
    return None


def _discard_receipt(target: Path, *, strict: bool = False) -> None:
    path = target / _RECEIPT_NAME
    try:
        linked = path.lstat()
        if stat.S_ISREG(linked.st_mode) and not _is_redirect(path, linked):
            path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        if strict:
            raise


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


def _receipt_missing_error() -> KokoroError:
    return _error(
        "SKILL_SUITE_RECEIPT_MISSING",
        "An installed Skill differs from the KokoroX suite, and no install "
        "receipt or known release proves it is an unedited earlier version.",
    )


def _conflict_error() -> KokoroError:
    return _error(
        "SKILL_SUITE_CONFLICT",
        "An installed Skill differs from the KokoroX suite.",
    )


def _limit_error(limit: str) -> KokoroError:
    return _error(
        "SKILL_SUITE_LIMIT_EXCEEDED",
        "The KokoroX Skill suite exceeds its configured limits.",
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
