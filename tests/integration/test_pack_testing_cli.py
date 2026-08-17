from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import yaml

from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RIN_PACK = REPOSITORY_ROOT / "characters" / "original" / "rin-aster"
SCHEMAS = SchemaRegistry(REPOSITORY_ROOT / "schemas" / "v1")


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")
    return path


def _run_cli(
    data_dir: Path,
    *arguments: str,
    expected_returncode: int = 0,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    env = os.environ.copy()
    env["KOKOROARC_DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments, "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=REPOSITORY_ROOT,
        timeout=90,
    )
    assert completed.returncode == expected_returncode, completed.stderr
    assert completed.stderr == ""
    assert len(completed.stdout.splitlines()) == 1
    return json.loads(completed.stdout), completed


def _copy_researched_pack(tmp_path: Path) -> Path:
    pack = tmp_path / "researched-pack"
    shutil.copytree(RIN_PACK, pack)
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
    (pack / "evidence.yaml").write_text(
        yaml.safe_dump(
            {
                "authored_original": False,
                "claims": [
                    {"claim_id": "claim-role", "source": "research_bundle"}
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (pack / "overrides.yaml").write_text(
        yaml.safe_dump({"values": {}}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return pack


def test_pack_testing_cli_exact_release_handoff(
    tmp_path: Path,
    rin_verified_release: dict[str, Any],
) -> None:
    data_dir = tmp_path / "data"
    inputs = tmp_path / "inputs"
    evidence = rin_verified_release["evidence"]
    request = _write_json(inputs / "request.json", evidence["request"])
    hard = _write_json(inputs / "hard.json", evidence["hard_report"])
    review = _write_json(inputs / "review.json", evidence["review_attestation"])
    soft_input = _write_json(
        inputs / "soft-input.json", evidence["soft_evaluation_input"]
    )
    soft = _write_json(
        inputs / "soft.json", evidence["soft_evaluation_report"]
    )

    hard_arguments = (
        "pack",
        "test",
        str(RIN_PACK),
        "--request",
        str(request),
        "--out",
        "hard-report.json",
    )
    hard_result, first_hard = _run_cli(data_dir, *hard_arguments)
    repeated_hard, second_hard = _run_cli(data_dir, *hard_arguments)
    hard_path = data_dir / "reports" / "hard-report.json"
    assert hard_result == {
        "ok": True,
        "artifact_id": evidence["hard_report"]["artifact_id"],
        "compiled_hash": evidence["hard_report"]["compiled_hash"],
        "passed": True,
        "path": str(hard_path.resolve()),
        "report_hash": sha256(canonical_bytes(evidence["hard_report"])).hexdigest(),
        "source_hash": evidence["hard_report"]["source_hash"],
    }
    assert repeated_hard == hard_result
    assert second_hard.stdout == first_hard.stdout
    assert hard_path.read_bytes() == canonical_bytes(evidence["hard_report"]) + b"\n"
    SCHEMAS.validate("pack-hard-validation-report", json.loads(hard_path.read_bytes()))

    soft_result, _ = _run_cli(
        data_dir,
        "pack",
        "soft-eval",
        str(soft_input),
        "--out",
        str((data_dir / "reports" / "soft-report.json").resolve()),
    )
    soft_path = data_dir / "reports" / "soft-report.json"
    assert soft_result["passed"] is True
    assert soft_result["path"] == str(soft_path.resolve())
    assert soft_path.read_bytes() == (
        canonical_bytes(evidence["soft_evaluation_report"]) + b"\n"
    )

    reviewed_id = "rin-promotion-reviewed-cli-01"
    reviewed_relative = (
        f"promotions/rin-aster/{reviewed_id}/promotion.json"
    )
    reviewed_result, _ = _run_cli(
        data_dir,
        "pack",
        "promote",
        str(RIN_PACK),
        "--target",
        "reviewed",
        "--promotion-id",
        reviewed_id,
        "--request",
        str(request),
        "--hard-report",
        str(hard),
        "--review",
        str(review),
        "--out",
        reviewed_relative,
    )
    reviewed_path = data_dir / "reports" / reviewed_relative
    reviewed = json.loads(reviewed_path.read_bytes())
    assert reviewed_result["to_status"] == "reviewed"
    assert reviewed_result["path"] == str(reviewed_path.resolve())
    assert reviewed["promotion_id"] == reviewed_id

    verified_id = "rin-promotion-verified-cli-01"
    verified_relative = (
        f"promotions/rin-aster/{verified_id}/promotion.json"
    )
    verified_result, _ = _run_cli(
        data_dir,
        "pack",
        "promote",
        str(RIN_PACK),
        "--target",
        "verified",
        "--promotion-id",
        verified_id,
        "--request",
        str(request),
        "--hard-report",
        str(hard),
        "--review",
        str(review),
        "--previous",
        str(reviewed_path),
        "--soft-input",
        str(soft_input),
        "--soft-report",
        str(soft),
        "--out",
        verified_relative,
    )
    verified_path = data_dir / "reports" / verified_relative
    verified = json.loads(verified_path.read_bytes())
    assert verified_result["activation_allowed"] is True
    assert verified_result["path"] == str(verified_path.resolve())
    assert verified["previous_promotion"]["artifact_id"] == reviewed["artifact_id"]

    publication_result, _ = _run_cli(
        data_dir,
        "pack",
        "publication-check",
        str(RIN_PACK),
        "--promotion",
        str(verified_path),
        "--request",
        str(request),
        "--hard-report",
        str(hard),
        "--review",
        str(review),
        "--previous",
        str(reviewed_path),
        "--soft-input",
        str(soft_input),
        "--soft-report",
        str(soft),
        "--visibility",
        "private",
        "--out",
        "publication-readiness.json",
    )
    publication_path = data_dir / "reports" / "publication-readiness.json"
    publication = json.loads(publication_path.read_bytes())
    assert publication_result["ready_for_private_export"] is True
    assert publication_result["ready_for_publication"] is False
    assert publication_result["path"] == str(publication_path.resolve())
    assert publication["promotion"]["artifact_id"] == verified["artifact_id"]
    assert publication["blockers"] == []


def test_pack_soft_eval_failure_is_sanitized_and_leaves_no_output(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    secret = "PRIVATE-CLI-SOFT-SECRET"
    invalid = _write_json(tmp_path / f"{secret}.json", {"secret": secret})

    body, completed = _run_cli(
        data_dir,
        "pack",
        "soft-eval",
        str(invalid),
        "--out",
        "soft-report.json",
        expected_returncode=2,
    )

    assert body["ok"] is False
    assert body["error"]["code"] == "SOFT_EVALUATION_INPUT_INVALID"
    assert body["error"]["details"] == {}
    assert secret not in completed.stdout
    assert not (data_dir / "reports" / "soft-report.json").exists()


def test_pack_test_accepts_exact_trusted_research_bundle_directory(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    bundle_result, _ = _run_cli(
        data_dir,
        "research",
        "bundle",
        "compile",
        "--workspace",
        str(REPOSITORY_ROOT / "tests" / "fixtures" / "research" / "complete"),
    )
    pack = _copy_researched_pack(tmp_path)
    request = REPOSITORY_ROOT / "tests" / "fixtures" / "authoring"
    request /= "researched-request.json"

    result, _ = _run_cli(
        data_dir,
        "pack",
        "test",
        str(pack),
        "--request",
        str(request),
        "--research-bundle",
        bundle_result["path"],
        "--out",
        "researched-hard-report.json",
    )

    report = json.loads(
        (data_dir / "reports" / "researched-hard-report.json").read_bytes()
    )
    assert result["passed"] is True
    assert report["mode"] == "researched"
    assert report["checks"]["provenance"]["passed"] is True


def test_pack_promote_rejects_noncanonical_output_before_publication(
    tmp_path: Path,
    rin_verified_release: dict[str, Any],
) -> None:
    data_dir = tmp_path / "data"
    evidence = rin_verified_release["evidence"]
    request = _write_json(tmp_path / "request.json", evidence["request"])
    hard = _write_json(tmp_path / "hard.json", evidence["hard_report"])
    review = _write_json(tmp_path / "review.json", evidence["review_attestation"])

    body, completed = _run_cli(
        data_dir,
        "pack",
        "promote",
        str(RIN_PACK),
        "--target",
        "reviewed",
        "--promotion-id",
        "rin-promotion-reviewed-wrong-output",
        "--request",
        str(request),
        "--hard-report",
        str(hard),
        "--review",
        str(review),
        "--out",
        "wrong.json",
        expected_returncode=2,
    )

    assert body["error"]["code"] == "REPORT_OUTPUT_MISMATCH"
    assert completed.stderr == ""
    promotions = data_dir / "reports" / "promotions"
    assert not promotions.exists()
