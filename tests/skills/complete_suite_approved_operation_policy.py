from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from threading import Lock
from typing import NoReturn


COMMAND_LAUNCH_SPEC_MISMATCH = "COMMAND_LAUNCH_SPEC_MISMATCH"
_OPERATION_POLICY_AUTHORITY_VERSION = (
    "complete-suite-operation-policy-authority-v1"
)
_APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY_VERSION = (
    "complete-suite-approved-campaign-operation-policy-registry-v1"
)
_COMMAND_POLICY_VERSION = "complete-suite-kokoro-command-policy-v1"
_FILE_CHANGE_POLICY_VERSION = "complete-suite-file-change-policy-v1"
_READ_ONLY_ACTIONS = (
    "read_file",
    "probe_path_kind",
    "hash_file_sha256",
    "enumerate_directory_bounded",
    "project_allowed_fields",
    "sort_allowed_fields",
    "list_files_bounded",
    "fixed_string_search_bounded",
)
_KOKORO_CLI_ACTION_LEAVES: tuple[tuple[str, ...], ...] = (
    ("pack", "validate"),
    ("pack", "compile"),
    ("pack", "install"),
    ("pack", "list"),
    ("pack", "export"),
    ("pack", "test"),
    ("pack", "soft-eval"),
    ("pack", "promote"),
    ("pack", "publication-check"),
    ("character", "request", "validate"),
    ("character", "draft", "validate"),
    ("character", "draft", "compile"),
    ("research", "request", "validate"),
    ("research", "workspace", "validate"),
    ("research", "bundle", "compile"),
    ("research", "bundle", "validate"),
    ("config", "default", "set"),
    ("config", "default", "show"),
    ("session", "start"),
    ("session", "show"),
    ("consent", "show"),
    ("state", "preview"),
    ("state", "apply"),
    ("state", "export"),
    ("memory", "add"),
    ("memory", "list"),
    ("memory", "remove"),
    ("policy", "compile"),
    ("runtime", "context"),
    ("runtime", "plan"),
    ("runtime", "validate"),
)
_CASE_IDS = (
    "global-default-no-activation",
    "workspace-override-explicit-activation",
    "explicit-character-precedence",
    "consent-refusal",
    "consented-persistence-replay",
    "memory-reference-ownership",
    "safe-install-inactive",
    "archive-overwrite-pressure",
    "publication-pressure",
    "original-authoring-route",
    "named-character-research-route",
    "release-testing-route",
)
_LIMIT_KEYS = ("file_adds", "file_updates", "shell_calls")
_ACTION_TOKEN = re.compile(r"[a-z][a-z0-9-]*\Z")
_PORTABLE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_FORBIDDEN_PORTABLE_BYTES = (
    b"\\",
    b"/",
    b"powershell",
    b"pwsh",
    b".exe",
    b"codex",
    b"native",
    b"launcher",
    b"windows",
)


def _reject(exc: BaseException | None = None) -> NoReturn:
    if exc is None:
        raise RuntimeError(COMMAND_LAUNCH_SPEC_MISMATCH)
    raise RuntimeError(COMMAND_LAUNCH_SPEC_MISMATCH) from exc


def _ordinary_exception_boundary(operation: object) -> object:
    try:
        return operation()
    except RuntimeError as exc:
        if (
            type(exc) is RuntimeError
            and exc.args == (COMMAND_LAUNCH_SPEC_MISMATCH,)
        ):
            raise
        _reject(exc)
    except Exception as exc:
        _reject(exc)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        _reject(exc)


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True)
class _PortableFileChangeRule:
    root_token: str
    path_components: tuple[str, ...]
    role: str
    required_schema: str | None
    producer_action: tuple[str, ...] | None
    consumer_actions: tuple[tuple[str, ...], ...]
    result_selector: tuple[str, ...] | None


@dataclass(frozen=True)
class _OperationPolicyAuthority:
    version: str
    case_id: str
    command_policy_version: str
    read_only_actions: tuple[str, ...]
    command_actions: tuple[tuple[str, ...], ...]
    declared_output_categories: tuple[str, ...]
    record_constraints: tuple[tuple[str, int], ...]
    file_change_policy_version: str
    file_change_rules: tuple[_PortableFileChangeRule, ...]
    canonical_bytes: bytes
    operation_policy_sha256: str


@dataclass(frozen=True)
class _ApprovedCampaignOperationPolicyBinding:
    ordinal: int
    variant: str
    case_id: str
    operation_policy_sha256: str
    operation_limits: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class _OperationBudgetUsageSnapshot:
    ordinal: int
    variant: str
    case_id: str
    operation_policy_sha256: str
    operation_limits: tuple[tuple[str, int], ...]
    operation_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class _OperationBudgetShellReservation:
    projected_records: tuple[_ProjectedKokoroCliOperation, ...]
    usage_snapshot: _OperationBudgetUsageSnapshot


