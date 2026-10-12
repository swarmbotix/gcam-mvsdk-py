# gcam-mvsdk-py

`gcam-mvsdk-py` is a command-line tool and a Python library for HuaTeng Vision (华腾威视) GigE and
USB industrial cameras on Linux. It finds the cameras on your network, renames them, sets their IP
address, reads and changes exposure, and grabs frames as NumPy arrays.

It does this by loading the vendor's own SDK library (`libMVSDK.so`) at run time through `ctypes`.
That library is not in this repository or in the Python package, because HuaTeng does not permit
redistribution. The installer downloads it from HuaTeng's website, checks its SHA-256 against a value
recorded here, and stores it in your home directory. The package itself is pure Python.

## Quick start

```bash
git clone https://github.com/swarmbotix/gcam-mvsdk-py
cd gcam-mvsdk-py
bash install.bash
gcam-mvsdk-py list
```

Takes about two minutes: one to create the environment and install NumPy, one to download the SDK.
The installer prints each step as it goes and can be run again at any time; it skips what is
already done.

Supported: Linux on x86_64, aarch64, armv7l and i686 with Python 3.9 or newer. Tested on Ubuntu
24.04 x86_64 with Python 3.9 and 3.13. Other distributions work when `python3` with the `venv`
module is available. The installer refuses to run on macOS and Windows; see
[Windows and macOS](#windows-and-macos).

## What install.bash does to your computer

Read this section if you want to know exactly what changes before you run the script. Everything
below is also printed by the script while it runs, and `bash install.bash --help` lists the options.

### Steps, in order

1. **Checks the platform.** Reads `/etc/os-release` and `uname -m`. Stops if the CPU architecture
   has no SDK build.
2. **Checks Python.** Needs `python3` 3.9 or newer with the `venv` and `ensurepip` modules. On
   Debian and Ubuntu those modules are a separate package; if missing, the script offers
   `sudo apt-get install -y python3-venv python3-pip`. Nothing else is installed with `apt`. Your
   system Python is never modified.
3. **Creates a private Python environment** at `~/.gcam-mvsdk/py-venv/`, with
   `python3 -m venv --copies`. "Copies" means the interpreter inside it is a real file, not a link
   to `/usr/bin/python3`; this matters for step 6. Nothing is installed into the system Python or
   into any environment you already have.
4. **Installs the package into that environment** with `pip`, together with NumPy. Dependencies
   come from PyPI. With `--with-opencv`, OpenCV is added as well.
5. **Links the command.** Creates `~/.local/bin/gcam-mvsdk-py` as a symbolic link to the command
   inside the private environment. `~/.local/bin` is on `PATH` by default on Ubuntu once it exists;
   if it is not on yours, the script prints the line to add.
6. **Downloads the vendor SDK.** Fetches
   `http://huatengvision.com/attachment/down/13/linuxSDK_V2.1.0.49%28202511141513%29.tar.gz`
   (58 MB, plain HTTP), compares the SHA-256 with the value in `sdk-manifest.toml`, and refuses the
   file if it differs. Extracts it to `~/.gcam-mvsdk/2.1.0.49/`. With `--from FILE` it uses an
   archive you downloaded yourself instead, verified the same way.
7. **Privileges for camera discovery (asks first).** GigE cameras answer a broadcast that Linux only
   allows from a process with the `CAP_NET_RAW` capability. The script shows the command
   `sudo setcap cap_net_raw,cap_net_admin+ep ~/.gcam-mvsdk/py-venv/bin/python3` and asks before
   running it. This is why step 3 used `--copies`: the capability lands on the private interpreter
   file only, never on `/usr/bin/python3`. Saying no is fine; see [Privileges](#privileges-and-network)
   for what that means and for the alternative.
8. **USB udev rules (only with `--udev`).** Copies the vendor's two rule files to
   `/etc/udev/rules.d/` (converted to Unix line endings) and reloads udev. Skip this unless you have
   USB cameras.
9. **Verifies.** Runs `gcam-mvsdk-py doctor` and `gcam-mvsdk-py list`, then prints where everything
   went.

All `sudo` commands are collected and shown together before the first prompt. `--no-sudo` prints
them and never runs them. Without a terminal attached (for example in a Dockerfile), the script
answers "no" to every question unless `--yes` is given.

### Files written

| Path | What | Size |
|---|---|---|
| `~/.gcam-mvsdk/py-venv/` | The private Python environment: interpreter copy, `pip`, NumPy, this package | about 190 MB (more with OpenCV) |
| `~/.local/bin/gcam-mvsdk-py` | Symbolic link to `~/.gcam-mvsdk/py-venv/bin/gcam-mvsdk-py` | 0 |
| `~/.gcam-mvsdk/2.1.0.49/` | The vendor SDK: `lib/<arch>/libMVSDK.so`, `include/`, `tools/GeConfigCmd`, udev rules, `manifest.json` | about 75 MB for all architectures |
| `~/.gcam-mvsdk/udev-rules/` | Line-ending-converted copies of the udev rules (only with `--udev`) | tiny |
| `~/.cache/pip/` | pip's normal download cache | varies |

`~/.gcam-mvsdk` is shared with the Rust tool `gcam-mvsdk-rs`; installing both downloads the SDK
once.

### System-wide changes

Only these, each one only with your explicit `sudo` confirmation:

| Change | Why | Undo |
|---|---|---|
| `setcap cap_net_raw,cap_net_admin+ep` on `~/.gcam-mvsdk/py-venv/bin/python3` | GigE discovery broadcast | `sudo setcap -r ~/.gcam-mvsdk/py-venv/bin/python3`, or delete the environment |
| `apt-get install python3-venv python3-pip` (Debian/Ubuntu, only if `venv` is missing) | Needed to create the private environment | `sudo apt-get remove python3-venv` (harmless to keep) |
| `apt-get install libcap2-bin` (only if `setcap` itself is missing) | Provides the `setcap` command | `sudo apt-get remove libcap2-bin` |
| Copy `88-mvusb.rules`, `99-mvusb.rules` to `/etc/udev/rules.d/` (only with `--udev`) | USB camera access without root | `sudo rm /etc/udev/rules.d/88-mvusb.rules /etc/udev/rules.d/99-mvusb.rules` |

### What it never does

- Does not install anything into the system Python or `pip install` outside the private environment.
- Does not write to `/usr`, `/lib`, `/opt`, or `/etc` (except the udev rules above, on request).
- Does not run `ldconfig`, install a kernel module, start a service, or add a cron job.
- Does not change `sysctl` settings or the firewall. `doctor` prints those commands; you run them.
- Does not modify `~/.bashrc`, `~/.profile`, or any shell configuration. If `~/.local/bin` is
  missing from `PATH`, it prints the line and leaves the edit to you.
- Does not touch Docker, Rust, or any other project on the machine.
- Does not need the repository after installation. You may delete the clone; the installed command
  does not reference it (unless you used `--dev`).

### Network access

Two destinations: `pypi.org` and `files.pythonhosted.org` (NumPy and build tools), and
`huatengvision.com` (the SDK, plain HTTP, which is why the checksum check is mandatory). No
telemetry, no other hosts. For a machine without internet access see
[Air-gapped install](#air-gapped-install).

## After installation: how it works

**Finding the command.** Typing `gcam-mvsdk-py` makes your shell search the directories in `PATH`
for a file with that name. It is the link in `~/.local/bin`, which points into the private
environment, so the right Python and the right packages are used no matter which Python your shell
would otherwise pick. Being inside the repository directory does not matter; the shell never looks
there. If `~/.local/bin` did not exist before the install, open a new terminal so that your shell
profile adds it to `PATH`.

**Finding the SDK.** The command then loads `libMVSDK.so`. It looks, in order, at `$GCAM_MVSDK_DIR`
(if set, nowhere else), `./vendor/<version>/` (developer checkouts), `~/.gcam-mvsdk/<version>/`,
then the system library path. The installer also records the SDK home inside the private
environment, so the installed command finds it even if you set `GCAM_MVSDK_HOME` only for the
install. `gcam-mvsdk-py doctor` shows which one is in use.

**Finding cameras.** `list` sends a GigE Vision discovery broadcast on every network card and
waits for replies. This reaches only cameras on the same network segment as a card in your
machine, and only when the process may open raw sockets (step 7 above, or `sudo -E`). USB cameras
are found through the udev rules.

## Commands

| Command | What it does |
|---|---|
| `gcam-mvsdk-py list [--json]` | Every camera: user-set name, model, serial number, camera and host IP/MAC. |
| `gcam-mvsdk-py rename <SN> <NAME>` | Store a name in the camera (at most 31 characters, none of `\ / : * ? " < > \|`). Survives power cycles. |
| `gcam-mvsdk-py setip <MAC> <IP> <MASK> <GW>` | Give a GigE camera a permanent IP address, even when it is on the wrong subnet. |
| `gcam-mvsdk-py info <NAME or SN> [--json]` | Exposure, gain, resolution, frame rate, trigger, packet sizes. |
| `gcam-mvsdk-py grab <NAME or SN> [-n N] [-o DIR]` | Save N frames as PNG files (default 1, into the current directory). |
| `gcam-mvsdk-py doctor` | Check the SDK, permissions, `rp_filter`, firewall, and subnets, and print the fix for each. |
| `gcam-mvsdk-py setup [--from FILE]` | Download or reinstall the SDK (the installer already ran it). |

`gcam-mvsdk-py <command> --help` lists every option. Exit codes: 0 success, 1 error, 2 invalid
arguments, 3 SDK not found.

## Use from Python

```python
import gcam_mvsdk_py

sdk = gcam_mvsdk_py.load()                       # finds the SDK and initializes it
for dev in sdk.enumerate():
    print(dev.serial, dev.model, dev.port_type)

with sdk.open("sb01") as cam:                    # user-set name or serial number
    cam.exposure_us = 5000                       # microseconds; turns auto exposure off
    cam.output_format = gcam_mvsdk_py.Mono8
    cam.play()
    with cam.grab(timeout_ms=1000) as frame:     # the SDK buffer is returned on exit
        img = frame.to_numpy()                   # independent copy, shape (height, width)

print(img.shape, img.dtype, img.mean())
```

Two ways to run this:

- With the installed environment: `~/.gcam-mvsdk/py-venv/bin/python3 my_script.py`. That
  interpreter already has the package, NumPy, and (if granted) the raw-socket capability.
- In your own environment: `pip install /path/to/gcam-mvsdk-py` (or the wheel from `dist/`), then
  run as usual. Your interpreter then needs `CAP_NET_RAW` or `sudo -E` for GigE discovery, exactly
  like the command.

Errors raise `gcam_mvsdk_py.MvError`, which carries the SDK status code and message; a timed-out
`grab` raises `gcam_mvsdk_py.MvTimeout`.

## Privileges and network

GigE discovery needs four things. `gcam-mvsdk-py doctor` checks each one and prints the command
for your machine.

```bash
# 1. Raw-socket capability for the private Python (install.bash offers this)
sudo setcap cap_net_raw,cap_net_admin+ep ~/.gcam-mvsdk/py-venv/bin/python3

# 2. Reverse-path filtering off, now and after reboot (replace enp4s0 with your camera NIC)
sudo sysctl -w net.ipv4.conf.all.rp_filter=0 net.ipv4.conf.enp4s0.rp_filter=0
printf 'net.ipv4.conf.all.rp_filter=0\nnet.ipv4.conf.default.rp_filter=0\nnet.ipv4.conf.enp4s0.rp_filter=0\n' \
  | sudo tee /etc/sysctl.d/60-gige-camera.conf

# 3. Firewall: trust the camera NIC
sudo ufw allow in on enp4s0                                   # ufw
sudo firewall-cmd --zone=trusted --change-interface=enp4s0 --permanent && sudo firewall-cmd --reload   # firewalld

# 4. Host NIC and cameras in the same subnet (example: 192.168.3.0/24)
sudo nmcli con mod "<connection name>" ipv4.method manual ipv4.addresses 192.168.3.10/24
sudo nmcli con up "<connection name>"
gcam-mvsdk-py setip <camera MAC> 192.168.3.252 255.255.255.0 0.0.0.0

# USB cameras instead: vendor udev rules
gcam-mvsdk-py setup --udev
```

**What step 1 means, and its one drawback.** `setcap` marks one file so that it may open raw
network sockets without being root. Here that file is the Python interpreter inside the private
environment. Because an interpreter runs whatever script it is given, any script started with
`~/.gcam-mvsdk/py-venv/bin/python3` gets the same capability, not only this tool. The exposure is
limited: the capability applies to that one file (never to `/usr/bin/python3`), the environment
contains only this package and NumPy, and `CAP_NET_RAW` allows sniffing and crafting packets on
your own network cards, not root access. If you are not comfortable with that, say no at step 7 and
use `sudo -E ~/.local/bin/gcam-mvsdk-py list` instead; `-E` keeps `GCAM_MVSDK_HOME` and `HOME` so
the SDK is still found. The Rust tool `gcam-mvsdk-rs` is a single binary, so its capability covers
only that program; prefer it where this matters. Inside Docker, use `network_mode: host` and
`privileged: true`.

The capability is lost whenever the interpreter file is replaced. After upgrading the system Python,
run `bash install.bash` again so the private copy and its capability are refreshed.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `gcam-mvsdk-py: command not found` | `~/.local/bin` is not on `PATH` in this terminal | Open a new terminal; or `export PATH="$HOME/.local/bin:$PATH"` and add it to `~/.bashrc`. Being in the repository directory does not help. |
| `list` says "No cameras found" | Missing raw-socket permission, `rp_filter` not 0, firewall, camera on another subnet or another NIC, no power or link | Run `gcam-mvsdk-py doctor` and apply the fixes it prints (see [Privileges](#privileges-and-network)) |
| `SdkNotFound` / "HuaTeng MVSDK library not found" | SDK not installed, deleted, or for another CPU architecture | `gcam-mvsdk-py setup`, or `export GCAM_MVSDK_DIR=<extracted SDK>`; on soft-float ARM `export GCAM_MVSDK_ARCH=arm_softfp` |
| `status 32774` (0x8006) or `status -45` when opening | The camera is held by another process or host (a publisher, an old container, a viewer) | Stop the holder: `docker ps`, then `docker stop <id>`; close other viewers; retry |
| `status -13` (I/O error) when opening | Same as above, or the camera is not reachable on the current subnet | Stop other holders; `gcam-mvsdk-py doctor`; move the camera with `setip` |
| `Permission denied` or `Operation not permitted` | GigE: the Python lacks the raw-socket permission. USB: udev rules missing | GigE: the `setcap` command above, or `sudo -E`. USB: `gcam-mvsdk-py setup --udev`, then replug |
| `grab` times out (`status -12`) | Packets larger than the NIC MTU, `rp_filter`, firewall | Apply the network fixes; for jumbo frames set the NIC MTU to 9000 |
| Download fails, or the size or checksum does not match | The vendor moved or replaced the file | Download from http://huatengvision.com/download/1/ and use `--from`. A checksum mismatch is never overridden. |

## Air-gapped install

On a machine with internet access:

```bash
git clone https://github.com/swarmbotix/gcam-mvsdk-py && cd gcam-mvsdk-py
python3 -m pip install build && python3 -m build                # creates dist/*.whl
python3 -m pip download dist/*.whl -d wheelhouse                 # numpy etc.; same Python version and CPU as the target
curl -O 'http://huatengvision.com/attachment/down/13/linuxSDK_V2.1.0.49%28202511141513%29.tar.gz'
sha256sum linuxSDK_V2.1.0.49*.tar.gz   # must be 9624d193a908d94a9850400346cf1ab8095437a040e381b2fd39029b0183dd8a
```

Copy the directory to the target machine, then:

```bash
PIP_NO_INDEX=1 PIP_FIND_LINKS="$PWD/wheelhouse" \
  bash install.bash --wheel --from 'linuxSDK_V2.1.0.49(202511141513).tar.gz'
```

If the SDK download fails during a normal install, the installer prints the same download link and
the `--from` command.

## Uninstall

```bash
bash install.bash --uninstall
```

Removes the private environment (and with it the capability) and the command link, then asks before
deleting the downloaded SDK (kept by default, because `gcam-mvsdk-rs` uses the same files). To
remove the rest by hand:

```bash
sudo rm -f /etc/udev/rules.d/88-mvusb.rules /etc/udev/rules.d/99-mvusb.rules   # only if --udev was used
sudo rm -f /etc/sysctl.d/60-gige-camera.conf                                     # only if you added it
```

After that the machine is as it was.

## Environment variables

| Variable | Effect |
|---|---|
| `GCAM_MVSDK_HOME` | Where `install.bash` and `setup` put the environment and the SDK, and where the command looks. Default `~/.gcam-mvsdk`. Shared with `gcam-mvsdk-rs`. The installed command remembers the value used at install time. |
| `GCAM_MVSDK_DIR` | One extracted SDK directory (the one containing `lib/`). When set, it is the only place searched. |
| `GCAM_MVSDK_ARCH` | Overrides the `lib/<arch>` directory name (`x64`, `x86`, `arm64`, `arm`, `arm_softfp`). Needed on soft-float ARM boards. |
| `GCAM_MVSDK_HW_TEST` | `1` enables the hardware tests (developers). |

To keep everything somewhere other than `~/.gcam-mvsdk`:

```bash
GCAM_MVSDK_HOME=/data/gcam-mvsdk bash install.bash
```

To use an SDK that is already extracted somewhere:

```bash
export GCAM_MVSDK_DIR="/opt/linuxSDK_V2.1.0.49(202511141513)"
gcam-mvsdk-py doctor
```

## Windows and macOS

`install.bash` supports Linux only. On Windows: `pip install` this directory (or the wheel), then
`gcam-mvsdk-py setup --allow-unverified` to fetch and unpack the vendor installer, run that
installer as administrator (it installs the GigE driver), and set `GCAM_MVSDK_DIR` to the installed
SDK directory. macOS is not supported yet.

## For developers

- Design and roadmap: [PLAN_PYTHON_WRAPPER.md](PLAN_PYTHON_WRAPPER.md)
- Working on this repository (build, test, conventions): [CLAUDE.md](CLAUDE.md)
- `bash install.bash --dev` installs editable with test tools and puts the SDK in `./vendor/`
  instead of your home.

## License

MIT for this package. The HuaTeng MVSDK is proprietary, is not included in this repository or
package, and is subject to HuaTeng Vision's terms.
