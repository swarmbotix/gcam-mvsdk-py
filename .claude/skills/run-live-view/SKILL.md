---
name: run-live-view
description: Run examples/live_view.py to watch one HuaTeng camera live in an OpenCV window and record PNG images from it (r starts, c stops; rate and duration in examples/record.yaml; output under ~/.gcam-mvsdk/data): install OpenCV with GUI support and PyYAML (examples/requirements.txt, the [view] extra, or install.bash --with-view), choose the interpreter (the installed ~/.gcam-mvsdk/py-venv/bin/python3 or your own python3), handle the display, read the frame-rate overlay, and fix common failures (no DISPLAY, headless OpenCV, 0 cameras, busy camera). Use when the user wants to see a camera image live, check focus or framing interactively, save a short image sequence from the live view, or asks why the live view does not start.
---

# Live view

`examples/live_view.py` opens one camera, sets Mono8 output, continuous capture and a fixed
exposure for that session, and shows the frames in a resizable OpenCV window with a frame-rate
overlay. Pressing `r` records a PNG image sequence (see Recording). It never saves settings.

## When to use

- Watch a camera live to aim it, focus the lens, or judge exposure interactively.
- Check that frames arrive continuously and at roughly the expected rate.
- Record a short image sequence (default 5 images per second for 30 s) while watching.

For a single saved frame, or on a machine without a display, use camera-grab instead.

## Prerequisites

1. **A repository clone.** The example is not part of the installed package; run it from the
   repository root.
2. **OpenCV with GUI support and PyYAML** (`opencv-python`, never next to `opencv-python-headless`
   in the same environment, because both provide the `cv2` module). One of:

   ```bash
   pip install -r examples/requirements.txt                              # your environment, from the repository root
   pip install "gcam-mvsdk-py[view] @ file:///path/to/gcam-mvsdk-py"     # your environment, any directory
   bash install.bash --with-view                                         # the installer's environment ~/.gcam-mvsdk/py-venv
   ```

3. **A display.** A desktop session, or `DISPLAY` set (`echo $DISPLAY` prints something like `:0`);
   over SSH use `ssh -X` or `ssh -Y`. In Docker, run `xhost +local:` on the host once and pass
   `DISPLAY` and `/tmp/.X11-unix` into the container.
4. **A free camera.** No publisher, viewer or other host may hold it. No root or capability is
   needed to discover GigE cameras; run the example as your own user.

## Steps

```bash
cd /path/to/gcam-mvsdk-py
~/.gcam-mvsdk/py-venv/bin/python3 examples/live_view.py sb01         # installed environment
python3 examples/live_view.py 056090423003                           # your own environment, by serial
~/.gcam-mvsdk/py-venv/bin/python3 examples/live_view.py              # camera omitted: exactly one camera must be connected
~/.gcam-mvsdk/py-venv/bin/python3 examples/live_view.py sb01 --exposure-us 2000 --mtu 9000 --window "sb01 bench"
```

Options: `--exposure-us` (default 5000, manual exposure for this session), `--mtu` (largest GigE
packet size in bytes, for example 1500, or 9000 with jumbo frames), `--window` (window title,
default `gcam-mvsdk-py live view`), `--config FILE` (recording options, default
`examples/record.yaml`).

**Keys**: `r` (or `R`) starts a recording, `c` stops it before the duration is over. **Quit** with
`q` or Esc in the window, by closing the window, or with Ctrl+C in the terminal (exit status 130).
The camera is closed in every case; a running recording is finished first.

## Recording

`examples/record.yaml` holds the options; edit it or pass another file with `--config`:

```yaml
duration_s: 30   # a recording stops after this many seconds
rate_hz: 5       # images saved per second; the camera keeps running at its own frame rate
# data_dir: ~/.gcam-mvsdk/data   # default: <sdk home>/data
```

Each recording creates `<data_dir>/<YYYYMMDD_HHMMSS>_<camera>/` (local time at the key press;
`<camera>` is the user-set name, else the serial) and writes `0.png`, `1.png`, ... there: the
Mono8 camera image without the overlay. One image is saved per `1/rate_hz` seconds, anchored to
the start, so a 90 fps camera at `rate_hz: 5` yields about 150 files in 30 s. Unknown keys or a
non-positive number in the file stop the program at startup (`error: .../record.yaml: ...`). A
missing file is reported and the defaults above are used.

