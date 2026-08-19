from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import shutil

import pytest


REPOSITORY_ROOT = Path.cwd().resolve()
PLUGIN_MANIFEST = REPOSITORY_ROOT / ".codex-plugin" / "plugin.json"
SOURCE_SKILLS = REPOSITORY_ROOT / "skills"
EXPECTED_SKILL_FILES = {
    "using-kokoroarc": {
        "SKILL.md",
        "agents/openai.yaml",
        "references/runtime-contract.md",
    },
    "authoring-character-packs": {
        "SKILL.md",
        "agents/openai.yaml",
        "references/authoring-contract.md",
    },
    "researching-characters": {
        "SKILL.md",
        "agents/openai.yaml",
        "references/research-contract.md",
    },
    "testing-character-packs": {
        "SKILL.md",
        "agents/openai.yaml",
        "references/testing-contract.md",
    },
}


def _suite_module():
    return importlib.import_module("kokoroarc.distribution.suite")


def _relative_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _copy_source(tmp_path: Path) -> Path:
    destination = tmp_path / "source-skills"
    shutil.copytree(SOURCE_SKILLS, destination)
    return destination


def _assert_error(code: str, callback) -> None:
    with pytest.raises(Exception) as raised:
        callback()
    assert getattr(raised.value, "code", None) == code


def test_plugin_manifest_declares_only_the_four_skill_suite() -> None:
    payload = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))

    assert set(payload) == {
        "name",
        "version",
        "description",
        "author",
        "skills",
        "interface",
    }
    assert payload["name"] == "kokoroarc"
    assert re.fullmatch(r"\d+\.\d+\.\d+", payload["version"])
    assert payload["version"] == "0.1.0"
    assert isinstance(payload["description"], str)
    assert payload["description"].strip()
    assert payload["author"] == {"name": "KokoroArc"}
    assert payload["skills"] == "./skills/"
    assert set(payload["interface"]) == {
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
        "capabilities",
        "defaultPrompt",
    }
    assert payload["interface"]["developerName"] == "KokoroArc"
    assert payload["interface"]["capabilities"] == ["Skills"]
    assert isinstance(payload["interface"]["defaultPrompt"], str)
    for field in (
        "displayName",
        "shortDescription",
        "longDescription",
        "category",
        "defaultPrompt",
    ):
        assert payload["interface"][field].strip()


def test_plugin_skill_inventory_is_closed_and_complete() -> None:
    payload = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    suite_root = (REPOSITORY_ROOT / payload["skills"]).resolve(strict=True)

    assert suite_root == SOURCE_SKILLS.resolve(strict=True)
    assert {entry.name for entry in suite_root.iterdir()} == set(
        EXPECTED_SKILL_FILES
    )
    assert _relative_files(suite_root) == {
        f"{skill}/{relative}"
        for skill, files in EXPECTED_SKILL_FILES.items()
        for relative in files
    }


def test_distribution_suite_exposes_the_frozen_public_surface() -> None:
    suite = _suite_module()
    distribution = importlib.import_module("kokoroarc.distribution")

    assert suite.SKILL_SUITE_NAMES == tuple(EXPECTED_SKILL_FILES)
    assert suite.SkillSuiteLimits().max_files == 12
    assert suite.SkillSuiteLimits().max_file_bytes == 512 * 1024
    assert suite.SkillSuiteLimits().max_total_bytes == 2 * 1024 * 1024
    assert callable(suite.resolve_skill_suite_source)
    assert callable(suite.preview_skill_suite_install)
    assert callable(suite.install_skill_suite)
    for name in (
        "SKILL_SUITE_NAMES",
        "SkillSuiteLimits",
        "resolve_skill_suite_source",
        "preview_skill_suite_install",
        "install_skill_suite",
    ):
        assert getattr(distribution, name) is getattr(suite, name)
        assert name in distribution.__all__


