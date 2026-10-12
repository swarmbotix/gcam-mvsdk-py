"""Search path and architecture mapping of the runtime loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from gcam_mvsdk_py import _loader
from gcam_mvsdk_py._errors import SdkNotFound

VERSION = "2.1.0.49"


def make_lib(root: Path, arch: str = "x64", name: str = "libMVSDK.so") -> Path:
    path = root / "lib" / arch / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake library")
    return path


def make_native_lib(root: Path) -> Path:
    """Fake library with the directory and file name the loader expects on this platform.

    Tests that call the loader without pinning ``system``/``arch`` must use this:
    the loader looks for libMVSDK.so on Linux, libMVSDK.dylib on macOS, and
    MVCAMSDK_X64.dll / MVCAMSDK.dll on Windows.
    """
    return make_lib(root, arch=_loader.detect_arch(), name=_loader.library_names()[0])


@pytest.mark.parametrize(
    "machine, bits, system, expected",
    [
        ("x86_64", 64, "Linux", "x64"),
        ("AMD64", 64, "Linux", "x64"),
        ("aarch64", 64, "Linux", "arm64"),
        ("arm64", 64, "Darwin", "arm64"),
        ("armv7l", 32, "Linux", "arm"),
        ("armv6l", 32, "Linux", "arm"),
        ("i686", 32, "Linux", "x86"),
        ("i386", 32, "Linux", "x86"),
        ("x86_64", 32, "Linux", "x86"),  # 32-bit interpreter on a 64-bit kernel
        ("aarch64", 32, "Linux", "arm"),  # 32-bit userland on a 64-bit kernel
        ("AMD64", 64, "Windows", "x64"),
        ("AMD64", 32, "Windows", "x86"),
        ("x86", 32, "Windows", "x86"),
        ("riscv64", 64, "Linux", "riscv64"),
    ],
)
def test_detect_arch(machine, bits, system, expected):
    assert _loader.detect_arch(machine=machine, pointer_bits=bits, system=system, env={}) == expected


def test_arch_override_for_soft_float():
    env = {"GCAM_MVSDK_ARCH": "arm_softfp"}
    assert _loader.detect_arch(machine="armv7l", pointer_bits=32, system="Linux", env=env) == "arm_softfp"


@pytest.mark.parametrize(
    "system, bits, expected",
    [
        ("Linux", 64, ["libMVSDK.so"]),
        ("Linux", 32, ["libMVSDK.so"]),
        ("Windows", 64, ["MVCAMSDK_X64.dll"]),
        ("Windows", 32, ["MVCAMSDK.dll"]),
    ],
)
def test_library_names(system, bits, expected):
    assert _loader.library_names(system=system, pointer_bits=bits) == expected


def _find(env=None):
    return _loader.find_library(env=env, arch="x64", system="Linux", manifest_versions=[VERSION])


def test_search_order(isolated_env, monkeypatch):
    home, work, root = isolated_env["home"], isolated_env["work"], isolated_env["root"]
    home_lib = make_lib(home / ".gcam-mvsdk" / VERSION)
    vendor_lib = make_lib(work / "vendor" / VERSION)
    env_root = root / "envsdk"
    env_lib = make_lib(env_root)
    system_lib = root / "system-lib" / "libMVSDK.so"
    system_lib.parent.mkdir()
    system_lib.write_bytes(b"fake")

    env = {"GCAM_MVSDK_DIR": str(env_root)}
    loc = _find(env)
    assert Path(loc.path) == env_lib and loc.origin == "GCAM_MVSDK_DIR" and loc.sdk_root == env_root

    loc = _find({})
    assert Path(loc.path) == vendor_lib and loc.origin == "./vendor"
    assert loc.sdk_root == work / "vendor" / VERSION

    vendor_lib.unlink()
    loc = _find({})
    assert Path(loc.path) == home_lib and loc.origin == "~/.gcam-mvsdk"

    home_lib.unlink()
    loc = _find({})
    assert Path(loc.path) == system_lib and loc.origin == "system"

    system_lib.unlink()
    assert _find({}) is None


def test_env_dir_lib_without_arch(isolated_env):
    root = isolated_env["root"] / "flat"
    lib = root / "lib" / "libMVSDK.so"
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b"fake")
    loc = _find({"GCAM_MVSDK_DIR": str(root)})
    assert Path(loc.path) == lib


def test_env_dir_prefers_arch_subdirectory(isolated_env):
    root = isolated_env["root"] / "both"
    arch_lib = make_lib(root)
    (root / "lib" / "libMVSDK.so").write_bytes(b"generic")
    assert Path(_find({"GCAM_MVSDK_DIR": str(root)}).path) == arch_lib


def test_arch_override_selects_directory(isolated_env, monkeypatch):
    home = isolated_env["home"]
    make_lib(home / ".gcam-mvsdk" / VERSION, arch="arm")
    soft = make_lib(home / ".gcam-mvsdk" / VERSION, arch="arm_softfp")
    monkeypatch.setenv("GCAM_MVSDK_ARCH", "arm_softfp")
    loc = _loader.find_library(system="Linux", manifest_versions=[VERSION])
    assert Path(loc.path) == soft


def test_unknown_newer_version_directory_is_found_first(isolated_env):
    home = isolated_env["home"]
    make_lib(home / ".gcam-mvsdk" / VERSION)
    newer = make_lib(home / ".gcam-mvsdk" / "2.1.10.7")
    assert Path(_find({}).path) == newer


def test_version_ordering_is_numeric(tmp_path):
    for v in ("2.1.0.49", "2.1.0.100", "2.1.0.9"):
        (tmp_path / v / "lib").mkdir(parents=True)
    (tmp_path / ".hidden" / "lib").mkdir(parents=True)
    assert _loader.candidate_versions(tmp_path, []) == ["2.1.0.100", "2.1.0.49", "2.1.0.9"]


def test_describe_search_lists_every_location(isolated_env):
    entries = _loader.describe_search(env={"GCAM_MVSDK_DIR": "/opt/sdk"}, arch="x64", system="Linux",
                                      manifest_versions=[VERSION])
    text = "\n".join(entries)
    env_root = str(Path("/opt/sdk"))  # uses backslashes on Windows
    assert str(Path("/opt/sdk/lib/x64/libMVSDK.so")) in text
    assert str(isolated_env["work"] / "vendor" / VERSION / "lib" / "x64" / "libMVSDK.so") in text
    assert str(isolated_env["home"] / ".gcam-mvsdk" / VERSION / "lib" / "x64" / "libMVSDK.so") in text
    assert "[dynamic loader]" in text
    # Order: env, vendor, home, system.
    idx = [text.index(s) for s in (env_root, "vendor", ".gcam-mvsdk", "system-lib")]
    assert idx == sorted(idx)


def test_open_library_raises_sdk_not_found(isolated_env, monkeypatch):
    # An SDK directory without a library for this platform. It also makes the
    # ~/.gcam-mvsdk/<version> candidates appear on macOS, where the manifest has
    # no release and versions are discovered from the file system only.
    (isolated_env["home"] / ".gcam-mvsdk" / VERSION / "lib").mkdir(parents=True)

    def refuse(path):
        raise OSError("cannot open shared object file")

    monkeypatch.setattr(_loader, "_open", refuse)
    with pytest.raises(SdkNotFound) as info:
        _loader.open_library()
    message = str(info.value)
    assert "gcam-mvsdk-py setup" in message
    assert "GCAM_MVSDK_DIR" in message
    assert info.value.searched
    assert any(".gcam-mvsdk" in s for s in info.value.searched)


def test_open_library_reports_rejected_file(isolated_env, monkeypatch):
    # The rejection is simulated (as glibc reports "wrong ELF class" and Windows
    # reports "%1 is not a valid Win32 application"), so this runs on every platform.
    lib = make_native_lib(isolated_env["home"] / ".gcam-mvsdk" / VERSION)

    def refuse(path):
        raise OSError("simulated loader rejection: wrong architecture")

    monkeypatch.setattr(_loader, "_open", refuse)
    with pytest.raises(SdkNotFound) as info:
        _loader.open_library()
    assert str(lib) in str(info.value)
    assert "simulated loader rejection" in str(info.value)


def test_open_library_with_directory_argument(isolated_env, monkeypatch):
    root = isolated_env["root"] / "explicit"
    lib = make_native_lib(root)
    opened = []
    monkeypatch.setattr(_loader, "_open", lambda path: opened.append(path) or object())
    _, loc = _loader.open_library(str(root))
    assert opened == [str(lib)] and loc.sdk_root == root


def test_sdk_home_uses_home(isolated_env):
    assert _loader.sdk_home() == isolated_env["home"] / ".gcam-mvsdk"


def test_gcam_mvsdk_home_overrides_default(isolated_env, monkeypatch):
    custom = isolated_env["root"] / "custom-home"
    lib = make_lib(custom / VERSION)
    make_lib(isolated_env["home"] / ".gcam-mvsdk" / VERSION)
    monkeypatch.setenv("GCAM_MVSDK_HOME", str(custom))
    assert _loader.sdk_home() == custom
    loc = _loader.find_library(arch="x64", system="Linux", manifest_versions=[VERSION])
    assert Path(loc.path) == lib and loc.origin == "SDK home"


def test_venv_marker_is_used_when_env_is_unset(isolated_env, monkeypatch):
    recorded = isolated_env["root"] / "recorded-home"
    monkeypatch.setattr(_loader, "_venv_marker_home", lambda: recorded)
    assert _loader.sdk_home() == recorded
    monkeypatch.setenv("GCAM_MVSDK_HOME", str(isolated_env["root"] / "env-home"))
    assert _loader.sdk_home() == isolated_env["root"] / "env-home"


def test_venv_marker_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(_loader.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(_loader.sys, "base_prefix", "/usr")
    assert _loader._venv_marker_home() is None
    (tmp_path / _loader.VENV_HOME_MARKER).write_text(str(tmp_path / "sdk") + "\n")
    assert _loader._venv_marker_home() == tmp_path / "sdk"
    monkeypatch.setattr(_loader.sys, "base_prefix", str(tmp_path))  # not a venv: ignored
    assert _loader._venv_marker_home() is None
