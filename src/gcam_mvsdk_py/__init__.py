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
    CT_MODE_AUTO,
    CT_MODE_PRESET,
    CT_MODE_USER_DEF,
    EXT_TRIG_EXP_GRR,
    EXT_TRIG_EXP_STANDARD,
    EXT_TRIG_HIGH_LEVEL,
    EXT_TRIG_LEADING_EDGE,
    EXT_TRIG_LOW_LEVEL,
    EXT_TRIG_MASK_BUFFERED_DELAY,
    EXT_TRIG_MASK_DOUBLE_EDGE,
    EXT_TRIG_MASK_GRR_SHUTTER,
    EXT_TRIG_MASK_LEVEL_MODE,
    EXT_TRIG_TRAILING_EDGE,
    ISP_PROCESSOR_DEVICE,
    ISP_PROCESSOR_PC,
    LUTMODE_PARAM_GEN,
    LUTMODE_PRESET,
    LUTMODE_USER_DEF,
    PARAMETER_TEAM_A,
    PARAMETER_TEAM_B,
    PARAMETER_TEAM_C,
    PARAMETER_TEAM_D,
    PARAMETER_TEAM_DEFAULT,
    PARAM_MODE_BY_MODEL,
    PARAM_MODE_BY_NAME,
    PARAM_MODE_BY_SN,
    PARAM_MODE_IN_DEVICE,
    STROBE_ALWAYS_HIGH,
    STROBE_ALWAYS_LOW,
    STROBE_SYNC_WITH_TRIG_AUTO,
    STROBE_SYNC_WITH_TRIG_MANUAL,
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
    "ResolutionPreset",
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
    "CT_MODE_AUTO",
    "CT_MODE_PRESET",
    "CT_MODE_USER_DEF",
    "EXT_TRIG_EXP_GRR",
    "EXT_TRIG_EXP_STANDARD",
    "EXT_TRIG_HIGH_LEVEL",
    "EXT_TRIG_LEADING_EDGE",
    "EXT_TRIG_LOW_LEVEL",
    "EXT_TRIG_MASK_BUFFERED_DELAY",
    "EXT_TRIG_MASK_DOUBLE_EDGE",
    "EXT_TRIG_MASK_GRR_SHUTTER",
    "EXT_TRIG_MASK_LEVEL_MODE",
    "EXT_TRIG_TRAILING_EDGE",
    "ISP_PROCESSOR_DEVICE",
    "ISP_PROCESSOR_PC",
    "LUTMODE_PARAM_GEN",
    "LUTMODE_PRESET",
    "LUTMODE_USER_DEF",
    "PARAMETER_TEAM_A",
    "PARAMETER_TEAM_B",
    "PARAMETER_TEAM_C",
    "PARAMETER_TEAM_D",
    "PARAMETER_TEAM_DEFAULT",
    "PARAM_MODE_BY_MODEL",
    "PARAM_MODE_BY_NAME",
    "PARAM_MODE_BY_SN",
    "PARAM_MODE_IN_DEVICE",
    "STROBE_ALWAYS_HIGH",
    "STROBE_ALWAYS_LOW",
    "STROBE_SYNC_WITH_TRIG_AUTO",
    "STROBE_SYNC_WITH_TRIG_MANUAL",
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
