"""Locate and open the HuaTeng MVSDK shared library at runtime.

Search order (first existing file wins):

1. ``$GCAM_MVSDK_DIR/lib/<arch>``, ``$GCAM_MVSDK_DIR/lib``, ``$GCAM_MVSDK_DIR``
2. ``./vendor/<version>/lib/<arch>`` (developer checkout, ``scripts/fetch-sdk.sh``)
3. ``<sdk home>/<version>/lib/<arch>`` (``gcam-mvsdk-py setup``), where the SDK
   home is ``$GCAM_MVSDK_HOME``, else the directory recorded by ``install.bash``
   in the running virtual environment, else ``~/.gcam-mvsdk``
4. The system library path (``/lib``, ``/usr/lib``, ... on Linux; ``PATH`` on
   Windows), and finally the dynamic loader by bare file name.

``<arch>`` is derived from ``platform.machine()`` and the interpreter's pointer
size; ``GCAM_MVSDK_ARCH`` overrides it (for example ``arm_softfp``).
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ._errors import SdkNotFound

ENV_DIR = "GCAM_MVSDK_DIR"
ENV_ARCH = "GCAM_MVSDK_ARCH"
ENV_HOME = "GCAM_MVSDK_HOME"
SDK_HOME_DIRNAME = ".gcam-mvsdk"
VENDOR_DIRNAME = "vendor"
# Written by install.bash into the root of the virtual environment it creates;
# holds the absolute path of the SDK home chosen at install time.
VENV_HOME_MARKER = "gcam-mvsdk-py-home"

_ARCH_ALIASES: Dict[str, str] = {
    "x86_64": "x64",
    "amd64": "x64",
    "x64": "x64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv8l": "arm",
    "armv7l": "arm",
    "armv7": "arm",
    "armv7a": "arm",
    "armv6l": "arm",
    "armhf": "arm",
    "arm": "arm",
    "i386": "x86",
    "i486": "x86",
    "i586": "x86",
    "i686": "x86",
    "x86": "x86",
}

# Keep os.add_dll_directory handles alive for the lifetime of the process.
_DLL_DIRECTORY_HANDLES: List[object] = []


def _system_name(system: Optional[str] = None) -> str:
    s = (system or platform.system()).lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "macos"
    return "linux"


def _pointer_bits() -> int:
    return ctypes.sizeof(ctypes.c_void_p) * 8


def detect_arch(
    machine: Optional[str] = None,
    pointer_bits: Optional[int] = None,
    system: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Return the vendor ``lib/<arch>`` directory name for this interpreter.

    ``x86_64`` maps to ``x64``, ``aarch64`` to ``arm64``, ``armv7l`` to ``arm``
    (hard float; set ``GCAM_MVSDK_ARCH=arm_softfp`` for soft-float boards), and
    ``i686`` to ``x86``. A 32-bit interpreter on a 64-bit kernel maps to the
    32-bit library. On Windows the choice follows ``platform.architecture()``.
    """
    env = os.environ if env is None else env
    override = env.get(ENV_ARCH, "").strip()
    if override:
        return override
    bits = pointer_bits if pointer_bits is not None else _pointer_bits()
    sysname = _system_name(system)
    raw = (machine if machine is not None else platform.machine()).strip().lower()
    if sysname == "windows":
        if raw in ("arm64", "aarch64"):
            return "arm64" if bits == 64 else "arm"
        return "x64" if bits == 64 else "x86"
    arch = _ARCH_ALIASES.get(raw)
    if arch is None:
        if raw.startswith("arm"):
            arch = "arm"
        elif raw.startswith("i") and raw.endswith("86"):
            arch = "x86"
        else:
            return raw or "unknown"
    if bits == 32 and arch == "x64":
        return "x86"
    if bits == 32 and arch == "arm64":
        return "arm"
    return arch


def library_names(system: Optional[str] = None, pointer_bits: Optional[int] = None) -> List[str]:
    """File names of the vendor library for the given platform."""
    sysname = _system_name(system)
    if sysname == "windows":
        if pointer_bits is None:
            is64 = platform.architecture()[0] == "64bit"
        else:
            is64 = pointer_bits == 64
        return ["MVCAMSDK_X64.dll"] if is64 else ["MVCAMSDK.dll"]
    if sysname == "macos":
        # The macOS SDK packages have not been inspected; these are best guesses.
        return ["libMVSDK.dylib", "libmvsdk.dylib"]
    return ["libMVSDK.so"]


