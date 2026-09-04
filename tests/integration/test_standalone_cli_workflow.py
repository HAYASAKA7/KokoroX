from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from kokoroarc.packs.compiler import canonical_bytes

from karc_test_support import archive_documents, build_private_archive
from kokoroarc import __version__


REPOSITORY_ROOT = Path.cwd().resolve()


def _isolated_environment(root: Path, installed: Path | None = None) -> dict[str, str]:
    temporary = root / "temporary"
    pip_cache = root / "pip-cache"
    temporary.mkdir(parents=True, exist_ok=True)
    pip_cache.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["TMP"] = str(temporary)
    environment["TEMP"] = str(temporary)
    environment["PIP_CACHE_DIR"] = str(pip_cache)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if installed is not None:
        environment["PYTHONPATH"] = str(installed)
    return environment


def _build_and_install(root: Path) -> tuple[Path, Path, Path]:
    dist = root / "dist"
    environment = _isolated_environment(root)
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--outdir",
            str(dist),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
        env=environment,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    wheel = next(dist.glob("*.whl"))
    sdist = next(dist.glob("*.tar.gz"))
    installed = root / "installed"
    installed_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-compile",
            "--no-deps",
            "--target",
            str(installed),
            str(wheel),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=root,
        env=environment,
    )
    assert installed_result.returncode == 0, (
        installed_result.stdout + installed_result.stderr
    )
    return wheel, sdist, installed


def _installed_cli(
    installed: Path,
    working: Path,
    temporary_root: Path,
    arguments: list[str],
    *,
    data_root: Path | None = None,
) -> dict[str, Any]:
    environment = _isolated_environment(temporary_root, installed)
    if data_root is None:
        environment.pop("KOKOROX_DATA_DIR", None)
    else:
        environment["KOKOROX_DATA_DIR"] = str(data_root)
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments],
        check=False,
        capture_output=True,
        text=True,
        cwd=working,
        env=environment,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stderr == ""
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    body = json.loads(lines[0])
    assert body["ok"] is True
    return body


