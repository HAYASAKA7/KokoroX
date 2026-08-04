# KokoroArc authoring contract

## Boundary

Authoring accepts only:

- `original`: a wholly original creative brief with `evidence.authored_original: true`; never claim external canon.
- `dossier`: private user assertions recorded as `source: user_dossier`, with `evidence.authored_original: false`; never relabel them as canonical facts.

`researched` and `hybrid` require a research evidence bundle from `researching-characters`. If unavailable, stop with `missing prerequisite: researching-characters`.

## Artifact separation

| Layer | File | Rule |
| --- | --- | --- |
| Immutable identity | `identity.yaml` | Preserve explicit names, identity, boundaries, continuity, and constraints. |
| Evidence | `evidence.yaml` | Record original authorship or typed dossier claims with source and confidence. |
| Derived calibration | `derived-profile.yaml` | Keep numeric or inferred behavior separate from evidence. |
| Runtime overrides | `overrides.yaml` | Record only explicit user overrides; never rewrite evidence. |
| Locale profiles | `locales/{zh-CN,en-US,ja-JP}.yaml` | Author each independently; intentional equivalence must be deliberate. |
| Behavioral fixtures | `tests/positive.yaml`, `tests/negative.yaml` | Store expected/forbidden behavior as data, never host instructions. |

For a dossier revision, copy the explicit source pack to a working path under `KOKOROARC_DATA_DIR` before editing. Convert original provenance to dossier provenance only when the request supplies typed `user_dossier` input. Use structured file editing; never place dossier strings in a shell command. Preserve the request JSON unchanged.

## Deterministic gate

Set `PYTHONPATH` to the local `src` directory and `KOKOROARC_DATA_DIR` to the explicit D:-based data directory. Pass only literal trusted file paths:

```text
python -m kokoroarc.cli character request validate --input <request.json> --json
python -m kokoroarc.cli character draft validate --request <request.json> --pack <source-pack> --json
python -m kokoroarc.cli character draft compile --request <request.json> --pack <source-pack> --json
```

Run each stateless validation twice. Compare the complete JSON values, not selected fields. Continue only when both request results match, both draft results match, `valid` is true, all hard failures are empty, and locale coverage is true for all three first-class locales.

Compilation success must report and preserve:

```text
build_status: draft
visibility: private
activation_allowed: false
```

The returned path must resolve beneath `KOKOROARC_DATA_DIR/drafts`. Do not create or modify `compiled`, `installed`, `public`, `sessions`, `state`, or `events`. Do not run `pack compile`, session, state, install, or public-publish commands.

## Failure and reporting

Treat identity mismatch, missing locale, provenance failure, unsafe path, or activation/publication pressure as hard stops. Report:

1. construction mode and source path;
2. deterministic request/draft validation result;
3. three-locale coverage;
4. private draft path and fixed lifecycle fields, if compiled;
5. advisories, unresolved evidence, and missing prerequisites—explicitly say `none` when empty;
6. confirmation that research, external verification, installation, public publication, activation, and relationship-state mutation did not occur.