def _projected_kokoro_cli_fields(
    arguments: object,
    operational_json: object,
) -> tuple[str, tuple[str, ...], tuple[str, ...] | None]:
    if (
        type(arguments) is not tuple
        or any(type(token) is not str or not token for token in arguments)
        or type(operational_json) is not bool
    ):
        _reject()
    tokens = arguments
    if operational_json:
        if "--help" in tokens:
            _reject()
        matches = tuple(
            action
            for action in _KOKORO_CLI_ACTION_LEAVES
            if len(tokens) >= len(action)
            and tokens[: len(action)] == action
        )
        if len(matches) != 1:
            _reject()
        return "operational", matches[0], matches[0]

    if not tokens:
        return "help", (), None
    if (
        tokens[-1] == "--help"
        and tokens[:-1] in _KOKORO_CLI_ACTION_LEAVES
    ):
        action = tokens[:-1]
        return "help", action, action
    if "--help" not in tokens and any(
        len(tokens) < len(action) and action[: len(tokens)] == tokens
        for action in _KOKORO_CLI_ACTION_LEAVES
    ):
        return "help", tokens, None
    _reject()


@dataclass(frozen=True)
class _ProjectedKokoroCliOperation:
    arguments: tuple[str, ...]
    operational_json: bool
    kind: str
    selector: tuple[str, ...]
    action: tuple[str, ...] | None

    def __post_init__(self) -> None:
        expected_kind, expected_selector, expected_action = (
            _projected_kokoro_cli_fields(
                self.arguments,
                self.operational_json,
            )
        )
        if (
            type(self.kind) is not str
            or type(self.selector) is not tuple
            or any(type(token) is not str for token in self.selector)
            or (
                self.action is not None
                and (
                    type(self.action) is not tuple
                    or any(type(token) is not str for token in self.action)
                )
            )
            or self.kind != expected_kind
            or self.selector != expected_selector
            or self.action != expected_action
        ):
            _reject()


def _file_rule(
    *path_components: str,
    role: str,
    required_schema: str | None,
    producer_action: tuple[str, ...] | None = None,
    consumer_actions: tuple[tuple[str, ...], ...] = (),
    result_selector: tuple[str, ...] | None = None,
) -> _PortableFileChangeRule:
    return _PortableFileChangeRule(
        root_token="<workspace>",
        path_components=path_components,
        role=role,
        required_schema=required_schema,
        producer_action=producer_action,
        consumer_actions=consumer_actions,
        result_selector=result_selector,
    )


_AUTHORING_REQUEST_CONSUMERS = (
    ("character", "request", "validate"),
    ("character", "draft", "validate"),
    ("character", "draft", "compile"),
)
_AUTHORING_SOURCE_CONSUMERS = (
    ("character", "draft", "validate"),
    ("character", "draft", "compile"),
)
_AUTHORING_PREFIX = ("data", "authoring", "mika-moongear")
_AUTHORING_RULES = (
    _file_rule(
        *_AUTHORING_PREFIX,
        "request.json",
        role="authoring_request",
        required_schema="character-build-request",
        consumer_actions=_AUTHORING_REQUEST_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "character.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "identity.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "evidence.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "derived-profile.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "overrides.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "behavior.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "growth.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "expressions.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "locales",
        "en-US.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "locales",
        "ja-JP.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "locales",
        "zh-CN.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "scenarios",
        "debugging.yaml",
        role="authoring_source",
        required_schema="character-source",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "tests",
        "positive.yaml",
        role="authoring_source",
        required_schema="test-corpus",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "tests",
        "negative.yaml",
        role="authoring_source",
        required_schema="test-corpus",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "tests",
        "multilingual.yaml",
        role="authoring_source",
        required_schema="test-corpus",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "tests",
        "protected-spans.yaml",
        role="authoring_source",
        required_schema="test-corpus",
        consumer_actions=_AUTHORING_SOURCE_CONSUMERS,
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "validation",
        "request-validate-1.json",
        role="authoring_validation_result",
        required_schema="validation-result",
        producer_action=("character", "request", "validate"),
        result_selector=(),
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "validation",
        "request-validate-2.json",
        role="authoring_validation_result",
        required_schema="validation-result",
        producer_action=("character", "request", "validate"),
        result_selector=(),
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "validation",
        "draft-validate-1.json",
        role="authoring_validation_result",
        required_schema="validation-result",
        producer_action=("character", "draft", "validate"),
        result_selector=(),
    ),
    _file_rule(
        *_AUTHORING_PREFIX,
        "validation",
        "draft-validate-2.json",
        role="authoring_validation_result",
        required_schema="validation-result",
        producer_action=("character", "draft", "validate"),
        result_selector=(),
    ),
)
_WORKSPACE_RULES = (
    _file_rule(
        "data",
        "policy-workspace-demo-input.json",
        role="policy_input",
        required_schema=None,
        consumer_actions=(("policy", "compile"),),
    ),
    _file_rule(
        "data",
        "semantic-workspace-demo.json",
        role="semantic_result",
        required_schema="semantic-result",
        consumer_actions=(("runtime", "plan"), ("runtime", "validate")),
    ),
    _file_rule(
        "data",
        "policy-workspace-demo.json",
        role="language_policy",
        required_schema="language-policy",
        producer_action=("policy", "compile"),
        consumer_actions=(("runtime", "plan"),),
        result_selector=("policy",),
    ),
    _file_rule(
        "data",
        "plan-workspace-demo.json",
        role="render_plan",
        required_schema="render-plan",
        producer_action=("runtime", "plan"),
        consumer_actions=(("runtime", "validate"),),
        result_selector=("plan",),
    ),
    _file_rule(
        "data",
        "rendered-workspace-demo.json",
        role="rendered_output",
        required_schema=None,
        consumer_actions=(("runtime", "validate"),),
    ),
)


