"""examples/capabilities.py runs against the fake SDK, and docs/CAPABILITIES.md matches it.

Each example function is executed once with a fresh GenericFakeLib; this proves the
snippets are valid code that calls the SDK the way the document says. It does not
prove that a particular camera model supports every feature.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

from gcam_mvsdk_py import api
from gcam_mvsdk_py._loader import LibraryLocation

from fake_mvsdk import GenericFakeLib

REPO = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capabilities = _load("capabilities_examples", REPO / "examples" / "capabilities.py")
doc_tool = _load("update_capabilities_doc", REPO / "scripts" / "update_capabilities_doc.py")

EXAMPLES = sorted(
    (fn for _, fn in inspect.getmembers(capabilities, inspect.isfunction) if fn.__module__ == capabilities.__name__),
    key=lambda fn: fn.__code__.co_firstlineno,
)


def _run(fn, tmp_path, fake=None):
    fake = fake or GenericFakeLib()
    sdk = api.Sdk(fake, LibraryLocation("/fake/libMVSDK.so", "test"))
    first = next(iter(inspect.signature(fn).parameters))
    kwargs = {}
    if "config_path" in inspect.signature(fn).parameters:
        kwargs["config_path"] = str(tmp_path / "camera.config")
    if "data_dir" in inspect.signature(fn).parameters:
        kwargs["data_dir"] = str(tmp_path / "data")
    if first == "sdk":
        return fake, fn(sdk, **kwargs)
    with sdk.open("SN001") as cam:
        return fake, fn(cam, **kwargs)


def test_examples_are_discovered():
    assert len(EXAMPLES) >= 25
    assert {fn.__name__ for fn in EXAMPLES} >= {"exposure_auto", "trigger_hardware", "io_strobe", "callbacks"}


@pytest.mark.parametrize("variant", ["mono-basic", "colour-all-features"])
@pytest.mark.parametrize("fn", EXAMPLES, ids=[fn.__name__ for fn in EXAMPLES])
def test_example_runs_against_fake_sdk(fn, variant, tmp_path):
    fake = GenericFakeLib(mono=variant == "mono-basic", all_features=variant != "mono-basic")
    _, result = _run(fn, tmp_path, fake)
    assert isinstance(result, dict)


def test_feature_dependent_branches_run_on_a_full_featured_colour_camera(tmp_path):
    fake = GenericFakeLib(mono=False, all_features=True)
    _run(capabilities.isp_white_balance, tmp_path, fake)
    assert fake.calls_to("CameraSetUserClrTempMatrix") and fake.calls_to("CameraSetOnceWB")
    _run(capabilities.isp_output_and_processor, tmp_path, fake)
    assert fake.calls_to("CameraSetIspProcessor")[-1][1] == 1 and fake.calls_to("CameraSetMonochrome")
    _run(capabilities.exposure_flicker, tmp_path, fake)
    assert fake.calls_to("CameraSetLightFrequency")[-1][1] == 0
    _run(capabilities.trigger_hardware, tmp_path, fake)
    assert fake.calls_to("CameraSetExtTrigBufferedDelayTime") and fake.calls_to("CameraSetExtTrigShutterType")
    _run(capabilities.persistence_groups, tmp_path, fake)
    assert fake.calls_to("CameraSetParameterMode")[-1][1] == 3
    _run(capabilities.isp_noise, tmp_path, fake)
    assert fake.calls_to("CameraSetBayerDecAlgorithm")


def test_examples_call_the_documented_vendor_functions(tmp_path):
    fake, _ = _run(capabilities.trigger_hardware, tmp_path)
    assert fake.calls_to("CameraSetExtTrigSignalType")
    assert fake.calls_to("CameraSetExtTrigJitterTime")[-1][1] == 20
    fake, _ = _run(capabilities.exposure_auto, tmp_path)
    assert fake.calls_to("CameraSetAeTarget")[-1][1] == 120
    fake, _ = _run(capabilities.io_strobe, tmp_path)
    assert fake.calls_to("CameraSetStrobePulseWidth")[-1][1] == 2000


def test_unsupported_raw_feature_is_reported_not_raised(tmp_path):
    fake = GenericFakeLib()
    fake.fail["CameraGetMultiExposureMaxCount"] = -4
    _, result = _run(capabilities.exposure_multi_raw, tmp_path, fake)
    assert result == {"error": -4}


def test_document_is_in_sync_with_examples():
    doc = (REPO / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8")
    new, problems = doc_tool.updated_document(doc, doc_tool.example_sources())
    assert problems == []
    assert new == doc, "docs/CAPABILITIES.md is stale; run: python scripts/update_capabilities_doc.py"


def test_document_outline_matches_the_shared_order():
    doc = (REPO / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8")
    titles = [title for title, _, _ in doc_tool.section_counts(doc)]
    assert titles == [
        "1. Identity and network",
        "2. Exposure and gain",
        "3. Frame rate, trigger and timing",
        "4. Image geometry",
        "5. Image processing",
        "6. Digital I/O, strobe and lighting",
        "7. GigE transport",
        "8. Parameter persistence",
        "9. Callbacks",
        "10. Vendor GUI and recording",
    ]


def test_raw_frame_event_callback_from_the_example_fires(tmp_path):
    import ctypes

    from gcam_mvsdk_py import _ffi

    fake = GenericFakeLib()
    sdk = api.Sdk(fake, LibraryLocation("/fake/libMVSDK.so", "test"))
    with sdk.open("SN001") as cam:
        capabilities.callbacks(cam)
        wrapper = fake.calls_to("CameraSetFrameEventCallback")[-1][1]
        assert wrapper is cam.frame_event_callback  # kept alive on the camera object
        event = _ffi.tSdkFrameEvent(uType=2)
        wrapper(cam.handle, ctypes.pointer(event), None)  # the SDK would do this at frame end
