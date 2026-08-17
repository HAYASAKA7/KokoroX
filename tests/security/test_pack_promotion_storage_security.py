from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing import storage
from kokoroarc.testing.storage import (
    load_published_promotion_record,
    publish_promotion_record,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
RELEASE_FIXTURE = Path("tests/fixtures/pack-release/original-minimal.json")


def _sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = json.loads(RELEASE_FIXTURE.read_text(encoding="utf-8"))
    review = deepcopy(fixture["review_attestation"])
    record = deepcopy(fixture["promotion_record"])
    record["review_attestation"] = {
        "artifact_id": review["artifact_id"],
        "sha256": _sha256(review),
    }
    return record, review


def _target(data_root: Path, record: dict[str, Any]) -> Path:
    return (
        data_root
        / "reports"
        / "promotions"
        / record["character_id"]
        / record["promotion_id"]
        / "promotion.json"
    )


def _verified_record(reviewed: dict[str, Any]) -> dict[str, Any]:
    verified = deepcopy(reviewed)
    verified.update(
        {
            "artifact_id": "original/rin-aster/release/promotion-verified",
            "promotion_id": "rin-promotion-verified-01",
            "from_status": "reviewed",
            "to_status": "verified",
            "activation_allowed": True,
            "previous_promotion": {
                "artifact_id": reviewed["artifact_id"],
                "sha256": _sha256(reviewed),
            },
            "soft_evaluation_report": {
                "artifact_id": "original/rin-aster/release/soft-evaluation",
                "sha256": "f" * 64,
            },
        }
    )
    SCHEMAS.validate("pack-promotion-record", verified)
    return verified


@pytest.mark.parametrize("promotion_id", ["con", "con.txt", "lpt1.record"])
def test_reserved_device_promotion_ids_are_rejected_before_storage_creation(
    tmp_path: Path,
    promotion_id: str,
) -> None:
    record, review = _artifacts()
    record["promotion_id"] = promotion_id
    data_root = tmp_path / "data"

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_PATH_UNSAFE"
    assert not data_root.exists()


def test_redirected_destination_component_is_rejected_without_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    marked = data_root / "reports"
    marked.mkdir(parents=True)
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def is_marked(path: Path) -> bool:
        return path == marked or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", is_marked, raising=False)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_PATH_UNSAFE"
    assert not list(data_root.rglob("*.staging-*"))


def test_global_promotion_lock_contention_fails_retryably(
    tmp_path: Path,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    promotions_root = data_root / "reports" / "promotions"
    promotions_root.mkdir(parents=True)

    with storage._acquire_publication_lock(promotions_root / "records"):
        with pytest.raises(KokoroError) as caught:
            publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_BUSY"
    assert caught.value.retryable is True
    assert caught.value.details == {"reason": "reports_locked"}
    assert not _target(data_root, record).exists()


def test_hardlinked_publication_lock_is_rejected_without_touching_its_source(
    tmp_path: Path,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    promotions_root = data_root / "reports" / "promotions"
    promotions_root.mkdir(parents=True)
    outside = tmp_path / "outside-lock"
    outside.write_bytes(b"must remain unchanged")
    os.link(outside, promotions_root / ".records.publish.lock")

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_PATH_UNSAFE"
    assert outside.read_bytes() == b"must remain unchanged"
    assert not _target(data_root, record).exists()


@pytest.mark.parametrize(
    ("window", "expected_code", "expected_operation"),
    [
        ("create_staging", "PACK_PROMOTION_PUBLISH_FAILED", "create_staging"),
        ("write_review", "PACK_PROMOTION_PUBLISH_FAILED", "write"),
        ("verify", "PACK_PROMOTION_STAGING_INVALID", None),
        ("fsync_staging", "PACK_PROMOTION_PUBLISH_FAILED", "fsync_staging"),
        ("cutover", "PACK_PROMOTION_PUBLISH_FAILED", "cutover"),
    ],
)
def test_pre_cutover_failure_windows_leave_no_record_or_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    window: str,
    expected_code: str,
    expected_operation: str | None,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    target = _target(data_root, record)

    if window == "create_staging":
        monkeypatch.setattr(
            storage,
            "_create_staging",
            lambda _target: (_ for _ in ()).throw(
                PermissionError("sensitive staging failure")
            ),
        )
    elif window == "write_review":
        real_write = storage._write_canonical_file

        def fail_review_write(path: Path, value: Any, **kwargs: Any) -> None:
            if path.name == "review-attestation.json":
                raise PermissionError("sensitive review write failure")
            real_write(path, value, **kwargs)

        monkeypatch.setattr(storage, "_write_canonical_file", fail_review_write)
    elif window == "verify":
        monkeypatch.setattr(
            storage,
            "_verify_staged_bundle",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                KokoroError(
                    "PACK_PROMOTION_STAGING_INVALID",
                    "Promotion staging failed validation.",
                    details={"reason": "injected"},
                )
            ),
        )
    elif window == "fsync_staging":
        real_fsync = storage._fsync_directory

        def fail_staging_fsync(path: Path) -> None:
            if ".staging-" in path.name:
                raise PermissionError("sensitive staging fsync failure")
            real_fsync(path)

        monkeypatch.setattr(storage, "_fsync_directory", fail_staging_fsync)
    else:
        monkeypatch.setattr(
            storage,
            "_rename_staging",
            lambda *_args: (_ for _ in ()).throw(
                PermissionError("sensitive cutover failure")
            ),
        )

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == expected_code
    if expected_operation is not None:
        assert caught.value.details == {
            "operation": expected_operation,
            "reason": "PermissionError",
        }
    assert "sensitive" not in caught.value.message
    assert not target.exists()
    parent = target.parent.parent
    assert not parent.exists() or not list(parent.glob(".*.staging-*"))


def test_staging_identity_capture_failure_is_reported_without_unsafe_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    target = _target(data_root, record)
    real_capture = storage._capture_directory_identity

    def fail_staging_identity(path: Path):
        if ".staging-" in path.name:
            raise PermissionError("identity unavailable")
        return real_capture(path)

    monkeypatch.setattr(storage, "_capture_directory_identity", fail_staging_identity)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_CLEANUP_FAILED"
    assert caught.value.details == {
        "reason": "staging_identity_unavailable",
        "record_state": "not_visible",
    }
    assert not target.exists()
    leftovers = list(target.parent.parent.glob(".*.staging-*"))
    assert len(leftovers) == 1
    assert list(leftovers[0].iterdir()) == []


def test_staging_identity_capture_race_never_deletes_unverified_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    target = _target(data_root, record)
    real_capture = storage._capture_directory_identity
    replacement: Path | None = None
    displaced: Path | None = None

    def replace_then_fail(path: Path):
        nonlocal replacement, displaced
        if ".staging-" not in path.name:
            return real_capture(path)
        displaced = path.with_name(f"{path.name}.displaced")
        path.rename(displaced)
        path.mkdir()
        replacement = path
        raise PermissionError("identity unavailable after replacement")

    monkeypatch.setattr(storage, "_capture_directory_identity", replace_then_fail)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_CLEANUP_FAILED"
    assert caught.value.details == {
        "reason": "staging_identity_unavailable",
        "record_state": "not_visible",
    }
    assert replacement is not None and replacement.is_dir()
    assert displaced is not None and displaced.is_dir()
    assert not target.exists()


def test_staged_file_identity_change_before_cutover_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    real_fsync = storage._fsync_directory
    changed = False

    def replace_record_during_fsync(path: Path) -> None:
        nonlocal changed
        if ".staging-" in path.name and not changed:
            changed = True
            record_path = path / "promotion.json"
            payload = record_path.read_bytes()
            record_path.unlink()
            record_path.write_bytes(payload)
        real_fsync(path)

    monkeypatch.setattr(storage, "_fsync_directory", replace_record_during_fsync)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_STAGING_INVALID"
    assert changed is True
    assert not _target(data_root, record).exists()


def test_parent_fsync_failure_leaves_only_a_complete_retryable_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    target = _target(data_root, record)
    real_fsync = storage._fsync_directory

    def fail_after_cutover(path: Path) -> None:
        if path == target.parent.parent and target.exists():
            raise PermissionError("sensitive parent fsync failure")
        real_fsync(path)

    monkeypatch.setattr(storage, "_fsync_directory", fail_after_cutover)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_DURABILITY_FAILED"
    assert caught.value.details == {
        "operation": "fsync_parent",
        "reason": "PermissionError",
        "record_state": "complete_visible",
    }
    assert load_published_promotion_record(target, SCHEMAS) == record
    assert not list(target.parent.parent.glob(".*.staging-*"))

    with pytest.raises(KokoroError) as retry_error:
        publish_promotion_record(data_root, record, review, SCHEMAS)
    assert retry_error.value.code == "PACK_PROMOTION_DURABILITY_FAILED"

    monkeypatch.setattr(storage, "_fsync_directory", real_fsync)
    assert publish_promotion_record(data_root, record, review, SCHEMAS) == target


def test_cleanup_refuses_to_delete_a_replacement_staging_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    replacement: Path | None = None
    displaced: Path | None = None

    def replace_staging_then_fail(staging: Path, *_args: Any, **_kwargs: Any) -> Any:
        nonlocal replacement, displaced
        displaced = staging.with_name(f"{staging.name}.generated-displaced")
        staging.rename(displaced)
        staging.mkdir()
        (staging / "unrelated-sentinel.txt").write_text(
            "must remain",
            encoding="utf-8",
        )
        replacement = staging
        raise KokoroError(
            "PACK_PROMOTION_STAGING_INVALID",
            "Promotion staging failed validation.",
            details={"reason": "injected"},
        )

    monkeypatch.setattr(storage, "_verify_staged_bundle", replace_staging_then_fail)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_CLEANUP_FAILED"
    assert replacement is not None and replacement.is_dir()
    assert (replacement / "unrelated-sentinel.txt").read_text(
        encoding="utf-8"
    ) == "must remain"
    assert displaced is not None and displaced.is_dir()


def test_persistent_cleanup_error_is_reported_with_staging_left_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    monkeypatch.setattr(
        storage,
        "_verify_staged_bundle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            KokoroError(
                "PACK_PROMOTION_STAGING_INVALID",
                "Promotion staging failed validation.",
                details={"reason": "injected"},
            )
        ),
    )
    monkeypatch.setattr(
        storage,
        "_remove_entry_no_follow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("sensitive cleanup failure")
        ),
    )

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_CLEANUP_FAILED"
    assert caught.value.details["reason"] == "PermissionError"
    character_root = _target(data_root, record).parent.parent
    assert list(character_root.glob(".*.staging-*"))


