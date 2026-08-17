from __future__ import annotations

import json
from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile


REPOSITORY_ROOT = Path.cwd().resolve()
RESEARCH_FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures" / "research"
REQUIRED_RESEARCH_MODULES = {
    "kokoroarc/research/__init__.py",
    "kokoroarc/research/bundles.py",
    "kokoroarc/research/requests.py",
    "kokoroarc/research/storage.py",
    "kokoroarc/research/validation.py",
    "kokoroarc/research/workspace.py",
}
REQUIRED_TESTING_MODULES = {
    f"kokoroarc/testing/{name}.py"
    for name in (
        "__init__",
        "corpus",
        "hard",
        "promotion",
        "publication",
        "soft",
        "storage",
    )
}
REQUIRED_DISTRIBUTION_MODULES = {
    f"kokoroarc/distribution/{name}.py"
    for name in (
        "__init__",
        "archive",
        "compatibility",
        "installer",
        "migrations",
        "registry",
    )
}
REQUIRED_RESEARCH_SCHEMAS = {
    f"{name}.schema.json"
    for name in (
        "research-bundle",
        "research-claim",
        "research-conflict",
        "research-coverage",
        "research-request",
        "research-source-record",
        "research-validation-report",
        "research-workspace",
    )
}
REQUIRED_PACK_RELEASE_SCHEMAS = {
    f"{name}.schema.json"
    for name in (
        "pack-hard-validation-report",
        "pack-soft-evaluation-input",
        "pack-soft-evaluation-report",
        "pack-review-attestation",
        "pack-promotion-record",
        "pack-publication-readiness-report",
    )
}
REQUIRED_STANDALONE_SCHEMAS = {
    f"{name}.schema.json"
    for name in (
        "karc-manifest",
        "pack-compatibility-report",
        "pack-migration-plan",
        "installed-pack-registry",
        "character-default-config",
        "persistence-consent",
        "memory-reference",
    )
}
REQUIRED_SKILL_FILES = {
    f"{skill}/{relative}"
    for skill, contract in (
        ("using-kokoroarc", "runtime-contract.md"),
        ("authoring-character-packs", "authoring-contract.md"),
        ("researching-characters", "research-contract.md"),
        ("testing-character-packs", "testing-contract.md"),
    )
    for relative in (
        "SKILL.md",
        "agents/openai.yaml",
        f"references/{contract}",
    )
}
PROTECTED_STATE_ROOTS = (
    "drafts",
    "compiled",
    "installed",
    "public",
    "sessions",
    "state",
    "events",
    "workspaces",
    "config",
)


def _cli(
    arguments: list[str],
    *,
    data_dir: Path | None = None,
    python_path: Path | None = None,
    working_directory: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(python_path or REPOSITORY_ROOT / "src")
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
        cwd=working_directory,
    )


