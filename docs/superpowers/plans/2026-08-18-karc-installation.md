# Atomic `.karc` Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install, list, recover, and remove verified `.karc` archives in global or explicitly selected workspace scope without implicit activation or writes outside the selected data root.

**Architecture:** Keep deterministic decisions separate from filesystem mutation. `registry.py` owns scope identity, bounded scope locks, canonical registry reads, and compare-and-swap writes; `installer.py` owns archive preflight, same-parent staging, journaled cutover/recovery, reference-safe removal, and exact installed-bundle revalidation. All paths are derived from an explicit absolute data root, all archive members come from the already validated closed archive inventory, and every mutation runs under one scope lock with no-follow identity checks.

**Tech Stack:** Python 3.11+ standard library, canonical JSON, JSON Schema through `SchemaRegistry`, deterministic `.karc` archive APIs, `pytest`, Windows/POSIX filesystem primitives.

---

## Approved design decisions

The authoritative product contract is §8.1–8.2 of `docs/superpowers/specs/2026-08-14-kokoroarc-completion-design.md` and Task 13 of `docs/superpowers/plans/2026-08-14-kokoroarc-completion.md`.

Three implementation shapes were considered:

1. Direct extraction followed by a registry write is small, but exposes partial installations and cannot recover an interruption.
2. Reusing authoring publication storage would inherit strong primitives, but couples immutable distribution layout to editable draft replacement semantics.
3. A dedicated content-addressed archive plus journaled installation transaction adds a narrow storage layer, preserves no-overwrite semantics, and supports deterministic recovery.

Use option 3. Installation directories remain immutable. Reinstalling identical bytes is an idempotent read/verify operation; different bytes at the same registry identity are a conflict. Installation never writes default configuration or session state.

## File responsibilities

- Create `src/kokoroarc/distribution/registry.py`: scope derivation, workspace IDs, registry artifacts, bounded locks, stable reads, CAS writes, and installed-entry listing.
- Create `src/kokoroarc/distribution/installer.py`: dry-run plans, source capture, archive validation, staged extraction, journal recovery, install, reference checks, and removal.
- Modify `src/kokoroarc/distribution/__init__.py`: export the Task 13 public API.
- Create `tests/unit/test_karc_registry.py`: scope, schema, ordering, revision, and CAS tests.
- Create `tests/unit/test_karc_installer.py`: deterministic preflight and rejected archive tests.
- Create `tests/integration/test_karc_installer_integration.py`: global/workspace installation, idempotency, listing, recovery, and removal.
- Create `tests/security/test_karc_installer_security.py`: link/race/lock/CAS/bounds/failure-window tests.
- Modify `tests/integration/test_research_cli.py`: require the new modules and installed-wheel imports.
- Modify `docs/superpowers/plans/2026-08-14-kokoroarc-completion.md`: check Task 13 only after exact verification.

### Task 1: Scope identity and canonical registries

**Files:**
- Create: `src/kokoroarc/distribution/registry.py`
- Create: `tests/unit/test_karc_registry.py`

- [x] **Step 1: Write RED scope and empty-registry tests**

Cover global default scope, an explicit existing workspace root, stable SHA-256 workspace identity, no absolute workspace path in the artifact, and no filesystem writes during resolution.

```python
def test_workspace_scope_is_stable_and_does_not_expose_the_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    first = resolve_install_scope(workspace)
    second = resolve_install_scope(workspace)
    registry = empty_installed_registry(first)

    assert first == second
    assert first.kind == "workspace"
    assert len(first.workspace_id or "") == 64
    assert str(workspace) not in canonical_bytes(registry).decode()
```

- [x] **Step 2: Run the RED scope tests**

Run:

```powershell
$env:PYTHONPATH='src'
python -m pytest tests/unit/test_karc_registry.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task13-registry-red
```

Expected: collection fails because `kokoroarc.distribution.registry` does not exist.

- [x] **Step 3: Implement immutable scope resolution and registry construction**

Use these public contracts:

```python
@dataclass(frozen=True, slots=True)
class InstallScope:
    kind: Literal["global", "workspace"]
    workspace_id: str | None
    installed_relative_root: str
    registry_relative_path: str


def resolve_install_scope(workspace_root: Path | None = None) -> InstallScope:
    """Return global scope, or hash one explicit canonical workspace root."""


def empty_installed_registry(scope: InstallScope) -> dict[str, Any]:
    """Return the schema-valid revision-zero registry for one scope."""
```