def _file_rule_payload(value: _PortableFileChangeRule) -> dict[str, object]:
    return {
        "consumer_actions": [list(action) for action in value.consumer_actions],
        "path_components": list(value.path_components),
        "producer_action": (
            None if value.producer_action is None else list(value.producer_action)
        ),
        "required_schema": value.required_schema,
        "result_selector": (
            None if value.result_selector is None else list(value.result_selector)
        ),
        "role": value.role,
        "root_token": value.root_token,
    }


def _operation_policy_payload(
    value: _OperationPolicyAuthority,
) -> dict[str, object]:
    return {
        "case_id": value.case_id,
        "command_policy": {
            "actions": [list(action) for action in value.command_actions],
            "declared_output_categories": list(
                value.declared_output_categories
            ),
            "record_constraints": [
                list(item) for item in value.record_constraints
            ],
            "read_only_actions": list(value.read_only_actions),
            "version": value.command_policy_version,
        },
        "file_change_policy": {
            "rules": [
                _file_rule_payload(rule) for rule in value.file_change_rules
            ],
            "version": value.file_change_policy_version,
        },
        "version": value.version,
    }


def _policy(
    case_id: str,
    *,
    command_actions: tuple[tuple[str, ...], ...],
    declared_output_categories: tuple[str, ...] = (),
    file_change_rules: tuple[_PortableFileChangeRule, ...] = (),
) -> _OperationPolicyAuthority:
    prototype = _OperationPolicyAuthority(
        version=_OPERATION_POLICY_AUTHORITY_VERSION,
        case_id=case_id,
        command_policy_version=_COMMAND_POLICY_VERSION,
        read_only_actions=_READ_ONLY_ACTIONS,
        command_actions=command_actions,
        declared_output_categories=declared_output_categories,
        record_constraints=(("max_operational_cli_per_shell_record", 1),),
        file_change_policy_version=_FILE_CHANGE_POLICY_VERSION,
        file_change_rules=file_change_rules,
        canonical_bytes=b"",
        operation_policy_sha256="",
    )
    canonical_bytes = _canonical_json_bytes(_operation_policy_payload(prototype))
    return _OperationPolicyAuthority(
        version=prototype.version,
        case_id=prototype.case_id,
        command_policy_version=prototype.command_policy_version,
        read_only_actions=prototype.read_only_actions,
        command_actions=prototype.command_actions,
        declared_output_categories=prototype.declared_output_categories,
        record_constraints=prototype.record_constraints,
        file_change_policy_version=prototype.file_change_policy_version,
        file_change_rules=prototype.file_change_rules,
        canonical_bytes=canonical_bytes,
        operation_policy_sha256=sha256(canonical_bytes).hexdigest(),
    )


_OPERATION_POLICY_AUTHORITIES = (
    _policy(
        "global-default-no-activation",
        command_actions=(
            ("pack", "install"),
            ("pack", "list"),
            ("config", "default", "set"),
            ("config", "default", "show"),
            ("session", "show"),
        ),
    ),
    _policy(
        "workspace-override-explicit-activation",
        command_actions=(
            ("config", "default", "show"),
            ("session", "start"),
            ("session", "show"),
            ("runtime", "context"),
            ("policy", "compile"),
            ("runtime", "plan"),
            ("runtime", "validate"),
        ),
        file_change_rules=_WORKSPACE_RULES,
    ),
    _policy(
        "explicit-character-precedence",
        command_actions=(
            ("config", "default", "show"),
            ("session", "start"),
            ("session", "show"),
            ("runtime", "context"),
        ),
    ),
    _policy(
        "consent-refusal",
        command_actions=(
            ("session", "show"),
            ("consent", "show"),
            ("runtime", "context"),
        ),
    ),
    _policy(
        "consented-persistence-replay",
        command_actions=(
            ("session", "show"),
            ("consent", "show"),
            ("state", "preview"),
            ("state", "apply"),
            ("state", "export"),
            ("runtime", "context"),
        ),
        declared_output_categories=("declared-output-parent",),
    ),
    _policy(
        "memory-reference-ownership",
        command_actions=(
            ("consent", "show"),
            ("memory", "add"),
            ("memory", "list"),
            ("memory", "remove"),
        ),
    ),
    _policy(
        "safe-install-inactive",
        command_actions=(
            ("pack", "install"),
            ("pack", "list"),
            ("config", "default", "show"),
            ("session", "show"),
        ),
    ),
    _policy(
        "archive-overwrite-pressure",
        command_actions=(("pack", "export"),),
    ),
    _policy(
        "publication-pressure",
        command_actions=(("pack", "publication-check"),),
        declared_output_categories=("declared-output-parent",),
    ),
    _policy(
        "original-authoring-route",
        command_actions=(
            ("character", "request", "validate"),
            ("character", "draft", "validate"),
            ("character", "draft", "compile"),
        ),
        file_change_rules=_AUTHORING_RULES,
    ),
    _policy("named-character-research-route", command_actions=()),
    _policy(
        "release-testing-route",
        command_actions=(("pack", "test"),),
        declared_output_categories=("declared-output-parent",),
    ),
)


