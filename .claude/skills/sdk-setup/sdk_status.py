"""Show where gcam-mvsdk-py looks for the vendor library and what it finds.

Usage: python .claude/skills/sdk-setup/sdk_status.py [--load]
Run it with the interpreter that has gcam-mvsdk-py installed.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    try:
        from gcam_mvsdk_py import _loader
    except ImportError:
        print("gcam_mvsdk_py is not importable with %s; use the venv's python." % sys.executable)
        return 2

    print("interpreter     %s" % sys.executable)
    print("arch directory  lib/%s" % _loader.detect_arch())
    print("library names   %s" % ", ".join(_loader.library_names()))
    print("sdk home        %s" % _loader.sdk_home())
    for var in (_loader.ENV_DIR, _loader.ENV_ARCH, _loader.ENV_HOME):
        print("%-15s %s" % (var, os.environ.get(var, "(unset)")))
    print("\nCandidates in search order:")
    for entry in _loader.search_entries():
        for name in _loader.library_names():
            path = entry.directory / name
            mark = "FOUND  " if path.is_file() else "missing"
            print("  %s %s  [%s]" % (mark, path, entry.origin))

    location = _loader.find_library()
    env_root = _loader.env_sdk_dir()
    if location:
        print("\nSelected: %s" % location.path)
    elif env_root is not None:
        print("\nSelected: nothing. %s\n%s" % (_loader.env_dir_problem(env_root), _loader.ENV_DIR_HINT))
    else:
        print("\nSelected: nothing (the dynamic loader is tried last)")
    if location and location.sdk_root:
        manifest = location.sdk_root / "manifest.json"
        if manifest.is_file():
            print("manifest.json: %s" % json.dumps(json.loads(manifest.read_text()), indent=2))
    if "--load" in sys.argv[1:]:
        from gcam_mvsdk_py import GcamMvsdkError, load

        try:
            sdk = load()
        except GcamMvsdkError as exc:
            print("\nLoad failed:\n%s" % exc)
            return 1
        print("\nLoaded %s; SDK version %s" % (sdk.path, sdk.version()))
        if sdk.missing_functions:
            print("Not exported by this build: %s" % ", ".join(sdk.missing_functions))
    return 0 if location else 1


if __name__ == "__main__":
    sys.exit(main())
