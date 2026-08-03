# Behavioral transcript evidence

Each case directory contains the exact evaluator wrapper prompt, exact final message, and the Codex JSONL event stream. Large streams are split only at JSONL record boundaries. Read `part-001.jsonl`, `part-002.jsonl`, and so on in lexical order to reconstruct the stream.

Every stream begins with `thread.started` and ends with `turn.completed`. The campaign metadata and thread IDs are in `../../using-kokoroarc-campaign.md`.

The protected-span Skill case also contains `raw-message-bindings.json`. It records only a source path and byte range; the test reconstructs the protected value from the raw prompt. Host-specific paths and external platform-Skill bodies are redacted from two repository streams. `redactions.json` records the SHA-256 of each pre-redaction stream; private originals were retained under `D:\tmp` for the local review. Redaction does not hide target `using-kokoroarc` activation or KokoroArc commands.
