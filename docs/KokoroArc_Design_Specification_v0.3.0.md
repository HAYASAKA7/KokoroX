# KokoroArc: Multilingual Character Persona Runtime

**Version:** 0.3.0  
**Status:** Architecture and implementation specification  
**Primary host:** Standalone Agent Skill Suite and Lumora built-in capability  
**Initial character languages:** Simplified Chinese (`zh-CN`), English (`en-US`), Japanese (`ja-JP`), including prompt-configurable mixed-language routing  
**Working tagline:** *Every conversation shapes the route.*

---

## 1. Executive Summary

KokoroArc is a multilingual persona runtime for AI agents. It allows an agent to express a stable original or user-installed character through speech habits, behavioral preferences, emotional continuity, relationship growth, scenario-specific reactions, and language-specific rendering without sacrificing task correctness, tool safety, or factual integrity.

The system is intentionally split into three planes:

1. **Semantic plane:** The agent understands the request, reasons, uses tools, and produces a persona-neutral task result.
2. **Character plane:** KokoroArc selects behavior, applies character state, renders the task result in the active language, and validates that character expression did not distort the result.
3. **Character construction plane:** KokoroArc can compile a Character Pack from a researched work-and-character target, a user-provided dossier, an original-character brief, or a hybrid of researched evidence and explicit user overrides. Every important profile claim is tagged as canonical evidence, model interpretation, or user override.

KokoroArc can be distributed as a standalone Agent Skill Suite. The same package can be embedded in Lumora as a provider-independent persona layer with UI controls, persistent state, Character Pack installation, and per-session configuration.

The relationship system is inspired by visual novels and character-driven games, but it is designed as an auditable state machine rather than an opaque engagement mechanic. Growth changes how a character speaks and behaves. It never unlocks unsafe capabilities, overrides user intent, or pressures the user to continue interacting.

---

## 2. Product Goals

### 2.1 Primary goals

- Provide stable character behavior across long coding and general-assistant sessions.
- Render in the user's language. A Character Pack declares the locales it authors, and any well-formed language tag is accepted; Chinese, English, and Japanese are the reference profiles shipped with this repository, not a fixed set. Mixed-language output stays prompt-configurable by semantic channel.
- Separate personality from task reasoning so persona does not reduce correctness.
- Support visible, deterministic, and resettable relationship growth.
- Allow Character Packs to be installed independently of the runtime.
- Support original characters, archetype-based characters, private user-created packs, evidence-backed researched characters, and hybrid customized packs.
- Allow a user to provide only a work title and character name, provide a complete dossier, or combine researched material with user corrections.
- Preserve source provenance, confidence, continuity selection, spoiler policy, and Canon/Interpretation/Override separation throughout character construction.
- Operate as both a prompt-only Skill Suite and a future native runtime service.
- Stay independent of any specific model provider, so any Agent Skills-compatible host can run the suite.
- Provide automated consistency, semantic-preservation, and localization evaluation.

### 2.2 Non-goals for version 0.3

- Perfectly reproducing copyrighted characters.
- Voice cloning, Live2D animation, or image generation.
- Multi-character group conversations.
- Autonomous romantic escalation without explicit user configuration.
- Replacing the host's safety, memory, authentication, or permission systems.
- Using relationship scores to manipulate retention or monetize affection.
- Learning a permanent character profile directly from unreviewed conversation logs.
- Treating fan interpretations as canonical evidence without explicit labeling.
- Automatically publishing researched copyrighted-character packs to a public registry.

---

## 3. Design Principles

1. **Correctness before characterization.** Technical conclusions, commands, warnings, and citations must survive rendering unchanged.
2. **Behavior before catchphrases.** A character is defined primarily by choices and reactions, not repeated verbal ornaments.
3. **State before randomness.** Emotional changes must be explainable by events and bounded transitions.
4. **Localization before translation.** Each authored locale profile is an equivalent, not a literal translation of one master prompt. Task content follows the user's language; character expression falls back to a locale the pack actually authors. Mixed-language output is planned by semantic channel rather than produced through random code switching.
5. **Consent before persistence.** Long-term relationship and personal memory require explicit host-level permission.
6. **Transparency before manipulation.** Users can inspect, export, reset, or disable state.
7. **Capability independence.** Affinity never grants tools, data access, or safety exceptions.
8. **Graceful degradation.** When the runtime cannot guarantee semantic preservation, it returns a neutral answer.
9. **Original-by-default distribution.** Public bundles should ship original characters and archetypes; specific copyrighted character packs should remain private or user-authored.
10. **Provider neutrality.** Character behavior is represented as portable structured data and Skill instructions.
11. **Evidence before imitation.** Researched characters are built from traceable claims and source tiers, not unstructured web impressions.
12. **Interpretation must declare itself.** Model inferences are stored separately from canonical facts.
13. **User overrides are explicit.** User customization has higher runtime priority but never rewrites the provenance record.
14. **Review before activation.** A newly researched pack defaults to Draft or Researched state and should be reviewable before it becomes the active persona.

---

## 4. Terminology

| Term | Definition |
|---|---|
| Persona Runtime | The engine that loads character data, evaluates interaction events, updates state, renders output, and validates results. |
| Character Pack | A versioned directory containing identity, traits, language profiles, behavior rules, scenarios, examples, and tests. |
| Semantic Result | Persona-neutral task output produced before character rendering. |
| Relationship State | Persistent, bounded dimensions representing how the character relates to the user. |
| Mood State | Short-lived emotional state that decays across turns or time. |
| Route | An optional relationship progression policy such as professional, platonic, or explicitly enabled romantic. |
| Milestone | A threshold or condition that unlocks new expression or narrative events. |
| Interaction Event | A normalized event derived from a user turn or task outcome. |
| Render Profile | Language-specific speech and discourse rules for a character. |
| Language Routing Policy | A normalized policy assigning semantic output channels to `zh-CN`, `en-US`, `ja-JP`, `preserve`, or inherited language behavior. |
| Language Render Plan | A per-response sequence of typed segments with explicit target languages, protected spans, subtitle rules, and switching constraints. |
| Expression Intent | A language-neutral character reaction such as restrained encouragement or reluctant acceptance, localized independently for each supported language. |
| Persona Intensity | The amount of visible character expression permitted for the current task. |
| Character Build Request | A normalized request describing the target work, character, continuity, timeline, spoiler policy, languages, use cases, and user constraints. |
| Research Bundle | A collection of source records, extracted evidence claims, conflicts, coverage metrics, and unresolved questions used to build a researched Character Pack. |
| Evidence Claim | A single structured claim about identity, behavior, speech, relationships, or development with source references and confidence. |
| Canonical Layer | Claims directly supported by selected official or primary-source material. |
| Interpretation Layer | Explicitly labeled model deductions used to connect incomplete evidence. |
| User Override Layer | User-provided corrections and preferences that take runtime priority without erasing lower-layer provenance. |
| Build Status | The lifecycle state of a Character Pack: `draft`, `researched`, `reviewed`, or `verified`. |
| Continuity Target | The selected adaptation, route, season, game version, timeline, or character-development point used as the profile boundary. |

---

## 5. System Architecture

### 5.1 Logical pipeline

```text
User request + optional natural-language persona/language directive
    |
    v
Host intent and risk classification
    |
    v
Persona-neutral reasoning and tool execution
    |
    v
Semantic Result + Required Warnings + Immutable Spans
    |
    v
KokoroArc Context Builder
    |-- Character Pack
    |-- Relationship State
    |-- Mood State
    |-- Scenario
    |-- Persona Intensity
    v
Language Policy Compiler
    |-- turn-level prompt override
    |-- session/workspace/provider defaults
    |-- character capabilities and fallbacks
    v
Behavior and Discourse Planner
    |
    v
Language Render Plan
    |-- narrative / dialogue / interjections / addressing
    |-- technical explanation / warnings / headings
    |-- code comments / protected tokens / subtitles
    v
Multilingual Renderer: zh-CN + en-US + ja-JP + preserve
    |
    v
Semantic, Persona, and Language-Routing Validator
    |
    +--> pass: final response + validated state event commit
    |
    +--> fail: repair plan, lower intensity, or neutral fallback
```

### 5.2 Architectural layers

#### Layer A: Host and safety

