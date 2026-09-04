from __future__ import annotations

from copy import deepcopy
import errno
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from kokoroarc.authoring import storage
from kokoroarc.authoring.drafts import build_character_draft
from kokoroarc.authoring.storage import publish_draft_bundle
from kokoroarc.authoring.validation import validate_authoring_pack
from kokoroarc.errors import KokoroError
from kokoroarc.packs.loader import load_source_pack
from kokoroarc.schemas import SchemaRegistry
from kokoroarc import __version__


@pytest.fixture
def artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    request = {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/build-request",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "mode": "original",
        "namespace": "original",
        "character_id": "rin-aster",
        "display_name": "Rin Aster",
        "character_version": "1.0.0",
        "requested_locales": ["zh-CN", "en-US", "ja-JP"],
        "intended_use_cases": ["collaboration"],
        "user_constraints": ["Stay grounded."],
        "inputs": [{"type": "creative_brief", "content": "Original."}],
        "requested_visibility": "private",
    }
    source = load_source_pack(
        Path("characters/original/rin-aster"),
        SchemaRegistry(Path("schemas/v1")),
    )
    report = validate_authoring_pack(
        request, source, SchemaRegistry(Path("schemas/v1"))
    )
    return request, source, report, build_character_draft(request, source, report)


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    shutil.copytree(Path("characters/original/rin-aster"), root)
    return root


def _publish(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> Path:
    request, _source, report, draft = artifacts
    return publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)


