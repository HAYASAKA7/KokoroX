from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
import string

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
REPOSITORY_LITERAL_CHARACTERS = frozenset(string.ascii_letters + string.digits + "-_/:.,=@#")
REPOSITORY_CLASS_CHARACTERS = REPOSITORY_LITERAL_CHARACTERS - frozenset("-^") | frozenset("+?")
REPOSITORY_OUTSIDE_ESCAPED_LITERALS = frozenset("./+")
REPOSITORY_CLASS_ESCAPED_LITERALS = frozenset("-]\\^")
REPOSITORY_CLASS_SET_ESCAPES = frozenset("sS")



def _subset_error(pattern: str, offset: int, message: str) -> ValueError:
    return ValueError(f"{message} at offset {offset} in {pattern!r}")


def _consume_hex_escape(pattern: str, offset: int) -> tuple[int, int]:
    marker = pattern[offset + 1]
    if marker == "x":
        end = offset + 4
        digits = pattern[offset + 2:end]
        if len(digits) != 2 or any(character not in string.hexdigits for character in digits):
            raise _subset_error(pattern, offset, "invalid hexadecimal escape")
        return end, int(digits, 16)
    if offset + 2 < len(pattern) and pattern[offset + 2] == "{":
        close = pattern.find("}", offset + 3)
        digits = pattern[offset + 3:close] if close >= 0 else ""
        if not (1 <= len(digits) <= 6 and all(character in string.hexdigits for character in digits)):
            raise _subset_error(pattern, offset, "invalid Unicode code-point escape")
        code_point = int(digits, 16)
        if code_point > 0x10FFFF:
            raise _subset_error(pattern, offset, "Unicode code point exceeds U+10FFFF")
        return close + 1, code_point
    end = offset + 6
    digits = pattern[offset + 2:end]
    if len(digits) != 4 or any(character not in string.hexdigits for character in digits):
        raise _subset_error(pattern, offset, "invalid Unicode escape")
    return end, int(digits, 16)


def _consume_escape(pattern: str, offset: int, *, inside_class: bool) -> tuple[int, int | None]:
    if offset + 1 >= len(pattern):
        raise _subset_error(pattern, offset, "trailing escape")
    marker = pattern[offset + 1]
    if marker in "x" or marker == "u":
        return _consume_hex_escape(pattern, offset)
    if marker in "pP":
        raise _subset_error(pattern, offset, "Unicode property escapes are outside the repository subset")
    if inside_class:
        if marker in REPOSITORY_CLASS_SET_ESCAPES:
            return offset + 2, None
        if marker in REPOSITORY_CLASS_ESCAPED_LITERALS:
            return offset + 2, ord(marker)
        raise _subset_error(pattern, offset, "class escape is outside the repository subset")
    if marker in REPOSITORY_OUTSIDE_ESCAPED_LITERALS:
        return offset + 2, ord(marker)
    raise _subset_error(pattern, offset, "escape is outside the repository subset")


def _consume_class_atom(pattern: str, offset: int) -> tuple[int, int | None]:
    character = pattern[offset]
    if character == "\\":
        return _consume_escape(pattern, offset, inside_class=True)
    if character in REPOSITORY_CLASS_CHARACTERS:
        return offset + 1, ord(character)
    raise _subset_error(pattern, offset, "character class contains an unapproved literal")


def _consume_class(pattern: str, offset: int) -> int:
    cursor = offset + 1
    if cursor < len(pattern) and pattern[cursor] == "^":
        cursor += 1
    has_member = False
    while cursor < len(pattern):
        if pattern[cursor] == "]":
            if not has_member:
                raise _subset_error(pattern, offset, "empty character class")
            return cursor + 1
        if pattern[cursor] == "-":
            if cursor + 1 < len(pattern) and pattern[cursor + 1] == "]":
                has_member = True
                cursor += 1
                continue
            raise _subset_error(pattern, cursor, "hyphen must be a supported range or trailing literal")
        cursor, start = _consume_class_atom(pattern, cursor)
        has_member = True
        if cursor < len(pattern) and pattern[cursor] == "-" and cursor + 1 < len(pattern) and pattern[cursor + 1] != "]":
            range_offset = cursor
            cursor += 1
            end_cursor, end = _consume_class_atom(pattern, cursor)
            if start is None or end is None:
                raise _subset_error(pattern, range_offset, "character-class range endpoints must be single code points")
            if start > end:
                raise _subset_error(pattern, range_offset, "character-class range is inverted")
            cursor = end_cursor
    raise _subset_error(pattern, offset, "unterminated character class")


