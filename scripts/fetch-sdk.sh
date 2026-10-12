#!/usr/bin/env sh
# Download, verify (SHA-256), and extract the vendor SDK into ./vendor/<version>/
# for work inside this repository. The loader searches ./vendor/<version>/lib/<arch>
# when GCAM_MVSDK_DIR is unset. Extra arguments are passed to `setup`
# (for example --from <archive> or --version <V>).
set -eu
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}" exec "$PYTHON" -m gcam_mvsdk_py setup --dest vendor/ "$@"
