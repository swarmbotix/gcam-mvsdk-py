"""The safe layer, driven by an in-process fake of the vendor library.

The fake implements the C functions in Python with the same calling pattern
(ctypes buffers, ``byref`` out-parameters), so api.py is exercised end to end
without the SDK or a camera.
"""

from __future__ import annotations

import ctypes
import gc
import sys

import numpy as np
import pytest

from gcam_mvsdk_py import _ffi, api
from gcam_mvsdk_py._errors import (
    DeviceNotFound,
    GcamMvsdkError,
    MvError,
    MvTimeout,
    decode_c_string,
    error_from_status,
)
from gcam_mvsdk_py._loader import LibraryLocation

W, H = 4, 3


def _plain(fn):
    # ctypes.bind() sets attributes on the function objects; bound methods do
    # not accept attributes, plain functions do.
    return lambda *args: fn(*args)


class FakeLib:
    def __init__(self):
        self.devices = [
            {"sn": b"SN001", "friendly": b"MV-GE134GM", "port": b"NET-1000M-GigE", "name": "sb00"},
            {"sn": b"SN002", "friendly": b"MV-GE134GM", "port": b"NET-1000M-GigE", "name": "sb01"},
            {"sn": b"SN003", "friendly": "相机".encode("gbk"), "port": b"USB3.0", "name": "busy"},
        ]
        self.busy = {b"SN003"}
        self.open_handles = {}
        self.next_handle = 100
        self.uninit = []
        self.released = []
        self.calls = []
        self.timeout = False
        self.callback = None
        # The Windows SDK writes ISP output bottom-up (DIB/BMP row order); the Linux
        # SDK writes it top-down. Emulate the platform the tests run on.
        self.bottom_up = sys.platform == "win32"
        self.last_isp_dst = None
        self.isp_format = _ffi.CAMERA_MEDIA_TYPE_MONO8
        self.exposure = 1000.0
        self.ae = 1
        self.pack_index = 0
        self.frame = (ctypes.c_ubyte * (W * H))(*range(W * H))
        packs = [(0, 1440), (1, 4000), (2, 8000)]
        self.pack_desc = (_ffi.tSdkPackLength * len(packs))()
        for i, (idx, size) in enumerate(packs):
            self.pack_desc[i].iIndex = idx
            self.pack_desc[i].iPackSize = size
            self.pack_desc[i].acDescription = b"%d bytes" % size
        for name in _ffi.FUNCTIONS:
            impl = getattr(self, "_" + name, None)
            if impl is not None:
                setattr(self, name, _plain(impl))

    # helpers
    def _dev_for_handle(self, h):
        return self.open_handles[h]

    # library-level
    def _CameraSdkInit(self, lang):
        self.calls.append(("init", lang))
        return 0

    def _CameraGetErrorString(self, status):
        return b"fake message for %d" % status

    def _CameraSdkGetVersionString(self, buf):
        buf.value = b"2.1.0.49-fake"
        return 0

    def _CameraEnumerateDevice(self, array, count_ref):
        count = count_ref._obj
        n = min(count.value, len(self.devices))
        for i in range(n):
            d = self.devices[i]
            array[i].acSn = d["sn"]
            array[i].acFriendlyName = d["friendly"]
            array[i].acPortType = d["port"]
            array[i].acProductName = b"GE134"
            array[i].uInstance = i
        count.value = n
        return 0

    def _CameraInit(self, dev_ref, mode, team, handle_ref):
        sn = dev_ref._obj.acSn
        if sn in self.busy:
            return _ffi.CAMERA_STATUS_ACCESS_DENY
        h = self.next_handle
        self.next_handle += 1
        self.open_handles[h] = next(d for d in self.devices if d["sn"] == sn)
        handle_ref._obj.value = h
        return 0

    def _CameraUnInit(self, h):
        self.uninit.append(h)
        self.open_handles.pop(h, None)
        return 0

    def _CameraGetFriendlyName(self, h, buf):
        buf.value = self._dev_for_handle(h)["name"].encode("gbk")
        return 0

    def _CameraSetFriendlyName(self, h, buf):
        self._dev_for_handle(h)["name"] = decode_c_string(buf.raw)
        return 0

    def _CameraGigeGetIp(self, dev_ref, *bufs):
        values = [b"192.168.10.11", b"255.255.255.0", b"0.0.0.0", b"192.168.10.1", b"255.255.255.0", b"0.0.0.0"]
        for buf, v in zip(bufs, values):
            buf.value = v
        return 0

    def _CameraGigeGetMac(self, dev_ref, cam, host):
        cam.value = b"00-1A-2B-3C-4D-5E"
        host.value = b"AA-BB-CC-DD-EE-FF"
        return 0

    def _CameraGigeSetIp(self, dev_ref, ip, mask, gw, persistent):
        self.calls.append(("setip", dev_ref._obj.acSn, ip, mask, gw, persistent))
        return 0

    # camera
    def _CameraGetCapability(self, h, cap_ref):
        cap = cap_ref._obj
        cap.sIspCapacity.bMonoSensor = 1
        cap.sResolutionRange.iWidthMax = W
        cap.sResolutionRange.iHeightMax = H
        cap.pPackLenDesc = ctypes.cast(self.pack_desc, ctypes.POINTER(_ffi.tSdkPackLength))
        cap.iPackLenDesc = len(self.pack_desc)
        return 0

    def _CameraSetAeState(self, h, state):
        self.ae = state
        return 0

    def _CameraGetAeState(self, h, ref):
        ref._obj.value = self.ae
        return 0

    def _CameraSetExposureTime(self, h, value):
        self.exposure = value
        return 0

    def _CameraGetExposureTime(self, h, ref):
        ref._obj.value = self.exposure
        return 0

    def _CameraSetIspOutFormat(self, h, fmt):
        self.isp_format = fmt
        return 0

    def _CameraGetIspOutFormat(self, h, ref):
        ref._obj.value = self.isp_format
        return 0

    def _CameraSetFrameRate(self, h, hz):
        return _ffi.CAMERA_STATUS_SUCCESS if hz >= 0 else -6

    def _CameraSetTransPackLen(self, h, idx):
        self.pack_index = idx
        return 0

    def _CameraGetTransPackLen(self, h, ref):
        ref._obj.value = self.pack_index
        return 0

    def _CameraPlay(self, h):
        return 0

    def _CameraGetImageBuffer(self, h, head_ref, ptr_ref, timeout):
        if self.timeout:
            return _ffi.CAMERA_STATUS_TIME_OUT
        head = head_ref._obj
        head.iWidth, head.iHeight, head.uBytes = W, H, W * H
        head.uiMediaType = _ffi.CAMERA_MEDIA_TYPE_MONO8
        head.uiTimeStamp = 1234
        ptr_ref._obj.value = ctypes.addressof(self.frame)
        return 0

    def _CameraReleaseImageBuffer(self, h, ptr):
        self.released.append(ptr)
        return 0

    def _CameraImageProcess(self, h, src, dst, head_ref):
        # Simulated ISP: invert the image so processed output differs from raw, and
        # store the rows bottom-up when emulating the Windows SDK.
        self.last_isp_dst = dst
        raw = (ctypes.c_ubyte * (W * H)).from_address(src)
        out = (ctypes.c_ubyte * (W * H)).from_address(dst)
        for row in range(H):
            out_row = H - 1 - row if self.bottom_up else row
            for col in range(W):
                out[out_row * W + col] = 255 - raw[row * W + col]
        head_ref._obj.uiMediaType = self.isp_format
        head_ref._obj.uBytes = W * H
        return 0

    def _CameraSetCallbackFunction(self, h, cb, ctx, old):
        self.callback = cb
        return 0


