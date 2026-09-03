"""Process-free validation for Campaign 6 guarded Python targets.

This module is loaded only from approval-bound bytes by the retained Task 9
loader.  Importing it defines closed validation helpers; it does not discover,
import, or execute target code.
"""

import hashlib
import json
import os
import sys


GUARDED_TARGET_ROLES = (
    "root_role_entrypoint",
    "pytest_capture",
    "compile_audit",
    "build_frontend",
    "build_backend_hook",
    "pip_install",
    "source_cli",
    "installed_cli",
    "installed_probe",
    "approval_bound_test_probe",
    "multiprocessing_worker",
    "validator_audit",
)

ROOT_ENTRYPOINT_ROLES = (
    "development-pytest",
    "client-preflight-freeze",
    "client-preflight-audit",
    "guarded-pytest-audit",
    "candidate-input-freeze",
    "candidate-input-audit",
    "pre-freeze-gate-audit",
    "release-gate-audit",
    "envelope-audit",
    "host-review-audit",
    "authorize-provider",
    "close-provider-authorization-failure",
    "execute",
    "sealed-campaign-audit",
    "import-campaign",
    "adjudicate-campaign",
    "closure-manifest-audit",
)

FORBIDDEN_ENVIRONMENT_NAMES = (
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONUSERBASE",
)

GUARDED_IMPORT_ROOT_ROLES = (
    "python_home",
    "stdlib_zip",
    "stdlib_dlls",
    "stdlib_lib",
    "runtime_site",
    "repository_src",
    "repository_tests",
    "repository_skills",
    "repository_integration",
    "installed_target",
    "validator_bundle",
)

ALLOWED_PYTHON_ENVIRONMENT_NAMES = (
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONHASHSEED",
    "PYTHONNOUSERSITE",
    "PYTHONSAFEPATH",
    "PYTHONUTF8",
)

GUARDED_BOOTSTRAP_INVALID = "GUARDED_BOOTSTRAP_INVALID"
UNKNOWN_IMPORT_ORIGIN = "unknown import origin"
_TARGET_REQUEST_KEYS = ("role", "root_entrypoint_role", "logical_argv")
_MAX_REQUEST_BYTES = 256 * 1024
_MAX_PATH_CHARS = 32_767
_MAX_ARGV_ITEMS = 256


def _reject(reason):
    if type(reason) is not str or not reason:
        reason = GUARDED_BOOTSTRAP_INVALID
    raise RuntimeError(reason)


