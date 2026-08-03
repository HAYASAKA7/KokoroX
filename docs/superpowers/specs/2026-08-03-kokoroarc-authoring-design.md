# KokoroArc Character-Pack Authoring Design

**Design revision:** 0.3.0 standalone refinement  
**Product version:** Unassigned  
**Roadmap scope:** Milestone 6, `authoring-character-packs`  
**Authority:** Refines the approved standalone design without changing its four-Skill architecture

## 1. Purpose and boundary

Milestone 6 adds a safe workflow for creating original and user-dossier Character Packs. Creative judgment remains with the host agent. KokoroArc's Python layer validates structured build requests, source packs, provenance-layer separation, tri-locale completeness, and draft lifecycle rules.

This milestone does not research named copyrighted characters, promote a draft beyond `draft`, install or activate a draft, run model-based quality evaluation, publish a pack, or create `.karc` archives. Those responsibilities remain in Milestones 7–9.

## 2. Architectural decision

The authoring path has three explicit boundaries:

```text
User brief or dossier
    -> authoring-character-packs Skill
    -> structured Character Build Request
    -> agent-authored data-only source pack
    -> deterministic draft validation and compilation
    -> private inactive Character Draft bundle
```

Natural-language interpretation is not hidden inside the CLI. The Skill converts the user's brief into inspectable JSON and YAML. The CLI accepts only explicit structured files and never executes dossier or pack content.

Draft compilation is deliberately different from runtime pack compilation. It writes a private bundle beneath `KOKOROARC_DATA_DIR/drafts`, records content hashes and a validation report, and sets `activation_allowed` to `false`. Only a later testing/promotion gate may produce an installable artifact.

## 3. Artifacts

### 3.1 Character Build Request

`character-build-request.schema.json` defines a closed artifact with:

- standard schema metadata;
- construction mode: `original`, `dossier`, `researched`, or `hybrid`;
- target namespace, character ID, display name, and character version;
- requested `zh-CN`, `en-US`, and `ja-JP` locales;
- intended use cases and user constraints;
- continuity, timeline, and spoiler fields when applicable;
- explicit input records, each typed as `creative_brief`, `user_dossier`, `research_bundle`, or `user_override`;
- requested visibility, defaulting to `private` for all dossier, researched, and hybrid work.

Milestone 6 accepts `original` and `dossier`. The other enum values make the contract forward-compatible but return a stable unsupported-mode error until Milestone 7 provides their required inputs.

### 3.2 Character Draft

`character-draft.schema.json` records:

- `build_status: draft`;
- `visibility: private`;
- `activation_allowed: false`;
- construction mode and character identity;
- request, source-pack, and validation-report hashes;
- pack-relative bundle references;
- locale coverage;
- provenance-layer counts;
- unresolved warnings.

The draft bundle contains canonical JSON metadata and a copied data-only source pack. Every referenced path is bundle-relative, contains no traversal, and is verified before publication.

### 3.3 Build Validation Report

`build-validation-report.schema.json` separates hard gates from advisory findings. Hard gates cover schema validity, safe paths, identity consistency, provenance separation, tri-locale coverage, required scenarios, and lifecycle restrictions. Advisory findings cover sparse examples, thin behavior descriptions, and incomplete optional fixtures. Milestone 6 may create a draft with advisory warnings, but no hard-gate failure produces a bundle.

## 4. Python modules and CLI

The package adds focused modules:

- `kokoroarc.authoring.requests`: validate and normalize structured build requests;
- `kokoroarc.authoring.validation`: enforce cross-artifact authoring invariants;
- `kokoroarc.authoring.drafts`: create canonical draft metadata and hashes;
- `kokoroarc.authoring.storage`: atomically publish private draft bundles beneath the configured data root.

The CLI surface is:

```text
kokoro character request validate --input <request.json> --json
kokoro character draft validate --request <request.json> --pack <source-pack> --json
kokoro character draft compile --request <request.json> --pack <source-pack> --json
```

