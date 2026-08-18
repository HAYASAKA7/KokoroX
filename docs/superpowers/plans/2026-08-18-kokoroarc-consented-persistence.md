# KokoroArc Consented Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit-consent durable relationship and mood state, bounded
host-owned memory references, canonical export/reset, replay-verified state
migration, and installation-removal guards while keeping every ordinary
session ephemeral.

**Architecture:** A new `kokoroarc.persistence` package separates consent,
state, memory, and migration domains above one private filesystem transaction
layer. Each write resolves an exact same-scope installation, checks an exact
consent generation, publishes immutable canonical records before derived
projections, and re-audits all retained inputs and filesystem identities before
return. Session storage remains unchanged and no Task 15 function is invoked
implicitly by runtime or Skill flows.

**Tech Stack:** Python 3.11+, JSON Schema Draft 2020-12, canonical JSON and
SHA-256, standard-library file locking/direct `os.scandir`/fsync/atomic
publication, existing `.karc` installation and relationship-v1 contracts,
pytest.

---

## Working rules

- Work only in `.worktrees/standalone-suite` on `feat/standalone-suite`.
- Keep test, build, bytecode, and failure-injection temporaries below a unique
  `D:\tmp` directory. Never use the real user home for test storage.
- Use `apply_patch` for every source, schema, fixture, test, and documentation
  edit.
- Apply strict test-driven development: add the named RED assertion, run it and
  observe the intended failure, implement only that slice, then rerun GREEN.
- Do not add Task 17 CLI commands in Task 15. Public Python APIs and installed
  package discovery are the Task 15 boundary.
- Task 15 performs no network, model, browser, registry-upload, subprocess, or
  background work.
- Do not change `SessionStore` behavior or make config/default/session/runtime
  code call persistence automatically.
- Never weaken schema closure, installation verification, consent separation,
  canonical-byte checks, mutation audits, resource limits, or no-follow path
  checks to make a test pass.
- Preserve the Milestone 7 evidence subtree and all settled release evidence.
- Commit each independently green slice. Do not squash or rewrite commits
  unless the user explicitly requests it.
- Do not mark Task 15 complete until focused, adjacent, package, full-suite,
  static, exact-diff, and clean-worktree gates all pass.

## Frozen contract decisions

- Consent lifecycle revision is `revoked_revision` when revoked and
  `grant_revision` otherwise. First grant is revision 1; replace, revoke, and
  regrant each advance the lifecycle by exactly one.
- Permission order is fixed as `relationship_state`, `mood_state`, then
  `memory_references`. Grant replaces the complete permission set; it never
  unions permissions.
- Consent ID is deterministic from scope, workspace ID, namespace, and
  character ID. It remains stable across revisions and installation rebinding.
- Rebinding consent makes prior state read/export/reset/migration-only.
  Ordinary writes require the current consent and an exactly matching state
  generation.
- State journal publication is the commit point. `state.json` and
  `current.json` are recoverable projections.
- A generation ID is `generation-` plus the first 32 hex characters of the
  canonical scope, character, installation, consent revision, and creation
  operation digest. Repeating the same creation intent selects the same ID.
- Relationship-v1 is reused exactly. Persistent code reads
  `growth.max_delta_per_event` and `growth.repetition_window_turns` from the
  consent-bound compiled pack and records both values in every event.
- Mood values are explicit, not inferred. Canonical moods are `neutral`,
  `focused`, `curious`, `pleased`, `amused`, `concerned`, `embarrassed`,
  `irritated`, `disappointed`, `relieved`, `proud`, and `tired`.
- Memory stores only a host memory ID plus approved bounded summaries. It never
  dereferences the host ID.
- Migration re-emits source relationship events into a new target generation
  under the frozen target contract. It never copies a trusted state snapshot
  as authority.
- Historical revoked/superseded consent alone does not block installation
  removal. Current state, retained memory, active consent, or an incomplete
  migration does.

## Stable error contract

Use these exact public error codes. Error details contain only bounded
enum-like `phase`, `reason`, `limit`, `operation`, and `record_state` values:

- consent: `PERSISTENCE_CONSENT_INVALID`,
  `PERSISTENCE_CONSENT_NOT_FOUND`, `PERSISTENCE_CONSENT_CONFLICT`,
  `PERSISTENCE_CONSENT_REVOKED`, and `PERSISTENCE_PERMISSION_DENIED`;
- installation/input binding: `PERSISTENCE_INSTALLATION_STALE` and
  `PERSISTENCE_INPUT_MUTATION`;
- state: `PERSISTENCE_STATE_NOT_FOUND`,
  `PERSISTENCE_STATE_REVISION_CONFLICT`,
  `PERSISTENCE_STATE_JOURNAL_INVALID`,
  `PERSISTENCE_STATE_CONTRACT_UNSUPPORTED`,
  `PERSISTENCE_STATE_MIGRATION_REQUIRED`, and
  `PERSISTENCE_STATE_WRITE_FAILED`;
- mood: `PERSISTENCE_MOOD_INVALID`;
- memory: `PERSISTENCE_MEMORY_INVALID`,
  `PERSISTENCE_MEMORY_CONTENT_REJECTED`,
  `PERSISTENCE_MEMORY_CONFLICT`, and `PERSISTENCE_MEMORY_NOT_FOUND`;
- reset: `PERSISTENCE_RESET_STALE`;
- migration: `PERSISTENCE_MIGRATION_INVALID`,
  `PERSISTENCE_MIGRATION_STALE`, and
  `PERSISTENCE_MIGRATION_UNREPLAYABLE`;
- shared storage: `PERSISTENCE_PATH_UNSAFE`,
  `PERSISTENCE_LIMIT_EXCEEDED`, `PERSISTENCE_LOCKED`,
  `PERSISTENCE_WRITE_FAILED`, `PERSISTENCE_DURABILITY_FAILED`,
  `PERSISTENCE_CLEANUP_FAILED`, and `PERSISTENCE_CHANGED`.

Never place a host path, consent payload, interaction evidence, memory ID,
summary text, matched detector value, or secret in an error envelope.
Public domain boundaries translate schema, JSON, Unicode, filesystem, and type
failures into the codes above; raw `SCHEMA_*`, `OSError`, `TypeError`, and
decoder exceptions never escape.

## File map

```text
schemas/v1/persistence-consent.schema.json
  Tighten canonical permission combinations.

schemas/v1/memory-reference.schema.json
  Add the missing archive and compiled hashes to the exact installation bind.

schemas/v1/persistent-character-state.schema.json
  Closed generation envelope with relationship and bounded mood projections.

schemas/v1/persistent-state-event.schema.json
  Closed append-only relationship, mood, reset, and migration operations.

schemas/v1/persistence-export.schema.json
  Closed path-free consent/state/journal/memory export.

schemas/v1/state-migration-plan.schema.json
  Closed source/target bindings, strategies, and expected replay hashes.

src/kokoroarc/persistence/_storage.py
  Scope keys, limits, strict canonical reads, direct bounded scans, retained
  identities, locks, fsync, staging, transaction markers, and mutation audits.

src/kokoroarc/persistence/consent.py
  Grant/load/revoke lifecycle and active permission/installation guard.

src/kokoroarc/persistence/state.py
  Relationship and mood journal, replay, projection recovery, export, reset.

src/kokoroarc/persistence/memory.py
  Explicit approved reference add/list/remove and summary-content defenses.

src/kokoroarc/persistence/migrations.py
  Deterministic migration preview, target replay, generation cutover/recovery.

src/kokoroarc/persistence/__init__.py
  Stable typed Task 15 public surface.

src/kokoroarc/distribution/installer.py
  Bounded persistent-reference blockers during exact removal.

tests/persistence_support.py
  Real archive/install/consent/event helpers shared by persistence tests.

tests/fixtures/standalone-contracts/private-global.json
tests/fixtures/standalone-contracts/public-workspace.json
  Canonical global/workspace examples for all four new artifacts.

tests/unit/test_standalone_schemas.py
  Discovery, closure, conditionals, bounds, and executable-field rejection.

tests/unit/test_persistence_storage.py
  Internal canonical storage, limits, locks, and recovery primitives.

tests/unit/test_persistence_consent.py
tests/unit/test_persistent_state.py
tests/unit/test_memory_references.py
tests/unit/test_persistent_migrations.py
  Domain behavior, exact revisions, idempotency, replay, and migration.

tests/integration/test_persistence_workflow.py
  Real global/workspace install-to-removal workflows and process replay.

tests/security/test_persistence_security.py
  Content, path, callback, mutation, race, capacity, and failure windows.

tests/unit/test_karc_installer.py
tests/integration/test_karc_installer_integration.py
tests/security/test_karc_installer_security.py
  Exact active/inactive persistence removal blockers and reference races.

tests/integration/test_research_cli.py
  Wheel/sdist schema/module inventory and installed public-import smoke.
```

## Design coverage index

- Design §§1-3 are frozen by the goal, architecture, working rules, and
  contract decisions above.
- Design §§4-5 are implemented by Tasks 1-2.
- Design §6 is implemented by Task 3.
- Design §7 is implemented by Tasks 4-5.
- Design §8 is implemented by Task 6.
- Design §9 is implemented by Task 7.
- Design §10 is implemented by Task 8.
- Design §11 is implemented by Task 9.
- Design §§12-14 are implemented and adversarially closed by Tasks 10-11.
- Design §§15-17 are verified by Task 12.

