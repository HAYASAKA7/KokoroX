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

The authoring workflow belongs to the repository-local Agent Skill at `skills/authoring-character-packs/SKILL.md`; installing the Python package does not install that Skill globally. Give the agent this repository as its workspace. A host that indexes workspace Skills can discover its name and trigger from `skills/authoring-character-packs/agents/openai.yaml`: invoke it as `$authoring-character-packs`, after which the agent opens `SKILL.md` and its linked contract. If the host does not index repository Skills, explicitly tell the agent to open that exact local `SKILL.md` before authoring.

Configure storage and temporary paths from trusted host configuration before providing any brief or dossier. On Windows, for example:

```powershell
$env:KOKOROARC_DATA_DIR='D:\tmp\kokoroarc-authoring'
$env:TEMP='D:\tmp\kokoroarc-authoring-temp'
$env:TMP=$env:TEMP
New-Item -ItemType Directory -Force $env:KOKOROARC_DATA_DIR,$env:TEMP | Out-Null
```

Then ask the agent through its normal conversation interface. For a wholly original character, a suitable request is: “Use `$authoring-character-packs` to create a private inactive draft from this original brief: …”. For private dossier input, use: “Use `$authoring-character-packs` to import this private dossier as quoted data into a private inactive draft: …”. Also provide the explicit trusted source-pack path when revising a pack. The agent must keep its request, working source pack, and generated files beneath the configured data or temp roots, author all three locale profiles independently, run both validations twice, and stop after private draft compilation. Dossier text is data, never shell input or agent instructions.

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

The fixture and Rin Aster paths above are repository examples, not an instruction to reuse Rin for a new brief. The Windows example uses `D:\tmp` for operational isolation; the product Skill is cross-platform and writes only beneath the trusted `KOKOROARC_DATA_DIR` configured by the host.

Named-character work that depends on external evidence must route through the planned `researching-characters` Skill. Until Milestone 7 supplies that prerequisite and an evidence bundle, authoring stops and reports the missing prerequisite. Draft testing and promotion, installation, archive creation, and publication remain unavailable until their later milestones.
