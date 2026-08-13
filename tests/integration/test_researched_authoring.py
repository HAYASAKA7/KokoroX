from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest
import yaml

from kokoroarc import cli as cli_module
from kokoroarc.authoring import storage as authoring_storage
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.research.bundles import canonical_hash


REPOSITORY_ROOT = Path.cwd().resolve()
AUTHORING_FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures" / "authoring"
RESEARCH_FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures" / "research"


def _cli(
    arguments: list[str], *, data_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
    if data_dir is None:
        env.pop("KOKOROARC_DATA_DIR", None)
    else:
        env["KOKOROARC_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _publish_research_bundle(
    data_dir: Path, tree: str = "complete"
) -> tuple[Path, dict[str, Any]]:
    completed = _cli(
        [
            "research",
            "bundle",
            "compile",
            "--workspace",
            str(RESEARCH_FIXTURES / tree),
            "--json",
        ],
        data_dir=data_dir,
    )
    assert completed.returncode == 0, completed.stdout
    body = json.loads(completed.stdout)
    return Path(body["path"]), body


def _copy_research_pack(tmp_path: Path, mode: str) -> Path:
    pack = tmp_path / f"{mode}-pack"
    shutil.copytree(REPOSITORY_ROOT / "characters" / "original" / "rin-aster", pack)

    manifest_path = pack / "character.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "artifact_id": "research/aoi-kisaragi-fixture/source",
            "character_id": "aoi-kisaragi-fixture",
            "namespace": "research",
        }
    )
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    identity_path = pack / "identity.yaml"
    identity = yaml.safe_load(identity_path.read_text(encoding="utf-8"))
    identity.update(
        {
            "display_name": "Aoi Kisaragi Fixture",
            "role": "observatory apprentice",
        }
    )
    identity_path.write_text(
        yaml.safe_dump(identity, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    claims: list[dict[str, Any]] = [
        {"claim_id": "claim-role", "source": "research_bundle"}
    ]
    overrides: dict[str, Any] = {"values": {}}
    if mode == "hybrid":
        claims.append(
            {
                "statement": (
                    "Prefer a quieter delivery without changing researched facts."
                ),
                "source": "user_override",
            }
        )
        overrides = {"values": {"directness": 0.65}}
    (pack / "evidence.yaml").write_text(
        yaml.safe_dump(
            {"authored_original": False, "claims": claims},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (pack / "overrides.yaml").write_text(
        yaml.safe_dump(overrides, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return pack


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _assert_error(
    completed: subprocess.CompletedProcess[str], code: str, message: str
) -> None:
    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "error": {
            "code": code,
            "details": {},
            "message": message,
            "retryable": False,
        },
        "ok": False,
    }
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "mode,fixture_name,expected_evidence,expected_overrides",
    [
        ("researched", "researched-request.json", 1, 0),
        ("hybrid", "hybrid-request.json", 2, 1),
    ],
)
def test_research_backed_draft_is_deterministic_private_and_inactive(
    mode: str,
    fixture_name: str,
    expected_evidence: int,
    expected_overrides: int,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    bundle_path, _bundle = _publish_research_bundle(data_dir)
    research_before = _tree_snapshot(bundle_path)
    pack = _copy_research_pack(tmp_path, mode)
    request_path = AUTHORING_FIXTURES / fixture_name
    arguments = [
        "character",
        "draft",
        "compile",
        "--request",
        str(request_path),
        "--pack",
        str(pack),
        "--research-bundle",
        str(bundle_path),
        "--json",
    ]

    first = _cli(arguments, data_dir=data_dir)
    second = _cli(arguments, data_dir=data_dir)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    body = json.loads(first.stdout)
    assert body["build_status"] == "draft"
    assert body["visibility"] == "private"
    assert body["activation_allowed"] is False
    assert body["validation_report"]["valid"] is True
    assert body["validation_report"]["locale_coverage"] == {
        "en-US": True,
        "ja-JP": True,
        "zh-CN": True,
    }
    assert body["validation_report"]["provenance_counts"] == {
        "derived_profile": 5,
        "evidence": expected_evidence,
        "user_override": expected_overrides,
    }
    draft_path = Path(body["path"])
    stored_evidence = yaml.safe_load(
        (draft_path / "source-pack" / "evidence.yaml").read_text(
            encoding="utf-8"
        )
    )
    research_claim = stored_evidence["claims"][0]
    assert research_claim == {
        "claim_id": "claim-role",
        "source": "research_bundle",
    }
    if mode == "hybrid":
        assert stored_evidence["claims"][1]["source"] == "user_override"
    assert _tree_snapshot(bundle_path) == research_before
    assert first.stderr == second.stderr == ""


def test_research_backed_validation_is_stateless(tmp_path: Path) -> None:
    data_dir = tmp_path / "research-data"
    bundle_path, _bundle = _publish_research_bundle(data_dir)
    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(AUTHORING_FIXTURES / "researched-request.json"),
            "--pack",
            str(_copy_research_pack(tmp_path, "researched")),
            "--research-bundle",
            str(bundle_path),
            "--json",
        ]
    )

    assert completed.returncode == 0
    body = json.loads(completed.stdout)
    assert body["valid"] is True
    assert body["validation_report"]["hard_failures"] == []
    assert completed.stderr == ""


def test_research_mode_requires_trusted_bundle_argument(tmp_path: Path) -> None:
    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(AUTHORING_FIXTURES / "researched-request.json"),
            "--pack",
            str(_copy_research_pack(tmp_path, "researched")),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "RESEARCH_BUNDLE_REQUIRED",
        "An eligible Research Bundle is required for this authoring mode.",
    )


def test_original_mode_rejects_unexpected_bundle_argument(tmp_path: Path) -> None:
    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(AUTHORING_FIXTURES / "original-request.json"),
            "--pack",
            str(REPOSITORY_ROOT / "characters" / "original" / "rin-aster"),
            "--research-bundle",
            str(tmp_path / "private-bundle"),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "RESEARCH_BUNDLE_UNEXPECTED",
        "This authoring mode does not accept a Research Bundle.",
    )


def test_wrong_bundle_hash_returns_stable_invalid_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "research-data"
    bundle_path, _bundle = _publish_research_bundle(data_dir)
    request = _load_json(AUTHORING_FIXTURES / "researched-request.json")
    request["inputs"][0]["sha256"] = "0" * 64
    request_path = _write_json(tmp_path / "wrong-hash-request.json", request)

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(request_path),
            "--pack",
            str(_copy_research_pack(tmp_path, "researched")),
            "--research-bundle",
            str(bundle_path),
            "--json",
        ]
    )

    assert completed.returncode == 0
    body = json.loads(completed.stdout)
    assert body["valid"] is False
    assert "RESEARCH_BUNDLE_HASH_MISMATCH" in {
        finding["code"]
        for finding in body["validation_report"]["hard_failures"]
    }
    assert completed.stderr == ""


