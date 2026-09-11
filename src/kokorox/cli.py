from __future__ import annotations

import argparse
from contextlib import redirect_stderr
from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Callable, Final, cast

from kokorox import __version__
from kokorox.authoring.drafts import build_character_draft
from kokorox.authoring.requests import normalize_build_request
from kokorox.authoring.storage import publish_draft_bundle
from kokorox.authoring.validation import validate_authoring_pack
from kokorox.config import Settings, resolve_schema_dir
from kokorox.distribution.defaults import (
    CharacterSelection,
    _load_selected_compiled_snapshot,
    clear_character_default,
    load_character_default,
    load_selected_compiled,
    resolve_character_selection,
    set_character_default,
)
from kokorox.errors import KokoroError
from kokorox.json_compat import find_json_incompatibility
from kokorox.packs.compiler import (
    canonical_bytes,
    compile_pack,
    write_compiled_pack,
)
from kokorox.packs.loader import load_source_pack
from kokorox.policy.compiler import normalize_policy
from kokorox.research.bundles import build_research_bundle
from kokorox.research.requests import normalize_research_request
from kokorox.research.storage import (
    load_published_research_bundle,
    publish_research_bundle,
)
from kokorox.research.validation import validate_research_workspace
from kokorox.research.workspace import load_research_workspace
from kokorox.language_tags import is_language_tag
from kokorox.runtime.context import build_runtime_context
from kokorox.runtime.planning import build_render_plan
from kokorox.runtime.validation import validate_rendered_output
from kokorox.schemas import SchemaRegistry
from kokorox.standalone_cli import (
    add_standalone_parsers,
    handle_standalone,
    standalone_requires_data_root,
    standalone_route,
)
from kokorox.state.store import SessionStore
from kokorox.state.transitions import apply_event
from kokorox.testing.hard import run_hard_validation
from kokorox.testing.promotion import create_promotion_record
from kokorox.testing.publication import assess_publication_readiness
from kokorox.testing.soft import aggregate_soft_evaluation
from kokorox.testing.storage import publish_promotion_record


