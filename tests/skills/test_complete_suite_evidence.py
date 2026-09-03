from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
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
import complete_suite_command_policy as command_policy  # noqa: E402


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


def _task8_import_authorization_fixture(
    root: Path,
    *,
    campaign_sha256: str | None = None,
    envelope_sha256: str | None = None,
    raw_root: Path | None = None,
    retained_root: Path | None = None,
    retained_root_record: Path | None = None,
) -> tuple[bytes, dict[str, object], dict[str, object]]:
    authorization_id = "0123456789abcdef0123456789abcdef"
    campaign_sha256 = "1" * 64 if campaign_sha256 is None else campaign_sha256
    envelope_sha256 = "2" * 64 if envelope_sha256 is None else envelope_sha256
    provider_approval_sha256 = "3" * 64
    raw_seal_sha256 = "4" * 64
    raw_inventory_sha256 = "5" * 64
    raw_root = (
        (root / "sealed-raw-campaign").resolve()
        if raw_root is None
        else raw_root.resolve()
    )
    raw_root.mkdir(parents=True, exist_ok=True)
    retained_root = (
        (root / "repository" / "retained" / "approved6").resolve()
        if retained_root is None
        else retained_root.resolve()
    )
    retained_root_record = (
        retained_root if retained_root_record is None else retained_root_record
    )
    retained_root_text = (
        str(retained_root_record)
        if retained_root_record.is_absolute()
        else retained_root_record.as_posix()
    )
    authorization_root = (
        root / f"kokoroarc-c6-import-authorization-{authorization_id}"
    ).resolve()
    authorization_root.mkdir(parents=True)
    sealed_audit_path = (root / "sealed-audit" / "audit.json").resolve()
    sealed_audit = {
        "schema_version": "complete-suite-sealed-campaign-audit-v1",
        "result_class": "sealed_24_run",
        "campaign_sha256": campaign_sha256,
        "approval_envelope_sha256": envelope_sha256,
        "provider_approval_sha256": provider_approval_sha256,
        "raw_root": str(raw_root),
        "raw_seal_sha256": raw_seal_sha256,
        "raw_inventory_sha256": raw_inventory_sha256,
        "run_count": 24,
        "retained_root": retained_root_text,
        "retained_root_state": "absent",
        "retry_allowed": False,
    }
    _write_json(sealed_audit_path, sealed_audit)
    sealed_audit_sha256 = sha256(sealed_audit_path.read_bytes()).hexdigest()
    prompt_path = authorization_root / "import-authorization-prompt.txt"
    prompt = (
        "KOKOROARC CAMPAIGN 6 IMPORT AUTHORIZATION v1\n"
        f"authorization_id={authorization_id}\n"
        "campaign_id=2026-08-21-proposed6\n"
        f"campaign_sha256={campaign_sha256}\n"
        f"approval_envelope_sha256={envelope_sha256}\n"
        f"provider_approval_sha256={provider_approval_sha256}\n"
        f"sealed_campaign_audit_record={sealed_audit_path}\n"
        f"sealed_campaign_audit_sha256={sealed_audit_sha256}\n"
        "sealed_campaign_result_class=sealed_24_run\n"
        f"raw_root={raw_root}\n"
        f"raw_seal_sha256={raw_seal_sha256}\n"
        f"raw_inventory_sha256={raw_inventory_sha256}\n"
        "run_count=24\n"
        f"retained_root={retained_root_text}\n"
        "retained_root_state=absent\n"
        "actions=adjudicate,import,sanitize\n"
        "retry_allowed=false\n"
        "authorization=import sanitize adjudicate\n"
        "reply_grammar=APPROVE CAMPAIGN 6 IMPORT SANITIZE ADJUDICATE "
        "<sealed-campaign-audit-sha256> <authorization-prompt-sha256>\n"
    ).encode("utf-8")
    prompt_path.write_bytes(prompt)
    prompt_sha256 = sha256(prompt).hexdigest()
    response_text = (
        "APPROVE CAMPAIGN 6 IMPORT SANITIZE ADJUDICATE "
        f"{sealed_audit_sha256} {prompt_sha256}"
    )
    record = {
        "schema_version": "complete-suite-import-authorization-v2",
        "capture_method": "codex-conversation-operator-attestation-v1",
        "user_event_authentication": "operator-attested-not-cryptographic",
        "authorization_id": authorization_id,
        "observed_at": "2026-08-24T00:00:00Z",
        "authorization_prompt_record": str(prompt_path),
        "authorization_prompt_sha256": prompt_sha256,
        "response_text": response_text,
        "response_sha256": sha256(response_text.encode("utf-8")).hexdigest(),
        "campaign_id": "2026-08-21-proposed6",
        "campaign_sha256": campaign_sha256,
        "approval_envelope_sha256": envelope_sha256,
        "provider_approval_sha256": provider_approval_sha256,
        "sealed_campaign_audit_record": str(sealed_audit_path),
        "sealed_campaign_audit_sha256": sealed_audit_sha256,
        "raw_root": str(raw_root),
        "raw_seal_sha256": raw_seal_sha256,
        "raw_inventory_sha256": raw_inventory_sha256,
        "run_count": 24,
        "retained_root": retained_root_text,
        "actions": ["adjudicate", "import", "sanitize"],
        "retry_allowed": False,
    }
    record_bytes = _canonical_bytes(record) + b"\n"
    expected = {
        "expected_record_sha256": sha256(record_bytes).hexdigest(),
        "expected_import_authorization_prompt_sha256": prompt_sha256,
        "expected_campaign_sha256": campaign_sha256,
        "expected_envelope_sha256": envelope_sha256,
        "expected_provider_approval_sha256": provider_approval_sha256,
        "expected_sealed_campaign_audit_sha256": sealed_audit_sha256,
        "expected_raw_root": raw_root,
        "expected_raw_seal_sha256": raw_seal_sha256,
        "expected_raw_inventory_sha256": raw_inventory_sha256,
        "expected_retained_root": retained_root_record,
    }
    return record_bytes, expected, record


def test_import_authorization_accepts_exact_task15_record(tmp_path: Path) -> None:
    from import_complete_suite_campaign import validate_import_authorization

    record_bytes, expected, record = _task8_import_authorization_fixture(tmp_path)

    authorization = validate_import_authorization(record_bytes, **expected)

    assert authorization.authorization_id == record["authorization_id"]
    assert authorization.actions == ("adjudicate", "import", "sanitize")
    assert authorization.canonical_bytes == record_bytes
    assert authorization.canonical_sha256 == expected["expected_record_sha256"]


