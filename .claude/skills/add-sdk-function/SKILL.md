---
name: add-sdk-function
description: Expose another MVSDK C function (from CameraApi.h) in gcam-mvsdk-py end to end - ctypes signature in _ffi.py, safe property or method in api.py, unit test with the fake SDK, the entry in docs/CAPABILITIES.md, optional hardware test. Use when asked to wrap, bind, or add support for a Camera* SDK function or a new SDK structure, or to turn a "raw" item of docs/CAPABILITIES.md into a "wrapped" one.
---

# Wrap a new MVSDK function

Write declarations from the public interface in your own words. Never copy header text,
comments, or the vendor's `mvsdk.py` into the repository. The worked example below wraps
`CameraSetNoiseReductionValue` / `CameraGetNoiseReductionValue`, which docs/CAPABILITIES.md
currently lists as "raw".

## Step 1: read the prototype

The headers are in any installed SDK (`./vendor/<version>/include`, `~/.gcam-mvsdk/<version>/include`,
or `$GCAM_MVSDK_DIR/include`). `CameraApi.h` has CRLF line endings and Chinese plus English
comments; the helper strips the noise and prints the description and the declaration:

```bash
.claude/skills/add-sdk-function/show_prototype.sh CameraSetNoiseReductionValue
.claude/skills/add-sdk-function/show_prototype.sh CameraGetNoiseReductionValue /path/to/include   # explicit dir
```

Note ranges, defaults and buffer sizes stated in the comment (here: value 0 to 7). Do not
invent ranges the header does not give; say "model dependent" instead.

## Step 2: confirm the symbol exists in the shipped library

```bash
nm -D --defined-only vendor/2.1.0.49/lib/x64/libMVSDK.so | grep -w CameraSetNoiseReductionValue
```

Header declarations without an exported symbol exist (the plan's `CameraSetGigePacketSize`
was one); do not wrap those.

## Step 3: declare it in `src/gcam_mvsdk_py/_ffi.py`

Add the pair to `FUNCTIONS`, in the matching group (image processing here):

```python
"CameraSetNoiseReductionValue": (_S, [_H, c_int]),
"CameraGetNoiseReductionValue": (_S, [_H, _PINT]),
```

| C type | ctypes |
|---|---|
| `CameraSdkStatus` (return) | `_S` (`c_int`) |
| `CameraHandle` | `_H` |
| `int`, `INT`, `BOOL`, enum | `c_int` |
| `UINT`, `DWORD` | `c_uint` |
| `float` / `double` | `c_float` / `c_double` |
| `T*` output | `POINTER(T)` (`_PINT`, `_PUINT`, `_PDOUBLE`, `_PFLOAT`) |
| `char*` output, `char const*` input, `BYTE*` data | `c_char_p` (pass `create_string_buffer`) |
| `T name[N]` array parameter | `POINTER(T)` (pass a `(T * N)` array) |
| `tSdkXxx*` | `POINTER(tSdkXxx)` |
| callback | a `FUNCTYPE(...)` type (WINFUNCTYPE on Windows comes from `FUNCTYPE`) |

New enum values go next to the existing constants in `_ffi.py` and are exported from
`src/gcam_mvsdk_py/__init__.py`. New structure: define a `Structure` subclass with fields in
header order, then measure the C layout and record it in `C_SIZES_LP64` / `C_SIZES_ILP32` (the
size test parametrizes over those tables automatically):

```bash
.claude/skills/add-sdk-function/measure_struct.sh tSdkFrameStatistic iTotal iLost
```

## Step 4: add the safe wrapper in `src/gcam_mvsdk_py/api.py`

Scalar Set/Get pairs use the property factories at the top of the module: `_int_property`
(optional `low`/`high` range check), `_uint_property` (rejects negatives), `_bool_property`,
`_direction_property` (functions that take a direction first, such as mirroring):

```python
noise_reduction = _int_property(
    "CameraGetNoiseReductionValue", "CameraSetNoiseReductionValue",
    "Noise reduction strength, 0 to 7.", 0, 7)
```

Anything else is an explicit property or method using `self._call(name, ...)` (the handle is
added for you), `self._get(name, ctype)` or `self._get_many(name, *ctypes)`. Library-level
functions become `Sdk` methods. Strings: `create_string_buffer(...)` then `decode_c_string`;
inputs via `encode_c_string`. Every non-zero status must become `MvError` through `_call`.
Name properties after what they mean (units in the name, `_us`, `_hz`, `_deg`), not after the
C function.

## Step 5: test without hardware (`tests/test_api_settings.py`)

`tests/fake_mvsdk.py` has `GenericFakeLib`: it remembers every `CameraSet*` call and answers
the matching `CameraGet*` with the same values, so a simple pair needs no hand-written fake.
Add the property to the parametrized round-trip test, plus a range test when the wrapper
validates:

```python
("noise_reduction", 3, "CameraSetNoiseReductionValue"),   # in test_integer_settings_round_trip
("noise_reduction", 8),                                    # in test_out_of_range_values_...
```

Functions whose Get does not mirror the Set, or that fill buffers, get an explicit
`_CameraXxx` method on `GenericFakeLib` (out-parameters arrive as `byref` objects; set
`ref._obj.value`). Test the error path with `fake.fail["CameraXxx"] = -4` and `MvError`.

## Step 6: update docs/CAPABILITIES.md

1. In the item's row, change the Python column from `raw` to `wrapped: cam.noise_reduction`.
2. In `examples/capabilities.py`, replace the raw `cam.call(...)` line with the property. A new
   example function also needs a `<!-- snippet: name -->` block in its section of the document
   and an entry in the `SECTIONS` table at the end of `examples/capabilities.py`, which the
   command-line runner (run-capabilities-example skill) and the tests use.
3. Regenerate the snippets and the summary counts, then check:

```bash
python scripts/update_capabilities_doc.py
pytest tests/test_capabilities_examples.py    # runs every example and checks the document
```

## Step 7: hardware test (if it touches the camera)

Add a test to `tests/hw/test_hardware.py` that reads the original value, changes it, checks
it, and restores it in `finally`. Do not call `save_parameter` in tests.

## Step 8: finish

```bash
pytest                                    # current Python
<python3.9 venv>/bin/python -m pytest     # minimum supported version
ruff check --select F,E9,B src tests examples scripts
./scripts/check-no-vendor-files.sh
```

If the function is user-visible through the CLI, update the README command table; record
any non-obvious choice in a code comment next to the declaration.
