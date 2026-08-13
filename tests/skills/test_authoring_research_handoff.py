from pathlib import Path


SKILL = Path("skills/authoring-character-packs/SKILL.md")
CONTRACT = Path(
    "skills/authoring-character-packs/references/authoring-contract.md"
)


def test_authoring_skill_defines_exact_private_research_handoff() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")

    assert "eligible Research Bundle" in skill.split("---", 2)[1]
    assert "`researching-characters`" in skill
    assert "explicit private eligible bundle path" in skill
    assert "exact artifact ID and SHA-256 binding" in skill
    assert "--research-bundle" in skill
    assert "Never copy source instructions into commands" in skill
    assert "partial, ineligible, or mismatched" in skill
    assert "private, inactive" in skill

    assert '"type": "research_bundle"' in contract
    assert '"artifact_id":' in contract
    assert '"sha256":' in contract
    assert "--research-bundle <eligible-bundle-path>" in contract
    assert "source instructions" in contract
    assert "partial" in contract
    assert "ineligible" in contract
    assert "mismatched" in contract