def _task8_prompt_from_authorization(record: dict[str, object]) -> bytes:
    return (
        "KOKOROARC CAMPAIGN 6 IMPORT AUTHORIZATION v1\n"
        f"authorization_id={record['authorization_id']}\n"
        "campaign_id=2026-08-21-proposed6\n"
        f"campaign_sha256={record['campaign_sha256']}\n"
        "approval_envelope_sha256="
        f"{record['approval_envelope_sha256']}\n"
        "provider_approval_sha256="
        f"{record['provider_approval_sha256']}\n"
        "sealed_campaign_audit_record="
        f"{record['sealed_campaign_audit_record']}\n"
        "sealed_campaign_audit_sha256="
        f"{record['sealed_campaign_audit_sha256']}\n"
        "sealed_campaign_result_class=sealed_24_run\n"
        f"raw_root={record['raw_root']}\n"
        f"raw_seal_sha256={record['raw_seal_sha256']}\n"
        "raw_inventory_sha256="
        f"{record['raw_inventory_sha256']}\n"
        "run_count=24\n"
        f"retained_root={record['retained_root']}\n"
        "retained_root_state=absent\n"
        "actions=adjudicate,import,sanitize\n"
        "retry_allowed=false\n"
        "authorization=import sanitize adjudicate\n"
        "reply_grammar=APPROVE CAMPAIGN 6 IMPORT SANITIZE ADJUDICATE "
        "<sealed-campaign-audit-sha256> <authorization-prompt-sha256>\n"
    ).encode("utf-8")


def _task8_reseal_authorization(
    record: dict[str, object],
    expected: dict[str, object],
) -> tuple[bytes, dict[str, object]]:
    prompt = _task8_prompt_from_authorization(record)
    Path(str(record["authorization_prompt_record"])).write_bytes(prompt)
    prompt_sha256 = sha256(prompt).hexdigest()
    record["authorization_prompt_sha256"] = prompt_sha256
    expected["expected_import_authorization_prompt_sha256"] = prompt_sha256
    response = (
        "APPROVE CAMPAIGN 6 IMPORT SANITIZE ADJUDICATE "
        f"{record['sealed_campaign_audit_sha256']} {prompt_sha256}"
    )
    record["response_text"] = response
    record["response_sha256"] = sha256(response.encode("utf-8")).hexdigest()
    record_bytes = _canonical_bytes(record) + b"\n"
    expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    return record_bytes, expected


@pytest.mark.parametrize(
    "mutation",
    (
        "noncanonical-record",
        "duplicate-key",
        "wrong-record-hash",
        "unknown-field",
        "reordered-actions",
        "wrong-prompt-hash",
        "wrong-authorization-id",
        "wrong-response",
        "wrong-campaign",
        "wrong-raw-seal",
        "wrong-raw-inventory",
        "wrong-retained-root",
        "wrong-audit-class",
    ),
)
def test_import_authorization_rejects_closed_tamper_matrix(
    tmp_path: Path,
    mutation: str,
) -> None:
    from import_complete_suite_campaign import validate_import_authorization

    record_bytes, expected, record = _task8_import_authorization_fixture(tmp_path)
    if mutation == "noncanonical-record":
        record_bytes = b"{ " + record_bytes[1:]
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    elif mutation == "duplicate-key":
        record_bytes = (
            b'{"schema_version":"complete-suite-import-authorization-v2",'
            + record_bytes[1:]
        )
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    elif mutation == "wrong-record-hash":
        expected["expected_record_sha256"] = "f" * 64
    elif mutation == "unknown-field":
        record["unexpected"] = True
        record_bytes = _canonical_bytes(record) + b"\n"
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    elif mutation == "reordered-actions":
        record["actions"] = ["import", "sanitize", "adjudicate"]
        record_bytes = _canonical_bytes(record) + b"\n"
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    elif mutation == "wrong-prompt-hash":
        record["authorization_prompt_sha256"] = "e" * 64
        expected["expected_import_authorization_prompt_sha256"] = "e" * 64
        record_bytes = _canonical_bytes(record) + b"\n"
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    elif mutation == "wrong-authorization-id":
        record["authorization_id"] = "f" * 32
        record_bytes = _canonical_bytes(record) + b"\n"
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    elif mutation == "wrong-response":
        record["response_text"] = "APPROVE CAMPAIGN 6 IMPORT"
        record["response_sha256"] = sha256(
            str(record["response_text"]).encode("utf-8")
        ).hexdigest()
        record_bytes = _canonical_bytes(record) + b"\n"
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    elif mutation == "wrong-campaign":
        record["campaign_sha256"] = "d" * 64
        record_bytes = _canonical_bytes(record) + b"\n"
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    elif mutation == "wrong-raw-seal":
        record["raw_seal_sha256"] = "c" * 64
        record_bytes = _canonical_bytes(record) + b"\n"
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    elif mutation == "wrong-raw-inventory":
        record["raw_inventory_sha256"] = "b" * 64
        record_bytes = _canonical_bytes(record) + b"\n"
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    elif mutation == "wrong-retained-root":
        record["retained_root"] = str(tmp_path / "other-retained")
        record_bytes = _canonical_bytes(record) + b"\n"
        expected["expected_record_sha256"] = sha256(record_bytes).hexdigest()
    else:
        audit_path = Path(str(record["sealed_campaign_audit_record"]))
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["result_class"] = "sealed_zero_run_failure"
        _write_json(audit_path, audit)
        audit_sha256 = sha256(audit_path.read_bytes()).hexdigest()
        record["sealed_campaign_audit_sha256"] = audit_sha256
        expected["expected_sealed_campaign_audit_sha256"] = audit_sha256
        record_bytes, expected = _task8_reseal_authorization(record, expected)

    with pytest.raises(RuntimeError):
        validate_import_authorization(record_bytes, **expected)


def test_import_authorization_rejects_preexisting_retained_root(
    tmp_path: Path,
) -> None:
    from import_complete_suite_campaign import validate_import_authorization

    record_bytes, expected, _record = _task8_import_authorization_fixture(tmp_path)
    retained_root = expected["expected_retained_root"]
    assert isinstance(retained_root, Path)
    retained_root.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="already exists"):
        validate_import_authorization(record_bytes, **expected)