JSON_INPUT_MAX_BYTES = 4 * 1024 * 1024
COMPILED_SCAN_MAX_FILES = 256
COMPILED_SCAN_MAX_BYTES = 32 * 1024 * 1024
# Compiled filenames use the first 16 lowercase SHA-256 hex characters.
SOURCE_HASH_PREFIX_LENGTH = 16
_PUBLIC_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_WINDOWS_RESERVED_OUTPUT_NAMES = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)
_PUBLIC_MESSAGES = {
    "ARGUMENT_INVALID": "Command arguments are invalid.",
    "AUTHORING_MODE_UNSUPPORTED": (
        "Construction mode is not available in this milestone."
    ),
    "AUTHORING_SOURCE_CHANGED": "Character source pack changed during compilation.",
    "AUTHORING_VALIDATION_FAILED": "Character authoring validation failed.",
    "DATA_DIR_REQUIRED": "Set KOKOROX_DATA_DIR before running a stateful command.",
    "DRAFT_PUBLISH_BUSY": "Character draft publication is already in progress.",
    "DRAFT_PUBLISH_FAILED": "Character draft publication failed.",
    "INPUT_NOT_FOUND": "Input file was not found.",
    "INPUT_PATH_UNSAFE": "Input file path is unsafe.",
    "INPUT_READ_FAILED": "Input file could not be read.",
    "INPUT_TOO_LARGE": "Input file exceeds the size limit.",
    "INPUT_INVALID_JSON": "Input file contains invalid JSON.",
    "INVALID_PACK_DATA": "Character pack data is invalid.",
    "INVALID_RUNTIME_CONTEXT_INPUT": "Runtime context input is invalid.",
    # Every KARC_* code outside the DEFAULT family reached callers as
    # "Command could not be completed", including the two that deadlock a
    # scope after an interrupted install.
    "KARC_ARCHIVE_INVALID": "Character archive is invalid.",
    "KARC_ARCHIVE_LIMIT_EXCEEDED": "Character archive exceeds a bound.",
    "KARC_BINDING_MISMATCH": (
        "Archive binding does not match the request."
    ),
    "KARC_COMPATIBILITY_BLOCKED": (
        "Archive is not compatible with this runtime."
    ),
    "KARC_COMPATIBILITY_REPORT_INVALID": (
        "Compatibility report is invalid."
    ),
    "KARC_COMPATIBILITY_TARGET_INVALID": (
        "Compatibility target is invalid."
    ),
    "KARC_INPUT_INVALID": "Installation input is invalid.",
    "KARC_INPUT_MUTATION": (
        "Installation input changed while it was read."
    ),
    "KARC_INSTALL_ARCHIVE_INVALID": (
        "Archive could not be installed; it is invalid."
    ),
    "KARC_INSTALL_ATOMIC_UNAVAILABLE": (
        "Atomic installation is unavailable on this filesystem."
    ),
    "KARC_INSTALL_CLEANUP_FAILED": (
        "Installation staging could not be cleaned up."
    ),
    "KARC_INSTALL_CONFLICT": (
        "A different installation already occupies the target."
    ),
    "KARC_INSTALL_JOURNAL_CHANGED": (
        "The install journal changed during recovery."
    ),
    "KARC_INSTALL_JOURNAL_INVALID": (
        "The install journal is unreadable; recovery cannot proceed."
    ),
    "KARC_INSTALL_JOURNAL_WRITE_FAILED": (
        "The install journal could not be written."
    ),
    "KARC_INSTALL_LOCK_LOST": "The install scope lock was lost.",
    "KARC_INSTALL_PATH_CHANGED": (
        "An installation path changed during the transaction."
    ),
    "KARC_INSTALL_PATH_INVALID": "An installation path is unsafe.",
    "KARC_INSTALL_RECOVERY_REQUIRED": (
        "An unfinished install transaction must be recovered first; run `kokorox pack recover` for this scope."
    ),
    "KARC_INSTALL_SOURCE_CHANGED": (
        "The archive changed during installation."
    ),
    "KARC_INSTALL_SOURCE_INVALID": "The archive source is unusable.",
    "KARC_INSTALL_STAGING_INVALID": "Installation staging is invalid.",
    "KARC_INSTALL_WRITE_FAILED": (
        "The installation could not be written."
    ),
    "KARC_MANIFEST_SCHEMA_MUTATION": (
        "Archive manifest changed while it was read."
    ),
    "KARC_MANIFEST_SCHEMA_UNSUPPORTED": (
        "Archive manifest schema is unsupported."
    ),
    "KARC_MEMBER_INTEGRITY_INVALID": (
        "An archive member failed its integrity check."
    ),
    "KARC_MEMBER_INVENTORY_INVALID": (
        "The archive member inventory is invalid."
    ),
    "KARC_PROMOTION_NOT_VERIFIED": "The pack has no verified promotion.",
    "KARC_PUBLICATION_NOT_READY": (
        "The pack is not ready for publication."
    ),
    "KARC_PUBLICATION_REQUIRED": (
        "A publication readiness report is required."
    ),
    "KARC_PUBLICATION_UNEXPECTED": (
        "A publication report was not expected here."
    ),
    "KARC_REGISTRY_CHANGED": (
        "The installed registry changed during the operation."
    ),
    "KARC_REGISTRY_CONFLICT": (
        "The installed registry revision conflicted."
    ),
    "KARC_REGISTRY_INVALID": "The installed registry is invalid.",
    "KARC_REGISTRY_LIMIT_EXCEEDED": (
        "The installed registry exceeds a bound."
    ),
    "KARC_REGISTRY_LOCKED": (
        "The installed registry is locked by another operation."
    ),
    "KARC_REGISTRY_LOCK_FAILED": (
        "The installed registry could not be locked."
    ),
    "KARC_REGISTRY_PATH_INVALID": (
        "The installed registry path is unsafe."
    ),
    "KARC_REGISTRY_SCOPE_MISMATCH": (
        "The installed registry belongs to another scope."
    ),
    "KARC_RELEASE_INVALID": "Release evidence is invalid.",
    "KARC_REMOVE_CONFLICT": (
        "Removal conflicted with a concurrent change."
    ),
    "KARC_REMOVE_IDENTITY_INVALID": "The removal identity is invalid.",
    "KARC_REMOVE_NOT_FOUND": (
        "No installation is registered for that character in this scope."
    ),
    "KARC_REMOVE_PATH_CHANGED": (
        "An installation path changed during removal."
    ),
    "KARC_REMOVE_REFERENCED": (
        "The installation is still referenced by a session or memory reference."
    ),
    "KARC_REMOVE_REFERENCE_SCAN_INVALID": (
        "Reference scanning failed during removal."
    ),
    "KARC_REMOVE_STORAGE_INVALID": "Installation storage is invalid.",
    "KARC_RUNTIME_VERSION_UNSUPPORTED": (
        "The archive needs a different runtime version."
    ),
    "KARC_SCHEMA_VERSION_UNSUPPORTED": (
        "The archive schema version is unsupported."
    ),
    "KARC_SCOPE_CHANGED": (
        "The installation scope changed during the operation."
    ),
    "KARC_SCOPE_INVALID": "The installation scope is invalid.",
    "KARC_DEFAULT_AMBIGUOUS": "Character default selection is ambiguous.",
    "KARC_DEFAULT_BINDING_INVALID": "Character default selection is invalid.",
    "KARC_DEFAULT_CLEANUP_FAILED": "Character default cleanup failed.",
    "KARC_DEFAULT_CONFIG_INVALID": "Character default configuration is invalid.",
    "KARC_DEFAULT_CONFLICT": "Character default configuration conflicted.",
    "KARC_DEFAULT_DURABILITY_FAILED": (
        "Character default durability could not be confirmed."
    ),
    "KARC_DEFAULT_INPUT_MUTATION": "Character default input changed.",
    "KARC_DEFAULT_LIMIT_EXCEEDED": "Character default data exceeds its limit.",
    "KARC_DEFAULT_LOCK_UNSAFE": "Character default lock is unsafe.",
    "KARC_DEFAULT_LOCKED": "Character default configuration is busy.",
    "KARC_DEFAULT_NOT_INSTALLED": "Character is not installed in this scope.",
    "KARC_DEFAULT_NOT_CONFIGURED": "No character default is configured.",
    "KARC_DEFAULT_PATH_UNSAFE": "Character default path is unsafe.",
    "KARC_DEFAULT_SELECTION_INVALID": "Character default selection is invalid.",
    "KARC_DEFAULT_SCOPE_MISMATCH": "Character default scope does not match.",
    "KARC_DEFAULT_STALE": "Character default binding is stale.",
    "KARC_DEFAULT_WRITE_FAILED": "Character default configuration write failed.",
    "PACK_NOT_FOUND": "Character pack was not found.",
    "RESEARCH_BUNDLE_INVALID": (
        "Published Research Bundle validation failed."
    ),
    "RESEARCH_BUNDLE_MISMATCH": (
        "Research Bundle metadata did not match validated inputs."
    ),
    "RESEARCH_BUNDLE_REQUIRED": (
        "An eligible Research Bundle is required for this authoring mode."
    ),
    "RESEARCH_BUNDLE_UNEXPECTED": (
        "This authoring mode does not accept a Research Bundle."
    ),
    "RESEARCH_CONTINUITY_UNRESOLVED": (
        "Research identity and continuity must be resolved."
    ),
    "RESEARCH_DURABILITY_FAILED": (
        "Research bundle publication could not be made durable."
    ),
    "RESEARCH_PUBLISH_BUSY": (
        "Research bundle publication is already in progress."
    ),
    "RESEARCH_PUBLISH_FAILED": "Research bundle publication failed.",
    "RESEARCH_RECOVERY_REQUIRED": (
        "Research publication retained a recoverable previous bundle."
    ),
    "RESEARCH_REPORT_MISMATCH": (
        "Research validation report did not match the workspace."
    ),
    "RESEARCH_STAGING_INVALID": "Staged Research Bundle validation failed.",
    "RESEARCH_VALIDATION_FAILED": "Research validation failed.",
    "RESEARCH_WORKSPACE_CHANGED": (
        "Research workspace changed during validation."
    ),
    "RESEARCH_WORKSPACE_DIGEST_MISMATCH": (
        "Research workspace digest did not match."
    ),
    "RESEARCH_WORKSPACE_INVALID": "Research workspace is invalid.",
    "RESEARCH_WORKSPACE_LIMIT_EXCEEDED": (
        "Research workspace filesystem limit was exceeded."
    ),
    "RESEARCH_WORKSPACE_LIMIT_INVALID": (
        "Research workspace limits are invalid."
    ),
    "RESEARCH_WORKSPACE_NOT_FOUND": "Research workspace was not found.",
    "RESEARCH_WORKSPACE_UNSAFE": "Research workspace path is unsafe.",
    "REPORT_OUTPUT_CHANGED": "Report output changed during publication.",
    "REPORT_OUTPUT_MISMATCH": "The requested report output is invalid.",
    "REPORT_OUTPUT_PATH_UNSAFE": "Report output path is unsafe.",
    "REPORT_OUTPUT_WRITE_FAILED": "Report output could not be written.",
    "SCHEMA_VALIDATION_FAILED": "Input did not match the required schema.",
    # Suite errors reached callers with the generic fallback message, so every
    # remedy they carry -- which source to name, what to remove -- was dropped
    # before anyone could read it.
    "SKILL_SUITE_CLEANUP_FAILED": "Skill suite staging could not be cleaned up.",
    "SKILL_SUITE_CONFLICT": (
        "An installed Skill differs from the KokoroX suite; remove it first."
    ),
    "SKILL_SUITE_DESTINATION_CHANGED": (
        "The Skill destination changed during the operation."
    ),
    "SKILL_SUITE_INSTALL_FAILED": "The Skill suite could not be installed.",
    "SKILL_SUITE_LIMIT_EXCEEDED": "The Skill suite source exceeds a bound.",
    "SKILL_SUITE_PATH_INVALID": "A Skill suite path is unsafe.",
    "SKILL_SUITE_REMOVE_CONFLICT": (
        "An installed Skill differs from the suite source; nothing was "
        "removed. Name the suite that installed it with --source, or remove "
        "it by hand."
    ),
    "SKILL_SUITE_REMOVE_FAILED": "The Skill suite could not be removed.",
    "SKILL_SUITE_RESTORE_FAILED": (
        "Skill suite removal failed and could not put moved Skills back."
    ),
    "SKILL_SUITE_ROLLBACK_FAILED": "Skill suite installation could not roll back.",
    "SKILL_SUITE_SOURCE_AMBIGUOUS": (
        "Several complete Skill suite sources were found; name one with --source."
    ),
    "SKILL_SUITE_SOURCE_CHANGED": "The Skill suite source changed during install.",
    "SKILL_SUITE_SOURCE_INVALID": (
        "The named Skill suite source is unusable or incomplete."
    ),
    "SKILL_SUITE_SOURCE_MISSING": (
        "No Skill suite source was found; name one with --source."
    ),
    "SOFT_EVALUATION_INPUT_INVALID": "Soft-evaluation input is invalid.",
    "STATE_REVISION_CONFLICT": "Relationship state revision conflicted.",
    "UNSAFE_PACK_PATH": "Character pack path is unsafe.",
    "UNSAFE_RESEARCH_PATH": "Research publication path is unsafe.",
    # Every other raised code. These reached callers as "Command could not
    # be completed" -- 133 of them, core session and runtime paths included --
    # because a family got messages only once a report happened to name it.
    # `test_every_raised_error_code_has_a_public_message` keeps this whole.
    "AUTHORING_SOURCE_HASH_MISMATCH": (
        "The character source pack does not match the draft metadata."
    ),
    "COMMAND_FAILED": "Command could not be completed.",
    "COMPILED_IDENTITY_MISMATCH": "The compiled artifact identity does not match.",
    "COMPILED_PACK_AMBIGUOUS": "Several compiled artifacts match the session.",
    "COMPILED_PACK_NOT_FOUND": "No compiled artifact was found for the session.",
    "COMPILED_PATH_UNSAFE": "The compiled artifact path is unsafe.",
    "COMPILED_SCAN_FAILED": "Compiled artifacts could not be scanned.",
    "COMPILED_SCAN_LIMIT": "The compiled artifact scan limit was exceeded.",
    "COMPILED_WRITE_FAILED": (
        "The compiled artifact could not be written, read back, or made "
        "durable."
    ),
    "DRAFT_DURABILITY_FAILED": "Character draft publication could not be made durable.",
    "DRAFT_RESTORE_FAILED": (
        "Character draft publication failed; the previous draft remains in a "
        "recovery backup."
    ),
    "DRAFT_STAGING_INVALID": (
        "The character draft staging bundle failed final verification."
    ),
    "INVALID_DRAFT_DATA": "Character draft metadata is invalid.",
    "INVALID_EVENT": "The interaction event is invalid.",
    "INVALID_FALLBACK_ATTEMPT": "The fallback attempt must be a bounded integer.",
    "INVALID_LANGUAGE_POLICY": (
        "The language policy is invalid: check its keys, mode, channels, and "
        "language tags."
    ),
    "INVALID_PACK_TEST_CORPUS": "The character pack test corpus is invalid.",
    "INVALID_PROFILE_VALUE": "A profile field has an invalid value.",
    "INVALID_RENDER_PLAN_INPUT": "Render plan input is invalid.",
    "INVALID_RUNTIME_CONTEXT": "Runtime context input is invalid.",
    "KARC_REGISTRY_WRITE_FAILED": (
        "The installed registry could not be published atomically."
    ),
    "MIGRATION_CYCLE": "The migration registry contains a cycle.",
    "MIGRATION_DOWNGRADE_UNSUPPORTED": "Archive downgrades are not supported.",
    "MIGRATION_IDENTITY_CHANGED": (
        "The migration would change protected character identity."
    ),
    "MIGRATION_INPUT_CHANGED": "The migration input changed while it was being read.",
    "MIGRATION_INPUT_INVALID": (
        "The migration input is not a readable, safe, canonical archive with "
        "exact source versions."
    ),
    "MIGRATION_INPUT_NOT_FOUND": "The migration input does not exist.",
    "MIGRATION_OUTPUT_CONFLICT": "The migration output must differ from its input.",
    "MIGRATION_OUTPUT_EXISTS": "The migration output already exists.",
    "MIGRATION_OUTPUT_INVALID": (
        "The migration did not produce a valid archive for the target version."
    ),
    "MIGRATION_OUTPUT_WRITE_FAILED": (
        "The migration output could not be written atomically."
    ),
    "MIGRATION_PATH_INVALID": (
        "A migration path is invalid or changed during the operation."
    ),
    "MIGRATION_UNAVAILABLE": (
        "No registered migration reaches the requested archive version."
    ),
    "PACK_CHANGED": "The character pack changed while hard validation was running.",
    "PACK_LIMIT_EXCEEDED": "A character pack filesystem limit was exceeded.",
    "PACK_LIMIT_INVALID": "Pack limits must be non-negative integers.",
    "PACK_PROMOTION_BINDING_MISMATCH": (
        "The promotion evidence does not bind one exact pack, review, and hard "
        "report."
    ),
    "PACK_PROMOTION_BUNDLE_INVALID": "The promotion bundle is invalid.",
    "PACK_PROMOTION_BUSY": "Another promotion publication is already in progress.",
    "PACK_PROMOTION_CLEANUP_FAILED": (
        "Promotion staging could not be cleaned up safely."
    ),
    "PACK_PROMOTION_CONFLICT": (
        "The promotion ID is already bound to a different record."
    ),
    "PACK_PROMOTION_DURABILITY_FAILED": (
        "The promotion record could not be confirmed durable."
    ),
    "PACK_PROMOTION_EVIDENCE_REQUIRED": (
        "A reviewed-to-verified promotion requires previous and soft evidence."
    ),
    "PACK_PROMOTION_HARD_GATE_FAILED": "The hard-validation report did not pass.",
    "PACK_PROMOTION_HARD_REPORT_STALE": (
        "The hard-validation report is not current for the exact pack inputs; "
        "re-run the hard gate."
    ),
    "PACK_PROMOTION_INPUT_INVALID": "A promotion input is not canonical JSON data.",
    "PACK_PROMOTION_INPUT_MUTATION": "A promotion input changed during promotion.",
    "PACK_PROMOTION_PATH_UNSAFE": (
        "The promotion destination contains an unsafe filesystem path."
    ),
    "PACK_PROMOTION_PREVIOUS_MISMATCH": (
        "The verified promotion does not extend the exact reviewed record."
    ),
    "PACK_PROMOTION_PREVIOUS_NOT_PUBLISHED": (
        "The exact reviewed promotion has not been published."
    ),
    "PACK_PROMOTION_PUBLISH_FAILED": "Promotion record publication failed.",
    "PACK_PROMOTION_REVIEW_ID_CONFLICT": (
        "The review ID is already bound outside its matching transition."
    ),
    "PACK_PROMOTION_REVIEW_REJECTED": (
        "The Character Pack review did not accept promotion."
    ),
    "PACK_PROMOTION_SOFT_GATE_FAILED": "The soft-evaluation report did not pass.",
    "PACK_PROMOTION_SOFT_PROFILE_INAPPLICABLE": (
        "The single-locale soft profile applies only to a pack that declares "
        "exactly one locale; evaluate this pack under default-release."
    ),
    "PACK_PROMOTION_SOFT_REPORT_STALE": (
        "The soft-evaluation report is not current for its exact input; re-run "
        "the soft evaluation."
    ),
    "PACK_PROMOTION_SOURCE_CHANGED": (
        "The Character Pack source changed during promotion."
    ),
    "PACK_PROMOTION_STAGING_INVALID": "Promotion staging failed final validation.",
    "PACK_PROMOTION_STORAGE_LIMIT": (
        "The promotion report store exceeds its bounded layout."
    ),
    "PACK_PROMOTION_TRANSITION_INVALID": (
        "The requested promotion transition is invalid."
    ),
    "PACK_PUBLICATION_COMPILE_FAILED": (
        "The Character Pack cannot be compiled for publication readiness."
    ),
    "PACK_PUBLICATION_COMPLIANCE_UNEXPECTED": (
        "A private readiness check cannot take a public compliance attestation."
    ),
    "PACK_PUBLICATION_INPUT_INVALID": (
        "A publication-readiness input is not canonical JSON data."
    ),
    "PACK_PUBLICATION_INPUT_MUTATION": (
        "A publication-readiness input changed during inspection."
    ),
    "PACK_PUBLICATION_PIPELINE_MUTATION": (
        "A publication-readiness dependency mutated a retained value."
    ),
    "PACK_PUBLICATION_SOURCE_CHANGED": (
        "The Character Pack changed during publication-readiness inspection."
    ),
    "PACK_PUBLICATION_SOURCE_INVALID": (
        "The Character Pack source cannot be inspected for publication "
        "readiness."
    ),
    "PACK_PUBLICATION_VALIDATOR_MUTATION": (
        "Schema validation mutated a publication-readiness artifact."
    ),
    "PACK_PUBLICATION_VISIBILITY_INVALID": (
        "The requested publication visibility is invalid."
    ),
    "PACK_SCAN_FAILED": "The character pack filesystem scan failed.",
    "PACK_TEST_CORPUS_CHANGED": (
        "The character pack test corpus changed while it was being loaded."
    ),
    "PACK_TEST_CORPUS_LIMIT_EXCEEDED": (
        "The character pack test corpus exceeds a data limit."
    ),
    "PACK_TEST_CORPUS_LIMIT_INVALID": (
        "Pack test corpus limits must be positive integers."
    ),
    "PERSISTENCE_CHANGED": "Persistent storage changed or is invalid.",
    "PERSISTENCE_CLEANUP_FAILED": "Persistent storage cleanup failed.",
    "PERSISTENCE_CONSENT_CONFLICT": (
        "The persistent consent revision conflicts with the request."
    ),
    "PERSISTENCE_CONSENT_INVALID": "Persistent consent is invalid.",
    "PERSISTENCE_CONSENT_NOT_FOUND": "No persistent consent was found.",
    "PERSISTENCE_CONSENT_REVOKED": "Persistent consent is revoked.",
    "PERSISTENCE_DURABILITY_FAILED": (
        "Persistent storage durability could not be confirmed."
    ),
    "PERSISTENCE_INPUT_MUTATION": "A persistence input changed during the operation.",
    "PERSISTENCE_INSTALLATION_STALE": (
        "The character this consent is bound to could not be resolved as "
        "recorded: it may not be installed in this scope, or it changed after "
        "consent was granted."
    ),
    "PERSISTENCE_LIMIT_EXCEEDED": "A persistent storage limit was exceeded.",
    "PERSISTENCE_LOCKED": "Persistent storage is busy.",
    "PERSISTENCE_MEMORY_CONFLICT": "The memory reference conflicts with retained data.",
    "PERSISTENCE_MEMORY_CONTENT_REJECTED": "The memory summary content was rejected.",
    "PERSISTENCE_MEMORY_INVALID": "The memory reference is invalid.",
    "PERSISTENCE_MEMORY_NOT_FOUND": "The memory reference was not found.",
    "PERSISTENCE_MIGRATION_CONFLICT": (
        "The persistent state migration conflicts with retained data."
    ),
    "PERSISTENCE_MIGRATION_INVALID": "The persistent state migration is invalid.",
    "PERSISTENCE_MIGRATION_STALE": "The persistent state migration inputs changed.",
    "PERSISTENCE_MIGRATION_UNREPLAYABLE": (
        "The persistent state migration cannot be replayed safely."
    ),
    "PERSISTENCE_MIGRATION_WRITE_FAILED": (
        "Persistent state migration publication failed."
    ),
    "PERSISTENCE_MOOD_INVALID": "The persistent mood event is invalid.",
    "PERSISTENCE_PATH_UNSAFE": "The persistent storage path is unsafe.",
    "PERSISTENCE_PERMISSION_DENIED": "Persistent permission is not granted.",
    "PERSISTENCE_RESET_STALE": (
        "The persistent reset preview is stale; preview it again."
    ),
    "PERSISTENCE_STATE_CONTRACT_UNSUPPORTED": (
        "The persistent state contract is unsupported."
    ),
    "PERSISTENCE_STATE_JOURNAL_INVALID": "The persistent state journal is invalid.",
    "PERSISTENCE_STATE_MIGRATION_REQUIRED": (
        "Persistent state requires an explicit migration."
    ),
    "PERSISTENCE_STATE_REVISION_CONFLICT": (
        "The persistent state revision conflicts with the request."
    ),
    "PERSISTENCE_STATE_WRITE_FAILED": (
        "Persistent state publication was committed but incomplete."
    ),
    "PERSISTENCE_WRITE_FAILED": "Persistent storage write failed.",
    "PLAN_CONCLUSION_LANGUAGE_MISMATCH": (
        "The conclusion must route to the primary language; recompile the "
        "policy so it does."
    ),
    "PROTECTED_CHANNEL_OVERRIDE": "A protected language channel cannot be overridden.",
    "SCHEMA_INVALID": "A bundled schema is invalid.",
    "SCHEMA_NAME_INVALID": "The schema name is invalid.",
    "SCHEMA_NOT_FOUND": "A required schema was not found.",
    "SCHEMA_READ_FAILED": "A schema file could not be read.",
    "SESSION_ALREADY_ACTIVE": "The session is already active.",
    "SESSION_CHANGED": "The session binding changed.",
    "SESSION_DATA_INVALID": "Session data is invalid.",
    "SESSION_LOCK_FAILED": "The session lock operation failed.",
    "SESSION_LOCK_TIMEOUT": "Session lock acquisition timed out.",
    "SESSION_NOT_ACTIVE": "The session is not active; start it first.",
    "SESSION_NOT_FOUND": "The session was not found.",
    "SESSION_PATH_UNSAFE": "The session storage path is unsafe.",
    "SESSION_READ_FAILED": "Session data could not be read.",
    "SESSION_RESTART_INVALID": "Session restart data is invalid.",
    "SESSION_WRITE_FAILED": "Session data could not be written.",
    "SOFT_EVALUATION_BINDING_MISMATCH": (
        "The soft-evaluation identity bindings do not match."
    ),
    "SOFT_EVALUATION_CURRENTNESS_MUTATION": (
        "A soft-evaluation currentness input changed during validation."
    ),
    "SOFT_EVALUATION_DUPLICATE_SAMPLE": (
        "The soft-evaluation input contains a duplicate sample."
    ),
    "SOFT_EVALUATION_FINDING_LIMIT": (
        "The soft-evaluation findings exceed the report limit."
    ),
    "SOFT_EVALUATION_INPUT_MUTATION": (
        "The soft-evaluation input changed during aggregation."
    ),
    "SOFT_EVALUATION_REPORT_INVALID": "The soft-evaluation report is invalid.",
    "SOFT_EVALUATION_RESERVED_FINDING": (
        "The evaluator used a finding code reserved for the aggregator."
    ),
    "SOFT_THRESHOLD_PROFILE_INAPPLICABLE": (
        "The soft-evaluation samples do not fit the threshold profile: "
        "single-locale-release takes one locale and no cross-language samples."
    ),
    "SOFT_THRESHOLD_PROFILE_UNSUPPORTED": (
        "The soft-evaluation threshold profile is unsupported."
    ),
    "STATE_BUSY": "Relationship state is busy.",
    "STATE_CAPACITY_EXCEEDED": "Relationship state capacity was exceeded.",
    "STATE_JOURNAL_INVALID": "The session event journal is invalid.",
    "UNKNOWN_SCENARIO": "The requested scenario is not available in this pack.",
    "UNSAFE_DRAFT_PATH": (
        "The character draft destination contains an unsafe filesystem path."
    ),
    "UNSUPPORTED_LOCALE": "The requested locale is not available.",
}


