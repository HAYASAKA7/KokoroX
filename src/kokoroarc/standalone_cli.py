from __future__ import annotations

import argparse
from dataclasses import dataclass
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Callable

from kokoroarc.distribution.archive import KarcLimits, build_karc_archive
from kokoroarc.distribution.compatibility import inspect_karc_compatibility
from kokoroarc.distribution.installer import (
    install_karc_archive,
    remove_installed_pack,
)
from kokoroarc.distribution.migrations import (
    apply_karc_migration,
    preview_karc_migration,
)
from kokoroarc.distribution.registry import (
    list_installed_packs,
    resolve_install_scope,
)
from kokoroarc.distribution.suite import install_skill_suite
from kokoroarc.errors import KokoroError
from kokoroarc.json_compat import find_json_incompatibility
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.persistence.consent import (
    grant_consent,
    load_consent,
    revoke_consent,
)
from kokoroarc.persistence.memory import (
    add_memory_reference,
    list_memory_references,
    remove_memory_reference,
)
from kokoroarc.persistence.state import (
    export_persistent_data,
    preview_persistent_reset,
    reset_persistent_data,
)
from kokoroarc.schemas import SchemaRegistry


StandaloneRoute = tuple[str, str]
StandaloneHandler = Callable[
    [argparse.Namespace, Path | None, SchemaRegistry],
    dict[str, Any],
]

JSON_INPUT_MAX_BYTES = 4 * 1024 * 1024
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)
_DIRECTORY_FSYNC_UNSUPPORTED = frozenset(
    value
    for value in (
        getattr(errno, "EINVAL", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "EBADF", None),
    )
    if value is not None
)
_PERSISTENCE_PERMISSIONS = frozenset(
    {"relationship_state", "mood_state", "memory_references"}
)

_PACK_ROUTES = frozenset(
    {
        "compatibility",
        "export",
        "install",
        "list",
        "migrate",
        "remove",
    }
)
_STATE_ROUTES = frozenset({"export", "reset"})
_TOP_LEVEL_ROUTES = frozenset({"consent", "memory", "suite"})
_DATA_ROOT_ROUTES = frozenset(
    {
        ("pack", "install"),
        ("pack", "list"),
        ("pack", "remove"),
        ("consent", "grant"),
        ("consent", "show"),
        ("consent", "revoke"),
        ("state", "export"),
        ("state", "reset"),
        ("memory", "add"),
        ("memory", "list"),
        ("memory", "remove"),
    }
)


@dataclass(frozen=True, slots=True)
class _InputIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int
    file_type: int
    links: int


@dataclass(frozen=True, slots=True)
class _InputDirectoryIdentity:
    path: Path
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True, slots=True)
class _CapturedFile:
    path: Path
    directories: tuple[_InputDirectoryIdentity, ...]
    identity: _InputIdentity
    payload: bytes
    max_bytes: int


@dataclass(frozen=True, slots=True)
class _CapturedJson:
    file: _CapturedFile
    value: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    path: Path
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True, slots=True)
class _NewOutput:
    target: Path
    directories: tuple[_DirectoryIdentity, ...]
    unsafe_code: str
    exists_code: str
    write_code: str
    cleanup_code: str
    durability_code: str


class _AuditedSchemas:
    def __init__(
        self,
        delegate: SchemaRegistry,
        audit: Callable[[], None],
    ) -> None:
        self._delegate = delegate
        self._audit = audit

    def validate(self, name: str, instance: Any) -> None:
        try:
            self._delegate.validate(name, instance)
        finally:
            self._audit()


def _add_json(
    parser: argparse.ArgumentParser,
    leaf_json: Callable[[argparse.ArgumentParser], None],
) -> None:
    leaf_json(parser)


def _add_scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scope",
        choices=("global", "workspace"),
        default="global",
    )
    parser.add_argument("--workspace")


