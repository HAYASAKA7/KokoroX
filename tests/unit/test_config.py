from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import kokoroarc.config as config
from kokoroarc.config import Settings
from kokoroarc.errors import KokoroError


def test_settings_require_explicit_data_directory() -> None:
    with pytest.raises(KokoroError) as raised:
        Settings.from_env({})
    assert raised.value.code == "DATA_DIR_REQUIRED"


def test_settings_resolve_data_directory(tmp_path: Path) -> None:
    settings = Settings.from_env({"KOKOROARC_DATA_DIR": str(tmp_path)})
    assert settings.data_dir == tmp_path.resolve()


def test_kokoro_error_envelope_and_details_are_independent() -> None:
    first = KokoroError("EXAMPLE", "Example failure", details={"item": "first"})
    second = KokoroError("EXAMPLE", "Example failure")

    assert first.envelope() == {
        "ok": False,
        "error": {
            "code": "EXAMPLE",
            "message": "Example failure",
            "retryable": False,
            "details": {"item": "first"},
        },
    }
    first.details["new"] = "value"
    assert second.details == {}


def test_kokoro_error_string_is_its_message() -> None:
    assert str(KokoroError("EXAMPLE", "Example failure")) == "Example failure"


def test_settings_is_frozen_and_slotted(tmp_path: Path) -> None:
    settings = Settings.from_env({"KOKOROARC_DATA_DIR": str(tmp_path)})

    assert not hasattr(settings, "__dict__")
    with pytest.raises(FrozenInstanceError):
        settings.data_dir = tmp_path / "other"


def test_settings_ensure_directories_creates_expected_layout(tmp_path: Path) -> None:
    root = tmp_path / "data"
    settings = Settings.from_env({"KOKOROARC_DATA_DIR": str(root)})

    settings.ensure_directories()

    assert {path.name for path in root.iterdir()} == {
        "compiled",
        "sessions",
        "state",
        "events",
        "reports",
    }
    assert all(path.is_dir() for path in root.iterdir())


def test_settings_prefers_repository_schemas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package_file = tmp_path / "repository" / "src" / "kokoroarc" / "config.py"
    repository_schemas = tmp_path / "repository" / "schemas" / "v1"
    default_schemas = tmp_path / "default" / "share" / "kokoroarc" / "schemas" / "v1"
    repository_schemas.mkdir(parents=True)
    default_schemas.mkdir(parents=True)
    monkeypatch.setattr(config, "__file__", str(package_file))
    monkeypatch.setattr(config.sysconfig, "get_path", lambda name, scheme=None: str(tmp_path / "default"))

    settings = Settings.from_env({"KOKOROARC_DATA_DIR": str(tmp_path / "data")})

    assert settings.schema_dir == repository_schemas.resolve()


def test_settings_uses_default_installed_schema_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package_file = tmp_path / "repository" / "src" / "kokoroarc" / "config.py"
    default_root = tmp_path / "default"
    default_schemas = default_root / "share" / "kokoroarc" / "schemas" / "v1"
    default_schemas.mkdir(parents=True)
    monkeypatch.setattr(config, "__file__", str(package_file))
    monkeypatch.setattr(config.sysconfig, "get_path", lambda name, scheme=None: str(default_root))

    settings = Settings.from_env({"KOKOROARC_DATA_DIR": str(tmp_path / "data")})

    assert settings.schema_dir == default_schemas.resolve()


def test_settings_uses_user_installed_schema_when_default_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package_file = tmp_path / "repository" / "src" / "kokoroarc" / "config.py"
    default_root = tmp_path / "default"
    user_root = tmp_path / "user"
    user_schemas = user_root / "share" / "kokoroarc" / "schemas" / "v1"
    user_schemas.mkdir(parents=True)
    monkeypatch.setattr(config, "__file__", str(package_file))
    monkeypatch.setattr(config.sysconfig, "get_preferred_scheme", lambda key: "user")
    monkeypatch.setattr(
        config.sysconfig,
        "get_path",
        lambda name, scheme=None: str(user_root if scheme == "user" else default_root),
    )

    settings = Settings.from_env({"KOKOROARC_DATA_DIR": str(tmp_path / "data")})

    assert settings.schema_dir == user_schemas.resolve()


def test_settings_uses_target_adjacent_schema_when_other_installed_paths_are_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package_file = tmp_path / "target" / "kokoroarc" / "config.py"
    default_root = tmp_path / "default"
    target_schemas = tmp_path / "target" / "share" / "kokoroarc" / "schemas" / "v1"
    target_schemas.mkdir(parents=True)
    monkeypatch.setattr(config, "__file__", str(package_file))
    monkeypatch.setattr(config.sysconfig, "get_preferred_scheme", lambda key: "user")
    monkeypatch.setattr(config.sysconfig, "get_path", lambda name, scheme=None: str(default_root))

    settings = Settings.from_env({"KOKOROARC_DATA_DIR": str(tmp_path / "data")})

    assert settings.schema_dir == target_schemas.resolve()