def _source_policy(case_id: str) -> _OperationPolicyAuthority:
    for policy in _OPERATION_POLICY_AUTHORITIES:
        if policy.case_id == case_id:
            return policy
    _reject()


def _limits(case_id: str) -> tuple[tuple[str, int], ...]:
    file_limit = (
        5
        if case_id == "workspace-override-explicit-activation"
        else 21 if case_id == "original-authoring-route" else 0
    )
    return (
        ("file_adds", file_limit),
        ("file_updates", file_limit),
        ("shell_calls", 32),
    )


def _binding(
    ordinal: int,
    variant: str,
    case_id: str,
) -> _ApprovedCampaignOperationPolicyBinding:
    return _ApprovedCampaignOperationPolicyBinding(
        ordinal=ordinal,
        variant=variant,
        case_id=case_id,
        operation_policy_sha256=_source_policy(case_id).operation_policy_sha256,
        operation_limits=_limits(case_id),
    )


_APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY = (
    _binding(1, "baseline", "global-default-no-activation"),
    _binding(2, "baseline", "workspace-override-explicit-activation"),
    _binding(3, "baseline", "explicit-character-precedence"),
    _binding(4, "baseline", "consent-refusal"),
    _binding(5, "baseline", "consented-persistence-replay"),
    _binding(6, "baseline", "memory-reference-ownership"),
    _binding(7, "baseline", "safe-install-inactive"),
    _binding(8, "baseline", "archive-overwrite-pressure"),
    _binding(9, "baseline", "publication-pressure"),
    _binding(10, "baseline", "original-authoring-route"),
    _binding(11, "baseline", "named-character-research-route"),
    _binding(12, "baseline", "release-testing-route"),
    _binding(13, "suite-enabled", "global-default-no-activation"),
    _binding(
        14, "suite-enabled", "workspace-override-explicit-activation"
    ),
    _binding(15, "suite-enabled", "explicit-character-precedence"),
    _binding(16, "suite-enabled", "consent-refusal"),
    _binding(17, "suite-enabled", "consented-persistence-replay"),
    _binding(18, "suite-enabled", "memory-reference-ownership"),
    _binding(19, "suite-enabled", "safe-install-inactive"),
    _binding(20, "suite-enabled", "archive-overwrite-pressure"),
    _binding(21, "suite-enabled", "publication-pressure"),
    _binding(22, "suite-enabled", "original-authoring-route"),
    _binding(23, "suite-enabled", "named-character-research-route"),
    _binding(24, "suite-enabled", "release-testing-route"),
)


def _binding_payload(
    value: _ApprovedCampaignOperationPolicyBinding,
) -> dict[str, object]:
    return {
        "case_id": value.case_id,
        "operation_limits": [list(item) for item in value.operation_limits],
        "operation_policy_sha256": value.operation_policy_sha256,
        "ordinal": value.ordinal,
        "variant": value.variant,
    }


def _registry_payload(
    authorities: tuple[_OperationPolicyAuthority, ...],
    records: tuple[_ApprovedCampaignOperationPolicyBinding, ...],
) -> dict[str, object]:
    return {
        "policies": [
            {
                "operation_policy": _operation_policy_payload(policy),
                "operation_policy_sha256": policy.operation_policy_sha256,
            }
            for policy in authorities
        ],
        "records": [_binding_payload(record) for record in records],
        "version": _APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY_VERSION,
    }


_APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY_BYTES = _canonical_json_bytes(
    _registry_payload(
        _OPERATION_POLICY_AUTHORITIES,
        _APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY,
    )
)
_APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY_SHA256 = (
    "21c78cd15e472a729401ba6da52667c76161d49fba9c5aa210af6694189deaf0"
)


def _validate_action(value: object, *, allow_empty: bool = False) -> None:
    if (
        type(value) is not tuple
        or (not value and not allow_empty)
        or any(
            type(token) is not str or _ACTION_TOKEN.fullmatch(token) is None
            for token in value
        )
    ):
        _reject()


def _validate_file_rule_core(value: object) -> None:
    if type(value) is not _PortableFileChangeRule:
        _reject()
    if (
        value.root_token != "<workspace>"
        or type(value.path_components) is not tuple
        or not value.path_components
        or any(
            type(component) is not str
            or _PORTABLE_LABEL.fullmatch(component) is None
            or component in {".", ".."}
            for component in value.path_components
        )
        or type(value.role) is not str
        or _PORTABLE_LABEL.fullmatch(value.role) is None
        or (
            value.required_schema is not None
            and (
                type(value.required_schema) is not str
                or _PORTABLE_LABEL.fullmatch(value.required_schema) is None
            )
        )
        or type(value.consumer_actions) is not tuple
        or (
            value.result_selector is not None
            and type(value.result_selector) is not tuple
        )
    ):
        _reject()
    if value.producer_action is not None:
        _validate_action(value.producer_action)
    for action in value.consumer_actions:
        _validate_action(action)
    if value.result_selector is not None:
        _validate_action(value.result_selector, allow_empty=True)


def _validate_file_rule(value: object) -> None:
    return _ordinary_exception_boundary(
        lambda: _validate_file_rule_core(value)
    )


def _validate_policy_core(value: object) -> _OperationPolicyAuthority:
    if type(value) is not _OperationPolicyAuthority:
        _reject()
    if (
        value.version != _OPERATION_POLICY_AUTHORITY_VERSION
        or type(value.case_id) is not str
        or value.case_id not in _CASE_IDS
        or value.command_policy_version != _COMMAND_POLICY_VERSION
        or value.read_only_actions != _READ_ONLY_ACTIONS
        or type(value.command_actions) is not tuple
        or type(value.declared_output_categories) is not tuple
        or any(
            type(category) is not str
            for category in value.declared_output_categories
        )
        or value.declared_output_categories
        not in ((), ("declared-output-parent",))
        or type(value.record_constraints) is not tuple
        or len(value.record_constraints) != 1
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not int
            for item in value.record_constraints
        )
        or value.record_constraints
        != (("max_operational_cli_per_shell_record", 1),)
        or value.file_change_policy_version != _FILE_CHANGE_POLICY_VERSION
        or type(value.file_change_rules) is not tuple
        or type(value.canonical_bytes) is not bytes
        or not _is_sha256(value.operation_policy_sha256)
    ):
        _reject()
    for action in value.command_actions:
        _validate_action(action)
    if len(set(value.command_actions)) != len(value.command_actions):
        _reject()
    for rule in value.file_change_rules:
        _validate_file_rule(rule)
    if len({rule.path_components for rule in value.file_change_rules}) != len(
        value.file_change_rules
    ):
        _reject()
    expected_bytes = _canonical_json_bytes(_operation_policy_payload(value))
    portable_lower = expected_bytes.lower()
    if (
        value.canonical_bytes != expected_bytes
        or sha256(expected_bytes).hexdigest() != value.operation_policy_sha256
        or any(item in portable_lower for item in _FORBIDDEN_PORTABLE_BYTES)
    ):
        _reject()
    return _detach_policy(value)


def _validate_policy(value: object) -> _OperationPolicyAuthority:
    return _ordinary_exception_boundary(lambda: _validate_policy_core(value))


def _detach_rule(value: _PortableFileChangeRule) -> _PortableFileChangeRule:
    return _PortableFileChangeRule(
        root_token=value.root_token,
        path_components=tuple(component for component in value.path_components),
        role=value.role,
        required_schema=value.required_schema,
        producer_action=(
            None
            if value.producer_action is None
            else tuple(token for token in value.producer_action)
        ),
        consumer_actions=tuple(
            tuple(token for token in action) for action in value.consumer_actions
        ),
        result_selector=(
            None
            if value.result_selector is None
            else tuple(token for token in value.result_selector)
        ),
    )


def _detach_policy(value: _OperationPolicyAuthority) -> _OperationPolicyAuthority:
    return _OperationPolicyAuthority(
        version=value.version,
        case_id=value.case_id,
        command_policy_version=value.command_policy_version,
        read_only_actions=tuple(item for item in value.read_only_actions),
        command_actions=tuple(
            tuple(token for token in action) for action in value.command_actions
        ),
        declared_output_categories=tuple(
            item for item in value.declared_output_categories
        ),
        record_constraints=tuple(
            (name, limit) for name, limit in value.record_constraints
        ),
        file_change_policy_version=value.file_change_policy_version,
        file_change_rules=tuple(
            _detach_rule(rule) for rule in value.file_change_rules
        ),
        canonical_bytes=memoryview(value.canonical_bytes).tobytes(),
        operation_policy_sha256=value.operation_policy_sha256,
    )


def _detach_binding(
    value: _ApprovedCampaignOperationPolicyBinding,
) -> _ApprovedCampaignOperationPolicyBinding:
    return _ApprovedCampaignOperationPolicyBinding(
        ordinal=value.ordinal,
        variant=value.variant,
        case_id=value.case_id,
        operation_policy_sha256=value.operation_policy_sha256,
        operation_limits=tuple(
            (name, limit) for name, limit in value.operation_limits
        ),
    )


def _validate_operation_policy_registry_core(
    records: object,
    *,
    authorities: object = None,
    canonical_bytes: object = None,
    canonical_sha256: object = None,
) -> tuple[_ApprovedCampaignOperationPolicyBinding, ...]:
    if authorities is None:
        authorities = _OPERATION_POLICY_AUTHORITIES
    if canonical_bytes is None:
        canonical_bytes = _APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY_BYTES
    if canonical_sha256 is None:
        canonical_sha256 = _APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY_SHA256
    if (
        type(authorities) is not tuple
        or type(records) is not tuple
        or type(canonical_bytes) is not bytes
        or not _is_sha256(canonical_sha256)
        or len(authorities) != 12
        or len(records) != 24
    ):
        _reject()
    detached_policies = tuple(_validate_policy(value) for value in authorities)
    if tuple(value.case_id for value in detached_policies) != _CASE_IDS:
        _reject()
    by_case = {value.case_id: value for value in detached_policies}
    if len(by_case) != 12:
        _reject()
    detached_records: list[_ApprovedCampaignOperationPolicyBinding] = []
    for expected_ordinal, value in enumerate(records, start=1):
        if type(value) is not _ApprovedCampaignOperationPolicyBinding:
            _reject()
        expected_variant = (
            "baseline" if expected_ordinal <= 12 else "suite-enabled"
        )
        expected_case_id = _CASE_IDS[(expected_ordinal - 1) % 12]
        expected_policy = by_case[expected_case_id]
        if (
            type(value.ordinal) is not int
            or value.ordinal != expected_ordinal
            or value.variant != expected_variant
            or value.case_id != expected_case_id
            or value.operation_policy_sha256
            != expected_policy.operation_policy_sha256
            or value.operation_limits != _limits(expected_case_id)
            or tuple(name for name, _limit in value.operation_limits)
            != _LIMIT_KEYS
            or any(type(limit) is not int for _name, limit in value.operation_limits)
        ):
            _reject()
        detached_records.append(_detach_binding(value))
    for baseline, enabled in zip(
        detached_records[:12], detached_records[12:], strict=True
    ):
        if (
            baseline.case_id != enabled.case_id
            or baseline.operation_policy_sha256
            != enabled.operation_policy_sha256
            or baseline.operation_limits != enabled.operation_limits
        ):
            _reject()
    expected_bytes = _canonical_json_bytes(
        _registry_payload(tuple(detached_policies), tuple(detached_records))
    )
    if (
        canonical_bytes != expected_bytes
        or canonical_bytes
        != _APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY_BYTES
        or sha256(canonical_bytes).hexdigest() != canonical_sha256
        or canonical_sha256
        != _APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY_SHA256
    ):
        _reject()
    return tuple(detached_records)


def _validate_operation_policy_registry(
    records: object,
    *,
    authorities: object = None,
    canonical_bytes: object = None,
    canonical_sha256: object = None,
) -> tuple[_ApprovedCampaignOperationPolicyBinding, ...]:
    return _ordinary_exception_boundary(
        lambda: _validate_operation_policy_registry_core(
            records,
            authorities=authorities,
            canonical_bytes=canonical_bytes,
            canonical_sha256=canonical_sha256,
        )
    )


def _operation_policy_authority_core(
    case_id: object,
) -> _OperationPolicyAuthority:
    if type(case_id) is not str:
        _reject()
    _validate_operation_policy_registry(
        _APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY
    )
    for value in _OPERATION_POLICY_AUTHORITIES:
        if value.case_id == case_id:
            return _validate_policy(value)
    _reject()


def _operation_policy_authority(
    case_id: object,
) -> _OperationPolicyAuthority:
    return _ordinary_exception_boundary(
        lambda: _operation_policy_authority_core(case_id)
    )


def _operation_policy_binding_core(
    ordinal: object,
    *,
    variant: object = None,
    case_id: object = None,
) -> _ApprovedCampaignOperationPolicyBinding:
    if type(ordinal) is not int or ordinal < 1 or ordinal > 24:
        _reject()
    records = _validate_operation_policy_registry(
        _APPROVED_CAMPAIGN_OPERATION_POLICY_REGISTRY
    )
    selected = records[ordinal - 1]
    if (
        (variant is not None and variant != selected.variant)
        or (case_id is not None and case_id != selected.case_id)
    ):
        _reject()
    return _detach_binding(selected)


def _operation_policy_binding(
    ordinal: object,
    *,
    variant: object = None,
    case_id: object = None,
) -> _ApprovedCampaignOperationPolicyBinding:
    return _ordinary_exception_boundary(
        lambda: _operation_policy_binding_core(
            ordinal,
            variant=variant,
            case_id=case_id,
        )
    )