Require workspace roots to exist as regular non-link directories. Hash the UTF-8 bytes of the normalized canonical path, using `os.path.normcase` on Windows. Use `global.json` for global scope and `workspaces/<workspace-id>.json` for workspace scope.

- [x] **Step 4: Add RED canonical registry read/list tests**

Test absent registry as revision zero, schema validation, lexicographic entry ordering, detached return values, a 1,024-entry bound, duplicate identity rejection, invalid relative paths, malformed JSON, noncanonical JSON, and registry input mutation by a schema callback.

- [x] **Step 5: Implement bounded registry reads**

Use a 2 MiB maximum registry size and stable handle identity checks. Validate a detached object with `installed-pack-registry`, require canonical bytes, and reject symlinks, junctions, non-regular files, changed bytes, and changed ancestor identities with stable `KARC_REGISTRY_*` errors.

```python
def load_installed_registry(
    data_root: Path,
    schemas: SchemaRegistry,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Read one canonical registry without creating storage."""


def list_installed_packs(
    data_root: Path,
    schemas: SchemaRegistry,
    *,
    workspace_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return detached entries ordered by registry identity."""
```

- [x] **Step 6: Add RED lock and CAS tests**

Exercise nonblocking lock contention, replacement of the lock path after open, registry revision mismatch, registry byte mutation between read and replace, destination parent replacement, and schema failure before publication.

- [x] **Step 7: Implement the bounded scope lock and CAS writer**

Use a same-registry hidden lock file with `msvcrt.locking` on Windows and `fcntl.flock` on POSIX. Retry only `(0, .01, .02, .04, .08)` seconds, then raise `KARC_REGISTRY_LOCKED`. Write canonical registry bytes to a same-parent regular staging file, fsync it, recheck expected revision/hash plus the full ancestor chain, atomically replace the registry, and fsync its parent where supported.

```python
def write_installed_registry_cas(
    data_root: Path,
    scope: InstallScope,
    expected_revision: int,
    expected_sha256: str | None,
    registry: dict[str, Any],
    schemas: SchemaRegistry,
) -> None:
    """Publish one exact next revision while the caller holds the scope lock."""
```

- [x] **Step 8: Run Task 1 GREEN tests**

Run the Task 1 unit file. Expected: all pass, with only explicit platform capability skips.

### Task 2: Deterministic install preflight

**Files:**
- Create: `src/kokoroarc/distribution/installer.py`
- Create: `tests/unit/test_karc_installer.py`

- [x] **Step 1: Write RED deterministic preview tests**

Build real private and public archives through `tests/karc_test_support.py`. Assert repeated previews are equal, perform no writes, include exact archive/manifest/compiled hashes, use the identity `namespace/character-id/version`, derive the schema fixture-compatible relative path, report current registry revisions, and always say `activates_character: false`.

```python
def test_preview_is_deterministic_and_read_only(
    rin_verified_release: dict[str, Any], tmp_path: Path
) -> None:
    archive = build_private_archive(rin_verified_release)

    first = preview_karc_install(archive, tmp_path / "data", SCHEMAS)
    second = preview_karc_install(archive, tmp_path / "data", SCHEMAS)

    assert first == second
    assert first["will_write"] is True
    assert first["activates_character"] is False
    assert not (tmp_path / "data").exists()
```

- [x] **Step 2: Run the RED preview tests**

Expected: import failure for `preview_karc_install`.

- [x] **Step 3: Implement the closed preview artifact**

Call `inspect_karc_compatibility` and `load_karc_archive`; require `installation_allowed is True`, `promotion_status == verified`, `activation_allowed is True`, and `trust == unsigned_local`. Read but never create the selected registry. Return canonical detached data with these exact keys:

```python
{
    "schema_version": "1.0",
    "operation": "install",
    "scope": scope.kind,
    "workspace_id": scope.workspace_id,
    "registry_identity": identity,
    "installation_id": installation_id,
    "archive_sha256": loaded.archive_sha256,
    "manifest_sha256": manifest_hash,
    "compiled_artifact_id": manifest["compiled_artifact_id"],
    "compiled_sha256": manifest["compiled_hash"],
    "visibility": manifest["visibility"],
    "relative_path": relative_path,
    "registry_revision_before": revision,
    "registry_revision_after": revision + 1,
    "idempotent": False,
    "will_write": True,
    "activates_character": False,
}
```

