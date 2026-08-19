# KokoroArc Standalone CLI and Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the completed Milestone 9 distribution, scoped-default,
consent, persistent-state, memory-reference, and Skill-suite APIs through a
stable JSON CLI, then document and prove the complete workflow from installed
wheel and sdist artifacts with repository source unavailable.

**Architecture:** Keep `kokoroarc.cli` as the shared entry point and error
envelope owner, but place the new parser branches and handlers in a focused
`kokoroarc.standalone_cli` adapter. The adapter consumes only public domain
APIs, strictly captures bounded file inputs, uses identity-bound no-replace
output publication, and declares whether a route needs `KOKOROARC_DATA_DIR`.
Read-only archive and suite-discovery routes therefore work without stateful
configuration; install, default, consent, state, and memory routes require the
configured data root. Tests drive the adapter through the real `kokoro` entry
point and reserve direct API calls only for seeding host-owned persistent
events that the approved CLI intentionally does not expose.

**Tech Stack:** Python 3.11+, `argparse`, canonical JSON, existing KokoroArc
distribution/persistence APIs and schemas, standard-library no-follow file
operations, pytest, setuptools wheel/sdist builds, and PowerShell D:-based
workflow probes.

---

## Frozen command contract

The new command surface is:

```text
kokoro pack export --compiled <compiled.json> --promotion <verified.json> \
  --hard-report <hard.json> --soft-report <soft.json> \
  [--publication-report <publication.json>] --out <pack.karc> --json
kokoro pack compatibility <pack.karc> --json
kokoro pack migrate <pack.karc> --to-format <version> --out <new.karc> \
  [--dry-run] --json
kokoro pack install <pack.karc> [--scope global|workspace] \
  [--workspace <root>] [--dry-run] --json
kokoro pack list [--scope global|workspace] [--workspace <root>] --json
kokoro pack remove <character-id> --version <version> \
  [--namespace <namespace>] [--scope global|workspace] \
  [--workspace <root>] [--dry-run] --json

kokoro config default set --character <id> [--version <version>] \
  [--namespace <namespace>] [--scope global|workspace] \
  [--workspace <root>] --json
kokoro config default show [scope options] --json
kokoro config default clear [scope options] --json

kokoro consent grant --character <id> --scope global|workspace \
  --permissions <comma-list> [--namespace <namespace>] \
  [--version <version>] [--workspace <root>] --json
kokoro consent show --character <id> [--namespace <namespace>] \
  [scope options] --json
kokoro consent revoke --character <id> [--namespace <namespace>] \
  [scope options] --json

kokoro state export --character <id> [--namespace <namespace>] \
  [scope options] --out <state.json> --json
kokoro state reset --character <id> \
  --part mood|relationship|memory|all [--namespace <namespace>] \
  [scope options] [--dry-run] --json

kokoro memory add --character <id> --host-id <id> \
  --summary-file <summary.json> [--namespace <namespace>] \
  [scope options] --json
kokoro memory list --character <id> [--namespace <namespace>] \
  [scope options] --json
kokoro memory remove --character <id> --host-id <id> \
  [--namespace <namespace>] [scope options] [--dry-run] --json

kokoro suite install [--scope user|repo] [--repo <root>] \
  [--skills-root <root>] [--dry-run] --json
```

`global` is the default pack/default/read scope. Consent grant keeps `--scope`
required so persistence is never authorized by an omitted choice. Suite scope
defaults to `user`. Workspace scope always requires one explicit workspace
root; supplying a workspace for any other scope is invalid. `pack export`
loads `review-attestation.json` from the exact published promotion directory;
the optional publication report is required by the archive builder for a
public-candidate promotion. `pack migrate --dry-run` returns the existing
deterministic migration plan and writes nothing.

Memory summary input is a closed JSON object:

```json
{
  "summary": "A bounded host-approved summary.",
  "localized_summaries": {
    "en-US": "A bounded host-approved summary."
  }
}
```

The handler loads the current consent and supplies its exact ID/revision to
consent-bound operations. Initial consent grant uses expected revision zero;
later exact grants use the currently retained revision. Reset IDs are derived
from canonical scope, character, consent, target, and current export hashes so
the same state/request is idempotent and changed state gets a distinct reset.

