# CLAUDE.md

Guidance for Claude Code sessions working in this repository.

## Purpose

Pure-Python ctypes wrapper and CLI for the HuaTeng Vision MVSDK (GigE and USB
industrial cameras). The vendor library is loaded at runtime and is never shipped.
Design and roadmap: `PLAN_PYTHON_WRAPPER.md`. Implementation decisions:
`IMPLEMENTATION_NOTES.md`. Sibling Rust package: `../gcam-mvsdk-rs`.

## Naming (exact, no variants)

- Repository, PyPI package, console script: `gcam-mvsdk-py`. Import package: `gcam_mvsdk_py`.
- Shared with the Rust package: `~/.gcam-mvsdk/<version>/lib/<arch>/`, `GCAM_MVSDK_HOME`,
  `GCAM_MVSDK_DIR`, `GCAM_MVSDK_ARCH`, `GCAM_MVSDK_HW_TEST`. Python only: `GCAM_MVSDK_BIN_DIR`
  and the `<venv>/gcam-mvsdk-py-home` marker file.
- No shorthand ("gcam", "mvsdk-py", "gcam_mvsdk") in code, docs, or messages. The bare stem
  `gcam-mvsdk` appears only in the shared items above and in the base class `GcamMvsdkError`.

## Never commit vendor files

No `.so`, `.dll`, `.dylib`, `.lib`, archives, `.chm`, `CameraApi.h`, `CameraDefine.h`,
`CameraStatus.h`, or the vendor's `mvsdk.py`. `vendor/` is git-ignored and holds a local SDK
copy only. Do not paste vendor header text or comments into source; declare signatures from
the public interface in your own words. Before any commit: `./scripts/check-no-vendor-files.sh`.
Never run `git commit` or `git push` unless the user asks.

## Layout

```
install.bash                 one-command user installer (venv, CLI link, SDK, setcap, udev)
sdk-manifest.toml            known vendor releases; byte-identical to the Rust repo's copy
scripts/fetch-sdk.sh         developer SDK fetch into ./vendor/<version>/
scripts/check-no-vendor-files.sh   fails if git tracks a vendor file
src/gcam_mvsdk_py/
  __init__.py                public names; __version__ from installed metadata
  _loader.py                 library search order, arch mapping, CDLL / WinDLL open
  _ffi.py                    ctypes Structures, FUNCTIONS table (argtypes/restype), status codes
  _errors.py                 MvError, MvTimeout, SdkNotFound, DeviceNotFound, string decoding
  _manifest.py               sdk-manifest.toml reader (tomllib or tomli)
  api.py                     safe layer: load, Sdk, DeviceInfo, Camera, Frame
  setup_cmd.py               downloader: HEAD, GET, sha256, safe extract, manifest.json, udev
  cli.py                     argparse CLI: setup, list, rename, setip, info, grab, doctor
  _doctor.py                 diagnostics: SDK, CAP_NET_RAW, rp_filter, firewall, subnets
  _png.py                    PNG writer (OpenCV if present, zlib fallback)
tests/                       unit tests (no SDK needed); tests/hw/ needs cameras
.claude/skills/              task procedures: sdk-setup, camera-discovery, add-sdk-function,
                             release, hardware-test
```

## Build and test

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"                 # no SDK needed
pytest                                  # unit tests; must pass on Python 3.9 and current
./scripts/fetch-sdk.sh                  # SDK into ./vendor/ (or bash install.bash --dev)
GCAM_MVSDK_HW_TEST=1 pytest tests/hw -v # hardware; see .claude/skills/hardware-test
python -m build                         # dist/gcam_mvsdk_py-<ver>-py3-none-any.whl + sdist
```

Python 3.9 for testing without touching the system: `uv python install 3.9` with
`UV_PYTHON_INSTALL_DIR` pointing at a scratch directory. Lint: `ruff check --select F,E9,B src tests`.
Shell: `shellcheck -x install.bash scripts/*.sh` (`uvx --from shellcheck-py shellcheck` works).

## Loader search order (`_loader.find_library`)

1. `$GCAM_MVSDK_DIR/lib/<arch>`, `$GCAM_MVSDK_DIR/lib`, `$GCAM_MVSDK_DIR`
2. `./vendor/<version>/lib/<arch>` (relative to the current directory)
3. `<sdk home>/<version>/lib/<arch>`; sdk home = `$GCAM_MVSDK_HOME`, else the path in
   `<venv>/gcam-mvsdk-py-home` written by install.bash, else `~/.gcam-mvsdk`
4. System dirs (`LD_LIBRARY_PATH`, `/lib`, `/usr/lib`, multiarch; `PATH` on Windows), then bare name

Versions are the manifest's entries for the OS plus existing subdirectories, newest first.
`<arch>`: x64, arm64, arm, x86 (`GCAM_MVSDK_ARCH` overrides, e.g. `arm_softfp`).

## SDK source and new releases

Vendor download page: http://huatengvision.com/download/1/ (plain HTTP only, so the
SHA-256 check is mandatory). To add a release: download it, `sha256sum` it, inspect the
layout (`tar tzf`), append one `[[release]]` block (version, os, url, size, sha256, layout)
to `sdk-manifest.toml`, make the identical change in `../gcam-mvsdk-rs/sdk-manifest.toml`,
then update `MANIFEST_SHA256` in `tests/test_manifest.py`. The two files must stay
byte-identical; `tests/test_manifest.py` compares them when the Rust checkout exists.

## Wrapping a new MVSDK function

Full procedure: `.claude/skills/add-sdk-function/SKILL.md`. In short:
1. Read the prototype in `include/CameraApi.h` (GBK and CRLF; use the skill's helper script).
2. Add `"CameraXxx": (restype, [argtypes])` to `_ffi.FUNCTIONS`; new structs get a
   size test against values measured with gcc (`measure_struct.sh`).
3. Add an `api.py` method or property that calls `self._call("CameraXxx", ...)` and decodes
   strings with `decode_c_string`.
4. Test it in `tests/test_api_fake.py` by extending `FakeLib`; add a hardware test if it
   touches the camera.

## Conventions

- Standard library first. numpy is the only hard dependency (plus tomli on Python < 3.11).
  OpenCV stays optional. No compiled code: the wheel must remain `py3-none-any`.
- Python 3.9 syntax: `from __future__ import annotations`, `typing.Optional`/`List`, no `match`.
- Every SDK status goes through `_errors.check` and becomes `MvError` (`MvTimeout` for -12).
- No bare `except:`. Catch specific exceptions; `except Exception` only where a failure must
  be reported rather than raised (doctor, `__del__`, callback trampoline).
- Strings from the SDK: ASCII, then GBK (`decode_c_string`). Never assume UTF-8.
- CLI output and errors are written for users: say what failed and the command that fixes it.
- Unit tests never need the SDK, a camera, root, or the network (use `isolated_env`, `FakeLib`,
  and the local `http.server` fixture).

## Do not

- Do not commit, push, or tag without being asked.
- Do not add vendor files, vendor text, or downloaded archives to the repository.
- Do not change `sdk-manifest.toml` in one repository only.
- Do not run `sudo`, `setcap`, or udev changes from tests or helper scripts without the user's consent.
- Do not run the rename hardware test on a production camera without `GCAM_MVSDK_HW_RENAME_SN`.
- Do not apply `setcap` to a system interpreter or to a venv whose `python3` is a symlink.
- Do not make the default `cam.grab()` path zero-copy; `Frame.to_numpy()` copies by design.
- Do not add a hard dependency on OpenCV, click, or any compiled package.
