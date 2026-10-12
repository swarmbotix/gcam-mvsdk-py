"""Settings added to the safe layer (docs/CAPABILITIES.md), driven by GenericFakeLib.

Each test checks the vendor function that is called, the values passed, and the
round trip through the matching getter. Ranges and support depend on the camera
model and are not checked here.
"""

from __future__ import annotations

import gc
from ctypes import c_double, c_int, c_uint

import pytest

import gcam_mvsdk_py as g
from gcam_mvsdk_py import _ffi, api
from gcam_mvsdk_py._errors import FunctionUnavailable, MvError
from gcam_mvsdk_py._loader import LibraryLocation

from fake_mvsdk import H, W, GenericFakeLib


@pytest.fixture
def fake():
    return GenericFakeLib()


@pytest.fixture
def cam(fake):
    sdk = api.Sdk(fake, LibraryLocation("/fake/libMVSDK.so", "test"))
    camera = sdk.open("SN001")
    yield camera
    camera.close()


@pytest.mark.parametrize(
    "prop, value, setter",
    [
        ("ae_target", 120, "CameraSetAeTarget"),
        ("ae_threshold", 5, "CameraSetAeThreshold"),
        ("gamma", 110, "CameraSetGamma"),
        ("contrast", 90, "CameraSetContrast"),
        ("saturation", 130, "CameraSetSaturation"),
        ("sharpness", 20, "CameraSetSharpness"),
        ("black_level", 8, "CameraSetBlackLevel"),
        ("white_level", 240, "CameraSetWhiteLevel"),
        ("isp_processor", g.ISP_PROCESSOR_DEVICE, "CameraSetIspProcessor"),
        ("color_temperature_mode", g.CT_MODE_PRESET, "CameraSetClrTempMode"),
        ("preset_color_temperature", 1, "CameraSetPresetClrTemp"),
        ("lut_mode", g.LUTMODE_PRESET, "CameraSetLutMode"),
        ("trigger_count", 3, "CameraSetTriggerCount"),
        ("trigger_delay_us", 1500, "CameraSetTriggerDelayTime"),
        ("trigger_period_us", 20000, "CameraSetTriggerPeriodTime"),
        ("ext_trigger_signal", g.EXT_TRIG_TRAILING_EDGE, "CameraSetExtTrigSignalType"),
        ("ext_trigger_shutter", g.EXT_TRIG_EXP_GRR, "CameraSetExtTrigShutterType"),
        ("ext_trigger_delay_us", 250, "CameraSetExtTrigDelayTime"),
        ("ext_trigger_buffered_delay_us", 300, "CameraSetExtTrigBufferedDelayTime"),
        ("ext_trigger_interval_us", 1000, "CameraSetExtTrigIntervalTime"),
        ("ext_trigger_jitter_us", 50, "CameraSetExtTrigJitterTime"),
        ("strobe_mode", g.STROBE_SYNC_WITH_TRIG_MANUAL, "CameraSetStrobeMode"),
        ("strobe_polarity", 0, "CameraSetStrobePolarity"),
        ("strobe_delay_us", 100, "CameraSetStrobeDelayTime"),
        ("strobe_pulse_width_us", 2000, "CameraSetStrobePulseWidth"),
        ("parameter_mode", g.PARAM_MODE_BY_SN, "CameraSetParameterMode"),
    ],
)
def test_integer_settings_round_trip(fake, cam, prop, value, setter):
    setattr(cam, prop, value)
    assert fake.calls_to(setter)[-1] == (cam.handle, value)
    assert getattr(cam, prop) == value


