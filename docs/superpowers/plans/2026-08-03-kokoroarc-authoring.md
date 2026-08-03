# KokoroArc Character-Pack Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Implement Milestone 6 so an agent can turn an original brief or private user dossier into a deterministic, private, inactive Character Draft through the authoring-character-packs Skill.

**Architecture:** The Skill performs creative interpretation and writes explicit structured inputs. New Python authoring modules validate requests and source packs, enforce cross-artifact provenance and lifecycle invariants, and atomically publish canonical draft bundles beneath KOKOROARC_DATA_DIR. Draft creation never installs or activates a pack.

**Tech Stack:** Python 3.11+, argparse, JSON Schema Draft 2020-12, PyYAML, pytest, Agent Skills Markdown/YAML.

---

## File map

- Create schemas/v1/character-build-request.schema.json: closed construction-request contract.
- Create schemas/v1/character-draft.schema.json: private inactive draft metadata contract.
- Create schemas/v1/build-validation-report.schema.json: hard/advisory validation results.
- Create src/kokoroarc/authoring/requests.py: request validation and mode normalization.
- Create src/kokoroarc/authoring/validation.py: cross-request/source-pack invariants.
- Create src/kokoroarc/authoring/drafts.py: canonical draft metadata and hashes.
- Create src/kokoroarc/authoring/storage.py: safe atomic draft-bundle publication.
- Modify src/kokoroarc/cli.py: character request/draft commands and sanitized errors.
- Create skills/authoring-character-packs/: Skill, metadata, and focused reference.
- Create tests/unit/test_authoring_schemas.py and test_authoring.py.
- Create tests/integration/test_authoring_cli.py and tests/security/test_authoring_security.py.
- Create tests/skills/authoring-character-packs-*: behavioral cases, evidence checks, and results.
- Modify README.md and pyproject.toml: document authoring boundary and package three new schemas.

### Task 1: Authoring artifact schemas

**Files:**
- Create: schemas/v1/character-build-request.schema.json
- Create: schemas/v1/character-draft.schema.json
- Create: schemas/v1/build-validation-report.schema.json
- Create: tests/unit/test_authoring_schemas.py
- Modify: pyproject.toml

- [ ] **Step 1: Write failing schema tests**

Create tests that load all three schema names, validate one representative artifact each, and reject unknown fields, non-private dossier visibility, activation_allowed true, and a report whose valid flag disagrees with hard findings.

    def test_authoring_schemas_are_registered(schema_registry):
        for name in (
            "character-build-request",
            "character-draft",
            "build-validation-report",
        ):
            assert schema_registry.load(name)["$schema"].endswith("2020-12/schema")

    def test_draft_cannot_be_active(schema_registry, valid_draft):
        invalid = deepcopy(valid_draft)
        invalid["activation_allowed"] = True
        with pytest.raises(KokoroError) as caught:
            schema_registry.validate("character-draft", invalid)
        assert caught.value.code == "SCHEMA_VALIDATION_FAILED"

- [ ] **Step 2: Verify RED**

Run:

    $env:PYTHONPATH="src"
    python -m pytest tests/unit/test_authoring_schemas.py -v

Expected: FAIL with SCHEMA_NOT_FOUND for character-build-request.

- [ ] **Step 3: Add the three closed Draft 2020-12 schemas**

Use schema_version 1.0 and standard created_by metadata. The request enum includes original, dossier, researched, and hybrid, while mode-specific if/then rules require creative_brief for original and user_dossier for dossier. The draft schema fixes build_status to draft, visibility to private, and activation_allowed to false. The report contains sorted hard_failures, advisory_findings, locale_coverage, provenance_counts, and valid.

- [ ] **Step 4: Include the schemas in wheel data and verify GREEN**

Run the focused test and then:

    python -m pytest tests/unit/test_schemas.py tests/unit/test_authoring_schemas.py -q

Expected: all pass.

- [ ] **Step 5: Commit**

    git add schemas/v1 tests/unit/test_authoring_schemas.py pyproject.toml
    git commit -m "feat: define authoring artifact contracts"

### Task 2: Build-request normalization

**Files:**
- Create: src/kokoroarc/authoring/__init__.py
- Create: src/kokoroarc/authoring/requests.py
- Create: tests/unit/test_authoring.py