def test_staging_outside_character_root_is_rejected_before_metadata_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    outside = tmp_path / "outside" / "staging"
    outside.mkdir(parents=True)
    writes: list[Path] = []
    real_write = storage._write_canonical_file

    monkeypatch.setattr(storage, "_create_staging", lambda _final: outside)

    def record_write(path: Path, value: Any, **kwargs: Any) -> None:
        writes.append(path)
        real_write(path, value, **kwargs)

    monkeypatch.setattr(storage, "_write_canonical_file", record_write)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_PATH_UNSAFE"
    assert writes == []
    assert list(outside.iterdir()) == []


def test_character_directory_redirect_after_staging_blocks_metadata_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    real_create = storage._create_staging
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)
    redirected: set[Path] = set()
    writes: list[Path] = []

    def redirect_parent_after_create(final: Path) -> Path:
        staging = real_create(final)
        redirected.add(final.parent)
        return staging

    def is_redirected(path: Path) -> bool:
        return path in redirected or bool(real_is_junction(path))

    def record_write(path: Path, _value: Any, **_kwargs: Any) -> None:
        writes.append(path)

    monkeypatch.setattr(storage, "_create_staging", redirect_parent_after_create)
    monkeypatch.setattr(Path, "is_junction", is_redirected, raising=False)
    monkeypatch.setattr(storage, "_write_canonical_file", record_write)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_CLEANUP_FAILED"
    assert caught.value.details == {
        "reason": "staging_identity_changed",
        "record_state": "not_visible",
    }
    assert writes == []
    character_root = _target(data_root, record).parent.parent
    assert len(list(character_root.glob(".*.staging-*"))) == 1