def _clean_text(value, *, allow_empty=False, max_chars=_MAX_PATH_CHARS):
    if (
        type(value) is not str
        or (not allow_empty and not value)
        or len(value) > max_chars
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    return value


def _absolute_path(value):
    path = _clean_text(value)
    if not os.path.isabs(path):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    normalized = os.path.normpath(path)
    if normalized != path or not os.path.isabs(normalized):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    return normalized


def _path_key(value):
    return os.path.normcase(os.path.normpath(value))


def _path_components(value):
    return tuple(
        component.casefold()
        for component in value.replace("\\", "/").split("/")
        if component
    )


def _reject_implicit_import_path(value):
    components = _path_components(value)
    if any(
        component == "site-packages"
        or component == "__pycache__"
        or component.endswith(".pth")
        or component.endswith(".pyc")
        for component in components
    ):
        _reject(GUARDED_BOOTSTRAP_INVALID)


def validate_guarded_environment(environment):
    """Validate the descriptor's sorted, from-scratch environment pairs."""

    if type(environment) not in (list, tuple):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    pairs = []
    seen = set()
    forbidden = {name.casefold() for name in FORBIDDEN_ENVIRONMENT_NAMES}
    allowed_python = {
        name.casefold() for name in ALLOWED_PYTHON_ENVIRONMENT_NAMES
    }
    for item in environment:
        if type(item) not in (list, tuple) or len(item) != 2:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        name = _clean_text(item[0], max_chars=1_024)
        value = _clean_text(item[1], allow_empty=True, max_chars=32_767)
        if "=" in name:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        folded = name.casefold()
        if folded in seen or folded in forbidden:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if folded.startswith("python") and folded not in allowed_python:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        seen.add(folded)
        pairs.append((name, value))
    expected = tuple(sorted(pairs, key=lambda item: (item[0].casefold(), item[0])))
    if tuple(pairs) != expected:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    return expected


def validate_guarded_cwd(cwd):
    """Validate a bound cwd without turning it into an import root."""

    return _absolute_path(cwd)


def _import_root_record(value):
    role = None
    entries = ()
    if type(value) is str:
        path = value
    elif type(value) in (list, tuple) and len(value) == 2:
        role, path = value
    elif type(value) is dict:
        if "path" not in value or "role" not in value:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        role = value["role"]
        path = value["path"]
        entries = value.get("entries", ())
        if type(entries) not in (list, tuple):
            _reject(GUARDED_BOOTSTRAP_INVALID)
    else:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    if role is not None and role not in GUARDED_IMPORT_ROOT_ROLES:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    path = _absolute_path(path)
    _reject_implicit_import_path(path)
    for entry in entries:
        if type(entry) is dict:
            relative_path = entry.get("relative_path")
        else:
            relative_path = entry
        relative_path = _clean_text(relative_path)
        if os.path.isabs(relative_path):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        normalized = relative_path.replace("\\", "/")
        segments = normalized.split("/")
        if (
            normalized.startswith("/")
            or any(segment in ("", ".", "..") for segment in segments)
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        _reject_implicit_import_path(normalized)
    return role, path


def _origin_paths(value):
    if type(value) is str:
        return (value,)
    if type(value) in (list, tuple) and value:
        if any(type(item) is not str for item in value):
            _reject(UNKNOWN_IMPORT_ORIGIN)
        return tuple(value)
    _reject(UNKNOWN_IMPORT_ORIGIN)


def _origin_is_below(origin, root):
    try:
        return os.path.commonpath((_path_key(origin), _path_key(root))) == _path_key(
            root
        )
    except (OSError, ValueError):
        return False


def validate_guarded_import_roots(
    import_roots,
    loaded_origins,
    cwd,
    environment,
    active_sys_path=None,
):
    """Validate closed roots and already-loaded module origins without imports."""

    validate_guarded_environment(environment)
    validate_guarded_cwd(cwd)
    if type(import_roots) not in (list, tuple) or not import_roots:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    roots = []
    seen_paths = set()
    for raw_root in import_roots:
        role, path = _import_root_record(raw_root)
        key = _path_key(path)
        if key in seen_paths:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        seen_paths.add(key)
        roots.append((role, path))

    expected_paths = tuple(path for _role, path in roots)
    if active_sys_path is None:
        active_sys_path = tuple(sys.path)
    if type(active_sys_path) not in (list, tuple):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    if any(type(path) is not str or not path for path in active_sys_path):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    if tuple(_path_key(path) for path in active_sys_path) != tuple(
        _path_key(path) for path in expected_paths
    ):
        _reject(GUARDED_BOOTSTRAP_INVALID)

    if type(loaded_origins) is not dict:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    for module_name, raw_origin in loaded_origins.items():
        _clean_text(module_name, max_chars=1_024)
        for origin in _origin_paths(raw_origin):
            if origin in ("built-in", "frozen"):
                continue
            try:
                origin = _absolute_path(origin)
                _reject_implicit_import_path(origin)
            except RuntimeError:
                _reject(UNKNOWN_IMPORT_ORIGIN)
            if not any(_origin_is_below(origin, root) for root in expected_paths):
                _reject(UNKNOWN_IMPORT_ORIGIN)
    return tuple(roots)


def validate_guarded_target_request(role, root_entrypoint_role, logical_argv):
    """Validate a broker-derived logical request; do not execute it here."""

    if role not in GUARDED_TARGET_ROLES:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    if role == "root_role_entrypoint":
        if root_entrypoint_role not in ROOT_ENTRYPOINT_ROLES:
            _reject(GUARDED_BOOTSTRAP_INVALID)
    elif root_entrypoint_role is not None:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    if (
        type(logical_argv) not in (list, tuple)
        or not logical_argv
        or len(logical_argv) > _MAX_ARGV_ITEMS
    ):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    argv = tuple(_clean_text(item) for item in logical_argv)
    for item in argv:
        lowered = item.casefold()
        if lowered in ("-m", "-c") or lowered.endswith((".py", ".pyw")):
            _reject(GUARDED_BOOTSTRAP_INVALID)
    return role, root_entrypoint_role, argv


def _duplicate_key_object(pairs):
    value = {}
    for key, item in pairs:
        if type(key) is not str or key in value:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        value[key] = item
    return value


def _reject_json_constant(_value):
    _reject(GUARDED_BOOTSTRAP_INVALID)


def decode_guarded_target_request(payload, expected_sha256):
    """Strictly decode the small logical request schema and validate its values."""

    if (
        type(payload) is not bytes
        or not payload
        or len(payload) > _MAX_REQUEST_BYTES
        or not payload.endswith(b"\n")
        or b"\r" in payload
        or b"\x00" in payload
        or type(expected_sha256) is not str
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
        or hashlib.sha256(payload).hexdigest() != expected_sha256
    ):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    try:
        text = payload[:-1].decode("utf-8", errors="strict")
        request = json.loads(
            text,
            object_pairs_hook=_duplicate_key_object,
            parse_constant=_reject_json_constant,
        )
    except RuntimeError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise RuntimeError(GUARDED_BOOTSTRAP_INVALID) from exc
    if type(request) is not dict or tuple(request) != _TARGET_REQUEST_KEYS:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    canonical = json.dumps(
        request,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    if canonical != payload:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    return validate_guarded_target_request(
        request["role"],
        request["root_entrypoint_role"],
        request["logical_argv"],
    )


_C6_BROKER_NATIVE_CORE_DRAFT_VECTOR_CONTRACT = (
    "complete-suite-windows-native-vector-v1"
)
_C6_BROKER_NATIVE_CORE_DRAFT_IMPLEMENTATION_ID = "broker-native-core-v1"
_C6_BROKER_NATIVE_CORE_DRAFT_MAX_COMMAND_LINE_UNITS = 30_000
_C6_BROKER_NATIVE_CORE_DRAFT_LEAF_ATTRIBUTES = (
    "HANDLE_LIST",
    "JOB_LIST",
    "CHILD_PROCESS_POLICY=PROCESS_CREATION_CHILD_PROCESS_RESTRICTED",
)
_C6_BROKER_NATIVE_CORE_DRAFT_CLIENT_ATTRIBUTES = (
    "HANDLE_LIST",
    "JOB_LIST",
)
_C6_BROKER_NATIVE_CORE_DRAFT_POLICY_ROWS = (
    (
        "guarded-target-or-native-leaf",
        "guarded-python-target",
        _C6_BROKER_NATIVE_CORE_DRAFT_LEAF_ATTRIBUTES,
        "none",
    ),
    (
        "guarded-target-or-native-leaf",
        "native-leaf",
        _C6_BROKER_NATIVE_CORE_DRAFT_LEAF_ATTRIBUTES,
        "none",
    ),
    (
        "codex-client-root",
        "loopback-codex-client-root",
        _C6_BROKER_NATIVE_CORE_DRAFT_CLIENT_ATTRIBUTES,
        "unchanged-client-declared-descendants-only",
    ),
    (
        "codex-client-root",
        "approved-codex-client-root",
        _C6_BROKER_NATIVE_CORE_DRAFT_CLIENT_ATTRIBUTES,
        "unchanged-client-declared-descendants-only",
    ),
)
_C6_BROKER_NATIVE_CORE_DRAFT_IO_CHUNK_BYTES = 65_536
_C6_BROKER_NATIVE_CORE_DRAFT_DESCRIPTOR_TRANSPORT_PAYLOAD_CAP_BYTES = 4_194_304
_C6_BROKER_NATIVE_CORE_DRAFT_TARGET_DESCRIPTOR_SCHEMA_CAP_BYTES = 262_144
_C6_BROKER_NATIVE_CORE_DRAFT_CONTROL_FRAME_PAYLOAD_CAP_BYTES = 65_536
_C6_BROKER_NATIVE_CORE_DRAFT_IOCP_POLL_QUANTUM_MS = 50
_C6_BROKER_NATIVE_CORE_DRAFT_TERMINATION_GRACE_MS = 10_000
_C6_BROKER_NATIVE_CORE_DRAFT_PER_TARGET_BROKER_PAIR_COUNT = 1_024
_C6_BROKER_NATIVE_CORE_DRAFT_ROOT_AGGREGATE_BROKER_PAIR_COUNT = 4_096
_C6_BROKER_NATIVE_CORE_DRAFT_ONE_CONTROL_FRAME_WIRE_BYTES = 1 * (
    4 + _C6_BROKER_NATIVE_CORE_DRAFT_CONTROL_FRAME_PAYLOAD_CAP_BYTES
)
_C6_BROKER_NATIVE_CORE_DRAFT_ORDINARY_ACK_STATUS_WIRE_BYTES = 2 * (
    4 + _C6_BROKER_NATIVE_CORE_DRAFT_CONTROL_FRAME_PAYLOAD_CAP_BYTES
)
_C6_BROKER_NATIVE_CORE_DRAFT_EXECUTE_ACK_STATUS_WIRE_BYTES = 4 * (
    4 + _C6_BROKER_NATIVE_CORE_DRAFT_CONTROL_FRAME_PAYLOAD_CAP_BYTES
)
_C6_BROKER_NATIVE_CORE_DRAFT_PER_TARGET_BROKER_REQUEST_WIRE_BYTES = (
    _C6_BROKER_NATIVE_CORE_DRAFT_PER_TARGET_BROKER_PAIR_COUNT
    * (4 + _C6_BROKER_NATIVE_CORE_DRAFT_CONTROL_FRAME_PAYLOAD_CAP_BYTES)
)
_C6_BROKER_NATIVE_CORE_DRAFT_PER_TARGET_BROKER_RESPONSE_WIRE_BYTES = (
    _C6_BROKER_NATIVE_CORE_DRAFT_PER_TARGET_BROKER_PAIR_COUNT
    * (4 + _C6_BROKER_NATIVE_CORE_DRAFT_CONTROL_FRAME_PAYLOAD_CAP_BYTES)
)
_C6_BROKER_NATIVE_CORE_DRAFT_ROOT_AGGREGATE_BROKER_REQUEST_WIRE_BYTES = (
    _C6_BROKER_NATIVE_CORE_DRAFT_ROOT_AGGREGATE_BROKER_PAIR_COUNT
    * (4 + _C6_BROKER_NATIVE_CORE_DRAFT_CONTROL_FRAME_PAYLOAD_CAP_BYTES)
)
_C6_BROKER_NATIVE_CORE_DRAFT_ROOT_AGGREGATE_BROKER_RESPONSE_WIRE_BYTES = (
    _C6_BROKER_NATIVE_CORE_DRAFT_ROOT_AGGREGATE_BROKER_PAIR_COUNT
    * (4 + _C6_BROKER_NATIVE_CORE_DRAFT_CONTROL_FRAME_PAYLOAD_CAP_BYTES)
)


class _C6BrokerNativeCoreDraftNativeVector(tuple):
    __slots__ = ()

    def __new__(cls, contract, utf16_units, utf16le_sha256, command_line):
        return tuple.__new__(
            cls,
            (contract, utf16_units, utf16le_sha256, command_line),
        )

    @property
    def contract(self):
        return self[0]

    @property
    def utf16_units(self):
        return self[1]

    @property
    def utf16le_sha256(self):
        return self[2]

    @property
    def command_line(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftNativeVector("
            f"contract={self.contract!r}, "
            f"utf16_units={self.utf16_units!r}, "
            f"utf16le_sha256={self.utf16le_sha256!r})"
        )


class _C6BrokerNativeCoreDraftEnvironmentBlock(tuple):
    __slots__ = ()

    def __new__(
        cls,
        ordered_pairs,
        block_text,
        utf16_units,
        utf16le_byte_count,
        utf16le_sha256,
    ):
        return tuple.__new__(
            cls,
            (
                ordered_pairs,
                block_text,
                utf16_units,
                utf16le_byte_count,
                utf16le_sha256,
            ),
        )

    @property
    def ordered_pairs(self):
        return self[0]

    @property
    def block_text(self):
        return self[1]

    @property
    def utf16_units(self):
        return self[2]

    @property
    def utf16le_byte_count(self):
        return self[3]

    @property
    def utf16le_sha256(self):
        return self[4]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftEnvironmentBlock("
            f"pair_count={len(self.ordered_pairs)!r}, "
            f"utf16_units={self.utf16_units!r}, "
            f"utf16le_byte_count={self.utf16le_byte_count!r}, "
            f"utf16le_sha256={self.utf16le_sha256!r})"
        )


class _C6BrokerNativeCoreDraftPolicyProjection(tuple):
    __slots__ = ()

    def __new__(
        cls,
        implementation_id,
        constructor_class,
        subject_kind,
        attributes,
        direct_child_authority,
    ):
        return tuple.__new__(
            cls,
            (
                implementation_id,
                constructor_class,
                subject_kind,
                attributes,
                direct_child_authority,
            ),
        )

    @property
    def implementation_id(self):
        return self[0]

    @property
    def constructor_class(self):
        return self[1]

    @property
    def subject_kind(self):
        return self[2]

    @property
    def attributes(self):
        return self[3]

    @property
    def direct_child_authority(self):
        return self[4]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftPolicyProjection("
            f"implementation_id={self.implementation_id!r}, "
            f"constructor_class={self.constructor_class!r}, "
            f"subject_kind={self.subject_kind!r}, "
            f"attributes={self.attributes!r}, "
            f"direct_child_authority={self.direct_child_authority!r})"
        )


class _C6BrokerNativeCoreDraftLimitTable(tuple):
    __slots__ = ()

    def __new__(
        cls,
        table_id,
        field_names,
        rows,
        canonical_bytes,
        draft_sha256,
    ):
        if (
            cls is not _C6BrokerNativeCoreDraftLimitTable
            or type(table_id) is not str
            or type(field_names) is not tuple
            or type(rows) is not tuple
            or type(canonical_bytes) is not bytes
            or type(draft_sha256) is not str
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if (
            not table_id
            or len(field_names) < 2
            or not rows
            or any(type(field_name) is not str for field_name in field_names)
            or any(type(row) is not tuple for row in rows)
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(
            len(row) != len(field_names)
            or type(row[0]) is not str
            or any(type(value) is not int for value in row[1:])
            for row in rows
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if (
            field_names[0] != "role"
            or any(not field_name for field_name in field_names)
            or len(set(field_names)) != len(field_names)
            or any(not row[0] for row in rows)
            or len(set(row[0] for row in rows)) != len(rows)
            or len(draft_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in draft_sha256
            )
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        projected_rows = tuple(
            {
                field_name: row[index]
                for index, field_name in enumerate(field_names)
            }
            for row in rows
        )
        expected_canonical_bytes = json.dumps(
            projected_rows,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict") + b"\n"
        expected_draft_sha256 = hashlib.sha256(
            expected_canonical_bytes
        ).hexdigest()
        if (
            canonical_bytes != expected_canonical_bytes
            or draft_sha256 != expected_draft_sha256
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        return tuple.__new__(
            cls,
            (table_id, field_names, rows, canonical_bytes, draft_sha256),
        )

    @property
    def table_id(self):
        return self[0]

    @property
    def field_names(self):
        return self[1]

    @property
    def rows(self):
        return self[2]

    @property
    def canonical_bytes(self):
        return self[3]

    @property
    def draft_sha256(self):
        return self[4]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftLimitTable("
            f"table_id={self.table_id!r}, "
            f"row_count={len(self.rows)!r}, "
            f"draft_sha256={self.draft_sha256!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftLimitSelection(tuple):
    __slots__ = ()

    def __new__(cls, table_id, field_names, row, table_sha256):
        if (
            cls is not _C6BrokerNativeCoreDraftLimitSelection
            or type(table_id) is not str
            or type(field_names) is not tuple
            or type(row) is not tuple
            or type(table_sha256) is not str
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if (
            not table_id
            or len(field_names) < 2
            or any(type(field_name) is not str for field_name in field_names)
            or len(row) != len(field_names)
            or type(row[0]) is not str
            or any(type(value) is not int for value in row[1:])
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if (
            field_names[0] != "role"
            or any(not field_name for field_name in field_names)
            or len(set(field_names)) != len(field_names)
            or not row[0]
            or len(table_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in table_sha256
            )
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        return tuple.__new__(cls, (table_id, field_names, row, table_sha256))

    @property
    def table_id(self):
        return self[0]

    @property
    def field_names(self):
        return self[1]

    @property
    def row(self):
        return self[2]

    @property
    def table_sha256(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftLimitSelection("
            f"table_id={self.table_id!r}, "
            f"role={self.row[0]!r}, "
            f"table_sha256={self.table_sha256!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftConstructorAttributeRegistry(tuple):
    __slots__ = ()

    def __new__(cls, field_names, rows):
        if (
            cls is not _C6BrokerNativeCoreDraftConstructorAttributeRegistry
            or type(field_names) is not tuple
            or type(rows) is not tuple
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if (
            len(field_names) != 5
            or any(type(field_name) is not str for field_name in field_names)
            or len(rows) != 3
            or any(type(row) is not tuple for row in rows)
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(len(row) != 5 for row in rows):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(
            type(row[0]) is not str
            or type(row[1]) is not tuple
            or type(row[2]) is not tuple
            or type(row[3]) is not tuple
            or type(row[4]) is not str
            for row in rows
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(
            type(subject_kind) is not str
            for row in rows
            for subject_kind in row[1]
        ) or any(
            type(attribute_token) is not str
            for row in rows
            for attribute_token in row[3]
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(
            type(implementation_context) is not tuple
            for row in rows
            for implementation_context in row[2]
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(
            len(implementation_context) != 2
            for row in rows
            for implementation_context in row[2]
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(
            type(value) is not str
            for row in rows
            for implementation_context in row[2]
            for value in implementation_context
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)

        expected_field_names = (
            "constructor_class",
            "subject_kinds",
            "permitted_implementation_contexts",
            "proc_thread_attribute_tokens",
            "direct_child_authority",
        )
        expected_rows = (
            (
                "root-broker",
                ("root-broker",),
                (("host-native-core-v1", "root-broker"),),
                ("HANDLE_LIST", "JOB_LIST"),
                "closed-broker-api-only",
            ),
            (
                "guarded-target-or-native-leaf",
                ("guarded-python-target", "native-leaf"),
                (
                    ("host-native-core-v1", "standalone-native-leaf"),
                    (
                        "broker-native-core-v1",
                        "guarded-target-or-native-leaf",
                    ),
                ),
                (
                    "HANDLE_LIST",
                    "JOB_LIST",
                    "CHILD_PROCESS_POLICY="
                    "PROCESS_CREATION_CHILD_PROCESS_RESTRICTED",
                ),
                "none",
            ),
            (
                "codex-client-root",
                (
                    "loopback-codex-client-root",
                    "approved-codex-client-root",
                ),
                (("broker-native-core-v1", "codex-client-root"),),
                ("HANDLE_LIST", "JOB_LIST"),
                "unchanged-client-declared-descendants-only",
            ),
        )
        if field_names != expected_field_names or rows != expected_rows:
            _reject(GUARDED_BOOTSTRAP_INVALID)

        projected_rows = tuple(
            {
                field_name: row[index]
                for index, field_name in enumerate(field_names)
            }
            for row in rows
        )
        canonical_bytes = json.dumps(
            projected_rows,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii", errors="strict") + b"\n"
        constructor_attribute_set_sha256 = hashlib.sha256(
            canonical_bytes
        ).hexdigest()
        if (
            len(canonical_bytes) != 994
            or constructor_attribute_set_sha256
            != "21061550a33f8b697aab6d5f33719e2bfcd66f9cefa57c1b649fb06dcfeed58c"
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        return tuple.__new__(
            cls,
            (
                field_names,
                rows,
                canonical_bytes,
                constructor_attribute_set_sha256,
            ),
        )

    @property
    def field_names(self):
        return self[0]

    @property
    def rows(self):
        return self[1]

    @property
    def canonical_bytes(self):
        return self[2]

    @property
    def constructor_attribute_set_sha256(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftConstructorAttributeRegistry("
            f"field_count={len(self.field_names)!r}, "
            f"row_count={len(self.rows)!r}, "
            "constructor_attribute_set_sha256="
            f"{self.constructor_attribute_set_sha256!r})"
        )

    __str__ = __repr__


_C6_BROKER_NATIVE_CORE_DRAFT_CONSTRUCTOR_ATTRIBUTE_REGISTRY = (
    _C6BrokerNativeCoreDraftConstructorAttributeRegistry(
        (
            "constructor_class",
            "subject_kinds",
            "permitted_implementation_contexts",
            "proc_thread_attribute_tokens",
            "direct_child_authority",
        ),
        (
            (
                "root-broker",
                ("root-broker",),
                (("host-native-core-v1", "root-broker"),),
                ("HANDLE_LIST", "JOB_LIST"),
                "closed-broker-api-only",
            ),
            (
                "guarded-target-or-native-leaf",
                ("guarded-python-target", "native-leaf"),
                (
                    ("host-native-core-v1", "standalone-native-leaf"),
                    (
                        "broker-native-core-v1",
                        "guarded-target-or-native-leaf",
                    ),
                ),
                (
                    "HANDLE_LIST",
                    "JOB_LIST",
                    "CHILD_PROCESS_POLICY="
                    "PROCESS_CREATION_CHILD_PROCESS_RESTRICTED",
                ),
                "none",
            ),
            (
                "codex-client-root",
                (
                    "loopback-codex-client-root",
                    "approved-codex-client-root",
                ),
                (("broker-native-core-v1", "codex-client-root"),),
                ("HANDLE_LIST", "JOB_LIST"),
                "unchanged-client-declared-descendants-only",
            ),
        ),
    )
)


class _C6BrokerNativeCoreDraftJobTopologyRegistry(tuple):
    __slots__ = ()

    def __new__(cls, field_names, rows):
        if (
            cls is not _C6BrokerNativeCoreDraftJobTopologyRegistry
            or type(field_names) is not tuple
            or type(rows) is not tuple
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if (
            len(field_names) != 7
            or any(type(field_name) is not str for field_name in field_names)
            or len(rows) != 7
            or any(type(row) is not tuple for row in rows)
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(len(row) != 7 for row in rows):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(
            type(row[0]) is not str
            or type(row[1]) is not tuple
            or type(row[2]) is not tuple
            or type(row[3]) is not tuple
            or type(row[4]) is not str
            or type(row[5]) is not str
            or type(row[6]) is not str
            for row in rows
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(
            type(job_kind) is not str
            for row in rows
            for job_kinds in row[1:4]
            for job_kind in job_kinds
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)

        expected_field_names = (
            "topology_id",
            "implicit_campaign_job_kinds",
            "explicit_job_list_kinds",
            "effective_campaign_job_kinds",
            "immediate_scope",
            "completion_owner",
            "termination_owner",
        )
        expected_rows = (
            (
                "root-broker",
                (),
                ("J0",),
                ("J0",),
                "J0",
                "host:P0:J0",
                "host:J0",
            ),
            (
                "standalone-native-leaf",
                (),
                ("L0",),
                ("L0",),
                "L0",
                "host:P0:L0",
                "host:L0",
            ),
            (
                "initial-guarded-target",
                ("J0",),
                ("J1", "T0"),
                ("J0", "J1", "T0"),
                "T0",
                "root:P1:J1",
                "root:T0",
            ),
            (
                "nested-guarded-target",
                ("J0",),
                ("J1", "T0..Tk", "Tnew"),
                ("J0", "J1", "T0..Tk", "Tnew"),
                "Tnew",
                "root:P1:J1",
                "root:Tnew",
            ),
            (
                "broker-native-leaf",
                ("J0",),
                ("J1", "T0..Tk", "Ln"),
                ("J0", "J1", "T0..Tk", "Ln"),
                "Ln",
                "root:P1:J1",
                "root:Ln",
            ),
            (
                "codex-client-root",
                ("J0",),
                ("J1", "T0..Tk", "Cn"),
                ("J0", "J1", "T0..Tk", "Cn"),
                "Cn",
                "root:P1:J1",
                "root:Cn",
            ),
            (
                "codex-client-descendant",
                ("parent-effective-chain",),
                (),
                ("parent-effective-chain",),
                "inherited-Cn",
                "root:P1:J1",
                "root:Cn",
            ),
        )
        if field_names != expected_field_names or rows != expected_rows:
            _reject(GUARDED_BOOTSTRAP_INVALID)

        projected_rows = tuple(
            {
                field_name: row[index]
                for index, field_name in enumerate(field_names)
            }
            for row in rows
        )
        canonical_bytes = json.dumps(
            projected_rows,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii", errors="strict") + b"\n"
        job_topology_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
        if (
            len(canonical_bytes) != 1780
            or job_topology_sha256
            != "21e62cebf3ef108f10c9d17b614021a2d84cfcef8429c1ccd8168246c65b2c5e"
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        return tuple.__new__(
            cls,
            (
                field_names,
                rows,
                canonical_bytes,
                job_topology_sha256,
            ),
        )

    @property
    def field_names(self):
        return self[0]

    @property
    def rows(self):
        return self[1]

    @property
    def canonical_bytes(self):
        return self[2]

    @property
    def job_topology_sha256(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftJobTopologyRegistry(field_count="
            f"{len(self.field_names)!r}, "
            f"row_count={len(self.rows)!r}, "
            f"job_topology_sha256={self.job_topology_sha256!r})"
        )

    __str__ = __repr__


_C6_BROKER_NATIVE_CORE_DRAFT_JOB_TOPOLOGY_REGISTRY = (
    _C6BrokerNativeCoreDraftJobTopologyRegistry(
        (
            "topology_id",
            "implicit_campaign_job_kinds",
            "explicit_job_list_kinds",
            "effective_campaign_job_kinds",
            "immediate_scope",
            "completion_owner",
            "termination_owner",
        ),
        (
            (
                "root-broker",
                (),
                ("J0",),
                ("J0",),
                "J0",
                "host:P0:J0",
                "host:J0",
            ),
            (
                "standalone-native-leaf",
                (),
                ("L0",),
                ("L0",),
                "L0",
                "host:P0:L0",
                "host:L0",
            ),
            (
                "initial-guarded-target",
                ("J0",),
                ("J1", "T0"),
                ("J0", "J1", "T0"),
                "T0",
                "root:P1:J1",
                "root:T0",
            ),
            (
                "nested-guarded-target",
                ("J0",),
                ("J1", "T0..Tk", "Tnew"),
                ("J0", "J1", "T0..Tk", "Tnew"),
                "Tnew",
                "root:P1:J1",
                "root:Tnew",
            ),
            (
                "broker-native-leaf",
                ("J0",),
                ("J1", "T0..Tk", "Ln"),
                ("J0", "J1", "T0..Tk", "Ln"),
                "Ln",
                "root:P1:J1",
                "root:Ln",
            ),
            (
                "codex-client-root",
                ("J0",),
                ("J1", "T0..Tk", "Cn"),
                ("J0", "J1", "T0..Tk", "Cn"),
                "Cn",
                "root:P1:J1",
                "root:Cn",
            ),
            (
                "codex-client-descendant",
                ("parent-effective-chain",),
                (),
                ("parent-effective-chain",),
                "inherited-Cn",
                "root:P1:J1",
                "root:Cn",
            ),
        ),
    )
)


class _C6BrokerNativeCoreDraftJobListProjection(tuple):
    __slots__ = ()

    def __new__(cls, explicit_job_list_ids):
        if (
            cls is not _C6BrokerNativeCoreDraftJobListProjection
            or type(explicit_job_list_ids) is not tuple
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(
            type(job_id) is not str
            for job_id in explicit_job_list_ids
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if any(
            len(job_id) != 32
            for job_id in explicit_job_list_ids
        ) or any(
            any(
                character not in "0123456789abcdef"
                for character in job_id
            )
            for job_id in explicit_job_list_ids
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if len(set(explicit_job_list_ids)) != len(explicit_job_list_ids):
            _reject(GUARDED_BOOTSTRAP_INVALID)

        canonical_bytes = json.dumps(
            explicit_job_list_ids,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii", errors="strict") + b"\n"
        expected_length = (
            3
            if not explicit_job_list_ids
            else 35 * len(explicit_job_list_ids) + 2
        )
        if len(canonical_bytes) != expected_length:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        job_list_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
        return tuple.__new__(
            cls,
            (
                explicit_job_list_ids,
                canonical_bytes,
                job_list_sha256,
            ),
        )

    @property
    def explicit_job_list_ids(self):
        return self[0]

    @property
    def canonical_bytes(self):
        return self[1]

    @property
    def job_list_sha256(self):
        return self[2]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftJobListProjection(job_count="
            f"{len(self.explicit_job_list_ids)!r}, "
            f"job_list_sha256={self.job_list_sha256!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftInternalChannelAddress(tuple):
    __slots__ = ()

    def __new__(cls, token, fixed_role):
        if (
            cls is not _C6BrokerNativeCoreDraftInternalChannelAddress
            or type(token) is not str
            or type(fixed_role) is not str
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if len(token) != 32 or any(
            character not in "0123456789abcdef" for character in token
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)

        role_rows = (
            (
                "descriptor",
                "writes",
                "PIPE_ACCESS_OUTBOUND",
                "GENERIC_READ",
            ),
            (
                "ack-status",
                "reads",
                "PIPE_ACCESS_INBOUND",
                "GENERIC_WRITE",
            ),
            (
                "go",
                "writes",
                "PIPE_ACCESS_OUTBOUND",
                "GENERIC_READ",
            ),
            (
                "broker-request",
                "reads",
                "PIPE_ACCESS_INBOUND",
                "GENERIC_WRITE",
            ),
            (
                "broker-response",
                "writes",
                "PIPE_ACCESS_OUTBOUND",
                "GENERIC_READ",
            ),
            (
                "stdin",
                "writes",
                "PIPE_ACCESS_OUTBOUND",
                "GENERIC_READ",
            ),
            (
                "stdout",
                "reads",
                "PIPE_ACCESS_INBOUND",
                "GENERIC_WRITE",
            ),
            (
                "stderr",
                "reads",
                "PIPE_ACCESS_INBOUND",
                "GENERIC_WRITE",
            ),
        )
        for (
            registered_role,
            parent_action,
            server_open_mode,
            child_access,
        ) in role_rows:
            if fixed_role == registered_role:
                pipe_name = (
                    r"\\.\pipe\kokoroarc-c6-control-"
                    + token
                    + "-"
                    + registered_role
                )
                return tuple.__new__(
                    cls,
                    (
                        token,
                        registered_role,
                        pipe_name,
                        parent_action,
                        server_open_mode,
                        child_access,
                    ),
                )
        _reject(GUARDED_BOOTSTRAP_INVALID)

    @property
    def token(self):
        return self[0]

    @property
    def fixed_role(self):
        return self[1]

    @property
    def pipe_name(self):
        return self[2]

    @property
    def parent_action(self):
        return self[3]

    @property
    def server_open_mode(self):
        return self[4]

    @property
    def child_access(self):
        return self[5]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftInternalChannelAddress("
            f"fixed_role={self.fixed_role!r}, "
            f"pipe_name_length={len(self.pipe_name)!r}, "
            f"parent_action={self.parent_action!r}, "
            f"server_open_mode={self.server_open_mode!r}, "
            f"child_access={self.child_access!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftInternalChannelApplicabilityRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftInternalChannelApplicabilityRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        field_names = (
            "implementation_id",
            "constructor_class",
            "subject_kind",
            "applicable_fixed_roles",
        )
        rows = (
            (
                "broker-native-core-v1",
                "guarded-target-or-native-leaf",
                "guarded-python-target",
                (
                    "descriptor",
                    "ack-status",
                    "go",
                    "broker-request",
                    "broker-response",
                    "stdin",
                    "stdout",
                    "stderr",
                ),
            ),
            (
                "broker-native-core-v1",
                "guarded-target-or-native-leaf",
                "native-leaf",
                ("stdin", "stdout", "stderr"),
            ),
            (
                "broker-native-core-v1",
                "codex-client-root",
                "loopback-codex-client-root",
                ("stdin", "stdout", "stderr"),
            ),
            (
                "broker-native-core-v1",
                "codex-client-root",
                "approved-codex-client-root",
                ("stdin", "stdout", "stderr"),
            ),
        )
        return tuple.__new__(cls, (field_names, rows))

    @property
    def field_names(self):
        return self[0]

    @property
    def rows(self):
        return self[1]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftInternalChannelApplicabilityRegistry("
            f"field_count={len(self.field_names)!r}, "
            f"row_count={len(self.rows)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftInternalChannelEndpointConstructionFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftInternalChannelEndpointConstructionFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        field_names = (
            "implementation_id",
            "server_inheritable",
            "common_server_open_flag_tokens",
            "pipe_mode_tokens",
            "maximum_instances",
            "input_buffer_bytes",
            "output_buffer_bytes",
            "server_permitted_security_principals",
            "connect_overlapped",
            "accepted_initial_connect_result_literal",
            "successful_connect_completions_required_before_process_creation",
            "connect_overlapped_retained_until_completion_consumed",
            "connect_buffer_retained_until_completion_consumed",
            "child_share_mode",
            "child_creation_disposition",
            "child_inheritable",
            "child_synchronous",
            "per_channel_handle_list_endpoint",
        )
        rows = (
            (
                "broker-native-core-v1",
                False,
                ("FILE_FLAG_FIRST_PIPE_INSTANCE", "FILE_FLAG_OVERLAPPED"),
                (
                    "PIPE_TYPE_BYTE",
                    "PIPE_READMODE_BYTE",
                    "PIPE_WAIT",
                    "PIPE_REJECT_REMOTE_CLIENTS",
                ),
                1,
                65_536,
                65_536,
                ("current-user-sid",),
                True,
                "FALSE/ERROR_IO_PENDING",
                1,
                True,
                True,
                0,
                "OPEN_EXISTING",
                True,
                True,
                "child-endpoint-only",
            ),
        )
        successful_path_per_channel_phases = (
            "server-created",
            "server-associated-with-private-iocp",
            "overlapped-connect-issued-with-FALSE/ERROR_IO_PENDING",
            "child-endpoint-opened",
            "one-successful-connect-completion-consumed",
            "per-channel-child-endpoint-only-placed-in-HANDLE_LIST",
            "CreateProcessW-succeeded",
            "parent-duplicate-of-child-endpoint-closed-immediately",
        )
        return tuple.__new__(
            cls,
            (
                field_names,
                rows,
                successful_path_per_channel_phases,
            ),
        )

    @property
    def field_names(self):
        return self[0]

    @property
    def rows(self):
        return self[1]

    @property
    def successful_path_per_channel_phases(self):
        return self[2]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftInternalChannelEndpointConstructionFactsRegistry("
            f"field_count={len(self.field_names)!r}, "
            f"row_count={len(self.rows)!r}, "
            "phase_count="
            f"{len(self.successful_path_per_channel_phases)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpOperationIssueFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftIocpOperationIssueFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "issue_api_literals",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    ("ReadFile", "WriteFile"),
                ),
            ),
        )
        issue_phases = (
            "zero-dedicated-OVERLAPPED",
            "allocate-immutable-operation-buffer-and-cursor",
            "insert-ISSUING-ledger-entry",
            "invoke-overlapped-ReadFile-or-WriteFile",
        )
        issue_return_table = (
            (
                "api_scope",
                "return_match",
                "ledger_state_before",
                "ledger_state_after",
                "recorded_outcome",
                "packet_expected",
                "immediate_byte_count_policy",
            ),
            (
                (
                    "ReadFile-or-WriteFile",
                    "TRUE",
                    "ISSUING",
                    "LIVE_AWAIT_PACKET",
                    "none",
                    True,
                    "ignore",
                ),
                (
                    "ReadFile-or-WriteFile",
                    "FALSE/ERROR_IO_PENDING",
                    "ISSUING",
                    "LIVE_AWAIT_PACKET",
                    "none",
                    True,
                    "not-applicable",
                ),
                (
                    "ReadFile",
                    "FALSE/ERROR_BROKEN_PIPE-and-role-permitted-read-terminal",
                    "ISSUING",
                    None,
                    "immediate-EOF",
                    False,
                    "not-applicable",
                ),
                (
                    "ReadFile-or-WriteFile",
                    "any-other-FALSE/GetLastError()",
                    "ISSUING",
                    None,
                    "immediate-terminal-error",
                    False,
                    "not-applicable",
                ),
            ),
        )
        allocation_lifetime_table = (
            (
                "issue_return_match",
                "overlapped_action",
                "buffer_and_cursor_action",
                "retention_boundary",
                "pre_retirement_prohibition",
            ),
            (
                (
                    "TRUE",
                    "retain",
                    "retain",
                    "exact-one-queued-packet-consumed",
                    "no-reuse-move-or-free",
                ),
                (
                    "FALSE/ERROR_IO_PENDING",
                    "retain",
                    "retain",
                    "exact-one-queued-packet-consumed",
                    "no-reuse-move-or-free",
                ),
            ),
        )
        invariants = (
            "one-outstanding-operation-per-parent-endpoint",
            "one-dedicated-OVERLAPPED-per-parent-endpoint",
            "only-LIVE_AWAIT_PACKET-is-outstanding-or-cancelable",
            "completion-skip-modes-forbidden",
            "every-pipe-packet-must-match-exactly-one-live-OVERLAPPED",
            "no-OVERLAPPED-or-operation-buffer/cursor-reuse-move-or-free-before-exact-retirement",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                issue_phases,
                issue_return_table,
                allocation_lifetime_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def issue_phases(self):
        return self[1]

    @property
    def issue_return_table(self):
        return self[2]

    @property
    def allocation_lifetime_table(self):
        return self[3]

    @property
    def invariants(self):
        return self[4]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpOperationIssueFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "issue_phase_count="
            f"{len(self.issue_phases)!r}, "
            "issue_return_row_count="
            f"{len(self.issue_return_table[1])!r}, "
            "allocation_lifetime_row_count="
            f"{len(self.allocation_lifetime_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpDispatchResultFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftIocpDispatchResultFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "dispatch_api_literals",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    ("GetQueuedCompletionStatus",),
                ),
            ),
        )
        result_field_names = (
            "gqcs_return_match",
            "completion_key_domain",
            "lp_overlapped_semantics",
            "packet_dequeued",
            "last_error_policy",
            "classification",
        )
        result_rows = (
            (
                "TRUE",
                "symbolic-associated-Job-domain",
                "documented-message-value-PID-sized-where-defined-otherwise-null-never-dereference",
                True,
                "not-applicable",
                "advisory-Job-notification",
            ),
            (
                "TRUE",
                "symbolic-registered-pipe-role-domain",
                "non-null-exact-live-OVERLAPPED",
                True,
                "not-applicable",
                "successful-pipe-I/O-completion",
            ),
            (
                "FALSE",
                "symbolic-registered-pipe-role-domain",
                "non-null-exact-live-OVERLAPPED",
                True,
                "reconcile-using-GetLastError()-value",
                "failed-pipe-I/O-completion",
            ),
            (
                "FALSE",
                "no-dequeued-packet",
                "null",
                False,
                "GetLastError()==WAIT_TIMEOUT",
                "poll-timeout",
            ),
            (
                "FALSE",
                "no-dequeued-packet",
                "null",
                False,
                "any-other-GetLastError()",
                "terminal-dispatcher-failure",
            ),
        )
        invariants = (
            "GetQueuedCompletionStatus-is-the-only-dispatch-api",
            "every-dequeued-packet-completion-key-must-resolve-to-exactly-one-symbolic-associated-Job-or-registered-pipe-role-domain",
            "associated-Job-lpOverlapped-is-documented-message-value-PID-sized-where-defined-otherwise-null-and-never-dereferenced",
            "every-pipe-packet-must-match-exactly-one-live-OVERLAPPED",
            "FALSE-with-non-null-lpOverlapped-is-a-dequeued-failed-I/O-completion",
            "FALSE-with-null-lpOverlapped-is-poll-timeout-only-for-WAIT_TIMEOUT",
            "FALSE-with-null-lpOverlapped-and-any-other-error-is-terminal-dispatcher-failure",
            "Job-completion-port-notifications-are-advisory-and-never-mandatory-success-gates",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                result_field_names,
                result_rows,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def result_field_names(self):
        return self[1]

    @property
    def result_rows(self):
        return self[2]

    @property
    def invariants(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpDispatchResultFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "result_field_count="
            f"{len(self.result_field_names)!r}, "
            "result_row_count="
            f"{len(self.result_rows)!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpSuccessfulZeroByteWriteResultFactsRegistry(
    tuple
):
    __slots__ = ()

    def __new__(cls):
        if (
            cls
            is not _C6BrokerNativeCoreDraftIocpSuccessfulZeroByteWriteResultFactsRegistry
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "write_api_literals",
                "upstream_dispatch_classification",
                "completion_byte_count_source",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    ("WriteFile",),
                    "successful-pipe-I/O-completion",
                    "lpNumberOfBytesTransferred-from-the-exact-dequeued-successful-WriteFile-completion-packet",
                ),
            ),
        )
        result_field_names = (
            "completion_byte_count_match",
            "result_classification",
        )
        result_rows = (
            (
                "zero-bytes",
                "failure",
            ),
        )
        invariants = (
            "these-facts-apply-only-to-the-exact-dequeued-successful-WriteFile-completion-packet",
            "the-dequeued-pipe-packet-must-match-exactly-one-LIVE_AWAIT_PACKET-OVERLAPPED",
            "the-immediate-WriteFile-byte-count-is-never-an-input-to-this-result",
            "successful-zero-byte-write-is-failure",
            "failure-is-only-a-write-result-classification-and-grants-no-retirement-continuation-reissue-cleanup-cancellation-closing-or-overall-publication-authority",
            "partial-write-and-full-write-result-semantics-are-out-of-scope",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                result_field_names,
                result_rows,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def result_field_names(self):
        return self[1]

    @property
    def result_rows(self):
        return self[2]

    @property
    def invariants(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpSuccessfulZeroByteWriteResultFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "result_field_count="
            f"{len(self.result_field_names)!r}, "
            "result_row_count="
            f"{len(self.result_rows)!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpCancelIoExAcceptedCallResultFactsRegistry(
    tuple
):
    __slots__ = ()

    def __new__(cls):
        if (
            cls
            is not _C6BrokerNativeCoreDraftIocpCancelIoExAcceptedCallResultFactsRegistry
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "cancel_api_literals",
                "call_context",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    ("CancelIoEx",),
                    "failure-sequence-after-freeze-new-operations-and-smallest-owning-Job-termination",
                ),
            ),
        )
        accepted_call_result_field_names = (
            "request_target_state",
            "request_target_scope",
            "call_result_match",
            "accepted",
            "retires_operation",
        )
        accepted_call_result_rows = (
            (
                "LIVE_AWAIT_PACKET",
                "every-live-operation",
                "Success",
                True,
                False,
            ),
            (
                "LIVE_AWAIT_PACKET",
                "every-live-operation",
                "FALSE/ERROR_NOT_FOUND",
                True,
                False,
            ),
        )
        invariants = (
            "these-accepted-call-result-facts-apply-only-to-CancelIoEx-requests-issued-in-the-bound-failure-sequence-call-context",
            "within-the-bound-context-every-operation-observed-as-LIVE_AWAIT_PACKET-during-request-target-enumeration-is-a-request-target",
            "only-LIVE_AWAIT_PACKET-is-cancelable",
            "Success-and-FALSE/ERROR_NOT_FOUND-are-the-only-accepted-CancelIoEx-call-results",
            "accepted-CancelIoEx-call-results-do-not-retire-the-operation",
            "CancelIoEx-call-result-acceptance-is-distinct-from-dequeued-cleanup-completion-classification",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                accepted_call_result_field_names,
                accepted_call_result_rows,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def accepted_call_result_field_names(self):
        return self[1]

    @property
    def accepted_call_result_rows(self):
        return self[2]

    @property
    def invariants(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpCancelIoExAcceptedCallResultFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "accepted_call_result_field_count="
            f"{len(self.accepted_call_result_field_names)!r}, "
            "accepted_call_result_row_count="
            f"{len(self.accepted_call_result_rows)!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpCleanupCompletionFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftIocpCleanupCompletionFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "operation_api_literals",
                "upstream_dispatch_classifications",
                "cleanup_context",
                "failed_completion_error_source",
                "role_permission_requirement",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    ("ReadFile", "WriteFile"),
                    (
                        "successful-pipe-I/O-completion",
                        "failed-pipe-I/O-completion",
                    ),
                    "bound-failure-sequence-cleanup-processing-of-an-exact-dequeued-pipe-packet-for-exactly-one-still-unretired-operation-whose-ledger-state-immediately-before-processing-is-LIVE_AWAIT_PACKET",
                    "reconcile-using-GetLastError()-value",
                    "independent-symbolic-role-permitted-read-terminal-predicate-with-no-local-mapping-or-evaluation-authority",
                ),
            ),
        )
        cleanup_completion_field_names = (
            "upstream_dispatch_classification",
            "completion_result_match",
            "accepted_cleanup_completion",
            "retires_operation",
            "recorded_cleanup_outcome",
        )
        cleanup_completion_rows = (
            (
                "successful-pipe-I/O-completion",
                "Success",
                True,
                True,
                "accepted-cleanup-completion",
            ),
            (
                "failed-pipe-I/O-completion",
                "ERROR_OPERATION_ABORTED",
                True,
                True,
                "accepted-cleanup-completion",
            ),
            (
                "failed-pipe-I/O-completion",
                "ERROR_BROKEN_PIPE-and-ReadFile-and-independent-symbolic-role-permitted-read-terminal",
                True,
                True,
                "EOF",
            ),
            (
                "failed-pipe-I/O-completion",
                "every-complementary-failed-pipe-completion-including-ERROR_BROKEN_PIPE-outside-the-exact-ReadFile-and-independent-symbolic-role-permitted-read-terminal-condition",
                False,
                True,
                "terminal-protocol-failure",
            ),
        )
        invariants = (
            "these-facts-apply-only-to-bound-failure-sequence-cleanup-processing-of-an-exact-dequeued-pipe-packet-for-exactly-one-still-unretired-operation-whose-ledger-state-immediately-before-processing-is-LIVE_AWAIT_PACKET",
            "cleanup-processing-does-not-require-or-classify-any-CancelIoEx-call-result",
            "each-applicable-pipe-packet-must-match-exactly-one-still-unretired-LIVE_AWAIT_PACKET-OVERLAPPED",
            "the-four-cleanup-completion-rows-are-mutually-exclusive-and-exhaustive-within-the-bound-context",
            "each-row-records-retirement-only-at-the-exact-one-dequeued-completion-boundary",
            "ERROR_BROKEN_PIPE-is-EOF-only-for-ReadFile-with-the-independent-symbolic-role-permitted-read-terminal-predicate-satisfied-and-every-unqualified-ERROR_BROKEN_PIPE-is-terminal-protocol-failure",
            "ERROR_OPERATION_ABORTED-is-an-accepted-cleanup-completion-and-is-never-EOF",
            "cleanup-completion-acceptance-is-distinct-from-CancelIoEx-call-result-acceptance",
            "accepted-successful-cleanup-completion-grants-no-byte-count-cursor-write-result-overall-success-or-publication-authority",
            "successful-zero-byte-WriteFile-remains-failure-and-partial/full-write-semantics-remain-independent",
            "the-role-permission-requirement-defines-no-raw-role-mapping-or-runtime-evaluation-authority",
            "accepted_cleanup_completion=False-does-not-prevent-exact-packet-consumption-or-retirement",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                cleanup_completion_field_names,
                cleanup_completion_rows,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def cleanup_completion_field_names(self):
        return self[1]

    @property
    def cleanup_completion_rows(self):
        return self[2]

    @property
    def invariants(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpCleanupCompletionFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "cleanup_completion_field_count="
            f"{len(self.cleanup_completion_field_names)!r}, "
            "cleanup_completion_row_count="
            f"{len(self.cleanup_completion_rows)!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpWriterCloseEligibilityFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftIocpWriterCloseEligibilityFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "endpoint_scope",
                "failure_sequence_boundary",
                "writer_operation_state_source",
                "retirement_boundary",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "applicable-parent-endpoints-whose-parent-action-is-writes",
                    "bound-failure-sequence-step-4-writer-close-eligibility-evaluation",
                    "exact-per-parent-endpoint-operation-ledger-with-only-LIVE_AWAIT_PACKET-outstanding",
                    "exact-matching-dequeued-completion-packet-consumed-and-operation-retired",
                ),
            ),
        )
        close_eligibility_field_names = (
            "writer_operation_state_at_step_4",
            "close_eligible_at_step_4",
            "step_4_disposition",
            "later_close_eligibility_boundary",
        )
        close_eligibility_rows = (
            (
                "idle-with-no-still-unretired-LIVE_AWAIT_PACKET-operation",
                True,
                "close-immediately",
                "already-satisfied",
            ),
            (
                "pending-with-exactly-one-still-unretired-LIVE_AWAIT_PACKET-operation",
                False,
                "retain-open",
                "exact-matching-dequeued-completion-packet-consumed-and-operation-retired",
            ),
        )
        invariants = (
            "these-facts-apply-only-to-bound-failure-sequence-step-4-for-applicable-parent-endpoints-whose-parent-action-is-writes",
            "step-4-writer-close-eligibility-is-evaluated-after-new-operations-are-frozen-at-a-boundary-with-no-ISSUING-ledger-entry",
            "the-two-writer-operation-state-rows-are-mutually-exclusive-and-exhaustive-because-each-parent-endpoint-permits-at-most-one-outstanding-operation",
            "only-an-idle-writer-with-no-still-unretired-LIVE_AWAIT_PACKET-operation-is-close-eligible-immediately",
            "a-writer-with-exactly-one-still-unretired-LIVE_AWAIT_PACKET-operation-remains-open",
            "a-pending-writer-becomes-close-eligible-only-after-its-exact-matching-dequeued-completion-packet-is-consumed-and-that-operation-retires",
            "no-CancelIoEx-call-result-closes-the-writer-or-retires-its-operation",
            "exact-packet-consumption-retires-the-writer-operation-even-when-accepted_cleanup_completion=False-and-terminal-protocol-failure-remains-recorded",
            "an-immediate-terminal-issue-return-that-removes-ISSUING-and-expects-no-packet-is-not-pending-I/O-at-step-4",
            "successful-zero-byte-write-and-partial/full-write-result-semantics-grant-no-earlier-writer-close-eligibility",
            "this-registry-grants-no-handle-selection-CloseHandle-call-packet-consumption-retirement-cancellation-grace-job-polling-pump-stop-quarantine-free-publication-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                close_eligibility_field_names,
                close_eligibility_rows,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def close_eligibility_field_names(self):
        return self[1]

    @property
    def close_eligibility_rows(self):
        return self[2]

    @property
    def invariants(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpWriterCloseEligibilityFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "close_eligibility_field_count="
            f"{len(self.close_eligibility_field_names)!r}, "
            "close_eligibility_row_count="
            f"{len(self.close_eligibility_rows)!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpFailureGraceFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftIocpFailureGraceFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "failure_sequence_step",
                "grace_duration_ms",
                "grace_multiplicity",
                "grace_deadline_policy",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "step-5",
                    10000,
                    "exactly-one",
                    "single-nonextendable-monotonic-grace-deadline",
                ),
            ),
        )
        grace_activity_table = (
            (
                "grace_activity",
                "activity_scope",
                "required_mode",
            ),
            (
                (
                    "dispatch-result-processing",
                    "every-result-classified-by-existing-exact-dispatch-facts",
                    "classify-and-reconcile",
                ),
                (
                    "process-handle-polling",
                    "every-retained-process-handle",
                    "nonblocking-query",
                ),
                (
                    "Job-accounting-polling",
                    "every-applicable-owned-Job",
                    "nonblocking-query",
                ),
            ),
        )
        canceled_stdio_read_rule = (
            (
                "operation_scope",
                "completion_result_match",
                "accepted_cleanup_completion",
                "retires_operation",
                "recorded_stdio_outcome",
            ),
            (
                (
                    "stdout-or-stderr-ReadFile",
                    "ERROR_OPERATION_ABORTED",
                    True,
                    True,
                    "not-EOF",
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-bound-failure-sequence-step-5",
            "the-grace-duration-is-exactly-10000-ms",
            "there-is-exactly-one-nonextendable-grace-with-no-reconnect-retry-or-second-grace",
            "the-three-grace-activity-rows-are-the-exact-permitted-activity-classes",
            "dispatch-result-processing-uses-the-existing-exact-dispatch-facts-and-only-exact-matched-pipe-packets-use-the-existing-cleanup-retirement-and-writer-close-eligibility-facts",
            "after-every-dequeued-packet-or-WAIT_TIMEOUT-poll-timeout-the-two-nonblocking-polling-activities-run-before-the-next-wait",
            "process-handle-polling-is-nonblocking-and-covers-every-retained-process-handle",
            "Job-accounting-polling-is-nonblocking-covers-every-applicable-owned-Job-and-does-not-require-a-Job-notification",
            "each-positive-remainder-wait-uses-the-existing-min-50-ceil-remaining-monotonic-ns-over-1000000-rule-and-a-nonpositive-remainder-fails-without-a-wait",
            "a-canceled-stdout-or-stderr-ReadFile-completion-is-accepted-and-retires-but-is-never-recorded-as-EOF",
            "these-facts-grant-no-success-path-or-grace-success-close-ordering-grace-expiry-quarantine-free-or-publication-authority",
            "this-registry-grants-no-GetQueuedCompletionStatus-process-query-Job-query-wait-packet-consumption-polling-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                grace_activity_table,
                canceled_stdio_read_rule,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def grace_activity_table(self):
        return self[1]

    @property
    def canceled_stdio_read_rule(self):
        return self[2]

    @property
    def invariants(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpFailureGraceFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "grace_activity_row_count="
            f"{len(self.grace_activity_table[1])!r}, "
            "canceled_stdio_read_rule_row_count="
            f"{len(self.canceled_stdio_read_rule[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpGraceReconciledCloseOrderFactsRegistry(
    tuple
):
    __slots__ = ()

    def __new__(cls):
        if (
            cls
            is not _C6BrokerNativeCoreDraftIocpGraceReconciledCloseOrderFactsRegistry
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "failure_sequence_step",
                "cleanup_outcome",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "step-6",
                    "failure-grace-reconciled-terminal-cleanup",
                ),
            ),
        )
        reconciliation_precondition_table = (
            (
                "reconciliation_scope",
                "required_evidence_match",
                "required_before_close",
            ),
            (
                (
                    "operation-ledger",
                    "zero-LIVE_AWAIT_PACKET-operations-and-every-packet-expected-operation-retired",
                    True,
                ),
                (
                    "retained-process-handles",
                    "every-retained-process-handle-signaled-with-reconciled-exit-code",
                    True,
                ),
                (
                    "every-applicable-owned-Job",
                    "ActiveProcesses==0-and-final-bounded-process-ID-list-empty-and-TotalProcesses==unique-known-process-count-for-that-Job-scope",
                    True,
                ),
            ),
        )
        close_order_table = (
            (
                "stage_ordinal",
                "resource_scope",
                "within_stage_rule",
                "required_predecessor",
            ),
            (
                (
                    1,
                    "all-owned-pipe-handles-and-all-retained-process-handles",
                    "relative-order-within-stage-1-is-out-of-scope",
                    "all-reconciliation-preconditions-satisfied",
                ),
                (
                    2,
                    "all-applicable-unassociated-inner-Campaign-Jobs:T0,T0..Tk,Tnew,Ln,Cn",
                    "leaf-first",
                    "stage-1-complete",
                ),
                (
                    3,
                    "the-single-applicable-associated-Campaign-Job:J0-or-L0-or-J1",
                    "close-after-all-applicable-inner-Jobs",
                    "stage-2-complete-or-no-inner-Job-applies",
                ),
                (
                    4,
                    "the-single-applicable-completion-port",
                    "close-last",
                    "stage-3-complete",
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-bound-failure-sequence-step-6-after-step-5-reconciliation",
            "all-three-reconciliation-preconditions-are-conjunctive-and-must-hold-before-any-stage-1-close",
            "the-operation-ledger-precondition-means-zero-LIVE_AWAIT_PACKET-operations-and-every-packet-expected-operation-has-retired-from-its-exact-dequeued-packet",
            "every-retained-process-handle-must-be-signaled-with-its-exit-code-reconciled-before-close",
            "every-applicable-owned-Job-must-have-ActiveProcesses-zero-an-empty-final-bounded-process-ID-list-and-TotalProcesses-equal-to-its-unique-known-process-count",
            "advisory-Job-notifications-never-substitute-for-the-authoritative-Job-precondition",
            "the-four-close-stage-rows-are-exact-strict-noninterleavable-and-may-not-be-reordered-or-omitted",
            "all-owned-pipe-handles-and-retained-process-handles-close-before-any-Campaign-Job-and-their-within-stage-relative-order-is-out-of-scope",
            "only-T0-T0..Tk-Tnew-Ln-and-Cn-are-unassociated-inner-Job-symbols-and-all-applicable-inner-Jobs-close-leaf-first",
            "only-J0-L0-and-J1-are-associated-Job-symbols-and-the-single-applicable-associated-Job-closes-after-all-applicable-inner-Jobs",
            "the-single-applicable-completion-port-closes-after-the-associated-Job-and-is-last",
            "an-ambient-ancestor-Job-is-unowned-excluded-from-Campaign-Job-domains-and-never-closed",
            "step-6-reconciliation-does-not-erase-the-terminal-attempt-failure-or-grant-overall-success-or-publication-authority",
            "this-registry-grants-no-handle-selection-CloseHandle-process-query-Job-query-packet-consumption-retirement-free-pump-stop-grace-expiry-quarantine-publication-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                reconciliation_precondition_table,
                close_order_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def reconciliation_precondition_table(self):
        return self[1]

    @property
    def close_order_table(self):
        return self[2]

    @property
    def invariants(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpGraceReconciledCloseOrderFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "reconciliation_precondition_row_count="
            f"{len(self.reconciliation_precondition_table[1])!r}, "
            "close_order_row_count="
            f"{len(self.close_order_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpGraceExpiryQuarantineFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if (
            cls
            is not _C6BrokerNativeCoreDraftIocpGraceExpiryQuarantineFactsRegistry
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "failure_sequence_step",
                "expiry_source",
                "cleanup_outcome",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "step-7",
                    "single-nonextendable-step-5-10000-ms-monotonic-grace-expired",
                    "irreversible-terminal-expiry-cleanup",
                ),
            ),
        )
        expiry_disposition_table = (
            (
                "expiry_boundary",
                "required_disposition",
                "forbidden_fallback",
            ),
            (
                (
                    "deadline-reached-before-step-6-close-branch-commit",
                    "enter-step-7-exactly-once",
                    "step-6-close-reentry-or-renewed-wait",
                ),
            ),
        )
        close_order_table = (
            (
                "stage_ordinal",
                "resource_scope",
                "within_stage_rule",
                "required_predecessor",
            ),
            (
                (
                    1,
                    "all-applicable-owned-kill-on-close-Campaign-Jobs",
                    "relative-order-within-stage-1-is-out-of-scope",
                    "expiry-branch-committed-and-live-allocation-quarantine-bound",
                ),
                (
                    2,
                    "all-still-open-owned-pipe-handles-and-all-retained-process-handles",
                    "relative-order-within-stage-2-is-out-of-scope",
                    "stage-1-complete",
                ),
                (
                    3,
                    "the-completion-pump",
                    "stop",
                    "stage-2-complete",
                ),
                (
                    4,
                    "the-single-applicable-completion-port",
                    "close-last",
                    "stage-3-complete",
                ),
            ),
        )
        quarantine_rule_table = (
            (
                "operation_state_at_expiry",
                "allocation_scope",
                "quarantine_start_boundary",
                "retention_boundary",
                "reuse_or_move_authority",
                "explicit_free_authority",
                "success_publication_authority",
            ),
            (
                (
                    "LIVE_AWAIT_PACKET",
                    "the-exact-dedicated-OVERLAPPED-and-associated-operation-buffer",
                    "step-7-entry-before-the-first-close-stage",
                    "through-owning-host-or-root-process-exit",
                    "forbidden",
                    "forbidden",
                    "forbidden",
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-bound-failure-sequence-step-7-after-the-single-grace-expires",
            "the-step-7-branch-is-irreversible-and-may-not-reenter-step-5-or-step-6",
            "step-7-requires-no-operation-retirement-process-signal-or-authoritative-Job-empty-precondition",
            "the-four-close-stage-rows-are-exact-strict-noninterleavable-and-may-not-be-reordered-or-omitted",
            "stage-1-covers-only-applicable-owned-kill-on-close-Campaign-Jobs",
            "ambient-or-unowned-Jobs-are-not-stage-1-close-targets",
            "no-leaf-first-or-other-relative-Job-close-order-is-granted-within-stage-1",
            "remaining-pipe-and-process-handles-close-after-the-Job-stage-with-no-relative-order-granted-within-stage-2",
            "a-still-live-writer-no-longer-defers-handle-close-after-expiry-but-its-live-allocation-remains-quarantined",
            "the-pump-stops-after-pipe-and-process-handle-close-and-before-completion-port-close",
            "the-applicable-completion-port-closes-last",
            "every-LIVE_AWAIT_PACKET-operation-at-expiry-irrevocably-binds-its-exact-OVERLAPPED-and-buffer-to-quarantine",
            "a-late-completion-or-CancelIoEx-result-cannot-release-reuse-free-or-publish-success-for-an-expiry-quarantined-allocation",
            "owning-host-or-root-process-exit-is-a-minimum-retention-boundary-not-explicit-free-or-reuse-authority",
            "step-7-never-records-canceled-stdio-as-EOF-or-erases-the-terminal-attempt-failure",
            "there-is-no-reconnect-retry-second-grace-handle-reuse-or-success-publication",
            "this-registry-grants-no-handle-selection-CloseHandle-Job-close-pump-stop-packet-consumption-retirement-quarantine-mutation-free-wait-query-publication-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                expiry_disposition_table,
                close_order_table,
                quarantine_rule_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def expiry_disposition_table(self):
        return self[1]

    @property
    def close_order_table(self):
        return self[2]

    @property
    def quarantine_rule_table(self):
        return self[3]

    @property
    def invariants(self):
        return self[4]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpGraceExpiryQuarantineFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "expiry_disposition_row_count="
            f"{len(self.expiry_disposition_table[1])!r}, "
            "close_order_row_count="
            f"{len(self.close_order_table[1])!r}, "
            "quarantine_rule_row_count="
            f"{len(self.quarantine_rule_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpSuccessConvergenceFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if (
            cls
            is not _C6BrokerNativeCoreDraftIocpSuccessConvergenceFactsRegistry
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "convergence_scope",
                "deadline_scope",
                "outcome_scope",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "overall-run-success",
                    "the-one-absolute-applicable-deadline",
                    "authoritative-conjunctive-convergence",
                ),
            ),
        )
        authoritative_gate_table = (
            (
                "convergence_gate",
                "required_scope",
                "required_evidence_match",
                "required_for_success",
            ),
            (
                (
                    "retained-process-terminal-state",
                    "every-retained-process-handle",
                    "every-retained-process-handle-signaled-with-reconciled-exit-code",
                    True,
                ),
                (
                    "owned-Job-active-process-accounting",
                    "every-applicable-owned-Campaign-Job",
                    "ActiveProcesses==0",
                    True,
                ),
                (
                    "owned-Job-final-process-ID-membership",
                    "every-applicable-owned-Campaign-Job",
                    "final-bounded-process-ID-list-empty",
                    True,
                ),
                (
                    "owned-Job-total-process-accounting",
                    "every-applicable-owned-Campaign-Job",
                    "TotalProcesses==unique-known-process-count-for-that-Job-scope",
                    True,
                ),
                (
                    "process-identity-and-Job-membership-reconciliation",
                    "every-reserved-known-and-observed-process-and-applicable-Job-binding",
                    "no-accounting-identity-or-membership-mismatch",
                    True,
                ),
                (
                    "required-terminal-frames",
                    "every-applicable-role-and-context-requiring-a-terminal-frame",
                    "all-required-terminal-frames-observed-exactly-under-the-existing-bound-grammar",
                    True,
                ),
                (
                    "required-pipe-EOFs",
                    "every-applicable-pipe-role-requiring-terminal-EOF",
                    "role-permitted-EOF-observed-after-the-exact-required-protocol",
                    True,
                ),
                (
                    "outstanding-I/O",
                    "every-applicable-parent-endpoint-operation-ledger",
                    "zero-LIVE_AWAIT_PACKET-operations-and-every-packet-expected-operation-retired",
                    True,
                ),
            ),
        )
        advisory_job_notification_table = (
            (
                "notification_class",
                "permitted_ledger_effect",
                "required_for_success",
                "authoritative_gate_substitution",
            ),
            (
                (
                    "JOB_OBJECT_MSG_NEW_PROCESS",
                    "optional-typed-monotonic-ledger-enrichment",
                    False,
                    "none",
                ),
                (
                    "JOB_OBJECT_MSG_EXIT_PROCESS",
                    "optional-typed-monotonic-ledger-enrichment",
                    False,
                    "none",
                ),
                (
                    "JOB_OBJECT_MSG_ABNORMAL_EXIT_PROCESS",
                    "optional-typed-monotonic-ledger-enrichment",
                    False,
                    "none",
                ),
                (
                    "JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO",
                    "optional-typed-monotonic-ledger-enrichment",
                    False,
                    "none",
                ),
            ),
        )
        mismatch_disposition_table = (
            (
                "mismatch_class",
                "unreconciled_condition",
                "success_boundary_disposition",
            ),
            (
                (
                    "accounting",
                    "any-authoritative-process-or-Job-accounting-mismatch",
                    "fail-closed",
                ),
                (
                    "identity",
                    "any-bound-process-identity-mismatch",
                    "fail-closed",
                ),
                (
                    "membership",
                    "any-Campaign-Job-membership-mismatch",
                    "fail-closed",
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-overall-run-success-convergence-before-any-terminal-failure-sequence",
            "all-eight-convergence-gate-rows-are-conjunctive-and-none-may-be-omitted-or-substituted",
            "registry-row-order-is-canonical-data-order-and-grants-no-runtime-evaluation-order",
            "every-retained-process-handle-remains-open-until-signaled-and-GetExitCodeProcess-reconciles",
            "a-reconciled-exit-code-does-not-waive-the-separately-bound-role-specific-expected-exit-contract",
            "PID-alone-is-never-process-identity-authority",
            "all-three-authoritative-Job-facts-must-hold-independently-for-every-applicable-owned-Campaign-Job",
            "ambient-unowned-Jobs-and-query-only-duplicates-are-excluded-from-owned-Job-success-gates",
            "an-empty-final-process-ID-list-does-not-substitute-for-ActiveProcesses-zero-or-TotalProcesses-reconciliation",
            "TotalProcesses-reconciliation-detects-a-short-lived-or-otherwise-missed-Job-member",
            "all-four-Job-notification-classes-are-optional-ledger-enrichment-and-never-mandatory-success-gates",
            "a-missing-Job-notification-is-harmless-only-when-all-authoritative-accounting-identity-and-membership-facts-reconcile",
            "an-observed-malformed-unknown-duplicate-or-contradictory-Job-packet-remains-terminal-failure",
            "required-terminal-frames-and-EOFs-are-selected-only-by-existing-exact-role-context-and-pipe-grammar-facts",
            "zero-outstanding-I/O-means-zero-LIVE_AWAIT_PACKET-and-exact-retirement-of-every-packet-expected-operation",
            "immediate-terminal-I/O-errors-successful-zero-byte-writes-and-recorded-protocol-failures-prevent-success-even-after-zero-outstanding-I/O",
            "failure-sequence-step-6-reconciliation-or-step-7-expiry-cleanup-never-satisfies-overall-success-convergence",
            "these-facts-waive-no-upstream-authentication-deadline-cap-parser-construction-identity-membership-or-ordering-gate",
            "this-registry-grants-no-process-query-Job-query-packet-consumption-frame-parsing-EOF-classification-retirement-close-publication-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                authoritative_gate_table,
                advisory_job_notification_table,
                mismatch_disposition_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def authoritative_gate_table(self):
        return self[1]

    @property
    def advisory_job_notification_table(self):
        return self[2]

    @property
    def mismatch_disposition_table(self):
        return self[3]

    @property
    def invariants(self):
        return self[4]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpSuccessConvergenceFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "authoritative_gate_row_count="
            f"{len(self.authoritative_gate_table[1])!r}, "
            "advisory_job_notification_row_count="
            f"{len(self.advisory_job_notification_table[1])!r}, "
            "mismatch_disposition_row_count="
            f"{len(self.mismatch_disposition_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftConstructorControlFrameGrammarFactsRegistry(
    tuple
):
    __slots__ = ()

    def __new__(cls):
        if (
            cls
            is not _C6BrokerNativeCoreDraftConstructorControlFrameGrammarFactsRegistry
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "protocol_scope",
                "included_fixed_roles",
                "excluded_semantic_roles",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "constructor-static-ACK-status-and-GO-wire-role-grammar",
                    ("ack-status", "go"),
                    (
                        "broker-request",
                        "broker-response",
                        "credential-data",
                        "credential-host-status",
                    ),
                ),
            ),
        )
        frame_wire_rule_table = (
            (
                "length_prefix_bytes",
                "length_prefix_type",
                "length_prefix_endianness",
                "payload_encoding",
                "payload_canonical_form",
                "payload_cap_bytes",
                "maximum_frame_wire_bytes",
            ),
            (
                (
                    4,
                    "unsigned-payload-byte-length",
                    "little-endian",
                    "strict-UTF-8",
                    "canonical-JSON",
                    65_536,
                    65_540,
                ),
            ),
        )
        control_role_table = (
            (
                "fixed_role",
                "parent_action",
                "server_open_mode",
                "child_access",
                "handle_and_lifetime_alias_policy",
            ),
            (
                (
                    "ack-status",
                    "reads",
                    "PIPE_ACCESS_INBOUND",
                    "GENERIC_WRITE",
                    "distinct-no-alias",
                ),
                (
                    "go",
                    "writes",
                    "PIPE_ACCESS_OUTBOUND",
                    "GENERIC_READ",
                    "distinct-no-alias",
                ),
            ),
        )
        grammar_table = (
            (
                "fixed_role",
                "endpoint_context",
                "readiness_frame_state",
                "peer_connection_state",
                "exact_ordered_wire_events",
                "maximum_frame_count_for_role_context",
            ),
            (
                (
                    "ack-status",
                    "host-facing-execute-root",
                    "absent",
                    "not-applicable",
                    ("ack", "terminal", "EOF"),
                    4,
                ),
                (
                    "ack-status",
                    "host-facing-execute-root",
                    "exactly-one-claim-ready",
                    "no-peer-connection-observed",
                    ("ack", "claim-ready", "terminal", "EOF"),
                    4,
                ),
                (
                    "ack-status",
                    "host-facing-execute-root",
                    "exactly-one-claim-ready",
                    "exactly-one-authenticated-peer-connection-observed",
                    (
                        "ack",
                        "claim-ready",
                        "credential-peer-accepted",
                        "terminal",
                        "EOF",
                    ),
                    4,
                ),
                (
                    "ack-status",
                    "every-other-host-facing-root",
                    "forbidden",
                    "not-applicable",
                    ("ack", "terminal", "EOF"),
                    2,
                ),
                (
                    "ack-status",
                    "every-target-including-execute-target",
                    "forbidden",
                    "not-applicable",
                    ("ack", "terminal", "EOF"),
                    2,
                ),
                (
                    "go",
                    "every-applicable-constructor-control-context",
                    "not-applicable",
                    "not-applicable",
                    ("go", "writer-close", "observed-EOF"),
                    1,
                ),
            ),
        )
        ack_go_binding_table = (
            (
                "frame_kind",
                "fixed_role",
                "authentication_requirement",
                "exact_bound_fields",
            ),
            (
                (
                    "ack",
                    "ack-status",
                    "authenticated",
                    (
                        "protocol-version",
                        "descriptor-nonce",
                        "descriptor-hash",
                        "constructor-class",
                        "constructor-table-hash",
                        "PID",
                        "process-creation-time",
                    ),
                ),
                (
                    "go",
                    "go",
                    "authenticated",
                    (
                        "protocol-version",
                        "descriptor-nonce",
                        "descriptor-hash",
                        "constructor-class",
                        "constructor-table-hash",
                        "PID",
                        "process-creation-time",
                    ),
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-static-constructor-ack-status-and-go-control-roles",
            "ack-status-go-broker-request-and-broker-response-are-four-distinct-fixed-role-handle-and-lifetime-domains",
            "credential-data-and-credential-host-status-are-additional-distinct-noninherited-dynamic-role-domains-and-are-out-of-scope",
            "no-included-role-may-alias-any-static-or-dynamic-control-handle-or-lifetime",
            "each-control-frame-is-exactly-four-byte-unsigned-little-endian-payload-byte-length-followed-by-canonical-strict-UTF-8-JSON",
            "the-payload-cap-is-exactly-65536-bytes-and-the-maximum-single-frame-wire-size-is-65540-bytes",
            "the-six-grammar-rows-are-the-exact-permitted-static-constructor-control-grammars",
            "every-ack-status-sequence-begins-with-exactly-one-ack-and-ends-with-exactly-one-terminal-followed-by-EOF",
            "an-execute-root-permits-zero-or-one-claim-ready-frame",
            "credential-peer-accepted-is-present-exactly-once-if-and-only-if-one-claim-ready-is-followed-by-an-authenticated-peer-connection",
            "every-nonexecute-root-permits-only-ack-terminal-EOF",
            "every-target-including-an-execute-target-permits-only-ack-terminal-EOF",
            "an-execute-target-never-emits-claim-ready-or-credential-peer-accepted-on-ack-status",
            "the-execute-target-secret-free-capability-content-and-transport-semantics-are-out-of-scope",
            "GO-is-exactly-one-authenticated-go-frame-followed-immediately-by-writer-close-and-observed-EOF",
            "ACK-and-GO-bind-exactly-the-seven-listed-protocol-descriptor-constructor-and-process-identity-fields",
            "execute-ack-status-has-a-four-frame-wire-budget-ordinary-ack-status-a-two-frame-wire-budget-and-GO-a-one-frame-wire-budget",
            "early-duplicate-reordered-or-unknown-frame-trailing-byte-missing-EOF-or-ack-status-close-before-terminal-is-terminal-Job-failure",
            "a-control-grammar-failure-never-publishes-a-success-record",
            "broker-request-and-broker-response-sequencing-count-response-and-EOF-semantics-are-out-of-scope",
            "dynamic-credential-role-name-direction-peer-authentication-and-lifecycle-semantics-are-out-of-scope",
            "terminal-claim-ready-and-credential-peer-accepted-payload-schemas-are-not-defined-by-this-registry",
            "this-registry-grants-no-context-selection-canonicalization-encoding-decoding-frame-parsing-authentication-read-write-close-Job-termination-success-publication-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                frame_wire_rule_table,
                control_role_table,
                grammar_table,
                ack_go_binding_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def frame_wire_rule_table(self):
        return self[1]

    @property
    def control_role_table(self):
        return self[2]

    @property
    def grammar_table(self):
        return self[3]

    @property
    def ack_go_binding_table(self):
        return self[4]

    @property
    def invariants(self):
        return self[5]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftConstructorControlFrameGrammarFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "frame_wire_rule_row_count="
            f"{len(self.frame_wire_rule_table[1])!r}, "
            "control_role_row_count="
            f"{len(self.control_role_table[1])!r}, "
            "grammar_row_count="
            f"{len(self.grammar_table[1])!r}, "
            "ack_go_binding_row_count="
            f"{len(self.ack_go_binding_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftPostCapabilityCredentialRoleFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if (
            cls
            is not _C6BrokerNativeCoreDraftPostCapabilityCredentialRoleFactsRegistry
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "protocol_scope",
                "included_dynamic_roles",
                "boundary_status_events",
                "excluded_semantic_roles",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "post-capability-dynamic-credential-role-construction-and-peer-admission",
                    ("credential-data", "credential-host-status"),
                    ("claim-ready", "credential-peer-accepted"),
                    ("broker-request", "broker-response"),
                ),
            ),
        )
        name_derivation_table = (
            (
                "transport_version",
                "digest_algorithm",
                "digest_input_encoding",
                "literal_first_line",
                "ordered_bound_field_lines",
                "line_separator",
                "terminal_line_separator_required",
                "suffix_projection",
                "suffix_alphabet",
            ),
            (
                (
                    "complete-suite-provider-credential-pipe-v1",
                    "SHA-256",
                    "ASCII",
                    "complete-suite-provider-credential-pipe-v1",
                    (
                        "root_descriptor_nonce",
                        "target_descriptor_nonce",
                        "provider_attempt_claim_sha256",
                    ),
                    "LF",
                    True,
                    "first-32-lowercase-hex-characters",
                    "0123456789abcdef",
                ),
            ),
        )
        role_endpoint_table = (
            (
                "dynamic_role",
                "name_record_type",
                "name_record_version",
                "pipe_name_prefix",
                "name_grammar_bytes",
                "name_grammar_sha256",
                "root_action",
                "server_access_mode",
                "host_action",
                "client_access",
                "root_completion_key",
                "host_completion_key",
                "payload_cap_bytes",
                "endpoint_byte_cap_bytes",
                "wire_cap_formula",
            ),
            (
                (
                    "credential-data",
                    "ExecuteCredentialPipeName",
                    "complete-suite-execute-credential-pipe-name-v1",
                    "\\\\.\\pipe\\kokoroarc-c6-execute-",
                    (
                        b"complete-suite-execute-credential-pipe-name-v1\n"
                        b"\\\\.\\pipe\\kokoroarc-c6-execute-<32-lowercase-hex>\n"
                    ),
                    "29078e6b8f6b81c33cbd530d75d50af49d57efeb7cbf178772b6991ceb90dba7",
                    "reads",
                    "PIPE_ACCESS_INBOUND",
                    "writes",
                    "GENERIC_WRITE",
                    "credential-data",
                    "credential-data-write",
                    65_536,
                    65_540,
                    "4+65536",
                ),
                (
                    "credential-host-status",
                    "ExecuteCredentialHostStatusPipeName",
                    "complete-suite-execute-credential-host-status-pipe-name-v1",
                    "\\\\.\\pipe\\kokoroarc-c6-execute-status-",
                    (
                        b"complete-suite-execute-credential-host-status-pipe-name-v1\n"
                        b"\\\\.\\pipe\\kokoroarc-c6-execute-status-<32-lowercase-hex>\n"
                    ),
                    "9c3c0b32ef2fc6d043800293ae1cb964fc0a212a9107472e9a8326c855be7837",
                    "reads",
                    "PIPE_ACCESS_INBOUND",
                    "writes",
                    "GENERIC_WRITE",
                    "credential-host-status",
                    "credential-host-status-write",
                    65_536,
                    65_540,
                    "F(65536,1)",
                ),
            ),
        )
        server_construction_table = (
            (
                "applies_to_dynamic_roles",
                "creator",
                "dwOpenMode_tokens",
                "dwPipeMode_tokens",
                "nMaxInstances",
                "nOutBufferSize",
                "nInBufferSize",
                "nDefaultTimeOut",
                "security_attributes_inheritable",
                "owner",
                "dacl_state",
                "explicit_ace_count",
                "explicit_ace_flags",
                "explicit_ace_type",
                "explicit_ace_trustee",
                "explicit_ace_access",
                "forbidden_ace_categories",
                "all_dynamic_role_handles_inheritable",
                "descriptor_membership",
                "HANDLE_LIST_membership",
                "security_requery_boundary",
            ),
            (
                (
                    ("credential-data", "credential-host-status"),
                    "execute-root-broker",
                    (
                        "PIPE_ACCESS_INBOUND",
                        "FILE_FLAG_FIRST_PIPE_INSTANCE",
                        "FILE_FLAG_OVERLAPPED",
                    ),
                    (
                        "PIPE_TYPE_BYTE",
                        "PIPE_READMODE_BYTE",
                        "PIPE_WAIT",
                        "PIPE_REJECT_REMOTE_CLIENTS",
                    ),
                    1,
                    0,
                    65_540,
                    0,
                    False,
                    "root-current-TokenUser-SID",
                    ("present", "non-defaulted", "protected"),
                    1,
                    0,
                    "explicit-allow",
                    "same-root-current-TokenUser-SID",
                    "FILE_GENERIC_WRITE",
                    (
                        "inherited",
                        "group",
                        "world",
                        "anonymous",
                        "system",
                        "additional",
                    ),
                    False,
                    "forbidden",
                    "forbidden",
                    "both-servers-before-claim-ready",
                ),
            ),
        )
        host_client_construction_table = (
            (
                "applies_to_dynamic_roles",
                "creator",
                "open_api",
                "open_count_per_bound_name",
                "desired_access",
                "share_mode",
                "creation_disposition",
                "flag_tokens",
                "inheritable",
                "security_requery_boundary",
                "forbidden_actions",
            ),
            (
                (
                    ("credential-data", "credential-host-status"),
                    "trusted-host",
                    "CreateFileW",
                    1,
                    "GENERIC_WRITE",
                    0,
                    "OPEN_EXISTING",
                    (
                        "FILE_FLAG_OVERLAPPED",
                        "SECURITY_SQOS_PRESENT",
                        "SECURITY_IDENTIFICATION",
                    ),
                    False,
                    "both-client-handles-after-open-and-before-credential-lookup",
                    (
                        "WaitNamedPipe",
                        "retry",
                        "reconnect",
                        "second-open",
                        "DisconnectNamedPipe",
                        "instance-reuse",
                    ),
                ),
            ),
        )
        admission_table = (
            (
                "gate",
                "actor",
                "required_predecessors",
                "required_action_or_match",
                "cardinality",
                "successor_boundary",
                "failure_disposition",
            ),
            (
                (
                    "dynamic-pair-construction",
                    "execute-root-broker",
                    (
                        "authenticated-GO",
                        "root-independent-validation-of-one-post-GO-execute-claim-capability",
                    ),
                    "exact-capability-agreement-permits-construction",
                    "exactly-one-paired-instance",
                    "root-server-arm",
                    "fail-closed-before-claim-ready",
                ),
                (
                    "claim-ready-emission",
                    "execute-root-broker",
                    (
                        "both-exact-servers-created",
                        "both-owner-and-DACL-requeries-succeeded",
                        "both-servers-associated-with-root-private-IOCP-under-distinct-typed-keys",
                        "exactly-one-overlapped-ConnectNamedPipe-issued-per-server",
                    ),
                    "each-initial-ConnectNamedPipe-result-is-FALSE/ERROR_IO_PENDING",
                    "exactly-one-result-per-dynamic-role",
                    "host-validates-claim-ready-before-open",
                    "synchronous-success-ERROR_PIPE_CONNECTED-or-any-other-result-is-unauthorized-pre-readiness-race-and-fail-closed",
                ),
                (
                    "host-open-and-root-peer-verification",
                    "trusted-host",
                    ("exactly-one-authenticated-bound-claim-ready-validated",),
                    (
                        "open-each-bound-name-once-associate-both-with-host-private-IOCP-"
                        "before-any-write-and-query-each-server-with-"
                        "PROCESS_QUERY_LIMITED_INFORMATION"
                    ),
                    "exactly-one-open-and-one-root-identity-match-per-dynamic-role",
                    "root-consumes-connect-completions",
                    "consume-both-one-shot-instances-and-fail-closed",
                ),
                (
                    "root-connect-and-host-peer-verification",
                    "execute-root-broker",
                    ("both-successful-connect-completions-consumed",),
                    (
                        "query-each-client-with-PROCESS_QUERY_LIMITED_INFORMATION-and-"
                        "match-the-same-descriptor-bound-host-PID-and-creation-time"
                    ),
                    (
                        "exactly-one-connect-completion-and-one-host-identity-match-"
                        "per-dynamic-role"
                    ),
                    "credential-peer-accepted-emission",
                    "consume-both-one-shot-instances-and-fail-closed",
                ),
                (
                    "credential-peer-accepted-and-fresh-host-revalidation",
                    "execute-root-broker-and-trusted-host",
                    ("root-authenticated-both-host-peers",),
                    (
                        "emit-and-validate-exactly-one-canonical-"
                        "ExecuteCredentialPeerAccepted-binding-capability-claim-both-"
                        "pipe-name-hashes-and-both-host-and-root-PID-creation-time-"
                        "identities-then-freshly-repeat-host-state-validation"
                    ),
                    "exactly-one",
                    "credential-lookup-boundary",
                    "consume-both-one-shot-instances-and-fail-closed",
                ),
            ),
        )
        shared_constructor_binding_table = (
            (
                "state_machine_id",
                "applies_to_endpoint_domains",
                "required_fact_bindings",
            ),
            (
                (
                    "complete-suite-native-constructor-state-machine-v1",
                    (
                        "execute-root-broker-server-endpoints",
                        "trusted-host-client-endpoints",
                    ),
                    (
                        (
                            "issue-ledger-and-exact-packet-retirement",
                            "_C6BrokerNativeCoreDraftIocpOperationIssueFactsRegistry",
                        ),
                        (
                            "symbolic-IOCP-dispatch",
                            "_C6BrokerNativeCoreDraftIocpDispatchResultFactsRegistry",
                        ),
                        (
                            "successful-zero-byte-write-failure",
                            "_C6BrokerNativeCoreDraftIocpSuccessfulZeroByteWriteResultFactsRegistry",
                        ),
                        (
                            "absolute-deadline-wait-window",
                            "_C6BrokerNativeCoreDraftIocpWaitWindow",
                        ),
                        (
                            "bounded-read-window",
                            "_C6BrokerNativeCoreDraftWireReadWindow",
                        ),
                        (
                            "length-prefixed-frame-cap-admission",
                            "_C6BrokerNativeCoreDraftControlFrameAdmission",
                        ),
                        (
                            "CancelIoEx-call-result",
                            "_C6BrokerNativeCoreDraftIocpCancelIoExAcceptedCallResultFactsRegistry",
                        ),
                        (
                            "cleanup-completion-retirement",
                            "_C6BrokerNativeCoreDraftIocpCleanupCompletionFactsRegistry",
                        ),
                        (
                            "writer-close-eligibility",
                            "_C6BrokerNativeCoreDraftIocpWriterCloseEligibilityFactsRegistry",
                        ),
                        (
                            "single-failure-grace",
                            "_C6BrokerNativeCoreDraftIocpFailureGraceFactsRegistry",
                        ),
                        (
                            "reconciled-close-order",
                            "_C6BrokerNativeCoreDraftIocpGraceReconciledCloseOrderFactsRegistry",
                        ),
                        (
                            "expiry-quarantine",
                            "_C6BrokerNativeCoreDraftIocpGraceExpiryQuarantineFactsRegistry",
                        ),
                        (
                            "overall-success-convergence",
                            "_C6BrokerNativeCoreDraftIocpSuccessConvergenceFactsRegistry",
                        ),
                    ),
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-the-post-capability-dynamic-credential-data-and-credential-host-status-role-pair",
            "pair-construction-is-permitted-only-after-root-independent-validation-of-one-post-GO-execute-claim-capability",
            "credential-data-and-credential-host-status-are-distinct-noninherited-dynamic-role-handle-key-buffer-operation-and-lifetime-domains",
            "neither-dynamic-role-may-alias-the-other-or-any-static-constructor-control-handle-key-buffer-operation-or-lifetime",
            "no-dynamic-role-handle-is-inheritable-or-present-in-any-descriptor-or-HANDLE_LIST",
            "both-pipe-names-use-the-same-derived-P-and-neither-name-is-caller-supplied",
            "both-name-records-bind-transport-value-value-hash-root-and-target-nonces-claim-hash-payload-cap-and-grammar-digest",
            "neither-name-record-depends-on-a-later-status-or-lifecycle-hash",
            "both-server-instances-must-be-created-armed-associated-and-security-requeried-before-claim-ready",
            "each-server-accepts-only-the-initial-FALSE/ERROR_IO_PENDING-ConnectNamedPipe-result",
            "both-root-and-host-completion-key-domains-are-distinct-and-typed-per-dynamic-role",
            "the-host-opens-each-bound-name-exactly-once-only-after-validating-claim-ready",
            "both-sides-use-only-PROCESS_QUERY_LIMITED_INFORMATION-for-peer-process-identity",
            "both-handles-on-each-side-must-match-the-same-authenticated-peer-PID-and-creation-time",
            "credential-peer-accepted-is-emitted-only-after-both-connect-completions-and-both-root-side-host-identity-checks-succeed",
            "credential-peer-accepted-binds-the-capability-claim-both-pipe-name-hashes-and-both-host-and-root-PID-creation-time-identities",
            "credential-lookup-remains-forbidden-until-the-host-validates-exactly-one-peer-accepted-frame-and-freshly-revalidates-state",
            "any-connection-association-security-identity-status-frame-or-fresh-state-mismatch-consumes-both-one-shot-instances-with-no-reconnect-or-reuse",
            "credential-data-has-exact-byte-cap-65540-from-4-plus-65536",
            "credential-host-status-has-exact-byte-cap-65540-from-F(65536,1)",
            "both-dynamic-roles-use-the-shared-constructor-ledger-dispatch-deadline-cap-cancellation-retirement-close-and-quarantine-rules",
            "neither-dynamic-role-may-extend-the-one-continuously-decreasing-root-role-absolute-deadline",
            "admission-predecessor-tuples-are-conjunctive-partial-order-gates-and-registry-row-order-grants-no-extra-runtime-order",
            "credential-payload-parsing-value-classification-ASCII-validation-and-EOF-outcome-semantics-are-out-of-scope",
            "credential-host-status-payload-fields-counters-progress-outcomes-and-data-status-join-semantics-are-out-of-scope",
            "credential-and-pipe-lifecycle-records-buffer-scrubbing-and-persistence-semantics-are-out-of-scope",
            "broker-request-and-broker-response-wrapper-sequence-response-count-and-EOF-semantics-are-out-of-scope",
            "this-registry-grants-no-name-derivation-pipe-creation-association-connect-open-process-query-frame-emission-validation-I/O-close-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                name_derivation_table,
                role_endpoint_table,
                server_construction_table,
                host_client_construction_table,
                admission_table,
                shared_constructor_binding_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def name_derivation_table(self):
        return self[1]

    @property
    def role_endpoint_table(self):
        return self[2]

    @property
    def server_construction_table(self):
        return self[3]

    @property
    def host_client_construction_table(self):
        return self[4]

    @property
    def admission_table(self):
        return self[5]

    @property
    def shared_constructor_binding_table(self):
        return self[6]

    @property
    def invariants(self):
        return self[7]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftPostCapabilityCredentialRoleFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "name_derivation_row_count="
            f"{len(self.name_derivation_table[1])!r}, "
            "role_endpoint_row_count="
            f"{len(self.role_endpoint_table[1])!r}, "
            "server_construction_row_count="
            f"{len(self.server_construction_table[1])!r}, "
            "host_client_construction_row_count="
            f"{len(self.host_client_construction_table[1])!r}, "
            "admission_row_count="
            f"{len(self.admission_table[1])!r}, "
            "shared_constructor_binding_row_count="
            f"{len(self.shared_constructor_binding_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftBrokerDuplexProtocolFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftBrokerDuplexProtocolFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "protocol_scope",
                "applicable_subject_kind",
                "included_fixed_roles",
                "activation_boundary",
                "excluded_semantic_scopes",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "guarded-target-retained-broker-request-response-duplex-protocol",
                    "guarded-python-target",
                    ("broker-request", "broker-response"),
                    "authenticated-GO",
                    (
                        "execute-claim-capability-payload-schema",
                        "credential-data",
                        "credential-host-status",
                        "credential-lifecycle",
                    ),
                ),
            ),
        )
        frame_wire_rule_table = (
            (
                "length_prefix_bytes",
                "length_prefix_type",
                "length_prefix_endianness",
                "payload_encoding",
                "payload_canonical_form",
                "payload_cap_bytes",
                "maximum_frame_wire_bytes",
            ),
            (
                (
                    4,
                    "unsigned-payload-byte-length",
                    "little-endian",
                    "strict-UTF-8",
                    "canonical-JSON",
                    65_536,
                    65_540,
                ),
            ),
        )
        role_table = (
            (
                "fixed_role",
                "root_action",
                "server_open_mode",
                "target_action",
                "target_access",
                "retained_after_authenticated_GO",
                "target_endpoint_lifetime",
                "handle_and_lifetime_alias_policy",
                "per_target_frame_count_cap",
                "per_target_byte_cap",
                "root_aggregate_frame_count_cap",
                "root_aggregate_byte_cap",
            ),
            (
                (
                    "broker-request",
                    "reads",
                    "PIPE_ACCESS_INBOUND",
                    "writes",
                    "GENERIC_WRITE",
                    True,
                    "retained-until-orderly-shutdown-EOF-handshake",
                    "distinct-no-alias",
                    1_024,
                    67_112_960,
                    4_096,
                    268_451_840,
                ),
                (
                    "broker-response",
                    "writes",
                    "PIPE_ACCESS_OUTBOUND",
                    "reads",
                    "GENERIC_READ",
                    True,
                    "retained-until-orderly-shutdown-EOF-handshake",
                    "distinct-no-alias",
                    1_024,
                    67_112_960,
                    4_096,
                    268_451_840,
                ),
            ),
        )
        request_table = (
            (
                "producer",
                "admission_boundary",
                "initial_sequence",
                "sequence_progression",
                "outstanding_request_cap",
                "exact_bound_fields",
                "requested_role_scope",
                "payload_digest_verification",
            ),
            (
                (
                    "guarded-target",
                    "only-after-authenticated-GO",
                    1,
                    "strictly-monotonically-increasing",
                    1,
                    (
                        "protocol-version",
                        "root-descriptor-nonce",
                        "root-descriptor-hash",
                        "target-descriptor-nonce",
                        "target-descriptor-hash",
                        "requested-closed-role",
                        "canonical-payload-bytes",
                        "payload-SHA-256",
                    ),
                    "closed-role-only",
                    "payload-SHA-256-must-match-canonical-payload-bytes",
                ),
            ),
        )
        response_table = (
            (
                "producer",
                "request_correlation",
                "repeated_descriptor_bindings",
                "decision_cardinality",
                "branch_cardinality",
                "result_branch",
                "error_branch",
                "target_result_verification",
                "outstanding_request_effect",
            ),
            (
                (
                    "root-broker",
                    "repeat-request-sequence",
                    (
                        "root-descriptor-nonce",
                        "root-descriptor-hash",
                        "target-descriptor-nonce",
                        "target-descriptor-hash",
                    ),
                    "exactly-one-closed-decision",
                    "exactly-one-result-or-error-branch",
                    (
                        "canonical-result-payload-bytes",
                        "result-payload-SHA-256",
                    ),
                    ("stable-public-error-code",),
                    "verify-result-payload-SHA-256-before-use",
                    "clear-sole-outstanding-request-only-after-exact-response-validation",
                ),
            ),
        )
        cap_table = (
            (
                "counter_scope",
                "pair_count_cap",
                "request_frame_count_cap",
                "response_frame_count_cap",
                "request_byte_cap",
                "response_byte_cap",
                "counter_policy",
                "next_frame_admission_policy",
            ),
            (
                (
                    "per-target",
                    1_024,
                    1_024,
                    1_024,
                    67_112_960,
                    67_112_960,
                    "separate-monotonically-increasing-request-and-response-counters",
                    "both-frame-count-and-byte-cap-must-admit-before-next-frame",
                ),
                (
                    "root-aggregate-across-all-targets",
                    4_096,
                    4_096,
                    4_096,
                    268_451_840,
                    268_451_840,
                    "separate-monotonically-increasing-request-and-response-counters",
                    "both-frame-count-and-byte-cap-must-admit-before-next-frame",
                ),
            ),
        )
        state_table = (
            (
                "current_state",
                "event",
                "required_condition",
                "resulting_outstanding_request_count",
                "resulting_next_sequence",
                "disposition",
            ),
            (
                (
                    "post-authenticated-GO-ready",
                    "send-request",
                    "sequence-equals-next-bindings-and-digest-validate-and-all-count-byte-caps-admit",
                    1,
                    "unchanged-until-matching-response",
                    "awaiting-exact-response",
                ),
                (
                    "awaiting-response",
                    "send-request",
                    "forbidden-because-exactly-one-request-is-already-outstanding",
                    1,
                    "unchanged",
                    "terminal-Job-failure-no-success",
                ),
                (
                    "awaiting-response",
                    "receive-response",
                    "sequence-and-descriptor-bindings-repeat-and-exactly-one-closed-branch-validates",
                    0,
                    "greater-than-completed-sequence",
                    "ready-or-cap-exhausted",
                ),
                (
                    "ready-or-awaiting-response",
                    "frame-sequence-binding-order-count-response-deadline-or-EOF-drift",
                    "any-drift-is-forbidden",
                    "frozen-at-failure-observation",
                    "frozen-at-failure-observation",
                    "terminal-Job-failure-no-success",
                ),
            ),
        )
        shutdown_table = (
            (
                "step",
                "actor",
                "required_precondition",
                "action",
                "required_peer_observation",
                "successor_boundary",
            ),
            (
                (
                    1,
                    "guarded-target",
                    "no-outstanding-request",
                    "close-broker-request-writer",
                    "root-requires-broker-request-EOF",
                    "root-response-writer-close-eligibility",
                ),
                (
                    2,
                    "root-broker",
                    "broker-request-EOF-observed",
                    "close-broker-response-writer",
                    "target-requires-broker-response-EOF",
                    "target-terminal-status-frame-eligibility",
                ),
                (
                    3,
                    "guarded-target",
                    "broker-response-EOF-observed",
                    "emit-target-terminal-status-frame",
                    "terminal-frame-required-by-root",
                    "target-broker-duplex-shutdown-complete",
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-retained-guarded-target-broker-request-and-broker-response-fixed-role-channels",
            "broker-request-and-broker-response-are-distinct-from-each-other-and-from-ACK-status-GO-and-all-dynamic-credential-handle-and-lifetime-domains",
            "among-broker-duplex-endpoints-the-guarded-target-retains-only-its-broker-request-writer-and-broker-response-reader-after-authenticated-GO",
            "no-request-is-permitted-before-authenticated-GO",
            "request-sequence-begins-at-one-and-each-later-request-sequence-is-strictly-greater-than-the-previously-completed-request-sequence",
            "each-request-binds-exactly-protocol-version-root-and-target-descriptor-nonce-hash-requested-closed-role-canonical-payload-bytes-and-payload-SHA-256",
            "requested-role-is-closed-and-request-payload-SHA-256-must-match-the-canonical-payload-bytes",
            "exactly-one-request-may-be-outstanding-per-target",
            "each-response-repeats-the-request-sequence-and-all-four-root-target-descriptor-nonce-hash-bindings",
            "each-response-has-exactly-one-closed-decision-and-exactly-one-canonical-result-plus-hash-or-stable-public-error-branch",
            "the-target-verifies-result-payload-bytes-against-the-returned-SHA-256-before-use",
            "per-target-request-and-response-count-caps-are-each-1024-and-byte-caps-are-each-67112960",
            "root-aggregate-request-and-response-count-caps-are-each-4096-and-byte-caps-are-each-268451840",
            "per-target-and-root-aggregate-request-and-response-counters-are-four-separate-monotonically-increasing-counters",
            "all-applicable-frame-count-and-byte-caps-must-admit-before-the-next-request-or-response-frame",
            "target-shutdown-requires-no-outstanding-request-then-request-writer-close-root-request-EOF-response-writer-close-target-response-EOF-and-only-then-target-terminal-status",
            "no-request-response-or-descendant-may-extend-the-one-continuously-decreasing-root-role-absolute-deadline",
            "frame-cap-sequence-binding-ordering-count-response-deadline-or-EOF-drift-terminates-the-Job",
            "broker-duplex-failure-publishes-no-success-record",
            "execute-claim-capability-request-payload-fields-and-root-validation-semantics-are-out-of-scope",
            "credential-data-credential-host-status-peer-authentication-counters-and-lifecycle-semantics-are-out-of-scope",
            "this-registry-grants-no-role-selection-frame-encoding-decoding-hashing-authentication-I/O-counter-deadline-close-Job-termination-success-publication-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                frame_wire_rule_table,
                role_table,
                request_table,
                response_table,
                cap_table,
                state_table,
                shutdown_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def frame_wire_rule_table(self):
        return self[1]

    @property
    def role_table(self):
        return self[2]

    @property
    def request_table(self):
        return self[3]

    @property
    def response_table(self):
        return self[4]

    @property
    def cap_table(self):
        return self[5]

    @property
    def state_table(self):
        return self[6]

    @property
    def shutdown_table(self):
        return self[7]

    @property
    def invariants(self):
        return self[8]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftBrokerDuplexProtocolFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "frame_wire_rule_row_count="
            f"{len(self.frame_wire_rule_table[1])!r}, "
            "role_row_count="
            f"{len(self.role_table[1])!r}, "
            "request_row_count="
            f"{len(self.request_table[1])!r}, "
            "response_row_count="
            f"{len(self.response_table[1])!r}, "
            "cap_row_count="
            f"{len(self.cap_table[1])!r}, "
            "state_row_count="
            f"{len(self.state_table[1])!r}, "
            "shutdown_row_count="
            f"{len(self.shutdown_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftExecuteClaimCapabilityFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftExecuteClaimCapabilityFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "protocol_scope",
                "producer",
                "consumer",
                "request_role",
                "activation_boundary",
                "excluded_semantic_scopes",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "execute-claim-capability-secret-free-payload-and-root-independent-validation",
                    "authenticated-execute-root-role-target",
                    "trusted-root-broker",
                    "execute-claim-capability",
                    "post-authenticated-GO-after-complete-claimed-campaign-preparation-and-frozen-client-identity-reopen",
                    (
                        "execute-claim-ready-and-credential-peer-accepted-payloads",
                        "dynamic-credential-pipe-construction-and-peer-admission",
                        "credential-lookup-transfer-and-counters",
                        "credential-and-pipe-lifecycle",
                        "broker-response-projection-and-lifecycle-persistence",
                    ),
                ),
            ),
        )
        payload_schema_table = (
            (
                "record_type",
                "schema_version",
                "serialized_field_order",
                "wrapper_only_fields",
                "raw_root_identity_field_order",
                "canonical_payload_contract",
                "forbidden_payload_categories",
                "credential_literal_policy",
            ),
            (
                (
                    "ExecuteClaimCapability",
                    "complete-suite-execute-claim-capability-v1",
                    (
                        "version",
                        "root_descriptor_nonce",
                        "root_descriptor_sha256",
                        "target_descriptor_nonce",
                        "target_descriptor_sha256",
                        "constructor_implementation_set_sha256",
                        "constructor_attribute_set_sha256",
                        "job_topology_sha256",
                        "approved_campaign_sha256",
                        "approval_envelope_sha256",
                        "approval_prompt_sha256",
                        "provider_approval_sha256",
                        "provider_execution_authorization_sha256",
                        "reservation_sha256",
                        "preclaim_snapshot_sha256",
                        "execute_consumption_sha256",
                        "provider_attempt_claim_sha256",
                        "raw_root_identity",
                        "frozen_client_identity_sha256",
                        "client_launch_template_sha256",
                        "credential_transport_version",
                        "credential_environment_name",
                        "target_pid",
                        "target_creation_time",
                    ),
                    ("canonical_sha256",),
                    (
                        "device",
                        "inode",
                        "file_type",
                        "reparse_tag",
                        "link_count",
                    ),
                    "inherit-broker-duplex-canonical-JSON-strict-UTF-8-payload-and-SHA-256-contract",
                    (
                        "filesystem-path",
                        "credential-value",
                        "environment-mapping",
                        "free-form-message",
                        "caller-selected-expected-value",
                        "unknown-or-extra-field",
                    ),
                    "OPENAI_API_KEY-name-literal-is-allowed-but-no-credential-value-or-environment-mapping",
                ),
            ),
        )
        request_admission_table = (
            (
                "request_role",
                "producer",
                "admission_predecessors",
                "sequence_binding",
                "send_cardinality",
                "outstanding_request_cardinality",
                "canonical_payload_type",
                "target_wait_policy",
                "target_forbidden_capabilities",
                "successor_boundary",
            ),
            (
                (
                    "execute-claim-capability",
                    "authenticated-execute-root-role-target",
                    (
                        "authenticated-GO",
                        "complete-claimed-campaign-preparation",
                        "frozen-client-identity-reopen-and-validation",
                        "both-lifecycle-destinations-proven-absent",
                    ),
                    "exact-target-next-broker-sequence",
                    "at-most-once-per-execute-target",
                    "sole-outstanding-broker-request",
                    "ExecuteClaimCapability",
                    "block-with-capability-as-sole-outstanding-request",
                    (
                        "secret-pipe-constructor",
                        "host-status-writer",
                        "credential-receiver",
                        "spawn-environment-materializer",
                        "client-constructor",
                    ),
                    "root-independent-validation-before-dynamic-pair-construction",
                ),
            ),
        )
        validator_interface_table = (
            (
                "function_name",
                "implementation_boundary",
                "ordered_arguments",
                "input_authority",
                "forbidden_parameter_categories",
                "return_type",
                "import_policy",
                "mutation_policy",
            ),
            (
                (
                    "validate_execute_claim_capability_stdlib",
                    "locked-Task-9-broker-module",
                    (
                        "capability_bytes",
                        "root_descriptor_bytes",
                        "target_descriptor_bytes",
                        "opened_campaign_bytes",
                        "opened_approval_envelope_bytes",
                        "opened_prompt_bytes",
                        "opened_provider_record_bytes",
                        "opened_reservation_bytes",
                        "preclaim_snapshot_bytes",
                        "opened_execute_consumption_bytes",
                        "opened_claim_bytes",
                        "raw_root_snapshot",
                        "opened_candidate_inputs_bytes",
                    ),
                    "descriptor-opened-bytes-and-retained-pre-ACK-snapshot-bytes-only",
                    (
                        "callback",
                        "filesystem-path",
                        "repository-object",
                        "Task-10-authorization-object",
                        "caller-supplied-authorization-bytes",
                        "caller-provided-expected-field",
                    ),
                    "one-validated-ExecuteClaimCapability",
                    "stdlib-only-no-Task-10-through-16-or-repository-import",
                    "read-only-reopen-validation-with-no-durable-write",
                ),
            ),
        )
        source_binding_table = (
            (
                "source_family",
                "input_source",
                "independent_acquisition",
                "bound_capability_fields",
                "additional_required_agreement",
            ),
            (
                (
                    "root-descriptor",
                    "root_descriptor_bytes",
                    "authenticated-descriptor-input-bytes",
                    (
                        "root_descriptor_nonce",
                        "root_descriptor_sha256",
                        "constructor_implementation_set_sha256",
                        "constructor_attribute_set_sha256",
                        "job_topology_sha256",
                    ),
                    (
                        "derive-every-reopen-path-from-authenticated-root-descriptor",
                        "validate-root-PID-and-creation-time-without-serializing-them",
                    ),
                ),
                (
                    "target-descriptor",
                    "target_descriptor_bytes",
                    "authenticated-descriptor-input-bytes",
                    (
                        "target_descriptor_nonce",
                        "target_descriptor_sha256",
                        "target_pid",
                        "target_creation_time",
                    ),
                    ("repeat-constructor-digest-agreement",),
                ),
                (
                    "approved-campaign",
                    "opened_campaign_bytes",
                    "descriptor-bound-no-follow-reopen",
                    ("approved_campaign_sha256",),
                    ("exact-canonical-bytes-and-hash",),
                ),
                (
                    "approval-envelope",
                    "opened_approval_envelope_bytes",
                    "descriptor-bound-no-follow-reopen",
                    ("approval_envelope_sha256",),
                    ("exact-canonical-bytes-and-hash",),
                ),
                (
                    "approval-prompt",
                    "opened_prompt_bytes",
                    "descriptor-bound-no-follow-reopen",
                    ("approval_prompt_sha256",),
                    ("exact-canonical-bytes-and-hash",),
                ),
                (
                    "provider-approval-record",
                    "opened_provider_record_bytes",
                    "descriptor-bound-no-follow-reopen",
                    ("provider_approval_sha256",),
                    ("exact-canonical-bytes-and-hash",),
                ),
                (
                    "authorization-reservation",
                    "opened_reservation_bytes",
                    "descriptor-bound-no-follow-reopen",
                    ("reservation_sha256",),
                    ("exact-canonical-bytes-hash-identity-and-parent",),
                ),
                (
                    "retained-pre-ACK-snapshot",
                    "preclaim_snapshot_bytes",
                    "exact-broker-memory-bytes-retained-before-ACK",
                    ("preclaim_snapshot_sha256",),
                    ("exact-absence-facts-and-canonical-hash",),
                ),
                (
                    "execute-consumption-marker",
                    "opened_execute_consumption_bytes",
                    "descriptor-bound-no-follow-reopen",
                    ("execute_consumption_sha256",),
                    ("exact-canonical-bytes-hash-identity-and-parent",),
                ),
                (
                    "provider-attempt-claim",
                    "opened_claim_bytes",
                    "descriptor-bound-no-follow-reopen",
                    ("provider_attempt_claim_sha256",),
                    ("exact-canonical-bytes-hash-identity-and-parent",),
                ),
                (
                    "claimed-raw-root",
                    "raw_root_snapshot",
                    "descriptor-derived-no-follow-identity-and-membership-recapture",
                    ("raw_root_identity",),
                    ("exact-claim-bound-identity-ancestry-and-membership",),
                ),
                (
                    "candidate-input-aggregate",
                    "opened_candidate_inputs_bytes",
                    "descriptor-bound-no-follow-reopen",
                    (
                        "frozen_client_identity_sha256",
                        "client_launch_template_sha256",
                    ),
                    ("exact-canonical-bytes-hash-and-prepared-root-binding",),
                ),
                (
                    "stdlib-reconstructed-detached-authorization",
                    "root-descriptor-plus-five-reopened-facts-and-retained-pre-ACK-snapshot",
                    "separately-reviewed-stdlib-only-reconstruction",
                    (
                        "provider_execution_authorization_sha256",
                        "approved_campaign_sha256",
                        "approval_envelope_sha256",
                        "approval_prompt_sha256",
                        "provider_approval_sha256",
                        "reservation_sha256",
                        "preclaim_snapshot_sha256",
                        "credential_transport_version",
                        "credential_environment_name",
                    ),
                    (
                        "reconstructed-canonical-bytes-and-SHA-256-match-Task-10-differential-oracle",
                        "credential-transport-is-complete-suite-provider-credential-pipe-v1",
                        "credential-environment-name-is-OPENAI_API_KEY",
                    ),
                ),
            ),
        )
        validation_gate_table = (
            (
                "step",
                "gate",
                "required_action_or_match",
                "successor_boundary",
                "failure_boundary",
            ),
            (
                (
                    1,
                    "authenticated-request-admission",
                    "one-execute-target-request-with-exact-role-next-sequence-and-sole-outstanding-state",
                    "strict-capability-parse",
                    "reject-before-secret-pipe-creation-with-all-four-credential-counters-zero",
                ),
                (
                    2,
                    "strict-capability-parse",
                    "duplicate-key-free-exact-canonical-schema-key-order-and-payload-hash",
                    "descriptor-derived-path-resolution",
                    "reject-before-secret-pipe-creation-with-all-four-credential-counters-zero",
                ),
                (
                    3,
                    "descriptor-derived-path-resolution",
                    "derive-every-reopen-path-from-authenticated-root-descriptor-never-capability-bytes",
                    "independent-source-reopen",
                    "reject-before-secret-pipe-creation-with-all-four-credential-counters-zero",
                ),
                (
                    4,
                    "independent-source-reopen",
                    "no-follow-reopen-and-revalidate-every-descriptor-bound-input",
                    "detached-authorization-reconstruction",
                    "reject-before-secret-pipe-creation-with-all-four-credential-counters-zero",
                ),
                (
                    5,
                    "detached-authorization-reconstruction",
                    "reconstruct-canonical-provider-execution-authorization-with-stdlib-only-code",
                    "authorization-agreement",
                    "reject-before-secret-pipe-creation-with-all-four-credential-counters-zero",
                ),
                (
                    6,
                    "authorization-agreement",
                    "reconstructed-bytes-hash-six-constituent-hashes-and-two-credential-literals-agree-with-capability-and-descriptors",
                    "remaining-source-agreement",
                    "reject-before-secret-pipe-creation-with-all-four-credential-counters-zero",
                ),
                (
                    7,
                    "remaining-source-agreement",
                    "marker-claim-raw-root-identity-membership-candidate-input-client-template-constructor-and-target-identity-all-agree",
                    "conjunctive-validation-decision",
                    "reject-before-secret-pipe-creation-with-all-four-credential-counters-zero",
                ),
                (
                    8,
                    "conjunctive-validation-decision",
                    "all-predecessor-gates-succeed-with-exact-agreement",
                    "return-validated-capability-and-permit-dynamic-pair-construction",
                    "reject-before-secret-pipe-creation-with-all-four-credential-counters-zero",
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-the-secret-free-execute-claim-capability-payload-and-root-independent-stdlib-validation-boundary",
            "the-only-producer-is-the-authenticated-execute-root-role-target-and-the-only-consumer-is-the-trusted-root-broker",
            "the-request-role-is-exactly-execute-claim-capability",
            "the-request-is-forbidden-before-authenticated-GO-complete-claimed-campaign-preparation-frozen-client-reopen-and-both-lifecycle-slot-absence-proofs",
            "the-request-sequence-is-the-targets-exact-next-broker-sequence-and-is-not-hard-coded-to-one",
            "the-target-sends-at-most-one-capability-and-it-is-the-sole-outstanding-broker-request",
            "the-payload-is-exactly-one-secret-free-ExecuteClaimCapability-with-no-path-value-environment-mapping-free-form-message-caller-expected-value-or-extra-field",
            "the-twenty-four-serialized-fields-are-ordered-exactly-and-canonical_sha256-is-wrapper-only",
            "OPENAI_API_KEY-is-an-allowed-name-literal-but-no-credential-value-or-environment-mapping-is-permitted",
            "raw_root_identity-is-the-five-field-filesystem-identity-object-and-never-a-path",
            "root-PID-and-creation-time-are-validation-only-and-are-not-capability-fields",
            "the-validator-interface-is-exactly-thirteen-ordered-byte-or-snapshot-inputs-and-no-caller-authority-input",
            "every-reopen-path-is-derived-from-the-authenticated-root-descriptor-and-never-from-capability-bytes",
            "the-broker-independently-no-follow-reopens-and-revalidates-every-descriptor-bound-input",
            "the-broker-does-not-trust-the-targets-detached-validation-result",
            "the-validator-imports-no-Task-10-through-16-or-repository-object-and-accepts-no-Task-10-authorization-object-or-caller-authorization-bytes",
            "the-detached-provider-execution-authorization-is-reconstructed-by-separately-reviewed-stdlib-only-code",
            "the-six-authorization-constituents-are-campaign-envelope-prompt-provider-approval-reservation-and-preclaim-snapshot-hashes-only",
            "execute-consumption-and-provider-attempt-claim-hashes-are-not-authorization-constituent-hashes",
            "the-reconstructed-credential-literals-are-exactly-complete-suite-provider-credential-pipe-v1-and-OPENAI_API_KEY",
            "all-descriptor-authorization-reservation-marker-claim-root-candidate-client-template-constructor-and-target-identity-bindings-are-conjunctive",
            "any-mismatch-rejects-before-secret-pipe-creation-with-lookup-transfer-completion-and-root-accept-counts-all-zero",
            "validation-writes-no-durable-authorization-file-and-creates-no-hidden-target-to-root-byte-channel",
            "successful-validation-returns-only-one-validated-ExecuteClaimCapability-and-no-repository-object-or-credential-bearing-value",
            "only-exact-conjunctive-agreement-permits-post-capability-dynamic-credential-pair-construction",
            "readiness-peer-admission-credential-transfer-counters-lifecycle-response-and-persistence-semantics-are-out-of-scope",
            "this-registry-grants-no-parsing-hashing-path-selection-reopen-authorization-reconstruction-validation-pipe-creation-readiness-credential-counter-process-persistence-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                payload_schema_table,
                request_admission_table,
                validator_interface_table,
                source_binding_table,
                validation_gate_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def payload_schema_table(self):
        return self[1]

    @property
    def request_admission_table(self):
        return self[2]

    @property
    def validator_interface_table(self):
        return self[3]

    @property
    def source_binding_table(self):
        return self[4]

    @property
    def validation_gate_table(self):
        return self[5]

    @property
    def invariants(self):
        return self[6]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftExecuteClaimCapabilityFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "payload_schema_row_count="
            f"{len(self.payload_schema_table[1])!r}, "
            "request_admission_row_count="
            f"{len(self.request_admission_table[1])!r}, "
            "validator_interface_row_count="
            f"{len(self.validator_interface_table[1])!r}, "
            "source_binding_row_count="
            f"{len(self.source_binding_table[1])!r}, "
            "validation_gate_row_count="
            f"{len(self.validation_gate_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftExecuteClaimReadyFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftExecuteClaimReadyFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "protocol_scope",
                "record_type",
                "frame_kind",
                "fixed_role",
                "producer",
                "consumer",
                "activation_boundary",
                "excluded_semantic_scopes",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "execute-claim-ready-secret-free-host-facing-readiness-payload",
                    "ExecuteClaimReady",
                    "claim-ready",
                    "ack-status",
                    "trusted-root-broker",
                    "trusted-host",
                    "after-validated-ExecuteClaimCapability-and-both-dynamic-servers-created-security-requeried-associated-and-pending-connects",
                    (
                        "execute-credential-peer-accepted-payload",
                        "host-client-open-and-bidirectional-peer-authentication",
                        "credential-framing-transfer-and-counters",
                        "credential-and-pipe-lifecycle",
                        "broker-response-and-persistence",
                    ),
                ),
            ),
        )
        payload_schema_table = (
            (
                "record_type",
                "schema_version",
                "serialized_field_order",
                "wrapper_only_fields",
                "raw_root_identity_field_order",
                "canonical_payload_contract",
                "forbidden_payload_categories",
                "allowed_literal_policy",
            ),
            (
                (
                    "ExecuteClaimReady",
                    "complete-suite-execute-claim-ready-v1",
                    (
                        "version",
                        "root_descriptor_nonce",
                        "root_descriptor_sha256",
                        "target_descriptor_nonce",
                        "target_descriptor_sha256",
                        "constructor_implementation_set_sha256",
                        "constructor_attribute_set_sha256",
                        "job_topology_sha256",
                        "approved_campaign_sha256",
                        "approval_envelope_sha256",
                        "approval_prompt_sha256",
                        "provider_approval_sha256",
                        "provider_execution_authorization_sha256",
                        "reservation_sha256",
                        "preclaim_snapshot_sha256",
                        "execute_consumption_sha256",
                        "provider_attempt_claim_sha256",
                        "raw_root_identity",
                        "frozen_client_identity_sha256",
                        "client_launch_template_sha256",
                        "credential_transport_version",
                        "credential_environment_name",
                        "pipe",
                        "host_status_pipe",
                        "host_pid",
                        "host_creation_time",
                        "root_pid",
                        "root_creation_time",
                        "target_pid",
                        "target_creation_time",
                    ),
                    ("canonical_sha256",),
                    (
                        "device",
                        "inode",
                        "file_type",
                        "reparse_tag",
                        "link_count",
                    ),
                    "inherit-constructor-control-frame-canonical-JSON-strict-UTF-8-payload-and-SHA-256-contract",
                    (
                        "credential-value",
                        "credential-length-or-credential-derived-hash",
                        "environment-mapping",
                        "arbitrary-filesystem-path",
                        "caller-supplied-pipe-name",
                        "free-form-or-private-error-text",
                        "pipe-or-process-handle",
                        "completion-or-lifecycle-object",
                        "unknown-or-extra-field",
                    ),
                    "OPENAI_API_KEY-name-and-two-validated-bound-pipe-name-values-are-allowed-but-no-credential-material-or-arbitrary-path",
                ),
            ),
        )
        capability_projection_table = (
            (
                "source_record_type",
                "source_version",
                "readiness_version",
                "exact_repeated_binding_fields",
                "relocated_fields",
                "source_version_policy",
                "capability_hash_field_policy",
                "projection_requirement",
            ),
            (
                (
                    "ExecuteClaimCapability",
                    "complete-suite-execute-claim-capability-v1",
                    "complete-suite-execute-claim-ready-v1",
                    (
                        "root_descriptor_nonce",
                        "root_descriptor_sha256",
                        "target_descriptor_nonce",
                        "target_descriptor_sha256",
                        "constructor_implementation_set_sha256",
                        "constructor_attribute_set_sha256",
                        "job_topology_sha256",
                        "approved_campaign_sha256",
                        "approval_envelope_sha256",
                        "approval_prompt_sha256",
                        "provider_approval_sha256",
                        "provider_execution_authorization_sha256",
                        "reservation_sha256",
                        "preclaim_snapshot_sha256",
                        "execute_consumption_sha256",
                        "provider_attempt_claim_sha256",
                        "raw_root_identity",
                        "frozen_client_identity_sha256",
                        "client_launch_template_sha256",
                        "credential_transport_version",
                        "credential_environment_name",
                        "target_pid",
                        "target_creation_time",
                    ),
                    ("target_pid", "target_creation_time"),
                    "replace-source-version-with-readiness-version",
                    "execute_claim_capability_sha256-is-absent-and-first-belongs-to-ExecuteCredentialPeerAccepted",
                    "every-repeated-value-matches-the-one-validated-capability-exactly",
                ),
            ),
        )
        pipe_name_embedding_table = (
            (
                "readiness_field",
                "nested_record_type",
                "nested_record_version",
                "transport_version_value",
                "dynamic_role",
                "exact_name_prefix",
                "name_grammar_sha256",
                "payload_cap_bytes",
                "nested_serialized_field_order",
                "nested_wrapper_only_fields",
                "nested_field_binding_sources",
                "root_direction",
                "host_direction",
                "root_iocp_key",
                "host_iocp_key",
                "same_derived_suffix_binding",
                "caller_supplied",
                "later_status_or_lifecycle_hash_dependency",
                "handle_inheritable",
                "alias_policy",
            ),
            (
                (
                    "pipe",
                    "ExecuteCredentialPipeName",
                    "complete-suite-execute-credential-pipe-name-v1",
                    "complete-suite-provider-credential-pipe-v1",
                    "credential-data",
                    "\\\\.\\pipe\\kokoroarc-c6-execute-",
                    "29078e6b8f6b81c33cbd530d75d50af49d57efeb7cbf178772b6991ceb90dba7",
                    65_536,
                    (
                        "version",
                        "transport_version",
                        "value",
                        "value_sha256",
                        "root_descriptor_nonce",
                        "target_descriptor_nonce",
                        "provider_attempt_claim_sha256",
                        "payload_cap_bytes",
                        "grammar_sha256",
                    ),
                    ("canonical_sha256",),
                    (
                        ("version", "literal-complete-suite-execute-credential-pipe-name-v1"),
                        ("transport_version", "outer-credential_transport_version-exact"),
                        ("value", "exact-derived-credential-data-name-from-same-P"),
                        ("value_sha256", "SHA-256-of-ASCII-exact-value"),
                        ("root_descriptor_nonce", "outer-root_descriptor_nonce-exact"),
                        ("target_descriptor_nonce", "outer-target_descriptor_nonce-exact"),
                        ("provider_attempt_claim_sha256", "outer-provider_attempt_claim_sha256-exact"),
                        ("payload_cap_bytes", "literal-65536"),
                        ("grammar_sha256", "literal-29078e6b8f6b81c33cbd530d75d50af49d57efeb7cbf178772b6991ceb90dba7"),
                        ("canonical_sha256", "wrapper-only-SHA-256-over-exact-nested-canonical-bytes"),
                    ),
                    "reads",
                    "writes",
                    "credential-data",
                    "credential-data-write",
                    "same-P-from-root-nonce-target-nonce-and-provider-attempt-claim",
                    False,
                    "none",
                    False,
                    "distinct-from-other-dynamic-and-every-static-role-domain",
                ),
                (
                    "host_status_pipe",
                    "ExecuteCredentialHostStatusPipeName",
                    "complete-suite-execute-credential-host-status-pipe-name-v1",
                    "complete-suite-provider-credential-pipe-v1",
                    "credential-host-status",
                    "\\\\.\\pipe\\kokoroarc-c6-execute-status-",
                    "9c3c0b32ef2fc6d043800293ae1cb964fc0a212a9107472e9a8326c855be7837",
                    65_536,
                    (
                        "version",
                        "transport_version",
                        "value",
                        "value_sha256",
                        "root_descriptor_nonce",
                        "target_descriptor_nonce",
                        "provider_attempt_claim_sha256",
                        "payload_cap_bytes",
                        "grammar_sha256",
                    ),
                    ("canonical_sha256",),
                    (
                        ("version", "literal-complete-suite-execute-credential-host-status-pipe-name-v1"),
                        ("transport_version", "outer-credential_transport_version-exact"),
                        ("value", "exact-derived-credential-host-status-name-from-same-P"),
                        ("value_sha256", "SHA-256-of-ASCII-exact-value"),
                        ("root_descriptor_nonce", "outer-root_descriptor_nonce-exact"),
                        ("target_descriptor_nonce", "outer-target_descriptor_nonce-exact"),
                        ("provider_attempt_claim_sha256", "outer-provider_attempt_claim_sha256-exact"),
                        ("payload_cap_bytes", "literal-65536"),
                        ("grammar_sha256", "literal-9c3c0b32ef2fc6d043800293ae1cb964fc0a212a9107472e9a8326c855be7837"),
                        ("canonical_sha256", "wrapper-only-SHA-256-over-exact-nested-canonical-bytes"),
                    ),
                    "reads",
                    "writes",
                    "credential-host-status",
                    "credential-host-status-write",
                    "same-P-from-root-nonce-target-nonce-and-provider-attempt-claim",
                    False,
                    "none",
                    False,
                    "distinct-from-other-dynamic-and-every-static-role-domain",
                ),
            ),
        )
        process_identity_binding_table = (
            (
                "identity_domain",
                "pid_field",
                "creation_time_field",
                "authoritative_source",
                "required_match",
                "pid_only_authority",
            ),
            (
                (
                    "host",
                    "host_pid",
                    "host_creation_time",
                    "authenticated-trusted-host-identity",
                    "exact-PID-and-creation-time-pair",
                    False,
                ),
                (
                    "root",
                    "root_pid",
                    "root_creation_time",
                    "authenticated-root-broker-identity",
                    "exact-PID-and-creation-time-pair",
                    False,
                ),
                (
                    "target",
                    "target_pid",
                    "target_creation_time",
                    "validated-ExecuteClaimCapability-and-authenticated-target-descriptor",
                    "exact-PID-and-creation-time-pair",
                    False,
                ),
            ),
        )
        admission_gate_table = (
            (
                "step",
                "gate",
                "actor",
                "required_predecessors",
                "required_action_or_match",
                "successor_boundary",
                "failure_disposition",
                "failure_counter_state",
            ),
            (
                (
                    1,
                    "validated-capability-admission",
                    "execute-root-broker",
                    ("one-root-independently-validated-ExecuteClaimCapability",),
                    "permit-exactly-one-dynamic-credential-data-and-host-status-pair-construction",
                    "both-exact-servers-created-and-security-requeried",
                    "fail-closed-before-readiness-with-no-host-open-or-credential-lookup",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    2,
                    "paired-server-construction-and-security-requery",
                    "execute-root-broker",
                    ("exactly-one-dynamic-pair-construction-permitted",),
                    "create-both-first-instance-servers-and-requery-both-owner-and-DACL-descriptors",
                    "root-private-IOCP-association",
                    "consume-both-one-shot-instances-and-fail-closed-before-readiness",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    3,
                    "distinct-root-IOCP-association",
                    "execute-root-broker",
                    (
                        "both-exact-servers-created",
                        "both-owner-and-DACL-requeries-succeeded",
                    ),
                    "associate-both-servers-with-root-private-IOCP-under-distinct-credential-data-and-credential-host-status-keys",
                    "one-overlapped-connect-issuance-per-server",
                    "consume-both-one-shot-instances-and-fail-closed-before-readiness",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    4,
                    "one-connect-issuance-per-server",
                    "execute-root-broker",
                    ("both-root-private-IOCP-associations-succeeded",),
                    "issue-exactly-one-overlapped-ConnectNamedPipe-per-server",
                    "initial-connect-result-admission",
                    "consume-both-one-shot-instances-and-fail-closed-before-readiness",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    5,
                    "pending-connect-result-admission",
                    "execute-root-broker",
                    ("exactly-one-overlapped-ConnectNamedPipe-issued-per-server",),
                    "both-initial-results-are-exactly-FALSE/ERROR_IO_PENDING",
                    "authenticated-readiness-construction-and-emission",
                    "synchronous-success-ERROR_PIPE_CONNECTED-or-any-other-result-is-an-unauthorized-pre-readiness-race-and-consumes-both-one-shot-instances",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    6,
                    "claim-ready-construction-and-emission",
                    "execute-root-broker",
                    (
                        "one-validated-ExecuteClaimCapability",
                        "both-exact-servers-created",
                        "both-owner-and-DACL-requeries-succeeded",
                        "both-servers-associated-under-distinct-root-IOCP-keys",
                        "both-initial-connect-results-are-FALSE/ERROR_IO_PENDING",
                    ),
                    "construct-and-emit-exactly-one-authenticated-canonical-ExecuteClaimReady-on-host-facing-ack-status",
                    "trusted-host-readiness-validation",
                    "consume-both-one-shot-instances-and-fail-closed-with-no-host-open-or-credential-lookup",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    7,
                    "trusted-host-readiness-validation",
                    "trusted-host",
                    ("exactly-one-authenticated-claim-ready-frame-received",),
                    "authenticate-canonical-frame-then-independently-reopen-and-revalidate-authorization-reservation-marker-claim-raw-root-identity-and-membership-root-and-target-descriptor-nonce-hash-PID-creation-time-frozen-client-identity-client-launch-template-and-both-name-records-and-match-all-three-authenticated-PID-creation-time-pairs",
                    "bound-pair-open-eligibility",
                    "consume-both-one-shot-instances-and-fail-closed-with-no-name-lookup-open-or-credential-lookup",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    8,
                    "bound-pair-open-eligibility",
                    "trusted-host",
                    ("successful-exact-trusted-host-readiness-validation",),
                    "permit-exactly-once-CreateFileW-open-of-each-of-the-two-validated-bound-names-only",
                    "post-readiness-host-open-and-bidirectional-peer-authentication",
                    "no-open-retry-reconnect-second-open-instance-reuse-or-credential-lookup",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-the-secret-free-ExecuteClaimReady-payload-and-its-pre-open-admission-boundary",
            "the-only-producer-is-the-trusted-root-broker-and-the-only-consumer-is-the-trusted-host",
            "the-frame-kind-is-exactly-claim-ready-on-the-existing-host-facing-ack-status-role",
            "readiness-is-forbidden-before-one-capability-validates-and-both-exact-servers-are-security-requeried-associated-and-pending-connects",
            "the-thirty-serialized-fields-are-ordered-exactly-and-canonical_sha256-is-wrapper-only",
            "raw_root_identity-is-the-five-field-filesystem-identity-object-and-never-a-path",
            "all-twenty-three-capability-bindings-repeat-exactly-with-only-version-replaced-and-target-identity-relocated",
            "execute_claim_capability_sha256-is-absent-and-first-belongs-to-ExecuteCredentialPeerAccepted",
            "readiness-contains-no-credential-value-length-derived-hash-environment-mapping-arbitrary-path-private-error-handle-lifecycle-object-or-extra-field",
            "OPENAI_API_KEY-and-the-two-validated-bound-pipe-name-values-are-the-only-allowed-name-like-literals",
            "both-nested-name-records-have-the-exact-nine-field-order-and-wrapper-only-canonical_sha256",
            "both-names-have-their-fixed-distinct-prefix-version-grammar-digest-and-65536-byte-payload-cap",
            "both-names-use-the-same-derived-P-and-neither-is-caller-supplied-or-dependent-on-a-later-status-or-lifecycle-hash",
            "credential-data-and-credential-host-status-remain-distinct-root-read-host-write-noninherited-nonaliasing-endpoint-domains",
            "root-and-host-IOCP-keys-are-distinct-and-typed-per-dynamic-role-and-never-alias-a-static-role",
            "exactly-one-overlapped-ConnectNamedPipe-is-issued-per-server-and-only-FALSE/ERROR_IO_PENDING-is-admissible-before-readiness",
            "the-root-constructs-and-emits-exactly-one-authenticated-canonical-readiness-frame-after-all-five-conjunctive-predecessors",
            "connect-completion-and-root-side-host-peer-authentication-occur-after-host-open-and-are-not-readiness-predecessors",
            "the-host-authenticates-then-independently-reopens-and-revalidates-every-named-authorization-reservation-marker-claim-raw-root-descriptor-frozen-client-identity-client-launch-template-and-name-fact-and-all-three-process-identities-before-open",
            "host-root-and-target-identities-each-bind-an-exact-PID-and-creation-time-pair",
            "a-PID-without-its-matching-creation-time-never-grants-identity-authority",
            "successful-readiness-validation-permits-only-one-open-of-each-bound-name-and-no-wait-retry-reconnect-second-open-or-instance-reuse",
            "any-early-duplicate-replayed-reordered-malformed-mismatched-or-unknown-readiness-state-consumes-the-pair-with-lookup-transfer-attempt-transfer-completion-and-root-accept-counts-all-zero",
            "both-dynamic-roles-inherit-the-shared-ledger-dispatch-deadline-cap-cancellation-retirement-close-grace-and-quarantine-rules",
            "peer-accepted-payload-credential-framing-transfer-counters-lifecycle-broker-response-and-persistence-semantics-are-out-of-scope",
            "admission-predecessor-tuples-are-conjunctive-partial-order-gates-and-row-order-grants-no-extra-runtime-order",
            "this-registry-grants-no-hashing-name-derivation-pipe-creation-association-connect-frame-emission-validation-open-process-query-I/O-close-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                payload_schema_table,
                capability_projection_table,
                pipe_name_embedding_table,
                process_identity_binding_table,
                admission_gate_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def payload_schema_table(self):
        return self[1]

    @property
    def capability_projection_table(self):
        return self[2]

    @property
    def pipe_name_embedding_table(self):
        return self[3]

    @property
    def process_identity_binding_table(self):
        return self[4]

    @property
    def admission_gate_table(self):
        return self[5]

    @property
    def invariants(self):
        return self[6]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftExecuteClaimReadyFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "payload_schema_row_count="
            f"{len(self.payload_schema_table[1])!r}, "
            "capability_projection_row_count="
            f"{len(self.capability_projection_table[1])!r}, "
            "pipe_name_embedding_row_count="
            f"{len(self.pipe_name_embedding_table[1])!r}, "
            "process_identity_binding_row_count="
            f"{len(self.process_identity_binding_table[1])!r}, "
            "admission_gate_row_count="
            f"{len(self.admission_gate_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftExecuteCredentialPeerAcceptedFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftExecuteCredentialPeerAcceptedFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "protocol_scope",
                "record_type",
                "frame_kind",
                "fixed_role",
                "producer",
                "consumer",
                "activation_boundary",
                "excluded_semantic_scopes",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "execute-credential-peer-accepted-secret-free-host-facing-peer-authentication-payload",
                    "ExecuteCredentialPeerAccepted",
                    "credential-peer-accepted",
                    "ack-status",
                    "trusted-root-broker",
                    "trusted-host",
                    "after-one-validated-ExecuteClaimReady-exactly-once-paired-host-open-and-bidirectional-two-handle-PID-creation-time-authentication",
                    (
                        "credential-payload-parsing-and-transfer",
                        "credential-counters-and-lifecycle",
                        "broker-request-response-sequencing",
                        "persistence-and-private-errors",
                        "runtime-I/O-execution",
                    ),
                ),
            ),
        )
        payload_schema_table = (
            (
                "record_type",
                "schema_version",
                "serialized_field_order",
                "wrapper_only_fields",
                "canonical_inner_payload_contract",
                "outer_ack_status_frame_contract",
                "payload_cap_bytes",
                "forbidden_payload_categories",
                "allowed_value_policy",
            ),
            (
                (
                    "ExecuteCredentialPeerAccepted",
                    "complete-suite-execute-credential-peer-accepted-v1",
                    (
                        "version",
                        "root_descriptor_nonce",
                        "root_descriptor_sha256",
                        "target_descriptor_nonce",
                        "target_descriptor_sha256",
                        "execute_claim_capability_sha256",
                        "provider_attempt_claim_sha256",
                        "pipe_name_sha256",
                        "host_status_pipe_name_sha256",
                        "host_pid",
                        "host_creation_time",
                        "root_pid",
                        "root_creation_time",
                    ),
                    ("canonical_sha256",),
                    "canonical-compact-strict-ASCII-JSON-plus-exactly-one-LF-with-SHA-256-over-exact-inner-bytes",
                    (
                        ("length_prefix_bytes", 4),
                        ("length_prefix_type", "unsigned-payload-byte-length"),
                        ("length_prefix_endianness", "little-endian"),
                        ("payload_encoding", "strict-UTF-8"),
                        ("payload_canonical_form", "canonical-JSON"),
                        ("payload_cap_bytes", 65_536),
                        ("maximum_frame_wire_bytes", 65_540),
                    ),
                    65_536,
                    (
                        "ExecuteClaimReady-canonical_sha256",
                        "target-PID-or-creation-time",
                        "pipe-name-value",
                        "credential-value",
                        "credential-length-or-credential-derived-hash",
                        "environment-mapping",
                        "arbitrary-filesystem-path",
                        "free-form-or-private-error-text",
                        "pipe-or-process-handle",
                        "completion-lifecycle-or-status-object",
                        "unknown-or-extra-field",
                    ),
                    "only-exact-secret-free-identity-and-binding-values-named-by-the-thirteen-field-schema",
                ),
            ),
        )
        source_binding_table = (
            (
                "source_family",
                "bound_payload_fields",
                "authoritative_sources",
                "required_agreement",
                "caller_supplied",
                "fresh_host_revalidation_required",
            ),
            (
                (
                    "schema-version",
                    ("version",),
                    ("protocol-literal",),
                    "exact-complete-suite-execute-credential-peer-accepted-v1",
                    False,
                    False,
                ),
                (
                    "root-descriptor",
                    ("root_descriptor_nonce", "root_descriptor_sha256"),
                    ("validated-ExecuteClaimCapability", "validated-ExecuteClaimReady"),
                    "capability-and-readiness-exactly-agree-with-the-authenticated-root-descriptor",
                    False,
                    True,
                ),
                (
                    "target-descriptor",
                    ("target_descriptor_nonce", "target_descriptor_sha256"),
                    ("validated-ExecuteClaimCapability", "validated-ExecuteClaimReady"),
                    "capability-and-readiness-exactly-agree-with-the-authenticated-target-descriptor",
                    False,
                    True,
                ),
                (
                    "capability-wrapper-hash",
                    ("execute_claim_capability_sha256",),
                    (
                        "exact-validated-ExecuteClaimCapability-wrapper-canonical_sha256",
                        "ExecuteClaimReady-exact-repeated-capability-bindings",
                    ),
                    "exact-validated-capability-wrapper-hash-and-independent-readiness-repeated-field-agreement",
                    False,
                    True,
                ),
                (
                    "provider-attempt-claim",
                    ("provider_attempt_claim_sha256",),
                    (
                        "validated-ExecuteClaimCapability",
                        "validated-ExecuteClaimReady",
                        "freshly-reopened-provider-attempt-claim",
                    ),
                    "one-exact-provider-attempt-claim-hash-agrees-across-capability-readiness-and-fresh-reopen",
                    False,
                    True,
                ),
                (
                    "readiness-nested-name-value-hashes",
                    ("pipe_name_sha256", "host_status_pipe_name_sha256"),
                    (
                        "ExecuteClaimReady.pipe.value_sha256",
                        "ExecuteClaimReady.host_status_pipe.value_sha256",
                    ),
                    "bind-exact-nested-value_sha256-fields-never-nested-canonical_sha256",
                    False,
                    True,
                ),
                (
                    "authenticated-host-peer-identity",
                    ("host_pid", "host_creation_time"),
                    (
                        "both-root-side-client-peer-PID-observations",
                        "authenticated-trusted-host-process-creation-time",
                    ),
                    "same-host-PID-and-creation-time-pair-on-both-connected-clients",
                    False,
                    True,
                ),
                (
                    "authenticated-root-peer-identity",
                    ("root_pid", "root_creation_time"),
                    (
                        "both-host-side-server-peer-PID-observations",
                        "validated-ExecuteClaimReady-root-process-identity",
                    ),
                    "same-root-PID-and-creation-time-pair-on-both-connected-servers-and-readiness",
                    False,
                    True,
                ),
            ),
        )
        pipe_name_hash_binding_table = (
            (
                "payload_field",
                "readiness_field",
                "nested_record_type",
                "nested_value_hash_field",
                "forbidden_nested_wrapper_hash_field",
                "dynamic_role",
                "exact_source_expression",
                "hash_input_contract",
                "caller_supplied",
                "pipe_name_value_serialized",
            ),
            (
                (
                    "pipe_name_sha256",
                    "pipe",
                    "ExecuteCredentialPipeName",
                    "value_sha256",
                    "canonical_sha256",
                    "credential-data",
                    "ExecuteClaimReady.pipe.value_sha256",
                    "SHA-256-of-ASCII-exact-bound-pipe-name-value",
                    False,
                    False,
                ),
                (
                    "host_status_pipe_name_sha256",
                    "host_status_pipe",
                    "ExecuteCredentialHostStatusPipeName",
                    "value_sha256",
                    "canonical_sha256",
                    "credential-host-status",
                    "ExecuteClaimReady.host_status_pipe.value_sha256",
                    "SHA-256-of-ASCII-exact-bound-pipe-name-value",
                    False,
                    False,
                ),
            ),
        )
        peer_authentication_table = (
            (
                "verifier",
                "peer",
                "queried_endpoint_side",
                "dynamic_roles",
                "completion_predecessor",
                "peer_pid_query_requirement",
                "peer_process_query_requirement",
                "process_open_access",
                "peer_creation_time_query_requirement",
                "authoritative_identity_fields",
                "same_pair_on_both",
                "pid_only_authority",
            ),
            (
                (
                    "trusted-host",
                    "execute-root-broker",
                    "server-peer-through-both-host-client-handles",
                    ("credential-data", "credential-host-status"),
                    "exactly-once-open-and-host-private-IOCP-security-association-of-both-client-handles",
                    "query-each-server-peer-PID",
                    "query-each-observed-server-peer-process",
                    "PROCESS_QUERY_LIMITED_INFORMATION",
                    "query-each-observed-server-peer-process-creation-time",
                    ("root_pid", "root_creation_time"),
                    True,
                    False,
                ),
                (
                    "execute-root-broker",
                    "trusted-host",
                    "client-peer-through-both-root-server-handles",
                    ("credential-data", "credential-host-status"),
                    "both-successful-ConnectNamedPipe-completions-consumed-under-distinct-root-IOCP-keys",
                    "query-each-client-peer-PID",
                    "query-each-observed-client-peer-process",
                    "PROCESS_QUERY_LIMITED_INFORMATION",
                    "query-each-observed-client-peer-process-creation-time",
                    ("host_pid", "host_creation_time"),
                    True,
                    False,
                ),
            ),
        )
        admission_gate_table = (
            (
                "step",
                "gate",
                "actor",
                "required_predecessors",
                "required_action_or_match",
                "successor_boundary",
                "failure_disposition",
                "failure_counter_state",
            ),
            (
                (
                    1,
                    "validated-readiness-open-eligibility",
                    "trusted-host",
                    (
                        "one-authenticated-canonical-ExecuteClaimReady-validated",
                        "fresh-pre-open-host-revalidation-succeeded",
                        "bound-pair-open-eligibility-granted",
                    ),
                    "admit-exactly-once-open-of-both-readiness-bound-name-values-with-no-credential-lookup",
                    "paired-host-open-IOCP-and-security-association",
                    "consume-both-one-shot-instances-with-no-retry-reconnect-second-open-or-instance-reuse-and-fail-closed",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    2,
                    "paired-host-open-IOCP-and-security-association",
                    "trusted-host",
                    ("validated-readiness-open-eligibility-succeeded",),
                    "open-each-bound-name-exactly-once-and-associate-both-noninherited-client-handles-with-host-private-IOCP-under-distinct-typed-keys-and-preserve-security-identification",
                    "host-authenticates-root-on-both",
                    "consume-both-one-shot-instances-with-no-retry-reconnect-second-open-or-instance-reuse-and-fail-closed",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    3,
                    "host-authenticates-root-on-both",
                    "trusted-host",
                    ("both-exactly-once-host-opens-and-private-IOCP-associations-succeeded",),
                    "query-both-server-peer-PIDs-and-each-observed-process-with-only-PROCESS_QUERY_LIMITED_INFORMATION-and-require-one-readiness-bound-root-PID-creation-time-pair-on-both",
                    "root-consumes-both-connect-completions",
                    "consume-both-one-shot-instances-with-no-retry-reconnect-second-open-or-instance-reuse-and-fail-closed",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    4,
                    "root-consumes-both-connect-completions",
                    "execute-root-broker",
                    (
                        "host-authenticated-the-root-on-both-server-peers",
                        "one-pending-ConnectNamedPipe-operation-per-server",
                    ),
                    "consume-exactly-one-successful-connect-completion-per-server-under-distinct-root-IOCP-keys",
                    "root-authenticates-host-on-both",
                    "consume-both-one-shot-instances-with-no-retry-reconnect-second-open-or-instance-reuse-and-fail-closed",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    5,
                    "root-authenticates-host-on-both",
                    "execute-root-broker",
                    ("both-successful-connect-completions-consumed",),
                    "query-both-client-peer-PIDs-and-each-observed-process-with-only-PROCESS_QUERY_LIMITED_INFORMATION-and-require-one-descriptor-bound-host-PID-creation-time-pair-on-both",
                    "root-emits-one-canonical-peer-accepted-frame",
                    "consume-both-one-shot-instances-with-no-retry-reconnect-second-open-or-instance-reuse-and-fail-closed",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    6,
                    "root-emits-one-canonical-peer-accepted-frame",
                    "execute-root-broker",
                    (
                        "host-authenticated-root-on-both",
                        "both-root-connect-completions-consumed",
                        "root-authenticated-host-on-both",
                    ),
                    "construct-and-emit-exactly-one-canonical-ExecuteCredentialPeerAccepted-on-host-facing-ack-status-with-exact-thirteen-field-inner-payload-and-four-byte-little-endian-length-prefix",
                    "host-validates-one-exact-peer-accepted-frame",
                    "consume-both-one-shot-instances-with-no-retry-reconnect-second-open-or-instance-reuse-and-fail-closed",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    7,
                    "host-validates-one-exact-peer-accepted-frame",
                    "trusted-host",
                    ("exactly-one-credential-peer-accepted-frame-received-after-authenticated-peer-connection",),
                    "validate-exact-outer-prefix-inner-canonical-bytes-schema-order-wrapper-hash-source-bindings-peer-identities-and-no-duplicate-unknown-or-trailing-data",
                    "fresh-full-host-revalidation",
                    "consume-both-one-shot-instances-with-no-retry-reconnect-second-open-or-instance-reuse-and-fail-closed",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
                (
                    8,
                    "fresh-full-host-revalidation",
                    "trusted-host",
                    ("one-exact-canonical-ExecuteCredentialPeerAccepted-validated",),
                    "independently-reopen-and-revalidate-authorization-reservation-marker-claim-raw-root-identity-and-membership-root-and-target-descriptor-nonce-hash-PID-creation-time-frozen-client-identity-client-launch-template-validated-capability-exact-readiness-both-name-records-and-both-authenticated-peer-PID-creation-time-pairs-and-requery-both-open-client-handle-owner-and-DACL-security-descriptors",
                    "single-credential-lookup-eligibility",
                    "consume-both-one-shot-instances-with-no-retry-reconnect-second-open-or-instance-reuse-and-fail-closed",
                    (
                        ("credential_lookup_count", 0),
                        ("credential_transfer_attempt_count", 0),
                        ("credential_transfer_completion_count", 0),
                        ("credential_frame_accept_count", 0),
                    ),
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-the-secret-free-ExecuteCredentialPeerAccepted-payload-and-post-readiness-peer-authentication-boundary",
            "the-only-producer-is-the-trusted-root-broker-and-the-only-consumer-is-the-trusted-host",
            "the-frame-kind-is-exactly-credential-peer-accepted-on-the-existing-host-facing-ack-status-role",
            "peer-accepted-is-forbidden-before-one-valid-readiness-exactly-once-paired-host-open-and-bidirectional-two-handle-authentication",
            "the-thirteen-serialized-fields-are-ordered-exactly-through-root_creation_time",
            "canonical_sha256-is-wrapper-only-and-is-never-an-inner-serialized-field",
            "the-inner-payload-is-canonical-compact-strict-ASCII-JSON-plus-exactly-one-LF-and-its-hash-covers-the-exact-inner-bytes",
            "the-outer-frame-is-exactly-a-four-byte-unsigned-little-endian-payload-length-followed-by-the-exact-inner-bytes",
            "the-inner-payload-cap-is-65536-bytes-and-the-maximum-wire-size-is-65540-bytes",
            "execute_claim_capability_sha256-equals-the-exact-validated-capability-wrapper-hash-with-independent-readiness-projection-agreement-and-is-never-caller-supplied",
            "root-and-target-descriptor-and-provider-attempt-claim-bindings-agree-exactly-across-capability-readiness-and-fresh-reopen",
            "both-pipe-name-hash-fields-bind-the-corresponding-readiness-nested-value_sha256-and-never-nested-canonical_sha256",
            "the-payload-contains-no-ExecuteClaimReady-hash-target-PID-or-time-or-pipe-name-value",
            "the-payload-contains-no-credential-material-derived-secret-hash-path-mapping-private-error-handle-lifecycle-status-object-or-extra-field",
            "the-two-peer-authentication-rows-are-host-checks-root-on-both-servers-and-root-checks-host-on-both-clients",
            "the-host-queries-both-servers-and-requires-one-readiness-bound-root-PID-and-creation-time-pair-on-both",
            "the-root-consumes-both-connect-completions-before-querying-both-clients-and-requires-one-descriptor-bound-host-PID-and-creation-time-pair-on-both",
            "both-sides-open-peer-processes-only-with-PROCESS_QUERY_LIMITED_INFORMATION-and-PID-alone-never-grants-authority",
            "the-host-opens-each-bound-name-exactly-once-and-associates-both-noninherited-security-identified-clients-under-distinct-private-IOCP-keys",
            "the-root-consumes-exactly-two-connect-completions-under-distinct-typed-root-IOCP-keys",
            "the-root-emits-exactly-one-canonical-peer-accepted-frame-only-after-both-direction-authentication-gates-succeed",
            "the-host-validates-exactly-one-peer-accepted-frame-with-no-duplicate-replay-reorder-unknown-or-trailing-data",
            "the-host-freshly-reopens-and-revalidates-every-named-authorization-reservation-marker-claim-root-descriptor-target-descriptor-client-template-readiness-name-and-peer-identity-fact-and-requeries-both-open-client-handle-owner-and-DACL-security-descriptors-before-lookup",
            "credential-lookup-becomes-eligible-only-after-all-eight-conjunctive-gates-succeed",
            "every-gate-failure-consumes-both-one-shot-instances-with-no-retry-or-reuse-and-leaves-lookup-attempt-completion-and-accept-counts-zero",
            "the-host-facing-execute-root-grammar-is-exactly-ack-claim-ready-credential-peer-accepted-terminal-EOF-after-one-authenticated-peer-connection",
            "credential-data-and-credential-host-status-remain-distinct-noninherited-nonaliasing-handle-key-buffer-operation-and-lifetime-domains",
            "both-dynamic-roles-inherit-the-shared-ledger-dispatch-deadline-cap-cancellation-retirement-close-grace-and-quarantine-facts",
            "admission-predecessor-tuples-are-conjunctive-partial-order-gates-and-row-order-grants-no-extra-runtime-order",
            "this-registry-grants-no-hashing-open-association-connect-query-authentication-frame-I/O-lookup-counter-lifecycle-broker-response-persistence-or-runtime-authority",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                payload_schema_table,
                source_binding_table,
                pipe_name_hash_binding_table,
                peer_authentication_table,
                admission_gate_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def payload_schema_table(self):
        return self[1]

    @property
    def source_binding_table(self):
        return self[2]

    @property
    def pipe_name_hash_binding_table(self):
        return self[3]

    @property
    def peer_authentication_table(self):
        return self[4]

    @property
    def admission_gate_table(self):
        return self[5]

    @property
    def invariants(self):
        return self[6]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftExecuteCredentialPeerAcceptedFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "payload_schema_row_count="
            f"{len(self.payload_schema_table[1])!r}, "
            "source_binding_row_count="
            f"{len(self.source_binding_table[1])!r}, "
            "pipe_name_hash_binding_row_count="
            f"{len(self.pipe_name_hash_binding_table[1])!r}, "
            "peer_authentication_row_count="
            f"{len(self.peer_authentication_table[1])!r}, "
            "admission_gate_row_count="
            f"{len(self.admission_gate_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftCredentialDataTransferFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftCredentialDataTransferFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (('implementation_id',
          'state_machine_id',
          'protocol_scope',
          'dynamic_role',
          'producer',
          'consumer',
          'activation_predecessors',
          'lookup_admission_boundary',
          'successor_boundary',
          'serialized_data_frame_policy',
          'excluded_semantic_scopes'),
         (('broker-native-core-v1',
           'complete-suite-native-constructor-state-machine-v1',
           'credential-data-transfer-framing-value-admission-counters-and-cleanup-handoff',
           'credential-data',
           'trusted-host',
           'execute-root-broker',
           ('canonical-ExecuteClaimReady-emitted-and-validated',
            'post-readiness-one-shot-cleanup-is-mandatory'),
           'single-credential-lookup-eligibility',
           'CredentialHostStatus-construction',
           'no-serialized-CredentialDataFrame-and-no-data-frame-hash',
           ('CredentialHostStatus-payload-schema-and-wire-serialization',
            'credential-and-pipe-lifecycle-record-serialization',
            'broker-request-response-sequencing',
            'durable-persistence',
            'private-error-projection',
            'runtime-I/O-authority')),))
        wire_classification_table = (('classification',
          'N_domain',
          'prefix_contract',
          'payload_contract',
          'writer_termination',
          'reader_strategy',
          'extra_read_contract',
          'admissible_extra_read_result',
          'payload_cap_bytes',
          'maximum_wire_bytes',
          'payload_allocation_policy',
          'provider_credential_policy',
          'public_disposition'),
         (('complete-unavailable',
           'N-equals-0',
           'exactly-four-byte-unsigned-little-endian-N',
           'exactly-zero-payload-bytes',
           'writer-close-then-immediate-EOF',
           'incremental-prefix-read',
           'exactly-one-bounded-one-byte-extra-read',
           'EOF-or-ERROR_BROKEN_PIPE-at-role-permitted-read-terminal',
           65536,
           65540,
           'no-payload-allocation',
           'forbidden',
           'CAMPAIGN_CREDENTIAL_UNAVAILABLE'),
          ('bounded-nonzero-candidate',
           '1-less-than-or-equal-to-N-less-than-or-equal-to-65536',
           'exactly-four-byte-unsigned-little-endian-N',
           'exactly-N-payload-bytes',
           'writer-close-then-immediate-EOF',
           'incremental-prefix-and-payload-read',
           'exactly-one-bounded-one-byte-extra-read',
           'EOF-or-ERROR_BROKEN_PIPE-at-role-permitted-read-terminal',
           65536,
           65540,
           'allocate-only-after-complete-prefix-decodes-within-cap',
           'permitted-only-after-root-visible-ASCII-exact-length-and-immediate-EOF-validation',
           'candidate-not-yet-accepted'),
          ('over-cap-prefix',
           'N-greater-than-65536',
           'exactly-four-byte-unsigned-little-endian-N',
           'payload-is-never-read',
           'fail-closed',
           'incremental-prefix-read-only',
           'not-issued',
           'none',
           65536,
           65540,
           'reject-before-payload-allocation',
           'forbidden',
           'CAMPAIGN_SECRET_ISOLATION_FAILED'),
          ('isolation-failure-framing',
           'incomplete-or-undecodable-prefix-partial-payload-early-EOF-trailing-byte-second-frame-second-connection-or-missing-EOF',
           'four-byte-prefix-must-complete-before-classification',
           'declared-payload-must-complete-exactly',
           'writer-close-and-exact-end-of-stream-required',
           'incremental-prefix-and-payload-read-with-no-recovery',
           'at-most-the-one-bounded-classification-read-with-no-retry',
           'anything-other-than-EOF-or-ERROR_BROKEN_PIPE-at-role-permitted-read-terminal-is-rejected',
           65536,
           65540,
           'never-allocate-before-bounded-prefix-admission',
           'forbidden',
           'CAMPAIGN_SECRET_ISOLATION_FAILED')))
        lookup_value_admission_table = (('value_classification',
          'registry_lifecycle_activation',
          'lookup_admission_boundary',
          'pre_admission_lookup_policy',
          'lookup_transition',
          'credential_name',
          'validation_subject',
          'validation_order',
          'character_domain',
          'encoded_length_domain',
          'forbidden_transformations',
          'value_retention_policy',
          'wire_action',
          'provider_credential_eligibility',
          'possible_terminal_counter_states',
          'cleanup_handoff'),
         (('pre-lookup-admission-failure',
           ('canonical-ExecuteClaimReady-emitted-and-validated',
            'post-readiness-one-shot-cleanup-is-mandatory'),
           'single-credential-lookup-eligibility',
           'lookup-forbidden-unless-the-exact-boundary-is-reached',
           'no-lookup-and-all-four-counters-remain-zero',
           'not-requested',
           'none',
           'none',
           ('fresh-full-host-revalidation-failure', 'earlier-post-readiness-gate-failure'),
           'not-observed',
           ('no-value-observation',
            'no-trim',
            'no-normalize',
            'no-hash',
            'no-log',
            'no-canonicalization',
            'no-durable-serialization',
            'no-exact-or-rounded-length-retention'),
           'no-value-is-retained',
           'no-credential-data-frame',
           'forbidden',
           ((0, 0, 0, 0),),
           'continue-mandated-cleanup-and-CredentialHostStatus-handoff'),
          ('accepted-visible-ASCII',
           ('canonical-ExecuteClaimReady-emitted-and-validated',
            'post-readiness-one-shot-cleanup-is-mandatory'),
           'single-credential-lookup-eligibility',
           'lookup-forbidden-before-the-exact-boundary',
           'atomically-increment-credential_lookup_count-exactly-once',
           'OPENAI_API_KEY',
           'original-UTF-16-value-character-by-character',
           'complete-character-validation-before-strict-encoding',
           'every-character-is-visible-ASCII-0x21-through-0x7e',
           'nonempty-and-at-most-65536-encoded-bytes',
           ('no-trim',
            'no-normalize',
            'no-hash',
            'no-log',
            'no-canonicalization',
            'no-durable-serialization',
            'no-exact-or-rounded-length-retention'),
           'root-scoped-transient-retention-only-after-root-acceptance-until-terminal-broker-shutdown',
           'write-and-dequeue-four-byte-nonzero-prefix-before-one-no-retry-payload-attempt',
           'ProviderCredential-construction-only-after-root-acceptance-with-no-client-materialization-authority',
           ((1, 0, 0, 0), (1, 1, 0, 0), (1, 1, 1, 0), (1, 1, 1, 1)),
           'status-handoff-and-root-concurrent-drain-remain-mandatory'),
          ('rejected-original-value',
           ('canonical-ExecuteClaimReady-emitted-and-validated',
            'post-readiness-one-shot-cleanup-is-mandatory'),
           'single-credential-lookup-eligibility',
           'lookup-forbidden-before-the-exact-boundary',
           'atomically-increment-credential_lookup_count-exactly-once',
           'OPENAI_API_KEY',
           'original-UTF-16-value-character-by-character',
           'complete-character-validation-before-any-encoding',
           ('NUL', 'space', 'control', 'non-ASCII', 'surrogate', 'empty', 'over-cap'),
           'empty-over-65536-or-strict-encoding-failure',
           ('no-trim',
            'no-normalize',
            'no-hash',
            'no-log',
            'no-canonicalization',
            'no-durable-serialization',
            'no-exact-or-rounded-length-retention'),
           'invalid-value-is-not-retained',
           'write-exactly-four-zero-bytes-then-close-without-payload',
           'forbidden',
           ((1, 0, 0, 0),),
           'status-handoff-and-cleanup-remain-mandatory')))
        transfer_partial_order_table = (('step',
          'actor',
          'event',
          'required_predecessors',
          'required_action_or_order',
          'counter_transition',
          'retry_policy',
          'maximum_counter_values'),
         ((1,
           'trusted-host',
           'lookup-admission',
           ('single-credential-lookup-eligibility',),
           'perform-one-atomic-named-credential-lookup-and-validate-the-original-value',
           '0000-to-1000',
           'no-second-lookup',
           (1, 1, 1, 1)),
          (2,
           'trusted-host',
           'nonzero-prefix-issue',
           ('accepted-visible-ASCII-value-encoded-within-cap',),
           'issue-the-exact-four-byte-nonzero-prefix-before-any-payload-byte',
           'no-counter-change',
           'no-prefix-retry',
           (1, 1, 1, 1)),
          (3,
           'trusted-host',
           'nonzero-prefix-retirement',
           ('exact-four-byte-prefix-issued',),
           'complete-and-dequeue-the-prefix-before-first-payload-write-admission',
           'no-counter-change',
           'no-prefix-retry',
           (1, 1, 1, 1)),
          (4,
           'trusted-host',
           'first-payload-write-admission',
           ('exact-four-byte-prefix-completion-dequeued',),
           'increment-attempt-immediately-before-the-first-and-only-payload-write-sequence',
           '1000-to-1100',
           'no-payload-retry',
           (1, 1, 1, 1)),
          (5,
           'trusted-host',
           'payload-write-retirement',
           ('attempt-counter-incremented-immediately-before-first-payload-write',),
           'retire-every-payload-completion-covering-exactly-N-transient-bytes',
           'no-counter-change-until-writer-close',
           'no-payload-retry',
           (1, 1, 1, 1)),
          (6,
           'trusted-host',
           'host-transfer-completion',
           ('prefix-completion-dequeued',
            'all-payload-completions-dequeued',
            'credential-data-writer-closed'),
           'increment-host-completion-only-after-all-prefix-payload-retirement-and-writer-close',
           '1100-to-1110',
           'no-reopen-or-retry',
           (1, 1, 1, 1)),
          (7,
           'execute-root-broker',
           'root-credential-acceptance',
           ('exact-length-nonzero-payload',
            'visible-ASCII-validation',
            'immediate-end-of-stream-validation'),
           'increment-root-accept-only-after-all-three-root-validation-predecessors',
           '1110-to-1111',
           'no-second-frame-connection-or-accept',
           (1, 1, 1, 1))))
        root_validation_table = (('step',
          'validation',
          'input_authority',
          'required_match',
          'failure_public_disposition',
          'successor_boundary',
          'retained_or_serialized_data',
          'provider_credential_projection'),
         ((1,
           'exact-length',
           'transient-decoded-prefix-and-retired-payload-read-cursor',
           'exactly-N-nonzero-bytes-with-no-retained-completed-or-transferred-byte-count',
           'CAMPAIGN_SECRET_ISOLATION_FAILED',
           'visible-ASCII-validation',
           'none',
           ()),
          (2,
           'visible-ASCII',
           'transient-complete-payload-buffer',
           'every-byte-is-0x21-through-0x7e',
           'CAMPAIGN_SECRET_ISOLATION_FAILED',
           'immediate-end-of-stream-validation',
           'none',
           ()),
          (3,
           'immediate-end-of-stream',
           'one-bounded-one-byte-extra-read-after-exact-payload',
           'EOF-or-ERROR_BROKEN_PIPE-at-role-permitted-read-terminal-with-no-trailing-byte-second-frame-or-missing-EOF',
           'CAMPAIGN_SECRET_ISOLATION_FAILED',
           'ProviderCredential-construction-eligibility',
           'none',
           ()),
          (4,
           'accepted-nonzero-provider-credential',
           'terminal-counter-state-1111-exact-authoritative-bindings-and-root-accepted-visible-ASCII-payload',
           'terminal-1111-permits-exact-ProviderCredential-construction-and-root-scoped-retention-only',
           'not-constructed',
           'later-H-to-P-of-H-to-C-of-H-and-P-to-authenticated-broker-response-and-persistence',
           ('value-retained-by-root-until-terminal-broker-shutdown',
            'value-repr-False',
            'value-compare-False',
            'value-never-canonicalized-hashed-logged-or-durably-serialized',
            'exact-or-rounded-length-never-retained'),
           (('environment_name', 'OPENAI_API_KEY'),
            ('transport_version', 'complete-suite-provider-credential-pipe-v1'),
            ('source_pipe_name_sha256', 'validated-readiness-pipe.value_sha256'),
            ('provider_attempt_claim_sha256',
             'authoritative-validated-provider-attempt-claim-sha256'),
            ('value',
             'exact-root-accepted-visible-ASCII-payload-decoded-without-substitution')))))
        terminal_counter_table = (('outcome',
          'credential_lookup_count',
          'credential_transfer_attempt_count',
          'credential_transfer_completion_count',
          'credential_frame_accept_count',
          'maximum_per_counter',
          'provider_credential_construction_permitted',
          'public_disposition'),
         (('pre-lookup-failure', 0, 0, 0, 0, 1, False, 'fail-before-credential-data-lookup'),
          ('prefix-incomplete-undecodable-or-unavailable-framing-rejected',
           1,
           0,
           0,
           0,
           1,
           False,
           'CAMPAIGN_SECRET_ISOLATION_FAILED'),
          ('complete-unavailable-N-zero',
           1,
           0,
           0,
           0,
           1,
           False,
           'CAMPAIGN_CREDENTIAL_UNAVAILABLE'),
          ('nonzero-started-host-write-failure',
           1,
           1,
           0,
           0,
           1,
           False,
           'CAMPAIGN_SECRET_ISOLATION_FAILED'),
          ('host-completed-nonzero-root-rejected-framing-or-EOF',
           1,
           1,
           1,
           0,
           1,
           False,
           'CAMPAIGN_SECRET_ISOLATION_FAILED'),
          ('accepted-nonzero-credential',
           1,
           1,
           1,
           1,
           1,
           True,
           'ProviderCredential-construction-and-root-scoped-retention-permitted-with-no-client-materialization-authority')))
        cleanup_successor_table = (('node',
          'actor',
          'required_predecessors',
          'required_action',
          'buffer_retirement_rule',
          'successor_boundary',
          'serialized_or_retained_surface',
          'concurrency_rule'),
         (('pre-lookup-admission-failure-lane',
           'trusted-host-and-execute-root-broker',
           ('registry-lifecycle-activated-after-canonical-ExecuteClaimReady',
            'fresh-revalidation-or-earlier-post-readiness-gate-failed'),
           'perform-no-credential-lookup-and-emit-no-credential-data-frame-with-all-four-counters-0000-then-continue-mandated-cleanup-and-status-handoff',
           'no-credential-data-value-prefix-or-payload-buffer-exists',
           'CredentialHostStatus-construction',
           'coarse-0000-counter-state-only',
           'the-one-mandated-status-handoff-and-its-cleanup-I/O-remain-exempt-from-the-credential-data-work-freeze'),
          ('freeze-new-credential-data-work',
           'trusted-host-and-execute-root-broker',
           ('any-pre-lookup-or-terminal-credential-data-path-entered',),
           'freeze-all-new-credential-data-connect-read-write-and-frame-work-while-exempting-the-one-mandated-CredentialHostStatus-handoff-and-its-cleanup-I/O',
           'no-buffer-is-scrubbed-before-its-I/O-retires',
           'credential-data-outstanding-operation-cancellation',
           'none',
           'row-order-grants-no-cross-actor-temporal-authority-and-both-sides-freeze-credential-data-work-independently'),
          ('cancel-and-retire-outstanding-credential-data-I/O',
           'trusted-host-and-execute-root-broker',
           ('new-credential-data-work-frozen',),
           'request-cancellation-for-each-outstanding-credential-data-connect-read-and-write-and-consume-every-completion',
           'all-operation-ledger-entries-retire-exactly-once',
           'side-specific-buffer-retirement',
           'coarse-operation-state-only',
           'status-handoff-and-status-cleanup-I/O-continue-under-their-own-ledger-and-neither-side-waits-for-the-other-to-start-data-cleanup'),
          ('host-data-writer-close-and-scrub',
           'trusted-host',
           ('all-host-credential-data-I/O-retired',),
           'close-the-credential-data-writer-exactly-once-then-best-effort-overwrite-every-allocated-mutable-payload-and-frame',
           'scrub-only-after-no-host-I/O-can-reference-the-buffer',
           'CredentialHostStatus-construction',
           'no-credential-bytes-N-length-count-or-hash',
           'host-waits-for-no-root-response'),
          ('mandated-status-handoff',
           'trusted-host',
           ('credential-data-writer-closed', 'host-mutable-data-buffers-scrubbed-or-absent'),
           'construct-CredentialHostStatus-only-from-immutable-bindings-and-coarse-terminal-counter-state',
           'later-status-buffer-retirement-is-a-successor-contract',
           'CredentialHostStatus-single-frame-handoff',
           'later-status-payload-and-lifecycle-serialization-out-of-scope',
           'status-construction-does-not-wait-for-root-credential-data-drain'),
          ('root-concurrent-data-status-pump',
           'execute-root-broker',
           ('credential-data-and-host-status-reads-armed',),
           'drain-credential-data-and-host-status-concurrently-and-never-wait-for-status-before-draining-data',
           'mutable-prefix-and-payload-remain-live-until-their-data-reads-retire',
           'root-data-buffer-retirement',
           'coarse-frame-and-counter-state-only',
           'both-channel-ledgers-progress-independently-under-one-deadline'),
          ('root-data-scrub-and-server-close',
           'execute-root-broker',
           ('all-root-credential-data-reads-retired',
            'both-channel-terminal-retirement-proven'),
           'best-effort-overwrite-mutable-prefix-and-payload-then-close-both-servers-exactly-once',
           'kernel-pipe-buffers-and-immutable-strings-are-not-claimed-zeroized',
           'cleanup-convergence',
           'no-credential-bytes-private-errors-handles-or-buffers',
           'status-channel-retirement-is-proven-independently'),
          ('provider-credential-construction-and-scoped-retention',
           'execute-root-broker',
           ('terminal-counter-state-is-exactly-1111',
            'exact-root-accepted-visible-ASCII-payload-decoded-without-substitution'),
           'permit-one-exact-ProviderCredential-construction-and-root-scoped-value-retention-until-terminal-broker-shutdown-only',
           'accepted-value-remains-root-scoped-until-terminal-broker-shutdown-and-is-never-canonicalized-hashed-logged-or-durably-serialized',
           'later-H-to-P-of-H-to-C-of-H-and-P-to-authenticated-broker-response-and-persistence',
           'exact-five-field-ProviderCredential-schema-with-value-repr-False-and-compare-False',
           '1111-is-necessary-but-not-sufficient-for-a-later-authenticated-client-request-and-independently-reopened-launch-evidence-and-this-registry-grants-no-materialization-authority')))
        invariants = ('these-facts-apply-only-to-the-credential-data-role-transfer-classification-counter-and-cleanup-handoff',
         'the-only-producer-is-the-trusted-host-and-the-only-consumer-is-the-execute-root-broker',
         'registry-lifecycle-activation-begins-after-canonical-ExecuteClaimReady-and-mandatory-post-readiness-one-shot-cleanup',
         'lookup-admission-is-only-the-exact-PeerAccepted-successor-single-credential-lookup-eligibility',
         'fresh-revalidation-or-earlier-post-readiness-gate-failure-before-lookup-emits-no-data-frame-keeps-0000-and-continues-cleanup-and-status-handoff',
         'the-successor-boundary-is-CredentialHostStatus-construction',
         'there-is-no-serialized-CredentialDataFrame-and-no-credential-data-frame-hash',
         'the-wire-is-exactly-four-byte-unsigned-little-endian-N-then-N-bytes-writer-close-and-EOF',
         'the-payload-cap-is-65536-and-the-maximum-wire-size-is-65540',
         'N-zero-is-the-only-unavailable-frame-creates-no-ProviderCredential-and-requires-EOF-or-ERROR_BROKEN_PIPE-at-role-permitted-read-terminal',
         'N-from-one-through-65536-is-only-a-candidate-until-root-validation-completes',
         'N-greater-than-65536-rejects-before-payload-allocation',
         'prefix-and-payload-reads-are-incremental-and-followed-by-exactly-one-bounded-one-byte-extra-read',
         'only-EOF-or-ERROR_BROKEN_PIPE-at-role-permitted-read-terminal-is-admissible-after-the-declared-payload',
         'partial-early-trailing-second-frame-second-connection-or-missing-EOF-fails-with-CAMPAIGN_SECRET_ISOLATION_FAILED',
         'credential-lookup-is-forbidden-before-the-exact-single-credential-lookup-eligibility-boundary',
         'the-host-atomically-increments-lookup-once-and-requests-only-OPENAI_API_KEY',
         'the-original-UTF-16-value-is-validated-character-by-character-before-strict-encoding',
         'only-nonempty-visible-ASCII-0x21-through-0x7e-of-at-most-65536-encoded-bytes-is-valid',
         'NUL-space-control-non-ASCII-surrogate-empty-over-cap-or-strict-encoding-failure-is-invalid',
         'invalid-values-are-never-trimmed-normalized-canonicalized-hashed-logged-durably-serialized-or-value-or-exact-or-rounded-length-retained',
         'an-invalid-value-writes-exactly-four-zero-bytes-then-closes-without-payload',
         'a-valid-nonzero-prefix-completes-and-dequeues-before-any-payload-write',
         'attempt-increments-immediately-before-the-first-payload-write-and-no-retry-is-permitted',
         'completion-increments-only-after-every-prefix-and-payload-completion-retires-and-the-writer-closes',
         'root-accept-increments-only-after-exact-length-visible-ASCII-and-immediate-EOF-validation',
         'the-six-terminal-counter-rows-are-closed-and-every-counter-never-exceeds-one',
         'ProviderCredential-schema-order-is-exactly-environment_name-transport_version-source_pipe_name_sha256-provider_attempt_claim_sha256-value',
         'ProviderCredential-binds-OPENAI_API_KEY-complete-suite-provider-credential-pipe-v1-readiness-pipe.value_sha256-authoritative-claim-sha256-and-the-root-accepted-visible-ASCII-value-decoded-without-substitution',
         'the-accepted-value-is-root-scoped-and-transiently-retained-only-until-terminal-broker-shutdown',
         'ProviderCredential-value-is-repr-False-compare-False-and-never-canonicalized-hashed-logged-or-durably-serialized',
         'terminal-1111-permits-ProviderCredential-construction-and-scoped-retention-only-is-necessary-not-sufficient-and-grants-no-client-materialization-authority',
         'later-materialization-requires-H-to-P-to-C-to-authenticated-broker-response-and-persistence-then-a-later-authenticated-client-request-and-independently-reopened-launch-evidence',
         'credential-bytes-N-exact-or-rounded-length-completed-or-transferred-count-and-payload-length-or-frame-hashes-are-never-durably-serialized-canonicalized-hashed-logged-or-length-retained-while-the-accepted-value-may-remain-root-scoped-until-shutdown',
         'generic-pipe-lifecycle-projections-private-errors-handles-and-buffers-are-excluded',
         'each-terminal-path-freezes-only-new-credential-data-work-while-exempting-the-one-mandated-status-handoff-and-its-cleanup-I/O',
         'each-side-requests-outstanding-credential-data-operation-cancellation-and-consumes-every-completion',
         'the-host-closes-data-writer-once-scrubs-after-I/O-retirement-and-constructs-status-only-from-immutable-and-coarse-state',
         'the-root-drains-data-and-status-concurrently-never-waits-for-status-first-and-scrubs-only-after-data-reads-retire',
         'cleanup-table-row-order-grants-no-cross-actor-temporal-authority-and-only-explicit-predecessor-edges-constrain-each-node',
         'kernel-pipe-buffers-and-immutable-strings-are-not-claimed-zeroized-and-both-servers-close-once',
         'later-status-lifecycle-broker-response-and-persistence-semantics-are-out-of-scope-and-this-registry-grants-no-runtime-authority')
        return tuple.__new__(
            cls,
            (
                identity_table,
                wire_classification_table,
                lookup_value_admission_table,
                transfer_partial_order_table,
                root_validation_table,
                terminal_counter_table,
                cleanup_successor_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def wire_classification_table(self):
        return self[1]

    @property
    def lookup_value_admission_table(self):
        return self[2]

    @property
    def transfer_partial_order_table(self):
        return self[3]

    @property
    def root_validation_table(self):
        return self[4]

    @property
    def terminal_counter_table(self):
        return self[5]

    @property
    def cleanup_successor_table(self):
        return self[6]

    @property
    def invariants(self):
        return self[7]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftCredentialDataTransferFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "wire_classification_row_count="
            f"{len(self.wire_classification_table[1])!r}, "
            "lookup_value_admission_row_count="
            f"{len(self.lookup_value_admission_table[1])!r}, "
            "transfer_partial_order_row_count="
            f"{len(self.transfer_partial_order_table[1])!r}, "
            "root_validation_row_count="
            f"{len(self.root_validation_table[1])!r}, "
            "terminal_counter_row_count="
            f"{len(self.terminal_counter_table[1])!r}, "
            "cleanup_successor_row_count="
            f"{len(self.cleanup_successor_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftCredentialHostStatusFactsRegistry(tuple):
    __slots__ = ()

    def __new__(cls):
        if cls is not _C6BrokerNativeCoreDraftCredentialHostStatusFactsRegistry:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        identity_table = (
            (
                "implementation_id",
                "state_machine_id",
                "protocol_scope",
                "record_type",
                "dynamic_role",
                "producer",
                "consumer",
                "activation_boundary",
                "predecessor_boundary",
                "successor_boundary",
                "applicability",
                "excluded_semantic_scopes",
            ),
            (
                (
                    "broker-native-core-v1",
                    "complete-suite-native-constructor-state-machine-v1",
                    "credential-host-status-secret-free-host-only-terminal-projection-and-single-frame-handoff",
                    "CredentialHostStatus",
                    "credential-host-status",
                    "trusted-host",
                    "execute-root-broker",
                    (
                        "canonical-ExecuteClaimReady-emitted-and-validated",
                        "any-terminal-CredentialDataTransfer-path-entered",
                        "credential-data-writer-closed-exactly-once",
                        "credential-data-writer-outstanding-I/O-final-zero",
                        "host-mutable-credential-data-buffers-scrubbed-or-absent",
                    ),
                    "CredentialHostStatus-construction",
                    "CredentialPipeLifecycleRecord-construction-as-P-of-H",
                    "every-post-readiness-terminal-path-including-pre-lookup-failure-credential-unavailable-host-transfer-failure-and-host-transfer-complete",
                    (
                        "CredentialPipeLifecycleRecord-payload-and-serialization",
                        "CredentialLifecycleRecord-construction-and-serialization",
                        "broker-response-sequencing",
                        "durable-persistence",
                        "client-environment-materialization",
                        "private-error-projection",
                        "runtime-I/O-authority",
                    ),
                ),
            ),
        )
        payload_schema_table = (
            (
                "record_type",
                "schema_version",
                "serialized_field_order",
                "wrapper_only_fields",
                "field_domain_table",
                "canonical_payload_contract",
                "wrapper_hash_contract",
                "outer_frame_contract",
                "payload_cap_bytes",
                "maximum_wire_bytes",
                "forbidden_payload_categories",
            ),
            (
                (
                    "CredentialHostStatus",
                    "complete-suite-credential-host-status-v1",
                    (
                        "version",
                        "transport_version",
                        "provider_attempt_claim_sha256",
                        "execute_claim_capability_sha256",
                        "claim_ready_sha256",
                        "peer_accepted_sha256",
                        "pipe_name_sha256",
                        "host_status_pipe_name_sha256",
                        "host_pid",
                        "host_creation_time",
                        "root_pid",
                        "root_creation_time",
                        "frame_kind",
                        "prefix_progress",
                        "payload_progress",
                        "outcome",
                        "credential_lookup_count",
                        "credential_transfer_attempt_count",
                        "credential_transfer_completion_count",
                        "credential_data_writer_closed",
                        "credential_data_writer_outstanding_io_final",
                        "host_mutable_buffers_scrubbed_or_absent",
                    ),
                    ("canonical_sha256",),
                    (
                        (
                            "version",
                            ("literal-complete-suite-credential-host-status-v1",),
                        ),
                        (
                            "transport_version",
                            ("literal-complete-suite-provider-credential-pipe-v1",),
                        ),
                        (
                            "provider_attempt_claim_sha256",
                            ("exact-validated-wrapper-64-lowercase-hex",),
                        ),
                        (
                            "execute_claim_capability_sha256",
                            ("exact-validated-wrapper-64-lowercase-hex",),
                        ),
                        (
                            "claim_ready_sha256",
                            ("exact-validated-wrapper-64-lowercase-hex",),
                        ),
                        (
                            "peer_accepted_sha256",
                            (
                                "null-if-no-canonical-peer-accepted-frame-was-successfully-emitted",
                                "exact-emitted-wrapper-canonical_sha256-after-successful-root-emission",
                            ),
                        ),
                        (
                            "pipe_name_sha256",
                            ("exact-readiness-nested-value-sha256",),
                        ),
                        (
                            "host_status_pipe_name_sha256",
                            ("exact-readiness-nested-value-sha256",),
                        ),
                        (
                            "host_pid-and-host_creation_time",
                            ("exact-authenticated-host-PID-and-creation-time-pair",),
                        ),
                        (
                            "root_pid-and-root_creation_time",
                            ("exact-authenticated-root-PID-and-creation-time-pair",),
                        ),
                        (
                            "frame_kind",
                            ("none", "indeterminate", "unavailable", "nonzero"),
                        ),
                        (
                            "prefix_progress",
                            ("none", "partial", "complete"),
                        ),
                        (
                            "payload_progress",
                            ("not-applicable", "none", "partial", "complete"),
                        ),
                        (
                            "outcome",
                            (
                                "pre-lookup-failure",
                                "credential-unavailable",
                                "host-transfer-failure",
                                "host-transfer-complete",
                            ),
                        ),
                        (
                            "credential_lookup_count",
                            (0, 1),
                        ),
                        (
                            "credential_transfer_attempt_count",
                            (0, 1),
                        ),
                        (
                            "credential_transfer_completion_count",
                            (0, 1),
                        ),
                        (
                            "credential_data_writer_closed",
                            (True,),
                        ),
                        (
                            "credential_data_writer_outstanding_io_final",
                            (0,),
                        ),
                        (
                            "host_mutable_buffers_scrubbed_or_absent",
                            (True,),
                        ),
                    ),
                    "one-compact-strict-ASCII-JSON-object-in-exact-serialized-field-order-plus-exactly-one-LF",
                    "SHA-256-over-the-exact-canonical-payload-bytes-including-its-one-LF-with-canonical_sha256-excluded",
                    (
                        ("length_prefix_bytes", 4),
                        ("length_prefix_type", "unsigned-payload-byte-length"),
                        ("length_prefix_endianness", "little-endian"),
                        ("payload_encoding", "strict-ASCII"),
                        ("payload_canonical_form", "compact-JSON-plus-one-LF"),
                        ("writer_termination", "writer-close-then-EOF"),
                    ),
                    65_536,
                    65_540,
                    (
                        "serialized-canonical_sha256",
                        "canonical-bytes-field",
                        "credential-frame-accept-count",
                        "N-or-credential-bytes-or-value",
                        "exact-or-rounded-credential-payload-length",
                        "credential-data-transferred-byte-count",
                        "credential-or-length-derived-hash",
                        "private-error-or-free-form-text",
                        "pipe-or-process-handle",
                        "mutable-buffer",
                        "credential-or-pipe-lifecycle-object-or-hash",
                        "unknown-or-extra-field",
                    ),
                ),
            ),
        )
        source_binding_table = (
            (
                "source_family",
                "bound_payload_fields",
                "authoritative_sources",
                "required_agreement",
                "caller_supplied",
                "phase_rule",
            ),
            (
                (
                    "schema-and-transport-versions",
                    ("version", "transport_version"),
                    (
                        "protocol-literals",
                        "validated-ExecuteClaimReady.credential_transport_version",
                    ),
                    "exact-status-and-provider-credential-transport-version-literals",
                    False,
                    "same-on-every-post-readiness-status",
                ),
                (
                    "provider-attempt-claim-wrapper-hash",
                    ("provider_attempt_claim_sha256",),
                    (
                        "validated-ExecuteClaimCapability",
                        "validated-ExecuteClaimReady",
                        "freshly-reopened-provider-attempt-claim",
                    ),
                    "one-exact-independently-validated-provider-attempt-claim-wrapper-hash",
                    False,
                    "required-on-every-status",
                ),
                (
                    "execute-claim-capability-wrapper-hash",
                    ("execute_claim_capability_sha256",),
                    (
                        "exact-validated-ExecuteClaimCapability-wrapper-canonical_sha256",
                        "ExecuteClaimReady-exact-repeated-capability-bindings",
                    ),
                    "exact-capability-wrapper-hash-never-a-reconstruction-from-selected-fields",
                    False,
                    "required-on-every-status",
                ),
                (
                    "execute-claim-ready-wrapper-hash",
                    ("claim_ready_sha256",),
                    ("exact-authenticated-canonical-ExecuteClaimReady-frame",),
                    "exact-readiness-wrapper-hash-over-the-validated-canonical-readiness-bytes",
                    False,
                    "required-on-every-post-readiness-status",
                ),
                (
                    "optional-peer-accepted-wrapper-hash",
                    ("peer_accepted_sha256",),
                    (
                        "exact-canonical-ExecuteCredentialPeerAccepted-wrapper-after-successful-root-emission",
                    ),
                    "null-if-and-only-if-no-canonical-peer-accepted-frame-was-successfully-emitted-otherwise-the-exact-emitted-wrapper-canonical_sha256",
                    False,
                    "not-emitted-implies-pre-lookup-failure-000-and-null; emitted-implies-pre-lookup-failure-or-later-outcome-with-the-exact-non-null-hash; inability-to-produce-an-exact-coherent-post-readiness-H-is-invalid_consumed_attempt",
                ),
                (
                    "readiness-nested-pipe-name-value-hashes",
                    ("pipe_name_sha256", "host_status_pipe_name_sha256"),
                    (
                        "ExecuteClaimReady.pipe.value_sha256",
                        "ExecuteClaimReady.host_status_pipe.value_sha256",
                    ),
                    "bind-the-two-exact-nested-value-sha256-fields-never-either-nested-canonical_sha256",
                    False,
                    "required-on-every-status",
                ),
                (
                    "authenticated-host-peer-identity",
                    ("host_pid", "host_creation_time"),
                    (
                        "authenticated-trusted-host-identity",
                        "both-root-side-client-peer-PID-observations",
                        "authenticated-trusted-host-process-creation-time",
                    ),
                    "one-exact-host-PID-and-creation-time-pair",
                    False,
                    "readiness-bound-on-every-status-and-emitted-wrapper-reconfirmed-after-successful-root-emission",
                ),
                (
                    "authenticated-root-peer-identity",
                    ("root_pid", "root_creation_time"),
                    (
                        "authenticated-root-broker-identity",
                        "both-host-side-server-peer-PID-observations",
                        "validated-ExecuteClaimReady-root-process-identity",
                    ),
                    "one-exact-root-PID-and-creation-time-pair",
                    False,
                    "readiness-bound-on-every-status-and-emitted-wrapper-reconfirmed-after-successful-root-emission",
                ),
                (
                    "retired-host-credential-data-ledger-projection",
                    (
                        "frame_kind",
                        "prefix_progress",
                        "payload_progress",
                        "outcome",
                        "credential_lookup_count",
                        "credential_transfer_attempt_count",
                        "credential_transfer_completion_count",
                    ),
                    (
                        "retired-host-operation-ledger",
                        "immutable-coarse-terminal-counter-state",
                    ),
                    "closed-host-projection-agrees-with-the-exact-retired-write-cursor-without-retaining-a-byte-count",
                    False,
                    "constructed-only-after-no-host-credential-data-I/O-can-reference-a-buffer",
                ),
                (
                    "credential-data-cleanup-convergence",
                    (
                        "credential_data_writer_closed",
                        "credential_data_writer_outstanding_io_final",
                        "host_mutable_buffers_scrubbed_or_absent",
                    ),
                    (
                        "host-credential-data-writer-close-ledger",
                        "host-credential-data-operation-retirement-ledger",
                        "post-retirement-best-effort-mutable-buffer-overwrite",
                    ),
                    "exactly-True-zero-True",
                    False,
                    "precedes-status-construction-and-does-not-cover-status-writer-I/O",
                ),
            ),
        )
        host_projection_table = (
            (
                "outcome",
                "frame_kind",
                "prefix_progress",
                "payload_progress",
                "credential_lookup_count",
                "credential_transfer_attempt_count",
                "credential_transfer_completion_count",
                "admissible_cursor_projections",
                "required_host_evidence",
                "relational_rule",
                "root_accept_projection",
            ),
            (
                (
                    "pre-lookup-failure",
                    "none",
                    "none",
                    "not-applicable",
                    0,
                    0,
                    0,
                    (("none", "none", "not-applicable", 0),),
                    "no-credential-lookup-and-no-credential-data-frame",
                    "peer_accepted_sha256-is-null-before-successful-root-emission-or-exactly-non-null-after-successful-root-emission-followed-by-pre-lookup-rejection",
                    "not-observed-or-serialized-by-host-status",
                ),
                (
                    "credential-unavailable",
                    "unavailable",
                    "complete",
                    "not-applicable",
                    1,
                    0,
                    0,
                    (("unavailable", "complete", "not-applicable", 0),),
                    "authoritative-retired-host-operation-and-completion-ledger-proves-the-exact-four-byte-N-zero-prefix-completed-successfully-before-data-writer-close",
                    "complete-successful-unavailable-framing-is-distinguished-from-the-same-cursor-failure-projection-by-authoritative-host-operation-and-completion-evidence",
                    "not-observed-or-serialized-by-host-status",
                ),
                (
                    "host-transfer-failure",
                    ("indeterminate", "unavailable", "nonzero"),
                    ("none", "partial", "complete"),
                    ("not-applicable", "none", "partial"),
                    1,
                    (0, 1),
                    0,
                    (
                        ("indeterminate", "none", "not-applicable", 0),
                        ("indeterminate", "partial", "not-applicable", 0),
                        ("unavailable", "complete", "not-applicable", 0),
                        ("nonzero", "complete", "none", 1),
                        ("nonzero", "complete", "partial", 1),
                    ),
                    "authoritative-retired-host-operation-and-completion-ledger-proves-a-required-prefix-or-payload-write-did-not-complete-successfully-at-the-exact-retired-write-cursor",
                    "the-five-declared-cursor-projections-are-the-complete-relation-and-their-derived-column-domains-grant-no-Cartesian-widening-or-byte-count",
                    "not-observed-or-serialized-by-host-status",
                ),
                (
                    "host-transfer-complete",
                    "nonzero",
                    "complete",
                    "complete",
                    1,
                    1,
                    1,
                    (("nonzero", "complete", "complete", 1),),
                    "all-prefix-and-payload-completions-retired-and-credential-data-writer-closed",
                    "host-completion-is-identical-whether-the-root-later-rejects-framing-or-accepts-the-credential",
                    "later-root-counter-may-be-zero-or-one-and-is-never-serialized-in-host-status",
                ),
            ),
        )
        credential_data_join_table = (
            (
                "credential_data_terminal_outcome",
                "terminal_counter_state",
                "additional_host_authority",
                "host_status_outcome",
                "host_status_counter_projection",
                "classification_rule",
                "root_accept_projection",
            ),
            (
                (
                    "pre-lookup-failure",
                    (0, 0, 0, 0),
                    "no-lookup-and-no-data-frame",
                    "pre-lookup-failure",
                    (0, 0, 0),
                    "counter-state-and-absence-of-host-data-work-agree",
                    "not-serialized",
                ),
                (
                    "prefix-incomplete-undecodable-or-unavailable-framing-rejected",
                    (1, 0, 0, 0),
                    "retired-host-prefix-cursor-and-writer-close-evidence",
                    ("host-transfer-failure", "credential-unavailable"),
                    (1, 0, 0),
                    "the-ambiguous-1000-state-is-never-classified-from-counters-alone",
                    "root-rejected-and-not-serialized",
                ),
                (
                    "complete-unavailable-N-zero",
                    (1, 0, 0, 0),
                    "exact-complete-four-byte-N-zero-host-frame-and-writer-close",
                    "credential-unavailable",
                    (1, 0, 0),
                    "retired-host-cursor-proves-complete-unavailable-framing",
                    "root-not-accepted-and-not-serialized",
                ),
                (
                    "nonzero-started-host-write-failure",
                    (1, 1, 0, 0),
                    "first-nonzero-payload-write-issued-and-one-or-more-required-host-write-completions-did-not-converge",
                    "host-transfer-failure",
                    (1, 1, 0),
                    "attempt-one-is-bound-to-the-first-nonzero-payload-write-issue",
                    "root-not-accepted-and-not-serialized",
                ),
                (
                    "host-completed-nonzero-root-rejected-framing-or-EOF",
                    (1, 1, 1, 0),
                    "host-completed-nonzero-frame-before-later-root-rejection",
                    "host-transfer-complete",
                    (1, 1, 1),
                    "host-status-does-not-rewrite-the-host-outcome-from-the-later-root-result",
                    "zero-and-not-serialized",
                ),
                (
                    "accepted-nonzero-credential",
                    (1, 1, 1, 1),
                    "host-completed-nonzero-frame-before-later-root-acceptance",
                    "host-transfer-complete",
                    (1, 1, 1),
                    "root-acceptance-is-a-later-root-side-fact-not-host-status-authority",
                    "one-and-not-serialized",
                ),
            ),
        )
        status_handoff_table = (
            (
                "step",
                "node",
                "actor",
                "required_predecessors",
                "required_action",
                "retirement_or_hash_rule",
                "forbidden_retained_surface",
                "successor_boundary",
                "concurrency_rule",
            ),
            (
                (
                    1,
                    "status-construction-admission",
                    "trusted-host",
                    (
                        "credential-data-writer-closed-exactly-once",
                        "credential-data-writer-outstanding-I/O-final-zero",
                        "host-mutable-credential-data-buffers-scrubbed-or-absent",
                    ),
                    "construct-one-CredentialHostStatus-only-from-immutable-bindings-and-the-coarse-host-projection",
                    "credential-data-I/O-and-buffer-lifetimes-retire-before-status-construction",
                    "credential-bytes-N-length-count-hash-private-error-handle-or-buffer",
                    "canonical-status-payload-construction",
                    "host-waits-for-no-root-response-and-does-not-wait-for-root-data-drain",
                ),
                (
                    2,
                    "canonical-status-payload-construction",
                    "trusted-host",
                    ("one-admitted-CredentialHostStatus",),
                    "serialize-exactly-the-twenty-two-fields-in-order-as-one-compact-strict-ASCII-JSON-object-plus-one-LF",
                    "hash-the-exact-canonical-payload-bytes-including-the-one-LF-without-the-wrapper-field-or-frame-prefix",
                    "canonical_sha256-field-second-LF-extra-whitespace-unknown-field-or-credential-derived-data",
                    "single-status-frame-issue",
                    "no-status-I/O-is-performed-by-this-dormant-facts-registry",
                ),
                (
                    3,
                    "single-status-frame-issue",
                    "trusted-host",
                    ("canonical-status-payload-within-65536-byte-cap",),
                    "issue-one-unsigned-four-byte-little-endian-payload-length-followed-by-the-exact-payload",
                    "retire-every-prefix-and-payload-write-completion-before-status-writer-close",
                    "second-frame-retry-reconnect-credential-data-or-transferred-byte-count",
                    "status-writer-close",
                    "the-status-writer-has-its-own-ledger-distinct-from-the-already-closed-data-writer",
                ),
                (
                    4,
                    "status-writer-close",
                    "trusted-host",
                    ("all-status-prefix-and-payload-write-completions-retired",),
                    "close-the-status-writer-exactly-once-to-produce-EOF",
                    "the-CredentialHostStatus-data-writer-outstanding-I/O-field-does-not-claim-status-writer-retirement",
                    "second-status-frame-retry-root-response-or-open-writer",
                    "root-status-frame-and-EOF-validation",
                    "host-waits-for-no-root-response-before-or-after-close",
                ),
                (
                    5,
                    "root-concurrent-data-status-pump",
                    "execute-root-broker",
                    ("credential-data-and-host-status-reads-armed",),
                    "drain-both-channels-concurrently-and-never-wait-for-status-before-draining-credential-data",
                    "prove-status-frame-EOF-and-zero-outstanding-status-reads-independently-of-the-host-data-writer-field",
                    "credential-bytes-or-status-before-data-ordering-authority",
                    "authenticated-host-status-validation",
                    (
                        "status-handoff-table-row-order-grants-no-cross-actor-temporal-authority",
                        "both-read-ledgers-progress-independently-under-one-deadline",
                    ),
                ),
            ),
        )
        root_validation_table = (
            (
                "step",
                "validation",
                "input_authority",
                "required_match",
                "failure_disposition",
                "successor_boundary",
                "retained_or_serialized_surface",
            ),
            (
                (
                    1,
                    "single-bounded-canonical-frame-and-EOF",
                    "credential-host-status-read-ledger-and-exact-received-bytes",
                    "one-uint32-little-endian-length-at-most-65536-one-canonical-payload-one-LF-immediate-EOF-and-no-trailing-or-second-frame",
                    "invalid_consumed_attempt-after-readiness",
                    "binding-and-wrapper-hash-validation",
                    "exact-secret-free-status-bytes-only",
                ),
                (
                    2,
                    "binding-and-wrapper-hash-validation",
                    "validated-readiness-capability-claim-optional-peer-and-recomputed-canonical-status-hash",
                    "every-wrapper-pipe-name-hash-and-version-binding-agrees-exactly",
                    "invalid_consumed_attempt-after-readiness",
                    "peer-identity-validation",
                    "exact-CredentialHostStatus-and-its-recomputed-wrapper-hash",
                ),
                (
                    3,
                    "peer-identity-validation",
                    "validated-readiness-and-both-direction-authenticated-peer-observations",
                    "host-and-root-PID-and-creation-time-pairs-agree-and-peer_accepted_sha256-obeys-its-phase-rule",
                    "invalid_consumed_attempt-after-readiness",
                    "credential-data-observation-and-host-projection-validation",
                    "no-process-handle-or-private-query-error",
                ),
                (
                    4,
                    "credential-data-observation-and-host-projection-validation",
                    "exact-authenticated-received-CredentialHostStatus-H-root-owned-credential-data-pipe-observations-and-closed-CredentialHostStatus-host-projection-table",
                    "frame-progress-outcome-counters-data-writer-close-and-cleanup-form-one-closed-coherent-host-row",
                    "invalid_consumed_attempt-after-readiness",
                    "CredentialPipeLifecycleRecord-construction-as-P-of-H",
                    "preserve-the-exact-authenticated-H-and-its-exact-hash-without-rewriting-host-outcome-from-root-acceptance",
                ),
                (
                    5,
                    "post-readiness-presence-rule",
                    "authenticated-ExecuteClaimReady-emission-and-terminal-cleanup-state",
                    "every-orderly-post-readiness-response-has-one-authenticated-H-and-later-both-lifecycle-objects",
                    "missing-malformed-unauthenticated-incoherent-over-cap-trailing-second-or-unterminated-status-is-invalid_consumed_attempt-not-a-controlled-null-projection",
                    "CredentialPipeLifecycleRecord-construction-as-P-of-H",
                    "no-null-lifecycle-after-observed-readiness",
                ),
            ),
        )
        invariants = (
            "these-facts-apply-only-to-secret-free-CredentialHostStatus-construction-serialization-single-frame-handoff-and-root-validation-after-readiness",
            "the-only-producer-is-the-trusted-host-and-the-only-consumer-validator-is-the-execute-root-broker",
            "every-post-readiness-terminal-credential-data-path-must-produce-one-status-including-pre-lookup-unavailable-failed-and-host-complete-paths",
            "before-canonical-ExecuteClaimReady-there-is-no-H-P-or-C-and-all-four-counters-are-zero",
            "the-predecessor-boundary-is-exactly-CredentialHostStatus-construction-from-the-CredentialDataTransfer-successor-registry",
            "the-only-immediate-successor-is-CredentialPipeLifecycleRecord-construction-as-P-of-H",
            "the-authority-order-is-H-then-P-of-H-then-C-of-H-sha256-and-P-sha256-then-authenticated-broker-response-and-persistence",
            "the-exact-twenty-two-fields-through-host_mutable_buffers_scrubbed_or_absent-serialize-in-dataclass-order",
            "canonical_sha256-is-wrapper-only-and-never-serialized-inside-its-own-payload",
            "the-version-and-transport-version-literals-are-exact-and-the-enum-and-counter-domains-are-closed",
            "the-payload-is-one-compact-strict-ASCII-JSON-object-plus-exactly-one-LF",
            "the-wrapper-hash-covers-the-exact-canonical-payload-bytes-including-the-one-LF-and-excludes-prefix-close-EOF-and-wrapper-field",
            "the-outer-frame-is-one-unsigned-four-byte-little-endian-payload-length-then-payload-writer-close-and-EOF",
            "the-payload-cap-is-65536-and-the-maximum-framed-wire-size-is-65540",
            "the-host-status-is-secret-free-and-never-contains-credential-bytes-value-N-or-exact-or-rounded-credential-length",
            "the-host-status-never-contains-a-credential-data-transferred-byte-count-or-credential-or-length-derived-hash",
            "the-host-status-never-contains-private-error-text-handles-mutable-buffers-lifecycle-objects-or-unknown-fields",
            "provider-claim-capability-readiness-and-optional-peer-hashes-are-exact-independently-validated-wrapper-hashes-not-reconstructions",
            "pipe-name-hashes-bind-readiness-nested-value_sha256-fields-never-the-nested-wrapper-hashes",
            "host-and-root-identities-are-exact-authenticated-PID-and-creation-time-pairs-and-PID-alone-grants-no-authority",
            "peer_accepted_sha256-is-null-if-and-only-if-no-canonical-peer-accepted-frame-was-successfully-emitted-and-otherwise-is-the-exact-emitted-wrapper-canonical_sha256",
            "not-emitted-implies-pre-lookup-failure-000-and-null-while-emitted-implies-pre-lookup-failure-or-later-outcome-with-the-exact-non-null-hash",
            "inability-to-produce-an-exact-coherent-post-readiness-H-after-successful-root-emission-is-invalid_consumed_attempt-and-never-a-null-fallback",
            "every-lookup-transfer-unavailable-failure-or-complete-outcome-requires-the-exact-non-null-peer-hash",
            "pre-lookup-failure-is-exactly-none-none-not-applicable-and-host-counters-000",
            "credential-unavailable-is-exactly-unavailable-complete-not-applicable-and-host-counters-100",
            "host-transfer-failure-has-exactly-the-five-declared-admissible-cursor-projections-with-lookup-one-and-completion-zero",
            "host-transfer-failure-attempt-one-implies-nonzero-complete-and-none-or-partial-payload-while-attempt-zero-implies-not-applicable-payload",
            "host-transfer-failure-forbids-nonzero-complete-complete-attempt-one-with-completion-zero-and-grants-no-Cartesian-widening-or-retained-byte-count",
            "unavailable-complete-not-applicable-attempt-zero-is-admissible-for-host-transfer-failure-and-authoritative-host-operation-and-completion-evidence-distinguishes-it-from-credential-unavailable",
            "host-transfer-complete-is-exactly-nonzero-complete-complete-and-host-counters-111",
            "host-transfer-complete-covers-both-later-root-rejection-1110-and-later-root-acceptance-1111",
            "root-credential-acceptance-is-not-host-status-authority-and-is-never-serialized-in-H",
            "the-ambiguous-predecessor-1000-state-is-classified-only-with-the-retired-host-prefix-and-close-evidence-never-from-counters-alone",
            "the-host-closes-the-credential-data-writer-once-retires-all-data-I/O-and-scrubs-or-marks-absent-mutable-data-buffers-before-H-construction",
            "credential_data_writer_outstanding_io_final-covers-only-the-already-closed-data-writer-not-the-status-writer",
            "the-host-retires-the-one-status-frame-write-closes-the-status-writer-and-waits-for-no-root-response",
            "the-root-drains-data-and-status-concurrently-and-never-waits-for-status-before-draining-data",
            "status-handoff-table-row-order-grants-no-cross-actor-temporal-authority-and-both-read-ledgers-progress-independently-under-one-deadline",
            "the-root-validates-framing-EOF-hash-bindings-peer-identities-data-observations-and-the-closed-host-projection-before-P-of-H",
            "root-host-projection-validation-authority-is-only-the-exact-authenticated-received-H-root-owned-data-pipe-observations-and-the-closed-HostStatus-projection-table-never-the-private-retired-host-ledger",
            "the-root-preserves-the-exact-authenticated-H-and-hash-and-never-rewrites-host-outcome-from-root-acceptance",
            "missing-malformed-unauthenticated-incoherent-over-cap-trailing-second-or-unterminated-post-readiness-status-is-invalid_consumed_attempt",
            "a-null-lifecycle-after-observed-readiness-is-forbidden-and-never-an-orderly-controlled-failure",
            "pipe-and-credential-lifecycle-broker-response-persistence-client-materialization-private-error-and-runtime-I/O-semantics-are-out-of-scope",
            "this-registry-performs-no-serialization-hashing-I/O-cleanup-lifecycle-construction-process-launch-persistence-or-runtime-selection",
        )
        return tuple.__new__(
            cls,
            (
                identity_table,
                payload_schema_table,
                source_binding_table,
                host_projection_table,
                credential_data_join_table,
                status_handoff_table,
                root_validation_table,
                invariants,
            ),
        )

    @property
    def identity_table(self):
        return self[0]

    @property
    def payload_schema_table(self):
        return self[1]

    @property
    def source_binding_table(self):
        return self[2]

    @property
    def host_projection_table(self):
        return self[3]

    @property
    def credential_data_join_table(self):
        return self[4]

    @property
    def status_handoff_table(self):
        return self[5]

    @property
    def root_validation_table(self):
        return self[6]

    @property
    def invariants(self):
        return self[7]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftCredentialHostStatusFactsRegistry("
            "identity_row_count="
            f"{len(self.identity_table[1])!r}, "
            "payload_schema_row_count="
            f"{len(self.payload_schema_table[1])!r}, "
            "source_binding_row_count="
            f"{len(self.source_binding_table[1])!r}, "
            "host_projection_row_count="
            f"{len(self.host_projection_table[1])!r}, "
            "credential_data_join_row_count="
            f"{len(self.credential_data_join_table[1])!r}, "
            "status_handoff_row_count="
            f"{len(self.status_handoff_table[1])!r}, "
            "root_validation_row_count="
            f"{len(self.root_validation_table[1])!r}, "
            f"invariant_count={len(self.invariants)!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftIocpWaitWindow(tuple):
    __slots__ = ()

    def __new__(cls, remaining_monotonic_ns):
        if (
            cls is not _C6BrokerNativeCoreDraftIocpWaitWindow
            or type(remaining_monotonic_ns) is not int
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if remaining_monotonic_ns <= 0:
            _reject(GUARDED_BOOTSTRAP_INVALID)

        wait_timeout_ms = min(
            50,
            (remaining_monotonic_ns + 999_999) // 1_000_000,
        )
        return tuple.__new__(
            cls,
            (
                remaining_monotonic_ns,
                wait_timeout_ms,
            ),
        )

    @property
    def remaining_monotonic_ns(self):
        return self[0]

    @property
    def wait_timeout_ms(self):
        return self[1]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftIocpWaitWindow(wait_timeout_ms="
            f"{self.wait_timeout_ms!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftWireReadWindow(tuple):
    __slots__ = ()

    def __new__(cls, byte_cap, completed_wire_bytes):
        if (
            cls is not _C6BrokerNativeCoreDraftWireReadWindow
            or type(byte_cap) is not int
            or type(completed_wire_bytes) is not int
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if (
            byte_cap < 0
            or completed_wire_bytes < 0
            or completed_wire_bytes > byte_cap
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)

        remaining_cap_bytes = byte_cap - completed_wire_bytes
        maximum_read_request_bytes = min(
            65_536,
            remaining_cap_bytes + 1,
        )
        return tuple.__new__(
            cls,
            (
                byte_cap,
                completed_wire_bytes,
                remaining_cap_bytes,
                maximum_read_request_bytes,
            ),
        )

    @property
    def byte_cap(self):
        return self[0]

    @property
    def completed_wire_bytes(self):
        return self[1]

    @property
    def remaining_cap_bytes(self):
        return self[2]

    @property
    def maximum_read_request_bytes(self):
        return self[3]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftWireReadWindow("
            "maximum_read_request_bytes="
            f"{self.maximum_read_request_bytes!r})"
        )

    __str__ = __repr__


class _C6BrokerNativeCoreDraftControlFrameAdmission(tuple):
    __slots__ = ()

    def __new__(cls, remaining_cap_bytes, payload_length_bytes):
        if (
            cls is not _C6BrokerNativeCoreDraftControlFrameAdmission
            or type(remaining_cap_bytes) is not int
            or type(payload_length_bytes) is not int
        ):
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if remaining_cap_bytes < 0 or payload_length_bytes < 0:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        if payload_length_bytes > 65_536:
            _reject(GUARDED_BOOTSTRAP_INVALID)

        frame_wire_bytes = 4 + payload_length_bytes
        if frame_wire_bytes > remaining_cap_bytes:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        return tuple.__new__(
            cls,
            (
                remaining_cap_bytes,
                payload_length_bytes,
                frame_wire_bytes,
            ),
        )

    @property
    def remaining_cap_bytes(self):
        return self[0]

    @property
    def payload_length_bytes(self):
        return self[1]

    @property
    def frame_wire_bytes(self):
        return self[2]

    def __repr__(self):
        return (
            "_C6BrokerNativeCoreDraftControlFrameAdmission("
            f"payload_length_bytes={self.payload_length_bytes!r}, "
            f"frame_wire_bytes={self.frame_wire_bytes!r})"
        )

    __str__ = __repr__


_C6_BROKER_NATIVE_CORE_DRAFT_ROOT_PROCESS_LIMIT_TABLE = (
    _C6BrokerNativeCoreDraftLimitTable(
        "invoke-c6-root-python",
            (
                "role",
                "deadline_ms",
                "stdin_cap_bytes",
                "stdout_cap_bytes",
                "stderr_cap_bytes",
            ),
            (
                ("development-pytest", 900_000, 0, 4_194_304, 4_194_304),
                ("client-preflight-freeze", 1_800_000, 0, 4_194_304, 4_194_304),
                ("client-preflight-audit", 600_000, 0, 4_194_304, 4_194_304),
                ("guarded-pytest-audit", 3_600_000, 0, 4_194_304, 4_194_304),
                ("candidate-input-freeze", 1_800_000, 0, 4_194_304, 4_194_304),
                ("candidate-input-audit", 600_000, 0, 4_194_304, 4_194_304),
                ("pre-freeze-gate-audit", 7_200_000, 0, 4_194_304, 4_194_304),
                ("release-gate-audit", 21_600_000, 0, 4_194_304, 4_194_304),
                ("envelope-audit", 300_000, 0, 4_194_304, 4_194_304),
                ("host-review-audit", 300_000, 0, 4_194_304, 4_194_304),
                ("authorize-provider", 300_000, 0, 4_194_304, 4_194_304),
                (
                    "close-provider-authorization-failure",
                    300_000,
                    0,
                    4_194_304,
                    4_194_304,
                ),
                ("execute", 21_600_000, 0, 4_194_304, 4_194_304),
                ("sealed-campaign-audit", 1_800_000, 0, 4_194_304, 4_194_304),
                ("import-campaign", 3_600_000, 0, 4_194_304, 4_194_304),
                ("adjudicate-campaign", 3_600_000, 0, 4_194_304, 4_194_304),
                ("closure-manifest-audit", 1_800_000, 0, 4_194_304, 4_194_304),
            ),
            (
                b'[{"role":"development-pytest","deadline_ms":900000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"client-preflight-freeze","deadline_ms":1800000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"client-preflight-audit","deadline_ms":600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"guarded-pytest-audit","deadline_ms":3600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"candidate-input-freeze","deadline_ms":1800000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"candidate-input-audit","deadline_ms":600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"pre-freeze-gate-audit","deadline_ms":7200000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"release-gate-audit","deadline_ms":21600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"envelope-audit","deadline_ms":300000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"host-review-audit","deadline_ms":300000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"authorize-provider","deadline_ms":300000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"close-provider-authorization-failure","deadline_ms":300000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"execute","deadline_ms":21600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"sealed-campaign-audit","deadline_ms":1800000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"import-campaign","deadline_ms":3600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"adjudicate-campaign","deadline_ms":3600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"closure-manifest-audit","deadline_ms":1800000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304}]\n'
            ),
            "5ad682096b40c0a64c4792d5e1c17b3e350b0347751838309e1429a4848491c6",
    )
)
_C6_BROKER_NATIVE_CORE_DRAFT_GUARDED_TARGET_PROCESS_LIMIT_TABLE = (
    _C6BrokerNativeCoreDraftLimitTable(
        "guarded-python-target",
            (
                "role",
                "deadline_cap_ms",
                "stdin_cap_bytes",
                "stdout_cap_bytes",
                "stderr_cap_bytes",
            ),
            (
                ("root_role_entrypoint", 21_600_000, 0, 4_194_304, 4_194_304),
                ("pytest_capture", 3_600_000, 0, 4_194_304, 4_194_304),
                ("compile_audit", 900_000, 0, 4_194_304, 4_194_304),
                ("build_frontend", 1_800_000, 0, 4_194_304, 4_194_304),
                ("build_backend_hook", 1_800_000, 0, 4_194_304, 4_194_304),
                ("pip_install", 1_800_000, 0, 4_194_304, 4_194_304),
                ("source_cli", 600_000, 0, 4_194_304, 4_194_304),
                ("installed_cli", 600_000, 0, 4_194_304, 4_194_304),
                ("installed_probe", 300_000, 0, 4_194_304, 4_194_304),
                ("approval_bound_test_probe", 600_000, 0, 4_194_304, 4_194_304),
                ("multiprocessing_worker", 1_800_000, 0, 4_194_304, 4_194_304),
                ("validator_audit", 900_000, 0, 4_194_304, 4_194_304),
            ),
            (
                b'[{"role":"root_role_entrypoint","deadline_cap_ms":21600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"pytest_capture","deadline_cap_ms":3600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"compile_audit","deadline_cap_ms":900000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"build_frontend","deadline_cap_ms":1800000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"build_backend_hook","deadline_cap_ms":1800000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"pip_install","deadline_cap_ms":1800000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"source_cli","deadline_cap_ms":600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"installed_cli","deadline_cap_ms":600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"installed_probe","deadline_cap_ms":300000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"approval_bound_test_probe","deadline_cap_ms":600000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"multiprocessing_worker","deadline_cap_ms":1800000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"validator_audit","deadline_cap_ms":900000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304}]\n'
            ),
            "e60192a674210db309eaa1fb67d48ba27348fca0eb65eb434db56a610d8568e7",
    )
)
_C6_BROKER_NATIVE_CORE_DRAFT_INVOKE_C6_GIT_PROCESS_LIMIT_TABLE = (
    _C6BrokerNativeCoreDraftLimitTable(
        "invoke-c6-git",
            ("role", "deadline_ms", "stdout_cap_bytes", "stderr_cap_bytes"),
            (
                ("read-source-identity", 120_000, 4_194_304, 4_194_304),
                (
                    "read-task15-uncommitted-primary-identity",
                    300_000,
                    4_194_304,
                    4_194_304,
                ),
                ("task09-verify-trust-anchor", 900_000, 4_194_304, 4_194_304),
                ("task10-stage-write-tree-seal", 600_000, 4_194_304, 4_194_304),
                (
                    "task10-verify-provisional-unchanged",
                    600_000,
                    4_194_304,
                    4_194_304,
                ),
                ("task10-commit-provisional", 300_000, 4_194_304, 4_194_304),
                ("task10-materialize-committed", 900_000, 4_194_304, 4_194_304),
                ("task11-stage-write-tree-seal", 600_000, 4_194_304, 4_194_304),
                ("task11-materialize-provisional", 900_000, 4_194_304, 4_194_304),
                (
                    "task11-verify-provisional-unchanged",
                    600_000,
                    4_194_304,
                    4_194_304,
                ),
                ("task11-commit", 300_000, 4_194_304, 4_194_304),
                ("task12-commit-candidate", 300_000, 4_194_304, 4_194_304),
                ("task14-commit-authorization", 300_000, 4_194_304, 4_194_304),
                ("verify-clean-source", 120_000, 4_194_304, 4_194_304),
                ("release-checkout-diff-check", 300_000, 4_194_304, 4_194_304),
                ("task16-stage-closure", 600_000, 4_194_304, 4_194_304),
                ("task16-commit-closure", 300_000, 4_194_304, 4_194_304),
                ("task16-stage-final-docs", 600_000, 4_194_304, 4_194_304),
                ("task16-commit-final-docs", 300_000, 4_194_304, 4_194_304),
            ),
            (
                b'[{"role":"read-source-identity","deadline_ms":120000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"read-task15-uncommitted-primary-identity","deadline_ms":300000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task09-verify-trust-anchor","deadline_ms":900000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task10-stage-write-tree-seal","deadline_ms":600000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task10-verify-provisional-unchanged","deadline_ms":600000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task10-commit-provisional","deadline_ms":300000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task10-materialize-committed","deadline_ms":900000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task11-stage-write-tree-seal","deadline_ms":600000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task11-materialize-provisional","deadline_ms":900000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task11-verify-provisional-unchanged","deadline_ms":600000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task11-commit","deadline_ms":300000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task12-commit-candidate","deadline_ms":300000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task14-commit-authorization","deadline_ms":300000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"verify-clean-source","deadline_ms":120000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"release-checkout-diff-check","deadline_ms":300000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task16-stage-closure","deadline_ms":600000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task16-commit-closure","deadline_ms":300000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task16-stage-final-docs","deadline_ms":600000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"task16-commit-final-docs","deadline_ms":300000,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304}]\n'
            ),
            "efa0f8e58274d800341664793fe6d84bf4407a159edf074c1279eeaeede8dd5f",
    )
)
_C6_BROKER_NATIVE_CORE_DRAFT_NATIVE_LEAF_PROCESS_LIMIT_TABLE = (
    _C6BrokerNativeCoreDraftLimitTable(
        "native-leaf",
            (
                "role",
                "deadline_ms",
                "stdin_cap_bytes",
                "stdout_cap_bytes",
                "stderr_cap_bytes",
            ),
            (
                ("git-read-leaf", 300_000, 0, 4_194_304, 4_194_304),
                ("git-mutation-leaf", 900_000, 0, 4_194_304, 4_194_304),
                ("node", 300_000, 0, 4_194_304, 4_194_304),
                ("powershell_decoder", 30_000, 262_144, 4_194_304, 65_536),
            ),
            (
                b'[{"role":"git-read-leaf","deadline_ms":300000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"git-mutation-leaf","deadline_ms":900000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"node","deadline_ms":300000,"stdin_cap_bytes":0,"stdout_cap_bytes":4194304,"stderr_cap_bytes":4194304},'
                b'{"role":"powershell_decoder","deadline_ms":30000,"stdin_cap_bytes":262144,"stdout_cap_bytes":4194304,"stderr_cap_bytes":65536}]\n'
            ),
            "b2c3b5bb503de8552ff734fbcb41c3b2df0a42d1a7b40a6c08dd0d89faabd04d",
    )
)
_C6_BROKER_NATIVE_CORE_DRAFT_CLIENT_PROCESS_LIMIT_TABLE = (
    _C6BrokerNativeCoreDraftLimitTable(
        "codex-client",
            (
                "role",
                "deadline_ms",
                "stdin_cap_bytes",
                "stdout_cap_bytes",
                "stderr_cap_bytes",
            ),
            (
                ("loopback-client", 300_000, 262_144, 16_777_216, 1_048_576),
                ("approved-client", 2_700_000, 1_048_576, 67_108_864, 4_194_304),
            ),
            (
                b'[{"role":"loopback-client","deadline_ms":300000,"stdin_cap_bytes":262144,"stdout_cap_bytes":16777216,"stderr_cap_bytes":1048576},'
                b'{"role":"approved-client","deadline_ms":2700000,"stdin_cap_bytes":1048576,"stdout_cap_bytes":67108864,"stderr_cap_bytes":4194304}]\n'
            ),
            "938ada50256f26cc34494cc8482de7ff4453d4217b647a33de7dc87f1bdefdf4",
    )
)


def _c6_broker_native_core_draft_validate_utf16_text(value, *, allow_empty):
    if (
        type(value) is not str
        or (not allow_empty and not value)
        or "\x00" in value
        or any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    ):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    return value


def _c6_broker_native_core_draft_render_argument(argument):
    if argument and not any(character in " \t\"" for character in argument):
        return argument

    rendered = ['"']
    pending_backslashes = 0
    for character in argument:
        if character == "\\":
            pending_backslashes += 1
        elif character == '"':
            rendered.append("\\" * (pending_backslashes * 2 + 1))
            rendered.append('"')
            pending_backslashes = 0
        else:
            rendered.append("\\" * pending_backslashes)
            rendered.append(character)
            pending_backslashes = 0
    rendered.append("\\" * (pending_backslashes * 2))
    rendered.append('"')
    return "".join(rendered)


def _c6_broker_native_core_draft_native_vector(executable, arguments):
    executable = _c6_broker_native_core_draft_validate_utf16_text(
        executable,
        allow_empty=False,
    )
    if not os.path.isabs(executable) or os.path.normpath(executable) != executable:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    if type(arguments) is not tuple:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    validated_arguments = tuple(
        _c6_broker_native_core_draft_validate_utf16_text(
            argument,
            allow_empty=True,
        )
        for argument in arguments
    )
    command_line = " ".join(
        _c6_broker_native_core_draft_render_argument(argument)
        for argument in (executable, *validated_arguments)
    )
    encoded = (command_line + "\x00").encode("utf-16-le", errors="strict")
    utf16_units = len(encoded) // 2
    if not 1 <= utf16_units <= _C6_BROKER_NATIVE_CORE_DRAFT_MAX_COMMAND_LINE_UNITS:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    return _C6BrokerNativeCoreDraftNativeVector(
        _C6_BROKER_NATIVE_CORE_DRAFT_VECTOR_CONTRACT,
        utf16_units,
        hashlib.sha256(encoded).hexdigest(),
        command_line,
    )


def _c6_broker_native_core_draft_environment_text(value, *, allow_empty):
    value = _c6_broker_native_core_draft_validate_utf16_text(
        value,
        allow_empty=allow_empty,
    )
    if any(character in value for character in ("\r", "\n")):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    return value


def _c6_broker_native_core_draft_environment_name(name):
    """Validate an exact descriptor name without narrowing Unicode scalars."""

    name = _c6_broker_native_core_draft_environment_text(
        name,
        allow_empty=False,
    )
    if "=" in name:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    return name


def _c6_broker_native_core_draft_simple_ordinal_case_key(name):
    """Return a non-linguistic case key with one scalar per input scalar."""

    mapped = []
    for character in name:
        uppercase = character.upper()
        mapped.append(uppercase if len(uppercase) == 1 else character)
    return "".join(mapped)


def _c6_broker_native_core_draft_utf16_ordinal_name_key(name):
    """Big-endian bytes preserve unsigned UTF-16 code-unit ordinal order."""

    return name.encode("utf-16-be", errors="strict")


def _c6_broker_native_core_draft_environment_block(environment):
    if type(environment) is not tuple:
        _reject(GUARDED_BOOTSTRAP_INVALID)
    pairs = []
    seen_names = set()
    for pair in environment:
        if type(pair) is not tuple or len(pair) != 2:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        name = _c6_broker_native_core_draft_environment_name(pair[0])
        value = _c6_broker_native_core_draft_environment_text(
            pair[1],
            allow_empty=True,
        )
        case_key = _c6_broker_native_core_draft_simple_ordinal_case_key(name)
        if case_key in seen_names:
            _reject(GUARDED_BOOTSTRAP_INVALID)
        seen_names.add(case_key)
        pairs.append((name, value))
    ordered_pairs = tuple(
        sorted(
            pairs,
            key=lambda pair: _c6_broker_native_core_draft_utf16_ordinal_name_key(
                pair[0]
            ),
        )
    )
    block_text = (
        "".join(f"{name}={value}\x00" for name, value in ordered_pairs) + "\x00"
        if ordered_pairs
        else "\x00\x00"
    )
    encoded = block_text.encode("utf-16-le", errors="strict")
    return _C6BrokerNativeCoreDraftEnvironmentBlock(
        ordered_pairs,
        block_text,
        len(encoded) // 2,
        len(encoded),
        hashlib.sha256(encoded).hexdigest(),
    )


def _c6_broker_native_core_draft_project_policy(
    constructor_class,
    subject_kind,
    attributes,
):
    if (
        type(constructor_class) is not str
        or type(subject_kind) is not str
        or type(attributes) is not tuple
        or any(type(attribute) is not str for attribute in attributes)
    ):
        _reject(GUARDED_BOOTSTRAP_INVALID)
    for (
        registered_class,
        registered_subject,
        registered_attributes,
        direct_child_authority,
    ) in _C6_BROKER_NATIVE_CORE_DRAFT_POLICY_ROWS:
        if (
            constructor_class == registered_class
            and subject_kind == registered_subject
            and attributes == registered_attributes
        ):
            return _C6BrokerNativeCoreDraftPolicyProjection(
                _C6_BROKER_NATIVE_CORE_DRAFT_IMPLEMENTATION_ID,
                registered_class,
                registered_subject,
                registered_attributes,
                direct_child_authority,
            )
    _reject(GUARDED_BOOTSTRAP_INVALID)


def _c6_broker_native_core_draft_bind_trusted_registry():
    trusted_invalid = GUARDED_BOOTSTRAP_INVALID
    trusted_runtime_error = RuntimeError
    trusted_type = type
    trusted_str = str
    trusted_tuple_new = tuple.__new__
    trusted_selection_type = _C6BrokerNativeCoreDraftLimitSelection

    trusted_root_table = _C6_BROKER_NATIVE_CORE_DRAFT_ROOT_PROCESS_LIMIT_TABLE
    (
        trusted_root_table_id,
        trusted_root_field_names,
        trusted_root_rows,
        trusted_root_canonical_bytes,
        trusted_root_sha256,
    ) = trusted_root_table
    trusted_target_table = (
        _C6_BROKER_NATIVE_CORE_DRAFT_GUARDED_TARGET_PROCESS_LIMIT_TABLE
    )
    (
        trusted_target_table_id,
        trusted_target_field_names,
        trusted_target_rows,
        trusted_target_canonical_bytes,
        trusted_target_sha256,
    ) = trusted_target_table
    trusted_git_table = (
        _C6_BROKER_NATIVE_CORE_DRAFT_INVOKE_C6_GIT_PROCESS_LIMIT_TABLE
    )
    (
        trusted_git_table_id,
        trusted_git_field_names,
        trusted_git_rows,
        trusted_git_canonical_bytes,
        trusted_git_sha256,
    ) = trusted_git_table
    trusted_leaf_table = (
        _C6_BROKER_NATIVE_CORE_DRAFT_NATIVE_LEAF_PROCESS_LIMIT_TABLE
    )
    (
        trusted_leaf_table_id,
        trusted_leaf_field_names,
        trusted_leaf_rows,
        trusted_leaf_canonical_bytes,
        trusted_leaf_sha256,
    ) = trusted_leaf_table
    trusted_client_table = _C6_BROKER_NATIVE_CORE_DRAFT_CLIENT_PROCESS_LIMIT_TABLE
    (
        trusted_client_table_id,
        trusted_client_field_names,
        trusted_client_rows,
        trusted_client_canonical_bytes,
        trusted_client_sha256,
    ) = trusted_client_table

    def _c6_broker_native_core_draft_root_process_limit(role):
        if (
            _C6_BROKER_NATIVE_CORE_DRAFT_ROOT_PROCESS_LIMIT_TABLE
            is not trusted_root_table
        ):
            raise trusted_runtime_error(trusted_invalid)
        if trusted_type(role) is not trusted_str:
            raise trusted_runtime_error(trusted_invalid)
        for row in trusted_root_rows:
            if row[0] == role:
                return trusted_tuple_new(
                    trusted_selection_type,
                    (
                        trusted_root_table_id,
                        trusted_root_field_names,
                        row,
                        trusted_root_sha256,
                    ),
                )
        raise trusted_runtime_error(trusted_invalid)

    def _c6_broker_native_core_draft_guarded_target_process_limit(role):
        if (
            _C6_BROKER_NATIVE_CORE_DRAFT_GUARDED_TARGET_PROCESS_LIMIT_TABLE
            is not trusted_target_table
        ):
            raise trusted_runtime_error(trusted_invalid)
        if trusted_type(role) is not trusted_str:
            raise trusted_runtime_error(trusted_invalid)
        for row in trusted_target_rows:
            if row[0] == role:
                return trusted_tuple_new(
                    trusted_selection_type,
                    (
                        trusted_target_table_id,
                        trusted_target_field_names,
                        row,
                        trusted_target_sha256,
                    ),
                )
        raise trusted_runtime_error(trusted_invalid)

    def _c6_broker_native_core_draft_invoke_c6_git_process_limit(role):
        if (
            _C6_BROKER_NATIVE_CORE_DRAFT_INVOKE_C6_GIT_PROCESS_LIMIT_TABLE
            is not trusted_git_table
        ):
            raise trusted_runtime_error(trusted_invalid)
        if trusted_type(role) is not trusted_str:
            raise trusted_runtime_error(trusted_invalid)
        for row in trusted_git_rows:
            if row[0] == role:
                return trusted_tuple_new(
                    trusted_selection_type,
                    (
                        trusted_git_table_id,
                        trusted_git_field_names,
                        row,
                        trusted_git_sha256,
                    ),
                )
        raise trusted_runtime_error(trusted_invalid)

    def _c6_broker_native_core_draft_native_leaf_process_limit(role):
        if (
            _C6_BROKER_NATIVE_CORE_DRAFT_NATIVE_LEAF_PROCESS_LIMIT_TABLE
            is not trusted_leaf_table
        ):
            raise trusted_runtime_error(trusted_invalid)
        if trusted_type(role) is not trusted_str:
            raise trusted_runtime_error(trusted_invalid)
        for row in trusted_leaf_rows:
            if row[0] == role:
                return trusted_tuple_new(
                    trusted_selection_type,
                    (
                        trusted_leaf_table_id,
                        trusted_leaf_field_names,
                        row,
                        trusted_leaf_sha256,
                    ),
                )
        raise trusted_runtime_error(trusted_invalid)

    def _c6_broker_native_core_draft_client_process_limit(role):
        if (
            _C6_BROKER_NATIVE_CORE_DRAFT_CLIENT_PROCESS_LIMIT_TABLE
            is not trusted_client_table
        ):
            raise trusted_runtime_error(trusted_invalid)
        if trusted_type(role) is not trusted_str:
            raise trusted_runtime_error(trusted_invalid)
        for row in trusted_client_rows:
            if row[0] == role:
                return trusted_tuple_new(
                    trusted_selection_type,
                    (
                        trusted_client_table_id,
                        trusted_client_field_names,
                        row,
                        trusted_client_sha256,
                    ),
                )
        raise trusted_runtime_error(trusted_invalid)

    return (
        _c6_broker_native_core_draft_root_process_limit,
        _c6_broker_native_core_draft_guarded_target_process_limit,
        _c6_broker_native_core_draft_invoke_c6_git_process_limit,
        _c6_broker_native_core_draft_native_leaf_process_limit,
        _c6_broker_native_core_draft_client_process_limit,
    )


(
    _c6_broker_native_core_draft_root_process_limit,
    _c6_broker_native_core_draft_guarded_target_process_limit,
    _c6_broker_native_core_draft_invoke_c6_git_process_limit,
    _c6_broker_native_core_draft_native_leaf_process_limit,
    _c6_broker_native_core_draft_client_process_limit,
) = _c6_broker_native_core_draft_bind_trusted_registry()
del _c6_broker_native_core_draft_bind_trusted_registry
