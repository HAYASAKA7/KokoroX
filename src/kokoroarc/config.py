from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sysconfig
from typing import Mapping

from kokoroarc.errors import KokoroError


def _installed_schema_candidates() -> tuple[Path, ...]:
    suffix = Path("share") / "kokoroarc" / "schemas" / "v1"
    package_file = Path(__file__).resolve()
    target_candidate = package_file.parents[1] / suffix
    try:
        default_scheme = sysconfig.get_default_scheme()
    except AttributeError:
        default_scheme = None

    schemes: list[str | None] = [None]
    try:
        user_scheme = sysconfig.get_preferred_scheme("user")
    except (AttributeError, KeyError):
        pass
    else:
        if user_scheme != default_scheme:
            schemes.append(user_scheme)

    matching_candidates: list[Path] = []
    nonmatching_candidates: list[Path] = []
    for path_scheme in schemes:
        try:
            path_kwargs = {} if path_scheme is None else {"scheme": path_scheme}
            purelib = Path(sysconfig.get_path("purelib", **path_kwargs)).resolve()
            platlib = Path(sysconfig.get_path("platlib", **path_kwargs)).resolve()
            data_candidate = (Path(sysconfig.get_path("data", **path_kwargs)) / suffix).resolve()
        except KeyError:
            continue

        if package_file.is_relative_to(purelib) or package_file.is_relative_to(platlib):
            matching_candidates.append(data_candidate)
        else:
            nonmatching_candidates.append(data_candidate)

    if matching_candidates:
        candidates = [*matching_candidates, target_candidate, *nonmatching_candidates]
    else:
        candidates = [target_candidate, *nonmatching_candidates]

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
