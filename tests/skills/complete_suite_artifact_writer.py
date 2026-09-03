import sys
import os


_ARTIFACT_WRITER_EARLY_SYS_PATH = (
    r"C:\Python314\python314.zip",
    r"C:\Python314\DLLs",
    r"C:\Python314\Lib",
    r"C:\Python314",
)
_ARTIFACT_WRITER_EARLY_ENVIRONMENT = {
    "SYSTEMROOT": r"C:\Windows",
    "WINDIR": r"C:\Windows",
}
_ARTIFACT_WRITER_HELPER_SUFFIX = (
    r"\tests\skills\complete_suite_artifact_writer.py"
)


def validate_artifact_writer_early_runtime_contract(
    *,
    os_origin: object,
    executable: object,
    isolated: object,
    no_site: object,
    dont_write_bytecode: object,
    utf8_mode: object,
    sys_path: object,
    argv: object,
    environment: object,
) -> None:
    if (
        os_origin != "frozen"
        or executable != r"C:\Python314\python.exe"
        or type(isolated) is not int
        or isolated != 1
        or type(no_site) is not int
        or no_site != 1
        or type(dont_write_bytecode) is not int
        or dont_write_bytecode != 1
        or type(utf8_mode) is not int
        or utf8_mode != 1
        or type(sys_path) is not tuple
        or sys_path != _ARTIFACT_WRITER_EARLY_SYS_PATH
        or type(argv) is not tuple
        or len(argv) != 3
        or type(environment) is not dict
        or environment != _ARTIFACT_WRITER_EARLY_ENVIRONMENT
    ):
        raise RuntimeError("artifact inner runtime drift")
    helper_path, option, request_sha256 = argv
    if (
        type(helper_path) is not str
        or not helper_path.startswith("D:\\")
        or "/" in helper_path
        or not helper_path.endswith(_ARTIFACT_WRITER_HELPER_SUFFIX)
        or option != "--expected-request-sha256"
        or type(request_sha256) is not str
        or len(request_sha256) != 64
        or any(character not in "0123456789abcdef" for character in request_sha256)
    ):
        raise RuntimeError("artifact inner runtime drift")


def _run_artifact_writer_early_runtime_gate() -> None:
    specification = getattr(os, "__spec__", None)
    validate_artifact_writer_early_runtime_contract(
        os_origin=getattr(specification, "origin", None),
        executable=sys.executable,
        isolated=sys.flags.isolated,
        no_site=sys.flags.no_site,
        dont_write_bytecode=sys.flags.dont_write_bytecode,
        utf8_mode=sys.flags.utf8_mode,
        sys_path=tuple(sys.path),
        argv=tuple(sys.argv),
        environment=dict(os.environ),
    )


_ARTIFACT_WRITER_FROZEN_EXTERNAL = sys.modules["_frozen_importlib_external"]


class _ArtifactWriterSourceOnlyLoader(
    _ARTIFACT_WRITER_FROZEN_EXTERNAL.SourceFileLoader
):
    def get_code(self, fullname: str) -> object:
        source_path = self.get_filename(fullname)
        source_bytes = self.get_data(source_path)
        return self.source_to_code(source_bytes, source_path)


def _configure_artifact_writer_source_only_imports() -> None:
    source_details = (
        _ArtifactWriterSourceOnlyLoader,
        _ARTIFACT_WRITER_FROZEN_EXTERNAL.SOURCE_SUFFIXES,
    )
    extension_details = (
        _ARTIFACT_WRITER_FROZEN_EXTERNAL.ExtensionFileLoader,
        _ARTIFACT_WRITER_FROZEN_EXTERNAL.EXTENSION_SUFFIXES,
    )
    sys.path_hooks[:] = [
        _ARTIFACT_WRITER_FROZEN_EXTERNAL.FileFinder.path_hook(
            source_details,
            extension_details,
        )
    ]
    sys.path_importer_cache.clear()


_ARTIFACT_WRITER_AUDIT_IMPORT_NAMES = frozenset(
    (
        "_blake2",
        "_collections",
        "_contextvars",
        "_ctypes",
        "_functools",
        "_hashlib",
        "_json",
        "_operator",
        "_py_warnings",
        "_sre",
        "_struct",
        "_types",
        "base64",
        "binascii",
        "collections",
        "copyreg",
        "ctypes",
        "ctypes._endian",
        "ctypes._layout",
        "ctypes.wintypes",
        "encodings.utf_16_le",
        "enum",
        "functools",
        "hashlib",
        "itertools",
        "json",
        "json.decoder",
        "json.encoder",
        "json.scanner",
        "keyword",
        "operator",
        "re",
        "re._casefix",
        "re._compiler",
        "re._constants",
        "re._parser",
        "reprlib",
        "struct",
        "types",
        "warnings",
    )
)
_ARTIFACT_WRITER_AUDIT_EXTENSION_IMPORTS = {
    "_ctypes": r"C:\Python314\DLLs\_ctypes.pyd",
    "_hashlib": r"C:\Python314\DLLs\_hashlib.pyd",
}
_ARTIFACT_WRITER_AUDIT_SOURCE_PATHS = frozenset(
    (
        r"C:\Python314\Lib\_py_warnings.py",
        r"C:\Python314\Lib\base64.py",
        r"C:\Python314\Lib\collections\__init__.py",
        r"C:\Python314\Lib\copyreg.py",
        r"C:\Python314\Lib\ctypes\__init__.py",
        r"C:\Python314\Lib\ctypes\_endian.py",
        r"C:\Python314\Lib\ctypes\_layout.py",
        r"C:\Python314\Lib\ctypes\wintypes.py",
        r"C:\Python314\Lib\encodings\utf_16_le.py",
        r"C:\Python314\Lib\enum.py",
        r"C:\Python314\Lib\functools.py",
        r"C:\Python314\Lib\hashlib.py",
        r"C:\Python314\Lib\json\__init__.py",
        r"C:\Python314\Lib\json\decoder.py",
        r"C:\Python314\Lib\json\encoder.py",
        r"C:\Python314\Lib\json\scanner.py",
        r"C:\Python314\Lib\keyword.py",
        r"C:\Python314\Lib\operator.py",
        r"C:\Python314\Lib\re\__init__.py",
        r"C:\Python314\Lib\re\_casefix.py",
        r"C:\Python314\Lib\re\_compiler.py",
        r"C:\Python314\Lib\re\_constants.py",
        r"C:\Python314\Lib\re\_parser.py",
        r"C:\Python314\Lib\reprlib.py",
        r"C:\Python314\Lib\struct.py",
        r"C:\Python314\Lib\types.py",
        r"C:\Python314\Lib\warnings.py",
    )
)
_ARTIFACT_WRITER_AUDIT_DIRECTORY_PATHS = frozenset(
    (
        r"C:\Python314\DLLs",
        r"C:\Python314\Lib",
        r"C:\Python314\Lib\ctypes",
        r"C:\Python314\Lib\encodings",
        r"C:\Python314\Lib\json",
        r"C:\Python314\Lib\re",
    )
)
_ARTIFACT_WRITER_DYNAMIC_COMPILE_SOURCE = (
    b"lambda _cls, hits, misses, maxsize, currsize: "
    b"_tuple_new(_cls, (hits, misses, maxsize, currsize))"
)
_ARTIFACT_WRITER_DYNAMIC_CODE_SHA256 = (
    "c42d2459e408c7ce26d981f4ad0a1b98af7606241fbc87ea7028c1d5f8ebb303"
)
ARTIFACT_WRITER_AUDIT_IMPORT_EVENT_COUNTS = (
    ("import", 42),
    ("os.listdir", 6),
    ("open", 27),
    ("compile", 28),
    ("exec", 28),
    ("ctypes.dlopen", 1),
    ("ctypes.dlsym", 1),
    ("sys._getframemodulename", 1),
    ("object.__setattr__", 1),
)
ARTIFACT_WRITER_NATIVE_SYMBOLS_BY_DLL = (
    (
        r"C:\Windows\System32\kernel32.dll",
        (
            "CloseHandle",
            "CreateFileW",
            "FindClose",
            "FindFirstFileW",
            "FindNextFileW",
            "FlushFileBuffers",
            "GetCommandLineW",
            "GetFileInformationByHandle",
            "GetFileInformationByHandleEx",
            "GetFinalPathNameByHandleW",
            "GetModuleFileNameW",
            "LocalFree",
            "ReadFile",
            "SetFilePointerEx",
            "WriteFile",
        ),
    ),
    (r"C:\Windows\System32\ntdll.dll", ("NtCreateFile",)),
    (r"C:\Windows\System32\shell32.dll", ("CommandLineToArgvW",)),
)
ARTIFACT_WRITER_NATIVE_CALL_ARITIES = (
    ("GetModuleFileNameW", 3),
    ("GetCommandLineW", 0),
    ("CommandLineToArgvW", 2),
    ("LocalFree", 1),
    ("CreateFileW", 7),
    ("NtCreateFile", 11),
    ("GetFileInformationByHandle", 2),
    ("GetFileInformationByHandleEx", 4),
    ("GetFinalPathNameByHandleW", 4),
    ("WriteFile", 5),
    ("FlushFileBuffers", 1),
    ("ReadFile", 5),
    ("SetFilePointerEx", 4),
    ("FindFirstFileW", 2),
    ("FindNextFileW", 2),
    ("FindClose", 1),
    ("CloseHandle", 1),
    ("ctypes._cast", 3),
)
ARTIFACT_WRITER_AUDIT_NATIVE_EVENTS = (
    ("ctypes.dlopen", r"C:\Windows\System32\kernel32.dll", None),
    ("ctypes.dlopen", r"C:\Windows\System32\ntdll.dll", None),
    ("ctypes.dlopen", r"C:\Windows\System32\shell32.dll", None),
    ("ctypes.dlsym", r"C:\Windows\System32\kernel32.dll", "GetModuleFileNameW"),
    ("ctypes.dlsym", r"C:\Windows\System32\kernel32.dll", "GetCommandLineW"),
    ("ctypes.dlsym", r"C:\Windows\System32\shell32.dll", "CommandLineToArgvW"),
    ("ctypes.dlsym", r"C:\Windows\System32\kernel32.dll", "LocalFree"),
    ("ctypes.dlsym", r"C:\Windows\System32\kernel32.dll", "CreateFileW"),
    ("ctypes.dlsym", r"C:\Windows\System32\ntdll.dll", "NtCreateFile"),
    (
        "ctypes.dlsym",
        r"C:\Windows\System32\kernel32.dll",
        "GetFileInformationByHandle",
    ),
    (
        "ctypes.dlsym",
        r"C:\Windows\System32\kernel32.dll",
        "GetFileInformationByHandleEx",
    ),
    (
        "ctypes.dlsym",
        r"C:\Windows\System32\kernel32.dll",
        "GetFinalPathNameByHandleW",
    ),
    ("ctypes.dlsym", r"C:\Windows\System32\kernel32.dll", "WriteFile"),
    (
        "ctypes.dlsym",
        r"C:\Windows\System32\kernel32.dll",
        "FlushFileBuffers",
    ),
    ("ctypes.dlsym", r"C:\Windows\System32\kernel32.dll", "ReadFile"),
    (
        "ctypes.dlsym",
        r"C:\Windows\System32\kernel32.dll",
        "SetFilePointerEx",
    ),
    ("ctypes.dlsym", r"C:\Windows\System32\kernel32.dll", "FindFirstFileW"),
    ("ctypes.dlsym", r"C:\Windows\System32\kernel32.dll", "FindNextFileW"),
    ("ctypes.dlsym", r"C:\Windows\System32\kernel32.dll", "FindClose"),
    ("ctypes.dlsym", r"C:\Windows\System32\kernel32.dll", "CloseHandle"),
)
_ARTIFACT_WRITER_AUDIT_PHASE = "inactive"
_ARTIFACT_WRITER_AUDIT_COUNTS = {
    event: 0 for event, _count in ARTIFACT_WRITER_AUDIT_IMPORT_EVENT_COUNTS
}
_ARTIFACT_WRITER_AUDIT_NATIVE_OBSERVED: list[tuple[str, object, object]] = []
_ARTIFACT_WRITER_AUDIT_PUBLICATION_CALL_ARITIES: tuple[tuple[int, int], ...] = ()


