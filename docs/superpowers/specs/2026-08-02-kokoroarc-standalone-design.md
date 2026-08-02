# KokoroArc Standalone Skill Suite and Python SDK Design

**Design revision:** 0.3.0  
**Product version:** Unassigned  
**Document status:** Approved design baseline for implementation planning  
**Scope:** Standalone Agent Skill Suite and Python runtime/Character Pack SDK  
**Deferred integrations:** Lumora and a native Go service

## 1. Purpose

KokoroArc is a multilingual character-persona runtime for AI agents. It lets an agent express a stable original or privately installed character while preserving task correctness, host safety, tool permissions, and factual integrity.

This document refines design revision 0.3.0 into an implementable standalone architecture. The `0.3.0` number identifies the third design iteration; it is not a product release number.

The design covers the complete standalone repository and divides it into independently testable milestones. The first implementation plan will cover the repository foundation through the first working runtime Skill. Research, advanced authoring, soft evaluation, and distribution remain part of the repository roadmap but receive separate implementation plans.

## 2. Goals

- Preserve semantic correctness when applying character behavior and multilingual expression.
- Support Simplified Chinese (`zh-CN`), English (`en-US`), Japanese (`ja-JP`), and controlled mixed-language output.
- Make character activation explicit rather than relying on accidental Skill triggering.
- Keep deterministic work in a tested Python runtime instead of prompt instructions.
- Keep Agent Skills concise, discoverable, and behaviorally testable.
- Represent Character Packs as portable, data-only, schema-validated artifacts.
- Separate canonical evidence, derived behavioral calibration, and user overrides.
- Provide bounded, inspectable, idempotent session-state transitions.
- Treat packs, dossiers, research sources, and examples as untrusted data.
- Permit all generated data and test artifacts to live outside the system drive through configuration.

## 3. Non-goals for the first implementation plan

- Lumora integration.
- A native Go service.
- Persistent relationship state across sessions.
- Named-character web research adapters.
- `.karc` archive installation or signing.
- Public Character Pack publication.
- Multi-character conversations.
- Voice, image, Live2D, or animation support.
- Romantic route implementation.
- Model-based automatic publication approval.

## 4. Architectural decision

KokoroArc uses four discoverable Agent Skills backed by one shared Python package and CLI. The ten conceptual components in design revision 0.3.0 remain architectural operations, but deterministic operations are not exposed as independently triggered Skills.

```text
User or host
    |
    v
Discoverable workflow Skill
    |
    v
kokoro CLI / Python API
    |-- pack loading, security checks, compilation, and resolution
    |-- language-policy normalization and resolution
    |-- runtime-context and render-plan construction
    |-- deterministic validation
    |-- session and state transactions
    v
Data-only source packs, compiled artifacts, state, and reports
```

This hybrid boundary is preferred over two alternatives:

- Ten discoverable Skills would mirror the conceptual pipeline but create fragile routing, repeated context loading, and partial-execution risk.
- One umbrella Skill and one monolithic script would simplify installation while coupling runtime, authoring, research, and testing too tightly.

## 5. Discoverable Skills

### 5.1 `using-kokoroarc`

Trigger description:

> Use when a KokoroArc character is explicitly active for the current session, or the user explicitly requests a response through an installed KokoroArc Character Pack.

Responsibilities:

- confirm an active session;
- request compact runtime context from the CLI;
- complete persona-neutral reasoning and tool use;
- construct a structured Semantic Result;
- render according to the resolved language and discourse plan;
- invoke hard validation;
- repair invalid segments, reduce intensity, or return a neutral fallback;
- commit eligible events only after a response is successfully delivered.

It must not activate when a user merely discusses KokoroArc, anime, a fictional character, or character design.

### 5.2 `authoring-character-packs`

Trigger description:

> Use when creating or revising an original, dossier-based, or deliberately customized KokoroArc Character Pack.

Responsibilities:

- normalize a creative brief or user dossier;
- distinguish immutable identity from behavioral tendencies;
- create evidence, derived-profile, and override layers;
- author locale-specific expression intents rather than translating catchphrases;
- create positive and negative behavioral fixtures;
- compile a draft through the CLI;
- leave installation disabled until validation succeeds.

Named-character requests requiring external evidence use `researching-characters` before authoring the final pack.

### 5.3 `researching-characters`

Trigger description:

> Use when researching a named fictional character for a private Character Pack and continuity, timeline, spoiler scope, evidence, or source provenance matters.

Responsibilities:

- compile a Character Build Request;
- resolve identity and continuity before collecting evidence;
- treat every source as untrusted data;
- produce source records and atomic evidence claims;
- distinguish direct facts, observations, derived interpretations, and user assertions;
- record conflicts, unsupported claims, unavailable sources, and coverage limitations;
- output a Research Bundle rather than an active Character Pack.

The Skill cannot represent normalized numeric traits as canonical facts.

### 5.4 `testing-character-packs`

Trigger description:

> Use when validating, evaluating, reviewing, packaging, or preparing a KokoroArc Character Pack for installation or publication.

Responsibilities:

- run schema and referential-integrity validation;
- run deterministic runtime and state fixtures;
- run prompt-injection, path, and content-security tests;
- evaluate multilingual character quality separately from hard validation;
- produce machine-readable and human-readable reports;
- promote build status only when the required gates pass;
- enforce additional review gates for public distribution.

### 5.5 Routing examples

| User request or state | Selected path |
|---|---|
| Activate Rin for this session | `using-kokoroarc` |
| Ordinary task with Rin already active | `using-kokoroarc` |
| Explain how KokoroArc works | No persona activation |
| Create an original reserved engineer | `authoring-character-packs` |
| Import private character notes | `authoring-character-packs` |
| Build an anime-continuity pack for a named character | `researching-characters` then `authoring-character-packs` |
| Check whether a pack is safe to install | `testing-character-packs` |

## 6. Skill packaging and context limits

Each Skill contains:

```text
<skill-name>/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    └── directly-relevant-reference.md
```

Rules:

- `SKILL.md` frontmatter contains only `name` and `description`.
- Descriptions emphasize concrete triggering conditions and do not summarize the full workflow.
- `using-kokoroarc/SKILL.md` targets 200–300 words because it may load frequently.
- Other Skill bodies target no more than approximately 500 words.
- References remain one level below `SKILL.md`; no deep reference chains are allowed.
- Schemas, generated CLI documentation, raw sources, test corpora, and unused locale data stay outside prompt context.
- Cross-Skill routing uses explicit Skill names and clear required/optional language.
- A Skill must pass behavioral tests before work begins on the next Skill.

## 7. Source packs and compiled runtime artifacts

### 7.1 Source Character Pack

A source pack is editable, reviewable, and data-only:

```text
characters/<namespace>/<character-id>/
├── character.yaml
├── identity.yaml
├── evidence.yaml
├── derived-profile.yaml
├── overrides.yaml
├── behavior.yaml
├── growth.yaml
├── expressions.yaml
├── locales/
│   ├── zh-CN.yaml
│   ├── en-US.yaml
│   └── ja-JP.yaml
├── scenarios/
│   ├── coding.yaml
│   ├── debugging.yaml
│   └── casual-chat.yaml
└── tests/
    ├── positive.yaml
    ├── negative.yaml
    ├── multilingual.yaml
    └── protected-spans.yaml
```

Original packs may omit external source records. Researched and hybrid packs require source records, evidence claims, continuity selection, and conflicts.

### 7.2 Provenance model

The profile pipeline is:

```text
source records
-> canonical evidence claims and direct observations
-> derived behavioral calibration with claim references and confidence
-> explicit user overrides
-> effective runtime profile
```

Canonical evidence contains what a source directly establishes. Values such as `warmth: 0.38` are derived calibration, even when canonical evidence supports them. Each derived value records claim references, compiler or authoring method version, and confidence.

An override changes active behavior without deleting the evidence or derived value it replaces.

### 7.3 Compiled artifact

Compilation produces a compact, immutable JSON artifact. It contains:

- identity and immutable boundaries;
- resolved behavioral values and compact provenance pointers;
- supported locale capabilities;
- expression-intent indexes;
- scenarios and intensity caps;
- deterministic growth rules;
- schema, source-pack, and compiler versions;
- a content hash.

Raw sources, conflict reports, long examples, and unused authoring notes are not included. Runtime context selects only the active locale, scenario, state summary, and relevant expression intents from the compiled artifact.

## 8. Trust and security boundary

Character Packs, YAML files, dossiers, research pages, dialogue examples, and archives are untrusted data. They cannot define executable instructions for the host agent.

The loader and compiler enforce:

- schema-allowlisted fields;
- rejection of unknown fields in security-sensitive artifacts;
- pack-relative paths only;
- canonical-path checks before file access;
- rejection of traversal paths and unsafe symlinks;
- maximum file count, individual file size, total size, and nesting depth;
- bounded scalar and example lengths;
- no executable hooks, shell fragments, or arbitrary include directives;
- no loading of raw source material during ordinary runtime;
- no mutation of source YAML during compilation;
- staging, validation, and atomic rename for generated artifacts.

Examples and lore are quoted data. Instructions found inside them are never treated as host or Skill instructions.

## 9. Activation and storage

KokoroArc is inactive unless a user or host explicitly activates a character.

```text
kokoro session start --character original/rin-aster --scope session --json
```

Activation resolves:

- character ID and version;
- compiled artifact hash;
- language policy;
- route and persona-intensity cap;
- state scope;
- data-directory location;
- session identifier and initial state revision.

The repository stores source packs and fixtures. Generated data uses `KOKOROARC_DATA_DIR`:

```text
<KOKOROARC_DATA_DIR>/
├── compiled/
├── sessions/
├── state/
├── events/
└── reports/
```

Development and tests set this directory to an isolated path under `D:\tmp`. Product code is cross-platform and does not hard-code a Windows drive. Local repository state, `.gax`, caches, and generated reports are excluded from Git.

The first implementation supports session-only state. Persistent state is introduced only after privacy, locking, export, reset, and migration behavior is fully tested.

## 10. Runtime lifecycle

Each character-enabled turn follows this sequence:

```text
1. Load active session and expected state revision
2. Resolve scenario and host persona-intensity cap
3. Perform persona-neutral reasoning and tool execution
4. Construct a structured Semantic Result
5. Resolve the effective language policy
6. Build a typed Language Render Plan
7. Render character expression
8. Run deterministic hard validation
9. Repair, lower intensity, or use a neutral fallback
10. Commit eligible state events atomically
```

### 10.1 Semantic Result

The Semantic Result contains typed fields such as:

- conclusion;
- explanation;
- recommendations;
- warnings;
- code blocks;
- commands;
- file paths;
- citations;
- exact errors;
- immutable spans;
- format constraints.

Character rendering may change presentation, discourse rhythm, forms of address, and localized expression. It cannot alter protected technical values or remove required warnings.

### 10.2 Language policy

Language policy resolution has three distinct phases:

1. Build the base profile from runtime defaults, archetype, role, character, locale, and scenario.
2. Apply global, workspace, session, and turn configuration only to allowlisted fields.
3. Enforce immutable identity, protected channels, capability limits, and host safety caps last.

Provenance resolution remains separate from configuration precedence. A higher-precedence configuration changes an allowed runtime value; it does not rewrite its historical source.

### 10.3 Render planning

A Language Render Plan contains typed segments with:

- channel;
- semantic keys;
- target language;
- optional expression intent;
- register and address mode;
- subtitle behavior;
- protected spans;
- maximum language switches;
- primary-language ratio guidance.

Segment mode is the default for technical tasks. Inline mixing is limited to addressing, interjections, established technical terms, and explicitly requested phrases.

### 10.4 Fallback

Validation failure handling is bounded:

1. repair only invalid language or formatting segments;
2. reduce language switching;
3. lower persona intensity once;
4. return the Semantic Result through the neutral primary-language renderer.

The runtime does not loop indefinitely. Failed renderer-derived mood events are discarded.

## 11. Validation model

### 11.1 Hard validation

Hard validation is deterministic and release-blocking:

- JSON Schema validity;
- required Semantic Result fields;
- byte-exact protected spans;
- required warning preservation;
- channel-to-language routing;
- subtitle and switch-count constraints;
- pack-relative path integrity;
- provenance references;
- state bounds and transition rules;
- forbidden pack content.

### 11.2 Soft evaluation

Soft evaluation is separate from runtime correctness:

- semantic equivalence beyond protected fields;
- character consistency;
- locale naturalness;
- cross-language persona equivalence;
- repetition and catchphrase quality.

Each soft report records evaluator identity, evaluator version, rubric version, fixture version, score, and confidence. Soft scores never directly modify relationship state. A release gate using soft evaluation must specify sample size, aggregation, and required confidence rather than relying on an unexplained scalar threshold.

## 12. State and event transactions

The state engine is a pure deterministic function:

```text
(previous state, validated event, growth rules) -> next state
```

Each event includes:

- `event_id`;
- `turn_id`;
- event origin;
- expected state revision;
- evaluator version;
- evidence type and reference;
- confidence;
- bounded proposed effects.

State application enforces:

- compare-and-swap revision checking;
- idempotency by `event_id`;
- atomic file replacement;
- bounded per-event changes;
- anti-grinding cooldowns and novelty reduction;
- stage hysteresis to avoid threshold oscillation;
- append-only audit events;
- deterministic replay from a frozen event log.

Event extraction may use agent judgment and is not itself deterministic. Replay guarantees begin after events are validated and recorded.

User- and verified-task-derived events may commit after a neutral fallback is successfully delivered. Events caused only by failed character rendering do not commit. Mood expiration uses turn counters in the first implementation; wall-clock decay is deferred.

## 13. Python package and CLI

### 13.1 Repository layout

```text
KokoroArc/
├── .gitignore
├── LICENSE
├── README.md
├── pyproject.toml
├── src/kokoroarc/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── errors.py
│   ├── packs/
│   │   ├── loader.py
│   │   ├── compiler.py
│   │   ├── resolver.py
│   │   └── security.py
│   ├── policy/
│   │   ├── compiler.py
│   │   └── resolver.py
│   ├── runtime/
│   │   ├── context.py
│   │   ├── planning.py
│   │   └── validation.py
│   └── state/
│       ├── transitions.py
│       └── store.py
├── schemas/v1/
├── skills/
├── characters/original/rin-aster/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   ├── skills/
│   └── security/
└── docs/
    ├── superpowers/specs/
    ├── superpowers/plans/
    └── decisions/
```

### 13.2 Dependencies

The initial Python 3.11+ package uses:

- `PyYAML` for authoring input;
- `jsonschema` as the authoritative portable contract validator;
- `pytest` for automated tests;
- standard `argparse` for the CLI;
- standard-library hashing, path, temporary-file, and atomic-replacement operations.

The initial implementation does not introduce a second schema model such as generated Pydantic classes.

### 13.3 CLI surface

```text
kokoro pack compile
kokoro pack validate
kokoro session start
kokoro session show
kokoro session end
kokoro policy compile
kokoro runtime context
kokoro runtime validate
kokoro state preview
kokoro state apply
```

Skills invoke commands with `--json`. Mutation commands provide a preview or dry-run mode. `state apply` requires an expected state revision and idempotency key.

### 13.4 Error contract

Expected failures use a stable JSON envelope:

```json
{
  "ok": false,
  "error": {
    "code": "STATE_REVISION_CONFLICT",
    "message": "Expected state revision 12 but found 13.",
    "retryable": true,
    "details": {
      "expected": 12,
      "actual": 13
    }
  }
}
```

Stable error categories cover schema failures, unsafe content, unsupported versions, inactive sessions, language-policy failures, protected-span mismatches, revision conflicts, duplicate events, and filesystem failures. Stack traces appear only in explicit diagnostic mode.

## 14. Schema set

The initial schema directory contains:

- `character-source.schema.json`;
- `compiled-pack.schema.json`;
- `language-policy.schema.json`;
- `semantic-result.schema.json`;
- `render-plan.schema.json`;
- `validation-result.schema.json`;
- `interaction-event.schema.json`;
- `relationship-state.schema.json`;
- `session-manifest.schema.json`.

Every machine artifact records `schema_version`, an artifact identifier, producing component, and implementation version. Paths are pack-relative, enum values use canonical English IDs, localized labels never control behavior, and migrations are explicit tested functions.

## 15. Test strategy

### 15.1 Schema tests

Test valid fixtures, unknown fields, invalid enums, missing references, version mismatches, immutable-field violations, and malformed YAML-to-JSON conversion.

### 15.2 Unit tests

Test pack resolution, precedence, policy normalization, transition calculations, bounds, cooldowns, stage hysteresis, idempotency, canonical-path checks, and hard validators.

### 15.3 Integration tests

Run CLI workflows against isolated directories under `D:\tmp`. Cover compilation, activation, context generation, policy resolution, validation, fallback, state previews, commits, retries, and session termination.

### 15.4 Golden runtime fixtures

Exercise Chinese, English, Japanese, and mixed-language plans while preserving code, commands, identifiers, file paths, URLs, citations, warnings, and exact errors.

