# Implementation notes

Choices made where `PLAN_PYTHON_WRAPPER.md` is silent, and the places where the
implementation deviates from it. Version 0.1.0. The second part of this file covers the
production installer and developer tooling added afterwards.

## Deviations from the plan

1. **`CameraSetGigePacketSize` does not exist** in SDK 2.1.0.49 (neither in
   `CameraApi.h` nor among the exported symbols of `libMVSDK.so`). The GigE
   packet size is selected by index into the capability's `pPackLenDesc` table
   with `CameraSetTransPackLen` / `CameraGetTransPackLen`, as the production C++
   publisher does. `Camera.gige_packet_index` exposes the raw index;
   `Camera.gige_packet_size = N` selects the largest advertised size that does
   not exceed N bytes. The 25-function subset is therefore the plan's list with
   `CameraSetTransPackLen` in place of `CameraSetGigePacketSize`.
2. **`Frame.view()` versus `Frame.to_numpy()`.** `view()` is a zero-copy view of
   the raw SDK buffer. `to_numpy()` runs the SDK ISP (`CameraImageProcess`) into
   a new 64-byte-aligned array in the camera's `output_format`, which is what
   makes `cam.output_format = Mono8` meaningful. `to_numpy(process=False)` is the
   raw copy. The hardware test asserts that `view()` and `to_numpy(process=False)`
   agree byte for byte; ISP output is not guaranteed to equal the raw bytes.
   On Windows the ISP output is bottom-up, so `to_numpy()` flips it.
3. **Windows checksum.** The manifest records an empty `sha256` for the Windows
   release, so `setup` cannot verify it. It prints the computed digest and
   requires `--allow-unverified`. The size must still match.
4. **Windows DLL discovery after the installer.** The vendor installer's default
   path is unconfirmed, so `setup` and `doctor` do not yet locate and record the
   installed DLL automatically. `setup` prints how to point the loader at it
   (`PATH`, `GCAM_MVSDK_DIR`, or copying it into `~/.gcam-mvsdk/<ver>/lib/x64`).
5. **`GCAM_MVSDK_DIR` itself** is searched as a third location after
   `$GCAM_MVSDK_DIR/lib/<arch>` and `$GCAM_MVSDK_DIR/lib`, so the variable can also
   name a directory that holds the library directly.

## Packaging

* Build backend: hatchling, src layout. The canonical `sdk-manifest.toml` stays at
  the repository root (byte-identical to the `gcam-mvsdk-rs` copy, checked by
  `tests/test_manifest.py`) and is force-included into the wheel as
  `gcam_mvsdk_py/sdk-manifest.toml`. A source checkout or editable install reads
  the root copy.
* Dependencies: `numpy>=1.20`; `tomli` on Python < 3.11. Extras: `opencv`
  (`opencv-python-headless`) and `dev` (`pytest`, `build`). The CLI uses argparse,
  so no click extra exists.
* Additional private modules not named in the plan: `_manifest.py` (manifest
  reader shared by loader and setup), `_doctor.py`, `_png.py`, and `__main__.py`
  for `python -m gcam_mvsdk_py`.
* `scripts/check-no-vendor-files.sh` and `.github/workflows/ci.yml` implement the
  plan's CI binary check; CI runs the unit tests on Linux, Windows, and macOS with
  Python 3.9 and 3.13.

## Loader

* Versions tried under `./vendor/` and `~/.gcam-mvsdk/`: the manifest's versions
  for the running OS plus any existing subdirectory containing `lib/`, newest
  first by numeric version order.
* System step: `LD_LIBRARY_PATH`, `/lib`, `/usr/lib`, `/usr/local/lib`, `/lib64`,
  `/usr/lib64`, the Debian multiarch directory for the architecture, then the
  dynamic loader by bare name (which honours `ld.so.cache`). On Windows `PATH` is
  scanned explicitly, because Python 3.8+ no longer searches it for DLLs, and
  `os.add_dll_directory` is called for the DLL's directory.
* A 32-bit interpreter on a 64-bit kernel maps to the 32-bit library (`x86` or
  `arm`), using the interpreter's pointer size.
* `SdkNotFound` lists every candidate file path with its origin.
* macOS library names (`libMVSDK.dylib`, `libmvsdk.dylib`) are guesses; the macOS
  SDK has not been inspected and macOS is out of scope for this release.

## Raw bindings (`_ffi.py`)

* Structures written from the public interface: all of `tSdkCameraDevInfo`,
  `tSdkFrameHead`, `tSdkCameraCapbility` (complete, including its sub-structures),
  `tSdkImageResolution`, `tSdkPackLength`, `tSdkFrameStatistic`, `tSdkFrameEvent`,
  and the small description records. Sizes and selected offsets were measured
  with `gcc -S` from the vendor headers for x86_64 and `-m32` and are asserted in
  `tests/test_struct_sizes.py` (`tSdkCameraCapbility` is 344 bytes on LP64 and
  256 on ILP32; the others are pointer-free).
