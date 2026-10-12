#!/usr/bin/env sh
# Fail if any vendor binary, archive, or header is tracked by git.
set -eu
cd "$(dirname "$0")/.."
bad=$(git ls-files | grep -E '\.(so|so\.[0-9.]+|dll|dylib|lib|exe|chm|tar\.gz|tgz|rar|zip|7z)$|(^|/)(CameraApi|CameraDefine|CameraStatus)\.h$|(^|/)mvsdk\.py$|^vendor/' || true)
if [ -n "$bad" ]; then
    echo "Vendor files must not be committed:" >&2
    echo "$bad" >&2
    exit 1
fi
echo "No vendor files tracked."
