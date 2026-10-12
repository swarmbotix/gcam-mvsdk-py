"""Verify that gcam-mvsdk-py build artifacts contain no vendor bytes.

Usage: python .claude/skills/release/check_wheel.py dist/*
Exit status 0 when every artifact passes, 1 otherwise. Standard library only.
"""

from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterator, List, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

REPO = Path(__file__).resolve().parents[3]
FORBIDDEN_SUFFIXES = (
    ".so", ".dll", ".dylib", ".lib", ".a", ".o", ".exe", ".chm", ".pdf",
    ".tar.gz", ".tgz", ".rar", ".zip", ".7z", ".whl",
)
FORBIDDEN_NAMES = {"CameraApi.h", "CameraDefine.h", "CameraStatus.h", "mvsdk.py"}
BINARY_MAGIC = (b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
WHEEL_PACKAGE_SUFFIXES = (".py", ".typed", ".toml")


def project_version() -> str:
    return tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]


def members(path: Path) -> Iterator[Tuple[str, bytes]]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if not info.is_dir():
                    yield info.filename, zf.read(info)
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as tf:
            for info in tf:
                if info.isfile():
                    fh = tf.extractfile(info)
                    yield info.name, fh.read() if fh else b""
                elif not info.isdir():
                    yield info.name, b"<link or special file>"
    else:
        raise ValueError("unsupported artifact %s" % path)


def check_common(name: str, data: bytes, problems: List[str]) -> None:
    base = PurePosixPath(name).name
    lower = name.lower()
    if base in FORBIDDEN_NAMES:
        problems.append("vendor file: %s" % name)
    if lower.endswith(FORBIDDEN_SUFFIXES):
        problems.append("forbidden file type: %s" % name)
    if data.startswith(BINARY_MAGIC):
        problems.append("binary executable content: %s" % name)
    if data == b"<link or special file>":
        problems.append("link or special file: %s" % name)


def check_wheel(path: Path, version: str) -> List[str]:
    problems: List[str] = []
    expected = "gcam_mvsdk_py-%s-py3-none-any.whl" % version
    if path.name != expected:
        problems.append("file name %s, expected %s" % (path.name, expected))
    manifest = (REPO / "sdk-manifest.toml").read_bytes()
    dist_info = "gcam_mvsdk_py-%s.dist-info/" % version
    seen_manifest = False
    for name, data in members(path):
        check_common(name, data, problems)
        if name.startswith(dist_info):
            if name.endswith("/WHEEL"):
                text = data.decode()
                if "Root-Is-Purelib: true" not in text or "Tag: py3-none-any" not in text:
                    problems.append("WHEEL is not pure py3-none-any")
            if name.endswith("/METADATA") and not re.search(r"^Version: %s$" % re.escape(version), data.decode(), re.M):
                problems.append("METADATA version differs from pyproject.toml (%s)" % version)
            continue
        if not name.startswith("gcam_mvsdk_py/"):
            problems.append("unexpected top-level path: %s" % name)
        elif not name.endswith(WHEEL_PACKAGE_SUFFIXES):
            problems.append("unexpected file type in package: %s" % name)
        if name == "gcam_mvsdk_py/sdk-manifest.toml":
            seen_manifest = True
            if data != manifest:
                problems.append("packaged sdk-manifest.toml differs from the repository root copy")
    if not seen_manifest:
        problems.append("gcam_mvsdk_py/sdk-manifest.toml missing")
    return problems


def check_sdist(path: Path, version: str) -> List[str]:
    problems: List[str] = []
    top = "gcam_mvsdk_py-%s/" % version
    names = []
    for name, data in members(path):
        names.append(name)
        check_common(name, data, problems)
        if not name.startswith(top):
            problems.append("unexpected path: %s" % name)
        if "/vendor/" in name:
            problems.append("vendor directory content: %s" % name)
    if top + "sdk-manifest.toml" not in names:
        problems.append("sdk-manifest.toml missing")
    return problems


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    version = project_version()
    failed = False
    for arg in argv:
        path = Path(arg)
        problems = check_wheel(path, version) if path.suffix == ".whl" else check_sdist(path, version)
        size_kib = path.stat().st_size / 1024
        if problems:
            failed = True
            print("FAIL %s (%.0f KiB)" % (path, size_kib))
            for p in problems:
                print("     - %s" % p)
        else:
            print("OK   %s (%.0f KiB, version %s)" % (path, size_kib, version))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