def test_explicit_source_resolution_requires_the_closed_suite(
    tmp_path: Path,
) -> None:
    suite = _suite_module()

    assert suite.resolve_skill_suite_source(SOURCE_SKILLS) == (
        SOURCE_SKILLS.resolve(strict=True)
    )
    with pytest.raises(Exception) as raised:
        suite.resolve_skill_suite_source(tmp_path)
    assert getattr(raised.value, "code", None) == "SKILL_SUITE_SOURCE_INVALID"


def test_explicit_source_cannot_rebind_during_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    outside = tmp_path / "outside-source"
    shutil.copytree(source, outside)
    real_resolve = Path.resolve

    def resolve(path: Path, strict: bool = False) -> Path:
        if path == source and strict:
            return outside
        return real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)

    assert suite.resolve_skill_suite_source(source) == source


def test_repository_source_is_discovered_without_an_override() -> None:
    suite = _suite_module()

    assert suite.resolve_skill_suite_source() == SOURCE_SKILLS.resolve(strict=True)


def test_installed_share_source_is_discovered_without_repository_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = _suite_module()
    site_packages = tmp_path / "site-packages"
    installed_module = site_packages / "kokoroarc" / "distribution" / "suite.py"
    installed_module.parent.mkdir(parents=True)
    installed_module.write_text("# location marker\n", encoding="utf-8")
    installed_skills = site_packages / "share" / "kokoroarc" / "skills"
    shutil.copytree(SOURCE_SKILLS, installed_skills)
    monkeypatch.setattr(suite, "__file__", str(installed_module))

    assert suite.resolve_skill_suite_source() == installed_skills.resolve(strict=True)


def test_automatic_source_discovery_rejects_two_complete_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = _suite_module()
    module = (
        tmp_path
        / "environment"
        / "lib"
        / "kokoroarc"
        / "distribution"
        / "suite.py"
    )
    module.parent.mkdir(parents=True)
    module.write_text("# location marker\n", encoding="utf-8")
    checkout_skills = module.parents[3] / "skills"
    installed_skills = module.parents[2] / "share" / "kokoroarc" / "skills"
    shutil.copytree(SOURCE_SKILLS, checkout_skills)
    shutil.copytree(SOURCE_SKILLS, installed_skills)
    monkeypatch.setattr(suite, "__file__", str(module))

    _assert_error("SKILL_SUITE_SOURCE_INVALID", suite.resolve_skill_suite_source)


def test_automatic_source_discovery_rejects_no_complete_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = _suite_module()
    module = tmp_path / "lib" / "kokoroarc" / "distribution" / "suite.py"
    module.parent.mkdir(parents=True)
    module.write_text("# location marker\n", encoding="utf-8")
    monkeypatch.setattr(suite, "__file__", str(module))

    _assert_error("SKILL_SUITE_SOURCE_INVALID", suite.resolve_skill_suite_source)


def test_preview_is_deterministic_closed_and_does_not_create_user_root(
    tmp_path: Path,
) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "user-home" / ".agents" / "skills"

    first = suite.preview_skill_suite_install(
        source_root=source,
        skills_root=skills_root,
    )
    second = suite.install_skill_suite(
        source_root=source,
        skills_root=skills_root,
        dry_run=True,
    )

    assert first == second
    assert first == {
        "artifact_id": "kokoroarc/skill-suite/install-plan",
        "version": "1.0.0",
        "scope": "user",
        "skills_root": str(skills_root.resolve(strict=False)),
        "source_tree_sha256": first["source_tree_sha256"],
        "skills": [
            {
                "name": name,
                "source_sha256": first["skills"][index]["source_sha256"],
                "target": str((skills_root / name).resolve(strict=False)),
                "action": "install",
            }
            for index, name in enumerate(EXPECTED_SKILL_FILES)
        ],
        "dry_run": True,
        "will_write": True,
    }
    assert re.fullmatch(r"[0-9a-f]{64}", first["source_tree_sha256"])
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", skill["source_sha256"])
        for skill in first["skills"]
    )
    assert not skills_root.exists()
    assert not (tmp_path / "user-home" / ".agents").exists()


def test_preview_uses_a_fake_home_without_creating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    fake_home = tmp_path / "fake-home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    result = suite.preview_skill_suite_install(source_root=source)

    assert result["skills_root"] == str(
        (fake_home / ".agents" / "skills").resolve(strict=False)
    )
    assert not fake_home.exists()


