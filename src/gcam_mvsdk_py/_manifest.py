"""Reader for ``sdk-manifest.toml``, the table of known vendor SDK releases.

The canonical file lives at the repository root and is byte-identical to the
copy in the ``gcam-mvsdk-rs`` repository. Wheels carry it as package data
(``gcam_mvsdk_py/sdk-manifest.toml``); a source checkout or editable install
reads it from the repository root.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import unquote, urlsplit

if sys.version_info >= (3, 11):
    import tomllib as _toml
else:  # pragma: no cover - exercised on Python < 3.11
    import tomli as _toml

MANIFEST_NAME = "sdk-manifest.toml"
KNOWN_LAYOUTS = ("tar", "rar-installer", "zip")
KNOWN_OS = ("linux", "windows", "macos")


class ManifestError(ValueError):
    """The manifest file is missing or malformed."""


@dataclass(frozen=True)
class Release:
    """One vendor SDK release entry."""

    version: str
    os: str
    url: str
    size: int
    sha256: str
    layout: str

    @property
    def filename(self) -> str:
        """Decoded file name of the download (last URL path segment)."""
        return unquote(urlsplit(self.url).path.rsplit("/", 1)[-1])

    @property
    def has_checksum(self) -> bool:
        return bool(self.sha256)


def version_key(version: str) -> Tuple[Any, ...]:
    """Sort key for dotted version strings; numeric parts compare numerically."""
    parts: List[Any] = []
    for piece in re.split(r"[.\-_]", version):
        parts.append((0, int(piece), "") if piece.isdigit() else (1, 0, piece))
    return tuple(parts)


def current_os(platform_name: Optional[str] = None) -> str:
    """Return ``linux``, ``windows``, or ``macos`` for the running system."""
    name = platform_name or sys.platform
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "macos"
    return "linux"


def default_manifest_paths() -> List[Path]:
    """Candidate locations of the manifest, in lookup order."""
    here = Path(__file__).resolve().parent
    return [
        here / MANIFEST_NAME,  # wheel / regular install (package data)
        here.parent.parent / MANIFEST_NAME,  # source checkout or editable install (src layout)
    ]


def find_manifest() -> Path:
    for candidate in default_manifest_paths():
        if candidate.is_file():
            return candidate
    raise ManifestError(
        "%s not found; looked in: %s" % (MANIFEST_NAME, ", ".join(str(p) for p in default_manifest_paths()))
    )


def parse_manifest(text: Union[str, bytes]) -> List[Release]:
    """Parse manifest text into a list of :class:`Release` entries."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    try:
        data: Dict[str, Any] = _toml.loads(text)
    except Exception as exc:  # tomllib.TOMLDecodeError or tomli equivalent
        raise ManifestError("invalid TOML: %s" % exc) from exc
    entries = data.get("release")
    if not isinstance(entries, list) or not entries:
        raise ManifestError("manifest has no [[release]] entries")
    releases: List[Release] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError("release #%d is not a table" % i)
        try:
            rel = Release(
                version=str(entry["version"]),
                os=str(entry["os"]),
                url=str(entry["url"]),
                size=int(entry["size"]),
                sha256=str(entry.get("sha256", "")).lower(),
                layout=str(entry["layout"]),
            )
        except KeyError as exc:
            raise ManifestError("release #%d is missing key %s" % (i, exc)) from exc
        if rel.sha256 and not re.fullmatch(r"[0-9a-f]{64}", rel.sha256):
            raise ManifestError("release %s has a malformed sha256" % rel.version)
        if rel.size <= 0:
            raise ManifestError("release %s has a non-positive size" % rel.version)
        releases.append(rel)
    return releases


def load_manifest(path: Optional[Union[str, os.PathLike]] = None) -> List[Release]:
    """Load the manifest from ``path`` or from the default location."""
    p = Path(path) if path is not None else find_manifest()
    try:
        return parse_manifest(p.read_bytes())
    except OSError as exc:
        raise ManifestError("cannot read %s: %s" % (p, exc)) from exc


def releases_for_os(releases: Sequence[Release], os_name: str) -> List[Release]:
    """Releases for ``os_name``, newest version first."""
    matching = [r for r in releases if r.os == os_name]
    return sorted(matching, key=lambda r: version_key(r.version), reverse=True)


def select_release(releases: Sequence[Release], os_name: str, version: Optional[str] = None) -> Release:
    """Pick the release for ``os_name``: the given ``version`` or the newest."""
    candidates = releases_for_os(releases, os_name)
    if version is not None:
        candidates = [r for r in candidates if r.version == version]
    if not candidates:
        known = ", ".join("%s/%s" % (r.os, r.version) for r in releases) or "none"
        wanted = "%s %s" % (os_name, version) if version else os_name
        raise ManifestError("no SDK release for %s in the manifest (known: %s)" % (wanted, known))
    return candidates[0]


def find_by_sha256(releases: Sequence[Release], digest: str) -> Optional[Release]:
    digest = digest.lower()
    for rel in releases:
        if rel.sha256 and rel.sha256 == digest:
            return rel
    return None
