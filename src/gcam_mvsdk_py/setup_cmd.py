"""``gcam-mvsdk-py setup``: download, verify, and extract the vendor SDK.

Only the standard library is used. The flow for the Linux tarball:

1. ``HEAD`` the recorded URL and compare ``Content-Length`` with the manifest.
2. ``GET`` it with a progress indicator, hashing while downloading.
3. Compare SHA-256 with the manifest; a mismatch aborts (the vendor serves
   plain HTTP only, so the checksum is the integrity guarantee).
4. Extract ``include/``, ``lib/``, ``tools/GeConfigCmd/`` and the udev rules
   into ``<dest>/<version>/`` and write ``manifest.json`` next to them.

``--from FILE`` performs steps 3 and 4 on a local archive. On Windows the
vendor ships a ``.rar`` wrapping an installer: it is downloaded and verified,
unpacked with ``7z`` when available, and the user is told to run the installer
(which also installs the GigE filter driver).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import IO, Callable, List, Optional, Sequence, Tuple

from . import __version__
from ._loader import detect_arch, sdk_home
from ._manifest import (
    ManifestError,
    Release,
    current_os,
    find_by_sha256,
    load_manifest,
    releases_for_os,
    select_release,
)

INSTALL_MANIFEST = "manifest.json"
DOWNLOADS_DIRNAME = ".downloads"
# Paths (relative to the archive's top-level directory) that are extracted.
EXTRACT_PREFIXES = ("include/", "lib/", "tools/GeConfigCmd/")
EXTRACT_FILES = ("88-mvusb.rules", "99-mvusb.rules")
UDEV_RULES = EXTRACT_FILES
UDEV_DIR = "/etc/udev/rules.d"
USER_AGENT = "gcam-mvsdk-py/%s (+https://github.com/swarmbotix/gcam-mvsdk-py)" % __version__
CHUNK = 1 << 20


class SetupError(RuntimeError):
    """Setup failed; the message is meant for the user."""


class ChecksumMismatch(SetupError):
    pass


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _log(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(msg, file=sys.stderr)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _human(n: float) -> str:
    return "%.1f MiB" % (n / (1 << 20))


class _Progress:
    """Minimal download progress indicator on stderr."""

    def __init__(self, total: int, quiet: bool) -> None:
        self.total = total
        self.quiet = quiet
        self.tty = sys.stderr.isatty()
        self.last_pct = -1
        self.last_time = 0.0
        self.start = time.monotonic()

    def update(self, done: int) -> None:
        if self.quiet:
            return
        pct = int(done * 100 / self.total) if self.total else 0
        now = time.monotonic()
        if self.tty:
            if now - self.last_time < 0.1 and done < self.total:
                return
            rate = done / max(now - self.start, 1e-6)
            sys.stderr.write("\r  %s / %s (%3d%%)  %s/s   " % (_human(done), _human(self.total), pct, _human(rate)))
            sys.stderr.flush()
        elif pct // 10 != self.last_pct // 10:
            sys.stderr.write("  %3d%%  (%s / %s)\n" % (pct, _human(done), _human(self.total)))
        self.last_pct = pct
        self.last_time = now

    def finish(self) -> None:
        if not self.quiet and self.tty:
            sys.stderr.write("\n")


def _request(url: str, method: str = "GET") -> urllib.request.Request:
    return urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def head_check(release: Release, timeout: float = 30.0, opener: Callable[..., IO[bytes]] = urllib.request.urlopen) -> int:
    """``HEAD`` the release URL; return ``Content-Length`` or raise :class:`SetupError`."""
    try:
        with opener(_request(release.url, "HEAD"), timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            length = resp.headers.get("Content-Length")
    except urllib.error.HTTPError as exc:
        raise SetupError(
            "The vendor URL answered HTTP %d:\n  %s\nThe vendor changes attachment ids when it uploads a new "
            "version. Download the SDK by hand from http://huatengvision.com/download/1/ and run "
            "`gcam-mvsdk-py setup --from <file>`." % (exc.code, release.url)
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SetupError("Cannot reach %s: %s" % (release.url, exc)) from exc
    if status != 200:
        raise SetupError("HEAD %s returned status %s, expected 200" % (release.url, status))
    if length is None:
        return -1
    size = int(length)
    if size != release.size:
        raise SetupError(
            "The vendor file size changed: Content-Length %d, manifest records %d.\n"
            "The vendor may have replaced the file. Refusing to download; obtain the archive by hand and "
            "use `--from`, or update sdk-manifest.toml." % (size, release.size)
        )
    return size


def download(
    release: Release,
    target: Path,
    quiet: bool = False,
    timeout: float = 60.0,
    opener: Callable[..., IO[bytes]] = urllib.request.urlopen,
) -> str:
    """Download ``release.url`` to ``target`` (via ``target.part``); return the SHA-256."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    h = hashlib.sha256()
    done = 0
    progress = _Progress(release.size, quiet)
    try:
        with opener(_request(release.url), timeout=timeout) as resp, open(part, "wb") as out:
            while True:
                block = resp.read(CHUNK)
                if not block:
                    break
                out.write(block)
                h.update(block)
                done += len(block)
                progress.update(done)
    except (urllib.error.URLError, OSError) as exc:
        progress.finish()
        part.unlink(missing_ok=True)
        raise SetupError("Download of %s failed: %s" % (release.url, exc)) from exc
    progress.finish()
    if done != release.size:
        part.unlink()
        raise SetupError("Downloaded %d bytes, expected %d; the transfer was truncated or the file changed." % (done, release.size))
    os.replace(part, target)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Verification and release selection
