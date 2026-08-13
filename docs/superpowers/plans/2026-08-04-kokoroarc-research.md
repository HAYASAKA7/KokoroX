# KokoroArc Character Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a host-tool-agnostic `researching-characters` workflow that compiles deterministic, private, inactive Research Bundles and safely unlocks researched or hybrid authoring.

**Architecture:** Host agents acquire evidence and write closed research artifacts; the KokoroArc core performs offline schema validation, cross-artifact verification, deterministic compilation, and confined atomic publication. Research artifacts remain separate from Character Packs and runtime memory. Authoring receives a trusted bundle path as a CLI argument and binds it to the artifact ID and SHA-256 stored in the Character Build Request.

**Tech Stack:** Python 3.11+, JSON Schema Draft 2020-12, `jsonschema`, `pytest`, PowerShell 7 release harnesses, Codex Agent Skills, canonical UTF-8 JSON and SHA-256.

**Design:** `docs/superpowers/specs/2026-08-04-kokoroarc-research-design.md`

**Execution discipline:** Every task uses RED-GREEN-REFACTOR, commits only its declared scope, then receives a fresh specification review followed by a fresh quality review. Fix every Critical or Important review finding with a new failing regression test before advancing. Use unique `D:\tmp` roots for operational evidence and do not claim Milestones 8-9 or the complete suite.

---

## File map

New core files:

- `src/kokoroarc/research/__init__.py`: public research API exports.
- `src/kokoroarc/research/requests.py`: Research Request normalization.
- `src/kokoroarc/research/workspace.py`: safe explicit-manifest loading, file identity, and canonical workspace assembly.
- `src/kokoroarc/research/validation.py`: cross-artifact claim, conflict, coverage, continuity, and spoiler validation.
- `src/kokoroarc/research/bundles.py`: deterministic Research Bundle metadata and hashes.
- `src/kokoroarc/research/storage.py`: confined atomic bundle publication.

New schemas:

- `schemas/v1/research-request.schema.json`
- `schemas/v1/research-source-record.schema.json`
- `schemas/v1/research-claim.schema.json`
- `schemas/v1/research-conflict.schema.json`
- `schemas/v1/research-coverage.schema.json`
- `schemas/v1/research-workspace.schema.json`
- `schemas/v1/research-validation-report.schema.json`
- `schemas/v1/research-bundle.schema.json`

New fixtures and tests:

- `tests/fixtures/research/complete/`: complete eligible workspace.
- `tests/fixtures/research/partial/`: structurally valid but authoring-blocked workspace.
- `tests/fixtures/research/injection/`: inert malicious-source workspace.
- `tests/unit/test_research_schemas.py`
- `tests/unit/test_research_requests.py`
- `tests/unit/test_research_workspace.py`
- `tests/unit/test_research_validation.py`
- `tests/unit/test_research_bundles.py`
- `tests/integration/test_research_storage.py`
- `tests/integration/test_research_cli.py`
- `tests/integration/test_researched_authoring.py`
- `tests/security/test_research_security.py`

Skill and release files:

- `skills/researching-characters/SKILL.md`
- `skills/researching-characters/agents/openai.yaml`
- `skills/researching-characters/references/research-contract.md`
- `tests/skills/researching-characters-cases.yaml`
- `tests/skills/researching-characters-baseline.md`
- `tests/skills/researching-characters-results.md`
- `tests/skills/test_researching_characters_evidence.py`
- `tests/skills/research-release-verification.md`
- `tests/skills/test_research_release_evidence.py`

Modified integration files:

- `src/kokoroarc/cli.py`
- `src/kokoroarc/authoring/requests.py`
- `src/kokoroarc/authoring/validation.py`
- `schemas/v1/character-build-request.schema.json`
- `README.md`
- `docs/superpowers/plans/2026-08-04-kokoroarc-research.md`

---

### Task 1: Define closed research schemas and representative fixtures

**Files:**
- Create: `schemas/v1/research-request.schema.json`
- Create: `schemas/v1/research-source-record.schema.json`
- Create: `schemas/v1/research-claim.schema.json`
- Create: `schemas/v1/research-conflict.schema.json`
- Create: `schemas/v1/research-coverage.schema.json`
- Create: `schemas/v1/research-workspace.schema.json`
- Create: `schemas/v1/research-validation-report.schema.json`
- Create: `schemas/v1/research-bundle.schema.json`
- Create: `tests/fixtures/research/complete/request.json`
- Create: `tests/fixtures/research/complete/workspace.json`
- Create: `tests/fixtures/research/complete/sources/source-official-profile.json`
- Create: `tests/fixtures/research/complete/sources/source-episode-01.json`
- Create: `tests/fixtures/research/complete/claims/claim-role.json`
- Create: `tests/fixtures/research/complete/claims/claim-behavior.json`
- Create: `tests/fixtures/research/complete/conflicts/conflict-adaptation-wording.json`
- Create: `tests/fixtures/research/complete/coverage.json`
- Create: `tests/fixtures/research/partial/**`
- Create: `tests/fixtures/research/injection/**`
- Create: `tests/unit/test_research_schemas.py`

- [ ] **Step 1: Write the failing schema-load test**

```python
RESEARCH_SCHEMAS = (
    "research-request",
    "research-source-record",
    "research-claim",
    "research-conflict",
    "research-coverage",
    "research-workspace",
    "research-validation-report",
    "research-bundle",
)


def test_research_schemas_are_draft_2020_12() -> None:
    for name in RESEARCH_SCHEMAS:
        assert SCHEMAS.load(name)["$schema"].endswith("2020-12/schema")
```

- [ ] **Step 2: Run the test and record RED**

Run:

```powershell
python -m pytest tests/unit/test_research_schemas.py -v
```

Expected: FAIL with `SCHEMA_NOT_FOUND` for `research-request`.

- [ ] **Step 3: Add common closed identifiers and lifecycle constraints to every schema**

Use `additionalProperties: false`, Draft 2020-12, `schema_version: "1.0"`, the existing `created_by` contract, bounded strings and arrays, Windows-reserved-name rejection for path identities, and SHA-256 patterns of `^[0-9a-f]{64}$`. The Research Bundle lifecycle must be exactly:

```json
{
  "build_status": "research",
  "visibility": "private",
  "activation_allowed": false,
  "authoring_allowed": true
}
```

`authoring_allowed` is a boolean gate, not a fixed `true`; the other three fields use `const`.

- [ ] **Step 4: Encode the exact artifact relationships**

The request requires subject identity, franchise, aliases, medium, work, adaptation, continuity, timeline cutoff, spoiler scope, ordered questions, coverage topics, user assertions, constraints, and `requested_visibility: private`.

Source records require `source_id`, category, HTTPS or `kokoro-evidence` locator, title, publisher, host-supplied RFC 3339 access time, availability, content SHA-256, bounded excerpts, continuity, spoiler scope, limitations, and trust notes. Explicitly reject credentials in network locators and all `file`, UNC, device, executable, and script schemes.

