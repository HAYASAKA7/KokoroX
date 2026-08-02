from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sysconfig
from typing import Mapping

from kokoroarc.errors import KokoroError


def _installed_schema_candidates() -> tuple[Path, ...]:
    suffix = Path("share") / "kokoroarc" / "schemas" / "v1"
    candidates = [Path(sysconfig.get_path("data")) / suffix]

    try:
        user_scheme = sysconfig.get_preferred_scheme("user")
    except AttributeError:
        pass
    else:
        try:
            candidates.append(
                Path(sysconfig.get_path("data", scheme=user_scheme)) / suffix
            )
        except KeyError:
            pass

    candidates.append(Path(__file__).resolve().parents[1] / suffix)
    return tuple(dict.fromkeys(candidate.resolve() for candidate in candidates))


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
        installed_schemas = _installed_schema_candidates()
        schema_dir = repository_schemas
        if not schema_dir.is_dir():
            schema_dir = next(
                (candidate for candidate in installed_schemas if candidate.is_dir()),
                installed_schemas[0],
            )
        return cls(
            data_dir=Path(raw_data_dir).expanduser().resolve(),
            schema_dir=schema_dir,
        )

    def ensure_directories(self) -> None:
        for name in ("compiled", "sessions", "state", "events", "reports"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