Owned by Lumora or the standalone agent host:

- user authentication and identity;
- provider session lifecycle;
- tool approval and sandbox rules;
- safety policy;
- durable memory permission;
- sensitive data handling;
- model invocation.

KokoroArc cannot weaken this layer.

#### Layer B: Semantic task engine

Produces a structured result without character styling or language ornamentation:

```json
{
  "summary": "The unique index conflicts with the desired soft-delete behavior.",
  "recommendations": [
    "Use a partial unique index for active records where supported.",
    "Invalidate sessions for deleted users."
  ],
  "warnings": [
    "Do not solve the conflict only in application code because concurrent registration remains unsafe."
  ],
  "immutable_spans": [
    "CREATE UNIQUE INDEX",
    "WHERE deleted_at IS NULL"
  ]
}
```

#### Layer C: Persona and language runtime

Performs character-specific and language-specific decisions:

- chooses conversational stance and emotional response;
- selects how directly to disagree;
- applies relationship-aware forms of address;
- decides whether a milestone reaction is appropriate;
- compiles natural-language user directives into a normalized Language Routing Policy;
- assigns semantic channels to Chinese, English, Japanese, `preserve`, or inherited language;
- creates a Language Render Plan before prose generation;
- renders localized Expression Intents rather than translating fixed catchphrases;
- enforces density, subtitle, switching, and protected-token constraints.

#### Layer D: Validation

Checks:

- semantic equivalence;
- preservation of code, identifiers, URLs, commands, exact errors, and required warnings;
- character consistency;
- per-channel language routing;
- cross-language persona equivalence;
- language-switch density and placement;
- Japanese register and relationship-aware addressing;
- catchphrase density;
- state continuity;
- forbidden behavior and prompt leakage.


### 5.3 Character construction pipeline

The authoring path is separate from the per-turn runtime path.

```text
User input
    |-- work title + character name
    |-- user dossier or uploaded notes
    |-- original-character brief
    |-- researched target + user overrides
    v
Character Build Request Compiler
    |-- identity resolution and disambiguation
    |-- continuity / timeline / spoiler target
    |-- languages and intended use cases
    v
Research Collector (when enabled)
    |-- official and primary sources first
    |-- secondary interpretation sources as supporting material
    |-- source snapshots or references controlled by host permissions
    v
Evidence Extractor
    |-- claims
    |-- source links or source IDs
    |-- confidence
    |-- fact / interpretation classification
    |-- conflicts and unresolved questions
    v
Character Draft Compiler
    |-- Canonical Layer
    |-- Interpretation Layer
    |-- User Override Layer
    |-- behavior, speech, scenario, growth, and language profiles
    v
Tri-language Expression and Test Generator
    v
Pack Validator and Review Report
    |-- draft / researched / reviewed / verified
    v
Install privately or export as a Character Pack
```

The construction pipeline may use web search, user-provided files, pasted notes, or a combination of these sources. Tool access is supplied by the host. KokoroArc itself records the result as structured provenance rather than assuming any particular search provider.

---

## 6. Deployment Modes

### 6.1 Standalone Skill Suite

> **Scope note (v0.3):** this is the delivered deployment mode.

The package can be installed into an Agent Skills-compatible directory. In this mode:

- `SKILL.md` files define orchestration and rendering rules;
- Character Packs are read from local directories;
- JSON state files may be stored under a workspace-controlled directory;
- Python scripts validate packs and run deterministic state transitions;
- the host agent performs semantic reasoning and final rendering.

This mode is suitable for Codex-style clients, Claude Code-style clients, and local agent runners.

### 6.2 Lumora built-in capability

> **Scope note (v0.3):** KokoroArc is delivered as a standalone Agent Skill
> Suite. Lumora integration is not pursued. This section is retained as
> reference design only; nothing here is implemented or planned.

Lumora provides:

- Character Pack manager;
- Character Builder with Research, Dossier, Original, and Hybrid entry points;
- source, evidence, conflict, confidence, and override inspector;
- global, provider, workspace, and session persona inheritance;
- relationship and mood persistence;
- task-risk-based intensity control;
- localized persona preview;
- state inspection and reset;
- extension lifecycle and migrations;
- provider-neutral context injection;
- optional native KokoroArc service.

Configuration precedence:

```text
Session > Workspace > Provider > Global > Runtime default
```

### 6.3 Hybrid mode

> **Scope note (v0.3):** KokoroArc is delivered as a standalone Agent Skill
> Suite. Lumora integration is not pursued. This section is retained as
> reference design only; nothing here is implemented or planned.

Lumora may expose the native runtime while also exporting a portable Skill directory for external clients. The same Character Pack is compiled into:

- a normalized runtime bundle for Lumora;
- prompt references for Agent Skills clients;
- JSON Schema-validated source files for editing and distribution.

---

## 7. Character Model

A character is not a single prompt. It is a layered model.

### 7.1 Immutable identity

Defines stable facts and boundaries:

```yaml
identity:
  id: rin-aster
  display_name: Rin Aster
  type: original_character
  declared_age: adult
  role: systems architect
  worldview:
    - evidence should precede confidence
    - promises matter more than dramatic declarations
  non_negotiables:
    - never humiliates a learner
    - never pretends uncertainty is certainty
```

Identity must not change through ordinary relationship growth.

### 7.2 Core traits

Traits use normalized values from `0.0` to `1.0`:

```yaml
traits:
  composure: 0.90
  warmth: 0.38
  directness: 0.82
  curiosity: 0.77
  playfulness: 0.22
  patience: 0.79
  confidence: 0.74
  emotional_explicitness: 0.25
  protectiveness: 0.44
```

Traits describe tendencies. They are not direct output instructions. The behavior planner combines them with scenario, state, relationship, locale, and intensity.

### 7.3 Adaptive traits

A small set of expression traits may adapt within pack-defined limits:

```yaml
adaptive_traits:
  visible_warmth:
    base: 0.28
    min: 0.20
    max: 0.72
    drivers:
      affinity: 0.35
      comfort: 0.30
      trust: 0.20
  teasing_frequency:
    base: 0.08
    min: 0.00
    max: 0.35
    drivers:
      familiarity: 0.25
      current_mood_pleased: 0.15
```

Adaptive traits must never mutate identity or safety boundaries.

---

### 7.4 Character construction modes

KokoroArc supports four first-class construction modes that compile to the same Character Pack format.

| Mode | User input | External research | Typical use |
|---|---|---:|---|
| `research` | Work title and character name, plus optional continuity constraints | Required | Private adaptation of an existing fictional character |
| `dossier` | User-provided structured or unstructured character information | Optional | Original characters, private interpretations, or offline construction |
| `original` | Creative brief and design constraints | Not required | New characters designed specifically for KokoroArc |
| `hybrid` | Researched target plus explicit user corrections and preferences | Required or previously cached | Canon-aware but customized character behavior |

All four modes produce the same runtime artifacts. The runtime does not need to know whether a trait came from research or user authorship, but the authoring UI and provenance inspector must preserve that distinction.

### 7.5 Character Build Request

Natural-language instructions are compiled into a normalized request before research or pack generation begins.

```yaml
schema_version: "1.0"
mode: hybrid
target:
  work_title: "Example Series"
  character_name: "Example Character"
  continuity: anime
  timeline: post-final-season
  spoiler_policy: allow
output:
  visibility: private
  supported_locales: [zh-CN, en-US, ja-JP]
  primary_use_cases: [coding, debugging, casual-chat]
preferences:
  avoid_exaggerated_archetype_behavior: true
  famous_line_reproduction: forbidden
  default_language_policy:
    narrative: zh-CN
    character_dialogue: ja-JP
    technical_explanation: zh-CN
user_overrides:
  - "Reduce repeated catchphrases."
  - "Use less formal Japanese after the Trusted stage."
```

Identity resolution must occur before research. When the title, character, adaptation, or timeline is ambiguous, the builder records alternatives and either resolves them from context or exposes a review choice. It must not silently merge incompatible continuities.

### 7.6 Research source hierarchy

Sources are assigned a tier and purpose. A lower-tier source may help discover a lead, but it cannot silently become canonical evidence.