def test_preview_reports_an_unavailable_user_home_as_a_path_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = _suite_module()

    def unavailable_home() -> Path:
        raise RuntimeError("home unavailable")

    monkeypatch.setattr(Path, "home", unavailable_home)

    _assert_error(
        "SKILL_SUITE_PATH_INVALID",
        lambda: suite.preview_skill_suite_install(source_root=SOURCE_SKILLS),
    )


def test_repo_preview_requires_an_explicit_existing_root(tmp_path: Path) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    repo_root = tmp_path / "consumer-repo"
    repo_root.mkdir()

    result = suite.preview_skill_suite_install(
        source_root=source,
        scope="repo",
        repo_root=repo_root,
    )

    assert result["scope"] == "repo"
    assert result["skills_root"] == str(
        (repo_root / ".agents" / "skills").resolve(strict=False)
    )
    assert not (repo_root / ".agents").exists()


def test_repo_target_cannot_rebind_outside_the_explicit_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    repo_root = tmp_path / "consumer-repo"
    repo_root.mkdir()
    expected = repo_root / ".agents" / "skills"
    outside = tmp_path / "outside" / "skills"
    real_resolve = Path.resolve

    def resolve(path: Path, strict: bool = False) -> Path:
        if path == expected and not strict:
            return outside
        return real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)

    result = suite.preview_skill_suite_install(
        source_root=source,
        scope="repo",
        repo_root=repo_root,
    )

    assert result["skills_root"] == str(expected)
    assert not outside.parent.exists()


@pytest.mark.parametrize(
    ("kwargs", "prepare_repo"),
    [
        ({"scope": "repo"}, False),
        ({"scope": "repo", "skills_root": Path("skills")}, True),
        ({"scope": "user", "repo_root": Path("repo")}, False),
        ({"scope": "invalid"}, False),
        ({"scope": "user", "skills_root": Path("relative")}, False),
        ({"scope": "repo", "repo_root": Path("relative")}, False),
    ],
)
def test_preview_rejects_invalid_scope_arguments(
    tmp_path: Path,
    kwargs: dict[str, object],
    prepare_repo: bool,
) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    if prepare_repo:
        kwargs = dict(kwargs)
        kwargs["repo_root"] = tmp_path

    _assert_error(
        "SKILL_SUITE_PATH_INVALID",
        lambda: suite.preview_skill_suite_install(source_root=source, **kwargs),
    )


def test_preview_rejects_missing_repo_root(tmp_path: Path) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)

    _assert_error(
        "SKILL_SUITE_PATH_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            scope="repo",
            repo_root=tmp_path / "missing",
        ),
    )


@pytest.mark.parametrize("target_relation", ["same", "inside", "contains"])
def test_preview_rejects_source_target_overlap(
    tmp_path: Path,
    target_relation: str,
) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    if target_relation == "same":
        target = source
    elif target_relation == "inside":
        target = source / "install-target"
    else:
        target = source.parent

    _assert_error(
        "SKILL_SUITE_PATH_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=target,
        ),
    )


def test_preview_classifies_identical_and_missing_skills(tmp_path: Path) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    skills_root.mkdir()
    for name in tuple(EXPECTED_SKILL_FILES)[:2]:
        shutil.copytree(source / name, skills_root / name)

    result = suite.preview_skill_suite_install(
        source_root=source,
        skills_root=skills_root,
    )

    assert [skill["action"] for skill in result["skills"]] == [
        "unchanged",
        "unchanged",
        "install",
        "install",
    ]
    assert result["will_write"] is True
    assert not any(path.name.startswith(".kokoroarc") for path in skills_root.iterdir())


def test_preview_of_an_identical_suite_is_a_noop(tmp_path: Path) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    shutil.copytree(source, skills_root)

    result = suite.preview_skill_suite_install(
        source_root=source,
        skills_root=skills_root,
    )

    assert {skill["action"] for skill in result["skills"]} == {"unchanged"}
    assert result["will_write"] is False


