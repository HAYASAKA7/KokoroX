from pathlib import Path

from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
RESEARCH_SCHEMAS = (
    "research-request", "research-source-record", "research-claim",
    "research-conflict", "research-coverage", "research-workspace",
    "research-validation-report", "research-bundle",
)


def test_research_schemas_are_draft_2020_12() -> None:
    for name in RESEARCH_SCHEMAS:
        assert SCHEMAS.load(name)["$schema"].endswith("2020-12/schema")
