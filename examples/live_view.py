#!/usr/bin/env python3
"""Live view of one HuaTeng camera in an OpenCV window, with recording.

    ~/.gcam-mvsdk/py-venv/bin/python3 examples/live_view.py sb01    # installed environment
    python3 examples/live_view.py <serial>                           # with gcam-mvsdk-py[view]

Keys: r starts a recording, c stops it early, q or Esc quits; closing the window also quits.
A recording saves ``rate_hz`` images per second for ``duration_s`` seconds (examples/record.yaml)
into ``<data_dir>/<YYYYMMDD_HHMMSS>_<camera>/0.png, 1.png, ...``; ``data_dir`` defaults to
``<sdk home>/data``. Needs a display (DISPLAY must be set).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional

try:
    import cv2
except ImportError:
    sys.exit("OpenCV with GUI support is required: pip install 'gcam-mvsdk-py[view]'")

import gcam_mvsdk_py
from gcam_mvsdk_py._loader import sdk_home

DEFAULT_CONFIG = Path(__file__).resolve().with_name("record.yaml")
DEFAULT_DURATION_S = 30.0
DEFAULT_RATE_HZ = 5.0
CONFIG_KEYS = ("duration_s", "rate_hz", "data_dir")


class RecordConfig:
    """Recording options from ``record.yaml``; missing keys take the defaults."""

    def __init__(self, duration_s: float = DEFAULT_DURATION_S, rate_hz: float = DEFAULT_RATE_HZ,
                 data_dir: Optional[Path] = None):
        self.duration_s = float(duration_s)
        self.rate_hz = float(rate_hz)
        self.data_dir = data_dir
        for name in ("duration_s", "rate_hz"):
            value = getattr(self, name)
            if not (value > 0 and value != float("inf")):
                raise ValueError("%s must be a positive number, got %r" % (name, value))

    def __eq__(self, other):
        return isinstance(other, RecordConfig) and (self.duration_s, self.rate_hz, self.data_dir) == (
            other.duration_s, other.rate_hz, other.data_dir)

    def __repr__(self):
        return "RecordConfig(duration_s=%r, rate_hz=%r, data_dir=%r)" % (self.duration_s, self.rate_hz, self.data_dir)

    @property
    def interval_s(self) -> float:
        return 1.0 / self.rate_hz

    @classmethod
    def parse(cls, text: str) -> "RecordConfig":
        """Parse YAML text; unknown keys and non-positive numbers raise ``ValueError``."""
        import yaml  # PyYAML, part of the view extra

        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError("record.yaml must hold a mapping of options")
        unknown = sorted(set(data) - set(CONFIG_KEYS))
        if unknown:
            raise ValueError("unknown option(s) %s; accepted: %s" % (", ".join(unknown), ", ".join(CONFIG_KEYS)))
        for name in ("duration_s", "rate_hz"):
            if name in data and (isinstance(data[name], bool) or not isinstance(data[name], (int, float))):
                raise ValueError("%s must be a number, got %r" % (name, data[name]))
        data_dir = data.get("data_dir")
        return cls(data.get("duration_s", DEFAULT_DURATION_S), data.get("rate_hz", DEFAULT_RATE_HZ),
                   Path(str(data_dir)).expanduser() if data_dir is not None else None)

    @classmethod
    def load(cls, path: Path) -> "tuple[RecordConfig, bool]":
        """Read ``path``; a missing file gives the defaults and ``False``."""
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls(), False
        try:
            return cls.parse(text), True
        except ValueError as exc:
            raise ValueError("%s: %s" % (path, exc)) from None

    def resolved_data_dir(self) -> Path:
        """``data_dir`` from the file, else ``<sdk home>/data``."""
        return self.data_dir if self.data_dir is not None else sdk_home() / "data"


# What a key press asks for, given whether a recording is running.
IGNORE, START, STOP, QUIT = "ignore", "start", "stop", "quit"


def action_for_key(key: int, recording: bool) -> str:
    """r/R start a recording, c/C stop one, q or Esc quit; anything else is ignored."""
    if key in (ord("r"), ord("R")):
        return IGNORE if recording else START
    if key in (ord("c"), ord("C")):
        return STOP if recording else IGNORE
    if key in (ord("q"), 27):
        return QUIT
    return IGNORE


def session_dir_name(local_time: str, camera: str) -> str:
    """``<YYYYMMDD_HHMMSS>_<camera>`` with the camera name reduced to file-safe characters."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", camera)
    return "%s_%s" % (local_time, safe or "camera")


