"""In-process fakes of the vendor library for unit tests.

``FakeLib`` implements selected C functions in Python with the same calling
pattern (ctypes buffers, ``byref`` out-parameters). ``GenericFakeLib`` adds a
fallback for every other ``Camera*`` function: ``Set`` calls are remembered and
a later ``Get`` with the same leading input arguments returns those values
through its pointer arguments, so property round trips work without one fake
per function. Nothing here talks to a camera or loads the SDK.
"""

from __future__ import annotations

import ctypes
import sys

from gcam_mvsdk_py import _ffi
from gcam_mvsdk_py._errors import decode_c_string

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
        presets = [(0, W, H, b"full", 0, 0), (1, W // 2, H // 2, b"bin 2x2", 1, 0)]
        self.presets = (_ffi.tSdkImageResolution * len(presets))()
        for i, (idx, w, hgt, desc, bin_sum, skip) in enumerate(presets):
            p = self.presets[i]
            p.iIndex, p.iWidth, p.iHeight, p.acDescription = idx, w, hgt, desc
            p.uBinSumMode, p.uSkipMode = bin_sum, skip
            p.iWidthFOV, p.iHeightFOV = W, H
        self.frame_speed_desc = (_ffi.tSdkFrameSpeed * 3)()
        self.trigger_desc = (_ffi.tSdkTrigger * 3)()
        for i, (speed, trig) in enumerate(zip((b"Low", b"Normal", b"High"), (b"Continuous", b"Software", b"Hardware"))):
            self.frame_speed_desc[i].iIndex, self.frame_speed_desc[i].acDescription = i, speed
            self.trigger_desc[i].iIndex, self.trigger_desc[i].acDescription = i, trig
        self.media_desc = (_ffi.tSdkMediaType * 2)()
        for i, (mt, desc) in enumerate(((_ffi.CAMERA_MEDIA_TYPE_MONO8, b"Mono8"), (_ffi.CAMERA_MEDIA_TYPE_MONO12, b"Mono12"))):
            self.media_desc[i].iIndex, self.media_desc[i].iMediaType, self.media_desc[i].acDescription = i, mt, desc
        self.clr_temps = (_ffi.tSdkColorTemperatureDes * 2)()
        for i, desc in enumerate((b"5000K", b"6500K")):
            self.clr_temps[i].iIndex, self.clr_temps[i].acDescription = i, desc
        self.user_data = bytearray(64)
        self.resolution_set = None
        self.mono = True          # False: report a colour sensor
        self.all_features = False  # True: report every optional capability flag
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
        cap.sIspCapacity.bMonoSensor = int(self.mono)
        if self.all_features:
            isp = cap.sIspCapacity
            isp.bAntiFlick = isp.bDeviceIsp = isp.bAutoWb = isp.bWbOnce = 1
            isp.bAutoExposure = isp.bManualExposure = 1
            cap.bParamInDevice = 1
        cap.sResolutionRange.iWidthMax = W
        cap.sResolutionRange.iHeightMax = H
        cap.sResolutionRange.uBinSumModeMask = 0b1  # 2x2
        cap.sResolutionRange.uBinAverageModeMask = 0b11  # 2x2, 3x3
        cap.sResolutionRange.uSkipModeMask = 0
        cap.pPackLenDesc = ctypes.cast(self.pack_desc, ctypes.POINTER(_ffi.tSdkPackLength))
        cap.iPackLenDesc = len(self.pack_desc)
        cap.pImageSizeDesc = ctypes.cast(self.presets, ctypes.POINTER(_ffi.tSdkImageResolution))
        cap.iImageSizeDesc = len(self.presets)
        cap.pClrTempDesc = ctypes.cast(self.clr_temps, ctypes.POINTER(_ffi.tSdkColorTemperatureDes))
        cap.pFrameSpeedDesc = ctypes.cast(self.frame_speed_desc, ctypes.POINTER(_ffi.tSdkFrameSpeed))
        cap.iFrameSpeedDesc = len(self.frame_speed_desc)
        cap.pTriggerDesc = ctypes.cast(self.trigger_desc, ctypes.POINTER(_ffi.tSdkTrigger))
        cap.iTriggerDesc = len(self.trigger_desc)
        cap.pMediaTypeDesc = ctypes.cast(self.media_desc, ctypes.POINTER(_ffi.tSdkMediaType))
        cap.iMediaTypdeDesc = len(self.media_desc)
        cap.iClrTempDesc = len(self.clr_temps)
        cap.iInputIoCounts, cap.iOutputIoCounts = 1, 2
        cap.iUserDataMaxLen = len(self.user_data)
        cap.sExposeDesc.uiTargetMin, cap.sExposeDesc.uiTargetMax = 20, 255
        cap.sGammaRange.iMin, cap.sGammaRange.iMax = 0, 250
        cap.sContrastRange.iMin, cap.sContrastRange.iMax = 0, 200
        cap.sSaturationRange.iMin, cap.sSaturationRange.iMax = 0, 200
        cap.sSharpnessRange.iMin, cap.sSharpnessRange.iMax = 0, 100
        cap.sRgbGainRange.iRGainMin, cap.sRgbGainRange.iRGainMax = 0, 400
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


def _is_ref(arg):
    return hasattr(arg, "_obj")  # objects made by ctypes.byref()


class GenericFakeLib(FakeLib):
    """FakeLib with a remembering fallback for every other ``Camera*`` function."""

    # Getter names whose setter is spelled differently.
    ALIASES = {"NoiseFilterState": "NoiseFilter", "OutPutIOStateEx": "IOStateEx"}

    def __init__(self, mono=True, all_features=False):
        self.state = {}
        self.generic_calls = []
        self.fail = {}
        self.inputs = {}
        self.parameter_group_value = 0
        self.saved_groups = []
        super().__init__()
        self.mono = mono
        self.all_features = all_features
        if all_features:
            self.state["ExtTrigCapability"] = [(0b1111,)]  # every EXT_TRIG_MASK_* bit

    def __getattr__(self, name):
        if not name.startswith("Camera"):
            raise AttributeError(name)
        fn = _plain(lambda *args: self._generic(name, *args))
        setattr(self, name, fn)  # cache it so argtypes assigned by the code under test stick
        return fn

    def calls_to(self, name):
        return [args for called, args in self.generic_calls if called == name]

    def _generic(self, name, *args):
        self.generic_calls.append((name, args))
        if name in self.fail:
            return self.fail[name]
        camera_call = bool(args) and isinstance(args[0], int) and args[0] in self.open_handles
        rest = list(args[1:] if camera_call else args)
        if name.startswith("CameraSet"):
            self.state.setdefault(name[len("CameraSet"):], []).append(tuple(rest))
        elif name.startswith("CameraGet"):
            key = name[len("CameraGet"):]
            key = self.ALIASES.get(key, key)
            inputs = [a for a in rest if not _is_ref(a)]
            refs = [a for a in rest if _is_ref(a)]
            for stored in reversed(self.state.get(key, [])):
                if list(stored[: len(inputs)]) == inputs:
                    for ref, value in zip(refs, stored[len(inputs):]):
                        ref._obj.value = value
                    break
        return 0

    # Functions whose behaviour the generic rule cannot express.
    def _CameraGetIOStateEx(self, h, index, ref):
        ref._obj.value = self.inputs.get(index, 0)
        return 0

    def _CameraLoadParameter(self, h, group):
        self.parameter_group_value = group
        return 0

    def _CameraSaveParameter(self, h, group):
        self.parameter_group_value = group
        self.saved_groups.append(group)
        return 0

    def _CameraGetCurrentParameterGroup(self, h, ref):
        ref._obj.value = self.parameter_group_value
        return 0

    def _CameraReadSN(self, h, buf, level):
        buf.value = b"LEVEL%dSN" % level
        return 0

    def _CameraLoadUserData(self, h, offset, buf, length):
        ctypes.memmove(buf, bytes(self.user_data[offset : offset + length]), length)
        return 0

    def _CameraSaveUserData(self, h, offset, buf, length):
        self.user_data[offset : offset + length] = buf.raw[:length]
        return 0

    def _CameraSetImageResolution(self, h, res_ref):
        self.resolution_set = (res_ref._obj.iIndex, res_ref._obj.iWidth, res_ref._obj.iHeight)
        return 0
