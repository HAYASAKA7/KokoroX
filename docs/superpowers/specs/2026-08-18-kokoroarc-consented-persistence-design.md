# KokoroArc Consented Persistence and Memory Design

**Date:** 2026-08-18

**Status:** Approved for implementation planning

**Owning milestone:** Milestone 9, Task 15

## 1. Goal

Add durable relationship state, bounded mood state, and host-owned memory
references without changing KokoroArc's session-only default. Every durable
write is an explicit, consent-bound operation. Users can inspect, export,
reset, remove, migrate, and revoke persistent data without allowing state or
memory to activate a character, grant a capability, or become canonical
character evidence.

Task 15 provides domain APIs and storage contracts. Task 17 exposes them
through the CLI. No Task 15 API starts a session or silently converts an
ordinary session event into durable state.

## 2. Product invariants

- Session-only state remains the default before and after Task 15.
- Creating a session, applying a session event, resolving a character default,
  or invoking a Skill never creates durable state by itself.
- Every persistent relationship or mood write names the exact active consent
  ID and grant revision that authorizes it.
- `relationship_state`, `mood_state`, and `memory_references` are independent
  permissions. Granting one never grants or persists another.
- Consent is scoped to one global or workspace installation binding. It never
  floats by character name or follows an upgrade automatically.
- Revocation blocks new durable writes immediately. It does not erase or
  rewrite existing data.
- Erasure requires a separate explicit reset or memory-removal request and may
  still run after revocation.
- Memory contains only host memory IDs and explicit approved summaries. It
  never stores a transcript, prompt history, secret, host path, tool output,
  or hidden copy of the host memory.
- Persistent data never overrides pack canon, host safety, tool permissions,
  authentication, refusal behavior, or factual results.
- All JSON artifacts are strict, canonical, bounded, schema-validated, and
  detached across callback boundaries.
- All writes stay below the configured KokoroArc data root. Workspace roots
  are identity inputs and are never modified.
- Task 15 performs no network, model, browser, registry-upload, or background
  work.

## 3. Considered architectures

### 3.1 Separate consent, state, memory, and migration stores — selected

Each subsystem owns one closed data model while sharing a small internal
filesystem transaction layer. Consent changes cannot rewrite memory, memory
removal cannot rewrite relationship history, and state replay does not need to
scan unrelated host references. A per-character scope lock coordinates the
few operations, such as `reset all` and migration, that cross stores.

This architecture best preserves permission separation, bounded scans,
recoverability, and installation-reference auditing.

### 3.2 Reuse `SessionStore` below a durable directory — rejected

This would reduce initial code but encode durable state in manifests whose
contract says `scope: session`. Session restart/archive behavior would become
the persistence lifecycle, consent could not be bound cleanly, and mood or
memory operations would be forced into a relationship journal.

### 3.3 One mutable per-character document — rejected

A monolithic file would simplify lookup but couple unrelated permissions and
make every memory change contend with relationship replay. It would also make
partial reset, append-only audit, migration, and crash recovery weaker.

## 4. Scope and storage model

Task 15 reuses `InstallScope` and `resolve_install_scope`. The canonical scope
root is `global` or `workspaces/<workspace-id>`, where the workspace ID remains
the SHA-256 of the canonical case-normalized workspace path.

The logical layout is:

```text
<data-root>/
  consents/<scope-root>/<namespace>/<character-id>/
    current.json
    history/<revision>.json
  persistent-state/<scope-root>/<namespace>/<character-id>/
    current.json
    generations/<generation-id>/
      state.json
      events/<revision>-<operation-id>.json
  memory-references/<scope-root>/<namespace>/<character-id>/
    entries/<memory-reference-id>.json
  persistence-transactions/<scope-root>/
    <namespace>.<character-id>.json
  persistence-locks/<scope-root>/
    <namespace>.<character-id>.lock
```

The physical implementation may keep a bounded index next to memory entries,
but an index is a derived projection and never the sole source of truth.
Directory membership, canonical bytes, identities, and aggregate limits are
rechecked under the same lock before a result is returned.

Global and workspace stores do not refer across scopes. Namespace and
character IDs are schema-safe path segments. Installation IDs and generated
operation IDs are values, not unchecked path fragments.

Read-only show/list/export operations do not create the data root, locks,
empty files, or directories. An absent consent, state, or reference collection
has an explicit in-memory representation and remains absent on disk.

## 5. Closed artifacts

The existing `persistence-consent` and `memory-reference` schemas remain
authoritative. Task 15 adds the minimum missing durable-state contracts:

- `persistent-character-state`: exact scope, installation, consent generation,
  outer revision, relationship state, bounded mood state, and last event hash;
- `persistent-state-event`: one append-only relationship, mood, reset, or
  migration operation with predecessor/successor hashes;
- `persistence-export`: a canonical read-only bundle containing the exact
  consent, state, event digest, and ordered memory-reference artifacts; and
- `state-migration-plan`: a closed declarative source-to-target replay plan.

Every schema is recursively closed. Schema discovery, installed-wheel data,
ECMAScript compatibility, fixtures, and negative matrices are extended for
these contracts. No placeholder hashes, arbitrary JSON Patch, commands,
expressions, import names, scripts, or executable migration fields are
permitted.

### 5.1 Persistent state envelope

The state envelope binds:

- scope and nullable workspace ID;
- exact installation ID, namespace, character ID/version, archive hash, and
  compiled hash;
- consent ID and exact grant revision;
- state contract and transition algorithm versions;
- monotonically increasing outer revision;
- one schema-valid `relationship-state` projection;
- one bounded mood projection;
- applied persistent operation IDs; and
- the SHA-256 of the last canonical event record, or null at revision zero.

The outer revision covers every durable state operation. The embedded
relationship revision advances only for relationship events or a relationship
reset. The mood revision advances only for mood updates, decay, or a mood
reset. This prevents a mood write from forging a relationship CAS conflict and
keeps both histories replayable.

### 5.2 Mood projection

The v1 mood projection contains:

- mood revision;
- `primary`, one of the twelve canonical v0.3 moods;
- nullable `secondary` canonical mood;
- bounded arousal, valence, and intensity;
- remaining turn count and original expiry turn count;
- nullable triggering interaction-event ID; and
- bounded unique applied mood-event IDs.

Revision zero is neutral with zero intensity and no trigger. A mood update is
an explicit closed event with an expected mood revision and trigger reference.
Values outside the contract fail; the core does not infer or invent a mood.
An advance-turn event decrements the counter deterministically and returns to
neutral at zero. Serious-context suppression remains a runtime rendering rule
and cannot rewrite durable mood without an explicit mood event.

## 6. Consent lifecycle

Create `src/kokoroarc/persistence/consent.py`.

### 6.1 Grant

`grant_consent` takes an explicit character, namespace, optional version,
scope, exact requested permissions, and expected consent revision. It resolves
one eligible installation in the same scope using the Task 14 installation
rules. An omitted version must resolve uniquely; ambiguity fails.

The stable consent ID is scope/character specific. `grant_revision` increases
monotonically for each explicit grant or permission replacement. The active
document always contains exactly the requested permissions; it never unions a
new request with an old grant. Replacing permissions or rebinding an installed
version therefore requires a new exact grant revision.

First creation requires expected revision zero. Later grant, replacement, or
regrant requires the current exact lifecycle revision. A stale caller receives
a retryable consent conflict. Repeating byte-identical grant intent at the
current revision is idempotent.

Rebinding consent to a different installation supersedes the prior grant. Data
bound to that prior grant remains inspectable, exportable, resettable, and
migratable, but it cannot accept ordinary relationship, mood, or memory
writes. Only a replay-verified migration may create a current state generation
under the successor target grant.

### 6.2 Show

`load_consent` is read-only and returns a detached schema-valid artifact or an
explicit absent result. It verifies workspace identity, the current file,
history membership, canonical bytes, and installation binding. Invalid or
changed history fails closed rather than being omitted.

### 6.3 Revoke

`revoke_consent` publishes a revoked successor with an exact
`revoked_revision`. Repeated revocation is idempotent. Revocation is never an
erase operation and never removes state, history, events, or memory.

The active-consent guard checks all of the following before a new durable
write:

1. scope/workspace and character match;
2. status is active;
3. consent ID and grant revision match the caller;
4. the requested permission is present;
5. the bound registry entry, archive, installed tree, and compiled artifact
   still match; and
6. the consent and installation snapshots remain unchanged through every
   external schema callback and until return.

## 7. Persistent relationship and mood state

Create `src/kokoroarc/persistence/state.py`.

### 7.1 Relationship application

`apply_persistent_relationship_event` requires:

- exact scope and character;
- active consent ID and grant revision with `relationship_state`;
- expected outer state revision;
- a schema-valid `interaction-event`; and
- target compiled growth configuration from the consent-bound installation.

The event's `expected_state_revision` remains the embedded relationship
revision. The implementation calls the frozen existing transition contract,
records one closed persistent event, and refreshes the state projection. An
already-applied operation/event ID is idempotent only when all canonical input
bytes match; changed bytes under a reused ID are a conflict.

