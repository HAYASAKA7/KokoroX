# KokoroArc Scoped Character Defaults Design

**Date:** 2026-08-18

**Status:** Approved for implementation planning

**Owning milestone:** Milestone 9, Task 14

## 1. Goal

Add deterministic global and workspace character defaults without weakening
KokoroArc's inactive-by-default behavior. Global is the normal user-facing
scope. A workspace default is an explicit, project-specific override. A
default selects a character only when a user or host explicitly requests
KokoroArc activation, most importantly through `session start`.

## 2. Product invariants

- Setting, showing, clearing, or resolving a default never starts a session.
- Installing a pack never sets a default.
- A normal runtime request, Skill trigger check, or repository visit never
  starts a session.
- `session start` remains an explicit mutation and remains the only Task 14
  CLI path that can activate the resolved character.
- Global is the default scope for configuration commands. Workspace scope
  always requires an explicit, existing workspace root.
- A default binds one exact installed release, not a mutable character name.
- A higher-precedence stale or invalid binding fails closed. It is not silently
  replaced by a lower-precedence binding.
- No omitted version means "latest." An omitted version must identify exactly
  one eligible installation or fail as ambiguous.
- Task 14 performs no network, model, registry-upload, or background work.

## 3. Considered architectures

### 3.1 Separate scope documents — selected

Store one closed `character-default-config` document per scope:

```text
<data-root>/config/global.json
<data-root>/config/workspaces/<workspace-id>.json
```

Each document has its own revision, lock, atomic publication boundary, and
exact installation binding. This matches the existing schema and the Task 13
removal-reference contract. A corrupt workspace document cannot rewrite the
global default, and global writes do not require scanning every workspace.

### 3.2 Embed defaults in installed-pack registries — rejected

This would make a preference change mutate installation inventory and couple
default recovery to archive installation recovery. It would also enlarge the
Task 13 transaction boundary and make registry revision conflicts more common.

### 3.3 One cross-scope configuration map — rejected

A single file would simplify discovery but make all workspace preferences
share one lock, one corruption boundary, and one size bound. It would also
require whole-map rewrites for unrelated workspaces.

## 4. Scope and storage model

Task 14 reuses `InstallScope` and `resolve_install_scope` from
`kokoroarc.distribution.registry`. The workspace ID remains the SHA-256 of the
canonical, case-normalized workspace path. Product code never hard-codes a
drive, and tests use explicit roots below `D:\tmp`.

An absent configuration file is represented in memory as a schema-valid
revision-zero document with `binding: null`. Reading an absent default is
read-only and does not create the data root. A clear operation on an already
absent or null default is idempotent and performs no write.

A successful changed set or clear operation increments the configuration
revision exactly once. Repeating an identical set is idempotent and does not
increment the revision. Canonical JSON bytes are authoritative.

In v1, a global default binds an installation from the global registry, and a
workspace default binds an installation from that workspace's registry. This
same-scope rule keeps removal-reference checks complete and prevents a
workspace document from creating a hidden reference to a global installation.
When no workspace binding exists, resolution may fall through to the global
default.

## 5. Binding and eligibility

The existing `character-default-config` schema remains authoritative. A
non-null binding contains:

- installation ID;
- namespace;
- character ID and semantic version;
- archive SHA-256; and
- compiled artifact SHA-256.

Setting or resolving a binding proves all of the following against one stable
snapshot:

1. the selected registry exists or has a canonical empty representation;
2. exactly one registry entry matches the requested namespace/character and
   optional version;
3. the entry is a verified release with `activation_allowed: true`;
4. the binding fields exactly match the registry entry;
5. the retained archive is a regular, single-link, bounded file with the
   recorded digest and a valid closed `.karc` manifest;
6. the installed member tree contains only the manifest members with exact
   bytes, hashes, and safe regular-file identities; and
7. `pack/compiled.json` validates as the bound compiled artifact and matches
   the recorded compiled digest, character ID, and version.

An omitted version succeeds only when one eligible registry entry matches. No
match produces a not-installed error; multiple matches produce an ambiguity
error. Namespace is explicit in the domain API. The CLI may use `original` as
its v1 default namespace while retaining a future-compatible API parameter.

