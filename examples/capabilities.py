"""Snippets for docs/CAPABILITIES.md: what the HuaTeng SDK can change, one function per group.

Every code block in docs/CAPABILITIES.md is copied from this file by
``python scripts/update_capabilities_doc.py``, and tests/test_capabilities_examples.py
runs each function once against a fake SDK. The functions are written to be read;
call them yourself with an open camera, for example::

    import gcam_mvsdk_py
    from capabilities import exposure_auto      # run from the examples/ directory

    sdk = gcam_mvsdk_py.load()
    with sdk.open("sb01") as cam:
        print(exposure_auto(cam))

Functions whose first parameter is ``sdk`` work on the library and must run before
a camera is opened. Settings marked "model dependent" raise ``gcam_mvsdk_py.MvError``
(usually status -4, not supported) on cameras that lack the feature.
"""

# snippet: imports
from ctypes import POINTER, byref, c_double, c_float, c_int, c_uint, c_ushort

import numpy as np

import gcam_mvsdk_py
from gcam_mvsdk_py import MvError
from gcam_mvsdk_py._ffi import CAMERA_FRAME_EVENT_CALLBACK, tSdkImageResolution
# end snippet


# ---------------------------------------------------------------------------
# 1. Identity and network
# ---------------------------------------------------------------------------


def identity_name(cam):
    """FriendlyName: the user-set name that publishers select cameras by."""
    old = cam.user_name                      # CameraGetFriendlyName
    cam.user_name = "sb01"                   # CameraSetFriendlyName; 31 bytes max, stored in the camera
    return {"old": old, "new": cam.user_name}


def identity_network(sdk):
    """GigE IP/mask/gateway: read and set a camera's address, even from the wrong subnet."""
    dev = sdk.enumerate()[0]
    before = dev.gige_ip()                   # CameraGigeGetIp: camera and host NIC addresses
    mac = dev.gige_mac().camera_mac          # CameraGigeGetMac
    sdk.gige_set_ip(dev, "192.168.3.21", "255.255.255.0", "0.0.0.0", persistent=True)  # CameraGigeSetIp
    return {"camera_ip": before.camera_ip, "mac": mac}


def identity_serial_and_user_data(cam):
    """WriteSN is not wrapped (it rewrites serial numbers); levels 1 and 2 can be read. User data is free NVM."""
    level1 = cam.read_sn(1)                  # CameraReadSN; level 0 is the factory serial (cam.device.serial)
    if cam.user_data_size >= 16:             # iUserDataMaxLen; 0 means no user data area
        cam.write_user_data(0, b"lens=8mm cal=v3")   # CameraSaveUserData
        stored = cam.read_user_data(0, 15)            # CameraLoadUserData
    else:
        stored = b""
    return {"sn_level1": level1, "user_data": stored}


# ---------------------------------------------------------------------------
# 2. Exposure and gain
# ---------------------------------------------------------------------------


def exposure_manual(cam):
    """Fixed exposure and gain, e.g. for marker detection under flicker-free LED light."""
    lo, hi, step = cam.exposure_range_us()   # CameraGetExposureTimeRange, microseconds
    cam.exposure_us = min(max(2000.0, lo), hi)        # CameraSetExposureTime; also turns AeState off
    actual = cam.exposure_us                 # rounded to whole sensor lines; read it back
    gmin, gmax, gstep = cam.analog_gain_x_range()     # CameraGetAnalogGainXRange
    cam.analog_gain_x = max(gmin, 1.0)       # CameraSetAnalogGainX: gain as a factor
    raw_gain = cam.analog_gain               # CameraGetAnalogGain: units of sExposeDesc.fAnalogGainStep
    return {"exposure_us": actual, "gain_x": cam.analog_gain_x, "gain_raw": raw_gain}