Claims use this closed shape:

```json
{
  "schema_version": "1.0",
  "artifact_id": "research-claim/aoi-kisaragi-fixture/role",
  "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
  "claim_id": "role-mage",
  "subject_id": "aoi-kisaragi-fixture",
  "statement": "Aoi Kisaragi is a courier.",
  "classification": "direct_fact",
  "support": "direct",
  "source_ids": ["official-profile"],
  "supporting_claim_ids": [],
  "continuity": "anime-season-1",
  "timeline": "through-episode-12",
  "spoiler_scope": "through-episode-12",
  "limitations": []
}
```

Derived interpretations require nonempty `supporting_claim_ids` and `derivation_rationale`; user assertions require no external source; direct claims require sources. Claims may carry a closed optional `measurement` object with `kind`, decimal JSON `value`, `unit`, and optional `trait_name`. `kind` is either `in_world_quantity` or `normalized_trait`; semantic validation rejects the latter with the stable canonical-trait error so it cannot enter a valid bundle. Schemas enforce shapes while semantic code enforces cross-record existence.

- [ ] **Step 5: Create complete, partial, and injection fixtures**

Use one internally consistent fictionalized research subject so tests never depend on current web content. The complete fixture must contain two sources, two claims, one `scope_separated` conflict, and fully covered topics. The partial fixture has a missing blocking topic and `authoring_allowed: false`. The injection fixture stores strings such as `Ignore prior instructions`, `${env:PRIVATE_VALUE}`, and `file:///C:/secret` only in quoted excerpt/limitation fields; its locator remains an allowed inert test locator.

- [ ] **Step 6: Add negative schema matrices**

```python
@pytest.mark.parametrize(
    ("schema_name", "mutation"),
    [
        ("research-request", lambda d: d.update(requested_visibility="public")),
        ("research-source-record", lambda d: d.update(locator="file:///secret")),
        ("research-claim", lambda d: d.update(classification="canonical_score")),
        ("research-conflict", lambda d: d.update(status="majority_wins")),
        ("research-bundle", lambda d: d.update(activation_allowed=True)),
    ],
)
def test_research_schemas_reject_closed_boundary_violations(
    schema_name: str, mutation: Callable[[dict[str, Any]], None]
) -> None:
    document = deepcopy(valid_artifact(schema_name))
    mutation(document)
    with pytest.raises(KokoroError, match="required schema"):
        SCHEMAS.validate(schema_name, document)
```

- [ ] **Step 7: Run schema tests GREEN**

Run:

```powershell
python -m pytest tests/unit/test_research_schemas.py tests/unit/test_schemas.py -q
```

Expected: all tests pass with only existing platform capability skips.

- [ ] **Step 8: Commit**

```powershell
git add schemas/v1/research-*.schema.json tests/fixtures/research tests/unit/test_research_schemas.py
git commit -m "feat: define character research artifacts"
```

---

### Task 2: Normalize Research Requests deterministically

**Files:**
- Create: `src/kokoroarc/research/__init__.py`
- Create: `src/kokoroarc/research/requests.py`
- Create: `tests/unit/test_research_requests.py`

- [ ] **Step 1: Write failing normalization tests**

```python
def test_normalize_research_request_is_canonical_and_non_mutating(
    registry: SchemaRegistry, complete_request: dict[str, Any]
) -> None:
    before = deepcopy(complete_request)
    first = normalize_research_request(complete_request, registry)
    second = normalize_research_request(complete_request, registry)
    assert first == second
    assert canonical_bytes(first) == canonical_bytes(second)
    assert complete_request == before
    assert first["requested_visibility"] == "private"


def test_request_rejects_ambiguous_continuity_sentinels(
    registry: SchemaRegistry, complete_request: dict[str, Any]
) -> None:
    complete_request["continuity"] = "unknown"
    with pytest.raises(KokoroError) as raised:
        normalize_research_request(complete_request, registry)
    assert raised.value.code == "RESEARCH_CONTINUITY_UNRESOLVED"
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/unit/test_research_requests.py -v`

Expected: FAIL because `kokoroarc.research.requests` does not exist.

- [ ] **Step 3: Implement the public normalizer**

```python
_UNRESOLVED = frozenset({"unknown", "unspecified", "ambiguous", "mixed"})


def normalize_research_request(
    value: dict[str, Any], schemas: SchemaRegistry
) -> dict[str, Any]:
    normalized_value = json.loads(canonical_bytes(value))
    if isinstance(normalized_value, dict):
        normalized_value.setdefault("requested_visibility", "private")
    schemas.validate("research-request", normalized_value)
    normalized = cast(dict[str, Any], normalized_value)
    for field in ("medium", "work", "adaptation", "continuity", "timeline_cutoff"):
        if normalized[field].strip().casefold() in _UNRESOLVED:
            raise KokoroError(
                "RESEARCH_CONTINUITY_UNRESOLVED",
                "Research identity and continuity must be resolved before collection.",
                details={"field": field},
            )
    return normalized
```

Do not add timestamps, sort user-ordered questions, mutate inputs, or accept an inferred latest adaptation.

- [ ] **Step 4: Add Unicode, duplicate-key, bounds, and no-payload-leak tests**

Test canonical Unicode preservation, exact user assertion retention, all unresolved sentinels, explicit `not_applicable`, maximum counts, unknown fields, and that exception messages/details never contain assertion or source text.

- [ ] **Step 5: Run GREEN**

Run:

```powershell
python -m pytest tests/unit/test_research_requests.py tests/unit/test_research_schemas.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add src/kokoroarc/research tests/unit/test_research_requests.py
git commit -m "feat: normalize character research requests"
```

---

### Task 3: Load explicit research workspaces safely

**Files:**
- Create: `src/kokoroarc/research/workspace.py`
- Create: `tests/unit/test_research_workspace.py`
- Create: `tests/security/test_research_security.py`

- [ ] **Step 1: Write the failing complete-workspace load test**

```python
def test_load_research_workspace_returns_canonical_assembled_artifacts(
    registry: SchemaRegistry,
) -> None:
    loaded = load_research_workspace(
        Path("tests/fixtures/research/complete"), registry
    )
    assert loaded.request["character_id"] == "aoi-kisaragi-fixture"
    assert [item["source_id"] for item in loaded.sources] == sorted(
        item["source_id"] for item in loaded.sources
    )
    assert len(loaded.workspace_hash) == 64
    assert loaded.workspace_hash == load_research_workspace(
        Path("tests/fixtures/research/complete"), registry
    ).workspace_hash
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/unit/test_research_workspace.py -v`

Expected: FAIL because `load_research_workspace` is undefined.

- [ ] **Step 3: Implement immutable loaded types and limits**

