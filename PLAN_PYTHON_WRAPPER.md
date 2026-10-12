# Plan: Python wrapper for the HuaTeng MVSDK (`gcam-mvsdk-py`)

Goal: a user types `pip install gcam-mvsdk-py`, then `gcam-mvsdk-py setup`, then `gcam-mvsdk-py list`, and sees every
HuaTeng GigE / USB camera on the LAN. In code, `import gcam_mvsdk_py` gives enumerate, rename, set IP, set
exposure, and frame grabbing as numpy arrays, on Linux and Windows, on every CPU architecture the
vendor supports.

This document is the Python counterpart of `PLAN_RUST_WRAPPER.md` in the `gcam-mvsdk-rs` repository. The SDK facts (API surface,
platforms, dependencies, sizes, license, privileges) are recorded there in section 1 and are not
repeated here; only the points that change the Python design are restated. The two packages share
the same downloader behaviour and the same `~/.gcam-mvsdk` on-disk layout, so one download serves both.

---

## 1. Why Python is the easier case

- The vendor already ships a complete ctypes wrapper, `demo/python_demo/mvsdk.py`, which loads the
  library at runtime with `cdll.LoadLibrary("libMVSDK.so")` on Linux and `windll.MVCAMSDK` or
  `windll.MVCAMSDK_X64` on Windows. Runtime loading is therefore the native mode, not a design
  choice to defend.
- The existing scripts in `camconfig/` (`list_cameras.py`, `nameit.py`, `camera_info.py`,
  `live_stream.py`, `aruco_detect.py`) already `import mvsdk`. They port to the package with
  minimal changes.
- A pure-Python package needs no compiled extension, so a single `py3-none-any` wheel covers every
  OS and architecture. PyPI never receives a vendor binary.

---

## 2. Design decisions

### 2.1 Never ship vendor binaries or headers

Same reasons as the Rust plan: the vendor notice in `readme-中文.pdf` forbids redistribution without
authorization, and the libraries are 17 to 23 MB each. The wheel contains Python source only, under
MIT. The user obtains the SDK from HuaTeng, through `gcam-mvsdk-py setup` or by hand.

### 2.2 Runtime loading through ctypes

`gcam_mvsdk_py._loader.find_library()` searches, in order:

1. `$GCAM_MVSDK_DIR/lib/<arch>` and `$GCAM_MVSDK_DIR/lib`
2. `./vendor/<version>/lib/<arch>` (developer checkout, populated by `scripts/fetch-sdk.sh`)
3. `~/.gcam-mvsdk/<version>/lib/<arch>` (populated by `gcam-mvsdk-py setup`)
4. The system loader path (`/lib`, `/usr/lib`, or `PATH` on Windows)

`<arch>` is derived from `platform.machine()`: `x86_64` to `x64`, `aarch64` to `arm64`,
`armv7l` to `arm` (hard float assumed; `GCAM_MVSDK_ARCH=arm_softfp` overrides), `i686` to `x86`.
On Windows, `platform.architecture()` selects `MVCAMSDK.dll` or `MVCAMSDK_X64.dll`, and the
calling convention is `WINFUNCTYPE` instead of `CFUNCTYPE`, exactly as the vendor wrapper does.

If nothing is found, `gcam_mvsdk_py.load()` raises `SdkNotFound` with the list of paths searched and the
instruction to run `gcam-mvsdk-py setup` or set `GCAM_MVSDK_DIR`.

### 2.3 Hand-declared signatures, not a copy of the vendor file

`gcam_mvsdk_py/_ffi.py` declares `argtypes` and `restype` for each wrapped function and defines the ctypes
`Structure` subclasses for `tSdkCameraDevInfo`, `tSdkFrameHead`, and the parts of
`tSdkCameraCapbility` that are read. It is written from the public interface, not copied from
`mvsdk.py`, so the package can carry an MIT license without question. Field order and sizes are
asserted in tests against values recorded from the C header.

### 2.4 The downloader is a CLI subcommand

