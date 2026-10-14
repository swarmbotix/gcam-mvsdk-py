---
name: run-capabilities-example
description: Run examples/capabilities.py against a real HuaTeng camera (python examples/capabilities.py <cam> [function or section] [--write], or --list) to see which settings of docs/CAPABILITIES.md a camera model supports, read-only by default; map each example function to its document section and interpret results, skipped writes and status -4. Use when the user asks what a camera model can do, wants to try a CAPABILITIES.md example on hardware, or wants to compare two models.
---

# Run the capabilities examples on a camera

`examples/capabilities.py` holds one function per settings group; docs/CAPABILITIES.md shows each
function as the example of its section. Run as a script, it executes the functions against one
camera. By default it is read-only: every setter is skipped and listed, while reads, streaming and
grabbing still run.

## When to use

- Find out which settings of docs/CAPABILITIES.md a camera model supports.
- Try a section's example on hardware before writing your own code.
- Compare two camera models (run it on each and compare the output).

For changing and keeping one setting, use camera-configure; for the model's ranges alone,
`gcam-mvsdk-py info <cam>` (Capability block) is quicker.

## Prerequisites

- A repository clone (the examples are not in the installed package); run from its root.
- An interpreter with the package and NumPy: `~/.gcam-mvsdk/py-venv/bin/python3`, or your own
  environment with the package installed (as in run-live-view). No root or capability is needed.
- The camera is listed (`gcam-mvsdk-py list`) and not held by another program.

## Steps

```bash
cd /path/to/gcam-mvsdk-py
PY=~/.gcam-mvsdk/py-venv/bin/python3
$PY examples/capabilities.py --list                    # functions by section; needs no camera
$PY examples/capabilities.py sb01                      # every function, read-only
$PY examples/capabilities.py sb01 2                    # section 2 only (Exposure and gain)
$PY examples/capabilities.py sb01 exposure_auto        # one function
$PY examples/capabilities.py sb01 > /tmp/sb01-capabilities.txt; gcam-mvsdk-py info sb01 --json > /tmp/sb01-info.json
$PY examples/capabilities.py sb01 exposure_auto --write   # apply the setters (bench camera, with consent)
```

Arguments: `CAMERA` (user-set name or serial number), `FUNCTION` (a function name or a section
number, default all), `--write` (apply the setters), `--list` (print the mapping and exit).

### Functions and sections

| Section of docs/CAPABILITIES.md | Functions | With `--write` |
|---|---|---|
| 1. Identity and network | `identity_name`, `identity_network`, `identity_serial_and_user_data` | always a dry run |
| 2. Exposure and gain | `exposure_manual`, `exposure_auto`, `exposure_flicker`, `gain_rgb`, `exposure_multi_raw` | applied |
| 3. Frame rate, trigger and timing | `frame_rate`, `trigger_software`, `trigger_hardware`, `streaming_control` | applied |
| 4. Image geometry | `geometry_resolution`, `geometry_snap_and_transfer_roi_raw`, `geometry_orientation`, `geometry_flip`, `geometry_line_scan_raw` | applied |
| 5. Image processing | `isp_output_and_processor`, `isp_tone`, `isp_noise`, `isp_white_balance`, `isp_lut_and_undistort_raw` | applied |
| 6. Digital I/O, strobe and lighting | `io_digital`, `io_strobe`, `io_led_lighting_encoder_raw` | applied: drives the camera's outputs |
| 7. GigE transport | `gige_transport` | applied |
| 8. Parameter persistence | `persistence_groups`, `persistence_library` | always a dry run |
| 9. Callbacks | `callbacks` | applied |
| 10. Vendor GUI and recording | `vendor_media_type_raw` | applied |

Sections 1 and 8 write things that outlive the program (the name `sb01`, the address
192.168.3.21 on the first camera found, user data, parameter group B, a `.config` file, the SDK data
directory), so the runner never executes their setters. Functions ending in `_raw` call vendor
functions that have no wrapper, through `cam.call()` and `cam.query()`.

## Reading the output

```
Camera 'sb01': SN 056090423003, model MV-GE134GM. Read-only: setters are listed, not called.

== exposure_auto  [2. Exposure and gain; dry run]
   result : {'target': 110, 'window': (0, 0, 0, 0)}
   skipped: auto_exposure = True
            ae_target = 120
            ...

== exposure_multi_raw  [2. Exposure and gain; dry run]
   result : {'error': -4}

5 function(s), 0 raised an error.
```

- `result`: the dictionary the function returns. In a dry run, values read back are the camera's
  current values, not the example's.
- `skipped`: setters that were not called, with the values the example would write. In a dry run a
  setter is never tried, so whether the camera accepts it is only known with `--write`.
- `error : ... (status -4, CAMERA_STATUS_NOT_SUPPORTED)  <- not supported by this model`: the
  model lacks that function. The `_raw` functions catch such errors themselves and return them
  as `{'error': -4}` or keys such as `transfer_roi_error`.
- Other statuses: -12 (timeout) in a function that grabs usually means the camera is in a trigger
  mode or the network drops packets, not missing support; 32774, -45 or -13 mean the camera is
  held elsewhere.
- The exit status is 1 when any function raised an error, otherwise 0.

To judge support for a model, combine three sources: the Capability block of `gcam-mvsdk-py info`
(flags and ranges), the dry-run errors from getters, and, on a bench camera, `--write` errors from
setters. Then read the matching section of docs/CAPABILITIES.md for what each setting does.

## If it fails

| Message | Cause | Fix |
|---|---|---|
| `error: HuaTeng MVSDK library not found ...` | SDK missing for this interpreter | sdk-setup skill |
| `error: no cameras found; ...` or `no camera with serial or name 'X'` | Not discovered, or the name is not readable | camera-list; camera-discovery |
| `ModuleNotFoundError: No module named 'gcam_mvsdk_py'` | Wrong interpreter | Use `~/.gcam-mvsdk/py-venv/bin/python3` or install the package |
| `no function or section 'X'; see --list` (exit 2) | Typo | `--list` |
| Status 32774, -45 or -13 for every function | Camera held elsewhere | Stop the holder and retry |
| After `--write`, later functions time out when grabbing | `trigger_hardware` left hardware trigger mode in the working settings | Reopen or power-cycle the camera; run that function last or alone |

## Safety

- Run without `--write` unless the user asks for it. With `--write`, use a bench camera, never one a
  production pipeline uses, and get the user's consent: the setters change trigger mode, ROI,
  rotation, white balance, packet size and more in the working settings, until the camera is
  reopened with its saved group or power-cycled. Nothing is saved to a parameter group.
- Section 6 with `--write` drives digital outputs and the strobe; run it only when nothing is wired
  to the camera's outputs, or the user confirms that switching them is harmless.
- Do not copy the section 1 and 8 examples into scripts without changing their hard-coded values
  (name, address, group, paths).
- When changing `examples/capabilities.py` itself: add new functions to `SECTIONS`, then run
  `python scripts/update_capabilities_doc.py` and `pytest tests/test_capabilities_examples.py`.