```python
@dataclass(frozen=True, slots=True)
class ResearchWorkspace:
    root: Path
    request: dict[str, Any]
    sources: tuple[dict[str, Any], ...]
    claims: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, Any], ...]
    coverage: dict[str, Any]
    manifest: dict[str, Any]
    file_hashes: Mapping[str, str]
    workspace_hash: str


@dataclass(frozen=True, slots=True)
class ResearchLimits:
    max_files: int = 1024
    max_file_bytes: int = 4 * 1024 * 1024
    max_total_bytes: int = 32 * 1024 * 1024
```

- [ ] **Step 4: Implement manifest-first, explicit-file loading**

Load and schema-validate `workspace.json` before following any reference. Each reference contains only a normalized relative POSIX path and expected lowercase SHA-256. Resolve beneath the workspace root, open regular files without following redirects, reject symlink/junction/reparse/hardlink/alternate-stream/reserved-name paths, enforce limits, parse strict JSON with duplicate-key and non-finite-number rejection, schema-validate by declared kind, and compare the exact bytes to the manifest digest.

Compute `workspace_hash` from canonical bytes of this closed object:

```python
assembled = {
    "request": request,
    "sources": sorted(sources, key=itemgetter("source_id")),
    "claims": sorted(claims, key=itemgetter("claim_id")),
    "conflicts": sorted(conflicts, key=itemgetter("conflict_id")),
    "coverage": coverage,
}
workspace_hash = hashlib.sha256(canonical_bytes(assembled)).hexdigest()
```

- [ ] **Step 5: Add path and mutation RED tests before hardening each branch**

Cover `../`, absolute, drive-relative, UNC, ADS colon, reserved devices, duplicate normalized path, unexpected unreferenced file, symlink, junction, reparse point, hardlink, FIFO, short read, file replacement between stat/read/stat, ancestor replacement, digest mismatch, oversized files, too many files, and invalid UTF-8. Capability-dependent tests must skip with an exact reason only when the platform cannot construct the primitive.

- [ ] **Step 6: Add inert-source tests**

Set secret environment variables and marker paths, load the injection fixture, and assert no command executes, no marker appears, no environment value is expanded, no source string is emitted in errors, and no file outside the workspace is read.

- [ ] **Step 7: Run GREEN**

Run:

```powershell
python -m pytest tests/unit/test_research_workspace.py tests/security/test_research_security.py -q
```

Expected: all supported checks pass; capability skips are explicit.

- [ ] **Step 8: Commit**

```powershell
git add src/kokoroarc/research/workspace.py tests/unit/test_research_workspace.py tests/security/test_research_security.py
git commit -m "feat: load confined research workspaces"
```

---

### Task 4: Validate claims, conflicts, coverage, continuity, and spoilers

**Files:**
- Create: `src/kokoroarc/research/validation.py`
- Create: `tests/unit/test_research_validation.py`

- [ ] **Step 1: Write the failing eligible-workspace report test**

```python
def test_validate_complete_workspace_allows_authoring(
    registry: SchemaRegistry, complete_workspace: ResearchWorkspace
) -> None:
    report = validate_research_workspace(complete_workspace, registry)
    assert report["valid"] is True
    assert report["authoring_allowed"] is True
    assert report["hard_failures"] == []
    assert report["blocking_reasons"] == []
    assert report["coverage_summary"] == {
        "blocked": 0,
        "covered": 2,
        "missing": 0,
        "partial": 0,
    }
    registry.validate("research-validation-report", report)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/unit/test_research_validation.py -v`

Expected: FAIL because the validator does not exist.

- [ ] **Step 3: Implement deterministic findings**

```python
def _finding(code: str, path: list[str | int], message: str) -> dict[str, Any]:
    return {"code": code, "path": path, "message": message}


def _finding_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(item["code"]),
        json.dumps(item["path"], ensure_ascii=False, separators=(",", ":")),
        str(item["message"]),
    )
```

The report must be input-non-mutating, bounded to 256 hard findings and 256 advisories, sorted with `_finding_key`, schema-valid, and byte-stable.

- [ ] **Step 4: Implement cross-artifact invariants**

Validate unique IDs; every reference; acyclic derived-claim graphs; subject, franchise, adaptation, continuity, timeline, and spoiler containment; direct-source requirements; derived rationale; user-assertion separation; conflict status/rationale; complete coverage accounting; unavailable-source limitations; and authoring-blocking topics.

Use these stable hard codes:

```text
RESEARCH_IDENTITY_MISMATCH
RESEARCH_CONTINUITY_MISMATCH
RESEARCH_TIMELINE_VIOLATION
RESEARCH_SPOILER_SCOPE_VIOLATION
RESEARCH_DUPLICATE_ID
RESEARCH_DANGLING_REFERENCE
RESEARCH_CIRCULAR_DERIVATION
RESEARCH_SOURCE_SUPPORT_REQUIRED
RESEARCH_DERIVATION_REQUIRED
RESEARCH_USER_ASSERTION_RELABELLED
RESEARCH_CANONICAL_TRAIT_SCORE_PROHIBITED
RESEARCH_CONFLICT_BLOCKING
RESEARCH_COVERAGE_INCOMPLETE
```

- [ ] **Step 5: Prohibit canonical normalized traits**

Reject claims whose classification or statement/rationale asserts a normalized personality, morality, relationship, or behavior score as canon. Do not reject explicit sourced in-world quantities. Tests must distinguish `"She waited 10 years"` from `"patience: 0.9 is canonical"` without relying on an unrestricted keyword substring; use closed structured fields `measurement_kind` and `normalized_trait_name`, allowed only for derived authoring artifacts, not research claims.

- [ ] **Step 6: Add complete negative matrix and partial behavior**

For each stable code, write one focused failing test, then implement the minimum branch. Assert the partial fixture is structurally `valid: true` but `authoring_allowed: false`, retains its missing coverage and unavailable source, and has exact sorted blocking reasons.

- [ ] **Step 7: Run GREEN**

Run:

```powershell
python -m pytest tests/unit/test_research_validation.py tests/unit/test_research_workspace.py -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add src/kokoroarc/research/validation.py tests/unit/test_research_validation.py
git commit -m "feat: validate research evidence graphs"
```

---

### Task 5: Build deterministic Research Bundles

**Files:**
- Create: `src/kokoroarc/research/bundles.py`
- Create: `tests/unit/test_research_bundles.py`
- Modify: `src/kokoroarc/research/__init__.py`

- [ ] **Step 1: Write the failing deterministic bundle test**

```python
def test_build_research_bundle_is_byte_stable_and_non_mutating(
    complete_workspace: ResearchWorkspace,
    complete_report: dict[str, Any],
) -> None:
    before = deepcopy(complete_report)
    first = build_research_bundle(complete_workspace, complete_report)
    second = build_research_bundle(complete_workspace, complete_report)
    assert canonical_bytes(first) == canonical_bytes(second)
    assert first["build_status"] == "research"
    assert first["visibility"] == "private"
    assert first["activation_allowed"] is False
    assert first["authoring_allowed"] is True
    assert first["workspace_hash"] == complete_workspace.workspace_hash
    assert complete_report == before
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/unit/test_research_bundles.py -v`

