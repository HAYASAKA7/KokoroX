from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from kokoroarc.errors import KokoroError


class SchemaRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def load(self, name: str) -> dict[str, Any]:
        path = self.root / f"{name}.schema.json"
        if not path.is_file():
            raise KokoroError(
                "SCHEMA_NOT_FOUND",
                f"Schema {name!r} was not found.",
                details={"path": str(path)},
            )
        return json.loads(path.read_text(encoding="utf-8"))

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
