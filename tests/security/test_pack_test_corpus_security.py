from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from kokoroarc.errors import KokoroError
from kokoroarc.packs import security as pack_security
from kokoroarc.testing import corpus as corpus_module
from kokoroarc.testing.corpus import CorpusLimits, load_test_corpus


def complete_documents() -> dict[str, dict[str, Any]]:
    return {
        "tests/multilingual.yaml": {
            "intent": "diagnosis",
            "semantic_key": "conclusion",
            "expected_locales": ["zh-CN", "en-US", "ja-JP"],
        },
        "tests/negative.yaml": {
            "scenario": "debugging",
            "cases": [
                {
                    "case_id": "negative-one",
                    "user_need": "Incomplete evidence.",
                    "forbidden_behavior": ["invent_evidence"],
                    "safe_alternative": "Ask for evidence.",
                }
            ],
        },
        "tests/positive.yaml": {
            "scenario": "debugging",
            "cases": [
                {
                    "case_id": "positive-one",
                    "user_need": "Diagnose a regression.",
                    "expected_behavior": ["inspect_evidence"],
                    "expected_locales": {
                        "zh-CN": "检查证据。",
                        "en-US": "Inspect evidence.",
                        "ja-JP": "根拠を確認します。",
                    },
                }
            ],
        },
        "tests/protected-spans.yaml": {
            "immutable_spans": ["go test ./..."],
            "required_warning_id": "keep-command-exact",
        },
    }


def write_corpus(pack: Path, documents: dict[str, dict[str, Any]]) -> None:
    for relative, document in documents.items():
        path = pack.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def assert_rejected(pack: Path, *codes: str, limits: CorpusLimits | None = None) -> None:
    with pytest.raises(KokoroError) as raised:
        load_test_corpus(pack, limits or CorpusLimits())
    assert raised.value.code in codes


@pytest.mark.parametrize(
    "name", ["unknown.yaml", "unexpected.yml", "payload.txt"]
)
def test_rejects_unknown_test_files(tmp_path: Path, name: str) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    (pack / "tests" / name).write_text("value: inert\n", encoding="utf-8")

    assert_rejected(pack, "PACK_LIMIT_EXCEEDED", "INVALID_PACK_TEST_CORPUS")