def _artifact_writer_constant_shape(value: object) -> tuple[object, ...]:
    if type(value) is _ARTIFACT_WRITER_CODE_TYPE:
        return ("code", _artifact_writer_code_shape(value))
    if value is None:
        return ("none",)
    if type(value) in {bool, int, float, complex, str, bytes}:
        return (type(value).__name__, value)
    if type(value) is tuple:
        return (
            "tuple",
            tuple(_artifact_writer_constant_shape(item) for item in value),
        )
    return ("unsupported", type(value).__name__)


def _artifact_writer_code_shape(code: object) -> tuple[object, ...]:
    return (
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code.hex(),
        tuple(
            _artifact_writer_constant_shape(value)
            for value in code.co_consts
        ),
        code.co_names,
        code.co_varnames,
        code.co_filename,
        code.co_name,
        code.co_qualname,
        code.co_firstlineno,
        code.co_linetable.hex(),
        code.co_exceptiontable.hex(),
        code.co_freevars,
        code.co_cellvars,
    )


_ARTIFACT_WRITER_CODE_TYPE = type(
    validate_artifact_writer_early_runtime_contract.__code__
)


def _artifact_writer_code_sha256(code: object) -> str:
    if type(code) is not _ARTIFACT_WRITER_CODE_TYPE:
        _artifact_writer_audit_reject()
    return sha256(
        repr(_artifact_writer_code_shape(code)).encode("utf-8", errors="strict")
    ).hexdigest()


def _artifact_writer_audit_reject() -> None:
    raise RuntimeError("artifact audit policy violation")


def _artifact_writer_audit_library_name(library: object) -> object:
    try:
        return object.__getattribute__(library, "_name")
    except (AttributeError, TypeError):
        return None


def _validate_artifact_writer_call_arities(value: object) -> None:
    if type(value) is not tuple or not value:
        _artifact_writer_audit_reject()
    seen: set[int] = set()
    for entry in value:
        if type(entry) is not tuple or len(entry) != 2:
            _artifact_writer_audit_reject()
        address, arity = entry
        if (
            type(address) is not int
            or address <= 0
            or type(arity) is not int
            or not 0 <= arity <= 11
            or address in seen
        ):
            _artifact_writer_audit_reject()
        seen.add(address)


def validate_artifact_writer_publication_audit_event(
    *,
    event: object,
    arguments: object,
    authorized_call_arities: object,
) -> None:
    if type(event) is not str or type(arguments) is not tuple:
        _artifact_writer_audit_reject()
    _validate_artifact_writer_call_arities(authorized_call_arities)

    if event == "ctypes.create_unicode_buffer":
        if len(arguments) != 2:
            _artifact_writer_audit_reject()
        initial, size = arguments
        if type(size) is not int or not 1 <= size <= 32_768:
            _artifact_writer_audit_reject()
        if initial is None:
            return
        if (
            type(initial) is not str
            or not initial
            or not initial.isascii()
            or "\x00" in initial
            or len(initial) + 1 != size
        ):
            _artifact_writer_audit_reject()
        return

    if event == "ctypes.call_function":
        if (
            len(arguments) != 2
            or type(arguments[0]) is not int
            or type(arguments[1]) is not tuple
        ):
            _artifact_writer_audit_reject()
        expected_arity = dict(authorized_call_arities).get(arguments[0])
        if expected_arity is None or len(arguments[1]) != expected_arity:
            _artifact_writer_audit_reject()
        return

    if event == "ctypes.get_last_error":
        if arguments:
            _artifact_writer_audit_reject()
        return

    if event == "ctypes.cdata/buffer":
        if (
            len(arguments) != 3
            or type(arguments[0]) is not int
            or arguments[0] <= 0
            or type(arguments[1]) is not int
            or not 1 <= arguments[1] <= 262_144
            or type(arguments[2]) is not int
            or arguments[2] != 0
        ):
            _artifact_writer_audit_reject()
        return

    if event == "ctypes.addressof":
        if len(arguments) != 1:
            _artifact_writer_audit_reject()
        value = arguments[0]
        value_type = type(value)
        if (
            not isinstance(value, ctypes.Array)
            or value_type.__bases__ != (ctypes.Array,)
            or value_type._type_ is not ctypes.c_ubyte
            or type(value_type._length_) is not int
            or not 1 <= value_type._length_ <= 262_144
            or len(value) != value_type._length_
        ):
            _artifact_writer_audit_reject()
        return

    _artifact_writer_audit_reject()


def validate_artifact_writer_audit_event(
    *,
    event: object,
    arguments: object,
    phase: object,
) -> None:
    if (
        type(event) is not str
        or type(arguments) is not tuple
        or phase not in {"imports", "native", "publication", "sealed"}
    ):
        _artifact_writer_audit_reject()

    if phase == "imports":
        if event == "import":
            if len(arguments) != 5:
                _artifact_writer_audit_reject()
            name, filename, paths, meta_path, path_hooks = arguments
            if type(name) is not str or name not in _ARTIFACT_WRITER_AUDIT_IMPORT_NAMES:
                _artifact_writer_audit_reject()
            if filename is None:
                if (
                    type(paths) is not list
                    or tuple(paths) != _ARTIFACT_WRITER_EARLY_SYS_PATH
                    or type(meta_path) is not list
                    or type(path_hooks) is not list
                ):
                    _artifact_writer_audit_reject()
                return
            if (
                _ARTIFACT_WRITER_AUDIT_EXTENSION_IMPORTS.get(name) != filename
                or arguments[2:] != (None, None, None)
            ):
                _artifact_writer_audit_reject()
            return
        if event == "open":
            if (
                len(arguments) != 3
                or arguments[0] not in _ARTIFACT_WRITER_AUDIT_SOURCE_PATHS
                or arguments[1:] != ("r", 32896)
            ):
                _artifact_writer_audit_reject()
            return
        if event == "compile":
            if len(arguments) != 2:
                _artifact_writer_audit_reject()
            source, filename = arguments
            if filename in _ARTIFACT_WRITER_AUDIT_SOURCE_PATHS:
                if type(source) is not bytes or not source:
                    _artifact_writer_audit_reject()
                return
            if (
                filename == "<string>"
                and type(source) is bytes
                and source == _ARTIFACT_WRITER_DYNAMIC_COMPILE_SOURCE
            ):
                return
            _artifact_writer_audit_reject()
        if event == "exec":
            if len(arguments) != 1:
                _artifact_writer_audit_reject()
            code = arguments[0]
            if type(code) is not _ARTIFACT_WRITER_CODE_TYPE:
                _artifact_writer_audit_reject()
            filename = code.co_filename
            code_name = code.co_name
            if filename == "<string>":
                if (
                    code_name != "<module>"
                    or _artifact_writer_code_sha256(code)
                    != _ARTIFACT_WRITER_DYNAMIC_CODE_SHA256
                ):
                    _artifact_writer_audit_reject()
                return
            if (
                code_name != "<module>"
                or filename not in _ARTIFACT_WRITER_AUDIT_SOURCE_PATHS
            ):
                _artifact_writer_audit_reject()
            return
        if event == "os.listdir":
            if len(arguments) != 1 or arguments[0] not in (
                _ARTIFACT_WRITER_AUDIT_DIRECTORY_PATHS
            ):
                _artifact_writer_audit_reject()
            return
        if event == "ctypes.dlopen":
            if arguments != ("kernel32",):
                _artifact_writer_audit_reject()
            return
        if event == "ctypes.dlsym":
            if (
                len(arguments) != 2
                or _artifact_writer_audit_library_name(arguments[0]) != "kernel32"
                or arguments[1] != "GetLastError"
            ):
                _artifact_writer_audit_reject()
            return
        if event == "sys._getframemodulename":
            if len(arguments) != 1 or type(arguments[0]) is not int:
                _artifact_writer_audit_reject()
            return
        if event == "object.__setattr__":
            if len(arguments) != 3 or type(arguments[1]) is not str:
                _artifact_writer_audit_reject()
            return
        _artifact_writer_audit_reject()

    if phase == "native":
        if event == "ctypes.dlopen":
            if (
                len(arguments) != 1
                or not any(
                    arguments[0] == path
                    for path, _symbols in ARTIFACT_WRITER_NATIVE_SYMBOLS_BY_DLL
                )
            ):
                _artifact_writer_audit_reject()
            return
        if event == "ctypes.dlsym":
            if len(arguments) != 2 or type(arguments[1]) is not str:
                _artifact_writer_audit_reject()
            library_name = _artifact_writer_audit_library_name(arguments[0])
            if not any(
                library_name == path and arguments[1] in symbols
                for path, symbols in ARTIFACT_WRITER_NATIVE_SYMBOLS_BY_DLL
            ):
                _artifact_writer_audit_reject()
            return
        _artifact_writer_audit_reject()

    if phase == "publication":
        validate_artifact_writer_publication_audit_event(
            event=event,
            arguments=arguments,
            authorized_call_arities=(
                _ARTIFACT_WRITER_AUDIT_PUBLICATION_CALL_ARITIES
            ),
        )
        return

    _artifact_writer_audit_reject()


def validate_artifact_writer_audit_import_counts(counts: object) -> None:
    expected = dict(ARTIFACT_WRITER_AUDIT_IMPORT_EVENT_COUNTS)
    if (
        type(counts) is not dict
        or tuple(counts) != tuple(expected)
        or any(type(value) is not int for value in counts.values())
        or counts != expected
    ):
        _artifact_writer_audit_reject()


def validate_artifact_writer_audit_native_trace(trace: object) -> None:
    if type(trace) is not tuple or trace != ARTIFACT_WRITER_AUDIT_NATIVE_EVENTS:
        _artifact_writer_audit_reject()


def _artifact_writer_native_call_address(function: object) -> int:
    if not isinstance(function, ctypes._CFuncPtr):
        _artifact_writer_audit_reject()
    encoded = bytes(function)
    if type(encoded) is not bytes or len(encoded) != 8:
        _artifact_writer_audit_reject()
    address = int.from_bytes(encoded, "little", signed=False)
    if address <= 0:
        _artifact_writer_audit_reject()
    return address


def _register_artifact_writer_publication_call_arities(functions: object) -> None:
    global _ARTIFACT_WRITER_AUDIT_PUBLICATION_CALL_ARITIES
    if (
        _ARTIFACT_WRITER_AUDIT_PHASE != "native"
        or _ARTIFACT_WRITER_AUDIT_PUBLICATION_CALL_ARITIES
        or type(functions) is not tuple
        or len(functions) != len(ARTIFACT_WRITER_NATIVE_CALL_ARITIES)
    ):
        _artifact_writer_audit_reject()
    registered: list[tuple[int, int]] = []
    for expected, entry in zip(ARTIFACT_WRITER_NATIVE_CALL_ARITIES, functions):
        if (
            type(entry) is not tuple
            or len(entry) != 2
            or entry[0] != expected[0]
        ):
            _artifact_writer_audit_reject()
        registered.append(
            (_artifact_writer_native_call_address(entry[1]), expected[1])
        )
    result = tuple(registered)
    _validate_artifact_writer_call_arities(result)
    _ARTIFACT_WRITER_AUDIT_PUBLICATION_CALL_ARITIES = result


def _artifact_writer_audit_hook(
    event: str,
    arguments: tuple[object, ...],
) -> None:
    validate_artifact_writer_audit_event(
        event=event,
        arguments=arguments,
        phase=_ARTIFACT_WRITER_AUDIT_PHASE,
    )
    if _ARTIFACT_WRITER_AUDIT_PHASE == "imports":
        current = _ARTIFACT_WRITER_AUDIT_COUNTS.get(event)
        expected = dict(ARTIFACT_WRITER_AUDIT_IMPORT_EVENT_COUNTS).get(event)
        if current is None or expected is None or current >= expected:
            _artifact_writer_audit_reject()
        _ARTIFACT_WRITER_AUDIT_COUNTS[event] = current + 1
    elif _ARTIFACT_WRITER_AUDIT_PHASE == "native":
        if event == "ctypes.dlopen":
            observed = (event, arguments[0], None)
        else:
            observed = (
                event,
                _artifact_writer_audit_library_name(arguments[0]),
                arguments[1],
            )
        index = len(_ARTIFACT_WRITER_AUDIT_NATIVE_OBSERVED)
        if (
            index >= len(ARTIFACT_WRITER_AUDIT_NATIVE_EVENTS)
            or observed != ARTIFACT_WRITER_AUDIT_NATIVE_EVENTS[index]
        ):
            _artifact_writer_audit_reject()
        _ARTIFACT_WRITER_AUDIT_NATIVE_OBSERVED.append(observed)


