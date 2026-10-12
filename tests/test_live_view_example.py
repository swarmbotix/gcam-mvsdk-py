"""examples/live_view.py without a camera or a display: argument parsing and early exits.

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


def test_all_options(example):
    ns = example.parse_args(["sb01", "--exposure-us", "2500", "--mtu", "9000", "--window", "bench"])
    assert (ns.camera, ns.exposure_us, ns.mtu, ns.window) == ("sb01", 2500.0, 9000, "bench")


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
