from copy import deepcopy
import json
from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


ROOT = Path("tests/fixtures/research")
SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def load(tree: str, path: str) -> dict:
    return json.loads((ROOT / tree / path).read_text(encoding="utf-8"))


def invalid(name: str, artifact: dict) -> None:
    with pytest.raises(KokoroError):
        SCHEMAS.validate(name, artifact)


@pytest.mark.parametrize("character_id", ["con", "AUX", "com1", "LPT9", "con.txt"])
def test_request_rejects_windows_device_character_ids(character_id: str) -> None:
    request = load("complete", "request.json")
    request["character_id"] = character_id
    invalid("research-request", request)


def test_request_allows_benign_device_substrings() -> None:
    request = load("complete", "request.json")
    request["character_id"] = "context-conductor"
    SCHEMAS.validate("research-request", request)


@pytest.mark.parametrize("name,path", [
    ("research-request", "request.json"), ("research-source-record", "sources/source-official-profile.json"),
    ("research-claim", "claims/claim-role.json"), ("research-conflict", "conflicts/conflict-adaptation-wording.json"),
    ("research-coverage", "coverage.json"), ("research-workspace", "workspace.json"),
    ("research-validation-report", "validation-report.json"), ("research-bundle", "bundle.json"),
])
@pytest.mark.parametrize("artifact_id", ["con.txt", "research/con.txt/item", "research/AUX/item", "com1.json"])
def test_every_research_artifact_rejects_reserved_artifact_id(name: str, path: str, artifact_id: str) -> None:
    artifact = load("complete", path)
    artifact["artifact_id"] = artifact_id
    invalid(name, artifact)


def test_complete_scope_separation_binds_incompatible_same_topic_claims() -> None:
    claims = {path.stem: load("complete", f"claims/{path.name}") for path in (ROOT / "complete" / "claims").glob("*.json")}
    conflict = load("complete", "conflicts/conflict-adaptation-wording.json")
    referenced = [next(claim for claim in claims.values() if claim["claim_id"] == claim_id) for claim_id in conflict["claim_ids"]]
    assert len({claim["subject_id"] for claim in referenced}) == 1
    assert len({claim["timeline"] for claim in referenced}) >= 2
    statements = {claim["statement"] for claim in referenced}
    assert any("observatory apprentice" in statement for statement in statements)
    assert any("not an observatory apprentice" in statement for statement in statements)
