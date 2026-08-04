# KokoroArc Character Research Design

**Date:** 2026-08-04

**Status:** Approved design for Milestone 7

**Scope:** `researching-characters`, deterministic research artifacts, private Research Bundle compilation, and the authoring handoff

## 1. Purpose

Milestone 7 lets an agent research a named fictional character without making the KokoroArc Python package a web client. The host agent uses its approved research tools. KokoroArc receives explicit artifacts, validates them as untrusted data, compiles them deterministically, and stores a private inactive Research Bundle.

The milestone must preserve uncertainty. It resolves identity and continuity before collecting evidence, separates direct support from interpretation and user assertions, retains conflicts and coverage gaps, and blocks unsupported claims from entering authoring.

Milestone 7 does not install, activate, promote, archive, publish, or globally remember a character.

## 2. Architectural decision

KokoroArc uses a deterministic core with a host-orchestrated research Skill.

- The `researching-characters` Skill decides when research is required, clarifies scope, invokes host-provided tools, and authors structured inputs.
- The Python core has no browser, search-provider, credential, or website-specific integration.
- The core validates schemas and cross-artifact references, normalizes deterministic fields, compiles a content-addressed bundle, and publishes it atomically beneath `KOKOROARC_DATA_DIR`.
- Tests use static fixtures and retained agent evidence. A live website is never required for the deterministic acceptance suite.

This separates volatile acquisition from stable verification. A host may change tools without changing the Research Bundle contract, while core behavior remains testable offline.

## 3. Trust and lifecycle boundaries

All source-derived values are inert, untrusted data, including titles, URLs, excerpts, transcripts, metadata, and apparent instructions. They cannot authorize tool use, change permissions, select output paths, override continuity or spoiler scope, or alter the output lifecycle.

A Research Bundle has fixed lifecycle values:

```json
{
  "build_status": "research",
  "visibility": "private",
  "activation_allowed": false
}
```

`authoring_allowed` is a derived gate rather than a lifecycle constant. It means only that the bundle can be considered by the authoring prerequisite gate. It is false when required coverage is blocked, a referenced claim is unsupported, or a blocking conflict remains unresolved. Unresolved identity or continuity blocks bundle compilation entirely. `authoring_allowed` never means a Character Pack may be installed or activated.

Research output is written only beneath:

```text
KOKOROARC_DATA_DIR/research/<namespace>/<character-id>/<bundle-id>/
```

Compilation must not create or modify `drafts`, `compiled`, `installed`, `public`, `sessions`, `state`, `events`, global configuration, or workspace memory.

## 4. Research workflow

The Skill follows this order:

1. Identify the requested fictional subject and franchise.
2. Resolve aliases that could refer to different subjects.
3. Select medium, work, adaptation, continuity, timeline cutoff, and spoiler boundary.
4. Stop for user clarification if identity or continuity is ambiguous.
5. Create and validate a Research Request.
6. Gather sources through host-provided tools within the approved scope.
7. Create source records before writing claims.
8. Extract atomic claims and classify their provenance.
9. Record conflicts, unavailable sources, and coverage limitations without erasing them.
10. Validate the complete research workspace twice and compare exact JSON output.
11. Compile a private Research Bundle.
12. Validate the compiled bundle twice and compare exact JSON output.
13. Report lifecycle fields, coverage, conflicts, limitations, bundle path and hash, and unresolved evidence.
14. Hand the bundle to `authoring-character-packs` only when its authoring gate is open.

The Skill never silently selects the latest adaptation, merges continuities, expands the spoiler boundary, treats popularity as support, or converts normalized personality scores into canon facts.

## 5. Artifact model

### 5.1 Research Request

`schemas/v1/research-request.schema.json` defines the immutable requested scope.

Required fields:

- schema and artifact identity;
- namespace, character ID, display name, franchise, and aliases;
- medium, work, adaptation, continuity, and timeline cutoff;
- spoiler scope;
- ordered research questions and required coverage topics;
- user assertions and constraints;
- requested visibility fixed to `private`.