def _seal_artifact_writer_import_audit() -> None:
    global _ARTIFACT_WRITER_AUDIT_PHASE
    if (
        _ARTIFACT_WRITER_AUDIT_PHASE != "imports"
        or tuple(sys.path) != _ARTIFACT_WRITER_EARLY_SYS_PATH
        or len(sys.path_hooks) != 1
    ):
        _artifact_writer_audit_reject()
    validate_artifact_writer_audit_import_counts(_ARTIFACT_WRITER_AUDIT_COUNTS)
    _ARTIFACT_WRITER_AUDIT_PHASE = "native"


def _seal_artifact_writer_native_audit() -> None:
    global _ARTIFACT_WRITER_AUDIT_PHASE
    if _ARTIFACT_WRITER_AUDIT_PHASE != "native":
        _artifact_writer_audit_reject()
    validate_artifact_writer_audit_native_trace(
        tuple(_ARTIFACT_WRITER_AUDIT_NATIVE_OBSERVED)
    )
    if len(_ARTIFACT_WRITER_AUDIT_PUBLICATION_CALL_ARITIES) != len(
        ARTIFACT_WRITER_NATIVE_CALL_ARITIES
    ):
        _artifact_writer_audit_reject()
    _ARTIFACT_WRITER_AUDIT_PHASE = "publication"


if __name__ == "__main__":
    _run_artifact_writer_early_runtime_gate()
    _configure_artifact_writer_source_only_imports()
    _ARTIFACT_WRITER_AUDIT_PHASE = "imports"
    sys.addaudithook(_artifact_writer_audit_hook)


import base64
import ctypes
from ctypes import wintypes
import encodings.utf_16_le
from hashlib import sha256
import json
import re


ARTIFACT_WRITER_REQUEST_KEYS = (
    "schema_version",
    "mode",
    "root",
    "leaf",
    "content_base64",
    "expected_content_sha256",
)
ARTIFACT_WRITER_MODES = (
    "operator-prompt",
    "operator-attestation",
    "host-review-envelope",
    "host-review-result",
)
ARTIFACT_WRITER_ALLOWED_IMPORTS = (
    "base64",
    "ctypes",
    "encodings",
    "hashlib",
    "json",
    "os",
    "re",
    "sys",
)
ARTIFACT_WRITER_LOADED_MODULE_ORIGINS = (
    ("sys", "built-in", None),
    ("builtins", "built-in", None),
    ("_frozen_importlib", "frozen", None),
    ("_imp", "built-in", None),
    ("_thread", "built-in", None),
    ("_warnings", "built-in", None),
    ("_weakref", "built-in", None),
    ("winreg", "built-in", None),
    ("_io", "built-in", None),
    ("marshal", "built-in", None),
    ("nt", "built-in", None),
    ("_frozen_importlib_external", "frozen", "C:\\Python314\\Lib\\importlib\\_bootstrap_external.py"),
    ("time", "built-in", None),
    ("zipimport", "frozen", "C:\\Python314\\Lib\\zipimport.py"),
    ("_codecs", "built-in", None),
    ("codecs", "frozen", "C:\\Python314\\Lib\\codecs.py"),
    ("encodings.aliases", "C:\\Python314\\Lib\\encodings\\aliases.py", "C:\\Python314\\Lib\\encodings\\aliases.py"),
    ("encodings._win_cp_codecs", "C:\\Python314\\Lib\\encodings\\_win_cp_codecs.py", "C:\\Python314\\Lib\\encodings\\_win_cp_codecs.py"),
    ("encodings", "C:\\Python314\\Lib\\encodings\\__init__.py", "C:\\Python314\\Lib\\encodings\\__init__.py"),
    ("encodings.utf_8", "C:\\Python314\\Lib\\encodings\\utf_8.py", "C:\\Python314\\Lib\\encodings\\utf_8.py"),
    ("_signal", "built-in", None),
    ("__main__", None, "$HELPER"),
    ("_abc", "built-in", None),
    ("abc", "frozen", "C:\\Python314\\Lib\\abc.py"),
    ("_stat", "built-in", None),
    ("stat", "frozen", "C:\\Python314\\Lib\\stat.py"),
    ("_collections_abc", "frozen", "C:\\Python314\\Lib\\_collections_abc.py"),
    ("genericpath", "frozen", "C:\\Python314\\Lib\\genericpath.py"),
    ("_winapi", "built-in", None),
    ("ntpath", "frozen", "C:\\Python314\\Lib\\ntpath.py"),
    ("os.path", "frozen", "C:\\Python314\\Lib\\ntpath.py"),
    ("os", "frozen", "C:\\Python314\\Lib\\os.py"),
    ("_struct", "built-in", None),
    ("struct", "C:\\Python314\\Lib\\struct.py", "C:\\Python314\\Lib\\struct.py"),
    ("binascii", "built-in", None),
    ("base64", "C:\\Python314\\Lib\\base64.py", "C:\\Python314\\Lib\\base64.py"),
    ("_types", "built-in", None),
    ("types", "C:\\Python314\\Lib\\types.py", "C:\\Python314\\Lib\\types.py"),
    ("_ctypes", "C:\\Python314\\DLLs\\_ctypes.pyd", "C:\\Python314\\DLLs\\_ctypes.pyd"),
    ("ctypes._endian", "C:\\Python314\\Lib\\ctypes\\_endian.py", "C:\\Python314\\Lib\\ctypes\\_endian.py"),
    ("ctypes", "C:\\Python314\\Lib\\ctypes\\__init__.py", "C:\\Python314\\Lib\\ctypes\\__init__.py"),
    ("_contextvars", "built-in", None),
    ("_py_warnings", "C:\\Python314\\Lib\\_py_warnings.py", "C:\\Python314\\Lib\\_py_warnings.py"),
    ("warnings", "C:\\Python314\\Lib\\warnings.py", "C:\\Python314\\Lib\\warnings.py"),
    ("ctypes._layout", "C:\\Python314\\Lib\\ctypes\\_layout.py", "C:\\Python314\\Lib\\ctypes\\_layout.py"),
    ("ctypes.wintypes", "C:\\Python314\\Lib\\ctypes\\wintypes.py", "C:\\Python314\\Lib\\ctypes\\wintypes.py"),
    ("encodings.utf_16_le", "C:\\Python314\\Lib\\encodings\\utf_16_le.py", "C:\\Python314\\Lib\\encodings\\utf_16_le.py"),
    ("_hashlib", "C:\\Python314\\DLLs\\_hashlib.pyd", "C:\\Python314\\DLLs\\_hashlib.pyd"),
    ("_blake2", "built-in", None),
    ("hashlib", "C:\\Python314\\Lib\\hashlib.py", "C:\\Python314\\Lib\\hashlib.py"),
    ("enum", "C:\\Python314\\Lib\\enum.py", "C:\\Python314\\Lib\\enum.py"),
    ("_sre", "built-in", None),
    ("re._constants", "C:\\Python314\\Lib\\re\\_constants.py", "C:\\Python314\\Lib\\re\\_constants.py"),
    ("re._parser", "C:\\Python314\\Lib\\re\\_parser.py", "C:\\Python314\\Lib\\re\\_parser.py"),
    ("re._casefix", "C:\\Python314\\Lib\\re\\_casefix.py", "C:\\Python314\\Lib\\re\\_casefix.py"),
    ("re._compiler", "C:\\Python314\\Lib\\re\\_compiler.py", "C:\\Python314\\Lib\\re\\_compiler.py"),
    ("collections.abc", "frozen", "C:\\Python314\\Lib\\_collections_abc.py"),
    ("itertools", "built-in", None),
    ("keyword", "C:\\Python314\\Lib\\keyword.py", "C:\\Python314\\Lib\\keyword.py"),
    ("_operator", "built-in", None),
    ("operator", "C:\\Python314\\Lib\\operator.py", "C:\\Python314\\Lib\\operator.py"),
    ("reprlib", "C:\\Python314\\Lib\\reprlib.py", "C:\\Python314\\Lib\\reprlib.py"),
    ("_collections", "built-in", None),
    ("collections", "C:\\Python314\\Lib\\collections\\__init__.py", "C:\\Python314\\Lib\\collections\\__init__.py"),
    ("_functools", "built-in", None),
    ("functools", "C:\\Python314\\Lib\\functools.py", "C:\\Python314\\Lib\\functools.py"),
    ("copyreg", "C:\\Python314\\Lib\\copyreg.py", "C:\\Python314\\Lib\\copyreg.py"),
    ("re", "C:\\Python314\\Lib\\re\\__init__.py", "C:\\Python314\\Lib\\re\\__init__.py"),
    ("_json", "built-in", None),
    ("json.scanner", "C:\\Python314\\Lib\\json\\scanner.py", "C:\\Python314\\Lib\\json\\scanner.py"),
    ("json.decoder", "C:\\Python314\\Lib\\json\\decoder.py", "C:\\Python314\\Lib\\json\\decoder.py"),
    ("json.encoder", "C:\\Python314\\Lib\\json\\encoder.py", "C:\\Python314\\Lib\\json\\encoder.py"),
    ("json", "C:\\Python314\\Lib\\json\\__init__.py", "C:\\Python314\\Lib\\json\\__init__.py"),
)
ARTIFACT_WRITER_NATIVE_API_NAMES = (
    "CloseHandle",
    "CommandLineToArgvW",
    "CreateFileW",
    "FindClose",
    "FindFirstFileW",
    "FindNextFileW",
    "FlushFileBuffers",
    "GetCommandLineW",
    "GetFileInformationByHandle",
    "GetFileInformationByHandleEx",
    "GetFinalPathNameByHandleW",
    "GetModuleFileNameW",
    "LocalFree",
    "NtCreateFile",
    "ReadFile",
    "SetFilePointerEx",
    "WriteFile",
)
ARTIFACT_WRITER_NATIVE_CONSTANTS = {
    "FILE_ATTRIBUTE_DIRECTORY": 0x00000010,
    "FILE_ATTRIBUTE_REPARSE_POINT": 0x00000400,
    "FILE_ATTRIBUTE_TAG_INFO": 9,
    "FILE_CREATE": 2,
    "FILE_DIRECTORY_FILE": 0x00000001,
    "FILE_FLAG_BACKUP_SEMANTICS": 0x02000000,
    "FILE_FLAG_OPEN_REPARSE_POINT": 0x00200000,
    "FILE_LIST_DIRECTORY": 0x00000001,
    "FILE_NON_DIRECTORY_FILE": 0x00000040,
    "FILE_OPEN": 1,
    "FILE_OPEN_FOR_BACKUP_INTENT": 0x00004000,
    "FILE_OPEN_REPARSE_POINT": 0x00200000,
    "FILE_READ_ATTRIBUTES": 0x00000080,
    "FILE_READ_DATA": 0x00000001,
    "FILE_SHARE_READ": 0x00000001,
    "FILE_SYNCHRONOUS_IO_NONALERT": 0x00000020,
    "FILE_TRAVERSE": 0x00000020,
    "FILE_WRITE_DATA": 0x00000002,
    "OBJ_DONT_REPARSE": 0x00001000,
    "OPEN_EXISTING": 3,
    "SYNCHRONIZE": 0x00100000,
}
ARTIFACT_WRITER_OUTER_ENVIRONMENT_MARKER = (
    b'{"policy_revision":"complete-suite-artifact-outer-environment-name-drift-v1",'
    b'"present_name_count":0}'
)
ARTIFACT_WRITER_OUTER_ENVIRONMENT_MARKER_SHA256 = (
    "d298e1ff2f169cdd2e7234aef1184c0a090c70d60e784f8cd79c2edce60b892b"
)
ARTIFACT_WRITER_CHILD_ENVIRONMENT_ITEMS = (
    ("SYSTEMROOT", r"C:\Windows"),
    ("WINDIR", r"C:\Windows"),
)