Expected: FAIL because `build_research_bundle` is undefined.

- [ ] **Step 3: Implement canonical hashes and identifiers**

```python
def canonical_hash(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def build_research_bundle(
    workspace: ResearchWorkspace,
    report: dict[str, Any],
) -> dict[str, Any]:
    request_hash = canonical_hash(workspace.request)
    report_hash = canonical_hash(report)
    suffix = workspace.workspace_hash[:16]
    artifact_id = (
        f"{workspace.request['namespace']}/"
        f"{workspace.request['character_id']}/research/{suffix}"
    )
    bundle = {
        "schema_version": "1.0",
        "artifact_id": artifact_id,
        "created_by": {"component": "kokoroarc", "version": __version__},
        "namespace": workspace.request["namespace"],
        "character_id": workspace.request["character_id"],
        "display_name": workspace.request["display_name"],
        "continuity": workspace.request["continuity"],
        "timeline_cutoff": workspace.request["timeline_cutoff"],
        "spoiler_scope": workspace.request["spoiler_scope"],
        "request_hash": request_hash,
        "workspace_hash": workspace.workspace_hash,
        "validation_report_hash": report_hash,
        "sources": list(workspace.sources),
        "claims": list(workspace.claims),
        "conflicts": list(workspace.conflicts),
        "coverage": workspace.coverage,
        "limitations": aggregate_limitations(workspace),
        "blocking_reasons": list(report["blocking_reasons"]),
        "build_status": "research",
        "visibility": "private",
        "activation_allowed": False,
        "authoring_allowed": report["authoring_allowed"],
    }
    bundle["bundle_hash"] = canonical_hash(bundle)
    return bundle
```

If the artifact ID would exceed the schema bound, use `"research/" + sha256(identity_bytes).hexdigest()` rather than truncating identity fields unpredictably.

`bundle_hash` is SHA-256 over canonical bundle bytes before the `bundle_hash` member is added. Validation removes that one member, recomputes the digest, and requires exact equality.

- [ ] **Step 4: Test order independence and meaningful-order preservation**

Shuffle manifest source/claim/conflict references and prove the bundle is unchanged. Reorder the Research Request questions and prove the request and bundle hashes change because question order is intentional.

- [ ] **Step 5: Test partial bundles and mutation resistance**

Assert a safe partial workspace produces `authoring_allowed: false` with retained conflicts, limitations, and coverage. Mutating the returned bundle must not mutate the workspace or report.

- [ ] **Step 6: Run GREEN**

Run:

```powershell
python -m pytest tests/unit/test_research_bundles.py tests/unit/test_research_validation.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add src/kokoroarc/research/bundles.py src/kokoroarc/research/__init__.py tests/unit/test_research_bundles.py
git commit -m "feat: build deterministic research bundles"
```

---

### Task 6: Publish Research Bundles atomically and safely

**Files:**
- Create: `src/kokoroarc/research/storage.py`
- Create: `tests/integration/test_research_storage.py`
- Extend: `tests/security/test_research_security.py`

- [ ] **Step 1: Write the failing publication test**

```python
def test_publish_research_bundle_is_confined_complete_and_repeatable(
    tmp_path: Path,
    complete_workspace_path: Path,
    complete_workspace: ResearchWorkspace,
    complete_report: dict[str, Any],
    complete_bundle: dict[str, Any],
) -> None:
    data_root = tmp_path / "data"
    first = publish_research_bundle(
        data_root, complete_workspace_path, complete_workspace,
        complete_report, complete_bundle,
    )
    second = publish_research_bundle(
        data_root, complete_workspace_path, complete_workspace,
        complete_report, complete_bundle,
    )
    assert first == second
    assert first.is_relative_to((data_root / "research").resolve())
    assert sorted(path.name for path in first.iterdir()) == [
        "bundle.json", "request.json", "validation-report.json", "workspace.json",
    ]
    assert not any((data_root / name).exists() for name in PROTECTED_ROOTS)
```

`PROTECTED_ROOTS` is `("drafts", "compiled", "installed", "public", "sessions", "state", "events", "workspaces", "config")`.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/integration/test_research_storage.py -v`

Expected: FAIL because `publish_research_bundle` is undefined.

- [ ] **Step 3: Implement the public publication boundary**

```python
def publish_research_bundle(
    data_root: Path,
    source_root: Path,
    workspace: ResearchWorkspace,
    report: dict[str, Any],
    bundle: dict[str, Any],
) -> Path:
    schemas = SchemaRegistry(resolve_schema_dir())
    schemas.validate("research-request", workspace.request)
    schemas.validate("research-validation-report", report)
    schemas.validate("research-bundle", bundle)
    require_bundle_inputs(workspace, report, bundle)
    root = absolute_without_resolution(data_root)
    final = root / "research" / Path(*bundle["artifact_id"].split("/"))
    validate_existing_chain(root)
    create_secure_directories(final.parent)
    with acquire_publication_lock(final) as lock:
        return publish_locked(source_root, workspace, report, bundle, final, lock)
```

Do not import mutable private state from `authoring.storage`. Extract narrowly reusable destination-validation, fsync, locking, and bounded-cutover primitives into `src/kokoroarc/publication.py` only if Task 6 tests prove existing authoring behavior remains unchanged. Otherwise keep a focused research publisher.

- [ ] **Step 4: Generate canonical staging files**

Write exactly one-LF canonical JSON for the normalized request, closed workspace summary, validation report, and bundle. Before cutover, reload each staged file, schema-validate it, recompute hashes, and compare the validated source workspace to copied/assembled identities. The bundle directory must not contain raw webpage bodies or unreferenced workspace files.

Implement `load_published_research_bundle(path, schemas)` in this task. It accepts only an explicit host path, validates a safe regular `bundle.json`, rejects redirects/hardlinks/mutation, validates `research-bundle`, recomputes `bundle_hash`, and verifies the sibling request/report/workspace hashes. Task 7 uses it for `research bundle validate`; Task 8 uses it for the trusted authoring handoff.

- [ ] **Step 5: Implement same-parent bounded cutover and recovery**

Use a same-parent staging directory and backup name derived from sanitized artifact identity. Lock per final target. Reject unsafe final components before stale-backup cleanup. Fsync staged files/directories and the parent where supported. On replacement failure, restore the previous complete directory; if rollback cannot restore it, retain and report the same-parent recovery directory. Never report failure after deleting the sole previous complete bundle.

- [ ] **Step 6: Add RED tests for every failure window**

Monkeypatch staging creation, write, staged fsync, first rename, second rename, rollback, parent fsync, cleanup, and stale-backup reap. Add concurrent same-target and different-target tests. Assert bounded retries, deterministic error codes, previous-bundle preservation, no cross-target blocking, no orphan staging on recoverable failure, and exact retained recovery paths only when needed.

- [ ] **Step 7: Add destination and source attack tests**

Cover destination symlink/junction/reparse ancestors, final redirects, lock replacement, stale-backup redirects, source workspace mutation before and during staging, source hash mismatch, hardlinks, and cleanup races. Reuse platform capability helpers from authoring security tests without weakening skip conditions.

- [ ] **Step 8: Run storage and authoring regression GREEN**

Run:

```powershell
python -m pytest tests/integration/test_research_storage.py tests/security/test_research_security.py tests/integration/test_authoring_storage.py tests/security/test_authoring_security.py -q
```

Expected: all supported tests pass; existing authoring behavior is unchanged.

- [ ] **Step 9: Commit**

```powershell
git add src/kokoroarc/research/storage.py tests/integration/test_research_storage.py tests/security/test_research_security.py
git commit -m "feat: publish private research bundles"
```

Stage a shared `src/kokoroarc/publication.py` and changes to `src/kokoroarc/authoring/storage.py` only if the tested extraction was necessary.

---

### Task 7: Expose deterministic research CLI commands

**Files:**
- Modify: `src/kokoroarc/cli.py`
- Create: `tests/integration/test_research_cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Write parser and request-validation RED tests**

