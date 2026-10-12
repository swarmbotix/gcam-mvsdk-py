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
from ctypes import POINTER, byref, c_double, c_float, c_int, c_uint, c_void_p, create_string_buffer
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple, Union

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


class ResolutionPreset(NamedTuple):
    """One entry of the camera's preset resolution table (``tSdkImageResolution``).

    ``bin_sum_mode``, ``bin_average_mode`` and ``skip_mode`` are the raw values the
    SDK reports; 0 means the preset does not use that mode. ``fov_*`` is the
    sensor area the preset reads out, ``width``/``height`` the output size.
    """

    index: int
    width: int
    height: int
    description: str
    bin_sum_mode: int
    bin_average_mode: int
    skip_mode: int
    fov_x: int
    fov_y: int
    fov_width: int
    fov_height: int


_PARAMETER_GROUPS = {"A": _ffi.PARAMETER_TEAM_A, "B": _ffi.PARAMETER_TEAM_B, "C": _ffi.PARAMETER_TEAM_C,
                     "D": _ffi.PARAMETER_TEAM_D, "DEFAULT": _ffi.PARAMETER_TEAM_DEFAULT}


def _parameter_group(group: Union[int, str], allow_default: bool) -> int:
    """Translate ``"A"``..``"D"`` (or ``"default"`` when loading) or an int to the SDK value."""
    if isinstance(group, str):
        key = group.strip().upper()
        if key not in _PARAMETER_GROUPS or (key == "DEFAULT" and not allow_default):
            allowed = "A, B, C, D" + (", default" if allow_default else "")
            raise ValueError("parameter group must be one of %s, not %r" % (allowed, group))
        return _PARAMETER_GROUPS[key]
    value = int(group)
    valid = {0, 1, 2, 3} | ({_ffi.PARAMETER_TEAM_DEFAULT} if allow_default else set())
    if value not in valid:
        raise ValueError("parameter group %d is not valid" % value)
    return value


def _raw_function(lib: Any, name: str, argtypes: Optional[Sequence[Any]], prefix: Sequence[Any]) -> Callable[..., Any]:
    """Look up ``name`` in the library and, for undeclared functions, apply ``argtypes``."""
    try:
        fn = getattr(lib, name)
    except AttributeError:
        raise FunctionUnavailable(name) from None
    if argtypes is not None and name not in _ffi.FUNCTIONS:
        fn.argtypes = list(prefix) + list(argtypes)
        fn.restype = _ffi.CameraSdkStatus
    return fn


def _int_property(get_name: str, set_name: str, doc: str, low: Optional[int] = None, high: Optional[int] = None) -> property:
    """Read/write property over a ``Get(handle, int*)`` / ``Set(handle, int)`` pair."""

    def fget(self: "Camera") -> int:
        return int(self._get(get_name, c_int))

    def fset(self: "Camera", value: int) -> None:
        value = int(value)
        if (low is not None and value < low) or (high is not None and value > high):
            raise ValueError("%s must be in [%s, %s], got %d" % (set_name, low, high, value))
        self._call(set_name, value)

    return property(fget, fset, doc=doc)


def _uint_property(get_name: str, set_name: str, doc: str) -> property:
    """Read/write property over a ``Get(handle, UINT*)`` / ``Set(handle, UINT)`` pair (microseconds etc.)."""

    def fget(self: "Camera") -> int:
        return int(self._get(get_name, c_uint))

    def fset(self: "Camera", value: int) -> None:
        if int(value) < 0:
            raise ValueError("%s takes a non-negative value, got %d" % (set_name, int(value)))
        self._call(set_name, int(value))

    return property(fget, fset, doc=doc)


def _bool_property(get_name: str, set_name: str, doc: str) -> property:
    """Read/write property over a ``Get(handle, BOOL*)`` / ``Set(handle, BOOL)`` pair."""

    def fget(self: "Camera") -> bool:
        return bool(self._get(get_name, c_int))

    def fset(self: "Camera", enabled: bool) -> None:
        self._call(set_name, 1 if enabled else 0)

    return property(fget, fset, doc=doc)