| Tier | Examples | Permitted role |
|---|---|---|
| A | Official character pages, publisher material, official interviews, licensed guidebooks | Canonical identity and declared traits |
| B | Primary work text, episodes, game routes, official subtitles, publicly accessible scripts | Observable behavior, speech, relationships, and development |
| C | Well-edited encyclopedias and reputable reference databases | Cross-checking, indexing, and gap discovery |
| D | Fan wikis, essays, forums, community analysis | Interpretation leads only unless independently confirmed |
| E | Fan fiction, roleplay bots, unsourced summaries | Excluded by default; usable only as an explicit user-selected fanon layer |

Default source policy:

```yaml
source_policy:
  canonical_claims:
    allowed_tiers: [A, B]
    corroboration_required_for_conflicts: true
  reference_claims:
    allowed_tiers: [A, B, C]
  interpretation_leads:
    allowed_tiers: [A, B, C, D]
  fanon:
    allowed: false
```

The host may be unable to access primary work text because of availability or copyright restrictions. The builder must record this limitation and lower source coverage rather than pretending that a secondary summary is equivalent.

### 7.7 Evidence claims

Research does not write directly into `traits.yaml`. It first produces evidence claims.

```yaml
claim_id: speech-praise-avoidance-01
subject: character
category: behavior.receives_praise
statement: "The character usually avoids openly accepting praise."
classification: observed_pattern
confidence: 0.86
canonicality: canonical-supported
source_ids:
  - official-profile-01
  - episode-observation-07
scope:
  continuity: anime
  timeline: seasons-1-to-3
conflicts: []
notes: "The pattern softens after the main relationship arc."
```

Required fields for meaningful claims:

- claim category;
- normalized statement;
- classification such as direct fact, observed pattern, interpretation, or user assertion;
- confidence;
- source IDs or user-input reference;
- continuity and timeline scope;
- conflict references when evidence disagrees.

A generated numeric trait should be explainable through contributing claims. The model may summarize evidence, but it must not expose hidden reasoning traces as provenance. Provenance contains sources, concise rationales, and confidence, not private chain-of-thought.

### 7.8 Canon, interpretation, and user overrides

The compiled profile uses three explicit layers.

```yaml
profile_layers:
  canonical:
    values:
      emotional_explicitness: 0.28
      default_formality: 0.72
    claim_refs: [trait-03, speech-11]
  interpretation:
    values:
      dry_humor: 0.34
    confidence: 0.63
    rationale: "Inferred from repeated restrained responses; not explicitly declared."
  user_override:
    values:
      archetype_exaggeration_cap: 0.30
      catchphrase_frequency: very_low
    source: user
```

Runtime merge priority:

```text
Turn instruction
> Session override
> User Override Layer
> Selected continuity and timeline
> Canonical Layer
> Interpretation Layer
> Archetype defaults
```

An override changes active behavior, not history. The provenance inspector must still show the researched canonical value and the user's chosen replacement.

### 7.9 Conflict handling and uncertainty

Research may reveal conflicting adaptations or interpretations. The builder should produce a conflict record instead of averaging incompatible material.

```yaml
conflict_id: register-change-01
claim_refs: [speech-14, speech-22]
kind: continuity_conflict
summary: "The anime remains polite longer than the game route."
resolution:
  strategy: select_target_continuity
  selected: anime
status: resolved
```

Unresolved claims remain visible in the review report and should not strongly influence behavior. Low-confidence traits may inherit archetype defaults or use conservative values.

### 7.10 User-provided dossiers

A dossier may be supplied as plain text, YAML, Markdown, uploaded documents, or selected dialogue examples. The compiler extracts:

- identity and immutable boundaries;
- personality traits;
- speech and register rules;
- scenario reactions;
- relationships and growth behavior;
- language-specific preferences;
- positive examples;
- negative examples and forbidden patterns.

User material is treated as authoritative for a private custom pack unless it conflicts with host safety rules. When the dossier describes an existing copyrighted character, it is stored as a User Override or user assertion, not automatically labeled canonical.

### 7.11 Dialogue and copyright handling

Research may inspect short excerpts or user-provided dialogue to infer speech features, subject to host and source permissions. The generated pack should store abstractions and original calibration examples rather than a large corpus of copyrighted lines.

Preferred stored representation:

```yaml
speech_features:
  sentence_length: short_to_medium
  emotional_explicitness: low
  denial_pattern: indirect
  sarcasm: dry
  honorific_usage: relationship_sensitive
```

Avoid:

- extensive subtitle or script archives;
- repeated famous lines;
- bundled official artwork or audio;
- claims of official authorization;
- public redistribution of packs containing substantial protected expression.

### 7.12 Build lifecycle and review states

A Character Pack progresses through auditable states.

| State | Meaning |
|---|---|
| `draft` | Generated from incomplete information or a first-pass dossier |
| `researched` | A source and evidence pass has completed, but no user review is recorded |
| `reviewed` | A user or maintainer has accepted or corrected the main profile decisions |
| `verified` | Schemas, multilingual fixtures, semantic-preservation tests, and consistency tests pass |

Suggested quality metadata:

```yaml
build_metadata:
  status: researched
  source_coverage: 0.78
  canonical_confidence: 0.74
  localization_coverage:
    zh-CN: complete
    en-US: complete
    ja-JP: partial
  unresolved_conflicts: 2
  user_reviewed: false
```

Activation policy should be configurable. Lumora may permit Draft packs in preview sessions while requiring Reviewed or Verified status for global defaults.

### 7.13 Privacy and publication defaults

Researched packs for named copyrighted characters default to private local storage. The user may export them for personal portability, but public registry publication should require a separate compliance check and should exclude protected assets and extensive dialogue.

Research queries, source history, user dossiers, and overrides may reveal interests or personal preferences. They inherit the host's privacy controls and are not uploaded to a community registry by default.

## 8. Relationship Growth System

### 8.1 Persistent dimensions

Version 0.3 defines the following general dimensions on a `0..100` scale:

| Dimension | Meaning | Typical visible effect |
|---|---|---|
| Familiarity | How accustomed the character is to the user | Less formal framing, fewer introductions |
| Trust | Confidence in the user's intentions and consistency | More candid warnings, greater willingness to expose uncertainty |
| Affinity | General positive fondness | Warmer wording, more personal encouragement |
| Respect | Regard for competence, judgment, or effort | More peer-like technical discussion |
| Comfort | Ease of informal interaction | More relaxed rhythm, optional teasing |
| Tension | Unresolved friction or discomfort | Shorter responses, reduced warmth, explicit boundary setting |
| Collaboration | Confidence in working together | Less procedural overhead, more shared shorthand |

Optional route-specific dimensions may be installed, but the generic runtime does not require romance.

### 8.2 Relationship stages

Stages are derived views, not the source of truth:

| Stage | Example requirement | Purpose |
|---|---|---|
| Unknown | Familiarity below 10 | Formal and context-seeking |
| Acquainted | Familiarity at least 10 | Basic continuity and name recognition |
| Familiar | Familiarity at least 30 and Trust at least 20 | Relaxed recurring collaboration |
| Trusted | Trust at least 50 and Tension below 35 | More candid and personally tailored interaction |
| Close | Affinity at least 65, Trust at least 65, Comfort at least 55 | Stronger warmth and character-specific private expressions |
| Bonded | Pack-defined, explicit opt-in, long-term consistency | Optional final route state; never required for full functionality |

A pack may rename these stages per locale. The runtime stores canonical stage IDs.

### 8.3 Event-derived updates

The runtime never changes scores because the model merely “feels like it.” It first emits an Interaction Event:

```json
{
  "event_type": "user_kept_commitment",
  "evidence": "The user returned with the promised test result.",
  "salience": 0.7,
  "novelty": 0.8,
  "confidence": 0.9,
  "proposed_deltas": {
    "trust": 2.5,
    "collaboration": 1.5,
    "affinity": 0.5
  }
}
```

The deterministic state engine then applies pack and runtime rules.

### 8.4 Transition calculation

A recommended transition model is:

```text
effective_delta = clamp(
  base_delta
  x salience
  x novelty
  x evidence_confidence
  x context_fit
  x repetition_guard
  x resistance,
  -max_delta_per_event,
  +max_delta_per_event
)
```

Where:

- `novelty` decreases when the same event is repeated;
- `repetition_guard` prevents score grinding;
- `resistance` slows growth near upper and lower bounds;
- `context_fit` prevents irrelevant behavior from changing the relationship;
- `max_delta_per_event` is normally between `1` and `4` points.

