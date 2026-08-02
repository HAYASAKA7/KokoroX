from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from kokoroarc.errors import KokoroError


_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_SCHEMA_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_MAX_JSON_NESTING_DEPTH = 64


def _find_json_incompatibility(
    value: Any,
) -> tuple[list[str | int], str] | None:
    stack: list[tuple[bool, Any, tuple[str | int, ...], int]] = [
        (True, value, (), 0)
    ]
    active_container_ids: set[int] = set()

    while stack:
        entering, current, path, depth = stack.pop()
        if not entering:
            active_container_ids.remove(id(current))
            continue

        if current is None or isinstance(current, (bool, int, str)):
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                return list(path), "Non-finite numbers are not valid JSON artifacts."
            continue
        if not isinstance(current, (dict, list)):
            return list(path), "Artifact contains a value that is not JSON-compatible."
        if depth >= _MAX_JSON_NESTING_DEPTH:
            return list(path), "JSON artifact nesting exceeds the maximum depth."

        container_id = id(current)
        if container_id in active_container_ids:
            return list(path), "Cyclic containers are not valid JSON artifacts."

        if isinstance(current, dict):
            if any(not isinstance(key, str) for key in current):
                return list(path), "JSON artifact object keys must be strings."
            children = [
                (True, current[key], (*path, key), depth + 1)
                for key in reversed(sorted(current))
            ]
        else:
            children = [
                (True, current[index], (*path, index), depth + 1)
                for index in reversed(range(len(current)))
            ]

        active_container_ids.add(container_id)
        stack.append((False, current, path, depth))
        stack.extend(children)

    return None


class SchemaRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def load(self, name: str) -> dict[str, Any]:
        if not _SCHEMA_NAME_PATTERN.fullmatch(name):
            raise KokoroError(
                "SCHEMA_NAME_INVALID",
                "Schema name is invalid.",
                details={"schema": name},
            )

        path = (self.root / f"{name}.schema.json").resolve()
        if not path.is_relative_to(self.root):
            raise KokoroError(
                "SCHEMA_NAME_INVALID",
                "Schema name is invalid.",
                details={"schema": name},
            )
        if not path.is_file():
            raise KokoroError(
                "SCHEMA_NOT_FOUND",
                f"Schema {name!r} was not found.",
                details={"path": str(path)},
            )
        try:
            contents = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise KokoroError(
                "SCHEMA_INVALID",
                f"Schema {name!r} contains invalid UTF-8.",
                details={
                    "schema": name,
                    "path": str(path),
                    "reason": "invalid UTF-8 encoding",
                },
            ) from error
        except OSError as error:
            raise KokoroError(
                "SCHEMA_READ_FAILED",
                f"Schema {name!r} could not be read.",
                details={"path": str(path), "reason": type(error).__name__},
            ) from error

        try:
            schema = json.loads(contents)
        except json.JSONDecodeError as error:
            raise KokoroError(
                "SCHEMA_INVALID",
                f"Schema {name!r} contains invalid JSON.",
                details={
                    "schema": name,
                    "path": str(path),
                    "reason": f"{error.msg} at line {error.lineno}, column {error.colno}",
                },
            ) from error

        if not isinstance(schema, dict):
            raise KokoroError(
                "SCHEMA_INVALID",
                f"Schema {name!r} must be a JSON object.",
                details={"schema": name, "path": str(path), "reason": "root is not an object"},
            )
        if schema.get("$schema") != _DRAFT_2020_12:
            raise KokoroError(
                "SCHEMA_INVALID",
                f"Schema {name!r} must declare Draft 2020-12.",
                details={
                    "schema": name,
                    "path": str(path),
                    "reason": "unsupported $schema declaration",
                },
            )
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            raise KokoroError(
                "SCHEMA_INVALID",
                f"Schema {name!r} is not a valid Draft 2020-12 schema.",
                details={
                    "schema": name,
                    "path": str(path),
                    "reason": "Draft 2020-12 meta-schema validation failed",
                },
            ) from error
        return schema

    def validate(self, name: str, instance: Any) -> None:
        schema = self.load(name)
        incompatibility = _find_json_incompatibility(instance)
        if incompatibility is not None:
            path, message = incompatibility
            raise KokoroError(
                "SCHEMA_VALIDATION_FAILED",
                message,
                details={"schema": name, "path": path},
            )

        errors = sorted(
            Draft202012Validator(schema).iter_errors(instance),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            first = errors[0]
            raise KokoroError(
                "SCHEMA_VALIDATION_FAILED",
                first.message,
                details={"schema": name, "path": list(first.absolute_path)},
            )