## Planned file map

```text
src/kokoroarc/
  cli.py                    # shared entry point, public error envelope, dispatch
  standalone_cli.py         # new Milestone 9 parsers, capture/output, handlers
tests/unit/
  test_standalone_cli.py    # parser, JSON envelope, handler unit contracts
tests/integration/
  test_standalone_cli_workflow.py
  test_research_cli.py      # installed-wheel/sdist module and command smoke
tests/security/
  test_standalone_cli_security.py
README.md
docs/superpowers/plans/2026-08-14-kokoroarc-completion.md
```

### Task 1: Freeze parser, routing, and configuration behavior

**Files:**

- Create: `src/kokoroarc/standalone_cli.py`
- Create: `tests/unit/test_standalone_cli.py`
- Modify: `src/kokoroarc/cli.py`

- [ ] **Step 1: Write parser RED tests for every frozen command**

Create table-driven tests that call `build_parser().parse_args(...)` for every
command above and assert its route fields, default scope, namespace, dry-run,
workspace, and output values. Include parser failures for a missing required
argument, invalid choice, and unsupported extra argument.

```python
@pytest.mark.parametrize(
    ("argv", "route"),
    [
        (["pack", "compatibility", "rin.karc", "--json"],
         ("pack", "compatibility")),
        (["consent", "show", "--character", "rin-aster", "--json"],
         ("consent", "show")),
        (["suite", "install", "--dry-run", "--json"],
         ("suite", "install")),
    ],
)
def test_parses_standalone_routes(argv: list[str], route: tuple[str, str]):
    args = build_parser().parse_args(argv)
    assert standalone_route(args) == route
```

- [ ] **Step 2: Run parser tests and observe RED**

```powershell
$env:PYTHONPATH='src'
$env:TEMP='D:\tmp\kokoroarc-task17-parser-red-01'
$env:TMP=$env:TEMP
python -m pytest tests/unit/test_standalone_cli.py -q -p no:cacheprovider
```

Expected: collection or parser failures because `standalone_cli` and the new
subcommands do not exist.

- [ ] **Step 3: Add the focused parser adapter**

Define these internal entry points in `standalone_cli.py`:

```python
StandaloneRoute = tuple[str, str]

def add_standalone_parsers(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    pack_commands: argparse._SubParsersAction[argparse.ArgumentParser],
    state_commands: argparse._SubParsersAction[argparse.ArgumentParser],
    leaf_json: Callable[[argparse.ArgumentParser], None],
) -> None: ...

def standalone_route(args: argparse.Namespace) -> StandaloneRoute | None: ...

def standalone_requires_data_root(args: argparse.Namespace) -> bool: ...

def handle_standalone(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]: ...
```

Use one helper to add `--scope global|workspace`, `--workspace`, and `--json`.
Call this adapter after the core parser has created both subparser objects. Add
pack commands to the existing `pack_commands`; add `consent`, `memory`, and
`suite` at the top level; add `export` and `reset` to the existing
`state_commands`. Do not add a second default-config parser.

- [ ] **Step 4: Make core CLI dispatch data-root-aware**

Call `add_standalone_parsers` while constructing the existing parser. In
`main`, check `standalone_route(args)` before generic `_HANDLERS`. Build
`Settings` only when `standalone_requires_data_root(args)` is true; otherwise
construct `SchemaRegistry(resolve_schema_dir())` and pass `data_root=None`.
Keep stdout as one sorted JSON document and stderr empty.

- [ ] **Step 5: Run parser GREEN and existing CLI regressions**

```powershell
python -m pytest tests/unit/test_standalone_cli.py tests/unit/test_cli.py \
  tests/integration/test_pack_testing_cli.py -q -p no:cacheprovider
```

- [ ] **Step 6: Commit parser/routing slice**

```powershell
git add src/kokoroarc/cli.py src/kokoroarc/standalone_cli.py \
  tests/unit/test_standalone_cli.py
git diff --cached --check
git commit -m "feat: expose standalone command routes"
```

### Task 2: Expose archive export, compatibility, and migration

**Files:**

