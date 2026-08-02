from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sysconfig
from typing import Mapping

from kokoroarc.errors import KokoroError


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    schema_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        raw_data_dir = env.get("KOKOROARC_DATA_DIR")
        if not raw_data_dir:
            raise KokoroError(
                "DATA_DIR_REQUIRED",
                "Set KOKOROARC_DATA_DIR before running a stateful command.",
            )
        repository_root = Path(__file__).resolve().parents[2]
        repository_schemas = (repository_root / "schemas" / "v1").resolve()
        installed_schemas = (
            Path(sysconfig.get_path("data")) / "share" / "kokoroarc" / "schemas" / "v1"
        ).resolve()
        return cls(
            data_dir=Path(raw_data_dir).expanduser().resolve(),
            schema_dir=repository_schemas if repository_schemas.is_dir() else installed_schemas,
        )

    def ensure_directories(self) -> None:
        for name in ("compiled", "sessions", "state", "events", "reports"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
