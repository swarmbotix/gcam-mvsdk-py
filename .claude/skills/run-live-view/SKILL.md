---
name: run-live-view
description: Run examples/live_view.py to watch one HuaTeng camera live in an OpenCV window: install OpenCV with GUI support (examples/requirements.txt, the [view] extra, or install.bash --with-view), choose the interpreter (the installed ~/.gcam-mvsdk/py-venv/bin/python3 or your own python3), handle discovery permissions (setcap or sudo -E) and the display, read the frame-rate overlay, and fix common failures (no DISPLAY, headless OpenCV, 0 cameras, busy camera). Use when the user wants to see a camera image live, check focus or framing interactively, or asks why the live view does not start.
---

# Live view

`examples/live_view.py` opens one camera, sets Mono8 output, continuous capture and a fixed
exposure for that session, and shows the frames in a resizable OpenCV window with a frame-rate
overlay. It never saves settings.

## When to use

- Watch a camera live to aim it, focus the lens, or judge exposure interactively.
- Check that frames arrive continuously and at roughly the expected rate.

For a single saved frame, or on a machine without a display, use camera-grab instead.

## Prerequisites

1. **A repository clone.** The example is not part of the installed package; run it from the
   repository root.
2. **OpenCV with GUI support** (`opencv-python`, never next to `opencv-python-headless` in the same
   environment, because both provide the `cv2` module). One of:

   ```bash
   pip install -r examples/requirements.txt                              # your environment, from the repository root
   pip install "gcam-mvsdk-py[view] @ file:///path/to/gcam-mvsdk-py"     # your environment, any directory
   bash install.bash --with-view                                         # the installer's environment ~/.gcam-mvsdk/py-venv
   ```

3. **A display.** A desktop session, or `DISPLAY` set (`echo $DISPLAY` prints something like `:0`);
   over SSH use `ssh -X` or `ssh -Y`. In Docker, run `xhost +local:` on the host once and pass
   `DISPLAY` and `/tmp/.X11-unix` into the container.
4. **Permission to discover GigE cameras** for the interpreter you run:
   - `~/.gcam-mvsdk/py-venv/bin/python3` has `CAP_NET_RAW` if you accepted the `setcap` step of
     install.bash (`gcam-mvsdk-py doctor` reports it).
   - Your own environment: either run with `sudo -E` (below), or grant the capability to that
     environment's interpreter, only if it was created with `python3 -m venv --copies` so that
     `bin/python3` is a real file and not a link to the system Python:

     ```bash
     test ! -L .venv/bin/python3 && sudo setcap cap_net_raw,cap_net_admin+ep .venv/bin/python3
     ```

5. **A free camera.** No publisher, viewer or other host may hold it.

## Steps

```bash
cd /path/to/gcam-mvsdk-py
~/.gcam-mvsdk/py-venv/bin/python3 examples/live_view.py sb01         # installed environment
python3 examples/live_view.py 056090423003                           # your own environment, by serial
~/.gcam-mvsdk/py-venv/bin/python3 examples/live_view.py              # camera omitted: exactly one camera must be connected
~/.gcam-mvsdk/py-venv/bin/python3 examples/live_view.py sb01 --exposure-us 2000 --mtu 9000 --window "sb01 bench"
sudo -E "$(command -v python3)" examples/live_view.py sb01            # without the capability
```

Options: `--exposure-us` (default 5000, manual exposure for this session), `--mtu` (largest GigE
packet size in bytes, for example 1500, or 9000 with jumbo frames), `--window` (window title,
default `gcam-mvsdk-py live view`). With `sudo`, give the interpreter's full path, because `sudo`
resets `PATH`; if the window cannot open as root, allow it with `xhost +SI:localuser:root` and
revoke it afterwards with `xhost -SI:localuser:root`.

**Quit** with `q` or Esc in the window, by closing the window, or with Ctrl+C in the terminal (exit
status 130). The camera is closed in every case.

## Reading the output

- The window shows the camera image in grey (Mono8, also on colour cameras).
- The white text at the top left, for example `measured 29.8 fps  cap 30 Hz`, gives the rate at
  which `grab` returned frames over the last second on this host, then the camera's configured
  frame-rate cap, read once at start (`cap none` when uncapped). The measured rate drops below the
  cap when frames time out, when the host is slow, or when the exposure is long (at most
  1,000,000 divided by the exposure in microseconds).
- `no frame within 1000 ms; waiting` on the terminal means one grab timed out; the view keeps
  trying.

## If it fails

| Message | Cause | Fix |
|---|---|---|
| `OpenCV with GUI support is required: pip install 'gcam-mvsdk-py[view]'` | No `cv2` in this interpreter | Install the view extra (Prerequisites 2) into the interpreter you run |
| `cv2.error: ... The function is not implemented. Rebuild the library with Windows, GTK+ 2.x or Cocoa support ...` in `namedWindow` | Headless OpenCV is installed (from the `opencv` extra or `--with-opencv`) | `python3 -m pip uninstall -y opencv-python-headless opencv-python && python3 -m pip install -r examples/requirements.txt`; for the installer environment use `~/.gcam-mvsdk/py-venv/bin/python3 -m pip uninstall -y opencv-python-headless opencv-python` and then `bash install.bash --with-view` |
| `qt.qpa.xcb: could not connect to display`, `cannot open display` | No display or `DISPLAY` unset | Run in a desktop session, `ssh -X`, or set `DISPLAY`; for root see `xhost` above |
| `0 cameras found; name one. See: gcam-mvsdk-py list` (exit 2) | Nothing discovered | camera-discovery skill (often missing permission for this interpreter) |
| `2 cameras found; name one. ...` (exit 2) | Camera omitted with several connected | Pass the user-set name or serial number |
| `error: no camera with serial or name 'X'. Available: ...` | Typo, or the camera is held elsewhere and its name could not be read | Check `gcam-mvsdk-py list`; select by serial number |
| `error: CameraInit failed: ... (status -45 ...)`, status 32774 or -13 | Another program or host holds the camera | Stop the holder (`docker ps`, other viewers), retry |
| `error: HuaTeng MVSDK library not found ...` | SDK missing for this interpreter | sdk-setup skill |
| Repeated `no frame within 1000 ms; waiting` | Packet size above the NIC MTU, rp_filter, firewall, or exposure over 1 s | Try `--mtu 1500`, or enable jumbo frames and use `--mtu 9000`; `gcam-mvsdk-py doctor`; shorter `--exposure-us` |
| Low frame rate | Long exposure, slow frame-speed tier, or small socket buffers | Shorter `--exposure-us`; camera-configure; README "Known issues" for `net.core.rmem_max` |

## Safety

- The live view holds the camera exclusively while it runs; close it before starting a publisher.
- `sudo -E` runs the whole example as root; prefer the capability on the installed interpreter.
  Never apply `setcap` to a system interpreter or to a `bin/python3` that is a symbolic link.
- `xhost +local:` and `xhost +SI:localuser:root` widen access to your display; revoke them when done.