# ---------------------------------------------------------------------------


def verify(path: Path, release: Release, digest: Optional[str] = None, allow_unverified: bool = False, quiet: bool = False) -> str:
    """Check size and SHA-256 of ``path`` against ``release``; return the digest."""
    size = path.stat().st_size
    if size != release.size:
        raise ChecksumMismatch("%s is %d bytes; the manifest records %d for %s." % (path, size, release.size, release.version))
    digest = digest or sha256_file(path)
    if release.sha256:
        if digest != release.sha256:
            raise ChecksumMismatch(
                "SHA-256 mismatch for %s:\n  expected %s\n  actual   %s\nThe file is corrupt or not the vendor's "
                "release; it was not installed." % (path, release.sha256, digest)
            )
        _log("SHA-256 verified: %s" % digest, quiet)
    else:
        if not allow_unverified:
            raise ChecksumMismatch(
                "The manifest has no SHA-256 for %s %s, so the download cannot be verified.\n"
                "  computed sha256 = %s\nCompare it with a trusted copy, then rerun with --allow-unverified "
                "(and consider recording it in sdk-manifest.toml)." % (release.os, release.version, digest)
            )
        _log("WARNING: no recorded checksum; accepted unverified file with sha256 %s" % digest, quiet)
    return digest


def _infer_layout(path: Path) -> str:
    name = path.name.lower()
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        return "tar"
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".rar"):
        return "rar-installer"
    raise SetupError("Cannot tell the archive type of %s" % path)


def release_for_file(
    path: Path,
    releases: Sequence[Release],
    version: Optional[str],
    allow_unverified: bool,
    quiet: bool = False,
) -> Tuple[Release, str]:
    """Identify the release that a local archive corresponds to; return ``(release, sha256)``."""
    digest = sha256_file(path)
    match = find_by_sha256(releases, digest)
    if match is not None and (version is None or match.version == version):
        verify(path, match, digest, quiet=quiet)
        return match, digest
    if version is not None:
        same_version = [r for r in releases if r.version == version]
        if same_version:
            rel = same_version[0]
            verify(path, rel, digest, allow_unverified=allow_unverified, quiet=quiet)
            return rel, digest
        if allow_unverified:
            rel = Release(
                version=version,
                os=current_os(),
                url=path.resolve().as_uri(),
                size=path.stat().st_size,
                sha256="",
                layout=_infer_layout(path),
            )
            _log("WARNING: version %s is not in the manifest; installing unverified file (sha256 %s)" % (version, digest), quiet)
            return rel, digest
        raise SetupError("Version %s is not in the manifest. Pass --allow-unverified to install it anyway." % version)
    unchecked = [r for r in releases if not r.sha256 and r.size == path.stat().st_size]
    if len(unchecked) == 1:
        verify(path, unchecked[0], digest, allow_unverified=allow_unverified, quiet=quiet)
        return unchecked[0], digest
    raise ChecksumMismatch(
        "%s (sha256 %s) does not match any release in the manifest.\n"
        "Pass --version V --allow-unverified to install it anyway." % (path, digest)
    )


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _strip_top(name: str) -> Optional[PurePosixPath]:
    parts = PurePosixPath(name).parts
    if len(parts) < 2:
        return None
    rel = PurePosixPath(*parts[1:])
    if rel.is_absolute() or any(p in ("..", "") for p in rel.parts):
        raise SetupError("Refusing unsafe archive member path: %r" % name)
    return rel


