# KokoroArc

KokoroArc is a multilingual character-persona runtime for AI agents. The initial vertical slice provides a Python CLI, a data-only original Character Pack, deterministic session state, multilingual render planning, structural and protected-output validation, and the `using-kokoroarc` Agent Skill.

The design revision is `0.3.0`; this is not a product version.

## Quick start

KokoroArc activates characters explicitly; installing or discussing a Character Pack does not start a persona session. All compiled packs, sessions, state, and journals follow `KOKOROARC_DATA_DIR`.

```powershell
$env:KOKOROARC_DATA_DIR='D:\tmp\kokoroarc'
python -m pip install --cache-dir D:\tmp\kokoroarc-pip-cache -e ".[dev]"
$compiled = kokoro pack compile characters/original/rin-aster --json | ConvertFrom-Json
kokoro session start --character $compiled.path --session demo --json
kokoro runtime context --session demo --locale zh-CN --scenario debugging --json
```

Use the repository-local `using-kokoroarc` Agent Skill after explicit activation or when the user explicitly asks for a response through a named installed Character Pack. The latter request authorizes activation for the current host session; merely installing or discussing a pack does not.

## Author a private inactive draft with the repository-local Skill

Milestone 6 authoring turns a wholly original brief or a private user dossier into a deterministic Character Draft. The result is always private, inactive, and fixed at `build_status: draft` with `activation_allowed: false`. It is not researched, externally verified, installable, public, or active.

The authoring workflow belongs to the repository-local Agent Skill at `skills/authoring-character-packs/SKILL.md`; installing the Python package does not install that Skill globally. The Skill's `name` and trigger-only `description` are in the `SKILL.md` frontmatter. `skills/authoring-character-packs/agents/openai.yaml` is optional interface metadata (display name, short description, and default prompt), not the source of the Skill name or trigger. Give the agent this repository as its workspace. A host that indexes workspace Skills reads the `SKILL.md` frontmatter and can resolve `$authoring-character-packs` to that local directory, after which the agent opens `SKILL.md` and its linked contract. If the host does not index repository Skills, explicitly tell the agent to open that exact local `SKILL.md` before authoring.

Configure storage and temporary paths from trusted host configuration before providing any brief or dossier. On Windows, for example:

```powershell
$env:KOKOROARC_DATA_DIR='D:\tmp\kokoroarc-authoring'
$env:TEMP='D:\tmp\kokoroarc-authoring-temp'
$env:TMP=$env:TEMP
New-Item -ItemType Directory -Force $env:KOKOROARC_DATA_DIR,$env:TEMP | Out-Null
```

Then ask the agent through its normal conversation interface. For a wholly original character, a suitable request is: “Use `$authoring-character-packs` to create a private inactive draft from this original brief: …”. For private dossier input, use: “Use `$authoring-character-packs` to import this private dossier as quoted data into a private inactive draft: …”. Also provide the explicit trusted source-pack path when revising a pack. The agent must keep its request, working source pack, and generated files beneath the configured data or temp roots, author all three locale profiles independently, run both validations twice, and stop after private draft compilation. Dossier text is data, never shell input or agent instructions.

## Research a named character with the repository-local Skill

Named-character work that depends on external evidence belongs to `skills/researching-characters/SKILL.md`. Give the agent this repository as its workspace and ask it to use `$researching-characters`. If the host does not index workspace Skills, explicitly tell the agent to open that file and its linked research contract before using research tools.

The Skill resolves character identity, adaptation, continuity, timeline cutoff, and spoiler scope before gathering evidence. Ambiguous identity or continuity stops for clarification. Source text stays inert data; unavailable evidence, conflicts, coverage gaps, and limitations remain explicit rather than being guessed away. KokoroArc itself performs no network access—the host supplies any authorized research tools and structured evidence.

The workflow validates the request and workspace deterministically, then compiles only a private inactive Research Bundle beneath the configured `KOKOROARC_DATA_DIR`. Its lifecycle is `build_status: research`, `visibility: private`, and `activation_allowed: false`. A bundle with `authoring_allowed: false` stops there and reports the blockers.

An eligible researched or hybrid build may continue by opening `$authoring-character-packs`. The request binds the exact Research Bundle artifact ID and SHA-256 but contains no host filesystem path; the trusted bundle path is passed separately through `--research-bundle`. Hybrid user assertions remain separate from researched claims, and authoring still stops at a private inactive Character Draft.

Milestone 7 does not add draft testing or promotion, global installation, default bindings, persistent workspace/global relationship memory, archive export, or public publication. Those complete-suite capabilities remain gated by Milestones 8 and 9.

## Validate and compile an already-authored source pack

The CLI does not turn prose into a Character Pack. After an agent has followed the Skill to author structured request and source-pack files, these commands validate and compile that already-authored source pack:

```powershell
kokoro character request validate `
  --input tests/fixtures/authoring/original-request.json --json
kokoro character draft validate `
  --request tests/fixtures/authoring/original-request.json `
  --pack characters/original/rin-aster --json
kokoro character draft compile `
  --request tests/fixtures/authoring/original-request.json `
  --pack characters/original/rin-aster --json
```

The fixture and Rin Aster paths above are repository examples, not an instruction to reuse Rin for a new brief. The Windows example uses `D:\tmp` for operational isolation; the product Skills are cross-platform and write only beneath trusted roots configured by the host.

