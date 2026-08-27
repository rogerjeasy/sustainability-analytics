"""Path and convention resolution.

Import this instead of writing paths in notebooks::

    from wildfires.config import PATHS, CONVENTIONS
    gdf = gpd.read_file(PATHS["raw"]["gadm_municipal"])

Every path in config/paths.yml is resolved to an absolute path against the
repository root, so notebooks work regardless of which directory the kernel
was started in or whose laptop it is.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG_RELPATH = Path("config") / "paths.yml"


@lru_cache(maxsize=1)
def project_root() -> Path:
    """Walk up from this file until the directory holding config/paths.yml."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / _CONFIG_RELPATH).is_file():
            return candidate
    raise RuntimeError(
        f"Could not locate {_CONFIG_RELPATH} above {__file__}. "
        "Is the repository intact and installed with `pip install -e .`?"
    )


@lru_cache(maxsize=1)
def _load_config() -> dict:
    with (project_root() / _CONFIG_RELPATH).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _resolve(node):
    """Recursively turn relative path strings into absolute Paths."""
    if isinstance(node, dict):
        return {k: _resolve(v) for k, v in node.items()}
    if isinstance(node, str):
        return project_root() / node
    return node


def _build_paths() -> dict:
    cfg = _load_config()
    return {section: _resolve(body) for section, body in cfg.items() if section != "conventions"}


PATHS: dict = _build_paths()
CONVENTIONS: dict = _load_config()["conventions"]

CRS_GEOGRAPHIC: str = CONVENTIONS["crs_geographic"]
CRS_METRIC: str = CONVENTIONS["crs_metric"]
MIN_FIRE_HA: int = CONVENTIONS["min_fire_ha"]
STUDY_YEARS: tuple[int, int] = tuple(CONVENTIONS["study_years"])


def require(path: Path) -> Path:
    """Fail loudly and helpfully when a data file has not been downloaded."""
    if not path.exists():
        rel = path.relative_to(project_root())
        raise FileNotFoundError(
            f"Missing data file: {rel}\n"
            f"See data/README.md for where this comes from, or run: make data"
        )
    return path
