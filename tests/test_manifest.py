"""sdk-manifest.toml: content, parsing, and release selection."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from gcam_mvsdk_py import _manifest

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "sdk-manifest.toml"
RUST_COPY = REPO.parent / "gcam-mvsdk-rs" / "sdk-manifest.toml"
# SHA-256 of the committed manifest; changing the file requires changing the
# Rust repository's copy identically.
MANIFEST_SHA256 = "d7cab9f9a7ca0eb3e969a36d45c440269b12a3fcd433ce437d5886f6573934b2"

LINUX_SHA = "9624d193a908d94a9850400346cf1ab8095437a040e381b2fd39029b0183dd8a"


def test_manifest_file_content_is_pinned():
    assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == MANIFEST_SHA256


@pytest.mark.skipif(not RUST_COPY.is_file(), reason="gcam-mvsdk-rs checkout not present next to this repository")
def test_manifest_is_byte_identical_to_rust_copy():
    assert MANIFEST.read_bytes() == RUST_COPY.read_bytes()


def test_default_lookup_finds_repository_manifest():
    assert _manifest.find_manifest().resolve() in {
        MANIFEST.resolve(),
        (Path(_manifest.__file__).resolve().parent / "sdk-manifest.toml"),
    }


def test_parse_repository_manifest():
    releases = _manifest.load_manifest(MANIFEST)
    assert len(releases) == 2
    linux = _manifest.select_release(releases, "linux")
    assert linux.version == "2.1.0.49"
    assert linux.size == 57978497
    assert linux.sha256 == LINUX_SHA
    assert linux.layout == "tar"
    assert linux.url.startswith("http://huatengvision.com/attachment/down/13/")
    assert linux.filename == "linuxSDK_V2.1.0.49(202511141513).tar.gz"
    windows = _manifest.select_release(releases, "windows")
    assert windows.version == "2.1.10.195"
    assert windows.layout == "rar-installer"
    assert windows.sha256 == "" and not windows.has_checksum
    assert windows.size == 128081184
    assert windows.filename == "HuaTengVision Camera Platform Setup(2.1.10.195_20260616).rar"


def test_select_release_errors():
    releases = _manifest.load_manifest(MANIFEST)
    with pytest.raises(_manifest.ManifestError):
        _manifest.select_release(releases, "macos")
    with pytest.raises(_manifest.ManifestError):
        _manifest.select_release(releases, "linux", "9.9.9")
    assert _manifest.select_release(releases, "linux", "2.1.0.49").version == "2.1.0.49"


def test_find_by_sha256():
    releases = _manifest.load_manifest(MANIFEST)
    assert _manifest.find_by_sha256(releases, LINUX_SHA.upper()).os == "linux"
    assert _manifest.find_by_sha256(releases, "0" * 64) is None
    # An empty recorded checksum never matches.
    assert _manifest.find_by_sha256(releases, "") is None


def test_newest_version_wins():
    text = MANIFEST.read_text() + (
        '\n[[release]]\nversion = "2.1.0.100"\nos = "linux"\nurl = "http://example.invalid/x.tar.gz"\n'
        'size = 1\nsha256 = ""\nlayout = "tar"\n'
    )
    releases = _manifest.parse_manifest(text)
    assert _manifest.select_release(releases, "linux").version == "2.1.0.100"
    assert [r.version for r in _manifest.releases_for_os(releases, "linux")] == ["2.1.0.100", "2.1.0.49"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not toml = = =",
        '[[release]]\nversion = "1"\nos = "linux"\n',
        '[[release]]\nversion = "1"\nos = "linux"\nurl = "u"\nsize = 1\nsha256 = "xyz"\nlayout = "tar"\n',
        '[[release]]\nversion = "1"\nos = "linux"\nurl = "u"\nsize = 0\nsha256 = ""\nlayout = "tar"\n',
    ],
)
def test_malformed_manifests(text):
    with pytest.raises(_manifest.ManifestError):
        _manifest.parse_manifest(text)


def test_version_key():
    assert _manifest.version_key("2.1.0.100") > _manifest.version_key("2.1.0.49")
    assert _manifest.version_key("2.1.10.195") > _manifest.version_key("2.1.0.49")


@pytest.mark.parametrize("name, expected", [("linux", "linux"), ("win32", "windows"), ("darwin", "macos")])
def test_current_os(name, expected):
    assert _manifest.current_os(name) == expected
