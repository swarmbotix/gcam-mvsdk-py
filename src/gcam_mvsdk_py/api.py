"""Safe, Pythonic layer over the raw MVSDK bindings.

Typical use::

    import gcam_mvsdk_py

    sdk = gcam_mvsdk_py.load()
    for dev in sdk.enumerate():
        print(dev.serial, dev.model, dev.port_type, dev.gige_ip(), dev.gige_mac())

    with sdk.open(dev) as cam:
        cam.exposure_us = 5000
        cam.output_format = gcam_mvsdk_py.Mono8
        cam.play()
        with cam.grab(timeout_ms=1000) as frame:
            img = frame.to_numpy()
"""

from __future__ import annotations

import ctypes
import sys
import threading
import traceback
import warnings
import weakref
from ctypes import byref, c_double, c_float, c_int, c_uint, c_void_p, create_string_buffer
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, Union

import numpy as np

from . import _ffi
from ._errors import (
    DeviceNotFound,
    FunctionUnavailable,
    GcamMvsdkError,
    MvError,
    check,
    decode_c_string,
    encode_c_string,
    error_from_status,
)
from ._loader import LibraryLocation, open_library

# Output formats accepted by Camera.output_format.
Mono8 = _ffi.CAMERA_MEDIA_TYPE_MONO8
Mono16 = _ffi.CAMERA_MEDIA_TYPE_MONO16
RGB8 = _ffi.CAMERA_MEDIA_TYPE_RGB8
BGR8 = _ffi.CAMERA_MEDIA_TYPE_BGR8
RGBA8 = _ffi.CAMERA_MEDIA_TYPE_RGBA8
BGRA8 = _ffi.CAMERA_MEDIA_TYPE_BGRA8

_INVALID_NAME_CHARS = set('\\/:*?"<>|')
_IS_WINDOWS = sys.platform == "win32"

_LOAD_LOCK = threading.Lock()
_SDK_INSTANCE: Optional["Sdk"] = None


def load(path: Optional[str] = None, language: int = _ffi.SDK_LANGUAGE_ENGLISH) -> "Sdk":
    """Find and open the vendor library, call ``CameraSdkInit`` once, return :class:`Sdk`.

    ``path`` may name the library file or an SDK root directory; when omitted
    the search path of :mod:`gcam_mvsdk_py._loader` is used. Repeated calls
    return the same :class:`Sdk` instance.
    """
    global _SDK_INSTANCE
    with _LOAD_LOCK:
        if _SDK_INSTANCE is not None:
            return _SDK_INSTANCE
        lib, location = open_library(path)
        _SDK_INSTANCE = Sdk(lib, location, language)
        return _SDK_INSTANCE


class GigeIp(NamedTuple):
    camera_ip: str
    camera_mask: str
    camera_gateway: str
    host_ip: str
    host_mask: str
    host_gateway: str


class GigeMac(NamedTuple):
    camera_mac: str
    host_mac: str


class FrameStatistic(NamedTuple):
    total: int
    captured: int
    lost: int


class PacketSize(NamedTuple):
    index: int
    size: int
    description: str


class IndexedDescription(NamedTuple):
    index: int
    description: str


class Resolution(NamedTuple):
    index: int
    width: int
    height: int
    description: str