class Session:
    """One recording: decides which frames to save and when to stop."""

    def __init__(self, directory: Path, now: float, cfg: RecordConfig):
        self.dir = directory
        self.started = now
        self.next_due = now
        self.interval = cfg.interval_s
        self.duration = cfg.duration_s
        self.saved = 0

    def next_path(self, now: float) -> Optional[Path]:
        """Path for a frame that arrived at ``now`` when one is due; the first frame is always due."""
        if now < self.next_due:
            return None
        path = self.dir / ("%d.png" % self.saved)
        self.saved += 1
        # Keep the schedule anchored to the start; after a stall, continue from now instead of bursting.
        self.next_due = max(self.next_due + self.interval, now)
        return path

    def expired(self, now: float) -> bool:
        return now - self.started >= self.duration

    def elapsed(self, now: float) -> float:
        return now - self.started

    def finish(self) -> None:
        print("recording stopped: %d images in %s" % (self.saved, self.dir))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Show live frames from one camera with cv2.imshow; "
                                            "r records, c stops, q quits.")
    p.add_argument("camera", nargs="?", help="user-set name or serial (default: the only camera present)")
    p.add_argument("--exposure-us", type=float, default=5000.0, help="exposure time in microseconds (default 5000)")
    p.add_argument("--mtu", type=int, help="largest GigE packet size in bytes, e.g. 1500 or 9000 (jumbo frames)")
    p.add_argument("--window", default="gcam-mvsdk-py live view", help="window title")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                   help="recording options (duration_s, rate_hz, data_dir); default examples/record.yaml")
    return p.parse_args(argv)


def put_text(img, text: str, line: int) -> None:
    cv2.putText(img, text, (10, 30 + 40 * line), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 255, 2, cv2.LINE_AA)


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg, found = RecordConfig.load(args.config)
    if not found:
        print("%s not found; recording with defaults" % args.config)
    data_dir = cfg.resolved_data_dir()
    print("recording: %g images/s for %g s into %s" % (cfg.rate_hz, cfg.duration_s, data_dir))

    sdk = gcam_mvsdk_py.load()
    target = args.camera
    if target is None:
        devices = sdk.enumerate()
        if len(devices) != 1:
            print("%d cameras found; name one. See: gcam-mvsdk-py list" % len(devices), file=sys.stderr)
            return 2
        target = devices[0]
    session: Optional[Session] = None
    with sdk.open(target) as cam:  # CameraUnInit runs when the block exits, also on errors
        camera_name = cam.user_name or cam.device.serial
        cam.output_format = gcam_mvsdk_py.Mono8
        cam.trigger_mode = gcam_mvsdk_py.TRIGGER_CONTINUOUS
        cam.exposure_us = args.exposure_us
        if args.mtu:
            cam.gige_packet_size = args.mtu  # largest advertised size that fits
        try:
            cap_hz = cam.frame_rate_hz  # configured frame-rate cap, read once; 0 = uncapped
            cap = "cap %d Hz" % cap_hz if cap_hz > 0 else "cap none"
        except gcam_mvsdk_py.MvError:
            cap = "cap unknown"
        cam.play()
        cv2.namedWindow(args.window, cv2.WINDOW_NORMAL)
        stamps, shown = deque(), False
        while True:
            try:
                with cam.grab(timeout_ms=1000) as frame:
                    img = frame.to_numpy()
            except gcam_mvsdk_py.MvTimeout:
                print("no frame within 1000 ms; waiting", file=sys.stderr)
                img = None
            if img is not None:
                now = time.perf_counter()  # one stamp per frame returned by grab
                stamps.append(now)
                while now - stamps[0] > 1.0:
                    stamps.popleft()
                fps = (len(stamps) - 1) / (now - stamps[0]) if len(stamps) > 1 else 0.0
                # Save before the overlay is drawn, so the files hold the plain camera image.
                rec_text = None
                if session is not None:
                    path = session.next_path(now)
                    if path is not None and not cv2.imwrite(str(path), img):
                        raise OSError("could not write %s" % path)
                    if session.expired(now):
                        session.finish()
                        session = None
                    else:
                        rec_text = "REC %d saved  %.1f s" % (session.saved, session.elapsed(now))
                put_text(img, "measured %.1f fps  %s" % (fps, cap), 0)
                if rec_text:
                    put_text(img, rec_text, 1)
                cv2.imshow(args.window, img)
                shown = True
            key = cv2.waitKey(1) & 0xFF
            action = action_for_key(key, session is not None)
            if action == START:
                directory = data_dir / session_dir_name(time.strftime("%Y%m%d_%H%M%S"), camera_name)
                directory.mkdir(parents=True, exist_ok=True)
                print("recording to %s" % directory)
                session = Session(directory, time.perf_counter(), cfg)
            elif action == STOP:
                session.finish()
                session = None
            elif action == QUIT:
                break
            if shown and cv2.getWindowProperty(args.window, cv2.WND_PROP_VISIBLE) < 1:
                break  # window closed with the mouse
    if session is not None:
        session.finish()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (gcam_mvsdk_py.GcamMvsdkError, ValueError, OSError) as exc:  # SDK, camera, config or file errors
        sys.exit("error: %s" % exc)
    except KeyboardInterrupt:
        sys.exit(130)
