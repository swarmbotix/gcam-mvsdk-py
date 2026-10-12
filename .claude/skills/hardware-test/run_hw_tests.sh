#!/usr/bin/env bash
# Preflight checks, then the gcam-mvsdk-py hardware tests. Extra arguments go to pytest.
# Usage: .claude/skills/hardware-test/run_hw_tests.sh [pytest args...]
set -euo pipefail

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
python="${PYTHON:-python3}"

if ! "$python" -c "import gcam_mvsdk_py, pytest" >/dev/null 2>&1; then
    echo "gcam_mvsdk_py and pytest must be importable by $python (pip install -e \".[dev]\", or set PYTHON=...)" >&2
    exit 2
fi

echo "==> gcam-mvsdk-py doctor"
"$python" -m gcam_mvsdk_py doctor || echo "(doctor reported failures; continuing to the camera count)"

echo "==> Counting cameras"
count="$("$python" -m gcam_mvsdk_py list --json --no-open | "$python" -c 'import json, sys; print(len(json.load(sys.stdin)))')"
echo "    $count camera(s) visible"
if [ "$count" -eq 0 ]; then
    echo "No cameras visible; fix discovery first (.claude/skills/camera-discovery/SKILL.md)." >&2
    exit 1
fi
if [ -n "${GCAM_MVSDK_HW_RENAME_SN:-}" ]; then
    echo "    NOTE: the rename round trip will rewrite the name of camera $GCAM_MVSDK_HW_RENAME_SN and restore it"
fi

echo "==> pytest tests/hw"
cd -- "$repo"
GCAM_MVSDK_HW_TEST=1 exec "$python" -m pytest -p no:cacheprovider -v tests/hw "$@"