@dataclass(frozen=True)
class SearchEntry:
    """One directory the loader looks in."""

    directory: Path
    origin: str
    sdk_root: Optional[Path] = None


@dataclass(frozen=True)
class LibraryLocation:
    """Where the library was found (``path`` may be a bare name for the system loader)."""

    path: str
    origin: str
    sdk_root: Optional[Path] = None


def _venv_marker_home() -> Optional[Path]:
    """SDK home recorded by ``install.bash`` in the running virtual environment, if any."""
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        return None
    try:
        text = (Path(sys.prefix) / VENV_HOME_MARKER).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return Path(text).expanduser() if text else None


def sdk_home(home: Optional[Path] = None, env: Optional[Mapping[str, str]] = None) -> Path:
    """Directory that holds ``<version>/`` SDK installations.

    ``$GCAM_MVSDK_HOME`` if set, else the directory recorded by ``install.bash``
    in the running virtual environment, else ``~/.gcam-mvsdk`` (the default
    shared with ``gcam-mvsdk-rs``). Passing ``home`` selects
    ``<home>/.gcam-mvsdk`` and skips the other two sources.
    """
    if home is not None:
        return home / SDK_HOME_DIRNAME
    env = os.environ if env is None else env
    override = env.get(ENV_HOME, "").strip()
    if override:
        return Path(override).expanduser()
    marker = _venv_marker_home()
    if marker is not None:
        return marker
    return Path.home() / SDK_HOME_DIRNAME


def _manifest_versions(system: Optional[str] = None) -> List[str]:
    try:
        from . import _manifest

        releases = _manifest.load_manifest()
        os_name = {"windows": "windows", "macos": "macos"}.get(_system_name(system), "linux")
        return [r.version for r in _manifest.releases_for_os(releases, os_name)]
    except Exception:
        return []


def candidate_versions(base: Path, manifest_versions: Sequence[str]) -> List[str]:
    """Versions to try under ``base``: manifest versions plus existing subdirectories."""
    from ._manifest import version_key

    found = set(manifest_versions)
    try:
        for child in base.iterdir():
            if child.is_dir() and not child.name.startswith(".") and (child / "lib").is_dir():
                found.add(child.name)
    except OSError:
        pass
    return sorted(found, key=version_key, reverse=True)


def root_dirs(root: Path, arch: Optional[str] = None) -> List[Path]:
    """Directories checked inside an SDK root: ``lib/<arch>``, ``lib``, the root itself."""
    arch = arch or detect_arch()
    return [root / "lib" / arch, root / "lib", root]


def _system_dirs(sysname: str, arch: str, env: Mapping[str, str]) -> List[Path]:
    dirs: List[Path] = []
    if sysname == "windows":
        for entry in env.get("PATH", "").split(os.pathsep):
            if entry.strip():
                dirs.append(Path(entry.strip().strip('"')))
        return dirs
    var = "DYLD_LIBRARY_PATH" if sysname == "macos" else "LD_LIBRARY_PATH"
    for entry in env.get(var, "").split(os.pathsep):
        if entry.strip():
            dirs.append(Path(entry.strip()))
    triplets = {
        "x64": "x86_64-linux-gnu",
        "arm64": "aarch64-linux-gnu",
        "arm": "arm-linux-gnueabihf",
        "arm_softfp": "arm-linux-gnueabi",
        "x86": "i386-linux-gnu",
    }
    std = ["/lib", "/usr/lib", "/usr/local/lib", "/lib64", "/usr/lib64"]
    if sysname == "linux" and arch in triplets:
        std += ["/lib/" + triplets[arch], "/usr/lib/" + triplets[arch]]
    dirs.extend(Path(d) for d in std)
    return dirs


