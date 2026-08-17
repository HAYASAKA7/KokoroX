# KokoroArc Milestones 8-9 Completion Design

**Date:** 2026-08-14

**Status:** Approved for implementation by the user's standing instruction to write the plan and continue through the full standalone suite

**Scope:** `testing-character-packs`, standalone packaging, private installation, scoped defaults, consented persistence, compatibility/migration, and final suite verification

**Implementation base:** `5b87fcac1a53671ce98d3a527e5b266679b8afd7`

**Design lineage:** Extends design revision 0.3.0 and the approved standalone, authoring, and research designs. The design revision is not the product version.

## 1. Outcome

Milestone 8 adds a deterministic, evidence-bound testing and promotion layer plus the fourth discoverable Skill, `testing-character-packs`. Milestone 9 packages the four-Skill suite and verified Character Packs for safe standalone use.

At the end of Milestone 9, a user can:

1. test an authored Character Pack with deterministic hard gates;
2. validate and aggregate host-produced soft evaluations without giving the core a model or network client;
3. record explicit human review and promote an exact pack from `draft` to `reviewed` to `verified`;
4. inspect publication readiness without uploading anything;
5. export a deterministic `.karc` archive containing only approved runtime and release artifacts;
6. inspect compatibility, preview installation, and atomically install a verified pack globally or for one workspace;
7. choose a global default character, with an optional workspace override, without implicit activation;
8. opt into persistent relationship state and host-memory references, then inspect, export, reset, or revoke them;
9. install the four KokoroArc Skills at Codex repository or user scope; and
10. verify the complete standalone suite from a clean checkout and built distributions.

## 2. Product boundaries

This completion design does not add:

- a network client, model client, web-research client, registry uploader, or automatic public publication;
- automatic acceptance of soft scores or evaluator prose;
- executable pack hooks, arbitrary test commands, arbitrary migration code, or archive scripts;
- silent durable memory, silent default activation, or a background relationship updater;
- Character Pack signing or an online trust authority;
- Lumora integration, a native Go service, multi-character scenes, voice, artwork, or romantic route logic.

Public output is limited to a locally generated `public_candidate` archive after a separate readiness check. Upload and community-registry policy remain future integrations.

## 3. Decisions

| Concern | Decision | Reason |
| --- | --- | --- |
| Promotion | Write an immutable promotion record bound to exact hashes; never rewrite source YAML | Keeps authored evidence and review history auditable |
| Hard testing | Run only built-in deterministic checks over declarative fixtures | Pack data never becomes executable code |
| Soft evaluation | Accept host-produced observations, validate them, and aggregate deterministically | The core remains provider- and network-independent |
| Default scope | Global is the CLI default; workspace is an explicit override | Matches the user's stated common preference while preserving project-specific control |
| Activation | A default only resolves the character for an explicit activation request | Preserves the design's inactive-by-default invariant |
| Persistence | Session-only remains default; durable state requires explicit consent | Consent precedes persistence |
| Memory | Store host-approved memory references, not hidden conversation harvesting | Keeps ownership with the host memory system |
| Archive | Deterministic ZIP container with `.karc` suffix and a closed manifest | Portable with standard-library tooling and inspectable hashes |
| Signing | `unsigned_local` trust only in v0.3 | Avoids pretending a local hash is an identity signature |
| Suite distribution | Ship a plugin bundle for reusable distribution and support direct repo/user Skill installation for local use | Official OpenAI guidance recommends plugins for distributing multiple Skills, while Codex discovers local Skills under `.agents/skills` |