def test_preview_rejects_a_nonidentical_existing_skill(tmp_path: Path) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    shutil.copytree(source, skills_root)
    (skills_root / "using-kokoroarc" / "SKILL.md").write_text(
        "different\n",
        encoding="utf-8",
    )

    _assert_error(
        "SKILL_SUITE_CONFLICT",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=skills_root,
        ),
    )


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_preview_classifies_inventory_differences_as_conflicts(
    tmp_path: Path,
    mutation: str,
) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    skills_root = tmp_path / "installed"
    shutil.copytree(source, skills_root)
    target = skills_root / "using-kokoroarc"
    if mutation == "extra":
        (target / "extra.txt").write_text("extra\n", encoding="utf-8")
    else:
        (target / "references" / "runtime-contract.md").unlink()

    _assert_error(
        "SKILL_SUITE_CONFLICT",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=skills_root,
        ),
    )


def test_preview_rejects_lexically_ambiguous_absolute_target(
    tmp_path: Path,
) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    ambiguous = tmp_path / "parent" / ".." / "installed"

    _assert_error(
        "SKILL_SUITE_PATH_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=ambiguous,
        ),
    )

@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_file",
        "missing_file",
        "duplicate_frontmatter",
        "aliased_frontmatter",
        "wrong_name",
        "invalid_utf8",
        "missing_default_prompt",
        "unknown_agent_interface",
        "executable_file",
    ],
)
def test_preview_rejects_invalid_source_skills(
    tmp_path: Path,
    mutation: str,
) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)
    skill_file = source / "using-kokoroarc" / "SKILL.md"
    if mutation == "unknown_file":
        (source / "using-kokoroarc" / "unknown.txt").write_text("x")
    elif mutation == "missing_file":
        (source / "using-kokoroarc" / "agents" / "openai.yaml").unlink()
    elif mutation == "duplicate_frontmatter":
        text = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(
            text.replace("description:", "description: first\ndescription:", 1),
            encoding="utf-8",
        )
    elif mutation == "aliased_frontmatter":
        text = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(
            text.replace(
                "name: using-kokoroarc",
                "name: &skill_name using-kokoroarc\nmetadata: *skill_name",
                1,
            ),
            encoding="utf-8",
        )
    elif mutation == "wrong_name":
        text = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(
            text.replace("name: using-kokoroarc", "name: another-skill", 1),
            encoding="utf-8",
        )
    elif mutation == "invalid_utf8":
        skill_file.write_bytes(b"---\nname: \xff\n---\n")
    elif mutation == "missing_default_prompt":
        metadata = source / "using-kokoroarc" / "agents" / "openai.yaml"
        text = metadata.read_text(encoding="utf-8")
        metadata.write_text(
            "\n".join(
                line for line in text.splitlines() if "default_prompt:" not in line
            )
            + "\n",
            encoding="utf-8",
        )
    elif mutation == "unknown_agent_interface":
        metadata = source / "using-kokoroarc" / "agents" / "openai.yaml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8") + "  unknown: value\n",
            encoding="utf-8",
        )
    else:
        skill_file.chmod(skill_file.stat().st_mode | 0o111)
        if not skill_file.stat().st_mode & 0o111:
            pytest.skip("The current platform does not expose executable mode bits")

    _assert_error(
        "SKILL_SUITE_SOURCE_INVALID",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=tmp_path / "installed",
        ),
    )


@pytest.mark.parametrize(
    "limits",
    [
        {"max_files": 11},
        {"max_file_bytes": 1},
        {"max_total_bytes": 10},
    ],
)
def test_preview_enforces_source_limits(
    tmp_path: Path,
    limits: dict[str, int],
) -> None:
    suite = _suite_module()
    source = _copy_source(tmp_path)

    _assert_error(
        "SKILL_SUITE_LIMIT_EXCEEDED",
        lambda: suite.preview_skill_suite_install(
            source_root=source,
            skills_root=tmp_path / "installed",
            limits=suite.SkillSuiteLimits(**limits),
        ),
    )