Derive `installation_id` from namespace, character ID, version, and the first eight archive-hash characters, matching the standalone fixture contract.

- [x] **Step 4: Add RED incompatible and conflict previews**

Cover malformed, traversal, extra member, invalid binding, unverified promotion, incompatible runtime/schema, a same-identity/different-hash registry entry, and an exact existing entry. Exact entries produce `idempotent: true`, `will_write: false`, and no revision increase. Conflicts raise `KARC_INSTALL_CONFLICT` without echoing archive content or host paths.

- [x] **Step 5: Implement fail-closed preview decisions**

Map archive/compatibility failures to `KARC_INSTALL_ARCHIVE_INVALID`, preserve bounded machine-readable reason codes in `details`, and never accept archive-provided executable members. Validate an exact existing installation on disk before declaring idempotency; stale registry/disk disagreement raises `KARC_INSTALL_RECOVERY_REQUIRED`.

- [x] **Step 6: Run Task 2 GREEN tests**

Run the Task 2 unit file and the existing archive/compatibility matrices. Expected: all pass.

### Task 3: Journaled install transaction

**Files:**
- Modify: `src/kokoroarc/distribution/installer.py`
- Modify: `src/kokoroarc/distribution/registry.py`
- Create: `tests/integration/test_karc_installer_integration.py`

- [x] **Step 1: Write RED global/workspace install tests**

Assert exact closed members under `installed/global/<character>/<version>` and `installed/workspaces/<workspace-id>/<character>/<version>`, a content-addressed archive at `archives/<archive-sha256>.karc`, revision-one canonical registry bytes, no config/session creation, no writes inside the workspace, and an unchanged source archive.

- [x] **Step 2: Run the RED integration tests**

Expected: `install_karc_archive` is absent.

- [x] **Step 3: Implement stable source capture and secure storage roots**

```python
def install_karc_archive(
    archive_path: Path,
    data_root: Path,
    schemas: SchemaRegistry,
    *,
    workspace_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Preview or atomically install one current verified archive."""
```

Absolutize caller paths before the first callback. Read the source through one regular no-follow handle with the `KarcLimits.max_archive_bytes` cap, recording device/inode/type/size/mtime and bytes. Create only the explicit data-root chain, rejecting redirects at every existing component and recording each created directory for fsync.

- [x] **Step 4: Implement staged extraction from validated bytes only**

Never call ZIP extraction APIs. Write `manifest.json` plus exactly the manifest-listed member payloads returned by `load_karc_archive` into a same-parent staging directory. Each directory/file is created exclusively, each file is mode `0600`, every payload is re-read with bounds and checked for exact size/hash/canonical JSON, and current schemas/release bindings are validated again before cutover.

- [x] **Step 5: Implement the install journal state machine**

The canonical internal journal contains operation, scope/workspace ID, registry identity, archive/manifest/compiled hashes, source and target relative paths, expected registry revision/hash, registry entry, staging names and captured identities, plus one phase from:

```python
InstallPhase = Literal[
    "prepared",
    "archive_published",
    "installation_published",
    "registry_published",
]
```

Write/fsync the journal before the first staging write and after every cutover. The journal path is `registry/journals/<scope-key>.json`; it is created and replaced only under the held scope lock.

- [x] **Step 6: Implement no-replace cutovers**

Use same-parent atomic no-replace rename for installation directories: native Windows rename, Linux `renameat2(RENAME_NOREPLACE)`, and macOS `renameatx_np(RENAME_EXCL)`. Fail closed with `KARC_INSTALL_ATOMIC_UNAVAILABLE` on unsupported POSIX systems. Publish the content-addressed archive with a same-parent fsynced staging file and atomic hard link, so existing bytes are never overwritten.

- [x] **Step 7: Commit the registry and finish**

Re-read source bytes, scope ancestry, staging identities, archive/install bytes, and registry CAS inputs immediately before each cutover. Publish the installation, CAS the next registry revision, mark the journal `registry_published`, remove only identity-matching staging/journal entries, and return the applied plan. Exact reinstall verifies all bytes and returns the idempotent plan without changing any revision or mtime.

