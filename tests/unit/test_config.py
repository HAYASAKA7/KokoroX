from pathlib import Path
import sysconfig

import pytest

from kokoroarc.config import Settings
from kokoroarc.errors import KokoroError


def test_settings_require_explicit_data_directory() -> None:
    with pytest.raises(KokoroError) as raised:
        Settings.from_env({})
    assert raised.value.code == "DATA_DIR_REQUIRED"


def test_settings_resolve_data_directory(tmp_path: Path) -> None:
    settings = Settings.from_env({"KOKOROARC_DATA_DIR": str(tmp_path)})
    assert settings.data_dir == tmp_path.resolve()