- Modify: `src/kokoroarc/standalone_cli.py`
- Modify: `tests/unit/test_standalone_cli.py`
- Create: `tests/security/test_standalone_cli_security.py`

- [ ] **Step 1: Write archive-command RED tests**

Build a verified Rin release with existing fixtures. Assert:

- private export writes one exact `.karc` and reports its path/SHA-256;
- public export requires and binds a publication-readiness report;
- compatibility returns the domain report and performs no writes;
- migration dry-run returns `MigrationPreview.plan` and leaves `--out` absent;
- migration apply writes exactly the selected new archive and never overwrites;
- changing any captured JSON/archive byte during a callback fails closed.

```python
completed = _cli(
    "pack", "compatibility", str(archive_path), "--json",
    environment={},
)
assert completed.returncode == 0
assert json.loads(completed.stdout)["compatibility"]["compatible"] is True
assert completed.stderr == ""
```

- [ ] **Step 2: Run the archive selection RED**

```powershell
python -m pytest tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py -k 'archive or compatibility or migration' \
  -q -p no:cacheprovider
```

- [ ] **Step 3: Implement bounded input and no-replace output capture**

Add private immutable snapshots that retain lexical absolute path, parent
directory identities, file identity, and bytes. JSON capture must reject
duplicates, constants, non-object roots, invalid UTF-8, redirects, hardlink
aliases, mutation, and `JSON_INPUT_MAX_BYTES`. Archive capture uses
`KarcLimits.max_archive_bytes`.

Add `_publish_new_bytes(target, payload, suffix)` that requires an explicit
absolute-or-current-directory-relative target, a safe existing parent chain,
an absent final path, exclusive same-parent staging, file fsync, identity/byte
recheck, atomic no-replace cutover, parent fsync, and identity-bound cleanup.
It never overwrites and never creates arbitrary missing parent hierarchies.

- [ ] **Step 4: Implement the three archive handlers**

`pack export` captures compiled, hard, soft, promotion, sibling review, and
optional publication JSON before the first schema callback, passes detached
objects to `build_karc_archive`, re-audits every capture, and publishes the
returned bytes once. `compatibility` passes captured bytes to
`inspect_karc_compatibility`. `migrate --dry-run` calls
`preview_karc_migration`; apply calls `apply_karc_migration` after an explicit
preview and returns both the plan and output identity.

- [ ] **Step 5: Run GREEN plus domain regressions**

```powershell
python -m pytest tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py \
  tests/unit/test_karc_archive.py tests/unit/test_karc_compatibility.py \
  tests/unit/test_karc_migrations.py tests/security/test_karc_archive_security.py \
  tests/security/test_karc_migrations_security.py -q -p no:cacheprovider
```

- [ ] **Step 6: Commit archive CLI slice**

```powershell
git add src/kokoroarc/standalone_cli.py tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py
git diff --cached --check
git commit -m "feat: expose karc archive commands"
```

### Task 3: Expose scoped install, list, remove, and existing defaults

**Files:**

- Modify: `src/kokoroarc/standalone_cli.py`
- Modify: `tests/unit/test_standalone_cli.py`
- Modify: `tests/security/test_standalone_cli_security.py`

- [ ] **Step 1: Write scoped distribution RED tests**

Cover global default, explicit workspace, missing/extra workspace argument,
install dry-run, exact install, list, idempotent reinstall, conflict, removal
dry-run, referenced removal rejection, default set/show/clear, and proof that a
default never activates a session. Every dry-run snapshots the complete data
root before/after and requires byte-identical state.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py -k 'install or list or remove or default' \
  -q -p no:cacheprovider
```

- [ ] **Step 3: Implement strict scope translation**

Use exactly one helper:

```python
def _workspace_root(args: argparse.Namespace) -> Path | None:
    if args.scope == "workspace":
        if args.workspace is None:
            raise _argument_invalid()
        return Path(args.workspace)
    if args.workspace is not None:
        raise _argument_invalid()
    return None