```python
def test_research_request_validate_is_stateless_and_deterministic() -> None:
    arguments = [
        "research", "request", "validate",
        "--input", "tests/fixtures/research/complete/request.json", "--json",
    ]
    first = _cli(arguments)
    second = _cli(arguments)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["request"]["requested_visibility"] == "private"
    assert first.stderr == second.stderr == ""
```

Also add parser tests for workspace validate, bundle compile, and bundle validate.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/integration/test_research_cli.py tests/unit/test_cli.py -q`

Expected: FAIL with `ARGUMENT_INVALID` because `research` is unknown.

- [ ] **Step 3: Add the exact parser surface**

```python
research = commands.add_parser("research")
research_groups = research.add_subparsers(dest="research_group", required=True)
research_request = research_groups.add_parser("request")
request_commands = research_request.add_subparsers(
    dest="research_request_command", required=True
)
request_validate = request_commands.add_parser("validate")
request_validate.add_argument("--input", required=True)
_leaf_json(request_validate)
research_workspace = research_groups.add_parser("workspace")
workspace_commands = research_workspace.add_subparsers(
    dest="research_workspace_command", required=True
)
workspace_validate = workspace_commands.add_parser("validate")
workspace_validate.add_argument("--workspace", required=True)
_leaf_json(workspace_validate)
research_bundle = research_groups.add_parser("bundle")
bundle_commands = research_bundle.add_subparsers(
    dest="research_bundle_command", required=True
)
for name in ("compile", "validate"):
    command = bundle_commands.add_parser(name)
    command.add_argument("--workspace" if name == "compile" else "--bundle", required=True)
    _leaf_json(command)
```

- [ ] **Step 4: Implement handlers and stateful settings selection**

Request/workspace/bundle validation resolves installed schemas without requiring `KOKOROARC_DATA_DIR`. Bundle compilation requires `Settings.from_env`.

```python
def _handle_research_workspace_validate(args, settings, schemas):
    del settings
    workspace = load_research_workspace(Path(args.workspace), schemas)
    report = validate_research_workspace(workspace, schemas)
    return {"ok": True, "valid": report["valid"], "validation_report": report}


def _handle_research_bundle_compile(args, settings, schemas):
    workspace = load_research_workspace(Path(args.workspace), schemas)
    report = validate_research_workspace(workspace, schemas)
    if not report["valid"]:
        raise KokoroError("RESEARCH_VALIDATION_FAILED", "Research validation failed.")
    bundle = build_research_bundle(workspace, report)
    target = publish_research_bundle(
        settings.data_dir, Path(args.workspace), workspace, report, bundle
    )
    return {"ok": True, "path": str(target), **public_bundle_summary(bundle, report)}