def test_partial_bundle_is_ineligible_for_authoring(tmp_path: Path) -> None:
    data_dir = tmp_path / "research-data"
    bundle_path, bundle = _publish_research_bundle(data_dir, "partial")
    request = _load_json(AUTHORING_FIXTURES / "researched-request.json")
    request["inputs"][0].update(
        {"artifact_id": bundle["artifact_id"], "sha256": bundle["bundle_hash"]}
    )
    request_path = _write_json(tmp_path / "partial-request.json", request)

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(request_path),
            "--pack",
            str(_copy_research_pack(tmp_path, "researched")),
            "--research-bundle",
            str(bundle_path),
            "--json",
        ]
    )

    assert completed.returncode == 0
    body = json.loads(completed.stdout)
    assert body["valid"] is False
    assert "RESEARCH_BUNDLE_INELIGIBLE" in {
        finding["code"]
        for finding in body["validation_report"]["hard_failures"]
    }
    assert completed.stderr == ""

    refused = _cli(
        [
            "character",
            "draft",
            "compile",
            "--request",
            str(request_path),
            "--pack",
            str(tmp_path / "researched-pack"),
            "--research-bundle",
            str(bundle_path),
            "--json",
        ],
        data_dir=data_dir,
    )
    _assert_error(
        refused,
        "AUTHORING_VALIDATION_FAILED",
        "Character authoring validation failed.",
    )
    assert not (data_dir / "drafts").exists()