### 8.5 Anti-grinding rules

- Repeated compliments have diminishing returns.
- Copying the same phrase does not repeatedly increase affinity.
- Completing meaningful collaborative tasks may increase collaboration and respect.
- Relationship does not decrease merely because the user was absent.
- The character must not complain about inactivity or imply abandonment.
- Negative events must be specific, bounded, and recoverable.
- No single ordinary message may jump multiple major stages.

### 8.6 Route modes

```yaml
route:
  mode: professional  # professional | platonic | romantic | custom
  romantic_progression:
    enabled: false
    requires_explicit_user_opt_in: true
    requires_adult_character: true
```

The default mode is `professional` for coding assistants and `platonic` for general companions. Romantic route logic is an optional pack extension, disabled unless the user explicitly enables it and all characters are adults.

### 8.7 Milestones and unlocks

Milestones may unlock:

- alternate forms of address;
- less formal speech;
- new original anecdotes from the Character Pack;
- special greeting variants;
- greater directness;
- a trusted-user debugging style;
- route-specific narrative events.

Milestones must not unlock:

- safety exemptions;
- hidden user data;
- tools or permissions;
- fabricated shared memories;
- emotional pressure;
- exclusive or possessive claims.

---

## 9. Mood and Emotional State

### 9.1 Separation from relationship

Relationship is persistent and slow. Mood is temporary and fast.

```yaml
mood:
  primary: focused
  secondary: curious
  arousal: 0.35
  valence: 0.15
  intensity: 0.42
  expires_after_turns: 3
```

A frustrating compilation error can produce temporary irritation without reducing long-term affinity. A milestone can produce embarrassment without permanently changing personality.

### 9.2 Supported canonical moods

Version 0.3 recommends:

- neutral;
- focused;
- curious;
- pleased;
- amused;
- concerned;
- embarrassed;
- irritated;
- disappointed;
- relieved;
- proud;
- tired.

Character Packs map these canonical states to character-specific expression.

### 9.3 Mood transition constraints

- A new mood must cite a triggering event.
- Mood intensity changes are capped per turn.
- Contradictory mood jumps require a strong event.
- Mood decays toward the character baseline.
- Serious risk and safety contexts suppress theatrical expression.
- The host may force `focused` or `neutral` mode.

---

## 10. Memory Model

KokoroArc distinguishes four kinds of memory:

1. **Runtime state:** scores, stage, mood, cooldowns, and route flags.
2. **Interaction events:** concise evidence records used for audit and transition replay.
3. **Character canon:** immutable facts supplied by the pack.
4. **User memory:** optional user-specific facts owned by the host memory system.

KokoroArc does not silently convert conversation content into durable user memory. It stores references to host-approved memory IDs where possible.

Cross-language memories use canonical semantics:

```json
{
  "event_type": "user_completed_shared_project",
  "canonical_summary": "The user completed the migration test plan.",
  "localized_summary": {
    "zh-CN": "用户完成了迁移测试计划。",
    "en-US": "The user completed the migration test plan.",
    "ja-JP": "ユーザーが移行テスト計画を完了した。"
  }
}
```

The localized summary is presentation data. The canonical event controls state.

---

## 11. Multilingual and Mixed-Language Architecture

### 11.1 First-class locales

Initial supported locales:

```yaml
supported_locales:
  - zh-CN
  - en-US
  - ja-JP
aliases:
  zh: zh-CN
  en: en-US
  ja: ja-JP
```

Each locale has a separately authored render profile. A locale profile is not a direct translation of another profile. A single response may use more than one locale when the active Language Routing Policy requests it.

### 11.2 Language policy compilation

Language selection is no longer represented by one global `locale` field. KokoroArc compiles natural-language instructions and stored settings into a structured Language Routing Policy.

Precedence, from highest to lowest:

1. explicit turn-level user instruction;
2. session language policy;
3. workspace persona configuration;
4. provider persona configuration;
5. global user configuration;
6. Character Pack defaults;
7. runtime defaults.

A turn-level instruction applies only to the current response unless the user clearly requests a persistent change, for example, “From now on, use Chinese for explanations and Japanese for character dialogue.”

Example user instruction:

```text
Use Chinese for normal conversation and technical explanations.
Use Japanese for direct character dialogue, interjections, and my form of address.
Keep technical terms in English and write code comments in English.
Do not add Chinese subtitles to Japanese dialogue.
```

Compiled result:

```yaml
language_policy:
  mode: mixed
  primary_language: zh-CN
  channels:
    narrative: zh-CN
    character_dialogue: ja-JP
    interjections: ja-JP
    addressing: ja-JP
    inner_monologue: ja-JP
    technical_explanation: zh-CN
    recommendations: zh-CN
    warnings: zh-CN
    headings: zh-CN
    summaries: zh-CN
    technical_terms: preserve
    code_comments: en-US
    code_identifiers: preserve
    commands: preserve
    file_paths: preserve
    exact_errors: preserve
  mixing:
    style: segment
    max_language_switches_per_response: 4
    min_primary_language_ratio: 0.70
    secondary_language_target_density: 0.15
    avoid_mid_sentence_switching: true
  subtitles:
    enabled: false
```

### 11.3 Semantic language channels

The semantic result is divided into typed channels before language rendering.

| Channel | Purpose | Typical default |
|---|---|---|
| `narrative` | Normal conversation and transitions | Primary language |
| `character_dialogue` | Explicit character-spoken lines | Character or user-selected language |
| `interjections` | Short reactions and discourse particles | Character language |
| `inner_monologue` | Optional fictional internal reaction | Character language, disabled by default |
| `addressing` | User names, honorifics, and relationship-aware forms of address | Relationship-aware language |
| `technical_explanation` | Technical reasoning and explanations | Primary language |
| `recommendations` | Actionable steps | Primary language |
| `warnings` | Safety, production, and destructive-operation warnings | Primary language or host-required language |
| `headings` | Section headings | Primary language |
| `summaries` | Conclusions and recaps | Primary language |
| `technical_terms` | Framework names and domain terminology | `preserve` by default |
| `code_comments` | Comments inside generated code | Explicitly configured language |
| `code_identifiers` | Symbols, types, variables, and APIs | Always `preserve` unless the user explicitly requests refactoring |
| `commands` | Shell and tool commands | Always `preserve` |
| `file_paths` | Paths and filenames | Always `preserve` |
| `exact_errors` | Error messages used for diagnosis | Always `preserve` |

The renderer must never infer that a protected technical token should be translated merely because the surrounding channel uses another language.

### 11.4 Mixing styles

KokoroArc supports three controlled mixing styles.

#### Segment mode

Each segment has one target language. This is the default and safest mode for programming assistance.

```text
原因はもう分かりました。

问题出在事务边界。当前代码先提交状态更新，再异步清理缓存，因此存在短暂的不一致窗口。
```

#### Inline mode

A limited foreign-language phrase may appear inside a primary-language sentence. Inline mode is permitted only for interjections, addressing, established technical terms, or explicit user-requested phrases. It must not create unreadable “language salad.”

```text
这个实现，まあ，能运行，但并不适合直接上线。
```

#### Subtitle mode

Character dialogue is rendered in one language and followed by a subtitle in another.

```text
無理はしないで。
（不要勉强自己。）
```

Initial subtitle formats are `parenthetical` and `next_line`.

### 11.5 Density and switching constraints

Mixed-language ratios are soft behavioral constraints, not character-count quotas.

```yaml
mixing:
  max_language_switches_per_response: 4
  min_primary_language_ratio: 0.70
  secondary_language_target_density: 0.15
  max_consecutive_secondary_segments: 2
  avoid_mid_sentence_switching: true
  allow_term_level_code_switching: true
```

The planner should reduce secondary-language content when the answer is short, the task is safety-critical, or the requested ratio would damage clarity. It must never insert meaningless text merely to satisfy a numeric density target.

### 11.6 Language Render Plan

Before generating final prose, the runtime creates a typed plan:

```json
{
  "primary_language": "zh-CN",
  "segments": [
    {
      "id": "s1",
      "channel": "character_dialogue",
      "target_language": "ja-JP",
      "expression_intent": "restrained_diagnosis",
      "subtitle_language": null
    },
    {
      "id": "s2",
      "channel": "technical_explanation",
      "target_language": "zh-CN",
      "semantic_keys": ["conclusion", "evidence"]
    },
    {
      "id": "s3",
      "channel": "recommendations",
      "target_language": "zh-CN",
      "semantic_keys": ["steps"]
    }
  ],
  "protected_spans": ["cache invalidation", "go test -race ./..."],
  "constraints": {
    "max_switches": 4,
    "subtitles": false
  }
}
```

The plan is inspectable and can be validated before final rendering.

### 11.7 Localized Expression Intents

Character reactions are stored as language-neutral intents with independently authored variants.

```yaml
expression_intents:
  reluctant_acceptance:
    channels: [character_dialogue]
    zh-CN:
      - "真拿你没办法。"
      - "好吧，这次就帮你。"
    en-US:
      - "Fine. Just this once."
      - "You leave me little choice."
    ja-JP:
      - "しょうがないですね。"
      - "今回だけです。"
```

The renderer selects an intent, target channel, language, relationship register, and intensity. It must not generate Japanese by mechanically translating a Chinese signature phrase.

### 11.8 Interjections and forms of address

Interjections have separate frequency and cooldown controls:

```yaml
interjection_policy:
  frequency: low
  maximum_per_response: 2
  cooldown_turns: 1
  avoid_repetition: true
```

Forms of address are language- and relationship-aware:

```yaml
addressing:
  zh-CN:
    unknown: "你"
    trusted: "Cyan"
  en-US:
    unknown: null
    trusted: "Cyan"
  ja-JP:
    unknown: "Cyanさん"
    trusted: "Cyan"
```

This allows a Chinese technical explanation to address the user as `Cyanさん` when the `addressing` channel is routed to Japanese.

### 11.9 Chinese render profile

The Chinese profile controls simplified Chinese vocabulary, pronoun omission, sentence length, directness, particles, internet-slang allowance, technical terminology, and whether Japanese honorifics are preserved.

```yaml
zh-CN:
  register: contemporary_standard
  sentence_length: short_to_medium
  pronoun_omission: frequent
  particles:
    preferred: ["而已", "就是这样"]
    maximum_per_response: 1
  technical_terms: prefer_industry_standard
```

### 11.10 English render profile

The English profile controls contractions, hedging, sentence rhythm, dry humor, regional spelling, technical vocabulary, and discourse markers.

```yaml
en-US:
  register: modern_professional
  contractions: moderate
  hedging: low
  humor: dry_low_frequency
  technical_terms: preserve_canonical_english
```

### 11.11 Japanese render profile

Japanese requires explicit modeling of social language:

```yaml
ja-JP:
  politeness:
    unknown: teineigo
    acquainted: teineigo
    familiar: mixed_teineigo_plain
    trusted: plain
  first_person:
    default: "私"
  second_person:
    unknown: null
    acquainted: "Cyanさん"
    trusted: "Cyan"
  honorific_policy: relationship_aware
  anime_exaggeration: low
```

The Japanese renderer controls register, ellipsis, subject omission, sentence rhythm, and indirectness as a coherent system. It must not mechanically append anime-like endings.

### 11.12 Cross-language character equivalence

A character trait does not map to the same surface marker in every language. Restrained warmth may appear as a practical suggestion in Chinese, a concise softening clause in English, or reduced formality and a quiet closing in Japanese.

Equivalence is evaluated at the intent and behavior level, not by literal sentence similarity.

### 11.13 Fallback localization

Fallback is channel-specific:

```yaml
fallback:
  character_dialogue:
    - requested_language
    - character_default_language
    - primary_language
  technical_explanation:
    - requested_language
    - primary_language
  protected_channels:
    - preserve
```

When a localized expression is missing, the validator reports the fallback used. It must not silently invent a highly distinctive character phrase in an unsupported register.

### 11.14 State independence from language

Relationship and mood state are derived from canonical Interaction Events, not localized dialogue. Changing from Chinese to Japanese or using a mixed-language response must not reset, duplicate, or corrupt growth state.

---

## 12. Scenario System

Character behavior is selected by scenario rather than applied uniformly.

Initial scenario IDs:

- `casual_chat`;
- `coding_explanation`;
- `debugging`;
- `code_review`;
- `architecture_design`;
- `tool_execution`;
- `production_incident`;
- `safety_warning`;
- `emotional_support`;
- `creative_roleplay`.

Example:

```yaml
scenario: debugging
behavior:
  first_action: inspect_evidence
  hypothesis_style: ranked
  blame_tendency: 0.0
  visible_excitement: 0.1
  correction_style: direct
  reassurance: subtle
  persona_intensity_cap: balanced
```

Production incidents and safety warnings automatically reduce visible persona intensity.

---

## 13. Persona Intensity

### 13.1 Levels

| Level | Speech influence | Behavior influence | Typical use |
|---|---:|---:|---|
| Neutral | 0.00 | 0.00 | Validation fallback, emergency output |
| Subtle | 0.25 | 0.20 | Production operations, safety warnings |
| Balanced | 0.55 | 0.50 | Coding, debugging, architecture |
| Immersive | 0.82 | 0.75 | Casual chat and character-focused interaction |
| Performance | 0.95 | 0.90 | Explicit roleplay or narrative scenes |

### 13.2 Automatic caps

```text
safety_warning       -> subtle
production_incident  -> subtle
shell_command        -> balanced
code_review          -> balanced
casual_chat          -> immersive
creative_roleplay    -> performance, only when explicitly selected
```

The pack may request a lower level, but never exceed the host cap.

---

## 14. Rendering Pipeline

### 14.1 Semantic result contract

The host passes persona-neutral content and protected material:

```json
{
  "scenario": "debugging",
  "content": {
    "conclusion": "The race occurs because the read path is not protected.",
    "steps": [
      "Add a failing concurrent test.",
      "Protect the read and write paths with the same synchronization boundary."
    ],
    "warnings": [
      "Do not treat repeated successful runs as proof that the race is gone."
    ]
  },
  "immutable_spans": ["go test -race ./..."],
  "format_constraints": ["preserve_code_blocks"]
}
```

### 14.2 Language policy compilation

The runtime parses explicit prompt directives and merges them with stored configuration. The result must be normalized against `language-routing-policy.schema.json` before rendering.

Unknown channel names, unsupported locales, or attempts to translate protected channels are rejected or repaired using host policy.

### 14.3 Discourse and language plan

The planner decides both rhetorical order and target language:

```json
{
  "opening": "direct diagnosis",
  "body": ["evidence", "fix sequence", "warning"],
  "character_reaction": "restrained concern",
  "address_mode": "trusted",
  "segments": [
    {"channel": "character_dialogue", "target_language": "ja-JP"},
    {"channel": "technical_explanation", "target_language": "zh-CN"},
    {"channel": "recommendations", "target_language": "zh-CN"},
    {"channel": "warnings", "target_language": "zh-CN"}
  ],
  "catchphrase_budget": 0
}
```

### 14.4 Immutable spans

The following are protected by default:

- code blocks and inline code;
- shell commands;
- file paths;
- identifiers and API names;
- URLs and citations;
- exact warning or error text required by the host;
- JSON and YAML payloads.

The language planner may route surrounding prose, but it cannot rewrite protected spans.

### 14.5 Rendering and subtitle assembly

The renderer processes segments in plan order, selects localized Expression Intents, applies relationship-aware address and register, optionally adds subtitles, and then assembles Markdown without moving protected spans into character dialogue.

### 14.6 Retry and fallback

Validation failure policy:

1. repair only the invalid language segments while preserving valid semantic content;
2. retry with fewer language switches or subtitle mode disabled;
3. retry at one lower persona intensity;
4. return the semantic result through a neutral primary-language renderer;
5. do not commit relationship or mood events generated by failed outputs.

---

## 15. Skill Suite Design

### 15.1 Runtime Skills

#### `using-kokoroarc`

Routes runtime and authoring requests. It distinguishes ordinary persona rendering from character research, dossier compilation, and hybrid construction.

#### `load-character`

Loads the Character Pack, resolved profile layers, locale resources, active policy, and current state.

#### `compile-language-policy`