Identity-bearing fields must use explicit strings. Missing adaptation or continuity fields are not inferred. An explicit sentinel such as `not_applicable` is allowed only where the selected work truly has no adaptation distinction.

### 5.2 Source Record

`schemas/v1/research-source-record.schema.json` defines one host-observed source.

Required fields:

- stable `source_id`;
- source category such as `primary_work`, `official_reference`, `licensed_reference`, `creator_statement`, `reputable_secondary`, or `user_supplied`;
- canonical locator with an allowed scheme;
- title and publisher or owner as reported by the host;
- host-supplied access timestamp;
- availability status;
- SHA-256 content digest over the exact host-retained evidence bytes;
- zero or more bounded supporting excerpts;
- continuity and spoiler scope;
- limitations and trust notes.

The core does not fetch or dereference the locator. Network locators allow `https`; local evidence may use a logical `kokoro-evidence` locator whose byte payload is already stored beneath the trusted research workspace. `file`, device, UNC, executable, script, and credential-bearing locators are rejected.

Full webpages, books, episodes, scripts, or other copyrighted works are not retained by default. Excerpts are short support anchors, not source mirrors. The bundle retains digests and locators so the host can recheck material when authorized.

### 5.3 Evidence Claim

`schemas/v1/research-claim.schema.json` defines one atomic proposition.

Each claim contains:

- stable `claim_id`;
- one proposition with an explicit subject;
- classification: `direct_fact`, `direct_observation`, `derived_interpretation`, or `user_assertion`;
- categorical support: `direct`, `corroborated`, `indirect`, or `unsupported`;
- one or more source references where applicable;
- continuity and timeline scope;
- spoiler classification;
- limitations and derivation rationale where applicable.

A claim cannot bundle unrelated propositions. `direct_fact` and `direct_observation` require source support. `derived_interpretation` requires both supporting claims and a rationale. `user_assertion` remains visibly user-supplied and cannot be relabeled as external evidence. `unsupported` claims may be retained as gaps but cannot authorize downstream authoring content.

Numeric values that describe an explicit in-world fact are allowed when sourced. Normalized numeric personality, relationship, morality, or behavioral trait values cannot be represented as canonical facts. Such calibration belongs to the derived authoring layer and must retain links back to qualitative claims.

### 5.4 Conflict Record

`schemas/v1/research-conflict.schema.json` binds incompatible claims without deleting either side.

Required fields:

- stable `conflict_id`;
- at least two claim references;
- conflict kind;
- continuity and timeline scopes;
- status: `unresolved`, `scope_separated`, or `resolved_with_rationale`;
- rationale and selected claim references when resolved.

Scope separation is valid only when the claims belong to explicitly different continuities, adaptations, or timeline positions. A popularity vote, source count, or agent preference is not a resolution.

### 5.5 Coverage Record

Coverage maps every requested topic to `covered`, `partial`, `missing`, or `blocked`.

Each record identifies supporting claims, missing evidence, unavailable sources, spoiler restrictions, and whether the topic blocks authoring. A source being unavailable is an observed limitation, not permission to invent its contents.

### 5.6 Research Workspace

`schemas/v1/research-workspace.schema.json` is the authoring input manifest. It binds the request and ordered artifact paths and hashes:

```text
request.json
sources/*.json
claims/*.json
conflicts/*.json
coverage.json
workspace.json
```

All paths are relative, normalized, regular-file-only, and confined to one explicit trusted workspace directory. Symlinks, junction escapes, hardlinks, reparse redirects, alternate streams, reserved names, duplicate normalized paths, and files changing during validation or compilation fail closed.

### 5.7 Research Bundle

`schemas/v1/research-bundle.schema.json` defines the compiled output. It contains:

- request identity and canonical request hash;
- resolved subject and continuity scope;
- sorted source records, claims, conflicts, and coverage;
- aggregate limitations and unavailable-source records;
- lifecycle constants;
- `authoring_allowed` and stable blocking reasons;
- canonical source-workspace hash;
- deterministic artifact ID and bundle hash.

