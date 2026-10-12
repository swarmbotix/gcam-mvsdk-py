"""Python wrapper for the HuaTeng MVSDK industrial camera SDK.

The vendor library is not bundled. It is located at runtime (see
:mod:`gcam_mvsdk_py._loader`); install it with ``gcam-mvsdk-py setup`` or point
``GCAM_MVSDK_DIR`` at an extracted SDK.

Example::

    import gcam_mvsdk_py

    sdk = gcam_mvsdk_py.load()
    for dev in sdk.enumerate():
        print(dev.serial, dev.model, dev.port_type)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from ._errors import (
    DeviceNotFound,
    FunctionUnavailable,
    GcamMvsdkError,
    MvError,
    MvTimeout,
    SdkNotFound,
)
from ._ffi import (
    PARAMETER_TEAM_A,
    PARAMETER_TEAM_B,
    PARAMETER_TEAM_C,
    PARAMETER_TEAM_D,
    TRIGGER_CONTINUOUS,
    TRIGGER_HARDWARE,
    TRIGGER_SOFTWARE,
)
from ._loader import detect_arch, find_library

if TYPE_CHECKING:  # pragma: no cover
    from .api import DeviceInfo

try:  # single source of truth: the version in pyproject.toml, via installed metadata
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _distribution_version

    __version__ = _distribution_version("gcam-mvsdk-py")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0+unknown"

_API_NAMES = (
    "BGR8",
    "BGRA8",
    "Camera",
    "DeviceInfo",
    "Frame",
    "FrameStatistic",
    "GigeIp",
    "GigeMac",
    "Mono16",
    "Mono8",
    "PacketSize",
    "RGB8",
    "RGBA8",
    "Sdk",
    "load",
)

__all__ = [
    "DeviceNotFound",
    "FunctionUnavailable",
    "GcamMvsdkError",
    "MvError",
    "MvTimeout",
    "SdkNotFound",
    "PARAMETER_TEAM_A",
    "PARAMETER_TEAM_B",
    "PARAMETER_TEAM_C",
    "PARAMETER_TEAM_D",
    "TRIGGER_CONTINUOUS",
    "TRIGGER_HARDWARE",
    "TRIGGER_SOFTWARE",
    "detect_arch",
    "enumerate",
    "find_library",
    "__version__",
    *_API_NAMES,
]


def __getattr__(name: str):  # PEP 562: import numpy-dependent API lazily
    if name in _API_NAMES:
        from . import api

        return getattr(api, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def enumerate(path: Optional[str] = None) -> List["DeviceInfo"]:  # noqa: A001 - mirrors Sdk.enumerate
    """Shorthand for ``load(path).enumerate()``."""
    from . import api

    return api.load(path).enumerate()