def _add_character(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--character", required=True)
    parser.add_argument("--namespace", default="original")


def add_standalone_parsers(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    pack_commands: argparse._SubParsersAction[argparse.ArgumentParser],
    state_commands: argparse._SubParsersAction[argparse.ArgumentParser],
    leaf_json: Callable[[argparse.ArgumentParser], None],
) -> None:
    pack_export = pack_commands.add_parser("export")
    pack_export.add_argument("--compiled", required=True)
    pack_export.add_argument("--promotion", required=True)
    pack_export.add_argument("--hard-report", required=True)
    pack_export.add_argument("--soft-report", required=True)
    pack_export.add_argument("--publication-report")
    pack_export.add_argument("--out", required=True)
    _add_json(pack_export, leaf_json)

    compatibility = pack_commands.add_parser("compatibility")
    compatibility.add_argument("archive")
    _add_json(compatibility, leaf_json)

    migrate = pack_commands.add_parser("migrate")
    migrate.add_argument("archive")
    migrate.add_argument("--to-format", required=True)
    migrate.add_argument("--out", required=True)
    migrate.add_argument("--dry-run", action="store_true")
    _add_json(migrate, leaf_json)

    install = pack_commands.add_parser("install")
    install.add_argument("archive")
    _add_scope(install)
    install.add_argument("--dry-run", action="store_true")
    _add_json(install, leaf_json)

    pack_list = pack_commands.add_parser("list")
    _add_scope(pack_list)
    _add_json(pack_list, leaf_json)

    remove = pack_commands.add_parser("remove")
    remove.add_argument("character_id")
    remove.add_argument("--version", required=True)
    remove.add_argument("--namespace", default="original")
    _add_scope(remove)
    remove.add_argument("--dry-run", action="store_true")
    _add_json(remove, leaf_json)

    consent = commands.add_parser("consent")
    consent_commands = consent.add_subparsers(
        dest="consent_command",
        required=True,
    )
    grant = consent_commands.add_parser("grant")
    _add_character(grant)
    grant.add_argument("--version")
    grant.add_argument(
        "--scope",
        choices=("global", "workspace"),
        required=True,
    )
    grant.add_argument("--workspace")
    grant.add_argument("--permissions", required=True)
    _add_json(grant, leaf_json)
    for name in ("show", "revoke"):
        command = consent_commands.add_parser(name)
        _add_character(command)
        _add_scope(command)
        _add_json(command, leaf_json)

    state_export = state_commands.add_parser("export")
    _add_character(state_export)
    _add_scope(state_export)
    state_export.add_argument("--out", required=True)
    _add_json(state_export, leaf_json)
    state_reset = state_commands.add_parser("reset")
    _add_character(state_reset)
    _add_scope(state_reset)
    state_reset.add_argument(
        "--part",
        choices=("mood", "relationship", "memory", "all"),
        required=True,
    )
    state_reset.add_argument("--dry-run", action="store_true")
    _add_json(state_reset, leaf_json)

    memory = commands.add_parser("memory")
    memory_commands = memory.add_subparsers(
        dest="memory_command",
        required=True,
    )
    memory_add = memory_commands.add_parser("add")
    _add_character(memory_add)
    _add_scope(memory_add)
    memory_add.add_argument("--host-id", required=True)
    memory_add.add_argument("--summary-file", required=True)
    _add_json(memory_add, leaf_json)
    memory_list = memory_commands.add_parser("list")
    _add_character(memory_list)
    _add_scope(memory_list)
    _add_json(memory_list, leaf_json)
    memory_remove = memory_commands.add_parser("remove")
    _add_character(memory_remove)
    _add_scope(memory_remove)
    memory_remove.add_argument("--host-id", required=True)
    memory_remove.add_argument("--dry-run", action="store_true")
    _add_json(memory_remove, leaf_json)

    suite = commands.add_parser("suite")
    suite_commands = suite.add_subparsers(
        dest="suite_command",
        required=True,
    )
    suite_install = suite_commands.add_parser("install")
    suite_install.add_argument(
        "--scope",
        choices=("user", "repo"),
        default="user",
    )
    suite_install.add_argument("--repo")
    suite_install.add_argument("--skills-root")
    suite_install.add_argument("--dry-run", action="store_true")
    _add_json(suite_install, leaf_json)


def standalone_route(args: argparse.Namespace) -> StandaloneRoute | None:
    command = getattr(args, "command", None)
    if command == "pack":
        subcommand = getattr(args, "pack_command", None)
        if subcommand in _PACK_ROUTES:
            return (command, subcommand)
        return None
    if command == "state":
        subcommand = getattr(args, "state_command", None)
        if subcommand in _STATE_ROUTES:
            return (command, subcommand)
        return None
    if command in _TOP_LEVEL_ROUTES:
        subcommand = getattr(args, f"{command}_command", None)
        if isinstance(subcommand, str):
            return (command, subcommand)
    return None


def standalone_requires_data_root(args: argparse.Namespace) -> bool:
    route = standalone_route(args)
    return route in _DATA_ROOT_ROUTES


def _input_error(code: str, message: str) -> KokoroError:
    return KokoroError(code, message)


def _input_identity(path_stat: os.stat_result) -> _InputIdentity:
    return _InputIdentity(
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        size=path_stat.st_size,
        modified_ns=path_stat.st_mtime_ns,
        file_type=stat.S_IFMT(path_stat.st_mode),
        links=path_stat.st_nlink,
    )


def _input_is_redirect(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    is_junction = getattr(path, "is_junction", None)
    try:
        if is_junction is not None and is_junction():
            return True
    except OSError as error:
        raise _input_error(
            "INPUT_READ_FAILED",
            "Input file could not be read.",
        ) from error
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(reparse and attributes & reparse)


def _argument_path(raw_path: str) -> Path:
    return Path(os.path.abspath(Path(raw_path).expanduser()))


def _input_directory_identity(path: Path) -> _InputDirectoryIdentity:
    try:
        path_stat = path.lstat()
    except OSError as error:
        raise _input_error(
            "INPUT_PATH_UNSAFE",
            "Input file path is unsafe.",
        ) from error
    if (
        not stat.S_ISDIR(path_stat.st_mode)
        or _input_is_redirect(path, path_stat)
    ):
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.")
    return _InputDirectoryIdentity(
        path=path,
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        file_type=stat.S_IFMT(path_stat.st_mode),
    )


def _input_directory_chain(path: Path) -> tuple[_InputDirectoryIdentity, ...]:
    return tuple(
        _input_directory_identity(directory)
        for directory in reversed((path.parent, *path.parent.parents))
    )


def _capture_binary(path: Path, *, max_bytes: int) -> _CapturedFile:
    directories = _input_directory_chain(path)
    try:
        path_stat = path.lstat()
    except FileNotFoundError as error:
        raise _input_error("INPUT_NOT_FOUND", "Input file was not found.") from error
    except OSError as error:
        raise _input_error(
            "INPUT_READ_FAILED",
            "Input file could not be read.",
        ) from error
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or _input_is_redirect(path, path_stat)
        or path_stat.st_nlink != 1
    ):
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.")
    if path_stat.st_size > max_bytes:
        raise _input_error("INPUT_TOO_LARGE", "Input file exceeds the size limit.")
    initial_identity = _input_identity(path_stat)
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            if _input_identity(os.fstat(handle.fileno())) != initial_identity:
                raise _input_error(
                    "INPUT_PATH_UNSAFE",
                    "Input file path is unsafe.",
                )
            contents = handle.read(max_bytes + 1)
            handle.seek(0)
            repeated = handle.read(max_bytes + 1)
            final_open_identity = _input_identity(os.fstat(handle.fileno()))
    except FileNotFoundError as error:
        raise _input_error("INPUT_NOT_FOUND", "Input file was not found.") from error
    except KokoroError:
        raise
    except OSError as error:
        raise _input_error(
            "INPUT_READ_FAILED",
            "Input file could not be read.",
        ) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    if len(contents) > max_bytes:
        raise _input_error("INPUT_TOO_LARGE", "Input file exceeds the size limit.")
    if contents != repeated or final_open_identity != initial_identity:
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.")
    try:
        final_identity = _input_identity(path.lstat())
    except OSError as error:
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.") from error
    if final_identity != initial_identity:
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.")
    if _input_directory_chain(path) != directories:
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.")
    return _CapturedFile(
        path=path,
        directories=directories,
        identity=initial_identity,
        payload=contents,
        max_bytes=max_bytes,
    )


def _audit_capture(capture: _CapturedFile) -> None:
    current = _capture_binary(capture.path, max_bytes=capture.max_bytes)
    if (
        current.directories != capture.directories
        or current.identity != capture.identity
        or current.payload != capture.payload
    ):
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.")


def _audit_captures(captures: tuple[_CapturedFile, ...]) -> None:
    for capture in captures:
        _audit_capture(capture)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite number")


def _capture_json(path: Path) -> _CapturedJson:
    captured = _capture_binary(path, max_bytes=JSON_INPUT_MAX_BYTES)
    try:
        value = json.loads(
            captured.payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise _input_error(
            "INPUT_INVALID_JSON",
            "Input file contains invalid JSON.",
        ) from error
    if not isinstance(value, dict) or find_json_incompatibility(value) is not None:
        raise _input_error(
            "INPUT_INVALID_JSON",
            "Input file contains invalid JSON.",
        )
    return _CapturedJson(file=captured, value=value)


def _output_error(code: str, message: str) -> KokoroError:
    return KokoroError(code, message)


def _output_is_redirect(
    path: Path,
    path_stat: os.stat_result,
    *,
    unsafe_code: str = "KARC_EXPORT_PATH_UNSAFE",
) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    is_junction = getattr(path, "is_junction", None)
    try:
        if is_junction is not None and is_junction():
            return True
    except OSError as error:
        raise _output_error(
            unsafe_code,
            "Archive output path is unsafe.",
        ) from error
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(reparse and attributes & reparse)


def _directory_identity(
    path: Path,
    *,
    unsafe_code: str = "KARC_EXPORT_PATH_UNSAFE",
) -> _DirectoryIdentity:
    try:
        path_stat = path.lstat()
    except OSError as error:
        raise _output_error(
            unsafe_code,
            "Archive output path is unsafe.",
        ) from error
    if (
        not stat.S_ISDIR(path_stat.st_mode)
        or _output_is_redirect(path, path_stat, unsafe_code=unsafe_code)
    ):
        raise _output_error(
            unsafe_code,
            "Archive output path is unsafe.",
        )
    return _DirectoryIdentity(
        path=path,
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        file_type=stat.S_IFMT(path_stat.st_mode),
    )


def _safe_output_component(component: str, *, unsafe_code: str) -> None:
    if (
        not component
        or component.rstrip(" .") != component
        or ":" in component
        or any(ord(character) < 32 for character in component)
        or component.split(".", 1)[0].lower() in _WINDOWS_RESERVED_NAMES
    ):
        raise _output_error(
            unsafe_code,
            "Archive output path is unsafe.",
        )


def _prepare_new_output(
    raw_path: str,
    *,
    suffix: str,
    unsafe_code: str = "KARC_EXPORT_PATH_UNSAFE",
    exists_code: str = "KARC_EXPORT_OUTPUT_EXISTS",
    write_code: str = "KARC_EXPORT_WRITE_FAILED",
    cleanup_code: str = "KARC_EXPORT_CLEANUP_FAILED",
    durability_code: str = "KARC_EXPORT_DURABILITY_FAILED",
) -> _NewOutput:
    supplied = Path(raw_path).expanduser()
    if ".." in supplied.parts:
        raise _output_error(
            unsafe_code,
            "Archive output path is unsafe.",
        )
    target = Path(os.path.abspath(supplied))
    if target.suffix.lower() != suffix:
        raise _output_error(
            unsafe_code,
            "Archive output path is unsafe.",
        )
    for component in target.parts[1:]:
        _safe_output_component(component, unsafe_code=unsafe_code)
    directories = tuple(
        _directory_identity(path, unsafe_code=unsafe_code)
        for path in reversed((target.parent, *target.parent.parents))
    )
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        target_stat = None
    except OSError as error:
        raise _output_error(
            unsafe_code,
            "Archive output path is unsafe.",
        ) from error
    if target_stat is not None:
        raise _output_error(
            exists_code,
            "Archive output already exists.",
        )
    return _NewOutput(
        target=target,
        directories=directories,
        unsafe_code=unsafe_code,
        exists_code=exists_code,
        write_code=write_code,
        cleanup_code=cleanup_code,
        durability_code=durability_code,
    )


def _audit_new_output(output: _NewOutput) -> None:
    for expected in output.directories:
        if (
            _directory_identity(
                expected.path,
                unsafe_code=output.unsafe_code,
            )
            != expected
        ):
            raise _output_error(
                output.unsafe_code,
                "Archive output path is unsafe.",
            )
    try:
        output.target.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise _output_error(
            output.unsafe_code,
            "Archive output path is unsafe.",
        ) from error
    raise _output_error(
        output.exists_code,
        "Archive output already exists.",
    )


def _node(identity: _InputIdentity) -> tuple[int, int, int]:
    return (identity.device, identity.inode, identity.file_type)


def _cleanup_staging(
    path: Path,
    expected_node: tuple[int, int, int],
    *,
    cleanup_code: str,
) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise _output_error(
            cleanup_code,
            "Output staging cleanup failed.",
        ) from error
    identity = _input_identity(path_stat)
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or _output_is_redirect(
            path,
            path_stat,
            unsafe_code=cleanup_code,
        )
        or _node(identity) != expected_node
    ):
        raise _output_error(
            cleanup_code,
            "Output staging cleanup failed.",
        )
    try:
        path.unlink()
    except OSError as error:
        raise _output_error(
            cleanup_code,
            "Output staging cleanup failed.",
        ) from error


def _fsync_directory(path: Path, *, durability_code: str) -> None:
    if os.name == "nt":
        return
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    except OSError as error:
        if error.errno not in _DIRECTORY_FSYNC_UNSUPPORTED:
            raise _output_error(
                durability_code,
                "Output durability could not be confirmed.",
            ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _publish_new_bytes(output: _NewOutput, payload: bytes) -> Path:
    descriptor = -1
    staging: Path | None = None
    staging_node: tuple[int, int, int] | None = None
    try:
        descriptor, raw_staging = tempfile.mkstemp(
            prefix=f".{output.target.name}.staging-",
            suffix=".tmp",
            dir=output.target.parent,
        )
        staging = Path(raw_staging)
        staging_identity = _input_identity(os.fstat(descriptor))
        staging_node = _node(staging_identity)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        written = _capture_binary(staging, max_bytes=len(payload))
        if _node(written.identity) != staging_node or written.payload != payload:
            raise _output_error(
                output.write_code,
                "Output file could not be written.",
            )
        _audit_new_output(output)
        os.link(staging, output.target)
        staging.unlink()
        staging = None
        _fsync_directory(
            output.target.parent,
            durability_code=output.durability_code,
        )
        published = _capture_binary(output.target, max_bytes=len(payload))
        if published.payload != payload:
            raise _output_error(
                output.write_code,
                "Output file could not be written.",
            )
        for expected in output.directories:
            if (
                _directory_identity(
                    expected.path,
                    unsafe_code=output.unsafe_code,
                )
                != expected
            ):
                raise _output_error(
                    output.unsafe_code,
                    "Archive output path is unsafe.",
                )
        return output.target
    except FileExistsError as error:
        raise _output_error(
            output.exists_code,
            "Output file already exists.",
        ) from error
    except KokoroError:
        raise
    except OSError as error:
        raise _output_error(
            output.write_code,
            "Output file could not be written.",
        ) from error
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if staging is not None and staging_node is not None:
            _cleanup_staging(
                staging,
                staging_node,
                cleanup_code=output.cleanup_code,
            )


def _handle_pack_compatibility(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    del data_root
    limits = KarcLimits()
    captured = _capture_binary(
        _argument_path(args.archive),
        max_bytes=limits.max_archive_bytes,
    )
    audit = lambda: _audit_capture(captured)
    try:
        report = inspect_karc_compatibility(
            captured.payload,
            _AuditedSchemas(schemas, audit),
            limits=limits,
        )
        return {"ok": True, "compatibility": report}
    finally:
        audit()


def _handle_pack_export(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    del data_root
    promotion_path = _argument_path(args.promotion)
    captured = {
        "compiled": _capture_json(_argument_path(args.compiled)),
        "promotion": _capture_json(promotion_path),
        "hard": _capture_json(_argument_path(args.hard_report)),
        "soft": _capture_json(_argument_path(args.soft_report)),
        "review": _capture_json(
            promotion_path.parent / "review-attestation.json"
        ),
    }
    if args.publication_report is not None:
        captured["publication"] = _capture_json(
            _argument_path(args.publication_report)
        )
    files = tuple(item.file for item in captured.values())
    output = _prepare_new_output(args.out, suffix=".karc")

    def audit() -> None:
        _audit_captures(files)
        _audit_new_output(output)

    audit()
    try:
        try:
            archive = build_karc_archive(
                compiled_pack=captured["compiled"].value,
                hard_validation_report=captured["hard"].value,
                soft_evaluation_report=captured["soft"].value,
                review_attestation=captured["review"].value,
                promotion_record=captured["promotion"].value,
                publication_readiness_report=(
                    captured["publication"].value
                    if "publication" in captured
                    else None
                ),
                schemas=_AuditedSchemas(schemas, audit),
            )
        except Exception:
            audit()
            raise
        audit()
        target = _publish_new_bytes(output, archive)
    finally:
        _audit_captures(files)
    return {
        "ok": True,
        "path": str(target),
        "archive_sha256": sha256(archive).hexdigest(),
        "visibility": captured["promotion"].value["visibility"],
    }


def _handle_pack_migrate(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    del data_root
    limits = KarcLimits()
    source = _capture_binary(
        _argument_path(args.archive),
        max_bytes=limits.max_archive_bytes,
    )
    output = _prepare_new_output(
        args.out,
        suffix=".karc",
        unsafe_code="MIGRATION_PATH_INVALID",
        exists_code="MIGRATION_OUTPUT_EXISTS",
    )
    if os.path.normcase(str(source.path)) == os.path.normcase(str(output.target)):
        raise KokoroError(
            "MIGRATION_OUTPUT_CONFLICT",
            "Migration output must differ from its input.",
        )

    def audit_pending() -> None:
        _audit_capture(source)
        _audit_new_output(output)

    audit_pending()
    try:
        preview = preview_karc_migration(
            source.payload,
            args.to_format,
            _AuditedSchemas(schemas, audit_pending),
            limits=limits,
        )
    except Exception:
        audit_pending()
        raise
    audit_pending()
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "path": str(output.target),
            "plan": preview.plan,
        }

    try:
        applied = apply_karc_migration(
            input_path=source.path,
            output_path=output.target,
            target_format_version=args.to_format,
            schemas=_AuditedSchemas(schemas, audit_pending),
            limits=limits,
        )
    except Exception:
        audit_pending()
        raise
    _audit_capture(source)
    published = _capture_binary(
        output.target,
        max_bytes=limits.max_archive_bytes,
    )
    expected_hash = applied["output_archive_sha256"]
    if sha256(published.payload).hexdigest() != expected_hash:
        raise KokoroError(
            "MIGRATION_OUTPUT_INVALID",
            "Migration output is not a current canonical archive.",
        )
    for expected in output.directories:
        if (
            _directory_identity(
                expected.path,
                unsafe_code=output.unsafe_code,
            )
            != expected
        ):
            raise KokoroError(
                "MIGRATION_PATH_INVALID",
                "Migration output ancestry changed.",
            )
    return {
        "ok": True,
        "dry_run": False,
        "path": str(output.target),
        "archive_sha256": expected_hash,
        "plan": applied,
    }


def _workspace_root(args: argparse.Namespace) -> Path | None:
    scope = getattr(args, "scope", None)
    workspace = getattr(args, "workspace", None)
    if scope == "workspace":
        if not isinstance(workspace, str) or not workspace:
            raise KokoroError(
                "ARGUMENT_INVALID",
                "Command arguments are invalid.",
            )
        return Path(workspace)
    if scope != "global" or workspace is not None:
        raise KokoroError(
            "ARGUMENT_INVALID",
            "Command arguments are invalid.",
        )
    return None


def _require_data_root(data_root: Path | None) -> Path:
    if data_root is None:
        raise KokoroError(
            "DATA_DIR_REQUIRED",
            "Set KOKOROARC_DATA_DIR before running a stateful command.",
        )
    return data_root


def _handle_pack_install(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    plan = install_karc_archive(
        _argument_path(args.archive),
        _require_data_root(data_root),
        schemas,
        workspace_root=_workspace_root(args),
        dry_run=args.dry_run,
    )
    return {
        "ok": True,
        "dry_run": bool(args.dry_run),
        "plan": plan,
        "activates_character": False,
    }


def _handle_pack_list(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    workspace = _workspace_root(args)
    scope = resolve_install_scope(workspace)
    installed = list_installed_packs(
        _require_data_root(data_root),
        schemas,
        workspace_root=workspace,
    )
    return {
        "ok": True,
        "scope": scope.kind,
        "workspace_id": scope.workspace_id,
        "installed": installed,
        "activates_character": False,
    }


def _handle_pack_remove(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    plan = remove_installed_pack(
        _require_data_root(data_root),
        args.namespace,
        args.character_id,
        args.version,
        schemas,
        workspace_root=_workspace_root(args),
        dry_run=args.dry_run,
    )
    return {
        "ok": True,
        "dry_run": bool(args.dry_run),
        "plan": plan,
        "activates_character": False,
    }


def _permission_list(raw_permissions: Any) -> tuple[str, ...]:
    if not isinstance(raw_permissions, str):
        raise KokoroError(
            "ARGUMENT_INVALID",
            "Command arguments are invalid.",
        )
    permissions = tuple(
        permission.strip() for permission in raw_permissions.split(",")
    )
    if (
        not permissions
        or any(permission not in _PERSISTENCE_PERMISSIONS for permission in permissions)
        or len(set(permissions)) != len(permissions)
    ):
        raise KokoroError(
            "ARGUMENT_INVALID",
            "Command arguments are invalid.",
        )
    return permissions


def _consent_revision(consent: dict[str, Any] | None) -> int:
    if consent is None:
        return 0
    revoked = consent.get("revoked_revision")
    if isinstance(revoked, int) and not isinstance(revoked, bool):
        return revoked
    granted = consent.get("grant_revision")
    if isinstance(granted, int) and not isinstance(granted, bool):
        return granted
    raise KokoroError(
        "PERSISTENCE_CONSENT_INVALID",
        "Persistent consent is invalid.",
    )


def _require_current_consent(
    consent: dict[str, Any] | None,
) -> dict[str, Any]:
    if consent is None:
        raise KokoroError(
            "PERSISTENCE_CONSENT_NOT_FOUND",
            "Persistent consent was not found.",
        )
    return consent


def _handle_consent_grant(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    root = _require_data_root(data_root)
    workspace = _workspace_root(args)
    current = load_consent(
        root,
        args.character,
        schemas,
        namespace=args.namespace,
        workspace_root=workspace,
    )
    consent = grant_consent(
        root,
        args.character,
        list(_permission_list(args.permissions)),
        schemas,
        namespace=args.namespace,
        version=args.version,
        workspace_root=workspace,
        expected_revision=_consent_revision(current),
    )
    return {"ok": True, "consent": consent}


def _handle_consent_show(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    consent = load_consent(
        _require_data_root(data_root),
        args.character,
        schemas,
        namespace=args.namespace,
        workspace_root=_workspace_root(args),
    )
    return {"ok": True, "consent": consent}


def _handle_consent_revoke(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    root = _require_data_root(data_root)
    workspace = _workspace_root(args)
    current = load_consent(
        root,
        args.character,
        schemas,
        namespace=args.namespace,
        workspace_root=workspace,
    )
    current = _require_current_consent(current)
    consent = revoke_consent(
        root,
        args.character,
        current["consent_id"],
        schemas,
        namespace=args.namespace,
        workspace_root=workspace,
        expected_revision=_consent_revision(current),
    )
    return {"ok": True, "consent": consent}


def _persistence_output(raw_path: str) -> _NewOutput:
    return _prepare_new_output(
        raw_path,
        suffix=".json",
        unsafe_code="PERSISTENCE_PATH_UNSAFE",
        exists_code="PERSISTENCE_OUTPUT_EXISTS",
        write_code="PERSISTENCE_WRITE_FAILED",
        cleanup_code="PERSISTENCE_CLEANUP_FAILED",
        durability_code="PERSISTENCE_DURABILITY_FAILED",
    )


def _handle_state_export(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    output = _persistence_output(args.out)
    audit = lambda: _audit_new_output(output)
    audit()
    try:
        exported = export_persistent_data(
            _require_data_root(data_root),
            args.character,
            _AuditedSchemas(schemas, audit),
            namespace=args.namespace,
            workspace_root=_workspace_root(args),
        )
    except Exception:
        audit()
        raise
    audit()
    payload = canonical_bytes(exported)
    _publish_new_bytes(output, payload)
    return {
        "ok": True,
        "export_sha256": exported["export_sha256"],
    }


def _reset_id(
    *,
    workspace: Path | None,
    namespace: str,
    character_id: str,
    consent: dict[str, Any],
    target: str,
    exported: dict[str, Any],
) -> str:
    scope = resolve_install_scope(workspace)
    identity = {
        "scope": scope.kind,
        "workspace_id": scope.workspace_id,
        "namespace": namespace,
        "character_id": character_id,
        "consent_id": consent["consent_id"],
        "consent_sha256": sha256(canonical_bytes(consent)).hexdigest(),
        "target": target,
        "export_sha256": exported["export_sha256"],
    }
    return "reset-" + sha256(canonical_bytes(identity)).hexdigest()[:32]


def _handle_state_reset(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    root = _require_data_root(data_root)
    workspace = _workspace_root(args)
    consent = _require_current_consent(
        load_consent(
            root,
            args.character,
            schemas,
            namespace=args.namespace,
            workspace_root=workspace,
        )
    )
    exported = export_persistent_data(
        root,
        args.character,
        schemas,
        namespace=args.namespace,
        workspace_root=workspace,
    )
    preview = preview_persistent_reset(
        root,
        args.character,
        consent["consent_id"],
        schemas,
        target=args.part,
        reset_id=_reset_id(
            workspace=workspace,
            namespace=args.namespace,
            character_id=args.character,
            consent=consent,
            target=args.part,
            exported=exported,
        ),
        namespace=args.namespace,
        workspace_root=workspace,
    )
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": preview.document,
        }
    result = reset_persistent_data(
        root,
        args.character,
        preview,
        consent["consent_id"],
        schemas,
        namespace=args.namespace,
        workspace_root=workspace,
    )
    return {
        "ok": True,
        "dry_run": False,
        "preview": preview.document,
        "result": result,
    }


def _memory_summary(captured: _CapturedJson) -> tuple[str, dict[str, str]]:
    value = captured.value
    if set(value) != {"summary", "localized_summaries"}:
        raise _input_error(
            "INPUT_INVALID_JSON",
            "Input file contains invalid JSON.",
        )
    summary = value["summary"]
    localized = value["localized_summaries"]
    if (
        not isinstance(summary, str)
        or not isinstance(localized, dict)
        or any(
            not isinstance(locale, str) or not isinstance(text, str)
            for locale, text in localized.items()
        )
    ):
        raise _input_error(
            "INPUT_INVALID_JSON",
            "Input file contains invalid JSON.",
        )
    return summary, localized


def _handle_memory_add(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    captured = _capture_json(_argument_path(args.summary_file))
    summary, localized = _memory_summary(captured)
    root = _require_data_root(data_root)
    workspace = _workspace_root(args)
    audit = lambda: _audit_capture(captured.file)
    audit()
    try:
        consent = _require_current_consent(
            load_consent(
                root,
                args.character,
                _AuditedSchemas(schemas, audit),
                namespace=args.namespace,
                workspace_root=workspace,
            )
        )
        reference = add_memory_reference(
            root,
            args.character,
            args.host_id,
            summary,
            localized,
            consent["consent_id"],
            _consent_revision(consent),
            _AuditedSchemas(schemas, audit),
            namespace=args.namespace,
            workspace_root=workspace,
        )
        return {"ok": True, "memory_reference": reference}
    finally:
        audit()


def _handle_memory_list(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    references = list_memory_references(
        _require_data_root(data_root),
        args.character,
        schemas,
        namespace=args.namespace,
        workspace_root=_workspace_root(args),
    )
    return {
        "ok": True,
        "memory_references": [
            {
                "reference": item.reference,
                "active_consent_generation": item.active_consent_generation,
            }
            for item in references
        ],
    }


def _handle_memory_remove(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    root = _require_data_root(data_root)
    workspace = _workspace_root(args)
    consent = _require_current_consent(
        load_consent(
            root,
            args.character,
            schemas,
            namespace=args.namespace,
            workspace_root=workspace,
        )
    )
    if args.dry_run:
        references = list_memory_references(
            root,
            args.character,
            schemas,
            namespace=args.namespace,
            workspace_root=workspace,
        )
        matching = next(
            (
                item.reference
                for item in references
                if item.reference["host_memory_id"] == args.host_id
            ),
            None,
        )
        if matching is None:
            raise KokoroError(
                "PERSISTENCE_MEMORY_NOT_FOUND",
                "Persistent memory reference was not found.",
            )
        return {
            "ok": True,
            "dry_run": True,
            "plan": {
                "action": "remove_memory_reference",
                "host_memory_id": args.host_id,
                "memory_reference_id": matching["memory_reference_id"],
                "will_remove": True,
            },
        }
    result = remove_memory_reference(
        root,
        args.character,
        args.host_id,
        consent["consent_id"],
        schemas,
        identifier_kind="host_memory_id",
        namespace=args.namespace,
        workspace_root=workspace,
    )
    return {
        "ok": True,
        "dry_run": False,
        "result": {
            "removed": result.removed,
            "memory_reference_id": result.memory_reference_id,
        },
    }


def _optional_path(raw_path: str | None) -> Path | None:
    return None if raw_path is None else Path(raw_path)


def _handle_suite_install(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    del data_root, schemas
    plan = install_skill_suite(
        scope=args.scope,
        repo_root=_optional_path(args.repo),
        skills_root=_optional_path(args.skills_root),
        dry_run=args.dry_run,
    )
    return {"ok": True, "skill_suite": plan}


_HANDLERS: dict[StandaloneRoute, StandaloneHandler] = {
    ("pack", "compatibility"): _handle_pack_compatibility,
    ("pack", "export"): _handle_pack_export,
    ("pack", "install"): _handle_pack_install,
    ("pack", "list"): _handle_pack_list,
    ("pack", "migrate"): _handle_pack_migrate,
    ("pack", "remove"): _handle_pack_remove,
    ("consent", "grant"): _handle_consent_grant,
    ("consent", "revoke"): _handle_consent_revoke,
    ("consent", "show"): _handle_consent_show,
    ("state", "export"): _handle_state_export,
    ("state", "reset"): _handle_state_reset,
    ("memory", "add"): _handle_memory_add,
    ("memory", "list"): _handle_memory_list,
    ("memory", "remove"): _handle_memory_remove,
    ("suite", "install"): _handle_suite_install,
}


def handle_standalone(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    route = standalone_route(args)
    handler = _HANDLERS.get(route) if route is not None else None
    if handler is None:
        raise KokoroError("COMMAND_FAILED", "Command could not be completed.")
    return handler(args, data_root, schemas)


__all__ = [
    "StandaloneRoute",
    "add_standalone_parsers",
    "handle_standalone",
    "standalone_requires_data_root",
    "standalone_route",
]
