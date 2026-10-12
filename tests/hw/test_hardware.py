"""Hardware tests against real cameras. Skipped unless GCAM_MVSDK_HW_TEST=1.

Optional environment variables:

* ``GCAM_MVSDK_HW_EXPECT``: comma-separated user-set names that must be
  present, for example ``sb00,sb01,sb02,sb03``.
* ``GCAM_MVSDK_HW_CAMERA``: serial number or user-set name used for the grab
  tests (default: the first camera that can be opened).
* ``GCAM_MVSDK_HW_RENAME_SN``: serial number of a camera whose user-set name
  may be rewritten for the rename round trip (it is restored afterwards).
"""

from __future__ import annotations

import os

import numpy as np
import pytest

pytestmark = [
    pytest.mark.hw,
    pytest.mark.skipif(os.environ.get("GCAM_MVSDK_HW_TEST") != "1", reason="set GCAM_MVSDK_HW_TEST=1 to run hardware tests"),
]


@pytest.fixture(scope="module")
def sdk():
    import gcam_mvsdk_py

    return gcam_mvsdk_py.load()


@pytest.fixture(scope="module")
def devices(sdk):
    devs = sdk.enumerate()
    if not devs:
        pytest.fail("no cameras discovered; run `gcam-mvsdk-py doctor`")
    return devs


@pytest.fixture(scope="module")
def target(sdk, devices):
    key = os.environ.get("GCAM_MVSDK_HW_CAMERA")
    if key:
        return sdk.find(key, devices)
    for dev in devices:
        if sdk.read_user_name(dev) is not None:
            return dev
    pytest.skip("every camera is in use by another process")


def test_sdk_version(sdk):
    assert sdk.version()


def test_enumerate_finds_expected_names(sdk, devices):
    expected = [n for n in os.environ.get("GCAM_MVSDK_HW_EXPECT", "").split(",") if n]
    names = {sdk.read_user_name(d) for d in devices}
    for name in expected:
        assert name in names, "camera %r not found among %r" % (name, sorted(n for n in names if n))
    for dev in devices:
        assert dev.serial
        if dev.is_gige:
            ip = dev.gige_ip()
            assert ip.camera_ip.count(".") == 3


def test_grab_mono8_shape_and_view_matches_copy(sdk, target):
    import gcam_mvsdk_py

    with sdk.open(target) as cam:
        cam.output_format = gcam_mvsdk_py.Mono8
        cam.trigger_mode = gcam_mvsdk_py.TRIGGER_CONTINUOUS
        width, height = cam.resolution
        cam.play()
        with cam.grab(timeout_ms=3000) as frame:
            view = frame.view()
            raw_copy = frame.to_numpy(process=False)
            processed = frame.to_numpy()
            assert np.array_equal(view, raw_copy)
            assert view.tobytes() == raw_copy.tobytes()
        assert processed.dtype == np.uint8
        assert processed.shape == (height, width)
        assert (frame.width, frame.height) == (width, height)


def test_rename_round_trip(sdk, devices):
    serial = os.environ.get("GCAM_MVSDK_HW_RENAME_SN")
    if not serial:
        pytest.skip("set GCAM_MVSDK_HW_RENAME_SN to allow writing a camera's user-set name")
    dev = next(d for d in devices if d.serial == serial)
    with sdk.open(dev) as cam:
        original = cam.user_name
        try:
            cam.user_name = "hwtest"
            assert cam.user_name == "hwtest"
        finally:
            cam.user_name = original
        assert cam.user_name == original
