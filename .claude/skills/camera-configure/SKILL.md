---
name: camera-configure
description: Read and change HuaTeng camera settings with gcam-mvsdk-py (exposure, auto exposure, gain, frame rate, trigger mode, ROI and resolution, mirror and rotation, white balance, packet size) and make them persistent by saving a parameter group (save_parameter("A")). Use when the user asks to set, tune, check or keep a camera setting, asks why a setting did not stick after reopening or a power cycle, or asks what range a camera model supports.
---

# Configure a camera

Settings are read with `gcam-mvsdk-py info` and changed through the Python API (the command line
only sets exposure, output format and trigger mode for the duration of a `grab`). Every change goes
into the camera's working settings and is lost unless it is saved to a parameter group.
docs/CAPABILITIES.md is the reference for every setting, its range source, and a runnable example.

## When to use

- Change exposure, auto exposure, gain, frame rate, trigger mode, ROI or resolution, mirroring,
  rotation, white balance, output format, or the GigE packet size.
- Make settings survive reopening and power cycles.
- Find out which settings and ranges a camera model supports.

## Prerequisites

- The camera is listed (`gcam-mvsdk-py list`) and no other program holds it; configuring opens it.
- A Python with the package: `~/.gcam-mvsdk/py-venv/bin/python3` (installed environment, already
  allowed to discover cameras) or your own environment with `gcam-mvsdk-py` installed.

## How settings are stored

- **Working settings.** Every property assignment (`cam.exposure_us = 8000`) changes the camera's
  current, volatile settings. They are lost at power-off and are normally replaced the next time a
  program opens the camera, because opening loads a saved group.
- **Parameter groups A to D.** `cam.save_parameter("A")` stores the working settings in group A
  (also `"B"`, `"C"`, `"D"`); `cam.load_parameter("A")` loads it; `cam.load_parameter("default")`
  restores the defaults. `cam.parameter_group` is the current group (0 to 3 for A to D, 255 for
  the defaults).
- **Which group loads.** `sdk.open()`, and therefore every `gcam-mvsdk-py` command and example,
  calls `CameraInit` with -1 for the parameter-load mode and the group, which the SDK header defines
  as "the mode and the group used at the last exit". So the group that was current when the camera
  was last closed is the one loaded at the next open. To make group A the one that loads, save to A
  and then `load_parameter("A")` so that A is also the current group when the camera closes, and
  confirm with step 5 (this behaviour has not been verified on every model).
- **Where groups live (model dependent).** `cam.parameter_mode`: `PARAM_MODE_BY_MODEL` (0),
  `PARAM_MODE_BY_NAME` (1) and `PARAM_MODE_BY_SN` (2) keep groups in `.config` files on the PC, in
  the SDK data directory, which defaults to the current working directory of the program
  (`sdk.set_data_directory()` before opening fixes it). By model and by name, one file set is
  shared by every camera with the same model or name. `PARAM_MODE_IN_DEVICE` (3) keeps groups in
  the camera itself and is available only when `info` shows `parameters_in_device: True`.
  What a camera does at power-on without any program attached is not documented in the SDK headers.

## Steps

1. **Read the current values and the model's ranges.** Keep a copy to restore from.

   ```bash
   gcam-mvsdk-py info <cam>                       # Exposure, Gain, Resolution, Trigger, ..., Capability
   gcam-mvsdk-py info <cam> --json > /tmp/<cam>-before.json
   ```

2. **Look the setting up** in docs/CAPABILITIES.md ("Support and ranges" paragraph and table of its
   section). Ranges come from the Capability block or from methods such as
   `cam.exposure_range_us()`; where the headers give none, the range is model dependent.

3. **Try the change in one session and check a frame in the same session.** A new session (for
   example `gcam-mvsdk-py grab`) reloads the saved group, so it does not show unsaved changes.

   ```bash
   ~/.gcam-mvsdk/py-venv/bin/python3 - <<'PY'
   import gcam_mvsdk_py

   sdk = gcam_mvsdk_py.load()
   with sdk.open("sb01") as cam:                      # user-set name or serial number
       print("exposure range us:", cam.exposure_range_us())
       cam.exposure_us = 8000                         # manual exposure; turns auto exposure off
       print("exposure now:", cam.exposure_us)        # read back: rounded to whole sensor lines
       cam.output_format = gcam_mvsdk_py.Mono8
       cam.trigger_mode = gcam_mvsdk_py.TRIGGER_CONTINUOUS
       cam.play()
       with cam.grab(timeout_ms=2000) as frame:
           img = frame.to_numpy()
       print("mean %.1f, saturated %.2f %%" % (img.mean(), 100.0 * (img == 255).mean()))
   PY
   ```

4. **Save, only after the user confirms** (always on production cameras):

   ```python
   with sdk.open("sb01") as cam:
       cam.exposure_us = 8000                          # set every value to keep in this session
       print("mode", cam.parameter_mode, "group", cam.parameter_group)
       cam.save_parameter("A")                         # store the working settings in group A
       cam.load_parameter("A")                         # make A the current group, loaded at the next open
   ```

5. **Verify in a new session**, then after a power cycle:

   ```bash
   gcam-mvsdk-py info <cam>          # shows the saved values
   gcam-mvsdk-py grab <cam> -n 1 -o /tmp/<cam>-check   # see camera-grab
   ```

### Settings and where to set them

| Setting | Command line | Python (`cam.` ...) | CAPABILITIES.md |
|---|---|---|---|
| Exposure | `grab --exposure-us N` (that grab only) | `exposure_us`, `exposure_range_us()`, `exposure_line_time_us` | 2 |
| Auto exposure | none | `auto_exposure`, `ae_target`, `ae_threshold`, `ae_exposure_range_us = (lo, hi)`, `ae_analog_gain_range`, `ae_window`, `anti_flicker`, `light_frequency_hz` | 2 |
| Gain | none | `analog_gain_x` (factor; `analog_gain_x_range()`), `analog_gain` (steps), `digital_gain = (r, g, b)` (100 = 1.0x) | 2 |
| Frame rate | none | `frame_speed` (index from `frame_speeds()`), `frame_rate_hz` (0 = uncapped; some GigE models only) | 3 |
| Trigger mode | `grab` always uses continuous | `trigger_mode = gcam_mvsdk_py.TRIGGER_CONTINUOUS`, `TRIGGER_SOFTWARE` or `TRIGGER_HARDWARE`; `soft_trigger()`, `trigger_count`, `trigger_delay_us`, `ext_trigger_signal`, `ext_trigger_delay_us`, `ext_trigger_jitter_us` | 3 |
| ROI and resolution | none | `set_roi(x, y, w, h)` then read `resolution`; `set_resolution(index)` with `resolution_presets()`; `set_roi(0, 0, *cam.max_size)` for full frame | 4 |
| Mirror and rotation | none | `mirror_horizontal`, `mirror_vertical`, `hardware_mirror_horizontal`/`_vertical` (some models), `rotation_deg` (0, 90, 180, 270) | 4 |
| White balance (colour) | none | `auto_white_balance`, `white_balance_once()`, `wb_window`, `color_temperature_mode`, `preset_color_temperature`, `digital_gain` | 5 |
| Output format | `grab --format` | `output_format = gcam_mvsdk_py.Mono8` (or `BGR8`, `RGB8`) | 5 |
| Packet size (GigE) | none (`live_view.py --mtu` for its own session) | `gige_packet_size = 1500` (largest advertised size that fits), `packet_sizes()` | 7 |
| Persistence | none | `save_parameter("A")`, `load_parameter("A")`, `parameter_group`, `parameter_mode`, `save_parameter_to_file(path)` | 8 |

Functions without a property are reachable with `cam.call()` and `cam.query()`, as the "raw"
rows of docs/CAPABILITIES.md show. To try a whole section on a camera, use run-capabilities-example.

## Reading the output

`info` prints groups of `name : value` lines:

- `Exposure time : 5000.0 us  (5.000 ms)  ->  1/200 s` and `Max FPS from shutter alone`: the
  exposure time caps the frame rate at 1,000,000 divided by the exposure in microseconds.
- `Auto-exposure : ON` means the camera chooses the exposure; setting `exposure_us` turns it off.
- `Exposure range`, `Analog gain`, `Frame-rate cap: 0 Hz (0 = uncapped)`, `Frame speed` (current
  index and the available tiers), `Mode` under Trigger (`Continuous (free-run)`, `Software trigger`,
  `Hardware trigger`), and `Packet sizes` with the current index under GigE.
- **Capability block** (what this model supports): `auto_exposure`, `anti_flicker`,
  `auto_white_balance`, `device_isp`, `parameters_in_device` (True/False); ranges such as
  `ae_target_range`, `analog_gain_range` with `analog_gain_step`, `exposure_range_lines`,
  `gamma_range`, `width_range`; lists such as `trigger_modes`, `frame_speeds`, `packet_sizes`,
  `binning`; counts `inputs`, `outputs`, `user_data_bytes`.
- A value shown as `(error: ...)` could not be read; status -4 there means the model lacks it.

Values read back after a write can differ from the value written (exposure rounded to sensor
lines, ROI aligned, packet size chosen from the advertised list). Use the value read back.

## If it fails

| Symptom | Cause | Fix |
|---|---|---|
| `MvError` with status -4 (not supported) | The model lacks the feature | Check the Capability block; use another approach |
| `ValueError` before anything is sent | Out of the range the package checks (black/white level 0 to 255, rotation, ROI outside the sensor, unknown preset, no packet size that fits) | Choose a value inside the reported range |
| Status 32774, -45, -18 or -13 when opening | Another program or host holds the camera | Stop the holder, retry; restart it afterwards |
| Settings are back to old values after reopening | Not saved, saved to a group that is not current, or the program ran in another working directory (file-based parameter modes) | Save and load the group (step 4); fix the data directory or use `PARAM_MODE_IN_DEVICE` on models that support it |
| No frames after a change | Trigger mode is software or hardware | `cam.trigger_mode = gcam_mvsdk_py.TRIGGER_CONTINUOUS`, or trigger it |
| Frames time out after raising the packet size | Packet size above the NIC MTU | `cam.gige_packet_size = 1500`, or enable jumbo frames on the NIC (camera-grab) |
| Frame rate lower than expected | Exposure time, `frame_speed` tier, `frame_rate_hz` cap, or host socket buffers | See info; README "Known issues" for `net.core.rmem_max` |

## Safety

- Read before write: record `gcam-mvsdk-py info <cam> --json` before changing anything, and change
  one setting at a time.
- Confirm with the user before `save_parameter`, `load_parameter("default")`, `parameter_mode`
  changes, or `load_parameter_from_file` on a production camera. Saving overwrites a group that
  other programs load at every open; in the by-model and by-name modes the same files are used by
  every camera of that model or name on this PC.
- Do not change trigger mode, ROI or packet size on a camera that a production pipeline expects in
  a specific state without the owner's consent.
- Settings that drive hardware (digital outputs, strobe) can actuate connected equipment; change
  them only when the user knows what is wired to the camera.