```

Call `install_karc_archive(..., dry_run=args.dry_run)`,
`list_installed_packs`, and `remove_installed_pack(...,
dry_run=args.dry_run)`. Preserve each domain plan without inventing success
from `ok: true`; include `activates_character: false` on install/default
responses. Keep the existing default handlers and add regression coverage
rather than duplicate them.

- [ ] **Step 4: Run GREEN and installer/default suites**

```powershell
python -m pytest tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py \
  tests/unit/test_karc_installer.py tests/integration/test_karc_installer_integration.py \
  tests/security/test_karc_installer_security.py tests/unit/test_character_defaults.py \
  tests/integration/test_character_defaults_integration.py \
  tests/security/test_character_defaults_security.py -q -p no:cacheprovider
```

- [ ] **Step 5: Commit scoped distribution slice**

```powershell
git add src/kokoroarc/standalone_cli.py tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py
git diff --cached --check
git commit -m "feat: expose scoped pack installation"
```

### Task 4: Expose consent, state export/reset, and memory references

**Files:**

- Modify: `src/kokoroarc/standalone_cli.py`
- Modify: `tests/unit/test_standalone_cli.py`
- Modify: `tests/security/test_standalone_cli_security.py`

- [ ] **Step 1: Write consent/persistence RED tests**

Cover global/workspace grants, comma-list validation, idempotent grant, show,
revoke, permission separation, absent/revoked behavior, canonical export,
reset dry-run and apply for every part, memory add/list/remove and dry-run,
localized summaries, wrong consent/installation, stale reset, and no automatic
conversation harvesting. Assert all responses omit raw paths, secret-looking
input, and supplied invalid text.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py \
  -k 'consent or persistent or state_export or state_reset or memory' \
  -q -p no:cacheprovider
```

- [ ] **Step 3: Implement consent handlers with retained revision**

Parse permissions into a unique ordered tuple restricted to
`relationship_state`, `mood_state`, and `memory_references`. Capture the
current consent once, derive expected revision, then call `grant_consent`.
For revoke, require a current artifact and pass its exact consent ID and grant
revision to `revoke_consent`. Audit scope/arguments after callbacks.

- [ ] **Step 4: Implement state export/reset handlers**

`state export` calls `export_persistent_data`, canonicalizes once, then uses
the new output publisher. For reset, load the exact consent, export current
state, derive a stable `reset-<32 hex>` ID from canonical scope/character/
consent/target/export hashes, and call `preview_persistent_reset`. Dry-run
returns the decoded preview and writes nothing. Apply passes the exact retained
`PersistentResetPreview` to `reset_persistent_data`.

- [ ] **Step 5: Implement memory handlers**

Capture the closed summary JSON before callbacks. Add uses the current consent
ID/revision. List decodes each `MemoryReferenceView.payload` and records
`active_consent_generation`. Remove dry-run performs only a bounded list and
returns the exact matching reference ID/action; apply calls
`remove_memory_reference` with `identifier_kind="host_memory_id"` and the
retained consent ID. Unknown IDs stay fail-closed through the domain error.

- [ ] **Step 6: Run GREEN and the complete persistence matrix**

```powershell
python -m pytest tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py \
  tests/unit/test_persistence_consent.py tests/unit/test_persistence_storage.py \
  tests/unit/test_memory_references.py tests/unit/test_persistent_migrations.py \
  tests/integration/test_persistence_workflow.py \
  tests/security/test_persistence_security.py -q -p no:cacheprovider
```

- [ ] **Step 7: Commit persistence CLI slice**

```powershell
git add src/kokoroarc/standalone_cli.py tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py
git diff --cached --check
git commit -m "feat: expose consented persistence commands"
```

### Task 5: Expose Skill-suite installation

**Files:**

- Modify: `src/kokoroarc/standalone_cli.py`
- Modify: `tests/unit/test_standalone_cli.py`
- Modify: `tests/security/test_standalone_cli_security.py`

- [ ] **Step 1: Write suite-command RED tests**

Run without `KOKOROARC_DATA_DIR`. Cover default user dry-run with a patched
D:-based home, explicit user skills root, explicit repo root, exact install,
unchanged reinstall, conflict, wrong scope arguments, and no access or write
beneath the real home. Assert `~/.codex/config.toml` remains untouched.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py -k skill_suite \
  -q -p no:cacheprovider