## 6. Resolution precedence

The pure selection rule is:

```text
explicit character
> active session binding
> workspace default
> global default
> no character
```

The resolver returns a detached result containing the winning source and exact
binding, or an explicit no-character result. It never starts, ends, or mutates
a session.

Only present layers participate. A missing/null workspace default falls
through to global. A present workspace document with an invalid or stale
binding returns a stable error and does not fall through. The same rule applies
to global. Explicit and active-session layers prevent reads of lower-precedence
configuration, avoiding needless filesystem and callback exposure.

`session start` creates a new session, so its practical Task 14 path is:

```text
explicit --character compiled path
> explicit workspace default when --workspace is supplied
> global default
> error: no character resolved
```

The active-session layer exists for host/domain resolution and ordinary
already-active KokoroArc flows. Starting an already-active session remains an
error enforced by `SessionStore`.

## 7. Domain components

Create `src/kokoroarc/distribution/defaults.py` with four focused boundaries.

### 7.1 Configuration reader

Loads an absent or present scope document, validates it with
`character-default-config`, and returns a detached value. It retains the data
root ancestry, configuration path identity, workspace identity, canonical
bytes, and schema-callback audit state until return.

### 7.2 Atomic writer

Sets or clears one exact binding under a bounded same-scope lock. It uses a
same-parent retained staging file, canonical bytes, fsync, atomic replacement,
parent-directory fsync, compare-and-swap revision checks, and explicit cleanup
errors. It never follows links and never recursively deletes an unverified
path.

### 7.3 Installation resolver

Selects an exact eligible registry entry and validates its archive and installed
tree. It reuses the Task 13 registry and archive contracts rather than trusting
path strings or duplicating manifest semantics. All mutable snapshots remain
stable across schema callbacks and before return.

### 7.4 Precedence resolver

Chooses among detached explicit, session, workspace, and global candidates. It
performs no writes. The result identifies `explicit`, `active_session`,
`workspace_default`, `global_default`, or `none` without embedding host paths.

The stable public surface is exported from `kokoroarc.distribution`:

- `CharacterSelection`, an immutable detached result containing `source` and a
  nullable exact binding;
- `empty_character_default`, which creates the canonical absent representation;
- `load_character_default`, which performs a read-only scoped load;
- `set_character_default`, which resolves and atomically binds one installation;
- `clear_character_default`, which atomically publishes a null binding;
- `resolve_character_selection`, which applies the complete short-circuiting
  precedence rule without activation; and
- `load_selected_compiled`, which loads and revalidates the exact installed
  compiled artifact for a default-backed selection.

The implementation plan fixes their typed signatures. Explicit compiled-path
handling remains a CLI/session boundary because it is not an installed default
binding.

## 8. CLI and session integration

Task 14 adds the documented commands:

```text
kokoro config default set --character <id> [--namespace <id>] \
  [--version <version>] [--scope global|workspace] \
  [--workspace <root>] --json
kokoro config default show [--scope global|workspace] \
  [--workspace <root>] --json
kokoro config default clear [--scope global|workspace] \
  [--workspace <root>] --json
```

`--scope` defaults to `global`. `--workspace` is required for workspace scope
and rejected for global scope. Set/show/clear responses expose scope, revision,
and the non-sensitive exact binding; they never report activation success.

`session start --character <compiled-path>` remains backward-compatible and
has highest precedence. `--character` becomes optional, and `--workspace` is
accepted only to resolve a workspace default when the character path is
omitted. The command fails if no valid default resolves.

For a default-resolved start, the command validates the installed compiled
artifact and atomically publishes its canonical bytes into the existing
compiled-artifact projection used by runtime lookup. It audits the installed
source and projection before starting the session. This avoids changing the
session-manifest schema and keeps existing runtime context lookup compatible.
The projection is a derived cache, not activation; the explicit
`SessionStore.start` call remains the activation boundary.

## 9. Errors and fail-closed behavior

