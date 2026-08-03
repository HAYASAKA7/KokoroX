from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.authoring import storage
from kokoroarc.authoring.drafts import build_character_draft
from kokoroarc.authoring.storage import publish_draft_bundle
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


@pytest.fixture
def original_request() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/build-request",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "mode": "original",
        "namespace": "original",
        "character_id": "rin-aster",
        "display_name": "Rin Aster",
        "character_version": "1.0.0",
        "requested_locales": ["zh-CN", "en-US", "ja-JP"],
        "intended_use_cases": ["technical collaboration"],
        "user_constraints": ["Do not fabricate certainty."],
        "inputs": [{"type": "creative_brief", "content": "An original."}],
        "requested_visibility": "private",
    }


@pytest.fixture
def source() -> dict[str, Any]:
    return json.loads(
        Path("tests/fixtures/schema/valid-character-source.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.fixture
def report() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/build-validation",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "hard_failures": [],
        "advisory_findings": [
            {
                "code": "AUTHORING_SPARSE_EXAMPLES",
                "path": ["expressions"],
                "message": "More expression examples would improve coverage.",
            }
        ],
        "locale_coverage": {"zh-CN": True, "en-US": True, "ja-JP": True},
        "provenance_counts": {
            "evidence": 0,
            "derived_profile": 1,
            "user_override": 0,
        },
        "valid": True,
    }


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    (root / "locales").mkdir(parents=True)
    (root / "character.yaml").write_bytes(b"name: Rin Aster\n")
    (root / "locales" / "en-US.yaml").write_bytes(b"greeting: hello\n")
    return root


def test_character_draft_is_deterministic_and_hashes_canonical_inputs(
    original_request: dict[str, Any], source: dict[str, Any], report: dict[str, Any]
) -> None:
    request_before = deepcopy(original_request)
    source_before = deepcopy(source)
    report_before = deepcopy(report)

    first = build_character_draft(original_request, source, report)
    second = build_character_draft(original_request, source, report)

    assert first == second
    assert first["request_hash"] == sha256(canonical_bytes(original_request)).hexdigest()
    assert first["source_pack_hash"] == sha256(canonical_bytes(source)).hexdigest()
    assert first["validation_report_hash"] == sha256(
        canonical_bytes(report)
    ).hexdigest()
    assert first["artifact_id"] == (
        f"original/rin-aster/draft/{first['source_pack_hash'][:16]}"
    )
    assert first["build_status"] == "draft"
    assert first["visibility"] == "private"
    assert first["activation_allowed"] is False
    assert first["bundle_references"] == {
        "request": "request.json",
        "source_pack": "source-pack",
        "validation_report": "validation-report.json",
    }
    assert (original_request, source, report) == (
        request_before,
        source_before,
        report_before,
    )


def test_character_draft_artifact_id_respects_schema_bound(
    original_request: dict[str, Any], source: dict[str, Any], report: dict[str, Any]
) -> None:
    original_request["namespace"] = source["namespace"] = "a" * 64
    original_request["character_id"] = source["character_id"] = "b" * 64

    draft = build_character_draft(original_request, source, report)

    assert len(draft["artifact_id"]) == 152
    SchemaRegistry(Path("schemas/v1")).validate("character-draft", draft)


def test_publish_writes_canonical_metadata_and_inert_source_bytes_under_drafts(
    tmp_path: Path,
    source_root: Path,
    original_request: dict[str, Any],
    source: dict[str, Any],
    report: dict[str, Any],
) -> None:
    hostile = b'payload: "!!python/object/apply:os.system [whoami]"\n'
    (source_root / "hostile.yaml").write_bytes(hostile)
    draft = build_character_draft(original_request, source, report)
    data_root = tmp_path / "data"

    published = publish_draft_bundle(
        data_root, source_root, original_request, draft, report
    )

    assert published == data_root / "drafts" / Path(*draft["artifact_id"].split("/"))
    assert published.is_relative_to((data_root / "drafts").resolve())
    assert (published / "draft.json").read_bytes() == canonical_bytes(draft) + b"\n"
    assert (published / "request.json").read_bytes() == (
        canonical_bytes(original_request) + b"\n"
    )
    assert (published / "validation-report.json").read_bytes() == (
        canonical_bytes(report) + b"\n"
    )
    assert (published / "source-pack" / "hostile.yaml").read_bytes() == hostile
    for reference in draft["bundle_references"].values():
        assert (published / reference).exists()


def test_publish_uses_a_same_parent_staging_directory(
    tmp_path: Path,
    source_root: Path,
    original_request: dict[str, Any],
    source: dict[str, Any],
    report: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = build_character_draft(original_request, source, report)
    observed_parents: list[Path] = []
    real_mkdtemp = storage.tempfile.mkdtemp

    def observed_mkdtemp(*args: Any, **kwargs: Any) -> str:
        observed_parents.append(Path(kwargs["dir"]))
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(storage.tempfile, "mkdtemp", observed_mkdtemp)

    published = publish_draft_bundle(
        tmp_path / "data", source_root, original_request, draft, report
    )

    assert observed_parents == [published.parent]
    assert list(published.parent.glob(f".{published.name}.staging-*")) == []


def test_publish_replaces_an_existing_complete_draft(
    tmp_path: Path,
    source_root: Path,
    original_request: dict[str, Any],
    source: dict[str, Any],
    report: dict[str, Any],
) -> None:
    draft = build_character_draft(original_request, source, report)
    data_root = tmp_path / "data"
    published = publish_draft_bundle(
        data_root, source_root, original_request, draft, report
    )
    (published / "obsolete.txt").write_bytes(b"old")
    (source_root / "character.yaml").write_bytes(b"name: Rin Aster\nrevision: 2\n")

    replaced = publish_draft_bundle(
        data_root, source_root, original_request, draft, report
    )

    assert replaced == published
    assert not (replaced / "obsolete.txt").exists()
    assert (replaced / "source-pack" / "character.yaml").read_bytes().endswith(
        b"revision: 2\n"
    )
    assert list(replaced.parent.glob(f".{replaced.name}.*-*")) == []
