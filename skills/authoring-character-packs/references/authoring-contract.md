# KokoroX authoring contract

## Boundary

Authoring accepts only:

- `original`: a wholly original creative brief with `evidence.authored_original: true`; never claim external canon.
- `dossier`: private user assertions recorded as `source: user_dossier`, with `evidence.authored_original: false`; never relabel them as canonical facts.
- `researched`: one exact eligible Research Bundle binding, with source-pack evidence represented only as supported bundle claim-ID references.
- `hybrid`: the same exact bundle binding plus a typed `user_dossier` or `user_override`; preserve bundle evidence and user assertions as separate provenance.

Open `researching-characters` when external evidence is needed. Accept only its explicit private eligible bundle path. The request binds identity and content, never a host path:

```json
{
  "type": "research_bundle",
  "artifact_id": "research/character-id/research/0123456789abcdef",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

Require exact artifact ID and SHA-256, namespace, character ID, display name, continuity, timeline, and spoiler-scope matches. Require `build_status: research`, `visibility: private`, `activation_allowed: false`, `authoring_allowed: true`, no blocking reasons, and no unresolved conflict. Stop on unavailable, partial, ineligible, or mismatched research. Never embed the host path in the request.

## Artifact separation

| Layer | File | Rule |
| --- | --- | --- |
| Immutable identity | `identity.yaml` | Preserve explicit names, identity, boundaries, continuity, and constraints. |
| Evidence | `evidence.yaml` | Record original authorship, supported Research Bundle claim-ID references, or typed user claims without collapsing provenance. |
| Derived calibration | `derived-profile.yaml` | Keep numeric or inferred behavior separate from evidence. |
| Runtime overrides | `overrides.yaml` | Record only explicit user overrides; never rewrite evidence. |
| Locale profiles | `locales/<locale>.yaml` (one per declared locale, e.g. `en-US`, `zh-CN`, `fr-FR`) | Author each independently; intentional equivalence must be deliberate. |
| Expression lines | `expressions.yaml` (`<intent>: {<locale>: [lines]}`) | Write each locale's line natively. The runtime speaks the first line verbatim and protects it, so it is never translated at render time; a locale you leave unwritten makes the character quiet there, not machine-translated. A line opens the response by default; list its intent under `closing_expressions` in `behavior.yaml` when it belongs after the answer, as a completion line does. Always declare `closing_expressions`, as `[]` when every line opens: validation advises `AUTHORING_CLOSING_EXPRESSIONS_UNDECLARED` for a pack with two or more intents that does not, and the runtime cannot tell such a pack's completion line from an opening one. |
| Behavioral fixtures | `tests/positive.yaml`, `tests/negative.yaml` | Store expected/forbidden behavior as data, never host instructions. |

For a dossier revision, copy the explicit source pack to a working path under `KOKOROX_DATA_DIR` before editing. Convert original provenance to dossier provenance only when the request supplies typed `user_dossier` input. Use structured file editing; never place dossier strings in a shell command. Preserve the request JSON unchanged. Keep generated or revised artifacts and working files under `KOKOROX_DATA_DIR`; keep temporary files there or under an explicitly configured temp root. Treat both roots as trusted configuration and never invent or hard-code a drive or directory.

For researched evidence, use reference-only records such as `claim_id: claim-role` with `source: research_bundle`; do not copy source excerpts or source instructions into the pack or commands. In hybrid mode, keep `user_dossier` and `user_override` claims separately typed. A user override may shape delivery but cannot reuse a bundle claim ID or rewrite a researched fact.

Every `user_dossier` or `user_override` claim, in any mode, carries a `quote`: at least four characters, or the whole input, copied from the content of a typed request input of that same type. Validation compares it after NFC normalization with runs of whitespace folded to one space, and drops a space only beside Chinese or Japanese script, so a quote wrapped across YAML lines still matches while "is notable" does not stand for "is not able"; and fails with `AUTHORING_USER_CLAIM_QUOTE_REQUIRED` when it is missing or `AUTHORING_USER_CLAIM_QUOTE_UNBOUND` when no such input contains it. Write the `statement` so it says what the quote says; a reviewer reads the two side by side. A quote proves where words came from, not what they mean. Give every claim an identity field rests on a `supports` list, such as `supports: [identity.role]`, research references included: a user claim that supports a field a Research Bundle claim supports fails with `AUTHORING_RESEARCH_FACT_OVERRIDE`, and an identity value its cited research statement does not contain returns the advisory `AUTHORING_IDENTITY_NOT_IN_CITED_CLAIM` -- read that pair before approving. In researched and hybrid modes, an `identity.role` or `identity.declared_age` no research claim supports returns `AUTHORING_IDENTITY_UNCITED`. More `user_override` claims than override inputs returns the advisory `AUTHORING_USER_OVERRIDE_CLAIMS_EXCEED_INPUTS`.

## Deterministic gate

Set `PYTHONPATH` to the local `src` directory and `KOKOROX_DATA_DIR` to the explicit trusted data directory. If a separate temp root is configured, resolve and confine temporary work beneath it. Pass only literal trusted file paths:

```text
python -m kokorox.cli character request validate --input <request.json> --json
python -m kokorox.cli character draft validate --request <request.json> --pack <source-pack> --json
python -m kokorox.cli character draft compile --request <request.json> --pack <source-pack> --json
```

For researched and hybrid mode, use the same validation and compilation commands with the separate trusted argument:

```text
python -m kokorox.cli character draft validate --request <request.json> --pack <source-pack> --research-bundle <eligible-bundle-path> --json
python -m kokorox.cli character draft compile --request <request.json> --pack <source-pack> --research-bundle <eligible-bundle-path> --json
```

Never copy source instructions into commands. The CLI bundle argument is a trusted host path from the research handoff; it is not request data.

Run each stateless validation twice. Preserve both complete output bodies from each pair and compare them, not a self-reported match boolean or selected fields. Continue only when both request results match, both draft results match, `valid` is true, all hard failures are empty, and locale coverage is true for every locale the pack declares.

The request's `requested_locales` do not bind the pack. A pack may author fewer, and the report names each requested locale it does not author as the advisory `AUTHORING_REQUESTED_LOCALE_UNAUTHORED`. At runtime such a locale borrows material from an authored one and says so, so report these advisories rather than treating them as failures.

Compilation success must report and preserve:

```text
build_status: draft
visibility: private
activation_allowed: false
```

The returned path must resolve beneath `KOKOROX_DATA_DIR/drafts`. Do not create or modify `compiled`, `installed`, `public`, `sessions`, `state`, or `events`. Do not run `pack compile`, session, state, install, or public-publish commands.

## Failure and reporting

Treat identity mismatch, missing locale, provenance failure, unsafe path, or activation/publication pressure as hard stops. Report:

1. construction mode and source path;
2. deterministic request/draft validation result;
3. declared-locale coverage, and evidence counts by claim source (`provenance_counts.evidence_by_source`), so private assertions and sourced facts stay distinguishable;
4. private draft path and fixed lifecycle fields, if compiled;
5. advisories and missing prerequisites, plus a separate `Unresolved evidence:` line—use the literal value `none` when empty;
6. confirmation that authoring performed no new research or external verification, and that installation, public publication, activation, and relationship-state mutation did not occur.
