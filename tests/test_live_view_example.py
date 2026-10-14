"""examples/live_view.py without a camera or a display: argument parsing, early exits, recording
keys, the record.yaml options and the save schedule.

cv2 is replaced by a stub module, so no window is ever opened and OpenCV need not be installed.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "live_view.py"


def load_example(monkeypatch, cv2_module):
    monkeypatch.setitem(sys.modules, "cv2", cv2_module)  # None makes `import cv2` fail
    spec = importlib.util.spec_from_file_location("live_view_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def example(monkeypatch):
    return load_example(monkeypatch, types.ModuleType("cv2"))


def test_defaults(example):
    ns = example.parse_args([])
    assert ns.camera is None
    assert ns.exposure_us == 5000.0
    assert ns.mtu is None
    assert ns.window == "gcam-mvsdk-py live view"
    assert ns.config == EXAMPLE.with_name("record.yaml")


def test_all_options(example):
    ns = example.parse_args(["sb01", "--exposure-us", "2500", "--mtu", "9000", "--window", "bench",
                             "--config", "/tmp/r.yaml"])
    assert (ns.camera, ns.exposure_us, ns.mtu, ns.window) == ("sb01", 2500.0, 9000, "bench")
    assert ns.config == Path("/tmp/r.yaml")


def test_keys_start_stop_and_quit(example):
    act = example.action_for_key
    assert act(ord("r"), recording=False) == example.START
    assert act(ord("R"), recording=False) == example.START
    assert act(ord("r"), recording=True) == example.IGNORE  # already recording
    assert act(ord("c"), recording=True) == example.STOP
    assert act(ord("c"), recording=False) == example.IGNORE  # nothing to stop
    assert act(ord("q"), recording=True) == example.QUIT
    assert act(27, recording=False) == example.QUIT  # Esc
    assert act(255, recording=False) == example.IGNORE  # waitKey with no key pressed


def test_record_config_file_and_save_schedule(example, tmp_path):
    cfg = example.RecordConfig
    # The shipped file holds the documented defaults; a missing file falls back to them.
    shipped, found = cfg.load(EXAMPLE.with_name("record.yaml"))
    assert found and shipped == cfg(30.0, 5.0, None)
    missing, found = cfg.load(tmp_path / "none.yaml")
    assert not found and missing == cfg()
    custom = tmp_path / "record.yaml"
    custom.write_text("duration_s: 1\nrate_hz: 5\ndata_dir: ~/rec\n")
    loaded, _ = cfg.load(custom)
    assert loaded == cfg(1.0, 5.0, Path("~/rec").expanduser())
    for bad in ("rate_hz: 0", "duration_s: -1", "rate: 5", "duration_s: fast"):
        with pytest.raises(ValueError):
            cfg.parse(bad)
    # 5 Hz schedule anchored to the start: a 90 fps camera saves one frame per 200 ms.
    s = example.Session(Path("/d"), 100.0, loaded)
    assert s.next_path(100.0) == Path("/d/0.png")
    assert s.next_path(100.011) is None
    assert s.next_path(100.199) is None
    assert s.next_path(100.205) == Path("/d/1.png")
    assert s.next_path(100.4) == Path("/d/2.png")
    assert not s.expired(100.999) and s.expired(101.0)
    assert example.session_dir_name("20261013_142530", "sb 00/a") == "20261013_142530_sb_00_a"
    assert example.session_dir_name("20261013_142530", "") == "20261013_142530_camera"


@pytest.mark.parametrize("argv", [["--mtu", "jumbo"], ["--exposure-us", "fast"], ["a", "b"]])
def test_invalid_arguments(example, argv):
    with pytest.raises(SystemExit) as info:
        example.parse_args(argv)
    assert info.value.code == 2


def test_missing_opencv_explains_the_extra(monkeypatch):
    with pytest.raises(SystemExit) as info:
        load_example(monkeypatch, None)
    assert "pip install 'gcam-mvsdk-py[view]'" in str(info.value.code)


@pytest.mark.parametrize("count", [0, 2])
def test_camera_required_unless_exactly_one(example, monkeypatch, capsys, count):
    fake_sdk = types.SimpleNamespace(enumerate=lambda: [object()] * count)
    monkeypatch.setattr(example.gcam_mvsdk_py, "load", lambda: fake_sdk)
    assert example.main([]) == 2
    assert "gcam-mvsdk-py list" in capsys.readouterr().err