def test_guarded_write_rechecks_character_ancestry_before_opening_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    real_write = storage._write_canonical_file
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)
    redirected: set[Path] = set()
    attempted = False

    def redirect_inside_write(path: Path, value: Any, **kwargs: Any) -> None:
        nonlocal attempted
        attempted = True
        redirected.add(path.parent.parent)
        real_write(path, value, **kwargs)

    def is_redirected(path: Path) -> bool:
        return path in redirected or bool(real_is_junction(path))

    monkeypatch.setattr(storage, "_write_canonical_file", redirect_inside_write)
    monkeypatch.setattr(Path, "is_junction", is_redirected, raising=False)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert attempted is True
    assert caught.value.code == "PACK_PROMOTION_CLEANUP_FAILED"
    character_root = _target(data_root, record).parent.parent
    staging = next(character_root.glob(".*.staging-*"))
    assert list(staging.iterdir()) == []
    assert not _target(data_root, record).exists()


def test_idempotent_retry_rechecks_character_ancestry_after_bundle_callbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    target = publish_promotion_record(data_root, record, review, SCHEMAS)
    character_root = target.parent.parent
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    class RedirectingRegistry:
        record_validations = 0
        redirected = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-promotion-record":
                self.record_validations += 1
                if self.record_validations == 3:
                    self.redirected = True

    registry = RedirectingRegistry()

    def is_redirected(path: Path) -> bool:
        return (
            path == character_root and registry.redirected
        ) or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", is_redirected, raising=False)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(
            data_root,
            record,
            review,
            registry,  # type: ignore[arg-type]
        )

    assert registry.redirected is True
    assert caught.value.code in {
        "PACK_PROMOTION_CONFLICT",
        "PACK_PROMOTION_PATH_UNSAFE",
    }


