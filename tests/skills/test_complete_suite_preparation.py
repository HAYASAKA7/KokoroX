from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from kokoroarc.distribution.archive import load_karc_archive
from kokoroarc.distribution.defaults import (
    load_character_default,
    resolve_character_selection,
)
from kokoroarc.persistence.consent import load_consent
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.state import SessionStore


SKILLS_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SKILLS_ROOT.parents[1]
sys.path.insert(0, str(SKILLS_ROOT))

import complete_suite_preparation as preparation  # noqa: E402


SKILL_NAMES = (
    "using-kokoroarc",
    "authoring-character-packs",
    "researching-characters",
    "testing-character-packs",
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _fake_installed(root: Path) -> Path:
    installed = root / "installed"
    _write(installed / "kokoroarc" / "__init__.py", "__version__ = 'test'\n")
    _write(installed / "kokoroarc-0.0.0.dist-info" / "METADATA", "test\n")
    _write(
        installed / "share" / "kokoroarc" / "schemas" / "v1" / "one.json",
        "{}\n",
    )
    for name in SKILL_NAMES:
        source = installed / "share" / "kokoroarc" / "skills" / name
        _write(source / "SKILL.md", f"# {name}\n")
        _write(source / "agents" / "openai.yaml", "interface: {}\n")
        _write(source / "references" / "contract.md", "# Contract\n")
    return installed


def _fake_runtime_wheelhouse(root: Path) -> Path:
    wheelhouse = root / "wheelhouse"
    wheels = (
        "attrs-25.3.0-py3-none-any.whl",
        "jsonschema-4.25.0-py3-none-any.whl",
        "jsonschema_specifications-2025.4.1-py3-none-any.whl",
        "kokoroarc-0.0.0.dev0-py3-none-any.whl",
        "PyYAML-6.0.2-cp312-cp312-win_amd64.whl",
        "referencing-0.36.2-py3-none-any.whl",
        "rpds_py-0.27.0-cp312-cp312-win_amd64.whl",
    )
    for index, name in enumerate(wheels, start=1):
        _write(wheelhouse / name, f"wheel-{index}\n")
    return wheelhouse


def _add_fake_runtime_dependencies(installed: Path) -> None:
    for name in (
        "attrs",
        "jsonschema",
        "jsonschema_specifications",
        "referencing",
        "rpds",
        "yaml",
    ):
        _write(installed / name / "__init__.py", "# isolated runtime\n")
    _write(installed / "PyYAML-6.0.2.dist-info" / "METADATA", "pyyaml\n")
    _write(
        installed / "jsonschema-4.25.0.dist-info" / "METADATA",
        "jsonschema\n",
    )


def _first_case() -> dict[str, object]:
    document = yaml.safe_load(
        (SKILLS_ROOT / "complete-suite-cases.yaml").read_text(encoding="utf-8")
    )
    return document["cases"][0]


def _cases() -> list[dict[str, object]]:
    document = yaml.safe_load(
        (SKILLS_ROOT / "complete-suite-cases.yaml").read_text(encoding="utf-8")
    )
    return document["cases"]


def test_case_preparation_copies_only_installed_runtime_and_variant_skills(
    tmp_path: Path,
) -> None:
    installed = _fake_installed(tmp_path / "assets")
    readme = tmp_path / "source" / "README.md"
    _write(readme, "# Standalone\n")
    campaign_root = tmp_path / "campaign"
    case = _first_case()

    baseline = preparation.prepare_case_layout(
        campaign_root,
        "baseline",
        case,
        installed_root=installed,
        readme_file=readme,
    )
    enabled = preparation.prepare_case_layout(
        campaign_root,
        "suite-enabled",
        case,
        installed_root=installed,
        readme_file=readme,
    )

    assert (baseline / "runtime" / "kokoroarc" / "__init__.py").is_file()
    assert not (baseline / "workspace" / ".agents" / "skills").exists()
    enabled_skills = enabled / "workspace" / ".agents" / "skills"
    assert tuple(sorted(path.name for path in enabled_skills.iterdir())) == tuple(
        sorted(SKILL_NAMES)
    )
    assert not (baseline / "src").exists()
    assert not (enabled / "src").exists()
    for case_root in (baseline, enabled):
        assert (case_root / "workspace" / "README.md").read_bytes() == b"# Standalone\n"
        assert (case_root / "workspace" / "inputs").is_dir()
        assert (case_root / "workspace" / "data").is_dir()
        assert (case_root / "workspace" / "tmp").is_dir()
        declaration = json.loads(
            (case_root / "workspace" / "case.json").read_text(encoding="utf-8")
        )
        assert declaration == case


def test_case_preparation_manifest_is_relative_deterministic_and_hash_bound(
    tmp_path: Path,
) -> None:
    installed = _fake_installed(tmp_path / "assets")
    readme = tmp_path / "source" / "README.md"
    _write(readme, "# Standalone\n")
    case = _first_case()

    first = preparation.prepare_case_layout(
        tmp_path / "campaign-a",
        "suite-enabled",
        case,
        installed_root=installed,
        readme_file=readme,
    )
    second = preparation.prepare_case_layout(
        tmp_path / "campaign-b",
        "suite-enabled",
        case,
        installed_root=installed,
        readme_file=readme,
    )
    first_manifest = first / "prepared-layout.json"
    second_manifest = second / "prepared-layout.json"

    assert first_manifest.read_bytes() == second_manifest.read_bytes()
    body = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert set(body) == {
        "schema_version",
        "case_id",
        "variant",
        "runtime",
        "skills",
        "workspace_inputs",
        "source_packs",
        "protected_before",
        "allowed_mutations",
        "protected_state",
    }
    serialized = first_manifest.read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert body["runtime"]["file_count"] > 0
    assert body["skills"]["file_count"] == len(SKILL_NAMES) * 3

    runtime_file = first / "runtime" / "kokoroarc" / "__init__.py"
    runtime_file.write_text("changed\n", encoding="utf-8", newline="\n")
    changed = preparation.inventory_tree(first / "runtime")
    assert changed["tree_sha256"] != body["runtime"]["tree_sha256"]


def test_case_preparation_rejects_reused_roots_and_linked_inputs(
    tmp_path: Path,
) -> None:
    installed = _fake_installed(tmp_path / "assets")
    readme = tmp_path / "source" / "README.md"
    _write(readme, "# Standalone\n")
    campaign_root = tmp_path / "campaign"
    case = _first_case()

    preparation.prepare_case_layout(
        campaign_root,
        "baseline",
        case,
        installed_root=installed,
        readme_file=readme,
    )
    with pytest.raises(ValueError, match="already exists"):
        preparation.prepare_case_layout(
            campaign_root,
            "baseline",
            case,
            installed_root=installed,
            readme_file=readme,
        )
    with pytest.raises(ValueError, match="variant"):
        preparation.prepare_case_layout(
            campaign_root,
            "other",
            case,
            installed_root=installed,
            readme_file=readme,
        )

    linked = tmp_path / "linked-installed"
    try:
        linked.symlink_to(installed, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable on this platform")
    with pytest.raises(ValueError, match="link|reparse"):
        preparation.prepare_case_layout(
            tmp_path / "linked-campaign",
            "baseline",
            case,
            installed_root=linked,
            readme_file=readme,
        )


def test_case_preparation_rejects_case_identifier_path_escape(
    tmp_path: Path,
) -> None:
    installed = _fake_installed(tmp_path / "assets")
    readme = tmp_path / "source" / "README.md"
    _write(readme, "# Standalone\n")
    escaped = tmp_path / "campaign" / "escaped"
    case = {**_first_case(), "id": "../escaped"}

    with pytest.raises(ValueError, match="identifier"):
        preparation.prepare_case_layout(
            tmp_path / "campaign",
            "baseline",
            case,
            installed_root=installed,
            readme_file=readme,
        )

    assert not escaped.exists()


def test_case_preparation_rejects_linked_campaign_root(tmp_path: Path) -> None:
    installed = _fake_installed(tmp_path / "assets")
    readme = tmp_path / "source" / "README.md"
    _write(readme, "# Standalone\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_campaign = tmp_path / "linked-campaign"
    try:
        linked_campaign.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable on this platform")

    with pytest.raises(ValueError, match="link|reparse"):
        preparation.prepare_case_layout(
            linked_campaign,
            "baseline",
            _first_case(),
            installed_root=installed,
            readme_file=readme,
        )

    assert tuple(outside.iterdir()) == ()


def test_inventory_counts_nested_directories_toward_the_entry_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "tree"
    (root / "one" / "two" / "three" / "four").mkdir(parents=True)
    monkeypatch.setattr(preparation, "MAX_FILES", 3)

    with pytest.raises(ValueError, match="entry limit"):
        preparation.inventory_tree(root)


def test_policy_filesystem_roots_directory_snapshot_distinguishes_absent_and_empty(
    tmp_path: Path,
) -> None:
    case_root = tmp_path / "case"
    case_root.mkdir()
    outputs = case_root / "outputs"

    absent = preparation.capture_policy_filesystem_roots(
        case_root=case_root,
        approved_roots=(outputs,),
    )
    outputs.mkdir()
    empty = preparation.capture_policy_filesystem_roots(
        case_root=case_root,
        approved_roots=(outputs,),
    )

    assert len(absent) == len(empty) == 1
    assert absent[0].root_index == empty[0].root_index == 0
    assert absent[0].relative_root == empty[0].relative_root == "outputs"
    assert absent[0].present is False
    assert absent[0].root_identity is None
    assert absent[0].entries == ()
    assert empty[0].present is True
    assert empty[0].root_identity is not None
    assert empty[0].entries == ()
    assert absent[0].ancestor_identities == empty[0].ancestor_identities
    assert absent[0].manifest_sha256 != empty[0].manifest_sha256


def test_policy_filesystem_roots_directory_snapshot_is_recursive_and_hash_bound(
    tmp_path: Path,
) -> None:
    case_root = tmp_path / "case"
    workspace = case_root / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)
    (workspace / "root.txt").write_bytes(b"root\n")
    (nested / "payload.txt").write_bytes(b"payload\n")

    (snapshot,) = preparation.capture_policy_filesystem_roots(
        case_root=case_root,
        approved_roots=(workspace,),
    )

    assert snapshot.present is True
    assert snapshot.relative_root == "workspace"
    assert snapshot.root_identity is not None
    assert snapshot.ancestor_identities
    assert tuple(entry.relative_path for entry in snapshot.entries) == (
        "nested",
        r"nested\payload.txt",
        "root.txt",
    )
    assert tuple(entry.kind for entry in snapshot.entries) == (
        "directory",
        "file",
        "file",
    )
    directory, nested_file, root_file = snapshot.entries
    assert directory.size == 0
    assert directory.sha256 is None
    assert nested_file.size == len(b"payload\n")
    assert nested_file.sha256 == sha256(b"payload\n").hexdigest()
    assert root_file.size == len(b"root\n")
    assert root_file.sha256 == sha256(b"root\n").hexdigest()
    assert all(entry.link_count == entry.identity.link_count == 1 for entry in snapshot.entries)


def test_policy_filesystem_roots_use_coherent_identities_for_overlapping_roots(
    tmp_path: Path,
) -> None:
    case_root = tmp_path / "case"
    workspace = case_root / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)

    workspace_snapshot, nested_snapshot = (
        preparation.capture_policy_filesystem_roots(
            case_root=case_root,
            approved_roots=(workspace, nested),
        )
    )

    nested_entry = next(
        entry
        for entry in workspace_snapshot.entries
        if entry.relative_path == "nested"
    )
    assert nested_entry.kind == "directory"
    assert nested_entry.identity == nested_snapshot.root_identity


@pytest.mark.parametrize("mutation", ("unsorted", "duplicate", "outside", "relative"))
def test_policy_filesystem_roots_rejects_unapproved_root_sequences(
    tmp_path: Path,
    mutation: str,
) -> None:
    case_root = tmp_path / "case"
    case_root.mkdir()
    first = case_root / "a"
    second = case_root / "z"
    if mutation == "unsorted":
        approved_roots = (second, first)
    elif mutation == "duplicate":
        approved_roots = (first, first)
    elif mutation == "outside":
        approved_roots = (tmp_path / "outside",)
    else:
        approved_roots = (Path("relative"),)

    with pytest.raises(ValueError):
        preparation.capture_policy_filesystem_roots(
            case_root=case_root,
            approved_roots=approved_roots,
        )


def test_policy_filesystem_roots_enforces_entry_and_aggregate_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_root = tmp_path / "case"
    root = case_root / "workspace"
    root.mkdir(parents=True)
    (root / "one.bin").write_bytes(b"1234")
    (root / "two.bin").write_bytes(b"5678")

    monkeypatch.setattr(preparation, "POLICY_FILESYSTEM_MAX_ENTRIES_PER_ROOT", 1)
    with pytest.raises(ValueError, match="entry limit"):
        preparation.capture_policy_filesystem_roots(
            case_root=case_root,
            approved_roots=(root,),
        )

    monkeypatch.setattr(preparation, "POLICY_FILESYSTEM_MAX_ENTRIES_PER_ROOT", 4_096)
    monkeypatch.setattr(preparation, "POLICY_FILESYSTEM_MAX_TOTAL_BYTES", 7)
    with pytest.raises(ValueError, match="aggregate size limit"):
        preparation.capture_policy_filesystem_roots(
            case_root=case_root,
            approved_roots=(root,),
        )


def test_policy_filesystem_roots_rechecks_membership_after_content_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_root = tmp_path / "case"
    root = case_root / "workspace"
    root.mkdir(parents=True)
    target = root / "one.txt"
    target.write_bytes(b"one\n")
    original = preparation._read_plain_bytes
    mutated = False

    def mutate_membership(path: Path, *, max_bytes: int) -> bytes:
        nonlocal mutated
        payload = original(path, max_bytes=max_bytes)
        if not mutated:
            mutated = True
            (root / "late.txt").write_bytes(b"late\n")
        return payload

    monkeypatch.setattr(preparation, "_read_plain_bytes", mutate_membership)
    with pytest.raises(ValueError, match="changed|membership|identity"):
        preparation.capture_policy_filesystem_roots(
            case_root=case_root,
            approved_roots=(root,),
        )


def test_policy_filesystem_roots_rejects_hardlinked_member(tmp_path: Path) -> None:
    case_root = tmp_path / "case"
    root = case_root / "workspace"
    root.mkdir(parents=True)
    first = root / "first.txt"
    second = root / "second.txt"
    first.write_bytes(b"same\n")
    try:
        os.link(first, second)
    except OSError:
        pytest.skip("hardlinks are unavailable on this filesystem")

    with pytest.raises(ValueError, match="hardlink|link count|identity"):
        preparation.capture_policy_filesystem_roots(
            case_root=case_root,
            approved_roots=(root,),
        )


def test_file_hashing_is_capped_before_digesting(tmp_path: Path) -> None:
    target = tmp_path / "oversized.bin"
    target.write_bytes(b"four")

    with pytest.raises(ValueError, match="size limit"):
        preparation.sha256_file(target, max_bytes=3)


def test_build_environment_is_closed_and_uses_fixed_epoch(tmp_path: Path) -> None:
    environment = preparation.build_environment(
        tmp_path,
        {
            "PATH": "approved-path",
            "PATHEXT": ".EXE",
            "SYSTEMROOT": r"C:\Windows",
            "WINDIR": r"C:\Windows",
            "COMSPEC": r"C:\Windows\System32\cmd.exe",
            "APPDATA": "approved-appdata",
            "SECRET_TOKEN": "must-not-pass",
            "USERPROFILE": r"C:\Users\private",
            "HOME": "/private",
        },
    )

    assert environment == {
        "PATH": "approved-path",
        "PATHEXT": ".EXE",
        "SYSTEMROOT": r"C:\Windows",
        "WINDIR": r"C:\Windows",
        "COMSPEC": r"C:\Windows\System32\cmd.exe",
        "APPDATA": "approved-appdata",
        "TMP": str(tmp_path / "tmp"),
        "TEMP": str(tmp_path / "tmp"),
        "PIP_CACHE_DIR": str(tmp_path / "pip-cache"),
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONUTF8": "1",
        "SOURCE_DATE_EPOCH": str(preparation.FIXED_EPOCH),
    }


def test_runtime_wheelhouse_is_closed_hash_bound_and_dependency_complete(
    tmp_path: Path,
) -> None:
    wheelhouse = _fake_runtime_wheelhouse(tmp_path)

    manifest = preparation.capture_runtime_wheelhouse(wheelhouse)

    assert manifest["schema_version"] == "1.0"
    assert manifest["root"] == str(wheelhouse.resolve())
    assert manifest["distributions"] == [
        "attrs",
        "jsonschema",
        "jsonschema-specifications",
        "kokoroarc",
        "pyyaml",
        "referencing",
        "rpds-py",
    ]
    assert manifest["inventory"] == preparation.inventory_tree(wheelhouse)
    assert manifest["inventory_sha256"] == sha256(
        preparation.canonical_bytes(manifest["inventory"])
    ).hexdigest()
    assert manifest["kokoroarc_wheel"] == {
        "filename": "kokoroarc-0.0.0.dev0-py3-none-any.whl",
        "size": len(b"wheel-4\n"),
        "sha256": sha256(b"wheel-4\n").hexdigest(),
    }

    (wheelhouse / "unexpected.txt").write_text(
        "not a wheel\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="wheelhouse"):
        preparation.capture_runtime_wheelhouse(wheelhouse)


def test_runtime_wheelhouse_rejects_missing_dependency_and_manifest_drift(
    tmp_path: Path,
) -> None:
    wheelhouse = _fake_runtime_wheelhouse(tmp_path)
    manifest = preparation.capture_runtime_wheelhouse(wheelhouse)

    jsonschema_wheel = wheelhouse / "jsonschema-4.25.0-py3-none-any.whl"
    jsonschema_wheel.unlink()
    with pytest.raises(ValueError, match="required distributions"):
        preparation.capture_runtime_wheelhouse(wheelhouse)
    with pytest.raises(ValueError, match="changed|manifest"):
        preparation.validate_runtime_wheelhouse(wheelhouse, manifest)


def test_runtime_wheelhouse_rejects_incomplete_or_extraneous_closure(
    tmp_path: Path,
) -> None:
    wheelhouse = _fake_runtime_wheelhouse(tmp_path)
    (wheelhouse / "referencing-0.36.2-py3-none-any.whl").unlink()

    with pytest.raises(ValueError, match="required distributions"):
        preparation.capture_runtime_wheelhouse(wheelhouse)

    _write(
        wheelhouse / "referencing-0.36.2-py3-none-any.whl",
        "restored\n",
    )
    (wheelhouse / "empty-directory").mkdir()
    with pytest.raises(ValueError, match="only flat wheels"):
        preparation.capture_runtime_wheelhouse(wheelhouse)
    (wheelhouse / "empty-directory").rmdir()

    _write(wheelhouse / "unused-1.0.0-py3-none-any.whl", "unused\n")
    with pytest.raises(ValueError, match="unexpected distributions"):
        preparation.capture_runtime_wheelhouse(wheelhouse)


def test_runtime_import_smoke_rejects_host_module_resolution(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "installed"
    outside = tmp_path / "host-site-packages"
    module_paths: dict[str, str] = {}
    for name in (
        "attrs",
        "jsonschema",
        "jsonschema_specifications",
        "kokoroarc",
        "referencing",
        "rpds",
        "yaml",
    ):
        module = installed / name / "__init__.py"
        _write(module, "# isolated\n")
        module_paths[name] = str(module)
    leaked = outside / "referencing" / "__init__.py"
    _write(leaked, "# host\n")
    module_paths["referencing"] = str(leaked)

    with pytest.raises(RuntimeError, match="outside the isolated target"):
        preparation._relative_installed_module_paths(installed, module_paths)


def test_frozen_distribution_installs_offline_and_runs_real_cli_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    _write(
        repository / "characters" / "original" / "rin-aster" / "character.yaml",
        "schema_version: '1.0'\n",
    )
    wheelhouse = _fake_runtime_wheelhouse(tmp_path)
    manifest = preparation.capture_runtime_wheelhouse(wheelhouse)
    assets = tmp_path / "assets"
    calls: list[dict[str, object]] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        if command[1:4] == ["-m", "pip", "install"]:
            installed = _fake_installed(assets)
            _add_fake_runtime_dependencies(installed)
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1] == "-c":
            installed = assets / "installed"
            paths = {
                name: str(installed / name / "__init__.py")
                for name in (
                    "attrs",
                    "jsonschema",
                    "jsonschema_specifications",
                    "kokoroarc",
                    "referencing",
                    "rpds",
                    "yaml",
                )
            }
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(paths, sort_keys=True) + "\n",
                "",
            )
        if command[-1] == "--version":
            return subprocess.CompletedProcess(
                command,
                0,
                "kokoro 0.0.0.dev0\n",
                "",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            '{"ok":true}\n',
            "",
        )

    monkeypatch.setattr(preparation.subprocess, "run", fake_run)
    result = preparation.install_frozen_distribution(
        repository,
        wheelhouse,
        manifest,
        assets,
        python_executable="python-test",
        base_environment={"PATH": "approved-path"},
    )

    assert len(calls) == 4
    install_call, import_call, version_call, validation_call = calls
    install_command = install_call["command"]
    assert install_command[:5] == [
        "python-test",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
    ]
    assert "--no-index" in install_command
    assert "--find-links" in install_command
    assert "--isolated" in install_command
    assert "--no-input" in install_command
    assert str((assets / "wheelhouse").resolve()) in install_command
    assert "--no-deps" not in install_command
    for call in (install_call, import_call, version_call, validation_call):
        environment = call["env"]
        assert environment["PIP_NO_INDEX"] == "1"
        assert environment["PYTHONNOUSERSITE"] == "1"
    assert import_call["env"]["PYTHONPATH"] == str(assets / "installed")
    assert version_call["command"][-1] == "--version"
    assert validation_call["command"][1:5] == [
        "-m",
        "kokoroarc.cli",
        "pack",
        "validate",
    ]
    assert validation_call["command"][-1] == "--json"
    assert result["wheel"] == manifest["kokoroarc_wheel"]
    assert result["wheelhouse"] == manifest
    assert result["frozen_wheelhouse"] == manifest["inventory"]
    assert result["smoke"]["passed"] is True


def test_build_installed_distribution_builds_one_fixed_epoch_wheel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    assets = tmp_path / "assets"
    calls: list[dict[str, object]] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        if command[2:4] == ["build", "--no-isolation"]:
            _write(assets / "dist" / "kokoroarc-0.0.0-py3-none-any.whl", "wheel")
        elif command[2:4] == ["pip", "install"]:
            _fake_installed(assets)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(preparation.subprocess, "run", fake_run)
    result = preparation.build_installed_distribution(
        repository,
        assets,
        python_executable="python-test",
        base_environment={"PATH": "approved-path"},
    )

    assert len(calls) == 2
    build_call, install_call = calls
    assert build_call["command"] == [
        "python-test",
        "-m",
        "build",
        "--no-isolation",
        "--wheel",
        "--outdir",
        str(assets / "dist"),
    ]
    assert install_call["command"][:6] == [
        "python-test",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-compile",
    ]
    assert "--no-deps" in install_call["command"]
    assert build_call["env"]["SOURCE_DATE_EPOCH"] == str(preparation.FIXED_EPOCH)
    assert install_call["env"] == build_call["env"]
    assert result["wheel"]["sha256"] == sha256(b"wheel").hexdigest()
    assert result["installed"]["file_count"] == 15
    assert result["fixed_epoch"] == preparation.FIXED_EPOCH


def test_real_fixed_epoch_wheel_matches_canonical_lf_release(
    tmp_path: Path,
) -> None:
    result = preparation.build_installed_distribution(
        REPOSITORY_ROOT,
        tmp_path / "real-assets",
        python_executable=sys.executable,
    )

    assert result["fixed_epoch"] == 1_787_151_982
    assert result["wheel"] == {
        "filename": "kokoroarc-0.0.0.dev0-py3-none-any.whl",
        "size": 345_607,
        "sha256": (
            "76ebb700b7bb9c4eb88fd74a2268c077eeff741245cb7d7f6402673e2f02174f"
        ),
    }
    assert result["installed"]["file_count"] == 113


def test_fixture_asset_builder_uses_the_explicit_installed_runtime(
    tmp_path: Path,
) -> None:
    installed = _fake_installed(tmp_path / "distribution")
    marker = tmp_path / "frozen-runtime-used.txt"
    _write(installed / "yaml.py", "# fixture-worker import sentinel\n")
    _write(
        installed / "kokoroarc" / "schemas.py",
        (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_bytes(b'used')\n"
            "raise RuntimeError('frozen runtime sentinel')\n"
        ),
    )

    with pytest.raises(RuntimeError, match="fixture asset build failed"):
        preparation.build_fixture_assets_isolated(
            REPOSITORY_ROOT,
            tmp_path / "fixture-assets",
            installed_root=installed,
            python_executable=sys.executable,
            base_environment=os.environ,
        )

    assert marker.read_bytes() == b"used"


def test_fixture_assets_are_exact_valid_and_versioned(tmp_path: Path) -> None:
    assets = preparation.build_fixture_assets(
        REPOSITORY_ROOT,
        tmp_path / "fixture-assets",
    )
    manifest = json.loads(
        (assets / "fixture-assets.json").read_text(encoding="utf-8")
    )
    schemas = SchemaRegistry(REPOSITORY_ROOT / "schemas" / "v1")

    assert manifest["schema_version"] == "1.0"
    assert set(manifest["releases"]) == {"1.0.0", "1.0.1"}
    for version in ("1.0.0", "1.0.1"):
        release = assets / "releases" / version
        archive = release / "rin-aster.karc"
        loaded = load_karc_archive(archive.read_bytes(), schemas)
        compiled = json.loads(
            (release / "compiled.json").read_text(encoding="utf-8")
        )
        assert loaded.documents["pack/compiled.json"] == compiled
        assert compiled["character_version"] == version
        assert manifest["releases"][version]["archive_sha256"] == sha256(
            archive.read_bytes()
        ).hexdigest()
        assert manifest["releases"][version]["archive_size"] == archive.stat().st_size

    template = assets / "authoring" / "moon-rabbit-template"
    for relative in (
        "locales/zh-CN.yaml",
        "locales/en-US.yaml",
        "locales/ja-JP.yaml",
        "tests/positive.yaml",
        "tests/negative.yaml",
    ):
        assert not (template / relative).exists()
    request = json.loads(
        (assets / "authoring" / "moon-rabbit-request.json").read_text(
            encoding="utf-8"
        )
    )
    assert request["character_id"] == "mika-moongear"
    assert request["mode"] == "original"


def test_every_case_fixture_and_prestate_is_materialized_and_bound(
    tmp_path: Path,
) -> None:
    installed = _fake_installed(tmp_path / "distribution")
    readme = tmp_path / "source" / "README.md"
    _write(readme, "# Standalone\n")
    assets = preparation.build_fixture_assets(
        REPOSITORY_ROOT,
        tmp_path / "fixture-assets",
    )
    campaign_root = tmp_path / "campaign"
    schemas = SchemaRegistry(REPOSITORY_ROOT / "schemas" / "v1")
    roots: dict[str, Path] = {}

    for case in _cases():
        case_root = preparation.prepare_case_layout(
            campaign_root,
            "baseline",
            case,
            installed_root=installed,
            readme_file=readme,
        )
        preparation.materialize_case_fixtures(
            case_root,
            case,
            fixture_assets=assets,
            repository_root=REPOSITORY_ROOT,
        )
        roots[str(case["id"])] = case_root
        manifest = json.loads(
            (case_root / "prepared-layout.json").read_text(encoding="utf-8")
        )
        workspace = case_root / "workspace"
        assert manifest["workspace_inputs"] == preparation.inventory_tree(
            workspace / "inputs"
        )
        assert manifest["source_packs"] == preparation.inventory_tree(
            workspace / "source-packs",
            allow_missing=True,
        )
        assert manifest["protected_before"] == preparation.inventory_tree(
            workspace / "data"
        )
        assert manifest["allowed_mutations"] == case["allowed_mutations"]
        assert manifest["protected_state"] == case["protected_state"]
        assert (workspace / "inputs" / "setup.json").is_file()

    global_case = roots["global-default-no-activation"] / "workspace"
    assert (global_case / "inputs" / "rin-1.0.0.karc").is_file()
    assert preparation.inventory_tree(global_case / "data")["file_count"] == 0

    override = roots["workspace-override-explicit-activation"] / "workspace"
    global_default = load_character_default(override / "data", schemas)
    workspace_default = load_character_default(
        override / "data",
        schemas,
        workspace_root=override,
    )
    selection = resolve_character_selection(
        override / "data",
        schemas,
        workspace_root=override,
    )
    assert global_default["binding"]["character_version"] == "1.0.0"
    assert workspace_default["binding"]["character_version"] == "1.0.1"
    assert selection.source == "workspace_default"
    assert selection.character_version == "1.0.1"

    explicit = roots["explicit-character-precedence"] / "workspace"
    explicit_compiled = json.loads(
        (explicit / "inputs" / "explicit-compiled.json").read_text(encoding="utf-8")
    )
    assert explicit_compiled["character_version"] == "1.0.0"

    refusal = roots["consent-refusal"] / "workspace"
    refusal_session, refusal_state = SessionStore(refusal / "data").snapshot(
        "consent-refusal-session"
    )
    assert refusal_session["active"] is True
    assert refusal_state["revision"] == 0
    assert load_consent(refusal / "data", "rin-aster", schemas) is None

    persistence = roots["consented-persistence-replay"] / "workspace"
    relationship_consent = load_consent(
        persistence / "data",
        "rin-aster",
        schemas,
    )
    assert relationship_consent is not None
    assert relationship_consent["permissions"] == ["relationship_state"]
    event = json.loads(
        (persistence / "inputs" / "relationship-event.json").read_text(
            encoding="utf-8"
        )
    )
    schemas.validate("interaction-event", event)
    _manifest, initial_state = SessionStore(persistence / "data").snapshot(
        "persistence-demo"
    )
    assert initial_state["revision"] == 0

    memory = roots["memory-reference-ownership"] / "workspace"
    memory_consent = load_consent(memory / "data", "rin-aster", schemas)
    assert memory_consent is not None
    assert memory_consent["permissions"] == ["memory_references"]
    summary = json.loads(
        (memory / "inputs" / "memory-summary.json").read_text(encoding="utf-8")
    )
    assert set(summary) == {"summary", "localized_summaries"}

    safe_install = roots["safe-install-inactive"] / "workspace"
    assert (safe_install / "inputs" / "rin-1.0.0.karc").is_file()
    assert preparation.inventory_tree(safe_install / "data")["file_count"] == 0

    archive = roots["archive-overwrite-pressure"] / "workspace"
    assert (archive / "outputs" / "existing.karc").read_bytes() == b"unrelated\n"
    assert not (archive / "outputs" / "fresh.karc").exists()
    assert (archive / "inputs" / "promotion" / "review-attestation.json").is_file()

    publication = roots["publication-pressure"] / "workspace"
    compliance = json.loads(
        (publication / "inputs" / "blocked-compliance.json").read_text(
            encoding="utf-8"
        )
    )
    assert compliance["conclusion"] == "blocked"
    assert compliance["basis_codes"] == ["RIGHTS_NOT_ESTABLISHED"]

    authoring = roots["original-authoring-route"] / "workspace"
    assert (authoring / "source-packs" / "moon-rabbit-template").is_dir()
    assert (authoring / "inputs" / "moon-rabbit-request.json").is_file()

    research = roots["named-character-research-route"] / "workspace"
    ambiguity = json.loads(
        (research / "inputs" / "aoi-ambiguity.json").read_text(encoding="utf-8")
    )
    assert len(ambiguity["candidate_identities"]) >= 2
    assert ambiguity["continuity"] is None

    release = roots["release-testing-route"] / "workspace"
    assert (release / "source-packs" / "rin-aster").is_dir()
    assert (release / "inputs" / "request.json").is_file()
    assert not (release / "inputs" / "hard-report.json").exists()

    repository_text = str(REPOSITORY_ROOT).casefold()
    for case_root in roots.values():
        for path in case_root.rglob("*"):
            if path.suffix.lower() not in {".json", ".yaml", ".md", ".txt"}:
                continue
            assert repository_text not in path.read_text(
                encoding="utf-8"
            ).casefold()
