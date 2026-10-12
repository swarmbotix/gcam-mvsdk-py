---
name: camera-discovery
description: Troubleshoot HuaTeng GigE and USB camera discovery with gcam-mvsdk-py. Explains why `gcam-mvsdk-py list` shows 0 cameras or misses one (privileges, rp_filter, firewall, subnet, link, busy camera) and gets it listed and openable again. Use for any "no cameras found", "camera not visible", or "camera listed but cannot be opened" request. For everyday listing use camera-list; for renaming, camera-rename; for changing an IP address, camera-setip.
---

# Camera discovery troubleshooting

GigE discovery is a GVCP broadcast (UDP 3956) on the host NIC the cameras are cabled to. It
needs raw-socket permission (root or `CAP_NET_RAW`), `rp_filter=0`, an open firewall on that
NIC, and the cameras on the same layer-2 segment. Cameras on a different IP subnet are usually
still discovered, but cannot be opened until `setip` moves them.

## Step 1: diagnose

```bash
gcam-mvsdk-py doctor       # SDK, privileges, rp_filter, firewall, NICs, camera subnets
gcam-mvsdk-py list         # names, serials, camera IP/MAC, host NIC IP/MAC
gcam-mvsdk-py list --json  # same, machine-readable (keys: serial, user_name, camera_ip, camera_mac, host_ip, ...)
```

## Step 2: interpret 0 cameras (work through in order)

1. **SDK not loaded**: doctor shows FAIL in the SDK section. Use the sdk-setup skill.
2. **No raw-socket permission**: doctor warns "CAP_NET_RAW is not effective". Fix once with
   `sudo setcap cap_net_raw,cap_net_admin+ep ~/.gcam-mvsdk/py-venv/bin/python3` (install.bash
   offers it), or test quickly with `sudo -E ~/.local/bin/gcam-mvsdk-py list`. Never setcap a
   system interpreter or a symlinked venv python; doctor explains if that is the case.
3. **rp_filter not 0**: `sudo sysctl -w net.ipv4.conf.all.rp_filter=0 net.ipv4.conf.<nic>.rp_filter=0`;
   persist it in `/etc/sysctl.d/60-gige-camera.conf`. The effective value is the maximum of
   `all` and the interface value, so both must be 0.
4. **Firewall**: `sudo ufw allow in on <nic>` or put the NIC in firewalld's trusted zone.
5. **Wrong NIC or no link**: `ip -br link` and `ip -br addr`; the camera NIC must be UP with a
   static IPv4 address. Check the cable, the PoE switch, and camera power. The workspace's
   cameras sit on a dedicated NIC of the bench host (see camera_publishers/cam_gige_ht/issue_report*.md),
   so a different machine will not see them at all.
6. **Cross-check with the vendor tool**: `sudo <sdk>/tools/GeConfigCmd/<arch>/GeConfigCmd`.
   If it also sees nothing, the problem is the network, not this package.

If cameras appear but show `<could not open: ...>` or open fails with status 32774 (0x8006),
-45, or -13, another process or host holds them. Find it (`docker ps`, publishers, viewers),
stop it, and retry.

## Step 3: camera on the wrong subnet (setip)

`doctor` reports "camera X is not in the subnet of host NIC Y". The full procedure, with the
address choice and the confirmation steps, is the camera-setip skill. In short:

```bash
gcam-mvsdk-py list --json            # note camera_mac, host_ip, host_mask of that camera
ping -c1 -W1 <new ip> || true        # the new address must be unused
gcam-mvsdk-py setip <camera_mac> <new ip in host subnet> <host_mask> 0.0.0.0
gcam-mvsdk-py list                   # confirm; power-cycle the camera if the old IP persists
```

Use the gateway `0.0.0.0` on an isolated camera network, or the real gateway when there is
one. `setip` stores a persistent address in the camera.

## Step 4: rename by serial number

Publishers select cameras by user-set name (`CAM_NAME` in the compose files), so names must
be unique and stable. The full procedure, with the name rules and the confirmation step, is the
camera-rename skill. In short:

```bash
gcam-mvsdk-py list                           # find the serial number of the physical camera
gcam-mvsdk-py rename <SN> <NAME>             # e.g. rename 056082422008 sb03
gcam-mvsdk-py list                           # the "User-set name" column shows the new name
```

Names are at most 31 bytes and must not contain `\ / : * ? " < > |`. The camera must not be
held by another process. Match by serial, never by position in the list, so the wrong
camera is not renamed.