def _direction_property(get_name: str, set_name: str, direction: int, doc: str) -> property:
    """Read/write property over ``Get(handle, dir, BOOL*)`` / ``Set(handle, dir, BOOL)`` (mirroring)."""

    def fget(self: "Camera") -> bool:
        value = c_int()
        self._call(get_name, direction, byref(value))
        return bool(value.value)

    def fset(self: "Camera", enabled: bool) -> None:
        self._call(set_name, direction, 1 if enabled else 0)

    return property(fget, fset, doc=doc)


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

    def call(self, name: str, *args: Any, argtypes: Optional[Sequence[Any]] = None) -> None:
        """Call a library-level SDK function (no camera handle) and check its status.

        ``argtypes`` declares the C parameter types of a function this package
        does not declare itself; declared functions keep their own signature.
        Raises :class:`MvError` on a non-zero status.
        """
        fn = _raw_function(self._lib, name, argtypes, ())
        check(self._lib, fn(*args), name)

    def set_sys_option(self, name: str, value: Any) -> None:
        """``CameraSetSysOption``: SDK-wide option, normally set before opening a camera."""
        self._call("CameraSetSysOption", encode_c_string(name), encode_c_string(str(value)))

    def set_data_directory(self, path: str) -> None:
        """``CameraSetDataDirectory``: where the SDK keeps its .config files; set before opening a camera."""
        self._call("CameraSetDataDirectory", encode_c_string(str(path)))

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
        self._connection_callback: Optional[Any] = None  # keeps the wrapper alive
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
            self._connection_callback = None

    def _call(self, name: str, *args: Any) -> None:
        self._sdk._call(name, self.handle, *args)

    def _get(self, name: str, ctype: Any) -> Any:
        value = ctype()
        self._call(name, byref(value))
        return value.value

    def _get_many(self, name: str, *ctypes_: Any) -> Tuple[Any, ...]:
        values = [t() for t in ctypes_]
        self._call(name, *[byref(v) for v in values])
        return tuple(v.value for v in values)

    @property
    def sdk(self) -> Sdk:
        """The :class:`Sdk` this camera was opened with."""
        return self._sdk

    # -- raw access to functions without a wrapper ----------------------------

    def call(self, name: str, *args: Any, argtypes: Optional[Sequence[Any]] = None) -> None:
        """Call ``name(handle, *args)`` and raise :class:`MvError` on a non-zero status.

        For a function this package does not declare, pass ``argtypes`` for the
        parameters after the handle, for example ``argtypes=[c_int, c_double]``.
        Unsupported features usually fail with status -4 (not supported).
        """
        fn = _raw_function(self._lib, name, argtypes, (_ffi.CameraHandle,))
        check(self._lib, fn(self.handle, *args), name)

    def query(self, name: str, *out_types: Any, args: Sequence[Any] = (), argtypes: Optional[Sequence[Any]] = None) -> Any:
        """Call ``name(handle, *args, &out1, &out2, ...)`` and return the output values.

        ``out_types`` are ctypes scalar types such as ``c_int`` or ``c_double``;
        one output is returned as a value, several as a tuple. ``argtypes`` covers
        only ``args`` (the inputs); the output pointer types are added for you.
        """
        outs = [t() for t in out_types]
        full = None if argtypes is None else list(argtypes) + [POINTER(t) for t in out_types]
        self.call(name, *args, *[byref(o) for o in outs], argtypes=full)
        values = tuple(o.value for o in outs)
        return values[0] if len(values) == 1 else values

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

    def read_sn(self, level: int) -> str:
        """Read serial-number level 1 or 2 (``CameraReadSN``); level 0 is the factory serial.

        Writing serial numbers (``CameraWriteSN``) is deliberately not wrapped.
        """
        if level not in (1, 2):
            raise ValueError("serial-number level must be 1 or 2")
        buf = create_string_buffer(_ffi.SN_BUFFER_SIZE + 1)
        self._call("CameraReadSN", buf, int(level))
        return decode_c_string(buf.raw)

    @property
    def user_data_size(self) -> int:
        """Bytes of user data the camera can store (``iUserDataMaxLen``; 0 = none)."""
        return int(self.capability().iUserDataMaxLen)

    def _check_user_data_range(self, offset: int, length: int) -> None:
        size = self.user_data_size
        if offset < 0 or length < 0 or offset + length > size:
            raise ValueError("user data range [%d, %d) exceeds the camera's %d bytes" % (offset, offset + length, size))

    def read_user_data(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes of user data stored in the camera (``CameraLoadUserData``)."""
        self._check_user_data_range(int(offset), int(length))
        buf = create_string_buffer(int(length))
        self._call("CameraLoadUserData", int(offset), buf, int(length))
        return buf.raw[: int(length)]

    def write_user_data(self, offset: int, data: bytes) -> None:
        """Store ``data`` in the camera's non-volatile user area (``CameraSaveUserData``)."""
        data = bytes(data)
        self._check_user_data_range(int(offset), len(data))
        self._call("CameraSaveUserData", int(offset), create_string_buffer(data, len(data)), len(data))

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

    def resolution_presets(self) -> List[ResolutionPreset]:
        """The preset resolution table with binning/skip modes and sensor field of view."""
        cap = self.capability()
        out = []
        for i in range(max(0, cap.iImageSizeDesc)):
            d = cap.pImageSizeDesc[i]
            out.append(ResolutionPreset(
                d.iIndex, d.iWidth, d.iHeight, decode_c_string(d.acDescription),
                int(d.uBinSumMode), int(d.uBinAverageMode), int(d.uSkipMode),
                d.iHOffsetFOV, d.iVOffsetFOV, d.iWidthFOV, d.iHeightFOV,
            ))
        return out

    def binning_modes(self) -> Dict[str, List[int]]:
        """Supported binning/skip factors from the capability masks (bit 0 = 2x2, bit 1 = 3x3, ...)."""
        rr = self.capability().sResolutionRange

        def factors(mask: int) -> List[int]:
            return [bit + 2 for bit in range(32) if mask & (1 << bit)]

        return {
            "sum": factors(int(rr.uBinSumModeMask)),
            "average": factors(int(rr.uBinAverageModeMask)),
            "skip": factors(int(rr.uSkipModeMask)),
        }

    def color_temperature_presets(self) -> List[IndexedDescription]:
        """Preset colour temperatures for white balance (``pClrTempDesc``)."""
        cap = self.capability()
        return [
            IndexedDescription(cap.pClrTempDesc[i].iIndex, decode_c_string(cap.pClrTempDesc[i].acDescription))
            for i in range(max(0, cap.iClrTempDesc))
        ]

    def capability_summary(self) -> Dict[str, Any]:
        """The capability struct as plain data: which features exist and their ranges.

        This is what ``gcam-mvsdk-py info`` prints under "Capability". Values come
        from the camera; units follow the header (exposure range in sensor lines,
        analog gain in steps of ``analog_gain_step``, digital gain 100 = 1.0x).
        """
        cap = self.capability()
        ed, rr, isp, rgb = cap.sExposeDesc, cap.sResolutionRange, cap.sIspCapacity, cap.sRgbGainRange
        return {
            "mono_sensor": bool(isp.bMonoSensor),
            "auto_exposure": bool(isp.bAutoExposure),
            "manual_exposure": bool(isp.bManualExposure),
            "anti_flicker": bool(isp.bAntiFlick),
            "auto_white_balance": bool(isp.bAutoWb),
            "once_white_balance": bool(isp.bWbOnce),
            "device_isp": bool(isp.bDeviceIsp),
            "device_isp_forced": bool(isp.bForceUseDeviceIsp),
            "hardware_zoom": bool(isp.bZoomHD),
            "ae_target_range": [int(ed.uiTargetMin), int(ed.uiTargetMax)],
            "analog_gain_range": [int(ed.uiAnalogGainMin), int(ed.uiAnalogGainMax)],
            "analog_gain_step": round(float(ed.fAnalogGainStep), 6),
            "exposure_range_lines": [int(ed.uiExposeTimeMin), int(ed.uiExposeTimeMax)],
            "rgb_gain_range": [[rgb.iRGainMin, rgb.iRGainMax], [rgb.iGGainMin, rgb.iGGainMax], [rgb.iBGainMin, rgb.iBGainMax]],
            "gamma_range": [cap.sGammaRange.iMin, cap.sGammaRange.iMax],
            "contrast_range": [cap.sContrastRange.iMin, cap.sContrastRange.iMax],
            "saturation_range": [cap.sSaturationRange.iMin, cap.sSaturationRange.iMax],
            "sharpness_range": [cap.sSharpnessRange.iMin, cap.sSharpnessRange.iMax],
            "width_range": [rr.iWidthMin, rr.iWidthMax],
            "height_range": [rr.iHeightMin, rr.iHeightMax],
            "binning": self.binning_modes(),
            "resolution_presets": len(self.resolution_presets()),
            "trigger_modes": [t.description for t in self.trigger_modes()],
            "frame_speeds": [f.description for f in self.frame_speeds()],
            "packet_sizes": [p.size for p in self.packet_sizes()],
            "color_temperature_presets": [c.description for c in self.color_temperature_presets()],
            "preset_luts": int(cap.iPresetLut),
            "bayer_algorithms_pc": int(cap.iBayerDecAlmSwDesc),
            "bayer_algorithms_device": int(cap.iBayerDecAlmHdDesc),
            "inputs": int(cap.iInputIoCounts),
            "outputs": int(cap.iOutputIoCounts),
            "user_data_bytes": int(cap.iUserDataMaxLen),
            "parameters_in_device": bool(cap.bParamInDevice),
        }

    @property
    def io_counts(self) -> Tuple[int, int]:
        """Number of programmable ``(inputs, outputs)`` (``iInputIoCounts``, ``iOutputIoCounts``)."""
        cap = self.capability()
        return (int(cap.iInputIoCounts), int(cap.iOutputIoCounts))

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

    def analog_gain_x_range(self) -> Tuple[float, float, float]:
        """``(min, max, step)`` of :attr:`analog_gain_x` (``CameraGetAnalogGainXRange``)."""
        return self._get_many("CameraGetAnalogGainXRange", c_float, c_float, c_float)

    @property
    def digital_gain(self) -> Tuple[int, int, int]:
        """Per-channel digital gain ``(r, g, b)``; 100 means 1.0x (``CameraSetGain``/``CameraGetGain``).

        The range is in the capability struct, ``sRgbGainRange``.
        """
        return self._get_many("CameraGetGain", c_int, c_int, c_int)

    @digital_gain.setter
    def digital_gain(self, rgb: Sequence[int]) -> None:
        r, g, b = (int(v) for v in rgb)
        self._call("CameraSetGain", r, g, b)

    ae_target = _int_property(
        "CameraGetAeTarget", "CameraSetAeTarget",
        "Auto-exposure brightness target; range in ``capability().sExposeDesc`` (uiTargetMin/Max).")
    ae_threshold = _int_property(
        "CameraGetAeThreshold", "CameraSetAeThreshold",
        "Auto exposure stops adjusting while abs(target - brightness) is below this value.")

    @property
    def ae_exposure_range_us(self) -> Tuple[float, float]:
        """``(min, max)`` exposure in microseconds that auto exposure may use."""
        return self._get_many("CameraGetAeExposureRange", c_double, c_double)

    @ae_exposure_range_us.setter
    def ae_exposure_range_us(self, limits: Sequence[float]) -> None:
        lo, hi = (float(v) for v in limits)
        self._call("CameraSetAeExposureRange", lo, hi)

    @property
    def ae_analog_gain_range(self) -> Tuple[int, int]:
        """``(min, max)`` analog gain (in :attr:`analog_gain` units) that auto exposure may use."""
        return self._get_many("CameraGetAeAnalogGainRange", c_int, c_int)

    @ae_analog_gain_range.setter
    def ae_analog_gain_range(self, limits: Sequence[int]) -> None:
        lo, hi = (int(v) for v in limits)
        self._call("CameraSetAeAnalogGainRange", lo, hi)

    @property
    def ae_window(self) -> Tuple[int, int, int, int]:
        """Auto-exposure reference window ``(x, y, width, height)``.

        All zeros selects the centred half-size window, which follows resolution changes.
        """
        return self._get_many("CameraGetAeWindow", c_int, c_int, c_int, c_int)

    @ae_window.setter
    def ae_window(self, window: Sequence[int]) -> None:
        x, y, w, h = (int(v) for v in window)
        self._call("CameraSetAeWindow", x, y, w, h)

    anti_flicker = _bool_property(
        "CameraGetAntiFlick", "CameraSetAntiFlick",
        "Anti-flicker for auto exposure (no effect in manual exposure); see ``capability().sIspCapacity.bAntiFlick``.")

    @property
    def light_frequency_hz(self) -> int:
        """Mains frequency anti-flicker works against: 50 or 60 (``CameraSetLightFrequency``)."""
        return 50 if self._get("CameraGetLightFrequency", c_int) == _ffi.LIGHT_FREQUENCY_50HZ else 60

    @light_frequency_hz.setter
    def light_frequency_hz(self, hz: int) -> None:
        selector = {50: _ffi.LIGHT_FREQUENCY_50HZ, 60: _ffi.LIGHT_FREQUENCY_60HZ}.get(int(hz))
        if selector is None:
            raise ValueError("light frequency must be 50 or 60 Hz")
        self._call("CameraSetLightFrequency", selector)

    # -- image processing (ISP) -------------------------------------------

    gamma = _int_property(
        "CameraGetGamma", "CameraSetGamma",
        "Gamma used when the LUT is generated from parameters (``lut_mode`` 0); range ``sGammaRange``.")
    contrast = _int_property(
        "CameraGetContrast", "CameraSetContrast",
        "Contrast used when the LUT is generated from parameters (``lut_mode`` 0); range ``sContrastRange``.")
    saturation = _int_property(
        "CameraGetSaturation", "CameraSetSaturation",
        "Colour saturation, 100 = unchanged; no effect on mono cameras; range ``sSaturationRange``.")
    sharpness = _int_property(
        "CameraGetSharpness", "CameraSetSharpness",
        "Sharpening, 0 = off; range ``sSharpnessRange`` (the header says usually 0 to 100).")
    black_level = _int_property(
        "CameraGetBlackLevel", "CameraSetBlackLevel", "Black level reference, 0 to 255 (default 0).", 0, 255)
    white_level = _int_property(
        "CameraGetWhiteLevel", "CameraSetWhiteLevel", "White level reference, 0 to 255 (default 255).", 0, 255)
    isp_processor = _int_property(
        "CameraGetIspProcessor", "CameraSetIspProcessor",
        "Where the ISP runs: ``ISP_PROCESSOR_PC`` (0) or ``ISP_PROCESSOR_DEVICE`` (1, if ``bDeviceIsp``).")
    monochrome = _bool_property(
        "CameraGetMonochrome", "CameraSetMonochrome", "Convert colour images to grey in the ISP.")
    noise_filter = _bool_property(
        "CameraGetNoiseFilterState", "CameraSetNoiseFilter", "Enable the ISP noise filter.")
    dead_pixel_correction = _bool_property(
        "CameraGetCorrectDeadPixel", "CameraSetCorrectDeadPixel", "Enable dead-pixel correction.")
    auto_white_balance = _bool_property(
        "CameraGetWbMode", "CameraSetWbMode",
        "Continuous auto white balance (``bAutoWb``); False = manual, use :meth:`white_balance_once`.")
    color_temperature_mode = _int_property(
        "CameraGetClrTempMode", "CameraSetClrTempMode",
        "White-balance colour temperature mode: ``CT_MODE_AUTO``, ``CT_MODE_PRESET``, ``CT_MODE_USER_DEF``.")
    preset_color_temperature = _int_property(
        "CameraGetPresetClrTemp", "CameraSetPresetClrTemp",
        "Index into :meth:`color_temperature_presets`, used in ``CT_MODE_PRESET``.")
    lut_mode = _int_property(
        "CameraGetLutMode", "CameraSetLutMode",
        "``LUTMODE_PARAM_GEN`` (gamma/contrast), ``LUTMODE_PRESET`` or ``LUTMODE_USER_DEF``.")

    def white_balance_once(self) -> None:
        """One white balance in manual mode; takes effect with the next frame (``CameraSetOnceWB``)."""
        self._call("CameraSetOnceWB")

    def black_balance_once(self) -> None:
        """One black balance (``CameraSetOnceBB``)."""
        self._call("CameraSetOnceBB")

    @property
    def wb_window(self) -> Tuple[int, int, int, int]:
        """White-balance reference window ``(x, y, width, height)``."""
        return self._get_many("CameraGetWbWindow", c_int, c_int, c_int, c_int)

    @wb_window.setter
    def wb_window(self, window: Sequence[int]) -> None:
        x, y, w, h = (int(v) for v in window)
        self._call("CameraSetWbWindow", x, y, w, h)

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

    trigger_count = _int_property(
        "CameraGetTriggerCount", "CameraSetTriggerCount",
        "Frames captured per trigger (software and hardware trigger); default 1.", 1, None)
    trigger_delay_us = _uint_property(
        "CameraGetTriggerDelayTime", "CameraSetTriggerDelayTime",
        "Delay in microseconds between a hardware trigger and capture (only some models).")
    trigger_period_us = _uint_property(
        "CameraGetTriggerPeriodTime", "CameraSetTriggerPeriodTime",
        "Interval in microseconds between frames when one trigger captures several (only some models).")
    ext_trigger_signal = _int_property(
        "CameraGetExtTrigSignalType", "CameraSetExtTrigSignalType",
        "``EXT_TRIG_LEADING_EDGE`` (default), ``EXT_TRIG_TRAILING_EDGE``, ``EXT_TRIG_HIGH_LEVEL``, ``EXT_TRIG_LOW_LEVEL``.")
    ext_trigger_shutter = _int_property(
        "CameraGetExtTrigShutterType", "CameraSetExtTrigShutterType",
        "``EXT_TRIG_EXP_STANDARD`` (default) or ``EXT_TRIG_EXP_GRR`` (some rolling-shutter models).")
    ext_trigger_delay_us = _uint_property(
        "CameraGetExtTrigDelayTime", "CameraSetExtTrigDelayTime",
        "Delay in microseconds after an external trigger before capture; default 0.")
    ext_trigger_buffered_delay_us = _uint_property(
        "CameraGetExtTrigBufferedDelayTime", "CameraSetExtTrigBufferedDelayTime",
        "Like ``ext_trigger_delay_us`` but triggers arriving during the delay are queued (up to 128).")
    ext_trigger_interval_us = _uint_property(
        "CameraGetExtTrigIntervalTime", "CameraSetExtTrigIntervalTime",
        "External trigger signal interval time in microseconds; default 0.")
    ext_trigger_jitter_us = _uint_property(
        "CameraGetExtTrigJitterTime", "CameraSetExtTrigJitterTime",
        "Debounce time in microseconds for the external trigger input; default 0.")

    @property
    def ext_trigger_capability(self) -> int:
        """Bit mask of ``EXT_TRIG_MASK_*`` features this model supports (``CameraGetExtTrigCapability``)."""
        return int(self._get("CameraGetExtTrigCapability", c_uint))

    @property
    def resolution(self) -> Tuple[int, int]:
        """Current output ``(width, height)``."""
        res = _ffi.tSdkImageResolution()
        self._call("CameraGetImageResolution", byref(res))
        return (res.iWidth, res.iHeight)

    def set_resolution(self, index: int) -> None:
        """Select a preset from :meth:`resolution_presets` by its index (``CameraSetImageResolution``)."""
        cap = self.capability()
        for i in range(max(0, cap.iImageSizeDesc)):
            if cap.pImageSizeDesc[i].iIndex == int(index):
                preset = _ffi.tSdkImageResolution.from_buffer_copy(cap.pImageSizeDesc[i])
                self._call("CameraSetImageResolution", byref(preset))
                return
        known = ", ".join(str(p.index) for p in self.resolution_presets()) or "none"
        raise ValueError("no preset resolution with index %d (presets: %s)" % (int(index), known))

    def set_roi(self, x: int, y: int, width: int, height: int) -> None:
        """Read out only a sensor region (custom resolution, ``CameraSetImageResolutionEx``).

        The SDK may adjust the values to the sensor's alignment; read
        :attr:`resolution` afterwards. ``set_roi(0, 0, *cam.max_size)`` restores full frame.
        """
        x, y, width, height = int(x), int(y), int(width), int(height)
        max_w, max_h = self.max_size
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > max_w or y + height > max_h:
            raise ValueError("ROI %dx%d at (%d, %d) does not fit the %dx%d sensor" % (width, height, x, y, max_w, max_h))
        self._call("CameraSetImageResolutionEx", _ffi.RESOLUTION_INDEX_CUSTOM, 0, 0, x, y, width, height, 0, 0)

    mirror_horizontal = _direction_property(
        "CameraGetMirror", "CameraSetMirror", _ffi.MIRROR_DIRECTION_HORIZONTAL, "Mirror left-right in the ISP.")
    mirror_vertical = _direction_property(
        "CameraGetMirror", "CameraSetMirror", _ffi.MIRROR_DIRECTION_VERTICAL, "Mirror top-bottom in the ISP.")
    hardware_mirror_horizontal = _direction_property(
        "CameraGetHardwareMirror", "CameraSetHardwareMirror", _ffi.MIRROR_DIRECTION_HORIZONTAL,
        "Mirror left-right in the camera itself (only some GigE and USB3 models).")
    hardware_mirror_vertical = _direction_property(
        "CameraGetHardwareMirror", "CameraSetHardwareMirror", _ffi.MIRROR_DIRECTION_VERTICAL,
        "Mirror top-bottom in the camera itself (only some GigE and USB3 models).")

    @property
    def rotation_deg(self) -> int:
        """Counter-clockwise rotation applied by the ISP: 0, 90, 180 or 270 (``CameraSetRotate``)."""
        return int(self._get("CameraGetRotate", c_int)) * 90

    @rotation_deg.setter
    def rotation_deg(self, degrees: int) -> None:
        if int(degrees) not in (0, 90, 180, 270):
            raise ValueError("rotation must be 0, 90, 180 or 270 degrees")
        self._call("CameraSetRotate", int(degrees) // 90)

    # -- digital I/O and strobe -------------------------------------------

    def _check_io(self, index: int, outputs: bool) -> int:
        inputs, outs = self.io_counts
        count = outs if outputs else inputs
        if not 0 <= int(index) < count:
            kind = "output" if outputs else "input"
            raise ValueError("%s index %d out of range; this camera has %d %ss" % (kind, int(index), count, kind))
        return int(index)

    def get_input(self, index: int) -> bool:
        """Level of programmable input ``index``: True = high (``CameraGetIOStateEx``)."""
        state = c_uint()
        self._call("CameraGetIOStateEx", self._check_io(index, False), byref(state))
        return bool(state.value)

    def get_output(self, index: int) -> bool:
        """Level of programmable output ``index``: True = high (``CameraGetOutPutIOStateEx``)."""
        state = c_uint()
        self._call("CameraGetOutPutIOStateEx", self._check_io(index, True), byref(state))
        return bool(state.value)

    def set_output(self, index: int, high: bool) -> None:
        """Drive programmable output ``index`` high or low (``CameraSetIOStateEx``)."""
        self._call("CameraSetIOStateEx", self._check_io(index, True), 1 if high else 0)

    strobe_mode = _int_property(
        "CameraGetStrobeMode", "CameraSetStrobeMode",
        "``STROBE_SYNC_WITH_TRIG_AUTO``, ``STROBE_SYNC_WITH_TRIG_MANUAL``, ``STROBE_ALWAYS_HIGH`` or ``STROBE_ALWAYS_LOW``.")
    strobe_polarity = _int_property(
        "CameraGetStrobePolarity", "CameraSetStrobePolarity", "Active level of the strobe: 1 high (default), 0 low.", 0, 1)
    strobe_delay_us = _uint_property(
        "CameraGetStrobeDelayTime", "CameraSetStrobeDelayTime",
        "Strobe delay after the trigger in microseconds (``STROBE_SYNC_WITH_TRIG_MANUAL``).")
    strobe_pulse_width_us = _uint_property(
        "CameraGetStrobePulseWidth", "CameraSetStrobePulseWidth",
        "Strobe pulse width in microseconds (``STROBE_SYNC_WITH_TRIG_MANUAL``).")

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

    def set_frame_resend_count(self, count: int) -> None:
        """Resends of a frame the PC did not acknowledge, in trigger mode (GigE only; <= 0 disables).

        The SDK offers no getter for this value.
        """
        self._call("CameraSetFrameResendCount", int(count))

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

    def save_parameter(self, group: Union[int, str] = "A") -> None:
        """Save the current settings to parameter group ``"A"`` to ``"D"`` (``CameraSaveParameter``)."""
        self._call("CameraSaveParameter", _parameter_group(group, allow_default=False))

    def load_parameter(self, group: Union[int, str] = "A") -> None:
        """Load group ``"A"`` to ``"D"``, or ``"default"`` for factory defaults (``CameraLoadParameter``)."""
        self._call("CameraLoadParameter", _parameter_group(group, allow_default=True))

    @property
    def parameter_group(self) -> int:
        """Currently selected parameter group (0 to 3 for A to D, 255 for defaults)."""
        return int(self._get("CameraGetCurrentParameterGroup", c_int))

    def save_parameter_to_file(self, path: str) -> None:
        """Write the current settings to a .config file (``CameraSaveParameterToFile``)."""
        self._call("CameraSaveParameterToFile", encode_c_string(str(path)))

    def load_parameter_from_file(self, path: str) -> None:
        """Load settings from a .config file (``CameraReadParameterFromFile``)."""
        self._call("CameraReadParameterFromFile", encode_c_string(str(path)))

    parameter_mode = _int_property(
        "CameraGetParameterMode", "CameraSetParameterMode",
        "Where parameter groups are stored: ``PARAM_MODE_BY_MODEL``, ``_BY_NAME``, ``_BY_SN`` or ``_IN_DEVICE``.")

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

    def set_connection_callback(self, fn: Optional[Callable[[bool, int], None]]) -> None:
        """Call ``fn(connected, reason)`` when the camera drops out or comes back.

        ``connected`` is False on disconnect and True when the connection is
        restored. For GigE cameras, on reconnect ``reason`` is 0 when the last
        drop was a network failure and 1 when the camera lost power; otherwise it
        is undefined. Runs on an SDK thread; exceptions are printed, not raised.
        ``None`` removes the callback.
        """
        if fn is None:
            self._call("CameraSetConnectionStatusCallback", _ffi.CAMERA_CONNECTION_STATUS_CALLBACK(), None)
            self._connection_callback = None
            return

        def trampoline(_handle: int, msg: int, param: int, _context: Any) -> None:
            try:
                fn(msg == 1, int(param))
            except BaseException:  # noqa: BLE001 - nothing may escape into C
                traceback.print_exc()

        wrapper = _ffi.CAMERA_CONNECTION_STATUS_CALLBACK(trampoline)
        self._call("CameraSetConnectionStatusCallback", wrapper, None)
        self._connection_callback = wrapper

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
