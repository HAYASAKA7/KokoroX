from __future__ import annotations

from hashlib import sha256
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PLAN = (
    ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-08-14-kokoroarc-completion.md"
).read_text(encoding="utf-8")
RESULTS = (
    ROOT / "tests" / "skills" / "testing-character-packs-results.md"
).read_text(encoding="utf-8")
EVIDENCE = (
    ROOT
    / "tests"
    / "skills"
    / "testing-character-packs-release-verification.md"
).read_text(encoding="utf-8")


def _section(document: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = document.index(marker) + len(marker)
    remainder = document[start:]
    next_heading = re.search(r"^## ", remainder, flags=re.MULTILINE)
    return remainder if next_heading is None else remainder[: next_heading.start()]


def test_readme_routes_agent_led_testing_through_repository_skill() -> None:
    section = _section(
        README,
        "Test, review, and promote a Character Pack",
    )
    for text in (
        "skills/testing-character-packs/SKILL.md",
        "$testing-character-packs",
        "validation, evaluation, review, promotion",
        "publication-readiness work",
        "ordinary character use",
        "private",
        "does not install",
        "does not activate",
        "does not publish",
        "Milestone 9",
    ):
        assert text in section


def test_release_evidence_records_complete_candidate_smoke() -> None:
    smoke = _section(EVIDENCE, "D:-confined deterministic CLI smoke")
    for text in (
        r"D:\tmp\kokoroarc-m8-release-20260817-candidate1",
        "10 commands",
        "hard-a.json",
        "hard-b.json",
        "soft-a.json",
        "soft-b.json",
        "rin-m8-release-reviewed-01",
        "rin-m8-release-verified-01",
        "publication-a.json",
        "publication-b.json",
        "source_snapshot_match: true",
        "input_snapshot_match: true",
        "protected_roots_absent: true",
        "7bf645816eb0cbd33a8433b6e6485078594f089a87588520fcdb32f53f7d50e7",
        "b0f57b7552df1d88e144d965530afc3704102802788d6295920b18ffd3afe24f",
        "f2ff67a32f2980385df16ebfd687302ce466417da05a710ab97cb9a42e108dc7",
        "457fba5b2bc2ccb316de119c25ecb9ad5f8702b7b5d098f9f70c86e0fd3836f8",
        "9a549e95d049ee21537d70b336b7a161cc0e5d3bf3ececa3f21080699877ea97",
        "aa9f766e4387152d1f330050ed7759a6215ad9729ba7d73585420ef74f89ba2e",
    ):
        assert text in smoke


def test_release_evidence_discloses_suite_attempts_and_capability_skips() -> None:
    suite = _section(EVIDENCE, "Complete repository suite")
    for text in (
        "ten-minute harness timeout",
        "zero-byte buffered stdout",
        "2,602 tests collected in 1.08s",
        "one corrected rerun",
        "2573 passed, 29 skipped in 629.74s",
        "4B1DEC7D764BF0214C0C8DC1091394E916E1F6180EFF454E2133A1854A389BEE",
        "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
        "symlink",
        "junction",
        "FIFO",
        "POSIX executable bits",
    ):
        assert text in suite


def test_release_evidence_records_packaging_red_green_and_fixed_epoch() -> None:
    distribution = _section(EVIDENCE, "Fixed-epoch distribution and inventory")
    for text in (
        "1786691951",
        "missing every Skill file",
        "1 failed",
        "1 passed",
        "seven testing modules",
        "six Milestone 8 schemas",
        "twelve Skill files",
        "candidate3",
        "16fc57205fca096cff52d25068d343d9f4bced8dd7f570b343ed4e0b82a13599",
        "9f3669347e46ebbf30a9bb94cf65e1599fa4ddbeb36273770c63afcba6364ad2",
        "2843b3f6edf7694c9b9b52493fdeb3f01328bcb13170edb4af9ac4c56f4622fb",
        "16089d3fbb3f0f810b818a5e49836f852d3df58e90b1921ea0d31d5073263226",
        "wheel_exact: true",
        "sdist_content_exact: true",
    ):
        assert text in distribution


def test_documented_skill_hashes_match_repository_bytes() -> None:
    skill_files = {
        "using-kokoroarc/SKILL.md": (
            "c643503c3cab5ffa1d7eddfbf64a1f3650e52aa179f49d47e62ec9400c629ac0"
        ),
        "authoring-character-packs/SKILL.md": (
            "a6318161baab6666a58c465c9f781b04c0bc01203643af1362f13dfef6240c1e"
        ),
        "researching-characters/SKILL.md": (
            "aa08f7e8bb5dd78c2434af0bd8878bb87d0cdbd7bad0fb04cd40aa13149bec21"
        ),
        "testing-character-packs/SKILL.md": (
            "72381d9b0ab71ce988d9313bf0960f8577878369ff969697ead0dfa3a166fedb"
        ),
    }
    validators = _section(EVIDENCE, "Four separate Skill validations")
    for relative, expected in skill_files.items():
        assert sha256((ROOT / "skills" / relative).read_bytes()).hexdigest() == expected
        assert f"`skills/{relative}` | `{expected}`" in validators
    assert validators.count("Skill is valid!") == 4


def test_release_evidence_records_exact_commit_closure_gates() -> None:
    closure = _section(EVIDENCE, "Exact-commit closure gates")
    for text in (
        "6419307e61385de122bb7041f0863c1f0dad338a",
        "48769f4d5d861a4aa98b0011eaa49a8147c1950b",
        "2,580 passed, 29 skipped in 599.06s",
        "cc4f9c5d9698d292f0ca23c44881db48645e506c329f3975408b79f7d485f432",
        "wrapper-only",
        "commands_rerun: 0",
        "2580 passed",
        "8 passed in 9.85s",
        "80 distribution inputs",
        "d6adc0abe91b38df2a9467a05a0dfe3e08b2c8402801ee66358d10601f904e99",
        "94dc843baacedd31b5cd4b4ff96e5f68203ac9d70fe76019b8e9c0e7885b9d1d",
        "86d61d51d9ce9ac446b2b491e256d926f3c20df4c7328ff7d3745d99c9d5cba6",
        "installed_skill_files: 12",
        "Specification review: **PASS**",
        "Quality/security review: **PASS_WITH_MINOR**",
        "README_SOFTBREAK_WORD_SPLIT",
    ):
        assert text in closure


def test_closure_record_marks_only_milestone_8_complete() -> None:
    assert "Milestone 8 complete; Milestone 9 pending" in RESULTS
    assert "Milestone 8 is complete" in EVIDENCE
    assert "Milestone 9 and the complete standalone suite remain pending" in EVIDENCE
    task9 = PLAN[PLAN.index("### Task 9:") : PLAN.index("## Milestone 9")]
    assert "- [x] Commit the settled release record" in task9
    assert "- [x] Mark Milestone 8 complete" in task9


def test_every_distribution_input_is_checkout_stable_lf() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for rule in (
        "README.md text eol=lf",
        "pyproject.toml text eol=lf",
        "src/** text eol=lf",
        "schemas/** text eol=lf",
        "skills/** text eol=lf",
    ):
        assert rule in attributes.splitlines()
