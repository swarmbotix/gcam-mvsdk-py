"""Downloader and installer, exercised with a synthetic SDK archive.

No vendor bytes are used: the archive is generated in a temporary directory
with the vendor's directory layout, and downloads are served by a local
``http.server`` thread.
"""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import stat
import sys
import tarfile
import threading
from pathlib import Path

import pytest

from gcam_mvsdk_py import setup_cmd
from gcam_mvsdk_py._manifest import Release

TOP = "linuxSDK_V9.9.9(000000000000)"
VERSION = "9.9.9"


def _add(tar: tarfile.TarFile, name: str, data: bytes = b"", mode: int = 0o666, kind: bytes = tarfile.REGTYPE, linkname: str = "") -> None:
    info = tarfile.TarInfo(name)
    info.mode = mode
    info.type = kind
    info.linkname = linkname
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    tar.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)


def make_sdk_tarball(path: Path, extra_members=()) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        _add(tar, TOP + "/", kind=tarfile.DIRTYPE, mode=0o777)
        _add(tar, TOP + "/include/", kind=tarfile.DIRTYPE, mode=0o777)
        _add(tar, TOP + "/include/CameraApi.h", b"/* synthetic */\n")
        for arch in ("x64", "arm64", "arm", "arm_softfp", "x86"):
            _add(tar, TOP + "/lib/%s/libMVSDK.so" % arch, b"\x7fELF synthetic " + arch.encode())
        _add(tar, TOP + "/tools/GeConfigCmd/x64/GeConfigCmd", b"#!/bin/sh\n")
        _add(tar, TOP + "/tools/QGeConfigTools/QGeConfigTools", b"not extracted")
        _add(tar, TOP + "/tools/QGeConfigTools/AppRun", kind=tarfile.SYMTYPE, linkname="QGeConfigTools")
        _add(tar, TOP + "/demo/python_demo/mvsdk.py", b"not extracted")
        _add(tar, TOP + "/88-mvusb.rules", b"RULE88\r\n")
        _add(tar, TOP + "/99-mvusb.rules", b"# comment\r\nRULE99\r\n")
        _add(tar, TOP + "/install.sh", b"not extracted")
        for member in extra_members:
            _add(tar, *member)
    return path


def release_for(path: Path, url: str = "", sha: str = None) -> Release:
    data = path.read_bytes()
    return Release(
        version=VERSION,
        os="linux",
        url=url or "http://127.0.0.1:1/never.tar.gz",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest() if sha is None else sha,
        layout="tar",
    )


def write_manifest(path: Path, releases) -> Path:
    blocks = []
    for r in releases:
        blocks.append(
            '[[release]]\nversion = "%s"\nos = "%s"\nurl = "%s"\nsize = %d\nsha256 = "%s"\nlayout = "%s"\n'
            % (r.version, r.os, r.url, r.size, r.sha256, r.layout)
        )
    path.write_text("\n".join(blocks))
    return path


@pytest.fixture
def archive(tmp_path):
    return make_sdk_tarball(tmp_path / "sdk.tar.gz")