### 7.2 Mood application

`apply_persistent_mood_event` requires active `mood_state` consent and exact
outer/mood revisions. It validates the closed mood event, records it, and
updates the bounded mood projection. `advance_persistent_mood_turn` is an
explicit deterministic operation; merely loading runtime context does not
advance or persist mood.

### 7.3 Journal and replay

The event journal is authoritative. Each record contains the outer revision,
operation ID, operation kind, consent binding, predecessor event hash,
predecessor state hash, operation payload, successor state hash, and frozen
algorithm version. Records are no-overwrite canonical files ordered by exact
revision.

Replay starts from the contract's canonical revision-zero envelope and
reapplies every event. It rejects gaps, duplicate revisions or IDs, hash-chain
breaks, changed algorithms, unknown entries, link-like nodes, oversized files,
aggregate overflow, and a projection that differs from replay. A missing or
stale projection is repaired only under the character lock; the read-only
replay API never writes.

### 7.4 CAS and publication order

Under the per-character lock, an apply operation:

1. recovers any prior transaction marker;
2. reloads and replays current state;
3. verifies consent, installation, caller values, and expected revisions;
4. computes the detached successor;
5. writes and fsyncs a retained same-parent event staging file;
6. publishes the no-overwrite event record;
7. atomically writes and fsyncs the derived state projection; and
8. confirms journal, projection, ancestry, consent, installation, and caller
   values before reporting success.

If event publication succeeds but projection publication fails, the event is
committed and the operation reports a recoverable write failure. The next
locked access repairs the projection from replay. No operation reports success
for an unconfirmed event or durability boundary.

## 8. Memory-reference store

Create `src/kokoroarc/persistence/memory.py`.

`add_memory_reference` takes an explicit host memory ID, canonical summary,
non-empty bounded localized-summary map, active consent ID/revision, and exact
scope/character. The function constructs the artifact; callers cannot set
`source_kind`, embedded-content, fact-authority, installation, consent, or
hash fields.

The content hash is the SHA-256 of a documented canonical payload containing
the host ID, canonical summary, and ordered localized summaries. The generated
memory-reference ID is a bounded deterministic digest-based ID, so host values
never become filesystem names.

Before publication, summaries are rejected if they contain credential-like
material, host-absolute paths or file URIs, control characters, transcript or
prompt-log structure, or content outside the schema limits. Findings never
echo the matched text. This is defense in depth; explicit host approval is
still required and the detector is not treated as proof that arbitrary
conversation text is safe memory.

An identical add is idempotent. Reusing a host ID with different approved
bytes is a conflict. `list_memory_references` returns a deterministic detached
order and identifies whether each reference still matches the active consent
generation without rewriting it.

Removal is explicit by host ID or memory-reference ID. It may run after
revocation because it reduces stored data. It verifies the exact artifact and
node identity before no-follow removal. A changed, missing, hardlinked, or
redirected target fails without deleting a replacement. Removing an already
absent exact ID is an idempotent no-op only when directory membership is still
safe and bounded.

## 9. Export, reset, and revocation behavior

### 9.1 Export

`export_persistent_data` is read-only. It captures consent, state generation,
journal digest, memory membership, workspace identity, and caller inputs before
the first callback. It returns one schema-valid `persistence-export` object in
canonical order with no host paths. Changed source bytes invalidate reuse.

The export includes stored references and approved summaries because those are
the user's inspectable KokoroArc artifacts. It never dereferences a host memory
ID or embeds the host memory body.

### 9.2 Reset

`preview_persistent_reset` and `reset_persistent_data` support:

- `relationship`: reset only relationship dimensions, stage, novelty, and
  relationship event IDs;
- `mood`: reset only mood to neutral revision zero semantics;
- `memory`: remove only the verified generated memory-reference collection;
  and
- `all`: perform all three under one transaction marker.

Relationship and mood reset are append-only state events, so replay preserves
the fact and ordering of the reset while discarding earlier values from the
current projection. Memory reset atomically renames the verified entries
directory to a retained cleanup path, publishes an empty membership state, and
then removes only the captured tree. Crash recovery completes the committed
side or restores the pre-cutover side according to the marker.

Reset requires an explicit matching consent ID even after revocation. It does
not require the permission to remain active because deletion must stay
available after permission withdrawal. It cannot target another consent,
scope, character, or installation.

### 9.3 Failure dominance

