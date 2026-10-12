---
name: hardware-test
description: Run the gcam-mvsdk-py hardware tests (GCAM_MVSDK_HW_TEST=1 pytest tests/hw) safely against real HuaTeng cameras, know what each test expects, and interpret failures. Use when asked to test on the bench, validate against real cameras, or verify a change that touches camera I/O.
---

# Hardware tests

The tests in `tests/hw/` are skipped unless `GCAM_MVSDK_HW_TEST=1`. They need the SDK, the
cameras on a NIC of this host, raw-socket permission, and no other process holding the
cameras.

## Step 1: preconditions

1. Stop anything that holds cameras: the publishers (`docker ps`, then `docker compose down`
   in `camera_publishers/cam_gige_ht`), viewers, other test runs. A held camera makes the
   grab test skip or fail with status 32774 (0x8006), -45, or -13.
2. Run `gcam-mvsdk-py doctor`: the SDK must load, CAP_NET_RAW must be effective (or run the
   tests under `sudo -E`), rp_filter 0, cameras in the host NIC subnet.
3. `gcam-mvsdk-py list` must show the expected cameras.

## Step 2: run

```bash
.claude/skills/hardware-test/run_hw_tests.sh                      # preflight, then pytest tests/hw -v
GCAM_MVSDK_HW_EXPECT=sb00,sb01,sb02,sb03 .claude/skills/hardware-test/run_hw_tests.sh
GCAM_MVSDK_HW_CAMERA=sb01 .claude/skills/hardware-test/run_hw_tests.sh -k grab
```

Without capabilities: `sudo -E env "PATH=$PATH" .claude/skills/hardware-test/run_hw_tests.sh`
(the script passes `-p no:cacheprovider` so no root-owned cache is written).

Variables:

| Variable | Effect |
|---|---|
| `GCAM_MVSDK_HW_TEST=1` | Enables the tests (the script sets it) |
| `GCAM_MVSDK_HW_EXPECT` | Comma-separated user-set names that must all be present |
| `GCAM_MVSDK_HW_CAMERA` | Serial or name for the grab test (default: first camera that opens) |
| `GCAM_MVSDK_HW_RENAME_SN` | Serial of a camera whose name may be rewritten (rename test runs only then) |

## What each test expects

| Test | Expects | Changes the camera? |
|---|---|---|
| `test_sdk_version` | `CameraSdkGetVersionString` returns a non-empty version | No |
| `test_enumerate_finds_expected_names` | At least one camera; every name in `GCAM_MVSDK_HW_EXPECT` present; serials non-empty; GigE IPs well formed | No (opens each camera briefly) |
| `test_grab_mono8_shape_and_view_matches_copy` | Mono8 output, continuous trigger, one frame within 3 s; `view()` equals `to_numpy(process=False)` byte for byte; `to_numpy()` is uint8 with shape (height, width) of the current resolution | Session settings only (output format, trigger mode); nothing is saved |
| `test_rename_round_trip` | Writes "hwtest", reads it back, restores the original name | Yes: writes camera memory twice; only with `GCAM_MVSDK_HW_RENAME_SN` |

## Safety rules

- Never set `GCAM_MVSDK_HW_RENAME_SN` for a camera in production use without the user's consent;
  an interrupted run can leave the name "hwtest" (fix with `gcam-mvsdk-py rename <SN> <name>`).
- Tests never call `save_parameter`; do not add tests that persist settings.
- Restart the publishers after the run if you stopped them.

## Interpreting failures

| Failure | Meaning |
|---|---|
| "no cameras discovered" | Privileges, rp_filter, firewall, or cabling: use the camera-discovery skill |
| Skip "every camera is in use" | Another process holds the cameras (Step 1) |
| `MvTimeout` in the grab test | Packet size above the NIC MTU, rp_filter, firewall, or a trigger mode left on |
| Shape mismatch | Resolution changed between reading and grabbing, or an ROI is active |
| `view()` differs from the raw copy | Buffer released too early: a real bug in `Frame` lifetime handling |
