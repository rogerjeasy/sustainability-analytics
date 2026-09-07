"""Checksum-verified acquisition of every raw input.

The manifest at config/sources.yml is the only place a URL or checksum appears.
Downloads are verified against it, so a truncated or wrong-version file fails
loudly instead of silently producing a broken panel.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
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


DRIVE_DIRECT = "https://drive.google.com/uc?export=download&id={file_id}"
DRIVE_CONFIRM = "https://drive.usercontent.google.com/download"
_TIMEOUT = 60
_FORM_INPUT = re.compile(r'name="([^"]+)"\s+value="([^"]*)"')


class ChecksumMismatch(RuntimeError):
    """A download completed but did not match the manifest digest."""


def parse_drive_confirm(html: str) -> dict[str, str]:
    """Extract the confirm-form fields from Drive's virus-scan interstitial.

    Returns an empty dict when the payload is not an interstitial, so binary
    file content is never mistaken for a form.
    """
    if "Virus scan warning" not in html and "<form" not in html:
        return {}
    fields = dict(_FORM_INPUT.findall(html))
    return fields if {"id", "confirm"} <= set(fields) else {}


def _stream_to(response: requests.Response, destination: Path, expected: str) -> None:
    """Stream to a sibling temp file, hashing as we go, and only then rename.

    Renaming after the digest matches means an interrupted or corrupted fetch can
    never leave a half-written file sitting where a valid one belongs. A dropped
    connection or full disk mid-loop is just as much a failure as a bad checksum,
    so any exception during streaming also unlinks the temp file before
    propagating — otherwise a retried, still-failing source would leave one
    orphan temp file per attempt.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
        try:
            for chunk in response.iter_content(chunk_size=_CHUNK):
                tmp.write(chunk)
                digest.update(chunk)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    if digest.hexdigest() != expected:
        actual = digest.hexdigest()
        temp_path.unlink()
        raise ChecksumMismatch(f"expected {expected}, got {actual}")
    # NamedTemporaryFile defaults to 0600; the destination should read like any
    # other file in the tree, not like a private scratch file.
    temp_path.chmod(0o644)
    temp_path.replace(destination)


def _download_http(source: Source) -> None:
    with requests.get(source.url, stream=True, timeout=_TIMEOUT) as response:
        response.raise_for_status()
        if source.unzip_member:
            with NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                archive = Path(tmp.name)
                try:
                    for chunk in response.iter_content(chunk_size=_CHUNK):
                        tmp.write(chunk)
                except Exception:
                    archive.unlink(missing_ok=True)
                    raise

            source.target.parent.mkdir(parents=True, exist_ok=True)
            extracted = source.target.with_suffix(source.target.suffix + ".part")
            try:
                # A truncated or wrong archive (zipfile.BadZipFile) or a manifest
                # that names a member the archive doesn't contain (KeyError) must
                # not leave a half-written .part file behind, same as any other
                # failure mode here.
                with zipfile.ZipFile(archive) as zf, \
                     zf.open(source.unzip_member) as member, \
                     extracted.open("wb") as out:
                    shutil.copyfileobj(member, out)
            except Exception:
                extracted.unlink(missing_ok=True)
                raise
            finally:
                archive.unlink(missing_ok=True)

            if sha256_of(extracted) != source.sha256:
                extracted.unlink()
                raise ChecksumMismatch(f"{source.name}: extracted member does not match")
            extracted.replace(source.target)
        else:
            _stream_to(response, source.target, source.sha256)


def _download_gdrive(source: Source) -> None:
    """Fetch a public Drive file, following the large-file confirm token."""
    with requests.Session() as session:
        url = DRIVE_DIRECT.format(file_id=source.file_id)
        response = session.get(url, stream=True, timeout=_TIMEOUT)
        response.raise_for_status()

        if response.headers.get("Content-Type", "").startswith("text/html"):
            fields = parse_drive_confirm(response.text)
            if not fields:
                raise RuntimeError(
                    f"{source.name}: Drive returned HTML with no confirm form. "
                    "Is the folder still shared publicly?"
                )
            response = session.get(DRIVE_CONFIRM, params=fields,
                                   stream=True, timeout=_TIMEOUT)
            response.raise_for_status()

        _stream_to(response, source.target, source.sha256)


def download(source: Source, *, force: bool = False) -> str:
    """Fetch one source and verify it. Returns 'ok', 'skipped' or 'failed'."""
    if not force and verify(source) == "ok":
        return "skipped"

    if source.kind == "manual":
        print(f"  {source.name} must be fetched by hand:\n    {source.instructions}")
        return "failed"
    try:
        if source.kind == "http":
            _download_http(source)
        elif source.kind == "gdrive":
            _download_gdrive(source)
        else:
            raise ValueError(f"Unknown source kind {source.kind!r}")
    except ChecksumMismatch as exc:
        print(f"  CHECKSUM MISMATCH for {source.name}\n    {exc}\n"
              "    The partial file was discarded. Re-run; if it recurs the "
              "upstream copy changed and the manifest needs updating.")
        return "failed"
    except requests.RequestException as exc:
        print(f"  DOWNLOAD FAILED for {source.name}: {exc}")
        return "failed"
    except (zipfile.BadZipFile, KeyError) as exc:
        print(f"  BAD ARCHIVE for {source.name}: {exc}\n"
              "    The download was not a valid zip, or did not contain the "
              "expected member. The partial file was discarded.")
        return "failed"
    return "ok"