class Sdk:
    """An opened and initialized MVSDK library.

    Obtain it with :func:`load`. ``sdk.raw`` is the underlying ``ctypes`` library
    object, so functions without a wrapper can be called directly after
    assigning ``argtypes`` and ``restype``.
    """

    def __init__(self, lib: Any, location: LibraryLocation, language: int = _ffi.SDK_LANGUAGE_ENGLISH) -> None:
        self._lib = lib
        self.location = location
        self.missing_functions: List[str] = _ffi.bind(lib)
        absent = [n for n in _ffi.REQUIRED_FUNCTIONS if n in self.missing_functions]
        if absent:
            raise GcamMvsdkError(
                "%s does not look like the HuaTeng MVSDK: missing %s" % (location.path, ", ".join(absent))
            )
        self._call("CameraSdkInit", int(language))

    # -- plumbing ---------------------------------------------------------

    @property
    def raw(self) -> Any:
        """The underlying ``ctypes.CDLL`` (``WinDLL`` on Windows)."""
        return self._lib

    @property
    def path(self) -> str:
        return self.location.path

    def _fn(self, name: str) -> Callable[..., Any]:
        if name in self.missing_functions:
            raise FunctionUnavailable(name)
        return getattr(self._lib, name)

    def _call(self, name: str, *args: Any) -> None:
        check(self._lib, self._fn(name)(*args), name)

    def has_function(self, name: str) -> bool:
        return hasattr(self._lib, name)

    def error_string(self, status: int) -> str:
        """Message for ``status`` from ``CameraGetErrorString``."""
        return error_from_status(self._lib, status).message

    # -- library-level calls ---------------------------------------------

    def version(self) -> str:
        """SDK version string from ``CameraSdkGetVersionString``."""
        buf = create_string_buffer(_ffi.VERSION_BUFFER_SIZE)
        self._call("CameraSdkGetVersionString", buf)
        return decode_c_string(buf.raw)

    def enumerate(self, max_count: int = 64) -> List["DeviceInfo"]:
        """Enumerate every camera visible to the SDK (GigE discovery and USB)."""
        array = (_ffi.tSdkCameraDevInfo * max_count)()
        count = c_int(max_count)
        status = self._fn("CameraEnumerateDevice")(array, byref(count))
        if status == _ffi.CAMERA_STATUS_NO_DEVICE_FOUND:
            return []
        check(self._lib, status, "CameraEnumerateDevice")
        n = max(0, min(count.value, max_count))
        return [DeviceInfo(self, _ffi.tSdkCameraDevInfo.from_buffer_copy(array[i])) for i in range(n)]

    def gige_get_ip(self, dev: "DeviceInfo") -> GigeIp:
        bufs = [create_string_buffer(_ffi.IP_BUFFER_SIZE) for _ in range(6)]
        self._call("CameraGigeGetIp", byref(dev.raw), *bufs)
        return GigeIp(*(decode_c_string(b.raw) for b in bufs))

    def gige_get_mac(self, dev: "DeviceInfo") -> GigeMac:
        bufs = [create_string_buffer(_ffi.MAC_BUFFER_SIZE) for _ in range(2)]
        self._call("CameraGigeGetMac", byref(dev.raw), *bufs)
        return GigeMac(*(decode_c_string(b.raw) for b in bufs))

    def gige_set_ip(self, dev: "DeviceInfo", ip: str, mask: str, gateway: str, persistent: bool = True) -> None:
        """Set a GigE camera's IP configuration (``CameraGigeSetIp``).

        ``persistent=True`` stores a fixed IP in the camera. ``persistent=False``
        switches the camera to automatic addressing; the SDK then ignores
        ``ip``, ``mask``, and ``gateway``. Works even when the camera is on a
        different subnet than the host NIC.
        """
        self._call(
            "CameraGigeSetIp",
            byref(dev.raw),
            encode_c_string(ip),
            encode_c_string(mask),
            encode_c_string(gateway),
            1 if persistent else 0,
        )

    def gige_set_option(self, name: str, value: str) -> None:
        """Global GigE transport option, for example ``("NumBuffers", "8")``."""
        self._call("CameraGigeSetOption", encode_c_string(name), encode_c_string(str(value)))

    def is_opened(self, dev: "DeviceInfo") -> bool:
        flag = c_int(0)
        self._call("CameraIsOpened", byref(dev.raw), byref(flag))
        return flag.value != 0

    def open(
        self,
        dev: Union["DeviceInfo", str],
        param_load_mode: int = _ffi.PARAM_MODE_AUTO,
        team: int = -1,
    ) -> "Camera":
        """Open a camera (``CameraInit``). Use as a context manager.

        ``dev`` is a :class:`DeviceInfo` or a serial number / user-set name,
        which is resolved with :meth:`find`.
        """
        if isinstance(dev, str):
            dev = self.find(dev)
        handle = _ffi.CameraHandle(0)
        self._call("CameraInit", byref(dev.raw), int(param_load_mode), int(team), byref(handle))
        return Camera(self, dev, handle.value)

    def read_user_name(self, dev: "DeviceInfo") -> Optional[str]:
        """Open ``dev`` briefly to read its user-set name; ``None`` if it cannot be opened."""
        try:
            cam = self.open(dev)
        except MvError:
            return None
        try:
            return cam.user_name
        except MvError:
            return None
        finally:
            cam.close()

    def find(
        self,
        key: str,
        devices: Optional[List["DeviceInfo"]] = None,
        read_user_names: bool = True,
    ) -> "DeviceInfo":
        """Return the camera whose serial number or user-set name equals ``key``.

        Matching order: serial number, user-set name read from the camera
        (requires briefly opening each camera, skipped for cameras that are in
        use elsewhere), then the friendly name reported by enumeration.
        """
        devices = self.enumerate() if devices is None else devices
        if not devices:
            raise DeviceNotFound("no cameras found; check cable, power, subnet, and privileges (gcam-mvsdk-py doctor)")
        by_serial = [d for d in devices if d.serial == key]
        if len(by_serial) == 1:
            return by_serial[0]
        names: List[Tuple["DeviceInfo", Optional[str]]] = []
        if read_user_names:
            names = [(d, self.read_user_name(d)) for d in devices]
            by_name = [d for d, n in names if n == key]
            if len(by_name) == 1:
                return by_name[0]
            if len(by_name) > 1:
                raise DeviceNotFound(
                    "user-set name %r is ambiguous: serials %s" % (key, ", ".join(d.serial for d in by_name))
                )
        by_friendly = [d for d in devices if d.friendly_name == key]
        if len(by_friendly) == 1:
            return by_friendly[0]
        listing = []
        for d, n in names or [(d, None) for d in devices]:
            label = n if n is not None else ("<in use>" if read_user_names else d.friendly_name)
            listing.append("%r (SN %s)" % (label, d.serial))
        raise DeviceNotFound("no camera with serial or name %r. Available: %s" % (key, ", ".join(listing)))


