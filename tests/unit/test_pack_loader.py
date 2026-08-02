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


REQUIRED_COMPONENTS = {
    "identity",
    "evidence",
    "derived_profile",
    "overrides",
    "behavior",
    "growth",
    "expressions",
}
REQUIRED_LOCALES = {"zh-CN", "en-US", "ja-JP"}


def valid_reference_manifest() -> dict[str, Any]:
    return {
        "files": {
            name: f"components/{name}.yaml" for name in REQUIRED_COMPONENTS
        },
        "locale_files": {
            name: f"locales/{name}.yaml" for name in REQUIRED_LOCALES
        },
        "scenario_files": {"debugging": "scenarios/debugging.yaml"},
    }


def scanned_manifest_paths(
    root: Path, manifest: dict[str, Any]
) -> list[Path]:
    references = {
        relative
        for section in ("files", "locale_files", "scenario_files")
        for relative in manifest[section].values()
    }
    return [
        (root / "character.yaml").resolve(),
        *((root / relative).resolve() for relative in sorted(references)),
    ]


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


@pytest.mark.parametrize(
    "contents",
    [
        "root: &root [leaf]\n"
        "level1: &level1 [*root, *root, *root, *root, *root]\n"
        "level2: &level2 [*level1, *level1, *level1, *level1, *level1]\n"
        "level3: &level3 [*level2, *level2, *level2, *level2, *level2]\n"
        "payload: *level3\n",
        "cycle: &cycle [*cycle]\n",
        "merged: {<<: {first: 1}}\n",
        "merged:\n  <<: {first: 1}\n  <<: {second: 2}\n",
        "merged: {<<: [{first: 1}, {second: 2}]}\n",
    ],
)
def test_load_yaml_rejects_aliases_and_merge_keys(
    tmp_path: Path, contents: str
) -> None:
    path = tmp_path / "aliases.yaml"
    path.write_text(contents, encoding="utf-8")

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
        "files": {
            "overrides": "overrides.yaml",
            "identity": "identity.yaml",
            "growth": "growth.yaml",
            "expressions": "expressions.yaml",
            "evidence": "evidence.yaml",
            "derived_profile": "derived.yaml",
            "behavior": "behavior.yaml",
        },
        "locale_files": {
            "zh-CN": "z.yaml",
            "ja-JP": "j.yaml",
            "en-US": "e.yaml",
        },
        "scenario_files": {"zeta": "zeta.yaml", "alpha": "alpha.yaml"},
    }
    documents = {
        "character.yaml": manifest,
        "behavior.yaml": {"value": "behavior"},
        "derived.yaml": {"value": "derived_profile"},
        "evidence.yaml": {"value": "evidence"},
        "expressions.yaml": {"value": "expressions"},
        "growth.yaml": {"value": "growth"},
        "identity.yaml": {"value": "identity"},
        "overrides.yaml": {"value": "overrides"},
        "e.yaml": {"locale": "en"},
        "j.yaml": {"locale": "ja"},
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
        return [(root / name).resolve() for name in documents]

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
        "behavior.yaml",
        "derived.yaml",
        "evidence.yaml",
        "expressions.yaml",
        "growth.yaml",
        "identity.yaml",
        "overrides.yaml",
        "e.yaml",
        "j.yaml",
        "z.yaml",
        "alpha.yaml",
        "zeta.yaml",
    ]
    assert assembled["character_id"] == "example"
    assert {name: assembled[name] for name in REQUIRED_COMPONENTS} == {
        name: {"value": name} for name in REQUIRED_COMPONENTS
    }
    assert assembled["locales"] == {
        "en-US": {"locale": "en"},
        "ja-JP": {"locale": "ja"},
        "zh-CN": {"locale": "zh"},
    }
    assert assembled["scenarios"] == {
        "alpha": {"scenario": "a"},
        "zeta": {"scenario": "z"},
    }
    assert not {"files", "locale_files", "scenario_files"} & assembled.keys()
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
    manifest = valid_reference_manifest()
    expected = KokoroError("SCHEMA_VALIDATION_FAILED", "invalid source")
    validations: list[tuple[str, dict[str, Any]]] = []

    def validate(name: str, value: dict[str, Any]) -> None:
        validations.append((name, value))
        raise expected

    scanned = scanned_manifest_paths(tmp_path, manifest)
    monkeypatch.setattr(pack_loader, "scan_pack", lambda *_args: scanned)

    def fake_load(path: Path) -> dict[str, Any]:
        if path.name == "character.yaml":
            return manifest
        return {"value": path.name}

    monkeypatch.setattr(pack_loader, "load_yaml", fake_load)

    with pytest.raises(KokoroError) as raised:
        schemas = SimpleNamespace(validate=validate)
        load_source_pack(tmp_path, schemas)  # type: ignore[arg-type]

    assert raised.value is expected
    assert len(validations) == 1
    assert validations[0][0] == "character-source"


