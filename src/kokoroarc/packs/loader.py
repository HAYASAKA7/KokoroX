from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any, Callable, Mapping, TypeVar, cast

import yaml
from yaml.constructor import ConstructorError

from kokoroarc.errors import KokoroError
from kokoroarc.packs.security import PackLimits, scan_pack
from kokoroarc.schemas import SchemaRegistry


_REFERENCE_SECTIONS = ("files", "locale_files", "scenario_files")
_REQUIRED_COMPONENTS = frozenset(
    {
        "identity",
        "evidence",
        "derived_profile",
        "overrides",
        "behavior",
        "growth",
        "expressions",
    }
)
_REQUIRED_LOCALES = frozenset({"zh-CN", "en-US", "ja-JP"})
_SCENARIO_NAME_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
_Reference = TypeVar("_Reference")
_WINDOWS_ILLEGAL_CHARACTERS = frozenset('*?"<>|')
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "conin$",
        "conout$",
        *(f"com{digit}" for digit in "123456789¹²³"),
        *(f"lpt{digit}" for digit in "123456789¹²³"),
    }
)


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            raise ConstructorError(
                None, None, "mapping merge keys are disabled", key_node.start_mark
            )
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise ConstructorError(
                None, None, "mapping key is not hashable", key_node.start_mark
            ) from error
        if duplicate:
            raise ConstructorError(
                None, None, "duplicate mapping key", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def resolve_pack_file(root: Path, relative: str) -> Path:
    _validate_pack_reference(relative)

    try:
        resolved_root = root.resolve(strict=True)
        resolved = (resolved_root / relative).resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise _unsafe_pack_path("reference could not be canonicalized") from error
    if not resolved.is_relative_to(resolved_root):
        raise _unsafe_pack_path("reference escapes the pack root")
    return resolved


def _validate_pack_reference(relative: str) -> None:
    if not isinstance(relative, str) or not relative:
        raise _unsafe_pack_path("reference must be a non-empty string")

    posix_path = PurePosixPath(relative)
    windows_path = PureWindowsPath(relative)
    if (
        "\\" in relative
        or ":" in relative
        or posix_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or ".." in posix_path.parts
        or any(_is_unsafe_windows_component(part) for part in posix_path.parts)
        or not relative.endswith((".yaml", ".yml"))
    ):
        raise _unsafe_pack_path("reference is not a pack-relative YAML path")


def _is_unsafe_windows_component(component: str) -> bool:
    if component.endswith((" ", ".")) or any(
        character in _WINDOWS_ILLEGAL_CHARACTERS or ord(character) < 32
        for character in component
    ):
        return True
    device_name = component.split(".", 1)[0].rstrip(" ").casefold()
    return device_name in _WINDOWS_RESERVED_NAMES


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        contents = path.read_bytes()
    except OSError as error:
        raise _invalid_pack_data(
            "YAML file could not be read.", "read_failed"
        ) from error

    return parse_yaml_bytes(contents)


def parse_yaml_bytes(contents: bytes) -> dict[str, Any]:
    """Parse UTF-8 YAML bytes with the pack loader's data-only rules."""
    try:
        text = contents.decode("utf-8")
    except UnicodeError as error:
        raise _invalid_pack_data(
            "YAML file could not be read.", "read_failed"
        ) from error

    loader: _UniqueKeySafeLoader | None = None
    try:
        _reject_alias_events(text)
        loader = _UniqueKeySafeLoader(text)
        document = loader.get_single_data()
    # SafeLoader constructors can raise ordinary Python exceptions for hostile
    # implicit scalars (for example invalid timestamps or guarded huge ints).
    # Keep every data-originated parser failure inside the sanitized boundary.
    except Exception as error:
        raise _invalid_pack_data("YAML document is invalid.", "invalid_yaml") from error
    finally:
        if loader is not None:
            loader.dispose()

    if not isinstance(document, dict):
        raise _invalid_pack_data(
            "YAML document must contain a mapping.", "root_not_mapping"
        )
    return cast(dict[str, Any], document)


def _reject_alias_events(contents: str) -> None:
    events = yaml.parse(contents, Loader=yaml.SafeLoader)
    try:
        for event in events:
            if isinstance(event, yaml.events.AliasEvent):
                raise ConstructorError(
                    None, None, "YAML aliases are disabled", event.start_mark
                )
    finally:
        events.close()


def load_source_pack(root: Path, schemas: SchemaRegistry) -> dict[str, Any]:
    scanned_files = frozenset(scan_pack(root, PackLimits()))
    manifest_path = resolve_pack_file(root, "character.yaml")
    if manifest_path not in scanned_files:
        raise _invalid_pack_data(
            "Character pack reference was not found.", "unscanned_reference"
        )
    manifest = load_yaml(manifest_path)
    references = _validated_manifest_references(manifest)
    resolved_references = _resolve_reference_paths(
        root, references, scanned_files, manifest_path
    )
    source = _assemble_source_pack(
        manifest,
        resolved_references,
        load_yaml,
    )
    schemas.validate("character-source", source)
    return source


def load_source_pack_from_contents(
    contents: Mapping[str, bytes], schemas: SchemaRegistry
) -> dict[str, Any]:
    """Assemble a source pack from one already-vetted immutable byte snapshot."""
    source = assemble_source_pack_from_contents(contents)
    schemas.validate("character-source", source)
    return source


def assemble_source_pack_from_contents(
    contents: Mapping[str, bytes],
) -> dict[str, Any]:
    """Assemble snapshot bytes without applying the source schema gate."""
    try:
        files = dict(contents)
    except (TypeError, ValueError):
        raise _invalid_pack_data(
            "Character pack snapshot is invalid.", "invalid_snapshot"
        ) from None
    if any(
        not isinstance(relative, str) or not isinstance(data, bytes)
        for relative, data in files.items()
    ):
        raise _invalid_pack_data(
            "Character pack snapshot is invalid.", "invalid_snapshot"
        )
    manifest_bytes = files.get("character.yaml")
    if manifest_bytes is None:
        raise _invalid_pack_data(
            "Character pack reference was not found.", "unscanned_reference"
        )
    manifest = parse_yaml_bytes(manifest_bytes)
    references = _validated_manifest_references(manifest)
    resolved_references = _resolve_reference_contents(references, files)
    return _assemble_source_pack(
        manifest,
        resolved_references,
        lambda relative: parse_yaml_bytes(files[relative]),
    )


def _validated_manifest_references(
    manifest: dict[str, Any],
) -> dict[str, list[tuple[str, str]]]:
    if any(not isinstance(key, str) for key in manifest):
        raise _invalid_pack_data(
            "Character pack manifest is invalid.", "invalid_manifest_key"
        )
    references = {
        section: _manifest_reference_items(manifest, section)
        for section in _REFERENCE_SECTIONS
    }
    _validate_reference_names(references)
    return references


def _assemble_source_pack(
    manifest: dict[str, Any],
    resolved_references: Mapping[str, list[tuple[str, _Reference]]],
    load_document: Callable[[_Reference], dict[str, Any]],
) -> dict[str, Any]:
    assembled = {
        key: manifest[key]
        for key in sorted(manifest)
        if key not in _REFERENCE_SECTIONS
    }
    for component, reference in resolved_references["files"]:
        assembled[component] = load_document(reference)
    assembled["locales"] = {
        locale: load_document(reference)
        for locale, reference in resolved_references["locale_files"]
    }
    assembled["scenarios"] = {
        scenario: load_document(reference)
        for scenario, reference in resolved_references["scenario_files"]
    }
    return assembled


def _manifest_reference_items(
    manifest: dict[str, Any], section: str
) -> list[tuple[str, str]]:
    references = manifest.get(section)
    if not isinstance(references, dict):
        raise _invalid_pack_data(
            "Character pack manifest is invalid.", "invalid_reference_map"
        )
    if any(not isinstance(key, str) for key in references):
        raise _invalid_pack_data(
            "Character pack manifest is invalid.", "invalid_reference_name"
        )
    if any(not isinstance(reference, str) for reference in references.values()):
        raise _invalid_pack_data(
            "Character pack manifest is invalid.", "invalid_reference_value"
        )
    return sorted(references.items())


def _validate_reference_names(
    references: dict[str, list[tuple[str, str]]],
) -> None:
    component_names = {name for name, _relative in references["files"]}
    locale_names = {name for name, _relative in references["locale_files"]}
    scenario_names = {name for name, _relative in references["scenario_files"]}
    if component_names != _REQUIRED_COMPONENTS:
        raise _invalid_pack_data(
            "Character pack manifest is invalid.", "invalid_component_names"
        )
    if locale_names != _REQUIRED_LOCALES:
        raise _invalid_pack_data(
            "Character pack manifest is invalid.", "invalid_locale_names"
        )
    if (
        not 1 <= len(scenario_names) <= 128
        or any(len(name) > 128 for name in scenario_names)
        or any(
            _SCENARIO_NAME_PATTERN.fullmatch(name) is None
            for name in scenario_names
        )
    ):
        raise _invalid_pack_data(
            "Character pack manifest is invalid.", "invalid_scenario_names"
        )


def _resolve_reference_paths(
    root: Path,
    references: dict[str, list[tuple[str, str]]],
    scanned_files: frozenset[Path],
    manifest_path: Path,
) -> dict[str, list[tuple[str, Path]]]:
    resolved_references: dict[str, list[tuple[str, Path]]] = {
        section: [] for section in _REFERENCE_SECTIONS
    }
    used_paths = {manifest_path}
    for section in _REFERENCE_SECTIONS:
        for name, relative in references[section]:
            path = resolve_pack_file(root, relative)
            if path in used_paths:
                raise _invalid_pack_data(
                    "Character pack references must be independent.",
                    "duplicate_reference",
                )
            used_paths.add(path)
            resolved_references[section].append((name, path))
    for section in _REFERENCE_SECTIONS:
        for _name, path in resolved_references[section]:
            if path not in scanned_files:
                raise _invalid_pack_data(
                    "Character pack reference was not found.",
                    "unscanned_reference",
                )
    return resolved_references


def _resolve_reference_contents(
    references: dict[str, list[tuple[str, str]]],
    contents: Mapping[str, bytes],
) -> dict[str, list[tuple[str, str]]]:
    resolved_references: dict[str, list[tuple[str, str]]] = {
        section: [] for section in _REFERENCE_SECTIONS
    }
    used_paths = {"character.yaml"}
    for section in _REFERENCE_SECTIONS:
        for name, relative in references[section]:
            _validate_pack_reference(relative)
            if relative in used_paths:
                raise _invalid_pack_data(
                    "Character pack references must be independent.",
                    "duplicate_reference",
                )
            used_paths.add(relative)
            if relative not in contents:
                raise _invalid_pack_data(
                    "Character pack reference was not found.",
                    "unscanned_reference",
                )
            resolved_references[section].append((name, relative))
    return resolved_references


def _unsafe_pack_path(reason: str) -> KokoroError:
    return KokoroError(
        "UNSAFE_PACK_PATH",
        "Character pack reference is unsafe.",
        details={"reason": reason},
    )


def _invalid_pack_data(message: str, reason: str) -> KokoroError:
    return KokoroError(
        "INVALID_PACK_DATA",
        message,
        details={"reason": reason},
    )
