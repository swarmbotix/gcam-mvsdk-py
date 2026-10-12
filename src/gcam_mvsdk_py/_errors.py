"""Exception types raised by :mod:`gcam_mvsdk_py`."""

from __future__ import annotations

from typing import Iterable, List, Optional

from . import _ffi


class GcamMvsdkError(Exception):
    """Base class of every exception raised by this package."""


class SdkNotFound(GcamMvsdkError):
    """The vendor library could not be located or opened.

    ``searched`` lists every location that was tried, in order.
    """

    def __init__(self, searched: Iterable[str], detail: Optional[str] = None) -> None:
        self.searched: List[str] = list(searched)
        self.detail = detail
        lines = ["HuaTeng MVSDK library not found."]
        if detail:
            lines.append(detail)
        if self.searched:
            lines.append("Searched:")
            lines.extend("  - %s" % s for s in self.searched)
        lines.append(
            "Run `gcam-mvsdk-py setup` to download it into ~/.gcam-mvsdk/, or set "
            "GCAM_MVSDK_DIR to an extracted SDK directory (the one containing lib/)."
        )
        super().__init__("\n".join(lines))


class MvError(GcamMvsdkError):
    """A call into the SDK returned a non-success status.

    Attributes:
        status: numeric ``CameraSdkStatus`` value.
        name: symbolic name of the status (for example ``CAMERA_STATUS_TIME_OUT``).
        message: text from ``CameraGetErrorString`` when available, otherwise
            this package's own description.
        function: name of the SDK function that failed, if known.
    """

    def __init__(self, status: int, message: Optional[str] = None, function: Optional[str] = None) -> None:
        self.status = int(status)
        self.name = _ffi.status_name(self.status)
        self.message = message or _ffi.status_text(self.status)
        self.function = function
        prefix = "%s failed: " % function if function else ""
        super().__init__("%s%s (status %d, %s)" % (prefix, self.message, self.status, self.name))


class MvTimeout(MvError, TimeoutError):
    """``CameraGetImageBuffer`` timed out (``CAMERA_STATUS_TIME_OUT``)."""


class DeviceNotFound(GcamMvsdkError, LookupError):
    """No enumerated camera matches the requested serial number or name."""


class FunctionUnavailable(GcamMvsdkError):
    """The loaded library does not export a function this package needs."""

    def __init__(self, name: str) -> None:
        self.function = name
        super().__init__("the loaded MVSDK library does not export %s" % name)


def decode_c_string(raw: bytes) -> str:
    """Decode a NUL-terminated C string as ASCII, falling back to GBK.

    The SDK never documents UTF-8; camera names and messages are either ASCII
    or GBK (the Simplified Chinese code page). Undecodable bytes are replaced
    rather than raising.
    """
    if raw is None:
        return ""
    raw = bytes(raw).split(b"\0", 1)[0]
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gbk")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def encode_c_string(text: str) -> bytes:
    """Encode ``text`` for the SDK: ASCII when possible, otherwise GBK."""
    try:
        return text.encode("ascii")
    except UnicodeEncodeError:
        return text.encode("gbk")


def error_from_status(lib: object, status: int, function: Optional[str] = None) -> MvError:
    """Build an :class:`MvError` (or :class:`MvTimeout`) for ``status``.

    The message comes from ``CameraGetErrorString`` in ``lib`` when the call
    succeeds; otherwise the package's own status table is used.
    """
    message: Optional[str] = None
    getter = getattr(lib, "CameraGetErrorString", None) if lib is not None else None
    if getter is not None:
        try:
            raw = getter(int(status))
            if raw:
                message = decode_c_string(raw).strip() or None
        except Exception:  # pragma: no cover - defensive: never mask the real error
            message = None
    cls = MvTimeout if status == _ffi.CAMERA_STATUS_TIME_OUT else MvError
    return cls(status, message, function)


def check(lib: object, status: int, function: str) -> None:
    """Raise :class:`MvError` unless ``status`` is ``CAMERA_STATUS_SUCCESS``."""
    if status != _ffi.CAMERA_STATUS_SUCCESS:
        raise error_from_status(lib, status, function)