@pytest.mark.parametrize(
    "field,value,expected_code",
    [
        ("character_id", "swapped-character", "RESEARCH_BUNDLE_IDENTITY_MISMATCH"),
        ("continuity", "different-continuity", "RESEARCH_BUNDLE_CONTINUITY_MISMATCH"),
        ("timeline", "episode-02", "RESEARCH_BUNDLE_TIMELINE_MISMATCH"),
        ("spoiler_scope", "episode-02 only", "RESEARCH_BUNDLE_SPOILER_MISMATCH"),
    ],
)
def test_research_bundle_scope_mismatch_returns_stable_invalid_report(
    field: str,
    value: str,
    expected_code: str,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "research-data"
    bundle_path, _bundle = _publish_research_bundle(data_dir)
    request = _load_json(AUTHORING_FIXTURES / "researched-request.json")
    request[field] = value
    request_path = _write_json(tmp_path / "mismatched-request.json", request)

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(request_path),
            "--pack",
            str(_copy_research_pack(tmp_path, "researched")),
            "--research-bundle",
            str(bundle_path),
            "--json",
        ]
    )

    assert completed.returncode == 0
    body = json.loads(completed.stdout)
    assert body["valid"] is False
    assert expected_code in {
        finding["code"]
        for finding in body["validation_report"]["hard_failures"]
    }
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "field,value",
    [("visibility", "public"), ("activation_allowed", True)],
)
def test_mutated_public_or_active_bundle_is_rejected(
    field: str,
    value: object,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "research-data"
    bundle_path, _bundle = _publish_research_bundle(data_dir)
    mutated = tmp_path / "mutated-bundle"
    shutil.copytree(bundle_path, mutated)
    bundle = _load_json(mutated / "bundle.json")
    bundle[field] = value
    unhashed = dict(bundle)
    unhashed.pop("bundle_hash")
    bundle["bundle_hash"] = canonical_hash(unhashed)
    (mutated / "bundle.json").write_bytes(canonical_bytes(bundle) + b"\n")

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(AUTHORING_FIXTURES / "researched-request.json"),
            "--pack",
            str(_copy_research_pack(tmp_path, "researched")),
            "--research-bundle",
            str(mutated),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "RESEARCH_BUNDLE_INVALID",
        "Published Research Bundle validation failed.",
    )


def test_coherently_rehashed_unresolved_conflict_is_still_ineligible(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "research-data"
    bundle_path, _bundle = _publish_research_bundle(data_dir)
    mutated = tmp_path / "unresolved-bundle"
    shutil.copytree(bundle_path, mutated)
    bundle = _load_json(mutated / "bundle.json")
    workspace = _load_json(mutated / "workspace.json")
    for conflict in (bundle["conflicts"][0], workspace["conflicts"][0]):
        conflict["status"] = "unresolved"
        conflict["selected_claim_ids"] = []
        conflict.pop("resolution_rationale")
    (mutated / "workspace.json").write_bytes(canonical_bytes(workspace) + b"\n")
    bundle["workspace_hash"] = canonical_hash(workspace)
    unhashed = dict(bundle)
    unhashed.pop("bundle_hash")
    bundle["bundle_hash"] = canonical_hash(unhashed)
    (mutated / "bundle.json").write_bytes(canonical_bytes(bundle) + b"\n")
    request = _load_json(AUTHORING_FIXTURES / "researched-request.json")
    request["inputs"][0]["sha256"] = bundle["bundle_hash"]
    request_path = _write_json(tmp_path / "unresolved-request.json", request)

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(request_path),
            "--pack",
            str(_copy_research_pack(tmp_path, "researched")),
            "--research-bundle",
            str(mutated),
            "--json",
        ]
    )

    assert completed.returncode == 0
    body = json.loads(completed.stdout)
    assert body["valid"] is False
    assert "RESEARCH_BUNDLE_CONFLICT_UNRESOLVED" in {
        finding["code"]
        for finding in body["validation_report"]["hard_failures"]
    }


