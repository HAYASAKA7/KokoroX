from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any

from jsonschema import Draft202012Validator
import pytest
import yaml


SKILLS_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SKILLS_ROOT.parents[1]
sys.path.insert(0, str(SKILLS_ROOT))

import run_complete_suite_campaign as runner  # noqa: E402


OUTPUT_SCHEMA = SKILLS_ROOT / "complete-suite-output.schema.json"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def _final_response(case_id: str = "example-case") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "outcome": "completed",
        "response": "The requested local operation completed.",
        "claimed_assertions": [
            {
                "id": "report_local_result",
                "status": "satisfied",
                "evidence_paths": ["outputs/result.json"],
            }
        ],
        "created_paths": ["outputs/result.json"],
        "blockers": [],
    }


def _prepared_case(root: Path) -> Path:
    case_root = root / "case"
    workspace = case_root / "workspace"
    raw = case_root / "raw"
    for relative in (
        "runtime/kokoroarc",
        "workspace/inputs",
        "workspace/data",
        "workspace/tmp",
        "workspace/.tools",
        "raw",
    ):
        (case_root / relative).mkdir(parents=True, exist_ok=True)
    (case_root / "runtime" / "kokoroarc" / "__init__.py").write_text(
        "__version__ = 'test'\n",
        encoding="utf-8",
        newline="\n",
    )
    (workspace / "README.md").write_text(
        "# Isolated\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_json(workspace / "case.json", {"id": "example-case"})
    _write_json(workspace / "inputs" / "setup.json", {"input": "fixed"})
    (workspace / ".tools" / "kokoro.cmd").write_bytes(
        b"@echo off\r\npython -m kokoroarc.cli %*\r\n"
    )
    _write_json(case_root / "prepared-layout.json", {"schema_version": "1.0"})
    schema = raw / "complete-suite-output.schema.json"
    schema.write_bytes(OUTPUT_SCHEMA.read_bytes())
    prompt = b"Handle the exact local example case.\n"
    (raw / "prompt.md").write_bytes(prompt)
    pre_run = {
        "schema_version": "1.0",
        "ordinal": 1,
        "variant": "baseline",
        "case_id": "example-case",
        "case_root_identity": runner._directory_identity(case_root),
        "workspace_root_identity": runner._directory_identity(workspace),
        "runtime_root_identity": runner._directory_identity(case_root / "runtime"),
        "raw_root_identity": runner._directory_identity(raw),
        "prompt_sha256": sha256(prompt).hexdigest(),
        "output_schema_sha256": sha256(schema.read_bytes()).hexdigest(),
        "workspace_before": runner.preparation.inventory_tree(workspace),
        "immutable_before": runner._immutable_case_state(case_root),
        "preexisting_outputs": runner.preparation.inventory_tree(
            workspace / "outputs",
            allow_missing=True,
        ),
    }
    _write_json(raw / "pre-run-state.json", pre_run)
    return case_root


def _paths(root: Path, raw_root: Path) -> runner.HarnessPaths:
    campaign = root / "tests" / "skills" / "complete-suite-campaign.yaml"
    cases = root / "tests" / "skills" / "complete-suite-cases.yaml"
    output_schema = root / "tests" / "skills" / "complete-suite-output.schema.json"
    runner_file = root / "tests" / "skills" / "run_complete_suite_campaign.py"
    output_schema.parent.mkdir(parents=True, exist_ok=True)
    output_schema.write_bytes(OUTPUT_SCHEMA.read_bytes())
    runner_file.write_text("# frozen runner\n", encoding="utf-8", newline="\n")
    _write_yaml(
        campaign,
        {
            "schema_version": "1.0",
            "campaign_id": "synthetic-proposed1",
            "status": "draft_not_approved",
            "proposed_approval": {
                "runs": {
                    "baseline": 1,
                    "suite_enabled": 1,
                    "corrective": 0,
                    "total": 2,
                },
                "variants": ["baseline", "suite-enabled"],
                "cases": ["example-case"],
                "evaluator": {
                    "provider": "openai",
                    "client": "codex-cli 0.148.0",
                    "model": "gpt-5.6-terra",
                    "reasoning_effort": "low",
                },
                "isolation": {
                    "ephemeral": True,
                    "sandbox": "workspace-write",
                    "command_review": "automatic --approve-for-me",
                    "ignore_user_config": True,
                    "ignore_rules": True,
                    "task_network": False,
                    "max_concurrency": 4,
                    "raw_root": str(raw_root),
                    "retained_root": (
                        "tests/skills/evidence/complete-suite/approved1"
                    ),
                },
                "reruns_require_fresh_approval": True,
                "immutable_failures": True,
                "disclosed_inputs": ["synthetic"],
                "retained_outputs": ["synthetic"],
                "prohibited": ["retry"],
            },
            "frozen_inputs": {},
            "user_approval": None,
            "execution": {
                "runs_started": 0,
                "runs_completed": 0,
                "raw_root_created": False,
            },
        },
    )
    _write_yaml(
        cases,
        {
            "schema_version": "1.0",
            "variants": ["baseline", "suite-enabled"],
            "cases": [
                {
                    "id": "example-case",
                    "route": "none",
                    "coverage": ["example"],
                    "setup": "A bounded synthetic setup exists for this test.",
                    "prompt": "Perform the bounded local synthetic request now.",
                    "must": ["report_local_result"],
                    "must_not": ["use_network"],
                    "allowed_mutations": ["result_output"],
                    "protected_state": ["input_fixture"],
                }
            ],
        },
    )
    return runner.HarnessPaths(
        repository_root=root,
        campaign_file=campaign,
        cases_file=cases,
        output_schema_file=output_schema,
        runner_file=runner_file,
    )


def _approve_synthetic(
    paths: runner.HarnessPaths,
    raw_root: Path,
) -> tuple[str, tuple[str, ...]]:
    cases_document = yaml.safe_load(paths.cases_file.read_text(encoding="utf-8"))
    template = cases_document["cases"][0]
    cases = [
        {**template, "id": f"case-{index:02d}"}
        for index in range(12)
    ]
    cases_document["cases"] = cases
    _write_yaml(paths.cases_file, cases_document)
    campaign = yaml.safe_load(paths.campaign_file.read_text(encoding="utf-8"))
    case_ids = [case["id"] for case in cases]
    campaign["proposed_approval"]["runs"] = {
        "baseline": 12,
        "suite_enabled": 12,
        "corrective": 0,
        "total": 24,
    }
    campaign["proposed_approval"]["cases"] = case_ids
    required = (
        paths.cases_file.relative_to(paths.repository_root).as_posix(),
        paths.output_schema_file.relative_to(paths.repository_root).as_posix(),
        paths.runner_file.relative_to(paths.repository_root).as_posix(),
    )
    campaign["frozen_inputs"] = {
        "schema_version": "1.0",
        "harness_git": {
            "commit": "1" * 40,
            "tree": "2" * 40,
            "parent": "3" * 40,
        },
        "files": runner.freeze_file_entries(
            paths.repository_root,
            tuple(
                paths.repository_root.joinpath(*relative.split("/"))
                for relative in required
            ),
        ),
        "wheel": {
            "filename": "kokoroarc-0.0.0.dev0-py3-none-any.whl",
            "size": 346_526,
            "sha256": (
                "e5e069cb5a219f0b6c59b4b2a94bbad7507a3add1ede0e544d2d304bfee6c5b4"
            ),
        },
    }
    envelope_hash = runner.approval_envelope_sha256(campaign)
    campaign["status"] = "approved_not_started"
    campaign["user_approval"] = {
        "approval_id": "synthetic-approval-01",
        "approved_at": "2026-08-20T12:00:00Z",
        "response": "approve",
        "approved_envelope_sha256": envelope_hash,
    }
    _write_yaml(paths.campaign_file, campaign)
    return sha256(paths.campaign_file.read_bytes()).hexdigest(), required


def test_approval_bound_complete_suite_inputs_are_lf_pinned() -> None:
    paths = (
        "tests/skills/complete-suite-cases.yaml",
        "tests/skills/complete-suite-campaign.yaml",
        "tests/skills/complete-suite-output.schema.json",
        "tests/skills/complete_suite_preparation.py",
        "tests/skills/run_complete_suite_campaign.py",
        "tests/skills/complete_suite_adjudication.py",
        "tests/skills/complete_suite_sanitization.py",
        "tests/skills/import_complete_suite_campaign.py",
        "tests/skills/researching_characters_sanitization.py",
        "tests/skills/test_complete_suite_evidence.py",
        "tests/skills/test_complete_suite_release_evidence.py",
        "docs/superpowers/plans/2026-08-20-kokoroarc-complete-suite-closure.md",
    )
    result = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", *paths],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    observed: dict[str, dict[str, str]] = {path: {} for path in paths}
    for line in result.stdout.splitlines():
        path, attribute, value = line.rsplit(": ", 2)
        observed[path][attribute] = value

    assert observed == {
        path: {"text": "set", "eol": "lf"} for path in paths
    }


def test_complete_suite_output_schema_is_closed_bounded_and_relative() -> None:
    schema = json.loads(OUTPUT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    assert list(validator.iter_errors(_final_response())) == []
    for mutation in (
        {**_final_response(), "extra": True},
        {**_final_response(), "case_id": "../escape"},
        {**_final_response(), "created_paths": [r"C:\outside.txt"]},
        {**_final_response(), "created_paths": ["../outside.txt"]},
        {**_final_response(), "created_paths": ["outputs/trailing "]},
        {**_final_response(), "created_paths": ["outputs/\u0000hidden"]},
        {**_final_response(), "response": "x" * 8001},
    ):
        assert list(validator.iter_errors(mutation))


def test_draft_campaign_stops_before_root_creation_or_process_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash = sha256(paths.campaign_file.read_bytes()).hexdigest()
    called = False

    def forbidden_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        nonlocal called
        called = True
        raise AssertionError("draft campaign attempted to spawn")

    monkeypatch.setattr(runner.subprocess, "Popen", forbidden_popen)

    with pytest.raises(RuntimeError, match="approved-not-started"):
        runner.execute_campaign(
            paths,
            approved_campaign_sha256=campaign_hash,
        )

    assert called is False
    assert not raw_root.exists()


def test_approved_campaign_binds_exact_envelope_files_wheel_and_run_plan(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash, required = _approve_synthetic(paths, raw_root)

    approved = runner.validate_approved_campaign(
        paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git={
            "commit": "1" * 40,
            "tree": "2" * 40,
            "parent": "3" * 40,
        },
    )

    assert approved.raw_root == raw_root
    assert len(approved.plan) == 24
    assert approved.campaign_sha256 == campaign_hash
    assert approved.wheel["sha256"].startswith("e5e069")
    assert not raw_root.exists()

    paths.output_schema_file.write_text("{}\n", encoding="utf-8", newline="\n")
    with pytest.raises(RuntimeError, match="frozen input mismatch"):
        runner.validate_approved_campaign(
            paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git={
                "commit": "1" * 40,
                "tree": "2" * 40,
                "parent": "3" * 40,
            },
        )


def test_approved_campaign_rejects_policy_or_user_envelope_drift(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    _campaign_hash, required = _approve_synthetic(paths, raw_root)
    campaign = yaml.safe_load(paths.campaign_file.read_text(encoding="utf-8"))
    campaign["proposed_approval"]["evaluator"]["model"] = "other-model"
    _write_yaml(paths.campaign_file, campaign)
    changed_hash = sha256(paths.campaign_file.read_bytes()).hexdigest()

    with pytest.raises(RuntimeError, match="approval envelope"):
        runner.validate_approved_campaign(
            paths,
            approved_campaign_sha256=changed_hash,
            required_frozen_paths=required,
            observed_git={
                "commit": "1" * 40,
                "tree": "2" * 40,
                "parent": "3" * 40,
            },
        )


def test_frozen_file_verification_is_exact_closed_and_link_safe(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    first = root / "one.txt"
    second = root / "nested" / "two.txt"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"one\n")
    second.write_bytes(b"two\n")
    frozen = runner.freeze_file_entries(root, (first, second))

    runner.verify_frozen_files(
        root,
        frozen,
        required_paths=("one.txt", "nested/two.txt"),
    )
    second.write_bytes(b"changed\n")
    with pytest.raises(RuntimeError, match="frozen input mismatch"):
        runner.verify_frozen_files(
            root,
            frozen,
            required_paths=("one.txt", "nested/two.txt"),
        )
    with pytest.raises(RuntimeError, match="frozen path"):
        runner.verify_frozen_files(
            root,
            {"../outside.txt": frozen["one.txt"]},
            required_paths=("../outside.txt",),
        )


def test_real_approval_bound_path_set_is_closed_and_complete() -> None:
    paths = runner.approval_bound_paths()

    assert len(paths) == 141
    assert len(set(paths)) == len(paths)
    assert "tests/skills/complete-suite-campaign.yaml" not in paths
    plan_path = (
        "docs/superpowers/plans/"
        "2026-08-20-kokoroarc-complete-suite-closure.md"
    )
    assert plan_path not in paths
    for required in (
        "README.md",
        "pyproject.toml",
        "src/kokoroarc/cli.py",
        "schemas/v1/common.schema.json",
        "skills/using-kokoroarc/SKILL.md",
        "skills/authoring-character-packs/SKILL.md",
        "skills/researching-characters/SKILL.md",
        "skills/testing-character-packs/SKILL.md",
        "characters/original/rin-aster/character.yaml",
        "tests/fixtures/authoring/original-request.json",
        "tests/skills/run_complete_suite_campaign.py",
        "tests/skills/import_complete_suite_campaign.py",
        "tests/skills/complete_suite_adjudication.py",
    ):
        assert required in paths


def test_run_plan_is_exactly_24_unique_one_shot_sessions() -> None:
    case_ids = [f"case-{index:02d}" for index in range(12)]
    campaign = {
        "proposed_approval": {
            "runs": {
                "baseline": 12,
                "suite_enabled": 12,
                "corrective": 0,
                "total": 24,
            },
            "variants": ["baseline", "suite-enabled"],
            "cases": case_ids,
            "isolation": {"max_concurrency": 4},
            "reruns_require_fresh_approval": True,
            "immutable_failures": True,
        }
    }
    cases = [{"id": case_id} for case_id in case_ids]

    plan = runner.build_run_plan(campaign, cases)

    assert len(plan) == 24
    assert len({(item.variant, item.case_id) for item in plan}) == 24
    assert [item.ordinal for item in plan] == list(range(1, 25))
    assert [item.variant for item in plan[:12]] == ["baseline"] * 12
    assert [item.variant for item in plan[12:]] == ["suite-enabled"] * 12
    changed = json.loads(json.dumps(campaign))
    changed["proposed_approval"]["runs"]["total"] = 23
    with pytest.raises(RuntimeError, match="24-run"):
        runner.build_run_plan(changed, cases)


def test_run_plan_uses_at_most_four_workers_without_retry() -> None:
    plan = tuple(
        runner.RunSpec(
            ordinal=index + 1,
            variant="baseline" if index < 12 else "suite-enabled",
            case_id=f"case-{index % 12:02d}",
        )
        for index in range(24)
    )
    lock = threading.Lock()
    active = 0
    maximum = 0
    calls: dict[tuple[str, str], int] = {}

    def worker(item: runner.RunSpec) -> dict[str, object]:
        nonlocal active, maximum
        key = (item.variant, item.case_id)
        with lock:
            calls[key] = calls.get(key, 0) + 1
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {
            "variant": item.variant,
            "case_id": item.case_id,
            "thread_id": f"thread-{item.ordinal:02d}",
        }

    results = runner.execute_run_plan(plan, worker, max_workers=4)

    assert len(results) == 24
    assert maximum <= 4
    assert set(calls.values()) == {1}
    assert [(item["variant"], item["case_id"]) for item in results] == [
        (item.variant, item.case_id) for item in plan
    ]


def test_run_plan_rejects_duplicate_external_session_ids_after_all_attempts() -> None:
    plan = tuple(
        runner.RunSpec(
            ordinal=index + 1,
            variant="baseline" if index < 12 else "suite-enabled",
            case_id=f"case-{index % 12:02d}",
        )
        for index in range(24)
    )
    calls = 0

    def worker(item: runner.RunSpec) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "variant": item.variant,
            "case_id": item.case_id,
            "thread_id": "duplicate-thread",
        }

    with pytest.raises(RuntimeError, match="session identifiers"):
        runner.execute_run_plan(plan, worker, max_workers=4)

    assert calls == 24


def _prepare_synthetic_approved_campaign(
    approved: runner.ApprovedCampaign,
    _paths: runner.HarnessPaths,
    *,
    python_executable: str,
    base_environment: dict[str, str] | None = None,
) -> Path:
    assert python_executable
    assert base_environment is not None
    raw_root = approved.raw_root
    raw_root.mkdir()
    _write_json(
        raw_root / "approval.json",
        {
            "schema_version": "1.0",
            "campaign_sha256": approved.campaign_sha256,
            "approval_envelope_sha256": approved.envelope_sha256,
        },
    )
    for item in approved.plan:
        (raw_root / "runs" / item.variant / item.case_id / "raw").mkdir(
            parents=True
        )
    _write_json(
        raw_root / "prepared-campaign.json",
        {
            "schema_version": "1.0",
            "campaign_sha256": approved.campaign_sha256,
            "approval_envelope_sha256": approved.envelope_sha256,
            "run_count": len(approved.plan),
            "runs": [
                {
                    "ordinal": item.ordinal,
                    "variant": item.variant,
                    "case_id": item.case_id,
                }
                for item in approved.plan
            ],
        },
    )
    (raw_root / "PREPARED").write_bytes(b"prepared\n")
    return raw_root


def _synthetic_run_status(
    case_root: Path,
    item: runner.RunSpec,
) -> dict[str, object]:
    raw = case_root / "raw"
    _write_json(
        raw / "launch-started.json",
        {
            "schema_version": "1.0",
            "ordinal": item.ordinal,
            "variant": item.variant,
            "case_id": item.case_id,
            "retry_allowed": False,
        },
    )
    status = {
        "schema_version": "1.0",
        "ordinal": item.ordinal,
        "variant": item.variant,
        "case_id": item.case_id,
        "thread_id": f"thread-{item.ordinal:02d}",
        "failure_codes": [],
        "lifecycle_passed": True,
    }
    _write_json(raw / "run-status.json", status)
    return status


def test_approved_campaign_executes_once_and_seals_exact_run_ledger(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash, required = _approve_synthetic(paths, raw_root)
    calls: dict[tuple[str, str], int] = {}

    def run_factory(
        case_root: Path,
        item: runner.RunSpec,
        **_kwargs: object,
    ) -> dict[str, object]:
        key = (item.variant, item.case_id)
        calls[key] = calls.get(key, 0) + 1
        return _synthetic_run_status(case_root, item)

    completed = runner.execute_campaign(
        paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git={
            "commit": "1" * 40,
            "tree": "2" * 40,
            "parent": "3" * 40,
        },
        codex_executable=Path(sys.executable),
        python_executable=Path(sys.executable),
        host_environment={"PATH": "synthetic"},
        prepare_factory=_prepare_synthetic_approved_campaign,
        run_factory=run_factory,
        version_factory=lambda _path, _environment: "codex-cli 0.148.0",
    )

    assert completed == raw_root
    assert len(calls) == 24
    assert set(calls.values()) == {1}
    ledger = json.loads(
        (raw_root / "campaign-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["runs_authorized"] == 24
    assert ledger["runs_started"] == 24
    assert ledger["runs_completed"] == 24
    assert ledger["deviations"] == []
    assert ledger["sealed"] is True
    assert len(ledger["runs"]) == 24
    completion = json.loads(
        (raw_root / "campaign-completion.json").read_text(encoding="utf-8")
    )
    assert completion["campaign_ledger_sha256"] == sha256(
        (raw_root / "campaign-ledger.json").read_bytes()
    ).hexdigest()
    assert (raw_root / "COMPLETED").read_bytes() == (
        completion["campaign_ledger_sha256"].encode("ascii") + b"\n"
    )

    with pytest.raises(RuntimeError, match="not new"):
        runner.execute_campaign(
            paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git={
                "commit": "1" * 40,
                "tree": "2" * 40,
                "parent": "3" * 40,
            },
            codex_executable=Path(sys.executable),
            python_executable=Path(sys.executable),
            host_environment={"PATH": "synthetic"},
            prepare_factory=_prepare_synthetic_approved_campaign,
            run_factory=run_factory,
            version_factory=lambda _path, _environment: "codex-cli 0.148.0",
        )
    assert set(calls.values()) == {1}


def test_approved_campaign_seals_worker_failure_without_retry(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash, required = _approve_synthetic(paths, raw_root)
    calls: dict[tuple[str, str], int] = {}

    def run_factory(
        case_root: Path,
        item: runner.RunSpec,
        **_kwargs: object,
    ) -> dict[str, object]:
        key = (item.variant, item.case_id)
        calls[key] = calls.get(key, 0) + 1
        if item.ordinal == 4:
            _write_json(
                case_root / "raw" / "launch-started.json",
                {
                    "schema_version": "1.0",
                    "ordinal": item.ordinal,
                    "variant": item.variant,
                    "case_id": item.case_id,
                    "retry_allowed": False,
                },
            )
            raise RuntimeError("synthetic worker failure")
        return _synthetic_run_status(case_root, item)

    with pytest.raises(RuntimeError, match="deviations"):
        runner.execute_campaign(
            paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git={
                "commit": "1" * 40,
                "tree": "2" * 40,
                "parent": "3" * 40,
            },
            codex_executable=Path(sys.executable),
            python_executable=Path(sys.executable),
            host_environment={"PATH": "synthetic"},
            prepare_factory=_prepare_synthetic_approved_campaign,
            run_factory=run_factory,
            version_factory=lambda _path, _environment: "codex-cli 0.148.0",
        )

    assert len(calls) == 24
    assert set(calls.values()) == {1}
    ledger = json.loads(
        (raw_root / "campaign-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["runs_started"] == 24
    assert ledger["runs_completed"] == 23
    assert ledger["sealed"] is True
    assert any(
        item["ordinal"] == 4 and item["code"] == "RUN_STATUS_MISSING"
        for item in ledger["deviations"]
    )
    assert (raw_root / "COMPLETED").is_file()


def test_approved_campaign_seal_rejects_inconsistent_lifecycle_status(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash, required = _approve_synthetic(paths, raw_root)

    def run_factory(
        case_root: Path,
        item: runner.RunSpec,
        **_kwargs: object,
    ) -> dict[str, object]:
        status = _synthetic_run_status(case_root, item)
        if item.ordinal == 1:
            status["lifecycle_passed"] = False
            _write_json(case_root / "raw" / "run-status.json", status)
        return status

    with pytest.raises(RuntimeError, match="sealed with deviations"):
        runner.execute_campaign(
            paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git={
                "commit": "1" * 40,
                "tree": "2" * 40,
                "parent": "3" * 40,
            },
            codex_executable=Path(sys.executable),
            python_executable=Path(sys.executable),
            host_environment={"PATH": "synthetic"},
            prepare_factory=_prepare_synthetic_approved_campaign,
            run_factory=run_factory,
            version_factory=lambda _path, _environment: "codex-cli 0.148.0",
        )

    ledger = json.loads(
        (raw_root / "campaign-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["runs"][0]["run_status"] is None
    assert any(
        deviation["ordinal"] == 1
        and deviation["code"] == "RUN_STATUS_INVALID"
        for deviation in ledger["deviations"]
    )


def test_approved_campaign_rejects_client_version_before_root_creation(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash, required = _approve_synthetic(paths, raw_root)

    with pytest.raises(RuntimeError, match="version does not match"):
        runner.execute_campaign(
            paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git={
                "commit": "1" * 40,
                "tree": "2" * 40,
                "parent": "3" * 40,
            },
            codex_executable=Path(sys.executable),
            python_executable=Path(sys.executable),
            host_environment={"PATH": "synthetic"},
            prepare_factory=_prepare_synthetic_approved_campaign,
            run_factory=lambda *_args, **_kwargs: {},
            version_factory=lambda _path, _environment: "codex-cli 0.149.0",
        )

    assert not raw_root.exists()


def test_codex_version_accepts_successful_stdout_with_host_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = subprocess.CompletedProcess(
        args=["codex", "--version"],
        returncode=0,
        stdout="codex-cli 0.148.0\n",
        stderr="WARNING: stale host temp alias could not be removed\n",
    )
    observed: dict[str, object] = {}

    def run_factory(*_args: object, **kwargs: object) -> object:
        observed.update(kwargs)
        return completed

    monkeypatch.setattr(
        runner.subprocess,
        "run",
        run_factory,
    )

    assert runner._codex_version(Path(sys.executable), {}) == "codex-cli 0.148.0"
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "replace"


def test_sealed_campaign_imports_once_and_replays_every_run(
    tmp_path: Path,
) -> None:
    from import_complete_suite_campaign import import_campaign

    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash, required = _approve_synthetic(paths, raw_root)

    runner.execute_campaign(
        paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git={
            "commit": "1" * 40,
            "tree": "2" * 40,
            "parent": "3" * 40,
        },
        codex_executable=Path(sys.executable),
        python_executable=Path(sys.executable),
        host_environment={"PATH": "synthetic"},
        prepare_factory=_prepare_synthetic_approved_campaign,
        run_factory=lambda case_root, item, **_kwargs: _synthetic_run_status(
            case_root,
            item,
        ),
        version_factory=lambda _path, _environment: "codex-cli 0.148.0",
    )
    retained_calls: list[tuple[str, str]] = []
    replayed: list[tuple[str, str]] = []

    def retain_factory(
        _case_root: Path,
        retained_run: Path,
        item: runner.RunSpec,
    ) -> dict[str, object]:
        retained_calls.append((item.variant, item.case_id))
        (retained_run / "evidence.txt").write_text(
            f"{item.variant}/{item.case_id}\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            "schema_version": "1.0",
            "ordinal": item.ordinal,
            "variant": item.variant,
            "case_id": item.case_id,
            "evaluable": True,
        }

    def replay_factory(
        _case_root: Path,
        _retained_run: Path,
        ledger: dict[str, object],
    ) -> None:
        replayed.append((str(ledger["variant"]), str(ledger["case_id"])))

    retained_root = import_campaign(
        raw_root,
        paths=paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git={
            "commit": "1" * 40,
            "tree": "2" * 40,
            "parent": "3" * 40,
        },
        retain_factory=retain_factory,
        replay_factory=replay_factory,
    )

    expected_root = (
        paths.repository_root
        / "tests"
        / "skills"
        / "evidence"
        / "complete-suite"
        / "approved1"
    )
    assert retained_root == expected_root
    assert len(retained_calls) == 24
    assert replayed == retained_calls
    import_ledger = json.loads(
        (retained_root / "import-ledger.json").read_text(encoding="utf-8")
    )
    assert import_ledger["run_count"] == 24
    assert len(import_ledger["runs"]) == 24
    assert import_ledger["raw_campaign_ledger_sha256"] == sha256(
        (raw_root / "campaign-ledger.json").read_bytes()
    ).hexdigest()

    with pytest.raises(RuntimeError, match="already exists"):
        import_campaign(
            raw_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git={
                "commit": "1" * 40,
                "tree": "2" * 40,
                "parent": "3" * 40,
            },
            retain_factory=retain_factory,
            replay_factory=replay_factory,
        )
    assert len(retained_calls) == 24


def test_campaign_import_rejects_sealed_ledger_drift(
    tmp_path: Path,
) -> None:
    from import_complete_suite_campaign import import_campaign

    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash, required = _approve_synthetic(paths, raw_root)
    runner.execute_campaign(
        paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git={
            "commit": "1" * 40,
            "tree": "2" * 40,
            "parent": "3" * 40,
        },
        codex_executable=Path(sys.executable),
        python_executable=Path(sys.executable),
        host_environment={"PATH": "synthetic"},
        prepare_factory=_prepare_synthetic_approved_campaign,
        run_factory=lambda case_root, item, **_kwargs: _synthetic_run_status(
            case_root,
            item,
        ),
        version_factory=lambda _path, _environment: "codex-cli 0.148.0",
    )
    ledger_path = raw_root / "campaign-ledger.json"
    ledger_path.write_bytes(ledger_path.read_bytes() + b" ")

    with pytest.raises(RuntimeError, match="sealed campaign"):
        import_campaign(
            raw_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git={
                "commit": "1" * 40,
                "tree": "2" * 40,
                "parent": "3" * 40,
            },
        )


def test_campaign_import_rejects_self_consistent_missing_status_forgery(
    tmp_path: Path,
) -> None:
    from import_complete_suite_campaign import import_campaign

    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash, required = _approve_synthetic(paths, raw_root)
    observed_git = {
        "commit": "1" * 40,
        "tree": "2" * 40,
        "parent": "3" * 40,
    }
    runner.execute_campaign(
        paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git=observed_git,
        codex_executable=Path(sys.executable),
        python_executable=Path(sys.executable),
        host_environment={"PATH": "synthetic"},
        prepare_factory=_prepare_synthetic_approved_campaign,
        run_factory=lambda case_root, item, **_kwargs: _synthetic_run_status(
            case_root,
            item,
        ),
        version_factory=lambda _path, _environment: "codex-cli 0.148.0",
    )
    ledger_path = raw_root / "campaign-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["runs"][0]["run_status"] = None
    _write_json(ledger_path, ledger)
    ledger_hash = sha256(ledger_path.read_bytes()).hexdigest()
    completion_path = raw_root / "campaign-completion.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["campaign_ledger_sha256"] = ledger_hash
    _write_json(completion_path, completion)
    (raw_root / "COMPLETED").write_bytes(ledger_hash.encode("ascii") + b"\n")

    def retain_factory(
        _case_root: Path,
        retained_run: Path,
        item: runner.RunSpec,
    ) -> dict[str, object]:
        (retained_run / "evidence.txt").write_text(
            f"{item.variant}/{item.case_id}\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            "schema_version": "1.0",
            "ordinal": item.ordinal,
            "variant": item.variant,
            "case_id": item.case_id,
            "evaluable": True,
        }

    with pytest.raises(RuntimeError, match="run status changed"):
        import_campaign(
            raw_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            retain_factory=retain_factory,
            replay_factory=lambda *_args: None,
        )


def _import_synthetic_campaign(
    tmp_path: Path,
) -> tuple[Path, Path, runner.HarnessPaths, str, tuple[str, ...]]:
    from import_complete_suite_campaign import import_campaign

    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash, required = _approve_synthetic(paths, raw_root)
    observed_git = {
        "commit": "1" * 40,
        "tree": "2" * 40,
        "parent": "3" * 40,
    }
    runner.execute_campaign(
        paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git=observed_git,
        codex_executable=Path(sys.executable),
        python_executable=Path(sys.executable),
        host_environment={"PATH": "synthetic"},
        prepare_factory=_prepare_synthetic_approved_campaign,
        run_factory=lambda case_root, item, **_kwargs: _synthetic_run_status(
            case_root,
            item,
        ),
        version_factory=lambda _path, _environment: "codex-cli 0.148.0",
    )

    def retain_factory(
        _case_root: Path,
        retained_run: Path,
        item: runner.RunSpec,
    ) -> dict[str, object]:
        (retained_run / "evidence.txt").write_text(
            f"{item.variant}/{item.case_id}\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            "schema_version": "1.0",
            "ordinal": item.ordinal,
            "variant": item.variant,
            "case_id": item.case_id,
            "evaluable": True,
        }

    retained_root = import_campaign(
        raw_root,
        paths=paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git=observed_git,
        retain_factory=retain_factory,
        replay_factory=lambda *_args: None,
    )
    return raw_root, retained_root, paths, campaign_hash, required


def test_sealed_import_adjudicates_all_runs_once_and_writes_bound_summaries(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_campaign

    raw_root, retained_root, paths, campaign_hash, required = (
        _import_synthetic_campaign(tmp_path)
    )
    replayed: list[tuple[str, str]] = []
    adjudicated: list[tuple[str, str]] = []

    def replay_factory(
        _case_root: Path,
        _retained_run: Path,
        ledger: dict[str, object],
    ) -> None:
        replayed.append((str(ledger["variant"]), str(ledger["case_id"])))

    def adjudicate_factory(
        case: dict[str, object],
        _case_root: Path,
        _retained_run: Path,
        ledger: dict[str, object],
    ) -> dict[str, object]:
        variant = str(ledger["variant"])
        case_id = str(case["id"])
        adjudicated.append((variant, case_id))
        passed = variant == "suite-enabled" or case_id in {
            "case-00",
            "case-01",
            "case-02",
        }
        failures = [] if passed else ["ASSERTION_FAILED"]
        return {
            "schema_version": "1.0",
            "variant": variant,
            "case_id": case_id,
            "evidence_integrity": {
                "passed": passed,
                "failure_codes": failures,
                "command_count": 0,
                "file_change_count": 0,
            },
            "assertions": [],
            "failure_codes": failures,
            "passed": passed,
        }

    results_root = adjudicate_campaign(
        raw_root,
        retained_root,
        paths=paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git={
            "commit": "1" * 40,
            "tree": "2" * 40,
            "parent": "3" * 40,
        },
        replay_factory=replay_factory,
        adjudicate_factory=adjudicate_factory,
    )

    assert results_root == retained_root / "results"
    assert len(replayed) == 24
    assert adjudicated == replayed
    baseline = json.loads(
        (results_root / "baseline-summary.json").read_text(encoding="utf-8")
    )
    enabled = json.loads(
        (results_root / "suite-enabled-summary.json").read_text(
            encoding="utf-8"
        )
    )
    delta = json.loads(
        (results_root / "baseline-versus-suite-delta.json").read_text(
            encoding="utf-8"
        )
    )
    campaign = json.loads(
        (results_root / "campaign-summary.json").read_text(encoding="utf-8")
    )
    ledger = json.loads(
        (results_root / "adjudication-ledger.json").read_text(encoding="utf-8")
    )
    assert (baseline["passed"], baseline["failed"]) == (3, 9)
    assert baseline["all_cases_passed"] is False
    assert (enabled["passed"], enabled["failed"]) == (12, 0)
    assert enabled["all_cases_passed"] is True
    assert delta["counts"] == {
        "improved": 9,
        "regressed": 0,
        "unchanged_fail": 0,
        "unchanged_pass": 3,
    }
    assert campaign["baseline_all_cases_passed"] is False
    assert campaign["suite_enabled_all_cases_passed"] is True
    assert campaign["suite_closure_passed"] is True
    assert ledger["run_count"] == 24
    assert len(ledger["results"]) == 24
    assert len(ledger["summaries"]) == 4
    for record in ledger["results"] + ledger["summaries"]:
        artifact = results_root.joinpath(*record["path"].split("/"))
        assert record["sha256"] == sha256(artifact.read_bytes()).hexdigest()

    with pytest.raises(RuntimeError, match="already exists"):
        adjudicate_campaign(
            raw_root,
            retained_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git={
                "commit": "1" * 40,
                "tree": "2" * 40,
                "parent": "3" * 40,
            },
            replay_factory=replay_factory,
            adjudicate_factory=adjudicate_factory,
        )
    assert len(adjudicated) == 24


def test_campaign_adjudication_keeps_failed_suite_case_failed(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_campaign

    raw_root, retained_root, paths, campaign_hash, required = (
        _import_synthetic_campaign(tmp_path)
    )

    def adjudicate_factory(
        case: dict[str, object],
        _case_root: Path,
        _retained_run: Path,
        ledger: dict[str, object],
    ) -> dict[str, object]:
        variant = str(ledger["variant"])
        case_id = str(case["id"])
        passed = not (variant == "suite-enabled" and case_id == "case-11")
        failures = [] if passed else ["ASSERTION_FAILED"]
        return {
            "schema_version": "1.0",
            "variant": variant,
            "case_id": case_id,
            "evidence_integrity": {
                "passed": passed,
                "failure_codes": failures,
                "command_count": 0,
                "file_change_count": 0,
            },
            "assertions": [],
            "failure_codes": failures,
            "passed": passed,
        }

    results_root = adjudicate_campaign(
        raw_root,
        retained_root,
        paths=paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git={
            "commit": "1" * 40,
            "tree": "2" * 40,
            "parent": "3" * 40,
        },
        replay_factory=lambda *_args: None,
        adjudicate_factory=adjudicate_factory,
    )
    campaign = json.loads(
        (results_root / "campaign-summary.json").read_text(encoding="utf-8")
    )
    enabled = json.loads(
        (results_root / "suite-enabled-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert campaign["suite_closure_passed"] is False
    assert campaign["suite_enabled_all_cases_passed"] is False
    assert (enabled["passed"], enabled["failed"]) == (11, 1)
    failed = json.loads(
        (
            results_root
            / "suite-enabled"
            / "case-11"
            / "result.json"
        ).read_text(encoding="utf-8")
    )
    assert failed["passed"] is False


def test_campaign_adjudication_rejects_unledgered_retained_campaign_file(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import adjudicate_campaign

    raw_root, retained_root, paths, campaign_hash, required = (
        _import_synthetic_campaign(tmp_path)
    )
    (retained_root / "campaign" / "unledgered.txt").write_text(
        "not approved\n",
        encoding="utf-8",
        newline="\n",
    )
    adjudicated = 0

    def adjudicate_factory(*_args: object) -> dict[str, object]:
        nonlocal adjudicated
        adjudicated += 1
        return {}

    with pytest.raises(RuntimeError, match="layout is invalid"):
        adjudicate_campaign(
            raw_root,
            retained_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git={
                "commit": "1" * 40,
                "tree": "2" * 40,
                "parent": "3" * 40,
            },
            replay_factory=lambda *_args: None,
            adjudicate_factory=adjudicate_factory,
        )
    assert adjudicated == 0
    assert not (retained_root / "results").exists()


def test_campaign_adjudication_replay_rejects_any_result_drift(
    tmp_path: Path,
) -> None:
    from complete_suite_adjudication import (
        adjudicate_campaign,
        replay_campaign_adjudication,
    )

    raw_root, retained_root, paths, campaign_hash, required = (
        _import_synthetic_campaign(tmp_path)
    )

    def adjudicate_factory(
        case: dict[str, object],
        _case_root: Path,
        _retained_run: Path,
        ledger: dict[str, object],
    ) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "variant": ledger["variant"],
            "case_id": case["id"],
            "evidence_integrity": {
                "passed": True,
                "failure_codes": [],
                "command_count": 0,
                "file_change_count": 0,
            },
            "assertions": [],
            "failure_codes": [],
            "passed": True,
        }

    arguments = {
        "paths": paths,
        "approved_campaign_sha256": campaign_hash,
        "required_frozen_paths": required,
        "observed_git": {
            "commit": "1" * 40,
            "tree": "2" * 40,
            "parent": "3" * 40,
        },
        "replay_factory": lambda *_args: None,
        "adjudicate_factory": adjudicate_factory,
    }
    results_root = adjudicate_campaign(
        raw_root,
        retained_root,
        **arguments,
    )
    replayed = replay_campaign_adjudication(
        raw_root,
        retained_root,
        **arguments,
    )
    assert replayed["suite_closure_passed"] is True

    result_path = results_root / "baseline" / "case-00" / "result.json"
    result_path.write_bytes(result_path.read_bytes() + b" ")
    with pytest.raises(RuntimeError, match="result changed"):
        replay_campaign_adjudication(
            raw_root,
            retained_root,
            **arguments,
        )


def test_post_import_git_guard_allows_only_the_approved_retained_root(
    tmp_path: Path,
) -> None:
    from import_complete_suite_campaign import _require_confined_worktree

    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@kokoroarc.invalid"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "KokoroArc Tests"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("frozen\n", encoding="utf-8", newline="\n")
    subprocess.run(
        ["git", "add", "tracked.txt"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test fixture"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    retained_root = (
        repository
        / "tests"
        / "skills"
        / "evidence"
        / "complete-suite"
        / "approved1"
    )
    retained_root.mkdir(parents=True)
    (retained_root / "import-ledger.json").write_text(
        "{}\n",
        encoding="utf-8",
        newline="\n",
    )

    _require_confined_worktree(repository, retained_root)

    tracked.write_text("changed\n", encoding="utf-8", newline="\n")
    with pytest.raises(RuntimeError, match="outside retained campaign root"):
        _require_confined_worktree(repository, retained_root)


def test_real_approved_preparation_builds_once_and_creates_24_fresh_cases(
    tmp_path: Path,
) -> None:
    campaign = yaml.safe_load(
        (SKILLS_ROOT / "complete-suite-campaign.yaml").read_text(encoding="utf-8")
    )
    cases_document = yaml.safe_load(
        (SKILLS_ROOT / "complete-suite-cases.yaml").read_text(encoding="utf-8")
    )
    cases = tuple(cases_document["cases"])
    plan = runner.build_run_plan(campaign, cases)
    raw_root = tmp_path / "approved-raw"
    approved = runner.ApprovedCampaign(
        campaign=campaign,
        cases=cases,
        plan=plan,
        raw_root=raw_root,
        campaign_sha256="1" * 64,
        envelope_sha256="2" * 64,
        wheel={
            "filename": "kokoroarc-0.0.0.dev0-py3-none-any.whl",
            "size": 346_526,
            "sha256": (
                "e5e069cb5a219f0b6c59b4b2a94bbad7507a3add1ede0e544d2d304bfee6c5b4"
            ),
        },
    )

    prepared = runner.prepare_approved_campaign(
        approved,
        runner.default_paths(),
        python_executable=sys.executable,
    )

    assert prepared == raw_root
    manifest = json.loads(
        (raw_root / "prepared-campaign.json").read_text(encoding="utf-8")
    )
    assert manifest["run_count"] == 24
    assert manifest["distribution"]["wheel"] == approved.wheel
    assert len(manifest["runs"]) == 24
    assert (raw_root / "PREPARED").read_bytes() == b"prepared\n"
    baseline = raw_root / "runs" / "baseline" / "publication-pressure"
    enabled = raw_root / "runs" / "suite-enabled" / "publication-pressure"
    assert not (baseline / "workspace" / ".agents" / "skills").exists()
    assert {
        path.name
        for path in (enabled / "workspace" / ".agents" / "skills").iterdir()
    } == {
        "using-kokoroarc",
        "authoring-character-packs",
        "researching-characters",
        "testing-character-packs",
    }
    assert (baseline / "raw" / "prompt.md").read_bytes() == (
        enabled / "raw" / "prompt.md"
    ).read_bytes()
    assert (baseline / "workspace" / ".tools" / "kokoro.cmd").is_file()
    assert not (baseline / "src").exists()
    assert not tuple(raw_root.rglob("session.jsonl"))
    assert not tuple(raw_root.rglob("run-status.json"))
    with pytest.raises(RuntimeError, match="not new"):
        runner.prepare_approved_campaign(
            approved,
            runner.default_paths(),
            python_executable=sys.executable,
        )


def test_codex_argv_and_shell_environment_are_literal_and_fail_closed(
    tmp_path: Path,
) -> None:
    case_root = tmp_path / "case"
    for relative in ("runtime", "workspace", "workspace/tmp", "raw"):
        (case_root / relative).mkdir(parents=True, exist_ok=True)
    schema = case_root / "raw" / "complete-suite-output.schema.json"
    schema.write_bytes(OUTPUT_SCHEMA.read_bytes())
    codex = Path(r"D:\tools\codex.exe")
    python = Path(r"C:\Python314\python.exe")
    spec = runner.build_launch_spec(
        case_root,
        schema,
        codex_executable=codex,
        python_executable=python,
        host_environment={
            "PATH": "ignored-user-path",
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "SYSTEMROOT": r"C:\Windows",
            "WINDIR": r"C:\Windows",
            "COMSPEC": r"C:\Windows\System32\cmd.exe",
            "USERPROFILE": r"C:\Users\private",
            "HOME": "/private",
            "SECRET_TOKEN": "must-not-pass",
        },
    )

    command = list(spec.command)
    assert command[:3] == [str(codex), "exec", "--ephemeral"]
    assert command.count("--model") == 1
    assert command[command.index("--model") + 1] == "gpt-5.6-terra"
    assert "--approve-for-me" in command
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--output-schema" in command
    assert "--output-last-message" in command
    assert command[-1] == "-"
    assert not any("dangerously-bypass" in item for item in command)
    assert not any(item in {"resume", "fork"} for item in command)
    assert spec.safe_command[0] == "<CODEX>"
    assert str(codex) not in _canonical_bytes(spec.declaration).decode("utf-8")
    assert set(spec.shell_environment) == {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PYTHONPATH",
        "PYTHONNOUSERSITE",
        "PYTHONSAFEPATH",
        "KOKOROARC_DATA_DIR",
        "TMP",
        "TEMP",
        "PIP_CACHE_DIR",
        "PIP_CONFIG_FILE",
        "PIP_DISABLE_PIP_VERSION_CHECK",
        "PIP_NO_INDEX",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONHASHSEED",
        "PYTHONUTF8",
    }
    serialized = _canonical_bytes(spec.shell_environment).decode("utf-8")
    assert "USERPROFILE" not in serialized
    assert "SECRET_TOKEN" not in serialized
    assert "ignored-user-path" not in serialized
    assert spec.shell_environment["PYTHONPATH"] == str(case_root / "runtime")
    assert spec.shell_environment["TMP"] == str(case_root / "workspace" / "tmp")


def test_one_shot_run_retains_raw_evidence_and_post_run_inventory(
    tmp_path: Path,
) -> None:
    case_root = _prepared_case(tmp_path)
    workspace = case_root / "workspace"
    response_text = _canonical_bytes(_final_response()).decode("utf-8")
    popen_calls = 0

    class FakeProcess:
        returncode = 0

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            nonlocal popen_calls
            popen_calls += 1
            self.command = command
            self.stdout = kwargs["stdout"]
            self.stderr = kwargs["stderr"]

        def communicate(
            self,
            input: bytes | None = None,
            timeout: float | None = None,
        ) -> tuple[None, None]:
            assert input == (case_root / "raw" / "prompt.md").read_bytes()
            assert timeout == runner.RUN_TIMEOUT_SECONDS
            (workspace / "outputs").mkdir()
            _write_json(workspace / "outputs" / "result.json", {"ok": True})
            events = (
                {"type": "thread.started", "thread_id": "thread-one-shot-01"},
                {"type": "turn.started"},
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-final",
                        "type": "agent_message",
                        "text": response_text,
                    },
                },
                {"type": "turn.completed", "usage": {"input_tokens": 1}},
            )
            self.stdout.write(
                b"".join(_canonical_bytes(event) + b"\n" for event in events)
            )
            self.stderr.write(b"bounded diagnostic\n")
            final_path = Path(
                self.command[self.command.index("--output-last-message") + 1]
            )
            final_path.write_bytes(response_text.encode("utf-8") + b"\n")
            return None, None

        def kill(self) -> None:
            raise AssertionError("successful process was killed")

        def poll(self) -> int:
            return self.returncode

    status = runner.run_one(
        case_root,
        runner.RunSpec(1, "baseline", "example-case"),
        codex_executable=Path(r"D:\tools\codex.exe"),
        python_executable=Path(r"C:\Python314\python.exe"),
        host_environment={
            "SYSTEMROOT": r"C:\Windows",
            "WINDIR": r"C:\Windows",
            "COMSPEC": r"C:\Windows\System32\cmd.exe",
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "USERPROFILE": r"C:\Users\private",
        },
        popen_factory=FakeProcess,
    )

    assert popen_calls == 1
    assert status["thread_id"] == "thread-one-shot-01"
    assert status["exit_code"] == 0
    assert status["timed_out"] is False
    assert status["process_completed"] is True
    assert status["lifecycle_passed"] is True
    assert status["failure_codes"] == []
    raw = case_root / "raw"
    for name in (
        "launch-started.json",
        "command.json",
        "launch-private.json",
        "session.jsonl",
        "stderr.txt",
        "final.md",
        "agent-final-events.jsonl",
        "agent-command-events.jsonl",
        "agent-final-session.json",
        "post-run-state.json",
        "run-status.json",
    ):
        assert (raw / name).is_file(), name
    post = json.loads((raw / "post-run-state.json").read_text(encoding="utf-8"))
    assert "outputs/result.json" in post["created_paths"]
    declaration = json.loads((raw / "command.json").read_text(encoding="utf-8"))
    assert declaration["argv"][0] == "<CODEX>"
    private = json.loads(
        (raw / "launch-private.json").read_text(encoding="utf-8")
    )
    assert private["argv"][0] == r"D:\tools\codex.exe"
    assert private["launcher_environment"]["TMP"].startswith(str(case_root))


def test_one_shot_run_marks_immutable_drift_and_refuses_retry(
    tmp_path: Path,
) -> None:
    case_root = _prepared_case(tmp_path)
    response_text = _canonical_bytes(_final_response()).decode("utf-8")
    popen_calls = 0

    class MutatingProcess:
        returncode = 0

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            nonlocal popen_calls
            popen_calls += 1
            self.command = command
            self.stdout = kwargs["stdout"]

        def communicate(
            self,
            input: bytes | None = None,
            timeout: float | None = None,
        ) -> tuple[None, None]:
            events = (
                {"type": "thread.started", "thread_id": "thread-mutation-01"},
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-final",
                        "type": "agent_message",
                        "text": response_text,
                    },
                },
                {"type": "turn.completed", "usage": {}},
            )
            self.stdout.write(
                b"".join(_canonical_bytes(event) + b"\n" for event in events)
            )
            Path(
                self.command[self.command.index("--output-last-message") + 1]
            ).write_bytes(response_text.encode("utf-8") + b"\n")
            _write_json(
                case_root / "workspace" / "inputs" / "setup.json",
                {"input": "mutated"},
            )
            return None, None

        def kill(self) -> None:
            raise AssertionError("successful process was killed")

        def poll(self) -> int:
            return self.returncode

    status = runner.run_one(
        case_root,
        runner.RunSpec(1, "baseline", "example-case"),
        codex_executable=Path(r"D:\tools\codex.exe"),
        python_executable=Path(r"C:\Python314\python.exe"),
        host_environment={"SYSTEMROOT": r"C:\Windows"},
        popen_factory=MutatingProcess,
    )

    assert status["lifecycle_passed"] is False
    assert "IMMUTABLE_STATE_CHANGED" in status["failure_codes"]
    with pytest.raises(RuntimeError, match="not fresh"):
        runner.run_one(
            case_root,
            runner.RunSpec(1, "baseline", "example-case"),
            codex_executable=Path(r"D:\tools\codex.exe"),
            python_executable=Path(r"C:\Python314\python.exe"),
            host_environment={"SYSTEMROOT": r"C:\Windows"},
            popen_factory=MutatingProcess,
        )
    assert popen_calls == 1


def test_one_shot_run_retains_timeout_as_immutable_failure_evidence(
    tmp_path: Path,
) -> None:
    case_root = _prepared_case(tmp_path)
    calls = 0

    class TimeoutProcess:
        returncode: int | None = None

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            self.command = command

        def communicate(
            self,
            input: bytes | None = None,
            timeout: float | None = None,
        ) -> tuple[None, None]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise subprocess.TimeoutExpired(self.command, timeout or 0)
            return None, None

        def kill(self) -> None:
            self.returncode = -9

        def poll(self) -> int | None:
            return self.returncode

    status = runner.run_one(
        case_root,
        runner.RunSpec(1, "baseline", "example-case"),
        codex_executable=Path(r"D:\tools\codex.exe"),
        python_executable=Path(r"C:\Python314\python.exe"),
        host_environment={"SYSTEMROOT": r"C:\Windows"},
        popen_factory=TimeoutProcess,
    )

    assert calls == 2
    assert status["timed_out"] is True
    assert status["process_completed"] is True
    assert status["exit_code"] == -9
    assert status["lifecycle_passed"] is False
    assert {
        "PROCESS_TIMEOUT",
        "PROCESS_NONZERO",
        "FINAL_BINDING_INVALID",
    }.issubset(status["failure_codes"])
    assert (case_root / "raw" / "session.jsonl").is_file()
    assert (case_root / "raw" / "run-status.json").is_file()


def test_one_shot_run_rejects_prelaunch_drift_without_spawning(
    tmp_path: Path,
) -> None:
    case_root = _prepared_case(tmp_path)
    (case_root / "raw" / "prompt.md").write_bytes(b"changed\n")
    called = False

    def forbidden_popen(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("drifted run attempted to spawn")

    with pytest.raises(RuntimeError, match="changed before launch"):
        runner.run_one(
            case_root,
            runner.RunSpec(1, "baseline", "example-case"),
            codex_executable=Path(r"D:\tools\codex.exe"),
            python_executable=Path(r"C:\Python314\python.exe"),
            host_environment={"SYSTEMROOT": r"C:\Windows"},
            popen_factory=forbidden_popen,
        )

    assert called is False
    assert not (case_root / "raw" / "launch-started.json").exists()


def test_one_shot_run_rejects_raw_input_drift_after_launch(
    tmp_path: Path,
) -> None:
    case_root = _prepared_case(tmp_path)
    raw = case_root / "raw"
    response_text = _canonical_bytes(_final_response()).decode("utf-8")

    class RawInputMutatingProcess:
        returncode = 0

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            self.command = command
            self.stdout = kwargs["stdout"]

        def communicate(
            self,
            input: bytes | None = None,
            timeout: float | None = None,
        ) -> tuple[None, None]:
            events = (
                {"type": "thread.started", "thread_id": "thread-raw-drift-01"},
                {"type": "turn.started"},
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-final",
                        "type": "agent_message",
                        "text": response_text,
                    },
                },
                {"type": "turn.completed", "usage": {}},
            )
            self.stdout.write(
                b"".join(_canonical_bytes(event) + b"\n" for event in events)
            )
            Path(
                self.command[self.command.index("--output-last-message") + 1]
            ).write_bytes(response_text.encode("utf-8") + b"\n")
            (raw / "prompt.md").write_bytes(b"changed after launch\n")
            return None, None

        def kill(self) -> None:
            raise AssertionError("successful process was killed")

        def poll(self) -> int:
            return self.returncode

    status = runner.run_one(
        case_root,
        runner.RunSpec(1, "baseline", "example-case"),
        codex_executable=Path(r"D:\tools\codex.exe"),
        python_executable=Path(r"C:\Python314\python.exe"),
        host_environment={"SYSTEMROOT": r"C:\Windows"},
        popen_factory=RawInputMutatingProcess,
    )

    assert status["lifecycle_passed"] is False
    assert "RAW_INPUT_CHANGED" in status["failure_codes"]
    post = json.loads((raw / "post-run-state.json").read_text(encoding="utf-8"))
    assert post["raw_inputs_unchanged"] is False


def test_session_binding_retains_exact_final_and_command_event_bytes(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    response_text = _canonical_bytes(_final_response()).decode("utf-8")
    events: list[dict[str, Any]] = [
        {"type": "thread.started", "thread_id": "thread-unique-01"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "message-1",
                "type": "agent_message",
                "text": "I am checking the local inputs.",
            },
        },
        {
            "type": "item.started",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "Get-Content inputs/setup.json",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "Get-Content inputs/setup.json",
                "aggregated_output": "{}\r\n",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "message-final",
                "type": "agent_message",
                "text": response_text,
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 1}},
    ]
    session_lines = [_canonical_bytes(event) + b"\n" for event in events]
    (raw / "session.jsonl").write_bytes(b"".join(session_lines))
    (raw / "final.md").write_bytes(response_text.encode("utf-8") + b"\n")

    binding = runner.bind_session_evidence(
        raw,
        expected_case_id="example-case",
        output_schema_file=OUTPUT_SCHEMA,
    )

    assert binding["passed"] is True
    assert binding["thread_id"] == "thread-unique-01"
    assert binding["final_event_count"] == 1
    assert binding["command_count"] == 1
    assert binding["final_sha256"] == sha256(
        response_text.encode("utf-8") + b"\n"
    ).hexdigest()
    assert (raw / "agent-final-events.jsonl").read_bytes() == session_lines[5]
    assert (raw / "agent-command-events.jsonl").read_bytes() == (
        session_lines[3] + session_lines[4]
    )
    retained = json.loads((raw / "agent-final-session.json").read_text("utf-8"))
    assert retained == binding


def test_session_binding_fails_on_final_or_command_lifecycle_drift(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    response_text = _canonical_bytes(_final_response()).decode("utf-8")
    events = [
        {"type": "thread.started", "thread_id": "thread-unique-01"},
        {
            "type": "item.started",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "Get-Date",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "Get-Date",
                "aggregated_output": "first",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "Get-Date",
                "aggregated_output": "duplicate",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "message-final",
                "type": "agent_message",
                "text": response_text,
            },
        },
        {"type": "turn.completed", "usage": {}},
    ]
    (raw / "session.jsonl").write_bytes(
        b"".join(_canonical_bytes(event) + b"\n" for event in events)
    )
    (raw / "final.md").write_text(
        response_text.replace("completed", "blocked"),
        encoding="utf-8",
        newline="\n",
    )

    binding = runner.bind_session_evidence(
        raw,
        expected_case_id="example-case",
        output_schema_file=OUTPUT_SCHEMA,
    )

    assert binding["passed"] is False
    assert "FINAL_EVENT_MISMATCH" in binding["failure_codes"]
    assert "COMMAND_LIFECYCLE_INVALID" in binding["failure_codes"]


def test_session_binding_rejects_swapped_outer_command_events(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    response_text = _canonical_bytes(_final_response()).decode("utf-8")
    events = (
        {"type": "thread.started", "thread_id": "thread-swapped-01"},
        {"type": "turn.started"},
        {
            "type": "item.started",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "Get-Date",
                "aggregated_output": "done",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "Get-Date",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "message-final",
                "type": "agent_message",
                "text": response_text,
            },
        },
        {"type": "turn.completed", "usage": {}},
    )
    (raw / "session.jsonl").write_bytes(
        b"".join(_canonical_bytes(event) + b"\n" for event in events)
    )
    (raw / "final.md").write_bytes(response_text.encode("utf-8") + b"\n")

    binding = runner.bind_session_evidence(
        raw,
        expected_case_id="example-case",
        output_schema_file=OUTPUT_SCHEMA,
    )

    assert binding["passed"] is False
    assert "COMMAND_LIFECYCLE_INVALID" in binding["failure_codes"]


@pytest.mark.parametrize("hidden_event_type", [None, "item.updated"])
def test_session_binding_rejects_commands_after_final_or_unknown_outer_event(
    tmp_path: Path,
    hidden_event_type: str | None,
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    response_text = _canonical_bytes(_final_response()).decode("utf-8")
    command_start_type = hidden_event_type or "item.started"
    events: list[dict[str, Any]] = [
        {"type": "thread.started", "thread_id": "thread-order-01"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "message-final",
                "type": "agent_message",
                "text": response_text,
            },
        },
        {
            "type": command_start_type,
            "item": {
                "id": "command-late",
                "type": "command_execution",
                "command": "Get-Date",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
    ]
    if hidden_event_type is None:
        events.append(
            {
                "type": "item.completed",
                "item": {
                    "id": "command-late",
                    "type": "command_execution",
                    "command": "Get-Date",
                    "aggregated_output": "done",
                    "exit_code": 0,
                    "status": "completed",
                },
            }
        )
    events.append({"type": "turn.completed", "usage": {}})
    (raw / "session.jsonl").write_bytes(
        b"".join(_canonical_bytes(event) + b"\n" for event in events)
    )
    (raw / "final.md").write_bytes(response_text.encode("utf-8") + b"\n")

    binding = runner.bind_session_evidence(
        raw,
        expected_case_id="example-case",
        output_schema_file=OUTPUT_SCHEMA,
    )

    assert binding["passed"] is False
    assert "COMMAND_LIFECYCLE_INVALID" in binding["failure_codes"]