`gcam-mvsdk-py setup` downloads the vendor tarball to `~/.gcam-mvsdk/<version>/`, verifies a SHA-256 stored in
the package, and extracts it. `gcam-mvsdk-py setup --from ./linuxSDK_V2.1.0.49.tar.gz` installs from a
tarball the user downloaded manually when the vendor URL cannot be fetched unattended. On Windows it
extracts the DLL, import library, and headers from the vendor zip and prints that the GigE filter
driver must be installed once by the vendor installer.

Whichever package ships first (Rust or Python) defines the checksum table and layout; the other reuses
them. A user who already ran `gcam-mvsdk-rs setup` needs no `gcam-mvsdk-py setup`, and vice versa.

---

### 2.5 Naming

One name per language, without variation. Python: repository `gcam-mvsdk-py`, PyPI package
`gcam-mvsdk-py`, console script `gcam-mvsdk-py`, import `gcam_mvsdk_py` (the hyphen is not legal in an
import name, so this is the only forced change). Rust: `gcam-mvsdk-rs` for repository, crate, and
binary. Shared, language-neutral: `~/.gcam-mvsdk/<version>/lib/<arch>/`, `GCAM_MVSDK_DIR`,
`GCAM_MVSDK_ARCH`, `GCAM_MVSDK_HW_TEST`. Full table and availability check in section 2.5 of
`PLAN_RUST_WRAPPER.md` in the `gcam-mvsdk-rs` repository.

---

### 2.6 Where the SDK comes from

Vendor download center: `http://huatengvision.com/download/1/`. Files are served directly, without
login or cookies, over plain HTTP, so `setup` can fetch them with `urllib` and must verify SHA-256.
Linux SDK direct URL, verified 2026-10-12, 57,978,497 bytes, SHA-256
`9624d193a908d94a9850400346cf1ab8095437a040e381b2fd39029b0183dd8a`:

```
http://huatengvision.com/attachment/down/13/linuxSDK_V2.1.0.49%28202511141513%29.tar.gz
```

Windows SDK is a `.rar` wrapping an installer (`attachment/down/24/...Setup(2.1.10.195_20260616).rar`,
128 MB); the installer must be run by the user because it also installs the GigE filter driver.
macOS packages (Intel and Apple Silicon) and GenTL producers exist on the same page; out of scope for
the first release. The full catalogue, URL mechanics, attachment-id churn, and the team's Dropbox mirror
are documented in section 1.7 of `PLAN_RUST_WRAPPER.md` in the `gcam-mvsdk-rs` repository. The (version, URL, size, SHA-256) table is
shared with the Rust package so that both `setup` commands fetch identical files.

---

## 3. Package layout

```
gcam-mvsdk-py/                          public GitHub + PyPI, MIT
├── pyproject.toml                 pure Python, dependencies: numpy; optional extras: opencv, click
├── sdk-manifest.toml              byte-identical copy of the Rust repo's manifest (section 3.1)
├── scripts/fetch-sdk.sh           python -m gcam_mvsdk_py setup --dest vendor/
├── .gitignore                     vendor/, archives, *.so, *.dll, *.dylib, vendor headers
├── vendor/                        NOT committed; populated by fetch-sdk.sh
├── src/gcam_mvsdk_py/
│   ├── __init__.py                load(), enumerate(), Camera, Frame, errors
│   ├── _loader.py                 search path, arch mapping, ctypes CDLL / WinDLL open
│   ├── _ffi.py                    Structure definitions, argtypes/restype, status code table
│   ├── _errors.py                 MvError(status) with message from CameraGetErrorString
│   ├── api.py                     safe layer (section 4)
│   ├── setup_cmd.py               downloader: fetch, checksum, extract, --from
│   └── cli.py                     `gcam-mvsdk-py` entry point: setup | list | rename | setip | info | grab | doctor
└── tests/
    ├── test_struct_sizes.py       ctypes.sizeof against recorded C values
    ├── test_loader.py             search path with a fake ~/.gcam-mvsdk
    └── hw/                        hardware tests, skipped unless GCAM_MVSDK_HW_TEST=1
```

---

