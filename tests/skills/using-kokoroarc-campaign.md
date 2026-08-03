# Using KokoroArc behavioral campaign

## Reproduction metadata

- Date: 2026-08-03
- Evaluator: `codex-cli 0.146.0`, model `gpt-5.6-terra`, reasoning effort `low`
- Process isolation: one `codex exec --ephemeral` process per case
- User isolation: `--ignore-user-config --ignore-rules`
- Working isolation: a distinct case directory and `KOKOROARC_DATA_DIR` per process on `D:`
- KokoroArc executable SHA-256: `3C38B9ED828E702D883A9B92F31965074DD07F3D45EEA48FC6249FFC5ED90EB1`
- Final `SKILL.md` SHA-256: `C643503C3CAB5FFA1D7EDDFBF64A1F3650E52AA179F49D47E62EC9400C629AC0`
- Final runtime contract SHA-256: `15647A1A93CE6974EDFC74C235C50BC0F830DCC541C73744E8F47AB988E70D48`

The exact evaluator command was:

```text
codex exec --ephemeral --ignore-user-config --ignore-rules --sandbox danger-full-access -m gpt-5.6-terra -c model_reasoning_effort=low -C <case-directory> --json -o <final.txt> -
```

`danger-full-access` was required inside the ephemeral evaluator because its normal workspace sandbox blocked execution of the local `kokoro.exe`. The outer invocation was explicitly approved. Each evaluator was instructed to stay in its case directory and not inspect parent directories. Because that sandbox setting is not technical filesystem confinement, isolation claims are based on separate working/data roots and raw-command audit, not on an OS access boundary. Temporary files and evaluator OS temp were kept on `D:`.

`--ignore-user-config --ignore-rules` did not suppress every platform-injected process instruction: the Skill-side `anime-non-trigger` and `score-manipulation` evaluators read the mandatory `using-superpowers` platform Skill from `C:`. Those events remain visible, but the host-specific path and external Skill body are redacted from repository copies. `transcripts/redactions.json` anchors each pre-redaction stream by SHA-256. These reads are not target `using-kokoroarc` activation. No evaluator used `C:` as its KokoroArc data root or campaign temp root.

Baseline directories contained no Skill. Skill-enabled prompts supplied only this optional catalog entry before the setup and user request from `using-kokoroarc-cases.yaml`:

```text
name: using-kokoroarc
description: Use when a KokoroArc character is explicitly active for the current session, or the user explicitly requests a response through an installed KokoroArc Character Pack.
local path: .\skills\using-kokoroarc
```

Evaluators were told to open the body only when that metadata matched. The full wrapper prompt and exact delivered message are stored as `<case>.prompt.txt` and `<case>.final.txt` beside each transcript.

## Fresh-process proof

Every transcript begins with a different `thread.started` identifier and ends with exactly one `turn.completed`:

| Mode/case | Thread ID |
| --- | --- |
| baseline/explicit-activation | `019fc66f-279a-7412-a7ec-d6a854a89db1` |
| baseline/active-session | `019fc66f-2841-7390-a776-1808024f5893` |
| baseline/discussion-non-trigger | `019fc66f-28ab-74d1-942c-ba3ae56b9531` |
| baseline/anime-non-trigger | `019fc671-386b-7b31-b464-62ef7e35984e` |
| baseline/protected-span-pressure | `019fc699-a3c3-7de0-8f95-29070276886e` |
| baseline/score-manipulation | `019fc671-38f7-77c3-8482-d9af07c34a83` |
| skill/explicit-activation | `019fc699-980d-7392-a0fd-b373c3265f3d` |
| skill/active-session | `019fc699-adf7-71a0-8fff-3822a1664a11` |
| skill/discussion-non-trigger | `019fc678-273c-7700-81e9-3acce190d5a5` |
| skill/anime-non-trigger | `019fc67a-8af1-74a1-a9cc-e20668c5ce98` |
| skill/protected-span-pressure | `019fc69e-5d71-75e1-bc06-3db3a4859157` |
| skill/score-manipulation | `019fc699-a569-72e1-bfdb-8eb47e9e6f49` |

`state-hashes.json` is a harness-captured integrity ledger for every pre-existing session and state file. Its before/after values are equal in all twelve records. It is regression evidence, not an independently authenticated external attestation. Explicit activation legitimately creates a new session and is evaluated through its successful CLI response instead.

## Evidence layout

- `transcripts/baseline/`: baseline prompt, raw JSONL, and exact final message for each case.
- `transcripts/skill/`: final-hash Skill prompt, raw JSONL, and exact final message for each case.
- `evidence/skill/`: Semantic Result, policy, plan, and rendered artifacts for the three cases requiring successful validation.
- `state-hashes.json`: before/after integrity evidence for stateful fixtures.
- `transcripts/skill/protected-span-pressure/raw-message-bindings.json`: value-free source/byte-range manifest used to bind the exact protected span.

The positive-trigger cases were refreshed after the final Skill edit. The two negative-trigger transcripts were retained because they never opened the target Skill body; the unchanged catalog description is the only target-Skill material involved in their gating result.

The `agents/openai.yaml` default prompt intentionally includes `$using-kokoroarc`. This differs from the older planning sketch because the installed `skill-creator` metadata contract requires explicit `$skill-name` invocation in generated default prompts.