Unit tests for the keys, the config file and the save schedule (no camera, display or OpenCV):
`pytest tests/test_live_view_example.py`.

## Reading the output

- The window shows the camera image in grey (Mono8, also on colour cameras).
- The white text at the top left, for example `measured 29.8 fps  cap 30 Hz`, gives the rate at
  which `grab` returned frames over the last second on this host, then the camera's configured
  frame-rate cap, read once at start (`cap none` when uncapped). The measured rate drops below the
  cap when frames time out, when the host is slow, or when the exposure is long (at most
  1,000,000 divided by the exposure in microseconds).
- `no frame within 1000 ms; waiting` on the terminal means one grab timed out; the view keeps
  trying.
- While recording, a second overlay line reads `REC 23 saved  4.6 s`. The terminal prints
  `recording to <dir>` when `r` is pressed and `recording stopped: N images in <dir>` when it ends
  (duration reached, `c`, or quit). At startup, `recording: 5 images/s for 30 s into <data_dir>`
  echoes the config file.

## If it fails

| Message | Cause | Fix |
|---|---|---|
| `OpenCV with GUI support is required: pip install 'gcam-mvsdk-py[view]'` | No `cv2` in this interpreter | Install the view extra (Prerequisites 2) into the interpreter you run |
| `cv2.error: ... The function is not implemented. Rebuild the library with Windows, GTK+ 2.x or Cocoa support ...` in `namedWindow` | Headless OpenCV is installed (from the `opencv` extra or `--with-opencv`) | `python3 -m pip uninstall -y opencv-python-headless opencv-python && python3 -m pip install -r examples/requirements.txt`; for the installer environment use `~/.gcam-mvsdk/py-venv/bin/python3 -m pip uninstall -y opencv-python-headless opencv-python` and then `bash install.bash --with-view` |
| `qt.qpa.xcb: could not connect to display`, `cannot open display` | No display or `DISPLAY` unset | Run in a desktop session, `ssh -X`, or set `DISPLAY` |
| `0 cameras found; name one. See: gcam-mvsdk-py list` (exit 2) | Nothing discovered | camera-discovery skill (rp_filter, firewall, subnet, cabling) |
| `2 cameras found; name one. ...` (exit 2) | Camera omitted with several connected | Pass the user-set name or serial number |
| `error: no camera with serial or name 'X'. Available: ...` | Typo, or the camera is held elsewhere and its name could not be read | Check `gcam-mvsdk-py list`; select by serial number |
| `error: CameraInit failed: ... (status -45 ...)`, status 32774 or -13 | Another program or host holds the camera | Stop the holder (`docker ps`, other viewers), retry |
| `error: HuaTeng MVSDK library not found ...` | SDK missing for this interpreter | sdk-setup skill |
| Repeated `no frame within 1000 ms; waiting` | Packet size above the NIC MTU, rp_filter, firewall, or exposure over 1 s | Try `--mtu 1500`, or enable jumbo frames and use `--mtu 9000`; `gcam-mvsdk-py doctor`; shorter `--exposure-us` |
| Low frame rate | Long exposure, slow frame-speed tier, or small socket buffers | Shorter `--exposure-us`; camera-configure; README "Known issues" for `net.core.rmem_max` |
| `ModuleNotFoundError: No module named 'yaml'` | PyYAML missing (older `view` installation) | Reinstall the view extra (Prerequisites 2) or `pip install pyyaml` into that interpreter |
| `error: .../record.yaml: unknown option(s) ...` or `rate_hz must be a positive number` | Bad config file | Only `duration_s`, `rate_hz` and `data_dir` are accepted; numbers must be positive |
| `error: [Errno 13] Permission denied: '.../data/...'` | `data_dir` not writable by this user | Set another `data_dir` in record.yaml |

## Safety

- The live view holds the camera exclusively while it runs; close it before starting a publisher.
- Recordings only add files under `data_dir`; nothing there is deleted or overwritten (every
  recording gets a new folder).
- `xhost +local:` widens access to your display; revoke it with `xhost -local:` when done.