### 3.1 How the repository manages the vendor SDK

Same rules as the Rust repository (section 3.5 of `PLAN_RUST_WRAPPER.md` in the `gcam-mvsdk-rs` repository), restated for Python:

- `.gitignore` excludes `vendor/`, archives, `*.so`, `*.dll`, `*.dylib`, and the vendor headers. A CI
  step fails if `git ls-files` contains any of those extensions.
- `sdk-manifest.toml` is committed, byte-identical to the Rust copy: `version`, `os`, `url`, `size`,
  `sha256`, `layout` per vendor release. `setup_cmd.py` reads it with `tomllib` (3.11+) or `tomli`.
- `gcam_mvsdk_py/setup_cmd.py` is the single downloader, reached as `gcam-mvsdk-py setup` (destination
  `~/.gcam-mvsdk/<version>/`) and as `scripts/fetch-sdk.sh`, which is `python -m gcam_mvsdk_py setup
  --dest vendor/` for people working in the repository. Uses only the standard library: `urllib.request`
  with a `HEAD` check of `Content-Length`, `hashlib.sha256`, `tarfile`, `zipfile`. `.rar` (Windows) needs
  an external `7z`; if absent, `setup` keeps the verified archive and prints the manual step.
- `setup` writes `manifest.json` (`version`, `source_url`, `sha256`, `installed_at`) next to the extracted
  files; `doctor` reads it. `--from <file>` runs the same verify-and-extract on a local archive.
- Nothing in `pip install`, `python -m build`, or the unit tests touches `vendor/`. The wheel is pure
  Python and builds on any machine with no SDK present.

Repository bootstrap for a developer:

```bash
git clone https://github.com/swarmbotix/gcam-mvsdk-py && cd gcam-mvsdk-py
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # works immediately, no SDK needed
./scripts/fetch-sdk.sh             # download + sha256 + extract into vendor/
gcam-mvsdk-py list                 # loader finds vendor/<ver>/lib/x64/libMVSDK.so
GCAM_MVSDK_HW_TEST=1 pytest        # hardware tests against the cameras on the bench
```

### 3.2 Building the wheel and using it from this machine

The wheel contains no vendor bytes, so building it locally and publishing it to PyPI are legally identical.
Until the API is stable, consumers use it without any registry.

Build once:

```bash
cd /mnt/A4CC6455CC6423B0/Github/vision_workspace/drivers/gcam-mvsdk-py
pip install build
python -m build                    # dist/gcam_mvsdk_py-0.1.0-py3-none-any.whl  and  .tar.gz
```

`py3-none-any` means one wheel for Linux, Windows, and macOS on every architecture; the architecture
choice happens at runtime when the loader picks `lib/<arch>/`.

Consume it from another project on this computer, any of:

```bash
pip install -e /mnt/A4CC6455CC6423B0/Github/vision_workspace/drivers/gcam-mvsdk-py                       # editable: edits visible without reinstall
pip install /mnt/A4CC6455CC6423B0/Github/vision_workspace/drivers/gcam-mvsdk-py                          # normal install from the source tree
pip install /mnt/A4CC6455CC6423B0/Github/vision_workspace/drivers/gcam-mvsdk-py/dist/gcam_mvsdk_py-0.1.0-py3-none-any.whl
```

In a consumer's `pyproject.toml` or `requirements.txt`:

```
gcam-mvsdk-py @ file:///mnt/A4CC6455CC6423B0/Github/vision_workspace/drivers/gcam-mvsdk-py
gcam-mvsdk-py @ git+https://github.com/swarmbotix/gcam-mvsdk-py@v0.1.0
```

Consume it from another machine without a registry:

```bash
pip install git+https://github.com/swarmbotix/gcam-mvsdk-py@v0.1.0
# or copy the .whl file and: pip install gcam_mvsdk_py-0.1.0-py3-none-any.whl
```

Later, once published, this becomes `pip install gcam-mvsdk-py`. The package contents are identical in all
cases.

