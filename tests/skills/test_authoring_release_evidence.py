from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README_PATH = ROOT / "README.md"
EVIDENCE_PATH = ROOT / "tests" / "skills" / "authoring-release-verification.md"
PLAN_PATH = ROOT / "docs" / "superpowers" / "plans" / "2026-08-03-kokoroarc-authoring.md"
README = README_PATH.read_text(encoding="utf-8")
EVIDENCE = EVIDENCE_PATH.read_text(encoding="utf-8")
PLAN = PLAN_PATH.read_text(encoding="utf-8")
AUTHORING_RELEASE_COMMIT = "d944c8277183fb111de233b7ff3fe5398c5e398f"


def _section(document: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = document.index(marker)
    remainder = document[start + len(marker) :]
    match = re.search(r"^## ", remainder, flags=re.MULTILINE)
    return remainder if match is None else remainder[: match.start()]


def _subsection(document: str, heading: str) -> str:
    marker = f"### {heading}\n"
    start = document.index(marker)
    remainder = document[start + len(marker) :]
    match = re.search(r"^### ", remainder, flags=re.MULTILINE)
    return remainder if match is None else remainder[: match.start()]


def _identity(label: str) -> str:
    match = re.search(
        rf"^\| {re.escape(label)} \| `([^`]+)` \|$", EVIDENCE, flags=re.MULTILINE
    )
    assert match is not None, f"missing identity row: {label}"
    return match.group(1)


def _git_stdout(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, stdout=subprocess.PIPE
    ).stdout


def _historical_file(path: str) -> bytes:
    return _git_stdout("show", f"{AUTHORING_RELEASE_COMMIT}:{path}")


def test_readme_routes_actual_authoring_through_repository_local_skill() -> None:
    authoring = _section(README, "Author a private inactive draft with the repository-local Skill")
    required = (
        "skills/authoring-character-packs/SKILL.md",
        "$authoring-character-packs",
        "original brief",
        "private dossier",
        "KOKOROARC_DATA_DIR",
        "private",
        "inactive",
        "`SKILL.md` frontmatter",
        "name",
        "trigger-only `description`",
        "optional interface metadata",
        "agents/openai.yaml",
    )
    for text in required:
        assert text in authoring

    assert "discover its name and trigger from `skills/authoring-character-packs/agents/openai.yaml`" not in authoring
    assert "globally installed" not in authoring
    assert "## Validate and compile an already-authored source pack" in README


def test_documented_build_identity_matches_computed_readme_patch() -> None:
    build = _section(EVIDENCE, "Exact distribution build input")
    base = _identity("Base HEAD")
    documented_sha256 = _identity("README SHA-256 (`Get-FileHash`)")
    documented_blob = _identity("README Git blob (`git hash-object`)")
    documented_patch = _identity("README normalized patch SHA-256")

    assert re.fullmatch(r"[0-9a-f]{40}", base)
    historical_readme = _historical_file("README.md")
    assert hashlib.sha256(historical_readme).hexdigest().upper() == documented_sha256
    assert (
        _git_stdout("rev-parse", f"{AUTHORING_RELEASE_COMMIT}:README.md")
        .decode()
        .strip()
        == documented_blob
    )

    raw_patch = _git_stdout(
        "diff", "--binary", base, AUTHORING_RELEASE_COMMIT, "--", "README.md"
    )
    normalized_patch = raw_patch.replace(b"\r\n", b"\n")
    assert hashlib.sha256(normalized_patch).hexdigest().upper() == documented_patch
    assert "CRLF byte pair with LF; no other normalization" in build


def test_readme_checkout_policy_is_lf_and_matches_documented_patch() -> None:
    historical_attributes = _historical_file(".gitattributes").decode("utf-8")
    assert "README.md text eol=lf" in historical_attributes.splitlines()

    base = _identity("Base HEAD")
    documented_blob = _identity(".gitattributes Git blob (`git hash-object`)")
    documented_patch = _identity(".gitattributes normalized patch SHA-256")
    assert (
        _git_stdout("rev-parse", f"{AUTHORING_RELEASE_COMMIT}:.gitattributes")
        .decode()
        .strip()
        == documented_blob
    )

    raw_patch = _git_stdout(
        "diff",
        "--binary",
        base,
        AUTHORING_RELEASE_COMMIT,
        "--",
        ".gitattributes",
    )
    normalized_patch = raw_patch.replace(b"\r\n", b"\n")
    assert hashlib.sha256(normalized_patch).hexdigest().upper() == documented_patch

    build = _section(EVIDENCE, "Exact distribution build input")
    assert ".gitattributes\nREADME.md" in build
    assert "checkout policy" in build


def test_only_readme_changed_among_explicit_distribution_inputs() -> None:
    base = _identity("Base HEAD")
    changed = _git_stdout(
        "diff",
        "--name-only",
        base,
        AUTHORING_RELEASE_COMMIT,
        "--",
        "pyproject.toml",
        "src",
        "schemas",
    )
    assert changed == b""

    build = _section(EVIDENCE, "Exact distribution build input")
    assert "`pyproject.toml`, `src/`, and `schemas/`" in build
    task8 = PLAN[PLAN.index("### Task 8: Milestone 6 release verification") :]
    assert "`pyproject.toml`, `src/`, and `schemas/`" in task8


def test_release_evidence_declares_prepared_host_and_external_validator() -> None:
    prerequisites = _section(EVIDENCE, "Prepared-host prerequisites and isolated directories")
    for text in (
        "Python 3.11+",
        "PowerShell 7",
        "Git",
        'python -m pip install -e ".[dev]"',
        "$skillCreatorValidator",
        "external prerequisite",
        "not repository content",
        "New-Item -ItemType Directory",
    ):
        assert text in prerequisites
    assert "fresh setup" not in EVIDENCE.lower()


def test_release_evidence_scopes_exact_outcomes_to_named_sections() -> None:
    complete = _section(EVIDENCE, "Complete verification")
    suite = _subsection(complete, "Runtime, authoring, and evidence suite")
    distribution = _subsection(complete, "Distribution build and contents")
    skills = _subsection(complete, "Skill validation and diff hygiene")
    smoke = _section(EVIDENCE, "Copy/paste auditable CLI smoke")

    assert "Exit code: `0`. Result: `1354 passed, 19 skipped`" in suite
    assert "$env:TEMP" in suite and "$env:TMP" in suite and "--basetemp" in suite
    assert "Exit code: `0`" in distribution
    assert "77,148" in distribution and "58,693" in distribution
    assert "python $skillCreatorValidator skills/using-kokoroarc" in skills
    assert "python $skillCreatorValidator skills/authoring-character-packs" in skills
    assert "Both Skill validators exited `0`" in skills
    assert "The exact `git diff --check` command above exited `0`" in skills

    for filename in (
        "request-1.json",
        "request-2.json",
        "draft-1.json",
        "draft-2.json",
        "compile.json",
    ):
        assert filename in smoke
    for text in (
        "SequenceEqual[byte]",
        "build_status",
        "activation_allowed",
        "compiled",
        "installed",
        "public",
        "sessions",
        "state",
        "events",
        "Get-FileHash",
        "canonical transcript",
    ):
        assert text in smoke