@pytest.mark.parametrize("mode", ("missing", "changed"))
def test_importer_authorization_failure_precedes_parent_or_stage_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    import import_complete_suite_campaign as importer

    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign = yaml.safe_load(paths.campaign_file.read_text(encoding="utf-8"))
    campaign["campaign_id"] = "2026-08-21-proposed6"
    _write_yaml(paths.campaign_file, campaign)
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
    retained_repository = tmp_path / "retained-repository"
    retained_repository.mkdir()
    expected_retained_root = (
        retained_repository
        / "tests"
        / "skills"
        / "evidence"
        / "complete-suite"
        / "approved2"
    )
    retained_parent = expected_retained_root.parent
    campaign = yaml.safe_load(paths.campaign_file.read_text(encoding="utf-8"))
    envelope_sha256 = runner.approval_envelope_sha256(campaign)
    record_bytes, expected, record = _task8_import_authorization_fixture(
        tmp_path / "authorization-fixture",
        campaign_sha256=campaign_hash,
        envelope_sha256=envelope_sha256,
        raw_root=raw_root,
        retained_root=expected_retained_root,
    )
    authorization_path = (
        Path(str(record["authorization_prompt_record"])).parent
        / "import-authorization.json"
    )
    authorization_path.write_bytes(record_bytes + b" ")

    def forbid_staging(*_args: object, **_kwargs: object) -> str:
        pytest.fail("authorization failure reached importer staging")

    monkeypatch.setattr(importer.tempfile, "mkdtemp", forbid_staging)
    arguments: dict[str, object] = {}
    if mode == "changed":
        arguments = {
            "import_authorization": authorization_path,
            "expected_import_authorization_sha256": expected[
                "expected_record_sha256"
            ],
            "expected_import_authorization_prompt_sha256": expected[
                "expected_import_authorization_prompt_sha256"
            ],
            "sealed_campaign_audit": Path(
                str(record["sealed_campaign_audit_record"])
            ),
            "expected_sealed_campaign_audit_sha256": expected[
                "expected_sealed_campaign_audit_sha256"
            ],
            "approved_envelope_sha256": envelope_sha256,
            "provider_approval_sha256": expected[
                "expected_provider_approval_sha256"
            ],
            "expected_raw_seal_sha256": expected[
                "expected_raw_seal_sha256"
            ],
            "expected_raw_inventory_sha256": expected[
                "expected_raw_inventory_sha256"
            ],
            "expected_retained_root": expected_retained_root,
        }

    with pytest.raises(RuntimeError, match="authorization"):
        importer.import_campaign(
            raw_root,
            paths=paths,
            retained_repository_root=retained_repository,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            retain_factory=lambda *_args, **_kwargs: pytest.fail(
                "authorization failure reached run retention"
            ),
            **arguments,
        )

    assert not retained_parent.exists()
    assert not expected_retained_root.exists()


def test_import_and_adjudication_cli_are_consumer_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect

    import complete_suite_adjudication as adjudication
    import import_complete_suite_campaign as importer

    raw_root = tmp_path / "raw"
    retained_root = tmp_path / "retained"
    declared_retained_root = Path(
        "tests/skills/evidence/complete-suite/approved6"
    )
    authorization_path = tmp_path / "authorization.json"
    sealed_audit_path = tmp_path / "sealed-audit.json"
    hashes = {
        "campaign": "1" * 64,
        "authorization": "2" * 64,
        "prompt": "3" * 64,
        "audit": "4" * 64,
        "envelope": "5" * 64,
        "provider": "6" * 64,
        "seal": "7" * 64,
        "inventory": "8" * 64,
    }
    common_argv = [
        "--import-authorization",
        str(authorization_path),
        "--expected-import-authorization-sha256",
        hashes["authorization"],
        "--expected-import-authorization-prompt-sha256",
        hashes["prompt"],
        "--sealed-campaign-audit",
        str(sealed_audit_path),
        "--expected-sealed-campaign-audit-sha256",
        hashes["audit"],
        "--approved-campaign-sha256",
        hashes["campaign"],
        "--approved-envelope-sha256",
        hashes["envelope"],
        "--provider-approval-sha256",
        hashes["provider"],
        "--expected-raw-seal-sha256",
        hashes["seal"],
        "--expected-raw-inventory-sha256",
        hashes["inventory"],
        "--expected-retained-root",
        declared_retained_root.as_posix(),
    ]
    imported: dict[str, object] = {}

    def fake_import(raw: Path, **kwargs: object) -> Path:
        imported.update({"raw_root": raw, **kwargs})
        return retained_root

    monkeypatch.setattr(importer, "import_campaign", fake_import)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_complete_suite_campaign.py",
            str(raw_root),
            *common_argv,
        ],
    )
    importer.main()
    assert imported == {
        "raw_root": raw_root,
        "expected_retained_root": declared_retained_root,
        "import_authorization": authorization_path,
        "expected_import_authorization_sha256": hashes["authorization"],
        "expected_import_authorization_prompt_sha256": hashes["prompt"],
        "sealed_campaign_audit": sealed_audit_path,
        "expected_sealed_campaign_audit_sha256": hashes["audit"],
        "approved_campaign_sha256": hashes["campaign"],
        "approved_envelope_sha256": hashes["envelope"],
        "provider_approval_sha256": hashes["provider"],
        "expected_raw_seal_sha256": hashes["seal"],
        "expected_raw_inventory_sha256": hashes["inventory"],
    }

    adjudicated: dict[str, object] = {}
    results_root = retained_root / "results"

    def fake_adjudicate(raw: Path, retained: Path, **kwargs: object) -> Path:
        adjudicated.update(
            {"raw_root": raw, "retained_root": retained, **kwargs}
        )
        return results_root

    monkeypatch.setattr(adjudication, "adjudicate_campaign", fake_adjudicate)
    monkeypatch.setattr(
        adjudication,
        "_load_json_object",
        lambda _path: {"suite_closure_passed": True},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "complete_suite_adjudication.py",
            str(raw_root),
            str(retained_root),
            *common_argv,
        ],
    )
    assert adjudication.main() == 0
    assert adjudicated == {
        "raw_root": raw_root,
        "retained_root": retained_root,
        "expected_retained_root": declared_retained_root,
        "import_authorization": authorization_path,
        "expected_import_authorization_sha256": hashes["authorization"],
        "expected_import_authorization_prompt_sha256": hashes["prompt"],
        "sealed_campaign_audit": sealed_audit_path,
        "expected_sealed_campaign_audit_sha256": hashes["audit"],
        "approved_campaign_sha256": hashes["campaign"],
        "approved_envelope_sha256": hashes["envelope"],
        "provider_approval_sha256": hashes["provider"],
        "expected_raw_seal_sha256": hashes["seal"],
        "expected_raw_inventory_sha256": hashes["inventory"],
    }
    for validator in (
        importer.validate_import_authorization,
        importer._validate_import_authorization_arguments,
    ):
        source = inspect.getsource(validator)
        assert ".write_" not in source
        assert ".mkdir(" not in source
        assert "mkdtemp" not in source