class DeviceInfo:
    """One enumerated camera (a copy of ``tSdkCameraDevInfo``).

    Text fields are decoded as ASCII, falling back to GBK.
    """

    def __init__(self, sdk: Sdk, raw: Any) -> None:
        self._sdk = sdk
        self.raw = raw
        self.series = decode_c_string(raw.acProductSeries)
        self.product = decode_c_string(raw.acProductName)
        self.friendly_name = decode_c_string(raw.acFriendlyName)
        self.link_name = decode_c_string(raw.acLinkName)
        self.driver_version = decode_c_string(raw.acDriverVersion)
        self.sensor_type = decode_c_string(raw.acSensorType)
        self.port_type = decode_c_string(raw.acPortType)
        self.serial = decode_c_string(raw.acSn)
        self.instance = int(raw.uInstance)

    @property
    def model(self) -> str:
        """Model display name (``acFriendlyName``; identical for all units of a model)."""
        return self.friendly_name

    @property
    def is_gige(self) -> bool:
        return "gige" in self.port_type.lower()

    def gige_ip(self) -> GigeIp:
        """Camera and host-NIC IP, mask, gateway (``CameraGigeGetIp``)."""
        return self._sdk.gige_get_ip(self)

    def gige_mac(self) -> GigeMac:
        """Camera and host-NIC MAC addresses (``CameraGigeGetMac``)."""
        return self._sdk.gige_get_mac(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "serial": self.serial,
            "model": self.model,
            "product": self.product,
            "series": self.series,
            "port_type": self.port_type,
            "sensor_type": self.sensor_type,
            "driver_version": self.driver_version,
            "instance": self.instance,
        }

    def __repr__(self) -> str:
        return "DeviceInfo(serial=%r, model=%r, product=%r, port_type=%r)" % (
            self.serial,
            self.model,
            self.product,
            self.port_type,
        )


