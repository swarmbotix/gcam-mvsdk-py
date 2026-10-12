"""Raw ctypes declarations for the HuaTeng MVSDK C interface.

This module is written by hand from the public C interface of the SDK
(function names, parameter types, and structure layouts). It contains no
vendor source text. Structure sizes are asserted against values measured from
the C compiler in ``tests/test_struct_sizes.py``.

Nothing in this module opens the shared library; :func:`bind` attaches
``argtypes`` and ``restype`` to an already opened ``ctypes.CDLL`` (or
``ctypes.WinDLL``) object.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import (
    POINTER,
    Structure,
    c_char,
    c_char_p,
    c_double,
    c_float,
    c_int,
    c_uint,
    c_void_p,
)
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Scalar typedefs (the SDK uses Windows-style names on every platform; on
# Linux they are all plain 32-bit integers).
# ---------------------------------------------------------------------------

CameraHandle = c_int
CameraSdkStatus = c_int
BOOL = c_int
INT = c_int
UINT = c_uint

# ---------------------------------------------------------------------------
# Calling convention for callbacks: stdcall on Windows (only significant on
# 32-bit Windows), cdecl everywhere else.
# ---------------------------------------------------------------------------

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:  # pragma: no cover - exercised only on Windows
    FUNCTYPE = ctypes.WINFUNCTYPE  # type: ignore[attr-defined]
else:
    FUNCTYPE = ctypes.CFUNCTYPE

# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------


class tSdkCameraDevInfo(Structure):
    """Device description returned by ``CameraEnumerateDevice`` (260 bytes)."""

    _fields_ = [
        ("acProductSeries", c_char * 32),
        ("acProductName", c_char * 32),
        ("acFriendlyName", c_char * 32),
        ("acLinkName", c_char * 32),
        ("acDriverVersion", c_char * 32),
        ("acSensorType", c_char * 32),
        ("acPortType", c_char * 32),
        ("acSn", c_char * 32),
        ("uInstance", c_uint),
    ]


class tSdkRect(Structure):
    _fields_ = [
        ("iLeft", c_int),
        ("iTop", c_int),
        ("iWidth", c_int),
        ("iHeight", c_int),
    ]


class tSdkResolutionRange(Structure):
    _fields_ = [
        ("iHeightMax", c_int),
        ("iHeightMin", c_int),
        ("iWidthMax", c_int),
        ("iWidthMin", c_int),
        ("uSkipModeMask", c_uint),
        ("uBinSumModeMask", c_uint),
        ("uBinAverageModeMask", c_uint),
        ("uResampleMask", c_uint),
    ]


class tSdkImageResolution(Structure):
    _fields_ = [
        ("iIndex", c_int),
        ("acDescription", c_char * 32),
        ("uBinSumMode", c_uint),
        ("uBinAverageMode", c_uint),
        ("uSkipMode", c_uint),
        ("uResampleMask", c_uint),
        ("iHOffsetFOV", c_int),
        ("iVOffsetFOV", c_int),
        ("iWidthFOV", c_int),
        ("iHeightFOV", c_int),
        ("iWidth", c_int),
        ("iHeight", c_int),
        ("iWidthZoomHd", c_int),
        ("iHeightZoomHd", c_int),
        ("iWidthZoomSw", c_int),
        ("iHeightZoomSw", c_int),
    ]


class _IndexedDescription(Structure):
    """Common shape of the small ``{index, description[32]}`` records."""

    _fields_ = [
        ("iIndex", c_int),
        ("acDescription", c_char * 32),
    ]


class tSdkColorTemperatureDes(_IndexedDescription):
    pass


class tSdkFrameSpeed(_IndexedDescription):
    pass


class tSdkTrigger(_IndexedDescription):
    pass


class tSdkPresetLut(_IndexedDescription):
    pass


class tSdkAeAlgorithm(_IndexedDescription):
    pass


class tSdkBayerDecodeAlgorithm(_IndexedDescription):
    pass


class tSdkPackLength(Structure):
    _fields_ = [
        ("iIndex", c_int),
        ("acDescription", c_char * 32),
        ("iPackSize", c_uint),
    ]


class tSdkMediaType(Structure):
    _fields_ = [
        ("iIndex", c_int),
        ("acDescription", c_char * 32),
        ("iMediaType", c_uint),
    ]


class tSdkExpose(Structure):
    _fields_ = [
        ("uiTargetMin", c_uint),
        ("uiTargetMax", c_uint),
        ("uiAnalogGainMin", c_uint),
        ("uiAnalogGainMax", c_uint),
        ("fAnalogGainStep", c_float),
        ("uiExposeTimeMin", c_uint),
        ("uiExposeTimeMax", c_uint),
    ]


class tSdkFrameStatistic(Structure):
    _fields_ = [
        ("iTotal", c_int),
        ("iCapture", c_int),
        ("iLost", c_int),
    ]


class _MinMax(Structure):
    _fields_ = [
        ("iMin", c_int),
        ("iMax", c_int),
    ]


class tGammaRange(_MinMax):
    pass


class tContrastRange(_MinMax):
    pass


class tSaturationRange(_MinMax):
    pass


class tSharpnessRange(_MinMax):
    pass


class tRgbGainRange(Structure):
    _fields_ = [
        ("iRGainMin", c_int),
        ("iRGainMax", c_int),
        ("iGGainMin", c_int),
        ("iGGainMax", c_int),
        ("iBGainMin", c_int),
        ("iBGainMax", c_int),
    ]


class tSdkIspCapacity(Structure):
    _fields_ = [
        ("bMonoSensor", c_int),
        ("bWbOnce", c_int),
        ("bAutoWb", c_int),
        ("bAutoExposure", c_int),
        ("bManualExposure", c_int),
        ("bAntiFlick", c_int),
        ("bDeviceIsp", c_int),
        ("bForceUseDeviceIsp", c_int),
        ("bZoomHD", c_int),
    ]


class tSdkCameraCapbility(Structure):
    """Capability block filled by ``CameraGetCapability``.

    The pointer members refer to arrays owned by the SDK; they stay valid
    while the camera handle is open. The spelling ``Capbility`` follows the
    C interface.
    """

    _fields_ = [
        ("pTriggerDesc", POINTER(tSdkTrigger)),
        ("iTriggerDesc", c_int),
        ("pImageSizeDesc", POINTER(tSdkImageResolution)),
        ("iImageSizeDesc", c_int),
        ("pClrTempDesc", POINTER(tSdkColorTemperatureDes)),
        ("iClrTempDesc", c_int),
        ("pMediaTypeDesc", POINTER(tSdkMediaType)),
        ("iMediaTypdeDesc", c_int),
        ("pFrameSpeedDesc", POINTER(tSdkFrameSpeed)),
        ("iFrameSpeedDesc", c_int),
        ("pPackLenDesc", POINTER(tSdkPackLength)),
        ("iPackLenDesc", c_int),
        ("iOutputIoCounts", c_int),
        ("iInputIoCounts", c_int),
        ("pPresetLutDesc", POINTER(tSdkPresetLut)),
        ("iPresetLut", c_int),
        ("iUserDataMaxLen", c_int),
        ("bParamInDevice", c_int),
        ("pAeAlmSwDesc", POINTER(tSdkAeAlgorithm)),
        ("iAeAlmSwDesc", c_int),
        ("pAeAlmHdDesc", POINTER(tSdkAeAlgorithm)),
        ("iAeAlmHdDesc", c_int),
        ("pBayerDecAlmSwDesc", POINTER(tSdkBayerDecodeAlgorithm)),
        ("iBayerDecAlmSwDesc", c_int),
        ("pBayerDecAlmHdDesc", POINTER(tSdkBayerDecodeAlgorithm)),
        ("iBayerDecAlmHdDesc", c_int),
        ("sExposeDesc", tSdkExpose),
        ("sResolutionRange", tSdkResolutionRange),
        ("sRgbGainRange", tRgbGainRange),
        ("sSaturationRange", tSaturationRange),
        ("sGammaRange", tGammaRange),
        ("sContrastRange", tContrastRange),
        ("sSharpnessRange", tSharpnessRange),
        ("sIspCapacity", tSdkIspCapacity),
    ]


class tSdkFrameHead(Structure):
    """Per-frame header filled by ``CameraGetImageBuffer`` (64 bytes)."""

    _fields_ = [
        ("uiMediaType", c_uint),
        ("uBytes", c_uint),
        ("iWidth", c_int),
        ("iHeight", c_int),
        ("iWidthZoomSw", c_int),
        ("iHeightZoomSw", c_int),
        ("bIsTrigger", c_int),
        ("uiTimeStamp", c_uint),
        ("uiExpTime", c_uint),
        ("fAnalogGain", c_float),
        ("iGamma", c_int),
        ("iContrast", c_int),
        ("iSaturation", c_int),
        ("fRgain", c_float),
        ("fGgain", c_float),
        ("fBgain", c_float),
    ]


class tSdkFrameEvent(Structure):
    _fields_ = [
        ("uType", c_uint),
        ("uStatus", c_uint),
        ("uFrameID", c_uint),
        ("uWidth", c_uint),
        ("uHeight", c_uint),
        ("uPixelFormat", c_uint),
        ("TimeStampL", c_uint),
        ("TimeStampH", c_uint),
    ]


# Sizes measured with gcc from the C headers of SDK 2.1.0.49. Pointer-bearing
# structures differ between 32-bit and 64-bit targets.
C_SIZES_LP64: Dict[str, int] = {
    "tSdkCameraDevInfo": 260,
    "tSdkFrameHead": 64,
    "tSdkCameraCapbility": 344,
    "tSdkImageResolution": 92,
    "tSdkPackLength": 40,
    "tSdkFrameSpeed": 36,
    "tSdkMediaType": 40,
    "tSdkTrigger": 36,
    "tSdkExpose": 28,
    "tSdkResolutionRange": 32,
    "tSdkIspCapacity": 36,
    "tSdkFrameStatistic": 12,
    "tRgbGainRange": 24,
    "tSdkRect": 16,
    "tSdkFrameEvent": 32,
}
C_SIZES_ILP32: Dict[str, int] = dict(C_SIZES_LP64, tSdkCameraCapbility=256)

# ---------------------------------------------------------------------------
# Callback types
# ---------------------------------------------------------------------------

# void (*)(CameraHandle, BYTE* frame, tSdkFrameHead* head, void* context)
CAMERA_SNAP_PROC = FUNCTYPE(None, c_int, c_void_p, POINTER(tSdkFrameHead), c_void_p)

# void (*)(CameraHandle, UINT msg, UINT param, void* context)
CAMERA_CONNECTION_STATUS_CALLBACK = FUNCTYPE(None, c_int, c_uint, c_uint, c_void_p)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Media type composition.
CAMERA_MEDIA_TYPE_MONO = 0x01000000
CAMERA_MEDIA_TYPE_COLOR = 0x02000000
CAMERA_MEDIA_TYPE_COLOR_MASK = 0xFF000000
CAMERA_MEDIA_TYPE_EFFECTIVE_PIXEL_SIZE_MASK = 0x00FF0000
CAMERA_MEDIA_TYPE_EFFECTIVE_PIXEL_SIZE_SHIFT = 16
CAMERA_MEDIA_TYPE_ID_MASK = 0x0000FFFF

_OCCUPY8 = 0x00080000
_OCCUPY12 = 0x000C0000
_OCCUPY16 = 0x00100000
_OCCUPY24 = 0x00180000
_OCCUPY32 = 0x00200000
_OCCUPY48 = 0x00300000

CAMERA_MEDIA_TYPE_MONO8 = CAMERA_MEDIA_TYPE_MONO | _OCCUPY8 | 0x0001
CAMERA_MEDIA_TYPE_MONO10 = CAMERA_MEDIA_TYPE_MONO | _OCCUPY16 | 0x0003
CAMERA_MEDIA_TYPE_MONO10_PACKED = CAMERA_MEDIA_TYPE_MONO | _OCCUPY12 | 0x0004
CAMERA_MEDIA_TYPE_MONO12 = CAMERA_MEDIA_TYPE_MONO | _OCCUPY16 | 0x0005
CAMERA_MEDIA_TYPE_MONO12_PACKED = CAMERA_MEDIA_TYPE_MONO | _OCCUPY12 | 0x0006
CAMERA_MEDIA_TYPE_MONO16 = CAMERA_MEDIA_TYPE_MONO | _OCCUPY16 | 0x0007
CAMERA_MEDIA_TYPE_BAYGR8 = CAMERA_MEDIA_TYPE_MONO | _OCCUPY8 | 0x0008
CAMERA_MEDIA_TYPE_BAYRG8 = CAMERA_MEDIA_TYPE_MONO | _OCCUPY8 | 0x0009
CAMERA_MEDIA_TYPE_BAYGB8 = CAMERA_MEDIA_TYPE_MONO | _OCCUPY8 | 0x000A
CAMERA_MEDIA_TYPE_BAYBG8 = CAMERA_MEDIA_TYPE_MONO | _OCCUPY8 | 0x000B
CAMERA_MEDIA_TYPE_RGB8 = CAMERA_MEDIA_TYPE_COLOR | _OCCUPY24 | 0x0014
CAMERA_MEDIA_TYPE_BGR8 = CAMERA_MEDIA_TYPE_COLOR | _OCCUPY24 | 0x0015
CAMERA_MEDIA_TYPE_RGBA8 = CAMERA_MEDIA_TYPE_COLOR | _OCCUPY32 | 0x0016
CAMERA_MEDIA_TYPE_BGRA8 = CAMERA_MEDIA_TYPE_COLOR | _OCCUPY32 | 0x0017
CAMERA_MEDIA_TYPE_RGB16 = CAMERA_MEDIA_TYPE_COLOR | _OCCUPY48 | 0x0033
CAMERA_MEDIA_TYPE_BGR16 = CAMERA_MEDIA_TYPE_COLOR | _OCCUPY48 | 0x004B

MEDIA_TYPE_NAMES: Dict[int, str] = {
    CAMERA_MEDIA_TYPE_MONO8: "Mono8",
    CAMERA_MEDIA_TYPE_MONO10: "Mono10",
    CAMERA_MEDIA_TYPE_MONO10_PACKED: "Mono10Packed",
    CAMERA_MEDIA_TYPE_MONO12: "Mono12",
    CAMERA_MEDIA_TYPE_MONO12_PACKED: "Mono12Packed",
    CAMERA_MEDIA_TYPE_MONO16: "Mono16",
    CAMERA_MEDIA_TYPE_BAYGR8: "BayerGR8",
    CAMERA_MEDIA_TYPE_BAYRG8: "BayerRG8",
    CAMERA_MEDIA_TYPE_BAYGB8: "BayerGB8",
    CAMERA_MEDIA_TYPE_BAYBG8: "BayerBG8",
    CAMERA_MEDIA_TYPE_RGB8: "RGB8",
    CAMERA_MEDIA_TYPE_BGR8: "BGR8",
    CAMERA_MEDIA_TYPE_RGBA8: "RGBA8",
    CAMERA_MEDIA_TYPE_BGRA8: "BGRA8",
    CAMERA_MEDIA_TYPE_RGB16: "RGB16",
    CAMERA_MEDIA_TYPE_BGR16: "BGR16",
}


def media_type_bits(media_type: int) -> int:
    """Return the number of bits one pixel occupies for ``media_type``."""
    return (media_type & CAMERA_MEDIA_TYPE_EFFECTIVE_PIXEL_SIZE_MASK) >> CAMERA_MEDIA_TYPE_EFFECTIVE_PIXEL_SIZE_SHIFT


def media_type_name(media_type: int) -> str:
    """Human readable name of a media type, or its hexadecimal value."""
    return MEDIA_TYPE_NAMES.get(media_type, "0x%08X" % media_type)


# Trigger modes (emSdkSnapMode).
TRIGGER_CONTINUOUS = 0
TRIGGER_SOFTWARE = 1
TRIGGER_HARDWARE = 2

# Parameter teams (emSdkParameterTeam).
PARAMETER_TEAM_DEFAULT = 0xFF
PARAMETER_TEAM_A = 0
PARAMETER_TEAM_B = 1
PARAMETER_TEAM_C = 2
PARAMETER_TEAM_D = 3

# Parameter load modes (emSdkParameterMode). -1 lets the SDK choose.
PARAM_MODE_AUTO = -1
PARAM_MODE_BY_MODEL = 0
PARAM_MODE_BY_NAME = 1
PARAM_MODE_BY_SN = 2
PARAM_MODE_IN_DEVICE = 3

# CameraSdkInit language selector.
SDK_LANGUAGE_CHINESE = 0
SDK_LANGUAGE_ENGLISH = 1

# Buffer sizes for string out-parameters. The interface documents minimums of
# 32 bytes (names, versions), 16 bytes (IPv4 strings), and 18 bytes (MAC
# strings); larger buffers are used for headroom.
NAME_BUFFER_SIZE = 64
VERSION_BUFFER_SIZE = 128
IP_BUFFER_SIZE = 64
MAC_BUFFER_SIZE = 64
FRIENDLY_NAME_MAX_BYTES = 31  # 32-byte field including the terminating NUL

# ---------------------------------------------------------------------------
# Status codes (CameraSdkStatus). Messages are written for this package; the
# SDK's own text is obtained at runtime from CameraGetErrorString.
# ---------------------------------------------------------------------------

CAMERA_STATUS_SUCCESS = 0
CAMERA_STATUS_TIME_OUT = -12
CAMERA_STATUS_NO_DEVICE_FOUND = -16
CAMERA_STATUS_DEVICE_IS_OPENED = -18
CAMERA_STATUS_ACCESS_DENY = -45

STATUS_CODES: Dict[int, Tuple[str, str]] = {
    0: ("CAMERA_STATUS_SUCCESS", "success"),
    -1: ("CAMERA_STATUS_FAILED", "operation failed"),
    -2: ("CAMERA_STATUS_INTERNAL_ERROR", "internal error"),
    -3: ("CAMERA_STATUS_UNKNOW", "unknown error"),
    -4: ("CAMERA_STATUS_NOT_SUPPORTED", "function not supported"),
    -5: ("CAMERA_STATUS_NOT_INITIALIZED", "initialization not completed"),
    -6: ("CAMERA_STATUS_PARAMETER_INVALID", "invalid parameter"),
    -7: ("CAMERA_STATUS_PARAMETER_OUT_OF_BOUND", "parameter out of bounds"),
    -8: ("CAMERA_STATUS_UNENABLED", "not enabled"),
    -9: ("CAMERA_STATUS_USER_CANCEL", "cancelled by the user"),
    -10: ("CAMERA_STATUS_PATH_NOT_FOUND", "path not found"),
    -11: ("CAMERA_STATUS_SIZE_DISMATCH", "image data size does not match the defined size"),
    -12: ("CAMERA_STATUS_TIME_OUT", "timeout"),
    -13: ("CAMERA_STATUS_IO_ERROR", "hardware I/O error"),
    -14: ("CAMERA_STATUS_COMM_ERROR", "communication error"),
    -15: ("CAMERA_STATUS_BUS_ERROR", "bus error"),
    -16: ("CAMERA_STATUS_NO_DEVICE_FOUND", "no device found"),
    -17: ("CAMERA_STATUS_NO_LOGIC_DEVICE_FOUND", "logical device not found"),
    -18: ("CAMERA_STATUS_DEVICE_IS_OPENED", "device is already open"),
    -19: ("CAMERA_STATUS_DEVICE_IS_CLOSED", "device is closed"),
    -20: ("CAMERA_STATUS_DEVICE_VEDIO_CLOSED", "device video stream is not open"),
    -21: ("CAMERA_STATUS_NO_MEMORY", "insufficient system memory"),
    -22: ("CAMERA_STATUS_FILE_CREATE_FAILED", "file creation failed"),
    -23: ("CAMERA_STATUS_FILE_INVALID", "invalid file format"),
    -24: ("CAMERA_STATUS_WRITE_PROTECTED", "write protected"),
    -25: ("CAMERA_STATUS_GRAB_FAILED", "data acquisition failed"),
    -26: ("CAMERA_STATUS_LOST_DATA", "data lost, incomplete frame"),
    -27: ("CAMERA_STATUS_EOF_ERROR", "end-of-frame marker not received"),
    -28: ("CAMERA_STATUS_BUSY", "busy, a previous operation is still in progress"),
    -29: ("CAMERA_STATUS_WAIT", "wait required, retry later"),
    -30: ("CAMERA_STATUS_IN_PROCESS", "operation already in progress"),
    -31: ("CAMERA_STATUS_IIC_ERROR", "I2C transfer error"),
    -32: ("CAMERA_STATUS_SPI_ERROR", "SPI transfer error"),
    -33: ("CAMERA_STATUS_USB_CONTROL_ERROR", "USB control transfer error"),
    -34: ("CAMERA_STATUS_USB_BULK_ERROR", "USB bulk transfer error"),
    -35: ("CAMERA_STATUS_SOCKET_INIT_ERROR", "network socket initialization failed"),
    -36: ("CAMERA_STATUS_GIGE_FILTER_INIT_ERROR", "GigE filter driver initialization failed"),
    -37: ("CAMERA_STATUS_NET_SEND_ERROR", "network send error"),
    -38: ("CAMERA_STATUS_DEVICE_LOST", "connection to the network camera lost"),
    -39: ("CAMERA_STATUS_DATA_RECV_LESS", "fewer bytes received than requested"),
    -40: ("CAMERA_STATUS_FUNCTION_LOAD_FAILED", "failed to load a function from file"),
    -41: ("CAMERA_STATUS_CRITICAL_FILE_LOST", "a file required by the program is missing"),
    -42: ("CAMERA_STATUS_SENSOR_ID_DISMATCH", "firmware does not match the program"),
    -43: ("CAMERA_STATUS_OUT_OF_RANGE", "parameter out of valid range"),
    -44: ("CAMERA_STATUS_REGISTRY_ERROR", "installation registry error, reinstall the SDK"),
    -45: ("CAMERA_STATUS_ACCESS_DENY", "access denied, the camera is in use by another program"),
    -46: ("CAMERA_STATUS_CAMERA_NEED_RESET", "camera must be reset (power cycle) before use"),
    -47: ("CAMERA_STATUS_ISP_MOUDLE_NOT_INITIALIZED", "ISP module not initialized"),
    -48: ("CAMERA_STATUS_ISP_DATA_CRC_ERROR", "data checksum error"),
    -49: ("CAMERA_STATUS_MV_TEST_FAILED", "data test failed"),
    -50: ("CAMERA_STATUS_INTERNAL_ERR1", "internal error 1"),
    -51: ("CAMERA_STATUS_U3V_NO_CONTROL_EP", "USB3 Vision control endpoint not found"),
    -52: ("CAMERA_STATUS_U3V_CONTROL_ERROR", "USB3 Vision control communication error"),
    -53: ("CAMERA_STATUS_INVALID_FRIENDLY_NAME", 'invalid device name (must not contain \\ / : * ? " < > |)'),
    -54: ("CAMERA_STATUS_FORMAT_ERROR", "format error"),
    -55: ("CAMERA_STATUS_PCIE_OPEN_ERROR", "PCIe device open failed"),
    -56: ("CAMERA_STATUS_PCIE_COMM_ERROR", "PCIe device communication failed"),
    -57: ("CAMERA_STATUS_PCIE_DDR_ERROR", "PCIe DDR error"),
    # GigE Vision (AIA) status values passed through by the SDK.
    0x0100: ("CAMERA_AIA_PACKET_RESEND", "frame requires packet resend"),
    0x8001: ("CAMERA_AIA_NOT_IMPLEMENTED", "command not implemented by the device"),
    0x8002: ("CAMERA_AIA_INVALID_PARAMETER", "invalid command parameter"),
    0x8003: ("CAMERA_AIA_INVALID_ADDRESS", "inaccessible address"),
    0x8004: ("CAMERA_AIA_WRITE_PROTECT", "object is not writable"),
    0x8005: ("CAMERA_AIA_BAD_ALIGNMENT", "address is not correctly aligned"),
    0x8006: ("CAMERA_AIA_ACCESS_DENIED", "access denied"),
    0x8007: ("CAMERA_AIA_BUSY", "command is being processed"),
    0x8008: ("CAMERA_AIA_DEPRECATED", "command deprecated"),
    0x800C: ("CAMERA_AIA_PACKET_UNAVAILABLE", "packet unavailable"),
    0x800D: ("CAMERA_AIA_DATA_OVERRUN", "data overrun"),
    0x800E: ("CAMERA_AIA_INVALID_HEADER", "invalid packet header"),
    0x8010: ("CAMERA_AIA_PACKET_NOT_YET_AVAILABLE", "packet not yet available"),
    0x8011: ("CAMERA_AIA_PACKET_AND_PREV_REMOVED_FROM_MEMORY", "packet and previous packets no longer in memory"),
    0x8012: ("CAMERA_AIA_PACKET_REMOVED_FROM_MEMORY", "packet no longer in memory"),
    0x0813: ("CAMERA_AIA_NO_REF_TIME", "no reference time source"),
    0x0814: ("CAMERA_AIA_PACKET_TEMPORARILY_UNAVAILABLE", "packet temporarily unavailable"),
    0x0815: ("CAMERA_AIA_OVERFLOW", "device overflow"),
    0x0816: ("CAMERA_AIA_ACTION_LATE", "action command arrived late"),
    0x8FFF: ("CAMERA_AIA_ERROR", "GigE Vision error"),
}


def status_name(status: int) -> str:
    """Symbolic name of a status code, or ``"UNKNOWN_STATUS"``."""
    entry = STATUS_CODES.get(status)
    return entry[0] if entry else "UNKNOWN_STATUS"


def status_text(status: int) -> str:
    """Package-provided English description of a status code."""
    entry = STATUS_CODES.get(status)
    return entry[1] if entry else "unknown status %d" % status


# ---------------------------------------------------------------------------
# Function signatures: name -> (restype, argtypes)
# ---------------------------------------------------------------------------

_S = CameraSdkStatus
_H = CameraHandle
_PDEV = POINTER(tSdkCameraDevInfo)
_PHEAD = POINTER(tSdkFrameHead)
_PINT = POINTER(c_int)
_PUINT = POINTER(c_uint)
_PDOUBLE = POINTER(c_double)
_PFLOAT = POINTER(c_float)

Signature = Tuple[object, Sequence[object]]

FUNCTIONS: Dict[str, Signature] = {
    # Library-level
    "CameraSdkInit": (_S, [c_int]),
    "CameraSdkGetVersionString": (_S, [c_char_p]),
    "CameraGetErrorString": (c_char_p, [c_int]),
    "CameraEnumerateDevice": (_S, [_PDEV, _PINT]),
    "CameraEnumerateDeviceEx": (c_int, []),
    "CameraIsOpened": (_S, [_PDEV, _PINT]),
    "CameraGigeGetIp": (_S, [_PDEV, c_char_p, c_char_p, c_char_p, c_char_p, c_char_p, c_char_p]),
    "CameraGigeSetIp": (_S, [_PDEV, c_char_p, c_char_p, c_char_p, BOOL]),
    "CameraGigeGetMac": (_S, [_PDEV, c_char_p, c_char_p]),
    "CameraGigeSetOption": (_S, [c_char_p, c_char_p]),
    "CameraSetSysOption": (_S, [c_char_p, c_char_p]),
    "CameraAlignMalloc": (c_void_p, [c_int, c_int]),
    "CameraAlignFree": (None, [c_void_p]),
    # Open / close
    "CameraInit": (_S, [_PDEV, c_int, c_int, POINTER(CameraHandle)]),
    "CameraUnInit": (_S, [_H]),
    "CameraGetCapability": (_S, [_H, POINTER(tSdkCameraCapbility)]),
    "CameraGetEnumInfo": (_S, [_H, _PDEV]),
    "CameraGetFriendlyName": (_S, [_H, c_char_p]),
    "CameraSetFriendlyName": (_S, [_H, c_char_p]),
    "CameraGetFirmwareVersion": (_S, [_H, c_char_p]),
    "CameraSaveParameter": (_S, [_H, c_int]),
    "CameraLoadParameter": (_S, [_H, c_int]),
    # Exposure and gain
    "CameraSetAeState": (_S, [_H, BOOL]),
    "CameraGetAeState": (_S, [_H, _PINT]),
    "CameraSetExposureTime": (_S, [_H, c_double]),
    "CameraGetExposureTime": (_S, [_H, _PDOUBLE]),
    "CameraGetExposureTimeRange": (_S, [_H, _PDOUBLE, _PDOUBLE, _PDOUBLE]),
    "CameraGetExposureLineTime": (_S, [_H, _PDOUBLE]),
    "CameraSetAnalogGain": (_S, [_H, c_int]),
    "CameraGetAnalogGain": (_S, [_H, _PINT]),
    "CameraSetAnalogGainX": (_S, [_H, c_float]),
    "CameraGetAnalogGainX": (_S, [_H, _PFLOAT]),
    "CameraGetAnalogGainXRange": (_S, [_H, _PFLOAT, _PFLOAT, _PFLOAT]),
    "CameraGetGain": (_S, [_H, _PINT, _PINT, _PINT]),
    "CameraGetGamma": (_S, [_H, _PINT]),
    "CameraGetContrast": (_S, [_H, _PINT]),
    "CameraGetSaturation": (_S, [_H, _PINT]),
    "CameraGetSharpness": (_S, [_H, _PINT]),
    # Timing, format, trigger
    "CameraSetFrameRate": (_S, [_H, c_int]),
    "CameraGetFrameRate": (_S, [_H, _PINT]),
    "CameraSetFrameSpeed": (_S, [_H, c_int]),
    "CameraGetFrameSpeed": (_S, [_H, _PINT]),
    "CameraSetIspOutFormat": (_S, [_H, c_uint]),
    "CameraGetIspOutFormat": (_S, [_H, _PUINT]),
    "CameraSetTriggerMode": (_S, [_H, c_int]),
    "CameraGetTriggerMode": (_S, [_H, _PINT]),
    "CameraGetTriggerDelayTime": (_S, [_H, _PUINT]),
    "CameraGetTriggerCount": (_S, [_H, _PINT]),
    "CameraSoftTrigger": (_S, [_H]),
    "CameraGetImageResolution": (_S, [_H, POINTER(tSdkImageResolution)]),
    "CameraSetImageResolution": (_S, [_H, POINTER(tSdkImageResolution)]),
    # GigE transport packet size (selected by index into pPackLenDesc).
    "CameraSetTransPackLen": (_S, [_H, c_int]),
    "CameraGetTransPackLen": (_S, [_H, _PINT]),
    # Streaming
    "CameraPlay": (_S, [_H]),
    "CameraPause": (_S, [_H]),
    "CameraStop": (_S, [_H]),
    "CameraClearBuffer": (_S, [_H]),
    "CameraGetImageBuffer": (_S, [_H, _PHEAD, POINTER(c_void_p), c_uint]),
    "CameraReleaseImageBuffer": (_S, [_H, c_void_p]),
    "CameraImageProcess": (_S, [_H, c_void_p, c_void_p, _PHEAD]),
    "CameraFlipFrameBuffer": (_S, [c_void_p, _PHEAD, c_int]),
    "CameraGetFrameStatistic": (_S, [_H, POINTER(tSdkFrameStatistic)]),
    "CameraSetCallbackFunction": (_S, [_H, CAMERA_SNAP_PROC, c_void_p, c_void_p]),
}

# Functions without which the safe layer cannot work at all.
REQUIRED_FUNCTIONS: Tuple[str, ...] = (
    "CameraSdkInit",
    "CameraEnumerateDevice",
    "CameraInit",
    "CameraUnInit",
    "CameraGetErrorString",
)


def bind(lib: object, names: Optional[Sequence[str]] = None) -> List[str]:
    """Attach ``argtypes``/``restype`` to the functions of an opened library.

    Returns the list of names that the library does not export. Missing
    optional functions are tolerated; the safe layer raises a clear error if
    one of them is called.
    """
    missing: List[str] = []
    for name in names if names is not None else FUNCTIONS:
        restype, argtypes = FUNCTIONS[name]
        try:
            fn: Callable = getattr(lib, name)
        except AttributeError:
            missing.append(name)
            continue
        fn.restype = restype
        fn.argtypes = list(argtypes)
    return missing