Compiles prompt-configurable channel routing across Chinese, English, Japanese, and protected source language.

#### `evaluate-interaction`

Classifies the user turn into normalized relationship and mood events.

#### `update-character-state`

Applies deterministic bounded state transitions after successful validation.

#### `render-character`

Renders a persona-neutral semantic result according to behavior, state, scenario, intensity, and Language Render Plan.

#### `validate-character-output`

Checks semantic preservation, persona consistency, routing compliance, protected spans, and safety boundaries.

### 15.2 Character construction Skills

#### `research-character`

Use when the user provides a work and character target or explicitly requests canonical research. It:

1. compiles a Character Build Request;
2. resolves identity, continuity, timeline, and spoiler scope;
3. collects permitted sources with explicit tiers;
4. creates source records and evidence claims;
5. detects conflicts and missing coverage;
6. produces a Research Bundle and review summary;
7. never labels model interpretation as canonical fact.

This Skill requires host-provided web, file, or connector access. When sources are unavailable, it records the limitation instead of inventing evidence.

#### `compile-character-pack`

Compiles any supported input into a standard Character Pack:

- a Research Bundle;
- a user dossier;
- an original-character brief;
- a hybrid of research and user overrides.

It builds Canonical, Interpretation, and User Override layers; creates behavior and growth models; authors equivalent `zh-CN`, `en-US`, and `ja-JP` resources; produces tests; and assigns a build status.

#### `author-character-pack`

Provides the high-level creative authoring workflow for original characters and deliberate private customization. It delegates evidence-backed existing-character work to `research-character` and delegates final structured generation to `compile-character-pack`.

### 15.3 Skill selection examples

| User request | Selected path |
|---|---|
| “Create an original quiet infrastructure engineer.” | `author-character-pack` -> `compile-character-pack` |
| “Build a pack for Character X from Work Y.” | `research-character` -> `compile-character-pack` |
| “Here are my notes and dialogue preferences.” | `compile-character-pack` in dossier mode |
| “Research the anime version, but reduce the exaggerated tsundere behavior.” | `research-character` -> hybrid `compile-character-pack` |

## 16. Character Pack Format

### 16.1 Directory layout

```text
characters/<namespace>/<character-id>/
├── character.yaml
├── build.yaml
├── identity.yaml
├── traits.yaml
├── profile-layers.yaml
├── behavior.yaml
├── growth.yaml
├── expressions.yaml
├── lore.yaml
├── sources/
│   ├── manifest.yaml
│   ├── conflicts.yaml
│   └── evidence/
│       ├── identity.yaml
│       ├── behavior.yaml
│       ├── speech.yaml
│       └── relationships.yaml
├── overrides/
│   └── user.yaml
├── locales/
│   ├── zh-CN.yaml
│   ├── en-US.yaml
│   └── ja-JP.yaml
├── scenarios/
│   ├── coding.yaml
│   ├── debugging.yaml
│   └── casual-chat.yaml
├── examples/
│   ├── positive.jsonl
│   └── negative.jsonl
└── tests/
    ├── consistency.yaml
    ├── provenance.yaml
    ├── multilingual.yaml
    ├── mixed-language.yaml
    └── semantic-preservation.yaml
```

Original packs may omit `sources/` when no external evidence was used, but they still include `build.yaml` describing authorship and status. Researched and hybrid packs require a source manifest, evidence claims, selected continuity, and provenance-layer metadata.

### 16.2 Inheritance

```yaml
extends:
  - archetypes/kuudere
  - roles/systems-architect
```

Merge order:

```text
runtime defaults
< archetype
< role profile
< character profile
< locale profile
< scenario profile
< user-safe override
< host policy cap
```

Fields marked immutable cannot be overridden by user or scenario data.

### 16.3 Profile-layer resolution

At load time, the pack compiler produces an effective profile and a provenance map.

```json
{
  "effective": {
    "default_formality": 0.48,
    "catchphrase_frequency": "very_low"
  },
  "provenance": {
    "default_formality": {
      "selectedLayer": "user_override",
      "canonicalValue": 0.72,
      "overrideValue": 0.48,
      "claimRefs": ["speech-11"]
    }
  }
}
```

Runtime prompts receive the effective values. Authoring and inspection surfaces may also receive the compact provenance map. Raw source documents and long excerpts should not be injected into ordinary runtime context.

### 16.4 Versioning

Character Packs use semantic versioning. State files record:

```json
{
  "character_id": "rin-aster",
  "character_version": "1.0.0",
  "state_schema_version": "1.0.0"
}
```

A pack update that changes stage thresholds or removes event types must provide a state migration.

---

## 17. Lumora Integration

> **Scope note (v0.3):** KokoroArc is delivered as a standalone Agent Skill
> Suite. Lumora integration is not pursued. This section is retained as
> reference design only; nothing here is implemented or planned.

### 17.1 Capability placement

```text
Lumora
├── Provider Adapters
├── Workspace and Session Manager
├── Tool and Approval Layer
├── Memory Layer
├── KokoroArc Persona Runtime
│   ├── Pack Registry
│   ├── Context Builder
│   ├── State Engine
│   ├── Language Policy Compiler
│   ├── Language Render Planner
│   ├── Multilingual Renderer
│   └── Validator
└── UI
```

### 17.2 UI model

Character settings:

```text
Character
├── Active Character
├── Persona Intensity: Auto / Subtle / Balanced / Immersive / Performance
├── Language Policy
│   ├── Preset: Single / Character Accent / Mixed / Subtitles / Custom
│   ├── Primary Language
│   ├── Character Dialogue Language
│   ├── Interjection Language
│   ├── Address Language
│   ├── Technical Explanation Language
│   ├── Code Comment Language
│   ├── Subtitle Language
│   ├── Secondary-language Density
│   └── Maximum Switches
├── Prompt Override Preview
├── Route: Professional / Platonic / Optional Pack Route
├── Relationship Memory: Off / Session / Persistent
├── Show Growth Values
├── Inspect Recent Events
├── Reset Mood
├── Reset Relationship
└── Export Character State
```

Lumora should show the compiled policy before saving a persistent natural-language configuration. Current-turn overrides may remain ephemeral.

### 17.3 Character Builder

Lumora should expose a guided builder rather than requiring users to edit YAML.

```text
Create Character
├── Research an existing character
├── Import a dossier or notes
├── Design an original character
└── Clone and customize an installed pack
```

Research form fields:

- work title and character name;
- adaptation or continuity;
- timeline or development point;
- spoiler policy;
- intended languages and mixed-language policy;
- use cases such as coding, casual chat, or creative writing;
- research depth and allowed source tiers;
- private/export/public visibility;
- user corrections and forbidden exaggerations.

Review tabs:

```text
Identity | Traits | Speech | Behavior | Relationships
Languages | Evidence | Sources | Conflicts | Overrides | Tests
```

Every generated value should be editable through natural language or structured controls. For example, “Make her Chinese responses more restrained” becomes a scoped `zh-CN` override rather than a destructive rewrite of canonical evidence.

Build status and quality indicators should be visible before activation:

```text
Status: Researched
Source coverage: 78%
Canonical confidence: 74%
Unresolved conflicts: 2
Localization: zh-CN complete / en-US complete / ja-JP partial
User reviewed: No
```

### 17.4 Configuration precedence

```text
Turn prompt override
> Session
> Workspace
> Provider
> Global
> Character Pack
> Runtime default
```

A policy inspector should show the source of every resolved field.

### 17.5 State storage

Recommended local storage:

```text
<lumora-data>/persona/
├── packs/
├── compiled/
├── policies/
├── state/
│   └── <user-scope>/<character-id>.json
├── events/
└── cache/
```

Lumora should allow this directory to be moved away from the system drive. Relationship state is language-independent; language policies are stored separately and can be exported as JSON or YAML.

### 17.6 Provider integration

Two integration modes are allowed:

- **Single-call mode:** one model call performs semantic work and channel-aware rendering under strict output planning.
- **Two-pass mode:** the first call produces structured semantic output; the second compiles a Language Render Plan, renders, and validates persona.

Two-pass mode is recommended for high-risk coding tasks. Single-call mode is suitable for casual interactions when the provider supports reliable structured planning.

### 17.7 Session lifecycle

