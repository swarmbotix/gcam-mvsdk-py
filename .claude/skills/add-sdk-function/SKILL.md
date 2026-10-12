---
name: add-sdk-function
description: Expose another MVSDK C function (from CameraApi.h) in gcam-mvsdk-py end to end - ctypes signature in _ffi.py, safe method or property in api.py, fake-library unit test, optional hardware test. Use when asked to wrap, bind, or add support for a Camera* SDK function or a new SDK structure.
---

# Wrap a new MVSDK function

Write declarations from the public interface in your own words. Never copy header text,
comments, or the vendor's `mvsdk.py` into the repository.

## Step 1: read the prototype

The headers are in any installed SDK (`./vendor/<version>/include`, `~/.gcam-mvsdk/<version>/include`,
or `$GCAM_MVSDK_DIR/include`). `CameraApi.h` has CRLF line endings and Chinese plus English
comments; the helper strips the noise and prints the English description and the declaration:

```bash
.claude/skills/add-sdk-function/show_prototype.sh CameraSetGamma
.claude/skills/add-sdk-function/show_prototype.sh CameraSetGamma /path/to/include   # explicit dir
```

Note buffer-size requirements for `char*` outputs (for example "at least 32 bytes").

## Step 2: confirm the symbol exists in the shipped library

```bash
nm -D --defined-only vendor/2.1.0.49/lib/x64/libMVSDK.so | grep -w CameraSetGamma
```

Header declarations without an exported symbol exist (the plan's `CameraSetGigePacketSize`
was one); do not wrap those.

## Step 3: declare it in `src/gcam_mvsdk_py/_ffi.py`

Add one entry to `FUNCTIONS`, in the matching group:

```python
"CameraSetGamma": (_S, [_H, c_int]),
"CameraGetGamma": (_S, [_H, _PINT]),
```

| C type | ctypes |
|---|---|
| `CameraSdkStatus` (return) | `_S` (`c_int`) |
| `CameraHandle` | `_H` |
| `int`, `INT`, `BOOL`, enum | `c_int` |
| `UINT`, `DWORD` | `c_uint` |
| `float` / `double` | `c_float` / `c_double` |
| `T*` output | `POINTER(T)` (`_PINT`, `_PUINT`, `_PDOUBLE`, `_PFLOAT`) |
| `char*` output, `char const*` input | `c_char_p` |
| `BYTE*` buffer | `c_void_p` |
| `tSdkXxx*` | `POINTER(tSdkXxx)` |
| callback | a `FUNCTYPE(...)` type (WINFUNCTYPE on Windows comes from `FUNCTYPE`) |

New structure: define a `Structure` subclass with fields in header order, then measure the
C layout and record it in `C_SIZES_LP64` / `C_SIZES_ILP32` (the size test parametrizes over
those tables automatically):

```bash
.claude/skills/add-sdk-function/measure_struct.sh tSdkFrameStatistic iTotal iLost
```

## Step 4: add the safe wrapper in `src/gcam_mvsdk_py/api.py`

- Camera getter: property using `self._get("CameraGetGamma", c_int)`.
- Camera setter: `self._call("CameraSetGamma", int(value))` (the handle is added for you).
- Library-level call: `Sdk` method using `self._call(name, ...)`.
- Strings: `create_string_buffer(_ffi.NAME_BUFFER_SIZE)` then `decode_c_string(buf.raw)`;
  inputs via `encode_c_string`. Never assume UTF-8.
- Validate arguments the SDK would silently clamp; raise `ValueError` with the allowed range.
- Every non-zero status must become `MvError` through `_call` / `check`.

```python
@property
def gamma(self) -> int:
    return int(self._get("CameraGetGamma", c_int))

@gamma.setter
def gamma(self, value: int) -> None:
    self._call("CameraSetGamma", int(value))
```

## Step 5: test without hardware (`tests/test_api_fake.py`)

Add a `_CameraSetGamma` method to `FakeLib` that mimics the C behaviour (out-parameters
arrive as `byref` objects; reach the value with `ref._obj.value`), then a test:

```python
def test_gamma(fake, sdk):
    with sdk.open("SN001") as cam:
        cam.gamma = 120
        assert cam.gamma == 120
```

Also test the error path (return a negative status from the fake and assert `MvError`).

## Step 6: hardware test (if it touches the camera)

Add a test to `tests/hw/test_hardware.py` that reads the original value, changes it, checks
it, and restores it in `finally`. Do not call `save_parameter` in tests.

## Step 7: finish

```bash
pytest                                    # current Python
<python3.9 venv>/bin/python -m pytest     # minimum supported version
ruff check --select F,E9,B src tests
./scripts/check-no-vendor-files.sh
```

If the function is user-visible through the CLI, update the README command table; record
any non-obvious choice in IMPLEMENTATION_NOTES.md.