### Task 1: Close the persistent artifact contracts

**Files:**
- Modify: `schemas/v1/persistence-consent.schema.json`
- Modify: `schemas/v1/memory-reference.schema.json`
- Create: `schemas/v1/persistent-character-state.schema.json`
- Create: `schemas/v1/persistent-state-event.schema.json`
- Create: `schemas/v1/persistence-export.schema.json`
- Create: `schemas/v1/state-migration-plan.schema.json`
- Modify: `tests/fixtures/standalone-contracts/private-global.json`
- Modify: `tests/fixtures/standalone-contracts/public-workspace.json`
- Modify: `tests/unit/test_standalone_schemas.py`

- [ ] **Step 1: Write RED discovery and canonical-fixture tests**

Extend the fixture map before creating the schemas:

```python
SCHEMA_BY_FIXTURE_KEY = {
    "karc_manifest": "karc-manifest",
    "compatibility_report": "pack-compatibility-report",
    "migration_plan": "pack-migration-plan",
    "installed_registry": "installed-pack-registry",
    "default_config": "character-default-config",
    "persistence_consent": "persistence-consent",
    "memory_reference": "memory-reference",
    "persistent_state": "persistent-character-state",
    "persistent_event": "persistent-state-event",
    "persistence_export": "persistence-export",
    "state_migration_plan": "state-migration-plan",
}
```

Add one global fixture at revision 1 and one workspace fixture at revision 3.
Use this exact mood projection in both so the tests lock its field names:

```python
MOOD = {
    "revision": 0,
    "primary": "neutral",
    "secondary": None,
    "arousal": 0.0,
    "valence": 0.0,
    "intensity": 0.0,
    "remaining_turns": 0,
    "expires_after_turns": 0,
    "triggering_event_id": None,
    "applied_event_ids": [],
}
```

Add negative matrices proving:

```python
@pytest.mark.parametrize(
    "permissions",
    [
        ["mood_state", "relationship_state"],
        ["memory_references", "mood_state"],
        ["relationship_state", "memory_references", "mood_state"],
    ],
)
def test_consent_requires_canonical_permission_order(
    permissions: list[str],
) -> None:
    invalid = deepcopy(_bundle("private-global.json")["persistence_consent"])
    invalid["permissions"] = permissions
    _assert_invalid("persistence-consent", invalid)


def test_memory_reference_requires_exact_archive_and_compiled_hashes() -> None:
    for field in ("archive_sha256", "compiled_sha256"):
        invalid = deepcopy(_bundle("private-global.json")["memory_reference"])
        del invalid[field]
        _assert_invalid("memory-reference", invalid)
```

Also cover unknown root/nested fields, global/workspace conditionals, revision
zero/null last-event coupling, relationship/mood revision bounds, all event
kinds, predecessor/successor hashes, sorted unique memory references, export
counts/digests, migration strategy enums, source/target mismatch, and rejection
of `script`, `command`, `expression`, `callback`, `module`, and `executable`.

- [ ] **Step 2: Run the schema RED tests**

Run:

```powershell
$env:TMP='D:\tmp'; $env:TEMP='D:\tmp'
$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/unit/test_standalone_schemas.py -q `
  -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t1-red
```

Expected: fail with `SCHEMA_NOT_FOUND` for the four new schema names and then
fail the new memory-binding and permission-order assertions.

- [ ] **Step 3: Implement the exact schema shapes**

Use these required root keys for `persistent-character-state`:

```json
[
  "schema_version", "artifact_id", "created_by", "scope",
  "workspace_id", "installation", "consent", "generation_id",
  "state_contract_version", "transition_algorithm", "revision",
  "relationship", "mood", "applied_operation_ids",
  "last_event_sha256"
]
```

Set `state_contract_version` to `1.0.0` and `transition_algorithm` to
`relationship-v1`. Bound `revision` and every ID list to 10,000. Require
revision zero to have empty operation IDs and null last-event hash; require a
positive revision to have a nonempty list and SHA-256 last-event hash.

Use these event kinds and closed payloads in
`persistent-state-event.schema.json`:

```json
{
  "relationship": ["interaction_event", "max_delta", "repetition_window"],
  "mood_update": [
    "event_id", "expected_mood_revision", "primary", "secondary",
    "arousal", "valence", "intensity", "expires_after_turns",
    "triggering_interaction_event_id"
  ],
  "mood_advance": ["event_id", "expected_mood_revision", "turns"],
  "relationship_reset": ["reset_id", "expected_relationship_revision"],
  "mood_reset": ["reset_id", "expected_mood_revision"],
  "migration_marker": [
    "plan_sha256", "source_generation_id", "source_state_sha256",
    "source_event_log_sha256", "mood_strategy"
  ]
}
```

Every event root also requires exact scope, workspace, installation, consent,
generation, outer revision, operation ID/kind, predecessor event/state hashes,
successor state hash, and algorithm version. All payload variants are selected
with `oneOf` plus `const` kind fields, never a free-form object.

The mood numeric bounds are arousal/valence `[-1, 1]`, intensity `[0, 1]`,
and expiry/remaining turns `[0, 1000]`. A neutral mood requires secondary and
trigger to be null and all numeric/turn fields zero.

`persistence-export` binds exact consent and nullable state, includes
`event_log_sha256`, an ordered memory-reference array, `memory_count`, and
`export_sha256`. It contains no filesystem-path property.

`state-migration-plan` binds source state/consent/installation and target
consent/installation, source event-log digest, source state hash, target replay
hash, expected target state hash, `relationship_strategy` fixed to
`replay_relationship_v1`, mood strategy `preserve_identical_contract` or
`reset_neutral`, mode `preview`, and `executable_code_accepted: false`.

Change consent permissions to the seven exact nonempty canonical arrays. Add
`archive_sha256` and `compiled_sha256` as required SHA-256 fields on every
memory reference and update both fixture bundles.

- [ ] **Step 4: Run schema GREEN and ECMAScript/package discovery guards**

Run:

```powershell
python -m pytest tests/unit/test_standalone_schemas.py `
  tests/unit/test_research_portable_contracts.py `
  tests/unit/test_schemas.py -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t1-green
```

Expected: all tests pass.

- [ ] **Step 5: Commit the closed contracts**

```powershell
git add schemas/v1/persistence-consent.schema.json `
  schemas/v1/memory-reference.schema.json `
  schemas/v1/persistent-character-state.schema.json `
  schemas/v1/persistent-state-event.schema.json `
  schemas/v1/persistence-export.schema.json `
  schemas/v1/state-migration-plan.schema.json `
  tests/fixtures/standalone-contracts/private-global.json `
  tests/fixtures/standalone-contracts/public-workspace.json `
  tests/unit/test_standalone_schemas.py
git diff --cached --check
git commit -m "feat: add persistent artifact contracts"
```

### Task 2: Build the shared persistence storage boundary

**Files:**
- Create: `src/kokoroarc/persistence/__init__.py`
- Create: `src/kokoroarc/persistence/_storage.py`
- Create: `tests/unit/test_persistence_storage.py`
- Create: `tests/security/test_persistence_security.py`

- [ ] **Step 1: Write RED read-only, canonical, scope, and limit tests**

Start with the exact public internal types used by later tasks:

```python
from kokoroarc.persistence._storage import (
    PersistenceKey,
    PersistenceLimits,
    open_persistence_scope,
)