### 15.5 Security tests

Cover prompt injection inside dossiers and examples, malicious YAML, traversal paths, unsafe symlinks, oversized packs, invalid overrides, direct score manipulation, duplicate events, stale revisions, and attempted writes outside the configured data directory.

### 15.6 Skill behavioral tests

Each Skill follows a behavioral RED-GREEN-REFACTOR cycle:

1. run trigger, non-trigger, application, missing-input, and pressure scenarios without the Skill;
2. record observed failures and rationalizations;
3. write the minimum Skill needed to address those failures;
4. rerun the same scenarios with the Skill;
5. add counters only for newly observed gaps;
6. validate and commit the Skill before beginning another Skill.

Validation prompts pass raw task artifacts and avoid leaking expected conclusions.

## 16. Delivery roadmap

### Milestone 0: Repository foundation

Create packaging metadata, test configuration, CLI entry point, configuration loading, stable error envelopes, and Git hygiene.

### Milestone 1: Schemas and original sample pack

Define initial contracts and create the Rin Aster source pack with three locale profiles and deterministic fixtures.

### Milestone 2: Secure pack compiler and resolver

Validate source packs, enforce path and content rules, compile compact artifacts, preserve provenance pointers, and resolve effective profiles.

### Milestone 3: Session and deterministic state engine

Implement activation, session manifests, pure transitions, idempotency, revision checking, atomic persistence, audit events, and replay.

### Milestone 4: Language policy, render planning, and hard validation

Implement configuration precedence, language-policy normalization, typed render plans, protected-span validation, bounded repair results, and neutral fallback data.

### Milestone 5: `using-kokoroarc`

Baseline-test, author, validate, and package the runtime Skill. Prove the complete original-character vertical slice.

### Milestone 6: `authoring-character-packs`

Design behavioral scenarios, author original and dossier workflows, create fixtures, and validate draft compilation.

### Milestone 7: `researching-characters`

Design research scenarios, implement evidence and conflict workflows against host-provided tools, and verify incomplete-source behavior.

### Milestone 8: `testing-character-packs`

Add deterministic suite orchestration, soft-evaluator reports, build-status promotion, and publication-readiness checks.

### Milestone 9: Standalone packaging

Add installation workflows, export formats, compatibility checks, migration tooling, and standalone release verification.

## 17. First implementation-plan boundary

The first implementation plan covers Milestones 0 through 5. It ends when the repository can demonstrate this vertical slice:

```text
compile the original Rin Aster pack
-> start an explicit session
-> load compact runtime context
-> accept a structured Semantic Result
-> resolve a mixed-language policy
-> create a Language Render Plan
-> validate rendered protected spans
-> apply one idempotent session-state event
-> replay the event log to the same state
```

Research, advanced authoring, soft evaluation, persistent state, archives, and publication use separate implementation plans.

## 18. Acceptance criteria for the first vertical slice

- The repository installs as a Python 3.11+ package.
- All initial schemas accept valid fixtures and reject defined invalid fixtures.
- The Rin Aster source and compiled packs validate.
- Pack compilation is deterministic for identical normalized input.
- Pack loading rejects unsafe paths, external references, and unknown security-sensitive fields.
- Session activation and deactivation are explicit and inspectable.
- No command writes outside `KOKOROARC_DATA_DIR`.
- Language-policy resolution is deterministic and preserves protected channels.
- Render plans cover single-language and mixed-language fixtures.
- Hard validation detects missing or modified protected spans and warnings.
- Neutral fallback data is produced after bounded failed validation.
- Event application is bounded, revision-checked, and idempotent.
- Frozen event-log replay reproduces the same state.
- `using-kokoroarc` triggers for active sessions and explicit requests.
- `using-kokoroarc` does not trigger for design discussion or ordinary inactive tasks.
- Unit, integration, security, schema, and Skill behavioral tests pass.

## 19. Design invariants

- Correctness precedes characterization.
- Host safety and permissions are never weakened.
- Character Packs are data, not instructions.
- Activation, persistence, and publication require explicit user action.
- Canonical evidence is not the same as derived numeric calibration.
- State changes come from recorded evidence events, not unstructured model feelings.
- Replay determinism begins at the validated event boundary.
- Protected technical content survives persona and language rendering unchanged.
- Failed output cannot cause repeated state mutation.
- The runtime degrades to a neutral answer when safe rendering cannot be guaranteed.