def _installed_probe(
    installed: Path,
    working: Path,
    temporary_root: Path,
    data_root: Path,
) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys\n"
                "from pathlib import Path\n"
                "import kokoroarc\n"
                "from kokoroarc.config import resolve_schema_dir\n"
                "from kokoroarc.persistence import (\n"
                "    apply_persistent_relationship_event,\n"
                "    load_consent,\n"
                "    replay_persistent_state,\n"
                ")\n"
                "from kokoroarc.schemas import SchemaRegistry\n"
                "installed = Path(sys.argv[1]).resolve(strict=True)\n"
                "module = Path(kokoroarc.__file__).resolve(strict=True)\n"
                "assert module.is_relative_to(installed)\n"
                "data_root = Path(sys.argv[2])\n"
                "schemas = SchemaRegistry(resolve_schema_dir())\n"
                "consent = load_consent(data_root, 'rin-aster', schemas)\n"
                "assert consent is not None\n"
                "event = {\n"
                "    'schema_version': '1.0',\n"
                "    'artifact_id': 'event/installed-workflow-01',\n"
                "    'created_by': {\n"
                "        'component': 'kokoroarc',\n"
                "        'version': kokoroarc.__version__,\n"
                "    },\n"
                "    'event_id': 'installed-workflow-01',\n"
                "    'turn_id': 'turn-1',\n"
                "    'origin': 'verified_task_outcome',\n"
                "    'novelty_key': 'novelty-installed-workflow-01',\n"
                "    'expected_state_revision': 0,\n"
                "    'evaluator_version': 'interaction-v1',\n"
                "    'evidence': {\n"
                "        'kind': 'test_result',\n"
                "        'reference': 'installed workflow',\n"
                "    },\n"
                "    'confidence': 1.0,\n"
                "    'effects': {'trust': 2.0},\n"
                "}\n"
                "state = apply_persistent_relationship_event(\n"
                "    data_root, 'rin-aster', event,\n"
                "    consent['consent_id'], consent['grant_revision'],\n"
                "    schemas, expected_state_revision=0,\n"
                "    operation_id='installed-workflow-operation-01',\n"
                ")\n"
                "replayed = replay_persistent_state(\n"
                "    data_root, 'rin-aster', schemas,\n"
                ")\n"
                "print(json.dumps(\n"
                "    {'state': state, 'replayed': replayed},\n"
                "    sort_keys=True, separators=(',', ':'),\n"
                "))\n"
            ),
            str(installed),
            str(data_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=working,
        env=_isolated_environment(temporary_root, installed),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stderr == ""
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def _prepare_release_inputs(
    root: Path,
    release: dict[str, Any],
) -> tuple[bytes, dict[str, Path], Path]:
    expected_archive = build_private_archive(release)
    documents = archive_documents(expected_archive)
    inputs = root / "release-inputs"
    promotion_root = inputs / "promotion"
    promotion_root.mkdir(parents=True)
    paths = {
        "compiled": inputs / "compiled.json",
        "promotion": promotion_root / "promotion.json",
        "hard": inputs / "hard.json",
        "soft": inputs / "soft.json",
        "review": promotion_root / "review-attestation.json",
    }
    members = {
        "compiled": "pack/compiled.json",
        "promotion": "release/promotion-record.json",
        "hard": "release/hard-validation-report.json",
        "soft": "release/soft-evaluation-report.json",
        "review": "release/review-attestation.json",
    }
    for name, member in members.items():
        paths[name].write_bytes(canonical_bytes(documents[member]))
    summary = root / "memory-summary.json"
    summary.write_bytes(
        canonical_bytes(
            {
                "summary": "The user approved concise technical explanations.",
                "localized_summaries": {
                    "en-US": (
                        "The user approved concise technical explanations."
                    ),
                    "ja-JP": "簡潔な技術説明をユーザーが承認しました。",
                    "zh-CN": "用户批准了简洁的技术说明。",
                },
            }
        )
    )
    return expected_archive, paths, summary


def test_clean_installed_artifact_standalone_workflow(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    expected_archive, release_paths, summary = _prepare_release_inputs(
        tmp_path,
        rin_verified_release,
    )
    wheel, sdist, installed = _build_and_install(tmp_path)
    assert wheel.is_file()
    assert sdist.is_file()
    working = tmp_path / "outside-checkout"
    working.mkdir()
    # This path is intentionally a sibling of the installation prefix. Installed
    # package discovery must never mistake the target for a checkout source.
    skills_root = tmp_path / "skills"
    data_root = tmp_path / "data"
    archive = tmp_path / "rin-aster.karc"

    suite = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "suite",
            "install",
            "--scope",
            "user",
            "--skills-root",
            str(skills_root),
            "--json",
        ],
    )
    assert suite["skill_suite"]["skills_root"] == str(skills_root)
    assert [
        item["action"] for item in suite["skill_suite"]["skills"]
    ] == ["install", "install", "install", "install"]
    assert all(
        Path(item["target"]).is_relative_to(skills_root)
        for item in suite["skill_suite"]["skills"]
    )

    exported = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "pack",
            "export",
            "--compiled",
            str(release_paths["compiled"]),
            "--promotion",
            str(release_paths["promotion"]),
            "--hard-report",
            str(release_paths["hard"]),
            "--soft-report",
            str(release_paths["soft"]),
            "--out",
            str(archive),
            "--json",
        ],
    )
    assert exported["path"] == str(archive)
    assert exported["archive_sha256"] == sha256(expected_archive).hexdigest()
    assert archive.read_bytes() == expected_archive
    compatibility = _installed_cli(
        installed,
        working,
        tmp_path,
        ["pack", "compatibility", str(archive), "--json"],
    )
    assert compatibility["compatibility"]["compatible"] is True
    assert compatibility["compatibility"]["installation_allowed"] is True

    installation = _installed_cli(
        installed,
        working,
        tmp_path,
        ["pack", "install", str(archive), "--json"],
        data_root=data_root,
    )
    assert installation["activates_character"] is False
    assert installation["plan"]["scope"] == "global"
    assert installation["plan"]["relative_path"] == (
        "global/rin-aster/1.0.0"
    )
    installed_pack = (
        data_root
        / "installed"
        / Path(installation["plan"]["relative_path"])
    )
    assert installed_pack.is_dir()
    listed = _installed_cli(
        installed,
        working,
        tmp_path,
        ["pack", "list", "--json"],
        data_root=data_root,
    )
    assert listed["activates_character"] is False
    assert len(listed["installed"]) == 1

    selected = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "config",
            "default",
            "set",
            "--character",
            "rin-aster",
            "--json",
        ],
        data_root=data_root,
    )
    assert selected["activates_character"] is False
    assert not (data_root / "sessions").exists()
    no_session = _installed_cli(
        installed,
        working,
        tmp_path,
        ["session", "show", "--json"],
        data_root=data_root,
    )
    assert no_session["session"] is None
    started = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "session",
            "start",
            "--session",
            "installed-workflow",
            "--json",
        ],
        data_root=data_root,
    )
    assert started["session"]["active"] is True
    assert started["session"]["character_id"] == "rin-aster"

    consent = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "consent",
            "grant",
            "--character",
            "rin-aster",
            "--scope",
            "global",
            "--permissions",
            "relationship_state,mood_state,memory_references",
            "--json",
        ],
        data_root=data_root,
    )
    assert consent["consent"]["status"] == "active"
    probe = _installed_probe(
        installed,
        working,
        tmp_path,
        data_root,
    )
    assert probe["state"] == probe["replayed"]
    assert probe["state"]["revision"] == 1

    state_output = tmp_path / "persistent-state.json"
    state_export = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "state",
            "export",
            "--character",
            "rin-aster",
            "--out",
            str(state_output),
            "--json",
        ],
        data_root=data_root,
    )
    state_document = json.loads(state_output.read_bytes())
    assert state_output.read_bytes() == canonical_bytes(state_document)
    assert state_export["export_sha256"] == state_document["export_sha256"]
    assert state_document["state"]["revision"] == 1

    memory = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "memory",
            "add",
            "--character",
            "rin-aster",
            "--host-id",
            "host-memory-installed-01",
            "--summary-file",
            str(summary),
            "--json",
        ],
        data_root=data_root,
    )
    memory_id = memory["memory_reference"]["memory_reference_id"]
    memories = _installed_cli(
        installed,
        working,
        tmp_path,
        ["memory", "list", "--character", "rin-aster", "--json"],
        data_root=data_root,
    )
    assert memories["memory_references"] == [
        {
            "reference": memory["memory_reference"],
            "active_consent_generation": True,
        }
    ]
    removal_preview = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "memory",
            "remove",
            "--character",
            "rin-aster",
            "--host-id",
            "host-memory-installed-01",
            "--dry-run",
            "--json",
        ],
        data_root=data_root,
    )
    assert removal_preview["plan"]["memory_reference_id"] == memory_id
    removed_memory = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "memory",
            "remove",
            "--character",
            "rin-aster",
            "--host-id",
            "host-memory-installed-01",
            "--json",
        ],
        data_root=data_root,
    )
    assert removed_memory["result"] == {
        "removed": True,
        "memory_reference_id": memory_id,
    }

    reset = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "state",
            "reset",
            "--character",
            "rin-aster",
            "--part",
            "all",
            "--json",
        ],
        data_root=data_root,
    )
    assert reset["preview"]["target"] == "all"
    assert reset["result"]["record_state"] == "committed"
    reset_output = tmp_path / "reset-state.json"
    reset_export = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "state",
            "export",
            "--character",
            "rin-aster",
            "--out",
            str(reset_output),
            "--json",
        ],
        data_root=data_root,
    )
    reset_document = json.loads(reset_output.read_bytes())
    assert reset_export["export_sha256"] == reset_document["export_sha256"]
    assert reset_document["state"]["relationship"]["revision"] == 0
    assert reset_document["memory_references"] == []

    revoked = _installed_cli(
        installed,
        working,
        tmp_path,
        ["consent", "revoke", "--character", "rin-aster", "--json"],
        data_root=data_root,
    )
    assert revoked["consent"]["status"] == "revoked"
    ended = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "session",
            "end",
            "--session",
            "installed-workflow",
            "--json",
        ],
        data_root=data_root,
    )
    assert ended["session"]["active"] is False
    cleared = _installed_cli(
        installed,
        working,
        tmp_path,
        ["config", "default", "clear", "--json"],
        data_root=data_root,
    )
    assert cleared["default"]["binding"] is None
    removal = [
        "pack",
        "remove",
        "rin-aster",
        "--version",
        "1.0.0",
        "--json",
    ]
    removal_plan = _installed_cli(
        installed,
        working,
        tmp_path,
        [*removal[:-1], "--dry-run", "--json"],
        data_root=data_root,
    )
    assert removal_plan["dry_run"] is True
    assert removal_plan["plan"]["archive_will_be_removed"] is True
    assert installed_pack.is_dir()
    removed_pack = _installed_cli(
        installed,
        working,
        tmp_path,
        removal,
        data_root=data_root,
    )
    assert removed_pack["dry_run"] is False
    assert not installed_pack.exists()
    empty = _installed_cli(
        installed,
        working,
        tmp_path,
        ["pack", "list", "--json"],
        data_root=data_root,
    )
    assert empty["installed"] == []

    repeated_suite = _installed_cli(
        installed,
        working,
        tmp_path,
        [
            "suite",
            "install",
            "--scope",
            "user",
            "--skills-root",
            str(skills_root),
            "--json",
        ],
    )
    assert repeated_suite["skill_suite"]["will_write"] is False
    assert [
        item["action"] for item in repeated_suite["skill_suite"]["skills"]
    ] == ["unchanged", "unchanged", "unchanged", "unchanged"]
