"""``gcam-mvsdk-py doctor``: diagnose SDK presence and host configuration.

Checks: SDK library and installed version, raw-socket privileges of the
running interpreter, ``rp_filter``, firewall state, NIC addresses and MTU, and
whether discovered GigE cameras share a subnet with the host NIC.
"""

from __future__ import annotations

import ipaddress
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from . import __version__
from ._loader import (
    ENV_DIR,
    ENV_DIR_HINT,
    ENV_HOME,
    _venv_marker_home,
    describe_search,
    detect_arch,
    env_dir_problem,
    env_sdk_dir,
    find_library,
    library_names,
    sdk_home,
)

CAP_NET_ADMIN = 12
CAP_NET_RAW = 13
GVCP_PORT = 3956

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"


@dataclass
class Interface:
    name: str
    addresses: List[ipaddress.IPv4Interface] = field(default_factory=list)
    mtu: Optional[int] = None
    up: Optional[bool] = None


@dataclass
class Report:
    lines: List[Tuple[str, str]] = field(default_factory=list)
    failures: int = 0
    warnings: int = 0

    def add(self, status: str, text: str) -> None:
        self.lines.append((status, text))
        if status == FAIL:
            self.failures += 1
        elif status == WARN:
            self.warnings += 1
        tag = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]", INFO: "[INFO]"}.get(status, "[    ]")
        first, *rest = text.split("\n")
        print("%s %s" % (tag, first))
        for line in rest:
            print("       %s" % line)

    def section(self, title: str) -> None:
        print("\n== %s" % title)


# ---------------------------------------------------------------------------
# Privileges
# ---------------------------------------------------------------------------


def effective_capabilities(status_text: Optional[str] = None) -> Optional[int]:
    """Effective capability mask of this process (Linux), or ``None`` if unknown."""
    if status_text is None:
        try:
            status_text = Path("/proc/self/status").read_text()
        except OSError:
            return None
    for line in status_text.splitlines():
        if line.startswith("CapEff:"):
            return int(line.split()[1], 16)
    return None


def has_capability(bit: int, status_text: Optional[str] = None) -> bool:
    caps = effective_capabilities(status_text)
    return caps is not None and bool(caps & (1 << bit))


def is_root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0


def has_raw_socket_privilege() -> bool:
    """True if this process can open raw sockets (root or CAP_NET_RAW)."""
    if sys.platform == "win32":
        return True
    return is_root() or has_capability(CAP_NET_RAW)


def interpreter_setcap_advice() -> Tuple[str, str]:
    """Return ``(status, text)`` describing how to grant CAP_NET_RAW to this interpreter."""
    exe = sys.executable
    real = os.path.realpath(exe)
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    cmd = "sudo setcap cap_net_raw,cap_net_admin+ep %s" % real
    if not in_venv:
        return (
            WARN,
            "This interpreter (%s) is not a virtual environment. Do not grant capabilities to a\n"
            "system interpreter. Run `bash install.bash` from the gcam-mvsdk-py checkout: it creates\n"
            "~/.gcam-mvsdk/py-venv with a private copy of Python and offers the setcap step. By hand:\n"
            "  python3 -m venv --copies ~/.gcam-mvsdk/py-venv && ~/.gcam-mvsdk/py-venv/bin/pip install gcam-mvsdk-py\n"
            "  sudo setcap cap_net_raw,cap_net_admin+ep ~/.gcam-mvsdk/py-venv/bin/python3" % real,
        )
    prefix = os.path.realpath(sys.prefix)
    if not (real == prefix or real.startswith(prefix + os.sep)):
        return (
            WARN,
            "The venv interpreter %s is a symlink to %s, which other programs share;\n"
            "setcap would apply to that file. Recreate the venv with --copies:\n"
            "  python3 -m venv --copies %s\n"
            "then run: sudo setcap cap_net_raw,cap_net_admin+ep %s/bin/python3" % (exe, real, sys.prefix, sys.prefix),
        )
    return (INFO, "Grant raw-socket access to this venv's interpreter once:\n  %s" % cmd)