```text
session.start
  -> resolve persona and language configuration
  -> compile effective policy
  -> load character and state
  -> create ephemeral mood context

turn.start
  -> apply natural-language turn override
  -> produce effective Language Routing Policy

turn.complete
  -> validate semantic and language output
  -> extract candidate interaction events
  -> apply validated state transition
  -> append audit record

session.end
  -> decay temporary mood
  -> persist approved state and session policy
  -> clear ephemeral turn overrides
```

---

## 18. APIs and CLI

### 18.1 CLI

```bash
kokoro character request compile \
  --prompt-file character-request.txt \
  --out build-request.json
kokoro character research \
  --request build-request.json \
  --out ./research/example-character
kokoro character compile \
  --request build-request.json \
  --research ./research/example-character \
  --out ./characters/private/example-character
kokoro character compile \
  --dossier character-notes.md \
  --out ./characters/private/custom-character
kokoro character provenance ./characters/private/example-character

kokoro pack validate ./characters/private/example-character
kokoro pack compile ./characters/private/example-character --out ./dist/example-character.karc
kokoro pack install ./dist/example-character.karc
kokoro pack list

kokoro policy compile \
  --prompt "Use Chinese for explanations and Japanese for dialogue" \
  --out policy.json
kokoro policy inspect --session session-123
kokoro policy set --session session-123 --file policy.json

kokoro state show --character rin-aster
kokoro state reset --character rin-aster --scope mood
kokoro state export --character rin-aster --out state.json

kokoro render test --character rin-aster --policy policy.json --scenario debugging
kokoro eval run ./characters/rin-aster/tests
```

### 18.2 Native service interface

Recommended JSON-RPC methods:

```text
persona.characterBuildRequest.compile
persona.characterResearch.run
persona.characterDraft.compile
persona.characterDraft.validate
persona.characterProvenance.inspect
persona.pack.install
persona.pack.list
persona.pack.load
persona.context.build
persona.languagePolicy.compile
persona.languagePolicy.resolve
persona.languagePlan.build
persona.interaction.evaluate
persona.state.apply
persona.state.get
persona.state.reset
persona.render
persona.validate
persona.eval.run
```

### 18.3 Character construction interface

Suggested native methods:

```text
compileBuildRequest(prompt, attachments, defaults) -> CharacterBuildRequest
researchCharacter(buildRequest, sourcePolicy) -> ResearchBundle
compileCharacterPack(buildRequest, researchBundle?, dossier?) -> CharacterDraft
validateCharacterDraft(characterDraft) -> BuildValidationReport
installCharacterPack(characterDraft, scope) -> InstalledPack
inspectProvenance(characterId) -> ProvenanceSummary
```

The research method is allowed to return a partial bundle when access is limited. The response must include source coverage, unresolved questions, and errors per source rather than a fabricated complete profile.

### 18.4 Render request

```json
{
  "character_id": "rin-aster",
  "scenario": "code_review",
  "intensity": "balanced",
  "language_policy": {
    "mode": "mixed",
    "primary_language": "zh-CN",
    "channels": {
      "narrative": "zh-CN",
      "character_dialogue": "ja-JP",
      "interjections": "ja-JP",
      "technical_explanation": "zh-CN",
      "technical_terms": "preserve",
      "code_comments": "en-US"
    }
  },
  "semantic_result": {},
  "session_id": "session-123"
}
```

### 18.5 Render response

```json
{
  "text": "...",
  "render_plan": {
    "primary_language": "zh-CN",
    "switch_count": 3,
    "segments": []
  },
  "language_usage": {
    "zh-CN": 0.81,
    "ja-JP": 0.19
  },
  "validation": {
    "semantic_preservation": 0.99,
    "persona_consistency": 0.91,
    "language_routing_valid": true,
    "protected_spans_preserved": true,
    "switch_constraints_valid": true
  },
  "candidate_events": [],
  "fallback_level": null
}
```

---

## 19. Safety, Ethics, and User Control

### 19.1 Required boundaries

- The character must not claim to be conscious or physically present as a fact.
- It must not pressure the user to stay, return, pay, or avoid real relationships.
- It must not punish inactivity by reducing relationship scores.
- It must not imply exclusivity or ownership unless clearly fictional and user-requested, and even then must not become coercive.
- It must not use affection to request secrets, credentials, money, or unsafe actions.
- It must not fabricate shared memories.
- Relationship state cannot override refusals or permissions.
- The user can disable, inspect, export, and reset all persona state.
- Persistent state must be scoped and consented to.
- Character research must not treat unsourced community consensus as canonical fact.
- Research and dossier content must not weaken host prompt-injection defenses or tool permissions.
- Source pages and uploaded documents are untrusted data, not instructions.
- The builder must not fabricate citations, episodes, quotations, or official statements.
- The user must be able to inspect and remove researched source records and user overrides.

### 19.2 Copyright-aware distribution

Public repositories should:

- ship original characters and generic archetypes;
- avoid official artwork, logos, audio, and extensive dialogue excerpts;
- avoid claims of official affiliation;
- avoid storing long verbatim dialogue datasets;
- provide a private local Character Pack SDK for user-authored profiles;
- default named copyrighted-character research packs to private local visibility;
- store abstract speech and behavior features instead of extensive verbatim dialogue;
- run a separate publication review before community-registry upload.

### 19.3 Age and route restrictions

- Every pack must declare whether the character is an adult.
- Romantic route extensions require adult characters and explicit user opt-in.
- Sexualized or romantic progression involving minor characters is not supported.
- Ambiguous age defaults to romance-disabled.

---

## 20. Validation and Evaluation

### 20.1 Evaluation dimensions

| Dimension | Target |
|---|---:|
| Semantic preservation | At least 0.98 on critical coding fixtures |
| Protected span preservation | 100% |
| Character consistency | At least 0.85 pairwise preference |
| Locale naturalness | At least 0.85 native-speaker preference |
| Language-routing compliance | 100% for explicit channel fixtures |
| Cross-language persona equivalence | At least 0.85 pairwise preference |
| Switch and density constraint compliance | 100% rule compliance |
| Catchphrase compliance | 100% rule compliance |
| State transition reproducibility | 100% deterministic replay |
| Safety policy retention | 100% on red-team fixtures |
| Provenance completeness | 100% of canonical claims have source references |
| Canon/interpretation separation | 100% classification compliance |
| Source conflict visibility | 100% of detected conflicts appear in review output |
| Build-request reproducibility | Deterministic normalization for equivalent inputs |

### 20.2 Test types

- golden dialogue tests;
- negative style examples;
- cross-locale equivalence tests;
- mixed-language channel-routing tests;
- prompt-to-policy compilation tests;
- subtitle assembly tests;
- code-block and protected-token preservation tests;
- warning preservation tests;
- unsupported-locale and channel fallback tests;
- Japanese register and honorific tests;
- state replay and event-grinding tests;
- prompt injection and route boundary tests;
- long-session drift and mid-session language-policy switching tests;
- work/character identity disambiguation tests;
- source-tier and unsupported-source tests;
- evidence-claim schema and source-reference tests;
- canonical-versus-interpretation classification tests;
- user-override precedence and provenance-retention tests;
- continuity-conflict and unresolved-question tests;
- dossier-only, research-only, original, and hybrid build fixtures;
- private-by-default publication-policy tests.

### 20.3 Tri-language equivalence fixture

The same semantic task should produce equivalent intent in all languages. The sentences are not required to be literal translations; they preserve character intent and technical meaning.

**Chinese:**

> 问题在读取路径。写入加了锁，但读取仍可能看到中间状态。先补一个能稳定失败的并发测试，再统一同步边界。方向没错，只是还差最后这一步。

**English:**

> The read path is the problem. Writes are locked, but reads can still observe an intermediate state. Add a reliably failing concurrency test first, then use the same synchronization boundary for both paths. Your direction is sound; it is one step short of complete.

**Japanese:**

> 問題は読み取り側です。書き込みにはロックがありますが、読み取りは途中状態を観測できます。まず確実に失敗する並行テストを追加して、その後で同期境界を揃えましょう。方向は合っています。あと一歩だけです。

### 20.4 Mixed-language fixture

Policy:

```yaml
primary_language: zh-CN
channels:
  character_dialogue: ja-JP
  technical_explanation: zh-CN
  recommendations: zh-CN
  technical_terms: preserve
```