def _selected(rel: PurePosixPath) -> bool:
    s = rel.as_posix()
    return s in EXTRACT_FILES or any(s.startswith(p) or (s + "/") == p for p in EXTRACT_PREFIXES)


def _file_mode(rel: PurePosixPath) -> int:
    s = rel.as_posix()
    if s.startswith("tools/GeConfigCmd/") or s.endswith(".so"):
        return 0o755
    return 0o644


def extract_tar(archive: Path, target: Path) -> List[str]:
    """Extract the selected subset of a vendor tarball into ``target``.

    The archive's single top-level directory is stripped. Only regular files
    and directories are written; permissions are normalized (the vendor
    archive marks everything world-writable).
    """
    written: List[str] = []
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            rel = _strip_top(member.name)
            if rel is None or not _selected(rel):
                continue
            dest = target.joinpath(*rel.parts)
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue  # links and special files are not needed
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            with src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
            os.chmod(dest, _file_mode(rel))
            written.append(rel.as_posix())
    if not any(w.startswith("lib/") for w in written):
        raise SetupError("%s does not contain a lib/ directory; is it the HuaTeng Linux SDK?" % archive)
    return written


def extract_zip(archive: Path, target: Path) -> List[str]:
    """Extract the selected subset of a zip archive laid out like the tarball."""
    written: List[str] = []
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            rel = _strip_top(info.filename)
            if rel is None or not _selected(rel) or info.is_dir():
                continue
            dest = target.joinpath(*rel.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
            os.chmod(dest, _file_mode(rel))
            written.append(rel.as_posix())
    return written


def write_install_manifest(version_dir: Path, release: Release, source_url: str, digest: str, **extra: object) -> Path:
    data = {
        "version": release.version,
        "source_url": source_url,
        "sha256": digest,
        "installed_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "os": release.os,
        "layout": release.layout,
        "installer": "gcam-mvsdk-py %s" % __version__,
    }
    data.update(extra)
    path = version_dir / INSTALL_MANIFEST
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def read_install_manifest(version_dir: Path) -> Optional[dict]:
    try:
        return json.loads((version_dir / INSTALL_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_installed(version_dir: Path, release: Release) -> bool:
    info = read_install_manifest(version_dir)
    if not info or info.get("version") != release.version:
        return False
    if release.sha256 and info.get("sha256") != release.sha256:
        return False
    return (version_dir / "lib").is_dir()


def install_archive(archive: Path, release: Release, dest_base: Path, source_url: str, digest: str, force: bool = False, quiet: bool = False) -> Path:
    """Extract a verified Linux archive into ``dest_base/<version>/`` atomically."""
    dest_base.mkdir(parents=True, exist_ok=True)
    version_dir = dest_base / release.version
    if version_dir.exists() and not force:
        if is_installed(version_dir, release):
            _log("SDK %s is already installed at %s" % (release.version, version_dir), quiet)
            return version_dir
        raise SetupError(
            "%s already exists but was not installed by setup (or holds another build). "
            "Rerun with --force to replace it." % version_dir
        )
    tmp = Path(tempfile.mkdtemp(prefix=".%s.partial-" % release.version, dir=str(dest_base)))
    try:
        layout = release.layout if release.layout in ("tar", "zip") else _infer_layout(archive)
        files = extract_zip(archive, tmp) if layout == "zip" else extract_tar(archive, tmp)
        write_install_manifest(tmp, release, source_url, digest, files=len(files))
        os.chmod(tmp, 0o755)
        if version_dir.exists():
            shutil.rmtree(version_dir)
        os.replace(tmp, version_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    _log("Installed SDK %s into %s (%d files)" % (release.version, version_dir, len(files)), quiet)
    return version_dir


# ---------------------------------------------------------------------------
# udev rules (USB cameras, Linux)
# ---------------------------------------------------------------------------


def udev_commands(rule_files: Sequence[Path]) -> List[List[str]]:
    return [
        ["sudo", "install", "-m", "0644", *[str(p) for p in rule_files], UDEV_DIR + "/"],
        ["sudo", "udevadm", "control", "--reload-rules"],
        ["sudo", "udevadm", "trigger"],
    ]


def install_udev_rules(version_dir: Path, assume_yes: bool = False, quiet: bool = False, runner: Callable[..., object] = subprocess.run) -> int:
    """Offer to install the vendor udev rules with ``sudo``; return an exit code."""
    if current_os() != "linux":
        _log("udev rules apply to Linux only; skipping.", quiet)
        return 0
    sources = [version_dir / name for name in UDEV_RULES if (version_dir / name).is_file()]
    if not sources:
        _log("No udev rules found in %s." % version_dir, quiet)
        return 1
    staging = Path(tempfile.mkdtemp(prefix="gcam-mvsdk-py-udev-"))
    try:
        staged = []
        for src in sources:
            # The vendor files use CRLF line endings; udev expects LF.
            data = src.read_bytes().replace(b"\r\n", b"\n")
            dst = staging / src.name
            dst.write_bytes(data)
            staged.append(dst)
        commands = udev_commands(staged)
        print("USB cameras need the vendor udev rules in %s:" % UDEV_DIR)
        for cmd in commands:
            print("  " + " ".join(cmd))
        if not assume_yes:
            if not sys.stdin.isatty():
                print("Not a terminal; run the commands above yourself, or rerun with --yes.")
                return 0
            answer = input("Install them now with sudo? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print("Skipped.")
                return 0
        for cmd in commands:
            result = runner(cmd)
            code = getattr(result, "returncode", 0)
            if code:
                print("Command failed with exit code %s: %s" % (code, " ".join(cmd)), file=sys.stderr)
                return int(code)
        print("udev rules installed. Replug USB cameras.")
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)


# ---------------------------------------------------------------------------
# Windows installer flow
# ---------------------------------------------------------------------------


def find_7z() -> Optional[str]:
    for name in ("7z", "7za", "7zz"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if os.path.isfile(candidate):
            return candidate
    return None


def install_windows_archive(archive: Path, release: Release, dest_base: Path, source_url: str, digest: str, quiet: bool = False) -> Path:
    """Unpack the vendor ``.rar`` with 7z (if present) and explain the manual installer step."""
    version_dir = dest_base / release.version
    version_dir.mkdir(parents=True, exist_ok=True)
    kept = version_dir / archive.name
    if archive.resolve() != kept.resolve():
        shutil.copy2(archive, kept)
    seven = find_7z()
    installers: List[Path] = []
    if seven:
        out_dir = version_dir / "installer"
        out_dir.mkdir(exist_ok=True)
        result = subprocess.run([seven, "x", "-y", "-o%s" % out_dir, str(kept)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            _log(result.stdout.decode(errors="replace"), quiet)
            raise SetupError("7z could not extract %s (exit %d)" % (kept, result.returncode))
        installers = sorted(out_dir.rglob("*.exe"))
    write_install_manifest(
        version_dir,
        release,
        source_url,
        digest,
        state="installer-extracted" if installers else "archive-verified",
        installers=[str(p) for p in installers],
    )
    lines = ["", "Verified vendor archive: %s" % kept]
    if installers:
        lines.append("Extracted installer(s):")
        lines.extend("  %s" % p for p in installers)
    else:
        lines.append("7-Zip was not found, so the .rar was not unpacked. Install 7-Zip (https://www.7-zip.org/)")
        lines.append("and rerun this command, or extract the archive with any RAR tool.")
    arch = detect_arch()
    dll = "MVCAMSDK_X64.dll" if arch == "x64" else "MVCAMSDK.dll"
    lines += [
        "",
        "Next steps (manual, administrator rights required):",
        "  1. Run the installer. It installs the SDK and the GigE filter and USB drivers;",
        "     the DLL alone is not sufficient for GigE cameras.",
        "  2. Point gcam-mvsdk-py at the installed DLL, either by adding the SDK directory that",
        "     contains %s to PATH, setting GCAM_MVSDK_DIR to it, or copying the DLL to" % dll,
        "     %s" % (version_dir / "lib" / arch),
        "  3. Run `gcam-mvsdk-py doctor` to confirm.",
    ]
    print("\n".join(lines))
    return version_dir


# ---------------------------------------------------------------------------
# Entry point used by the CLI
# ---------------------------------------------------------------------------


def run(
    source: Optional[str] = None,
    version: Optional[str] = None,
    dest: Optional[str] = None,
    udev: bool = False,
    force: bool = False,
    assume_yes: bool = False,
    keep_archive: bool = False,
    allow_unverified: bool = False,
    manifest: Optional[str] = None,
    quiet: bool = False,
) -> int:
    """Implement ``gcam-mvsdk-py setup``; return a process exit code."""
    try:
        releases = load_manifest(manifest)
    except ManifestError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    dest_base = Path(dest).expanduser().resolve() if dest else sdk_home()
    os_name = current_os()

    try:
        if source:
            archive = Path(source).expanduser()
            if not archive.is_file():
                raise SetupError("%s does not exist" % archive)
            _log("Verifying %s ..." % archive, quiet)
            release, digest = release_for_file(archive, releases, version, allow_unverified, quiet)
            source_url = archive.resolve().as_uri()
            downloaded: Optional[Path] = None
        else:
            release = select_release(releases, os_name, version)
            version_dir = dest_base / release.version
            if release.layout in ("tar", "zip") and not force and is_installed(version_dir, release):
                _log("SDK %s is already installed at %s (use --force to reinstall)." % (release.version, version_dir), quiet)
                return install_udev_rules(version_dir, assume_yes, quiet) if udev else 0
            downloads = dest_base / DOWNLOADS_DIRNAME
            archive = downloads / release.filename
            digest = ""
            if archive.is_file() and archive.stat().st_size == release.size:
                _log("Reusing previously downloaded %s" % archive, quiet)
                cached = sha256_file(archive)
                if release.sha256 and cached != release.sha256:
                    _log("Cached file fails verification; downloading again.", quiet)
                    archive.unlink()
                else:
                    digest = cached
            if not digest:
                _log("Checking %s" % release.url, quiet)
                head_check(release)
                _log("Downloading SDK %s for %s (%s) ..." % (release.version, release.os, _human(release.size)), quiet)
                digest = download(release, archive, quiet=quiet)
            try:
                digest = verify(archive, release, digest, allow_unverified=allow_unverified, quiet=quiet)
            except ChecksumMismatch:
                if release.sha256:
                    archive.unlink(missing_ok=True)  # never keep a file that failed verification
                raise
            source_url = release.url
            downloaded = archive

        if release.layout == "rar-installer":
            version_dir = install_windows_archive(archive, release, dest_base, source_url, digest, quiet)
            if downloaded is not None and not keep_archive:
                downloaded.unlink(missing_ok=True)
            return 0

        version_dir = install_archive(archive, release, dest_base, source_url, digest, force=force, quiet=quiet)
        if downloaded is not None and not keep_archive:
            downloaded.unlink(missing_ok=True)
            try:
                downloaded.parent.rmdir()
            except OSError:
                pass
        lib_dir = version_dir / "lib" / detect_arch()
        if not lib_dir.is_dir():
            _log("WARNING: %s does not exist; set GCAM_MVSDK_ARCH to one of: %s" % (
                lib_dir, ", ".join(sorted(p.name for p in (version_dir / "lib").iterdir() if p.is_dir()))), quiet)
        else:
            _log("Library for this machine: %s" % lib_dir, quiet)
        if udev:
            return install_udev_rules(version_dir, assume_yes, quiet)
        return 0
    except (SetupError, ManifestError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


def available_releases(manifest: Optional[str] = None) -> List[Release]:
    return releases_for_os(load_manifest(manifest), current_os())
