from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable

from kokoroarc import __version__
from kokoroarc.config import Settings
from kokoroarc.errors import KokoroError
from kokoroarc.json_compat import find_json_incompatibility
from kokoroarc.packs.compiler import compile_pack, write_compiled_pack
from kokoroarc.packs.loader import load_source_pack
from kokoroarc.policy.compiler import normalize_policy
from kokoroarc.runtime.context import build_runtime_context
from kokoroarc.runtime.planning import build_render_plan
from kokoroarc.runtime.validation import validate_rendered_output
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.state.store import SessionStore
from kokoroarc.state.transitions import apply_event


JSON_INPUT_MAX_BYTES = 4 * 1024 * 1024
COMPILED_SCAN_MAX_FILES = 256
COMPILED_SCAN_MAX_BYTES = 32 * 1024 * 1024
# Compiled filenames use the first 16 lowercase SHA-256 hex characters.
SOURCE_HASH_PREFIX_LENGTH = 16
_PUBLIC_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_PUBLIC_MESSAGES = {
    "DATA_DIR_REQUIRED": "Set KOKOROARC_DATA_DIR before running a stateful command.",
    "INPUT_NOT_FOUND": "Input file was not found.",
    "INPUT_PATH_UNSAFE": "Input file path is unsafe.",
    "INPUT_READ_FAILED": "Input file could not be read.",
    "INPUT_TOO_LARGE": "Input file exceeds the size limit.",
    "INPUT_INVALID_JSON": "Input file contains invalid JSON.",
    "STATE_REVISION_CONFLICT": "Relationship state revision conflicted.",
}


def _leaf_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kokoro")
    parser.add_argument("--version", action="version", version=f"kokoro {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    pack = commands.add_parser("pack")
    pack_commands = pack.add_subparsers(dest="pack_command", required=True)
    pack_compile = pack_commands.add_parser("compile")
    pack_compile.add_argument("pack_path")
    _leaf_json(pack_compile)
    pack_validate = pack_commands.add_parser("validate")
    pack_validate.add_argument("pack_path")
    _leaf_json(pack_validate)

    session = commands.add_parser("session")
    session_commands = session.add_subparsers(dest="session_command", required=True)
    session_start = session_commands.add_parser("start")
    session_start.add_argument("--character", required=True)
    session_start.add_argument("--session", required=True)
    _leaf_json(session_start)
    session_show = session_commands.add_parser("show")
    session_show.add_argument("--session")
    _leaf_json(session_show)
    session_end = session_commands.add_parser("end")
    session_end.add_argument("--session", required=True)
    _leaf_json(session_end)

    policy = commands.add_parser("policy")
    policy_commands = policy.add_subparsers(dest="policy_command", required=True)
    policy_compile = policy_commands.add_parser("compile")
    policy_compile.add_argument("--input", required=True)
    _leaf_json(policy_compile)

    runtime = commands.add_parser("runtime")
    runtime_commands = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_context = runtime_commands.add_parser("context")
    runtime_context.add_argument("--session", required=True)
    runtime_context.add_argument("--locale", required=True)
    runtime_context.add_argument("--scenario", required=True)
    _leaf_json(runtime_context)
    runtime_plan = runtime_commands.add_parser("plan")
    runtime_plan.add_argument("--semantic", required=True)
    runtime_plan.add_argument("--policy", required=True)
    runtime_plan.add_argument("--expression-intent")
    _leaf_json(runtime_plan)
    runtime_validate = runtime_commands.add_parser("validate")
    runtime_validate.add_argument("--semantic", required=True)
    runtime_validate.add_argument("--plan", required=True)
    runtime_validate.add_argument("--rendered", required=True)
    _leaf_json(runtime_validate)

    state = commands.add_parser("state")
    state_commands = state.add_subparsers(dest="state_command", required=True)
    for name in ("preview", "apply"):
        state_command = state_commands.add_parser(name)
        state_command.add_argument("--session", required=True)
        state_command.add_argument("--event", required=True)
        _leaf_json(state_command)
    return parser


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite number")


def _input_error(code: str, message: str) -> KokoroError:
    return KokoroError(code, message)


def _read_json(path: Path, *, max_bytes: int = JSON_INPUT_MAX_BYTES) -> Any:
    try:
        path_stat = path.lstat()
    except FileNotFoundError as error:
        raise _input_error("INPUT_NOT_FOUND", "Input file was not found.") from error
    except OSError as error:
        raise _input_error("INPUT_READ_FAILED", "Input file could not be read.") from error
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    is_junction = getattr(path, "is_junction", None)
    try:
        junction = bool(is_junction is not None and is_junction())
    except OSError as error:
        raise _input_error("INPUT_READ_FAILED", "Input file could not be read.") from error
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or junction
        or bool(reparse and attributes & reparse)
    ):
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.")
    if path_stat.st_size > max_bytes:
        raise _input_error("INPUT_TOO_LARGE", "Input file exceeds the size limit.")
    try:
        with path.open("rb") as handle:
            contents = handle.read(max_bytes + 1)
    except FileNotFoundError as error:
        raise _input_error("INPUT_NOT_FOUND", "Input file was not found.") from error
    except OSError as error:
        raise _input_error("INPUT_READ_FAILED", "Input file could not be read.") from error
    if len(contents) > max_bytes:
        raise _input_error("INPUT_TOO_LARGE", "Input file exceeds the size limit.")
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise _input_error("INPUT_INVALID_JSON", "Input file contains invalid JSON.") from error
    if find_json_incompatibility(value) is not None:
        raise _input_error("INPUT_INVALID_JSON", "Input file contains invalid JSON.")
    return value