For this repository's Docker image, the Dockerfile replaces `COPY ... mvsdk.py /opt/mvsdk/` and
`PYTHONPATH=/opt/mvsdk` with `pip install /workspace/gcam-mvsdk-py` (bind-mounted or copied) plus either
`gcam-mvsdk-py setup` at build time or `GCAM_MVSDK_DIR` pointing at a mounted SDK directory.

Every consumer still needs the SDK on its machine: `gcam-mvsdk-py setup` once, or `GCAM_MVSDK_DIR`.

---

## 4. Safe API

```python
import gcam_mvsdk_py

sdk = gcam_mvsdk_py.load()                       # finds and opens libMVSDK.so, calls CameraSdkInit once
for dev in sdk.enumerate():              # list[DeviceInfo]
    print(dev.serial, dev.model, dev.port_type, dev.gige_ip(), dev.gige_mac())

sdk.gige_set_ip(dev, "192.168.1.100", "255.255.255.0", "192.168.1.1", persistent=True)

with sdk.open(dev) as cam:               # CameraInit; CameraUnInit on exit
    print(cam.user_name)                 # CameraGetFriendlyName
    cam.user_name = "sb01"               # CameraSetFriendlyName, persisted in camera NVM
    cam.exposure_us = 5000
    cam.frame_rate_hz = 0                # 0 = uncapped
    cam.output_format = gcam_mvsdk_py.Mono8
    cam.play()
    with cam.grab(timeout_ms=1000) as frame:   # CameraGetImageBuffer; release on exit
        img = frame.to_numpy()           # copies into a (h, w) uint8 array
        view = frame.view()              # zero-copy view, valid only inside the with block
```

Details:

- `DeviceInfo` decodes `char` arrays as ASCII, falling back to GBK; never assumes UTF-8.
- `Camera` is a context manager; `__del__` also calls `CameraUnInit` as a safety net.
- `Frame` wraps the raw pointer plus `tSdkFrameHead`. `to_numpy()` copies, so the result outlives
  the SDK buffer. `view()` returns `numpy.frombuffer` over the raw pointer and is documented as
  valid only until the `with` block exits. This is the one place where misuse can segfault, so the
  copying call is the default in examples.
- `MvError` carries the numeric status and the text from `CameraGetErrorString`.
- Callback mode: `cam.set_callback(fn)` wraps `fn` in `CFUNCTYPE` / `WINFUNCTYPE` and stores the
  wrapper on the `Camera` instance so the garbage collector cannot free it while the SDK still holds
  the pointer. Second iteration; polling `grab()` is sufficient for the config tools.
- ctypes releases the GIL during foreign calls, so a blocking `CameraGetImageBuffer` does not stall
  other Python threads.

Initial function subset, the same 25 as the Rust plan:

```
CameraSdkInit                 CameraEnumerateDevice          CameraInit
CameraUnInit                  CameraGetCapability            CameraGetFriendlyName
CameraSetFriendlyName         CameraGigeGetIp                CameraGigeSetIp
CameraGigeGetMac              CameraSetAeState               CameraSetExposureTime
CameraGetExposureTime         CameraSetFrameRate             CameraSetIspOutFormat
CameraSetTriggerMode          CameraPlay                     CameraPause
CameraGetImageBuffer          CameraReleaseImageBuffer       CameraImageProcess
CameraSetGigePacketSize       CameraGetErrorString           CameraSaveParameter
CameraLoadParameter
```

`sdk.raw` exposes the underlying `ctypes.CDLL` so any of the remaining functions can be called with
hand-supplied `argtypes` without waiting for a wrapper.

---

## 5. CLI