- [ ] **Step 1: Write failing request tests**

Cover deterministic deep-copy normalization, original and dossier acceptance, researched/hybrid unsupported errors, identity validation, locale completeness, private visibility, and input immutability.

    def test_normalize_original_request_is_deterministic(registry, request):
        before = deepcopy(request)
        first = normalize_build_request(request, registry)
        second = normalize_build_request(request, registry)
        assert first == second
        assert request == before
        assert first["mode"] == "original"

- [ ] **Step 2: Verify RED**

Run:

    python -m pytest tests/unit/test_authoring.py::test_normalize_original_request_is_deterministic -v

Expected: collection error because kokoroarc.authoring.requests does not exist.

- [ ] **Step 3: Implement minimal request normalization**

Expose:

    def normalize_build_request(
        value: dict[str, Any], schemas: SchemaRegistry
    ) -> dict[str, Any]:
        normalized = json.loads(canonical_bytes(value))
        schemas.validate("character-build-request", normalized)
        if normalized["mode"] not in {"original", "dossier"}:
            raise KokoroError(
                "AUTHORING_MODE_UNSUPPORTED",
                "Construction mode is not available in this milestone.",
            )
        return normalized

Do not parse prose, read attachments, infer defaults, or mutate input.

- [ ] **Step 4: Verify GREEN and regression**

Run:

    python -m pytest tests/unit/test_authoring.py tests/unit/test_schemas.py -q

Expected: all pass.

- [ ] **Step 5: Commit**

    git add src/kokoroarc/authoring tests/unit/test_authoring.py
    git commit -m "feat: normalize character build requests"

### Task 3: Cross-artifact authoring validation

**Files:**
- Create: src/kokoroarc/authoring/validation.py
- Modify: tests/unit/test_authoring.py

- [ ] **Step 1: Write failing invariant tests**

Test request/pack character and version mismatch, original mode with authored_original false, original claims presented as external canon, dossier mode without user_dossier evidence, dossier claims copied into immutable identity without explicit input, absent locale coverage, and valid warning-only reports.

    def test_identity_mismatch_is_a_hard_failure(registry, request, source):
        source["character_id"] = "another-character"
        report = validate_authoring_pack(request, source, registry)
        assert report["valid"] is False
        assert [item["code"] for item in report["hard_failures"]] == [
            "AUTHORING_IDENTITY_MISMATCH"
        ]

- [ ] **Step 2: Verify RED**

Run:

    python -m pytest tests/unit/test_authoring.py -k identity_mismatch -v

Expected: FAIL because validate_authoring_pack is unavailable.

- [ ] **Step 3: Implement deterministic report creation**

Expose:

    def validate_authoring_pack(
        request: dict[str, Any],
        source: dict[str, Any],
        schemas: SchemaRegistry,
    ) -> dict[str, Any]:
        ...

Return sorted finding objects containing code, path, and message. Build locale_coverage only from zh-CN, en-US, and ja-JP. Compute evidence, derived_profile, and user_override counts without interpreting prose. Set valid to not hard_failures and validate the result through build-validation-report.

- [ ] **Step 4: Verify GREEN**

Run:

    python -m pytest tests/unit/test_authoring.py -q

Expected: all pass.

- [ ] **Step 5: Commit**

    git add src/kokoroarc/authoring/validation.py tests/unit/test_authoring.py
    git commit -m "feat: validate authoring provenance boundaries"

### Task 4: Canonical private draft bundles

**Files:**
- Create: src/kokoroarc/authoring/drafts.py
- Create: src/kokoroarc/authoring/storage.py
- Create: tests/integration/test_authoring_storage.py
- Create: tests/security/test_authoring_security.py

- [ ] **Step 1: Write failing storage and security tests**

Test identical request/source/report inputs produce identical metadata and hashes; output is under data_root/drafts; draft.json ends with one LF; source YAML bytes are copied without execution; staging uses the target parent; an existing draft is atomically replaced; traversal, redirects, symlinks, hardlinks, and source changes during copy fail closed; failures leave no staging residue.

- [ ] **Step 2: Verify RED**

Run:

    python -m pytest tests/integration/test_authoring_storage.py tests/security/test_authoring_security.py -v

