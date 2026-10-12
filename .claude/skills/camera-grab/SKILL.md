---
name: camera-grab
description: Save frames from a HuaTeng camera as PNG files with gcam-mvsdk-py grab (-n, -o, --exposure-us, --timeout-ms, --format), check the exposure of the result, fix timeouts (status -12, packet size versus NIC MTU), and use it as the smoke test after installation or network changes. Use when the user asks to capture, grab, save or look at a frame, to check that a camera delivers images, or to verify a setup end to end.
---

# Grab frames to PNG

`gcam-mvsdk-py grab` opens one camera, switches it to continuous capture, and writes the requested
number of frames as PNG files. It changes only the working settings of that session (output
format, trigger mode, and exposure if `--exposure-us` is given) and never saves them.

## When to use

- Capture one or a few frames from a camera, for example to check focus, framing or exposure.
- Smoke test after `install.bash`, after `setip`, after network changes, or after configuring.
- Measure throughput roughly (`-n 200` and the wall-clock time).

## Prerequisites

- The camera is listed (`gcam-mvsdk-py list`) and not held by another program; grab opens it.
- Raw-socket permission for GigE discovery, as for `list`.
- Disk space: one full-resolution PNG is up to a few MB.

## Steps

Options, as listed by `gcam-mvsdk-py grab --help`:

| Option | Default | Effect |
|---|---|---|
| `NAME_OR_SN` | required | User-set name or serial number |
| `-n`, `--count COUNT` | 1 | Number of frames to save |
| `-o`, `--output-dir DIR` | `.` | Output directory, created if missing |
| `--timeout-ms TIMEOUT_MS` | 2000 | Wait per frame |
| `--exposure-us EXPOSURE_US` | camera's current value | Manual exposure in microseconds (turns auto exposure off for the session) |
| `--format {auto,mono8,bgr8,rgb8}` | `auto` | ISP output format: mono8 for mono sensors, otherwise bgr8 |

There is no packet-size or MTU option; see "If it fails".

```bash
gcam-mvsdk-py grab sb01                                   # one frame into the current directory
gcam-mvsdk-py grab sb01 -n 10 -o /tmp/sb01-check          # ten frames into a fresh directory
gcam-mvsdk-py grab sb01 -n 3 -o /tmp/sb01-exp --exposure-us 2000
gcam-mvsdk-py grab 056090423003 --format mono8 --timeout-ms 5000
```

Smoke test after setup:

```bash
gcam-mvsdk-py doctor && gcam-mvsdk-py list && gcam-mvsdk-py grab <cam> -n 3 -o /tmp/<cam>-smoke
```

Three PNG files and no error mean that the SDK, discovery, opening and streaming all work.

**Check the exposure.** Look at the image (Claude Code can open a PNG with its Read tool; a user can
run `xdg-open <file>`), and measure it numerically in one session:

```bash
~/.gcam-mvsdk/py-venv/bin/python3 - <<'PY'
import gcam_mvsdk_py

sdk = gcam_mvsdk_py.load()
with sdk.open("sb01") as cam:
    cam.output_format = gcam_mvsdk_py.Mono8
    cam.trigger_mode = gcam_mvsdk_py.TRIGGER_CONTINUOUS
    cam.play()
    with cam.grab(timeout_ms=2000) as frame:
        img = frame.to_numpy()
print("mean %.1f  min %d  max %d  saturated %.2f %%" % (img.mean(), img.min(), img.max(), 100.0 * (img == 255).mean()))
PY
```

As a rule of thumb for 8-bit images: more than about 1 % of pixels at 255 means overexposed
(shorter exposure or less gain); a mean below about 30 means underexposed. Try values with
`--exposure-us`, then keep the chosen value with camera-configure.

## Reading the output

One line per saved frame:

```
/tmp/sb01-check/sb01_056090423003_0000.png  1024x1280 uint8  ts=123456789  [opencv]
```

- File name: `<user-set name>_<serial>_<NNNN>.png`, or `<serial>_<NNNN>.png` when the camera has no
  name; characters other than letters, digits, `.`, `_` and `-` become `_`. Numbering restarts at
  0000 on every run, so earlier files with the same names are overwritten; use a fresh `-o`
  directory per run.
- Shape: `height x width` for Mono8 (a single-channel 8-bit grey PNG), `height x width x 3` for
  colour formats (written with the correct channel order).
- `ts`: the camera's frame timestamp.
- `[opencv]` or `[builtin]`: the PNG writer (OpenCV when installed, otherwise the package's own).

## If it fails

| Message | Cause | Fix |
|---|---|---|
| `no frame within 2000 ms, 5 times in a row. Check packet size/MTU, firewall, and rp_filter` (exit 1); single timeouts (status -12) are retried silently | GigE packets larger than the NIC MTU (most common), rp_filter, firewall, or an exposure longer than the timeout | Compare `ip link show <nic>` (mtu) with `Packet sizes ... (current index N)` in `gcam-mvsdk-py info <cam>`; raise the NIC MTU (below) or lower the camera's packet size; `gcam-mvsdk-py doctor`; raise `--timeout-ms` for long exposures |
| Status 32774, -45, -18 or -13 when opening | Another program or host holds the camera | Stop the holder (`docker ps`, viewers, other hosts), retry, restart it afterwards |
| `no camera with serial or name 'X'` | Typo or camera not discovered | `gcam-mvsdk-py list`; camera-discovery if absent |
| `HuaTeng MVSDK library not found` (exit 3) | SDK missing | sdk-setup skill |
| Images all black or all white | Exposure far off, lens cap, or aperture | `--exposure-us`, then camera-configure |

**MTU fix.** Either enable jumbo frames on the camera NIC (the NIC and any switch must support
them):

```bash
sudo ip link set dev <nic> mtu 9000                                   # until reboot
sudo nmcli con mod "<connection name>" 802-3-ethernet.mtu 9000 && sudo nmcli con up "<connection name>"   # persistent
```

or give the camera a packet size that fits a 1500-byte MTU: `cam.gige_packet_size = 1500` from
Python, saved to the parameter group that loads at open (camera-configure), because `grab` opens a
new session that reloads the saved settings. For live viewing only, `examples/live_view.py --mtu 1500`
sets it for that session.

## Safety

- `grab` takes the camera exclusively while it runs; a publisher cannot start meanwhile. Do not stop
  a production publisher to grab without the owner's consent, and restart it afterwards.
- `grab` never saves settings, but large `-n` values fill the disk quickly at full resolution.