def test_absent_scope_open_is_read_only(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    scope = open_persistence_scope(
        root,
        SCHEMAS,
        character_id="rin-aster",
    )
    assert scope.key == PersistenceKey(
        scope="global",
        workspace_id=None,
        namespace="original",
        character_id="rin-aster",
    )
    assert not root.exists()


def test_limits_are_frozen_and_bounded() -> None:
    limits = PersistenceLimits()
    assert limits.max_consent_history == 1024
    assert limits.max_state_generations == 64
    assert limits.max_state_events == 10_000
    assert limits.max_memory_references == 1024
    assert limits.max_journal_bytes == 64 * 1024 * 1024
```

Add strict JSON tests for duplicate keys, NaN, invalid UTF-8, noncanonical
bytes, too-large files, aggregate overflow, direct-scandir stop at limit + 1,
unsafe suffixes, and mixed node types. Add global/workspace isolation and prove
the workspace is neither created nor modified.

Security RED cases must cover symlink, Windows junction/reparse point,
hardlink, special file, ancestor replacement, case-collision, lock replacement,
same-name staging replacement, and schema callback A-to-B-to-A mutation.

- [ ] **Step 2: Run the storage RED tests**

Run:

```powershell
python -m pytest tests/unit/test_persistence_storage.py `
  tests/security/test_persistence_security.py `
  -k "storage or canonical or scope or limit or link or lock" -q `
  -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t2-red
```

Expected: collection fails because `kokoroarc.persistence` is absent.

- [ ] **Step 3: Implement immutable keys, limits, and callback audits**

Create these exact foundations:

```python
class SchemaValidator(Protocol):
    def validate(self, name: str, instance: Any) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class PersistenceLimits:
    max_consent_bytes: int = 64 * 1024
    max_state_bytes: int = 4 * 1024 * 1024
    max_event_bytes: int = 16 * 1024
    max_memory_bytes: int = 16 * 1024
    max_transaction_bytes: int = 128 * 1024
    max_consent_history: int = 1024
    max_state_generations: int = 64
    max_state_events: int = 10_000
    max_memory_references: int = 1024
    max_journal_bytes: int = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PersistenceKey:
    scope: Literal["global", "workspace"]
    workspace_id: str | None
    namespace: str
    character_id: str

    @property
    def scope_parts(self) -> tuple[str] | tuple[str, str]:
        if self.scope == "global":
            return ("global",)
        return ("workspaces", cast(str, self.workspace_id))


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    path: Path
    payload: bytes
    value: dict[str, Any]
    identity: tuple[int, int, int, int, int, int]


@dataclass(slots=True)
class PersistenceBoundary:
    schemas: SchemaValidator
    audits: dict[str, Callable[[], None]]
    violation: KokoroError | None = None

    def validate(self, schema_name: str, payload: bytes) -> None:
        probe = json.loads(payload)
        try:
            self.schemas.validate(schema_name, probe)
            if canonical_bytes(probe) != payload:
                raise _mutation_error("schema_input")
        finally:
            self.assert_clean()

    def assert_clean(self) -> None:
        if self.violation is not None:
            raise self.violation
        for name in sorted(self.audits):
            try:
                self.audits[name]()
            except KokoroError as error:
                self.violation = error
                raise

    def fail(self, reason: str) -> NoReturn:
        error = KokoroError(
            "PERSISTENCE_INPUT_MUTATION",
            "A persistence input changed during the operation.",
            details={"reason": reason},
        )
        self.violation = error
        raise error


@dataclass(frozen=True, slots=True)
class PersistenceScope:
    root: Path
    key: PersistenceKey
    boundary: PersistenceBoundary
    limits: PersistenceLimits
```

Add `_MutationProbe` that captures canonical bytes and becomes sticky after
any mismatch. `_BoundarySchemas.validate` must validate a fresh JSON decode and
run every registered audit in `finally`. `assert_clean()` reruns every audit
before return and preserves the first mutation/path failure.

- [ ] **Step 4: Implement bounded no-follow storage primitives**

Add exact helpers used by domain modules:

```python
def open_persistence_scope(
    data_root: Path,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    character_id: str,
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> PersistenceScope:
    root = _absolute_path(data_root)
    key = _persistence_key(
        namespace,
        character_id,
        workspace_root,
    )
    boundary = _capture_scope_boundary(root, key, workspace_root, schemas)
    return PersistenceScope(root, key, boundary, limits)


def read_canonical_object(
    path: Path,
    *,
    limit: int,
    schema_name: str,
    boundary: PersistenceBoundary,
    optional: bool = False,
) -> ArtifactSnapshot | None:
    captured = _read_regular_file(path, limit=limit, optional=optional)
    if captured is None:
        boundary.audits[str(path)] = _absent_file_audit(path)
        return None
    payload, identity = captured
    value = _parse_canonical_object(payload)
    boundary.validate(schema_name, payload)
    boundary.audits[str(path)] = _file_audit(path, payload, identity)
    return ArtifactSnapshot(path, payload, value, identity)


def scan_canonical_directory(
    path: Path,
    *,
    entry_limit: int,
    aggregate_limit: int,
    file_limit: int,
    schema_name: str,
    boundary: PersistenceBoundary,
) -> Sequence[ArtifactSnapshot]:
    paths = _bounded_regular_json_entries(path, entry_limit)
    snapshots = tuple(
        cast(
            ArtifactSnapshot,
            read_canonical_object(
                item,
                limit=file_limit,
                schema_name=schema_name,
                boundary=boundary,
            ),
        )
        for item in paths
    )
    if sum(len(item.payload) for item in snapshots) > aggregate_limit:
        raise _limit_error("aggregate_bytes", aggregate_limit)
    return snapshots
```

The implementation must use `os.scandir` directly, increment the total entry
count before filtering, stop at limit + 1 before sorting, read at most
`limit + 1` bytes, reject duplicate keys/non-finite values, require exact
canonical bytes, and retain linked/opened/after/final identities with link
count one. Optional absence retains the nearest existing ancestor and fails if
the node appears during a callback.

Absolutize `data_root` before any callback. Validate namespace and character
with the existing schema-safe artifact-segment rule, derive workspace ID only
through `resolve_install_scope`, and reject case/path identity mismatch. Never
accept caller-provided internal roots or turn installation, consent, event,
memory, reset, or migration IDs directly into path fragments.

Add a per-character cross-process lock, exclusive/no-follow staging creation,
immutable no-overwrite publication, verified atomic projection replacement,
file and parent fsync, identified cleanup, and a one-marker transaction API.
Every cleanup result is one of `not_visible`, `committed`, or `unknown`.

- [ ] **Step 5: Run storage GREEN beside registry/default storage tests**

Run:

```powershell
python -m pytest tests/unit/test_persistence_storage.py `
  tests/security/test_persistence_security.py `
  tests/unit/test_karc_registry.py tests/unit/test_character_defaults.py -q `
  -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t2-green
```

Expected: all runnable tests pass; capability skips must name the unavailable
filesystem primitive.

- [ ] **Step 6: Commit the storage boundary**

```powershell
git add src/kokoroarc/persistence/__init__.py `
  src/kokoroarc/persistence/_storage.py `
  tests/unit/test_persistence_storage.py `
  tests/security/test_persistence_security.py
git diff --cached --check
git commit -m "feat: add persistence storage primitives"
```

### Task 3: Implement explicit consent lifecycle and active guards

**Files:**
- Create: `src/kokoroarc/persistence/consent.py`
- Create: `tests/persistence_support.py`
- Create: `tests/unit/test_persistence_consent.py`
- Modify: `tests/security/test_persistence_security.py`

- [ ] **Step 1: Write the real-install helper and RED lifecycle tests**

Create this shared setup using the real archive and installer:

```python
def install_rin(
    data_root: Path,
    release: dict[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    label = "workspace" if workspace_root is not None else "global"
    archive = data_root.parent / f"rin-{label}.karc"
    archive.write_bytes(build_private_archive(release))
    return install_karc_archive(
        archive,
        data_root,
        SCHEMAS,
        workspace_root=workspace_root,
    )


@dataclass(frozen=True, slots=True)
class ConsentedRin:
    data_root: Path
    workspace_root: Path | None
    installation_payload: bytes
    consent_payload: bytes

    @property
    def installation(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.installation_payload))

    @property
    def consent(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.consent_payload))


@pytest.fixture
def consented_rin(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> ConsentedRin:
    data_root = tmp_path / "data"
    installation = install_rin(data_root, rin_verified_release)
    consent = grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state", "mood_state", "memory_references"],
        SCHEMAS,
        expected_revision=0,
    )
    return ConsentedRin(
        data_root=data_root,
        workspace_root=None,
        installation_payload=canonical_bytes(installation),
        consent_payload=canonical_bytes(consent),
    )
```

Lock the lifecycle with this control:

```python
def test_grant_replace_revoke_regrant_has_exact_lifecycle_revisions(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    install_rin(root, rin_verified_release)

    first = grant_consent(
        root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        expected_revision=0,
    )
    repeated = grant_consent(
        root,
        "rin-aster",
        ["relationship_state"],
        SCHEMAS,
        expected_revision=1,
    )
    replaced = grant_consent(
        root,
        "rin-aster",
        ["relationship_state", "mood_state"],
        SCHEMAS,
        expected_revision=1,
    )
    revoked = revoke_consent(
        root,
        "rin-aster",
        first["consent_id"],
        SCHEMAS,
        expected_revision=2,
    )
    regranted = grant_consent(
        root,
        "rin-aster",
        ["memory_references"],
        SCHEMAS,
        expected_revision=3,
    )

    assert repeated == first
    assert replaced["grant_revision"] == 2
    assert revoked["grant_revision"] == 2
    assert revoked["revoked_revision"] == 3
    assert regranted["grant_revision"] == 4
    assert regranted["consent_id"] == first["consent_id"]
    assert regranted["permissions"] == ["memory_references"]
```

Add absent read-only load, explicit version, ambiguous omitted version, stale
expected revision, wrong consent ID, repeated revoke, workspace isolation,
permission replacement rather than union, exact current/history bytes, and
revoked/superseded state inspection cases.

Add a caller-normalization control: grant all three permissions in reverse
order and assert the artifact contains the fixed canonical order. Repeating
the same set in another order at the current revision must return the exact
same artifact rather than publish a new revision.

- [ ] **Step 2: Write RED authorization and callback tests**

Test `_require_active_consent` through a small test-only call in this task and
through domain APIs in later tasks. Cover absent, revoked, missing permission,
wrong grant revision, wrong scope/character, uninstalled/replaced archive,
changed registry, changed installed tree, and changed compiled bytes.

Add a schema proxy that retains and mutates the detached consent instance,
another that mutates the caller permissions list, and an A-to-B-to-A callback
sequence across two schema calls. All must fail with a stable non-echoing
consent mutation or stale-installation code and leave no new history file.

- [ ] **Step 3: Run consent RED**

Run:

```powershell
python -m pytest tests/unit/test_persistence_consent.py `
  tests/security/test_persistence_security.py `
  -k "consent or permission or installation" -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t3-red
```

Expected: fail because consent functions are absent.

- [ ] **Step 4: Implement grant, load, revoke, and active guard**

Use these exact public signatures:

```python
def grant_consent(
    data_root: Path,
    character_id: str,
    permissions: Sequence[str],
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    version: str | None = None,
    workspace_root: Path | None = None,
    expected_revision: int,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    return _change_consent(
        data_root=data_root,
        character_id=character_id,
        permissions=permissions,
        schemas=schemas,
        namespace=namespace,
        version=version,
        workspace_root=workspace_root,
        expected_revision=expected_revision,
        revoke=False,
        consent_id=None,
        limits=limits,
    )


def load_consent(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any] | None:
    snapshot = _load_consent_snapshot(
        data_root,
        character_id,
        schemas,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
    if snapshot is None:
        return None
    return cast(dict[str, Any], json.loads(snapshot.payload))


def revoke_consent(
    data_root: Path,
    character_id: str,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    expected_revision: int,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    return _change_consent(
        data_root=data_root,
        character_id=character_id,
        permissions=(),
        schemas=schemas,
        namespace=namespace,
        version=None,
        workspace_root=workspace_root,
        expected_revision=expected_revision,
        revoke=True,
        consent_id=consent_id,
        limits=limits,
    )
```

Capture the caller sequence before the first callback. Reject unknown,
duplicate, or empty input, then normalize a valid set to the fixed canonical
order before artifact construction. Caller order is not semantically
significant; stored schema artifacts are always canonical. Derive consent ID
as:

```python
payload = {
    "scope": key.scope,
    "workspace_id": key.workspace_id,
    "namespace": key.namespace,
    "character_id": key.character_id,
}
consent_id = f"consent-{sha256(canonical_bytes(payload)).hexdigest()[:32]}"
```

Resolve the exact installation with the existing Task 14 resolver, collecting
its compiled result and boundary audits. Under the character lock, load and
verify every history revision before calculating the successor. Publish the
new immutable history file first, then atomically replace `current.json`, then
recheck history membership, current bytes, installation, workspace, and caller
inputs before success.

Add an internal frozen `ActiveConsent` snapshot containing canonical consent
bytes, exact binding, compiled bytes, permission, and audit functions. Its
`assert_clean()` must be called after every later schema callback and directly
before every domain write/return.

- [ ] **Step 5: Run consent GREEN with installer/default regressions**

Run:

```powershell
python -m pytest tests/unit/test_persistence_consent.py `
  tests/security/test_persistence_security.py `
  tests/unit/test_character_defaults.py `
  tests/integration/test_character_defaults_integration.py -q `
  -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t3-green
```

Expected: all runnable tests pass.

- [ ] **Step 6: Commit consent lifecycle**

```powershell
git add src/kokoroarc/persistence/consent.py tests/persistence_support.py `
  tests/unit/test_persistence_consent.py `
  tests/security/test_persistence_security.py
git diff --cached --check
git commit -m "feat: add explicit persistence consent"
```

### Task 4: Persist and replay relationship state

**Files:**
- Create: `src/kokoroarc/persistence/state.py`
- Create: `tests/unit/test_persistent_state.py`
- Modify: `tests/persistence_support.py`
- Modify: `tests/security/test_persistence_security.py`

- [ ] **Step 1: Write RED initial-state, apply, CAS, and replay tests**

Add a schema-valid event helper:

```python
def interaction_event(
    event_id: str,
    relationship_revision: int,
    *,
    trust: float = 2.0,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": f"event/{event_id}",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "event_id": event_id,
        "turn_id": f"turn-{relationship_revision + 1}",
        "origin": "verified_task_outcome",
        "novelty_key": f"novelty-{event_id}",
        "expected_state_revision": relationship_revision,
        "evaluator_version": "interaction-v1",
        "evidence": {"kind": "test_result", "reference": "pytest"},
        "confidence": 1.0,
        "effects": {"trust": trust},
    }
```

The primary control is:

```python
def test_relationship_apply_is_outer_cas_idempotent_and_replayable(
    consented_rin: ConsentedRin,
) -> None:
    first = apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("event-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="relationship-operation-1",
    )
    duplicate = apply_persistent_relationship_event(
        consented_rin.data_root,
        "rin-aster",
        interaction_event("event-1", 0),
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
        expected_state_revision=0,
        operation_id="relationship-operation-1",
    )

    assert first["revision"] == 1
    assert first["relationship"]["revision"] == 1
    assert first["relationship"]["dimensions"]["trust"] == 2.0
    assert duplicate == first
    assert replay_persistent_state(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == first
```

Add absent read-only load, wrong permission, revoked consent, stale outer
revision, stale embedded relationship revision, changed bytes under reused
operation/event IDs, exact compiled growth parameters, frozen algorithm replay,
event/hash-chain gaps, duplicate revisions, projection repair, capacity, and
concurrent process CAS tests.

- [ ] **Step 2: Run relationship RED**

Run:

```powershell
python -m pytest tests/unit/test_persistent_state.py `
  tests/security/test_persistence_security.py `
  -k "relationship or replay or projection or state_revision" -q `
  -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t4-red
```

Expected: fail because persistent state APIs are absent.

- [ ] **Step 3: Implement initial envelope and deterministic replay**

Expose these signatures:

```python
def load_persistent_state(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any] | None:
    return _load_or_replay(
        data_root,
        character_id,
        schemas,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
        repair=False,
    )


def replay_persistent_state(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any] | None:
    return _replay_read_only(
        data_root,
        character_id,
        schemas,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
```

`_initial_state(active_consent)` creates outer revision zero, a canonical
relationship revision-zero state, neutral mood, no operation IDs, and null
last-event hash. Replay starts only from this constructor, validates every
event and hash transition, dispatches by the recorded frozen algorithm, and
compares the final canonical bytes to the projection when present.

- [ ] **Step 4: Implement relationship apply and recovery ordering**

Add the exact mutating signature:

```python
def apply_persistent_relationship_event(
    data_root: Path,
    character_id: str,
    event: Mapping[str, Any],
    consent_id: str,
    consent_revision: int,
    schemas: SchemaValidator,
    *,
    expected_state_revision: int,
    operation_id: str,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    return _apply_state_operation(
        data_root=data_root,
        character_id=character_id,
        operation_kind="relationship",
        operation_payload=event,
        consent_id=consent_id,
        consent_revision=consent_revision,
        schemas=schemas,
        expected_state_revision=expected_state_revision,
        operation_id=operation_id,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
```

Under the character lock, recover a pending projection, require active
`relationship_state` consent, load its compiled growth values, replay current
state, check both revisions, and call `apply_event_v1` on detached inputs.
Construct the complete event with predecessor hashes and validate it before
publication. Publish the immutable event as the commit point, atomically write
the state projection, update the generation pointer, and re-audit all inputs,
consent, installation, event membership, hashes, lock, and ancestry.

Never use caller operation or event IDs as path fragments. Name each event
with its fixed-width revision plus the first 32 hex characters of the SHA-256
of the canonical operation ID; retain the full caller ID only inside the closed
event artifact.

If the event is visible but projection/pointer write fails, raise
`PERSISTENCE_STATE_WRITE_FAILED` with `record_state: committed`. The next
locked mutation repairs projections from the journal before applying anything.

- [ ] **Step 5: Run relationship GREEN and existing transition suites**

Run:

```powershell
python -m pytest tests/unit/test_persistent_state.py `
  tests/security/test_persistence_security.py tests/unit/test_transitions.py `
  tests/unit/test_session_store.py tests/integration/test_state_transactions.py `
  -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t4-green
```

Expected: all tests pass and existing session behavior remains byte-stable.

- [ ] **Step 6: Commit relationship persistence**

```powershell
git add src/kokoroarc/persistence/state.py `
  tests/persistence_support.py tests/unit/test_persistent_state.py `
  tests/security/test_persistence_security.py
git diff --cached --check
git commit -m "feat: persist relationship state"
```

### Task 5: Add bounded explicit mood transitions

**Files:**
- Modify: `schemas/v1/persistent-state-event.schema.json`
- Modify: `src/kokoroarc/persistence/state.py`
- Modify: `tests/unit/test_standalone_schemas.py`
- Modify: `tests/unit/test_persistent_state.py`
- Modify: `tests/security/test_persistence_security.py`

- [ ] **Step 1: Write RED mood update, separation, and expiry tests**

Use this exact explicit event shape:

```python
def mood_event(event_id: str, mood_revision: int) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "expected_mood_revision": mood_revision,
        "primary": "pleased",
        "secondary": "focused",
        "arousal": 0.35,
        "valence": 0.4,
        "intensity": 0.42,
        "expires_after_turns": 3,
        "triggering_interaction_event_id": "event-1",
        "trigger_strength": "ordinary",
    }
```

Assert a mood update increments outer and mood revisions but not relationship
revision; a relationship event does the inverse. Assert each requires its own
permission. Advancing one turn decrements remaining turns, and advancing to
zero returns exactly to neutral while preserving the outer journal history.

Add RED boundaries for all twelve moods, invalid secondary equality, missing
trigger, values outside numeric bounds, ordinary intensity jump above 0.35,
ordinary strong-valence sign reversal, strong trigger acceptance, wrong mood
revision, duplicate event ID with changed bytes, and advance past expiry.

- [ ] **Step 2: Run mood RED**

Run:

```powershell
python -m pytest tests/unit/test_persistent_state.py `
  tests/unit/test_standalone_schemas.py `
  tests/security/test_persistence_security.py -k "mood or permission" -q `
  -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t5-red
```

Expected: fail because mood APIs and `trigger_strength` are absent.

- [ ] **Step 3: Close mood schema and implement deterministic updates**

Add `trigger_strength` with enum `ordinary` or `strong` to the mood-update
payload. Implement:

```python
def apply_persistent_mood_event(
    data_root: Path,
    character_id: str,
    event: Mapping[str, Any],
    consent_id: str,
    consent_revision: int,
    schemas: SchemaValidator,
    *,
    expected_state_revision: int,
    operation_id: str,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    return _apply_state_operation(
        data_root=data_root,
        character_id=character_id,
        operation_kind="mood_update",
        operation_payload=event,
        consent_id=consent_id,
        consent_revision=consent_revision,
        schemas=schemas,
        expected_state_revision=expected_state_revision,
        operation_id=operation_id,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
```

For `ordinary`, reject an intensity delta over 0.35 and reject a valence sign
change when both old and target absolute valence are at least 0.5. `strong`
may use the full schema range. Never infer a target value.

Add:

```python
def advance_persistent_mood_turn(
    data_root: Path,
    character_id: str,
    consent_id: str,
    consent_revision: int,
    schemas: SchemaValidator,
    *,
    expected_state_revision: int,
    expected_mood_revision: int,
    operation_id: str,
    turns: int = 1,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    payload = {
        "event_id": operation_id,
        "expected_mood_revision": expected_mood_revision,
        "turns": turns,
    }
    return _apply_state_operation(
        data_root=data_root,
        character_id=character_id,
        operation_kind="mood_advance",
        operation_payload=payload,
        consent_id=consent_id,
        consent_revision=consent_revision,
        schemas=schemas,
        expected_state_revision=expected_state_revision,
        operation_id=operation_id,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
```

- [ ] **Step 4: Run mood GREEN and replay the mixed journal**

Run:

```powershell
python -m pytest tests/unit/test_persistent_state.py `
  tests/unit/test_standalone_schemas.py `
  tests/security/test_persistence_security.py -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t5-green
```

Expected: all tests pass; a mixed relationship/mood journal replays to exact
canonical state bytes.

- [ ] **Step 5: Commit mood persistence**

```powershell
git add schemas/v1/persistent-state-event.schema.json `
  src/kokoroarc/persistence/state.py `
  tests/unit/test_standalone_schemas.py `
  tests/unit/test_persistent_state.py `
  tests/security/test_persistence_security.py
git diff --cached --check
git commit -m "feat: add bounded persistent mood state"
```

### Task 6: Store only explicit bounded memory references

**Files:**
- Create: `src/kokoroarc/persistence/memory.py`
- Create: `tests/unit/test_memory_references.py`
- Modify: `tests/persistence_support.py`
- Modify: `tests/security/test_persistence_security.py`

- [ ] **Step 1: Write RED add/list/idempotency/conflict tests**

Use this control:

```python
def test_add_list_and_remove_reference_never_embeds_host_memory(
    consented_rin: ConsentedRin,
) -> None:
    added = add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        "host-memory-preference-01",
        "The user approved concise technical explanations.",
        {"en-US": "The user approved concise technical explanations."},
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )
    repeated = add_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        "host-memory-preference-01",
        "The user approved concise technical explanations.",
        {"en-US": "The user approved concise technical explanations."},
        consented_rin.consent["consent_id"],
        consented_rin.consent["grant_revision"],
        SCHEMAS,
    )

    listed = list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    )
    assert repeated == added
    assert [item.reference for item in listed] == [added]
    assert listed[0].active_consent_generation is True
    assert "content" not in canonical_bytes(added).decode("utf-8")

    removed = remove_memory_reference(
        consented_rin.data_root,
        "rin-aster",
        added["memory_reference_id"],
        consented_rin.consent["consent_id"],
        SCHEMAS,
        identifier_kind="memory_reference_id",
    )
    assert removed.removed is True
    assert list_memory_references(
        consented_rin.data_root,
        "rin-aster",
        SCHEMAS,
    ) == ()
```

Add deterministic ID/content-hash assertions, canonical locale ordering,
global/workspace separation, exact retry, changed summary under reused host ID,
wrong consent/permission, revoked add denial, list after revoke marked inactive,
remove after revoke, remove by host ID, absent exact-id no-op, entry capacity,
and deterministic detached return tests.

Start with an absent-list control. It must return `()` and leave the entire
`memory-references` root absent, proving that list is a read-only operation.

- [ ] **Step 2: Write RED harvesting and non-echoing detector tests**

Parametrize summary/localized-summary content with credential assignments,
Authorization bearer tokens, private-key blocks, Windows/POSIX absolute paths,
file URIs, control characters, role-prefixed transcript blocks, prompt logs,
tool-result dumps, and mixed mapping-key attacks. Assert:

```python
def test_memory_detector_rejects_without_echo_or_write(
    consented_rin: ConsentedRin,
    secret_value: str,
) -> None:
    memory_root = (
        consented_rin.data_root
        / "memory-references"
        / "global"
        / "original"
        / "rin-aster"
    )
    with pytest.raises(KokoroError) as raised:
        add_memory_reference(
            consented_rin.data_root,
            "rin-aster",
            "host-memory-security-probe",
            secret_value,
            {"en-US": secret_value},
            consented_rin.consent["consent_id"],
            consented_rin.consent["grant_revision"],
            SCHEMAS,
        )

    envelope = canonical_bytes(raised.value.envelope()).decode("utf-8")
    assert raised.value.code == "PERSISTENCE_MEMORY_CONTENT_REJECTED"
    assert secret_value not in envelope
    assert not memory_root.exists()
```

Include safe controls containing ordinary colons, URLs without credentials,
short quoted dialogue descriptions, and localized punctuation.

- [ ] **Step 3: Run memory RED**

Run:

```powershell
python -m pytest tests/unit/test_memory_references.py `
  tests/security/test_persistence_security.py `
  -k "memory or summary or harvest or secret or transcript" -q `
  -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t6-red
```

Expected: fail because memory-reference APIs are absent.

- [ ] **Step 4: Implement deterministic references and safe views**

Create the detached view/result types:

```python
@dataclass(frozen=True, slots=True)
class MemoryReferenceView:
    payload: bytes
    active_consent_generation: bool

    @property
    def reference(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.payload))


@dataclass(frozen=True, slots=True)
class MemoryRemovalResult:
    removed: bool
    memory_reference_id: str | None
```

Expose these exact signatures:

```python
def add_memory_reference(
    data_root: Path,
    character_id: str,
    host_memory_id: str,
    summary: str,
    localized_summaries: Mapping[str, str],
    consent_id: str,
    consent_revision: int,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    return _add_memory_reference(
        data_root,
        character_id,
        host_memory_id,
        summary,
        localized_summaries,
        consent_id,
        consent_revision,
        schemas,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )


def list_memory_references(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> Sequence[MemoryReferenceView]:
    return _list_memory_references(
        data_root,
        character_id,
        schemas,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )


def remove_memory_reference(
    data_root: Path,
    character_id: str,
    identifier: str,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    identifier_kind: Literal["host_memory_id", "memory_reference_id"],
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> MemoryRemovalResult:
    return _remove_memory_reference(
        data_root,
        character_id,
        identifier,
        consent_id,
        schemas,
        identifier_kind=identifier_kind,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
```

The content hash payload is exactly:

```python
content = {
    "host_memory_id": host_memory_id,
    "summary": summary,
    "localized_summaries": {
        locale: localized_summaries[locale]
        for locale in sorted(localized_summaries)
    },
}
content_hash = sha256(canonical_bytes(content)).hexdigest()
memory_reference_id = (
    "memory-"
    + sha256(
        canonical_bytes(
            {
                "scope": active.key.scope,
                "workspace_id": active.key.workspace_id,
                "namespace": active.key.namespace,
                "character_id": active.key.character_id,
                "host_memory_id": host_memory_id,
            }
        )
    ).hexdigest()[:32]
)
```

Run the bounded detector before schema callbacks. It returns only enum-like
reason codes and never the matched value. Publish one exclusive canonical file
by generated ID. On exact retry, require the retained file and consent/member
snapshots to remain unchanged before returning.

Removal may use active, revoked, or superseded consent with the same stable
consent ID. Resolve the identifier through a bounded scan, retain exact file
and parent identity, and unlink only that verified single-link regular file.
Refuse a missing-by-host-ID result because absence cannot identify an exact
artifact; allow an absent generated memory-reference ID as an idempotent no-op
only after a stable bounded membership scan.

- [ ] **Step 5: Run memory GREEN**

Run:

```powershell
python -m pytest tests/unit/test_memory_references.py `
  tests/security/test_persistence_security.py `
  tests/unit/test_persistence_consent.py -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t6-green
```

Expected: all tests pass.

- [ ] **Step 6: Commit memory references**

```powershell
git add src/kokoroarc/persistence/memory.py `
  tests/persistence_support.py tests/unit/test_memory_references.py `
  tests/security/test_persistence_security.py
git diff --cached --check
git commit -m "feat: add bounded memory references"
```

### Task 7: Add canonical export and explicit scoped reset

**Files:**
- Modify: `src/kokoroarc/persistence/state.py`
- Modify: `src/kokoroarc/persistence/memory.py`
- Modify: `tests/unit/test_persistent_state.py`
- Modify: `tests/unit/test_memory_references.py`
- Modify: `tests/security/test_persistence_security.py`

- [ ] **Step 1: Write RED export and currentness tests**

Create relationship, mood, and memory data, revoke consent, then assert export
still succeeds and is schema-valid:

```python
exported = export_persistent_data(
    data_root,
    "rin-aster",
    SCHEMAS,
)
SCHEMAS.validate("persistence-export", exported)
assert exported["consent"]["status"] == "revoked"
assert exported["state"]["revision"] == 2
assert exported["memory_count"] == 1
assert "path" not in canonical_bytes(exported).decode("utf-8").lower()
```

Call export twice and require exact canonical bytes. Mutate consent, event,
state projection, memory membership, workspace identity, caller character, and
schema-retained objects during callbacks; every changed byte must fail rather
than produce an export. Prove export never dereferences a host memory ID.

- [ ] **Step 2: Write RED preview/reset/recovery tests**

Use `preview_persistent_reset` for each target and require an exact preview hash
at apply time. Assert:

- relationship reset preserves mood and memory, resets embedded relationship
  to revision zero, and appends one outer journal event;
- mood reset preserves relationship and memory and returns exact neutral mood;
- memory reset preserves state and removes only captured generated entries;
- all reset performs all three under one transaction marker;
- reset works after revocation with the same consent ID;
- wrong consent/scope/character/installation or changed preview fails;
- repeat with the same reset ID and bytes is idempotent; and
- every marker/rename/projection/fsync/cleanup failure recovers to the recorded
  `not_visible`, `committed`, or `unknown` state.

- [ ] **Step 3: Run export/reset RED**

Run:

```powershell
python -m pytest tests/unit/test_persistent_state.py `
  tests/unit/test_memory_references.py `
  tests/security/test_persistence_security.py `
  -k "export or reset or revoke or recovery" -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t7-red
```

Expected: fail because export/reset APIs are absent.

- [ ] **Step 4: Implement canonical export**

Add:

```python
def export_persistent_data(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    captured = _capture_export_inputs(
        data_root,
        character_id,
        schemas,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
    exported = _assemble_export(captured)
    _validate_export(exported, captured)
    captured.assert_clean()
    return _detached(exported)
```

Capture consent, current pointer, current generation, complete event membership
and digest, memory membership, caller values, scope, and workspace before the
first callback. Compute `export_sha256` over the same object with that field
temporarily null. Validate a detached report and rerun every audit before
return.

- [ ] **Step 5: Implement reset preview/apply and transaction recovery**

Create:

```python
@dataclass(frozen=True, slots=True)
class PersistentResetPreview:
    payload: bytes

    @property
    def document(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.payload))
```

Expose these exact signatures:

```python
def preview_persistent_reset(
    data_root: Path,
    character_id: str,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    target: Literal["relationship", "mood", "memory", "all"],
    reset_id: str,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> PersistentResetPreview:
    captured = _capture_reset_inputs(
        data_root,
        character_id,
        consent_id,
        schemas,
        target=target,
        reset_id=reset_id,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
    return PersistentResetPreview(_assemble_reset_preview(captured))


def reset_persistent_data(
    data_root: Path,
    character_id: str,
    preview: PersistentResetPreview,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    return _apply_reset(
        data_root,
        character_id,
        preview,
        consent_id,
        schemas,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
```

The preview document binds scope, workspace, character, consent ID,
installation, current state/event/memory hashes, expected state revision,
exact memory IDs, and its own SHA-256.

Relationship/mood reset use closed append-only state events. Memory reset
creates a transaction marker, atomically renames the captured entries directory
to a same-parent cleanup name, confirms empty visible membership, and deletes
only the retained renamed identity. `all` records the state events and memory
cutover phases in one marker so recovery never guesses.

- [ ] **Step 6: Run export/reset GREEN**

Run:

```powershell
python -m pytest tests/unit/test_persistent_state.py `
  tests/unit/test_memory_references.py `
  tests/security/test_persistence_security.py -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t7-green
```

Expected: all tests pass.

- [ ] **Step 7: Commit export/reset**

```powershell
git add src/kokoroarc/persistence/state.py `
  src/kokoroarc/persistence/memory.py `
  tests/unit/test_persistent_state.py `
  tests/unit/test_memory_references.py `
  tests/security/test_persistence_security.py
git diff --cached --check
git commit -m "feat: export and reset persistent data"
```

### Task 8: Add declarative replay-verified state migration

**Files:**
- Create: `src/kokoroarc/persistence/migrations.py`
- Create: `tests/unit/test_persistent_migrations.py`
- Modify: `tests/persistence_support.py`
- Modify: `tests/security/test_persistence_security.py`

- [ ] **Step 1: Write RED two-installation preview/apply tests**

In `tests/persistence_support.py`, copy Rin to a temporary pack, change only
`character_version` to `1.1.0`, generate a fresh verified release with
`verified_release_factory`, build/install its archive, and grant the successor
target consent revision.

The main migration test must:

1. apply two source relationship events and one mood event under version 1.0.0;
2. install 1.1.0 and explicitly regrant consent to it;
3. prove ordinary state writes now fail as stale;
4. preview `preserve_identical_contract` migration;
5. validate the plan and apply it;
6. replay the target generation independently; and
7. prove the new current state binds 1.1.0 while the old generation remains.

Assert a second identical apply returns the exact current target state. Add
`reset_neutral` coverage and confirm relationship dimensions replay while mood
is neutral.

Add explicit target-permission ceilings:

- nonzero source relationship state requires target `relationship_state`;
- `preserve_identical_contract` with non-neutral source mood requires target
  `mood_state`;
- `reset_neutral` may proceed without target `mood_state` when relationship
  migration remains authorized; and
- memory references are never copied. They remain bound to the source
  installation and keep that installation removal-blocked until explicitly
  removed.

- [ ] **Step 2: Write RED stale/unsupported/failure tests**

Cover changed source journal/state, changed target consent or installation,
changed plan bytes, target replay hash mismatch, missing history grant, unknown
event/algorithm/state contract, mood preserve across a changed mood contract,
generation capacity, target generation collision, pointer cutover failure,
parent-fsync failure, recovery marker mutation, and source/target path swap.

Assert the schema rejects any executable field and runtime never imports,
evaluates, shells, or dispatches a callable from the plan.

- [ ] **Step 3: Run migration RED**

Run:

```powershell
python -m pytest tests/unit/test_persistent_migrations.py `
  tests/security/test_persistence_security.py -k "migration or generation" -q `
  -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t8-red
```

Expected: fail because state migration APIs are absent.

- [ ] **Step 4: Implement deterministic preview**

Expose:

```python
def preview_state_migration(
    data_root: Path,
    character_id: str,
    target_consent_id: str,
    target_consent_revision: int,
    schemas: SchemaValidator,
    *,
    mood_strategy: Literal[
        "preserve_identical_contract",
        "reset_neutral",
    ],
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    captured = _capture_migration_inputs(
        data_root,
        character_id,
        target_consent_id,
        target_consent_revision,
        schemas,
        mood_strategy=mood_strategy,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
    return _migration_plan(captured)
```

The capture proves the current state matches a retained source consent history
artifact and the active target consent exactly. Treat target permissions as an
upper bound: replay nonzero relationship data only with
`relationship_state`; preserve non-neutral mood only with `mood_state`; and
allow `reset_neutral` without mood permission. Re-emit relationship/reset
events through target growth rules. Preserve mood by replaying mood events only
when the mood contract version is identical; otherwise only reset is allowed.
Never migrate memory references. Append a closed migration marker and compute
the target replay/state hashes.

- [ ] **Step 5: Implement staged generation apply and recovery**

Expose this exact apply signature:

```python
def apply_state_migration(
    data_root: Path,
    character_id: str,
    target_consent_id: str,
    target_consent_revision: int,
    plan: Mapping[str, Any],
    schemas: SchemaValidator,
    *,
    mood_strategy: Literal[
        "preserve_identical_contract",
        "reset_neutral",
    ],
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    return _apply_migration(
        data_root,
        character_id,
        target_consent_id,
        target_consent_revision,
        plan,
        schemas,
        mood_strategy=mood_strategy,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
```

Capture canonical plan bytes before callbacks and require exact recomputed
preview bytes.

Under the character lock:

1. write a marker with source/current and target/staging identities;
2. create and retain the target generation directory identity;
3. write each re-emitted immutable event in revision order;
4. replay only staged event bytes and compare the expected target hash;
5. write the target projection and fsync every file/directory;
6. atomically replace the small `current.json` pointer;
7. fsync the pointer parent;
8. confirm target replay/current pointer and all inputs without callbacks; and
9. remove only the captured marker.

Before pointer cutover, failure removes only the identified target staging
generation. After cutover, recovery finishes/validates the target and retains
the source generation. Never recursively delete an unidentified replacement.

- [ ] **Step 6: Run migration GREEN**

Run:

```powershell
python -m pytest tests/unit/test_persistent_migrations.py `
  tests/unit/test_persistent_state.py `
  tests/security/test_persistence_security.py -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t8-green
```

Expected: all tests pass.

- [ ] **Step 7: Commit state migration**

```powershell
git add src/kokoroarc/persistence/migrations.py `
  tests/persistence_support.py tests/unit/test_persistent_migrations.py `
  tests/security/test_persistence_security.py
git diff --cached --check
git commit -m "feat: add replay verified state migration"
```

### Task 9: Block installation removal on exact persistent references

**Files:**
- Modify: `src/kokoroarc/persistence/_storage.py`
- Modify: `src/kokoroarc/distribution/installer.py:1536-1681`
- Modify: `tests/unit/test_karc_installer.py`
- Modify: `tests/integration/test_karc_installer_integration.py`
- Modify: `tests/security/test_karc_installer_security.py`

- [ ] **Step 1: Write RED blocker lifecycle tests**

For one installed release, write four explicit tests. Each calls
`remove_installed_pack(data_root, "original", "rin-aster", "1.0.0",
SCHEMAS)` and asserts `KARC_REMOVE_REFERENCED` with only its expected label:

1. grant consent and expect `persistence_consent`;
2. apply one relationship event, revoke consent, and expect
   `persistent_state`;
3. add one memory reference, revoke consent, reset state if present, and expect
   `memory_reference`; and
4. install a successor, preview migration, then fault
   `_replace_current_generation_pointer` after the real bounded migration
   marker is durably visible. Expect `state_migration` while the marker remains.

The fourth test must use the ordinary `apply_state_migration` API plus
`monkeypatch` on that single internal cutover function. It must not fabricate a
marker file or bypass schema/storage validation.

Add controls proving revoked consent alone does not block, historical state
generation alone does not block after target migration, unrelated scope/
character/version does not block, and reset/removed memory clears blockers.

- [ ] **Step 2: Write RED bounded scan and creation-race tests**

Add over-limit hidden/unknown entries, unsafe links, malformed JSON, changed
membership during schema callbacks, and direct-scandir consumption assertions.
Race a grant, memory add, first state apply, and migration marker against the
final removal scan. The removal or new reference may win, but both must never
report success with a dangling reference.

- [ ] **Step 3: Run removal RED**

Run:

```powershell
python -m pytest tests/unit/test_karc_installer.py `
  tests/integration/test_karc_installer_integration.py `
  tests/security/test_karc_installer_security.py `
  -k "persistence or reference or removal" -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t9-red
```

Expected: removal incorrectly succeeds because persistent roots are not yet
scanned.

- [ ] **Step 4: Implement shared reference lock and bounded blockers**

In `_storage.py`, expose only these installer-facing internal capabilities:

```python
@contextmanager
def persistence_reference_lock(
    data_root: Path,
    scope: InstallScope,
    namespace: str,
    character_id: str,
) -> Iterator[PersistenceLock]:
    lock = _acquire_character_lock(
        data_root,
        PersistenceKey(
            scope=scope.kind,
            workspace_id=scope.workspace_id,
            namespace=namespace,
            character_id=character_id,
        ),
    )
    with lock:
        yield lock


def persistence_reference_blockers(
    data_root: Path,
    scope: InstallScope,
    installation: Mapping[str, Any],
    schemas: SchemaValidator,
    *,
    limits: PersistenceLimits = PersistenceLimits(),
) -> list[str]:
    return _scan_reference_snapshot(
        data_root,
        scope,
        installation,
        schemas,
        limits,
    ).blockers
```

Every reference-creating Task 15 mutation must already hold this same
character lock. In `remove_installed_pack`, acquire locks in the fixed order
registry lock then persistence character lock, call the bounded scanner before
the removal journal/cutover, retain membership identities through cutover, and
merge its sorted blocker labels into `_reference_blockers`.

Scan only current active consent, current state pointer/generation, every
retained memory entry, and incomplete migration marker in the selected scope.
Validate exact schemas and installation fields; reject malformed/unsafe
reference storage rather than ignoring it.

- [ ] **Step 5: Run removal GREEN with full installer regressions**

Run:

```powershell
python -m pytest tests/unit/test_karc_installer.py `
  tests/integration/test_karc_installer_integration.py `
  tests/security/test_karc_installer_security.py `
  tests/unit/test_persistence_consent.py `
  tests/unit/test_memory_references.py `
  tests/unit/test_persistent_migrations.py -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t9-green
```

Expected: all runnable tests pass.

- [ ] **Step 6: Commit persistent removal guards**

```powershell
git add src/kokoroarc/persistence/_storage.py `
  src/kokoroarc/distribution/installer.py `
  tests/unit/test_karc_installer.py `
  tests/integration/test_karc_installer_integration.py `
  tests/security/test_karc_installer_security.py
git diff --cached --check
git commit -m "feat: guard removal with persistent references"
```

### Task 10: Close adversarial mutation, storage, and failure windows

**Files:**
- Modify: `src/kokoroarc/persistence/_storage.py`
- Modify: `src/kokoroarc/persistence/consent.py`
- Modify: `src/kokoroarc/persistence/state.py`
- Modify: `src/kokoroarc/persistence/memory.py`
- Modify: `src/kokoroarc/persistence/migrations.py`
- Modify: `tests/security/test_persistence_security.py`

- [ ] **Step 1: Add the complete retained-alias mutation matrix**

For each external schema callback phase, retain and mutate each object the
pipeline supplied or received. The matrix must include:

```python
MUTATION_CASES = (
    "caller_permissions",
    "caller_interaction_event",
    "caller_mood_event",
    "caller_summaries",
    "caller_reset_preview",
    "caller_migration_plan",
    "consent_schema_input",
    "state_schema_input",
    "event_schema_input",
    "memory_schema_input",
    "export_schema_input",
    "migration_schema_input",
    "compiled_installation_input",
    "transition_state_input",
    "transition_event_input",
    "transition_output",
    "migration_replay_output",
)
```

Test direct mutation, later-phase mutation, A-to-B-to-A restoration, mutation
during final report validation, and closed-over caller mutation. Every case
must raise `PERSISTENCE_INPUT_MUTATION`; none may return a successful artifact
whose inputs changed during the call.

- [ ] **Step 2: Add the complete filesystem/race/resource matrix**

Parametrize every durable root, ancestor, lock, current pointer, history file,
event, state projection, memory entry, generation, marker, and staging node
with these attacks where the host supports them:

```python
FILESYSTEM_ATTACKS = (
    "symlink",
    "junction",
    "reparse_point",
    "hardlink",
    "fifo_or_special_file",
    "ancestor_swap",
    "same_name_replacement",
    "case_collision",
    "membership_insert",
    "membership_remove",
    "scan_then_grow",
    "scan_then_chmod_executable",
)
```

Add exact max + 1 cases for files, consent history, state generations, events,
memory entries, transaction markers, nested JSON depth, summary length,
aggregate journal bytes, and total directory entries including hidden or
unknown names. Instrument `os.scandir` so the test proves enumeration stops at
limit + 1 rather than materializing the directory.

Add a no-capability test that patches `socket.create_connection`,
`subprocess.Popen`, and `threading.Thread.start` to raise an assertion. Exercise
grant/show/revoke, relationship/mood apply, memory add/list/remove,
export/reset, and migration preview/apply through local fixtures. No Task 15
domain call may attempt network, subprocess, browser, upload, or background
work.

Parametrize every code in the stable error contract. Assert the public code is
exact, detail keys are limited to `phase`, `reason`, `limit`, `operation`, and
`record_state`, textual values are closed enums no longer than 64 characters,
and serialized envelopes contain none of the supplied path, consent, event,
memory, summary, or secret probes.

- [ ] **Step 3: Add every publication and cleanup failure window**

Inject failure before and after each open, write, flush, file fsync, immutable
publish, projection replacement, pointer replacement, directory fsync, marker
update, confirmation read, and cleanup call. Assert exact record state,
recoverability, no false success, and no deletion of a replacement.

Include the durability retry regression: when a record is visible but its
parent fsync failed, an identical retry must retry the fsync and cannot return
from an idempotent-visible branch first.

Take before/after filesystem inventories of the test workspace, data root
parent, and a sentinel directory. Successful and failed operations may change
only the exact data root paths declared by the operation.

- [ ] **Step 4: Run the expanded security suite RED**

Run:

```powershell
python -m pytest tests/security/test_persistence_security.py -q `
  -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t10-red
```

Expected: new mutants expose any missing final audit, resource cap, identity
check, durability retry, or cleanup state.

- [ ] **Step 5: Make every security mutant fail closed**

Centralize final detached validation so every domain uses the same ordering:

```python
def validate_and_finalize(
    schema_name: str,
    value: Mapping[str, Any],
    boundary: PersistenceBoundary,
) -> dict[str, Any]:
    payload = canonical_bytes(dict(value))
    probe = json.loads(payload)
    boundary.schemas.validate(schema_name, probe)
    if canonical_bytes(probe) != payload:
        boundary.fail("schema_input_mutation")
    boundary.assert_clean()
    result = cast(dict[str, Any], json.loads(payload))
    boundary.assert_clean()
    return result
```

Mutation probes remain active until immediately before function return. For a
write, recheck the logical commit point, retained parent/node identities, lock,
caller inputs, consent, installation, and relevant membership after the last
callback. After visibility, use only callback-free byte/identity confirmation.

Keep cleanup identity-bound. When identity capture itself fails after creation,
delete nothing and raise `PERSISTENCE_CLEANUP_FAILED` with
`record_state: not_visible`. Never hide cleanup/durability/unknown-state errors
behind the earlier domain exception.

- [ ] **Step 6: Run security GREEN with adjacent storage suites**

Run:

```powershell
python -m pytest tests/security/test_persistence_security.py `
  tests/security/test_karc_installer_security.py `
  tests/security/test_character_defaults_security.py `
  tests/unit/test_persistence_storage.py -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t10-green
```

Expected: all runnable tests pass; every skip is a named missing platform
capability.

- [ ] **Step 7: Commit the security closure**

```powershell
git add src/kokoroarc/persistence/_storage.py `
  src/kokoroarc/persistence/consent.py `
  src/kokoroarc/persistence/state.py `
  src/kokoroarc/persistence/memory.py `
  src/kokoroarc/persistence/migrations.py `
  tests/security/test_persistence_security.py
git diff --cached --check
git commit -m "test: harden consented persistence boundaries"
```

### Task 11: Export the API and prove the installed workflow

**Files:**
- Modify: `src/kokoroarc/persistence/__init__.py`
- Create: `tests/integration/test_persistence_workflow.py`
- Modify: `tests/integration/test_research_cli.py:10-88`
- Modify: `tests/integration/test_research_cli.py:490-660`

- [ ] **Step 1: Write RED stable-import and package inventory tests**

Add:

```python
REQUIRED_PERSISTENCE_MODULES = {
    f"kokoroarc/persistence/{name}.py"
    for name in (
        "__init__",
        "_storage",
        "consent",
        "memory",
        "migrations",
        "state",
    )
}
```

Add the four new schemas to `REQUIRED_STANDALONE_SCHEMAS`. Extend the wheel
probe to import every stable Task 15 type/function from
`kokoroarc.persistence` and assert each function is callable.

- [ ] **Step 2: Write RED global/workspace/process workflow tests**

The global integration test must perform this exact sequence through public
APIs:

1. install verified Rin;
2. prove no persistence roots exist;
3. grant all three permissions;
4. apply relationship and mood events;
5. add one memory reference;
6. replay from a fresh Python process;
7. export exact data;
8. revoke and prove writes fail;
9. reset relationship/mood and remove memory after revoke;
10. prove installation removal now succeeds.

The workspace test repeats the workflow in one explicit workspace while a
global installation/consent remains unchanged. Add a session control proving
`SessionStore.start/apply/end` creates only session paths and never calls a
persistence API.

- [ ] **Step 3: Run public/package RED**

Run:

```powershell
python -m pytest tests/integration/test_persistence_workflow.py `
  tests/integration/test_research_cli.py `
  -k "persistence or built_archives" -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t11-red
```

Expected: stable exports and package inventory fail because the Task 15 public
names and new inventory entries are absent.

- [ ] **Step 4: Publish the stable Task 15 API**

Export exactly:

```python
from kokoroarc.persistence.consent import (
    grant_consent,
    load_consent,
    revoke_consent,
)
from kokoroarc.persistence.memory import (
    MemoryReferenceView,
    MemoryRemovalResult,
    add_memory_reference,
    list_memory_references,
    remove_memory_reference,
)
from kokoroarc.persistence.migrations import (
    apply_state_migration,
    preview_state_migration,
)
from kokoroarc.persistence.state import (
    PersistentResetPreview,
    advance_persistent_mood_turn,
    apply_persistent_mood_event,
    apply_persistent_relationship_event,
    export_persistent_data,
    load_persistent_state,
    preview_persistent_reset,
    replay_persistent_state,
    reset_persistent_data,
)
```

Set `__all__` to those exact names. Do not export `_storage`, lock, path, raw
write, or mutation-audit helpers.

- [ ] **Step 5: Run integration and installed wheel/sdist GREEN**

Run:

```powershell
$package_test = (
  'tests/integration/test_research_cli.py::' +
  'test_built_archives_and_installed_research_cli_are_complete'
)
python -m pytest tests/integration/test_persistence_workflow.py `
  $package_test `
  -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-t11-green
```

Expected: all tests pass. The installed probe runs outside the repository with
repository source absent and imports every persistence API/schema from the
built wheel.

### Task 12: Exact Task 15 closure and feature commit

**Files:**
- Modify: `docs/superpowers/plans/2026-08-14-kokoroarc-completion.md`
- Include: all uncommitted Task 11 files

- [ ] **Step 1: Run the focused Task 15 gate with JUnit evidence**

Run:

```powershell
$env:TMP='D:\tmp'; $env:TEMP='D:\tmp'
$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/unit/test_standalone_schemas.py `
  tests/unit/test_persistence_storage.py `
  tests/unit/test_persistence_consent.py `
  tests/unit/test_persistent_state.py `
  tests/unit/test_memory_references.py `
  tests/unit/test_persistent_migrations.py `
  tests/integration/test_persistence_workflow.py `
  tests/security/test_persistence_security.py -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-focused `
  --junitxml D:\tmp\kokoroarc-task15-focused.xml
```

Expected: zero failures/errors; only documented filesystem-capability skips.

- [ ] **Step 2: Run adjacent state/distribution/schema regressions**

Run:

```powershell
python -m pytest tests/unit/test_transitions.py `
  tests/unit/test_session_store.py tests/integration/test_state_transactions.py `
  tests/unit/test_karc_installer.py `
  tests/integration/test_karc_installer_integration.py `
  tests/security/test_karc_installer_security.py `
  tests/unit/test_character_defaults.py `
  tests/integration/test_character_defaults_integration.py `
  tests/security/test_character_defaults_security.py `
  tests/unit/test_schemas.py -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-adjacent
```

Expected: zero failures/errors; only documented capability skips.

- [ ] **Step 3: Build and verify wheel/sdist from an isolated output root**

Run:

```powershell
$env:PYTHONPYCACHEPREFIX='D:\tmp\kokoroarc-task15-build-pycache'
python -m build --outdir D:\tmp\kokoroarc-task15-dist
$package_test = (
  'tests/integration/test_research_cli.py::' +
  'test_built_archives_and_installed_research_cli_are_complete'
)
python -m pytest $package_test `
  -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-package
```

Expected: build exit 0 and installed archive smoke passes.

- [ ] **Step 4: Run the complete suite**

Run:

```powershell
python -m pytest -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task15-full `
  --junitxml D:\tmp\kokoroarc-task15-full.xml
```

Expected: zero failures/errors; skips are only the suite's documented
platform/capability skips.

- [ ] **Step 5: Run changed-file static and exact-diff gates**

Run:

```powershell
$env:PYTHONPYCACHEPREFIX='D:\tmp\kokoroarc-task15-pycache'
python -m compileall -q -f src/kokoroarc/persistence `
  tests/persistence_support.py tests/unit/test_persistence_storage.py `
  tests/unit/test_persistence_consent.py `
  tests/unit/test_persistent_state.py `
  tests/unit/test_memory_references.py `
  tests/unit/test_persistent_migrations.py `
  tests/integration/test_persistence_workflow.py `
  tests/security/test_persistence_security.py
git diff --check 61a8b3b452589e47e7733dcff425f9117badd625..HEAD
git diff --check
git status --short
```

Also scan changed Python/Markdown lines and require every line to be at most 88
columns. Expected: compile exit 0, both diff checks empty, and status contains
only the intentional final Task 11/meta-plan files.

- [ ] **Step 6: Update the milestone checklist only after evidence is green**

Change only Task 15 checkboxes in
`docs/superpowers/plans/2026-08-14-kokoroarc-completion.md` from `[ ]` to `[x]`.
Leave Tasks 16-18 unchecked and do not claim the complete suite is finished.

- [ ] **Step 7: Stage, audit, and commit the final Task 15 slice**

```powershell
git add src/kokoroarc/persistence/__init__.py `
  tests/integration/test_persistence_workflow.py `
  tests/integration/test_research_cli.py `
  docs/superpowers/plans/2026-08-14-kokoroarc-completion.md
git diff --cached --check
git diff --cached --name-status
git commit -m "feat: add consented character persistence"
```

- [ ] **Step 8: Verify the exact committed range and clean worktree**

Run:

```powershell
git rev-parse HEAD
git rev-parse HEAD^
git diff --check 61a8b3b452589e47e7733dcff425f9117badd625..HEAD
git status --short --branch
```

Expected: HEAD is the final Task 15 commit, the full design-to-implementation
range is whitespace-clean, and the worktree is clean. Report Task 15 as a
milestone checkpoint only; Tasks 16-18 still remain.
