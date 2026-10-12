"""The built-in PNG encoder used when OpenCV is not installed."""

from __future__ import annotations

import struct
import zlib

import numpy as np
import pytest

from gcam_mvsdk_py import _png


def decode(data: bytes):
    assert data[:8] == _png.PNG_SIGNATURE
    pos, chunks = 8, []
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF
        chunks.append((kind, body))
        pos += 12 + length
    assert chunks[0][0] == b"IHDR" and chunks[-1][0] == b"IEND"
    width, height, depth, ctype = struct.unpack(">IIBB", chunks[0][1][:10])
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    return width, height, depth, ctype, raw


@pytest.mark.parametrize(
    "shape, dtype, ctype, depth, channels",
    [
        ((3, 5), np.uint8, 0, 8, 1),
        ((3, 5, 1), np.uint8, 0, 8, 1),
        ((3, 5, 3), np.uint8, 2, 8, 3),
        ((3, 5, 4), np.uint8, 6, 8, 4),
        ((3, 5), np.uint16, 0, 16, 1),
    ],
)
def test_round_trip(shape, dtype, ctype, depth, channels):
    rng = np.random.default_rng(0)
    img = rng.integers(0, np.iinfo(dtype).max, size=shape, dtype=dtype)
    w, h, d, t, raw = decode(_png.encode_png(img))
    assert (w, h, d, t) == (shape[1], shape[0], depth, ctype)
    stride = shape[1] * channels * (depth // 8) + 1
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(shape[0], stride)
    assert (rows[:, 0] == 0).all()
    payload = rows[:, 1:].tobytes()
    expected = img.astype(">u2").tobytes() if dtype == np.uint16 else np.ascontiguousarray(img).tobytes()
    assert payload == expected


def test_rejects_unsupported_input():
    with pytest.raises(ValueError):
        _png.encode_png(np.zeros((2, 2), dtype=np.float32))
    with pytest.raises(ValueError):
        _png.encode_png(np.zeros((2, 2, 2), dtype=np.uint8))
    with pytest.raises(ValueError):
        _png.encode_png(np.zeros((0, 2), dtype=np.uint8))


def test_save_image_builtin_converts_bgr(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_cv2(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("no cv2")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_cv2)
    img = np.zeros((1, 1, 3), dtype=np.uint8)
    img[0, 0] = (10, 20, 30)  # B, G, R
    path = tmp_path / "x.png"
    assert _png.save_image(path, img, bgr=True) == "builtin"
    _, _, _, _, raw = decode(path.read_bytes())
    assert raw[1:4] == bytes([30, 20, 10])