* 63 functions are declared, beyond the 25 in the plan (version string,
  gain, gamma, trigger details, resolution, frame statistics, frame speed, GigE
  option, callback, and so on). All of them resolve in `libMVSDK.so` 2.1.0.49.
  Missing optional symbols are tolerated and reported in `Sdk.missing_functions`.
* Status messages in the table are this package's own English text; the SDK's
  message is fetched at runtime from `CameraGetErrorString` (`CameraSdkInit(1)`
  selects English).

## Safe API

* `load()` is a process-wide singleton: later calls return the first `Sdk`, even
  with a different path argument.
* `DeviceInfo.model` is `acFriendlyName`, matching the "Model" column of
  `camconfig/list_cameras.py`; `friendly_name` is the same value. The user-set
  name (DeviceUserID) is read and written through an open camera
  (`Camera.user_name`), because enumeration does not report it reliably.
* `Sdk.find(key)` and `sdk.open("name or SN")` match the serial number first, then
  the user-set name (opening each camera briefly; cameras held by another process
  are skipped), then the enumeration friendly name.
* Setting `Camera.exposure_us` switches auto exposure off first, as every vendor
  and workspace example does before setting an exposure.
* Name validation mirrors the SDK: at most 31 bytes, none of `\ / : * ? " < > |`.
* Strings are decoded as ASCII, then GBK, with replacement as a last resort, and
  encoded as ASCII or GBK.
* Exceptions: `GcamMvsdkError` (base), `MvError` (`status`, `name`, `message`,
  `function`), `MvTimeout` (also a `TimeoutError`), `SdkNotFound`,
  `DeviceNotFound` (also a `LookupError`), `FunctionUnavailable`.
* `Camera.close()` releases outstanding frames before `CameraUnInit`; `Frame` and
  `Camera` both have `__del__` safety nets (skipped at interpreter shutdown).
* Callback frames are released after the user function returns. Exceptions in
  the callback are printed, not propagated. Closing the camera from inside its
  own callback is not supported.

## `setup`

* Extracted subset: `include/`, `lib/`, `tools/GeConfigCmd/`, `88-mvusb.rules`,
  `99-mvusb.rules`. Regular files and directories only (the one symlink in the
  archive is outside the subset); members with absolute or `..` paths abort the
  install. Permissions are normalized to 0644, or 0755 for `lib/*.so` and
  `GeConfigCmd`, because the vendor archive marks every entry world-writable.
* Installation is atomic: extraction goes to a temporary sibling directory that
  is renamed to `<dest>/<version>` only after success. An existing directory that
  `setup` did not create is never replaced without `--force`.
* `--dest DIR` is the parent of `<version>/` (so `--dest ./vendor` yields
  `vendor/2.1.0.49/`), matching `scripts/fetch-sdk.sh`.
* Downloads go to `<dest>/.downloads/<file>.part`, are renamed after the size
  check, and are deleted after a Linux install unless `--keep-archive` is given.
  A cached archive of the right size is reused after re-hashing; one that fails
  verification is deleted and fetched again.
* `--from FILE` identifies the release by SHA-256, so `--version` is not needed.
  A file matching no recorded checksum requires `--version V --allow-unverified`.
* `manifest.json` carries the four required keys (`version`, `source_url`,
  `sha256`, `installed_at` in ISO 8601 UTC) plus `os`, `layout`, `installer`, and
  `files` (Windows: `state` and `installers`). `source_url` is a `file://` URI for
  `--from`.
* `--udev` stages the two rules with LF line endings (the vendor files use CRLF),
  shows the `sudo install` and `udevadm` commands, and runs them only after
  confirmation or `--yes`; without a terminal it only prints them. Note that the
  vendor's `88-mvusb.rules` in 2.1.0.49 appears truncated (its lines end in `A"`),
  so udev may warn about it; `99-mvusb.rules` carries the effective rule.

## CLI

* Extra options beyond the plan: global `--sdk PATH`, `list --no-open`,
  `info --json`, `grab --timeout-ms/--exposure-us/--format`, and the setup flags
  `--force`, `--yes`, `--keep-archive`, `--allow-unverified`, `--manifest`,
  `--quiet`.
* `list --json` keys: `index`, `user_name`, `open_error` (when the camera could not
  be opened), `serial`, `model`, `product`, `series`, `port_type`, `sensor_type`,
  `driver_version`, `instance`, and for GigE `camera_ip`, `camera_mask`,
  `camera_gateway`, `host_ip`, `host_mask`, `host_gateway`, `camera_mac`,
  `host_mac`.