@pytest.mark.parametrize(
    "prop, setter",
    [
        ("anti_flicker", "CameraSetAntiFlick"),
        ("auto_white_balance", "CameraSetWbMode"),
        ("monochrome", "CameraSetMonochrome"),
        ("noise_filter", "CameraSetNoiseFilter"),
        ("dead_pixel_correction", "CameraSetCorrectDeadPixel"),
    ],
)
def test_boolean_settings_round_trip(fake, cam, prop, setter):
    setattr(cam, prop, True)
    assert fake.calls_to(setter)[-1] == (cam.handle, 1)
    assert getattr(cam, prop) is True
    setattr(cam, prop, False)
    assert getattr(cam, prop) is False


@pytest.mark.parametrize(
    "prop, value",
    [("black_level", 256), ("white_level", -1), ("strobe_polarity", 2), ("trigger_count", 0),
     ("trigger_delay_us", -5), ("ext_trigger_jitter_us", -1)],
)
def test_out_of_range_values_are_rejected_before_the_sdk(fake, cam, prop, value):
    before = len(fake.generic_calls)
    with pytest.raises(ValueError):
        setattr(cam, prop, value)
    assert len(fake.generic_calls) == before


def test_digital_gain_rgb(fake, cam):
    cam.digital_gain = (120, 100, 90)
    assert fake.calls_to("CameraSetGain")[-1] == (cam.handle, 120, 100, 90)
    assert cam.digital_gain == (120, 100, 90)


def test_auto_exposure_limits_and_window(fake, cam):
    cam.ae_exposure_range_us = (100.0, 8000.0)
    assert cam.ae_exposure_range_us == (100.0, 8000.0)
    cam.ae_analog_gain_range = (16, 64)
    assert cam.ae_analog_gain_range == (16, 64)
    cam.ae_window = (10, 20, 300, 200)
    assert fake.calls_to("CameraSetAeWindow")[-1] == (cam.handle, 10, 20, 300, 200)
    assert cam.ae_window == (10, 20, 300, 200)
    assert cam.analog_gain_x_range() == (0.0, 0.0, 0.0)  # fake reports zeros


@pytest.mark.parametrize("hz, selector", [(50, 0), (60, 1)])
def test_light_frequency(fake, cam, hz, selector):
    cam.light_frequency_hz = hz
    assert fake.calls_to("CameraSetLightFrequency")[-1] == (cam.handle, selector)
    assert cam.light_frequency_hz == hz


def test_light_frequency_rejects_other_values(cam):
    with pytest.raises(ValueError):
        cam.light_frequency_hz = 55


def test_soft_trigger_and_one_shot_balances(fake, cam):
    cam.soft_trigger()
    cam.white_balance_once()
    cam.black_balance_once()
    assert fake.calls_to("CameraSoftTrigger") == [(cam.handle,)]
    assert fake.calls_to("CameraSetOnceWB") == [(cam.handle,)]
    assert fake.calls_to("CameraSetOnceBB") == [(cam.handle,)]


def test_wb_window(fake, cam):
    cam.wb_window = (0, 0, W, H)
    assert cam.wb_window == (0, 0, W, H)


def test_mirror_directions_are_independent(fake, cam):
    cam.mirror_horizontal = True
    cam.mirror_vertical = False
    assert fake.calls_to("CameraSetMirror")[-2:] == [(cam.handle, 0, 1), (cam.handle, 1, 0)]
    assert cam.mirror_horizontal is True and cam.mirror_vertical is False
    cam.hardware_mirror_vertical = True
    assert fake.calls_to("CameraSetHardwareMirror")[-1] == (cam.handle, 1, 1)
    assert cam.hardware_mirror_vertical is True


@pytest.mark.parametrize("degrees, index", [(0, 0), (90, 1), (180, 2), (270, 3)])
def test_rotation(fake, cam, degrees, index):
    cam.rotation_deg = degrees
    assert fake.calls_to("CameraSetRotate")[-1] == (cam.handle, index)
    assert cam.rotation_deg == degrees


def test_rotation_rejects_other_angles(cam):
    with pytest.raises(ValueError):
        cam.rotation_deg = 45