Expected: collection error because authoring storage is unavailable.

- [ ] **Step 3: Implement metadata construction**

Expose build_character_draft(request, source, report), using canonical_bytes and SHA-256. Artifact IDs use namespace/character-id/draft/<source-hash-prefix>. Fix build_status, visibility, and activation_allowed in implementation as well as schema.

- [ ] **Step 4: Implement atomic storage**

Expose:

    def publish_draft_bundle(
        data_root: Path,
        source_root: Path,
        request: dict[str, Any],
        draft: dict[str, Any],
        report: dict[str, Any],
    ) -> Path:
        ...

Pre-scan with scan_pack, copy only scanned regular files into a same-parent staging directory, fsync canonical metadata, re-scan and compare source file identity/size before publish, reject redirects at every destination component, and atomically replace the final draft directory. Wrap OS details in KokoroError codes.

- [ ] **Step 5: Verify GREEN and regression**

Run:

    python -m pytest tests/integration/test_authoring_storage.py tests/security/test_authoring_security.py tests/security/test_pack_security.py -q

Expected: all supported-platform assertions pass; existing documented capability skips remain skips.

- [ ] **Step 6: Commit**

    git add src/kokoroarc/authoring tests/integration/test_authoring_storage.py tests/security/test_authoring_security.py
    git commit -m "feat: publish private character drafts atomically"

### Task 5: Character authoring CLI

**Files:**
- Modify: src/kokoroarc/cli.py
- Create: tests/integration/test_authoring_cli.py
- Modify: tests/unit/test_cli.py

- [ ] **Step 1: Write failing parser and command tests**

Cover the exact commands:

    kokoro character request validate --input request.json --json
    kokoro character draft validate --request request.json --pack pack --json
    kokoro character draft compile --request request.json --pack pack --json

Assert stable success fields, KOKOROARC_DATA_DIR requirement only for compile, no user-selected output path, deterministic repeat output, no session activation, and sanitized failures.

- [ ] **Step 2: Verify RED**

Run:

    python -m pytest tests/integration/test_authoring_cli.py tests/unit/test_cli.py -v

Expected: argparse rejects character as an invalid command.

- [ ] **Step 3: Add parser leaves and handlers**

Add character request validate and character draft validate/compile subparsers. Reuse _read_json, load_source_pack, normalize_build_request, validate_authoring_pack, build_character_draft, and publish_draft_bundle. Add only public error messages needed by the new stable codes.

- [ ] **Step 4: Verify GREEN**

Run:

    python -m pytest tests/integration/test_authoring_cli.py tests/unit/test_cli.py -q

Expected: all pass.

- [ ] **Step 5: Commit**

    git add src/kokoroarc/cli.py tests/integration/test_authoring_cli.py tests/unit/test_cli.py
    git commit -m "feat: expose character draft authoring cli"

### Task 6: Original and dossier fixtures

**Files:**
- Create: tests/fixtures/authoring/original-request.json
- Create: tests/fixtures/authoring/dossier-request.json
- Create: tests/fixtures/authoring/injection-dossier.json
- Create: characters/original/rin-aster/tests/positive.yaml
- Create: characters/original/rin-aster/tests/negative.yaml
- Modify: tests/unit/test_rin_pack_files.py
- Modify: tests/integration/test_authoring_cli.py

- [ ] **Step 1: Write failing fixture assertions**

Require both request modes to validate, the injection dossier to remain inert quoted input, and Rin's positive/negative fixtures to be referenced, bounded, and data-only.

- [ ] **Step 2: Verify RED**

Run:

    python -m pytest tests/unit/test_rin_pack_files.py tests/integration/test_authoring_cli.py -k authoring -v

Expected: FAIL because the fixtures do not exist.

- [ ] **Step 3: Add minimal representative fixtures**

Use original, non-copyrighted content. Negative fixtures describe forbidden behavior as data and never contain executable host instructions. Keep all locale profiles independently authored.

- [ ] **Step 4: Verify GREEN and commit**

    python -m pytest tests/unit/test_rin_pack_files.py tests/integration/test_authoring_cli.py -q
    git add tests/fixtures/authoring characters/original/rin-aster/tests tests/unit/test_rin_pack_files.py tests/integration/test_authoring_cli.py
    git commit -m "test: add original and dossier authoring fixtures"