* `setip` always stores a persistent address (`bPersistent = TRUE`); the API's
  `persistent=False` switches the camera to automatic addressing.
* `grab` sets continuous trigger mode, Mono8 for mono sensors or BGR8 otherwise,
  writes `<name>_<serial>_<NNNN>.png`, and gives up after five consecutive
  timeouts. PNG output uses OpenCV when importable, otherwise a built-in encoder
  (8/16-bit gray, RGB, RGBA; filter type 0; zlib level 6).
* Exit codes: 0 success, 1 error, 2 usage, 3 SDK not found.
* `doctor` checks the library location and `manifest.json`, loads the SDK and
  prints its version, checks root or `CapEff` bit 13 (`CAP_NET_RAW`), prints the
  `setcap` command for the running venv interpreter, warns when the interpreter is
  not a venv or when the venv's `python3` is a symlink to a shared interpreter
  (recommending `python -m venv --copies`), reads `rp_filter` per interface
  (effective value is the maximum of `all` and the interface), inspects ufw and
  firewalld, lists IPv4 interfaces with MTU (`ip -j -4 addr`, ioctl fallback), and
  compares each GigE camera's IP with the host NIC subnet the SDK reports.

## Testing

* 158 unit tests, none of which needs the SDK: struct sizes and offsets, status
  table, loader search order with a fake tree (monkeypatched `HOME` and cwd),
  manifest parsing and byte identity with the Rust copy, CLI parsing, the
  downloader against a local `http.server` with a synthetic archive, the PNG
  encoder, and the safe layer driven by an in-process fake of the C library.
* `tests/hw/` runs only with `GCAM_MVSDK_HW_TEST=1`; optional variables
  `GCAM_MVSDK_HW_EXPECT`, `GCAM_MVSDK_HW_CAMERA`, `GCAM_MVSDK_HW_RENAME_SN`. The
  rename round trip runs only when a serial number is given explicitly, because it
  writes camera memory.
* Verified locally on Python 3.9.25 and 3.13.9 (Linux x86_64).

## Production installer (`install.bash`)

* Steps, each announced with one `==>` line: OS check (`/etc/os-release`; macOS and
  Windows refused with a pointer to README), architecture mapping (`uname -m` to
  `lib/<arch>`, `GCAM_MVSDK_ARCH` honoured, unsupported machines refused), Python >= 3.9
  with `venv` and `ensurepip` (on Debian/Ubuntu it offers
  `sudo apt-get install -y python3-venv python3-pip`), venv at
  `$GCAM_MVSDK_HOME/py-venv` created with `--copies`, pip upgrade (a failure only warns, so
  offline installs continue), package install (source tree, newest `dist/` wheel with
  `--wheel`, or editable with `--dev`), symlink `~/.local/bin/gcam-mvsdk-py`, SDK via
  `gcam-mvsdk-py setup` (or `--from`), privileged setup, `doctor`, `list`, summary.
* Additions beyond the specification: `-y/--yes` (needed for unattended runs; never
  deletes the SDK), `PYTHON` (interpreter used to create the venv), and
  `GCAM_MVSDK_BIN_DIR` (link directory, default `~/.local/bin`).
* `GCAM_MVSDK_HOME` (default `~/.gcam-mvsdk`) is now honoured by the loader and by
  `setup`, and install.bash records it in `<venv>/gcam-mvsdk-py-home`, so the installed
  command finds the SDK later without the variable. Resolution order of the SDK home:
  `$GCAM_MVSDK_HOME`, the venv marker, `~/.gcam-mvsdk`. `gcam-mvsdk-rs` does not know
  `GCAM_MVSDK_HOME` yet; a non-default home is therefore not shared with the Rust tool
  until it adopts the same variable.
* Privileged step: the `setcap` target is the interpreter named in the console script
  (pip writes either a `#!` line or, for long paths, a `/bin/sh` trampoline; both forms are
  parsed). It must be a regular file inside the venv; symlinks are refused. Udev rules are
  staged with LF line endings in `$GCAM_MVSDK_HOME/udev-rules/` and skipped when
  `/etc/udev/rules.d` already holds identical copies. All root commands (`libcap2-bin` if
  `setcap` is missing, `setcap`, `install`, `udevadm` x2) are printed first and run in one
  `sudo bash -c` call after one confirmation. Without a terminal and without `--yes`, the
  answer is no and the commands are only printed. After `setcap`, the script verifies that
  the interpreter still imports numpy and the package and that `CAP_NET_RAW` is effective;
  otherwise it prints `sudo setcap -r <python>`.
* The apt step for a missing `venv` module is a separate prompt because it must run before
  the venv exists; sudo's credential cache normally avoids a second password prompt.
* The final `doctor` and `list` run from `$GCAM_MVSDK_HOME` (from the repository with
  `--dev`), so a developer `./vendor/` copy does not shadow the installed SDK.