def _aligned_empty(nbytes: int, alignment: int = 64) -> np.ndarray:
    """A 1-D uint8 array of ``nbytes`` whose data pointer is ``alignment``-aligned."""
    base = np.empty(nbytes + alignment, dtype=np.uint8)
    offset = (-base.ctypes.data) % alignment
    return base[offset : offset + nbytes]


def _shape_buffer(flat: np.ndarray, media_type: int, width: int, height: int) -> np.ndarray:
    """Reshape a flat byte buffer according to the media type, if the sizes agree."""
    bits = _ffi.media_type_bits(media_type)
    pixels = width * height
    n = flat.size
    if pixels <= 0:
        return flat
    if bits == 8 and n == pixels:
        return flat.reshape(height, width)
    if bits == 16 and n == pixels * 2 and media_type & _ffi.CAMERA_MEDIA_TYPE_MONO:
        return flat.view("<u2").reshape(height, width)
    if bits == 24 and n == pixels * 3:
        return flat.reshape(height, width, 3)
    if bits == 32 and n == pixels * 4:
        return flat.reshape(height, width, 4)
    if bits == 48 and n == pixels * 6:
        return flat.view("<u2").reshape(height, width, 3)
    return flat


class Camera:
    """An open camera handle. Close it with :meth:`close` or a ``with`` block."""

    def __init__(self, sdk: Sdk, device: DeviceInfo, handle: int) -> None:
        self._sdk = sdk
        self._lib = sdk.raw
        self.device = device
        self._handle = handle
        self._closed = False
        self._callback: Optional[Any] = None  # keeps the CFUNCTYPE wrapper alive
        self._callback_fn: Optional[Callable[["Frame"], None]] = None
        self._frames: "weakref.WeakSet[Frame]" = weakref.WeakSet()
        self._capability: Optional[_ffi.tSdkCameraCapbility] = None

    # -- lifetime ---------------------------------------------------------

    def __enter__(self) -> "Camera":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __del__(self) -> None:
        if getattr(self, "_closed", True) or sys.is_finalizing():
            return
        try:
            self.close()
        except Exception:
            pass

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def handle(self) -> int:
        if self._closed:
            raise GcamMvsdkError("camera is closed")
        return self._handle

    def close(self) -> None:
        """Release outstanding frames and call ``CameraUnInit``. Idempotent."""
        if self._closed:
            return
        for frame in list(self._frames):
            try:
                frame.release()
            except Exception:
                pass
        try:
            self._sdk._call("CameraUnInit", self._handle)
        finally:
            self._closed = True
            self._capability = None
            self._callback = None
            self._callback_fn = None

    def _call(self, name: str, *args: Any) -> None:
        self._sdk._call(name, self.handle, *args)

    def _get(self, name: str, ctype: Any) -> Any:
        value = ctype()
        self._call(name, byref(value))
        return value.value

    # -- identity ---------------------------------------------------------

    @property
    def user_name(self) -> str:
        """User-set name (DeviceUserID), stored in the camera's non-volatile memory."""
        buf = create_string_buffer(_ffi.NAME_BUFFER_SIZE)
        self._call("CameraGetFriendlyName", buf)
        return decode_c_string(buf.raw)

    @user_name.setter
    def user_name(self, name: str) -> None:
        bad = sorted(set(name) & _INVALID_NAME_CHARS)
        if bad:
            raise ValueError("camera name must not contain any of %s" % " ".join(bad))
        encoded = encode_c_string(name)
        if len(encoded) > _ffi.FRIENDLY_NAME_MAX_BYTES:
            raise ValueError("camera name is %d bytes; the limit is %d" % (len(encoded), _ffi.FRIENDLY_NAME_MAX_BYTES))
        buf = create_string_buffer(encoded, _ffi.NAME_BUFFER_SIZE)
        self._call("CameraSetFriendlyName", buf)

    @property
    def firmware_version(self) -> str:
        buf = create_string_buffer(_ffi.VERSION_BUFFER_SIZE)
        self._call("CameraGetFirmwareVersion", buf)
        return decode_c_string(buf.raw)

    # -- capability -------------------------------------------------------

    def capability(self) -> _ffi.tSdkCameraCapbility:
        """Raw ``tSdkCameraCapbility``; pointer members stay valid while the camera is open."""
        if self._capability is None:
            cap = _ffi.tSdkCameraCapbility()
            self._call("CameraGetCapability", byref(cap))
            self._capability = cap
        return self._capability

    @property
    def is_mono(self) -> bool:
        return bool(self.capability().sIspCapacity.bMonoSensor)

    @property
    def max_size(self) -> Tuple[int, int]:
        """Maximum sensor ``(width, height)``."""
        rr = self.capability().sResolutionRange
        return (rr.iWidthMax, rr.iHeightMax)

    def frame_speeds(self) -> List[IndexedDescription]:
        cap = self.capability()
        return [
            IndexedDescription(cap.pFrameSpeedDesc[i].iIndex, decode_c_string(cap.pFrameSpeedDesc[i].acDescription))
            for i in range(max(0, cap.iFrameSpeedDesc))
        ]

    def packet_sizes(self) -> List[PacketSize]:
        """GigE transport packet sizes the camera advertises."""
        cap = self.capability()
        return [
            PacketSize(
                cap.pPackLenDesc[i].iIndex,
                int(cap.pPackLenDesc[i].iPackSize),
                decode_c_string(cap.pPackLenDesc[i].acDescription),
            )
            for i in range(max(0, cap.iPackLenDesc))
        ]

    def resolutions(self) -> List[Resolution]:
        cap = self.capability()
        out = []
        for i in range(max(0, cap.iImageSizeDesc)):
            d = cap.pImageSizeDesc[i]
            out.append(Resolution(d.iIndex, d.iWidth, d.iHeight, decode_c_string(d.acDescription)))
        return out

    def media_types(self) -> List[Tuple[int, int, str]]:
        """``(index, media_type, description)`` for each sensor output type."""
        cap = self.capability()
        return [
            (
                cap.pMediaTypeDesc[i].iIndex,
                int(cap.pMediaTypeDesc[i].iMediaType),
                decode_c_string(cap.pMediaTypeDesc[i].acDescription),
            )
            for i in range(max(0, cap.iMediaTypdeDesc))
        ]

    def trigger_modes(self) -> List[IndexedDescription]:
        cap = self.capability()
        return [
            IndexedDescription(cap.pTriggerDesc[i].iIndex, decode_c_string(cap.pTriggerDesc[i].acDescription))
            for i in range(max(0, cap.iTriggerDesc))
        ]

    # -- exposure and gain ------------------------------------------------

    @property
    def auto_exposure(self) -> bool:
        return bool(self._get("CameraGetAeState", c_int))

    @auto_exposure.setter
    def auto_exposure(self, enabled: bool) -> None:
        self._call("CameraSetAeState", 1 if enabled else 0)

    @property
    def exposure_us(self) -> float:
        """Exposure time in microseconds. Setting it switches auto exposure off."""
        return float(self._get("CameraGetExposureTime", c_double))

    @exposure_us.setter
    def exposure_us(self, value: float) -> None:
        self._call("CameraSetAeState", 0)
        self._call("CameraSetExposureTime", float(value))

    def exposure_range_us(self) -> Tuple[float, float, float]:
        lo, hi, step = c_double(), c_double(), c_double()
        self._call("CameraGetExposureTimeRange", byref(lo), byref(hi), byref(step))
        return (lo.value, hi.value, step.value)

    @property
    def exposure_line_time_us(self) -> float:
        return float(self._get("CameraGetExposureLineTime", c_double))

    @property
    def analog_gain(self) -> int:
        return int(self._get("CameraGetAnalogGain", c_int))

    @analog_gain.setter
    def analog_gain(self, value: int) -> None:
        self._call("CameraSetAnalogGain", int(value))

    @property
    def analog_gain_x(self) -> float:
        """Analog gain as a multiplication factor."""
        return float(self._get("CameraGetAnalogGainX", c_float))

    @analog_gain_x.setter
    def analog_gain_x(self, value: float) -> None:
        self._call("CameraSetAnalogGainX", float(value))

    @property
    def digital_gain(self) -> Tuple[int, int, int]:
        """Per-channel digital gain ``(r, g, b)``."""
        r, g, b = c_int(), c_int(), c_int()
        self._call("CameraGetGain", byref(r), byref(g), byref(b))
        return (r.value, g.value, b.value)

    @property
    def gamma(self) -> int:
        return int(self._get("CameraGetGamma", c_int))

    @property
    def contrast(self) -> int:
        return int(self._get("CameraGetContrast", c_int))

    @property
    def saturation(self) -> int:
        return int(self._get("CameraGetSaturation", c_int))

    @property
    def sharpness(self) -> int:
        return int(self._get("CameraGetSharpness", c_int))

    # -- timing, format, trigger -----------------------------------------

    @property
    def frame_rate_hz(self) -> int:
        """Frame-rate limit in Hz; 0 (or less) means uncapped. Only some GigE models support it."""
        return int(self._get("CameraGetFrameRate", c_int))

    @frame_rate_hz.setter
    def frame_rate_hz(self, value: int) -> None:
        self._call("CameraSetFrameRate", int(value))

    @property
    def frame_speed(self) -> int:
        """Index into :meth:`frame_speeds` (readout speed tier)."""
        return int(self._get("CameraGetFrameSpeed", c_int))

    @frame_speed.setter
    def frame_speed(self, index: int) -> None:
        self._call("CameraSetFrameSpeed", int(index))

    @property
    def output_format(self) -> int:
        """ISP output media type used by :meth:`Frame.to_numpy` (for example :data:`Mono8`)."""
        return int(self._get("CameraGetIspOutFormat", c_uint))

    @output_format.setter
    def output_format(self, media_type: int) -> None:
        self._call("CameraSetIspOutFormat", int(media_type))

    @property
    def trigger_mode(self) -> int:
        """0 continuous, 1 software trigger, 2 hardware trigger."""
        return int(self._get("CameraGetTriggerMode", c_int))

    @trigger_mode.setter
    def trigger_mode(self, mode: int) -> None:
        self._call("CameraSetTriggerMode", int(mode))

    @property
    def trigger_delay_us(self) -> int:
        return int(self._get("CameraGetTriggerDelayTime", c_uint))

    @property
    def trigger_count(self) -> int:
        return int(self._get("CameraGetTriggerCount", c_int))

    @property
    def resolution(self) -> Tuple[int, int]:
        """Current output ``(width, height)``."""
        res = _ffi.tSdkImageResolution()
        self._call("CameraGetImageResolution", byref(res))
        return (res.iWidth, res.iHeight)

    # -- GigE transport ---------------------------------------------------

    @property
    def gige_packet_index(self) -> int:
        """Index into :meth:`packet_sizes` (``CameraGetTransPackLen``)."""
        return int(self._get("CameraGetTransPackLen", c_int))

    @gige_packet_index.setter
    def gige_packet_index(self, index: int) -> None:
        self._call("CameraSetTransPackLen", int(index))

    @property
    def gige_packet_size(self) -> int:
        """Current GigE packet size in bytes.

        Setting it selects the largest advertised size that does not exceed the
        requested value (the SDK selects packet sizes by index, not by bytes).
        """
        index = self.gige_packet_index
        for p in self.packet_sizes():
            if p.index == index:
                return p.size
        raise GcamMvsdkError("packet size index %d is not among the advertised sizes" % index)

    @gige_packet_size.setter
    def gige_packet_size(self, max_bytes: int) -> None:
        fitting = [p for p in self.packet_sizes() if p.size <= int(max_bytes)]
        if not fitting:
            sizes = ", ".join(str(p.size) for p in self.packet_sizes()) or "none"
            raise ValueError("no advertised packet size <= %d bytes (advertised: %s)" % (max_bytes, sizes))
        best = max(fitting, key=lambda p: p.size)
        self.gige_packet_index = best.index

    # -- streaming --------------------------------------------------------

    def play(self) -> None:
        self._call("CameraPlay")

    def pause(self) -> None:
        self._call("CameraPause")

    def stop(self) -> None:
        self._call("CameraStop")

    def clear_buffer(self) -> None:
        self._call("CameraClearBuffer")

    def soft_trigger(self) -> None:
        self._call("CameraSoftTrigger")

    def frame_statistic(self) -> FrameStatistic:
        stat = _ffi.tSdkFrameStatistic()
        self._call("CameraGetFrameStatistic", byref(stat))
        return FrameStatistic(stat.iTotal, stat.iCapture, stat.iLost)

    def save_parameter(self, team: int = _ffi.PARAMETER_TEAM_A) -> None:
        self._call("CameraSaveParameter", int(team))

    def load_parameter(self, team: int = _ffi.PARAMETER_TEAM_A) -> None:
        self._call("CameraLoadParameter", int(team))

    def grab(self, timeout_ms: int = 1000) -> "Frame":
        """Wait for the next frame (``CameraGetImageBuffer``).

        Returns a :class:`Frame`; use it as a context manager so the SDK buffer
        is released (``CameraReleaseImageBuffer``) promptly. Raises
        :class:`~gcam_mvsdk_py.MvTimeout` when no frame arrives in time. ctypes
        releases the GIL during the wait.
        """
        head = _ffi.tSdkFrameHead()
        pointer = c_void_p()
        self._call("CameraGetImageBuffer", byref(head), byref(pointer), int(timeout_ms))
        frame = Frame(self, pointer.value, head)
        self._frames.add(frame)
        return frame

    def set_callback(self, fn: Optional[Callable[["Frame"], None]]) -> None:
        """Deliver frames to ``fn(frame)`` from the SDK's capture thread.

        The frame is valid only during the call and is released afterwards.
        The ctypes wrapper is stored on this instance so it is not garbage
        collected while the SDK holds the pointer. ``None`` removes the callback.
        Exceptions raised by ``fn`` are printed to stderr; they cannot propagate
        into the SDK thread.
        """
        if fn is None:
            self.clear_callback()
            return
        camera_ref = weakref.ref(self)

        def trampoline(_handle: int, raw: Optional[int], head_ptr: Any, _context: Any) -> None:
            cam = camera_ref()
            if cam is None or cam._closed or cam._callback_fn is None:
                return
            try:
                head = _ffi.tSdkFrameHead.from_buffer_copy(head_ptr.contents)
                frame = Frame(cam, raw, head)
                try:
                    cam._callback_fn(frame)
                finally:
                    frame.release()
            except BaseException:  # noqa: BLE001 - nothing may escape into C
                traceback.print_exc()

        wrapper = _ffi.CAMERA_SNAP_PROC(trampoline)
        self._callback_fn = fn
        self._call("CameraSetCallbackFunction", wrapper, None, None)
        self._callback = wrapper

    def clear_callback(self) -> None:
        self._call("CameraSetCallbackFunction", _ffi.CAMERA_SNAP_PROC(), None, None)
        self._callback_fn = None
        self._callback = None

    def __repr__(self) -> str:
        state = "closed" if self._closed else "handle=%d" % self._handle
        return "Camera(%s, serial=%r)" % (state, self.device.serial)