def _consume_braced_quantifier(pattern: str, offset: int) -> int:
    cursor = offset + 1
    lower_start = cursor
    while cursor < len(pattern) and pattern[cursor].isdigit():
        cursor += 1
    if cursor == lower_start:
        raise _subset_error(pattern, offset, "invalid braced quantifier")
    lower = int(pattern[lower_start:cursor])
    if cursor < len(pattern) and pattern[cursor] == "}":
        return cursor + 1
    if cursor >= len(pattern) or pattern[cursor] != ",":
        raise _subset_error(pattern, offset, "invalid braced quantifier")
    cursor += 1
    upper_start = cursor
    while cursor < len(pattern) and pattern[cursor].isdigit():
        cursor += 1
    if cursor >= len(pattern) or pattern[cursor] != "}":
        raise _subset_error(pattern, offset, "invalid braced quantifier")
    if cursor > upper_start and lower > int(pattern[upper_start:cursor]):
        raise _subset_error(pattern, offset, "quantifier range is inverted")
    return cursor + 1


def _consume_quantifier(pattern: str, offset: int, can_quantify: bool) -> int:
    if not can_quantify:
        raise _subset_error(pattern, offset, "quantifier has no preceding atom")
    cursor = _consume_braced_quantifier(pattern, offset) if pattern[offset] == "{" else offset + 1
    if cursor < len(pattern) and pattern[cursor] == "?":
        cursor += 1
    if cursor < len(pattern) and pattern[cursor] in "*+?{":
        raise _subset_error(pattern, cursor, "stacked or possessive quantifier")
    return cursor


def scan_repository_ecmascript_subset(pattern: str) -> None:
    """Accept only the deliberately conservative ECMAScript subset used by repository schemas."""
    cursor = 0
    can_quantify = False
    can_end_alternative = False
    groups: list[bool] = []
    while cursor < len(pattern):
        character = pattern[cursor]
        if character == "\\":
            cursor, _ = _consume_escape(pattern, cursor, inside_class=False)
            can_quantify = True
            can_end_alternative = True
        elif character == "[":
            cursor = _consume_class(pattern, cursor)
            can_quantify = True
            can_end_alternative = True
        elif character == "(":
            if cursor + 1 < len(pattern) and pattern[cursor + 1] == "?":
                opener = pattern[cursor + 1:cursor + 3]
                if opener == "?:":
                    groups.append(True)
                    cursor += 3
                elif opener in {"?=", "?!"}:
                    groups.append(False)
                    cursor += 3
                else:
                    raise _subset_error(pattern, cursor, "group extension is outside the repository ECMAScript subset")
            else:
                groups.append(True)
                cursor += 1
            can_quantify = False
            can_end_alternative = False
        elif character == ")":
            if not groups:
                raise _subset_error(pattern, cursor, "unmatched closing group")
            can_quantify = groups.pop()
            can_end_alternative = can_quantify
            cursor += 1
        elif character in "*+?{":
            cursor = _consume_quantifier(pattern, cursor, can_quantify)
            can_quantify = False
            can_end_alternative = True
        elif character == "|":
            if not can_end_alternative:
                raise _subset_error(pattern, cursor, "alternative has no preceding atom")
            cursor += 1
            can_quantify = False
            can_end_alternative = False
        elif character in "^$":
            cursor += 1
            can_quantify = False
            can_end_alternative = True
        elif character == ".":
            cursor += 1
            can_quantify = True
            can_end_alternative = True
        elif character in REPOSITORY_LITERAL_CHARACTERS:
            cursor += 1
            can_quantify = True
            can_end_alternative = True
        else:
            raise _subset_error(pattern, cursor, "literal is outside the repository ECMAScript subset")
    if groups:
        raise _subset_error(pattern, len(pattern), "unterminated group")



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


def assert_ecmascript_subset(patterns: list[str]) -> None:
    assert patterns, "expected at least one schema pattern"
    for pattern in patterns:
        try:
            scan_repository_ecmascript_subset(pattern)
        except ValueError as error:
            raise AssertionError(
                "schema patterns use syntax outside the approved ECMAScript subset: "
                f"{error}"
            ) from None