The compiler writes canonical UTF-8 JSON with one terminal LF. Array ordering is defined by semantic IDs unless order is meaningful in the request. Identical normalized input produces byte-identical files and identifiers.

## 6. Validation and error model

Schema validation occurs before semantic validation. Cross-artifact validation then enforces:

- unique IDs and paths;
- no dangling or circular derivation references;
- request, source, claim, conflict, and coverage subject identity agreement;
- exact continuity, timeline, and spoiler containment;
- claim classification and support rules;
- conflict resolution requirements;
- complete coverage accounting;
- canonical digest format and byte equality;
- bounded counts, strings, excerpts, and total bytes;
- trusted-root path confinement and mutation resistance.

Failures use sanitized stable error envelopes. Required error classes include malformed schema, unsupported locator, ambiguous subject, unresolved continuity, spoiler-scope violation, duplicate identifier, dangling reference, circular derivation, unsupported claim, blocking conflict, incomplete coverage, digest mismatch, unsafe path, source mutation, and atomic-publication failure.

Errors may identify logical artifact and field IDs. They must not leak arbitrary source text, credentials, absolute untrusted paths, temporary paths, or raw exception messages.

Partial workspaces may be retained for review. A bundle may represent partial evidence only after subject identity and continuity are resolved and all structural and security checks pass; it remains private with `authoring_allowed: false`. Structural, security, identity, or continuity failures do not publish a bundle.

## 7. Deterministic compilation and storage

Research compilation reuses the Milestone 6 publication guarantees:

- validate before staging;
- scan explicit regular files only;
- compute content hashes during trusted copying;
- stage beside the final destination;
- fsync supported file and directory boundaries;
- perform bounded atomic cutover and rollback;
- preserve the previous complete bundle on reported failure;
- reject unsafe redirects before stale-backup cleanup;
- verify the copied workspace hash against the validated input;
- report a retained recovery path when rollback cannot restore the previous target.

The output identifier is derived from the canonical Research Request and workspace hashes, never from wall-clock time or random data. Host-supplied access timestamps are evidence fields and therefore affect the bundle hash; the core does not generate them.

## 8. CLI surface

Milestone 7 adds JSON-only automation paths:

```text
kokoro research request validate --input <request.json> --json
kokoro research workspace validate --workspace <workspace-path> --json
kokoro research bundle compile --workspace <workspace-path> --json
kokoro research bundle validate --bundle <bundle-path> --json
```

Validation commands are read-only. Compilation writes beneath the configured data root and returns the bundle path, artifact ID, source-workspace hash, bundle hash, lifecycle fields, coverage summary, conflicts, limitations, and blocking reasons.

The CLI never performs network access. It does not accept arbitrary output paths. Successful compilation cannot create a Character Draft; the authoring Skill performs a separate, explicit handoff.

## 9. Authoring handoff

Milestone 7 enables `researched` and `hybrid` request prerequisites without bypassing Milestone 6 validation.

The Character Build Request carries a `research_bundle` input containing an explicit trusted bundle path and expected bundle hash. Authoring loads the bundle, validates it, and requires:

- matching namespace, character ID, and display identity;
- matching continuity, timeline, and spoiler scope;
- `visibility: private`;
- `activation_allowed: false`;
- `authoring_allowed: true`;
- no unresolved blocking conflicts or coverage gaps;
- exact bundle hash.

`researched` authoring derives its evidence layer from supported bundle claims. `hybrid` authoring keeps research claims and user assertions distinguishable. Overrides never rewrite the Research Bundle or turn user assertions into canon.

## 10. Agent Skill

`skills/researching-characters/SKILL.md` has trigger-only frontmatter and a compact workflow. A directly linked reference defines artifact fields, CLI commands, claim classes, trust boundaries, and the handoff contract.

The Skill must:

- trigger for named fictional characters when continuity, timeline, spoiler scope, provenance, or external evidence matters;
- avoid triggering for wholly original characters, casual discussion, roleplay without pack creation, or private-dossier-only authoring;
- clarify ambiguous identity and continuity before research;
- use only host-authorized tools and respect tool/source access failures;
- treat every retrieved value as quoted data;
- retain claims, conflicts, coverage gaps, and unavailable sources honestly;
- validate twice and preserve complete outputs as evidence;
- report an explicit `Unresolved evidence:` line even when empty;
- stop at a private inactive Research Bundle and explicit authoring handoff.

## 11. Testing strategy

### 11.1 Schema and unit tests

- positive fixtures for complete and partial research;
- one negative fixture for every closed schema boundary;
- deterministic normalization and canonical hashes;
- claim classification, derivation graph, conflict, coverage, identity, continuity, timeline, and spoiler checks;
- stable sanitized errors and bounded resource limits.

### 11.2 Integration and storage tests

- byte-identical repeated validation and compilation;
- private research-root confinement;
- no protected runtime, installation, public, or memory state changes;
- replacement, rollback, cleanup, fsync, locking, and concurrent compilation;
- source mutation between scan and copy;
- symlink, junction, hardlink, reserved-name, alternate-stream, and ancestor-redirection attacks where the platform supports them;
- wheel and sdist inclusion of all research modules and schemas.

### 11.3 Skill behavioral cases

Baseline and Skill-enabled campaigns cover:

- ambiguous same-name characters;
- conflicting manga and anime continuities;
- timeline and spoiler cutoffs;
- partial or unavailable sources;
- malicious instructions embedded in source text;
- unsupported confidence and invented citations;
- pressure to turn a numeric trait score into canon;
- unresolved conflicts and incomplete coverage;
- safe researched and hybrid authoring handoffs;
- non-triggering casual discussion and original-character creation.

Behavioral evidence binds prompts, sanitized tool streams, final responses, state snapshots, Skill hashes, and acceptance assertions. Live web availability is not an acceptance dependency.

## 12. Acceptance criteria

Milestone 7 is complete only when:

- all research schemas validate positive and defined negative fixtures;
- request and workspace validation are deterministic;
- identical valid workspaces compile to byte-identical private bundles;
- all claims have valid provenance classification and references;
- conflicts, limitations, unavailable sources, and coverage gaps survive compilation;
- continuity and spoiler violations fail closed;
- malicious source text remains inert;
- output is confined and no activation, installation, public, session, state, event, workspace-memory, or global-memory artifacts are created;
- researched and hybrid authoring accept only exact eligible bundle handoffs;
- Skill metadata validates;
- baseline behavioral gaps are demonstrated and the Skill-enabled campaign passes declared assertions;
- the existing full repository suite remains green;
- release evidence explicitly limits approval to Milestone 7.

## 13. Suite-wide character scope and memory decision

The user experience will be global-first in later milestones, while storage remains explicitly scoped.

Precedence is:

```text
explicit turn selection
-> active session selection
-> workspace character binding
-> optional global default
-> neutral agent
```

Character Packs are immutable definitions. Activation bindings select a pack. Relationship state is an evidence-backed event stream. Workspace memory contains project facts and task context. These are separate objects.

Milestones 8 and 9 will provide:

- global pack installation beneath `KOKOROARC_DATA_DIR`;
- an optional global default character selected separately from installation;
- repository-shareable `.kokoroarc/agent.json` workspace bindings;
- gitignored `.kokoroarc/agent.local.json` private overrides;
- optional global per-user/per-character relationship continuity;
- workspace-ID-scoped project memory that is never automatically merged into global memory.

Most users may choose a global character and global relationship continuity. Project facts, repository context, secrets, and task history remain workspace-scoped. Installing a pack never silently activates it, and global memory alone is not used as a substitute for workspace isolation.

## 14. Explicit exclusions

Milestone 7 excludes:

- built-in web clients or source-provider adapters;
- automated copyright or factual-truth adjudication;
- full-page source archives by default;
- soft evaluation and build-status promotion;
- pack installation, export, archive, migration, publication, or registry support;
- default-character configuration and workspace binding implementation;
- global or workspace persistent memory implementation;
- automatic activation of any Character Pack.