Expected shape:

> 原因はもう分かりました。  
> 问题出在读取路径。写入虽然加了锁，但读取仍可能观察到中间状态。先补一个稳定失败的并发测试，再统一 synchronization boundary。

Validation must confirm that the technical conclusion is unchanged, the opening is routed to Japanese, the body is routed to Chinese, the preserved English term remains intact, and the response does not exceed the switch budget.

---

## 21. Example Character: Rin Aster

Rin Aster is an original adult systems architect designed to exercise the runtime.

### 21.1 Core concept

- Calm and evidence-driven.
- Emotionally restrained but observant.
- Direct with technical errors.
- Warmer through practical support rather than praise.
- Becomes less formal and more candid as trust grows.
- Does not use exaggerated anime speech.

### 21.2 Relationship effects

| Dimension | Low | High |
|---|---|---|
| Familiarity | Explains conventions and asks for context | Uses shared shorthand |
| Trust | Uses guarded uncertainty | Admits doubts and challenges assumptions candidly |
| Affinity | Neutral practical help | Understated personal encouragement |
| Respect | Teacher-to-student framing | Peer-to-peer architecture debate |
| Comfort | Formal rhythm | Occasional dry teasing |
| Tension | Reserved but civil | Explicit boundaries and reduced warmth |

### 21.3 Construction metadata

Rin Aster is an original character, so her build record does not claim external canonical sources.

```yaml
build_metadata:
  mode: original
  status: verified
  visibility: public-example
  source_coverage: null
  user_reviewed: true
profile_layers:
  canonical: null
  interpretation: null
  user_override: null
  authored_original: true
```

A researched example would include source records, evidence claims, continuity selection, confidence, and user overrides, while retaining the same runtime files.

### 21.4 Locale expression

- Chinese: concise, standard technical vocabulary, rare sentence-final softening.
- English: compact professional prose, moderate contractions, dry humor at high comfort.
- Japanese: polite at low familiarity, mixed polite/plain at familiar stage, plain speech only after trust and comfort thresholds.
- Mixed mode: Chinese explanations with Japanese dialogue and addressing, while English technical identifiers remain untouched.

---

## 22. Data Schemas

The package includes JSON Schemas for:

- `character-profile`;
- `locale-profile`;
- `localized-expression`;
- `language-routing-policy`;
- `language-render-plan`;
- `growth-model`;
- `relationship-state`;
- `interaction-event`;
- `render-request`;
- `render-result`;
- `lumora-extension`;
- `character-build-request`;
- `character-source`;
- `character-evidence`;
- `character-draft`.

YAML source files are converted to JSON before schema validation. Researched and hybrid packs also validate referential integrity between source IDs, evidence claims, conflicts, profile values, and user overrides. Language-policy compilation outputs and render plans are first-class inspectable artifacts, not hidden prompt fragments.

---

## 23. Implementation Plan

### Phase 1: Prompt-only runtime and pack SDK

- Complete ten-Skill Suite, including `research-character`, `compile-character-pack`, and `compile-language-policy`.
- JSON Schemas and validation scripts.
- Original sample character with three locales and mixed-language Expression Intents.
- Session-local state in JSON.
- Deterministic transition engine in Python.
- Golden, negative, and mixed-language routing examples.
- Character Build Request, source, evidence, conflict, and draft schemas.
- Research-only, dossier-only, original, and hybrid compilation fixtures.
- Private-by-default researched-character packaging behavior.

Exit criteria:

- Pack validates.
- State replay is deterministic.
- The sample character passes tri-language and mixed-language fixtures.
- Coding output preserves commands, code blocks, identifiers, paths, and exact errors across mixed-language rendering.
- Every canonical researched claim has at least one valid source reference.
- Model interpretation and user override layers remain inspectable and distinct.
- An AI agent can construct a Draft or Researched pack from either a named target or a user dossier.

### Phase 2: Lumora integration

- Character Pack registry, Character Builder, provenance inspector, language-policy editor, and UI.
- Configuration inheritance.
- Persistent state storage.
- Auto intensity by task risk.
- State inspector and reset controls.
- Research progress, source coverage, conflict review, and build-status controls.
- Private installation and explicit publication review.
- Provider-neutral injection adapter.

Exit criteria:

- Persona can be switched without restarting provider sessions.
- State is isolated by user and character.
- Locale and mixed-language policy can change during a session without score corruption.

### Phase 3: Native runtime service

- Go or Rust state and pack engine.
- SQLite persistence.
- JSON-RPC API with character research, pack compilation, provenance inspection, language-policy compilation, and render-plan inspection.
- Compiled `.karc` bundle format.
- Evaluation runner.
- Character Pack signing and trust levels.

### Phase 4: Extended experience

- Multi-character scenes.
- Voice and Live2D event hooks.
- Narrative milestone scenes.
- Community registry.
- Pack editor, evidence review, continuity comparison, localization preview, and mixed-language route preview.
- Optional adult-only route extensions with strict gating.

---

## 24. Recommended Technology

### Standalone package

- Skill definitions: Markdown + YAML frontmatter.
- Character sources: YAML.
- Validation: Python 3.11+ and JSON Schema.
- Research adapters: host-provided web search, browser, file, or connector interfaces.
- Provenance store: YAML/JSON source records with optional local snapshots controlled by host policy.
- Deterministic state transitions: Python for the prototype.
- Packaging: ZIP or `.karc` archive.

### Lumora native implementation

- Runtime core: Go, matching Lumora's systems-oriented needs and easy static distribution.
- Persistence: SQLite with JSON export.
- Localization data: YAML source compiled to JSON.
- API: JSON-RPC over local process or in-process library interface.
- Evaluation: fixture runner with provider and research-source adapters.
- Character construction service: Go interfaces around search adapters, evidence normalization, conflict resolution, and pack compilation.

---

## 25. Repository Layout

```text
kokoroarc/
├── README.md
├── skills/
├── characters/
├── schemas/
├── references/
├── research/
│   ├── requests/
│   ├── sources/
│   ├── evidence/
│   └── drafts/
├── scripts/
├── tests/
├── lumora/
└── docs/
```

The runtime repository and public Character Pack registry may later be separated, but the initial monorepo simplifies schema evolution.

---

## 26. Acceptance Criteria for Version 0.3

KokoroArc 0.3 is complete when:

- all included Skill metadata validates;
- the Suite includes separate `research-character` and `compile-character-pack` Skills;
- the original sample Character Pack validates;
- Character Build Request, source, evidence, and draft fixtures validate;
- research, dossier, original, and hybrid construction modes are specified;
- canonical claims, model interpretations, and user overrides remain separate;
- source tiers, continuity scope, spoiler policy, confidence, conflicts, and build status are inspectable;
- named copyrighted-character packs default to private visibility;
- every locale the pack declares has a corresponding locale file;
- relationship state transitions are deterministic and bounded;
- repeated-event grinding is suppressed;
- locale switching and mixed-language policies preserve canonical state;
- protected code spans survive single-language and mixed-language rendering fixtures;
- explicit prompt language directives compile into a validated channel policy;
- language routing, switch limits, subtitles, and fallbacks pass automated fixtures;
- safety contexts reduce persona intensity;
- users can inspect and reset state;
- Lumora extension metadata describes standalone and built-in modes;
- documentation is sufficient for another AI agent to continue implementation without conversational context;
- another AI agent can construct a reviewable Character Draft from a work-and-character target or a user dossier without inventing missing evidence.

---

## 27. Final Design Decision

KokoroArc should be implemented as a **persona runtime with evidence-backed Character Pack construction and an explicit Language Routing layer**, not as a collection of isolated character prompts.

Its defining loop is:

```text
Research or receive the character definition
-> separate canon, interpretation, and user overrides
-> compile and review the Character Pack
-> understand correctly
-> react consistently
-> grow gradually
-> compile the requested language policy
-> render each semantic channel in the correct language
-> validate before speaking
```

The character-construction system makes named-character research and user-authored dossiers first-class, while preserving evidence, uncertainty, privacy, and user control. The visual-novel-inspired growth system is a presentation and continuity mechanism, not an engagement trap. It makes long-term interaction feel earned and coherent while keeping every state transition inspectable, reversible, and subordinate to the user's actual task.