Task 14 adds stable, non-sensitive error families for:

- invalid scope or workspace use;
- unsafe/malformed/default configuration;
- configuration revision or write conflict;
- missing, ambiguous, stale, or ineligible installation binding;
- changed registry, archive, installed tree, workspace, caller input, or schema
  callback data;
- unsafe lock, staging, configuration, archive, installed, or projection path;
- cleanup or durability failure; and
- no character resolved for explicit session start.

Errors contain bounded reason/phase identifiers, not host paths, configuration
bytes, archive content, or character prose. A cleanup failure is never hidden
behind an earlier operational error. A failed write never reports a new
revision, and a failed session start never leaves an active manifest.

## 10. Filesystem and callback security

- Capture caller values, workspace identity, data-root ancestry, registry,
  configuration, archive, and installed-member identities before the first
  external schema callback that could observe them.
- Validate detached JSON values. Never hand retained caller objects to an
  external callback.
- Audit every retained mutation probe after each callback and once more before
  return. A change-and-restore sequence is still a failure.
- Reject symlinks, junctions/reparse points, special files, hardlinked mutable
  files, redirected ancestors, and name collisions.
- Bound all file sizes, aggregate member bytes, registry entries, directory
  entries, nesting, and callback-driven scans before materialization.
- Use direct bounded `os.scandir` iteration where enumeration is necessary.
- Keep every product write below the explicit data root. Workspace roots are
  identity inputs only and remain byte-for-byte unchanged.
- Recheck exact source and destination identities before and after atomic
  cutover and before reporting success.

## 11. Testing strategy

### 11.1 Unit tests

- canonical absent/global/workspace documents;
- global default set/show/idempotent-set/clear/idempotent-clear;
- exact explicit > session > workspace > global > none precedence;
- omitted-version unique resolution and ambiguity failure;
- same-scope binding and verified-activation eligibility;
- stale archive/compiled/registry/config hashes and revisions;
- deterministic detached results and unchanged caller inputs.

### 11.2 Integration tests

- install verified packs globally and in one explicit workspace;
- set both defaults and prove workspace override then global fallback;
- start a session without `--character` from each valid default;
- load runtime context from the resulting installed compiled projection;
- preserve explicit compiled-path session start behavior;
- clear references and then remove the installation;
- prove config commands never create session/state/event artifacts;
- prove ordinary runtime and Skill requests never auto-start a session.

### 11.3 Security tests

- unsafe workspace/data/config/lock/staging/archive/install/projection paths;
- same-byte identity replacement, A→B→A mutation, callback mutation, and
  ancestry swaps at every external boundary;
- registry/config CAS conflicts and lock contention;
- malformed/oversized configuration and bounded ambiguity scans;
- archive/member growth, link and hardlink substitution, and installed-tree
  replacement;
- interruption at staging write, fsync, replace, parent fsync, and cleanup;
- successful and failed operations create nothing outside the data root and do
  not modify the workspace.

### 11.4 Closure

Run focused default/installer/session/CLI/security suites, installed wheel and
sdist import/CLI smoke, the complete pytest suite, syntax compilation with
bytecode under `D:\tmp`, changed-line length checks, exact diff checks, and a
clean commit audit.

## 12. Non-goals

Task 14 does not add persistent relationship state, memory references, Skill
installation, online character discovery, automatic version upgrades,
cross-scope installation references, auto-activation, or background session
management. Those remain later tasks or future product decisions.

## 13. Acceptance criteria

- Global set/show/clear is the default CLI behavior.
- Workspace override requires an explicit stable workspace and writes nothing
  into it.
- Every non-null default binds one exact current eligible installation.
- Precedence is deterministic and stale higher-precedence bindings fail closed.
- Omitted versions never select implicitly among multiple installations.
- `session start` can omit `--character` only when a valid default resolves.
- Existing explicit compiled-path session starts remain compatible.
- Default-resolved sessions can immediately load runtime context.
- No other command, runtime request, or Skill path implicitly activates a
  character.
- All writes are atomic, recoverable or explicitly failed, race-audited, and
  confined to the data root.