| Command | Replaces | Notes |
|---|---|---|
| `gcam-mvsdk-py setup [--from FILE] [--version V]` | `install.sh`, Dockerfile `COPY` lines | Downloads or extracts SDK into `~/.gcam-mvsdk/<ver>/` |
| `gcam-mvsdk-py list [--json]` | `camconfig/list_cameras.py` | User name, model, SN, camera IP/MAC, host NIC IP/MAC |
| `gcam-mvsdk-py rename <SN> <NAME>` | `camconfig/nameit.py` | Writes DeviceUserID to camera NVM |
| `gcam-mvsdk-py setip <MAC> <IP> <MASK> <GW>` | `GeConfigCmd set ...` | Works when the camera is on the wrong subnet |
| `gcam-mvsdk-py info <NAME or SN>` | `camconfig/camera_info.py` | Capability dump |
| `gcam-mvsdk-py grab <NAME or SN> [-n N] [-o DIR]` | `camconfig/live_stream.py` (headless part) | Saves PNG frames |
| `gcam-mvsdk-py doctor` | README troubleshooting | Firewall, `rp_filter`, NIC subnet, privileges, SDK presence |

The console script is `gcam-mvsdk-py`; the Rust CLI is `gcam-mvsdk-rs`. The names differ so that installing both never
shadows one with the other. Both read the same `~/.gcam-mvsdk` directory. The full naming convention
is recorded in section 2.5 of `PLAN_RUST_WRAPPER.md` in the `gcam-mvsdk-rs` repository.

---

## 6. Privileges

GigE discovery needs raw sockets. Options, in order of preference:

1. `sudo setcap cap_net_raw,cap_net_admin+ep` on a dedicated virtual environment's Python binary
   (never on the system interpreter). `gcam-mvsdk-py doctor` prints the exact command for the running
   interpreter.
2. `sudo -E python -m gcam_mvsdk_py list`, preserving `GCAM_MVSDK_DIR` and `HOME` so the search path still finds
   `~/.gcam-mvsdk`.
3. Inside Docker, `network_mode: host` and `privileged: true`, as today.

USB cameras need the two udev rules from the SDK; `gcam-mvsdk-py setup --udev` offers to install them.

Windows needs the vendor installer once for the filter driver; the DLL alone is not enough.

---

## 7. Relationship to this repository

- `camconfig/*.py` becomes a thin layer over `gcam-mvsdk-py`, or is deleted in favour of the CLI:
  `list_cameras.py` is `gcam-mvsdk-py list`, `nameit.py` is `gcam-mvsdk-py rename`, `camera_info.py` is
  `gcam-mvsdk-py info`. `live_stream.py` and `aruco_detect.py` remain as examples under an `opencv` extra.
- The Dockerfile no longer needs `COPY ... mvsdk.py /opt/mvsdk/` or `PYTHONPATH=/opt/mvsdk`;
  `pip install gcam-mvsdk-py` plus a bind mount or `GCAM_MVSDK_DIR` replaces it.
- The frame publisher stays in Rust (`cam-gige-pub` in the Rust plan): iceoryx2 zero copy, no GIL,
  a single binary to grant `CAP_NET_RAW`. The Python package is for configuration, scripting,
  notebooks, and quick checks, which is the role `camconfig/` plays today.

---

## 8. Testing

- Unit, no hardware: struct sizes, status code table, loader search path, arch mapping, CLI argument
  parsing. Runs on every platform in CI.
- Hardware, bench machine: `gcam-mvsdk-py list` finds the four `sb0x` cameras; rename round trip; `grab`
  returns a Mono8 array with the expected shape; `view()` and `to_numpy()` agree byte for byte.
  Gated behind `GCAM_MVSDK_HW_TEST=1`.
- Windows: unit tests in CI; hardware tests when a Windows machine with the vendor driver is
  available.

---

## 9. Work items and estimate

| # | Item | Estimate |
|---|---|---|
| 1 | `_loader.py`, `_ffi.py`, `_errors.py`, struct size tests | 0.5 day |
| 2 | `api.py`: `load`, `enumerate`, `DeviceInfo`, `Camera`, `Frame` | 0.5 day |
| 3 | `cli.py`: `list`, `rename`, `setip`, `info`, `grab`, `doctor` | 0.25 day |
| 4 | `setup_cmd.py`: download, checksum, `--from`, `--udev`, Windows extraction | 0.5 day |
| 5 | Port `camconfig/` scripts, update Dockerfile and README | 0.25 day |
| 6 | `sdk-manifest.toml`, `.gitignore`, CI binary check, `scripts/fetch-sdk.sh`, `python -m build` | 0.25 day |
| 7 | Callback mode, broader coverage | incremental |