* `--uninstall` removes the link (only if it points into this venv) and the venv (only if
  it contains `pyvenv.cfg`), then asks, interactively only and defaulting to no, whether to
  delete the SDK versions, `.downloads`, and staged udev rules. Installed udev rules and the
  developer `./vendor/` copy are left in place, with the removal command printed.
* Secure-execution note (analysis, not verified here because `sudo` was unavailable): a
  binary with file capabilities ignores `LD_LIBRARY_PATH`, and glibc expands `$ORIGIN` in an
  executable's own RPATH only for trusted directories. The interpreters on this machine
  (Ubuntu's `python3.12`, Miniconda's `python3.13`) link only system libraries, so a copied,
  capability-bearing `python3` should start normally; extension modules such as numpy use
  `$ORIGIN`-relative RPATHs, which glibc still expands for non-executable objects. The
  post-`setcap` import check exists to catch an interpreter where this does not hold.

## Other changes in the second pass

* `__version__` is read from the installed distribution metadata, so `pyproject.toml` is
  the only place to change the version; `tests/test_cli_parsing.py` asserts they agree.
* CLI error hints by status: 32774 (0x8006), -45, -18 (camera held elsewhere), -13 (I/O
  error: held elsewhere or wrong subnet), -12 (timeout: MTU, rp_filter, firewall).
* `doctor` prints the SDK home and where it came from, and its venv advice now points to
  `bash install.bash` and `~/.gcam-mvsdk/py-venv`.
* Name hygiene: the venv marker is `gcam-mvsdk-py-home` and the udev staging prefix is
  `gcam-mvsdk-py-udev-`; the bare stem `gcam-mvsdk` is used only for shared items and for
  the base exception class `GcamMvsdkError`.
* `CLAUDE.md` and `.claude/skills/` (sdk-setup, camera-discovery, add-sdk-function, release,
  hardware-test) document the developer workflow. Helper scripts: `sdk_status.py`,
  `show_prototype.sh`, `measure_struct.sh`, `check_wheel.py`, `run_hw_tests.sh`. The header
  helpers print vendor text to the terminal only; nothing vendor-derived is written to the
  repository.
* The sdist now also carries `install.bash` and `CLAUDE.md`. CI additionally runs shellcheck
  on every shell script and `check_wheel.py` on the built artifacts.

## Cross-platform CI fixes (first CI run on GitHub)

* **Windows ISP output is bottom-up, and `Frame.to_numpy()` flips it on purpose.** The
  vendor's own Python examples call `CameraFlipFrameBuffer` after `CameraImageProcess` only
  on Windows, with a comment that the Windows output is stored upside down in BMP (DIB) row
  order while Linux output is upright. `to_numpy()` therefore reverses the rows on Windows so
  that callers get top-down rows on every platform; `view()` and `to_numpy(process=False)`
  expose the raw buffer and are never flipped. The unit test failed on Windows because the
  fake library wrote ISP output top-down on every platform, so the flip inverted correct
  data. The fake now emulates the platform's SDK (bottom-up on win32), the test asserts the
  real contract (top-down result), and a parametrized test exercises both orientations on
  every runner. The alignment assertion now checks the buffer passed to the SDK, because
  the flipped result is a new array whose alignment numpy does not guarantee.
* **Line endings.** GitHub's Windows runners check out with `core.autocrlf=true`, which
  turned `sdk-manifest.toml` into CRLF and changed its pinned SHA-256. `.gitattributes`
  (`* text=auto eol=lf`) now forces LF on every platform; this also keeps `install.bash`
  and the skill scripts runnable when a Windows checkout is copied to Linux.
* **Platform-dependent loader tests.** Tests that call the loader without pinning
  `system`/`arch` now create the library name and directory the loader expects on the
  running platform (`libMVSDK.so`, `libMVSDK.dylib`, `MVCAMSDK_X64.dll`), use
  `str(Path(...))` for expected paths (backslashes on Windows), and pin `arch="x64"` where
  they pin `system="Linux"` (the macOS runners are arm64). On macOS the manifest has no
  release, so `~/.gcam-mvsdk/<version>` candidates come only from existing directories; the
  "nothing found" test creates such a directory. The simulated "rejected library" test is not
  ELF-specific and runs everywhere. Locally, these were checked by patching
  `platform.system()`/`platform.machine()` to Windows/AMD64 and macOS/arm64, which reproduces
  the CI failures on the old tests and passes on the new ones.
* **shellcheck versions.** shellcheck 0.11 no longer reports SC2015 for `A && B || C`;
  0.9 and 0.10 (the versions distributions ship) do, at "info" severity, which CI counts.
  The two occurrences are rewritten as explicit `if` statements, and the documented local
  command pins `shellcheck-py==0.9.0.6`.