def test_staging_is_reverified_after_the_final_history_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    character_root = _target(data_root, record).parent.parent
    real_scan = storage._scan_existing_promotions
    scans = 0
    changed = False

    def change_staging_after_scan(path: Path, schemas: Any):
        nonlocal scans, changed
        result = real_scan(path, schemas)
        scans += 1
        if scans == 2:
            staging = next(character_root.glob(".*.staging-*"))
            promotion = staging / "promotion.json"
            promotion.write_bytes(promotion.read_bytes() + b" ")
            changed = True
        return result

    monkeypatch.setattr(storage, "_scan_existing_promotions", change_staging_after_scan)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert changed is True
    assert caught.value.code == "PACK_PROMOTION_STAGING_INVALID"
    assert not _target(data_root, record).exists()


def test_bounded_directory_enumeration_stops_at_limit_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "entries"
    root.mkdir()
    scandir_yielded = 0
    iterdir_materialized = 0
    real_iterdir = Path.iterdir
    real_scandir = storage.os.scandir

    class Entry:
        def __init__(self, name: str) -> None:
            self.name = name

    class LazyScandir:
        def __init__(self) -> None:
            self.index = 0

        def __enter__(self) -> LazyScandir:
            return self

        def __exit__(self, *_exception: object) -> None:
            return None

        def __iter__(self) -> LazyScandir:
            return self

        def __next__(self) -> Entry:
            nonlocal scandir_yielded
            if self.index == 10_000:
                raise StopIteration
            entry = Entry(f".record.staging-{self.index}")
            self.index += 1
            scandir_yielded += 1
            return entry

    def many_entries(path: Path):  # type: ignore[no-untyped-def]
        nonlocal iterdir_materialized
        if path != root:
            return real_iterdir(path)
        entries = [root / f".record.staging-{index}" for index in range(10_000)]
        iterdir_materialized += len(entries)
        return iter(entries)

    def lazy_scandir(path: Path):  # type: ignore[no-untyped-def]
        if Path(path) == root:
            return LazyScandir()
        return real_scandir(path)

    monkeypatch.setattr(Path, "iterdir", many_entries)
    monkeypatch.setattr(storage.os, "scandir", lazy_scandir)

    with pytest.raises(KokoroError) as caught:
        storage._bounded_entries(root, 3, "record_count")

    assert caught.value.code == "PACK_PROMOTION_STORAGE_LIMIT"
    assert scandir_yielded == 4
    assert iterdir_materialized == 0