@pytest.fixture
def fake():
    return FakeLib()


@pytest.fixture
def sdk(fake):
    return api.Sdk(fake, LibraryLocation("/fake/libMVSDK.so", "test"))


def test_init_calls_sdk_init_in_english(fake, sdk):
    assert ("init", _ffi.SDK_LANGUAGE_ENGLISH) in fake.calls
    assert sdk.version() == "2.1.0.49-fake"
    assert sdk.raw is fake


def test_enumerate_and_device_fields(sdk):
    devices = sdk.enumerate()
    assert [d.serial for d in devices] == ["SN001", "SN002", "SN003"]
    assert devices[0].model == "MV-GE134GM" and devices[0].product == "GE134"
    assert devices[0].is_gige and not devices[2].is_gige
    assert devices[2].friendly_name == "相机"  # GBK fallback
    assert devices[1].instance == 1
    ip = devices[0].gige_ip()
    assert ip.camera_ip == "192.168.10.11" and ip.host_ip == "192.168.10.1"
    mac = devices[0].gige_mac()
    assert mac.camera_mac == "00-1A-2B-3C-4D-5E"


def test_device_info_outlives_enumeration_buffer(sdk):
    devices = sdk.enumerate()
    gc.collect()
    assert devices[1].raw.acSn == b"SN002"