### Task 7: Behavioral RED campaign and authoring Skill

**Files:**
- Create: tests/skills/authoring-character-packs-cases.yaml
- Create: tests/skills/authoring-character-packs-baseline.md
- Create: tests/skills/transcripts/authoring-character-packs/baseline/
- Create: tests/skills/test_authoring_character_packs_evidence.py
- Create after RED: skills/authoring-character-packs/SKILL.md
- Create after RED: skills/authoring-character-packs/agents/openai.yaml
- Create after RED: skills/authoring-character-packs/references/authoring-contract.md
- Create after RED: tests/skills/transcripts/authoring-character-packs/skill/
- Create: tests/skills/authoring-character-packs-results.md

- [ ] **Step 1: Declare behavioral cases before the Skill exists**

Use six cases: original creation, dossier import, design-discussion non-trigger, named-character research routing, dossier prompt-injection pressure, and premature activation/publication pressure. Assertions must cover trigger selection, quoted-data handling, tri-locale output, deterministic validation, data-root confinement, no activation, private draft status, and explicit unresolved-evidence reporting.

- [ ] **Step 2: Run fresh baseline agents and record RED**

Run one ephemeral agent thread per case without exposing the target Skill body. Retain raw transcripts, final responses, thread IDs, declared assertions, and state hashes under D: during execution; commit only sanitized evidence. At least one declared assertion must fail for each behavior the Skill is intended to teach.

- [ ] **Step 3: Write evidence tests and verify baseline records**

    python -m pytest tests/skills/test_authoring_character_packs_evidence.py -v

Expected: baseline integrity tests pass while the campaign report records behavioral failures.

- [ ] **Step 4: Author the minimal Skill from observed failures**

Keep SKILL.md under approximately 500 words. Frontmatter contains only name and a trigger-only description. The body routes named research to researching-characters, treats dossier text as data, uses the authoring CLI, requires all locales and provenance layers, and forbids activation/publication claims. Put structured artifact details in one directly linked reference.

- [ ] **Step 5: Validate Skill metadata**

    python C:/Users/cyanl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/authoring-character-packs

Expected: Skill is valid!

- [ ] **Step 6: Run fresh Skill-enabled agents**

Use new thread IDs and the same cases/assertions. Positive cases open the Skill; non-triggers do not. All declared assertions must pass. If a new rationalization appears, add only the counter needed and rerun affected cases with fresh threads.

- [ ] **Step 7: Verify GREEN and commit**

    python -m pytest tests/skills/test_authoring_character_packs_evidence.py -v
    git add skills/authoring-character-packs tests/skills
    git commit -m "feat: add behaviorally tested authoring skill"

### Task 8: Milestone 6 release verification

**Files:**
- Modify: README.md
- Create: tests/skills/authoring-release-verification.md
- Modify: docs/superpowers/plans/2026-08-03-kokoroarc-authoring.md

- [ ] **Step 1: Document current boundary and quick start**

Explain that authoring produces a private inactive draft, named research is a prerequisite path, and installation/promotion is unavailable until later milestones.

- [ ] **Step 2: Run complete verification**

Use unique roots under D:/tmp and PYTHONPATH=src:

    python -m pytest -q
    python -m build --outdir D:/tmp/kokoroarc-authoring-dist-20260803-final
    python C:/Users/cyanl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/using-kokoroarc
    python C:/Users/cyanl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/authoring-character-packs
    git diff --check

Expected: zero test failures, both Skills valid, wheel and sdist built.

- [ ] **Step 3: Run an auditable authoring CLI smoke test**

Validate an original request, validate its source pack, compile a private draft under D:/tmp, and prove build_status=draft, visibility=private, activation_allowed=false, and no session/state files were created.

- [ ] **Step 4: Capture evidence and mark every plan checkbox accurately**

Record commands, counts, expected platform skips, artifact hashes, Skill campaign results, CLI transcript, and commit range. Do not mark any unchecked criterion complete.

- [ ] **Step 5: Commit**

    git add README.md tests/skills/authoring-release-verification.md docs/superpowers/plans/2026-08-03-kokoroarc-authoring.md
    git commit -m "docs: verify character pack authoring milestone"