class Frame:
    """One frame obtained from :meth:`Camera.grab`.

    :meth:`to_numpy` returns an independent copy (the default choice).
    :meth:`view` is a zero-copy view of the SDK buffer and is valid only until
    the frame is released (the end of its ``with`` block); using it afterwards
    can crash the interpreter.
    """

    def __init__(self, camera: Camera, pointer: Optional[int], head: Any) -> None:
        self._camera = camera
        self._pointer = pointer
        self.head = head
        self._released = pointer is None

    def __enter__(self) -> "Frame":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()

    def __del__(self) -> None:
        if getattr(self, "_released", True) or sys.is_finalizing():
            return
        warnings.warn("Frame was not released; use `with cam.grab() as frame:`", ResourceWarning, stacklevel=1)
        try:
            self.release()
        except Exception:
            pass

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        """Return the buffer to the SDK (``CameraReleaseImageBuffer``). Idempotent."""
        if self._released:
            return
        self._released = True
        cam = self._camera
        if not cam.closed:
            cam._sdk._call("CameraReleaseImageBuffer", cam.handle, self._pointer)

    @property
    def width(self) -> int:
        return int(self.head.iWidth)

    @property
    def height(self) -> int:
        return int(self.head.iHeight)

    @property
    def media_type(self) -> int:
        """Media type of the raw buffer (see :meth:`view`)."""
        return int(self.head.uiMediaType)

    @property
    def nbytes(self) -> int:
        return int(self.head.uBytes)

    @property
    def timestamp(self) -> int:
        """Camera timestamp in units of 0.1 ms (``uiTimeStamp``)."""
        return int(self.head.uiTimeStamp)

    @property
    def exposure_us(self) -> int:
        return int(self.head.uiExpTime)

    @property
    def is_trigger(self) -> bool:
        return bool(self.head.bIsTrigger)

    def _require_live(self) -> None:
        if self._released or self._pointer is None:
            raise GcamMvsdkError("frame buffer has been released")

    def view(self) -> np.ndarray:
        """Read-only zero-copy view of the raw SDK buffer (no ISP processing).

        Shaped ``(height, width)`` for 8-bit mono or Bayer data, otherwise flat.
        Valid only until :meth:`release`.
        """
        self._require_live()
        buffer = (ctypes.c_ubyte * self.nbytes).from_address(self._pointer)  # type: ignore[arg-type]
        flat = np.frombuffer(buffer, dtype=np.uint8)
        arr = _shape_buffer(flat, self.media_type, self.width, self.height)
        arr.flags.writeable = False
        return arr

    def to_numpy(self, process: bool = True) -> np.ndarray:
        """Copy the frame into a new array that outlives the SDK buffer.

        With ``process=True`` (default) the raw data passes through the SDK's
        ISP (``CameraImageProcess``) and comes out in the camera's
        ``output_format``: ``(h, w)`` uint8 for Mono8, ``(h, w, 3)`` for
        BGR8/RGB8, ``(h, w, 4)`` for BGRA8/RGBA8, ``(h, w)`` uint16 for Mono16.
        With ``process=False`` the raw bytes are copied unchanged.
        """
        self._require_live()
        if not process:
            return np.array(self.view(), copy=True)
        cam = self._camera
        try:
            out_format = cam.output_format
        except (MvError, FunctionUnavailable):
            out_format = Mono8 if cam.is_mono else BGR8
        bytes_per_pixel = max(1, (_ffi.media_type_bits(out_format) + 7) // 8)
        width = max(self.width, int(self.head.iWidthZoomSw))
        height = max(self.height, int(self.head.iHeightZoomSw))
        capacity = width * height * bytes_per_pixel
        out = _aligned_empty(capacity)
        out_head = _ffi.tSdkFrameHead.from_buffer_copy(self.head)
        cam._call("CameraImageProcess", self._pointer, out.ctypes.data, byref(out_head))
        used = int(out_head.uBytes) or capacity
        if used > capacity:  # pragma: no cover - would indicate an SDK contract change
            raise GcamMvsdkError("ISP output (%d bytes) exceeds the allocated %d bytes" % (used, capacity))
        arr = _shape_buffer(out[:used], int(out_head.uiMediaType), int(out_head.iWidth), int(out_head.iHeight))
        if _IS_WINDOWS and arr.ndim >= 2:
            # The Windows SDK writes ISP output bottom-up (DIB row order); the vendor's
            # own examples flip it with CameraFlipFrameBuffer. Return top-down rows on
            # every platform. view() and to_numpy(process=False) are never flipped.
            arr = np.ascontiguousarray(arr[::-1])
        return arr

    def __repr__(self) -> str:
        return "Frame(%dx%d, %s, %d bytes%s)" % (
            self.width,
            self.height,
            _ffi.media_type_name(self.media_type),
            self.nbytes,
            ", released" if self._released else "",
        )