@dataclass(frozen=True, slots=True)
class _PathIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int
    file_type: int
    links: int


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    path: Path
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True, slots=True)
class _ReportOutput:
    target: Path
    directories: tuple[_DirectoryIdentity, ...]
    initial_target: _PathIdentity | None


def _leaf_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kokorox")
    parser.add_argument("--version", action="version", version=f"kokorox {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    pack = commands.add_parser("pack")
    pack_commands = pack.add_subparsers(dest="pack_command", required=True)
    pack_compile = pack_commands.add_parser("compile")
    pack_compile.add_argument("pack_path")
    _leaf_json(pack_compile)
    pack_validate = pack_commands.add_parser("validate")
    pack_validate.add_argument("pack_path")
    _leaf_json(pack_validate)
    pack_test = pack_commands.add_parser("test")
    pack_test.add_argument("source_dir")
    pack_test.add_argument("--request", required=True)
    pack_test.add_argument("--research-bundle")
    pack_test.add_argument("--out", required=True)
    _leaf_json(pack_test)
    pack_soft_eval = pack_commands.add_parser("soft-eval")
    pack_soft_eval.add_argument("input")
    pack_soft_eval.add_argument("--out", required=True)
    # A pack authored in one locale is judged without the cross-language
    # dimension; promotion checks that the pack really declares only one.
    pack_soft_eval.add_argument(
        "--profile",
        choices=("default-release", "single-locale-release"),
        default="default-release",
    )
    _leaf_json(pack_soft_eval)
    pack_promote = pack_commands.add_parser("promote")
    pack_promote.add_argument("source_dir")
    pack_promote.add_argument(
        "--target",
        choices=("reviewed", "verified"),
        required=True,
    )
    pack_promote.add_argument("--promotion-id", required=True)
    pack_promote.add_argument("--request", required=True)
    pack_promote.add_argument("--hard-report", required=True)
    pack_promote.add_argument("--review", required=True)
    pack_promote.add_argument("--previous")
    pack_promote.add_argument("--soft-input")
    pack_promote.add_argument("--soft-report")
    pack_promote.add_argument("--research-bundle")
    pack_promote.add_argument("--out", required=True)
    _leaf_json(pack_promote)
    publication_check = pack_commands.add_parser("publication-check")
    publication_check.add_argument("source_dir")
    publication_check.add_argument("--promotion", required=True)
    publication_check.add_argument("--request", required=True)
    publication_check.add_argument("--hard-report", required=True)
    publication_check.add_argument("--review", required=True)
    publication_check.add_argument("--previous", required=True)
    publication_check.add_argument("--soft-input", required=True)
    publication_check.add_argument("--soft-report", required=True)
    publication_check.add_argument("--research-bundle")
    publication_check.add_argument(
        "--visibility", choices=("private", "public_candidate"), required=True
    )
    publication_check.add_argument("--compliance")
    publication_check.add_argument("--out", required=True)
    _leaf_json(publication_check)

    character = commands.add_parser("character")
    character_commands = character.add_subparsers(
        dest="character_command", required=True
    )
    character_request = character_commands.add_parser("request")
    request_commands = character_request.add_subparsers(
        dest="request_command", required=True
    )
    request_validate = request_commands.add_parser("validate")
    request_validate.add_argument("--input", required=True)
    _leaf_json(request_validate)
    character_draft = character_commands.add_parser("draft")
    draft_commands = character_draft.add_subparsers(
        dest="draft_command", required=True
    )
    for name in ("validate", "compile"):
        draft_command = draft_commands.add_parser(name)
        draft_command.add_argument("--request", required=True)
        draft_command.add_argument("--pack", required=True)
        draft_command.add_argument("--research-bundle")
        _leaf_json(draft_command)

    research = commands.add_parser("research")
    research_groups = research.add_subparsers(
        dest="research_group", required=True
    )
    research_request = research_groups.add_parser("request")
    research_request_commands = research_request.add_subparsers(
        dest="research_request_command", required=True
    )
    research_request_validate = research_request_commands.add_parser("validate")
    research_request_validate.add_argument("--input", required=True)
    _leaf_json(research_request_validate)
    research_workspace = research_groups.add_parser("workspace")
    research_workspace_commands = research_workspace.add_subparsers(
        dest="research_workspace_command", required=True
    )
    research_workspace_validate = research_workspace_commands.add_parser("validate")
    research_workspace_validate.add_argument("--workspace", required=True)
    _leaf_json(research_workspace_validate)
    research_bundle = research_groups.add_parser("bundle")
    research_bundle_commands = research_bundle.add_subparsers(
        dest="research_bundle_command", required=True
    )
    research_bundle_compile = research_bundle_commands.add_parser("compile")
    research_bundle_compile.add_argument("--workspace", required=True)
    _leaf_json(research_bundle_compile)
    research_bundle_validate = research_bundle_commands.add_parser("validate")
    research_bundle_validate.add_argument("--bundle", required=True)
    _leaf_json(research_bundle_validate)

    config = commands.add_parser("config")
    config_commands = config.add_subparsers(
        dest="config_command", required=True
    )
    config_default = config_commands.add_parser("default")
    default_commands = config_default.add_subparsers(
        dest="default_command", required=True
    )
    default_set = default_commands.add_parser("set")
    default_set.add_argument("--character", required=True)
    default_set.add_argument("--namespace", default="original")
    default_set.add_argument("--version")
    for default_command in (
        default_set,
        default_commands.add_parser("show"),
        default_commands.add_parser("clear"),
    ):
        default_command.add_argument(
            "--scope",
            choices=("global", "workspace"),
            default="global",
        )
        default_command.add_argument("--workspace")
        _leaf_json(default_command)

    session = commands.add_parser("session")
    session_commands = session.add_subparsers(dest="session_command", required=True)
    session_start = session_commands.add_parser("start")
    session_start.add_argument("--character")
    session_start.add_argument("--session", required=True)
    session_start.add_argument("--workspace")
    _leaf_json(session_start)
    session_show = session_commands.add_parser("show")
    session_show.add_argument("--session")
    _leaf_json(session_show)
    session_end = session_commands.add_parser("end")
    session_end.add_argument("--session", required=True)
    _leaf_json(session_end)

    policy = commands.add_parser("policy")
    policy_commands = policy.add_subparsers(dest="policy_command", required=True)
    policy_compile = policy_commands.add_parser("compile")
    policy_compile.add_argument("--input", required=True)
    _leaf_json(policy_compile)

    runtime = commands.add_parser("runtime")
    runtime_commands = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_context = runtime_commands.add_parser("context")
    runtime_context.add_argument("--session", required=True)
    runtime_context.add_argument("--locale", required=True)
    runtime_context.add_argument("--scenario", required=True)
    _leaf_json(runtime_context)
    runtime_plan = runtime_commands.add_parser("plan")
    runtime_plan.add_argument("--semantic", required=True)
    runtime_plan.add_argument("--policy", required=True)
    runtime_plan.add_argument("--expression-intent")
    # The pack's own lines live in the runtime context, so a plan that is to
    # carry one has to be shown the context that holds it.
    runtime_plan.add_argument("--context")
    _leaf_json(runtime_plan)
    runtime_validate = runtime_commands.add_parser("validate")
    runtime_validate.add_argument("--semantic", required=True)
    runtime_validate.add_argument("--plan", required=True)
    runtime_validate.add_argument("--rendered", required=True)
    # Validation is stateless, so the caller carries the retry count that
    # decides which rung of the fallback ladder `fallback_level` reports.
    runtime_validate.add_argument("--attempt", type=int, default=0)
    _leaf_json(runtime_validate)

    state = commands.add_parser("state")
    state_commands = state.add_subparsers(dest="state_command", required=True)
    for name in ("preview", "apply"):
        state_command = state_commands.add_parser(name)
        state_command.add_argument("--session", required=True)
        state_command.add_argument("--event", required=True)
        _leaf_json(state_command)
    add_standalone_parsers(
        commands,
        pack_commands,
        state_commands,
        _leaf_json,
    )
    return parser


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite number")


def _input_error(code: str, message: str) -> KokoroError:
    return KokoroError(code, message)


def _input_identity(path_stat: os.stat_result) -> _PathIdentity:
    return _PathIdentity(
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        size=path_stat.st_size,
        modified_ns=path_stat.st_mtime_ns,
        file_type=stat.S_IFMT(path_stat.st_mode),
        links=path_stat.st_nlink,
    )


def _read_json(path: Path, *, max_bytes: int = JSON_INPUT_MAX_BYTES) -> Any:
    try:
        path_stat = path.lstat()
    except FileNotFoundError as error:
        raise _input_error("INPUT_NOT_FOUND", "Input file was not found.") from error
    except OSError as error:
        raise _input_error(
            "INPUT_READ_FAILED",
            "Input file could not be read.",
        ) from error
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    is_junction = getattr(path, "is_junction", None)
    try:
        junction = bool(is_junction is not None and is_junction())
    except OSError as error:
        raise _input_error(
            "INPUT_READ_FAILED",
            "Input file could not be read.",
        ) from error
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or junction
        or bool(reparse and attributes & reparse)
        or path_stat.st_nlink != 1
    ):
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.")
    if path_stat.st_size > max_bytes:
        raise _input_error("INPUT_TOO_LARGE", "Input file exceeds the size limit.")
    initial_identity = _input_identity(path_stat)
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            opened_identity = _input_identity(os.fstat(handle.fileno()))
            if opened_identity != initial_identity:
                raise _input_error(
                    "INPUT_PATH_UNSAFE",
                    "Input file path is unsafe.",
                )
            contents = handle.read(max_bytes + 1)
            handle.seek(0)
            repeated = handle.read(max_bytes + 1)
            final_open_identity = _input_identity(os.fstat(handle.fileno()))
    except FileNotFoundError as error:
        raise _input_error("INPUT_NOT_FOUND", "Input file was not found.") from error
    except KokoroError:
        raise
    except OSError as error:
        raise _input_error(
            "INPUT_READ_FAILED",
            "Input file could not be read.",
        ) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    if len(contents) > max_bytes:
        raise _input_error("INPUT_TOO_LARGE", "Input file exceeds the size limit.")
    if contents != repeated or final_open_identity != initial_identity:
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.")
    try:
        final_stat = path.lstat()
    except OSError as error:
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.") from error
    if _input_identity(final_stat) != initial_identity:
        raise _input_error("INPUT_PATH_UNSAFE", "Input file path is unsafe.")
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise _input_error(
            "INPUT_INVALID_JSON",
            "Input file contains invalid JSON.",
        ) from error
    if find_json_incompatibility(value) is not None:
        raise _input_error("INPUT_INVALID_JSON", "Input file contains invalid JSON.")
    return value