def exposure_auto(cam):
    """Auto exposure with limits, e.g. a robot moving between bright and dark areas."""
    ed = cam.capability().sExposeDesc
    cam.auto_exposure = True                 # CameraSetAeState
    cam.ae_target = min(max(120, ed.uiTargetMin), ed.uiTargetMax)  # CameraSetAeTarget, range in sExposeDesc
    cam.ae_threshold = 5                     # CameraSetAeThreshold: dead band around the target
    cam.ae_exposure_range_us = (100.0, 8000.0)        # CameraSetAeExposureRange: keep motion blur bounded
    cam.ae_analog_gain_range = (ed.uiAnalogGainMin, ed.uiAnalogGainMax)  # CameraSetAeAnalogGainRange
    cam.ae_window = (0, 0, 0, 0)             # CameraSetAeWindow: zeros = centred half-size window
    return {"target": cam.ae_target, "window": cam.ae_window}


def exposure_flicker(cam):
    """AntiFlick and LightFrequency: auto exposure under mains-powered lighting."""
    if cam.capability().sIspCapacity.bAntiFlick:
        cam.anti_flicker = True              # CameraSetAntiFlick (auto exposure only)
        cam.light_frequency_hz = 50          # CameraSetLightFrequency: 50 or 60
    return {"anti_flicker": cam.anti_flicker, "hz": cam.light_frequency_hz}


def gain_rgb(cam):
    """Gain (RGB digital): per-channel gain applied in the ISP, 100 = 1.0x."""
    rg = cam.capability().sRgbGainRange
    cam.digital_gain = (min(120, rg.iRGainMax), 100, 100)   # CameraSetGain
    return {"rgb": cam.digital_gain}         # CameraGetGain


def exposure_multi_raw(cam):
    """MultiExposure* (line-scan cameras only): raw calls."""
    try:
        max_count = cam.query("CameraGetMultiExposureMaxCount", c_int)
        cam.call("CameraSetMultiExposureCount", min(2, max_count), argtypes=[c_int])
        cam.call("CameraSetMultiExposureTime", 0, 50.0, argtypes=[c_int, c_double])
        cam.call("CameraSetMultiExposureTime", 1, 400.0, argtypes=[c_int, c_double])
        return {"max_count": max_count}
    except MvError as exc:                   # area-scan models: not supported
        return {"error": exc.status}


# ---------------------------------------------------------------------------
# 3. Frame rate, trigger and timing
# ---------------------------------------------------------------------------


def frame_rate(cam):
    """FrameSpeed and FrameRate: full sensor speed, or a capped rate to save bandwidth."""
    speeds = cam.frame_speeds()              # pFrameSpeedDesc, e.g. low / normal / high
    if speeds:
        cam.frame_speed = speeds[-1].index   # CameraSetFrameSpeed: fastest readout tier
    try:
        cam.frame_rate_hz = 0                # CameraSetFrameRate: 0 = uncapped (only some GigE models)
    except MvError:
        pass
    return {"speed": cam.frame_speed, "rate_hz": cam.frame_rate_hz}


def trigger_software(cam):
    """SoftTrigger, TriggerCount, TriggerPeriodTime: capture exactly when the program asks."""
    cam.trigger_mode = gcam_mvsdk_py.TRIGGER_SOFTWARE        # CameraSetTriggerMode
    cam.trigger_count = 1                    # CameraSetTriggerCount: frames per trigger
    try:
        cam.trigger_period_us = 0            # CameraSetTriggerPeriodTime: gap between frames (some models)
    except MvError:
        pass
    cam.play()
    cam.soft_trigger()                       # CameraSoftTrigger
    with cam.grab(timeout_ms=1000) as frame:
        image = frame.to_numpy()
    return {"shape": image.shape}


def trigger_hardware(cam):
    """ExtTrig*: hardware trigger from an encoder or PLC for synchronized multi-camera capture."""
    cam.trigger_mode = gcam_mvsdk_py.TRIGGER_HARDWARE        # CameraSetTriggerMode
    mask = cam.ext_trigger_capability        # CameraGetExtTrigCapability: EXT_TRIG_MASK_* bits
    cam.ext_trigger_signal = gcam_mvsdk_py.EXT_TRIG_LEADING_EDGE   # CameraSetExtTrigSignalType
    cam.ext_trigger_jitter_us = 20           # CameraSetExtTrigJitterTime: debounce
    cam.ext_trigger_delay_us = 0             # CameraSetExtTrigDelayTime
    try:
        cam.trigger_delay_us = 0             # CameraSetTriggerDelayTime (only some models)
    except MvError:
        pass
    cam.ext_trigger_interval_us = 0          # CameraSetExtTrigIntervalTime
    if mask & gcam_mvsdk_py.EXT_TRIG_MASK_BUFFERED_DELAY:
        cam.ext_trigger_buffered_delay_us = 500   # CameraSetExtTrigBufferedDelayTime: queues triggers
    if mask & gcam_mvsdk_py.EXT_TRIG_MASK_GRR_SHUTTER:
        cam.ext_trigger_shutter = gcam_mvsdk_py.EXT_TRIG_EXP_STANDARD  # CameraSetExtTrigShutterType
    return {"mask": mask, "signal": cam.ext_trigger_signal}


