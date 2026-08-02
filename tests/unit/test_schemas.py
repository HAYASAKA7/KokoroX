from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


def test_registry_rejects_missing_artifact_metadata(tmp_path: Path) -> None:
    registry = SchemaRegistry(tmp_path)
    (tmp_path / "sample.schema.json").write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
        '"type":"object","required":["schema_version"],'
        '"properties":{"schema_version":{"const":"1.0"}}}',
        encoding="utf-8",
    )
    with pytest.raises(KokoroError) as raised:
        registry.validate("sample", {})
    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == []
