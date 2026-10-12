# What the SDK can change

This page lists the camera settings the HuaTeng MVSDK (version 2.1.0.49) exposes, what each one is
for, and how to use it from Python with `gcam-mvsdk-py`. Use it to decide whether the cameras can do
what your application needs before you write code.

- **wrapped**: `gcam-mvsdk-py` has a property or method for it, for example `cam.ae_target = 120`.
- **raw**: no wrapper yet. Call the vendor function through `cam.call()` or `cam.query()`, as the
  examples show (see [Calling functions that are not wrapped](#calling-functions-that-are-not-wrapped)).

**Does my camera support it, and in what range?** Each camera describes itself in its capability
structure. Print it with `gcam-mvsdk-py info <name or serial>` (the "Capability" block, or the
`capability` key with `--json`), or read it in Python with `cam.capability_summary()` and
`cam.capability()`. Every section below names the fields that matter. A function the model does not
support raises `gcam_mvsdk_py.MvError`, usually status -4 ("not supported"). Ranges and defaults
quoted here come from the comments in the SDK headers (`CameraApi.h`, `CameraDefine.h`); where the
headers give none, the range is **model dependent**: read it from the capability structure or set
the value and read it back.

Every code block on this page is copied from [`examples/capabilities.py`](../examples/capabilities.py)
by `scripts/update_capabilities_doc.py`, and the unit tests run each function once against a
simulated SDK. They have not been run against every camera model. To try them on your camera, run
`python examples/capabilities.py <name or serial> [function or section number]` from the repository
root: it is read-only unless `--write` is given (sections 1 and 8 are never written), and `--list`
shows which function belongs to which section. The examples use these imports:

<!-- snippet: imports -->
```python
from ctypes import POINTER, byref, c_double, c_float, c_int, c_uint, c_ushort

import numpy as np

import gcam_mvsdk_py
from gcam_mvsdk_py import MvError
from gcam_mvsdk_py._ffi import CAMERA_FRAME_EVENT_CALLBACK, tSdkImageResolution
```

## Summary

<!-- summary:start -->
| Section | Items | Wrapped | Raw |
|---|---:|---:|---:|
| [1. Identity and network](#1-identity-and-network) | 4 | 3 | 1 |
| [2. Exposure and gain](#2-exposure-and-gain) | 13 | 12 | 1 |
| [3. Frame rate, trigger and timing](#3-frame-rate-trigger-and-timing) | 16 | 16 | 0 |
| [4. Image geometry](#4-image-geometry) | 9 | 4 | 5 |
| [5. Image processing](#5-image-processing) | 26 | 18 | 8 |
| [6. Digital I/O, strobe and lighting](#6-digital-io-strobe-and-lighting) | 8 | 2 | 6 |
| [7. GigE transport](#7-gige-transport) | 2 | 2 | 0 |
| [8. Parameter persistence](#8-parameter-persistence) | 6 | 5 | 1 |
| [9. Callbacks](#9-callbacks) | 3 | 2 | 1 |
| [10. Vendor GUI and recording](#10-vendor-gui-and-recording) | 7 | 0 | 7 |
| **Total** | **94** | **64** | **30** |
<!-- summary:end -->

## Calling functions that are not wrapped

`cam.call(name, *args, argtypes=[...])` calls `name(handle, *args)` and raises `MvError` when the
status is not 0. `cam.query(name, *out_types, args=(...), argtypes=[...])` calls
`name(handle, *args, &out1, &out2, ...)` and returns the outputs. `argtypes` lists the C types of the
parameters after the camera handle (for `query`, only the inputs); take them from the declaration in
`include/CameraApi.h`. Functions this package already declares keep their own signature, so
`argtypes` can be left out for them. Library-level functions without a camera handle use
`sdk.call(...)`. `sdk.raw` is the underlying `ctypes` library for anything else. The structure and
callback types used by raw calls (`tSdkImageResolution`, `CAMERA_FRAME_EVENT_CALLBACK`, ...) live in
`gcam_mvsdk_py._ffi`, an internal module whose names follow the C headers and may change between
releases.

```python
from ctypes import c_double, c_int

max_count = cam.query("CameraGetMultiExposureMaxCount", c_int)                 # one output
cam.call("CameraSetMultiExposureTime", 0, 50.0, argtypes=[c_int, c_double])     # inputs only
```

## 1. Identity and network

**Support and ranges.** `iUserDataMaxLen` (`cam.user_data_size`) is the size of the user data area;
0 means the model has none, and offset plus length must stay inside it. Names are at most 31 bytes
and must not contain `\ / : * ? " < > |` (the SDK rejects them with status -53). The name reported by
enumeration changes only after the camera restarts. The IP functions apply to GigE cameras only and
work on cameras that are not opened, also from another subnet. Serial-number levels 1 and 2 are 32
bytes each and are reserved for the integrator; level 0 is the factory serial.

| Setting | What it does | Typical use | Vendor functions | Python | Example |
|---|---|---|---|---|---|
| FriendlyName | Reads or writes the user-set name stored in the camera. | Give each camera a stable name (`sb01`) that launch scripts select it by. | `CameraGetFriendlyName`, `CameraSetFriendlyName` | wrapped: `cam.user_name` | `identity_name` |
| GigE IP, mask, gateway | Reads the camera and host NIC addresses; sets a persistent or automatic camera address. | Move a new camera from 169.254.x.x into the camera network's subnet. | `CameraGigeGetIp`, `CameraGigeGetMac`, `CameraGigeSetIp` | wrapped: `dev.gige_ip()`, `dev.gige_mac()`, `sdk.gige_set_ip()` | `identity_network` |
| WriteSN | Overwrites serial-number level 1 or 2. Dangerous: it changes identification data in the camera; read the old value first. | Tagging cameras with an asset number in level 1. | `CameraWriteSN`, `CameraReadSN` | raw: writing is deliberately not wrapped; reading is `cam.read_sn(level)` | `identity_serial_and_user_data` |
| SaveUserData / LoadUserData | Stores and reads arbitrary bytes in the camera's non-volatile user area. | Keep the lens type or a calibration version with the camera itself. | `CameraSaveUserData`, `CameraLoadUserData` | wrapped: `cam.write_user_data()`, `cam.read_user_data()`, `cam.user_data_size` | `identity_serial_and_user_data` |

<!-- snippet: identity_name -->
```python
def identity_name(cam):
    """FriendlyName: the user-set name that publishers select cameras by."""
    old = cam.user_name                      # CameraGetFriendlyName
    cam.user_name = "sb01"                   # CameraSetFriendlyName; 31 bytes max, stored in the camera
    return {"old": old, "new": cam.user_name}
```

<!-- snippet: identity_network -->
```python
def identity_network(sdk):
    """GigE IP/mask/gateway: read and set a camera's address, even from the wrong subnet."""
    dev = sdk.enumerate()[0]
    before = dev.gige_ip()                   # CameraGigeGetIp: camera and host NIC addresses
    mac = dev.gige_mac().camera_mac          # CameraGigeGetMac
    sdk.gige_set_ip(dev, "192.168.3.21", "255.255.255.0", "0.0.0.0", persistent=True)  # CameraGigeSetIp
    return {"camera_ip": before.camera_ip, "mac": mac}
```

<!-- snippet: identity_serial_and_user_data -->
```python
def identity_serial_and_user_data(cam):
    """WriteSN is not wrapped (it rewrites serial numbers); levels 1 and 2 can be read. User data is free NVM."""
    level1 = cam.read_sn(1)                  # CameraReadSN; level 0 is the factory serial (cam.device.serial)
    if cam.user_data_size >= 16:             # iUserDataMaxLen; 0 means no user data area
        cam.write_user_data(0, b"lens=8mm cal=v3")   # CameraSaveUserData
        stored = cam.read_user_data(0, 15)            # CameraLoadUserData
    else:
        stored = b""
    return {"sn_level1": level1, "user_data": stored}
```

## 2. Exposure and gain

**Support and ranges.** `sIspCapacity.bAutoExposure`, `bManualExposure` and `bAntiFlick` say whether
auto exposure, manual exposure and anti-flicker exist. `sExposeDesc.uiTargetMin`/`uiTargetMax` is
the auto-exposure target range. `sExposeDesc.uiAnalogGainMin`/`uiAnalogGainMax` is the analog gain
range in steps of `fAnalogGainStep`; the factor is value times step (the header's example: 16 x 0.125
= 2x). `sExposeDesc.uiExposeTimeMin`/`uiExposeTimeMax` is the manual exposure range in sensor lines;
`cam.exposure_range_us()` gives it in microseconds and `cam.exposure_line_time_us` the length of one
line. `sRgbGainRange` is the digital gain range per channel (value / 100 = factor). The sensor rounds
exposure to whole lines, so read `cam.exposure_us` back. Setting `cam.exposure_us` also switches
auto exposure off. The headers give no ranges for AeThreshold, AeExposureRange and
AeAnalogGainRange: model dependent. MultiExposure is for line-scan cameras only.

| Setting | What it does | Typical use | Vendor functions | Python | Example |
|---|---|---|---|---|---|
| ExposureTime | Sets the exposure in microseconds. | Fixed exposure for marker detection under flicker-free LED light. | `CameraSetExposureTime`, `CameraGetExposureTime`, `CameraGetExposureTimeRange`, `CameraGetExposureLineTime` | wrapped: `cam.exposure_us`, `cam.exposure_range_us()`, `cam.exposure_line_time_us` | `exposure_manual` |
| AeState | Switches auto exposure on or off. | Follow changing daylight on an outdoor robot. | `CameraSetAeState`, `CameraGetAeState` | wrapped: `cam.auto_exposure` | `exposure_auto` |
| AeTarget | Brightness that auto exposure aims for. | A darker target so reflective parts do not clip. | `CameraSetAeTarget`, `CameraGetAeTarget` | wrapped: `cam.ae_target` | `exposure_auto` |
| AeThreshold | Auto exposure stops adjusting while the brightness is within this distance of the target. | Stop exposure hunting on a busy scene. | `CameraSetAeThreshold`, `CameraGetAeThreshold` | wrapped: `cam.ae_threshold` | `exposure_auto` |
| AeExposureRange | Shortest and longest exposure auto exposure may choose, in microseconds. | Bound motion blur on a moving platform. | `CameraSetAeExposureRange`, `CameraGetAeExposureRange` | wrapped: `cam.ae_exposure_range_us` | `exposure_auto` |
| AeAnalogGainRange | Lowest and highest analog gain auto exposure may choose. | Limit gain to keep noise down for feature tracking. | `CameraSetAeAnalogGainRange`, `CameraGetAeAnalogGainRange` | wrapped: `cam.ae_analog_gain_range` | `exposure_auto` |
| AeWindow | Region whose brightness auto exposure measures; all zeros is the centred half-size window. | Meter on the conveyor belt, not on the bright window behind it. | `CameraSetAeWindow`, `CameraGetAeWindow` | wrapped: `cam.ae_window` | `exposure_auto` |
| AnalogGain | Sensor gain in steps of `fAnalogGainStep`. | Brighter images in low light when the exposure cannot grow. | `CameraSetAnalogGain`, `CameraGetAnalogGain` | wrapped: `cam.analog_gain` | `exposure_manual` |
| AnalogGainX | The same gain as a multiplication factor. | Ask for "2x gain" without knowing the step size. | `CameraSetAnalogGainX`, `CameraGetAnalogGainX`, `CameraGetAnalogGainXRange` | wrapped: `cam.analog_gain_x`, `cam.analog_gain_x_range()` | `exposure_manual` |
| Gain (RGB digital) | Per-channel digital gain in the image processing; 100 = 1.0x. | Manual colour correction for a fixed light source. | `CameraSetGain`, `CameraGetGain` | wrapped: `cam.digital_gain` | `gain_rgb` |
| MultiExposure* | Several exposure times (and gammas) per line on line-scan cameras. | High dynamic range line scanning of shiny and dark parts together. | `CameraSetMultiExposureCount`, `CameraSetMultiExposureTime`, `CameraSetMultiExposureGamma`, their getters, `CameraGetMultiExposureMaxCount` | raw | `exposure_multi_raw` |
| AntiFlick | Lets auto exposure avoid flicker from mains-powered lights; no effect in manual exposure. | Indoor auto exposure under fluorescent tubes. | `CameraSetAntiFlick`, `CameraGetAntiFlick` | wrapped: `cam.anti_flicker` | `exposure_flicker` |
| LightFrequency | Mains frequency anti-flicker works against: 50 or 60 Hz. | Match the local mains frequency. | `CameraSetLightFrequency`, `CameraGetLightFrequency` | wrapped: `cam.light_frequency_hz` | `exposure_flicker` |

<!-- snippet: exposure_manual -->
```python
def exposure_manual(cam):
    """Fixed exposure and gain, e.g. for marker detection under flicker-free LED light."""
    lo, hi, step = cam.exposure_range_us()   # CameraGetExposureTimeRange, microseconds
    cam.exposure_us = min(max(2000.0, lo), hi)        # CameraSetExposureTime; also turns AeState off
    actual = cam.exposure_us                 # rounded to whole sensor lines; read it back
    gmin, gmax, gstep = cam.analog_gain_x_range()     # CameraGetAnalogGainXRange
    cam.analog_gain_x = max(gmin, 1.0)       # CameraSetAnalogGainX: gain as a factor
    raw_gain = cam.analog_gain               # CameraGetAnalogGain: units of sExposeDesc.fAnalogGainStep
    return {"exposure_us": actual, "gain_x": cam.analog_gain_x, "gain_raw": raw_gain}
```

<!-- snippet: exposure_auto -->
```python
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
```

<!-- snippet: exposure_flicker -->
```python
def exposure_flicker(cam):
    """AntiFlick and LightFrequency: auto exposure under mains-powered lighting."""
    if cam.capability().sIspCapacity.bAntiFlick:
        cam.anti_flicker = True              # CameraSetAntiFlick (auto exposure only)
        cam.light_frequency_hz = 50          # CameraSetLightFrequency: 50 or 60
    return {"anti_flicker": cam.anti_flicker, "hz": cam.light_frequency_hz}
```

<!-- snippet: gain_rgb -->
```python
def gain_rgb(cam):
    """Gain (RGB digital): per-channel gain applied in the ISP, 100 = 1.0x."""
    rg = cam.capability().sRgbGainRange
    cam.digital_gain = (min(120, rg.iRGainMax), 100, 100)   # CameraSetGain
    return {"rgb": cam.digital_gain}         # CameraGetGain
```

<!-- snippet: exposure_multi_raw -->
```python
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
```

## 3. Frame rate, trigger and timing

**Support and ranges.** `pTriggerDesc` (`cam.trigger_modes()`) lists the trigger modes; the header
says that in general 0 is continuous, 1 software and 2 hardware trigger (the enum also defines 3 and
4, rotary-encoder triggers). `pFrameSpeedDesc` (`cam.frame_speeds()`) lists the readout tiers, index 0
to count - 1. `cam.ext_trigger_capability` is a mask of `EXT_TRIG_MASK_GRR_SHUTTER`,
`EXT_TRIG_MASK_LEVEL_MODE`, `EXT_TRIG_MASK_DOUBLE_EDGE` and `EXT_TRIG_MASK_BUFFERED_DELAY`. FrameRate
is supported by some GigE cameras only (0 or less means the maximum). TriggerDelayTime and
TriggerPeriodTime exist on some models only. The external-trigger times default to 0 microseconds;
the headers give no upper limits: model dependent. After `CameraStop` no settings can be changed, so
use it only before closing.

| Setting | What it does | Typical use | Vendor functions | Python | Example |
|---|---|---|---|---|---|
| FrameRate | Caps the frame rate (line rate on line-scan cameras); 0 means maximum. | Share one GigE link between several cameras at 30 fps each. | `CameraSetFrameRate`, `CameraGetFrameRate` | wrapped: `cam.frame_rate_hz` | `frame_rate` |
| FrameSpeed | Selects the sensor readout tier, for example low, normal, high. | Reach the rated frame rate; a slower tier may be the default. | `CameraSetFrameSpeed`, `CameraGetFrameSpeed` | wrapped: `cam.frame_speed`, `cam.frame_speeds()` | `frame_rate` |
| TriggerMode | Continuous capture, software trigger, or hardware trigger. | Capture only when a part is in position. | `CameraSetTriggerMode`, `CameraGetTriggerMode` | wrapped: `cam.trigger_mode` | `trigger_software` |
| SoftTrigger | Fires one software trigger, which captures TriggerCount frames. | Take a picture on request from a robot program. | `CameraSoftTrigger` (`CameraSoftTriggerEx` with flags) | wrapped: `cam.soft_trigger()` | `trigger_software` |
| TriggerCount | Frames captured per trigger, software or hardware; default 1. | A burst of frames per part for averaging. | `CameraSetTriggerCount`, `CameraGetTriggerCount` | wrapped: `cam.trigger_count` | `trigger_software` |
| TriggerDelayTime | Delay from a hardware trigger to capture, in microseconds. | Wait until a part reaches the field of view after a light barrier. | `CameraSetTriggerDelayTime`, `CameraGetTriggerDelayTime` | wrapped: `cam.trigger_delay_us` | `trigger_hardware` |
| TriggerPeriodTime | Gap between the frames of one multi-frame trigger, in microseconds. | Evenly spaced bursts for motion measurement. | `CameraSetTriggerPeriodTime`, `CameraGetTriggerPeriodTime` | wrapped: `cam.trigger_period_us` | `trigger_software` |
| ExtTrigSignalType | Which input edge or level triggers: rising (default), falling, high or low level. | Match the output of the encoder or PLC that drives the trigger. | `CameraSetExtTrigSignalType`, `CameraGetExtTrigSignalType` | wrapped: `cam.ext_trigger_signal` | `trigger_hardware` |
| ExtTrigShutterType | Standard shutter (default) or global reset (GRR) on some rolling-shutter models. | Global-reset exposure together with an external mechanical shutter or flash. | `CameraSetExtTrigShutterType`, `CameraGetExtTrigShutterType` | wrapped: `cam.ext_trigger_shutter` | `trigger_hardware` |
| ExtTrigDelayTime | Delay from an external trigger to capture, in microseconds; default 0. | Hardware trigger from an encoder for synchronized multi-camera capture, aligned per camera. | `CameraSetExtTrigDelayTime`, `CameraGetExtTrigDelayTime` | wrapped: `cam.ext_trigger_delay_us` | `trigger_hardware` |
| ExtTrigBufferedDelayTime | Like ExtTrigDelayTime, but triggers arriving during the delay are queued (up to 128). | A fast conveyor where the next part triggers before the previous delay has ended. | `CameraSetExtTrigBufferedDelayTime`, `CameraGetExtTrigBufferedDelayTime` | wrapped: `cam.ext_trigger_buffered_delay_us` | `trigger_hardware` |
| ExtTrigIntervalTime | External trigger signal interval time in microseconds; default 0. The header does not explain it further. | Model dependent; check the camera's manual before relying on it. | `CameraSetExtTrigIntervalTime`, `CameraGetExtTrigIntervalTime` | wrapped: `cam.ext_trigger_interval_us` | `trigger_hardware` |
| ExtTrigJitterTime | Debounce time of the trigger input, in microseconds; default 0. | Ignore contact bounce from a mechanical switch or relay. | `CameraSetExtTrigJitterTime`, `CameraGetExtTrigJitterTime` | wrapped: `cam.ext_trigger_jitter_us` | `trigger_hardware` |
| ExtTrigCapability | Reports which trigger features the model has (GRR shutter, level trigger, double edge, buffered delay). | Check before relying on level triggering or the buffered delay. | `CameraGetExtTrigCapability` | wrapped: `cam.ext_trigger_capability` | `trigger_hardware` |
| Play / Pause / Stop | Starts streaming; pauses it (output stops, bandwidth is freed, settings apply at once); stops the SDK before closing. | Pause idle cameras so others get the bandwidth. | `CameraPlay`, `CameraPause`, `CameraStop` | wrapped: `cam.play()`, `cam.pause()`, `cam.stop()` | `streaming_control` |
| ClearBuffer | Drops all frames cached in the camera. | Make sure the next frame was exposed after a setting changed. | `CameraClearBuffer` | wrapped: `cam.clear_buffer()` | `streaming_control` |

<!-- snippet: frame_rate -->
```python
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
```

<!-- snippet: trigger_software -->
```python
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
```

<!-- snippet: trigger_hardware -->
```python
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
```

<!-- snippet: streaming_control -->
```python
def streaming_control(cam):
    """Play/Pause/Stop and ClearBuffer: start, suspend, and flush the stream."""
    cam.play()                               # CameraPlay
    cam.pause()                              # CameraPause: stops output, frees bandwidth, settings apply at once
    cam.clear_buffer()                       # CameraClearBuffer: drop frames cached in the camera
    cam.play()
    cam.stop()                               # CameraStop: only before closing; no configuration afterwards
    return {"stopped": True}
```

## 4. Image geometry

**Support and ranges.** `sResolutionRange` holds the minimum and maximum width and height and the
masks `uBinSumModeMask`, `uBinAverageModeMask` and `uSkipModeMask` (bit 0 = 2x2, bit 1 = 3x3, and so
on), which `cam.binning_modes()` decodes. `pImageSizeDesc` (`cam.resolution_presets()`) is the preset
table; the header says it usually has no more than 20 entries, and index 0xFF means a custom size.
`sIspCapacity.bZoomHD` says whether the camera can scale down in hardware. `CameraSetImageResolutionEx`
takes a mode (0 normal, 1 bin sum, 2 bin average, 3 skip, 4 resample) and a mode size (bit 0 = 2x2,
bit 1 = 3x3); `cam.set_roi()` uses mode 0. The headers do not say how the offset and size relate to
the binned output, so verify custom binning with `cam.resolution`, and read `cam.resolution` after any
ROI because the SDK may align the values. HardwareMirror exists on some GigE and USB3 models only;
TransferRoi supports four regions (bits 0 to 3) and returns an error on models without it;
SpliceLines is for line-scan cameras. Mirror, Rotate and Inverse are done by the SDK's image
processing, so they shape `Frame.to_numpy()`; HardwareMirror is the in-camera variant.

| Setting | What it does | Typical use | Vendor functions | Python | Example |
|---|---|---|---|---|---|
| ImageResolution / ImageResolutionEx | Selects a preset size (which may bin or skip pixels) or a custom region of interest. | Read out a small ROI for a higher frame rate, or bin 2x2 for more signal per pixel. | `CameraGetImageResolution`, `CameraSetImageResolution`, `CameraSetImageResolutionEx` | wrapped: `cam.resolution`, `cam.resolution_presets()`, `cam.set_resolution()`, `cam.set_roi()`, `cam.binning_modes()` | `geometry_resolution` |
| ResolutionForSnap | Output size used in snapshot mode; zeros follow the preview size. | Preview at a small size, capture at full size. | `CameraSetResolutionForSnap`, `CameraGetResolutionForSnap` | raw | `geometry_snap_and_transfer_roi_raw` |
| TransferRoi | Sends only up to four sensor regions; the PC fills the rest of the frame with black. | Two separate inspection areas at a higher frame rate. | `CameraSetTransferRoi`, `CameraGetTransferRoi`, `CameraEnableTransferRoi`, `CameraGetTransferRoiEnable` | raw | `geometry_snap_and_transfer_roi_raw` |
| Mirror | Mirrors the image horizontally or vertically. | A camera mounted upside down or looking through a mirror. | `CameraSetMirror`, `CameraGetMirror` | wrapped: `cam.mirror_horizontal`, `cam.mirror_vertical` | `geometry_orientation` |
| HardwareMirror | Mirrors inside the camera. | Mirroring without host CPU cost. | `CameraSetHardwareMirror`, `CameraGetHardwareMirror` | wrapped: `cam.hardware_mirror_horizontal`, `cam.hardware_mirror_vertical` | `geometry_orientation` |
| Rotate | Rotates the image counter-clockwise by 0, 90, 180 or 270 degrees. | A camera mounted in portrait orientation. | `CameraSetRotate`, `CameraGetRotate` | wrapped: `cam.rotation_deg` | `geometry_orientation` |
| Inverse | Inverts the image (negative). | Turn dark-on-light markers into light-on-dark for a detector. | `CameraSetInverse`, `CameraGetInverse` | raw | `geometry_orientation` |
| FlipFrameBuffer | Flips a processed buffer up-down, left-right, or both. | Not needed from Python: flip the numpy copy; `Frame.to_numpy()` already returns top-down rows on Windows. | `CameraFlipFrameBuffer` | raw | `geometry_flip` |
| SpliceLines | Stitches a number of lines from several frames into one frame. | Tall images from a line-scan camera. | `CameraSetSpliceLines`, `CameraGetSpliceLines` | raw | `geometry_line_scan_raw` |

<!-- snippet: geometry_resolution -->
```python
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
```

<!-- snippet: geometry_snap_and_transfer_roi_raw -->
```python
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
```

<!-- snippet: geometry_orientation -->
```python
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
```

<!-- snippet: geometry_flip -->
```python
def geometry_flip(cam):
    """FlipFrameBuffer: flip a numpy copy instead; to_numpy() already returns top-down rows on Windows."""
    cam.play()
    with cam.grab(timeout_ms=1000) as frame:
        image = frame.to_numpy()
    upside_down = np.flipud(image)           # CameraFlipFrameBuffer flag 1
    left_right = np.fliplr(image)            # flag 2
    rotated_180 = image[::-1, ::-1]          # flag 3
    return {"shapes": [a.shape for a in (upside_down, left_right, rotated_180)]}
```

<!-- snippet: geometry_line_scan_raw -->
```python
def geometry_line_scan_raw(cam):
    """SpliceLines (line-scan cameras): stitch lines from several frames into one; raw."""
    try:
        cam.call("CameraSetSpliceLines", 0, argtypes=[c_int])   # 0 = no splicing (default)
        return {"splice_lines": cam.query("CameraGetSpliceLines", c_int)}
    except MvError as exc:
        return {"error": exc.status}
```

## 5. Image processing

**Support and ranges.** `sIspCapacity.bMonoSensor` marks mono cameras, on which the colour settings
(saturation, white balance, colour temperature, Bayer algorithm, Monochrome) do not apply.
`bWbOnce` and `bAutoWb` say whether manual and automatic white balance exist; `bDeviceIsp` and
`bForceUseDeviceIsp` whether the camera has its own ISP and whether its use is mandatory.
`sGammaRange`, `sContrastRange`, `sSaturationRange` and `sSharpnessRange` hold the ranges (the header
says sharpness is usually 0 to 100). `pClrTempDesc` (`cam.color_temperature_presets()`) lists the
preset colour temperatures, `iPresetLut` the preset lookup tables, `iBayerDecAlmSwDesc` and
`iBayerDecAlmHdDesc` the Bayer algorithms on the PC and in the camera. From the header comments:
black and white level 0 to 255 (defaults 0 and 255), logarithmic curve 0 to 255, noise reduction
0 to 7, 3D noise reduction over 2 to 8 frames, user colour-temperature gains 0 to 400 (0 to 4x), a
custom lookup table of 4096 entries, saturation 100 = unchanged, sharpness 0 = off; gamma and
contrast act only in `LUTMODE_PARAM_GEN`. For the output format the header documents Mono8 and RGB8;
the vendor's own Python examples also use BGR8. When the ISP runs on the PC (`ISP_PROCESSOR_PC`),
these settings are applied in `CameraImageProcess`, so they shape `Frame.to_numpy()`, while
`Frame.view()` shows the buffer before that step.

| Setting | What it does | Typical use | Vendor functions | Python | Example |
|---|---|---|---|---|---|
| IspOutFormat | Pixel format that `Frame.to_numpy()` returns (Mono8, BGR8, RGB8, ...). | Mono8 for detection, BGR8 for OpenCV display. | `CameraSetIspOutFormat`, `CameraGetIspOutFormat` | wrapped: `cam.output_format` | `isp_output_and_processor` |
| IspProcessor | Runs the image processing on the PC or in the camera. | Lower host CPU load with several cameras. | `CameraSetIspProcessor`, `CameraGetIspProcessor` | wrapped: `cam.isp_processor` | `isp_output_and_processor` |
| Monochrome | Converts colour images to grey. | Feed a colour camera into a mono algorithm. | `CameraSetMonochrome`, `CameraGetMonochrome` | wrapped: `cam.monochrome` | `isp_output_and_processor` |
| Gamma | Gamma of the lookup table generated from parameters. | Brighten dark regions for display. | `CameraSetGamma`, `CameraGetGamma` | wrapped: `cam.gamma` | `isp_tone` |
| Contrast | Contrast of the lookup table generated from parameters. | Separate objects from the background for a simple threshold. | `CameraSetContrast`, `CameraGetContrast` | wrapped: `cam.contrast` | `isp_tone` |
| Saturation | Colour saturation; 100 leaves colours unchanged. | Stronger colours for colour-based sorting. | `CameraSetSaturation`, `CameraGetSaturation` | wrapped: `cam.saturation` | `isp_tone` |
| Sharpness | Sharpening; 0 turns it off. | Keep it at 0 for measurement so edges are not altered. | `CameraSetSharpness`, `CameraGetSharpness` | wrapped: `cam.sharpness` | `isp_tone` |
| BlackLevel | Black reference level, 0 to 255. | Remove a dark offset. | `CameraSetBlackLevel`, `CameraGetBlackLevel` | wrapped: `cam.black_level` | `isp_tone` |
| WhiteLevel | White reference level, 0 to 255. | Stretch a dim scene to the full range. | `CameraSetWhiteLevel`, `CameraGetWhiteLevel` | wrapped: `cam.white_level` | `isp_tone` |
| LogarithmicCurveValue | Logarithmic tone curve value, 0 to 255. | Compress highlights in high-contrast scenes. | `CameraSetLogarithmicCurveValue`, `CameraGetLogarithmicCurveValue` | raw | `isp_tone` |
| NoiseFilter | Enables the noise filter. | Cleaner images at high gain. | `CameraSetNoiseFilter`, `CameraGetNoiseFilterState` | wrapped: `cam.noise_filter` | `isp_noise` |
| NoiseReductionValue | Noise reduction strength, 0 to 7. | Balance noise against loss of detail. | `CameraSetNoiseReductionValue`, `CameraGetNoiseReductionValue` | raw | `isp_noise` |
| Denoise3DParams | Temporal noise reduction over 2 to 8 frames, with optional weights. | A static scene in low light. | `CameraSetDenoise3DParams`, `CameraGetDenoise3DParams` | raw | `isp_noise` |
| CorrectDeadPixel | Enables dead-pixel correction. | Hide hot pixels on long exposures. | `CameraSetCorrectDeadPixel`, `CameraGetCorrectDeadPixel` | wrapped: `cam.dead_pixel_correction` | `isp_noise` |
| BayerDecAlgorithm | Selects the Bayer-to-colour algorithm on the PC or in the camera. | Trade colour quality against CPU time. | `CameraSetBayerDecAlgorithm`, `CameraGetBayerDecAlgorithm` | raw | `isp_noise` |
| WbMode | Continuous automatic or manual white balance. | Automatic for changing light, manual for stable colours. | `CameraSetWbMode`, `CameraGetWbMode` | wrapped: `cam.auto_white_balance` | `isp_white_balance` |
| OnceWB | Runs one white balance in manual mode, applied with the next frame. | Calibrate on a grey card at start-up. | `CameraSetOnceWB` | wrapped: `cam.white_balance_once()` | `isp_white_balance` |
| WbWindow | Region used for white balance. | Point it at a grey reference patch in the scene. | `CameraSetWbWindow`, `CameraGetWbWindow` | wrapped: `cam.wb_window` | `isp_white_balance` |
| ClrTempMode | Automatic, preset, or user-defined colour temperature. | Fixed lighting with a known colour temperature. | `CameraSetClrTempMode`, `CameraGetClrTempMode` | wrapped: `cam.color_temperature_mode` | `isp_white_balance` |
| PresetClrTemp | Selects one of the camera's preset colour temperatures. | Use the preset that matches the light source. | `CameraSetPresetClrTemp`, `CameraGetPresetClrTemp` | wrapped: `cam.preset_color_temperature`, `cam.color_temperature_presets()` | `isp_white_balance` |
| UserClrTempGain | Per-channel gains of the user colour-temperature mode, 0 to 400 (0 to 4x). | Colour calibration for a custom light source. | `CameraSetUserClrTempGain`, `CameraGetUserClrTempGain` | raw | `isp_white_balance` |
| UserClrTempMatrix | 3x3 colour matrix of the user colour-temperature mode. | Apply a colour correction matrix from a calibration chart. | `CameraSetUserClrTempMatrix`, `CameraGetUserClrTempMatrix` | raw | `isp_white_balance` |
| OnceBB | Runs one black balance. | Remove a colour cast in dark areas. | `CameraSetOnceBB` | wrapped: `cam.black_balance_once()` | `isp_white_balance` |
| LutMode | Tone mapping from gamma and contrast, from a preset table, or from a user table. | A custom response curve for one task. | `CameraSetLutMode`, `CameraGetLutMode` | wrapped: `cam.lut_mode` | `isp_tone` |
| CustomLut | User lookup table: 4096 entries for one channel or all. | Exact tone mapping, for example a threshold table for binarisation. | `CameraSetCustomLut`, `CameraGetCustomLut` | raw | `isp_lut_and_undistort_raw` |
| Undistort* | Lens undistortion from the camera matrix (fx, fy, cx, cy) and distortion coefficients (k1, k2, p1, p2, k3). | Straight lines from a wide-angle lens without OpenCV. | `CameraSetUndistortParams`, `CameraSetUndistortEnable`, their getters | raw | `isp_lut_and_undistort_raw` |

<!-- snippet: isp_output_and_processor -->
```python
def isp_output_and_processor(cam):
    """IspOutFormat, IspProcessor, Monochrome: what to_numpy() returns and where the ISP runs."""
    cam.output_format = gcam_mvsdk_py.Mono8 if cam.is_mono else gcam_mvsdk_py.BGR8  # CameraSetIspOutFormat
    if cam.capability().sIspCapacity.bDeviceIsp:
        cam.isp_processor = gcam_mvsdk_py.ISP_PROCESSOR_DEVICE   # CameraSetIspProcessor: less host CPU
    if not cam.is_mono:
        cam.monochrome = True                # CameraSetMonochrome: grey output from a colour sensor
    return {"format": cam.output_format, "isp": cam.isp_processor}
```

<!-- snippet: isp_tone -->
```python
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
```

<!-- snippet: isp_noise -->
```python
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
```

<!-- snippet: isp_white_balance -->
```python
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
```

<!-- snippet: isp_lut_and_undistort_raw -->
```python
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
```

## 6. Digital I/O, strobe and lighting

**Support and ranges.** `iInputIoCounts` and `iOutputIoCounts` (`cam.io_counts`) are the numbers of
programmable inputs and outputs; indices start at 0. The Ex functions report 1 for high and 0 for low
on every model; the older `CameraGetIOState`/`CameraSetIOState` use the inverse on GE and SUA models,
which is why this package uses the Ex variants. Pin modes (`emCameraGPIOMode`): 0 trigger input,
1 strobe output, 2 general input, 3 general output, 4 PWM output, 5 rotary-encoder input, 6 line
strobe output; formats (`emCameraGPIOFormat`): 0 single ended, 1 RS422, 2 RS422 with termination,
3 optocoupler. Which modes and formats a pin accepts is reported by
`CameraGetInPutIOModeCapbility`, `CameraGetOutPutIOModeCapbility` and the matching
`...FormatCapbility` functions (raw). PWM duty is 1 to 99 %; pulse width, delay and PWM period are in
microseconds. The strobe is active high by default; `STROBE_ALWAYS_HIGH`/`LOW` ignore the other
strobe settings. LED brightness is 0 to 255, and the LED functions return an error on models without
LEDs. The light controller needs the smart camera series; the rotary-encoder settings belong to the
encoder input (pin mode 5).

| Setting | What it does | Typical use | Vendor functions | Python | Example |
|---|---|---|---|---|---|
| IOState / IOStateEx | Reads an input level; sets and reads an output level. | Drive a reject gate, or read a part-present sensor. | `CameraGetIOStateEx`, `CameraSetIOStateEx`, `CameraGetOutPutIOStateEx` | wrapped: `cam.get_input()`, `cam.set_output()`, `cam.get_output()`, `cam.io_counts` | `io_digital` |
| InPutIO* | Mode and electrical format of an input. | Use a pin as a general input instead of the trigger. | `CameraSetInPutIOMode`, `CameraSetInPutIOFormat`, their getters and capability queries | raw | `io_digital` |
| OutPutIO* | Mode and electrical format of an output. | Turn an output into a PWM signal for a light. | `CameraSetOutPutIOMode`, `CameraSetOutPutIOFormat`, their getters and capability queries | raw | `io_digital` |
| OutPutPolarity / PulseWidth / DelayTime / PWM | Polarity, pulse width and delay of an output, or PWM period and duty. | Send a 1 ms pulse to a PLC. | `CameraSetOutPutPolarity`, `CameraSetOutPutPulseWidth`, `CameraSetOutPutDelayTime`, `CameraSetOutPutPWM` | raw | `io_digital` |
| Strobe* | Strobe output in step with the trigger (automatic, or with delay and width) or held high or low; polarity selectable. | Fire a flash exactly during the exposure. | `CameraSetStrobeMode`, `CameraSetStrobePolarity`, `CameraSetStrobeDelayTime`, `CameraSetStrobePulseWidth`, their getters | wrapped: `cam.strobe_mode`, `cam.strobe_polarity`, `cam.strobe_delay_us`, `cam.strobe_pulse_width_us` | `io_strobe` |
| Led* | Brightness, on/off, enable and duration of built-in LEDs. | The built-in light of a smart camera. | `CameraSetLedBrightness`, `CameraSetLedOnOff`, `CameraSetLedEnable`, `CameraSetLedDuration`, their getters | raw | `io_led_lighting_encoder_raw` |
| LightingController* | Output mode (follow strobe or manual) and state of a light controller (smart camera series). | Switch an attached light on only while capturing. | `CameraSetLightingControllerMode`, `CameraSetLightingControllerState` | raw | `io_led_lighting_encoder_raw` |
| RotaryEnc* | Counted direction and frequency multiplier and divider of a rotary encoder input. | Line-scan capture locked to conveyor travel. | `CameraSetRotaryEncDir`, `CameraSetRotaryEncFreq`, their getters | raw | `io_led_lighting_encoder_raw` |

<!-- snippet: io_digital -->
```python
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
```

<!-- snippet: io_strobe -->
```python
def io_strobe(cam):
    """Strobe*: fire a flash or light controller in step with the exposure."""
    cam.strobe_mode = gcam_mvsdk_py.STROBE_SYNC_WITH_TRIG_MANUAL   # CameraSetStrobeMode
    cam.strobe_polarity = 1                  # CameraSetStrobePolarity: 1 = active high (default)
    cam.strobe_delay_us = 0                  # CameraSetStrobeDelayTime
    cam.strobe_pulse_width_us = 2000         # CameraSetStrobePulseWidth
    return {"mode": cam.strobe_mode}
```

<!-- snippet: io_led_lighting_encoder_raw -->
```python
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
```

## 7. GigE transport

**Support and ranges.** `pPackLenDesc` (`cam.packet_sizes()`) lists the packet sizes the camera
offers; the header recommends about 8 KB on NICs with jumbo frames to reduce CPU time.
FrameResendCount applies to GigE cameras in trigger mode only; 0 or less disables resends, and the
SDK has no getter. `CameraGigeSetOption` (`sdk.gige_set_option()`) sets transport options such as
`NumBuffers`. Not from the header but measured with this project's cameras: the host socket buffer
(`net.core.rmem_max`) limits throughput; see Known issue 2 in the README.

| Setting | What it does | Typical use | Vendor functions | Python | Example |
|---|---|---|---|---|---|
| TransPackLen | Selects the GigE packet size from the sizes the camera offers. | 1500-byte packets on a standard NIC; larger packets with jumbo frames. | `CameraSetTransPackLen`, `CameraGetTransPackLen` | wrapped: `cam.gige_packet_size`, `cam.gige_packet_index`, `cam.packet_sizes()` | `gige_transport` |
| FrameResendCount | How often the camera resends a frame the PC did not acknowledge, in trigger mode. | Reliable triggered capture on a lossy link. | `CameraSetFrameResendCount` | wrapped: `cam.set_frame_resend_count()` | `gige_transport` |

<!-- snippet: gige_transport -->
```python
def gige_transport(cam):
    """TransPackLen and FrameResendCount: packet size for the NIC MTU, resends in trigger mode."""
    sizes = [p.size for p in cam.packet_sizes()]     # pPackLenDesc
    if sizes:
        cam.gige_packet_size = 1500          # CameraSetTransPackLen: largest advertised size <= 1500
    cam.set_frame_resend_count(2)            # CameraSetFrameResendCount (no getter)
    cam.sdk.gige_set_option("NumBuffers", 8)  # CameraGigeSetOption
    return {"sizes": sizes, "packet": cam.gige_packet_size if sizes else None}
```

## 8. Parameter persistence

**Support and ranges.** `bParamInDevice` says whether groups can be stored in the camera
(`PARAM_MODE_IN_DEVICE`). There are four groups, A to D (`PARAMETER_TEAM_A` to `_D`, values 0 to
3); loading `"default"` (0xFF) restores the defaults. Parameter modes (`emSdkParameterMode`): 0 by
model name, 1 by device name, 2 by serial number (these three use `.config` files on the PC), 3 in
the camera. ParameterMask selects settings pages by the `PROP_SHEET_INDEX_*` values in
`CameraDefine.h` (exposure, colour, lookup table, transform, format, resolution, IO, trigger, and
more); the headers do not spell out the bit layout. DataDirectory must be set before a camera is
opened, and the header says SysOption usually is too; the data directory defaults to the current
directory and holds the `.config` and `.mvdat` files.

| Setting | What it does | Typical use | Vendor functions | Python | Example |
|---|---|---|---|---|---|
| SaveParameter / LoadParameter (groups A to D) | Saves the current settings into one of four groups; loads a group or the defaults. | Day and night profiles that a program switches between. | `CameraSaveParameter`, `CameraLoadParameter`, `CameraGetCurrentParameterGroup` | wrapped: `cam.save_parameter("A")`, `cam.load_parameter("A")`, `cam.parameter_group` | `persistence_groups` |
| SaveParameterToFile | Writes all settings to a `.config` file, or loads one. | Copy a tuned configuration to an identical camera on another PC. | `CameraSaveParameterToFile`, `CameraReadParameterFromFile` | wrapped: `cam.save_parameter_to_file()`, `cam.load_parameter_from_file()` | `persistence_groups` |
| ParameterMode | Where groups are stored: per model, per name, per serial number, or in the camera. | Store settings in the camera so they follow it to another PC. | `CameraSetParameterMode`, `CameraGetParameterMode` | wrapped: `cam.parameter_mode` | `persistence_groups` |
| ParameterMask | Which settings pages are saved and loaded. | Save exposure without touching the resolution. | `CameraSetParameterMask` | raw | `persistence_groups` |
| SysOption | SDK-wide option, usually set before a camera is opened. | Increase the number of frame buffers. | `CameraSetSysOption` | wrapped: `sdk.set_sys_option()` | `persistence_library` |
| DataDirectory | Folder where the SDK keeps its data files. | Keep parameter files in a fixed place instead of the working directory. | `CameraSetDataDirectory` | wrapped: `sdk.set_data_directory()` | `persistence_library` |

<!-- snippet: persistence_groups -->
```python
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
```

<!-- snippet: persistence_library -->
```python
def persistence_library(sdk, data_dir="/tmp/mvsdk-data"):
    """SysOption and DataDirectory: SDK-wide settings, before any camera is opened."""
    sdk.set_data_directory(data_dir)         # CameraSetDataDirectory: where .config files live
    sdk.set_sys_option("NumBuffers", 8)      # CameraSetSysOption
    return {"data_dir": data_dir}
```

## 9. Callbacks

**Support and ranges.** Callbacks run on SDK threads: keep them short and hand work to a queue.
Exceptions inside the wrapped callbacks are printed and swallowed, because they cannot travel back
into C. A ctypes callback object must stay alive while it is installed; the wrapped methods keep it on
the `Camera`, and for raw callbacks you must keep it yourself (the example stores it on the camera
object). Do not close the camera from inside its own callback. Frame events (`tSdkFrameEvent`) carry
a type (1 frame start, 2 frame end), a status (0 = success), the frame id, size, pixel format and a
64-bit timestamp in two halves; for global-shutter cameras, frame start means the exposure has
ended. The connection callback reports 0 for disconnected and 1 for restored; for GigE cameras the
reason on reconnect is 0 for a network failure and 1 for a power loss.

| Setting | What it does | Typical use | Vendor functions | Python | Example |
|---|---|---|---|---|---|
| CallbackFunction | Delivers each new frame to a function instead of polling. | Lowest-latency processing without a grab loop. | `CameraSetCallbackFunction` | wrapped: `cam.set_callback(fn)` | `callbacks` |
| FrameEventCallback | Reports frame start and frame end events. | Time-stamp exposures, or react as soon as an exposure ends. | `CameraSetFrameEventCallback` | raw | `callbacks` |
| ConnectionStatusCallback | Reports disconnects and reconnects, with a reason for GigE cameras. | Raise an alarm or restart a pipeline when a cable is pulled. | `CameraSetConnectionStatusCallback` | wrapped: `cam.set_connection_callback(fn)` | `callbacks` |

<!-- snippet: callbacks -->
```python
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
```

## 10. Vendor GUI and recording

These functions serve the vendor's own display window, settings dialog and recorder. They are not
wrapped; from Python, use NumPy and OpenCV on `Frame.to_numpy()` instead (see
[`examples/live_view.py`](../examples/live_view.py)). MediaType is the exception that can matter
outside the GUI: it selects the sensor's raw output format from `pMediaTypeDesc`.

| Setting | What it does | Typical use | Vendor functions | Python | Example |
|---|---|---|---|---|---|
| Display* | Draws frames into a native window handle. | Use OpenCV instead. | `CameraDisplayInit`, `CameraDisplayRGB24`, `CameraSetDisplayMode`, `CameraSetDisplayOffset`, `CameraSetDisplaySize` | raw | none |
| CrossLine | Crosshair overlays (nine lines) in the vendor display. | Draw with `cv2.line` on the NumPy frame instead. | `CameraSetCrossLine`, `CameraGetCrossLine` | raw | none |
| ActiveSettingSubPage | Selects the visible page of the vendor settings window. | None outside the vendor GUI. | `CameraSetActiveSettingSubPage` | raw | none |
| MediaType | Selects the sensor's raw output format (model dependent, for example a higher bit depth). | Raw data with more than 8 bits per pixel. | `CameraSetMediaType`, `CameraGetMediaType` | raw | `vendor_media_type_raw` |
| MediaBitRate | Bit rate of compressed outputs (H264, H265) on models that have them. | Compressed streaming models. | `CameraSetMediaBitRate`, `CameraGetMediaBitRate` | raw | none |
| StopRecord | Ends a recording started with `CameraInitRecord` (uncompressed or MSCV). | Use `cv2.VideoWriter` on NumPy frames instead. | `CameraInitRecord`, `CameraStopRecord` | raw | none |
| SaveImage | Saves a frame as BMP, JPG, PNG or RAW. | Use `gcam-mvsdk-py grab` or `cv2.imwrite` instead. | `CameraSaveImage` | raw | none |

<!-- snippet: vendor_media_type_raw -->
```python
def vendor_media_type_raw(cam):
    """MediaType: the sensor's raw output format (not the ISP output); raw call."""
    types = cam.media_types()                # pMediaTypeDesc: (index, media type, description)
    current = cam.query("CameraGetMediaType", c_int)
    if types:
        cam.call("CameraSetMediaType", types[0][0], argtypes=[c_int])
    return {"current": current, "available": [t[2] for t in types]}
```