_REQUEST_SCHEMA = "complete-suite-artifact-writer-request-v1"
_REQUEST_MAX_BYTES = 524_288
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_OUTER_RUNTIME_NAME_PREFIXES = ("DOTNET_", "CORECLR_", "COR_", "COMPLUS_")
_OPERATOR_ROOT_PATTERN = re.compile(
    r"D:\\tmp\\kokoroarc-c6-(provider-approval|import-authorization)-([0-9a-f]{32})",
    flags=re.ASCII,
)
_HOST_REVIEW_ROOT_PATTERN = re.compile(
    r"D:\\tmp\\kokoroarc-c6-host-review-"
    r"(candidate|closure|final-docs)-"
    r"(specification|quality-security)-([0-9a-f]{32})",
    flags=re.ASCII,
)
_CONTENT_LIMITS = {
    "operator-prompt": (1, 65_536),
    "operator-attestation": (1, 65_536),
    "host-review-envelope": (2, 131_072),
    "host-review-result": (2, 262_144),
}
_HEX40_PATTERN = re.compile(r"[0-9a-f]{40}", flags=re.ASCII)
_HOST_REVIEW_TARGET_BASE = "30beb3832d18f6d0011bb4f8af96b7cdda9222f6"
_HOST_REVIEW_ENVELOPE_KEYS = (
    "schema_version",
    "envelope_id",
    "phase",
    "review_type",
    "reviewer_task_name",
    "purpose",
    "target_head",
    "target_tree",
    "target_parent",
    "target_base",
    "design_sha256",
    "plan_sha256",
    "campaign_sha256",
    "subject_records",
    "subject_equivalence_sha256",
    "authorized_input_projection_entry_count",
    "authorized_input_projection_sha256",
    "host_review_input_bundle_entry_count",
    "host_review_input_bundle_decoded_bytes",
    "host_review_input_bundle_aggregate_sha256",
    "predecessor_review_result_sha256s",
    "phase_model_call_ordinal",
    "host_collaboration_model_call",
    "host_model_transport",
    "local_windows_processes_allowed",
    "local_windows_codex_client_processes_allowed",
    "local_provider_processes_allowed",
    "local_socket_network_calls_allowed",
    "network_access_allowed",
    "credential_access_allowed",
    "filesystem_read_authority",
    "unlisted_filesystem_access_allowed",
    "filesystem_writes_allowed",
    "git_mutations_allowed",
    "test_execution_allowed",
    "tool_execution_allowed",
    "child_agent_spawns_allowed",
    "result_transport",
    "deadline_ms",
    "deadline_clock",
    "deadline_expiry_action",
    "result_cap_bytes",
    "cybersecurity_checks_may_be_bypassed",
)
_HOST_REVIEW_RESULT_KEYS = (
    "schema_version",
    "capture_method",
    "evaluation_envelope_sha256",
    "phase",
    "review_type",
    "reviewer_task_name",
    "verdict",
    "target_head",
    "target_tree",
    "target_parent",
    "target_base",
    "design_sha256",
    "plan_sha256",
    "campaign_sha256",
    "subject_records",
    "subject_equivalence_sha256",
    "authorized_input_projection_entry_count",
    "authorized_input_projection_sha256",
    "host_review_input_bundle_entry_count",
    "host_review_input_bundle_decoded_bytes",
    "host_review_input_bundle_aggregate_sha256",
    "predecessor_review_result_sha256s",
    "phase_model_call_ordinal",
    "deadline_ms",
    "deadline_clock",
    "deadline_expiry_action",
    "critical_findings",
    "important_findings",
)
_HOST_REVIEW_SUBJECT_KEYS = ("role", "path", "identity", "size", "sha256")
_HOST_REVIEW_IDENTITY_KEYS = (
    "device",
    "inode",
    "file_type",
    "reparse_tag",
    "link_count",
)
_HOST_REVIEW_FINDING_KEYS = (
    "severity",
    "line_start",
    "line_end",
    "quoted_text",
    "why_blocking",
    "minimal_correction",
)
_HOST_REVIEW_TASKS = {
    ("candidate", "specification"): "c6_candidate_specification_review",
    ("candidate", "quality_security"): "c6_candidate_quality_security_review",
    ("closure", "specification"): "c6_closure_specification_review",
    ("closure", "quality_security"): "c6_closure_quality_security_review",
    ("final-docs", "specification"): "c6_final_docs_specification_review",
    ("final-docs", "quality_security"): "c6_final_docs_quality_security_review",
}
_HOST_REVIEW_RESULT_SCHEMAS = {
    "candidate": "complete-suite-candidate-review-v2",
    "closure": "complete-suite-closure-review-v1",
    "final-docs": "complete-suite-final-docs-review-v1",
}
_HOST_REVIEW_SUBJECT_ROWS = {
    "candidate": (
        (
            "pre-freeze-gate",
            re.compile(
                r"D:\\tmp\\kokoroarc-c6-task12-prefreeze-[0-9a-f]{32}\.json",
                flags=re.ASCII,
            ),
        ),
        (
            "candidate-input-aggregate",
            re.compile(
                r"D:\\tmp\\kokoroarc-c6-task12-inputs-[0-9a-f]{32}\.json",
                flags=re.ASCII,
            ),
        ),
        (
            "candidate-review-input-bundle",
            re.compile(
                r"D:\\tmp\\kokoroarc-c6-task12-prefreeze-[0-9a-f]{32}"
                r"\\host-review-input-bundle\.json",
                flags=re.ASCII,
            ),
        ),
    ),
    "closure": (
        (
            "closure-committed-release",
            re.compile(
                r"D:\\tmp\\kokoroarc-c6-task16-committed-[0-9a-f]{32}\.json",
                flags=re.ASCII,
            ),
        ),
        (
            "closure-review-input-bundle",
            re.compile(
                r"D:\\tmp\\kokoroarc-c6-task16-committed-[0-9a-f]{32}"
                r"\\host-review-input-bundle\.json",
                flags=re.ASCII,
            ),
        ),
    ),
    "final-docs": (
        (
            "final-docs-release",
            re.compile(
                r"D:\\tmp\\kokoroarc-c6-task16-final-docs-[0-9a-f]{32}\.json",
                flags=re.ASCII,
            ),
        ),
        (
            "final-cumulative-manifest",
            re.compile(
                r"D:\\tmp\\kokoroarc-c6-task16-final-docs-worktree-"
                r"[0-9a-f]{32}\\cumulative-release-scope\.json",
                flags=re.ASCII,
            ),
        ),
        (
            "closure-reviewed-release",
            re.compile(
                r"D:\\tmp\\kokoroarc-c6-task16-reviewed-[0-9a-f]{32}\.json",
                flags=re.ASCII,
            ),
        ),
        (
            "final-docs-review-input-bundle",
            re.compile(
                r"D:\\tmp\\kokoroarc-c6-task16-final-docs-[0-9a-f]{32}"
                r"\\host-review-input-bundle\.json",
                flags=re.ASCII,
            ),
        ),
    ),
}


ArtifactWriterMode = str


class _ArtifactWriterFrozenRecord:
    __slots__ = ()
    _record_fields: tuple[str, ...] = ()
    _repr_omitted_fields: frozenset[str] = frozenset()

    def _initialize_record(self, values: tuple[object, ...]) -> None:
        if len(values) != len(self._record_fields):
            raise TypeError("artifact record field-count drift")
        for name, value in zip(self._record_fields, values):
            object.__setattr__(self, name, value)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("immutable artifact record")

    def __delattr__(self, _name: str) -> None:
        raise AttributeError("immutable artifact record")

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return False
        return all(
            getattr(self, name) == getattr(other, name)
            for name in self._record_fields
        )

    def __hash__(self) -> int:
        return hash(
            (type(self),)
            + tuple(getattr(self, name) for name in self._record_fields)
        )

    def __repr__(self) -> str:
        fields = ", ".join(
            f"{name}={getattr(self, name)!r}"
            for name in self._record_fields
            if name not in self._repr_omitted_fields
        )
        return f"{type(self).__name__}({fields})"


class ArtifactWriterRequest(_ArtifactWriterFrozenRecord):
    __slots__ = (
        "schema_version",
        "mode",
        "root",
        "leaf",
        "content",
        "expected_content_sha256",
        "creates_root",
        "predecessor_leaf",
        "canonical_bytes",
        "canonical_sha256",
    )
    _record_fields = __slots__
    _repr_omitted_fields = frozenset({"content", "canonical_bytes"})

    def __init__(
        self,
        schema_version: str,
        mode: ArtifactWriterMode,
        root: str,
        leaf: str,
        content: bytes,
        expected_content_sha256: str,
        creates_root: bool,
        predecessor_leaf: str | None,
        canonical_bytes: bytes,
        canonical_sha256: str,
    ) -> None:
        self._initialize_record(
            (
                schema_version,
                mode,
                root,
                leaf,
                content,
                expected_content_sha256,
                creates_root,
                predecessor_leaf,
                canonical_bytes,
                canonical_sha256,
            )
        )


def _starts_with_ascii_case_insensitive(value: str, prefix: str) -> bool:
    if len(value) < len(prefix):
        return False
    for actual, expected in zip(value, prefix):
        if "a" <= actual <= "z":
            actual = chr(ord(actual) - 32)
        if actual != expected:
            return False
    return True


def validate_artifact_writer_outer_environment_names(
    environment_table: object,
) -> bytes:
    try:
        names = environment_table.keys()
    except (AttributeError, TypeError):
        raise RuntimeError("artifact outer environment-name drift") from None
    try:
        for name in names:
            if (
                type(name) is not str
                or not name
                or "\x00" in name
                or "=" in name
            ):
                raise RuntimeError("artifact outer environment-name drift")
            if any(
                _starts_with_ascii_case_insensitive(name, prefix)
                for prefix in _OUTER_RUNTIME_NAME_PREFIXES
            ):
                raise RuntimeError("artifact outer environment-family drift")
    except RuntimeError:
        raise
    except (TypeError, ValueError):
        raise RuntimeError("artifact outer environment-name drift") from None
    return ARTIFACT_WRITER_OUTER_ENVIRONMENT_MARKER


def build_artifact_writer_child_environment() -> dict[str, str]:
    return dict(ARTIFACT_WRITER_CHILD_ENVIRONMENT_ITEMS)


def validate_artifact_writer_child_environment(environment: object) -> None:
    try:
        items = tuple(environment.items())
    except (AttributeError, TypeError, ValueError):
        raise RuntimeError("artifact inner environment drift") from None
    if items != ARTIFACT_WRITER_CHILD_ENVIRONMENT_ITEMS:
        raise RuntimeError("artifact inner environment drift")


def validate_artifact_writer_native_process_contract(
    *,
    observed_image: object,
    observed_argv: object,
    managed_argv: object,
) -> None:
    if (
        observed_image != r"C:\Python314\python.exe"
        or type(observed_argv) is not tuple
        or type(managed_argv) is not tuple
        or len(managed_argv) != 3
    ):
        raise RuntimeError("artifact native process drift")
    helper_path, option, request_sha256 = managed_argv
    if (
        type(helper_path) is not str
        or not helper_path.startswith("D:\\")
        or "/" in helper_path
        or not helper_path.endswith(_ARTIFACT_WRITER_HELPER_SUFFIX)
        or option != "--expected-request-sha256"
        or type(request_sha256) is not str
        or len(request_sha256) != 64
        or any(character not in "0123456789abcdef" for character in request_sha256)
    ):
        raise RuntimeError("artifact native process drift")
    expected_argv = (
        r"C:\Python314\python.exe",
        "-I",
        "-S",
        "-B",
        "-X",
        "utf8",
        helper_path,
        "--expected-request-sha256",
        request_sha256,
    )
    if observed_argv != expected_argv:
        raise RuntimeError("artifact native process drift")


def _is_artifact_writer_runtime_source_path(value: object) -> bool:
    if (
        type(value) is not str
        or not value.startswith("C:\\Python314\\")
        or "/" in value
        or "\x00" in value
        or not value.endswith((".py", ".pyd"))
        or value.endswith(".pyc")
        or "\\__pycache__\\" in value
    ):
        return False
    components = value.split("\\")
    return (
        len(components) >= 3
        and components[0] == "C:"
        and all(component not in {"", ".", ".."} for component in components[1:])
    )


def validate_artifact_writer_loaded_module_origins(
    *,
    records: object,
    helper_path: object,
) -> None:
    if (
        type(records) is not tuple
        or type(helper_path) is not str
        or not helper_path.startswith("D:\\")
        or "/" in helper_path
        or "\x00" in helper_path
        or not helper_path.endswith(_ARTIFACT_WRITER_HELPER_SUFFIX)
    ):
        raise RuntimeError("artifact module origin drift")
    seen: set[str] = set()
    for record in records:
        if type(record) is not tuple or len(record) != 3:
            raise RuntimeError("artifact module origin drift")
        name, origin, source_path = record
        if (
            type(name) is not str
            or not name
            or name in seen
            or "\x00" in name
        ):
            raise RuntimeError("artifact module origin drift")
        seen.add(name)
        if name == "__main__":
            if origin is not None or source_path != helper_path:
                raise RuntimeError("artifact module origin drift")
            continue
        if origin == "built-in":
            if source_path is not None:
                raise RuntimeError("artifact module origin drift")
            continue
        if origin == "frozen":
            if source_path is not None and not _is_artifact_writer_runtime_source_path(
                source_path
            ):
                raise RuntimeError("artifact module origin drift")
            continue
        if (
            not _is_artifact_writer_runtime_source_path(origin)
            or source_path != origin
        ):
            raise RuntimeError("artifact module origin drift")
    expected = tuple(
        (
            name,
            origin,
            helper_path if source_path == "$HELPER" else source_path,
        )
        for name, origin, source_path in ARTIFACT_WRITER_LOADED_MODULE_ORIGINS
    )
    if records != expected:
        raise RuntimeError("artifact module origin drift")


