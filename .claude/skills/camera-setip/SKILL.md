---
name: camera-setip
description: Diagnose a GigE camera whose IP address is outside the host NIC's subnet (from gcam-mvsdk-py list and doctor) and fix it, either by giving the camera a persistent address with gcam-mvsdk-py setip <MAC> <IP> <MASK> <GW> or by changing the host NIC's address instead, then verify with list. Use when a camera is listed but cannot be opened because of its address, when doctor warns "not in the subnet of host NIC", or when the user asks to change or fix a camera's IP address.
---

# Set a camera's IP address

A GigE camera answers discovery from whatever address it holds, but it can only be opened when that
address lies in the subnet of the host NIC it is cabled to. `setip` writes a fixed address into the
camera, selected by MAC address, and works while the camera is still on the wrong subnet.

## When to use

- `gcam-mvsdk-py doctor` warns `camera A/M is not in the subnet of host NIC H/HM`.
- `gcam-mvsdk-py list` shows a `Camera` IP outside the `Host NIC` network, usually together with
  `<could not open: ...>` (often status -13).
- The user wants a camera moved to a planned address.

Use camera-discovery instead when the camera is not listed at all.

## Prerequisites

- The camera appears in `gcam-mvsdk-py list` (its MAC address is on the `Camera` line).
- The host NIC for the cameras has a static IPv4 address (`ip -br addr`).
- No other program or host is using the camera.
- The user has confirmed which camera (MAC and serial number) and which address to use.

## Steps

1. **Diagnose.**

   ```bash
   gcam-mvsdk-py doctor          # Cameras section: the subnet check per camera
   gcam-mvsdk-py list            # Camera and Host NIC lines of each camera
   ip -br addr                   # host interfaces and their addresses
   ```

   Example of a mismatch: `Camera : IP 169.254.12.7 Mask 255.255.0.0 ... MAC 00-1A-2B-3C-4D-5E` and
   `Host NIC : IP 192.168.3.10 Mask 255.255.255.0`. The doctor line ends with
   `Fix: gcam-mvsdk-py setip <camera MAC> <IP in 192.168.3.10/255.255.255.0> <mask> <gateway>`.

2. **Decide which side to change.**
   - Change the camera (the usual case): the host NIC already has the camera network's address, and
     other cameras live there.
   - Change the host NIC instead: the camera's address is deliberate (configured elsewhere, shared
     with other hosts), or this NIC carries nothing else. With NetworkManager:

     ```bash
     sudo nmcli con mod "<connection name>" ipv4.method manual ipv4.addresses 192.168.3.10/24
     sudo nmcli con up "<connection name>"
     ```

     This changes the host's networking: ask the user first, and never do it on the NIC that
     carries the host's own network access. Then skip to step 5.

3. **Choose the camera address.** It must be inside the host NIC's network, with the host NIC's
   mask, and unused:
   - not the host NIC's own address, not the network or broadcast address
     (for 192.168.3.0/24: not .0 and not .255);
   - not the address of another camera (`gcam-mvsdk-py list --json`, `camera_ip` values) or of any
     other device (`ping -c1 -W1 <ip>` should get no reply; `ip neigh show dev <nic>`);
   - gateway `0.0.0.0` on an isolated camera network; a real gateway only if one exists inside the
     subnet (otherwise the command warns `gateway G is outside N`).

   Confirm the MAC address, serial number, old address and new address with the user.

4. **Set it.**

   ```bash
   gcam-mvsdk-py setip <MAC> <IP> <MASK> <GW>
   gcam-mvsdk-py setip 00-1A-2B-3C-4D-5E 192.168.3.21 255.255.255.0 0.0.0.0     # example
   ```

   The MAC may be written with `-`, `:` or `.` separators; the mask also accepts a prefix length
   such as `24`.

5. **Verify.**

   ```bash
   gcam-mvsdk-py list            # the Camera line shows the new IP; the name is readable again
   gcam-mvsdk-py doctor          # [ OK ] ...: camera 192.168.3.21, host NIC 192.168.3.10/255.255.255.0
   gcam-mvsdk-py info <SN>       # the camera opens
   ```

   Some models apply the new address only after a power cycle; if `list` still shows the old
   address, power-cycle the camera and list again.

From Python: `sdk.gige_set_ip(dev, "192.168.3.21", "255.255.255.0", "0.0.0.0", persistent=True)`,
with `dev` taken from `sdk.enumerate()` by matching `dev.gige_mac().camera_mac` or `dev.serial`.
`persistent=False` switches the camera to automatic addressing and ignores the three addresses;
the command line has no option for that.

## Reading the output

```
Camera 00:1a:2b:3c:4d:5e (SN 056090423003) set to IP 192.168.3.21 mask 255.255.255.0 gateway 0.0.0.0 (persistent).
Run `gcam-mvsdk-py list` to confirm; some models apply the change after a power cycle.
```

"Persistent" means the address is stored in the camera and survives power cycles; it stays until
`setip` is run again. It applies to every host on that network, not only to this one.

## If it fails

| Message | Cause | Fix |
|---|---|---|
| `no GigE camera with MAC X (found: ...)` | Typo, a USB camera, or the camera is not discovered | Copy the MAC from the `Camera` line of `gcam-mvsdk-py list`; if the camera is absent, camera-discovery |
| `argument MAC: invalid MAC address`, `argument IP: invalid IPv4 address`, `argument MASK: invalid netmask` (exit status 2) | Malformed argument | Correct it; nothing was sent to the camera |
| `warning: gateway G is outside N` | Gateway not in the new subnet | Use `0.0.0.0` unless a real gateway exists in the subnet |
| An `MvError` status from `CameraGigeSetIp` | The camera is held elsewhere, or the model refused the address | Stop other holders; check the address; retry |
| The camera keeps its old address | The model applies it after a restart | Power-cycle the camera, then `gcam-mvsdk-py list` |
| The camera vanished from `list` afterwards | It is now in a subnet the host cannot hear (rp_filter, firewall), or the address collides | camera-discovery skill; then run `setip` again by MAC with a correct address |

## Safety

- Confirm the MAC address and the complete new address (IP, mask, gateway) with the user before
  running `setip`. Never pick the camera by list position.
- A wrong address (wrong subnet, typo, duplicate) can leave the camera unreachable for opening
  until `setip` is run again by MAC address, which needs the camera to be discoverable from a host
  on the same network segment (rp_filter 0, firewall open; see camera-discovery).
- The change affects every host and program that uses this camera; agree on it with whoever runs
  the camera network.
- Do not run the `identity_network` example from `examples/capabilities.py` on a real network: it
  sets 192.168.3.21 on the first camera found (the example runner always shows it as a dry run).
