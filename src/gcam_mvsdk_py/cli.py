"""Command-line interface: ``gcam-mvsdk-py <command>``.

Commands: setup, list, rename, setip, info, set, grab, doctor. Only the standard
library (argparse) is used for parsing; commands that talk to cameras import
the numpy-based API lazily so ``--help`` and ``setup`` stay fast.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import __version__
from ._errors import DeviceNotFound, GcamMvsdkError, MvError, SdkNotFound

PROG = "gcam-mvsdk-py"
FORMATS = ("auto", "mono8", "bgr8", "rgb8")

_BUSY_HINT = (
    "The camera is held by another process or host (a publisher, an old container, or a viewer). "
    "Stop it (for example `docker ps`, then stop the holder) and retry."
)
STATUS_HINTS = {
    -45: _BUSY_HINT,  # CAMERA_STATUS_ACCESS_DENY
    -18: _BUSY_HINT,  # CAMERA_STATUS_DEVICE_IS_OPENED
    0x8006: _BUSY_HINT,  # 32774, CAMERA_AIA_ACCESS_DENIED (GigE control channel taken)
    -13: "I/O error talking to the camera: it may be held by another process or host, or sit on a "
    "different subnet than the host NIC. Run `gcam-mvsdk-py doctor`.",
    -12: "Timed out waiting for the camera. Check the packet size against the NIC MTU, rp_filter, and the firewall.",
}

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NO_SDK = 3


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def normalize_mac(text: str) -> str:
    """Return ``aa:bb:cc:dd:ee:ff`` for any common MAC notation, or raise ``ValueError``."""
    digits = re.sub(r"[^0-9a-fA-F]", "", text).lower()
    if len(digits) != 12 or re.sub(r"[0-9a-fA-F:\-.\s]", "", text):
        raise ValueError("invalid MAC address: %r" % text)
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def _mac_arg(text: str) -> str:
    try:
        return normalize_mac(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _ipv4_arg(text: str) -> str:
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid IPv4 address: %r" % text) from exc


def _netmask_arg(text: str) -> str:
    try:
        return str(ipaddress.IPv4Network("0.0.0.0/%s" % text).netmask)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid netmask: %r" % text) from exc


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("not an integer: %r" % text) from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive: %r" % text)
    return value


def _non_negative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("not an integer: %r" % text) from exc
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more: %r" % text)
    return value


def _on_off(text: str) -> bool:
    value = text.strip().lower()
    if value not in ("on", "off"):
        raise argparse.ArgumentTypeError("expected on or off, not %r" % text)
    return value == "on"


def _camera_name_arg(text: str) -> str:
    bad = sorted(set(text) & set('\\/:*?"<>|'))
    if bad:
        raise argparse.ArgumentTypeError("name must not contain %s" % " ".join(bad))
    if not text:
        raise argparse.ArgumentTypeError("name must not be empty")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Configure and test HuaTeng (MVSDK) GigE and USB industrial cameras.",
        epilog=(
            "The vendor SDK is loaded from $GCAM_MVSDK_DIR when it is set (nowhere else);\n"
            "otherwise from ./vendor/<version>, ~/.gcam-mvsdk/<version>, then the system path.\n"
            "Run `%s setup` to download and install it." % PROG
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version="%s %s" % (PROG, __version__))
    parser.add_argument(
        "--sdk",
        metavar="PATH",
        help="vendor library file or SDK directory to use instead of the search path",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    p = sub.add_parser("setup", help="download, verify, and extract the vendor SDK")
    p.add_argument("--from", dest="source", metavar="FILE", help="install from a local archive instead of downloading")
    p.add_argument("--version", dest="sdk_version", metavar="V", help="SDK version from sdk-manifest.toml (default: newest)")
    p.add_argument("--dest", metavar="DIR", help="parent directory for <version>/ (default: ~/.gcam-mvsdk)")
    p.add_argument("--udev", action="store_true", help="offer to install the USB udev rules with sudo (Linux)")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--force", action="store_true", help="reinstall even if the version is already installed")
    p.add_argument("--keep-archive", action="store_true", help="keep the downloaded archive")
    p.add_argument("--allow-unverified", action="store_true", help="accept an archive without a recorded SHA-256")
    p.add_argument("--manifest", metavar="FILE", help="alternative sdk-manifest.toml")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")

    p = sub.add_parser("list", help="list cameras (user name, model, SN, IP/MAC)")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.add_argument("--no-open", action="store_true", help="do not open cameras to read their user-set names")

    p = sub.add_parser("rename", help="write a user-set name (DeviceUserID) to a camera's memory")
    p.add_argument("serial", metavar="SN", help="serial number of the camera")
    p.add_argument("name", metavar="NAME", type=_camera_name_arg, help="new user-set name (at most 31 bytes)")

    p = sub.add_parser("setip", help="set a GigE camera's persistent IP, identified by MAC")
    p.add_argument("mac", metavar="MAC", type=_mac_arg, help="camera MAC address")
    p.add_argument("ip", metavar="IP", type=_ipv4_arg)
    p.add_argument("mask", metavar="MASK", type=_netmask_arg)
    p.add_argument("gateway", metavar="GW", type=_ipv4_arg)

    p = sub.add_parser("info", help="dump a camera's settings and capabilities")
    p.add_argument("target", metavar="NAME_OR_SN", help="user-set name or serial number")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = sub.add_parser("set", help="change frame rate, exposure, or auto exposure; --save keeps them")
    p.add_argument("target", metavar="NAME_OR_SN", help="user-set name or serial number")
    p.add_argument("--frame-rate", type=_non_negative_int, metavar="HZ", help="frame-rate cap in Hz (0 = uncapped)")
    p.add_argument("--exposure-us", type=float, metavar="US", help="manual exposure time in microseconds (turns auto exposure off)")
    p.add_argument("--auto-exposure", type=_on_off, metavar="on|off", help="switch auto exposure on or off")
    p.add_argument("--save", type=str.upper, choices=("A", "B", "C", "D"),
                   help="save the camera's settings to this parameter group (persistent)")

    p = sub.add_parser("grab", help="save frames as PNG")
    p.add_argument("target", metavar="NAME_OR_SN", help="user-set name or serial number")
    p.add_argument("-n", "--count", type=_positive_int, default=1, help="number of frames (default 1)")
    p.add_argument("-o", "--output-dir", default=".", metavar="DIR", help="output directory (default .)")
    p.add_argument("--timeout-ms", type=_positive_int, default=2000, help="per-frame timeout (default 2000)")
    p.add_argument("--exposure-us", type=float, help="manual exposure time in microseconds")
    p.add_argument("--format", choices=FORMATS, default="auto", help="ISP output format (default: mono8 for mono sensors, else bgr8)")

    sub.add_parser("doctor", help="check SDK presence, privileges, rp_filter, firewall, NIC subnets")
    return parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _err(msg: str) -> None:
    print("%s: error: %s" % (PROG, msg), file=sys.stderr)


def _load(args: argparse.Namespace) -> Any:
    from .api import load

    return load(args.sdk)


def _no_camera_hint() -> str:
    from ._doctor import has_raw_socket_privilege

    hint = "No cameras found. Check cable, power, and that the host NIC is on the same subnet."
    if sys.platform.startswith("linux") and not has_raw_socket_privilege():
        hint += (
            "\nThis process is neither root nor holds CAP_NET_RAW, which GigE discovery needs."
            "\nRun `%s doctor` for the exact fix." % PROG
        )
    return hint


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except (MvError, GcamMvsdkError) as exc:
        return "(error: %s)" % getattr(exc, "message", exc)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_setup(args: argparse.Namespace) -> int:
    from . import setup_cmd

    return setup_cmd.run(
        source=args.source,
        version=args.sdk_version,
        dest=args.dest,
        udev=args.udev,
        force=args.force,
        assume_yes=args.yes,
        keep_archive=args.keep_archive,
        allow_unverified=args.allow_unverified,
        manifest=args.manifest,
        quiet=args.quiet,
    )


def collect_device_rows(sdk: Any, read_names: bool = True) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, dev in enumerate(sdk.enumerate()):
        row: Dict[str, Any] = {"index": index, "user_name": None}
        row.update(dev.to_dict())
        if read_names:
            try:
                with sdk.open(dev) as cam:
                    row["user_name"] = cam.user_name
            except MvError as exc:
                row["open_error"] = exc.message
        if dev.is_gige:
            try:
                row.update(dev.gige_ip()._asdict())
                row.update(dev.gige_mac()._asdict())
            except MvError as exc:
                row["gige_error"] = exc.message
        rows.append(row)
    return rows


def cmd_list(args: argparse.Namespace) -> int:
    sdk = _load(args)
    rows = collect_device_rows(sdk, read_names=not args.no_open)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return EXIT_OK
    if not rows:
        print(_no_camera_hint())
        return EXIT_OK
    print("\nFound %d camera(s)\n" % len(rows))
    line = "-" * 70
    for row in rows:
        if row.get("user_name") is not None:
            user = row["user_name"] or "<empty>"
        elif "open_error" in row:
            user = "<could not open: %s>" % row["open_error"]
        else:
            user = "<not read>"
        print(line)
        print("[%d]" % row["index"])
        print("    User-set name : %s" % user)
        print("    Product       : %s" % row["product"])
        print("    Serial number : %s" % row["serial"])
        print("    Port type     : %s" % row["port_type"])
        if "camera_ip" in row:
            print("    Camera        : IP %s  Mask %s  GW %s  MAC %s" % (
                row["camera_ip"], row["camera_mask"], row["camera_gateway"], row.get("camera_mac", "?")))
            print("    Host NIC      : IP %s  Mask %s  GW %s  MAC %s" % (
                row["host_ip"], row["host_mask"], row["host_gateway"], row.get("host_mac", "?")))
        elif "gige_error" in row:
            print("    (GigE info unavailable: %s)" % row["gige_error"])
    print(line)
    return EXIT_OK


def cmd_rename(args: argparse.Namespace) -> int:
    sdk = _load(args)
    devices = sdk.enumerate()
    matches = [d for d in devices if d.serial == args.serial]
    if not matches:
        known = ", ".join(d.serial for d in devices) or "none"
        raise DeviceNotFound("no camera with serial number %r (found: %s)" % (args.serial, known))
    dev = matches[0]
    with sdk.open(dev) as cam:
        old = cam.user_name
        cam.user_name = args.name
        new = cam.user_name
    print("%s: user-set name %r -> %r (stored in camera memory)" % (dev.serial, old, new))
    if new != args.name:
        print("warning: the camera reports %r after writing %r" % (new, args.name), file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def cmd_setip(args: argparse.Namespace) -> int:
    network = ipaddress.IPv4Network("%s/%s" % (args.ip, args.mask), strict=False)
    if args.gateway != "0.0.0.0" and ipaddress.IPv4Address(args.gateway) not in network:
        print("warning: gateway %s is outside %s" % (args.gateway, network), file=sys.stderr)
    sdk = _load(args)
    devices = sdk.enumerate()
    seen: List[str] = []
    target = None
    for dev in devices:
        if not dev.is_gige:
            continue
        try:
            mac = normalize_mac(dev.gige_mac().camera_mac)
        except (MvError, ValueError):
            continue
        seen.append("%s (SN %s)" % (mac, dev.serial))
        if mac == args.mac:
            target = dev
    if target is None:
        raise DeviceNotFound("no GigE camera with MAC %s (found: %s)" % (args.mac, ", ".join(seen) or "none"))
    sdk.gige_set_ip(target, args.ip, args.mask, args.gateway, persistent=True)
    print("Camera %s (SN %s) set to IP %s mask %s gateway %s (persistent)." % (
        args.mac, target.serial, args.ip, args.mask, args.gateway))
    print("Run `%s list` to confirm; some models apply the change after a power cycle." % PROG)
    return EXIT_OK


def collect_info(cam: Any) -> Dict[str, Any]:
    """Settings and capabilities of an open camera; failed reads become ``"(error: ...)"``."""
    from . import _ffi

    dev = cam.device
    cap = cam.capability()
    data: Dict[str, Any] = {
        "user_name": _safe(lambda: cam.user_name),
        "serial": dev.serial,
        "model": dev.model,
        "product": dev.product,
        "port_type": dev.port_type,
        "sensor_type": dev.sensor_type,
        "firmware_version": _safe(lambda: cam.firmware_version),
        "sensor": "monochrome" if cap.sIspCapacity.bMonoSensor else "color",
        "max_width": cap.sResolutionRange.iWidthMax,
        "max_height": cap.sResolutionRange.iHeightMax,
        "exposure_us": _safe(lambda: cam.exposure_us),
        "exposure_range_us": _safe(lambda: list(cam.exposure_range_us())),
        "auto_exposure": _safe(lambda: cam.auto_exposure),
        "line_time_us": _safe(lambda: cam.exposure_line_time_us),
        "analog_gain": _safe(lambda: cam.analog_gain),
        "analog_gain_x": _safe(lambda: cam.analog_gain_x),
        "digital_gain_rgb": _safe(lambda: list(cam.digital_gain)),
        "resolution": _safe(lambda: list(cam.resolution)),
        "frame_rate_limit_hz": _safe(lambda: cam.frame_rate_hz),
        "frame_speed_index": _safe(lambda: cam.frame_speed),
        "frame_speeds": [list(x) for x in cam.frame_speeds()],
        "output_format": _safe(lambda: _ffi.media_type_name(cam.output_format)),
        "trigger_mode": _safe(lambda: cam.trigger_mode),
        "trigger_delay_us": _safe(lambda: cam.trigger_delay_us),
        "trigger_count": _safe(lambda: cam.trigger_count),
        "gamma": _safe(lambda: cam.gamma),
        "contrast": _safe(lambda: cam.contrast),
        "saturation": _safe(lambda: cam.saturation),
        "sharpness": _safe(lambda: cam.sharpness),
        "packet_sizes": [list(p) for p in cam.packet_sizes()],
        "packet_size_index": _safe(lambda: cam.gige_packet_index) if cap.iPackLenDesc > 0 else None,
        "resolutions": [list(r) for r in cam.resolutions()],
        "media_types": [[i, _ffi.media_type_name(t), d] for i, t, d in cam.media_types()],
        "trigger_modes": [list(t) for t in cam.trigger_modes()],
        "ext_trigger_capability": _safe(lambda: cam.ext_trigger_capability),
        "capability": cam.capability_summary(),
    }
    if dev.is_gige:
        data["gige"] = _safe(lambda: dict(dev.gige_ip()._asdict(), **dev.gige_mac()._asdict()))
    return data


def print_info(d: Dict[str, Any]) -> None:
    trigger_names = {0: "Continuous (free-run)", 1: "Software trigger", 2: "Hardware trigger"}
    print("Name: %s  SN: %s  Type: %s" % (d["user_name"], d["serial"], d["port_type"]))
    print("Model: %s  Product: %s  Sensor: %s  Firmware: %s" % (d["model"], d["product"], d["sensor_type"], d["firmware_version"]))

    print("\n-- Exposure / Shutter " + "-" * 30)
    exp = d["exposure_us"]
    if isinstance(exp, float) and exp > 0:
        print("  Exposure time : %.1f us  (%.3f ms)  ->  1/%.0f s" % (exp, exp / 1000.0, 1e6 / exp))
        print("  Max FPS from shutter alone: %.1f" % (1e6 / exp))
    else:
        print("  Exposure time : %s" % exp)
    ae = d["auto_exposure"]
    print("  Auto-exposure : %s" % (("ON" if ae else "OFF") if isinstance(ae, bool) else ae))
    rng = d["exposure_range_us"]
    if isinstance(rng, list):
        print("  Exposure range: %.1f - %.1f us  (step %.1f us)" % tuple(rng))
    lt = d["line_time_us"]
    if isinstance(lt, float):
        print("  Line time     : %.3f us" % lt)

    print("\n-- Gain " + "-" * 44)
    print("  Analog gain   : %s  (x%s)" % (d["analog_gain"], d["analog_gain_x"]))
    g = d["digital_gain_rgb"]
    if isinstance(g, list):
        print("  Digital gain  : R=%s  G=%s  B=%s" % tuple(g))

    print("\n-- Resolution / Rate " + "-" * 31)
    res = d["resolution"]
    print("  Current       : %s" % ("%d x %d" % tuple(res) if isinstance(res, list) else res))
    print("  Sensor max    : %d x %d" % (d["max_width"], d["max_height"]))
    print("  Frame-rate cap: %s Hz (0 = uncapped)" % d["frame_rate_limit_hz"])
    print("  Frame speed   : index %s of %s" % (d["frame_speed_index"], ", ".join("[%d] %s" % (i, s) for i, s in d["frame_speeds"]) or "none"))
    print("  Output format : %s" % d["output_format"])

    print("\n-- Trigger " + "-" * 41)
    print("  Mode          : %s" % trigger_names.get(d["trigger_mode"], d["trigger_mode"]))
    print("  Delay         : %s us" % d["trigger_delay_us"])
    print("  Count         : %s" % d["trigger_count"])

    print("\n-- Image Quality " + "-" * 35)
    print("  Gamma         : %s" % d["gamma"])
    print("  Contrast      : %s" % d["contrast"])
    print("  Saturation    : %s" % d["saturation"])
    print("  Sharpness     : %s" % d["sharpness"])

    print("\n-- Sensor " + "-" * 42)
    print("  Type          : %s" % d["sensor"].capitalize())
    if d["media_types"]:
        print("  Raw formats   : %s" % ", ".join("[%d] %s" % (i, n) for i, n, _ in d["media_types"]))
    if d["resolutions"]:
        print("  Preset sizes  : %s" % ", ".join("[%d] %dx%d" % (i, w, h) for i, w, h, _ in d["resolutions"]))

    if "capability" in d:
        print("\n-- Capability (what this model supports) " + "-" * 11)
        for key, value in d["capability"].items():
            print("  %-26s: %s" % (key, value))
        print("  %-26s: %s" % ("ext_trigger_capability", d.get("ext_trigger_capability")))

    if "gige" in d:
        print("\n-- GigE " + "-" * 44)
        gi = d["gige"]
        if isinstance(gi, dict):
            print("  Camera        : IP %s  Mask %s  GW %s  MAC %s" % (gi["camera_ip"], gi["camera_mask"], gi["camera_gateway"], gi["camera_mac"]))
            print("  Host NIC      : IP %s  Mask %s  GW %s  MAC %s" % (gi["host_ip"], gi["host_mask"], gi["host_gateway"], gi["host_mac"]))
        else:
            print("  %s" % gi)
        if d["packet_sizes"]:
            print("  Packet sizes  : %s (current index %s)" % (
                ", ".join("[%d] %d B" % (i, s) for i, s, _ in d["packet_sizes"]), d["packet_size_index"]))
    print()


def cmd_info(args: argparse.Namespace) -> int:
    sdk = _load(args)
    dev = sdk.find(args.target)
    with sdk.open(dev) as cam:
        data = collect_info(cam)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print_info(data)
    return EXIT_OK


def _on_off_text(value: Any) -> str:
    return ("on" if value else "off") if isinstance(value, bool) else str(value)


def cmd_set(args: argparse.Namespace) -> int:
    if args.exposure_us is not None and args.auto_exposure:
        _err("--exposure-us sets a manual exposure, which turns auto exposure off; do not combine it with --auto-exposure on")
        return EXIT_USAGE
    changing = args.frame_rate is not None or args.exposure_us is not None or args.auto_exposure is not None
    sdk = _load(args)
    dev = sdk.find(args.target)
    with sdk.open(dev) as cam:
        rate, exposure, auto = (_safe(lambda: cam.frame_rate_hz), _safe(lambda: cam.exposure_us),
                                _safe(lambda: cam.auto_exposure))
        if not changing:
            print("frame rate: %s Hz (0 = uncapped)" % rate)
            print("exposure: %s us" % exposure)
            print("auto exposure: %s" % _on_off_text(auto))
        if args.frame_rate is not None:
            cam.frame_rate_hz = args.frame_rate
            print("frame rate: %s Hz (was %s)" % (_safe(lambda: cam.frame_rate_hz), rate))
        if args.exposure_us is not None:
            cam.exposure_us = args.exposure_us  # also turns auto exposure off
            print("exposure: %s us (was %s)" % (_safe(lambda: cam.exposure_us), exposure))
        if args.auto_exposure is not None:
            cam.auto_exposure = args.auto_exposure
        if args.auto_exposure is not None or args.exposure_us is not None:
            print("auto exposure: %s (was %s)" % (_on_off_text(_safe(lambda: cam.auto_exposure)), _on_off_text(auto)))
        if args.save:
            cam.save_parameter(args.save)
            cam.load_parameter(args.save)  # make it the current group, which the next open loads
            print("Saved to parameter group %s (persistent); it is now the camera's current group." % args.save)
        elif changing:
            print("Not saved: the change stays in the camera's working settings (RAM) until saved; add --save A to keep it.")
    return EXIT_OK


def _file_label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "camera"


def cmd_grab(args: argparse.Namespace) -> int:
    from . import api
    from ._errors import MvTimeout
    from ._png import save_image

    sdk = _load(args)
    dev = sdk.find(args.target)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with sdk.open(dev) as cam:
        try:
            name = cam.user_name
        except MvError:
            name = ""
        prefix = "%s_%s" % (_file_label(name), _file_label(dev.serial)) if name else _file_label(dev.serial)
        if args.format == "auto":
            fmt = api.Mono8 if cam.is_mono else api.BGR8
        else:
            fmt = {"mono8": api.Mono8, "bgr8": api.BGR8, "rgb8": api.RGB8}[args.format]
        cam.output_format = fmt
        cam.trigger_mode = 0
        if args.exposure_us is not None:
            cam.exposure_us = args.exposure_us
        cam.play()
        saved = 0
        consecutive_timeouts = 0
        while saved < args.count:
            try:
                with cam.grab(timeout_ms=args.timeout_ms) as frame:
                    image = frame.to_numpy()
                    stamp = frame.timestamp
            except MvTimeout:
                consecutive_timeouts += 1
                if consecutive_timeouts >= 5:
                    _err("no frame within %d ms, 5 times in a row. Check packet size/MTU, firewall, "
                         "and rp_filter (`%s doctor`)." % (args.timeout_ms, PROG))
                    return EXIT_ERROR
                continue
            consecutive_timeouts = 0
            path = out_dir / ("%s_%04d.png" % (prefix, saved))
            backend = save_image(path, image, bgr=(fmt == api.BGR8))
            print("%s  %s %s  ts=%d  [%s]" % (path, "x".join(str(s) for s in image.shape), image.dtype, stamp, backend))
            saved += 1
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    from ._doctor import run

    return run(args.sdk)


COMMANDS: Dict[str, Callable[[argparse.Namespace], int]] = {
    "setup": cmd_setup,
    "list": cmd_list,
    "rename": cmd_rename,
    "setip": cmd_setip,
    "info": cmd_info,
    "set": cmd_set,
    "grab": cmd_grab,
    "doctor": cmd_doctor,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except SdkNotFound as exc:
        _err(str(exc))
        return EXIT_NO_SDK
    except DeviceNotFound as exc:
        _err(str(exc))
        return EXIT_ERROR
    except MvError as exc:
        _err(str(exc))
        hint = STATUS_HINTS.get(exc.status)
        if hint:
            print(hint, file=sys.stderr)
        return EXIT_ERROR
    except (GcamMvsdkError, ValueError, OSError) as exc:
        _err(str(exc))
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