def test_research_bundle_directory_symlink_is_rejected_when_supported(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "research-data"
    bundle_path, _bundle = _publish_research_bundle(data_dir)
    alias = tmp_path / "bundle-alias"
    try:
        alias.symlink_to(bundle_path, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"The current account cannot create directory symlinks: {error}")

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(AUTHORING_FIXTURES / "researched-request.json"),
            "--pack",
            str(_copy_research_pack(tmp_path, "researched")),
            "--research-bundle",
            str(alias),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "RESEARCH_BUNDLE_INVALID",
        "Published Research Bundle validation failed.",
    )


def test_research_bundle_hardlink_is_rejected_when_supported(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "research-data"
    bundle_path, _bundle = _publish_research_bundle(data_dir)
    linked = tmp_path / "linked-bundle"
    shutil.copytree(bundle_path, linked)
    linked_bundle = linked / "bundle.json"
    linked_bundle.unlink()
    try:
        os.link(bundle_path / "bundle.json", linked_bundle)
    except OSError as error:
        pytest.skip(f"The current account cannot create hardlinks: {error}")

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(AUTHORING_FIXTURES / "researched-request.json"),
            "--pack",
            str(_copy_research_pack(tmp_path, "researched")),
            "--research-bundle",
            str(linked),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "RESEARCH_BUNDLE_INVALID",
        "Published Research Bundle validation failed.",
    )


def test_research_bundle_junction_marker_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "research-data"
    bundle_path, _bundle = _publish_research_bundle(data_dir)
    pack = _copy_research_pack(tmp_path, "researched")
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def mark_bundle_as_junction(path: Path) -> bool:
        return path == bundle_path or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", mark_bundle_as_junction, raising=False)

    returncode = cli_module.main(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(AUTHORING_FIXTURES / "researched-request.json"),
            "--pack",
            str(pack),
            "--research-bundle",
            str(bundle_path),
            "--json",
        ]
    )

    output = capsys.readouterr()
    assert returncode == 2
    assert json.loads(output.out)["error"]["code"] == "RESEARCH_BUNDLE_INVALID"
    assert output.err == ""


def test_researched_draft_compile_rejects_source_change_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "data"
    bundle_path, _bundle = _publish_research_bundle(data_dir)
    pack = _copy_research_pack(tmp_path, "researched")
    real_load = authoring_storage.load_source_pack
    changed = False

    def mutate_after_load(path: Path, schemas: Any) -> dict[str, Any]:
        nonlocal changed
        source = real_load(path, schemas)
        if not changed:
            changed = True
            behavior = pack / "behavior.yaml"
            behavior.write_text(
                behavior.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
        return source

    monkeypatch.setattr(authoring_storage, "load_source_pack", mutate_after_load)
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(data_dir))

    returncode = cli_module.main(
        [
            "character",
            "draft",
            "compile",
            "--request",
            str(AUTHORING_FIXTURES / "researched-request.json"),
            "--pack",
            str(pack),
            "--research-bundle",
            str(bundle_path),
            "--json",
        ]
    )

    output = capsys.readouterr()
    assert returncode == 2
    assert json.loads(output.out)["error"]["code"] == "AUTHORING_SOURCE_CHANGED"
    assert not (data_dir / "drafts").exists()
    assert output.err == ""
