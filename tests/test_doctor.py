"""``gcam-mvsdk-py doctor`` reporting of the SDK section (host checks are stubbed)."""

from __future__ import annotations

import pytest

from gcam_mvsdk_py import _doctor


@pytest.fixture
def quiet_host(monkeypatch):
    """Keep the network and firewall checks independent of the machine running the tests."""
    monkeypatch.setattr(_doctor, "list_interfaces", lambda: [])
    monkeypatch.setattr(_doctor, "firewall_status", lambda: [])


def test_doctor_reports_a_wrong_gcam_mvsdk_dir(isolated_env, quiet_host, monkeypatch, capsys):
    empty = isolated_env["root"] / "empty-sdk"
    empty.mkdir()
    monkeypatch.setenv("GCAM_MVSDK_DIR", str(empty))
    assert _doctor.run() == 1
    out = capsys.readouterr().out
    assert "[FAIL] GCAM_MVSDK_DIR is set to %s, a directory that holds no MVSDK library" % empty in out
    assert "no other location is searched" in out and "unset it" in out
    assert "[dynamic loader]" not in out


def test_doctor_reports_missing_sdk_without_gcam_mvsdk_dir(isolated_env, quiet_host, capsys):
    assert _doctor.run() == 1
    out = capsys.readouterr().out
    assert "MVSDK library not found" in out and "gcam-mvsdk-py setup" in out