@pytest.mark.parametrize(
    ("section", "names", "reason"),
    [
        (
            "files",
            REQUIRED_COMPONENTS - {"identity"},
            "invalid_component_names",
        ),
        (
            "files",
            REQUIRED_COMPONENTS | {"unknown"},
            "invalid_component_names",
        ),
        (
            "locale_files",
            REQUIRED_LOCALES - {"ja-JP"},
            "invalid_locale_names",
        ),
        (
            "locale_files",
            REQUIRED_LOCALES | {"fr-FR"},
            "invalid_locale_names",
        ),
        ("scenario_files", set(), "invalid_scenario_names"),
        (
            "scenario_files",
            {f"scenario_{index}" for index in range(129)},
            "invalid_scenario_names",
        ),
        ("scenario_files", {"Debugging"}, "invalid_scenario_names"),
        ("scenario_files", {"bad-name"}, "invalid_scenario_names"),
        ("scenario_files", {"9invalid"}, "invalid_scenario_names"),
        ("scenario_files", {"a" * 129}, "invalid_scenario_names"),
    ],
)
def test_load_source_pack_validates_all_reference_names_before_target_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    names: set[str],
    reason: str,
) -> None:
    manifest = valid_reference_manifest()
    for reference_section in ("files", "locale_files", "scenario_files"):
        manifest[reference_section] = {
            name: "payload.yaml" for name in manifest[reference_section]
        }
    manifest[section] = {name: "payload.yaml" for name in names}
    reads: list[str] = []

    def fake_load(path: Path) -> dict[str, Any]:
        reads.append(path.name)
        return manifest if path.name == "character.yaml" else {}

    scanned = [
        (tmp_path / "character.yaml").resolve(),
        (tmp_path / "payload.yaml").resolve(),
    ]
    monkeypatch.setattr(pack_loader, "scan_pack", lambda *_args: scanned)
    monkeypatch.setattr(pack_loader, "load_yaml", fake_load)
    schemas = SimpleNamespace(validate=lambda *_args: None)

    with pytest.raises(KokoroError) as raised:
        load_source_pack(tmp_path, schemas)  # type: ignore[arg-type]

    assert raised.value.code == "INVALID_PACK_DATA"
    assert raised.value.details == {"reason": reason}
    assert reads == ["character.yaml"]


def test_load_source_pack_does_not_read_target_missing_from_scan_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = valid_reference_manifest()
    character_path = tmp_path / "character.yaml"
    target_path = tmp_path / "components" / "identity.yaml"
    target_path.parent.mkdir()
    character_path.write_text("manifest: placeholder\n", encoding="utf-8")
    target_path.write_text("payload: present\n", encoding="utf-8")
    reads: list[Path] = []

    def fake_load(path: Path) -> dict[str, Any]:
        reads.append(path)
        return manifest if path == character_path.resolve() else {}

    scanned = set(scanned_manifest_paths(tmp_path, manifest))
    scanned.remove(target_path.resolve())
    monkeypatch.setattr(pack_loader, "scan_pack", lambda *_args: sorted(scanned))
    monkeypatch.setattr(pack_loader, "load_yaml", fake_load)
    schemas = SimpleNamespace(validate=lambda *_args: None)

    with pytest.raises(KokoroError) as raised:
        load_source_pack(tmp_path, schemas)  # type: ignore[arg-type]

    assert raised.value.code == "INVALID_PACK_DATA"
    assert raised.value.details == {"reason": "unscanned_reference"}
    assert reads == [character_path.resolve()]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("shared.yaml", "shared.yaml"),
        ("nested/shared.yaml", "nested//shared.yaml"),
    ],
)
def test_load_source_pack_rejects_duplicate_canonical_references_before_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
    second: str,
) -> None:
    manifest = valid_reference_manifest()
    manifest["locale_files"]["en-US"] = first
    manifest["locale_files"]["ja-JP"] = second
    character_path = (tmp_path / "character.yaml").resolve()
    reads: list[Path] = []

    def fake_load(path: Path) -> dict[str, Any]:
        reads.append(path)
        return manifest if path == character_path else {}

    scanned = scanned_manifest_paths(tmp_path, manifest)
    monkeypatch.setattr(pack_loader, "scan_pack", lambda *_args: scanned)
    monkeypatch.setattr(pack_loader, "load_yaml", fake_load)
    validations: list[object] = []
    schemas = SimpleNamespace(validate=lambda *_args: validations.append(_args))

    with pytest.raises(KokoroError) as raised:
        load_source_pack(tmp_path, schemas)  # type: ignore[arg-type]

    assert raised.value.code == "INVALID_PACK_DATA"
    assert raised.value.details == {"reason": "duplicate_reference"}
    assert reads == [character_path]
    assert validations == []


