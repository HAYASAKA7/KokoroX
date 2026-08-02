from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, cast

import yaml
from yaml.constructor import ConstructorError

from kokoroarc.errors import KokoroError
from kokoroarc.packs.security import PackLimits, scan_pack
from kokoroarc.schemas import SchemaRegistry


_REFERENCE_SECTIONS = ("files", "locale_files", "scenario_files")


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
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
    if not isinstance(relative, str) or not relative:
        raise _unsafe_pack_path("reference must be a non-empty string")

    posix_path = PurePosixPath(relative)
    windows_path = PureWindowsPath(relative)
    if (
        "\\" in relative
        or posix_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or ".." in posix_path.parts
        or not relative.endswith((".yaml", ".yml"))
    ):
        raise _unsafe_pack_path("reference is not a pack-relative YAML path")

    try:
        resolved_root = root.resolve(strict=True)
        resolved = (resolved_root / relative).resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise _unsafe_pack_path("reference could not be canonicalized") from error
    if not resolved.is_relative_to(resolved_root):
        raise _unsafe_pack_path("reference escapes the pack root")
    return resolved


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise _invalid_pack_data(
            "YAML file could not be read.", "read_failed"
        ) from error

    loader: _UniqueKeySafeLoader | None = None
    try:
        loader = _UniqueKeySafeLoader(contents)
        document = loader.get_single_data()
    except (RecursionError, yaml.YAMLError) as error:
        raise _invalid_pack_data("YAML document is invalid.", "invalid_yaml") from error
    finally:
        if loader is not None:
            loader.dispose()

    if not isinstance(document, dict):
        raise _invalid_pack_data(
            "YAML document must contain a mapping.", "root_not_mapping"
        )
    return cast(dict[str, Any], document)


def load_source_pack(root: Path, schemas: SchemaRegistry) -> dict[str, Any]:
    scan_pack(root, PackLimits())
    manifest = load_yaml(resolve_pack_file(root, "character.yaml"))
    if any(not isinstance(key, str) for key in manifest):
        raise _invalid_pack_data(
            "Character pack manifest is invalid.", "invalid_manifest_key"
        )

    references = {
        section: _manifest_reference_items(manifest, section)
        for section in _REFERENCE_SECTIONS
    }
    assembled = {
        key: manifest[key]
        for key in sorted(manifest)
        if key not in _REFERENCE_SECTIONS
    }
    for component, relative in references["files"]:
        assembled[component] = load_yaml(resolve_pack_file(root, relative))
    assembled["locales"] = {
        locale: load_yaml(resolve_pack_file(root, relative))
        for locale, relative in references["locale_files"]
    }
    assembled["scenarios"] = {
        scenario: load_yaml(resolve_pack_file(root, relative))
        for scenario, relative in references["scenario_files"]
    }
    schemas.validate("character-source", assembled)
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