def test_atomic_cutover_never_replaces_an_existing_empty_directory(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    final = tmp_path / "final"
    staging.mkdir()
    final.mkdir()

    with pytest.raises(FileExistsError):
        storage._atomic_rename_noreplace(staging, final)

    assert staging.is_dir()
    assert final.is_dir()


def test_final_history_scan_detects_late_character_membership_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, review = _artifacts()
    data_root = tmp_path / "data"
    publish_promotion_record(data_root, reviewed, review, SCHEMAS)
    verified = _verified_record(reviewed)
    character_root = _target(data_root, reviewed).parent.parent
    real_load = storage._load_published_bundle
    reviewed_loads = 0
    inserted = False

    def insert_after_enumeration(path: Path, schemas: Any, **kwargs: Any):
        nonlocal reviewed_loads, inserted
        bundle = real_load(path, schemas, **kwargs)
        if path.name == reviewed["promotion_id"]:
            reviewed_loads += 1
            if reviewed_loads == 2:
                inserted = True
                conflicting_review = deepcopy(review)
                conflicting_review["reviewer"]["id"] = "different-reviewer"
                conflicting_record = deepcopy(reviewed)
                conflicting_record["promotion_id"] = "rin-promotion-reviewed-02"
                conflicting_record["review_attestation"] = {
                    "artifact_id": conflicting_review["artifact_id"],
                    "sha256": _sha256(conflicting_review),
                }
                conflict_root = character_root / conflicting_record["promotion_id"]
                conflict_root.mkdir()
                (conflict_root / "promotion.json").write_bytes(
                    canonical_bytes(conflicting_record) + b"\n"
                )
                (conflict_root / "review-attestation.json").write_bytes(
                    canonical_bytes(conflicting_review) + b"\n"
                )
        return bundle

    monkeypatch.setattr(storage, "_load_published_bundle", insert_after_enumeration)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, verified, review, SCHEMAS)

    assert inserted is True
    assert caught.value.code == "PACK_PROMOTION_BUNDLE_INVALID"
    assert not _target(data_root, verified).exists()


def test_final_history_snapshot_is_rechecked_after_scan_returns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, review = _artifacts()
    data_root = tmp_path / "data"
    publish_promotion_record(data_root, reviewed, review, SCHEMAS)
    verified = _verified_record(reviewed)
    character_root = _target(data_root, reviewed).parent.parent
    real_scan = storage._scan_existing_promotions
    scans = 0
    inserted = False

    def insert_after_scan(path: Path, schemas: Any):
        nonlocal scans, inserted
        result = real_scan(path, schemas)
        scans += 1
        if scans == 2:
            inserted = True
            conflicting_review = deepcopy(review)
            conflicting_review["reviewer"]["id"] = "different-reviewer"
            conflicting_record = deepcopy(reviewed)
            conflicting_record["promotion_id"] = "rin-promotion-reviewed-02"
            conflicting_record["review_attestation"] = {
                "artifact_id": conflicting_review["artifact_id"],
                "sha256": _sha256(conflicting_review),
            }
            conflict_root = character_root / conflicting_record["promotion_id"]
            conflict_root.mkdir()
            (conflict_root / "promotion.json").write_bytes(
                canonical_bytes(conflicting_record) + b"\n"
            )
            (conflict_root / "review-attestation.json").write_bytes(
                canonical_bytes(conflicting_review) + b"\n"
            )
        return result

    monkeypatch.setattr(storage, "_scan_existing_promotions", insert_after_scan)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, verified, review, SCHEMAS)

    assert inserted is True
    assert caught.value.code == "PACK_PROMOTION_BUNDLE_INVALID"
    assert not _target(data_root, verified).exists()


def test_new_publication_uses_no_schema_callbacks_after_cutover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    original = deepcopy(record)
    data_root = tmp_path / "data"
    real_rename = storage._rename_staging
    cutover = False

    class Registry:
        def __init__(self) -> None:
            self.mutated_after_cutover = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if cutover and not self.mutated_after_cutover:
                self.mutated_after_cutover = True
                record["source_hash"] = "0" * 64

    def mark_cutover(*args: Any, **kwargs: Any) -> None:
        nonlocal cutover
        real_rename(*args, **kwargs)
        cutover = True

    registry = Registry()
    monkeypatch.setattr(storage, "_rename_staging", mark_cutover)

    result = publish_promotion_record(
        data_root,
        record,
        review,
        registry,  # type: ignore[arg-type]
    )

    assert cutover is True
    assert registry.mutated_after_cutover is False
    assert record == original
    assert result == _target(data_root, record)
    assert result.exists()


