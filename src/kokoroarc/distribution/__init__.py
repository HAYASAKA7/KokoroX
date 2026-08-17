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

__all__ = [
    "DEFAULT_MIGRATIONS",
    "InstallScope",
    "InspectedKarcContainer",
    "KarcLimits",
    "LoadedKarcArchive",
    "MigrationPreview",
    "MigrationRegistry",
    "MigrationStep",
    "apply_karc_migration",
    "build_karc_archive",
    "empty_installed_registry",
    "install_karc_archive",
    "inspect_karc_compatibility",
    "inspect_karc_container",
    "list_installed_packs",
    "load_karc_archive",
    "load_installed_registry",
    "preview_karc_install",
    "preview_karc_migration",
    "recover_karc_installations",
    "remove_installed_pack",
    "resolve_install_scope",
]