def _artifact_writer_loaded_module_records() -> tuple[
    tuple[str, object, object], ...
]:
    records: list[tuple[str, object, object]] = []
    for name, module in tuple(sys.modules.items()):
        specification = getattr(module, "__spec__", None)
        records.append(
            (
                name,
                getattr(specification, "origin", None),
                getattr(module, "__file__", None),
            )
        )
    return tuple(records)


def _reject() -> None:
    raise RuntimeError("ARTIFACT_WRITER_REQUEST_INVALID")


def _reject_json_constant(_value: str) -> None:
    _reject()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            _reject()
        result[key] = value
    return result


def _decode_canonical_host_review_document(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            raw[:-1].decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except RuntimeError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        _reject()
    if type(value) is not dict:
        _reject()
    canonical = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        + b"\n"
    )
    if canonical != raw:
        _reject()
    return value


def _is_lower_hex(value: object, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _validate_host_review_subjects(
    value: object,
    *,
    phase: str,
) -> list[dict[str, object]]:
    expected_rows = _HOST_REVIEW_SUBJECT_ROWS[phase]
    if type(value) is not list or len(value) != len(expected_rows):
        _reject()
    subjects: list[dict[str, object]] = []
    for ordinal, (subject, expected_row) in enumerate(
        zip(value, expected_rows),
    ):
        expected_role, path_pattern = expected_row
        if (
            type(subject) is not dict
            or tuple(subject) != _HOST_REVIEW_SUBJECT_KEYS
            or subject["role"] != expected_role
            or type(subject["path"]) is not str
            or path_pattern.fullmatch(subject["path"]) is None
            or not _is_lower_hex(subject["sha256"], _SHA256_PATTERN)
        ):
            _reject()
        identity = subject["identity"]
        if (
            type(identity) is not dict
            or tuple(identity) != _HOST_REVIEW_IDENTITY_KEYS
            or type(identity["device"]) is not int
            or identity["device"] < 0
            or type(identity["inode"]) is not int
            or identity["inode"] < 0
            or type(identity["file_type"]) is not int
            or identity["file_type"] != 1
            or type(identity["reparse_tag"]) is not int
            or identity["reparse_tag"] != 0
            or type(identity["link_count"]) is not int
            or identity["link_count"] != 1
        ):
            _reject()
        maximum_size = 50_331_648 if ordinal == len(expected_rows) - 1 else 4_194_304
        if (
            type(subject["size"]) is not int
            or not 1 <= subject["size"] <= maximum_size
        ):
            _reject()
        subjects.append(subject)
    primary_path = subjects[0]["path"]
    bundle_path = subjects[-1]["path"]
    if phase in {"candidate", "closure", "final-docs"} and bundle_path != (
        primary_path[:-5] + "\\host-review-input-bundle.json"
    ):
        _reject()
    return subjects


def _validate_host_review_common(
    value: dict[str, object],
    *,
    phase: str,
    review_type: str,
) -> None:
    if (
        value["phase"] != phase
        or value["review_type"] != review_type
        or value["reviewer_task_name"] != _HOST_REVIEW_TASKS[(phase, review_type)]
        or not _is_lower_hex(value["target_head"], _HEX40_PATTERN)
        or not _is_lower_hex(value["target_tree"], _HEX40_PATTERN)
        or not _is_lower_hex(value["target_parent"], _HEX40_PATTERN)
        or value["target_base"] != _HOST_REVIEW_TARGET_BASE
        or not _is_lower_hex(value["design_sha256"], _SHA256_PATTERN)
        or not _is_lower_hex(value["plan_sha256"], _SHA256_PATTERN)
        or not _is_lower_hex(value["campaign_sha256"], _SHA256_PATTERN)
        or not _is_lower_hex(value["subject_equivalence_sha256"], _SHA256_PATTERN)
        or not _is_lower_hex(
            value["host_review_input_bundle_aggregate_sha256"],
            _SHA256_PATTERN,
        )
    ):
        _reject()
    subjects = _validate_host_review_subjects(
        value["subject_records"],
        phase=phase,
    )
    projection = {
        "schema_version": (
            "complete-suite-host-review-authorized-input-projection-v1"
        ),
        "phase": phase,
        "entries": subjects,
    }
    projection_bytes = (
        json.dumps(
            projection,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    if (
        type(value["authorized_input_projection_entry_count"]) is not int
        or value["authorized_input_projection_entry_count"] != len(subjects)
        or value["authorized_input_projection_sha256"]
        != sha256(projection_bytes).hexdigest()
        or type(value["host_review_input_bundle_entry_count"]) is not int
        or not 1 <= value["host_review_input_bundle_entry_count"] <= 8192
        or type(value["host_review_input_bundle_decoded_bytes"]) is not int
        or not 1
        <= value["host_review_input_bundle_decoded_bytes"]
        <= 33_554_432
    ):
        _reject()
    predecessor = value["predecessor_review_result_sha256s"]
    expected_ordinal = 1 if review_type == "specification" else 2
    if (
        type(predecessor) is not list
        or (
            review_type == "specification"
            and predecessor != []
        )
        or (
            review_type == "quality_security"
            and (
                len(predecessor) != 1
                or not _is_lower_hex(predecessor[0], _SHA256_PATTERN)
            )
        )
        or type(value["phase_model_call_ordinal"]) is not int
        or value["phase_model_call_ordinal"] != expected_ordinal
        or type(value["deadline_ms"]) is not int
        or value["deadline_ms"] != 900_000
        or value["deadline_clock"] != "monotonic"
        or value["deadline_expiry_action"] != "interrupt_agent-exactly-once"
    ):
        _reject()


def _validate_host_review_envelope(
    value: dict[str, object],
    *,
    phase: str,
    review_type: str,
) -> None:
    if (
        tuple(value) != _HOST_REVIEW_ENVELOPE_KEYS
        or value["schema_version"]
        != "complete-suite-host-review-evaluation-envelope-v1"
        or type(value["envelope_id"]) is not str
        or value["purpose"] != "campaign-6-independent-read-only-review"
        or value["host_collaboration_model_call"] is not True
        or value["host_model_transport"]
        != "platform-managed-outside-campaign6-windows-process-boundary"
        or type(value["local_windows_processes_allowed"]) is not int
        or value["local_windows_processes_allowed"] != 0
        or type(value["local_windows_codex_client_processes_allowed"]) is not int
        or value["local_windows_codex_client_processes_allowed"] != 0
        or type(value["local_provider_processes_allowed"]) is not int
        or value["local_provider_processes_allowed"] != 0
        or type(value["local_socket_network_calls_allowed"]) is not int
        or value["local_socket_network_calls_allowed"] != 0
        or value["network_access_allowed"] is not False
        or value["credential_access_allowed"] is not False
        or value["filesystem_read_authority"]
        != "retained-envelope-phase-fixed-subjects-and-bundle-bounded-no-follow"
        or value["unlisted_filesystem_access_allowed"] is not False
        or value["filesystem_writes_allowed"] is not False
        or value["git_mutations_allowed"] is not False
        or value["test_execution_allowed"] is not False
        or value["tool_execution_allowed"] is not False
        or value["child_agent_spawns_allowed"] is not False
        or value["result_transport"] != "collaboration-final-message-only"
        or type(value["result_cap_bytes"]) is not int
        or value["result_cap_bytes"] != 262_144
        or value["cybersecurity_checks_may_be_bypassed"] is not False
    ):
        _reject()
    _validate_host_review_common(
        value,
        phase=phase,
        review_type=review_type,
    )


def _validate_host_review_findings(
    value: object,
    *,
    severity: str,
) -> list[dict[str, object]]:
    if type(value) is not list or len(value) > 64:
        _reject()
    findings: list[dict[str, object]] = []
    for finding in value:
        if (
            type(finding) is not dict
            or tuple(finding) != _HOST_REVIEW_FINDING_KEYS
            or finding["severity"] != severity
            or type(finding["line_start"]) is not int
            or finding["line_start"] <= 0
            or type(finding["line_end"]) is not int
            or finding["line_end"] < finding["line_start"]
            or type(finding["quoted_text"]) is not str
            or len(finding["quoted_text"].encode("utf-8")) > 4096
            or type(finding["why_blocking"]) is not str
            or len(finding["why_blocking"].encode("utf-8")) > 8192
            or type(finding["minimal_correction"]) is not str
            or len(finding["minimal_correction"].encode("utf-8")) > 8192
        ):
            _reject()
        findings.append(finding)
    return findings


def _validate_host_review_result(
    value: dict[str, object],
    *,
    phase: str,
    review_type: str,
) -> None:
    if (
        tuple(value) != _HOST_REVIEW_RESULT_KEYS
        or value["schema_version"] != _HOST_REVIEW_RESULT_SCHEMAS[phase]
        or value["capture_method"] != "codex-host-collaboration-final-v1"
        or not _is_lower_hex(
            value["evaluation_envelope_sha256"],
            _SHA256_PATTERN,
        )
        or value["verdict"] not in {"PASS", "BLOCKED"}
    ):
        _reject()
    _validate_host_review_common(
        value,
        phase=phase,
        review_type=review_type,
    )
    critical = _validate_host_review_findings(
        value["critical_findings"],
        severity="Critical",
    )
    important = _validate_host_review_findings(
        value["important_findings"],
        severity="Important",
    )
    if (
        value["verdict"] == "PASS"
        and (critical or important)
    ) or (
        value["verdict"] == "BLOCKED"
        and not (critical or important)
    ):
        _reject()


def validate_artifact_writer_host_review_content(
    *,
    mode: object,
    root: object,
    content: object,
) -> dict[str, object]:
    if (
        mode not in {"host-review-envelope", "host-review-result"}
        or type(root) is not str
        or type(content) is not bytes
    ):
        _reject()
    matched = _HOST_REVIEW_ROOT_PATTERN.fullmatch(root)
    if matched is None:
        _reject()
    phase = matched.group(1)
    review_type = matched.group(2).replace("-", "_")
    value = _decode_canonical_host_review_document(content)
    if mode == "host-review-envelope":
        _validate_host_review_envelope(
            value,
            phase=phase,
            review_type=review_type,
        )
    else:
        _validate_host_review_result(
            value,
            phase=phase,
            review_type=review_type,
        )
    return value


_HOST_REVIEW_COMMON_BINDING_KEYS = (
    "phase",
    "review_type",
    "reviewer_task_name",
    "target_head",
    "target_tree",
    "target_parent",
    "target_base",
    "design_sha256",
    "plan_sha256",
    "campaign_sha256",
    "subject_records",
    "subject_equivalence_sha256",
    "authorized_input_projection_entry_count",
    "authorized_input_projection_sha256",
    "host_review_input_bundle_entry_count",
    "host_review_input_bundle_decoded_bytes",
    "host_review_input_bundle_aggregate_sha256",
    "predecessor_review_result_sha256s",
    "phase_model_call_ordinal",
    "deadline_ms",
    "deadline_clock",
    "deadline_expiry_action",
)


def validate_artifact_writer_host_review_predecessor_binding(
    *,
    root: str,
    envelope_content: bytes,
    result_content: bytes,
) -> dict[str, object]:
    envelope = validate_artifact_writer_host_review_content(
        mode="host-review-envelope",
        root=root,
        content=envelope_content,
    )
    result = validate_artifact_writer_host_review_content(
        mode="host-review-result",
        root=root,
        content=result_content,
    )
    if result["evaluation_envelope_sha256"] != sha256(
        envelope_content
    ).hexdigest() or any(
        result[key] != envelope[key]
        for key in _HOST_REVIEW_COMMON_BINDING_KEYS
    ):
        _reject()
    return envelope


def _decode_canonical_request(raw: bytes) -> dict[str, object]:
    if (
        type(raw) is not bytes
        or not 2 <= len(raw) <= _REQUEST_MAX_BYTES
        or not raw.endswith(b"\n")
        or b"\n" in raw[:-1]
        or b"\r" in raw
        or b"\x00" in raw
        or raw.startswith(b"\xef\xbb\xbf")
    ):
        _reject()
    try:
        text = raw[:-1].decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except RuntimeError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        _reject()
    if type(value) is not dict:
        _reject()
    canonical = (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    if canonical != raw or tuple(value) != ARTIFACT_WRITER_REQUEST_KEYS:
        _reject()
    return value


def _decode_content(value: dict[str, object], mode: str) -> tuple[bytes, str]:
    encoded = value["content_base64"]
    expected = value["expected_content_sha256"]
    if (
        type(encoded) is not str
        or type(expected) is not str
        or _SHA256_PATTERN.fullmatch(expected) is None
    ):
        _reject()
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        _reject()
    if base64.b64encode(content).decode("ascii") != encoded:
        _reject()
    minimum, maximum = _CONTENT_LIMITS[mode]
    if (
        not minimum <= len(content) <= maximum
        or sha256(content).hexdigest() != expected
        or not content.endswith(b"\n")
        or b"\r" in content
        or b"\x00" in content
        or content.startswith(b"\xef\xbb\xbf")
    ):
        _reject()
    try:
        content.decode("utf-8", errors="strict")
    except UnicodeError:
        _reject()
    return content, expected


def _destination_contract(
    mode: str,
    root: str,
    leaf: str,
) -> tuple[bool, str | None]:
    if mode in {"operator-prompt", "operator-attestation"}:
        matched = _OPERATOR_ROOT_PATTERN.fullmatch(root)
        if matched is None:
            _reject()
        root_kind = matched.group(1)
        expected_leaf = (
            f"{root_kind}-prompt.txt"
            if mode == "operator-prompt"
            else f"{root_kind}.json"
        )
        if leaf != expected_leaf:
            _reject()
        return (
            mode == "operator-prompt",
            None if mode == "operator-prompt" else f"{root_kind}-prompt.txt",
        )
    matched = _HOST_REVIEW_ROOT_PATTERN.fullmatch(root)
    if matched is None:
        _reject()
    expected_leaf = (
        "review-evaluation-envelope.json"
        if mode == "host-review-envelope"
        else "review-result.json"
    )
    if leaf != expected_leaf:
        _reject()
    return (
        mode == "host-review-envelope",
        None
        if mode == "host-review-envelope"
        else "review-evaluation-envelope.json",
    )


def decode_artifact_writer_request(
    raw: bytes,
    *,
    expected_request_sha256: str,
) -> ArtifactWriterRequest:
    if (
        type(expected_request_sha256) is not str
        or _SHA256_PATTERN.fullmatch(expected_request_sha256) is None
        or type(raw) is not bytes
        or sha256(raw).hexdigest() != expected_request_sha256
    ):
        _reject()
    value = _decode_canonical_request(raw)
    if any(type(value[key]) is not str for key in ARTIFACT_WRITER_REQUEST_KEYS):
        _reject()
    schema_version = value["schema_version"]
    mode = value["mode"]
    root = value["root"]
    leaf = value["leaf"]
    if schema_version != _REQUEST_SCHEMA or mode not in ARTIFACT_WRITER_MODES:
        _reject()
    creates_root, predecessor_leaf = _destination_contract(mode, root, leaf)
    content, content_sha256 = _decode_content(value, mode)
    if mode in {"host-review-envelope", "host-review-result"}:
        validate_artifact_writer_host_review_content(
            mode=mode,
            root=root,
            content=content,
        )
    return ArtifactWriterRequest(
        schema_version=schema_version,
        mode=mode,
        root=root,
        leaf=leaf,
        content=content,
        expected_content_sha256=content_sha256,
        creates_root=creates_root,
        predecessor_leaf=predecessor_leaf,
        canonical_bytes=raw,
        canonical_sha256=expected_request_sha256,
    )


class ArtifactWriterObjectIdentity(_ArtifactWriterFrozenRecord):
    __slots__ = (
        "volume_serial_number",
        "file_index",
        "link_count",
        "attributes",
        "reparse_tag",
    )
    _record_fields = __slots__

    def __init__(
        self,
        volume_serial_number: int,
        file_index: int,
        link_count: int,
        attributes: int,
        reparse_tag: int,
    ) -> None:
        self._initialize_record(
            (
                volume_serial_number,
                file_index,
                link_count,
                attributes,
                reparse_tag,
            )
        )


class ArtifactWriterCreationEntry(_ArtifactWriterFrozenRecord):
    __slots__ = ("kind", "path", "identity", "size", "sha256")
    _record_fields = __slots__

    def __init__(
        self,
        kind: str,
        path: str,
        identity: ArtifactWriterObjectIdentity,
        size: int,
        sha256: str | None,
    ) -> None:
        self._initialize_record((kind, path, identity, size, sha256))


class ArtifactWriterPublicationReceipt(_ArtifactWriterFrozenRecord):
    __slots__ = (
        "output_path",
        "output_sha256",
        "before_members",
        "after_members",
        "creation_ledger",
        "parent_identity",
        "reopened_parent_identity",
        "root_identity",
        "reopened_root_identity",
        "output_identity",
        "reopened_output_identity",
        "predecessor_path",
        "predecessor_sha256",
        "predecessor_identity",
        "reopened_predecessor_identity",
    )
    _record_fields = __slots__

    def __init__(
        self,
        output_path: str,
        output_sha256: str,
        before_members: tuple[str, ...],
        after_members: tuple[str, ...],
        creation_ledger: tuple[ArtifactWriterCreationEntry, ...],
        parent_identity: ArtifactWriterObjectIdentity,
        reopened_parent_identity: ArtifactWriterObjectIdentity,
        root_identity: ArtifactWriterObjectIdentity,
        reopened_root_identity: ArtifactWriterObjectIdentity,
        output_identity: ArtifactWriterObjectIdentity,
        reopened_output_identity: ArtifactWriterObjectIdentity,
        predecessor_path: str | None,
        predecessor_sha256: str | None,
        predecessor_identity: ArtifactWriterObjectIdentity | None,
        reopened_predecessor_identity: ArtifactWriterObjectIdentity | None,
    ) -> None:
        self._initialize_record(
            (
                output_path,
                output_sha256,
                before_members,
                after_members,
                creation_ledger,
                parent_identity,
                reopened_parent_identity,
                root_identity,
                reopened_root_identity,
                output_identity,
                reopened_output_identity,
                predecessor_path,
                predecessor_sha256,
                predecessor_identity,
                reopened_predecessor_identity,
            )
        )


class _ArtifactWriterHandleSnapshot(_ArtifactWriterFrozenRecord):
    __slots__ = ("identity", "kind", "size", "final_path")
    _record_fields = __slots__

    def __init__(
        self,
        identity: ArtifactWriterObjectIdentity,
        kind: str,
        size: int,
        final_path: str,
    ) -> None:
        self._initialize_record((identity, kind, size, final_path))


class _FileTime(ctypes.Structure):
    _fields_ = (
        ("low", wintypes.DWORD),
        ("high", wintypes.DWORD),
    )


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = (
        ("file_attributes", wintypes.DWORD),
        ("creation_time", _FileTime),
        ("last_access_time", _FileTime),
        ("last_write_time", _FileTime),
        ("volume_serial_number", wintypes.DWORD),
        ("file_size_high", wintypes.DWORD),
        ("file_size_low", wintypes.DWORD),
        ("number_of_links", wintypes.DWORD),
        ("file_index_high", wintypes.DWORD),
        ("file_index_low", wintypes.DWORD),
    )


class _FileAttributeTagInformation(ctypes.Structure):
    _fields_ = (
        ("file_attributes", wintypes.DWORD),
        ("reparse_tag", wintypes.DWORD),
    )


class _UnicodeString(ctypes.Structure):
    _fields_ = (
        ("length", wintypes.USHORT),
        ("maximum_length", wintypes.USHORT),
        ("buffer", wintypes.LPWSTR),
    )


class _ObjectAttributes(ctypes.Structure):
    _fields_ = (
        ("length", wintypes.ULONG),
        ("root_directory", wintypes.HANDLE),
        ("object_name", ctypes.POINTER(_UnicodeString)),
        ("attributes", wintypes.ULONG),
        ("security_descriptor", wintypes.LPVOID),
        ("security_quality_of_service", wintypes.LPVOID),
    )


class _IoStatusBlock(ctypes.Structure):
    _fields_ = (
        ("status", wintypes.LPVOID),
        ("information", ctypes.c_size_t),
    )


class _Win32FindData(ctypes.Structure):
    _fields_ = (
        ("file_attributes", wintypes.DWORD),
        ("creation_time", _FileTime),
        ("last_access_time", _FileTime),
        ("last_write_time", _FileTime),
        ("file_size_high", wintypes.DWORD),
        ("file_size_low", wintypes.DWORD),
        ("reserved_zero", wintypes.DWORD),
        ("reserved_one", wintypes.DWORD),
        ("file_name", wintypes.WCHAR * 260),
        ("alternate_file_name", wintypes.WCHAR * 14),
        ("file_type", wintypes.DWORD),
        ("creator_type", wintypes.DWORD),
        ("finder_flags", wintypes.WORD),
    )


def _publication_reject() -> None:
    raise RuntimeError("ARTIFACT_WRITER_PUBLICATION_INVALID")


class _ArtifactWriterNativeApi:
    def __init__(self) -> None:
        if os.name != "nt":
            _publication_reject()
        kernel32 = ctypes.WinDLL(
            r"C:\Windows\System32\kernel32.dll",
            use_last_error=True,
        )
        ntdll = ctypes.WinDLL(
            r"C:\Windows\System32\ntdll.dll",
            use_last_error=True,
        )
        shell32 = ctypes.WinDLL(
            r"C:\Windows\System32\shell32.dll",
            use_last_error=True,
        )
        self.invalid_handle = ctypes.c_void_p(-1).value

        self.get_module_file_name = kernel32.GetModuleFileNameW
        self.get_module_file_name.argtypes = (
            wintypes.HMODULE,
            wintypes.LPWSTR,
            wintypes.DWORD,
        )
        self.get_module_file_name.restype = wintypes.DWORD
        self.get_command_line = kernel32.GetCommandLineW
        self.get_command_line.argtypes = ()
        self.get_command_line.restype = wintypes.LPCWSTR
        self.command_line_to_argv = shell32.CommandLineToArgvW
        self.command_line_to_argv.argtypes = (
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_int),
        )
        self.command_line_to_argv.restype = ctypes.POINTER(wintypes.LPWSTR)
        self.local_free = kernel32.LocalFree
        self.local_free.argtypes = (wintypes.HLOCAL,)
        self.local_free.restype = wintypes.HLOCAL
        self.create_file = kernel32.CreateFileW
        self.create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        self.create_file.restype = wintypes.HANDLE
        self.nt_create_file = ntdll.NtCreateFile
        self.nt_create_file.argtypes = (
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            ctypes.POINTER(_ObjectAttributes),
            ctypes.POINTER(_IoStatusBlock),
            wintypes.LPVOID,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.LPVOID,
            wintypes.ULONG,
        )
        self.nt_create_file.restype = ctypes.c_long
        self.get_information = kernel32.GetFileInformationByHandle
        self.get_information.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(_ByHandleFileInformation),
        )
        self.get_information.restype = wintypes.BOOL
        self.get_information_ex = kernel32.GetFileInformationByHandleEx
        self.get_information_ex.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        self.get_information_ex.restype = wintypes.BOOL
        self.get_final_path = kernel32.GetFinalPathNameByHandleW
        self.get_final_path.argtypes = (
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        self.get_final_path.restype = wintypes.DWORD
        self.write_file = kernel32.WriteFile
        self.write_file.argtypes = (
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        )
        self.write_file.restype = wintypes.BOOL
        self.flush_file_buffers = kernel32.FlushFileBuffers
        self.flush_file_buffers.argtypes = (wintypes.HANDLE,)
        self.flush_file_buffers.restype = wintypes.BOOL
        self.read_file = kernel32.ReadFile
        self.read_file.argtypes = (
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        )
        self.read_file.restype = wintypes.BOOL
        self.set_file_pointer = kernel32.SetFilePointerEx
        self.set_file_pointer.argtypes = (
            wintypes.HANDLE,
            ctypes.c_longlong,
            ctypes.POINTER(ctypes.c_longlong),
            wintypes.DWORD,
        )
        self.set_file_pointer.restype = wintypes.BOOL
        self.find_first = kernel32.FindFirstFileW
        self.find_first.argtypes = (
            wintypes.LPCWSTR,
            ctypes.POINTER(_Win32FindData),
        )
        self.find_first.restype = wintypes.HANDLE
        self.find_next = kernel32.FindNextFileW
        self.find_next.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(_Win32FindData),
        )
        self.find_next.restype = wintypes.BOOL
        self.find_close = kernel32.FindClose
        self.find_close.argtypes = (wintypes.HANDLE,)
        self.find_close.restype = wintypes.BOOL
        self.close_handle = kernel32.CloseHandle
        self.close_handle.argtypes = (wintypes.HANDLE,)
        self.close_handle.restype = wintypes.BOOL
        if _ARTIFACT_WRITER_AUDIT_PHASE == "native":
            _register_artifact_writer_publication_call_arities(
                (
                    ("GetModuleFileNameW", self.get_module_file_name),
                    ("GetCommandLineW", self.get_command_line),
                    ("CommandLineToArgvW", self.command_line_to_argv),
                    ("LocalFree", self.local_free),
                    ("CreateFileW", self.create_file),
                    ("NtCreateFile", self.nt_create_file),
                    ("GetFileInformationByHandle", self.get_information),
                    ("GetFileInformationByHandleEx", self.get_information_ex),
                    ("GetFinalPathNameByHandleW", self.get_final_path),
                    ("WriteFile", self.write_file),
                    ("FlushFileBuffers", self.flush_file_buffers),
                    ("ReadFile", self.read_file),
                    ("SetFilePointerEx", self.set_file_pointer),
                    ("FindFirstFileW", self.find_first),
                    ("FindNextFileW", self.find_next),
                    ("FindClose", self.find_close),
                    ("CloseHandle", self.close_handle),
                    ("ctypes._cast", ctypes._cast),
                )
            )
            _seal_artifact_writer_native_audit()
        elif _ARTIFACT_WRITER_AUDIT_PHASE != "inactive":
            _artifact_writer_audit_reject()

    def observe_native_process(self) -> tuple[str, tuple[str, ...]]:
        image_buffer = ctypes.create_unicode_buffer(32_768)
        image_length = int(
            self.get_module_file_name(None, image_buffer, len(image_buffer))
        )
        if image_length <= 0 or image_length >= len(image_buffer):
            raise RuntimeError("artifact native process drift")
        command_line = self.get_command_line()
        if type(command_line) is not str or not command_line:
            raise RuntimeError("artifact native process drift")
        count = ctypes.c_int()
        native_pointer = self.command_line_to_argv(
            command_line,
            ctypes.byref(count),
        )
        if not native_pointer or count.value <= 0 or count.value > 64:
            raise RuntimeError("artifact native process drift")
        try:
            arguments = tuple(
                str(native_pointer[index]) for index in range(count.value)
            )
        finally:
            allocation = wintypes.HLOCAL(
                ctypes.cast(native_pointer, ctypes.c_void_p).value
            )
            if self.local_free(allocation):
                raise RuntimeError("artifact native process drift")
        return image_buffer.value, arguments

    def _value(self, handle: object) -> int:
        value = getattr(handle, "value", handle)
        if value is None:
            _publication_reject()
        return int(value)

    def _valid(self, handle: object) -> bool:
        value = getattr(handle, "value", handle)
        return value not in (None, self.invalid_handle)

    def close(self, handle: object | None) -> bool:
        if handle is None or not self._valid(handle):
            return True
        return bool(self.close_handle(handle))

    def open_absolute_directory(self, path: str) -> object:
        constants = ARTIFACT_WRITER_NATIVE_CONSTANTS
        handle = self.create_file(
            path,
            constants["FILE_LIST_DIRECTORY"]
            | constants["FILE_READ_ATTRIBUTES"]
            | constants["FILE_TRAVERSE"]
            | constants["SYNCHRONIZE"],
            constants["FILE_SHARE_READ"],
            None,
            constants["OPEN_EXISTING"],
            constants["FILE_FLAG_OPEN_REPARSE_POINT"]
            | constants["FILE_FLAG_BACKUP_SEMANTICS"],
            None,
        )
        if not self._valid(handle):
            _publication_reject()
        return handle

    def open_relative(
        self,
        parent: object,
        component: str,
        *,
        directory: bool,
        create_new: bool,
        writable: bool = False,
    ) -> object:
        if (
            type(component) is not str
            or not component
            or component in {".", ".."}
            or "\\" in component
            or "/" in component
            or "\x00" in component
        ):
            _publication_reject()
        try:
            encoded = component.encode("utf-16-le", errors="strict")
        except UnicodeEncodeError:
            _publication_reject()
        if len(encoded) > 65_532:
            _publication_reject()
        name_buffer = ctypes.create_unicode_buffer(component)
        unicode_name = _UnicodeString(
            length=len(encoded),
            maximum_length=len(encoded) + 2,
            buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
        )
        constants = ARTIFACT_WRITER_NATIVE_CONSTANTS
        attributes = _ObjectAttributes(
            length=ctypes.sizeof(_ObjectAttributes),
            root_directory=parent,
            object_name=ctypes.pointer(unicode_name),
            attributes=constants["OBJ_DONT_REPARSE"],
            security_descriptor=None,
            security_quality_of_service=None,
        )
        io_status = _IoStatusBlock()
        handle = wintypes.HANDLE()
        desired = constants["FILE_READ_ATTRIBUTES"] | constants["SYNCHRONIZE"]
        options = (
            constants["FILE_SYNCHRONOUS_IO_NONALERT"]
            | constants["FILE_OPEN_REPARSE_POINT"]
        )
        if directory:
            desired |= constants["FILE_LIST_DIRECTORY"] | constants["FILE_TRAVERSE"]
            options |= (
                constants["FILE_DIRECTORY_FILE"]
                | constants["FILE_OPEN_FOR_BACKUP_INTENT"]
            )
        else:
            desired |= constants["FILE_READ_DATA"]
            if writable:
                desired |= constants["FILE_WRITE_DATA"]
            options |= constants["FILE_NON_DIRECTORY_FILE"]
        status = self.nt_create_file(
            ctypes.byref(handle),
            desired,
            ctypes.byref(attributes),
            ctypes.byref(io_status),
            None,
            0,
            constants["FILE_SHARE_READ"],
            constants["FILE_CREATE"] if create_new else constants["FILE_OPEN"],
            options,
            None,
            0,
        )
        if status < 0 or not self._valid(handle):
            if self._valid(handle):
                self.close(handle)
            _publication_reject()
        return handle

    @staticmethod
    def _normalize_final_path(value: str) -> str:
        if value.startswith("\\\\?\\UNC\\"):
            return "\\\\" + value[8:]
        if value.startswith("\\\\?\\"):
            return value[4:]
        return value

    def snapshot(
        self,
        handle: object,
        *,
        expected_kind: str,
        expected_path: str,
    ) -> _ArtifactWriterHandleSnapshot:
        information = _ByHandleFileInformation()
        tag_information = _FileAttributeTagInformation()
        constants = ARTIFACT_WRITER_NATIVE_CONSTANTS
        if not self.get_information(handle, ctypes.byref(information)):
            _publication_reject()
        if not self.get_information_ex(
            handle,
            constants["FILE_ATTRIBUTE_TAG_INFO"],
            ctypes.byref(tag_information),
            ctypes.sizeof(tag_information),
        ):
            _publication_reject()
        attributes = int(information.file_attributes)
        tag_attributes = int(tag_information.file_attributes)
        is_directory = bool(attributes & constants["FILE_ATTRIBUTE_DIRECTORY"])
        if (
            is_directory is not (expected_kind == "directory")
            or bool(tag_attributes & constants["FILE_ATTRIBUTE_DIRECTORY"])
            is not (expected_kind == "directory")
            or attributes & constants["FILE_ATTRIBUTE_REPARSE_POINT"]
            or tag_attributes & constants["FILE_ATTRIBUTE_REPARSE_POINT"]
            or int(tag_information.reparse_tag) != 0
            or int(information.number_of_links) <= 0
            or (
                expected_kind == "file"
                and int(information.number_of_links) != 1
            )
        ):
            _publication_reject()
        required = int(self.get_final_path(handle, None, 0, 0))
        if required <= 0 or required > 32_767:
            _publication_reject()
        buffer = ctypes.create_unicode_buffer(required + 1)
        length = int(self.get_final_path(handle, buffer, len(buffer), 0))
        if length <= 0 or length >= len(buffer):
            _publication_reject()
        final_path = self._normalize_final_path(buffer.value)
        if final_path != expected_path:
            _publication_reject()
        size = (
            int(information.file_size_high) << 32
        ) | int(information.file_size_low)
        if expected_kind == "directory":
            size = 0
        return _ArtifactWriterHandleSnapshot(
            identity=ArtifactWriterObjectIdentity(
                volume_serial_number=int(information.volume_serial_number),
                file_index=(int(information.file_index_high) << 32)
                | int(information.file_index_low),
                link_count=int(information.number_of_links),
                attributes=attributes,
                reparse_tag=int(tag_information.reparse_tag),
            ),
            kind=expected_kind,
            size=size,
            final_path=final_path,
        )

    def write_exact(self, handle: object, content: bytes) -> None:
        if type(content) is not bytes or not content:
            _publication_reject()
        buffer = (ctypes.c_ubyte * len(content)).from_buffer_copy(content)
        offset = 0
        while offset < len(content):
            written = wintypes.DWORD()
            address = ctypes.addressof(buffer) + offset
            if not self.write_file(
                handle,
                ctypes.c_void_p(address),
                len(content) - offset,
                ctypes.byref(written),
                None,
            ):
                _publication_reject()
            count = int(written.value)
            if count <= 0 or count > len(content) - offset:
                _publication_reject()
            offset += count
        if not self.flush_file_buffers(handle):
            _publication_reject()

    def read_exact(self, handle: object, expected_size: int) -> bytes:
        if type(expected_size) is not int or not 0 <= expected_size <= 262_144:
            _publication_reject()
        buffer = (ctypes.c_ubyte * max(expected_size, 1))()
        read = wintypes.DWORD()
        if expected_size and not self.read_file(
            handle,
            buffer,
            expected_size,
            ctypes.byref(read),
            None,
        ):
            _publication_reject()
        if int(read.value) != expected_size:
            _publication_reject()
        extra = (ctypes.c_ubyte * 1)()
        extra_read = wintypes.DWORD()
        if not self.read_file(
            handle,
            extra,
            1,
            ctypes.byref(extra_read),
            None,
        ) or int(extra_read.value) != 0:
            _publication_reject()
        return bytes(buffer[:expected_size])

    def enumerate_directory(
        self,
        root_handle: object,
        final_path: str,
    ) -> tuple[str, ...]:
        data = _Win32FindData()
        handle = self.find_first(final_path + "\\*", ctypes.byref(data))
        if not self._valid(handle):
            if ctypes.get_last_error() == 2:
                return ()
            _publication_reject()
        names: list[str] = []
        folded: set[str] = set()
        close_ok = False
        try:
            while True:
                name = str(data.file_name)
                if name not in {".", ".."}:
                    if (
                        not name
                        or "\\" in name
                        or "/" in name
                        or "\x00" in name
                        or int(data.file_attributes)
                        & ARTIFACT_WRITER_NATIVE_CONSTANTS[
                            "FILE_ATTRIBUTE_REPARSE_POINT"
                        ]
                    ):
                        _publication_reject()
                    normalized = name.casefold()
                    if normalized in folded:
                        _publication_reject()
                    folded.add(normalized)
                    names.append(name)
                if self.find_next(handle, ctypes.byref(data)):
                    continue
                if ctypes.get_last_error() != 18:
                    _publication_reject()
                break
            close_ok = bool(self.find_close(handle))
        finally:
            if not close_ok:
                self.find_close(handle)
        if not close_ok:
            _publication_reject()
        ordered = tuple(sorted(names))
        for name in ordered:
            member = self.open_relative(
                root_handle,
                name,
                directory=False,
                create_new=False,
            )
            try:
                self.snapshot(
                    member,
                    expected_kind="file",
                    expected_path=final_path + "\\" + name,
                )
            finally:
                self.close(member)
        return ordered


def _after_artifact_leaf_created(
    _request: ArtifactWriterRequest,
    _output_path: str,
) -> None:
    pass


def _after_artifact_predecessor_held(
    _request: ArtifactWriterRequest,
    _predecessor_path: str,
) -> None:
    pass


def _before_artifact_leaf_create(
    _request: ArtifactWriterRequest,
    _output_path: str,
) -> None:
    pass


class CompleteSuiteHeldDirectoryPublication:
    _CANONICAL_PARENT = r"D:\tmp"

    def __init__(
        self,
        request: ArtifactWriterRequest,
        *,
        native_api: _ArtifactWriterNativeApi | None = None,
    ) -> None:
        if (
            type(request) is not ArtifactWriterRequest
            or (
                native_api is not None
                and type(native_api) is not _ArtifactWriterNativeApi
            )
        ):
            _publication_reject()
        creates_root = request.mode in {
            "operator-prompt",
            "host-review-envelope",
        }
        if (
            request.mode not in ARTIFACT_WRITER_MODES
            or request.creates_root is not creates_root
            or (request.predecessor_leaf is None)
            is not creates_root
        ):
            _publication_reject()
        prefix = self._CANONICAL_PARENT + "\\"
        if not request.root.startswith(prefix):
            _publication_reject()
        root_component = request.root[len(prefix) :]
        if not root_component or "\\" in root_component or "/" in root_component:
            _publication_reject()
        self.request = request
        self.root_component = root_component
        self.output_path = request.root + "\\" + request.leaf
        self.native_api = native_api

    def _snapshot_reopened_root(
        self,
        api: _ArtifactWriterNativeApi,
        parent: object,
    ) -> _ArtifactWriterHandleSnapshot:
        reopened = api.open_relative(
            parent,
            self.root_component,
            directory=True,
            create_new=False,
        )
        try:
            return api.snapshot(
                reopened,
                expected_kind="directory",
                expected_path=self.request.root,
            )
        finally:
            api.close(reopened)

    def publish(self) -> ArtifactWriterPublicationReceipt:
        api = (
            _ArtifactWriterNativeApi()
            if self.native_api is None
            else self.native_api
        )
        canonical_parent: object | None = None
        parent: object | None = None
        root: object | None = None
        predecessor: object | None = None
        output: object | None = None
        predecessor_view: dict[str, object] | None = None
        try:
            canonical_parent = api.open_absolute_directory(self._CANONICAL_PARENT)
            canonical_parent_snapshot = api.snapshot(
                canonical_parent,
                expected_kind="directory",
                expected_path=self._CANONICAL_PARENT,
            )
            parent = api.open_absolute_directory(self._CANONICAL_PARENT)
            parent_snapshot = api.snapshot(
                parent,
                expected_kind="directory",
                expected_path=self._CANONICAL_PARENT,
            )
            if parent_snapshot.identity != canonical_parent_snapshot.identity:
                _publication_reject()
            root = api.open_relative(
                parent,
                self.root_component,
                directory=True,
                create_new=self.request.creates_root,
            )
            root_snapshot = api.snapshot(
                root,
                expected_kind="directory",
                expected_path=self.request.root,
            )
            canonical_root_snapshot = self._snapshot_reopened_root(
                api,
                canonical_parent,
            )
            if canonical_root_snapshot.identity != root_snapshot.identity:
                _publication_reject()
            before_members = api.enumerate_directory(root, root_snapshot.final_path)
            expected_before_members = (
                ()
                if self.request.creates_root
                else (self.request.predecessor_leaf,)
            )
            if before_members != expected_before_members:
                _publication_reject()

            predecessor_path: str | None = None
            predecessor_sha256: str | None = None
            predecessor_snapshot: _ArtifactWriterHandleSnapshot | None = None
            predecessor_content: bytes | None = None
            if self.request.predecessor_leaf is not None:
                predecessor_path = (
                    self.request.root + "\\" + self.request.predecessor_leaf
                )
                predecessor = api.open_relative(
                    root,
                    self.request.predecessor_leaf,
                    directory=False,
                    create_new=False,
                )
                predecessor_snapshot = api.snapshot(
                    predecessor,
                    expected_kind="file",
                    expected_path=predecessor_path,
                )
                predecessor_minimum = (
                    2 if self.request.mode == "host-review-result" else 1
                )
                predecessor_maximum = (
                    131_072
                    if self.request.mode == "host-review-result"
                    else 65_536
                )
                if not (
                    predecessor_minimum
                    <= predecessor_snapshot.size
                    <= predecessor_maximum
                ):
                    _publication_reject()
                predecessor_content = api.read_exact(
                    predecessor,
                    predecessor_snapshot.size,
                )
                if (
                    not predecessor_content.endswith(b"\n")
                    or b"\r" in predecessor_content
                    or b"\x00" in predecessor_content
                    or predecessor_content.startswith(b"\xef\xbb\xbf")
                ):
                    _publication_reject()
                try:
                    predecessor_content.decode("utf-8", errors="strict")
                except UnicodeError:
                    _publication_reject()
                predecessor_sha256 = sha256(predecessor_content).hexdigest()
                if self.request.mode == "host-review-result":
                    predecessor_view = (
                        validate_artifact_writer_host_review_predecessor_binding(
                            root=self.request.root,
                            envelope_content=predecessor_content,
                            result_content=self.request.content,
                        )
                    )
                _after_artifact_predecessor_held(
                    self.request,
                    predecessor_path,
                )

            _before_artifact_leaf_create(self.request, self.output_path)
            output = api.open_relative(
                root,
                self.request.leaf,
                directory=False,
                create_new=True,
                writable=True,
            )
            api.write_exact(output, self.request.content)
            output_snapshot = api.snapshot(
                output,
                expected_kind="file",
                expected_path=self.output_path,
            )
            if output_snapshot.size != len(self.request.content):
                _publication_reject()
            _after_artifact_leaf_created(self.request, self.output_path)
            if not api.close(output):
                _publication_reject()
            output = None
            output = api.open_relative(
                root,
                self.request.leaf,
                directory=False,
                create_new=False,
            )
            reopened_output_snapshot = api.snapshot(
                output,
                expected_kind="file",
                expected_path=self.output_path,
            )
            reopened_content = api.read_exact(
                output,
                reopened_output_snapshot.size,
            )
            if (
                reopened_output_snapshot.identity != output_snapshot.identity
                or reopened_content != self.request.content
                or sha256(reopened_content).hexdigest()
                != self.request.expected_content_sha256
            ):
                _publication_reject()
            after_members = api.enumerate_directory(root, root_snapshot.final_path)
            expected_after_members = tuple(
                sorted((*expected_before_members, self.request.leaf))
            )
            if after_members != expected_after_members:
                _publication_reject()

            reopened_parent = api.open_absolute_directory(self._CANONICAL_PARENT)
            try:
                reopened_parent_snapshot = api.snapshot(
                    reopened_parent,
                    expected_kind="directory",
                    expected_path=self._CANONICAL_PARENT,
                )
                fresh_parent_root_snapshot = self._snapshot_reopened_root(
                    api,
                    reopened_parent,
                )
            finally:
                api.close(reopened_parent)
            reopened_root_snapshot = self._snapshot_reopened_root(api, parent)
            final_canonical_root_snapshot = self._snapshot_reopened_root(
                api,
                canonical_parent,
            )
            final_output = api.open_relative(
                root,
                self.request.leaf,
                directory=False,
                create_new=False,
            )
            try:
                final_output_snapshot = api.snapshot(
                    final_output,
                    expected_kind="file",
                    expected_path=self.output_path,
                )
                final_content = api.read_exact(
                    final_output,
                    final_output_snapshot.size,
                )
            finally:
                api.close(final_output)

            reopened_predecessor_identity: ArtifactWriterObjectIdentity | None = None
            if (
                predecessor is not None
                and predecessor_snapshot is not None
                and predecessor_content is not None
                and predecessor_path is not None
            ):
                held_predecessor_snapshot = api.snapshot(
                    predecessor,
                    expected_kind="file",
                    expected_path=predecessor_path,
                )
                final_predecessor = api.open_relative(
                    root,
                    self.request.predecessor_leaf,
                    directory=False,
                    create_new=False,
                )
                try:
                    final_predecessor_snapshot = api.snapshot(
                        final_predecessor,
                        expected_kind="file",
                        expected_path=predecessor_path,
                    )
                    final_predecessor_content = api.read_exact(
                        final_predecessor,
                        final_predecessor_snapshot.size,
                    )
                finally:
                    api.close(final_predecessor)
                if (
                    held_predecessor_snapshot.identity
                    != predecessor_snapshot.identity
                    or final_predecessor_snapshot.identity
                    != predecessor_snapshot.identity
                    or final_predecessor_content != predecessor_content
                    or sha256(final_predecessor_content).hexdigest()
                    != predecessor_sha256
                ):
                    _publication_reject()
                reopened_predecessor_identity = (
                    final_predecessor_snapshot.identity
                )
            if (
                reopened_parent_snapshot.identity != parent_snapshot.identity
                or reopened_root_snapshot.identity != root_snapshot.identity
                or fresh_parent_root_snapshot.identity != root_snapshot.identity
                or final_canonical_root_snapshot.identity != root_snapshot.identity
                or final_output_snapshot.identity != output_snapshot.identity
                or final_content != self.request.content
                or api.enumerate_directory(root, root_snapshot.final_path)
                != expected_after_members
            ):
                _publication_reject()
            creation_entries: list[ArtifactWriterCreationEntry] = []
            if self.request.creates_root:
                creation_entries.append(
                    ArtifactWriterCreationEntry(
                        kind="directory",
                        path=self.request.root,
                        identity=root_snapshot.identity,
                        size=0,
                        sha256=None,
                    )
                )
            creation_entries.append(
                ArtifactWriterCreationEntry(
                    kind="file",
                    path=self.output_path,
                    identity=output_snapshot.identity,
                    size=output_snapshot.size,
                    sha256=self.request.expected_content_sha256,
                )
            )
            return ArtifactWriterPublicationReceipt(
                output_path=self.output_path,
                output_sha256=self.request.expected_content_sha256,
                before_members=before_members,
                after_members=after_members,
                creation_ledger=tuple(creation_entries),
                parent_identity=parent_snapshot.identity,
                reopened_parent_identity=reopened_parent_snapshot.identity,
                root_identity=root_snapshot.identity,
                reopened_root_identity=reopened_root_snapshot.identity,
                output_identity=output_snapshot.identity,
                reopened_output_identity=final_output_snapshot.identity,
                predecessor_path=predecessor_path,
                predecessor_sha256=predecessor_sha256,
                predecessor_identity=(
                    None
                    if predecessor_snapshot is None
                    else predecessor_snapshot.identity
                ),
                reopened_predecessor_identity=reopened_predecessor_identity,
            )
        finally:
            api.close(output)
            predecessor_view = None
            api.close(predecessor)
            api.close(root)
            api.close(parent)
            api.close(canonical_parent)


def publish_artifact_writer_request(
    request: ArtifactWriterRequest,
    *,
    native_api: _ArtifactWriterNativeApi | None = None,
) -> ArtifactWriterPublicationReceipt:
    return CompleteSuiteHeldDirectoryPublication(
        request,
        native_api=native_api,
    ).publish()


def _artifact_writer_main() -> None:
    records = _artifact_writer_loaded_module_records()
    validate_artifact_writer_loaded_module_origins(
        records=records,
        helper_path=sys.argv[0],
    )
    _seal_artifact_writer_import_audit()
    native_api = _ArtifactWriterNativeApi()
    observed_image, observed_argv = native_api.observe_native_process()
    validate_artifact_writer_native_process_contract(
        observed_image=observed_image,
        observed_argv=observed_argv,
        managed_argv=tuple(sys.argv),
    )
    raw = sys.stdin.buffer.read(_REQUEST_MAX_BYTES + 1)
    if type(raw) is not bytes or len(raw) > _REQUEST_MAX_BYTES:
        _publication_reject()
    request = decode_artifact_writer_request(
        raw,
        expected_request_sha256=sys.argv[2],
    )
    receipt = publish_artifact_writer_request(request, native_api=native_api)
    output = receipt.output_path.encode("utf-8", errors="strict") + b"\n"
    if (
        b"\r" in output
        or b"\x00" in output
        or output.count(b"\n") != 1
        or not output.endswith(b"\n")
    ):
        _publication_reject()
    written = sys.stdout.buffer.write(output)
    if written != len(output):
        _publication_reject()
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    _artifact_writer_main()