def test_rejects_nested_or_traversal_shaped_fixture_layout(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    positive = pack / "tests" / "positive.yaml"
    contents = positive.read_bytes()
    positive.unlink()
    nested = pack / "tests" / "nested" / "..-escape"
    nested.mkdir(parents=True)
    (nested / "positive.yaml").write_bytes(contents)

    assert_rejected(pack, "PACK_LIMIT_EXCEEDED", "INVALID_PACK_TEST_CORPUS")


def test_rejects_invalid_utf8_without_leaking_payload(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    (pack / "tests" / "positive.yaml").write_bytes(b"secret-marker:\xff")

    with pytest.raises(KokoroError) as raised:
        load_test_corpus(pack)

    assert raised.value.code == "INVALID_PACK_TEST_CORPUS"
    assert raised.value.details["reason"] == "invalid_yaml"
    assert "secret-marker" not in raised.value.message
    assert "secret-marker" not in repr(raised.value.details)


@pytest.mark.parametrize(
    "contents",
    [
        "scenario: debugging\ncases: !!python/object/apply:os.system ['danger']\n",
        "scenario: debugging\ncases: !include secret.yaml\n",
        "scenario: debugging\ncases: &cycle [*cycle]\n",
        "scenario: debugging\ncases: {<<: {case_id: merged}}\n",
    ],
)
def test_rejects_tags_aliases_cycles_and_merge_keys(
    tmp_path: Path, contents: str
) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    (pack / "tests" / "positive.yaml").write_text(contents, encoding="utf-8")

    with pytest.raises(KokoroError) as raised:
        load_test_corpus(pack)

    assert raised.value.code == "INVALID_PACK_TEST_CORPUS"
    assert raised.value.details["reason"] == "invalid_yaml"
    assert "danger" not in raised.value.message
    assert "secret.yaml" not in repr(raised.value.details)


@pytest.mark.parametrize(
    "hostile_scalar",
    [
        "2023-99-99",
        "9" * 5000,
    ],
)
def test_wraps_yaml_constructor_value_errors_as_invalid_corpus(
    tmp_path: Path, hostile_scalar: str
) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    (pack / "tests" / "positive.yaml").write_text(
        f"scenario: {hostile_scalar}\ncases: []\n", encoding="utf-8"
    )

    with pytest.raises(KokoroError) as raised:
        load_test_corpus(pack)

    assert raised.value.code == "INVALID_PACK_TEST_CORPUS"
    assert raised.value.details == {"reason": "invalid_yaml"}
    assert "5000" not in raised.value.message
    assert "month" not in repr(raised.value.details)


def test_rejects_symlinked_fixture(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    positive = pack / "tests" / "positive.yaml"
    outside = tmp_path / "outside.yaml"
    outside.write_bytes(positive.read_bytes())
    positive.unlink()
    try:
        positive.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"file symlinks are unavailable: {error}")

    assert_rejected(pack, "UNSAFE_PACK_PATH")


def test_rejects_symlinked_tests_root(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    outside = tmp_path / "outside-tests"
    write_corpus(tmp_path / "outside-pack", complete_documents())
    (tmp_path / "outside-pack" / "tests").rename(outside)
    pack.mkdir()
    try:
        (pack / "tests").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")

    assert_rejected(pack, "UNSAFE_PACK_PATH")


def test_rejects_hardlinked_fixture(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    positive = pack / "tests" / "positive.yaml"
    outside = tmp_path / "outside.yaml"
    positive.replace(outside)
    try:
        os.link(outside, positive)
    except OSError as error:
        pytest.skip(f"hardlinks are unavailable: {error}")

    assert_rejected(pack, "UNSAFE_PACK_PATH")


def test_rejects_special_file_reported_by_pack_scanner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    real_entry_stat = pack_security._entry_stat

    def special_stat(entry: os.DirEntry[str], path: Path) -> os.stat_result | Any:
        result = real_entry_stat(entry, path)
        if path.name == "positive.yaml":
            return SimpleNamespace(
                st_mode=stat.S_IFIFO,
                st_size=result.st_size,
                st_nlink=1,
                st_file_attributes=0,
            )
        return result

    monkeypatch.setattr(pack_security, "_entry_stat", special_stat)

    assert_rejected(pack, "UNSAFE_PACK_PATH")


def test_rejects_source_mutation_between_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    target = pack / "tests" / "positive.yaml"
    original_read = corpus_module._read_regular
    target_reads = 0

    def mutate_after_first_read(*args: Any, **kwargs: Any) -> Any:
        nonlocal target_reads
        result = original_read(*args, **kwargs)
        if args[1] == target:
            target_reads += 1
        if args[1] == target and target_reads == 1:
            target.write_text(
                target.read_text(encoding="utf-8") + "# changed\n",
                encoding="utf-8",
            )
        return result

    monkeypatch.setattr(corpus_module, "_read_regular", mutate_after_first_read)

    assert_rejected(pack, "PACK_TEST_CORPUS_CHANGED")


def test_rejects_tree_mutation_after_fixture_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    original_scan = corpus_module.scan_pack
    calls = 0

    def mutate_before_second_scan(*args: Any, **kwargs: Any) -> list[Path]:
        nonlocal calls
        calls += 1
        if calls == 2:
            (pack / "tests" / "unexpected.yaml").write_text(
                "value: inert\n", encoding="utf-8"
            )
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(corpus_module, "scan_pack", mutate_before_second_scan)

    assert_rejected(pack, "PACK_TEST_CORPUS_CHANGED")


def test_rejects_oversized_fixture_and_total_bytes(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())

    assert_rejected(
        pack,
        "PACK_LIMIT_EXCEEDED",
        limits=CorpusLimits(max_file_bytes=32),
    )
    assert_rejected(
        pack,
        "PACK_LIMIT_EXCEEDED",
        limits=CorpusLimits(max_total_bytes=64),
    )


def test_rejects_excessive_case_count(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    documents = complete_documents()
    case = documents["tests/positive.yaml"]["cases"][0]
    second = deepcopy(case)
    second["case_id"] = "positive-two"
    documents["tests/positive.yaml"]["cases"].append(second)
    write_corpus(pack, documents)

    with pytest.raises(KokoroError) as raised:
        load_test_corpus(pack, CorpusLimits(max_cases_per_file=1))

    assert raised.value.code == "PACK_TEST_CORPUS_LIMIT_EXCEEDED"
    assert raised.value.details["limit"] == "max_cases_per_file"


def test_rejects_excessive_document_depth(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())

    with pytest.raises(KokoroError) as raised:
        load_test_corpus(pack, CorpusLimits(max_document_depth=2))

    assert raised.value.code == "PACK_TEST_CORPUS_LIMIT_EXCEEDED"
    assert raised.value.details["limit"] == "max_document_depth"


def test_rejects_oversized_scalar(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    documents = complete_documents()
    documents["tests/positive.yaml"]["cases"][0]["user_need"] = "x" * 65
    write_corpus(pack, documents)

    with pytest.raises(KokoroError) as raised:
        load_test_corpus(pack, CorpusLimits(max_scalar_chars=64))

    assert raised.value.code == "PACK_TEST_CORPUS_LIMIT_EXCEEDED"
    assert raised.value.details["limit"] == "max_scalar_chars"


def test_rejects_excessive_collection_and_node_counts(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())

    with pytest.raises(KokoroError) as collection_error:
        load_test_corpus(pack, CorpusLimits(max_collection_items=2))
    assert collection_error.value.code == "PACK_TEST_CORPUS_LIMIT_EXCEEDED"
    assert collection_error.value.details["limit"] == "max_collection_items"

    with pytest.raises(KokoroError) as node_error:
        load_test_corpus(pack, CorpusLimits(max_total_nodes=8))
    assert node_error.value.code == "PACK_TEST_CORPUS_LIMIT_EXCEEDED"
    assert node_error.value.details["limit"] == "max_total_nodes"


def test_scan_failure_happens_before_any_fixture_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = tmp_path / "pack"
    write_corpus(pack, complete_documents())
    parses: list[bytes] = []
    expected = KokoroError("UNSAFE_PACK_PATH", "unsafe")

    def fail_scan(*_args: Any, **_kwargs: Any) -> list[Path]:
        raise expected

    monkeypatch.setattr(corpus_module, "scan_pack", fail_scan)
    monkeypatch.setattr(
        corpus_module,
        "parse_yaml_bytes",
        lambda value: parses.append(value),
    )

    with pytest.raises(KokoroError) as raised:
        load_test_corpus(pack)

    assert raised.value is expected
    assert parses == []