def confirm_node_patterns(patterns: list[str]) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; static ECMAScript subset validation remains active")
    probe = "for (const pattern of JSON.parse(require('fs').readFileSync(0, 'utf8'))) new RegExp(pattern, 'u');"
    result = subprocess.run([node, "-e", probe], input=json.dumps(patterns), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_all_schema_patterns_stay_within_the_ecmascript_subset() -> None:
    assert_ecmascript_subset(all_schema_patterns())


def test_node_confirms_all_schema_patterns_when_available() -> None:
    confirm_node_patterns(all_schema_patterns())


PYTHON_EXTENSION_MUTATIONS = [
    r"(?i:alpha)",
    r"(?-i:alpha)",
    r"(?im:alpha)",
    r"(?>alpha)",
    r"alpha*+",
    r"alpha++",
    r"alpha?+",
    r"alpha{1,2}+",
    r"alpha**",
    r"alpha?*",
    r"alpha{1,2}??",
    r"(?P<name>alpha)",
    r"(?P=name)",
    r"(?# Python comment)alpha",
    r"(?(1)alpha|beta)",
    r"(?|alpha|beta)",
    r"(?R)",
    r"(?1)",
    r"\Aalpha\Z",
    r"\N{LATIN SMALL LETTER A}",
    r"\u{110000}",
]


@pytest.mark.parametrize("pattern", PYTHON_EXTENSION_MUTATIONS)
def test_static_ecmascript_subset_rejects_python_only_syntax(pattern: str) -> None:
    with pytest.raises(AssertionError, match="outside the approved ECMAScript subset"):
        assert_ecmascript_subset([pattern])


@pytest.mark.parametrize("pattern", [r"(?>alpha)", r"alpha++", r"(?-i:alpha)"])
def test_reported_extensions_compile_in_python_and_fail_node_unicode(pattern: str) -> None:
    re.compile(pattern)
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable for the reported-extension confirmation")
    result = subprocess.run(
        [node, "-e", "new RegExp(process.argv[1], 'u');", pattern],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0, "Node accepted a reported Python-only extension"


CLASS_ESCAPE_MUTATIONS = [
    r"[z-a]",
    r"[\B]",
    r"\p{NotAProperty}",
    r"\-",
    r"[a-\s]",
    r"[a-b-c]",
    r"[-a]",
    r"[\A]",
    r"[\p{ASCII}]",
    r"\P{ASCII}",
]


@pytest.mark.parametrize("pattern", CLASS_ESCAPE_MUTATIONS)
def test_static_ecmascript_subset_rejects_invalid_classes_and_escapes(pattern: str) -> None:
    with pytest.raises(AssertionError, match="outside the approved ECMAScript subset"):
        assert_ecmascript_subset([pattern])


NODE_U_REJECTED_CLASS_ESCAPE_MUTATIONS = [
    r"[z-a]", r"[\B]", r"\p{NotAProperty}", r"\-", r"[a-\s]", r"[a-", r"[\A]"
]


@pytest.mark.parametrize("pattern", NODE_U_REJECTED_CLASS_ESCAPE_MUTATIONS)
def test_invalid_class_and_escape_mutations_fail_node_unicode(pattern: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable for the class and escape confirmation")
    result = subprocess.run(
        [node, "-e", "new RegExp(process.argv[1], 'u');", pattern],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0, "Node accepted an invalid class or escape mutation"


@pytest.mark.parametrize("pattern", [r"\p{ASCII}", r"\P{ASCII}", r"[-a]", r"[a-b-c]"])
def test_repository_subset_rejects_node_valid_class_and_property_forms(pattern: str) -> None:
    with pytest.raises(AssertionError, match="outside the approved ECMAScript subset"):
        assert_ecmascript_subset([pattern])
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable for the property-subset confirmation")
    result = subprocess.run(
        [node, "-e", "new RegExp(process.argv[1], 'u');", pattern],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "pattern",
    [r"[A-Za-z0-9.-]", r"[0-9a-f]", r"[^\s]", r"[\s\S]", r"[+-]", r"[A-Za-z-]"],
)
def test_static_ecmascript_subset_accepts_current_class_controls(pattern: str) -> None:
    assert_ecmascript_subset([pattern])


def test_portability_static_gate_remains_meaningful_without_node(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda executable: None)
    assert_ecmascript_subset(all_schema_patterns())
    with pytest.raises(pytest.skip.Exception, match="Node is unavailable"):
        confirm_node_patterns(all_schema_patterns())


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
