#!/usr/bin/env python3
"""Live view of one HuaTeng camera in an OpenCV window.

    ~/.gcam-mvsdk/py-venv/bin/python3 examples/live_view.py sb01    # installed environment
    python3 examples/live_view.py <serial>                           # with gcam-mvsdk-py[view]

Press q or Esc, or close the window, to quit. Needs a display (DISPLAY must be set).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import deque

try:
    import cv2
except ImportError:
    sys.exit("OpenCV with GUI support is required: pip install 'gcam-mvsdk-py[view]'")

import gcam_mvsdk_py


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Show live frames from one camera with cv2.imshow.")
    p.add_argument("camera", nargs="?", help="user-set name or serial (default: the only camera present)")
    p.add_argument("--exposure-us", type=float, default=5000.0, help="exposure time in microseconds (default 5000)")
    p.add_argument("--mtu", type=int, help="largest GigE packet size in bytes, e.g. 1500 or 9000 (jumbo frames)")
    p.add_argument("--window", default="gcam-mvsdk-py live view", help="window title")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    sdk = gcam_mvsdk_py.load()
    target = args.camera
    if target is None:
        devices = sdk.enumerate()
        if len(devices) != 1:
            print("%d cameras found; name one. See: gcam-mvsdk-py list" % len(devices), file=sys.stderr)
            return 2
        target = devices[0]
    with sdk.open(target) as cam:  # CameraUnInit runs when the block exits, also on errors
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
                cv2.putText(img, "measured %.1f fps  %s" % (fps, cap), (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 255, 2,
                            cv2.LINE_AA)
                cv2.imshow(args.window, img)
                shown = True
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if shown and cv2.getWindowProperty(args.window, cv2.WND_PROP_VISIBLE) < 1:
                break  # window closed with the mouse
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except gcam_mvsdk_py.GcamMvsdkError as exc:  # SDK missing, camera not found or busy
        sys.exit("error: %s" % exc)
    except KeyboardInterrupt:
        sys.exit(130)