def test_find_by_serial_name_and_fallback(sdk):
    assert sdk.find("SN002").serial == "SN002"
    assert sdk.find("sb01").serial == "SN002"
    # SN003 cannot be opened (in use); its enumeration name still matches.
    assert sdk.find("相机").serial == "SN003"
    with pytest.raises(DeviceNotFound) as info:
        sdk.find("nope")
    assert "sb00" in str(info.value) and "<in use>" in str(info.value)


def test_open_and_rename_round_trip(fake, sdk):
    dev = sdk.find("SN001")
    with sdk.open(dev) as cam:
        assert cam.user_name == "sb00"
        cam.user_name = "sb09"
        assert cam.user_name == "sb09"
        with pytest.raises(ValueError):
            cam.user_name = "a/b"
        with pytest.raises(ValueError):
            cam.user_name = "x" * 32
        handle = cam.handle
    assert fake.uninit == [handle]
    assert cam.closed
    with pytest.raises(GcamMvsdkError):
        _ = cam.user_name


def test_open_busy_camera_raises_mv_error(sdk):
    dev = sdk.enumerate()[2]
    with pytest.raises(MvError) as info:
        sdk.open(dev)
    assert info.value.status == _ffi.CAMERA_STATUS_ACCESS_DENY
    assert info.value.name == "CAMERA_STATUS_ACCESS_DENY"
    assert "fake message for -45" in str(info.value)


def test_properties(fake, sdk):
    with sdk.open("SN001") as cam:
        cam.exposure_us = 5000
        assert fake.ae == 0  # setting exposure disables auto exposure
        assert cam.exposure_us == 5000.0
        assert cam.auto_exposure is False
        cam.output_format = api.Mono8
        assert cam.output_format == api.Mono8
        cam.frame_rate_hz = 0
        with pytest.raises(MvError):
            cam.frame_rate_hz = -1
        assert cam.is_mono and cam.max_size == (W, H)
        assert [p.size for p in cam.packet_sizes()] == [1440, 4000, 8000]
        cam.gige_packet_size = 1500
        assert fake.pack_index == 0 and cam.gige_packet_size == 1440
        cam.gige_packet_size = 9000
        assert cam.gige_packet_size == 8000
        with pytest.raises(ValueError):
            cam.gige_packet_size = 1000


def test_grab_copy_and_view(fake, sdk):
    with sdk.open("SN001") as cam:
        cam.play()
        with cam.grab(timeout_ms=100) as frame:
            assert (frame.width, frame.height, frame.nbytes, frame.timestamp) == (W, H, W * H, 1234)
            view = frame.view()
            raw = frame.to_numpy(process=False)
            processed = frame.to_numpy()
            assert view.shape == (H, W) and view.dtype == np.uint8
            assert not view.flags.writeable
            assert np.array_equal(view, raw)
            # Contract: to_numpy() returns rows top-down on every platform.
            assert np.array_equal(processed, 255 - raw)
            # The buffer handed to the SDK's ISP is 64-byte aligned.
            assert fake.last_isp_dst % 64 == 0
        assert frame.released
        assert fake.released == [ctypes.addressof(fake.frame)]
        # Copies stay valid after release; the raw buffer may be reused.
        fake.frame[0] = 99
        assert raw[0, 0] == 0
        with pytest.raises(GcamMvsdkError):
            frame.view()