# ---------------------------------------------------------------------------
# Network interfaces
# ---------------------------------------------------------------------------


def _interfaces_from_ip_json(text: str) -> List[Interface]:
    out: List[Interface] = []
    for entry in json.loads(text):
        iface = Interface(entry.get("ifname", "?"), mtu=entry.get("mtu"))
        flags = entry.get("flags", [])
        iface.up = "UP" in flags if flags else None
        for addr in entry.get("addr_info", []):
            if addr.get("family") == "inet":
                iface.addresses.append(ipaddress.IPv4Interface("%s/%s" % (addr["local"], addr["prefixlen"])))
        out.append(iface)
    return out


def _interfaces_from_ioctl() -> List[Interface]:  # pragma: no cover - fallback path
    import fcntl

    siocgifaddr, siocgifnetmask = 0x8915, 0x891B
    out: List[Interface] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, name in socket.if_nameindex():
            iface = Interface(name)
            packed = struct.pack("256s", name.encode()[:15])
            try:
                addr = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), siocgifaddr, packed)[20:24])
                mask = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), siocgifnetmask, packed)[20:24])
                iface.addresses.append(ipaddress.IPv4Interface("%s/%s" % (addr, mask)))
            except OSError:
                pass
            try:
                iface.mtu = int(Path("/sys/class/net/%s/mtu" % name).read_text().strip())
            except (OSError, ValueError):
                pass
            out.append(iface)
    finally:
        sock.close()
    return out