```

- [ ] **Step 3: Implement the suite handler**

Call `install_skill_suite(scope=args.scope, repo_root=..., skills_root=...,
dry_run=args.dry_run)`. Do not resolve home or repository paths in the CLI;
leave source discovery, confinement, identity, staging, and rollback to the
verified Task 16 API. Return its exact canonical plan under `skill_suite`.

- [ ] **Step 4: Run GREEN plus Task 16 regression gate**

```powershell
python -m pytest tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py tests/unit/test_skill_suite.py \
  tests/integration/test_skill_suite_install.py \
  tests/security/test_skill_suite_security.py -q -p no:cacheprovider
```

- [ ] **Step 5: Commit suite CLI slice**

```powershell
git add src/kokoroarc/standalone_cli.py tests/unit/test_standalone_cli.py \
  tests/security/test_standalone_cli_security.py
git diff --cached --check
git commit -m "feat: expose skill suite installation"
```

### Task 6: Prove the clean installed-artifact workflow

**Files:**

- Create: `tests/integration/test_standalone_cli_workflow.py`
- Modify: `tests/integration/test_research_cli.py`

- [ ] **Step 1: Write the installed-workflow RED test**

Build wheel and sdist into a fresh D:-based root, install the wheel to an
isolated target, move the subprocess working directory outside the checkout,
and set `PYTHONPATH` only to the installed target. Prepare release JSON and a
host-approved memory summary under the test root before hiding repository
source.

Drive this sequence through installed `python -m kokoroarc.cli`:

1. install all four Skills into an explicit fake user root;
2. export, inspect, globally install, and list Rin;
3. set the global default and prove no session exists;
4. explicitly start one session from that default;
5. grant all three persistence permissions;
6. use an installed-package Python probe to apply one relationship event and
   replay it, because those host-event APIs are intentionally not CLI admin
   commands;
7. export state, add/list/remove one memory reference, and reset all state;
8. revoke consent, end the session, clear the default, dry-run removal, then
   remove the pack; and
9. reinstall the Skill suite and require four `unchanged` actions.

At every step require one JSON stdout document, empty stderr, expected exact
targets beneath the D:-root, and no implicit activation.

- [ ] **Step 2: Run workflow RED**

```powershell
python -m pytest tests/integration/test_standalone_cli_workflow.py -q \
  -p no:cacheprovider
```

- [ ] **Step 3: Close workflow-only defects with focused RED regressions**

Make only handler/adapter changes proven by a failing workflow assertion. Do
not weaken domain safety or bypass installed data discovery. Keep every build,
pip cache, data root, workspace, Skill root, and subprocess temp beneath the
test's unique D:-based root.

- [ ] **Step 4: Extend archive member and installed import assertions**

Add `kokoroarc/standalone_cli.py` to the required wheel/sdist module inventory
and probe parser construction plus one read-only compatibility command from
installed code. Keep repository source absent from `PYTHONPATH`.

- [ ] **Step 5: Run installed-artifact GREEN**

```powershell
python -m pytest tests/integration/test_standalone_cli_workflow.py \
  tests/integration/test_research_cli.py -q -p no:cacheprovider
```

- [ ] **Step 6: Commit installed workflow slice**

```powershell
git add tests/integration/test_standalone_cli_workflow.py \
  tests/integration/test_research_cli.py src/kokoroarc/standalone_cli.py \
  src/kokoroarc/cli.py
git diff --cached --check
git commit -m "test: prove installed standalone workflows"
```

### Task 7: Document global-first standalone operation

**Files:**

- Modify: `README.md`
- Modify: `tests/unit/test_standalone_cli.py`

- [ ] **Step 1: Write documentation-contract RED tests**

Assert README contains executable examples and explicit statements for:

- wheel install and four-Skill user/repo install;
- D:-based `KOKOROARC_DATA_DIR`, temp, build, and pip-cache configuration;
- global default and explicit workspace override;
- installation/default selection never activating a character;
- explicit session start/end;
- independent relationship/mood/memory consent and revocation;
- host-owned memory IDs and no transcript harvesting;
- state export/reset and removal ordering;
- deterministic unsigned-local archive and migration limits;
- private/publication readiness not publishing or granting rights; and
- recovery/conflict behavior and backup guidance.

- [ ] **Step 2: Run README contract RED**

```powershell
python -m pytest tests/unit/test_standalone_cli.py -k readme \
  -q -p no:cacheprovider
