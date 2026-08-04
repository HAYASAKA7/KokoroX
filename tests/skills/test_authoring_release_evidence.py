from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
EVIDENCE = (
    ROOT / "tests" / "skills" / "authoring-release-verification.md"
).read_text(encoding="utf-8")


def test_readme_routes_actual_authoring_through_repository_local_skill() -> None:
    required = (
        "skills/authoring-character-packs/SKILL.md",
        "$authoring-character-packs",
        "original brief",
        "private dossier",
        "KOKOROARC_DATA_DIR",
        "private",
        "inactive",
        "already-authored source pack",
    )
    for text in required:
        assert text in README

    assert "globally installed" not in README
    assert "## Validate and compile an already-authored source pack" in README


def test_release_evidence_identifies_the_readme_only_build_input() -> None:
    required = (
        "5324281d2ace5fe1306c1cdca195fcd766d3a764",
        "git diff --binary -- README.md",
        "git diff --name-only",
        "README SHA-256",
        "README Git blob",
        "normalized patch SHA-256",
        "README.md",
        "not packaged inputs",
    )
    for text in required:
        assert text in EVIDENCE

    assert "clean build" not in EVIDENCE.lower()


def test_release_evidence_reproduction_covers_all_final_gates() -> None:
    required = (
        "New-Item -ItemType Directory",
        "$env:TEMP",
        "$env:TMP",
        "--basetemp",
        "python -m build",
        "request-1.json",
        "request-2.json",
        "draft-1.json",
        "draft-2.json",
        "compile.json",
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
        "git diff --check",
        "Exit code: `0`",
    )
    for text in required:
        assert text in EVIDENCE