def _assert_staging_mutation_fails_closed(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    marker = published / "previous.txt"
    marker.write_bytes(b"previous complete bundle")
    real_require_report = storage._require_validation_report
    calls = 0

    def inject_after_second_report_check(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        real_require_report(*args, **kwargs)
        calls += 1
        if calls == 2:
            staging = next((tmp_path / "data").rglob(".*.staging-*"))
            mutation(staging)

    monkeypatch.setattr(
        storage, "_require_validation_report", inject_after_second_report_check
    )

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert calls == 2
    assert caught.value.code == "DRAFT_STAGING_INVALID"
    assert marker.read_bytes() == b"previous complete bundle"
    assert list(published.parent.glob(f".{published.name}.staging-*")) == []
    assert list(published.parent.glob(f".{published.name}.backup-*")) == []


def _assert_fsync_entry_mutation_fails_closed(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    marker = published / "previous.txt"
    marker.write_bytes(b"previous complete bundle")
    real_fsync_tree = storage._fsync_tree_directories
    calls = 0

    def mutate_on_fsync_entry(staging: Path) -> None:
        nonlocal calls
        calls += 1
        mutation(staging)
        real_fsync_tree(staging)

    monkeypatch.setattr(storage, "_fsync_tree_directories", mutate_on_fsync_entry)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert calls == 1
    assert caught.value.code == "DRAFT_STAGING_INVALID"
    assert marker.read_bytes() == b"previous complete bundle"
    assert list(published.parent.glob(f".{published.name}.staging-*")) == []
    assert list(published.parent.glob(f".{published.name}.backup-*")) == []


def test_invalid_report_is_rejected_before_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _source, report, draft = artifacts
    report["valid"] = False
    report["hard_failures"] = [
        {"code": "FAIL", "path": [], "message": "hard failure"}
    ]
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: pytest.fail("staging must not be created"),
    )

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "AUTHORING_VALIDATION_FAILED"
    assert caught.value.details == {"reason": "hard_failures"}
    assert not (tmp_path / "data").exists()


def test_recomputed_valid_report_and_matching_draft_publish(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    published = _publish(tmp_path, source_root, artifacts)

    assert (published / "draft.json").is_file()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("character_id", "forged-character"),
        ("character_version", "2.0.0"),
        ("namespace", "forged"),
        ("display_name", "Forged Rin"),
        ("mode", "dossier"),
    ],
)
def test_schema_valid_forged_report_cannot_hide_cross_artifact_failure(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    field: str,
    value: str,
) -> None:
    request, source, report, _draft = artifacts
    request[field] = value
    request["artifact_id"] = (
        f"{request['namespace']}/{request['character_id']}/build-request"
    )
    report["artifact_id"] = (
        f"{request['namespace']}/{request['character_id']}/build-validation"
    )
    if field == "mode":
        request["inputs"] = [{"type": "user_dossier", "content": "Forged."}]
    schemas = SchemaRegistry(Path("schemas/v1"))
    schemas.validate("character-build-request", request)
    schemas.validate("build-validation-report", report)
    draft = build_character_draft(request, source, report)
    schemas.validate("character-draft", draft)

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "AUTHORING_VALIDATION_FAILED"
    assert caught.value.details == {"reason": "report_mismatch"}
    assert not (tmp_path / "data").exists()


def test_schema_valid_stale_report_and_matching_draft_cannot_publish(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    request, source, report, _draft = artifacts
    report["provenance_counts"]["evidence"] += 1
    schemas = SchemaRegistry(Path("schemas/v1"))
    schemas.validate("build-validation-report", report)
    draft = build_character_draft(request, source, report)
    schemas.validate("character-draft", draft)

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "AUTHORING_VALIDATION_FAILED"
    assert caught.value.details == {"reason": "report_mismatch"}
    assert not (tmp_path / "data").exists()


def test_report_is_rebound_at_post_copy_checkpoint(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def change_second_report(
        request: dict[str, Any],
        source: dict[str, Any],
        schemas: SchemaRegistry,
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        recomputed = validate_authoring_pack(request, source, schemas)
        if calls == 2:
            recomputed["provenance_counts"]["evidence"] += 1
        return recomputed

    monkeypatch.setattr(
        storage, "validate_authoring_pack", change_second_report, raising=False
    )

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert calls == 2
    assert caught.value.code == "AUTHORING_VALIDATION_FAILED"
    assert caught.value.details == {"reason": "report_mismatch"}
    assert not list((tmp_path / "data").rglob("draft.json"))


def test_unmodified_staged_bundle_publishes(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    published = _publish(tmp_path, source_root, artifacts)

    assert (published / "source-pack" / "character.yaml").is_file()
    assert (published / "request.json").is_file()
    assert (published / "validation-report.json").is_file()
    assert (published / "draft.json").is_file()


@pytest.mark.parametrize("mutation_kind", ["content", "hardlink"])
def test_staged_source_file_mutation_fails_closed(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    mutation_kind: str,
) -> None:
    outside = tmp_path / "outside-source.yaml"
    outside.write_bytes(b"outside staged source")

    def mutate(staging: Path) -> None:
        target = staging / "source-pack" / "behavior.yaml"
        target.unlink()
        if mutation_kind == "hardlink":
            os.link(outside, target)
        else:
            target.write_bytes(b"tampered staged source")

    _assert_staging_mutation_fails_closed(
        tmp_path, source_root, artifacts, monkeypatch, mutate
    )
    assert outside.read_bytes() == b"outside staged source"


def test_staged_source_symlink_mutation_fails_closed_when_supported(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside-source.yaml"
    outside.write_bytes(b"outside staged source")

    def mutate(staging: Path) -> None:
        target = staging / "source-pack" / "behavior.yaml"
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError as error:
            pytest.skip(f"The current account cannot create file symlinks: {error}")

    _assert_staging_mutation_fails_closed(
        tmp_path, source_root, artifacts, monkeypatch, mutate
    )
    assert outside.read_bytes() == b"outside staged source"


def test_staged_source_junction_marker_fails_closed(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marked: Path | None = None
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def is_injected_junction(path: Path) -> bool:
        return path == marked or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", is_injected_junction, raising=False)

    def mutate(staging: Path) -> None:
        nonlocal marked
        marked = staging / "source-pack" / "injected-junction"
        marked.mkdir()

    _assert_staging_mutation_fails_closed(
        tmp_path, source_root, artifacts, monkeypatch, mutate
    )


@pytest.mark.parametrize(
    "metadata_name", ["request.json", "validation-report.json", "draft.json"]
)
def test_staged_metadata_mutation_fails_closed(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    metadata_name: str,
) -> None:
    def mutate(staging: Path) -> None:
        (staging / metadata_name).write_bytes(b"{}\n")

    _assert_staging_mutation_fails_closed(
        tmp_path, source_root, artifacts, monkeypatch, mutate
    )


@pytest.mark.parametrize(
    "unexpected_entry",
    ["extra-file", "extra-directory", "source-empty-directory"],
)
def test_unexpected_staged_bundle_entry_fails_closed(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    unexpected_entry: str,
) -> None:
    def mutate(staging: Path) -> None:
        if unexpected_entry == "extra-file":
            (staging / "extra.txt").write_bytes(b"unexpected")
        elif unexpected_entry == "extra-directory":
            (staging / "extra").mkdir()
        else:
            (staging / "source-pack" / "empty-extra").mkdir()

    _assert_staging_mutation_fails_closed(
        tmp_path, source_root, artifacts, monkeypatch, mutate
    )


@pytest.mark.parametrize(
    "mutation_kind",
    [
        "content",
        "add-file",
        "remove-file",
        "add-directory",
        "remove-directory",
        "hardlink",
    ],
)
def test_fsync_entry_source_mutation_fails_closed(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    mutation_kind: str,
) -> None:
    outside = tmp_path / "outside-fsync-source.yaml"
    outside.write_bytes(b"outside fsync source")

    def mutate(staging: Path) -> None:
        source_pack = staging / "source-pack"
        target = source_pack / "behavior.yaml"
        if mutation_kind == "content":
            target.write_bytes(b"late staged content")
        elif mutation_kind == "add-file":
            (source_pack / "late.yaml").write_bytes(b"late: true\n")
        elif mutation_kind == "remove-file":
            target.unlink()
        elif mutation_kind == "add-directory":
            (source_pack / "late-directory").mkdir()
        elif mutation_kind == "remove-directory":
            shutil.rmtree(source_pack / "locales")
        else:
            target.unlink()
            os.link(outside, target)

    _assert_fsync_entry_mutation_fails_closed(
        tmp_path, source_root, artifacts, monkeypatch, mutate
    )
    assert outside.read_bytes() == b"outside fsync source"


@pytest.mark.parametrize(
    "metadata_name", ["request.json", "validation-report.json", "draft.json"]
)
def test_fsync_entry_metadata_mutation_fails_closed(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    metadata_name: str,
) -> None:
    def mutate(staging: Path) -> None:
        (staging / metadata_name).write_bytes(b"late metadata\n")

    _assert_fsync_entry_mutation_fails_closed(
        tmp_path, source_root, artifacts, monkeypatch, mutate
    )


def test_fsync_entry_symlink_mutation_fails_closed_when_supported(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside-fsync-source.yaml"
    outside.write_bytes(b"outside fsync source")

    def mutate(staging: Path) -> None:
        target = staging / "source-pack" / "behavior.yaml"
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError as error:
            pytest.skip(f"The current account cannot create file symlinks: {error}")

    _assert_fsync_entry_mutation_fails_closed(
        tmp_path, source_root, artifacts, monkeypatch, mutate
    )
    assert outside.read_bytes() == b"outside fsync source"


def test_fsync_entry_real_junction_mutation_fails_closed_when_supported(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "nt" or not hasattr(Path, "is_junction"):
        pytest.skip("Real directory junctions are unavailable on this platform")
    outside = tmp_path / "outside-junction"
    outside.mkdir()
    marker = outside / "must-not-follow.txt"
    marker.write_bytes(b"outside junction data")

    def mutate(staging: Path) -> None:
        junction = staging / "source-pack" / "late-junction"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("The current account cannot create directory junctions")

    _assert_fsync_entry_mutation_fails_closed(
        tmp_path, source_root, artifacts, monkeypatch, mutate
    )
    assert marker.read_bytes() == b"outside junction data"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report.pop("artifact_id"),
        lambda report: report["locale_coverage"].__setitem__("en-US", None),
        lambda report: report.pop("provenance_counts"),
    ],
)
def test_malformed_valid_report_is_schema_rejected_before_scan_or_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
) -> None:
    request, _source, report, draft = artifacts
    mutation(report)
    monkeypatch.setattr(
        storage,
        "scan_pack",
        lambda *args, **kwargs: pytest.fail("scan must not run"),
    )
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: pytest.fail("staging must not be created"),
    )

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"
    assert caught.value.details["schema"] == "build-validation-report"
    assert not (tmp_path / "data").exists()


def test_malformed_request_is_schema_rejected_before_scan_or_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _source, report, draft = artifacts
    request["intended_use_cases"] = []
    draft["request_hash"] = storage.sha256(storage.canonical_bytes(request)).hexdigest()
    monkeypatch.setattr(
        storage,
        "scan_pack",
        lambda *args, **kwargs: pytest.fail("scan must not run"),
    )
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: pytest.fail("staging must not be created"),
    )

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"
    assert caught.value.details["schema"] == "character-build-request"
    assert not (tmp_path / "data").exists()


def test_malformed_draft_is_schema_rejected_before_scan_or_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _source, report, draft = artifacts
    draft = deepcopy(draft)
    draft["locale_coverage"]["ja-JP"] = None
    monkeypatch.setattr(
        storage,
        "scan_pack",
        lambda *args, **kwargs: pytest.fail("scan must not run"),
    )
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: pytest.fail("staging must not be created"),
    )

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"
    assert caught.value.details["schema"] == "character-draft"
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "mutation,expected_code",
    [
        (
            lambda draft: draft.__setitem__("artifact_id", "../escape"),
            "SCHEMA_VALIDATION_FAILED",
        ),
        (
            lambda draft: draft.__setitem__("visibility", "public"),
            "SCHEMA_VALIDATION_FAILED",
        ),
        (
            lambda draft: draft.__setitem__("activation_allowed", True),
            "SCHEMA_VALIDATION_FAILED",
        ),
        (
            lambda draft: draft["bundle_references"].__setitem__(
                "request", "../request.json"
            ),
            "SCHEMA_VALIDATION_FAILED",
        ),
        (
            lambda draft: draft.__setitem__("request_hash", "0" * 64),
            "INVALID_DRAFT_DATA",
        ),
    ],
)
def test_tampered_or_traversing_draft_metadata_fails_before_writes(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    mutation: Any,
    expected_code: str,
) -> None:
    mutation(artifacts[3])

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == expected_code
    assert not (tmp_path / "data").exists()


def test_destination_redirect_component_is_rejected(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    data_root = tmp_path / "data"
    data_root.mkdir()
    redirect = data_root / "drafts"
    try:
        redirect.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"The current account cannot create directory symlinks: {exc}")
    request, _source, report, draft = artifacts

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(data_root, source_root, request, draft, report)

    assert caught.value.code == "UNSAFE_DRAFT_PATH"
    assert not any(outside.iterdir())


def test_destination_junction_component_is_rejected_without_capability_dependency(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def mark_drafts_as_junction(path: Path) -> bool:
        return path.name == "drafts" or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", mark_drafts_as_junction, raising=False)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "UNSAFE_DRAFT_PATH"
    assert caught.value.details["reason"] == "junction"


def test_unsafe_final_never_reaps_the_only_complete_recovery_backup(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    backup = published.parent / f".{published.name}.backup-{'b' * 24}"
    os.replace(published, backup)
    marker = backup / "previous.txt"
    marker.write_bytes(b"only complete recovery copy")
    published.mkdir()
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def mark_final_as_junction(path: Path) -> bool:
        return path == published or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", mark_final_as_junction, raising=False)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "UNSAFE_DRAFT_PATH"
    assert marker.read_bytes() == b"only complete recovery copy"


def test_schema_valid_but_unrelated_source_hash_is_rejected_before_publication(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    request, source, report, _draft = artifacts
    unrelated_source = deepcopy(source)
    unrelated_source["artifact_id"] = "original/rin-aster/unrelated-source"
    SchemaRegistry(Path("schemas/v1")).validate("character-source", unrelated_source)
    draft = build_character_draft(request, unrelated_source, report)

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(tmp_path / "data", source_root, request, draft, report)

    assert caught.value.code == "AUTHORING_SOURCE_HASH_MISMATCH"
    assert caught.value.details == {"reason": "assembled_source_hash"}
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("mutation_after_call", [1, 2])
def test_source_change_immediately_after_assembled_load_cannot_publish(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    mutation_after_call: int,
) -> None:
    real_load = load_source_pack
    calls = 0

    def mutate_after_first_load(root: Path, schemas: SchemaRegistry) -> dict[str, Any]:
        nonlocal calls
        loaded = real_load(root, schemas)
        calls += 1
        if calls == mutation_after_call:
            (source_root / "behavior.yaml").write_text(
                "default_intensity: subtle\n"
                "catchphrase_frequency: very_low\n"
                "correction_style: direct\n"
                "reassurance_style: practical\n",
                encoding="utf-8",
            )
        return loaded

    monkeypatch.setattr(
        storage, "load_source_pack", mutate_after_first_load, raising=False
    )

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "AUTHORING_SOURCE_CHANGED"
    assert not list((tmp_path / "data").rglob("draft.json"))


def test_source_symlink_is_rejected_without_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    target = source_root / "target.yaml"
    target.write_bytes(b"safe: true\n")
    try:
        (source_root / "alias.yaml").symlink_to(target)
    except OSError as exc:
        pytest.skip(f"The current account cannot create file symlinks: {exc}")

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "UNSAFE_PACK_PATH"
    assert not (tmp_path / "data").exists()


def test_source_hardlink_is_rejected_without_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    try:
        os.link(source_root / "character.yaml", source_root / "alias.yaml")
    except OSError as exc:
        pytest.skip(f"Hardlink creation is unavailable: {exc}")

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "UNSAFE_PACK_PATH"
    assert not (tmp_path / "data").exists()


def test_source_mutation_during_copy_fails_closed_and_cleans_staging(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_copy = storage._copy_scanned_file
    mutated = False

    def mutate_after_copy(*args: Any, **kwargs: Any) -> Any:
        nonlocal mutated
        result = real_copy(*args, **kwargs)
        if not mutated:
            mutated = True
            (source_root / "character.yaml").write_bytes(b"name: Eve\n")
        return result

    monkeypatch.setattr(storage, "_copy_scanned_file", mutate_after_copy)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "AUTHORING_SOURCE_CHANGED"
    assert not list((tmp_path / "data").rglob("*.staging-*"))
    assert not list((tmp_path / "data").rglob("draft.json"))


@pytest.mark.parametrize("failing_call", [1, 2])
def test_replace_failure_preserves_previous_draft_and_removes_residue(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    failing_call: int,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    marker = published / "previous.txt"
    marker.write_bytes(b"complete previous draft")
    real_replace = storage.os.replace
    calls = 0

    def fail_new_publish(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == failing_call:
            raise OSError("sensitive operating system detail")
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_new_publish)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "DRAFT_PUBLISH_FAILED"
    assert caught.value.retryable is False
    assert caught.value.details == {"operation": "replace", "reason": "OSError"}
    assert "sensitive" not in caught.value.message
    assert marker.read_bytes() == b"complete previous draft"
    assert list(published.parent.glob(f".{published.name}.*-*")) == []


@pytest.mark.skipif(
    os.name != "nt",
    reason="injects a Windows winerror; transient-replace retry is Windows-only",
)
def test_transient_rollback_failures_restore_previous_complete_draft(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    marker = published / "previous.txt"
    marker.write_bytes(b"complete previous draft")
    real_replace = storage.os.replace
    calls = 0

    def fail_cutover_then_rollback_transiently(
        source: str | Path, destination: str | Path
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("cutover failed")
        if calls in {3, 4}:
            error = PermissionError("transient rollback race")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_cutover_then_rollback_transiently)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "DRAFT_PUBLISH_FAILED"
    assert marker.read_bytes() == b"complete previous draft"
    assert list(published.parent.glob(f".{published.name}.*-*")) == []


@pytest.mark.parametrize("failing_stage", ["backup", "cutover"])
@pytest.mark.skipif(
    os.name != "nt",
    reason="injects a Windows winerror; transient-replace retry is Windows-only",
)
def test_transient_rename_failures_are_retried_to_successful_publication(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    failing_stage: str,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    real_replace = storage.os.replace
    failures = 0

    def fail_selected_stage_transiently(
        source: str | Path, destination: str | Path
    ) -> None:
        nonlocal failures
        source_path = Path(source)
        destination_path = Path(destination)
        is_selected = (
            failing_stage == "backup" and ".backup-" in destination_path.name
        ) or (
            failing_stage == "cutover"
            and ".staging-" in source_path.name
            and destination_path == published
        )
        if is_selected and failures < 2:
            failures += 1
            error = PermissionError("transient rename race")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_selected_stage_transiently)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    replaced = _publish(tmp_path, source_root, artifacts)

    assert replaced == published
    assert failures == 2
    assert (published / "draft.json").is_file()
    assert list(published.parent.glob(f".{published.name}.*-*")) == []


@pytest.mark.skipif(
    os.name != "nt",
    reason="injects a Windows winerror; transient-replace retry is Windows-only",
)
def test_unrecoverable_rollback_preserves_only_good_copy_at_known_backup(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    (published / "previous.txt").write_bytes(b"complete previous draft")
    real_replace = storage.os.replace
    calls = 0

    def fail_cutover_and_restore(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            error = PermissionError("sensitive restore failure")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_cutover_and_restore)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "DRAFT_RESTORE_FAILED"
    backup = Path(caught.value.details["backup_path"])
    assert backup.parent == published.parent
    assert backup.name.startswith(f".{published.name}.backup-")
    assert (backup / "previous.txt").read_bytes() == b"complete previous draft"
    assert not published.exists()
    assert "sensitive" not in caught.value.message
    assert calls == 11


def test_transient_backup_cleanup_failure_is_retried_without_failing_publish(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    real_rmtree = storage.shutil.rmtree
    calls = 0

    def transient_cleanup(path: str | Path, *args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise PermissionError("transient cleanup race")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(storage.shutil, "rmtree", transient_cleanup)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    replaced = _publish(tmp_path, source_root, artifacts)

    assert replaced == published
    assert (published / "draft.json").is_file()
    assert list(published.parent.glob(f".{published.name}.backup-*")) == []


def test_stale_backup_reaping_never_follows_redirects(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    stale = published.parent / f".{published.name}.backup-{'a' * 24}"
    stale.mkdir()
    marker = stale / "must-not-follow.txt"
    marker.write_bytes(b"outside-like data")
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)
    real_rmtree = storage.shutil.rmtree

    def mark_stale_as_junction(path: Path) -> bool:
        return path == stale or bool(real_is_junction(path))

    def reject_redirect_cleanup(path: str | Path, *args: Any, **kwargs: Any) -> None:
        assert Path(path) != stale
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_junction", mark_stale_as_junction, raising=False)
    monkeypatch.setattr(storage.shutil, "rmtree", reject_redirect_cleanup)

    replaced = _publish(tmp_path, source_root, artifacts)

    assert replaced == published
    assert marker.read_bytes() == b"outside-like data"


def test_permanent_backup_cleanup_does_not_report_complete_publish_as_failure(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    real_rmtree = storage.shutil.rmtree
    monkeypatch.setattr(
        storage.shutil,
        "rmtree",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("busy")),
    )
    replaced = _publish(tmp_path, source_root, artifacts)
    assert replaced == published
    backups = list(published.parent.glob(f".{published.name}.backup-*"))
    assert len(backups) == 1

    monkeypatch.setattr(storage.shutil, "rmtree", real_rmtree)
    _publish(tmp_path, source_root, artifacts)

    assert list(published.parent.glob(f".{published.name}.backup-*")) == []


def test_concurrent_publish_is_busy_and_cannot_reap_live_rollback_backup(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    marker_payload = b"previous complete draft"
    (published / "previous.txt").write_bytes(marker_payload)
    real_replace_directory = storage._transactional_replace_directory
    backup_live = threading.Event()
    release_first = threading.Event()
    failures: list[BaseException] = []
    first_thread: threading.Thread

    def pause_first_with_live_backup(staging: Path, target: Path) -> Path | None:
        backup = real_replace_directory(staging, target)
        if threading.current_thread() is first_thread:
            assert backup is not None
            backup_live.set()
            assert release_first.wait(timeout=10)
        return backup

    def first_publish() -> None:
        try:
            _publish(tmp_path, source_root, artifacts)
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(
        storage, "_transactional_replace_directory", pause_first_with_live_backup
    )
    first_thread = threading.Thread(target=first_publish, daemon=True)
    first_thread.start()
    assert backup_live.wait(timeout=10)
    live_backups = list(published.parent.glob(f".{published.name}.backup-*"))
    assert len(live_backups) == 1
    real_scan_pack = storage.scan_pack
    monkeypatch.setattr(
        storage,
        "scan_pack",
        lambda *args, **kwargs: pytest.fail(
            "a contending publisher must fail before source validation"
        ),
    )

    try:
        with pytest.raises(KokoroError) as caught:
            _publish(tmp_path, source_root, artifacts)

        assert caught.value.code == "DRAFT_PUBLISH_BUSY"
        assert caught.value.retryable is True
        assert caught.value.details == {"reason": "target_locked"}
        assert "previous" not in caught.value.message.lower()
        assert (live_backups[0] / "previous.txt").read_bytes() == marker_payload
    finally:
        monkeypatch.setattr(storage, "scan_pack", real_scan_pack)
        release_first.set()
        first_thread.join(timeout=10)

    assert not first_thread.is_alive()
    assert failures == []
    assert _publish(tmp_path, source_root, artifacts) == published
    lock_files = list(published.parent.glob(f".{published.name}.publish.lock"))
    assert len(lock_files) == 1
    assert lock_files[0].is_file()


@pytest.mark.parametrize("mutation", ["identity", "redirect"])
def test_publish_rejects_changed_non_parent_lock_ancestor_before_cutover(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    marker_payload = b"previous complete draft"
    (published / "previous.txt").write_bytes(marker_payload)
    ancestor = published.parents[3]
    real_lstat = Path.lstat
    real_is_redirect = storage._stat_is_redirect
    real_verify = storage._verify_staged_bundle
    armed = False

    def changed_ancestor_lstat(path: Path) -> Any:
        path_stat = real_lstat(path)
        if armed and path == ancestor and mutation == "identity":
            return SimpleNamespace(
                st_mode=path_stat.st_mode,
                st_dev=path_stat.st_dev,
                st_ino=path_stat.st_ino + 1,
                st_file_attributes=(
                    getattr(path_stat, "st_file_attributes", 0) or 0
                ),
            )
        return path_stat

    def changed_ancestor_redirect(path: Path, path_stat: os.stat_result) -> bool:
        return (
            armed and path == ancestor and mutation == "redirect"
        ) or real_is_redirect(path, path_stat)

    def arm_after_staging_verification(*args: Any, **kwargs: Any) -> None:
        nonlocal armed
        real_verify(*args, **kwargs)
        armed = True

    monkeypatch.setattr(Path, "lstat", changed_ancestor_lstat)
    monkeypatch.setattr(storage, "_stat_is_redirect", changed_ancestor_redirect)
    monkeypatch.setattr(
        storage, "_verify_staged_bundle", arm_after_staging_verification
    )

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "UNSAFE_DRAFT_PATH"
    assert caught.value.details["reason"] == "publication lock ancestor changed"
    assert (published / "previous.txt").read_bytes() == marker_payload
    assert list(published.parent.glob(f".{published.name}.backup-*")) == []


@pytest.mark.parametrize(
    "failure_kind",
    ["lock", "lock_stat_error", "ancestor"],
)
def test_publication_lock_owns_restats_every_ancestor_after_early_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    final = tmp_path / "data" / "drafts" / "original" / "rin-aster" / "draft"
    storage._create_secure_directories(final.parent)

    with storage._acquire_publication_lock(final) as publication_lock:
        expected_paths = [
            identity.path for identity in publication_lock.ancestor_chain
        ]
        inspected_paths: list[Path] = []
        real_lstat = Path.lstat
        real_safe_lock_parent = storage._safe_lock_parent

        def record_ancestor_lstat(path: Path) -> os.stat_result:
            if failure_kind == "lock_stat_error" and path == publication_lock.path:
                raise OSError("lock path unavailable")
            if path in expected_paths:
                inspected_paths.append(path)
            return real_lstat(path)

        def reject_first_ancestor(
            path: Path, path_stat: os.stat_result
        ) -> bool:
            if failure_kind == "ancestor" and path == expected_paths[0]:
                return False
            return real_safe_lock_parent(path, path_stat)

        monkeypatch.setattr(Path, "lstat", record_ancestor_lstat)
        monkeypatch.setattr(storage, "_safe_lock_parent", reject_first_ancestor)
        if failure_kind == "lock":
            monkeypatch.setattr(
                storage,
                "_safe_lock_stats",
                lambda *args: False,
            )

        assert not publication_lock.owns(final)
        assert inspected_paths == expected_paths


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX symlink semantics")
def test_posix_ancestor_substitution_is_rejected_before_cutover(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    marker_payload = b"previous complete draft"
    (published / "previous.txt").write_bytes(marker_payload)
    ancestor = published.parents[3]
    moved_ancestor = ancestor.with_name(f"{ancestor.name}-moved")
    verification_complete = threading.Event()
    release_publish = threading.Event()
    failures: list[BaseException] = []
    real_verify = storage._verify_staged_bundle

    def pause_after_staging_verification(*args: Any, **kwargs: Any) -> None:
        real_verify(*args, **kwargs)
        verification_complete.set()
        assert release_publish.wait(timeout=10)

    def publish_again() -> None:
        try:
            _publish(tmp_path, source_root, artifacts)
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(
        storage, "_verify_staged_bundle", pause_after_staging_verification
    )
    worker = threading.Thread(target=publish_again, daemon=True)
    worker.start()
    assert verification_complete.wait(timeout=10)
    ancestor.rename(moved_ancestor)
    ancestor.symlink_to(moved_ancestor, target_is_directory=True)

    try:
        release_publish.set()
        worker.join(timeout=10)
    finally:
        release_publish.set()
        worker.join(timeout=10)

    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], KokoroError)
    assert failures[0].code == "UNSAFE_DRAFT_PATH"
    assert failures[0].details["reason"] == "publication lock ancestor changed"
    moved_published = moved_ancestor / published.relative_to(ancestor)
    assert (moved_published / "previous.txt").read_bytes() == marker_payload
    assert list(moved_published.parent.glob(f".{published.name}.backup-*")) == []


@pytest.mark.parametrize(
    "exception_factory",
    [
        lambda: KokoroError("PACK_SCAN_FAILED", "Injected failure."),
        lambda: PermissionError("Injected failure."),
        lambda: KeyboardInterrupt(),
    ],
    ids=["kokoro-error", "os-error", "base-exception"],
)
def test_publish_lock_releases_after_publication_error(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    exception_factory: Any,
) -> None:
    real_scan_pack = storage.scan_pack
    calls = 0
    injected = exception_factory()

    def fail_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise injected
        return real_scan_pack(*args, **kwargs)

    monkeypatch.setattr(storage, "scan_pack", fail_once)

    with pytest.raises(type(injected)):
        _publish(tmp_path, source_root, artifacts)

    published = _publish(tmp_path, source_root, artifacts)
    assert published.is_dir()


def test_process_exit_auto_releases_publication_lock(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    request, _source, report, draft = artifacts
    data_root = tmp_path / "data"
    published = data_root / "drafts" / Path(*draft["artifact_id"].split("/"))
    published.parent.mkdir(parents=True)
    script = (
        "import sys,time;"
        f"sys.path.insert(0,{str(Path('src').resolve())!r});"
        "from pathlib import Path;"
        "from kokoroarc.authoring.storage import _acquire_publication_lock;"
        "lock=_acquire_publication_lock(Path(sys.argv[1]));"
        "print('LOCKED',flush=True);"
        "time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(published)],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "LOCKED"
        process.kill()
        assert process.wait(timeout=10) != 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    recovered = publish_draft_bundle(data_root, source_root, request, draft, report)
    assert recovered == published


def test_stale_backup_reaper_requires_live_target_lock_owner(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    stale = published.parent / f".{published.name}.backup-{'b' * 24}"
    stale.mkdir()
    marker = stale / "preserved.txt"
    marker.write_bytes(b"stale complete bundle")
    released_lock = storage._acquire_publication_lock(published)
    released_lock.release()

    with pytest.raises(RuntimeError, match="requires the target publication lock"):
        storage._reap_stale_backups(published, released_lock)

    assert marker.read_bytes() == b"stale complete bundle"
    assert _publish(tmp_path, source_root, artifacts) == published
    assert not stale.exists()


def test_publish_rejects_hardlinked_target_lock_file(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    request, _source, report, draft = artifacts
    data_root = tmp_path / "data"
    published = data_root / "drafts" / Path(*draft["artifact_id"].split("/"))
    published.parent.mkdir(parents=True)
    outside = tmp_path / "outside-lock-target"
    outside.write_bytes(b"must remain unchanged")
    lock_path = published.parent / f".{published.name}.publish.lock"
    os.link(outside, lock_path)

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(data_root, source_root, request, draft, report)

    assert caught.value.code == "UNSAFE_DRAFT_PATH"
    assert outside.read_bytes() == b"must remain unchanged"
    assert not published.exists()


def test_reserved_device_identity_is_rejected_before_storage_creation(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    request, _source, report, draft = deepcopy(artifacts)
    request["namespace"] = "con"
    draft["namespace"] = "con"
    data_root = tmp_path / "data"

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(data_root, source_root, request, draft, report)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"
    assert not data_root.exists()


def test_storage_defense_rejects_reserved_device_identity_as_unsafe(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _source, report, draft = deepcopy(artifacts)
    request["character_id"] = "lpt1"
    draft["character_id"] = "lpt1"
    data_root = tmp_path / "data"
    monkeypatch.setattr(storage.SchemaRegistry, "validate", lambda *args: None)

    with pytest.raises(KokoroError) as caught:
        publish_draft_bundle(data_root, source_root, request, draft, report)

    assert caught.value.code == "UNSAFE_DRAFT_PATH"
    assert caught.value.details["reason"] == "reserved device name"
    assert not data_root.exists()


def test_directory_fsync_eacces_is_a_durability_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage.os, "name", "posix")

    def deny_directory_open(*args: Any, **kwargs: Any) -> int:
        raise OSError(errno.EACCES, "sensitive permission failure")

    monkeypatch.setattr(storage.os, "open", deny_directory_open)

    with pytest.raises(KokoroError) as caught:
        storage._fsync_directory(tmp_path)

    assert caught.value.code == "DRAFT_PUBLISH_FAILED"
    assert caught.value.details == {
        "operation": "fsync_directory",
        "reason": "PermissionError",
    }
    assert "sensitive" not in caught.value.message


def test_secure_directory_creation_reports_every_new_component(
    tmp_path: Path,
) -> None:
    target = tmp_path / "data" / "drafts" / "original"

    created = storage._create_secure_directories(target)

    assert created == (
        tmp_path / "data",
        tmp_path / "data" / "drafts",
        target,
    )


def test_first_publication_syncs_each_directory_and_containing_parent_in_order(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _request, _source, _report, draft = artifacts
    data_root = tmp_path / "data"
    final = data_root / "drafts" / Path(*draft["artifact_id"].split("/"))
    directories = [data_root]
    current = data_root
    for part in final.parent.relative_to(data_root).parts:
        current /= part
        directories.append(current)
    expected_calls = [
        path
        for directory in directories
        for path in (directory, directory.parent)
    ]
    calls: list[Path] = []
    monkeypatch.setattr(storage, "_fsync_directory", calls.append)

    published = _publish(tmp_path, source_root, artifacts)

    assert published == final
    assert calls[: len(expected_calls)] == expected_calls


@pytest.mark.parametrize(
    "failure_point",
    ["new_directory", "existing_containing_parent"],
)
def test_first_publication_directory_sync_failure_never_publishes_bundle(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    _request, _source, _report, draft = artifacts
    data_root = tmp_path / "data"
    final = data_root / "drafts" / Path(*draft["artifact_id"].split("/"))
    failure_path = (
        data_root / "drafts"
        if failure_point == "new_directory"
        else data_root.parent
    )

    def fail_selected_directory(path: Path) -> None:
        if path == failure_path:
            raise KokoroError(
                "DRAFT_PUBLISH_FAILED",
                "Character draft publication failed.",
                details={
                    "operation": "fsync_directory",
                    "reason": "PermissionError",
                },
            )

    monkeypatch.setattr(storage, "_fsync_directory", fail_selected_directory)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "DRAFT_PUBLISH_FAILED"
    assert caught.value.details == {
        "operation": "fsync_directory",
        "reason": "PermissionError",
    }
    assert not final.exists()
    assert list(final.parent.glob(f".{final.name}.staging-*")) == []


def test_parent_fsync_failure_preserves_previous_complete_bundle(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish(tmp_path, source_root, artifacts)
    marker_payload = b"complete previous draft"
    (published / "previous.txt").write_bytes(marker_payload)
    real_fsync_directory = storage._fsync_directory
    failed = False

    def fail_publish_parent_once(path: Path) -> None:
        nonlocal failed
        if path == published.parent and not failed:
            failed = True
            raise KokoroError(
                "DRAFT_PUBLISH_FAILED",
                "Character draft publication failed.",
                details={"operation": "fsync_directory", "reason": "OSError"},
            )
        real_fsync_directory(path)

    monkeypatch.setattr(storage, "_fsync_directory", fail_publish_parent_once)

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "DRAFT_DURABILITY_FAILED"
    if published.exists():
        preserved = published
    else:
        preserved = Path(caught.value.details["backup_path"])
    assert (preserved / "previous.txt").read_bytes() == marker_payload
    assert not list(published.parent.glob(f".{published.name}.staging-*"))


def test_staging_creation_failure_is_sanitized_without_residue(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = PermissionError("sensitive staging failure")
    monkeypatch.setattr(
        storage.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: (_ for _ in ()).throw(expected),
    )

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "DRAFT_PUBLISH_FAILED"
    assert caught.value.details == {
        "operation": "create_staging",
        "reason": "PermissionError",
    }
    assert "sensitive" not in caught.value.message
    assert not list((tmp_path / "data").rglob("*.staging-*"))


def test_unsupported_source_entry_fails_closed(
    tmp_path: Path,
    source_root: Path,
    artifacts: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("The platform has no portable FIFO creation API")
    try:
        os.mkfifo(source_root / "pipe")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"The platform cannot create a FIFO fixture: {exc}")

    with pytest.raises(KokoroError) as caught:
        _publish(tmp_path, source_root, artifacts)

    assert caught.value.code == "UNSAFE_PACK_PATH"