Total for a usable release: about 2.25 days, less if the manifest and downloader logic are ported from Rust.

---

## 10. Open questions

Shared with the Rust plan: Windows arm64 availability and whether to ask HuaTeng for redistribution
permission. The download URL question is resolved (section 2.6). Python specific:

1. Minimum Python version. 3.9 is the safe floor for the arm32 boards that the SDK supports; 3.10
   if match statements and modern typing are wanted.
2. Whether to publish to PyPI immediately or install from GitHub first
   (`pip install git+https://github.com/swarmbotix/gcam-mvsdk-py`). Both work with the same package; PyPI
   only adds discoverability.

---

## 11. Local development without installing the SDK

```bash
export GCAM_MVSDK_DIR="$HOME/Dropbox/Projects/huateng_gige_camera/linux/linuxSDK_V2.1.0.49(202511141513)"
pip install -e .
gcam-mvsdk-py list
```

---

## Status (2026-10-12)

Implemented in this repository, version 0.1.0, committed to `main`:

- Packaging: `pyproject.toml` (hatchling, src layout, console script `gcam-mvsdk-py`, extras `opencv`
  and `dev`, version single-sourced from `pyproject.toml`), `sdk-manifest.toml` (byte-identical to the
  Rust copy), `.gitignore`, `LICENSE` (MIT), `README.md` (rewritten for end users), `CLAUDE.md`,
  `IMPLEMENTATION_NOTES.md`, `scripts/fetch-sdk.sh`, `scripts/check-no-vendor-files.sh`, and a CI
  workflow (tests on Linux and Windows, shellcheck, artifact check). `python -m build` produces
  `gcam_mvsdk_py-0.1.0-py3-none-any.whl` with no vendor bytes.
- `_loader.py` (search order of section 2.2, plus `GCAM_MVSDK_HOME` and the installer's venv marker for
  the SDK home), `_ffi.py` (structures with sizes asserted against gcc, 153 function signatures, status
  table, `CFUNCTYPE`/`WINFUNCTYPE` callback type), `_errors.py`, `api.py` (section 4 API including
  `set_callback`), `setup_cmd.py` (download, SHA-256, extract, `--from`, `--dest`, `--udev`, Windows
  `.rar` branch), `cli.py` (setup, list, rename, setip, info, grab, doctor).
- `install.bash`: one-command Linux installer (venv with `--copies`, CLI link in `~/.local/bin`, SDK
  download or `--from`, grouped `sudo` for `setcap` and udev rules, `doctor` and `list`, `--uninstall`,
  `--dev`, `--wheel`, `--with-opencv`, `--no-sudo`). Tested end to end in a scratch HOME without sudo.
- `.claude/skills/`: sdk-setup, camera-discovery, add-sdk-function, release, hardware-test, with helper
  scripts.
- `docs/CAPABILITIES.md`: every setting the SDK exposes (94 items in ten sections, same order as the Rust
  copy; 64 wrapped, 30 reachable raw through `cam.call()`/`cam.query()`), with examples generated from
  `examples/capabilities.py`. Also `examples/live_view.py` with the `view` extra.
- Tests: 315 unit tests pass on Python 3.9 and 3.13 without the SDK; hardware tests are gated by
  `GCAM_MVSDK_HW_TEST=1` and have not been run against cameras yet.
- Deviation: `CameraSetGigePacketSize` does not exist in SDK 2.1.0.49; packet size uses
  `CameraSetTransPackLen`. Other choices are recorded in `IMPLEMENTATION_NOTES.md`.
- Open: hardware validation on the bench host (including every setting in `docs/CAPABILITIES.md`), the
  privileged installer path (`setcap`, udev, apt) on a
  machine where `sudo` can be used, automatic location of the DLL after the Windows installer, a recorded
  SHA-256 for the Windows release, `GCAM_MVSDK_HOME` support in `gcam-mvsdk-rs`, porting `camconfig/` and
  the Dockerfile.