def test_rendered_prompt_requires_exact_case_claim_coverage() -> None:
    case = {
        "id": "claim-contract-case",
        "setup": "A bounded local fixture is ready.",
        "prompt": "Inspect the fixture and report the result.",
        "must": ["report_local_result", "preserve_input_fixture"],
        "must_not": ["use_network", "publish_result"],
    }

    prompt = runner._render_prompt(case)

    assert "`workspace/case.json`" in prompt
    marker = "Claim each of these assertion IDs exactly once: "
    declaration = next(
        line.removeprefix(marker)
        for line in prompt.splitlines()
        if line.startswith(marker)
    )
    assert json.loads(declaration) == [
        "report_local_result",
        "preserve_input_fixture",
        "use_network",
        "publish_result",
    ]
    for identifier in json.loads(declaration):
        assert prompt.count(json.dumps(identifier)) == 1
    assert "Do not omit, duplicate, or invent an assertion ID." in prompt


def test_campaign_result_validator_accepts_not_applicable_claim_status() -> None:
    from complete_suite_adjudication import _validate_campaign_result

    result = {
        "schema_version": "1.0",
        "variant": "baseline",
        "case_id": "example-case",
        "evidence_integrity": {
            "passed": True,
            "failure_codes": [],
            "command_count": 0,
            "file_change_count": 0,
        },
        "assertions": [
            {
                "requirement": "must",
                "id": "report_local_result",
                "observed": False,
                "claimed_status": "not_applicable",
                "passed": False,
            }
        ],
        "failure_codes": ["ASSERTION_FAILED"],
        "passed": False,
    }

    assert _validate_campaign_result(
        result,
        runner.RunSpec(1, "baseline", "example-case"),
    ) == result


def _synthetic_runtime_wheelhouse(root: Path) -> dict[str, Any]:
    wheelhouse = root / "runtime-wheelhouse"
    for index, name in enumerate(
        (
            "attrs-25.3.0-py3-none-any.whl",
            "jsonschema-4.25.0-py3-none-any.whl",
            "jsonschema_specifications-2025.4.1-py3-none-any.whl",
            "kokoroarc-0.0.0.dev0-py3-none-any.whl",
            "PyYAML-6.0.2-cp312-cp312-win_amd64.whl",
            "referencing-0.36.2-py3-none-any.whl",
            "rpds_py-0.27.0-cp312-cp312-win_amd64.whl",
        ),
        start=1,
    ):
        path = wheelhouse / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"wheel-{index}\n".encode("utf-8"))
    return runner.preparation.capture_runtime_wheelhouse(wheelhouse)


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


def _prepared_case(
    root: Path,
    *,
    seed_policy_artifacts: bool = False,
) -> Path:
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
    if seed_policy_artifacts:
        (workspace / "data" / "compiled" / "changed-dir").mkdir(parents=True)
        (
            workspace / "data" / "compiled" / "changed-dir" / "value.txt"
        ).write_bytes(b"before\n")
        (workspace / "data" / "reports" / "removed-dir").mkdir(parents=True)
        (
            workspace / "data" / "reports" / "removed-dir" / "old.txt"
        ).write_bytes(b"remove me\n")
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
        "policy_filesystem_roots": [
            command_policy._root_record(snapshot)
            for snapshot in runner.preparation.capture_policy_filesystem_roots(
                case_root=case_root,
                approved_roots=(
                    workspace,
                    workspace / "data" / "compiled",
                    workspace / "data" / "reports",
                    workspace / "outputs",
                ),
            )
        ],
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
                        "tests/skills/evidence/complete-suite/approved2"
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
    runtime_wheelhouse = _synthetic_runtime_wheelhouse(raw_root.parent)
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
        "wheel": runtime_wheelhouse["kokoroarc_wheel"],
        "runtime_wheelhouse": runtime_wheelhouse,
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


def _task8_authorized_synthetic_campaign(
    root: Path,
) -> tuple[
    Path,
    runner.HarnessPaths,
    str,
    tuple[str, ...],
    dict[str, str],
    Path,
    Path,
    dict[str, object],
]:
    raw_root = root / "raw-campaign"
    paths = _paths(root / "repository", raw_root)
    campaign = yaml.safe_load(paths.campaign_file.read_text(encoding="utf-8"))
    campaign["campaign_id"] = "2026-08-21-proposed6"
    _write_yaml(paths.campaign_file, campaign)
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
    retained_repository = paths.repository_root
    retained_root = (
        retained_repository
        / "tests"
        / "skills"
        / "evidence"
        / "complete-suite"
        / "approved2"
    )
    campaign = yaml.safe_load(paths.campaign_file.read_text(encoding="utf-8"))
    envelope_sha256 = runner.approval_envelope_sha256(campaign)
    record_bytes, expected, record = _task8_import_authorization_fixture(
        root / "authorization-fixture",
        campaign_sha256=campaign_hash,
        envelope_sha256=envelope_sha256,
        raw_root=raw_root,
        retained_root=retained_root,
        retained_root_record=Path(
            "tests/skills/evidence/complete-suite/approved2"
        ),
    )
    authorization_path = (
        Path(str(record["authorization_prompt_record"])).parent
        / "import-authorization.json"
    )
    authorization_path.write_bytes(record_bytes)
    authorization_arguments: dict[str, object] = {
        "import_authorization": authorization_path,
        "expected_import_authorization_sha256": expected[
            "expected_record_sha256"
        ],
        "expected_import_authorization_prompt_sha256": expected[
            "expected_import_authorization_prompt_sha256"
        ],
        "sealed_campaign_audit": Path(
            str(record["sealed_campaign_audit_record"])
        ),
        "expected_sealed_campaign_audit_sha256": expected[
            "expected_sealed_campaign_audit_sha256"
        ],
        "approved_envelope_sha256": envelope_sha256,
        "provider_approval_sha256": expected[
            "expected_provider_approval_sha256"
        ],
        "expected_raw_seal_sha256": expected["expected_raw_seal_sha256"],
        "expected_raw_inventory_sha256": expected[
            "expected_raw_inventory_sha256"
        ],
        "expected_retained_root": expected["expected_retained_root"],
    }
    return (
        raw_root,
        paths,
        campaign_hash,
        required,
        observed_git,
        retained_repository,
        retained_root,
        authorization_arguments,
    )


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
        "tests/skills/test_complete_suite_preparation.py",
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
    assert approved.wheel == approved.runtime_wheelhouse["kokoroarc_wheel"]
    assert approved.runtime_wheelhouse["root"] == str(
        (tmp_path / "runtime-wheelhouse").resolve()
    )
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


