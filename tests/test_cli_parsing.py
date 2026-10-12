"""Argument parsing and offline behaviour of the command-line interface."""

from __future__ import annotations

import pytest

from gcam_mvsdk_py import cli


def parse(*argv):
    return cli.build_parser().parse_args(list(argv))


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["--help"])
    assert info.value.code == 0
    out = capsys.readouterr().out
    for command in ("setup", "list", "rename", "setip", "info", "grab", "doctor"):
        assert command in out


def test_version_flag(capsys):
    import gcam_mvsdk_py

    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert "gcam-mvsdk-py %s" % gcam_mvsdk_py.__version__ in capsys.readouterr().out


def test_version_matches_pyproject():
    """pyproject.toml is the single source; a stale editable install fails here (reinstall it)."""
    import sys
    from pathlib import Path

    import gcam_mvsdk_py

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert gcam_mvsdk_py.__version__ == expected


def test_command_required():
    with pytest.raises(SystemExit) as info:
        parse()
    assert info.value.code == 2


def test_setup_defaults():
    ns = parse("setup")
    assert ns.command == "setup"
    assert ns.source is None and ns.sdk_version is None and ns.dest is None
    assert not ns.udev and not ns.force and not ns.yes and not ns.allow_unverified


def test_setup_options():
    ns = parse("setup", "--from", "sdk.tar.gz", "--version", "2.1.0.49", "--dest", "vendor/", "--udev", "-y")
    assert ns.source == "sdk.tar.gz"
    assert ns.sdk_version == "2.1.0.49"
    assert ns.dest == "vendor/"
    assert ns.udev and ns.yes


def test_list_flags():
    assert parse("list").json is False
    ns = parse("list", "--json", "--no-open")
    assert ns.json and ns.no_open


def test_global_sdk_option():
    assert parse("--sdk", "/opt/sdk", "list").sdk == "/opt/sdk"


def test_rename():
    ns = parse("rename", "056082422008", "sb03")
    assert ns.serial == "056082422008" and ns.name == "sb03"


@pytest.mark.parametrize("bad", ["a/b", 'x"y', "c:d", ""])
def test_rename_rejects_invalid_names(bad):
    with pytest.raises(SystemExit):
        parse("rename", "SN", bad)


def test_setip():
    ns = parse("setip", "AA-BB-CC-00-11-22", "192.168.1.100", "255.255.255.0", "192.168.1.1")
    assert ns.mac == "aa:bb:cc:00:11:22"
    assert ns.ip == "192.168.1.100"
    assert ns.mask == "255.255.255.0"
    assert ns.gateway == "192.168.1.1"


def test_setip_accepts_prefix_length_mask():
    assert parse("setip", "aabbcc001122", "10.0.0.5", "24", "10.0.0.1").mask == "255.255.255.0"


@pytest.mark.parametrize(
    "argv",
    [
        ("setip", "not-a-mac", "192.168.1.100", "255.255.255.0", "192.168.1.1"),
        ("setip", "aa:bb:cc:00:11", "192.168.1.100", "255.255.255.0", "192.168.1.1"),
        ("setip", "aa:bb:cc:00:11:22", "192.168.1.300", "255.255.255.0", "192.168.1.1"),
        ("setip", "aa:bb:cc:00:11:22", "192.168.1.100", "255.0.255.0", "192.168.1.1"),
        ("setip", "aa:bb:cc:00:11:22", "192.168.1.100", "255.255.255.0"),
    ],
)
def test_setip_rejects_bad_arguments(argv):
    with pytest.raises(SystemExit) as info:
        parse(*argv)
    assert info.value.code == 2


@pytest.mark.parametrize(
    "text, expected",
    [
        ("00:1A:2B:3C:4D:5E", "00:1a:2b:3c:4d:5e"),
        ("00-1a-2b-3c-4d-5e", "00:1a:2b:3c:4d:5e"),
        ("001a.2b3c.4d5e", "00:1a:2b:3c:4d:5e"),
        ("001A2B3C4D5E", "00:1a:2b:3c:4d:5e"),
    ],
)
def test_normalize_mac(text, expected):
    assert cli.normalize_mac(text) == expected


def test_info_and_grab():
    ns = parse("info", "sb01")
    assert ns.target == "sb01" and not ns.json
    ns = parse("grab", "sb01")
    assert ns.count == 1 and ns.output_dir == "." and ns.format == "auto" and ns.exposure_us is None
    ns = parse("grab", "056082422008", "-n", "5", "-o", "frames", "--format", "mono8", "--exposure-us", "5000")
    assert ns.count == 5 and ns.output_dir == "frames" and ns.format == "mono8" and ns.exposure_us == 5000.0


@pytest.mark.parametrize("count", ["0", "-1", "x"])
def test_grab_rejects_bad_count(count):
    with pytest.raises(SystemExit):
        parse("grab", "sb01", "-n", count)


def test_doctor_parses():
    assert parse("doctor").command == "doctor"


def test_missing_sdk_gives_clear_error(isolated_env, reset_sdk_singleton, monkeypatch, capsys):
    from gcam_mvsdk_py import _loader

    def refuse(path):
        raise OSError("not found")

    monkeypatch.setattr(_loader, "_open", refuse)
    code = cli.main(["list"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_NO_SDK
    assert "gcam-mvsdk-py setup" in err
    assert "GCAM_MVSDK_DIR" in err
