#!/usr/bin/env bash
# Print the English description and the declaration of an MVSDK function.
# Usage: show_prototype.sh FUNCTION [INCLUDE_DIR]
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "usage: $0 FUNCTION [INCLUDE_DIR]" >&2
    exit 2
fi
func="$1"
dir="${2:-}"

if [ -z "$dir" ]; then
    candidates=()
    [ -n "${GCAM_MVSDK_DIR:-}" ] && candidates+=("$GCAM_MVSDK_DIR/include")
    for d in ./vendor/*/include "${GCAM_MVSDK_HOME:-$HOME/.gcam-mvsdk}"/*/include; do
        [ -d "$d" ] && candidates+=("$d")
    done
    for d in ${candidates[@]+"${candidates[@]}"}; do
        if [ -f "$d/CameraApi.h" ]; then
            dir="$d"
            break
        fi
    done
fi
header="$dir/CameraApi.h"
if [ -z "$dir" ] || [ ! -f "$header" ]; then
    echo "CameraApi.h not found; pass the include directory or install the SDK (./scripts/fetch-sdk.sh)" >&2
    exit 1
fi

tr -d '\r' <"$header" | awk -v fn="$func" '
    /^[[:space:]]*\/\*+\/?[[:space:]]*$/ { next }
    /^[[:space:]]*\/\// { doc[n++] = $0; next }
    $0 ~ "MVSDK_API[^(]*[^A-Za-z0-9_]" fn "[[:space:]]*\\(" {
        start = 0
        for (i = 0; i < n; i++) if (doc[i] ~ /\\~english/) start = i
        for (i = start; i < n; i++) if (doc[i] !~ /^[[:space:]]*\/\*+[[:space:]]*$/ && doc[i] !~ /^\/\/\/?[*]+/) print doc[i]
        printing = 1
    }
    printing { print; if ($0 ~ /\);/) { printing = 0; found = 1; exit } }
    !/^[[:space:]]*\/\// && !printing { n = 0 }
    END { if (!found) exit 1 }
' || {
    echo "$func not declared in $header" >&2
    exit 1
}
