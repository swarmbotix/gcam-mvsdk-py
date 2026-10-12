"""Image saving for ``gcam-mvsdk-py grab``.

Uses OpenCV when the ``opencv`` extra is installed, otherwise a small PNG
encoder built on :mod:`zlib` (8-bit and 16-bit grayscale, RGB, RGBA).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Union

import numpy as np

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def encode_png(image: np.ndarray, compression: int = 6) -> bytes:
    """Encode ``image`` as PNG bytes.

    Accepted shapes: ``(h, w)`` or ``(h, w, 1)`` grayscale, ``(h, w, 3)`` RGB,
    ``(h, w, 4)`` RGBA; dtype ``uint8`` or ``uint16``.
    """
    arr = np.asarray(image)
    if arr.ndim == 3 and arr.shape[2] == 1:
        arr = arr[:, :, 0]
    if arr.ndim == 2:
        color_type = 0
    elif arr.ndim == 3 and arr.shape[2] == 3:
        color_type = 2
    elif arr.ndim == 3 and arr.shape[2] == 4:
        color_type = 6
    else:
        raise ValueError("unsupported image shape %r" % (arr.shape,))
    if arr.dtype == np.uint8:
        bit_depth = 8
    elif arr.dtype == np.uint16:
        bit_depth = 16
        arr = arr.astype(">u2")  # PNG stores samples big-endian
    else:
        raise ValueError("unsupported dtype %s (use uint8 or uint16)" % arr.dtype)
    height, width = arr.shape[:2]
    if height == 0 or width == 0:
        raise ValueError("image is empty")
    rows = np.ascontiguousarray(arr).reshape(height, -1).view(np.uint8)
    # Filter type 0 (None) for every scanline.
    raw = np.empty((height, rows.shape[1] + 1), dtype=np.uint8)
    raw[:, 0] = 0
    raw[:, 1:] = rows
    header = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    return b"".join(
        [
            PNG_SIGNATURE,
            _chunk(b"IHDR", header),
            _chunk(b"IDAT", zlib.compress(raw.tobytes(), compression)),
            _chunk(b"IEND", b""),
        ]
    )


def write_png(path: Union[str, Path], image: np.ndarray) -> None:
    """Write ``image`` (grayscale or RGB order) with the built-in encoder."""
    Path(path).write_bytes(encode_png(image))


def have_opencv() -> bool:
    try:
        import cv2  # noqa: F401
    except Exception:
        return False
    return True


def save_image(path: Union[str, Path], image: np.ndarray, bgr: bool = False) -> str:
    """Save ``image`` as PNG; return the backend used (``"opencv"`` or ``"builtin"``).

    ``bgr`` states the channel order of 3- and 4-channel input.
    """
    arr = np.asarray(image)
    color = arr.ndim == 3 and arr.shape[2] in (3, 4)
    try:
        import cv2
    except Exception:
        cv2 = None
    if cv2 is not None:
        out = arr
        if color and not bgr:
            out = arr[:, :, [2, 1, 0, 3][: arr.shape[2]]]
        if not cv2.imwrite(str(path), np.ascontiguousarray(out)):
            raise OSError("OpenCV could not write %s" % path)
        return "opencv"
    out = arr
    if color and bgr:
        out = arr[:, :, [2, 1, 0, 3][: arr.shape[2]]]
    write_png(path, out)
    return "builtin"