- [x] **Step 8: Run Task 3 GREEN tests**

Run integration plus registry/installer unit tests. Expected: all pass.

### Task 4: Deterministic interruption recovery

**Files:**
- Modify: `src/kokoroarc/distribution/installer.py`
- Modify: `tests/integration/test_karc_installer_integration.py`
- Modify: `tests/security/test_karc_installer_security.py`

- [x] **Step 1: Write RED failure-window tests**

Inject failures after journal creation, archive staging, archive publication, installed staging, installed publication, registry staging, registry publication, journal phase write, and cleanup. Preserve the exact journal and visible filesystem from each injected boundary.

- [x] **Step 2: Define the public recovery contract**

```python
def recover_karc_installations(
    data_root: Path,
    schemas: SchemaRegistry,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Recover at most one bounded transaction for the selected scope."""
```

Return operation, scope, recovered boolean, prior/final phase, registry revision, and a stable action list. An absent journal is a deterministic no-op.

- [x] **Step 3: Implement fail-forward recovery**

Under the scope lock, validate the journal before using any path. If nothing became visible, remove only identity-matching staging and journal entries. If exact archive/install bytes became visible and the expected registry revision remains current, complete the registry CAS. If the exact registry entry is already committed, confirm archive/install bytes and clean the journal. Any conflict, missing visible bytes, replaced staging identity, changed ancestor, malformed journal, or unrelated registry revision raises `KARC_INSTALL_RECOVERY_REQUIRED` and deletes nothing unverified.

- [x] **Step 4: Add RED repeated recovery tests**

For every failure window, call recovery twice. The first call reaches one correct terminal state; the second is a no-op with byte-identical registry/install/archive state.

- [x] **Step 5: Run Task 4 GREEN tests**

Expected: every injected phase recovers deterministically and no unverified path is removed.

### Task 5: Reference-safe explicit removal

**Files:**
- Modify: `src/kokoroarc/distribution/installer.py`
- Modify: `tests/integration/test_karc_installer_integration.py`
- Modify: `tests/security/test_karc_installer_security.py`

- [x] **Step 1: Write RED successful-removal tests**

Install global and workspace copies, remove one exact identity, assert only that scope changes, increment its registry revision once, remove the installation directory, preserve a shared archive while referenced elsewhere, and remove the archive only after the final reference disappears.

- [x] **Step 2: Define the removal API**

```python
def remove_installed_pack(
    data_root: Path,
    namespace: str,
    character_id: str,
    character_version: str,
    schemas: SchemaRegistry,
    *,
    workspace_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Preview or remove one exact inactive installation."""
```

- [x] **Step 3: Write RED reference-blocker tests**

Create canonical references for:

- a matching `character-default-config` binding;
- an active `session-manifest` with exact character/version/compiled hash;
- a bounded canonical migration record with matching installation/archive hash.

Each must raise `KARC_REMOVE_REFERENCED` and leave registry/install/archive bytes unchanged. Inactive sessions and unrelated hashes do not block.

- [x] **Step 4: Implement bounded reference scans**

Inspect only the selected scope config, at most 1,024 session manifests, and at most 256 migration records, each at most 2 MiB. Reject unsafe entries, links, devices, parse errors, mutation, and enumeration growth with `KARC_REMOVE_REFERENCE_SCAN_INVALID`; do not ignore an unreadable potential reference.

- [x] **Step 5: Implement journaled removal**

Use the same scope journal with removal phases `prepared`, `registry_published`, and `installation_removed`. Commit the registry removal first so an interrupted operation cannot activate missing bytes. Rename the exact installation to an identity-bound same-parent removal staging name, remove it no-follow, delete the content-addressed archive only after a bounded scan confirms no registry references it, and finish by removing the journal.

- [x] **Step 6: Add RED removal-recovery tests**

Inject failure after registry publication, installation rename, tree cleanup, archive cleanup, and journal cleanup. Recovery must finish the intended removal or fail closed without restoring a registry entry to missing bytes.

- [x] **Step 7: Run Task 5 GREEN tests**

Expected: install/list/remove/recover integration tests pass in both scopes.

