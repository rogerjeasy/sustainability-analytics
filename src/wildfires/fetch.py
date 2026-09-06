"""Checksum-verified acquisition of every raw input.

The manifest at config/sources.yml is the only place a URL or checksum appears.
Downloads are verified against it, so a truncated or wrong-version file fails
loudly instead of silently producing a broken panel.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from wildfires.config import project_root

MANIFEST_RELPATH = Path("config") / "sources.yml"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    target: Path
    sha256: str
    bytes: int
    url: str | None = None
    file_id: str | None = None
    instructions: str | None = None
    unzip_member: str | None = None


def manifest_path() -> Path:
    return project_root() / MANIFEST_RELPATH


def _config() -> dict:
    with manifest_path().open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_manifest() -> list[Source]:
    """Every declared source, with targets resolved against the repository root."""
    root = project_root()
    return [
        Source(
            name=entry["name"],
            kind=entry["kind"],
            target=root / entry["target"],
            sha256=entry["sha256"],
            bytes=entry["bytes"],
            url=entry.get("url"),
            file_id=entry.get("file_id"),
            instructions=entry.get("instructions"),
            unzip_member=entry.get("unzip_member"),
        )
        for entry in _config()["sources"]
    ]


def sha256_of(path: Path) -> str:
    """Streaming digest — these files reach 300 MB and must not be slurped."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verify(source: Source) -> str:
    """Return 'ok', 'missing' or 'corrupt' for one source."""
    if not source.target.exists():
        return "missing"
    return "ok" if sha256_of(source.target) == source.sha256 else "corrupt"
