from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.loader import load_source_pack, resolve_pack_file
from kokoroarc.schemas import SchemaRegistry


def assert_unsafe_reference(root: Path, reference: object) -> None:
    with pytest.raises(KokoroError) as raised:
        resolve_pack_file(root, reference)  # type: ignore[arg-type]
    assert raised.value.code == "UNSAFE_PACK_PATH"


@pytest.mark.parametrize(
    "reference",
    [
        "",
        "../outside.yaml",
        "nested/../../outside.yaml",
        "/outside.yaml",
        r"\outside.yaml",
        r"C:\outside.yaml",
        "C:/outside.yaml",
        r"\\server\share\outside.yaml",
        "//server/share/outside.yaml",
        r"nested\..\outside.yaml",
        r"nested\file.yaml",
        "notes.txt",
        "component.YAML",
        1,
        None,
    ],
)
def test_resolve_pack_file_rejects_unsafe_references(
    tmp_path: Path, reference: object
) -> None:
    assert_unsafe_reference(tmp_path, reference)


def test_resolve_pack_file_rejects_canonical_symlink_escape(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.yaml").write_text("secret: true", encoding="utf-8")
    link = pack / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("The current account cannot create directory symlinks")

    assert_unsafe_reference(pack, "linked/secret.yaml")


@pytest.mark.parametrize(
    "manifest",
    [
        "locale_files: {}\nscenario_files: {}\n",
        "files: {}\nscenario_files: {}\n",
        "files: {}\nlocale_files: {}\n",
        "files: []\nlocale_files: {}\nscenario_files: {}\n",
        "files: {}\nlocale_files: []\nscenario_files: {}\n",
        "files: {}\nlocale_files: {}\nscenario_files: []\n",
        "files: {identity: 7}\nlocale_files: {}\nscenario_files: {}\n",
        "files: {7: identity.yaml}\nlocale_files: {}\nscenario_files: {}\n",
    ],
)
def test_load_source_pack_rejects_bad_manifest_sections(
    tmp_path: Path, manifest: str
) -> None:
    (tmp_path / "character.yaml").write_text(manifest, encoding="utf-8")

    with pytest.raises(KokoroError) as raised:
        load_source_pack(tmp_path, SchemaRegistry(Path("schemas/v1")))

    assert raised.value.code == "INVALID_PACK_DATA"


def test_load_source_pack_rejects_duplicate_manifest_reference_map(
    tmp_path: Path,
) -> None:
    (tmp_path / "character.yaml").write_text(
        "files: {}\n"
        "files: {identity: identity.yaml}\n"
        "locale_files: {}\n"
        "scenario_files: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(KokoroError) as raised:
        load_source_pack(tmp_path, SchemaRegistry(Path("schemas/v1")))

    assert raised.value.code == "INVALID_PACK_DATA"


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid-utf8"])
def test_load_source_pack_wraps_referenced_target_failures(
    tmp_path: Path, kind: str
) -> None:
    (tmp_path / "character.yaml").write_text(
        "files: {identity: sensitive-target.yaml}\n"
        "locale_files: {}\n"
        "scenario_files: {}\n",
        encoding="utf-8",
    )
    target = tmp_path / "sensitive-target.yaml"
    if kind == "directory":
        target.mkdir()
    elif kind == "invalid-utf8":
        target.write_bytes(b"\xff")

    with pytest.raises(KokoroError) as raised:
        load_source_pack(tmp_path, SchemaRegistry(Path("schemas/v1")))

    assert raised.value.code == "INVALID_PACK_DATA"
    assert "sensitive-target" not in raised.value.message
    assert "sensitive-target" not in repr(raised.value.details)


@pytest.mark.parametrize("target", ["character.yaml", "identity.yaml"])
def test_load_source_pack_schema_rejects_unknown_data_fields(
    tmp_path: Path, target: str
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    pack = tmp_path / "pack"
    shutil.copytree(
        repository_root / "characters" / "original" / "rin-aster", pack
    )
    with (pack / target).open("a", encoding="utf-8") as stream:
        stream.write("\npost_load_hook: execute-this-string\n")

    with pytest.raises(KokoroError) as raised:
        load_source_pack(pack, SchemaRegistry(repository_root / "schemas" / "v1"))

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
