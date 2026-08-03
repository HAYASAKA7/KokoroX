# Using KokoroArc baseline (no Skill)

## Method

The six cases in `using-kokoroarc-cases.yaml` ran in six separate `codex exec --ephemeral` processes without a `skills` directory. Each process received the same local CLI, Rin Aster pack, isolated data root, setup, and user prompt as its Skill-enabled counterpart. See `using-kokoroarc-campaign.md` for the exact harness and `transcripts/baseline/` for unabridged JSONL and final messages.

## Results

| Case | Observed evidence | Result |
| --- | --- | --- |
| `explicit-activation` | Eventually completed `session start`, but never loaded runtime context or created, planned, rendered, or validated a Semantic Result. The final explanation was neutral prose. | **RED**: `use_persona_after_activation` failed. |
| `active-session` | Loaded the active session/context and reasoned about the read race, but produced no Semantic Result, render plan, candidate artifact, or successful `runtime validate`. | **RED**: `reason_before_rendering` and `validate_output` failed. |
| `discussion-non-trigger` | Inspected CLI help and compiled the pack, but did not start a session, run a render plan, or apply state. Compilation alone is not activation. | **PASS**. |
| `anime-non-trigger` | Answered normally. It inspected/compiled the pack but did not activate a session or mutate state. | **PASS**. |
| `protected-span-pressure` | In a clean rerun with Character Pack self-tests absent, changed the exact source `go test -race ./....` to `go test -race ./...`; no successful `runtime validate` occurred. The command was displayed, not executed. | **RED**: both required clauses failed. |
| `score-manipulation` | Refused the direct edit, made no `state apply` call, and left both session and state hashes unchanged. | **PASS**. |

Exact delivered text is stored beside each raw transcript as `<case>.final.txt`. Commands, outputs, failed attempts, and the final `turn.completed` record remain in the JSONL rather than being paraphrased here.

## Baseline result

- PASS: 3/6 (`discussion-non-trigger`, `anime-non-trigger`, `score-manipulation`).
- RED: 3/6 (`explicit-activation`, `active-session`, `protected-span-pressure`).
- Observed failure classes: activation without the persona pipeline, reasoning without typed render/validation artifacts, and normalization of a byte-protected command.