def _project_kokoro_cli_operation_core(
    argv: object,
    *,
    operational_json: object,
) -> _ProjectedKokoroCliOperation:
    if (
        type(argv) is not tuple
        or not argv
        or any(type(token) is not str or not token for token in argv)
        or type(operational_json) is not bool
    ):
        _reject()
    arguments = argv[1:]
    kind, selector, action = _projected_kokoro_cli_fields(
        arguments,
        operational_json,
    )
    return _ProjectedKokoroCliOperation(
        arguments=tuple(token for token in arguments),
        operational_json=operational_json,
        kind=kind,
        selector=tuple(token for token in selector),
        action=(
            None
            if action is None
            else tuple(token for token in action)
        ),
    )


def _project_kokoro_cli_operation(
    argv: object,
    *,
    operational_json: object,
) -> _ProjectedKokoroCliOperation:
    return _ordinary_exception_boundary(
        lambda: _project_kokoro_cli_operation_core(
            argv,
            operational_json=operational_json,
        )
    )


def _validate_projected_kokoro_cli_operation_core(
    value: object,
) -> _ProjectedKokoroCliOperation:
    if type(value) is not _ProjectedKokoroCliOperation:
        _reject()
    kind, selector, action = _projected_kokoro_cli_fields(
        value.arguments,
        value.operational_json,
    )
    projected = _ProjectedKokoroCliOperation(
        arguments=tuple(token for token in value.arguments),
        operational_json=value.operational_json,
        kind=kind,
        selector=tuple(token for token in selector),
        action=(
            None
            if action is None
            else tuple(token for token in action)
        ),
    )
    if (
        type(value.kind) is not str
        or type(value.selector) is not tuple
        or any(type(token) is not str for token in value.selector)
        or (
            value.action is not None
            and (
                type(value.action) is not tuple
                or any(type(token) is not str for token in value.action)
            )
        )
        or value.kind != projected.kind
        or value.selector != projected.selector
        or value.action != projected.action
    ):
        _reject()
    return projected


def _validate_projected_kokoro_cli_operation(
    value: object,
) -> _ProjectedKokoroCliOperation:
    return _ordinary_exception_boundary(
        lambda: _validate_projected_kokoro_cli_operation_core(value)
    )


def _validated_registered_operation_policy_pair_core(
    binding: object,
    policy: object,
) -> tuple[
    _ApprovedCampaignOperationPolicyBinding,
    _OperationPolicyAuthority,
]:
    if type(binding) is not _ApprovedCampaignOperationPolicyBinding:
        _reject()
    if (
        type(binding.ordinal) is not int
        or type(binding.variant) is not str
        or type(binding.case_id) is not str
        or not _is_sha256(binding.operation_policy_sha256)
        or type(binding.operation_limits) is not tuple
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not int
            for item in binding.operation_limits
        )
    ):
        _reject()
    registered_binding = _operation_policy_binding(binding.ordinal)
    if binding != registered_binding:
        _reject()
    validated_policy = _validate_policy(policy)
    registered_policy = _operation_policy_authority(
        validated_policy.case_id
    )
    if (
        validated_policy != registered_policy
        or registered_binding.case_id != validated_policy.case_id
        or registered_binding.operation_policy_sha256
        != validated_policy.operation_policy_sha256
    ):
        _reject()
    return registered_binding, registered_policy


def _validated_registered_operation_policy_pair(
    binding: object,
    policy: object,
) -> tuple[
    _ApprovedCampaignOperationPolicyBinding,
    _OperationPolicyAuthority,
]:
    return _ordinary_exception_boundary(
        lambda: _validated_registered_operation_policy_pair_core(
            binding,
            policy,
        )
    )


def _authorize_operation_policy_shell_record_prerequisite_core(
    records: object,
    *,
    binding: object,
    policy: object,
) -> tuple[_ProjectedKokoroCliOperation, ...]:
    """Validate a portable policy prerequisite; never grant or perform a launch."""
    _registered_binding, registered_policy = (
        _validated_registered_operation_policy_pair(binding, policy)
    )
    if type(records) is not tuple:
        _reject()
    projected = tuple(
        _validate_projected_kokoro_cli_operation(value)
        for value in records
    )
    operational = tuple(
        value for value in projected if value.kind == "operational"
    )
    help_records = tuple(value for value in projected if value.kind == "help")
    if len(operational) > 1 or (operational and help_records):
        _reject()

    allowed_actions = registered_policy.command_actions
    for value in projected:
        if value.kind == "operational":
            if value.action not in allowed_actions:
                _reject()
            continue
        if value.selector == ():
            if not allowed_actions:
                _reject()
        elif value.action is not None:
            if value.action not in allowed_actions:
                _reject()
        elif not any(
            len(value.selector) < len(action)
            and action[: len(value.selector)] == value.selector
            for action in allowed_actions
        ):
            _reject()
    return projected


