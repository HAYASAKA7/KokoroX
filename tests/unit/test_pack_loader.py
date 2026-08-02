from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs import loader as pack_loader
from kokoroarc.packs.loader import load_source_pack, load_yaml, resolve_pack_file
from kokoroarc.packs.security import PackLimits
from kokoroarc.schemas import SchemaRegistry


def test_resolve_pack_file_accepts_nested_yaml_path(tmp_path: Path) -> None:
    nested = tmp_path / "locales"
    nested.mkdir()
    target = nested / "en-US.yaml"
    target.write_text("register: modern", encoding="utf-8")

    assert resolve_pack_file(tmp_path, "locales/en-US.yaml") == target.resolve()


def test_load_yaml_returns_mapping_without_executing_strings(tmp_path: Path) -> None:
    path = tmp_path / "data.yaml"
    path.write_text(
        'command: "!!python/object/apply:os.system [danger]"\nvalue: 3\n',
        encoding="utf-8",
    )

    assert load_yaml(path) == {
        "command": "!!python/object/apply:os.system [danger]",
        "value": 3,
    }


@pytest.mark.parametrize(
    "contents",
    [
        "key: [unterminated",
        "key: contains\0nul",
        'payload: !!python/object/apply:os.system ["danger"]',
        "payload: !include secret.yaml",
        "plain scalar",
        "- list item",
        "null",
        "duplicate: first\nduplicate: second",
    ],
)
def test_load_yaml_rejects_invalid_or_non_mapping_documents(
    tmp_path: Path, contents: str
) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(KokoroError) as raised:
        load_yaml(path)

    assert raised.value.code == "INVALID_PACK_DATA"
    assert "unterminated" not in raised.value.message
    assert "danger" not in raised.value.message
    assert "secret.yaml" not in repr(raised.value.details)


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid-utf8"])
def test_load_yaml_wraps_read_and_decode_failures(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / "sensitive-target.yaml"
    if kind == "directory":
        path.mkdir()
    elif kind == "invalid-utf8":
        path.write_bytes(b"\xff")

    with pytest.raises(KokoroError) as raised:
        load_yaml(path)

    assert raised.value.code == "INVALID_PACK_DATA"
    assert "sensitive-target" not in raised.value.message
    assert "sensitive-target" not in repr(raised.value.details)


def test_load_yaml_wraps_excessive_document_nesting(tmp_path: Path) -> None:
    path = tmp_path / "deep.yaml"
    depth_count = 500
    contents = "".join(
        f"{'  ' * depth}key:\n" for depth in range(depth_count)
    )
    path.write_text(
        contents + "  " * depth_count + "value: true\n", encoding="utf-8"
    )

    with pytest.raises(KokoroError) as raised:
        load_yaml(path)

    assert raised.value.code == "INVALID_PACK_DATA"


def test_load_source_pack_assembles_and_validates_real_rin_pack() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source = load_source_pack(
        repository_root / "characters" / "original" / "rin-aster",
        SchemaRegistry(repository_root / "schemas" / "v1"),
    )

    assert source["character_id"] == "rin-aster"
    assert set(source["locales"]) == {"zh-CN", "en-US", "ja-JP"}
    assert source["evidence"]["authored_original"] is True


def test_load_source_pack_assembles_sorted_references_without_mutating_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest: dict[str, Any] = {
        "character_id": "example",
        "files": {"second": "b.yaml", "first": "a.yaml"},
        "locale_files": {"zh-CN": "z.yaml", "en-US": "e.yaml"},
        "scenario_files": {"zeta": "zeta.yaml", "alpha": "alpha.yaml"},
    }
    documents = {
        "character.yaml": manifest,
        "a.yaml": {"value": "a"},
        "b.yaml": {"value": "b"},
        "e.yaml": {"locale": "en"},
        "z.yaml": {"locale": "zh"},
        "alpha.yaml": {"scenario": "a"},
        "zeta.yaml": {"scenario": "z"},
    }
    original_documents = deepcopy(documents)
    events: list[str] = []

    def fake_scan(root: Path, limits: PackLimits) -> list[Path]:
        assert root == tmp_path
        assert limits == PackLimits()
        events.append("scan")
        return []

    def fake_load(path: Path) -> dict[str, Any]:
        events.append(path.name)
        return documents[path.name]

    validated: list[tuple[str, dict[str, Any]]] = []
    schemas = SimpleNamespace(
        validate=lambda name, value: validated.append((name, value))
    )
    monkeypatch.setattr(pack_loader, "scan_pack", fake_scan)
    monkeypatch.setattr(pack_loader, "load_yaml", fake_load)

    assembled = load_source_pack(tmp_path, schemas)  # type: ignore[arg-type]

    assert events == [
        "scan",
        "character.yaml",
        "a.yaml",
        "b.yaml",
        "e.yaml",
        "z.yaml",
        "alpha.yaml",
        "zeta.yaml",
    ]
    assert assembled == {
        "character_id": "example",
        "first": {"value": "a"},
        "second": {"value": "b"},
        "locales": {"en-US": {"locale": "en"}, "zh-CN": {"locale": "zh"}},
        "scenarios": {
            "alpha": {"scenario": "a"},
            "zeta": {"scenario": "z"},
        },
    }
    assert validated == [("character-source", assembled)]
    assert documents == original_documents


def test_load_source_pack_propagates_scan_failure_before_any_yaml_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = KokoroError("PACK_LIMIT_EXCEEDED", "bounded")
    reads: list[Path] = []

    def fail_scan(_root: Path, limits: PackLimits) -> list[Path]:
        assert limits == PackLimits()
        raise expected

    monkeypatch.setattr(pack_loader, "scan_pack", fail_scan)
    monkeypatch.setattr(pack_loader, "load_yaml", lambda path: reads.append(path))

    with pytest.raises(KokoroError) as raised:
        schemas = SimpleNamespace(validate=lambda *_args: None)
        load_source_pack(tmp_path, schemas)  # type: ignore[arg-type]

    assert raised.value is expected
    assert reads == []


def test_load_source_pack_propagates_schema_error_after_exactly_one_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {
        "files": {},
        "locale_files": {},
        "scenario_files": {},
    }
    expected = KokoroError("SCHEMA_VALIDATION_FAILED", "invalid source")
    validations: list[tuple[str, dict[str, Any]]] = []

    def validate(name: str, value: dict[str, Any]) -> None:
        validations.append((name, value))
        raise expected

    monkeypatch.setattr(pack_loader, "scan_pack", lambda *_args: [])
    monkeypatch.setattr(pack_loader, "load_yaml", lambda _path: manifest)

    with pytest.raises(KokoroError) as raised:
        schemas = SimpleNamespace(validate=validate)
        load_source_pack(tmp_path, schemas)  # type: ignore[arg-type]

    assert raised.value is expected
    assert validations == [
        ("character-source", {"locales": {}, "scenarios": {}})
    ]