If cleanup, durability, or identity confirmation fails, the returned error
reports the exact safe phase and logical record state (`not_visible`,
`committed`, or `unknown`). A cleanup failure is never hidden behind an earlier
validation error. Cleanup never recursively removes an unidentified or
replacement path.

## 10. Declarative state migration

Create `src/kokoroarc/persistence/migrations.py`.

Persistent state does not follow a newly installed or default-selected version
automatically. Migration requires:

- existing source state and complete replayable journal;
- the retained, integrity-valid source consent generation that authorized that
  state, even when it is now superseded or revoked;
- a current active target consent generation, created by a separate explicit
  grant and bound to the target installation;
- exact source and target compiled artifacts;
- a previewed `state-migration-plan`; and
- unchanged plan, registry, consent, installation, state, and event hashes at
  apply time.

The historical source grant proves provenance but authorizes no new writes.
The active target grant authorizes the migration, and its permissions become
the upper bound on the migrated generation.

The v1 declarative strategies are deliberately narrow:

- replay relationship events under the target frozen growth contract;
- preserve mood only when the mood contract version is identical; or
- explicitly reset mood during migration.

Unknown dimensions, stages, algorithms, event kinds, or contract versions
block migration. There is no general expression language or arbitrary field
mapping in v1. The preview records source and target bindings, consent
generations, event-log digest, source state hash, target replay hash, selected
closed strategies, and expected output hash.

Apply creates a complete staged generation, replays it independently, verifies
the expected hash, atomically swaps the small `current.json` generation
pointer, fsyncs its parent, and retains the prior generation for bounded audit
and recovery. A migration marker makes every interruption recoverable. The
source installation remains removal-blocked until no current state, memory
reference, or incomplete migration binds it.

## 11. Installation-reference integration

Task 15 extends Task 13 removal checks. An exact installed release is blocked
by:

- active consent bound to it;
- current persistent state bound to it;
- any retained memory reference bound to it; or
- an incomplete/source-current migration bound to it.

A revoked consent with no state, memory, or migration does not by itself block
removal. Historical audit artifacts may remain, but they are not runtime
references. Reference scanning is direct, bounded before materialization, and
audited across schema callbacks and the removal cutover. New references racing
the final check block removal before the installation becomes invisible.

## 12. Domain components and public API

Create:

```text
src/kokoroarc/persistence/
  __init__.py
  _storage.py
  consent.py
  state.py
  memory.py
  migrations.py
```

`_storage.py` contains only shared scope-path, strict-JSON, bounded-read,
identity, lock, fsync, staging, transaction-marker, and callback-audit
primitives. Domain validation remains in the owning module.

The stable public surface exposes typed results and functions for:

- grant/load/revoke consent;
- load/apply/replay persistent relationship and mood state;
- add/list/remove memory references;
- export and preview/apply scoped reset; and
- preview/apply state migration.

The implementation plan fixes exact signatures after RED import tests. All
returned mappings are canonical-detached. No public function accepts a raw
destination path for internal storage, a command, executable callback, or an
unbounded iterator.

Task 17 will wire thin CLI handlers. Persistent state application will require
an explicit persistence option and consent ID; existing `state apply` remains
session-only when those are omitted.

## 13. Filesystem and callback security

- Absolutize the data root and capture every caller object, workspace identity,
  scope, consent, registry, archive, installed tree, state generation, journal,
  and memory membership before the first external schema callback.
- Validate only detached JSON values. Never give retained caller or store
  objects to schema code.
- Audit mutation probes in every callback `finally`, after every later phase,
  and immediately before return. A change-and-restore sequence fails.
- Reject symlinks, junctions/reparse points, special files, hardlinked mutable
  files, redirected ancestors, inconsistent case/path identity, and name
  collisions.
- Use direct bounded `os.scandir`; stop at limit plus one before sorting or
  loading entries. Bound file count, per-file bytes, aggregate bytes, journal
  revisions, memory entries, nesting, summary lengths, and retained histories.
- Open generated files with no-follow/exclusive semantics where available;
  retain file and parent identities through publication.
- Use atomic no-overwrite publication for immutable events/history and atomic
  replacement only for verified current projections or pointers.
- Fsync files before cutover and directories after visibility changes. A
  durability retry must retry the missing fsync rather than return from an
  idempotent visible-file branch.
- Never delete by name alone. Cleanup requires the captured generated node and
  ancestor identities; identity-unavailable cleanup deletes nothing and
  reports a cleanup failure.
- Error details contain only bounded enum-like phase/reason/state fields, never
  host paths, summaries, event evidence, consent bytes, or secrets.

## 14. Errors and recovery

Stable non-sensitive error families cover:

- invalid, missing, revoked, stale, or conflicting consent;
- absent permission or installation mismatch;
- state revision, event ID, replay, capacity, contract, or projection failure;
- invalid mood transition or expiry;
- unsafe/invalid/conflicting memory reference;
- secret/path/transcript-like summary rejection;
- reset preview mismatch, transaction conflict, or cleanup/durability failure;
- migration required, invalid, stale, unreplayable, or changed plan; and
- unsafe/changing scope, ancestry, lock, staging, journal, generation, or
  reference membership.

Every mutating operation writes a bounded transaction marker before the first
multi-node cutover. Recovery is deterministic and idempotent. It never guesses
from partially valid content, accepts an unbound replacement, or reports
success merely because a destination exists.

## 15. Testing strategy

### 15.1 Schema and unit tests

- discover and validate every new contract from source and installed wheel;
- valid global/workspace, active/revoked, relationship/mood/memory/export, and
  migration fixtures;
- closed-schema negative matrices, null/hash/revision conditionals, bounds, and
  executable-field rejection;
- consent first grant, exact replacement, idempotency, revoke, regrant, CAS,
  permission separation, and stale installation;
- deterministic relationship and mood apply, independent revisions,
  idempotency, replay, projection repair, capacity, export, and resets;
- memory add/list/remove, content hash, locale order, stale generation, and
  idempotent exact retry; and
- migration preview/apply, target replay, mood preserve/reset, stale plan, and
  unsupported-contract failure.

### 15.2 Integration tests

- install a verified pack, grant global consent, persist/replay/export/reset,
  revoke, erase after revoke, and finally remove the installation;
- repeat in one explicit workspace and prove cross-scope isolation;
- prove session start and ordinary session state apply remain session-only;
- explicitly persist selected session events with a consent ID and show exact
  durable replay across a new session/process;
- upgrade an installation only through a verified migration and target grant;
  and
- package/install smoke with repository source unavailable.

### 15.3 Security tests

- silent write attempts, permission widening, wrong consent revision, wrong
  character/version/scope, and cross-workspace access;
- transcript harvesting, credentials, absolute paths/file URIs, malicious
  mapping keys, mixed-type JSON, and non-echoing errors;
- input/callback A-to-B-to-A mutation, schema closure mutation, source/member
  replacement, and final-return mutation at every retained boundary;
- symlink, junction, hardlink, special-file, ancestor-swap, case-collision, and
  same-name replacement attacks;
- unbounded directory, journal, summary, history, and migration-plan pressure;
- lock contention, stale CAS, duplicate event/reference IDs, and direct
  filesystem races;
- every write, fsync, rename/link, pointer, marker, cleanup, reset, migration,
  and recovery failure window; and
- exact proof that failed and successful operations write nowhere outside the
  data root and never modify the workspace or real user home.

### 15.4 Closure

Run focused persistence/state/installer/schema/security suites, installed wheel
and sdist smoke, the complete pytest suite, changed-file compilation with
bytecode under `D:\tmp`, changed-line length checks, exact diff checks, and a
clean implementation commit audit.

## 16. Non-goals

Task 15 does not add automatic conversation extraction, semantic memory search,
host-memory dereferencing, a database service, background mood decay,
wall-clock decay, multi-user authentication, cloud sync, encryption/key
management, public state upload, automatic version migration, CLI handlers,
or implicit persistent writes. Authentication and encryption-at-rest remain
host responsibilities; KokoroArc still minimizes and isolates what it stores.

## 17. Acceptance criteria

- No durable artifact is created without an explicit consent grant and exact
  consent generation on each subsequent write.
- Relationship, mood, and memory permissions are independently enforced.
- Existing session behavior remains session-only unless a later CLI/host call
  explicitly chooses persistence and supplies consent.
- Relationship transitions use the existing frozen deterministic rules and
  replay exactly from a bounded append-only journal.
- Mood updates and expiry are closed, bounded, explicit, and replayable.
- Memory artifacts contain only host IDs and approved bounded summaries and
  cannot become canon or capability authority.
- Export is canonical, detached, path-free, and never dereferences host memory.
- Partial and all-scope resets are previewable, explicit, recoverable, and
  available after revocation.
- Revocation blocks new writes without silently erasing data.
- State never follows a pack upgrade without an exact target consent and
  replay-verified declarative migration.
- Installation removal observes every active persistent reference and cannot
  race a new one through cutover.
- All storage, callbacks, limits, failures, cleanup, and durability boundaries
  fail closed with no out-of-root writes and no sensitive error echo.