def test_schema_callback_input_mutation_fails_before_publication(
    tmp_path: Path,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"

    class MutatingRegistry:
        def __init__(self) -> None:
            self.mutated = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-promotion-record" and not self.mutated:
                self.mutated = True
                record["source_hash"] = "0" * 64

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(
            data_root,
            record,
            review,
            MutatingRegistry(),  # type: ignore[arg-type]
        )

    assert caught.value.code == "PACK_PROMOTION_INPUT_MUTATION"
    assert not data_root.exists()


def test_relative_data_root_is_bound_before_schema_callbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    entry = tmp_path / "entry"
    rebound = tmp_path / "rebound"
    entry.mkdir()
    rebound.mkdir()
    monkeypatch.chdir(entry)

    class RebindingRegistry:
        def __init__(self) -> None:
            self.rebound = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if not self.rebound:
                self.rebound = True
                monkeypatch.chdir(rebound)

    result = publish_promotion_record(
        Path("data"),
        record,
        review,
        RebindingRegistry(),  # type: ignore[arg-type]
    )

    assert result == _target(entry / "data", record)
    assert result.exists()
    assert not (rebound / "data").exists()


def test_caller_input_aba_mutation_across_storage_callbacks_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    original = deepcopy(record)
    data_root = tmp_path / "data"
    real_create = storage._create_staging
    real_write = storage._write_canonical_file
    restored = False

    def mutate_after_staging(final: Path) -> Path:
        staging = real_create(final)
        record["source_hash"] = "0" * 64
        return staging

    def restore_before_write(path: Path, value: Any, **kwargs: Any) -> None:
        nonlocal restored
        if not restored:
            restored = True
            record.clear()
            record.update(deepcopy(original))
        real_write(path, value, **kwargs)

    monkeypatch.setattr(storage, "_create_staging", mutate_after_staging)
    monkeypatch.setattr(storage, "_write_canonical_file", restore_before_write)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_INPUT_MUTATION"
    assert restored is False
    assert not _target(data_root, record).exists()
    character_root = _target(data_root, record).parent.parent
    assert not list(character_root.glob(".*.staging-*"))


def test_review_id_conflict_inserted_during_staging_is_rechecked_before_cutover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    data_root = tmp_path / "data"
    target = _target(data_root, record)
    real_fsync = storage._fsync_directory
    inserted = False

    def insert_conflict(path: Path) -> None:
        nonlocal inserted
        if ".staging-" in path.name and not inserted:
            inserted = True
            conflicting_review = deepcopy(review)
            conflicting_review["reviewer"]["id"] = "different-reviewer"
            conflicting_record = deepcopy(record)
            conflicting_record["promotion_id"] = "rin-promotion-reviewed-02"
            conflicting_record["review_attestation"] = {
                "artifact_id": conflicting_review["artifact_id"],
                "sha256": _sha256(conflicting_review),
            }
            conflict_root = target.parent.parent / conflicting_record["promotion_id"]
            conflict_root.mkdir()
            (conflict_root / "promotion.json").write_bytes(
                canonical_bytes(conflicting_record) + b"\n"
            )
            (conflict_root / "review-attestation.json").write_bytes(
                canonical_bytes(conflicting_review) + b"\n"
            )
        real_fsync(path)

    monkeypatch.setattr(storage, "_fsync_directory", insert_conflict)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_REVIEW_ID_CONFLICT"
    assert inserted is True
    assert not target.exists()
    assert not list(target.parent.parent.glob(".*.staging-*"))


def test_loader_rejects_hardlinked_or_redirected_bundle_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, review = _artifacts()
    first = publish_promotion_record(tmp_path / "hardlink", record, review, SCHEMAS)
    outside = tmp_path / "outside-record"
    os.link(first, outside)

    with pytest.raises(KokoroError) as hardlink_error:
        load_published_promotion_record(first, SCHEMAS)

    assert hardlink_error.value.code == "PACK_PROMOTION_BUNDLE_INVALID"
    assert outside.read_bytes() == first.read_bytes()

    second = publish_promotion_record(tmp_path / "redirect", record, review, SCHEMAS)
    marked = second.parent / "review-attestation.json"
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def is_marked(path: Path) -> bool:
        return path == marked or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", is_marked, raising=False)

    with pytest.raises(KokoroError) as redirect_error:
        load_published_promotion_record(second, SCHEMAS)

    assert redirect_error.value.code == "PACK_PROMOTION_BUNDLE_INVALID"
