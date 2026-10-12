"""examples/capabilities.py runs against the fake SDK, and docs/CAPABILITIES.md matches it.

Each example function is executed once with a fresh GenericFakeLib; this proves the
snippets are valid code that calls the SDK the way the document says. It does not
prove that a particular camera model supports every feature. The command-line runner
(``main``) is tested for its read-only default and for never writing sections 1 and 8.
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

EXAMPLES = [fn for fns in capabilities.SECTIONS.values() for fn in fns]


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


def test_sections_list_every_example_once_in_file_order():
    public = sorted(
        (fn for name, fn in inspect.getmembers(capabilities, inspect.isfunction)
         if fn.__module__ == capabilities.__name__ and name != "main" and not name.startswith("_")),
        key=lambda fn: fn.__code__.co_firstlineno,
    )
    assert EXAMPLES == public


def test_sections_match_where_the_document_shows_each_snippet():
    doc = (REPO / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8")
    shown_in = {}
    for section in doc_tool.SECTION_RE.finditer(doc):
        title = "%s. %s" % (section.group("num"), section.group("title"))
        rest = doc[section.end():]
        following = doc_tool.SECTION_RE.search(rest)
        body = rest[: following.start()] if following else rest
        for m in doc_tool.SNIPPET_RE.finditer(body):
            shown_in[m.group("name")] = title
    expected = {fn.__name__: title for title, fns in capabilities.SECTIONS.items() for fn in fns}
    assert shown_in == expected


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


# ---------------------------------------------------------------------------
# Command-line runner: python examples/capabilities.py <camera> [function] [--write]
# ---------------------------------------------------------------------------


@pytest.fixture
def runner_fake(monkeypatch):
    fake = GenericFakeLib()
    sdk = api.Sdk(fake, LibraryLocation("/fake/libMVSDK.so", "test"))
    monkeypatch.setattr(capabilities.gcam_mvsdk_py, "load", lambda *args, **kwargs: sdk)
    return fake


def _untouched(fake):
    """True when no setting, name, address, user data or parameter group was written."""
    return (
        fake.state == {}
        and fake.devices[0]["name"] == "sb00"
        and not [c for c in fake.calls if c[0] == "setip"]
        and fake.user_data == bytearray(64)
        and fake.saved_groups == []
        and fake.resolution_set is None
        and (fake.exposure, fake.ae, fake.pack_index, fake.isp_format) == (1000.0, 1, 0, api.Mono8)
        and fake.callback is None
    )


def test_runner_lists_sections_without_a_camera(capsys):
    assert capabilities.main(["--list"]) == 0
    out = capsys.readouterr().out
    for title, fns in capabilities.SECTIONS.items():
        assert title in out
        assert all(fn.__name__ in out for fn in fns)
    assert "8. Parameter persistence  (always a dry run)" in out


def test_runner_default_is_read_only_and_lists_the_skipped_writes(runner_fake, capsys):
    assert capabilities.main(["SN001"]) == 0
    out = capsys.readouterr().out
    assert _untouched(runner_fake)
    assert "Read-only" in out and "%d function(s), 0 raised an error." % len(EXAMPLES) in out
    assert "ae_target = 120" in out and "user_name = 'sb01'" in out and "save_parameter('B')" in out
    assert "gige_set_ip(" in out


def test_runner_write_applies_working_settings(runner_fake, capsys):
    assert capabilities.main(["SN001", "exposure_auto", "--write"]) == 0
    assert runner_fake.calls_to("CameraSetAeTarget")[-1][1] == 120
    assert runner_fake.saved_groups == []
    assert "[2. Exposure and gain; write]" in capsys.readouterr().out


@pytest.mark.parametrize("section", ["1", "8"])
def test_runner_never_writes_identity_or_persistence(runner_fake, capsys, section):
    assert capabilities.main(["SN001", section, "--write"]) == 0
    assert _untouched(runner_fake)
    assert "dry run" in capsys.readouterr().out


def test_runner_selects_a_section_by_number(runner_fake, capsys):
    assert capabilities.main(["SN001", "3"]) == 0
    out = capsys.readouterr().out
    assert [line.split()[1] for line in out.splitlines() if line.startswith("== ")] == [
        fn.__name__ for fn in capabilities.SECTIONS["3. Frame rate, trigger and timing"]
    ]


def test_runner_reports_an_unsupported_function_and_continues(runner_fake, capsys):
    runner_fake.fail["CameraGetGain"] = -4
    assert capabilities.main(["SN001", "2"]) == 1
    out = capsys.readouterr().out
    assert "status -4" in out and "not supported by this model" in out
    assert "5 function(s), 1 raised an error." in out


def test_runner_rejects_an_unknown_function_and_a_missing_camera(capsys):
    with pytest.raises(SystemExit) as exc:
        capabilities.main(["SN001", "no_such_function"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        capabilities.main([])
    assert exc.value.code == 2


def test_runner_reports_a_camera_that_is_not_found(runner_fake, capsys):
    assert capabilities.main(["nope", "gain_rgb"]) == 1
    assert "no camera with serial or name 'nope'" in capsys.readouterr().err