def search_entries(
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
    home: Optional[Path] = None,
    arch: Optional[str] = None,
    system: Optional[str] = None,
    manifest_versions: Optional[Sequence[str]] = None,
) -> List[SearchEntry]:
    """Every directory the loader inspects, in priority order."""
    env = os.environ if env is None else env
    sysname = _system_name(system)
    arch = arch or detect_arch(env=env, system=system)
    cwd = cwd if cwd is not None else Path.cwd()
    versions = list(manifest_versions) if manifest_versions is not None else _manifest_versions(system)
    entries: List[SearchEntry] = []

    root_env = env.get(ENV_DIR, "").strip()
    if root_env:
        root = Path(root_env).expanduser()
        entries.extend(SearchEntry(d, ENV_DIR, root) for d in root_dirs(root, arch))

    vendor_base = cwd / VENDOR_DIRNAME
    for ver in candidate_versions(vendor_base, versions):
        root = vendor_base / ver
        entries.append(SearchEntry(root / "lib" / arch, "./vendor", root))

    home_base = sdk_home(home, env)
    home_origin = "~/" + SDK_HOME_DIRNAME if home_base == Path.home() / SDK_HOME_DIRNAME else "SDK home"
    for ver in candidate_versions(home_base, versions):
        root = home_base / ver
        entries.append(SearchEntry(root / "lib" / arch, home_origin, root))

    for d in _system_dirs(sysname, arch, env):
        entries.append(SearchEntry(d, "system", None))
    return entries


def find_library(
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
    home: Optional[Path] = None,
    arch: Optional[str] = None,
    system: Optional[str] = None,
    manifest_versions: Optional[Sequence[str]] = None,
) -> Optional[LibraryLocation]:
    """Return the first existing library file along the search path, or ``None``."""
    names = library_names(system)
    for entry in search_entries(env, cwd, home, arch, system, manifest_versions):
        for name in names:
            candidate = entry.directory / name
            if candidate.is_file():
                return LibraryLocation(str(candidate), entry.origin, entry.sdk_root)
    return None


def describe_search(
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
    home: Optional[Path] = None,
    arch: Optional[str] = None,
    system: Optional[str] = None,
    manifest_versions: Optional[Sequence[str]] = None,
) -> List[str]:
    """Human-readable list of every candidate file path, for error messages."""
    names = library_names(system)
    out: List[str] = []
    for entry in search_entries(env, cwd, home, arch, system, manifest_versions):
        for name in names:
            out.append("%s  [%s]" % (entry.directory / name, entry.origin))
    out.extend("%s  [dynamic loader]" % n for n in names)
    return out


def _open(path: str) -> ctypes.CDLL:
    if _system_name() == "windows":  # pragma: no cover - Windows only
        directory = os.path.dirname(path)
        if directory and hasattr(os, "add_dll_directory"):
            try:
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(directory))
            except OSError:
                pass
        return ctypes.WinDLL(path)  # type: ignore[attr-defined]
    return ctypes.CDLL(path)


def open_library(path: Optional[str] = None) -> Tuple[ctypes.CDLL, LibraryLocation]:
    """Open the vendor library and return ``(library, location)``.

    Raises :class:`SdkNotFound` if nothing usable is found.
    """
    if path:
        p = Path(path).expanduser()
        if p.is_dir():
            candidates = [d / n for d in root_dirs(p) for n in library_names()]
            found = next((c for c in candidates if c.is_file()), None)
            if found is None:
                raise SdkNotFound([str(c) for c in candidates])
            loc = LibraryLocation(str(found), "explicit directory", p)
        else:
            loc = LibraryLocation(str(p), "explicit path", None)
        try:
            return _open(loc.path), loc
        except OSError as exc:
            raise SdkNotFound([loc.path], "Opening %s failed: %s" % (loc.path, exc)) from exc

    loc = find_library()
    if loc is not None:
        try:
            return _open(loc.path), loc
        except OSError as exc:
            raise SdkNotFound(
                [loc.path],
                "Found %s but the dynamic loader rejected it: %s. Check that it matches this "
                "interpreter's architecture (%s); GCAM_MVSDK_ARCH overrides the choice." % (loc.path, exc, detect_arch()),
            ) from exc

    for name in library_names():
        try:
            return _open(name), LibraryLocation(name, "dynamic loader", None)
        except OSError:
            continue
    raise SdkNotFound(describe_search())