def _output_unsafe() -> KokoroError:
    return KokoroError("REPORT_OUTPUT_PATH_UNSAFE", "Report output path is unsafe.")


def _output_redirect(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    is_junction = getattr(path, "is_junction", None)
    try:
        if is_junction is not None and is_junction():
            return True
    except OSError as error:
        raise _output_unsafe() from error
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(reparse and attributes & reparse)


def _directory_identity(path: Path) -> _DirectoryIdentity:
    try:
        path_stat = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise _output_unsafe() from error
    if (
        not stat.S_ISDIR(path_stat.st_mode)
        or _output_redirect(path, path_stat)
        or resolved != path
    ):
        raise _output_unsafe()
    return _DirectoryIdentity(
        path=path,
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        file_type=stat.S_IFMT(path_stat.st_mode),
    )


def _path_identity(path: Path) -> _PathIdentity | None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _output_unsafe() from error
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or _output_redirect(path, path_stat)
        or path_stat.st_nlink != 1
    ):
        raise _output_unsafe()
    return _PathIdentity(
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        size=path_stat.st_size,
        modified_ns=path_stat.st_mtime_ns,
        file_type=stat.S_IFMT(path_stat.st_mode),
        links=path_stat.st_nlink,
    )


def _assert_safe_output_component(component: str) -> None:
    if (
        component.rstrip(" .") != component
        or ":" in component
        or any(ord(character) < 32 for character in component)
        or component.split(".", 1)[0].lower()
        in _WINDOWS_RESERVED_OUTPUT_NAMES
    ):
        raise _output_unsafe()


def _resolve_report_target(settings: Settings, raw_path: str) -> tuple[Path, Path]:
    root = Path(os.path.abspath(settings.data_dir / "reports"))
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise _output_unsafe() from error
    _directory_identity(root)

    supplied = Path(raw_path).expanduser()
    if ".." in supplied.parts:
        raise _output_unsafe()
    for component in supplied.parts:
        if component != supplied.anchor:
            _assert_safe_output_component(component)
    target = Path(
        os.path.abspath(supplied if supplied.is_absolute() else root / supplied)
    )
    if target == root or not target.is_relative_to(root):
        raise _output_unsafe()
    for component in target.relative_to(root).parts:
        _assert_safe_output_component(component)
    if target.suffix.lower() != ".json":
        raise _output_unsafe()
    try:
        resolved = target.resolve(strict=False)
    except OSError as error:
        raise _output_unsafe() from error
    if not resolved.is_relative_to(root):
        raise _output_unsafe()
    return target, root


def _assert_output_not_alias(
    target: Path,
    *,
    inputs: tuple[Path, ...],
    protected_roots: tuple[Path, ...],
) -> None:
    target_resolved = target.resolve(strict=False)
    for input_path in inputs:
        try:
            if target_resolved == input_path.resolve(strict=False):
                raise _output_unsafe()
        except OSError as error:
            raise _output_unsafe() from error
    for protected_root in protected_roots:
        try:
            if target_resolved.is_relative_to(protected_root.resolve(strict=True)):
                raise _output_unsafe()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise _output_unsafe() from error


def _prepare_report_output(
    settings: Settings,
    raw_path: str,
    *,
    inputs: tuple[Path, ...] = (),
    protected_roots: tuple[Path, ...] = (),
) -> _ReportOutput:
    target, root = _resolve_report_target(settings, raw_path)
    _assert_output_not_alias(
        target,
        inputs=inputs,
        protected_roots=protected_roots,
    )

    directories = [_directory_identity(root)]
    cursor = root
    for component in target.parent.relative_to(root).parts:
        cursor = cursor / component
        try:
            cursor.mkdir()
        except FileExistsError:
            pass
        except OSError as error:
            raise _output_unsafe() from error
        directories.append(_directory_identity(cursor))
    return _ReportOutput(
        target=target,
        directories=tuple(directories),
        initial_target=_path_identity(target),
    )


def _assert_output_directories(output: _ReportOutput) -> None:
    for expected in output.directories:
        actual = _directory_identity(expected.path)
        if actual != expected:
            raise _output_unsafe()


def _assert_report_output_current(output: _ReportOutput) -> None:
    _assert_output_directories(output)
    if _path_identity(output.target) != output.initial_target:
        raise KokoroError(
            "REPORT_OUTPUT_CHANGED",
            "Report output changed during publication.",
        )


