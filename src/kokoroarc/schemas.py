from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from kokoroarc.errors import KokoroError


_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_SCHEMA_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")


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
        errors = sorted(
            Draft202012Validator(self.load(name)).iter_errors(instance),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            first = errors[0]
            raise KokoroError(
                "SCHEMA_VALIDATION_FAILED",
                first.message,
                details={"schema": name, "path": list(first.absolute_path)},
            )