def _assert_error(
    completed: subprocess.CompletedProcess[str],
    code: str,
    message: str,
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


def _protected_state_snapshot(data_dir: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for root_name in PROTECTED_STATE_ROOTS:
        root = data_dir / root_name
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(data_dir).as_posix()
            snapshot[relative + ("/" if path.is_dir() else "")] = (
                b"" if path.is_dir() else path.read_bytes()
            )
    return snapshot


def test_research_request_validate_is_stateless_and_deterministic() -> None:
    arguments = [
        "research",
        "request",
        "validate",
        "--input",
        str(RESEARCH_FIXTURES / "complete" / "request.json"),
        "--json",
    ]

    first = _cli(arguments)
    second = _cli(arguments)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["request"]["requested_visibility"] == "private"
    assert first.stderr == second.stderr == ""


def test_research_workspace_validate_is_stateless_and_deterministic() -> None:
    arguments = [
        "research",
        "workspace",
        "validate",
        "--workspace",
        str(RESEARCH_FIXTURES / "complete"),
        "--json",
    ]

    first = _cli(arguments)
    second = _cli(arguments)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    body = json.loads(first.stdout)
    assert body["ok"] is True
    assert body["valid"] is True
    assert body["validation_report"]["authoring_allowed"] is True
    assert body["workspace_hash"] == (
        "36c328d763dd4ca705f1619c8225cbc304ac09ccfe930c54375d2b9cf8c128a1"
    )
    assert first.stderr == second.stderr == ""


def test_research_bundle_compile_publishes_deterministic_private_bundle(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    arguments = [
        "research",
        "bundle",
        "compile",
        "--workspace",
        str(RESEARCH_FIXTURES / "complete"),
        "--json",
    ]

    first = _cli(arguments, data_dir=data_dir)
    second = _cli(arguments, data_dir=data_dir)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    body = json.loads(first.stdout)
    assert body["ok"] is True
    assert body["build_status"] == "research"
    assert body["visibility"] == "private"
    assert body["activation_allowed"] is False
    assert body["authoring_allowed"] is True
    assert body["coverage_summary"] == {
        "blocked": 0,
        "covered": 2,
        "missing": 0,
        "partial": 0,
    }
    assert body["blocking_reasons"] == []
    assert len(body["conflicts"]) == 1
    assert len(body["request_hash"]) == 64
    assert len(body["workspace_hash"]) == 64
    assert len(body["validation_report_hash"]) == 64
    assert len(body["bundle_hash"]) == 64
    published = Path(body["path"])
    assert published.is_relative_to((data_dir / "research").resolve())
    assert sorted(path.name for path in published.iterdir()) == [
        "bundle.json",
        "request.json",
        "validation-report.json",
        "workspace.json",
    ]
    for protected in (
        "drafts",
        "compiled",
        "installed",
        "public",
        "sessions",
        "state",
        "events",
        "workspaces",
        "config",
    ):
        assert not (data_dir / protected).exists()
    assert first.stderr == second.stderr == ""


def test_research_bundle_validate_is_stateless_and_deterministic(
    tmp_path: Path,
) -> None:
    compiled = _cli(
        [
            "research",
            "bundle",
            "compile",
            "--workspace",
            str(RESEARCH_FIXTURES / "complete"),
            "--json",
        ],
        data_dir=tmp_path / "data",
    )
    published = json.loads(compiled.stdout)["path"]
    arguments = [
        "research",
        "bundle",
        "validate",
        "--bundle",
        published,
        "--json",
    ]

    first = _cli(arguments)
    second = _cli(arguments)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    body = json.loads(first.stdout)
    assert body["ok"] is True
    assert body["valid"] is True
    assert body["build_status"] == "research"
    assert body["visibility"] == "private"
    assert body["activation_allowed"] is False
    assert body["coverage_summary"] == {
        "blocked": 0,
        "covered": 2,
        "missing": 0,
        "partial": 0,
    }
    assert "path" not in body
    assert first.stderr == second.stderr == ""


def test_research_bundle_compile_preserves_partial_blocked_lifecycle(
    tmp_path: Path,
) -> None:
    completed = _cli(
        [
            "research",
            "bundle",
            "compile",
            "--workspace",
            str(RESEARCH_FIXTURES / "partial"),
            "--json",
        ],
        data_dir=tmp_path / "data",
    )

    assert completed.returncode == 0
    body = json.loads(completed.stdout)
    assert body["build_status"] == "research"
    assert body["visibility"] == "private"
    assert body["activation_allowed"] is False
    assert body["authoring_allowed"] is False
    assert body["coverage_summary"] == {
        "blocked": 1,
        "covered": 0,
        "missing": 0,
        "partial": 1,
    }
    assert body["blocking_reasons"]
    assert body["limitations"] == [
        "The requested historical appendix is unavailable."
    ]
    assert completed.stderr == ""


def test_research_bundle_compile_alone_requires_data_dir() -> None:
    completed = _cli(
        [
            "research",
            "bundle",
            "compile",
            "--workspace",
            str(RESEARCH_FIXTURES / "complete"),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "DATA_DIR_REQUIRED",
        "Set KOKOROARC_DATA_DIR before running a stateful command.",
    )


def test_research_request_validate_sanitizes_malformed_json(
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-RESEARCH-CREDENTIAL"
    request_path = tmp_path / "private-request.json"
    request_path.write_text('{"secret": "' + secret + '",}', encoding="utf-8")

    completed = _cli(
        [
            "research",
            "request",
            "validate",
            "--input",
            str(request_path),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "INPUT_INVALID_JSON",
        "Input file contains invalid JSON.",
    )
    assert secret not in completed.stdout
    assert str(request_path) not in completed.stdout


def test_research_workspace_validate_sanitizes_missing_workspace(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "PRIVATE-WORKSPACE-NAME"

    completed = _cli(
        [
            "research",
            "workspace",
            "validate",
            "--workspace",
            str(missing),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "RESEARCH_WORKSPACE_NOT_FOUND",
        "Research workspace was not found.",
    )
    assert str(missing) not in completed.stdout


def test_research_bundle_validate_sanitizes_missing_bundle(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "PRIVATE-BUNDLE-NAME"

    completed = _cli(
        [
            "research",
            "bundle",
            "validate",
            "--bundle",
            str(missing),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "RESEARCH_BUNDLE_INVALID",
        "Published Research Bundle validation failed.",
    )
    assert str(missing) not in completed.stdout


def test_research_request_validate_resolves_wheel_install_schema_layout(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "installed"
    shutil.copytree(REPOSITORY_ROOT / "src" / "kokoroarc", installed / "kokoroarc")
    shutil.copytree(
        REPOSITORY_ROOT / "schemas" / "v1",
        installed / "share" / "kokoroarc" / "schemas" / "v1",
    )
    outside_repository = tmp_path / "working"
    outside_repository.mkdir()

    completed = _cli(
        [
            "research",
            "request",
            "validate",
            "--input",
            str(RESEARCH_FIXTURES / "complete" / "request.json"),
            "--json",
        ],
        python_path=installed,
        working_directory=outside_repository,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["request"]["requested_visibility"] == "private"
    assert completed.stderr == ""


def test_built_archives_and_installed_research_cli_are_complete(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
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
    )
    assert built.returncode == 0, built.stdout + built.stderr
    wheel = next(dist.glob("*.whl"))
    sdist = next(dist.glob("*.tar.gz"))

    with zipfile.ZipFile(wheel) as archive:
        wheel_entries = set(archive.namelist())
        wheel_payloads = {
            name: archive.read(name)
            for name in wheel_entries
            if "/share/kokoroarc/skills/" in name
        }
    with tarfile.open(sdist, "r:gz") as archive:
        sdist_entries = {member.name for member in archive.getmembers()}
        sdist_payloads = {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile() and "/skills/" in member.name
        }

    for module in (
        REQUIRED_DISTRIBUTION_MODULES
        | REQUIRED_RESEARCH_MODULES
        | REQUIRED_TESTING_MODULES
    ):
        assert module in wheel_entries
        assert any(entry.endswith(f"/src/{module}") for entry in sdist_entries)
    for schema in (
        REQUIRED_RESEARCH_SCHEMAS
        | REQUIRED_PACK_RELEASE_SCHEMAS
        | REQUIRED_STANDALONE_SCHEMAS
    ):
        wheel_suffix = f"/share/kokoroarc/schemas/v1/{schema}"
        assert any(entry.endswith(wheel_suffix) for entry in wheel_entries)
        assert any(entry.endswith(f"/schemas/v1/{schema}") for entry in sdist_entries)
    for relative in REQUIRED_SKILL_FILES:
        wheel_suffix = f"/share/kokoroarc/skills/{relative}"
        wheel_name = next(
            entry for entry in wheel_entries if entry.endswith(wheel_suffix)
        )
        sdist_name = next(
            entry
            for entry in sdist_entries
            if entry.endswith(f"/skills/{relative}")
        )
        expected = (REPOSITORY_ROOT / "skills" / relative).read_bytes()
        assert wheel_payloads[wheel_name] == expected
        assert sdist_payloads[sdist_name] == expected

    installed = tmp_path / "installed"
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
        cwd=tmp_path,
    )
    assert installed_result.returncode == 0, (
        installed_result.stdout + installed_result.stderr
    )
    outside_repository = tmp_path / "working"
    outside_repository.mkdir()

    probe_env = os.environ.copy()
    probe_env["PYTHONPATH"] = str(installed)
    probe_env.pop("KOKOROARC_DATA_DIR", None)
    schema_names = sorted(
        name.removesuffix(".schema.json")
        for name in REQUIRED_STANDALONE_SCHEMAS
    )
    schema_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json\n"
                "from kokoroarc.config import resolve_schema_dir\n"
                "from kokoroarc.schemas import SchemaRegistry\n"
                f"names = {schema_names!r}\n"
                "registry = SchemaRegistry(resolve_schema_dir())\n"
                "print(json.dumps([registry.load(name)['$id'] "
                "for name in names], sort_keys=True))\n"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=probe_env,
        cwd=outside_repository,
    )
    assert schema_probe.returncode == 0, schema_probe.stdout + schema_probe.stderr
    assert json.loads(schema_probe.stdout) == [
        f"https://kokoroarc.local/schemas/v1/{name}.schema.json"
        for name in schema_names
    ]
    assert schema_probe.stderr == ""

    distribution_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from kokoroarc.distribution import (\n"
                "    InstallScope,\n"
                "    apply_karc_migration,\n"
                "    empty_installed_registry,\n"
                "    install_karc_archive,\n"
                "    inspect_karc_compatibility,\n"
                "    list_installed_packs,\n"
                "    load_installed_registry,\n"
                "    preview_karc_migration,\n"
                "    preview_karc_install,\n"
                "    recover_karc_installations,\n"
                "    remove_installed_pack,\n"
                "    resolve_install_scope,\n"
                ")\n"
                "assert callable(InstallScope)\n"
                "assert callable(apply_karc_migration)\n"
                "assert callable(empty_installed_registry)\n"
                "assert callable(install_karc_archive)\n"
                "assert callable(inspect_karc_compatibility)\n"
                "assert callable(list_installed_packs)\n"
                "assert callable(load_installed_registry)\n"
                "assert callable(preview_karc_migration)\n"
                "assert callable(preview_karc_install)\n"
                "assert callable(recover_karc_installations)\n"
                "assert callable(remove_installed_pack)\n"
                "assert callable(resolve_install_scope)\n"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=probe_env,
        cwd=outside_repository,
    )
    assert distribution_probe.returncode == 0, (
        distribution_probe.stdout + distribution_probe.stderr
    )
    assert distribution_probe.stdout == ""
    assert distribution_probe.stderr == ""

    request = _cli(
        [
            "research",
            "request",
            "validate",
            "--input",
            str(RESEARCH_FIXTURES / "complete" / "request.json"),
            "--json",
        ],
        python_path=installed,
        working_directory=outside_repository,
    )
    workspace = _cli(
        [
            "research",
            "workspace",
            "validate",
            "--workspace",
            str(RESEARCH_FIXTURES / "complete"),
            "--json",
        ],
        python_path=installed,
        working_directory=outside_repository,
    )
    compiled = _cli(
        [
            "research",
            "bundle",
            "compile",
            "--workspace",
            str(RESEARCH_FIXTURES / "complete"),
            "--json",
        ],
        data_dir=tmp_path / "data",
        python_path=installed,
        working_directory=outside_repository,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    bundle_path = json.loads(compiled.stdout)["path"]
    bundle = _cli(
        [
            "research",
            "bundle",
            "validate",
            "--bundle",
            bundle_path,
            "--json",
        ],
        python_path=installed,
        working_directory=outside_repository,
    )

    for completed in (request, workspace, compiled, bundle):
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert json.loads(completed.stdout)["ok"] is True
        assert completed.stderr == ""


def test_research_validation_and_failed_compile_do_not_mutate_product_state(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    compiled = _cli(
        [
            "research",
            "bundle",
            "compile",
            "--workspace",
            str(RESEARCH_FIXTURES / "complete"),
            "--json",
        ],
        data_dir=data_dir,
    )
    assert compiled.returncode == 0
    bundle_path = json.loads(compiled.stdout)["path"]
    for root_name in PROTECTED_STATE_ROOTS:
        root = data_dir / root_name
        root.mkdir(parents=True)
        (root / "sentinel.bin").write_bytes(root_name.encode("ascii"))
    before = _protected_state_snapshot(data_dir)
    invalid_workspace = tmp_path / "invalid-workspace"
    shutil.copytree(RESEARCH_FIXTURES / "complete", invalid_workspace)
    claim_path = invalid_workspace / "claims" / "claim-role.json"
    claim = json.loads(claim_path.read_bytes())
    claim["source_ids"] = ["missing-source"]
    claim_bytes = json.dumps(
        claim, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    claim_path.write_bytes(claim_bytes)
    manifest_path = invalid_workspace / "workspace.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["claims"][1]["sha256"] = sha256(claim_bytes).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    request = _cli(
        [
            "research",
            "request",
            "validate",
            "--input",
            str(RESEARCH_FIXTURES / "complete" / "request.json"),
            "--json",
        ]
    )
    workspace = _cli(
        [
            "research",
            "workspace",
            "validate",
            "--workspace",
            str(RESEARCH_FIXTURES / "complete"),
            "--json",
        ]
    )
    bundle = _cli(
        [
            "research",
            "bundle",
            "validate",
            "--bundle",
            bundle_path,
            "--json",
        ]
    )
    failed_compile = _cli(
        [
            "research",
            "bundle",
            "compile",
            "--workspace",
            str(invalid_workspace),
            "--json",
        ],
        data_dir=data_dir,
    )

    assert request.returncode == workspace.returncode == bundle.returncode == 0
    _assert_error(
        failed_compile,
        "RESEARCH_VALIDATION_FAILED",
        "Research validation failed.",
    )
    assert _protected_state_snapshot(data_dir) == before