@pytest.mark.parametrize("windows", [False, True], ids=["linux-top-down", "windows-bottom-up"])
def test_to_numpy_returns_top_down_rows(fake, sdk, monkeypatch, windows):
    """to_numpy() undoes the Windows SDK's bottom-up ISP output; view() is never flipped."""
    monkeypatch.setattr(api, "_IS_WINDOWS", windows)
    fake.bottom_up = windows
    with sdk.open("SN001") as cam:
        with cam.grab() as frame:
            raw = frame.to_numpy(process=False)
            processed = frame.to_numpy()
            view = frame.view()
            assert np.array_equal(view, raw)
            assert raw[0, 0] == 0 and raw[-1, -1] == W * H - 1  # raw rows stay as delivered
    assert np.array_equal(processed, 255 - raw)
    assert processed.flags.c_contiguous


def test_grab_timeout(fake, sdk):
    fake.timeout = True
    with sdk.open("SN001") as cam:
        with pytest.raises(MvTimeout) as info:
            cam.grab(timeout_ms=10)
    assert isinstance(info.value, TimeoutError)
    assert info.value.status == -12


def test_close_releases_outstanding_frames(fake, sdk):
    cam = sdk.open("SN001")
    frame = cam.grab()
    cam.close()
    assert frame.released
    assert len(fake.released) == 1
    cam.close()  # idempotent
    assert len(fake.uninit) == 1


def test_callback_keeps_wrapper_alive_and_releases(fake, sdk):
    got = []
    with sdk.open("SN001") as cam:
        cam.set_callback(lambda frame: got.append(frame.to_numpy().copy()))
        assert cam._callback is fake.callback
        gc.collect()
        head = _ffi.tSdkFrameHead(uiMediaType=_ffi.CAMERA_MEDIA_TYPE_MONO8, uBytes=W * H, iWidth=W, iHeight=H)
        fake.callback(cam.handle, ctypes.addressof(fake.frame), ctypes.pointer(head), None)
        assert len(got) == 1 and got[0].shape == (H, W)
        assert fake.released == [ctypes.addressof(fake.frame)]


def test_callback_exception_does_not_escape(fake, sdk, capsys):
    def boom(frame):
        raise RuntimeError("boom in callback")

    with sdk.open("SN001") as cam:
        cam.set_callback(boom)
        head = _ffi.tSdkFrameHead(uiMediaType=_ffi.CAMERA_MEDIA_TYPE_MONO8, uBytes=W * H, iWidth=W, iHeight=H)
        fake.callback(cam.handle, ctypes.addressof(fake.frame), ctypes.pointer(head), None)
    assert "boom in callback" in capsys.readouterr().err
    assert len(fake.released) == 1


def test_gige_set_ip(fake, sdk):
    dev = sdk.enumerate()[0]
    sdk.gige_set_ip(dev, "192.168.1.100", "255.255.255.0", "192.168.1.1", persistent=True)
    assert ("setip", b"SN001", b"192.168.1.100", b"255.255.255.0", b"192.168.1.1", 1) in fake.calls


def test_missing_optional_function(fake):
    del fake.CameraSdkGetVersionString
    sdk = api.Sdk(fake, LibraryLocation("/fake", "test"))
    assert "CameraSdkGetVersionString" in sdk.missing_functions
    with pytest.raises(GcamMvsdkError):
        sdk.version()


def test_error_from_status_without_library():
    err = error_from_status(None, -16, "CameraEnumerateDevice")
    assert err.name == "CAMERA_STATUS_NO_DEVICE_FOUND"
    assert "no device found" in str(err)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (b"sb01\x00garbage", "sb01"),
        ("相机".encode("gbk") + b"\x00", "相机"),
        (b"", ""),
    ],
)
def test_decode_c_string(raw, expected):
    assert decode_c_string(raw) == expected