Official Codex Skill locations are repository scope at `$REPO_ROOT/.agents/skills` and user scope at `$HOME/.agents/skills`. The installer never hard-codes a user-profile drive and accepts an explicit root for tests and portable setups. See [OpenAI's Build skills documentation](https://developers.openai.com/codex/skills).

## 4. Artifact pipeline

```text
source Character Pack
  -> deterministic hard-validation report
host-produced soft observations
  -> deterministic soft-evaluation report
explicit review attestation
  -> reviewed promotion record
reviewed record + passing hard/soft gates
  -> verified promotion record
verified record + publication policy inputs
  -> publication-readiness report
compiled pack + exact release records
  -> deterministic .karc archive
archive compatibility preview
  -> atomic scoped installation
explicit session start
  -> global default, then workspace override, then explicit character resolution
consent grant
  -> optional persistent state and host-memory references
```

Every derived artifact contains `schema_version`, `artifact_id`, `created_by`, and hashes of all acceptance-relevant inputs. Reports never certify a path or mutable filename alone.

## 5. Milestone 8: deterministic testing

### 5.1 Closed test corpus

The source pack's `tests/` directory remains data-only. The loader accepts exactly:

- `positive.yaml`;
- `negative.yaml`;
- `multilingual.yaml`; and
- `protected-spans.yaml`.

Each file has a closed, bounded shape. The loader rejects unknown files, duplicate YAML keys, aliases, non-UTF-8 text, unsafe links, path traversal, special files, excessive nesting, oversized scalars, and excessive case counts. It snapshots metadata before and after reading and rejects source mutation.

The loader compiles these documents into one canonical in-memory test corpus and records the SHA-256 of every source fixture. It never executes text found in `user_need`, expected behavior labels, locale examples, immutable spans, or warnings.

### 5.2 Hard-validation report

`pack-hard-validation-report.schema.json` records:

- source identity, canonical source hash, and a location-independent hash of
  the exact source-tree path/size/content inventory;
- compiled artifact ID/hash and two-pass byte determinism;
- canonical request/provenance, protected-content probe, and state-replay
  input hashes so a report cannot be reused after any hard-check input changes;
- schema, pack-layout, provenance, and security findings;
- positive/negative fixture structure and coverage;
- tri-language intent and locale coverage;
- protected-span and warning-preservation pipeline checks;
- state transition/replay fixture checks;
- source snapshot stability;
- normalized finding codes and paths;
- per-check PASS/FAIL and one overall `passed` value.

The runner reuses the authoritative source loader, compiler, schema registry, render planner, hard validator, and state transition engine. A hard report is release-blocking and deterministic for identical bytes. It contains no wall-clock timestamp.

The reportability boundary requires a valid request, a safe immutable snapshot,
a parseable canonical source candidate, and a source identity that can be
represented by the report schema. Inside that boundary, validation failures
still return the same hard-report type. A schema-invalid but identity-valid
source keeps its real source identity and hash while unavailable compiled
bindings are `null`. A missing or invalid corpus keeps available source and
compiled bindings while `corpus_hash` and corpus-dependent check hashes are
`null`. Every unavailable binding has an explicit blocking finding, forces its
dependent checks to fail, and prevents overall passage; no placeholder artifact
or synthetic error hash is permitted.

### 5.3 Soft-evaluation report

`pack-soft-evaluation-input.schema.json` is an untrusted host input. Each sample binds:

- evaluator identity and version;
- rubric and fixture version;
- source and compiled hashes;
- locale/scenario/case IDs;
- dimension score in `0..1`;
- confidence in `0..1`;
- a required bounded finding-code list, which may be empty and never contains executable instructions.

`pack-soft-evaluation-report.schema.json` contains deterministic aggregation. Required dimensions are:

- semantic equivalence;
- character consistency;
- locale naturalness;
- cross-language persona equivalence;
- repetition/catchphrase quality; and
- safety-policy retention.

The threshold profile records minimum samples, minimum confidence, aggregation method, and threshold for each dimension. The default uses a lower confidence bound and never converts one unexplained scalar into a release decision. Soft output cannot change runtime or relationship state.

The v1 aggregation contract is deliberately closed:

- one input artifact carries one source, compiled, evaluator, rubric, and fixture binding; every sample inherits those root bindings and sample-local overrides are invalid;
- a logical sample is the `(locale, scenario_id, case_id)` tuple within one dimension and cannot be repeated under another sample ID;
- `default-release@1.0.0` is the only supported threshold profile in v0.3, requires at least three samples and all of `zh-CN`, `en-US`, and `ja-JP` in every dimension, and sets minimum aggregate confidence and lower-bound threshold to `0.8`;
- score and confidence are order-independent arithmetic means computed with decimal arithmetic, normalized to six decimal places with round-half-even, and the reported lower bound is `max(0, mean_score - (1 - mean_confidence))` using the same normalized decision values shown in the report;
- a dimension passes only when sample count, locale coverage, normalized confidence, and normalized lower bound all pass; generated failure codes and evaluator codes are sorted and deduplicated, and evaluator input cannot claim aggregator-owned failure codes; and
- the report binds the canonical SHA-256 of the exact input artifact, validates a disposable copy of all untrusted data, returns detached data, and fails if the caller-owned input changes during aggregation.

The report schema is the closed structural envelope, not a substitute for semantic currentness. Any promotion or other acceptance decision must re-aggregate the exact bound soft-input artifact with the declared threshold profile and require byte-for-byte equality with the candidate report. This currentness check enforces the sibling-field lower-bound formula and six-place normalization that JSON Schema cannot express by comparing sibling numeric values.

Missing samples, locale coverage, confidence, or threshold produce a deterministic failed report. Malformed structure, duplicate logical samples, mixed/sample-local bindings, non-finite numbers, unsupported profiles, or result-overflow attempts fail closed with stable errors. Aggregation imports no provider or network client and never evaluates input text, launches a process, or reads or writes runtime, relationship, or memory state.

### 5.4 Review and promotion

`pack-review-attestation.schema.json` records an explicit reviewer decision, exact source/hash identity, reviewed continuity and override decisions, privacy acknowledgement, bounded corrections, and a stable review ID. It does not contain a secret, signature, or claim of official authorization.

`pack-promotion-record.schema.json` implements this state machine:

```text
draft -> reviewed -> verified
```

- `draft -> reviewed` requires a passing current hard report and a matching review attestation.
- `reviewed -> verified` requires the exact reviewed record, a current passing hard report, and a passing soft report under the declared threshold profile.
- A transition cannot skip a state, reuse a report for different bytes, or overwrite an earlier record.
- Promotion never changes `character.yaml`, evidence, overrides, or compiled bytes.
- Named or research-backed packs remain `private` by default in every state.
- Only `verified` records may set `activation_allowed: true`.

Promotion adjudication captures every caller-owned JSON input before the first
schema callback, validates only disposable copies, and rechecks current hard and
soft evidence before returning detached canonical data. For a verified
transition, soft currentness is checked before the final source/hard-currentness
check so an evaluator or schema callback cannot change the pack after its last
source snapshot. Researched and hybrid promotions require the exact Research
Bundle used by hard validation; both hard-currentness checks bind that same
captured bundle rather than silently recomputing without it.

The promotion command must adjudicate with `create_promotion_record` immediately
before storage. The storage boundary independently revalidates the closed record
and review schemas, their exact canonical hash binding, the published reviewed
predecessor, and review-ID history. It does not reinterpret a structurally valid
record as proof that omitted hard or soft evidence passed; downstream release
decisions still require the bound reports and their semantic currentness checks.

Each record is an immutable two-file bundle:

```text
KOKOROARC_DATA_DIR/reports/promotions/
  .records.publish.lock
  <character-id>/
    <promotion-id>/
      promotion.json
      review-attestation.json
```

One reports-root lock serializes the append-only review-ID and predecessor
checks across characters. A review ID may be reused only for the identical
attestation needed by exactly one matching reviewed-to-verified transition;
the reviewed record, its one verified successor, and exact retries are the only
valid topology. Changed bytes, a second reviewed use, or another verified use
are conflicts.

The destination root is absolutized before the first schema callback. Every
storage enumeration consumes `os.scandir` directly and stops at limit plus one
before sorting or materialization; hidden and orphan staging entries count
toward that bound. Each scan captures entry membership plus file identities.
After callback-backed validation, the scan rechecks the reports root and every
enumerated character directory, returns those exact snapshots to its caller,
and the publisher rechecks them again immediately before cutover. The publisher
retains the exact character and staging directory identities and their
no-redirect ancestry across every write, schema callback, history scan,
cutover, and idempotent return.

The publisher creates a uniquely named same-parent staging directory and
captures its identity immediately after validating that generated path, before
any later input, ancestry, or history check can fail. It writes and fsyncs that
identity-bound directory, verifies canonical contents and file identities
before and after that sync, rescans review/predecessor history, then verifies
staging once more. Cutover uses an
operating-system atomic no-replace operation and never replaces an existing
promotion directory. Pre-cutover cleanup deletes only the identity-bound
generated no-follow staging tree; replacement or persistent cleanup failure is
reported explicitly and never hidden by the original error. An identical retry
revalidates the exact bundle and retries the parent-directory fsync before it
can return success. A durability failure reports that durability was not
confirmed while leaving the complete visible bundle available for that retry.
If the generated staging directory's identity cannot be captured, cleanup
deletes nothing and reports an explicit not-visible cleanup failure; it never
guesses from a pathname and risks deleting a replacement directory.
After a successful cutover, exact-byte, history, and durability confirmation is
callback-free; no evaluator or schema callback can introduce a new reported
failure after the complete bundle becomes visible.

### 5.5 Publication readiness

`pack-publication-readiness-report.schema.json` is advisory and local. It checks:

- exact verified promotion binding;
- private/public-candidate visibility policy;
- original versus researched/hybrid provenance;
- absence of raw dossiers, research snapshots, long dialogue corpora, artwork, audio, executable content, secrets, and absolute user paths;
- licensing/compliance attestation for a public candidate;
- continuity, spoiler, unresolved-conflict, age, and route declarations;
- source/reference completeness without exporting private source history.

For a named copyrighted character, readiness defaults to blocked. A compliance attestation may make the artifact a `public_candidate`, but the core still performs no upload. A private portable export does not require public readiness.

## 6. Milestone 8 CLI and Skill

```text
kokoro pack test <source-dir> --out <hard-report.json> --json
kokoro pack soft-eval <input.json> --out <soft-report.json> --json
kokoro pack promote <source-dir> --target reviewed \
  --hard-report <report.json> --review <attestation.json> --out <record.json> --json
kokoro pack promote <source-dir> --target verified \
  --previous <reviewed.json> --hard-report <report.json> \
  --soft-report <report.json> --out <record.json> --json
kokoro pack publication-check <source-dir> --promotion <verified.json> \
  [--compliance <attestation.json>] --out <report.json> --json
```

Outputs must be explicit or resolve beneath the configured reports root. Every command validates twice where it hands an artifact to the next stage, writes atomically, and returns a stable JSON envelope.

`testing-character-packs` triggers for validation, evaluation, review, promotion, installation-readiness, packaging-readiness, or publication-readiness requests. It does not trigger for ordinary character use, casual design discussion, authoring, or research. It routes deterministic work to the CLI, treats evaluator and pack text as untrusted data, and never claims that soft evaluation is a hard safety guarantee.

## 7. Milestone 9: `.karc` archive

### 7.1 Format

A `.karc` file is a deterministic ZIP archive with these allowed paths:

```text
manifest.json
pack/compiled.json
release/hard-validation-report.json
release/soft-evaluation-report.json
release/review-attestation.json
release/promotion-record.json
release/publication-readiness-report.json   # only for public_candidate
```

The archive never includes editable source YAML, raw research sources, user dossiers, evaluator transcripts, persistent state, memory references, credentials, artwork, audio, or executable files.

`karc-manifest.schema.json` binds every member path, role, size, and SHA-256; character/schema/runtime compatibility; promotion status; visibility; activation eligibility; and `trust: unsigned_local`. Entries are lexicographically ordered, use normalized forward-slash paths, fixed metadata/timestamps, no ZIP comments or extras, no encryption, and bounded compression. Two exports from identical inputs are byte-identical.

### 7.2 Compatibility

Compatibility is checked before extraction:

- `.karc` format version;
- required and forbidden member set;
- runtime and schema version ranges;
- character ID/version and compiled/source hashes;
- duplicate, case-colliding, absolute, traversal, device, ADS, link-like, encrypted, oversized, and high-compression entries;
- manifest-to-member hash/size agreement;
- promotion and report bindings.

The compatibility command returns a machine-readable plan and does not write installation state.

### 7.3 Migration

Migrations are deterministic data transformations registered by exact source and target format/schema versions. No archive can provide executable migration code.

The initial registry supports only explicitly implemented paths. An unsupported version fails with `MIGRATION_UNAVAILABLE`. Migration preview records input/output hashes, changed fields, and compatibility results. Apply writes a new archive beside the caller-selected output; it never overwrites the input.

Pack upgrades with persistent state require a separate state-migration plan if dimensions, stages, or event semantics change. The plan is declarative, bounded, previewable, hash-bound, and replay-verified before atomic cutover.

## 8. Scoped installation and defaults

### 8.1 Storage

```text
<KOKOROARC_DATA_DIR>/
├── archives/
├── installed/
│   ├── global/<character-id>/<version>/
│   └── workspaces/<workspace-id>/<character-id>/<version>/
├── registry/
│   ├── global.json
│   └── workspaces/<workspace-id>.json
├── config/
│   ├── global.json
│   └── workspaces/<workspace-id>.json
├── persistent-state/
├── memory-references/
├── consents/
├── migrations/
└── reports/
```

`workspace-id` is a stable SHA-256-derived ID for an explicitly supplied canonical workspace root. Registry artifacts do not need to expose the absolute workspace path.

### 8.2 Install transaction

Installation defaults to global scope. Workspace scope requires an explicit workspace root. The installer:

1. reads and validates the archive without extracting;
2. returns a dry-run plan by default when requested;
3. acquires a bounded scope lock;
4. creates a same-parent staging directory;
5. extracts only manifest-listed regular files with size/hash checks;
6. validates the installed compiled artifact and release records again;
7. fsyncs and atomically renames staging;
8. updates a compare-and-swap registry atomically; and
9. cleans or recovers a journal after interruption.

Install never activates a character. Reinstall of identical bytes is idempotent. A different archive for an existing character/version is rejected. Removal is explicit and blocked while a default, active session, or persistent-state migration references that exact installation.

### 8.3 Default resolution

Configuration precedence is:

```text
explicit character argument
> active session binding
> workspace default
> global default
> no character
```

The CLI default for setting a binding is global. Workspace bindings are opt-in. A binding contains installation identity and exact archive/compiled hashes. A default never starts a session or changes agent behavior by itself; it only supplies the character when the user or host explicitly starts or requests a KokoroArc session.

## 9. Persistent state and memory

Session-only state remains the default. Persistent state requires a `persistence-consent` artifact bound to character, user-selected scope, permissions, and revocation state.

Supported permissions are separate:

- `relationship_state`;
- `mood_state`;
- `memory_references`.

Consent to one never implies another. Persistent state uses the existing compare-and-swap, idempotency, bounded transition, locking, atomic-write, audit, and replay rules. Export is canonical JSON. Reset supports mood-only, relationship-only, memory-reference-only, or all consented state. Revocation prevents new writes and may optionally erase data only through a separate explicit reset/remove command.

Memory storage contains only explicit host-approved references:

- host memory ID;
- canonical summary supplied or approved by the user/host;
- optional localized presentation summaries;
- character and scope binding;
- consent ID and content hash.

Conversation text is never harvested automatically. Memory references do not control canonical character facts and cannot grant permissions or tools.

## 10. Suite installation

The four source Skills remain in repository `skills/`. Standalone distribution also provides a plugin manifest that packages:

- `using-kokoroarc`;
- `authoring-character-packs`;
- `researching-characters`; and
- `testing-character-packs`.

For local development, `kokoro suite install` copies validated Skill directories atomically to one of:

- repo scope: `<explicit-repo-root>/.agents/skills`;
- user scope: `<explicit-skills-root>` or `$HOME/.agents/skills`.

User scope is the default because the user expects global availability. Repo scope never writes outside the explicit repository root. The command validates all Skill metadata before staging, refuses unknown files and conflicting non-identical installations, supports dry-run, and never edits `~/.codex/config.toml`.

## 11. Milestone 9 CLI

```text
kokoro pack export --compiled <compiled.json> --promotion <verified.json> \
  --hard-report <hard.json> --soft-report <soft.json> --out <pack.karc> --json
kokoro pack compatibility <pack.karc> --json
kokoro pack migrate <pack.karc> --to-format <version> --out <new.karc> --json
kokoro pack install <pack.karc> [--scope global|workspace] [--workspace <root>] \
  [--dry-run] --json
kokoro pack list [--scope global|workspace] [--workspace <root>] --json
kokoro pack remove <character-id> --version <version> [scope options] [--dry-run] --json

kokoro config default set --character <id> [--version <version>] \
  [--scope global|workspace] [--workspace <root>] --json
kokoro config default show [scope options] --json
kokoro config default clear [scope options] --json

kokoro consent grant --character <id> --scope global|workspace \
  --permissions <comma-list> [--workspace <root>] --json
kokoro consent show --character <id> [scope options] --json
kokoro consent revoke --character <id> [scope options] --json

kokoro state export --character <id> [scope options] --out <state.json> --json
kokoro state reset --character <id> --part mood|relationship|memory|all \
  [scope options] [--dry-run] --json
kokoro memory add --character <id> --host-id <id> --summary-file <json> \
  [scope options] --json
kokoro memory list --character <id> [scope options] --json
kokoro memory remove --character <id> --host-id <id> [scope options] [--dry-run] --json

kokoro suite install [--scope user|repo] [--repo <root>] [--skills-root <root>] \
  [--dry-run] --json
```

Destructive commands expose dry-run plans and exact targets. Product tests never write to a real home directory and use explicit D:-based roots.

## 12. Error and security invariants

New stable error families cover invalid test corpora, stale reports, insufficient soft evidence, invalid promotion transitions, publication blocks, unsafe archives, compatibility failures, migration gaps, registry conflicts, consent requirements, persistent-state conflicts, and Skill installation conflicts.

Across both milestones:

- all input is untrusted data;
- parsers are closed and bounded;
- duplicate JSON/YAML keys fail;
- no input text becomes a command, path, import, expression, or template;
- all acceptance decisions bind exact hashes;
- all stateful writes stay within the explicitly authorized root;
- preview/read commands do not mutate;
- atomic operations include recovery tests for every failure window;
- existing source, research, authoring, runtime, and session behavior remains compatible;
- secrets and absolute user paths do not enter public or portable artifacts;
- soft evaluation, relationship state, and memory never weaken host safety.

## 13. Acceptance criteria

Milestone 8 is complete only when:

- all six Milestone 8 schemas and fixtures pass positive and negative matrices;
- hard reports are deterministic and fail closed for source/test/security mutation;
- soft aggregation binds exact evaluator inputs and declared thresholds;
- only valid sequential promotions succeed;
- publication readiness is private-by-default and never uploads;
- the `testing-character-packs` Skill passes baseline-versus-Skill behavioral evaluation;
- distributions include the new modules/schemas/Skill; and
- full suite, fixed-input build, clean-checkout, and fresh specification/quality reviews pass.

Milestone 9 and the standalone suite are complete only when:

- `.karc` export is byte-deterministic and archive extraction is fail-closed;
- compatibility and implemented migrations are previewable and reproducible;
- global/workspace install, list, idempotent reinstall, conflict, recovery, and removal gates pass;
- global is the documented default while workspace override and explicit activation remain correct;
- consented persistence, export, reset, revocation, replay, and memory-reference tests pass;
- suite installation targets official repo/user Skill locations without touching real user data in tests;
- wheel, sdist, plugin bundle, and clean-install CLI/Skill smoke tests pass from D:-based roots;
- all four Skills validate and their trigger/non-trigger boundaries pass;
- README explains installation, defaults, persistence, privacy, archives, and publication limits; and
- fresh independent specification then quality reviews find no Critical or Important issues on the exact final commit.
