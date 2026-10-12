"""Shared fixtures. Unit tests never need the vendor SDK."""

from __future__ import annotations

import pytest

from gcam_mvsdk_py import _loader


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Empty HOME and cwd, no GCAM_MVSDK_* variables, no system library dirs."""
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for var in ("GCAM_MVSDK_DIR", "GCAM_MVSDK_ARCH", "GCAM_MVSDK_HOME", "LD_LIBRARY_PATH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(_loader, "_venv_marker_home", lambda: None)
    monkeypatch.chdir(work)
    monkeypatch.setattr(_loader, "_system_dirs", lambda sysname, arch, env: [tmp_path / "system-lib"])
    return {"home": home, "work": work, "root": tmp_path}


@pytest.fixture
def reset_sdk_singleton(monkeypatch):
    from gcam_mvsdk_py import api

    monkeypatch.setattr(api, "_SDK_INSTANCE", None)
    yield