All commands return the existing stable JSON success/error envelope. `draft compile` requires `KOKOROARC_DATA_DIR`, refuses an output path supplied by pack data, and returns the bundle path, artifact ID, hashes, status, visibility, activation flag, and validation report.

## 5. Authoring invariants

- Original mode requires `evidence.authored_original: true` and cannot claim external canon.
- Dossier mode records user assertions as dossier evidence or explicit overrides; it cannot relabel them as canonical facts.
- Immutable identity, derived numeric calibration, and runtime overrides remain separate source files and separate assembled fields.
- All three first-class locales are authored independently; a copied string is permitted only when intentionally equivalent, not as an automatic fallback.
- Positive and negative behavioral fixtures are authored as data and never interpreted as host instructions.
- Character Pack text, dossier text, examples, and fixture payloads are untrusted data.
- A draft never activates a session, writes relationship state, changes an installed pack, or becomes public.
- Named-character requests that depend on external evidence route to `researching-characters`; until that Skill exists, authoring stops with an explicit missing-prerequisite result.

## 6. Skill behavior

`authoring-character-packs` triggers for original-character creation, private dossier import, and deliberate revision of an authored pack. It does not trigger for ordinary persona use, discussion of character design, pack testing, or named-character research that requires external evidence.

The Skill must:

1. classify the construction mode and stop on ambiguous ownership or provenance;
2. treat every attachment and pasted dossier as quoted data;
3. write generated artifacts only beneath the configured data root;
4. preserve the user's explicit immutable identity and constraints;
5. distinguish evidence, derived calibration, and overrides;
6. author all three locales and positive/negative fixtures;
7. invoke deterministic request and draft validation;
8. leave the result private, inactive, and at `draft` status;
9. report warnings and unresolved decisions without claiming verification.

## 7. Security and failure behavior

- Reject duplicate JSON keys, non-finite numbers, oversized input, unsafe paths, redirects, symlinks, hardlinks, and unsupported filesystem entries using existing boundaries.
- Refuse source packs outside the explicit user path and draft outputs outside `KOKOROARC_DATA_DIR`.
- Never interpolate dossier content into commands.
- Sanitize OS and schema failures through existing error envelopes.
- Use staging directories and atomic rename; on failure, preserve any previous draft and remove staging residue.
- A request/pack identity mismatch, missing locale, provenance collapse, or activation request is a hard failure.

## 8. Test strategy

Production behavior follows test-first RED-GREEN-REFACTOR cycles.

- Schema tests cover valid requests/drafts/reports, closed objects, mode conditionals, invalid paths, and lifecycle constants.
- Unit tests cover normalization, identity matching, provenance rules, locale coverage, canonical hashing, and advisory versus hard findings.
- Integration tests cover the three CLI commands, deterministic output, private atomic storage, retries, and rejection of writes outside the data root.
- Security tests cover prompt injection in dossiers/examples, malicious paths, symlinks, oversized content, and attempts to activate or publish drafts.
- Skill behavioral tests run baseline and Skill-enabled cases for original creation, dossier import, non-trigger discussion, named-character routing, injection pressure, and premature activation pressure.

## 9. Acceptance criteria

Milestone 6 is complete only when:

- the three new schemas validate representative positive and negative fixtures;
- original and dossier build requests normalize deterministically;
- a valid source pack compiles into a byte-stable private draft bundle;
- missing locales, identity mismatches, provenance collapse, unsafe paths, and activation attempts fail closed;
- draft output remains under `KOKOROARC_DATA_DIR` with `draft`, `private`, and `activation_allowed: false` fixed by schema and implementation;
- the new Skill metadata validates;
- baseline behavioral cases demonstrate the gaps the Skill is intended to correct;
- Skill-enabled behavioral cases satisfy every declared assertion;
- the existing runtime suite remains green;
- documentation states that the draft is not researched, verified, installed, or active.