def test_install_from_local_archive(tmp_path, archive, capsys):
    manifest = write_manifest(tmp_path / "m.toml", [release_for(archive)])
    dest = tmp_path / "vendor"
    code = setup_cmd.run(source=str(archive), dest=str(dest), manifest=str(manifest), quiet=True)
    assert code == 0
    root = dest / VERSION
    assert (root / "include" / "CameraApi.h").is_file()
    for arch in ("x64", "arm64", "arm", "arm_softfp", "x86"):
        assert (root / "lib" / arch / "libMVSDK.so").is_file()
    assert (root / "tools" / "GeConfigCmd" / "x64" / "GeConfigCmd").is_file()
    assert (root / "99-mvusb.rules").is_file()
    assert not (root / "tools" / "QGeConfigTools").exists()
    assert not (root / "demo").exists()
    assert not (root / "install.sh").exists()
    if os.name == "posix":
        mode = stat.S_IMODE((root / "include" / "CameraApi.h").stat().st_mode)
        assert mode == 0o644
        assert stat.S_IMODE((root / "lib" / "x64" / "libMVSDK.so").stat().st_mode) == 0o755
    info = json.loads((root / "manifest.json").read_text())
    for key in ("version", "source_url", "sha256", "installed_at"):
        assert key in info
    assert info["version"] == VERSION
    assert info["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert info["source_url"].startswith("file://")
    # No temporary directories are left behind.
    assert sorted(p.name for p in dest.iterdir()) == [VERSION]


def test_second_install_is_a_no_op(tmp_path, archive, capsys):
    manifest = write_manifest(tmp_path / "m.toml", [release_for(archive)])
    dest = tmp_path / "vendor"
    assert setup_cmd.run(source=str(archive), dest=str(dest), manifest=str(manifest), quiet=True) == 0
    stamp = (dest / VERSION / "manifest.json").read_text()
    assert setup_cmd.run(source=str(archive), dest=str(dest), manifest=str(manifest)) == 0
    assert "already installed" in capsys.readouterr().err
    assert (dest / VERSION / "manifest.json").read_text() == stamp


def test_checksum_mismatch_aborts(tmp_path, archive, capsys):
    manifest = write_manifest(tmp_path / "m.toml", [release_for(archive, sha="0" * 64)])
    dest = tmp_path / "vendor"
    code = setup_cmd.run(source=str(archive), dest=str(dest), manifest=str(manifest), quiet=True)
    assert code == 1
    assert "does not match any release" in capsys.readouterr().err
    assert not (dest / VERSION).exists()


def test_checksum_mismatch_with_explicit_version(tmp_path, archive, capsys):
    manifest = write_manifest(tmp_path / "m.toml", [release_for(archive, sha="0" * 64)])
    code = setup_cmd.run(source=str(archive), version=VERSION, dest=str(tmp_path / "v"), manifest=str(manifest), quiet=True)
    assert code == 1
    assert "SHA-256 mismatch" in capsys.readouterr().err


def test_unknown_version_requires_allow_unverified(tmp_path, archive, capsys):
    manifest = write_manifest(tmp_path / "m.toml", [release_for(archive, sha="0" * 64)])
    dest = tmp_path / "v"
    assert setup_cmd.run(source=str(archive), version="1.2.3", dest=str(dest), manifest=str(manifest), quiet=True) == 1
    assert setup_cmd.run(source=str(archive), version="1.2.3", dest=str(dest), manifest=str(manifest),
                         allow_unverified=True, quiet=True) == 0
    assert (dest / "1.2.3" / "lib" / "x64" / "libMVSDK.so").is_file()


def test_unsafe_member_is_rejected(tmp_path, capsys):
    bad = make_sdk_tarball(tmp_path / "bad.tar.gz", extra_members=[(TOP + "/lib/../../escape.so", b"x")])
    manifest = write_manifest(tmp_path / "m.toml", [release_for(bad)])
    dest = tmp_path / "vendor"
    assert setup_cmd.run(source=str(bad), dest=str(dest), manifest=str(manifest), quiet=True) == 1
    assert "unsafe" in capsys.readouterr().err
    assert not (tmp_path / "escape.so").exists()
    assert not (dest / VERSION).exists()


def test_archive_without_lib_is_rejected(tmp_path, capsys):
    path = tmp_path / "empty.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        _add(tar, "top/readme.txt", b"hello")
    manifest = write_manifest(tmp_path / "m.toml", [release_for(path)])
    assert setup_cmd.run(source=str(path), dest=str(tmp_path / "d"), manifest=str(manifest), quiet=True) == 1
    assert "lib/" in capsys.readouterr().err


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture
def http_root(tmp_path):
    root = tmp_path / "www"
    root.mkdir()

    def handler(*args, **kwargs):
        return _Handler(*args, directory=str(root), **kwargs)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield root, "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()
    server.server_close()


def test_download_verify_extract_over_http(tmp_path, http_root, capsys, monkeypatch):
    root, base = http_root
    archive = make_sdk_tarball(root / "linuxSDK_V9.9.9%28x%29.tar.gz".replace("%28", "(").replace("%29", ")"))
    url = base + "/linuxSDK_V9.9.9%28x%29.tar.gz"
    manifest = write_manifest(tmp_path / "m.toml", [release_for(archive, url=url)])
    monkeypatch.setattr(setup_cmd, "current_os", lambda: "linux")
    dest = tmp_path / "home" / ".gcam-mvsdk"
    code = setup_cmd.run(dest=str(dest), manifest=str(manifest), quiet=True)
    assert code == 0, capsys.readouterr().err
    assert (dest / VERSION / "lib" / "x64" / "libMVSDK.so").is_file()
    info = json.loads((dest / VERSION / "manifest.json").read_text())
    assert info["source_url"] == url
    # The downloaded archive is removed after extraction by default.
    assert not (dest / setup_cmd.DOWNLOADS_DIRNAME).exists()
    # Running again detects the installation without downloading.
    assert setup_cmd.run(dest=str(dest), manifest=str(manifest)) == 0
    assert "already installed" in capsys.readouterr().err


def test_head_size_mismatch_aborts(tmp_path, http_root, capsys, monkeypatch):
    root, base = http_root
    archive = make_sdk_tarball(root / "sdk.tar.gz")
    rel = release_for(archive, url=base + "/sdk.tar.gz")
    rel = Release(rel.version, rel.os, rel.url, rel.size + 1, rel.sha256, rel.layout)
    manifest = write_manifest(tmp_path / "m.toml", [rel])
    monkeypatch.setattr(setup_cmd, "current_os", lambda: "linux")
    assert setup_cmd.run(dest=str(tmp_path / "d"), manifest=str(manifest), quiet=True) == 1
    assert "size changed" in capsys.readouterr().err


def test_http_404_explains_manual_route(tmp_path, http_root, capsys, monkeypatch):
    _, base = http_root
    rel = Release(VERSION, "linux", base + "/missing.tar.gz", 10, "a" * 64, "tar")
    manifest = write_manifest(tmp_path / "m.toml", [rel])
    monkeypatch.setattr(setup_cmd, "current_os", lambda: "linux")
    assert setup_cmd.run(dest=str(tmp_path / "d"), manifest=str(manifest), quiet=True) == 1
    err = capsys.readouterr().err
    assert "HTTP 404" in err and "--from" in err


def test_verify_requires_checksum_or_flag(tmp_path):
    f = tmp_path / "x.rar"
    f.write_bytes(b"data")
    rel = Release("1", "windows", "http://x/x.rar", 4, "", "rar-installer")
    with pytest.raises(setup_cmd.ChecksumMismatch) as info:
        setup_cmd.verify(f, rel)
    assert hashlib.sha256(b"data").hexdigest() in str(info.value)
    assert setup_cmd.verify(f, rel, allow_unverified=True, quiet=True) == hashlib.sha256(b"data").hexdigest()
    with pytest.raises(setup_cmd.ChecksumMismatch):
        setup_cmd.verify(f, Release("1", "windows", "u", 5, "", "rar-installer"), allow_unverified=True)


def test_windows_flow_without_7z(tmp_path, monkeypatch, capsys):
    rar = tmp_path / "Setup.rar"
    rar.write_bytes(b"Rar!synthetic")
    rel = Release("2.1.10.195", "windows", "http://x/Setup.rar", rar.stat().st_size, "", "rar-installer")
    monkeypatch.setattr(setup_cmd, "find_7z", lambda: None)
    version_dir = setup_cmd.install_windows_archive(rar, rel, tmp_path / "dest", "file:///Setup.rar", "abc", quiet=True)
    out = capsys.readouterr().out
    assert "7-Zip was not found" in out
    assert "GigE filter" in out
    assert (version_dir / "Setup.rar").is_file()
    info = json.loads((version_dir / "manifest.json").read_text())
    assert info["state"] == "archive-verified"


def test_udev_rules_install_commands(tmp_path, archive, capsys, monkeypatch):
    manifest = write_manifest(tmp_path / "m.toml", [release_for(archive)])
    dest = tmp_path / "vendor"
    assert setup_cmd.run(source=str(archive), dest=str(dest), manifest=str(manifest), quiet=True) == 0
    monkeypatch.setattr(setup_cmd, "current_os", lambda: "linux")
    seen = []

    def runner(cmd):
        if cmd[1] == "install":
            seen.append({Path(p).name: Path(p).read_bytes() for p in cmd[4:-1]})
        seen.append(cmd)

        class R:
            returncode = 0

        return R()

    assert setup_cmd.install_udev_rules(dest / VERSION, assume_yes=True, runner=runner) == 0
    staged = seen[0]
    assert set(staged) == {"88-mvusb.rules", "99-mvusb.rules"}
    assert b"\r" not in staged["99-mvusb.rules"]
    assert seen[1][:4] == ["sudo", "install", "-m", "0644"] and seen[1][-1] == "/etc/udev/rules.d/"
    assert seen[2] == ["sudo", "udevadm", "control", "--reload-rules"]
    assert seen[3] == ["sudo", "udevadm", "trigger"]


def test_udev_without_terminal_only_prints(tmp_path, archive, capsys, monkeypatch):
    manifest = write_manifest(tmp_path / "m.toml", [release_for(archive)])
    dest = tmp_path / "vendor"
    assert setup_cmd.run(source=str(archive), dest=str(dest), manifest=str(manifest), quiet=True) == 0
    monkeypatch.setattr(setup_cmd, "current_os", lambda: "linux")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    def runner(cmd):  # pragma: no cover - must not run
        raise AssertionError("must not run sudo without consent")

    assert setup_cmd.install_udev_rules(dest / VERSION, assume_yes=False, runner=runner) == 0
    assert "sudo install" in capsys.readouterr().out


def test_existing_foreign_directory_needs_force(tmp_path, archive, capsys):
    manifest = write_manifest(tmp_path / "m.toml", [release_for(archive)])
    dest = tmp_path / "vendor"
    (dest / VERSION).mkdir(parents=True)
    (dest / VERSION / "mine.txt").write_text("user data")
    assert setup_cmd.run(source=str(archive), dest=str(dest), manifest=str(manifest), quiet=True) == 1
    assert "--force" in capsys.readouterr().err
    assert (dest / VERSION / "mine.txt").is_file()
    assert setup_cmd.run(source=str(archive), dest=str(dest), manifest=str(manifest), force=True, quiet=True) == 0
    assert not (dest / VERSION / "mine.txt").exists()


def test_corrupt_cached_download_is_replaced(tmp_path, http_root, capsys, monkeypatch):
    root, base = http_root
    archive = make_sdk_tarball(root / "sdk.tar.gz")
    rel = release_for(archive, url=base + "/sdk.tar.gz")
    manifest = write_manifest(tmp_path / "m.toml", [rel])
    monkeypatch.setattr(setup_cmd, "current_os", lambda: "linux")
    dest = tmp_path / "d"
    cached = dest / setup_cmd.DOWNLOADS_DIRNAME / "sdk.tar.gz"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"\0" * rel.size)  # right size, wrong content
    assert setup_cmd.run(dest=str(dest), manifest=str(manifest), quiet=True) == 0
    assert (dest / VERSION / "lib" / "x64" / "libMVSDK.so").is_file()


def test_local_archive_without_recorded_checksum(tmp_path, capsys):
    rar = tmp_path / "Setup.rar"
    rar.write_bytes(b"Rar!synthetic installer")
    rel = Release("2.1.10.195", "windows", "http://x/Setup.rar", rar.stat().st_size, "", "rar-installer")
    with pytest.raises(setup_cmd.ChecksumMismatch) as info:
        setup_cmd.release_for_file(rar, [rel], None, allow_unverified=False, quiet=True)
    assert "--allow-unverified" in str(info.value)
    found, digest = setup_cmd.release_for_file(rar, [rel], None, allow_unverified=True, quiet=True)
    assert found == rel and digest == hashlib.sha256(rar.read_bytes()).hexdigest()