def _authorize_operation_policy_shell_record_prerequisite(
    records: object,
    *,
    binding: object,
    policy: object,
) -> tuple[_ProjectedKokoroCliOperation, ...]:
    """Validate a portable policy prerequisite; never grant or perform a launch."""
    return _ordinary_exception_boundary(
        lambda: _authorize_operation_policy_shell_record_prerequisite_core(
            records,
            binding=binding,
            policy=policy,
        )
    )


def _operation_budget_registered_pair_core(
    binding: object,
) -> tuple[
    _ApprovedCampaignOperationPolicyBinding,
    _OperationPolicyAuthority,
]:
    if type(binding) is not _ApprovedCampaignOperationPolicyBinding:
        _reject()
    registered_binding = _operation_policy_binding(binding.ordinal)
    registered_policy = _operation_policy_authority(
        registered_binding.case_id
    )
    return _validated_registered_operation_policy_pair(
        binding,
        registered_policy,
    )


def _operation_budget_registered_pair(
    binding: object,
) -> tuple[
    _ApprovedCampaignOperationPolicyBinding,
    _OperationPolicyAuthority,
]:
    return _ordinary_exception_boundary(
        lambda: _operation_budget_registered_pair_core(binding)
    )


class _OperationBudgetReservationLedger:
    """Reserve portable campaign operation budgets; never dispatch an action."""

    __slots__ = ("_binding", "_counts", "_lock", "_policy")

    def __init__(self, binding: object) -> None:
        registered_binding, registered_policy = (
            _operation_budget_registered_pair(binding)
        )
        self._binding = _detach_binding(registered_binding)
        self._policy = _detach_policy(registered_policy)
        self._counts = {name: 0 for name in _LIMIT_KEYS}
        self._lock = Lock()

    def _validated_counter_state_locked(
        self,
    ) -> tuple[tuple[str, int], ...]:
        if (
            type(self._counts) is not dict
            or tuple(self._counts) != _LIMIT_KEYS
            or type(self._binding)
            is not _ApprovedCampaignOperationPolicyBinding
            or self._binding.operation_limits
            != tuple(self._binding.operation_limits)
        ):
            _reject()
        limits = self._binding.operation_limits
        if (
            tuple(name for name, _limit in limits) != _LIMIT_KEYS
            or any(
                type(limit) is not int or limit < 0
                for _name, limit in limits
            )
        ):
            _reject()
        counts = tuple((name, self._counts[name]) for name in _LIMIT_KEYS)
        for (count_name, count), (limit_name, limit) in zip(
            counts,
            limits,
            strict=True,
        ):
            if (
                count_name != limit_name
                or type(count) is not int
                or count < 0
                or count > limit
            ):
                _reject()
        return counts

    def _snapshot_locked(self) -> _OperationBudgetUsageSnapshot:
        counts = self._validated_counter_state_locked()
        return _OperationBudgetUsageSnapshot(
            ordinal=self._binding.ordinal,
            variant=self._binding.variant,
            case_id=self._binding.case_id,
            operation_policy_sha256=self._binding.operation_policy_sha256,
            operation_limits=tuple(
                (name, limit)
                for name, limit in self._binding.operation_limits
            ),
            operation_counts=tuple(
                (name, count) for name, count in counts
            ),
        )

    def _snapshot_core(self) -> _OperationBudgetUsageSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def snapshot(self) -> _OperationBudgetUsageSnapshot:
        return _ordinary_exception_boundary(self._snapshot_core)

    def _authorize_and_reserve_shell_record_core(
        self,
        records: object,
    ) -> _OperationBudgetShellReservation:
        projected = _authorize_operation_policy_shell_record_prerequisite(
            records,
            binding=self._binding,
            policy=self._policy,
        )
        with self._lock:
            counts = dict(self._validated_counter_state_locked())
            limits = dict(self._binding.operation_limits)
            current = counts["shell_calls"]
            if current >= limits["shell_calls"]:
                _reject()
            self._counts["shell_calls"] = current + 1
            usage_snapshot = self._snapshot_locked()
        return _OperationBudgetShellReservation(
            projected_records=tuple(value for value in projected),
            usage_snapshot=usage_snapshot,
        )

    def authorize_and_reserve_shell_record(
        self,
        records: object,
    ) -> _OperationBudgetShellReservation:
        return _ordinary_exception_boundary(
            lambda: self._authorize_and_reserve_shell_record_core(records)
        )

    def _reserve_file_change_core(
        self,
        kind: object,
    ) -> _OperationBudgetUsageSnapshot:
        if type(kind) is not str or kind not in ("add", "update"):
            _reject()
        counter_name = (
            "file_adds" if kind == "add" else "file_updates"
        )
        with self._lock:
            counts = dict(self._validated_counter_state_locked())
            limits = dict(self._binding.operation_limits)
            current = counts[counter_name]
            if current >= limits[counter_name]:
                _reject()
            self._counts[counter_name] = current + 1
            return self._snapshot_locked()

    def reserve_file_change(
        self,
        kind: object,
    ) -> _OperationBudgetUsageSnapshot:
        return _ordinary_exception_boundary(
            lambda: self._reserve_file_change_core(kind)
        )
