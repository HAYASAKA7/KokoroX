import json
from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


ROOT = Path("tests/fixtures/research")
SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def load(tree: str, relative: str) -> dict:
    return json.loads((ROOT / tree / relative).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "timestamp,accepted",
    [
        ("2024-02-29T00:00:00Z", True), ("2000-02-29T00:00:00Z", True),
        ("2025-02-29T00:00:00Z", False), ("1900-02-29T00:00:00Z", False),
        ("2026-02-30T25:61:61+99:99", False),
    ],
)
def test_standalone_source_enforces_leap_year_calendar(timestamp: str, accepted: bool) -> None:
    source = load("complete", "sources/source-official-profile.json")
    source["accessed_at"] = timestamp
    if accepted:
        SCHEMAS.validate("research-source-record", source)
    else:
        with pytest.raises(KokoroError):
            SCHEMAS.validate("research-source-record", source)


@pytest.mark.parametrize(
    "timestamp,accepted",
    [
        ("2024-02-29T00:00:00Z", True), ("2000-02-29T00:00:00Z", True),
        ("2025-02-29T00:00:00Z", False), ("1900-02-29T00:00:00Z", False),
        ("2026-02-30T25:61:61+99:99", False),
    ],
)
def test_embedded_source_enforces_same_calendar(timestamp: str, accepted: bool) -> None:
    bundle = load("complete", "bundle.json")
    bundle["sources"][0]["accessed_at"] = timestamp
    if accepted:
        SCHEMAS.validate("research-bundle", bundle)
    else:
        with pytest.raises(KokoroError):
            SCHEMAS.validate("research-bundle", bundle)