def _validated_artifact(
    value: dict[str, Any],
    schemas: SchemaRegistry,
    schema_name: str,
) -> tuple[dict[str, Any], bytes]:
    payload = canonical_bytes(value)
    snapshot = cast(dict[str, Any], json.loads(payload))
    schemas.validate(schema_name, cast(dict[str, Any], json.loads(payload)))
    schemas.validate(schema_name, cast(dict[str, Any], json.loads(payload)))
    if canonical_bytes(value) != payload:
        raise KokoroError(
            "REPORT_OUTPUT_CHANGED",
            "Report output changed during publication.",
        )
    return snapshot, payload


def _publish_report_output(
    output: _ReportOutput,
    value: dict[str, Any],
    schemas: SchemaRegistry,
    schema_name: str,
) -> tuple[dict[str, Any], str]:
    snapshot, payload = _validated_artifact(value, schemas, schema_name)
    _assert_report_output_current(output)
    try:
        write_compiled_pack(snapshot, output.target)
    except OSError as error:
        raise KokoroError(
            "REPORT_OUTPUT_WRITE_FAILED",
            "Report output could not be written.",
        ) from error
    _assert_output_directories(output)
    expected = payload + b"\n"
    try:
        actual = output.target.read_bytes()
    except OSError as error:
        raise KokoroError(
            "REPORT_OUTPUT_WRITE_FAILED",
            "Report output could not be written.",
        ) from error
    if actual != expected or _path_identity(output.target) is None:
        raise KokoroError(
            "REPORT_OUTPUT_CHANGED",
            "Report output changed during publication.",
        )
    _assert_output_directories(output)
    try:
        if output.target.read_bytes() != expected:
            raise KokoroError(
                "REPORT_OUTPUT_CHANGED",
                "Report output changed during publication.",
            )
    except OSError as error:
        raise KokoroError(
            "REPORT_OUTPUT_WRITE_FAILED",
            "Report output could not be written.",
        ) from error
    return snapshot, sha256(payload).hexdigest()


