#!/usr/bin/env bash
# Measure sizeof() and offsetof() of an MVSDK structure with gcc, for 64-bit and (if the
# compiler supports -m32) 32-bit targets. Compiles to assembly only; nothing is linked or run.
# Usage: measure_struct.sh STRUCT [FIELD...] [-- INCLUDE_DIR]
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "usage: $0 STRUCT [FIELD...] [-- INCLUDE_DIR]" >&2
    exit 2
fi
struct="$1"
shift
fields=()
inc=""
while [ $# -gt 0 ]; do
    if [ "$1" = "--" ]; then
        inc="${2:-}"
        break
    fi
    fields+=("$1")
    shift
done
if [ -z "$inc" ]; then
    for d in ${GCAM_MVSDK_DIR:+"$GCAM_MVSDK_DIR/include"} ./vendor/*/include "${GCAM_MVSDK_HOME:-$HOME/.gcam-mvsdk}"/*/include; do
        if [ -f "$d/CameraDefine.h" ]; then
            inc="$d"
            break
        fi
    done
fi
if [ -z "$inc" ] || [ ! -f "$inc/CameraDefine.h" ]; then
    echo "CameraDefine.h not found; pass -- INCLUDE_DIR or install the SDK" >&2
    exit 1
fi
command -v gcc >/dev/null 2>&1 || {
    echo "gcc is required" >&2
    exit 1
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
{
    echo '#include <stddef.h>'
    echo '#include "CameraApi.h"'
    echo "int size__ = sizeof($struct);"
    for f in ${fields[@]+"${fields[@]}"}; do
        echo "int off__$f = offsetof($struct, $f);"
    done
} >"$work/probe.c"

for bits in 64 32; do
    if gcc -m"$bits" -I"$inc" -S -o "$work/probe$bits.s" "$work/probe.c" 2>/dev/null; then
        echo "== ${bits}-bit"
        awk '/^(size__|off__)[A-Za-z0-9_]*:/ { name = $1; sub(":", "", name) }
             /\.long/ && name != "" { sub("size__", "sizeof", name); sub("off__", "offsetof ", name); print "  " name " = " $2; name = "" }' \
            "$work/probe$bits.s"
    else
        echo "== ${bits}-bit: compiler cannot target -m$bits (skipped)"
    fi
done
