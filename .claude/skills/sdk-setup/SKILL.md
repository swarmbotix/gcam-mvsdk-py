---
name: sdk-setup
description: Fetch, re-fetch, or verify the HuaTeng MVSDK used by gcam-mvsdk-py, point GCAM_MVSDK_DIR at an existing copy, and diagnose SdkNotFound ("HuaTeng MVSDK library not found"). Use when the SDK is missing, the loader cannot find libMVSDK.so, a checksum fails, or the vendor URL stopped working.
---

# SDK setup and SdkNotFound diagnosis

The vendor library is never in the repository. If `GCAM_MVSDK_DIR` is set, it is the only
place searched (`lib/<arch>`, `lib`, then the directory itself); a directory without the library
is an error, never silently replaced by another copy. Otherwise the first existing file wins:

1. `./vendor/<version>/lib/<arch>` (relative to the current directory)
2. `<sdk home>/<version>/lib/<arch>`; sdk home is `$GCAM_MVSDK_HOME`, else the path recorded in
   `<venv>/gcam-mvsdk-py-home` by install.bash, else `~/.gcam-mvsdk`
3. System library directories, then the dynamic loader by bare name

## Step 1: see what the loader sees

Run with the interpreter that has gcam-mvsdk-py installed:

```bash
python .claude/skills/sdk-setup/sdk_status.py          # every candidate, marked found/missing
python .claude/skills/sdk-setup/sdk_status.py --load   # also open it and print the SDK version
gcam-mvsdk-py doctor                                   # full diagnosis, including the SDK section
```

## Step 2: install or re-install

| Situation | Command |
|---|---|
| End user, normal install | `bash install.bash` (or `gcam-mvsdk-py setup`) |
| Working in this repository | `./scripts/fetch-sdk.sh` (SDK into `./vendor/<version>/`) |
| No internet on the machine | Download elsewhere, then `gcam-mvsdk-py setup --from <archive>` or `bash install.bash --from <archive>` |
| Re-fetch a damaged install | `gcam-mvsdk-py setup --force` (add `--dest ./vendor` in the repo) |
| Other location | `gcam-mvsdk-py setup --dest <dir>`; the SDK lands in `<dir>/<version>/` |

`setup` checks `Content-Length` against `sdk-manifest.toml`, downloads over plain HTTP,
verifies SHA-256, and extracts `include/`, `lib/`, `tools/GeConfigCmd/`, and the udev rules.
A checksum mismatch aborts without installing anything; never bypass it for the Linux SDK.

## Step 3: verify an archive by hand

```bash
sha256sum 'linuxSDK_V2.1.0.49(202511141513).tar.gz'
grep -A6 'os      = "linux"' sdk-manifest.toml      # compare with the recorded sha256 and size
```

## Step 4: use an SDK that is already extracted

```bash
export GCAM_MVSDK_DIR="/path/to/linuxSDK_V2.1.0.49(202511141513)"   # the directory containing lib/
gcam-mvsdk-py doctor
```

## SdkNotFound causes

| Clue in the error or in sdk_status.py | Cause | Fix |
|---|---|---|
| Every candidate missing | Not installed | Step 2 |
| "GCAM_MVSDK_DIR is set to ..., which does not exist" or "holds no MVSDK library" | The variable points at the wrong directory; nothing else is searched while it is set | Point it at the directory that contains `lib/`, or `unset GCAM_MVSDK_DIR` |
| `lib/x64` missing but `lib/arm` present (or similar) | Wrong architecture directory | `export GCAM_MVSDK_ARCH=<dir>` (e.g. `arm_softfp`) |
| "wrong ELF class" | 32-bit interpreter with 64-bit library or the reverse | Use a matching interpreter, or set `GCAM_MVSDK_ARCH` |
| "failed to map segment" or permission denied | SDK on a `noexec` mount | Install to a normal filesystem (`--dest`) |
| Works as user, fails under `sudo` | `sudo` resets `HOME` and the environment | `sudo -E ...`, or set `GCAM_MVSDK_DIR` |
| Works in the repo, fails elsewhere | Only `./vendor/` holds the SDK, which is cwd-relative | Install to the SDK home or set `GCAM_MVSDK_DIR` |
| Installed under a custom `GCAM_MVSDK_HOME` | A different interpreter than install.bash's venv is used | Export `GCAM_MVSDK_HOME`, or use `~/.gcam-mvsdk/py-venv/bin/python3` |

## The vendor URL stopped working

HTTP 404 or "file size changed" means HuaTeng uploaded a new build (the attachment id in the URL
changes). Get the new link from http://huatengvision.com/download/1/, download it, and add a
release to `sdk-manifest.toml` as described in CLAUDE.md ("SDK source and new releases"),
identically in `../gcam-mvsdk-rs`. Until then, `--from` with a verified archive works.