### Task 6: Adversarial filesystem and concurrency matrix

**Files:**
- Create: `tests/security/test_karc_installer_security.py`
- Modify: `src/kokoroarc/distribution/registry.py`
- Modify: `src/kokoroarc/distribution/installer.py`

- [x] **Step 1: Add RED path and link tests**

Cover symlink/junction roots and ancestors, archive input aliases, hardlinked mutable input, staging-file links, installed-directory replacement, archive/registry/journal replacement, device names, ADS/backslashes, case collisions, outside relative paths, and workspace-root mutation. Capability-gated real link tests may skip; monkeypatched redirect detection must always run.

- [x] **Step 2: Add RED race and callback tests**

Mutate source, data-root ancestry, workspace root, registry bytes, staging bytes, final target, and caller/schema inputs at every external callback and cutover boundary. Include A→B→A mutations. All must fail with stable mutation/path/CAS errors and never report success for changed inputs.

- [x] **Step 3: Add RED bounded-resource tests**

Drive registry/session/migration/staging enumerators past their limits with lazy fake iterators; grow files after stat/scan; use oversized archive/registry/journal/member payloads; and assert enumeration stops at limit + 1 without full materialization.

- [x] **Step 4: Harden until the security matrix is GREEN**

Use direct `os.scandir` iteration rather than `Path.iterdir`, retain identities for every generated staging entry, audit all mutable snapshots after each external callback and before return, and surface cleanup failures as `KARC_INSTALL_CLEANUP_FAILED` with a non-sensitive phase/reason. Never recursively delete a path whose retained identity or ancestor chain no longer matches.

- [x] **Step 5: Prove write confinement**

Snapshot the parent of the explicit data root and the explicit workspace root before/after successful and failing operations. The only allowed new paths are under the explicit data root; workspace scope uses the workspace solely for stable identity and never writes into it.

- [x] **Step 6: Run Task 6 GREEN tests**

Run security, unit, integration, existing archive, and migration matrices. Expected: all pass with only documented filesystem-capability skips.

### Task 7: Public API, packaging, and exact closure

**Files:**
- Modify: `src/kokoroarc/distribution/__init__.py`
- Modify: `tests/integration/test_research_cli.py`
- Modify: `docs/superpowers/plans/2026-08-14-kokoroarc-completion.md`

- [x] **Step 1: Export the stable Task 13 API**

Export `InstallScope`, `empty_installed_registry`, `resolve_install_scope`, `load_installed_registry`, `list_installed_packs`, `preview_karc_install`, `install_karc_archive`, `recover_karc_installations`, and `remove_installed_pack` from `kokoroarc.distribution`.

- [x] **Step 2: Extend the installed-wheel/sdist smoke**

Require `kokoroarc/distribution/registry.py` and `installer.py` in wheel/sdist and import every new public function from an installed wheel while the working directory is outside the repository.

- [x] **Step 3: Run focused closure**

```powershell
$env:PYTHONPATH='src'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/unit/test_karc_registry.py tests/unit/test_karc_installer.py tests/integration/test_karc_installer_integration.py tests/security/test_karc_installer_security.py tests/unit/test_karc_archive.py tests/unit/test_karc_compatibility.py tests/unit/test_karc_migrations.py tests/security/test_karc_archive_security.py tests/security/test_karc_migrations_security.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task13-focused
```

Expected: all runnable tests pass; skips name only unavailable filesystem capabilities.

- [x] **Step 4: Run package smoke and the full suite**

Run the installed wheel/sdist integration test, then:

```powershell
$env:PYTHONPATH='src'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task13-full
```

Expected: all runnable tests pass with documented capability skips.

- [x] **Step 5: Perform exact static closure**

Run syntax compilation with `PYTHONPYCACHEPREFIX` under `D:\tmp`, check changed Python lines are at most 88 columns, run `git diff --check`, verify only Task 13 paths are dirty, and inspect the staged name/status list.

- [x] **Step 6: Mark Task 13 complete and commit**

Change only Task 13 boxes in the completion plan to `[x]`, rerun `git diff --check`, and commit:

```powershell
git commit -m "feat: install character packs by scope"
```

Expected: clean `feat/standalone-suite` worktree and an exact commit whose parent is the Task 12 commit.