```

Partial but structurally valid research may compile with `authoring_allowed: false`; only structural/security validation failure blocks publication.

- [ ] **Step 5: Add sanitized public errors**

Map every research error class to stable messages in `_PUBLIC_MESSAGES`. `_public_error_envelope` must remove source text, locators, absolute untrusted paths, temporary paths, credentials, and raw exceptions while preserving safe logical IDs and field paths.

- [ ] **Step 6: Add complete CLI integration tests**

Run every stateless validation twice and compare exact stdout. Compile complete and partial bundles under unique data roots. Validate the published bundle twice. Assert lifecycle, coverage, hashes, confinement, empty stderr, no protected roots, data-dir-required behavior only for compilation, malformed JSON sanitization, missing workspace/bundle sanitization, and installed wheel schema resolution.

- [ ] **Step 7: Run GREEN**

Run:

```powershell
python -m pytest tests/integration/test_research_cli.py tests/unit/test_cli.py tests/integration/test_authoring_cli.py -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add src/kokoroarc/cli.py tests/integration/test_research_cli.py tests/unit/test_cli.py
git commit -m "feat: expose character research cli"
```

---

### Task 8: Bind researched and hybrid authoring to exact eligible bundles

**Files:**
- Modify: `schemas/v1/character-build-request.schema.json`
- Modify: `src/kokoroarc/authoring/requests.py`
- Modify: `src/kokoroarc/authoring/validation.py`
- Modify: `src/kokoroarc/cli.py`
- Create: `tests/fixtures/authoring/researched-request.json`
- Create: `tests/fixtures/authoring/hybrid-request.json`
- Create: `tests/integration/test_researched_authoring.py`
- Modify: `tests/unit/test_authoring_schemas.py`
- Modify: `tests/unit/test_authoring.py`
- Modify: `skills/authoring-character-packs/SKILL.md`
- Modify: `skills/authoring-character-packs/references/authoring-contract.md`

- [ ] **Step 1: Write failing request-binding tests**

The `research_bundle` input contains identity and hash, never a path:

```json
{
  "type": "research_bundle",
  "artifact_id": "private/aoi-kisaragi-fixture/research/0123456789abcdef",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

```python
@pytest.mark.parametrize("mode", ["researched", "hybrid"])
def test_researched_modes_require_typed_bundle_binding(mode, valid_request):
    request = researched_request(valid_request, mode)
    SCHEMAS.validate("character-build-request", request)
    request["inputs"][0]["path"] = "D:/untrusted/bundle"
    with pytest.raises(KokoroError):
        SCHEMAS.validate("character-build-request", request)
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest tests/unit/test_authoring_schemas.py tests/integration/test_researched_authoring.py -q
```

Expected: FAIL because researched/hybrid remain unsupported and the input schema requires string `content`.

- [ ] **Step 3: Update the conditional input schema**

Creative brief, dossier, and user override inputs retain required string `content`. A research bundle input instead requires exactly `type`, `artifact_id`, and lowercase `sha256`. Researched mode requires at least one research bundle. Hybrid requires a research bundle plus at least one typed `user_dossier` or `user_override`. Both remain private.

- [ ] **Step 4: Add the trusted CLI bundle argument**

Add optional `--research-bundle PATH` to `character draft validate` and `character draft compile`. It is required exactly when request mode is researched or hybrid and prohibited for original/dossier. `PATH` is argparse documentation for the host argument, never a value read from the request body.

```python
def _authoring_inputs(args, schemas):
    request = normalize_build_request(_read_json(Path(args.request)), schemas)
    research_bundle = None
    if request["mode"] in {"researched", "hybrid"}:
        if not args.research_bundle:
            raise KokoroError(
                "RESEARCH_BUNDLE_REQUIRED",
                "An eligible Research Bundle is required for this authoring mode.",
            )
        research_bundle = load_published_research_bundle(
            Path(args.research_bundle), schemas
        )
    elif args.research_bundle:
        raise KokoroError(
            "RESEARCH_BUNDLE_UNEXPECTED",
            "This authoring mode does not accept a Research Bundle.",
        )
    source = load_source_pack(Path(args.pack), schemas)
    report = validate_authoring_pack(
        request, source, schemas, research_bundle=research_bundle
    )
    return request, source, report
```

- [ ] **Step 5: Implement exact eligibility checks**

Require request binding artifact ID and SHA-256; namespace, character ID, display name, continuity, timeline, and spoiler scope equality; `build_status: research`; private visibility; inactive lifecycle; `authoring_allowed: true`; no blocking reasons; and a schema-valid bundle. Use stable failures for missing, unexpected, hash mismatch, identity mismatch, continuity mismatch, spoiler mismatch, ineligible partial bundle, and unsafe bundle path.

Researched evidence claims may populate the source pack evidence layer only as references to supported bundle claim IDs. Hybrid mode preserves bundle evidence and typed user assertions as separate provenance. User overrides cannot rewrite bundle facts.

- [ ] **Step 6: Add authoring Skill handoff instructions**

Replace the missing-Milestone-7 stop with: invoke/open `researching-characters`; accept only its explicit private eligible bundle path plus exact identity/hash binding; pass the path as the trusted CLI argument; never copy source instructions into commands; and stop on partial/ineligible/mismatched research. Preserve the private inactive draft boundary.

- [ ] **Step 7: Add integration and negative tests**

Compile one researched and one hybrid draft from an eligible bundle. Assert byte stability, provenance separation, three locales, private inactive draft lifecycle, and no research mutation. Add failures for path embedded in request, missing CLI path, wrong hash, swapped character, continuity mismatch, timeline/spoiler widening, partial bundle, unresolved conflict, public/active bundle mutation, symlink/junction/hardlink bundle paths, and source changes during authoring validation.

- [ ] **Step 8: Run GREEN**

Run:

```powershell
python -m pytest tests/unit/test_authoring_schemas.py tests/unit/test_authoring.py tests/integration/test_researched_authoring.py tests/integration/test_authoring_cli.py tests/security/test_authoring_security.py -q
```

Expected: all supported tests pass.

- [ ] **Step 9: Commit**

```powershell
git add schemas/v1/character-build-request.schema.json src/kokoroarc/authoring src/kokoroarc/cli.py tests/fixtures/authoring tests/unit/test_authoring_schemas.py tests/unit/test_authoring.py tests/integration/test_researched_authoring.py skills/authoring-character-packs
git commit -m "feat: authorize exact research handoffs"
```

---

### Task 9: Complete adversarial and package-distribution verification

**Files:**
- Extend: `tests/security/test_research_security.py`
- Extend: `tests/integration/test_research_storage.py`
- Extend: `tests/integration/test_research_cli.py`
- Modify: `pyproject.toml` only if package discovery or data inclusion fails

- [ ] **Step 1: Write failing installed-artifact test**

Build into a fresh `D:\tmp` directory, install the wheel into a fresh target or virtual environment, clear repository `PYTHONPATH`, and prove all eight research schemas resolve plus all four CLI commands run from installed code.

```python
def test_built_archives_include_research_modules_and_schemas(dist_paths):
    assert REQUIRED_RESEARCH_MODULES <= wheel_entries(dist_paths.wheel)
    assert REQUIRED_RESEARCH_SCHEMAS <= wheel_entries(dist_paths.wheel)
    assert REQUIRED_RESEARCH_MODULES <= sdist_entries(dist_paths.sdist)
    assert REQUIRED_RESEARCH_SCHEMAS <= sdist_entries(dist_paths.sdist)
```

- [ ] **Step 2: Run RED before any packaging change**

Run:

```powershell
python -m build --outdir D:\tmp\kokoroarc-m7-package-red-20260804-01\dist
python -m pytest tests/integration/test_research_cli.py -k installed -v
```

Expected: either PASS from existing package discovery/data globs or a precise missing module/schema failure. Do not modify `pyproject.toml` if it already passes.

- [ ] **Step 3: Complete the security matrix**

Audit every read and write boundary for duplicate keys, non-finite JSON, invalid Unicode, embedded NUL, traversal, device paths, ADS, UNC, symlink, junction, reparse, hardlink, FIFO, ancestor swaps, file replacement, lock swaps, stale-backup redirects, oversized graphs, reference cycles, hash substitution, source-text leakage, and concurrent mutation. Add a failing test for each uncovered branch before implementation.

- [ ] **Step 4: Prove state non-mutation**

Snapshot hashes for `drafts`, `compiled`, `installed`, `public`, `sessions`, `state`, `events`, `workspaces`, and `config` before request/workspace/bundle validation and before failed compilation. Afterward, assert exact equality. Successful research compilation may add only the expected `research` bundle.

- [ ] **Step 5: Run broad GREEN**

Run:

```powershell
python -m pytest tests/unit/test_research_*.py tests/integration/test_research_*.py tests/security/test_research_security.py tests/unit/test_authoring*.py tests/integration/test_authoring*.py tests/security/test_authoring_security.py -q
```

Expected: all supported checks pass.

- [ ] **Step 6: Commit**

```powershell
git add tests/security/test_research_security.py tests/integration/test_research_storage.py tests/integration/test_research_cli.py pyproject.toml
git commit -m "test: harden character research boundaries"
```

Do not stage `pyproject.toml` unless the RED packaging test required a minimal fix.

---

### Task 10: Create and structurally validate the `researching-characters` Skill

**Files:**
- Create: `skills/researching-characters/SKILL.md`
- Create: `skills/researching-characters/agents/openai.yaml`
- Create: `skills/researching-characters/references/research-contract.md`
- Create: `tests/skills/researching-characters-cases.yaml`
- Create: `tests/skills/researching-characters-baseline.md`
- Create: `tests/skills/test_researching_characters_evidence.py`

- [ ] **Step 1: Invoke the required writing-skills workflow**

Read and apply `superpowers:writing-skills` and the system `skill-creator` instructions before creating Skill files. Keep `SKILL.md` concise, with only `name` and trigger-only `description` in frontmatter. Put the artifact and command contract in one directly linked reference.

- [ ] **Step 2: Define behavioral cases before writing the Skill**

Create at least these cases with explicit `must` and `must_not` assertions:

```yaml
cases:
  - id: ambiguous-character-stop
  - id: continuity-conflict-clarification
  - id: spoiler-cutoff
  - id: partial-unavailable-source
  - id: source-prompt-injection
  - id: invented-citation-pressure
  - id: canonical-trait-score-pressure
  - id: eligible-researched-handoff
  - id: eligible-hybrid-handoff
  - id: casual-discussion-non-trigger
  - id: original-character-non-trigger
```

Every positive case opens the target Skill and linked contract, validates twice with complete retained outputs, keeps sources inert, confines files, reports conflicts/coverage/limitations and a separate `Unresolved evidence:` line, and stops at the private Research Bundle or explicit authoring handoff. Negative cases must not open the Skill or invoke research CLI.

- [ ] **Step 3: Record baseline RED behavior**

Use fresh evaluator threads and an isolated fixture workspace without the target Skill available. Record exact failed assertions; do not manufacture a baseline failure if the generic agent already satisfies a case. Bind prompts, raw/sanitized streams, finals, and protected state hashes.

External evaluator runs require explicit user approval for the exact count and disclosure scope before execution.

- [ ] **Step 4: Write the Skill and contract**

The Skill routes first, clarifies identity/continuity before browsing, uses only host-authorized tools, creates source records before claims, distinguishes four claim classes, preserves conflicts and unavailable sources, prohibits canonical normalized traits, validates workspace and bundle twice, reports exact lifecycle and unresolved evidence, and invokes authoring only with an eligible exact bundle binding.

The Skill must never hard-code `D:\tmp` or any platform path. Product paths come from trusted `KOKOROARC_DATA_DIR` and configured temporary roots.

- [ ] **Step 5: Validate structure and metadata**

Run:

```powershell
python $skillCreatorValidator skills/researching-characters
python -m pytest tests/skills/test_researching_characters_evidence.py -k structural -v
```

Expected: `Skill is valid!` and structural tests pass.

- [ ] **Step 6: Commit**

```powershell
git add skills/researching-characters tests/skills/researching-characters-cases.yaml tests/skills/researching-characters-baseline.md tests/skills/test_researching_characters_evidence.py
git commit -m "feat: add character research skill"
```

---

### Task 11: Run the behavioral campaign and close Milestone 7 release evidence

**Files:**
- Create: `tests/skills/researching-characters-results.md`
- Extend: `tests/skills/test_researching_characters_evidence.py`
- Create: `tests/skills/research-release-verification.md`
- Create: `tests/skills/test_research_release_evidence.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-04-kokoroarc-research.md`

**Campaign checkpoint (2026-08-14):** The exactly approved first campaign ran 11 baseline and 11 Skill-enabled cases in fresh isolated threads. Its immutable behavioral result remains baseline RED `9/11` and Skill PASS `10/11`, RED `1/11`; the only Skill failure is the missing separate `Unresolved evidence:` line on the early continuity-clarification stop. A focused RED regression drove the corrected Skill body. Approval `2026-08-13-approved2` then ran exactly 11 fresh corrected Skill-only cases, with no baseline reruns or behavioral retries, and passed all declared assertions `11/11`. Exact raw platform final-message events have now been recovered from all 33 original Codex session logs, and evidence-derived adjudication reproduces every result without truth-table constants. Reviews of the earlier evidence commits found Important checkout, whitespace, command-provenance, confinement, inert-source, sanitizer, raw-replay, quoted-wrapper, shell-reachability, environment-access, and structured-secret gaps. Each accepted finding has a focused RED regression and fail-closed remediation. A newest settled release-record gate plus two fresh independent reviews remain open, so Task 11 remains open and Milestone 8 is not authorized to begin.

- [x] **Step 1: Obtain campaign approval**

Before any external evaluator execution, state the exact number of baseline/Skill runs, model/provider if applicable, disclosed repository files, retained transcript fields, redactions, and `D:\tmp` roots. Wait for explicit user approval. Any rerun batch needs a new exact approval.

- [x] **Step 2: Run fresh Skill-enabled cases**

Use unique threads and isolated directories. Positive cases must open the current Skill and reference, use the exact current hashes, and retain complete validation outputs. Bind raw/sanitized streams, prompts, final responses, state snapshots, assertion outcomes, and current Skill/reference/metadata hashes. Reject and rerun only harness failures; retain and report product/Skill failures.

- [x] **Step 3: Write executable evidence verification**

The test must parse evidence rather than check global substring presence. It independently computes every retained file hash, verifies thread uniqueness and approval counts, binds final text to the final agent message with only declared newline normalization, checks complete JSON output pairs byte-for-byte, scans parsed strings recursively for forbidden paths/secrets, verifies state hashes, and maps each result row to exact case assertions.

- [x] **Step 4: Run campaign GREEN or fix with RED regressions**

Run:

```powershell
python -m pytest tests/skills/test_researching_characters_evidence.py -v
python $skillCreatorValidator skills/researching-characters
```

Expected: every declared baseline result is honest, every Skill-enabled case passes, and the Skill validates. Fix failures with new focused tests and fresh approved reruns; never edit retained model output to force a pass.

- [x] **Step 5: Run a copy/paste CLI release smoke**

Under one new unique `D:\tmp` root, explicitly create test/temp/build/smoke/data directories. Capture stdout and stderr separately for two request validations, two workspace validations, one bundle compilation, and two bundle validations. Assert byte equality of paired outputs, empty stderr, exact lifecycle, coverage/conflicts, confinement, protected-root absence, and canonical transcript hash.

- [x] **Step 6: Build and inspect distributions from an exact input identity**

Record exact HEAD or exact base-plus-patch identity; never call a dirty build clean. Build wheel and sdist into the unique root. Record names, sizes, SHA-256, entry counts, all research module/schema entries, README identity, and any excluded non-package evidence changes. Provide copy/paste reconstruction commands and parameterize external validator paths.

- [x] **Step 7: Run exact-final verification**

Run separately and record exact outputs:

```powershell
python -m pytest -q --basetemp D:\tmp\kokoroarc-m7-release-20260804-final\pytest
python -m build --outdir D:\tmp\kokoroarc-m7-release-20260804-final\dist
python $skillCreatorValidator skills/using-kokoroarc
python $skillCreatorValidator skills/authoring-character-packs
python $skillCreatorValidator skills/researching-characters
git diff --check
git status --short
```

Expected: zero failures/errors, only documented platform capability skips, all three Skills valid, wheel and sdist built, no bad whitespace, and only intended release-evidence changes before commit.

The earlier `final2` run is retained as historical evidence but was reopened after Important exact-commit review findings. Commit `c8095c105f4866f3728debfa1ca2568f28fff2be` then passed `1920 passed, 24 skipped`, the fixed-epoch build and archive inventory, all three validators, a detached `core.autocrlf=true` checkout, evidence byte reproduction, and the exact-range whitespace audit. The settled release-record commit repeats those gates under `D:\tmp\kokoroarc-m7-remediation-final4-settled-01`.

Fresh specification and quality reviews of later settled commit `646fc91f27eb723334f4ff4b25309985b56046a3` both failed with Important findings: CLI evidence was not executable-bound, an outside compile path could pass by suffix, environment dumps and JavaScript source execution could pass the inertness checks, common credential forms were missed, and the current sanitizer could not reproduce 12 retained historical files. Commit `a3fcdb809945cf823f3dd860c65666f0cab6b4be` closes those paths. Its exact D:-confined gate passed `1942 passed, 24 skipped`, the fixed-epoch build/inventory, all three validators, all 785 raw-ledger replay comparisons, the exact-range whitespace/status check, and a detached `core.autocrlf=true` checkout with 984/984 byte-identical evidence files. The settled release-record tree is assigned `D:\tmp\kokoroarc-m7-replay-hardening-settled-01`; Step 10 remains open until that exact tree passes and both new reviews return no Critical or Important findings.

Fresh specification review of exact settled commit `531ce43cf2f8dff4708fa64c601ec72bd680cbf2` then failed with three Important findings, so quality review was not run: a quoted non-executing wrapper could satisfy raw command provenance, `dir env:` and a quoted Node path reading `process['env']` could satisfy source safety, and escaped/nested assignment values could be partially redacted and then declared clean. Five regression items now cover those exact cases plus redaction-placeholder smuggling. The focused gate passes 57 tests, all 785 raw-ledger files remain reproducible, and a full dirty-tree preflight passes `1948 passed, 24 skipped`. The newest settled gate is assigned `D:\tmp\kokoroarc-m7-spec2-remediation-settled-01`; Step 10 remains open pending that exact rerun and both new independent reviews.

Fresh specification review of exact commit `57ea7ea7f215cedcf800dc266bd5486eb981976a` reconfirmed those paths were closed but found three further Important false passes, so quality review again was not run: executable-looking CLI text inside a PowerShell block comment could inherit captures, a quoted full-path Python `-c` command could pass source safety and confinement, and placeholder-prefixed URL credentials plus escaped Authorization values could leak suffixes and self-certify as clean. Six new regression items cover those findings plus dead-branch, short-circuit, and early-termination reachability. The focused gate passes 64 tests, all raw replay checks remain green, and the D:-confined full preflight passes `1955 passed, 24 skipped`. The next settled gate is assigned `D:\tmp\kokoroarc-m7-spec3-remediation-settled-01`; Step 10 remains open pending its exact rerun and both fresh independent reviews.

Exact settled commit `bea1fce58cbbf0c00a49da2fa662e0dc30c2d7b1` then passed `1956 passed, 24 skipped`, the fixed-epoch distribution/inventory gate, all three Skill validators, 785-file raw replay, 33 final-message bindings, exact-range whitespace/status checks, and a fresh detached `core.autocrlf=true` checkout with 984/984 byte-identical evidence files and 65 focused tests. Its fresh specification review nevertheless failed with one Important finding, so quality review was not run: raw PowerShell wrapper provenance was bound only to the CLI action, allowing different arguments, help-only execution, trailing failure/output, or different capture redirections to inherit the claimed argv and retained captures. Eight wrapper mutations plus an adjacent partial-direct-summary regression now bind the complete child invocation, both capture paths, and exact nonzero-exit propagation. The focused gate passes 75 tests, and the final D:-confined full preflight at `D:\tmp\kokoroarc-m7-spec4-remediation-preflight-04` passes `1966 passed, 24 skipped`; three superseded or failed launches are disclosed in the release record. The next settled gate is assigned `D:\tmp\kokoroarc-m7-spec4-remediation-settled-01`; Step 10 remains open pending its exact rerun and both fresh independent reviews.

Exact settled commit `670e44bf126daa2198c77889ad3bf142b60d0b72` then passed `1966 passed, 24 skipped`, the fixed-base-epoch build/inventory gate, all three Skill validators, 785-file raw replay, 33 final-message bindings, exact-range whitespace/status checks, and a fresh detached `core.autocrlf=true` checkout with 984/984 byte-identical evidence files and 75 focused tests. Its fresh specification review nevertheless failed with three Important findings, so quality review was not run: executable identity allowed path and alias substitution, wrapper `PYTHONPATH` plus CLI `cwd`/login/lifecycle metadata were not bound to the retained execution context, and conflicting capture aliases silently selected whichever field supported a pass. Seven RED full-run mutations now cover both executable substitutions, changed import root, outside working directory, login-shell and not-started contradictions, and duplicate capture disagreement. One shared fail-closed binding path requires exact argv identity, reported environment agreement, the trusted run root, the retained lifecycle, and consistent stdout/stderr aliases. The focused research/release gate passes 83 tests, and the D:-confined full preflight at `D:\tmp\kokoroarc-m7-spec5-remediation-preflight-01` passes `1974 passed, 24 skipped`; stdout SHA-256 is `95022C1B29E414D28554A40C7E8E5FBC5D3ED2088CF7AEF41B619B40EC552EB1` and stderr is empty. The next settled gate is assigned `D:\tmp\kokoroarc-m7-spec5-remediation-settled-01`. Step 10 remains open pending its exact rerun and both fresh independent reviews.

- [x] **Step 8: Document the exact boundary**

README must explain repository-local research Skill invocation, continuity/spoiler clarification, private Research Bundle output, exact eligible handoff to authoring, and that testing/promotion/global installation/default bindings/memory/publication remain unavailable until Milestones 8-9.

`research-release-verification.md` must state that Milestone 7 does not approve the complete standalone suite.

- [x] **Step 9: Commit release evidence**

```powershell
git add README.md tests/skills/researching-characters-results.md tests/skills/test_researching_characters_evidence.py tests/skills/research-release-verification.md tests/skills/test_research_release_evidence.py docs/superpowers/plans/2026-08-04-kokoroarc-research.md
git commit -m "docs: verify character research milestone"
```

- [ ] **Step 10: Require final independent closure**

Obtain a fresh specification review and a fresh quality review on the exact final commit. Both must report PASS with no Critical or Important findings. Fix any finding using a new RED test, rerun exact-final verification, recommit, and repeat both reviews.

Only after both reviews pass may Milestone 7 be marked complete and Milestone 8 begin.

---

## Plan self-review checklist

- [x] Every design artifact and acceptance criterion maps to a task above.
- [x] Research acquisition remains host-provided; the core has no network client.
- [x] The request never supplies a filesystem path; the host CLI argument does.
- [x] Complete and partial evidence remain distinguishable.
- [x] Global-first character defaults and persistent memory remain deferred to Milestones 8-9.
- [x] Every implementation task begins with a failing test and ends with a focused commit.
- [x] Every task receives specification then quality review before the next task.
- [x] No external evaluator run occurs without exact user approval.
- [x] No placeholder or unchecked acceptance claim is represented as completed work.