def streaming_control(cam):
    """Play/Pause/Stop and ClearBuffer: start, suspend, and flush the stream."""
    cam.play()                               # CameraPlay
    cam.pause()                              # CameraPause: stops output, frees bandwidth, settings apply at once
    cam.clear_buffer()                       # CameraClearBuffer: drop frames cached in the camera
    cam.play()
    cam.stop()                               # CameraStop: only before closing; no configuration afterwards
    return {"stopped": True}


# ---------------------------------------------------------------------------
# 4. Image geometry
# ---------------------------------------------------------------------------


def geometry_resolution(cam):
    """ImageResolution/ImageResolutionEx: preset sizes (binning, skipping) and ROI for more frames per second."""
    presets = cam.resolution_presets()       # pImageSizeDesc, with bin/skip modes and field of view
    binning = cam.binning_modes()            # from sResolutionRange masks, e.g. {"sum": [2], ...}
    binned = [p for p in presets if p.bin_sum_mode or p.bin_average_mode]
    if binned:
        cam.set_resolution(binned[0].index)  # CameraSetImageResolution with a table entry
    width, height = cam.max_size
    cam.set_roi(0, 0, width // 2, height // 2)    # CameraSetImageResolutionEx, index 0xFF = custom
    roi = cam.resolution                     # CameraGetImageResolution; the SDK may align values
    cam.set_roi(0, 0, width, height)         # back to the full sensor
    return {"presets": len(presets), "binning": binning, "roi": roi}


def geometry_snap_and_transfer_roi_raw(cam):
    """ResolutionForSnap and TransferRoi: raw calls (TransferRoi only on some models)."""
    snap = tSdkImageResolution()             # width = height = 0 means "same as preview"
    cam.call("CameraSetResolutionForSnap", byref(snap), argtypes=[POINTER(tSdkImageResolution)])
    try:
        width, height = cam.max_size
        cam.call("CameraSetTransferRoi", 0, 0, 0, width - 1, height // 4,
                 argtypes=[c_int, c_uint, c_uint, c_uint, c_uint])   # region 0: top quarter
        cam.call("CameraEnableTransferRoi", 0b0001, argtypes=[c_uint])  # bits 0..3 enable regions
    except MvError as exc:
        return {"transfer_roi_error": exc.status}
    return {"transfer_roi": True}


def geometry_orientation(cam):
    """Mirror, HardwareMirror, Rotate, Inverse: match the mounting orientation of the camera."""
    cam.mirror_horizontal = True             # CameraSetMirror(dir=0), done in the ISP
    cam.mirror_vertical = False              # CameraSetMirror(dir=1)
    try:
        cam.hardware_mirror_vertical = True  # CameraSetHardwareMirror: in the camera (some GigE/USB3 models)
    except MvError:
        pass
    cam.rotation_deg = 180                   # CameraSetRotate: 0/90/180/270 counter-clockwise
    cam.call("CameraSetInverse", 0, argtypes=[c_int])        # Inverse: negative image when 1 (raw)
    return {"rotation": cam.rotation_deg, "mirror_h": cam.mirror_horizontal}


def geometry_flip(cam):
    """FlipFrameBuffer: flip a numpy copy instead; to_numpy() already returns top-down rows on Windows."""
    cam.play()
    with cam.grab(timeout_ms=1000) as frame:
        image = frame.to_numpy()
    upside_down = np.flipud(image)           # CameraFlipFrameBuffer flag 1
    left_right = np.fliplr(image)            # flag 2
    rotated_180 = image[::-1, ::-1]          # flag 3
    return {"shapes": [a.shape for a in (upside_down, left_right, rotated_180)]}


def geometry_line_scan_raw(cam):
    """SpliceLines (line-scan cameras): stitch lines from several frames into one; raw."""
    try:
        cam.call("CameraSetSpliceLines", 0, argtypes=[c_int])   # 0 = no splicing (default)
        return {"splice_lines": cam.query("CameraGetSpliceLines", c_int)}
    except MvError as exc:
        return {"error": exc.status}


# ---------------------------------------------------------------------------
# 5. Image processing
# ---------------------------------------------------------------------------


def isp_output_and_processor(cam):
    """IspOutFormat, IspProcessor, Monochrome: what to_numpy() returns and where the ISP runs."""
    cam.output_format = gcam_mvsdk_py.Mono8 if cam.is_mono else gcam_mvsdk_py.BGR8  # CameraSetIspOutFormat
    if cam.capability().sIspCapacity.bDeviceIsp:
        cam.isp_processor = gcam_mvsdk_py.ISP_PROCESSOR_DEVICE   # CameraSetIspProcessor: less host CPU
    if not cam.is_mono:
        cam.monochrome = True                # CameraSetMonochrome: grey output from a colour sensor
    return {"format": cam.output_format, "isp": cam.isp_processor}


def isp_tone(cam):
    """Gamma, Contrast, Saturation, Sharpness, BlackLevel, WhiteLevel, LogarithmicCurveValue."""
    cap = cam.capability()
    cam.lut_mode = gcam_mvsdk_py.LUTMODE_PARAM_GEN   # CameraSetLutMode: gamma/contrast only act in this mode
    cam.gamma = min(max(100, cap.sGammaRange.iMin), cap.sGammaRange.iMax)            # CameraSetGamma
    cam.contrast = min(max(100, cap.sContrastRange.iMin), cap.sContrastRange.iMax)   # CameraSetContrast
    cam.saturation = 100                     # CameraSetSaturation: 100 = unchanged, colour only
    cam.sharpness = 0                        # CameraSetSharpness: 0 = off
    cam.black_level = 0                      # CameraSetBlackLevel, 0..255
    cam.white_level = 255                    # CameraSetWhiteLevel, 0..255
    try:
        cam.call("CameraSetLogarithmicCurveValue", 128, argtypes=[c_int])   # 0..255, model dependent
    except MvError:
        pass
    return {"gamma": cam.gamma, "contrast": cam.contrast}


def isp_noise(cam):
    """NoiseFilter, NoiseReductionValue, Denoise3DParams, CorrectDeadPixel, BayerDecAlgorithm."""
    cam.noise_filter = True                  # CameraSetNoiseFilter
    cam.dead_pixel_correction = True         # CameraSetCorrectDeadPixel
    try:
        cam.call("CameraSetNoiseReductionValue", 3, argtypes=[c_int])        # 0..7
        weights = (c_float * 3)(0.3, 0.3, 0.4)                               # newest frame weighted most
        cam.call("CameraSetDenoise3DParams", 1, 3, weights, argtypes=[c_int, c_int, POINTER(c_float)])
        if not cam.is_mono:
            cam.call("CameraSetBayerDecAlgorithm", gcam_mvsdk_py.ISP_PROCESSOR_PC, 0, argtypes=[c_int, c_int])
    except MvError as exc:
        return {"error": exc.status}
    return {"noise_filter": cam.noise_filter}


def isp_white_balance(cam):
    """WbMode, OnceWB, WbWindow, ClrTempMode, PresetClrTemp, UserClrTemp*, OnceBB (colour cameras)."""
    if cam.is_mono:
        return {"skipped": "mono sensor"}
    cam.auto_white_balance = False           # CameraSetWbMode: manual
    cam.wb_window = (0, 0, 0, 0)             # CameraSetWbWindow: point it at a grey card
    cam.white_balance_once()                 # CameraSetOnceWB: applied with the next frame
    presets = cam.color_temperature_presets()            # pClrTempDesc
    if presets:
        cam.color_temperature_mode = gcam_mvsdk_py.CT_MODE_PRESET   # CameraSetClrTempMode
        cam.preset_color_temperature = presets[0].index             # CameraSetPresetClrTemp
    cam.call("CameraSetUserClrTempGain", 100, 100, 100, argtypes=[c_int, c_int, c_int])  # 0..400 = 0..4x
    matrix = (c_float * 9)(1, 0, 0, 0, 1, 0, 0, 0, 1)    # 3x3 colour matrix, identity
    cam.call("CameraSetUserClrTempMatrix", matrix, argtypes=[POINTER(c_float)])
    cam.black_balance_once()                 # CameraSetOnceBB
    return {"presets": [p.description for p in presets]}


def isp_lut_and_undistort_raw(cam):
    """CustomLut and Undistort*: a user lookup table and lens undistortion, raw calls."""
    lut = np.clip(np.arange(4096) * 1.2, 0, 4095).astype(np.uint16)   # 4096 entries, 12-bit values
    cam.lut_mode = gcam_mvsdk_py.LUTMODE_USER_DEF                      # CameraSetLutMode
    lut_buf = (c_ushort * 4096)(*lut.tolist())
    cam.call("CameraSetCustomLut", 0, lut_buf, argtypes=[c_int, POINTER(c_ushort)])   # channel 0 = all
    width, height = cam.resolution
    matrix = (c_double * 4)(1000.0, 1000.0, width / 2, height / 2)    # fx, fy, cx, cy
    dist = (c_double * 5)(-0.1, 0.01, 0.0, 0.0, 0.0)                    # k1, k2, p1, p2, k3
    try:
        cam.call("CameraSetUndistortParams", width, height, matrix, dist,
                 argtypes=[c_int, c_int, POINTER(c_double), POINTER(c_double)])
        cam.call("CameraSetUndistortEnable", 1, argtypes=[c_int])
    except MvError as exc:
        return {"undistort_error": exc.status}
    return {"lut_mode": cam.lut_mode}


# ---------------------------------------------------------------------------
# 6. Digital I/O, strobe and lighting
# ---------------------------------------------------------------------------


def io_digital(cam):
    """IOState/IOStateEx and the raw IO mode, format and pulse settings."""
    inputs, outputs = cam.io_counts          # iInputIoCounts, iOutputIoCounts
    level = cam.get_input(0) if inputs else None          # CameraGetIOStateEx: True = high
    if outputs:
        cam.set_output(0, True)              # CameraSetIOStateEx: drive output 0 high
        cam.call("CameraSetOutPutIOMode", 0, 3, argtypes=[c_int, c_int])        # 3 = general output
        cam.call("CameraSetOutPutPolarity", 0, 0, argtypes=[c_int, c_uint])     # 0 forward, 1 reverse
        cam.call("CameraSetOutPutPulseWidth", 0, 1000, argtypes=[c_int, c_uint])  # microseconds
        cam.call("CameraSetOutPutDelayTime", 0, 0, argtypes=[c_int, c_uint])    # microseconds
        cam.call("CameraSetOutPutPWM", 0, 1000, 50, argtypes=[c_int, c_uint, c_uint])  # cycle us, duty %
    if inputs:
        cam.call("CameraSetInPutIOMode", 0, 0, argtypes=[c_int, c_int])         # 0 = trigger input
    return {"input0": level, "output0": cam.get_output(0) if outputs else None}


def io_strobe(cam):
    """Strobe*: fire a flash or light controller in step with the exposure."""
    cam.strobe_mode = gcam_mvsdk_py.STROBE_SYNC_WITH_TRIG_MANUAL   # CameraSetStrobeMode
    cam.strobe_polarity = 1                  # CameraSetStrobePolarity: 1 = active high (default)
    cam.strobe_delay_us = 0                  # CameraSetStrobeDelayTime
    cam.strobe_pulse_width_us = 2000         # CameraSetStrobePulseWidth
    return {"mode": cam.strobe_mode}


def io_led_lighting_encoder_raw(cam):
    """Led*, LightingController*, RotaryEnc*: model-specific hardware, raw calls."""
    results = {}
    try:
        cam.call("CameraSetLedBrightness", 0, 128, argtypes=[c_int, c_uint])     # 0..255
        cam.call("CameraSetLedOnOff", 0, 1, argtypes=[c_int, c_int])
    except MvError as exc:                   # models without LEDs
        results["led_error"] = exc.status
    try:
        cam.call("CameraSetLightingControllerMode", 0, 0, argtypes=[c_int, c_int])  # 0 = follow strobe
    except MvError as exc:                   # smart camera series only
        results["lighting_error"] = exc.status
    try:
        cam.call("CameraSetRotaryEncDir", 1, argtypes=[c_int])        # 1 = clockwise (A leads B)
        cam.call("CameraSetRotaryEncFreq", 1, 4, argtypes=[c_int, c_int])   # multiply 1, divide 4
    except MvError as exc:
        results["encoder_error"] = exc.status
    return results


# ---------------------------------------------------------------------------
# 7. GigE transport
# ---------------------------------------------------------------------------


def gige_transport(cam):
    """TransPackLen and FrameResendCount: packet size for the NIC MTU, resends in trigger mode."""
    sizes = [p.size for p in cam.packet_sizes()]     # pPackLenDesc
    if sizes:
        cam.gige_packet_size = 1500          # CameraSetTransPackLen: largest advertised size <= 1500
    cam.set_frame_resend_count(2)            # CameraSetFrameResendCount (no getter)
    cam.sdk.gige_set_option("NumBuffers", 8)  # CameraGigeSetOption
    return {"sizes": sizes, "packet": cam.gige_packet_size if sizes else None}


# ---------------------------------------------------------------------------
# 8. Parameter persistence
# ---------------------------------------------------------------------------


def persistence_groups(cam, config_path="sb01.config"):
    """SaveParameter/LoadParameter (groups A to D), files, ParameterMode, ParameterMask."""
    cam.save_parameter("B")                  # CameraSaveParameter: current settings into group B
    cam.load_parameter("B")                  # CameraLoadParameter
    group = cam.parameter_group              # CameraGetCurrentParameterGroup
    cam.save_parameter_to_file(config_path)  # CameraSaveParameterToFile
    cam.load_parameter_from_file(config_path)    # CameraReadParameterFromFile
    if cam.capability().bParamInDevice:
        cam.parameter_mode = gcam_mvsdk_py.PARAM_MODE_IN_DEVICE   # CameraSetParameterMode
    cam.call("CameraSetParameterMask", 0xFFFFFFFF, argtypes=[c_uint])   # all bits: every settings page (raw)
    return {"group": group, "mode": cam.parameter_mode}


def persistence_library(sdk, data_dir="/tmp/mvsdk-data"):
    """SysOption and DataDirectory: SDK-wide settings, before any camera is opened."""
    sdk.set_data_directory(data_dir)         # CameraSetDataDirectory: where .config files live
    sdk.set_sys_option("NumBuffers", 8)      # CameraSetSysOption
    return {"data_dir": data_dir}


# ---------------------------------------------------------------------------
# 9. Callbacks
# ---------------------------------------------------------------------------


def callbacks(cam):
    """CallbackFunction, ConnectionStatusCallback (wrapped) and FrameEventCallback (raw)."""
    shapes, links = [], []
    cam.set_callback(lambda frame: shapes.append(frame.to_numpy().shape))   # CameraSetCallbackFunction
    cam.set_connection_callback(lambda connected, reason: links.append((connected, reason)))

    def on_event(handle, event, context):    # event.contents.uType: 1 = frame start, 2 = frame end
        links.append(("event", event.contents.uType))

    # Raw callback: store the ctypes wrapper on the camera so it lives as long as the camera.
    cam.frame_event_callback = CAMERA_FRAME_EVENT_CALLBACK(on_event)
    cam.call("CameraSetFrameEventCallback", cam.frame_event_callback, None)
    cam.set_callback(None)                   # remove the frame callback again
    return {"callbacks": "installed"}


# ---------------------------------------------------------------------------
# 10. Vendor GUI and recording
# ---------------------------------------------------------------------------


def vendor_media_type_raw(cam):
    """MediaType: the sensor's raw output format (not the ISP output); raw call."""
    types = cam.media_types()                # pMediaTypeDesc: (index, media type, description)
    current = cam.query("CameraGetMediaType", c_int)
    if types:
        cam.call("CameraSetMediaType", types[0][0], argtypes=[c_int])
    return {"current": current, "available": [t[2] for t in types]}
