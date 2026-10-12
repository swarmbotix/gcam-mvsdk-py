---
name: camera-rename
description: Give a HuaTeng camera a user-set name with gcam-mvsdk-py (list, rename by serial number, list again), check the name rules (31 bytes, ASCII, no \ / : * ? " < > |) and uniqueness, and handle a camera that is busy (status -13 or 32774). Use when the user asks to name, rename, or relabel a camera, or to fix an empty or duplicated camera name, from the command line or from Python (cam.user_name).
---

# Rename a camera

The user-set name (DeviceUserID) is stored in the camera's non-volatile memory. It survives power
cycles and moves with the camera to another computer. Publishers, `info`, `grab`, live view and
`sdk.open()` select cameras by this name, so it must be unique on the network.

## When to use

- A new camera shows `<empty>` as its user-set name in `gcam-mvsdk-py list`.
- The user wants a camera renamed, or two cameras share a name (`user-set name 'X' is ambiguous`).
- Not for changing the IP address (camera-setip) or the model name shown by enumeration.

## Prerequisites

- The camera is listed by `gcam-mvsdk-py list` (otherwise camera-discovery).
- The user has named the camera to rename by its **serial number**, or has confirmed the serial
  number after seeing the list. Never infer it from list position, model, or IP address.
- No other program or host holds the camera: rename opens it. Stop publishers and viewers first.

## Steps

1. Show the current state and find the serial number:

   ```bash
   gcam-mvsdk-py list
   ```

2. Check the new name against the rules below and against every name already in use:

   ```bash
   gcam-mvsdk-py list --json | python3 -c 'import json, sys; print(sorted(str(r["user_name"]) for r in json.load(sys.stdin)))'
   ```

   Cameras that could not be opened show `None`; their names are unknown, so ask the user whether
   one of them might already carry the new name.

3. Confirm with the user, quoting the exact command: "Rename camera SN `<SN>` (currently
   `<old name>`) to `<NAME>`?" Rename only after an explicit yes.

4. Write the name, then verify it:

   ```bash
   gcam-mvsdk-py rename <SN> <NAME>        # for example: gcam-mvsdk-py rename 056090423003 sb00
   gcam-mvsdk-py list                      # the "User-set name" line shows the new name
   gcam-mvsdk-py info <NAME>               # selecting by the new name works
   ```

5. If a publisher or script selected the camera by its old name, update that configuration (for
   example a `CAM_NAME` setting) before restarting it.

The same from Python:

```python
import gcam_mvsdk_py

sdk = gcam_mvsdk_py.load()
with sdk.open("056090423003") as cam:     # by serial number
    print("current name:", cam.user_name)
    cam.user_name = "sb00"                # validated, then written to the camera
    assert cam.user_name == "sb00"
```

### Name rules

- At most 31 bytes (the camera field is 32 bytes including the terminating NUL).
- None of `\ / : * ? " < > |`. The SDK itself rejects them with status -53.
- ASCII only in practice: letters, digits, `-` and `_` (for example `sb00`, `line2-top`). The
  package does not reject other text but stores it as GBK, two bytes per Chinese character, and
  other tools may not display it correctly.
- Not empty, and unique among the cameras on the network. Nothing enforces uniqueness; a duplicate
  makes selection by name fail with `user-set name 'X' is ambiguous: serials A, B`.

Where each rule is enforced: the command line rejects an empty name and the forbidden characters
while parsing the arguments (`gcam-mvsdk-py rename: error: argument NAME: name must not contain /`,
exit status 2). The `cam.user_name` setter raises `ValueError` for the forbidden characters
(`camera name must not contain any of ...`) and for more than 31 bytes (`camera name is N bytes; the
limit is 31`) before anything is sent; the command line reports the latter as
`gcam-mvsdk-py: error: camera name is N bytes; the limit is 31` with exit status 1.

## Reading the output

```
056090423003: user-set name '' -> 'sb00' (stored in camera memory)
```

The first value is the name read before writing, the second the name read back after writing. If
the camera reports a different name than the one written, the command prints
`warning: the camera reports '...' after writing '...'` and exits with status 1. `list` reads the
name from the camera, so it shows the new name at once; the enumeration name on the `Model` line
may change only after the camera restarts.

## If it fails

| Message | Cause | Fix |
|---|---|---|
| `no camera with serial number 'X' (found: ...)` | Typo, or the camera is not discovered | Copy the serial from `gcam-mvsdk-py list`; if absent, camera-discovery |
| `status 32774` (0x8006), `status -45` or `status -18` | Another program or host holds the camera | Stop the holder (`docker ps`, then `docker stop <id>` or `docker compose down` in the publisher's directory; close viewers and other `gcam-mvsdk-py` runs; check other hosts on the camera network), then retry |
| `status -13` (I/O error) | Held elsewhere, or the camera is on another subnet | As above; `gcam-mvsdk-py doctor`; if the subnet is wrong, camera-setip first |
| `name must not contain ...`, `name must not be empty` | Rule violation caught by the command line | Choose another name |
| `camera name is N bytes; the limit is 31` | Name too long (also non-ASCII text counted as GBK bytes) | Shorten it |
| `status -53` | The SDK rejected the name | Use letters, digits, `-` and `_` only |

Restart any publisher you stopped once the rename is done.

## Safety

- Never rename a camera that the user did not identify explicitly by serial number, and confirm
  the serial number and the new name with the user before running `rename` or setting
  `cam.user_name`. Renaming the wrong camera silently breaks every program that selects it by name.
- Do not rename a camera in production use without the owner's consent; publishers that select it
  by its old name stop finding it.
- Do not run the `identity_name` example from `examples/capabilities.py` against a real camera: it
  renames the camera to `sb01` (the example runner always shows it as a dry run).
