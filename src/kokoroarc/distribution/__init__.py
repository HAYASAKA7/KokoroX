"""Standalone Character Pack distribution primitives."""

from kokoroarc.distribution.archive import (
    InspectedKarcContainer,
    KarcLimits,
    LoadedKarcArchive,
    build_karc_archive,
    inspect_karc_container,
    load_karc_archive,
)
from kokoroarc.distribution.compatibility import inspect_karc_compatibility
from kokoroarc.distribution.defaults import (
    CharacterSelection,
    clear_character_default,
    empty_character_default,
    load_character_default,
    load_selected_compiled,
    resolve_character_selection,
    set_character_default,
)
from kokoroarc.distribution.installer import (
    install_karc_archive,
    preview_karc_install,
    recover_karc_installations,
    remove_installed_pack,
)
from kokoroarc.distribution.migrations import (
    DEFAULT_MIGRATIONS,
    MigrationPreview,
    MigrationRegistry,
    MigrationStep,
    apply_karc_migration,
    preview_karc_migration,
)
from kokoroarc.distribution.registry import (
    InstallScope,
    empty_installed_registry,
    list_installed_packs,
    load_installed_registry,
    resolve_install_scope,
)
from kokoroarc.distribution.suite import (
    SKILL_SUITE_NAMES,
    SkillSuiteLimits,
    install_skill_suite,
    preview_skill_suite_install,
    resolve_skill_suite_source,
)

__all__ = [
    "CharacterSelection",
    "DEFAULT_MIGRATIONS",
    "InstallScope",
    "InspectedKarcContainer",
    "KarcLimits",
    "LoadedKarcArchive",
    "MigrationPreview",
    "MigrationRegistry",
    "MigrationStep",
    "SKILL_SUITE_NAMES",
    "SkillSuiteLimits",
    "apply_karc_migration",
    "build_karc_archive",
    "clear_character_default",
    "empty_character_default",
    "empty_installed_registry",
    "install_karc_archive",
    "install_skill_suite",
    "inspect_karc_compatibility",
    "inspect_karc_container",
    "list_installed_packs",
    "load_character_default",
    "load_karc_archive",
    "load_installed_registry",
    "load_selected_compiled",
    "preview_karc_install",
    "preview_karc_migration",
    "preview_skill_suite_install",
    "recover_karc_installations",
    "remove_installed_pack",
    "resolve_character_selection",
    "resolve_install_scope",
    "resolve_skill_suite_source",
    "set_character_default",
]