def test_resolution_presets_and_binning_modes(fake, cam):
    presets = cam.resolution_presets()
    assert [(p.index, p.width, p.height, p.description) for p in presets] == [(0, W, H, "full"), (1, W // 2, H // 2, "bin 2x2")]
    assert presets[1].bin_sum_mode == 1 and presets[1].fov_width == W
    assert cam.binning_modes() == {"sum": [2], "average": [2, 3], "skip": []}
    cam.set_resolution(1)
    assert fake.resolution_set == (1, W // 2, H // 2)
    with pytest.raises(ValueError):
        cam.set_resolution(7)


def test_roi(fake, cam):
    cam.set_roi(0, 0, 2, 2)
    assert fake.calls_to("CameraSetImageResolutionEx")[-1] == (cam.handle, 0xFF, 0, 0, 0, 0, 2, 2, 0, 0)
    with pytest.raises(ValueError):
        cam.set_roi(2, 0, W, H)  # does not fit the sensor


def test_color_temperature_presets(cam):
    assert [(p.index, p.description) for p in cam.color_temperature_presets()] == [(0, "5000K"), (1, "6500K")]


def test_digital_io(fake, cam):
    assert cam.io_counts == (1, 2)
    fake.inputs[0] = 1
    assert cam.get_input(0) is True
    cam.set_output(1, True)
    assert fake.calls_to("CameraSetIOStateEx")[-1] == (cam.handle, 1, 1)
    assert cam.get_output(1) is True
    with pytest.raises(ValueError):
        cam.get_input(1)  # only one input
    with pytest.raises(ValueError):
        cam.set_output(2, False)  # only two outputs


def test_ext_trigger_capability_mask(fake, cam):
    fake.state["ExtTrigCapability"] = [(g.EXT_TRIG_MASK_LEVEL_MODE | g.EXT_TRIG_MASK_BUFFERED_DELAY,)]
    assert cam.ext_trigger_capability & g.EXT_TRIG_MASK_LEVEL_MODE
    assert not cam.ext_trigger_capability & g.EXT_TRIG_MASK_GRR_SHUTTER


def test_frame_resend_count(fake, cam):
    cam.set_frame_resend_count(3)
    assert fake.calls_to("CameraSetFrameResendCount")[-1] == (cam.handle, 3)


@pytest.mark.parametrize("group, value", [("A", 0), ("b", 1), ("C", 2), (3, 3)])
def test_parameter_groups(fake, cam, group, value):
    cam.save_parameter(group)
    assert fake.saved_groups[-1] == value
    cam.load_parameter(group)
    assert cam.parameter_group == value


def test_parameter_group_default_only_for_loading(fake, cam):
    cam.load_parameter("default")
    assert cam.parameter_group == g.PARAMETER_TEAM_DEFAULT
    with pytest.raises(ValueError):
        cam.save_parameter("default")
    with pytest.raises(ValueError):
        cam.save_parameter("E")


def test_parameter_files(fake, cam, tmp_path):
    path = tmp_path / "sb01.config"
    cam.save_parameter_to_file(str(path))
    cam.load_parameter_from_file(str(path))
    assert fake.calls_to("CameraSaveParameterToFile")[-1] == (cam.handle, str(path).encode())
    assert fake.calls_to("CameraReadParameterFromFile")[-1] == (cam.handle, str(path).encode())


def test_library_level_options(fake, cam):
    cam.sdk.set_sys_option("NumBuffers", 8)
    cam.sdk.set_data_directory("/tmp/mvsdk-data")
    assert fake.calls_to("CameraSetSysOption")[-1] == (b"NumBuffers", b"8")
    assert fake.calls_to("CameraSetDataDirectory")[-1] == (b"/tmp/mvsdk-data",)


def test_serial_number_levels(cam):
    assert cam.read_sn(1) == "LEVEL1SN"
    with pytest.raises(ValueError):
        cam.read_sn(0)


def test_user_data_round_trip(cam):
    assert cam.user_data_size == 64
    cam.write_user_data(4, b"cal-2026")
    assert cam.read_user_data(4, 8) == b"cal-2026"
    with pytest.raises(ValueError):
        cam.write_user_data(60, b"too long")


def test_connection_callback_keeps_wrapper_and_translates_message(fake, cam):
    events = []
    cam.set_connection_callback(lambda connected, reason: events.append((connected, reason)))
    wrapper = fake.calls_to("CameraSetConnectionStatusCallback")[-1][1]
    assert cam._connection_callback is wrapper
    gc.collect()
    wrapper(cam.handle, 0, 0, None)
    wrapper(cam.handle, 1, 1, None)
    assert events == [(False, 0), (True, 1)]
    cam.set_connection_callback(None)
    assert cam._connection_callback is None


def test_raw_call_and_query(fake, cam):
    cam.call("CameraSetMultiExposureTime", 0, 120.0, argtypes=[c_int, c_double])
    fn = fake.CameraSetMultiExposureTime
    assert fn.argtypes == [c_int, c_int, c_double] and fn.restype is c_int
    assert cam.query("CameraGetMultiExposureTime", c_double, args=(0,), argtypes=[c_int]) == 120.0
    # Declared functions keep the package's own signature.
    cam.call("CameraSetAeTarget", 100, argtypes=[c_uint])
    assert fake.CameraSetAeTarget.argtypes == [c_int, c_int]
    assert cam.query("CameraGetAeWindow", c_int, c_int, c_int, c_int) == (0, 0, 0, 0)


def test_raw_call_errors(fake, cam):
    fake.fail["CameraSetLedBrightness"] = -4
    with pytest.raises(MvError) as info:
        cam.call("CameraSetLedBrightness", 0, 128, argtypes=[c_int, c_uint])
    assert info.value.status == -4
    with pytest.raises(FunctionUnavailable):
        cam.call("NotAnSdkFunction")


def test_unsupported_feature_raises_mv_error(fake, cam):
    fake.fail["CameraSetAntiFlick"] = -4
    with pytest.raises(MvError) as info:
        cam.anti_flicker = True
    assert info.value.name == "CAMERA_STATUS_NOT_SUPPORTED"


def test_constants_match_header_values():
    assert (g.EXT_TRIG_LEADING_EDGE, g.EXT_TRIG_TRAILING_EDGE, g.EXT_TRIG_HIGH_LEVEL, g.EXT_TRIG_LOW_LEVEL) == (0, 1, 2, 3)
    assert (g.STROBE_SYNC_WITH_TRIG_AUTO, g.STROBE_ALWAYS_LOW) == (0, 3)
    assert (g.CT_MODE_AUTO, g.CT_MODE_USER_DEF, g.LUTMODE_USER_DEF) == (0, 2, 2)
    assert (g.EXT_TRIG_MASK_GRR_SHUTTER, g.EXT_TRIG_MASK_BUFFERED_DELAY) == (1, 8)
    assert _ffi.RESOLUTION_INDEX_CUSTOM == 0xFF


def test_capability_summary(cam):
    summary = cam.capability_summary()
    assert summary["mono_sensor"] is True
    assert summary["ae_target_range"] == [20, 255]
    assert summary["binning"] == {"sum": [2], "average": [2, 3], "skip": []}
    assert summary["inputs"] == 1 and summary["outputs"] == 2
    assert summary["user_data_bytes"] == 64
    assert summary["color_temperature_presets"] == ["5000K", "6500K"]
    assert summary["packet_sizes"] == [1440, 4000, 8000]


def test_info_includes_capability(cam, capsys):
    from gcam_mvsdk_py import cli

    data = cli.collect_info(cam)
    assert data["capability"]["ae_target_range"] == [20, 255]
    cli.print_info(data)
    out = capsys.readouterr().out
    assert "Capability (what this model supports)" in out and "ae_target_range" in out