def test_load_source_pack_reports_duplicate_reference_before_missing_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = valid_reference_manifest()
    manifest["locale_files"]["en-US"] = "missing.yaml"
    manifest["locale_files"]["ja-JP"] = "missing.yaml"
    character_path = (tmp_path / "character.yaml").resolve()
    missing_path = (tmp_path / "missing.yaml").resolve()
    reads: list[Path] = []

    def fake_load(path: Path) -> dict[str, Any]:
        reads.append(path)
        return manifest if path == character_path else {}

    scanned = set(scanned_manifest_paths(tmp_path, manifest))
    scanned.remove(missing_path)
    monkeypatch.setattr(pack_loader, "scan_pack", lambda *_args: sorted(scanned))
    monkeypatch.setattr(pack_loader, "load_yaml", fake_load)
    schemas = SimpleNamespace(validate=lambda *_args: None)

    with pytest.raises(KokoroError) as raised:
        load_source_pack(tmp_path, schemas)  # type: ignore[arg-type]

    assert raised.value.code == "INVALID_PACK_DATA"
    assert raised.value.details == {"reason": "duplicate_reference"}
    assert reads == [character_path]


def test_load_source_pack_rejects_character_manifest_as_component_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = valid_reference_manifest()
    manifest["files"]["identity"] = "character.yaml"
    character_path = (tmp_path / "character.yaml").resolve()
    reads: list[Path] = []

    def fake_load(path: Path) -> dict[str, Any]:
        reads.append(path)
        return manifest if path == character_path else {}

    monkeypatch.setattr(
        pack_loader,
        "scan_pack",
        lambda *_args: scanned_manifest_paths(tmp_path, manifest),
    )
    monkeypatch.setattr(pack_loader, "load_yaml", fake_load)
    schemas = SimpleNamespace(validate=lambda *_args: None)

    with pytest.raises(KokoroError) as raised:
        load_source_pack(tmp_path, schemas)  # type: ignore[arg-type]

    assert raised.value.code == "INVALID_PACK_DATA"
    assert raised.value.details == {"reason": "duplicate_reference"}
    assert reads == [character_path]


def test_load_source_pack_keeps_accepted_reference_documents_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = valid_reference_manifest()
    character_path = (tmp_path / "character.yaml").resolve()
    load_counts: dict[Path, int] = {}

    def fake_load(path: Path) -> dict[str, Any]:
        load_counts[path] = load_counts.get(path, 0) + 1
        return manifest if path == character_path else {"path": str(path)}

    monkeypatch.setattr(
        pack_loader,
        "scan_pack",
        lambda *_args: scanned_manifest_paths(tmp_path, manifest),
    )
    monkeypatch.setattr(pack_loader, "load_yaml", fake_load)
    validations: list[object] = []
    schemas = SimpleNamespace(validate=lambda *_args: validations.append(_args))

    assembled = load_source_pack(tmp_path, schemas)  # type: ignore[arg-type]

    documents = [
        *(assembled[name] for name in sorted(REQUIRED_COMPONENTS)),
        *(assembled["locales"][name] for name in sorted(REQUIRED_LOCALES)),
        *assembled["scenarios"].values(),
    ]
    assert len({id(document) for document in documents}) == len(documents)
    assert set(load_counts) == set(scanned_manifest_paths(tmp_path, manifest))
    assert all(count == 1 for count in load_counts.values())
    assert len(validations) == 1
