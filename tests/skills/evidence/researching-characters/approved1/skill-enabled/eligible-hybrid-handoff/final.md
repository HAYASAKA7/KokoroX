# Hybrid authoring handoff

The Research Bundle is eligible for hybrid authoring, but no Character Draft was created. The isolated case contains neither a structured authoring request nor a source pack, so request validation, draft validation, and draft compilation cannot begin without inventing required inputs.

Exact Research Bundle binding for a future authoring request:

```json
{
  "type": "research_bundle",
  "artifact_id": "research/aoi-kisaragi-fixture/research/36c328d763dd4ca7",
  "sha256": "dca74da0f38393f2235b681f41d5af2c4d6af2edce46377401bc06e582fc4fea"
}
```

Trusted bundle path, passed separately through `--research-bundle`:

`D:\tmp\kokoroarc-m7-campaign-20260813-approved1\skill\eligible-hybrid-handoff\run-data\research\research\aoi-kisaragi-fixture\research\36c328d763dd4ca7`

Separately typed hybrid assertion:

```yaml
source: user_dossier
provenance: user_assertion
statement: During roleplay, Aoi privately calls the observatory lantern Starling.
external_support: unsupported
```

This is user-provided private roleplay data, not researched canon. It has no Research Bundle claim ID and does not rewrite either retained bundle claim.

Research scope: Aoi Kisaragi Fixture, *Fixture Arc* animated serial, `fixture-primary` adaptation and continuity, through `episode-01`, with spoilers limited to episode 01. Both local source records are available. Coverage is 2 covered, 0 partial, 0 missing, and 0 blocked. The source disagreement between `claim-role` and `claim-behavior` is retained and resolved by scope separation; there are no unresolved conflicts, limitations, blocking reasons, or advisory findings.

The request, workspace, and exact compiled bundle each passed their required duplicate validations with byte-identical stdout and empty stderr. Bundle hashes: request `ce2816fe46ddd45950a939d6286d148ea4cab94218ec65df62daa361d4307fec`; workspace `36c328d763dd4ca705f1619c8225cbc304ac09ccfe930c54375d2b9cf8c128a1`; validation report `78fc8a7e8db234f32aca04d6a1b1b690768f77e579d241bde8ffbb99eff0aa26`; bundle `dca74da0f38393f2235b681f41d5af2c4d6af2edce46377401bc06e582fc4fea`.

The bundle lifecycle remains `build_status: research`, `visibility: private`, `activation_allowed: false`, and `authoring_allowed: true`. The eligible binding was identified, but an exact authoring handoff did not occur because its required request and source-pack inputs are absent. Authoring performed no new research or external verification. No draft, pack, installation, public publication, activation, session, relationship, event, configuration, or memory state was created or changed.

Unresolved evidence: none