def list_interfaces() -> List[Interface]:
    """IPv4 interfaces of this host (Linux); empty list elsewhere."""
    if not sys.platform.startswith("linux"):
        return []
    ip = shutil.which("ip")
    if ip:
        try:
            res = subprocess.run([ip, "-j", "-4", "addr", "show"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                return _interfaces_from_ip_json(res.stdout.decode())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        return _interfaces_from_ioctl()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# rp_filter and firewall
# ---------------------------------------------------------------------------


def read_rp_filter(name: str, root: Path = Path("/proc/sys/net/ipv4/conf")) -> Optional[int]:
    try:
        return int((root / name / "rp_filter").read_text().strip())
    except (OSError, ValueError):
        return None


def effective_rp_filter(all_value: Optional[int], iface_value: Optional[int]) -> Optional[int]:
    """The kernel applies max(conf/all, conf/<iface>)."""
    values = [v for v in (all_value, iface_value) if v is not None]
    return max(values) if values else None


def firewall_status() -> List[Tuple[str, str]]:
    findings: List[Tuple[str, str]] = []
    ufw_conf = Path("/etc/ufw/ufw.conf")
    if ufw_conf.is_file():
        try:
            enabled = any(l.strip().upper() == "ENABLED=YES" for l in ufw_conf.read_text().splitlines())
        except OSError:
            enabled = False
        if enabled:
            findings.append((WARN, "ufw is enabled. Allow the camera NIC, for example:\n"
                                   "  sudo ufw allow in on <camera-nic>\n"
                                   "or at least UDP %d plus the stream ports; the vendor recommends the firewall off on that NIC." % GVCP_PORT))
        else:
            findings.append((OK, "ufw is installed but disabled"))
    fwcmd = shutil.which("firewall-cmd")
    if fwcmd:
        try:
            res = subprocess.run([fwcmd, "--state"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5)
            if b"running" in res.stdout and b"not running" not in res.stdout:
                findings.append((WARN, "firewalld is running; put the camera NIC in the trusted zone:\n"
                                       "  sudo firewall-cmd --zone=trusted --change-interface=<camera-nic> --permanent && sudo firewall-cmd --reload"))
            else:
                findings.append((OK, "firewalld is not running"))
        except (OSError, subprocess.SubprocessError):
            pass
    if not findings:
        findings.append((INFO, "No ufw or firewalld found. If nftables/iptables rules exist, allow UDP %d and the\n"
                               "GigE stream ports on the camera NIC (inspecting them requires root)." % GVCP_PORT))
    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _same_subnet(camera_ip: str, host_ip: str, host_mask: str) -> Optional[bool]:
    try:
        net = ipaddress.IPv4Network("%s/%s" % (host_ip, host_mask), strict=False)
        return ipaddress.IPv4Address(camera_ip) in net
    except ValueError:
        return None


def run(sdk_path: Optional[str] = None) -> int:
    report = Report()
    print("gcam-mvsdk-py %s doctor" % __version__)
    print("Python %s at %s" % (platform.python_version(), sys.executable))
    print("Platform %s %s, SDK arch directory: %s, library: %s" % (
        platform.system(), platform.machine(), detect_arch(), " / ".join(library_names())))

    # -- SDK ----------------------------------------------------------------
    report.section("SDK")
    if os.environ.get(ENV_HOME, "").strip():
        home_source = "from $%s" % ENV_HOME
    elif _venv_marker_home() is not None:
        home_source = "recorded by install.bash in %s" % sys.prefix
    else:
        home_source = "default"
    report.add(INFO, "SDK home: %s (%s)" % (sdk_home(), home_source))
    location = None
    if sdk_path:
        report.add(INFO, "Using --sdk %s" % sdk_path)
    else:
        location = find_library()
        env_root = env_sdk_dir()
        if location is None and env_root is not None:
            report.add(FAIL, env_dir_problem(env_root) + " Searched:\n" + "\n".join(describe_search()) +
                       "\n" + ENV_DIR_HINT)
        elif location is None:
            report.add(FAIL, "MVSDK library not found. Searched:\n" + "\n".join(describe_search()) +
                       "\nFix: gcam-mvsdk-py setup   (or export GCAM_MVSDK_DIR=<extracted SDK>)")
        else:
            report.add(OK, "Library: %s  [%s]" % (location.path, location.origin))
            if env_root is not None:
                report.add(INFO, "%s is set, so ./vendor, the SDK home and the system path are not searched." % ENV_DIR)
            if location.sdk_root is not None:
                manifest = location.sdk_root / "manifest.json"
                if manifest.is_file():
                    try:
                        info = json.loads(manifest.read_text(encoding="utf-8"))
                        report.add(OK, "Installed by setup: version %s, sha256 %s, installed %s" % (
                            info.get("version"), str(info.get("sha256", ""))[:16] + "...", info.get("installed_at")))
                    except ValueError:
                        report.add(WARN, "%s is not valid JSON" % manifest)
                else:
                    report.add(INFO, "No manifest.json in %s (SDK not installed by setup)" % location.sdk_root)

    sdk = None
    if sdk_path or location is not None:
        try:
            from .api import load

            sdk = load(sdk_path)
            report.add(OK, "Loaded and initialized; SDK reports version %s" % sdk.version())
            if sdk.missing_functions:
                report.add(INFO, "Functions not exported by this build: %s" % ", ".join(sdk.missing_functions))
        except Exception as exc:  # noqa: BLE001 - report every failure mode
            report.add(FAIL, "Loading the SDK failed: %s" % exc)

    # -- privileges ---------------------------------------------------------
    report.section("Privileges")
    if sys.platform == "win32":  # pragma: no cover - Windows only
        try:
            import ctypes

            admin = bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            admin = False
        report.add(INFO, "Administrator: %s. GigE cameras need the vendor installer's filter driver;\n"
                         "the DLL alone is not sufficient." % ("yes" if admin else "no"))
    elif sys.platform.startswith("linux"):
        if is_root():
            report.add(OK, "Running as root")
        elif has_capability(CAP_NET_RAW):
            report.add(OK, "CAP_NET_RAW is effective for this interpreter")
        else:
            report.add(WARN, "Not root and CAP_NET_RAW is not effective; GigE discovery may find no cameras.")
            status, text = interpreter_setcap_advice()
            report.add(status, text)
            report.add(INFO, "Alternatives: `sudo -E %s -m gcam_mvsdk_py list` (keeps GCAM_MVSDK_DIR and HOME),\n"
                             "or in Docker: network_mode: host and privileged: true." % sys.executable)
    else:
        report.add(INFO, "Privilege checks are implemented for Linux and Windows only")

    # -- network --------------------------------------------------------------
    interfaces = list_interfaces()
    if sys.platform.startswith("linux"):
        report.section("Network")
        all_rp = read_rp_filter("all")
        bad_rp = []
        for iface in interfaces:
            if iface.name == "lo" or not iface.addresses:
                continue
            eff = effective_rp_filter(all_rp, read_rp_filter(iface.name))
            addrs = ", ".join(str(a) for a in iface.addresses)
            mtu = " mtu %s" % iface.mtu if iface.mtu else ""
            state = "" if iface.up is None else (" up" if iface.up else " DOWN")
            report.add(INFO, "%s: %s%s%s rp_filter=%s" % (iface.name, addrs, mtu, state, eff))
            if eff not in (0, None):
                bad_rp.append(iface.name)
        if not interfaces:
            report.add(WARN, "Could not list network interfaces")
        if bad_rp:
            report.add(WARN, "rp_filter is not 0 on %s; the vendor requires 0 for GigE discovery:\n"
                             "  sudo sysctl -w net.ipv4.conf.all.rp_filter=0\n"
                             "  sudo sysctl -w net.ipv4.conf.<camera-nic>.rp_filter=0\n"
                             "Persist the settings in /etc/sysctl.d/." % ", ".join(bad_rp))
        elif interfaces:
            report.add(OK, "rp_filter is 0 on every addressed interface")
        for status, text in firewall_status():
            report.add(status, text)

    # -- cameras --------------------------------------------------------------
    report.section("Cameras")
    if sdk is None:
        report.add(INFO, "Skipped: SDK not loaded")
    else:
        try:
            devices = sdk.enumerate()
        except Exception as exc:  # noqa: BLE001
            devices = []
            report.add(FAIL, "Enumeration failed: %s" % exc)
        if not devices:
            hint = ""
            if sys.platform.startswith("linux") and not has_raw_socket_privilege():
                hint = "\nLikely cause: missing CAP_NET_RAW (see Privileges above)."
            report.add(WARN, "No cameras discovered. Check power, cable, a static host IP in the camera subnet,\n"
                             "rp_filter, and the firewall." + hint)
        for dev in devices:
            label = "%s %s (%s)" % (dev.model, dev.serial, dev.port_type)
            if not dev.is_gige:
                report.add(OK, "%s" % label)
                continue
            try:
                ip = dev.gige_ip()
            except Exception as exc:  # noqa: BLE001
                report.add(WARN, "%s: GigE IP unavailable: %s" % (label, exc))
                continue
            same = _same_subnet(ip.camera_ip, ip.host_ip, ip.host_mask)
            if same is False:
                report.add(WARN, "%s: camera %s/%s is not in the subnet of host NIC %s/%s.\n"
                                 "Fix: gcam-mvsdk-py setip <camera MAC> <IP in %s/%s> <mask> <gateway>" % (
                                     label, ip.camera_ip, ip.camera_mask, ip.host_ip, ip.host_mask, ip.host_ip, ip.host_mask))
            else:
                report.add(OK, "%s: camera %s, host NIC %s/%s" % (label, ip.camera_ip, ip.host_ip, ip.host_mask))

    print("\nSummary: %d failure(s), %d warning(s)" % (report.failures, report.warnings))
    return 1 if report.failures else 0