def _path_is_redirect(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        try:
            path_stat = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return False
    except OSError as error:
        raise KokoroError(
            "COMPILED_PATH_UNSAFE",
            "Compiled artifact path is unsafe.",
        ) from error
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(reparse and attributes & reparse)


def _compiled_directory(settings: Settings, *, create: bool) -> Path:
    root = settings.data_dir.resolve(strict=False)
    directory = root / "compiled"
    if _path_is_redirect(directory):
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    try:
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        resolved = directory.resolve(strict=False)
    except OSError as error:
        raise KokoroError(
            "COMPILED_PATH_UNSAFE",
            "Compiled artifact path is unsafe.",
        ) from error
    if not resolved.is_relative_to(root) or _path_is_redirect(directory):
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    if directory.exists() and not directory.is_dir():
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    return directory


def _compiled_file(settings: Settings, raw_path: str) -> Path:
    directory = _compiled_directory(settings, create=False)
    directory_resolved = directory.resolve(strict=False)
    path = Path(raw_path).expanduser()
    if _path_is_redirect(path):
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    try:
        resolved = path.resolve(strict=True)
        path_stat = path.stat(follow_symlinks=False)
    except (FileNotFoundError, OSError) as error:
        raise KokoroError(
            "COMPILED_PATH_UNSAFE",
            "Compiled artifact path is unsafe.",
        ) from error
    if (
        resolved.parent != directory_resolved
        or not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_nlink != 1
        or _path_is_redirect(path)
    ):
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    return resolved


def _validated_compiled(path: Path, schemas: SchemaRegistry) -> dict[str, Any]:
    value = _read_json(path)
    schemas.validate("compiled-pack", value)
    artifact_id = value["artifact_id"]
    components = artifact_id.split("/")
    if (
        len(components) != 3
        or not components[0]
        or components[1] != value["character_id"]
        or components[2] != "compiled"
    ):
        raise KokoroError(
            "COMPILED_IDENTITY_MISMATCH",
            "Compiled artifact identity does not match.",
        )
    return value


def _find_compiled(
    settings: Settings,
    schemas: SchemaRegistry,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    directory = _compiled_directory(settings, create=False)
    if not directory.exists():
        raise KokoroError(
            "COMPILED_PACK_NOT_FOUND",
            "Compiled artifact was not found for the session.",
        )
    matches: list[dict[str, Any]] = []
    aggregate = 0
    try:
        entries: list[os.DirEntry[str]] = []
        with os.scandir(directory) as iterator:
            for entry in iterator:
                entries.append(entry)
                if len(entries) > COMPILED_SCAN_MAX_FILES:
                    raise KokoroError(
                        "COMPILED_SCAN_LIMIT",
                        "Compiled artifact scan limit was exceeded.",
                    )
    except KokoroError:
        raise
    except OSError as error:
        raise KokoroError(
            "COMPILED_SCAN_FAILED",
            "Compiled artifacts could not be scanned.",
        ) from error
    for entry in sorted(entries, key=lambda item: item.name):
        path = Path(entry.path)
        try:
            if (
                entry.is_symlink()
                or not entry.is_file(follow_symlinks=False)
                or _path_is_redirect(path)
            ):
                raise KokoroError(
                    "COMPILED_PATH_UNSAFE",
                    "Compiled artifact path is unsafe.",
                )
            entry_stat = path.stat(follow_symlinks=False)
            if entry_stat.st_nlink != 1:
                raise KokoroError(
                    "COMPILED_PATH_UNSAFE",
                    "Compiled artifact path is unsafe.",
                )
            size = entry_stat.st_size
        except KokoroError:
            raise
        except OSError as error:
            raise KokoroError(
                "COMPILED_SCAN_FAILED",
                "Compiled artifacts could not be scanned.",
            ) from error
        aggregate += size
        if aggregate > COMPILED_SCAN_MAX_BYTES:
            raise KokoroError(
                "COMPILED_SCAN_LIMIT",
                "Compiled artifact scan limit was exceeded.",
            )
        if path.suffix != ".json":
            raise KokoroError(
                "COMPILED_PATH_UNSAFE",
                "Compiled artifact path is unsafe.",
            )
        compiled = _validated_compiled(path, schemas)
        if compiled["source_hash"] == manifest["compiled_pack_hash"]:
            if (
                compiled["character_id"] != manifest["character_id"]
                or compiled["character_version"]
                != manifest["character_version"]
            ):
                raise KokoroError(
                    "COMPILED_IDENTITY_MISMATCH",
                    "Compiled artifact identity does not match.",
                )
            matches.append(compiled)
    if not matches:
        raise KokoroError(
            "COMPILED_PACK_NOT_FOUND",
            "Compiled artifact was not found for the session.",
        )
    if len(matches) != 1:
        raise KokoroError(
            "COMPILED_PACK_AMBIGUOUS",
            "Multiple compiled artifacts match the session.",
        )
    return matches[0]


def _handle_pack_compile(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    source = load_source_pack(Path(args.pack_path), schemas)
    compiled = compile_pack(source, schemas)
    directory = _compiled_directory(settings, create=True)
    filename = (
        f"{compiled['character_id']}-"
        f"{compiled['source_hash'][:SOURCE_HASH_PREFIX_LENGTH]}.json"
    )
    target = directory / filename
    if _path_is_redirect(target):
        raise KokoroError("COMPILED_PATH_UNSAFE", "Compiled artifact path is unsafe.")
    try:
        if target.exists():
            target_stat = target.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(target_stat.st_mode)
                or target_stat.st_nlink != 1
            ):
                raise KokoroError(
                    "COMPILED_PATH_UNSAFE",
                    "Compiled artifact path is unsafe.",
                )
    except KokoroError:
        raise
    except OSError as error:
        raise KokoroError(
            "COMPILED_PATH_UNSAFE",
            "Compiled artifact path is unsafe.",
        ) from error
    try:
        write_compiled_pack(compiled, target)
    except OSError as error:
        raise KokoroError(
            "COMPILED_WRITE_FAILED",
            "Compiled artifact could not be written.",
        ) from error
    return {
        "ok": True,
        "path": str(target.resolve()),
        "character_id": compiled["character_id"],
        "character_version": compiled["character_version"],
        "source_hash": compiled["source_hash"],
        "artifact_id": compiled["artifact_id"],
    }


def _handle_pack_validate(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del settings
    source = load_source_pack(Path(args.pack_path), schemas)
    return {
        "ok": True,
        "artifact_id": source["artifact_id"],
        "character_id": source["character_id"],
        "character_version": source["character_version"],
    }


def _argument_path(raw_path: str) -> Path:
    return Path(os.path.abspath(Path(raw_path).expanduser()))


def _read_object(path: Path, code: str, message: str) -> dict[str, Any]:
    value = _read_json(path)
    if not isinstance(value, dict):
        raise KokoroError(code, message)
    return value


def _optional_research_bundle(
    raw_path: str | None,
    schemas: SchemaRegistry,
) -> dict[str, Any] | None:
    if raw_path is None:
        return None
    return load_published_research_bundle(_argument_path(raw_path), schemas)


def _handle_pack_test(
    args: argparse.Namespace,
    settings: Settings,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    source_root = _argument_path(args.source_dir)
    request_path = _argument_path(args.request)
    output = _prepare_report_output(
        settings,
        args.out,
        inputs=(request_path,),
        protected_roots=(
            source_root,
            *(
                (_argument_path(args.research_bundle),)
                if args.research_bundle is not None
                else ()
            ),
        ),
    )
    request = _read_object(
        request_path,
        "SCHEMA_VALIDATION_FAILED",
        "Input did not match the required schema.",
    )
    research_bundle = _optional_research_bundle(args.research_bundle, schemas)
    report = run_hard_validation(
        source_root,
        request,
        schemas,
        research_bundle=research_bundle,
    )
    report, report_hash = _publish_report_output(
        output,
        report,
        schemas,
        "pack-hard-validation-report",
    )
    return {
        "ok": True,
        "path": str(output.target),
        "artifact_id": report["artifact_id"],
        "passed": report["passed"],
        "source_hash": report["source_hash"],
        "compiled_hash": report["compiled_hash"],
        "report_hash": report_hash,
    }


def _handle_pack_soft_eval(
    args: argparse.Namespace,
    settings: Settings,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    input_path = _argument_path(args.input)
    output = _prepare_report_output(
        settings,
        args.out,
        inputs=(input_path,),
    )
    evaluation_input = _read_object(
        input_path,
        "SOFT_EVALUATION_INPUT_INVALID",
        "Soft-evaluation input is invalid.",
    )
    report = aggregate_soft_evaluation(
        evaluation_input, schemas, threshold_profile_id=args.profile
    )
    report, report_hash = _publish_report_output(
        output,
        report,
        schemas,
        "pack-soft-evaluation-report",
    )
    return {
        "ok": True,
        "path": str(output.target),
        "artifact_id": report["artifact_id"],
        "passed": report["passed"],
        "report_hash": report_hash,
    }


def _promotion_input_paths(args: argparse.Namespace) -> tuple[Path, ...]:
    raw_paths = (
        args.request,
        args.hard_report,
        args.review,
        args.previous,
        args.soft_input,
        args.soft_report,
    )
    return tuple(_argument_path(value) for value in raw_paths if value is not None)


def _handle_pack_promote(
    args: argparse.Namespace,
    settings: Settings,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    source_root = _argument_path(args.source_dir)
    input_paths = _promotion_input_paths(args)
    requested_target, reports_root = _resolve_report_target(settings, args.out)
    _assert_output_not_alias(
        requested_target,
        inputs=input_paths,
        protected_roots=(
            source_root,
            *(
                (_argument_path(args.research_bundle),)
                if args.research_bundle is not None
                else ()
            ),
        ),
    )
    request = _read_object(
        _argument_path(args.request),
        "PACK_PROMOTION_INPUT_INVALID",
        "A promotion input is invalid.",
    )
    hard_report = _read_object(
        _argument_path(args.hard_report),
        "PACK_PROMOTION_INPUT_INVALID",
        "A promotion input is invalid.",
    )
    review = _read_object(
        _argument_path(args.review),
        "PACK_PROMOTION_INPUT_INVALID",
        "A promotion input is invalid.",
    )
    previous = (
        None
        if args.previous is None
        else _read_object(
            _argument_path(args.previous),
            "PACK_PROMOTION_INPUT_INVALID",
            "A promotion input is invalid.",
        )
    )
    soft_input = (
        None
        if args.soft_input is None
        else _read_object(
            _argument_path(args.soft_input),
            "PACK_PROMOTION_INPUT_INVALID",
            "A promotion input is invalid.",
        )
    )
    soft_report = (
        None
        if args.soft_report is None
        else _read_object(
            _argument_path(args.soft_report),
            "PACK_PROMOTION_INPUT_INVALID",
            "A promotion input is invalid.",
        )
    )
    research_bundle = _optional_research_bundle(args.research_bundle, schemas)
    record = create_promotion_record(
        source_root,
        request,
        hard_report,
        review,
        schemas,
        target=args.target,
        promotion_id=args.promotion_id,
        research_bundle=research_bundle,
        previous_promotion=previous,
        soft_evaluation_input=soft_input,
        soft_evaluation_report=soft_report,
    )
    record, record_bytes = _validated_artifact(
        record,
        schemas,
        "pack-promotion-record",
    )
    expected_target = (
        reports_root
        / "promotions"
        / record["character_id"]
        / record["promotion_id"]
        / "promotion.json"
    )
    if os.path.normcase(str(requested_target)) != os.path.normcase(
        str(expected_target)
    ):
        raise KokoroError(
            "REPORT_OUTPUT_MISMATCH",
            "The requested report output is invalid.",
        )
    actual_target = publish_promotion_record(
        settings.data_dir,
        record,
        review,
        schemas,
    )
    if os.path.normcase(str(actual_target)) != os.path.normcase(
        str(expected_target)
    ):
        raise KokoroError(
            "REPORT_OUTPUT_MISMATCH",
            "The requested report output is invalid.",
        )
    stored = _read_object(
        actual_target,
        "PACK_PROMOTION_BUNDLE_INVALID",
        "The stored promotion bundle is invalid.",
    )
    schemas.validate("pack-promotion-record", stored)
    if canonical_bytes(stored) != record_bytes:
        raise KokoroError(
            "PACK_PROMOTION_BUNDLE_INVALID",
            "The stored promotion bundle is invalid.",
        )
    return {
        "ok": True,
        "path": str(actual_target),
        "bundle_path": str(actual_target.parent),
        "artifact_id": record["artifact_id"],
        "promotion_id": record["promotion_id"],
        "to_status": record["to_status"],
        "activation_allowed": record["activation_allowed"],
        "record_hash": sha256(record_bytes).hexdigest(),
    }


def _publication_input_paths(args: argparse.Namespace) -> tuple[Path, ...]:
    raw_paths = (
        args.promotion,
        args.request,
        args.hard_report,
        args.review,
        args.previous,
        args.soft_input,
        args.soft_report,
        args.compliance,
    )
    return tuple(_argument_path(value) for value in raw_paths if value is not None)


def _handle_pack_publication_check(
    args: argparse.Namespace,
    settings: Settings,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    source_root = _argument_path(args.source_dir)
    input_paths = _publication_input_paths(args)
    output = _prepare_report_output(
        settings,
        args.out,
        inputs=input_paths,
        protected_roots=(
            source_root,
            *(
                (_argument_path(args.research_bundle),)
                if args.research_bundle is not None
                else ()
            ),
        ),
    )
    values = {
        "promotion": _read_object(
            _argument_path(args.promotion),
            "PACK_PUBLICATION_PROMOTION_INVALID",
            "The verified promotion record is invalid.",
        ),
        "request": _read_object(
            _argument_path(args.request),
            "PACK_PUBLICATION_PROMOTION_EVIDENCE_INVALID",
            "The promotion evidence is invalid.",
        ),
        "hard_report": _read_object(
            _argument_path(args.hard_report),
            "PACK_PUBLICATION_PROMOTION_EVIDENCE_INVALID",
            "The promotion evidence is invalid.",
        ),
        "review_attestation": _read_object(
            _argument_path(args.review),
            "PACK_PUBLICATION_PROMOTION_EVIDENCE_INVALID",
            "The promotion evidence is invalid.",
        ),
        "previous_promotion": _read_object(
            _argument_path(args.previous),
            "PACK_PUBLICATION_PROMOTION_EVIDENCE_INVALID",
            "The promotion evidence is invalid.",
        ),
        "soft_evaluation_input": _read_object(
            _argument_path(args.soft_input),
            "PACK_PUBLICATION_PROMOTION_EVIDENCE_INVALID",
            "The promotion evidence is invalid.",
        ),
        "soft_evaluation_report": _read_object(
            _argument_path(args.soft_report),
            "PACK_PUBLICATION_PROMOTION_EVIDENCE_INVALID",
            "The promotion evidence is invalid.",
        ),
    }
    research_bundle = _optional_research_bundle(args.research_bundle, schemas)
    evidence = {
        "request": values["request"],
        "hard_report": values["hard_report"],
        "review_attestation": values["review_attestation"],
        "previous_promotion": values["previous_promotion"],
        "soft_evaluation_input": values["soft_evaluation_input"],
        "soft_evaluation_report": values["soft_evaluation_report"],
        **(
            {"research_bundle": research_bundle}
            if research_bundle is not None
            else {}
        ),
    }
    compliance = (
        None
        if args.compliance is None
        else _read_object(
            _argument_path(args.compliance),
            "PACK_PUBLICATION_COMPLIANCE_INVALID",
            "The publication compliance attestation is invalid.",
        )
    )
    report = assess_publication_readiness(
        source_root,
        values["promotion"],
        schemas,
        promotion_evidence=evidence,
        requested_visibility=args.visibility,
        compliance_attestation=compliance,
    )
    report, report_hash = _publish_report_output(
        output,
        report,
        schemas,
        "pack-publication-readiness-report",
    )
    return {
        "ok": True,
        "path": str(output.target),
        "artifact_id": report["artifact_id"],
        "ready_for_private_export": report["ready_for_private_export"],
        "ready_for_publication": report["ready_for_publication"],
        "blockers": report["blockers"],
        "report_hash": report_hash,
    }


def _handle_character_request_validate(
    args: argparse.Namespace,
    settings: Settings | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    del settings
    request = normalize_build_request(_read_json(Path(args.input)), schemas)
    return {"ok": True, "request": request}


def _handle_research_request_validate(
    args: argparse.Namespace,
    settings: Settings | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    del settings
    request = normalize_research_request(_read_json(Path(args.input)), schemas)
    return {"ok": True, "request": request}


def _handle_research_workspace_validate(
    args: argparse.Namespace,
    settings: Settings | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    del settings
    workspace = load_research_workspace(Path(args.workspace), schemas)
    report = validate_research_workspace(workspace, schemas)
    return {
        "ok": True,
        "valid": report["valid"],
        "workspace_hash": workspace.workspace_hash,
        "validation_report": report,
    }


def _public_research_bundle_summary(
    bundle: dict[str, Any],
    coverage_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_id": bundle["artifact_id"],
        "request_hash": bundle["request_hash"],
        "workspace_hash": bundle["workspace_hash"],
        "validation_report_hash": bundle["validation_report_hash"],
        "bundle_hash": bundle["bundle_hash"],
        "build_status": bundle["build_status"],
        "visibility": bundle["visibility"],
        "activation_allowed": bundle["activation_allowed"],
        "authoring_allowed": bundle["authoring_allowed"],
        "coverage_summary": coverage_summary,
        "conflicts": bundle["conflicts"],
        "limitations": bundle["limitations"],
        "blocking_reasons": bundle["blocking_reasons"],
    }


def _research_coverage_summary(bundle: dict[str, Any]) -> dict[str, int]:
    summary = {
        "covered": 0,
        "partial": 0,
        "missing": 0,
        "blocked": 0,
    }
    for topic in bundle["coverage"]["topics"]:
        summary[topic["status"]] += 1
    return summary


def _handle_research_bundle_compile(
    args: argparse.Namespace,
    settings: Settings,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    workspace_path = Path(args.workspace)
    workspace = load_research_workspace(workspace_path, schemas)
    report = validate_research_workspace(workspace, schemas)
    if not report["valid"]:
        raise KokoroError(
            "RESEARCH_VALIDATION_FAILED",
            "Research validation failed.",
        )
    bundle = build_research_bundle(workspace, report)
    target = publish_research_bundle(
        settings.data_dir,
        workspace_path,
        workspace,
        report,
        bundle,
    )
    return {
        "ok": True,
        "path": str(target),
        **_public_research_bundle_summary(bundle, report["coverage_summary"]),
    }


def _handle_research_bundle_validate(
    args: argparse.Namespace,
    settings: Settings | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    del settings
    bundle = load_published_research_bundle(Path(args.bundle), schemas)
    return {
        "ok": True,
        "valid": True,
        **_public_research_bundle_summary(
            bundle,
            _research_coverage_summary(bundle),
        ),
    }


def _authoring_inputs(
    args: argparse.Namespace, schemas: SchemaRegistry
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any] | None,
]:
    request = normalize_build_request(_read_json(Path(args.request)), schemas)
    research_bundle = None
    if request["mode"] in {"researched", "hybrid"}:
        if not args.research_bundle:
            raise KokoroError(
                "RESEARCH_BUNDLE_REQUIRED",
                "An eligible Research Bundle is required for this authoring mode.",
            )
        research_bundle = load_published_research_bundle(
            Path(args.research_bundle), schemas
        )
    elif args.research_bundle:
        raise KokoroError(
            "RESEARCH_BUNDLE_UNEXPECTED",
            "This authoring mode does not accept a Research Bundle.",
        )
    source = load_source_pack(Path(args.pack), schemas)
    report = validate_authoring_pack(
        request,
        source,
        schemas,
        research_bundle=research_bundle,
    )
    return request, source, report, research_bundle


def _handle_character_draft_validate(
    args: argparse.Namespace,
    settings: Settings | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    del settings
    _request, _source, report, _research_bundle = _authoring_inputs(args, schemas)
    return {
        "ok": True,
        "valid": report["valid"],
        "validation_report": report,
    }


def _handle_character_draft_compile(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    request, source, report, research_bundle = _authoring_inputs(args, schemas)
    if not report["valid"]:
        raise KokoroError(
            "AUTHORING_VALIDATION_FAILED",
            "Character authoring validation failed.",
            # The report already names every hard failure; dropping them told
            # the caller only that something, somewhere, was wrong.
            details={
                "failures": sorted(
                    {item["code"] for item in report["hard_failures"]}
                )
            },
        )
    draft = build_character_draft(request, source, report)
    publication_inputs = (
        settings.data_dir,
        Path(args.pack),
        request,
        draft,
        report,
    )
    target = (
        publish_draft_bundle(*publication_inputs)
        if research_bundle is None
        else publish_draft_bundle(*publication_inputs, research_bundle)
    )
    return {
        "ok": True,
        "path": str(target),
        "artifact_id": draft["artifact_id"],
        "request_hash": draft["request_hash"],
        "source_pack_hash": draft["source_pack_hash"],
        "validation_report_hash": draft["validation_report_hash"],
        "build_status": draft["build_status"],
        "visibility": draft["visibility"],
        "activation_allowed": draft["activation_allowed"],
        "validation_report": report,
    }


def _handle_session_start(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    if args.character is not None:
        path = _compiled_file(settings, args.character)
        compiled = _validated_compiled(path, schemas)
    else:
        workspace_root = (
            _argument_path(args.workspace)
            if args.workspace is not None
            else None
        )
        selection = resolve_character_selection(
            settings.data_dir,
            schemas,
            workspace_root=workspace_root,
        )
        if selection.source == "none":
            raise KokoroError(
                "KARC_DEFAULT_NOT_CONFIGURED",
                "No character default is configured.",
            )
        compiled = _publish_selected_compiled_projection(
            settings,
            selection,
            schemas,
            workspace_root=workspace_root,
        )
    session = SessionStore(settings.data_dir).start(
        args.session,
        compiled["character_id"],
        compiled["character_version"],
        compiled["source_hash"],
    )
    return {"ok": True, "session": session}


def _publish_selected_compiled_projection(
    settings: Settings,
    selection: CharacterSelection,
    schemas: SchemaRegistry,
    *,
    workspace_root: Path | None,
) -> dict[str, Any]:
    source_snapshot = _load_selected_compiled_snapshot(
        settings.data_dir,
        selection,
        schemas,
        workspace_root=workspace_root,
    )
    compiled = source_snapshot.compiled
    payload = canonical_bytes(compiled)
    directory = _compiled_directory(settings, create=True)
    directory_identity = _compiled_directory_identity(directory)
    filename = (
        f"{compiled['character_id']}-"
        f"{compiled['source_hash'][:SOURCE_HASH_PREFIX_LENGTH]}.json"
    )
    target = directory / filename
    expected = payload + b"\n"
    projection_identity = _publish_compiled_projection(
        directory,
        directory_identity,
        target,
        compiled,
        expected,
    )
    _require_projection_current(
        directory,
        directory_identity,
        target,
        projection_identity,
        expected,
    )
    source_snapshot.audit()
    projected = _validated_compiled(target, schemas)
    _require_projection_current(
        directory,
        directory_identity,
        target,
        projection_identity,
        expected,
    )
    source_snapshot.audit()
    refreshed = load_selected_compiled(
        settings.data_dir,
        selection,
        schemas,
        workspace_root=workspace_root,
    )
    _require_projection_current(
        directory,
        directory_identity,
        target,
        projection_identity,
        expected,
    )
    source_snapshot.audit()
    if (
        canonical_bytes(projected) != payload
        or canonical_bytes(refreshed) != payload
    ):
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Character default input changed during projection.",
        )
    _require_projection_current(
        directory,
        directory_identity,
        target,
        projection_identity,
        expected,
    )
    source_snapshot.audit()
    return projected


def _require_projection_current(
    directory: Path,
    directory_identity: _DirectoryIdentity,
    target: Path,
    target_identity: _PathIdentity,
    expected: bytes,
) -> None:
    if _compiled_directory_identity(directory) != directory_identity:
        raise KokoroError(
            "COMPILED_PATH_UNSAFE",
            "Compiled artifact path is unsafe.",
        )
    try:
        payload = target.read_bytes()
    except OSError as error:
        raise KokoroError(
            "COMPILED_WRITE_FAILED",
            "Compiled artifact could not be read.",
        ) from error
    if _compiled_path_identity(target) != target_identity or payload != expected:
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Character default projection changed during validation.",
        )


def _compiled_directory_identity(path: Path) -> _DirectoryIdentity:
    try:
        return _directory_identity(path)
    except KokoroError as error:
        raise KokoroError(
            "COMPILED_PATH_UNSAFE",
            "Compiled artifact path is unsafe.",
        ) from error


def _compiled_path_identity(path: Path) -> _PathIdentity | None:
    try:
        return _path_identity(path)
    except KokoroError as error:
        raise KokoroError(
            "COMPILED_PATH_UNSAFE",
            "Compiled artifact path is unsafe.",
        ) from error


def _projection_node(identity: _PathIdentity) -> tuple[int, int, int]:
    return identity.device, identity.inode, identity.file_type


def _publish_compiled_projection(
    directory: Path,
    directory_identity: _DirectoryIdentity,
    target: Path,
    compiled: dict[str, Any],
    expected: bytes,
) -> _PathIdentity:
    existing = _compiled_path_identity(target)
    if existing is not None:
        _require_projection_current(
            directory,
            directory_identity,
            target,
            existing,
            expected,
        )
        return existing
    descriptor = -1
    staging: Path | None = None
    staging_node: tuple[int, int, int] | None = None
    try:
        descriptor, raw_staging = tempfile.mkstemp(
            prefix=f".{target.name}.staging-",
            dir=directory,
        )
        staging = Path(raw_staging)
        initial = _compiled_path_identity(staging)
        if initial is None:
            raise KokoroError(
                "COMPILED_PATH_UNSAFE",
                "Compiled artifact path is unsafe.",
            )
        staging_node = _projection_node(initial)
        os.close(descriptor)
        descriptor = -1
        _write_projection_staging(staging, expected, staging_node)
        written = _compiled_path_identity(staging)
        if (
            written is None
            or _projection_node(written) != staging_node
            or staging.read_bytes() != expected
        ):
            raise KokoroError(
                "KARC_DEFAULT_INPUT_MUTATION",
                "Character default projection changed during publication.",
            )
        if _compiled_directory_identity(directory) != directory_identity:
            raise KokoroError(
                "COMPILED_PATH_UNSAFE",
                "Compiled artifact path is unsafe.",
            )
        if _compiled_path_identity(target) is not None:
            raise KokoroError(
                "KARC_DEFAULT_INPUT_MUTATION",
                "Character default projection appeared concurrently.",
            )
        os.link(staging, target)
        staging.unlink()
        staging = None
        published = _compiled_path_identity(target)
        if published is None:
            raise KokoroError(
                "COMPILED_WRITE_FAILED",
                "Compiled artifact could not be written.",
            )
        _require_projection_current(
            directory,
            directory_identity,
            target,
            published,
            expected,
        )
        return published
    except KokoroError:
        raise
    except OSError as error:
        raise KokoroError(
            "COMPILED_WRITE_FAILED",
            "Compiled artifact could not be written.",
        ) from error
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if staging is not None:
            _cleanup_projection_staging(staging, staging_node)


def _write_projection_staging(
    path: Path,
    payload: bytes,
    node: tuple[int, int, int],
) -> None:
    flags = os.O_WRONLY | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        opened_node = (
            int(opened.st_dev),
            int(opened.st_ino),
            stat.S_IFMT(opened.st_mode),
        )
        if opened_node != node or int(opened.st_nlink) != 1:
            raise KokoroError(
                "KARC_DEFAULT_INPUT_MUTATION",
                "Character default projection staging changed.",
            )
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("projection write made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except KokoroError:
        raise
    except OSError as error:
        raise KokoroError(
            "COMPILED_WRITE_FAILED",
            "Compiled artifact could not be made durable.",
        ) from error
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _cleanup_projection_staging(
    path: Path,
    node: tuple[int, int, int] | None,
) -> None:
    current = _compiled_path_identity(path)
    if current is None:
        return
    if node is None or _projection_node(current) != node:
        raise KokoroError(
            "COMPILED_WRITE_FAILED",
            "Compiled artifact staging cleanup failed.",
        )
    try:
        path.unlink()
    except OSError as error:
        raise KokoroError(
            "COMPILED_WRITE_FAILED",
            "Compiled artifact staging cleanup failed.",
        ) from error


def _workspace_argument(args: argparse.Namespace) -> Path | None:
    if args.scope == "workspace":
        if args.workspace is None:
            raise KokoroError(
                "ARGUMENT_INVALID",
                "Command arguments are invalid.",
            )
        return _argument_path(args.workspace)
    if args.workspace is not None:
        raise KokoroError(
            "ARGUMENT_INVALID",
            "Command arguments are invalid.",
        )
    return None


def _default_response(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "default": config,
        "activates_character": False,
    }


def _handle_default_set(
    args: argparse.Namespace,
    settings: Settings,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    config = set_character_default(
        settings.data_dir,
        args.character,
        schemas,
        namespace=args.namespace,
        version=args.version,
        workspace_root=_workspace_argument(args),
    )
    return _default_response(config)


def _handle_default_show(
    args: argparse.Namespace,
    settings: Settings,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    config = load_character_default(
        settings.data_dir,
        schemas,
        workspace_root=_workspace_argument(args),
    )
    return _default_response(config)


def _handle_default_clear(
    args: argparse.Namespace,
    settings: Settings,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    config = clear_character_default(
        settings.data_dir,
        schemas,
        workspace_root=_workspace_argument(args),
    )
    return _default_response(config)


def _handle_session_show(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del schemas
    if args.session is None:
        return {"ok": True, "session": None}
    return {
        "ok": True,
        "session": SessionStore(settings.data_dir).load(args.session),
    }


def _handle_session_end(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del schemas
    return {
        "ok": True,
        "session": SessionStore(settings.data_dir).end(args.session),
    }


def _handle_policy_compile(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del settings
    body = _read_json(Path(args.input))
    normalized = normalize_policy(body)
    policy = {
        "schema_version": "1.0",
        "artifact_id": "policy/compiled",
        "created_by": {"component": "kokorox", "version": __version__},
        **normalized,
    }
    schemas.validate("language-policy", policy)
    return {"ok": True, "policy": policy}


def _handle_runtime_context(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    store = SessionStore(settings.data_dir)
    manifest, state = store.snapshot(args.session)
    if not manifest["active"]:
        raise KokoroError("SESSION_NOT_ACTIVE", "Session is not active.")
    compiled = _find_compiled(settings, schemas, manifest)
    context = build_runtime_context(compiled, state, args.locale, args.scenario)
    return {"ok": True, "context": context}


def _runtime_context_body(value: Any) -> dict[str, Any]:
    """Accept either a bare context or the envelope `runtime context` prints.

    Callers save what the command gave them, and what it gives them is
    `{"ok": true, "context": {...}}`. Demanding they unwrap it first would
    turn a redirect into a scripting exercise for no gain.
    """

    if not isinstance(value, dict):
        raise _input_error(
            "INVALID_RUNTIME_CONTEXT_INPUT",
            "Runtime context input is invalid.",
        )
    if "ok" not in value:
        return value
    inner = value.get("context")
    if not isinstance(inner, dict):
        # An envelope with no context is an error envelope. Passing one along
        # would plan a contextless turn and leave the character silent for a
        # reason nobody could see.
        raise _input_error(
            "INVALID_RUNTIME_CONTEXT_INPUT",
            "Runtime context input is invalid.",
        )
    return inner


def _handle_runtime_plan(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del settings
    semantic = _read_json(Path(args.semantic))
    policy = _read_json(Path(args.policy))
    schemas.validate("semantic-result", semantic)
    schemas.validate("language-policy", policy)
    context = (
        _runtime_context_body(_read_json(Path(args.context)))
        if args.context is not None
        else None
    )
    plan = build_render_plan(
        semantic,
        policy,
        expression_intent=args.expression_intent,
        context=context,
    )
    schemas.validate("render-plan", plan)
    return {"ok": True, "plan": plan}


def _handle_runtime_validate(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    del settings
    semantic = _read_json(Path(args.semantic))
    plan = _read_json(Path(args.plan))
    rendered = _read_json(Path(args.rendered))
    schemas.validate("semantic-result", semantic)
    schemas.validate("render-plan", plan)
    validation = validate_rendered_output(
        rendered, semantic, plan, attempt=args.attempt
    )
    schemas.validate("validation-result", validation)
    return {"ok": True, "validation": validation}


def _active_compiled_and_state(
    settings: Settings,
    schemas: SchemaRegistry,
    session_id: str,
) -> tuple[
    SessionStore, dict[str, Any], dict[str, Any], dict[str, Any]
]:
    store = SessionStore(settings.data_dir)
    manifest, state = store.snapshot(session_id)
    if not manifest["active"]:
        raise KokoroError("SESSION_NOT_ACTIVE", "Session is not active.")
    compiled = _find_compiled(settings, schemas, manifest)
    return store, manifest, compiled, state


def _growth_config(
    compiled: dict[str, Any],
) -> tuple[float, int, dict[str, Any] | None]:
    """Return the pack's transition config, stage thresholds included."""

    growth = compiled["growth"]
    stages = growth.get("stages")
    return (
        float(growth.get("max_delta_per_event", 4.0)),
        int(growth.get("repetition_window_turns", 3)),
        stages if isinstance(stages, dict) else None,
    )


def _validated_event(
    args: argparse.Namespace,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    event = _read_json(Path(args.event))
    schemas.validate("interaction-event", event)
    return event


def _handle_state_preview(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    event = _validated_event(args, schemas)
    _store, _manifest, compiled, state = _active_compiled_and_state(
        settings, schemas, args.session
    )
    if event["event_id"] in state["applied_event_ids"]:
        return {"ok": True, "state": state}
    expected = event["expected_state_revision"]
    actual = state["revision"]
    if expected != actual:
        raise KokoroError(
            "STATE_REVISION_CONFLICT",
            "Relationship state revision conflicted.",
            retryable=True,
            details={"expected": expected, "actual": actual},
        )
    max_delta, repetition_window, stages = _growth_config(compiled)
    preview = apply_event(
        state,
        event,
        max_delta=max_delta,
        repetition_window=repetition_window,
        stages=stages,
    )
    return {"ok": True, "state": preview}


def _handle_state_apply(
    args: argparse.Namespace, settings: Settings, schemas: SchemaRegistry
) -> dict[str, Any]:
    event = _validated_event(args, schemas)
    store, manifest, compiled, _state = _active_compiled_and_state(
        settings, schemas, args.session
    )
    max_delta, repetition_window, stages = _growth_config(compiled)
    state = store.apply(
        args.session,
        event,
        max_delta=max_delta,
        repetition_window=repetition_window,
        stages=stages,
        expected_character_id=manifest["character_id"],
        expected_character_version=manifest["character_version"],
        expected_compiled_pack_hash=manifest["compiled_pack_hash"],
        expected_lifecycle_generation=manifest["lifecycle_generation"],
    )
    return {"ok": True, "state": state}


_SCHEMA_NAME: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z", re.ASCII)
_MIGRATION_PATH: Final = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+ -> [0-9]+\.[0-9]+\.[0-9]+\Z", re.ASCII
)
_INSTALLATION_STALE_REASONS: Final = frozenset(
    {"resolution", "installation_changed", "binding"}
)


def _public_error_envelope(error: KokoroError) -> dict[str, Any]:
    code = error.code
    if not isinstance(code, str) or _PUBLIC_ERROR_CODE.fullmatch(code) is None:
        code = "COMMAND_FAILED"
    details: dict[str, Any] = {}
    # The schema name says which contract was violated without echoing any of
    # the input, so it survives sanitization; an empty object left callers
    # guessing which argument was rejected.
    schema = error.details.get("schema")
    if isinstance(schema, str) and _SCHEMA_NAME.fullmatch(schema) is not None:
        details = {"schema": schema}
    sources = error.details.get("sources")
    if (
        code == "SKILL_SUITE_SOURCE_AMBIGUOUS"
        and isinstance(sources, int)
        and not isinstance(sources, bool)
        and 0 <= sources <= 64
    ):
        details = {"sources": sources}
    if code == "STATE_REVISION_CONFLICT":
        expected = error.details.get("expected")
        actual = error.details.get("actual")
        if (
            isinstance(expected, int)
            and not isinstance(expected, bool)
            and expected >= 0
            and isinstance(actual, int)
            and not isinstance(actual, bool)
            and actual >= 0
        ):
            details = {"expected": expected, "actual": actual}
    # Each of these carries structure a caller can act on without echoing any
    # input: two language tags, finding codes, registered format paths, and a
    # fixed reason. An empty object left every one of them a guessing game.
    if code == "PLAN_CONCLUSION_LANGUAGE_MISMATCH":
        route_expected = error.details.get("expected")
        route_actual = error.details.get("actual")
        if is_language_tag(route_expected) and is_language_tag(route_actual):
            details = {"expected": route_expected, "actual": route_actual}
    if code == "AUTHORING_VALIDATION_FAILED":
        failures = error.details.get("failures")
        if (
            isinstance(failures, list)
            and 0 < len(failures) <= 64
            and all(
                isinstance(item, str)
                and _PUBLIC_ERROR_CODE.fullmatch(item) is not None
                for item in failures
            )
        ):
            details = {"failures": list(failures)}
    if code == "MIGRATION_UNAVAILABLE":
        supported = error.details.get("supported")
        if (
            isinstance(supported, list)
            and len(supported) <= 32
            and all(
                isinstance(item, str) and _MIGRATION_PATH.fullmatch(item) is not None
                for item in supported
            )
        ):
            details = {"supported": list(supported)}
    if code == "PERSISTENCE_INSTALLATION_STALE":
        reason = error.details.get("reason")
        if isinstance(reason, str) and reason in _INSTALLATION_STALE_REASONS:
            details = {"reason": reason}
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": _PUBLIC_MESSAGES.get(
                code, "Command could not be completed."
            ),
            "retryable": bool(error.retryable),
            "details": details,
        },
    }


_HANDLERS: dict[tuple[str, str], Callable[..., dict[str, Any]]] = {
    ("pack", "compile"): _handle_pack_compile,
    ("pack", "promote"): _handle_pack_promote,
    ("pack", "publication-check"): _handle_pack_publication_check,
    ("pack", "soft-eval"): _handle_pack_soft_eval,
    ("pack", "test"): _handle_pack_test,
    ("pack", "validate"): _handle_pack_validate,
    ("session", "start"): _handle_session_start,
    ("session", "show"): _handle_session_show,
    ("session", "end"): _handle_session_end,
    ("policy", "compile"): _handle_policy_compile,
    ("runtime", "context"): _handle_runtime_context,
    ("runtime", "plan"): _handle_runtime_plan,
    ("runtime", "validate"): _handle_runtime_validate,
    ("state", "preview"): _handle_state_preview,
    ("state", "apply"): _handle_state_apply,
}

_CHARACTER_HANDLERS: dict[
    tuple[str, str], Callable[..., dict[str, Any]]
] = {
    ("request", "validate"): _handle_character_request_validate,
    ("draft", "validate"): _handle_character_draft_validate,
    ("draft", "compile"): _handle_character_draft_compile,
}

_RESEARCH_HANDLERS: dict[
    tuple[str, str], Callable[..., dict[str, Any]]
] = {
    ("request", "validate"): _handle_research_request_validate,
    ("workspace", "validate"): _handle_research_workspace_validate,
    ("bundle", "compile"): _handle_research_bundle_compile,
    ("bundle", "validate"): _handle_research_bundle_validate,
}

_CONFIG_HANDLERS: dict[
    tuple[str, str], Callable[..., dict[str, Any]]
] = {
    ("default", "set"): _handle_default_set,
    ("default", "show"): _handle_default_show,
    ("default", "clear"): _handle_default_clear,
}


def _force_utf8_output() -> None:
    """Emit UTF-8 regardless of the host console encoding.

    Every command prints JSON with ``ensure_ascii=False``, and Character Packs
    are multilingual by design. On a console using a legacy codepage (cp1252 on
    Windows, for example) encoding that JSON raises UnicodeEncodeError and the
    command dies after doing its work.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    try:
        with redirect_stderr(StringIO()):
            args = build_parser().parse_args(argv)
    except SystemExit as error:
        if error.code == 0:
            return 0
        invalid = KokoroError(
            "ARGUMENT_INVALID",
            "Command arguments are invalid.",
        )
        print(
            json.dumps(
                _public_error_envelope(invalid),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    try:
        route = standalone_route(args)
        if route is not None:
            settings = (
                Settings.from_env(os.environ)
                if standalone_requires_data_root(args)
                else None
            )
            schemas = SchemaRegistry(
                settings.schema_dir if settings is not None else resolve_schema_dir()
            )
            result = handle_standalone(
                args,
                settings.data_dir if settings is not None else None,
                schemas,
            )
        elif args.command == "character":
            group = args.character_command
            subcommand = getattr(args, f"{group}_command")
            settings = (
                Settings.from_env(os.environ)
                if (group, subcommand) == ("draft", "compile")
                else None
            )
            schemas = SchemaRegistry(
                settings.schema_dir if settings is not None else resolve_schema_dir()
            )
            result = _CHARACTER_HANDLERS[(group, subcommand)](
                args, settings, schemas
            )
        elif args.command == "research":
            group = args.research_group
            subcommand = getattr(args, f"research_{group}_command")
            settings = (
                Settings.from_env(os.environ)
                if (group, subcommand) == ("bundle", "compile")
                else None
            )
            schemas = SchemaRegistry(
                settings.schema_dir if settings is not None else resolve_schema_dir()
            )
            result = _RESEARCH_HANDLERS[(group, subcommand)](
                args, settings, schemas
            )
        elif args.command == "config":
            settings = Settings.from_env(os.environ)
            schemas = SchemaRegistry(settings.schema_dir)
            result = _CONFIG_HANDLERS[
                (args.config_command, args.default_command)
            ](args, settings, schemas)
        else:
            settings = Settings.from_env(os.environ)
            schemas = SchemaRegistry(settings.schema_dir)
            subcommand = getattr(args, f"{args.command}_command")
            result = _HANDLERS[(args.command, subcommand)](args, settings, schemas)
    except KokoroError as error:
        print(
            json.dumps(
                _public_error_envelope(error),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except (OSError, json.JSONDecodeError, UnicodeError, ValueError, TypeError):
        safe = KokoroError("COMMAND_FAILED", "Command could not be completed.")
        print(json.dumps(safe.envelope(), ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