def _path_is_redirect(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        try:
            path_stat = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return False
    except OSError as error:
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.") from error
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(reparse and attributes & reparse)


def _compiled_directory(settings: Settings, *, create: bool) -> Path:
    root = settings.data_dir.resolve(strict=False)
    directory = root / "compiled"
    if _path_is_redirect(directory):
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    try:
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        resolved = directory.resolve(strict=False)
    except OSError as error:
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.") from error
    if not resolved.is_relative_to(root) or _path_is_redirect(directory):
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    if directory.exists() and not directory.is_dir():
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    return directory


def _compiled_file(settings: Settings, raw_path: str) -> Path:
    directory = _compiled_directory(settings, create=False)
    directory_resolved = directory.resolve(strict=False)
    path = Path(raw_path).expanduser()
    if _path_is_redirect(path):
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    try:
        resolved = path.resolve(strict=True)
        path_stat = path.stat(follow_symlinks=False)
    except (FileNotFoundError, OSError) as error:
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.") from error
    if (
        resolved.parent != directory_resolved
        or not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_nlink != 1
        or _path_is_redirect(path)
    ):
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    return resolved


def _validated_compiled(path: Path, schemas: SchemaRegistry) -> dict[str, Any]:
    value = _read_json(path)
    schemas.validate("compiled-pack", value)
    artifact_id = value["artifact_id"]
    components = artifact_id.split("/")
    if (
        len(components) != 3
        or not components[0]
        or components[1] != value["character_id"]
        or components[2] != "compiled"
    ):
        raise KokoroError(
            "COMPILED_IDENTITY_MISMATCH",
            "Compiled artifact identity does not match.",
        )
    return value


def _find_compiled(
    settings: Settings,
    schemas: SchemaRegistry,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    directory = _compiled_directory(settings, create=False)
    if not directory.exists():
        raise KokoroError(
            "COMPILED_PACK_NOT_FOUND",
            "Compiled artifact was not found for the session.",
        )
    matches: list[dict[str, Any]] = []
    aggregate = 0
    try:
        entries: list[os.DirEntry[str]] = []
        with os.scandir(directory) as iterator:
            for entry in iterator:
                entries.append(entry)
                if len(entries) > COMPILED_SCAN_MAX_FILES:
                    raise KokoroError(
                        "COMPILED_SCAN_LIMIT",
                        "Compiled artifact scan limit was exceeded.",
                    )
    except KokoroError:
        raise
    except OSError as error:
        raise KokoroError("COMPILED_SCAN_FAILED", "Compiled artifacts could not be scanned.") from error
    for entry in sorted(entries, key=lambda item: item.name):
        path = Path(entry.path)
        try:
            if (
                entry.is_symlink()
                or not entry.is_file(follow_symlinks=False)
                or _path_is_redirect(path)
            ):
                raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
            entry_stat = path.stat(follow_symlinks=False)
            if entry_stat.st_nlink != 1:
                raise KokoroError(
                    "COMPILED_PATH_UNSAFE",
                    "Compiled artifact path is unsafe.",
                )
            size = entry_stat.st_size
        except KokoroError:
            raise
        except OSError as error:
            raise KokoroError("COMPILED_SCAN_FAILED", "Compiled artifacts could not be scanned.") from error
        aggregate += size
        if aggregate > COMPILED_SCAN_MAX_BYTES:
            raise KokoroError("COMPILED_SCAN_LIMIT", "Compiled artifact scan limit was exceeded.")
        if path.suffix != ".json":
            raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
        compiled = _validated_compiled(path, schemas)
        if compiled["source_hash"] == manifest["compiled_pack_hash"]:
            if (
                compiled["character_id"] != manifest["character_id"]
                or compiled["character_version"]
                != manifest["character_version"]
            ):
                raise KokoroError(
                    "COMPILED_IDENTITY_MISMATCH",
                    "Compiled artifact identity does not match.",
                )
            matches.append(compiled)
    if not matches:
        raise KokoroError("COMPILED_PACK_NOT_FOUND", "Compiled artifact was not found for the session.")
    if len(matches) != 1:
        raise KokoroError("COMPILED_PACK_AMBIGUOUS", "Multiple compiled artifacts match the session.")
    return matches[0]


def _handle_pack_compile(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    source = load_source_pack(Path(args.pack_path), schemas)
    compiled = compile_pack(source, schemas)
    directory = _compiled_directory(settings, create=True)
    filename = (
        f"{compiled['character_id']}-"
        f"{compiled['source_hash'][:SOURCE_HASH_PREFIX_LENGTH]}.json"
    )
    target = directory / filename
    if _path_is_redirect(target):
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    try:
        if target.exists():
            target_stat = target.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(target_stat.st_mode)
                or target_stat.st_nlink != 1
            ):
                raise KokoroError(
                    "COMPILED_PATH_UNSAFE",
                    "Compiled artifact path is unsafe.",
                )
    except KokoroError:
        raise
    except OSError as error:
        raise KokoroError(
            "COMPILED_PATH_UNSAFE",
            "Compiled artifact path is unsafe.",
        ) from error
    try:
        write_compiled_pack(compiled, target)
    except OSError as error:
        raise KokoroError("COMPILED_WRITE_FAILED", "Compiled artifact could not be written.") from error
    return {
        "ok": True,
        "path": str(target.resolve()),
        "character_id": compiled["character_id"],
        "character_version": compiled["character_version"],
        "source_hash": compiled["source_hash"],
        "artifact_id": compiled["artifact_id"],
    }


def _handle_pack_validate(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del settings
    source = load_source_pack(Path(args.pack_path), schemas)
    return {
        "ok": True,
        "artifact_id": source["artifact_id"],
        "character_id": source["character_id"],
        "character_version": source["character_version"],
    }


def _handle_session_start(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    path = _compiled_file(settings, args.character)
    compiled = _validated_compiled(path, schemas)
    session = SessionStore(settings.data_dir).start(
        args.session,
        compiled["character_id"],
        compiled["character_version"],
        compiled["source_hash"],
    )
    return {"ok": True, "session": session}


def _handle_session_show(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del schemas
    if args.session is None:
        return {"ok": True, "session": None}
    return {
        "ok": True,
        "session": SessionStore(settings.data_dir).load(args.session),
    }


def _handle_session_end(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del schemas
    return {
        "ok": True,
        "session": SessionStore(settings.data_dir).end(args.session),
    }


def _handle_policy_compile(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del settings
    body = _read_json(Path(args.input))
    normalized = normalize_policy(body)
    policy = {
        "schema_version": "1.0",
        "artifact_id": "policy/compiled",
        "created_by": {"component": "kokoroarc", "version": __version__},
        **normalized,
    }
    schemas.validate("language-policy", policy)
    return {"ok": True, "policy": policy}


def _handle_runtime_context(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    store = SessionStore(settings.data_dir)
    manifest, state = store.snapshot(args.session)
    if not manifest["active"]:
        raise KokoroError("SESSION_NOT_ACTIVE", "Session is not active.")
    compiled = _find_compiled(settings, schemas, manifest)
    context = build_runtime_context(compiled, state, args.locale, args.scenario)
    return {"ok": True, "context": context}


def _handle_runtime_plan(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del settings
    semantic = _read_json(Path(args.semantic))
    policy = _read_json(Path(args.policy))
    schemas.validate("semantic-result", semantic)
    schemas.validate("language-policy", policy)
    plan = build_render_plan(
        semantic, policy, expression_intent=args.expression_intent
    )
    schemas.validate("render-plan", plan)
    return {"ok": True, "plan": plan}


def _handle_runtime_validate(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del settings
    semantic = _read_json(Path(args.semantic))
    plan = _read_json(Path(args.plan))
    rendered = _read_json(Path(args.rendered))
    schemas.validate("semantic-result", semantic)
    schemas.validate("render-plan", plan)
    validation = validate_rendered_output(rendered, semantic, plan)
    schemas.validate("validation-result", validation)
    return {"ok": True, "validation": validation}


def _active_compiled_and_state(
    settings: Settings,
    schemas: SchemaRegistry,
    session_id: str,
) -> tuple[
    SessionStore, dict[str, Any], dict[str, Any], dict[str, Any]
]:
    store = SessionStore(settings.data_dir)
    manifest, state = store.snapshot(session_id)
    if not manifest["active"]:
        raise KokoroError("SESSION_NOT_ACTIVE", "Session is not active.")
    compiled = _find_compiled(settings, schemas, manifest)
    return store, manifest, compiled, state


def _growth_config(compiled: dict[str, Any]) -> tuple[float, int]:
    growth = compiled["growth"]
    return (
        float(growth.get("max_delta_per_event", 4.0)),
        int(growth.get("repetition_window_turns", 3)),
    )


def _validated_event(args: argparse.Namespace, schemas: SchemaRegistry) -> dict[str, Any]:
    event = _read_json(Path(args.event))
    schemas.validate("interaction-event", event)
    return event


def _handle_state_preview(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    event = _validated_event(args, schemas)
    _store, _manifest, compiled, state = _active_compiled_and_state(
        settings, schemas, args.session
    )
    if event["event_id"] in state["applied_event_ids"]:
        return {"ok": True, "state": state}
    expected = event["expected_state_revision"]
    actual = state["revision"]
    if expected != actual:
        raise KokoroError(
            "STATE_REVISION_CONFLICT",
            "Relationship state revision conflicted.",
            retryable=True,
            details={"expected": expected, "actual": actual},
        )
    max_delta, repetition_window = _growth_config(compiled)
    preview = apply_event(
        state,
        event,
        max_delta=max_delta,
        repetition_window=repetition_window,
    )
    return {"ok": True, "state": preview}


def _handle_state_apply(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    event = _validated_event(args, schemas)
    store, manifest, compiled, _state = _active_compiled_and_state(
        settings, schemas, args.session
    )
    max_delta, repetition_window = _growth_config(compiled)
    state = store.apply(
        args.session,
        event,
        max_delta=max_delta,
        repetition_window=repetition_window,
        expected_character_id=manifest["character_id"],
        expected_character_version=manifest["character_version"],
        expected_compiled_pack_hash=manifest["compiled_pack_hash"],
        expected_lifecycle_generation=manifest["lifecycle_generation"],
    )
    return {"ok": True, "state": state}


def _public_error_envelope(error: KokoroError) -> dict[str, Any]:
    code = error.code
    if not isinstance(code, str) or _PUBLIC_ERROR_CODE.fullmatch(code) is None:
        code = "COMMAND_FAILED"
    details: dict[str, Any] = {}
    if code == "STATE_REVISION_CONFLICT":
        expected = error.details.get("expected")
        actual = error.details.get("actual")
        if (
            isinstance(expected, int)
            and not isinstance(expected, bool)
            and expected >= 0
            and isinstance(actual, int)
            and not isinstance(actual, bool)
            and actual >= 0
        ):
            details = {"expected": expected, "actual": actual}
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": _PUBLIC_MESSAGES.get(
                code, "Command could not be completed."
            ),
            "retryable": bool(error.retryable),
            "details": details,
        },
    }


_HANDLERS: dict[tuple[str, str], Callable[..., dict[str, Any]]] = {
    ("pack", "compile"): _handle_pack_compile,
    ("pack", "validate"): _handle_pack_validate,
    ("session", "start"): _handle_session_start,
    ("session", "show"): _handle_session_show,
    ("session", "end"): _handle_session_end,
    ("policy", "compile"): _handle_policy_compile,
    ("runtime", "context"): _handle_runtime_context,
    ("runtime", "plan"): _handle_runtime_plan,
    ("runtime", "validate"): _handle_runtime_validate,
    ("state", "preview"): _handle_state_preview,
    ("state", "apply"): _handle_state_apply,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env(os.environ)
        schemas = SchemaRegistry(settings.schema_dir)
        subcommand = getattr(args, f"{args.command}_command")
        result = _HANDLERS[(args.command, subcommand)](args, settings, schemas)
    except KokoroError as error:
        print(
            json.dumps(
                _public_error_envelope(error),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except (OSError, json.JSONDecodeError, UnicodeError, ValueError, TypeError):
        safe = KokoroError("COMMAND_FAILED", "Command could not be completed.")
        print(json.dumps(safe.envelope(), ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
