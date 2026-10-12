"""ctypes layouts must match the C compiler's layout of the vendor headers.

Expected values were measured with gcc (x86_64 and -m32) from the headers of
SDK 2.1.0.49; see ``C_SIZES_LP64`` / ``C_SIZES_ILP32`` in ``_ffi``.
"""

from __future__ import annotations

import ctypes
import types

import pytest

from gcam_mvsdk_py import _ffi

POINTER_BITS = ctypes.sizeof(ctypes.c_void_p) * 8
EXPECTED = _ffi.C_SIZES_LP64 if POINTER_BITS == 64 else _ffi.C_SIZES_ILP32


def test_camera_dev_info_is_260_bytes():
    assert ctypes.sizeof(_ffi.tSdkCameraDevInfo) == 260


def test_frame_head_is_64_bytes():
    assert ctypes.sizeof(_ffi.tSdkFrameHead) == 64


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_struct_size_matches_c(name):
    assert ctypes.sizeof(getattr(_ffi, name)) == EXPECTED[name]


def test_recorded_tables_agree_except_pointer_struct():
    diff = {k for k in _ffi.C_SIZES_LP64 if _ffi.C_SIZES_LP64[k] != _ffi.C_SIZES_ILP32[k]}
    assert diff == {"tSdkCameraCapbility"}


@pytest.mark.parametrize(
    "struct, field, offset",
    [
        (_ffi.tSdkCameraDevInfo, "acFriendlyName", 64),
        (_ffi.tSdkCameraDevInfo, "acPortType", 192),
        (_ffi.tSdkCameraDevInfo, "acSn", 224),
        (_ffi.tSdkCameraDevInfo, "uInstance", 256),
        (_ffi.tSdkFrameHead, "uiTimeStamp", 28),
        (_ffi.tSdkFrameHead, "fBgain", 60),
        (_ffi.tSdkImageResolution, "iWidth", 68),
        (_ffi.tSdkImageResolution, "iHeightZoomSw", 88),
    ],
)
def test_fixed_offsets(struct, field, offset):
    assert getattr(struct, field).offset == offset


CAP_OFFSETS = {
    64: {"pPackLenDesc": 80, "iPackLenDesc": 88, "bParamInDevice": 120, "sExposeDesc": 188,
         "sResolutionRange": 216, "sIspCapacity": 304},
    32: {"pPackLenDesc": 40, "iPackLenDesc": 44, "bParamInDevice": 68, "sExposeDesc": 104,
         "sResolutionRange": 132, "sIspCapacity": 220},
}


@pytest.mark.parametrize("field", sorted(CAP_OFFSETS[64]))
def test_capability_offsets(field):
    assert getattr(_ffi.tSdkCameraCapbility, field).offset == CAP_OFFSETS[POINTER_BITS][field]


def test_status_table():
    assert _ffi.STATUS_CODES[0][0] == "CAMERA_STATUS_SUCCESS"
    assert _ffi.STATUS_CODES[-12][0] == "CAMERA_STATUS_TIME_OUT"
    assert _ffi.STATUS_CODES[-45][0] == "CAMERA_STATUS_ACCESS_DENY"
    # Every SDK status from -1 to -57 is present.
    assert all(code in _ffi.STATUS_CODES for code in range(-57, 1))
    names = [name for name, _ in _ffi.STATUS_CODES.values()]
    assert len(names) == len(set(names))
    assert _ffi.status_name(12345) == "UNKNOWN_STATUS"
    assert "12345" in _ffi.status_text(12345)


def test_media_types():
    assert _ffi.CAMERA_MEDIA_TYPE_MONO8 == 0x01080001
    assert _ffi.CAMERA_MEDIA_TYPE_BGR8 == 0x02180015
    assert _ffi.CAMERA_MEDIA_TYPE_RGB8 == 0x02180014
    assert _ffi.media_type_bits(_ffi.CAMERA_MEDIA_TYPE_MONO8) == 8
    assert _ffi.media_type_bits(_ffi.CAMERA_MEDIA_TYPE_BGR8) == 24
    assert _ffi.media_type_bits(_ffi.CAMERA_MEDIA_TYPE_MONO16) == 16
    assert _ffi.media_type_name(_ffi.CAMERA_MEDIA_TYPE_MONO8) == "Mono8"
    assert _ffi.media_type_name(0x12345678) == "0x12345678"


def test_plan_function_subset_is_declared():
    plan = """CameraSdkInit CameraEnumerateDevice CameraInit CameraUnInit CameraGetCapability
    CameraGetFriendlyName CameraSetFriendlyName CameraGigeGetIp CameraGigeSetIp CameraGigeGetMac
    CameraSetAeState CameraSetExposureTime CameraGetExposureTime CameraSetFrameRate
    CameraSetIspOutFormat CameraSetTriggerMode CameraPlay CameraPause CameraGetImageBuffer
    CameraReleaseImageBuffer CameraImageProcess CameraGetErrorString CameraSaveParameter
    CameraLoadParameter""".split()
    # The plan's CameraSetGigePacketSize does not exist in SDK 2.1.0.49; the
    # packet size is selected with CameraSetTransPackLen instead.
    plan.append("CameraSetTransPackLen")
    assert len(plan) == 25
    missing = [name for name in plan if name not in _ffi.FUNCTIONS]
    assert missing == []


def test_bind_reports_missing_functions():
    fake = types.SimpleNamespace(CameraSdkInit=lambda lang: 0)
    missing = _ffi.bind(fake)
    assert "CameraSdkInit" not in missing
    assert "CameraEnumerateDevice" in missing
    assert fake.CameraSdkInit.argtypes == [ctypes.c_int]
    assert fake.CameraSdkInit.restype is ctypes.c_int


def test_callback_type_constructs():
    calls = []
    cb = _ffi.CAMERA_SNAP_PROC(lambda h, p, head, ctx: calls.append(h))
    head = _ffi.tSdkFrameHead()
    cb(7, None, ctypes.pointer(head), None)
    assert calls == [7]
