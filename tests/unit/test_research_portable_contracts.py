from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


ROOT = Path("tests/fixtures/research")
SCHEMA_ROOT = Path("schemas/v1")
SCHEMAS = SchemaRegistry(SCHEMA_ROOT)
RESEARCH_ARTIFACTS = [
    ("research-request", "request.json"),
    ("research-source-record", "sources/source-official-profile.json"),
    ("research-claim", "claims/claim-role.json"),
    ("research-conflict", "conflicts/conflict-adaptation-wording.json"),
    ("research-coverage", "coverage.json"),
    ("research-workspace", "workspace.json"),
    ("research-validation-report", "validation-report.json"),
    ("research-bundle", "bundle.json"),
]
BUNDLE_CONTRACTS = {
    "source": "sources",
    "claim": "claims",
    "conflict": "conflicts",
    "coverage": "coverage",
}
PYTHON_ONLY_REGEX = (r"(?P<", r"(?P=", r"(?i", r"(?m", r"(?s", r"(?x", r"(?#", r"\\A", r"\\Z")


def load_fixture(path: str) -> dict:
    return json.loads((ROOT / "complete" / path).read_text(encoding="utf-8"))


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / f"{name}.schema.json").read_text(encoding="utf-8"))


def invalid(schema_name: str, value: dict) -> None:
    with pytest.raises(KokoroError):
        SCHEMAS.validate(schema_name, value)


@pytest.mark.parametrize(
    "artifact_id",
    [
        ".",
        "..",
        "research/../../escape",
        "research/a/./b",
        "research/a/../escape",
        "research//escape",
        "/research/escape",
        "research/escape/",
        "research/trailing.",
        "research/a./item",
    ],
)
@pytest.mark.parametrize("schema_name,path", RESEARCH_ARTIFACTS)
def test_research_artifact_ids_reject_non_normalized_paths(
    schema_name: str, path: str, artifact_id: str
) -> None:
    artifact = load_fixture(path)
    artifact["artifact_id"] = artifact_id
    invalid(schema_name, artifact)


@pytest.mark.parametrize("artifact_id", ["research/a.b/item_2", "alpha/bravo-charlie/v1.2"])
@pytest.mark.parametrize("schema_name,path", RESEARCH_ARTIFACTS)
def test_research_artifact_ids_accept_normalized_paths_with_internal_dots(
    schema_name: str, path: str, artifact_id: str
) -> None:
    artifact = load_fixture(path)
    artifact["artifact_id"] = artifact_id
    SCHEMAS.validate(schema_name, artifact)


def collect_patterns(value: object) -> list[str]:
    if isinstance(value, dict):
        patterns = [value["pattern"]] if isinstance(value.get("pattern"), str) else []
        return patterns + [pattern for child in value.values() for pattern in collect_patterns(child)]
    if isinstance(value, list):
        return [pattern for child in value for pattern in collect_patterns(child)]
    return []


def all_schema_patterns() -> list[str]:
    return [
        pattern
        for path in sorted(SCHEMA_ROOT.glob("*.schema.json"))
        for pattern in collect_patterns(json.loads(path.read_text(encoding="utf-8")))
    ]


def test_all_schema_patterns_are_ecmascript_portable() -> None:
    patterns = all_schema_patterns()
    forbidden = {token for token in PYTHON_ONLY_REGEX if any(token in pattern for pattern in patterns)}
    assert not forbidden, f"Python-only regex syntax found: {sorted(forbidden)}"

    node = shutil.which("node")
    if node is None:
        pytest.fail("Node is required to verify ECMAScript schema pattern portability")
    probe = "for (const pattern of JSON.parse(require('fs').readFileSync(0, 'utf8'))) new RegExp(pattern);"
    result = subprocess.run([node, "-e", probe], input=json.dumps(patterns), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def normalize_contract(root: dict, contract: dict) -> dict:
    referenced_defs: set[str] = set()

    def normalize(value: object) -> object:
        if isinstance(value, dict):
            normalized = {}
            for key, child in value.items():
                if key == "$ref" and isinstance(child, str) and child.startswith("#/$defs/"):
                    name = child.removeprefix("#/$defs/")
                    referenced_defs.add(name)
                    normalized[key] = f"#/$defs/{name}"
                else:
                    normalized[key] = normalize(child)
            return normalized
        if isinstance(value, list):
            return [normalize(child) for child in value]
        return value

    normalized_contract = normalize(contract)
    definitions = {}
    pending = list(referenced_defs)
    while pending:
        name = pending.pop()
        if name in definitions:
            continue
        definitions[name] = normalize(root["$defs"][name])
        pending.extend(referenced_defs.difference(definitions))
    return {"contract": normalized_contract, "$defs": definitions}


def embedded_contract(bundle: dict, name: str) -> dict:
    value = bundle["properties"][BUNDLE_CONTRACTS[name]]
    return value["items"] if name != "coverage" else value


def standalone_contract(schema: dict) -> dict:
    return {key: value for key, value in schema.items() if key not in {"$schema", "$id", "$defs"}}


def test_embedded_bundle_contracts_match_standalone_schemas() -> None:
    bundle = load_schema("research-bundle")
    for name in BUNDLE_CONTRACTS:
        standalone = load_schema(f"research-{name if name != 'source' else 'source-record'}")
        assert normalize_contract(bundle, embedded_contract(bundle, name)) == normalize_contract(standalone, standalone_contract(standalone))


@pytest.mark.parametrize("side", ["embedded", "standalone"])
def test_embedded_contract_equivalence_detects_meaningful_mutations(side: str) -> None:
    bundle = load_schema("research-bundle")
    standalone = load_schema("research-source-record")
    embedded = embedded_contract(bundle, "source")
    if side == "embedded":
        embedded = deepcopy(embedded)
        embedded["properties"]["title"]["maxLength"] = 513
    else:
        standalone = deepcopy(standalone)
        standalone["properties"]["title"]["maxLength"] = 513
    assert normalize_contract(bundle, embedded) != normalize_contract(standalone, standalone_contract(standalone))