def test_approved_campaign_seals_preparation_failure_without_starting_runs(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    campaign_hash, required = _approve_synthetic(paths, raw_root)
    run_calls = 0

    def prepare_failure(
        approved: runner.ApprovedCampaign,
        _paths: runner.HarnessPaths,
        **_kwargs: object,
    ) -> Path:
        approved.raw_root.mkdir()
        _write_json(
            approved.raw_root / "approval.json",
            {
                "schema_version": "1.0",
                "campaign_sha256": approved.campaign_sha256,
                "approval_envelope_sha256": approved.envelope_sha256,
            },
        )
        raise ModuleNotFoundError("sensitive host path must not be retained")

    def forbidden_run(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal run_calls
        run_calls += 1
        return {}

    with pytest.raises(RuntimeError, match="preparation sealed with deviations"):
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
            prepare_factory=prepare_failure,
            run_factory=forbidden_run,
            version_factory=lambda _path, _environment: "codex-cli 0.148.0",
        )

    failure = json.loads(
        (raw_root / "campaign-failure.json").read_text(encoding="utf-8")
    )
    assert failure == {
        "schema_version": "1.0",
        "phase": "preparation",
        "code": "CAMPAIGN_PREPARATION_FAILED",
        "error_type": "ModuleNotFoundError",
        "retry_allowed": False,
    }
    ledger = json.loads(
        (raw_root / "campaign-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["runs_authorized"] == 24
    assert ledger["runs_started"] == 0
    assert ledger["runs_completed"] == 0
    assert ledger["failure"] == failure
    assert ledger["failure_artifact"] == {
        "size": (raw_root / "campaign-failure.json").stat().st_size,
        "sha256": sha256(
            (raw_root / "campaign-failure.json").read_bytes()
        ).hexdigest(),
    }
    assert ledger["failure_snapshot"]["files"] == [
        {
            "path": "approval.json",
            "size": (raw_root / "approval.json").stat().st_size,
            "sha256": sha256((raw_root / "approval.json").read_bytes()).hexdigest(),
        }
    ]
    assert any(
        deviation["ordinal"] == 0
        and deviation["code"] == "CAMPAIGN_PREPARATION_FAILED"
        for deviation in ledger["deviations"]
    )
    assert run_calls == 0
    assert not (raw_root / "runs").exists()
    assert (raw_root / "COMPLETED").is_file()
    assert b"sensitive host path" not in (
        raw_root / "campaign-failure.json"
    ).read_bytes()


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


def test_preparation_failure_import_is_zero_run_and_exactly_replayable(
    tmp_path: Path,
) -> None:
    from import_complete_suite_campaign import (
        import_campaign,
        replay_campaign_import,
    )

    raw_root = tmp_path / "raw-campaign"
    paths = _paths(tmp_path / "repository", raw_root)
    retained_repository = tmp_path / "retained-repository"
    retained_repository.mkdir()
    campaign_hash, required = _approve_synthetic(paths, raw_root)
    observed_git = {
        "commit": "1" * 40,
        "tree": "2" * 40,
        "parent": "3" * 40,
    }

    def prepare_failure(
        approved: runner.ApprovedCampaign,
        _paths: runner.HarnessPaths,
        **_kwargs: object,
    ) -> Path:
        approved.raw_root.mkdir()
        _write_json(
            approved.raw_root / "approval.json",
            {
                "schema_version": "1.0",
                "campaign_sha256": approved.campaign_sha256,
                "approval_envelope_sha256": approved.envelope_sha256,
            },
        )
        partial = approved.raw_root / "harness" / "partial.txt"
        partial.parent.mkdir()
        partial.write_bytes(b"partial frozen preparation\n")
        raise RuntimeError("fixture preparation failed")

    with pytest.raises(RuntimeError, match="preparation sealed with deviations"):
        runner.execute_campaign(
            paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            codex_executable=Path(sys.executable),
            python_executable=Path(sys.executable),
            host_environment={"PATH": "synthetic"},
            prepare_factory=prepare_failure,
            run_factory=lambda *_args, **_kwargs: pytest.fail(
                "preparation failure must not launch a run"
            ),
            version_factory=lambda _path, _environment: "codex-cli 0.148.0",
        )

    retained_root = import_campaign(
        raw_root,
        paths=paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git=observed_git,
        retained_repository_root=retained_repository,
    )
    assert retained_root == (
        retained_repository
        / "tests"
        / "skills"
        / "evidence"
        / "complete-suite"
        / "approved2"
    )
    assert {path.name for path in retained_root.iterdir()} == {
        "campaign",
        "import-ledger.json",
    }
    assert {path.name for path in (retained_root / "campaign").iterdir()} == {
        "approval.json",
        "campaign-failure.json",
        "campaign-ledger.json",
        "campaign-completion.json",
        "COMPLETED",
    }
    import_ledger = json.loads(
        (retained_root / "import-ledger.json").read_text(encoding="utf-8")
    )
    assert import_ledger["failure"] == json.loads(
        (raw_root / "campaign-failure.json").read_text(encoding="utf-8")
    )
    assert import_ledger["runs_authorized"] == 24
    assert import_ledger["run_count"] == 0
    assert import_ledger["runs"] == []

    _campaign, _cases, plan, ledgers, replayed = replay_campaign_import(
        raw_root,
        retained_root,
        paths=paths,
        approved_campaign_sha256=campaign_hash,
        required_frozen_paths=required,
        observed_git=observed_git,
        retained_repository_root=retained_repository,
    )
    assert len(plan) == 24
    assert ledgers == ()
    assert replayed == import_ledger

    ledger_path = raw_root / "campaign-ledger.json"
    completion_path = raw_root / "campaign-completion.json"
    marker_path = raw_root / "COMPLETED"
    original_ledger = ledger_path.read_bytes()
    original_completion = completion_path.read_bytes()
    original_marker = marker_path.read_bytes()
    forged_ledger = json.loads(original_ledger)
    snapshot_files = forged_ledger["failure_snapshot"]["files"]
    snapshot_files.append(dict(snapshot_files[0]))
    forged_ledger["failure_snapshot"].update(
        {
            "file_count": len(snapshot_files),
            "total_bytes": sum(entry["size"] for entry in snapshot_files),
            "tree_sha256": sha256(_canonical_bytes(snapshot_files)).hexdigest(),
        }
    )
    _write_json(ledger_path, forged_ledger)
    forged_ledger_hash = sha256(ledger_path.read_bytes()).hexdigest()
    forged_completion = json.loads(original_completion)
    forged_completion["campaign_ledger_sha256"] = forged_ledger_hash
    _write_json(completion_path, forged_completion)
    marker_path.write_bytes(forged_ledger_hash.encode("ascii") + b"\n")
    with pytest.raises(RuntimeError, match="preparation snapshot is invalid"):
        replay_campaign_import(
            raw_root,
            retained_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            retained_repository_root=retained_repository,
        )
    ledger_path.write_bytes(original_ledger)
    completion_path.write_bytes(original_completion)
    marker_path.write_bytes(original_marker)

    (raw_root / "harness" / "partial.txt").write_bytes(b"changed\n")
    with pytest.raises(RuntimeError, match="preparation snapshot changed"):
        replay_campaign_import(
            raw_root,
            retained_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            retained_repository_root=retained_repository,
        )


def test_authorized_campaign_rejects_callback_provenance_bypass_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import import_complete_suite_campaign as importer

    (
        raw_root,
        paths,
        campaign_hash,
        required,
        observed_git,
        retained_repository,
        retained_root,
        authorization_arguments,
    ) = _task8_authorized_synthetic_campaign(tmp_path)

    calls: list[str] = []

    def forbidden_retain(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append("retain")
        return {}

    def forbidden_replay(*_args: object, **_kwargs: object) -> None:
        calls.append("replay")

    def forbid_staging(*_args: object, **_kwargs: object) -> str:
        pytest.fail("callback provenance bypass reached import staging")

    monkeypatch.setattr(importer.tempfile, "mkdtemp", forbid_staging)
    with pytest.raises(
        RuntimeError,
        match="operation provenance source unavailable",
    ):
        importer.import_campaign(
            raw_root,
            paths=paths,
            retained_repository_root=retained_repository,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            retain_factory=forbidden_retain,
            replay_factory=forbidden_replay,
            **authorization_arguments,
        )
    assert calls == []
    assert authorization_arguments["expected_retained_root"] == Path(
        "tests/skills/evidence/complete-suite/approved2"
    )
    assert not retained_root.exists()


def test_authorized_campaign_replay_rejects_callback_bypass_before_layout(
    tmp_path: Path,
) -> None:
    from import_complete_suite_campaign import replay_campaign_import

    (
        raw_root,
        paths,
        campaign_hash,
        required,
        observed_git,
        retained_repository,
        retained_root,
        authorization_arguments,
    ) = _task8_authorized_synthetic_campaign(tmp_path)
    retained_root.mkdir(parents=True)
    replay_calls = 0

    def forbidden_replay(*_args: object, **_kwargs: object) -> None:
        nonlocal replay_calls
        replay_calls += 1

    with pytest.raises(RuntimeError, match="callback"):
        replay_campaign_import(
            raw_root,
            retained_root,
            paths=paths,
            retained_repository_root=retained_repository,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            replay_factory=forbidden_replay,
            **authorization_arguments,
        )
    assert replay_calls == 0


def test_authorized_adjudication_rejects_behavior_callback_before_import_replay(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    (
        raw_root,
        paths,
        campaign_hash,
        required,
        observed_git,
        _retained_repository,
        retained_root,
        authorization_arguments,
    ) = _task8_authorized_synthetic_campaign(tmp_path)
    retained_root.mkdir(parents=True)
    behavior_calls = 0

    def forbidden_behavior(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal behavior_calls
        behavior_calls += 1
        return {}

    with pytest.raises(RuntimeError, match="callback"):
        adjudication.adjudicate_campaign(
            raw_root,
            retained_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            adjudicate_factory=forbidden_behavior,
            **authorization_arguments,
        )
    assert behavior_calls == 0
    assert not (retained_root / "results").exists()


def test_authorized_adjudication_replay_rejects_behavior_callback_before_layout(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    (
        raw_root,
        paths,
        campaign_hash,
        required,
        observed_git,
        _retained_repository,
        retained_root,
        authorization_arguments,
    ) = _task8_authorized_synthetic_campaign(tmp_path)
    behavior_calls = 0

    def forbidden_behavior(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal behavior_calls
        behavior_calls += 1
        return {}

    with pytest.raises(RuntimeError, match="callback"):
        adjudication.replay_campaign_adjudication(
            raw_root,
            retained_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            adjudicate_factory=forbidden_behavior,
            **authorization_arguments,
        )
    assert behavior_calls == 0
    assert not retained_root.exists()


def test_authorized_default_import_requires_operation_provenance_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import import_complete_suite_campaign as importer

    (
        raw_root,
        paths,
        campaign_hash,
        required,
        observed_git,
        retained_repository,
        retained_root,
        authorization_arguments,
    ) = _task8_authorized_synthetic_campaign(tmp_path)

    def forbid_staging(*_args: object, **_kwargs: object) -> str:
        pytest.fail("missing operation provenance reached import staging")

    monkeypatch.setattr(importer.tempfile, "mkdtemp", forbid_staging)
    with pytest.raises(
        RuntimeError,
        match="operation provenance source unavailable",
    ):
        importer.import_campaign(
            raw_root,
            paths=paths,
            retained_repository_root=retained_repository,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            **authorization_arguments,
        )
    assert not retained_root.exists()


def test_adjudicator_revalidates_authorization_before_stage_or_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import complete_suite_adjudication as adjudication

    (
        raw_root,
        paths,
        campaign_hash,
        required,
        observed_git,
        retained_repository,
        retained_root,
        authorization_arguments,
    ) = _task8_authorized_synthetic_campaign(tmp_path)

    retained_root.mkdir(parents=True)
    authorization_path = authorization_arguments["import_authorization"]
    assert isinstance(authorization_path, Path)
    authorization_path.write_bytes(authorization_path.read_bytes() + b" ")
    behavior_calls = 0

    def forbidden_behavior(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal behavior_calls
        behavior_calls += 1
        return {}

    def forbid_staging(*_args: object, **_kwargs: object) -> str:
        pytest.fail("authorization failure reached adjudication staging")

    monkeypatch.setattr(adjudication.tempfile, "mkdtemp", forbid_staging)
    with pytest.raises(RuntimeError, match="authorization"):
        adjudication.adjudicate_campaign(
            raw_root,
            retained_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            replay_factory=lambda *_args: None,
            adjudicate_factory=forbidden_behavior,
            **authorization_arguments,
        )
    assert behavior_calls == 0
    assert not (retained_root / "results").exists()


def test_adjudication_replay_revalidates_authorization_before_behavior(
    tmp_path: Path,
) -> None:
    import complete_suite_adjudication as adjudication

    (
        raw_root,
        paths,
        campaign_hash,
        required,
        observed_git,
        retained_repository,
        retained_root,
        authorization_arguments,
    ) = _task8_authorized_synthetic_campaign(tmp_path)

    (retained_root / "results").mkdir(parents=True)
    authorization_path = authorization_arguments["import_authorization"]
    assert isinstance(authorization_path, Path)
    authorization_path.write_bytes(authorization_path.read_bytes() + b" ")
    behavior_calls = 0

    def forbidden_behavior(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal behavior_calls
        behavior_calls += 1
        return {}

    with pytest.raises(RuntimeError, match="authorization"):
        adjudication.replay_campaign_adjudication(
            raw_root,
            retained_root,
            paths=paths,
            approved_campaign_sha256=campaign_hash,
            required_frozen_paths=required,
            observed_git=observed_git,
            replay_factory=lambda *_args: pytest.fail(
                "authorization failure reached import replay"
            ),
            adjudicate_factory=forbidden_behavior,
            **authorization_arguments,
        )
    assert behavior_calls == 0


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
        / "approved2"
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


def test_real_approved_preparation_uses_frozen_runtime_for_24_fresh_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    built_assets = tmp_path / "built-assets"
    built = runner.preparation.build_installed_distribution(
        REPOSITORY_ROOT,
        built_assets,
        python_executable=sys.executable,
    )
    wheelhouse_root = tmp_path / "runtime-wheelhouse"
    wheelhouse_root.mkdir()
    wheel_name = str(built["wheel"]["filename"])
    shutil.copy2(built_assets / "dist" / wheel_name, wheelhouse_root / wheel_name)
    for name in (
        "attrs-25.3.0-py3-none-any.whl",
        "jsonschema-4.25.0-py3-none-any.whl",
        "jsonschema_specifications-2025.4.1-py3-none-any.whl",
        "PyYAML-6.0.2-py3-none-any.whl",
        "referencing-0.36.2-py3-none-any.whl",
        "rpds_py-0.27.0-py3-none-any.whl",
    ):
        (wheelhouse_root / name).write_bytes(f"{name}\n".encode("utf-8"))
    wheelhouse = runner.preparation.capture_runtime_wheelhouse(wheelhouse_root)
    install_calls = 0
    fixture_calls = 0

    def frozen_install(
        repository_root: Path,
        supplied_root: Path,
        supplied_manifest: dict[str, Any],
        assets_root: Path,
        **_kwargs: object,
    ) -> dict[str, Any]:
        nonlocal install_calls
        install_calls += 1
        assert repository_root == REPOSITORY_ROOT
        assert supplied_root == wheelhouse_root
        assert supplied_manifest == wheelhouse
        assets_root.mkdir(parents=True)
        shutil.copytree(built_assets / "installed", assets_root / "installed")
        return {
            **built,
            "wheel": wheelhouse["kokoroarc_wheel"],
            "wheelhouse": wheelhouse,
            "smoke": {"passed": True},
        }

    monkeypatch.setattr(
        runner.preparation,
        "install_frozen_distribution",
        frozen_install,
    )

    def fixture_build(
        repository_root: Path,
        assets_root: Path,
        *,
        installed_root: Path,
        python_executable: str,
        base_environment: dict[str, str] | None,
    ) -> Path:
        nonlocal fixture_calls
        fixture_calls += 1
        assert repository_root == REPOSITORY_ROOT
        assert installed_root == raw_root / "harness" / "distribution" / "installed"
        assert python_executable == sys.executable
        assert base_environment is None
        return runner.preparation.build_fixture_assets(repository_root, assets_root)

    monkeypatch.setattr(
        runner.preparation,
        "build_fixture_assets_isolated",
        fixture_build,
    )
    approved = runner.ApprovedCampaign(
        campaign=campaign,
        cases=cases,
        plan=plan,
        raw_root=raw_root,
        campaign_sha256="1" * 64,
        envelope_sha256="2" * 64,
        wheel=wheelhouse["kokoroarc_wheel"],
        runtime_wheelhouse=wheelhouse,
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
    assert manifest["distribution"]["wheelhouse"] == wheelhouse
    assert install_calls == 1
    assert fixture_calls == 1
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
    assert command.count("--approve-for-me") == 1
    assert "--sandbox" not in command
    assert "--sandbox" not in spec.safe_command
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


def test_directory_artifact_approved_policy_filesystem_roots_are_exact(
    tmp_path: Path,
) -> None:
    case_root = tmp_path / "case"
    workspace = case_root / "workspace"

    assert runner._approved_policy_filesystem_roots(case_root) == (
        workspace,
        workspace / "data" / "compiled",
        workspace / "data" / "reports",
        workspace / "outputs",
    )


def test_directory_artifact_pre_and_post_state_keys_are_closed_v1(
    tmp_path: Path,
) -> None:
    case_root = _prepared_case(tmp_path)
    raw = case_root / "raw"
    pre_path = raw / "pre-run-state.json"
    pre = json.loads(pre_path.read_text(encoding="utf-8"))
    expected_pre_keys = {
        "schema_version",
        "ordinal",
        "variant",
        "case_id",
        "case_root_identity",
        "workspace_root_identity",
        "runtime_root_identity",
        "raw_root_identity",
        "prompt_sha256",
        "output_schema_sha256",
        "workspace_before",
        "immutable_before",
        "preexisting_outputs",
        "policy_filesystem_roots",
    }
    assert set(pre) == expected_pre_keys

    pre["unexpected"] = True
    with pytest.raises(RuntimeError, match="closed v1"):
        runner._validate_pre_run_state(
            case_root,
            runner.RunSpec(1, "baseline", "example-case"),
            pre,
        )

    post = {
        "schema_version": "1.0",
        "variant": "baseline",
        "case_id": "example-case",
        "workspace_after": {},
        "immutable_after": {},
        "preexisting_outputs_after": {},
        "root_identities_after": {},
        "policy_filesystem_roots": [],
        "created_paths": [],
        "changed_paths": [],
        "removed_paths": [],
        "raw_inputs_before": {},
        "raw_inputs_after": {},
        "raw_inputs_unchanged": True,
    }
    expected_post_keys = set(post)
    runner._validate_post_run_state(post)
    post["unexpected"] = True
    with pytest.raises(RuntimeError, match="closed v1"):
        runner._validate_post_run_state(post)
    assert expected_post_keys == {
        "schema_version",
        "variant",
        "case_id",
        "workspace_after",
        "immutable_after",
        "preexisting_outputs_after",
        "root_identities_after",
        "policy_filesystem_roots",
        "created_paths",
        "changed_paths",
        "removed_paths",
        "raw_inputs_before",
        "raw_inputs_after",
        "raw_inputs_unchanged",
    }


def test_directory_artifact_snapshot_capture_brackets_all_runner_root_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_root = tmp_path / "case"
    identities = {
        "case_root_identity": {"inode": 1},
        "workspace_root_identity": {"inode": 2},
        "runtime_root_identity": {"inode": 3},
        "raw_root_identity": {"inode": 4},
    }
    calls: list[str] = []

    def capture_identities(observed_case_root: Path) -> dict[str, object]:
        assert observed_case_root == case_root
        calls.append("identities")
        return dict(identities)

    def capture_roots(observed_case_root: Path) -> tuple[object, ...]:
        assert observed_case_root == case_root
        calls.append("snapshot")
        return ()

    monkeypatch.setattr(runner, "_runner_root_identities", capture_identities)
    monkeypatch.setattr(runner, "_capture_policy_filesystem_roots", capture_roots)

    for _ in range(2):
        snapshots, observed = runner._capture_bracketed_policy_filesystem_roots(
            case_root
        )
        assert snapshots == ()
        assert observed == identities

    assert calls == [
        "identities",
        "snapshot",
        "identities",
        "identities",
        "snapshot",
        "identities",
    ]


def test_directory_artifact_snapshot_capture_rejects_bracketed_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_root = tmp_path / "case"
    identities = [
        {
            "case_root_identity": {"inode": 1},
            "workspace_root_identity": {"inode": 2},
            "runtime_root_identity": {"inode": 3},
            "raw_root_identity": {"inode": 4},
        },
        {
            "case_root_identity": {"inode": 1},
            "workspace_root_identity": {"inode": 2},
            "runtime_root_identity": {"inode": 3},
            "raw_root_identity": {"inode": 5},
        },
    ]

    monkeypatch.setattr(
        runner,
        "_runner_root_identities",
        lambda _case_root: identities.pop(0),
    )
    monkeypatch.setattr(
        runner,
        "_capture_policy_filesystem_roots",
        lambda _case_root: (),
    )

    with pytest.raises(RuntimeError, match="identity changed during capture"):
        runner._capture_bracketed_policy_filesystem_roots(case_root)


def test_directory_artifact_one_shot_run_retains_raw_evidence_and_policy_filesystem_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_root = _prepared_case(tmp_path, seed_policy_artifacts=True)
    workspace = case_root / "workspace"
    response_text = _canonical_bytes(_final_response()).decode("utf-8")
    popen_calls = 0
    bracket_calls = 0
    original_bracketed_capture = runner._capture_bracketed_policy_filesystem_roots

    def traced_bracketed_capture(case: Path):
        nonlocal bracket_calls
        bracket_calls += 1
        return original_bracketed_capture(case)

    monkeypatch.setattr(
        runner,
        "_capture_bracketed_policy_filesystem_roots",
        traced_bracketed_capture,
    )

    class FakeProcess:
        returncode = 0

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            nonlocal popen_calls
            popen_calls += 1
            self.command = command
            self.stdout = kwargs["stdout"]
            self.stderr = kwargs["stderr"]
            pre = json.loads(
                (case_root / "raw" / "pre-run-state.json").read_text(
                    encoding="utf-8"
                )
            )
            assert tuple(
                root["relative_root"] for root in pre["policy_filesystem_roots"]
            ) == (
                "workspace",
                r"workspace\data\compiled",
                r"workspace\data\reports",
                r"workspace\outputs",
            )
            assert pre["policy_filesystem_roots"][-1]["present"] is False
            assert set(pre) == {
                "schema_version",
                "ordinal",
                "variant",
                "case_id",
                "case_root_identity",
                "workspace_root_identity",
                "runtime_root_identity",
                "raw_root_identity",
                "prompt_sha256",
                "output_schema_sha256",
                "workspace_before",
                "immutable_before",
                "preexisting_outputs",
                "policy_filesystem_roots",
            }
            assert not (case_root / "raw" / "post-run-state.json").exists()

        def communicate(
            self,
            input: bytes | None = None,
            timeout: float | None = None,
        ) -> tuple[None, None]:
            assert input == (case_root / "raw" / "prompt.md").read_bytes()
            assert timeout == runner.RUN_TIMEOUT_SECONDS
            (workspace / "outputs").mkdir()
            _write_json(workspace / "outputs" / "result.json", {"ok": True})
            (workspace / "outputs" / "nested").mkdir()
            (workspace / "outputs" / "nested" / "new.txt").write_bytes(b"new\n")
            (
                workspace / "data" / "compiled" / "changed-dir" / "value.txt"
            ).write_bytes(b"after\n")
            shutil.rmtree(workspace / "data" / "reports" / "removed-dir")
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
    assert bracket_calls == 2
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
    assert tuple(
        root["relative_root"] for root in post["policy_filesystem_roots"]
    ) == (
        "workspace",
        r"workspace\data\compiled",
        r"workspace\data\reports",
        r"workspace\outputs",
    )
    assert post["policy_filesystem_roots"][-1]["present"] is True
    assert {
        r"workspace\outputs",
        r"workspace\outputs\nested",
        r"workspace\outputs\nested\new.txt",
        r"workspace\outputs\result.json",
    }.issubset(post["created_paths"])
    assert post["changed_paths"] == [
        r"workspace\data\compiled\changed-dir\value.txt"
    ]
    assert post["removed_paths"] == [
        r"workspace\data\reports\removed-dir",
        r"workspace\data\reports\removed-dir\old.txt",
    ]
    assert set(post) == {
        "schema_version",
        "variant",
        "case_id",
        "workspace_after",
        "immutable_after",
        "preexisting_outputs_after",
        "root_identities_after",
        "policy_filesystem_roots",
        "created_paths",
        "changed_paths",
        "removed_paths",
        "raw_inputs_before",
        "raw_inputs_after",
        "raw_inputs_unchanged",
    }
    declaration = json.loads((raw / "command.json").read_text(encoding="utf-8"))
    assert declaration["argv"][0] == "<CODEX>"
    private = json.loads(
        (raw / "launch-private.json").read_text(encoding="utf-8")
    )
    assert private["argv"][0] == r"D:\tools\codex.exe"
    assert private["launcher_environment"]["TMP"].startswith(str(case_root))


def test_policy_filesystem_roots_reject_unexpected_preexisting_output_before_spawn(
    tmp_path: Path,
) -> None:
    case_root = _prepared_case(tmp_path)
    (case_root / "workspace" / "outputs").mkdir()
    called = False

    def forbidden_popen(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("drifted policy root attempted to spawn")

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
