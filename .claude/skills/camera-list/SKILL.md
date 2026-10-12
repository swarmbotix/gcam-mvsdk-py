---
name: camera-list
description: List the HuaTeng cameras that gcam-mvsdk-py can see (gcam-mvsdk-py list, list --json, list --no-open), explain each field, spot a camera on the wrong subnet or held by another program, and select a camera by user-set name or serial number. Use for everyday questions such as "which cameras are connected", "what is the serial, IP or MAC of camera X", "is sb01 there", and before renaming, re-addressing, configuring or grabbing. When the list is empty or an expected camera is missing, switch to camera-discovery.
---

# List cameras

`gcam-mvsdk-py list` enumerates every camera the SDK can see (GigE discovery broadcast plus USB),
opens each one briefly to read its user-set name, and prints one block per camera. It never changes
a camera.

## When to use

- The user asks which cameras are connected, or for a camera's serial number, IP or MAC address.
- Before `rename` (needs the serial number), `setip` (needs the MAC address), `info`, `grab`,
  live view, or any configuration, to confirm that the intended camera is present.
- To check whether a camera is on the host NIC's subnet or is held by another program.

Use camera-discovery instead when `list` prints "No cameras found" or an expected camera is absent.

## Prerequisites

- The command is installed (`bash install.bash`) and the SDK loads: `gcam-mvsdk-py doctor` shows
  no FAIL in its SDK section. Otherwise use the sdk-setup skill.
- GigE discovery needs raw-socket permission: the capability that install.bash offers on
  `~/.gcam-mvsdk/py-venv/bin/python3`, or `sudo -E ~/.local/bin/gcam-mvsdk-py list`.

## Steps

```bash
gcam-mvsdk-py list              # human-readable, opens each free camera to read its name
gcam-mvsdk-py list --json       # the same data as JSON, for scripts
gcam-mvsdk-py list --no-open    # enumeration only; never opens a camera (use while publishers run)
```

Pick out fields from the JSON without extra tools:

```bash
gcam-mvsdk-py list --json | python3 -c 'import json, sys
for r in json.load(sys.stdin):
    print(r["serial"], r["user_name"], r.get("camera_ip"), r.get("camera_mac"), r.get("open_error", ""))'
```

Select one camera by user-set name or serial number in every other command:

```bash
gcam-mvsdk-py info sb01              # by user-set name
gcam-mvsdk-py info 056090423003      # by serial number (always unique)
gcam-mvsdk-py grab sb01 -n 1 -o /tmp/sb01-check
```

In Python, `sdk.open("sb01")` and `sdk.find("sb01")` accept the same keys. Matching order: serial
number first, then the user-set name (each free camera is opened briefly to read it; cameras held
elsewhere are skipped), then the name reported by enumeration. `rename` accepts only a serial
number and `setip` only a MAC address.

## Reading the output

Text output, one block per camera, introduced by `Found N camera(s)`:

| Line | Meaning |
|---|---|
| `[N]` | Enumeration order. It can change between runs; never select a camera by it. |
| `User-set name` | Name stored in the camera (DeviceUserID), read by opening it. `<empty>`: no name set yet. `<could not open: ...>`: another program or host holds the camera, or it is unreachable on another subnet. `<not read>`: `--no-open` was given. |
| `Model` | Name reported by enumeration (`acFriendlyName`). On a camera that was never named it is the model, for example `MV-GE134GM`; the SDK lets this field carry a custom name, so it may show the user-set name after a rename and a restart. Identify cameras by the user-set name and serial number, not by this line. |
| `Product` | Product name reported by enumeration. |
| `Serial number` | Factory serial. Unique and permanent; use it for `rename` and when names are missing or duplicated. |
| `Port type` | How the camera is attached (GigE or USB), as reported by the SDK. |
| `Camera` | GigE only: the camera's IP, mask, gateway and MAC address. |
| `Host NIC` | GigE only: the IP, mask, gateway and MAC address of the host interface the camera answered on. |

JSON keys: `index`, `user_name` (`null` when not read or when opening failed), `serial`, `model`,
`product`, `series`, `port_type`, `sensor_type`, `driver_version`, `instance`, and for GigE cameras
`camera_ip`, `camera_mask`, `camera_gateway`, `camera_mac`, `host_ip`, `host_mask`, `host_gateway`,
`host_mac`. `open_error` and `gige_error` appear only when that step failed. An empty list prints
`[]`.

**Camera on the wrong subnet.** The camera IP must lie inside the host NIC's network (host IP and
mask). Example of a mismatch: `Camera : IP 169.254.12.7 Mask 255.255.0.0` with
`Host NIC : IP 192.168.3.10 Mask 255.255.255.0`. Such a camera is usually listed but shows
`<could not open: ...>`, and `gcam-mvsdk-py doctor` warns "camera ... is not in the subnet of host
NIC ...". Check one pair by hand:

```bash
python3 -c 'import ipaddress, sys; print(ipaddress.ip_address(sys.argv[1]) in ipaddress.ip_network(sys.argv[2] + "/" + sys.argv[3], strict=False))' 169.254.12.7 192.168.3.10 255.255.255.0
```

`False` means the camera must be moved: use camera-setip.

**While a publisher is streaming.** A camera that a publisher, viewer or other host holds cannot be
opened, so its name shows `<could not open: ...>` (status 32774, -45 or -13 in the message), while
its serial number and addresses are still listed from enumeration. Prefer `list --no-open` while
publishers run: it opens nothing, so it cannot race a publisher that is starting at the same moment.

## If it fails

| Symptom | Next step |
|---|---|
| "No cameras found. Check cable, power, ..." (or `[]` with `--json`) | camera-discovery skill |
| An expected camera is missing while others appear | camera-discovery skill (link, power, NIC, subnet) |
| `HuaTeng MVSDK library not found` (exit status 3) | sdk-setup skill |
| `<could not open: ...>` on a camera nobody should be using | Stop leftover holders (`docker ps`, viewers, other hosts); then `gcam-mvsdk-py doctor` for the subnet check |
| `user-set name 'X' is ambiguous: serials A, B` from another command | Two cameras share a name; select by serial number and fix the names with camera-rename |
| `<empty>` names | Name the cameras with camera-rename |

## Safety

`list` is read-only. Without `--no-open` it briefly opens every camera that is free, which can make
a program that tries to open the same camera at that instant fail; use `--no-open` on production
systems while publishers are starting or running.