```

- [ ] **Step 3: Rewrite README milestone boundaries into user workflows**

Preserve authoring/research/testing sections, replace obsolete statements that
Milestone 9 capabilities remain gated, and add concise PowerShell workflows.
Label repository fixture paths as examples. State that the design revision
`0.3.0` is not the product/package version.

- [ ] **Step 4: Run README GREEN and link/path checks**

```powershell
python -m pytest tests/unit/test_standalone_cli.py -k readme \
  -q -p no:cacheprovider
rg -n "Milestone 9.*gated|does not install that Skill globally" README.md
```

Expected: documentation tests pass; any retained historical boundary wording
is clearly scoped to its older milestone rather than current capability.

- [ ] **Step 5: Commit documentation slice**

```powershell
git add README.md tests/unit/test_standalone_cli.py
git diff --cached --check
git commit -m "docs: explain standalone suite workflows"
```

### Task 8: Verify, review, record, and commit Task 17

**Files:**

- Modify: `docs/superpowers/plans/2026-08-14-kokoroarc-completion.md`
- Test: all Task 17 files and adjacent CLI/distribution/persistence suites

- [ ] **Step 1: Run the focused Task 17 gate**

```powershell
$env:PYTHONPATH='src'
$env:TEMP='D:\tmp\kokoroarc-task17-focused-final-01'
$env:TMP=$env:TEMP
python -m pytest tests/unit/test_standalone_cli.py \
  tests/integration/test_standalone_cli_workflow.py \
  tests/security/test_standalone_cli_security.py tests/integration/test_research_cli.py \
  -q -p no:cacheprovider
```

- [ ] **Step 2: Run adjacent and complete deterministic gates**

Run non-overlapping unit, integration, security, and Skill partitions with
fresh D:-based roots. Record exact collection count, pass/skip totals,
durations, and every capability skip. Run `compileall`, enforce 88 columns on
Task 17 additions, and run `git diff --check`.

- [ ] **Step 3: Build wheel and sdist twice at one fixed base epoch**

Require byte-identical wheels, content-identical normalized sdists, exact
module/schema/Skill/plugin inventories, installed workflow success with source
unavailable, official plugin validation, and all four official Skill
validators against both source and installed copies.

- [ ] **Step 4: Perform inline specification and quality/security review**

Review the frozen tree against design sections 7-12 and Task 17. Probe parser
ambiguity, missing configuration, dry-run writes, path/output races, input ABA,
scope confusion, real-home access, secret/path echo, post-callback mutation,
installed-data discovery, and destructive-target reporting. Fix every Critical
or Important issue with a focused RED regression, then repeat affected gates.

- [ ] **Step 5: Mark only Task 17 complete**

Update the canonical completion plan with exact evidence. Leave Task 18
unchecked and explicitly state that external behavioral/release closure and
fresh independent final reviews remain open.

- [ ] **Step 6: Stage and commit the exact Task 17 slice**

```powershell
git add src/kokoroarc/cli.py src/kokoroarc/standalone_cli.py README.md \
  tests/unit/test_standalone_cli.py \
  tests/integration/test_standalone_cli_workflow.py \
  tests/integration/test_research_cli.py \
  tests/security/test_standalone_cli_security.py \
  docs/superpowers/plans/2026-08-14-kokoroarc-completion.md \
  docs/superpowers/plans/2026-08-19-kokoroarc-standalone-cli.md
git diff --cached --check
git diff --cached --name-status
git commit -m "feat: expose standalone suite workflows"
```

- [ ] **Step 7: Verify the exact committed tree**

Record commit/tree/parent, clean status, parent-to-HEAD diff check, focused
tests, installed wheel/sdist workflow, plugin validator, four Skill validators,
and README contract on the committed tree. Do not claim complete-suite release;
Task 18 remains the final approval/evidence boundary.
