#!/usr/bin/env bash
# install.bash: one-command installer for gcam-mvsdk-py on Linux.
#
# Creates a dedicated virtual environment, installs gcam-mvsdk-py into it,
# links the `gcam-mvsdk-py` command into ~/.local/bin, downloads and verifies
# the HuaTeng MVSDK, optionally grants raw-socket access and installs the USB
# udev rules, and finishes with `gcam-mvsdk-py doctor` and `gcam-mvsdk-py list`.
# Safe to run again: every step detects work that is already done.
#
# Usage: bash install.bash [options]      (bash install.bash --help)

if [ -z "${BASH_VERSINFO:-}" ] || [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    echo "install.bash: bash 4 or newer is required; run it as: bash install.bash" >&2
    exit 1
fi

set -euo pipefail
set -o errtrace
trap 'printf "install.bash: error: command failed at line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

readonly PKG="gcam-mvsdk-py"
readonly MODULE="gcam_mvsdk_py"
readonly MIN_PY="3.9"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR

GCAM_MVSDK_HOME="${GCAM_MVSDK_HOME:-$HOME/.gcam-mvsdk}"
case "$GCAM_MVSDK_HOME" in
    /*) ;;
    *) GCAM_MVSDK_HOME="$PWD/$GCAM_MVSDK_HOME" ;;
esac
export GCAM_MVSDK_HOME
readonly VENV_DIR="$GCAM_MVSDK_HOME/py-venv"
readonly VENV_PY="$VENV_DIR/bin/python3"
readonly VENV_CLI="$VENV_DIR/bin/$PKG"
readonly BIN_DIR="${GCAM_MVSDK_BIN_DIR:-$HOME/.local/bin}"
readonly LINK="$BIN_DIR/$PKG"
readonly HOME_MARKER="$VENV_DIR/gcam-mvsdk-py-home"
PYTHON="${PYTHON:-python3}"

FROM=""
NO_SUDO=0
WITH_OPENCV=0
WITH_VIEW=0
USE_WHEEL=0
DEV=0
UNINSTALL=0
ASSUME_YES=0

OS_ID="unknown"
OS_LIKE=""
OS_NAME="Linux"
IS_DEBIAN=0
SDK_ARCH=""
PKG_VERSION=""
SDK_ROOT=""
SDK_VERSION=""
RUN_DIR=""
CAP_STATE="not requested"
UDEV_STATE="not requested"
PATH_HINT=0
SUDO=()

usage() {
    cat <<EOF
Install gcam-mvsdk-py and the HuaTeng MVSDK for the current user.

Usage: bash install.bash [options]

Options:
  --from FILE     install the SDK from a downloaded archive instead of the
                  vendor URL (air-gapped machines)
  --no-sudo       never run sudo; print the privileged commands instead
  --with-opencv   also install headless OpenCV (the [opencv] extra, PNG writing)
  --with-view     also install OpenCV with GUI support (the [view] extra) for
                  examples/live_view.py; cannot be combined with --with-opencv
  --wheel         install the newest wheel from dist/ instead of the source tree
  --dev           editable install with test tools; SDK goes to ./vendor/
  --uninstall     remove the virtual environment and the command link, and
                  offer to delete the downloaded SDK
  -y, --yes       answer yes to installation prompts (never deletes the SDK)
  -h, --help      show this help

Environment:
  GCAM_MVSDK_HOME      where the venv and SDK live (default: ~/.gcam-mvsdk)
  GCAM_MVSDK_BIN_DIR   where the command link goes (default: ~/.local/bin)
  PYTHON               interpreter used to create the venv (default: python3)
EOF
}

say() { printf '==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '    WARNING: %s\n' "$*" >&2; }
die() {
    printf 'install.bash: error: %s\n' "$*" >&2
    exit 1
}

# confirm QUESTION DEFAULT(Y|N): honours --yes; without a terminal answers no.
confirm() {
    local question="$1" default="${2:-N}" answer=""
    if [ "$ASSUME_YES" -eq 1 ]; then
        return 0
    fi
    if [ ! -t 0 ]; then
        info "(no terminal: answering no to \"$question\"; rerun with --yes to accept)"
        return 1
    fi
    if [ "$default" = "Y" ]; then
        read -r -p "    $question [Y/n] " answer || answer=""
        answer="${answer:-y}"
    else
        read -r -p "    $question [y/N] " answer || answer=""
        answer="${answer:-n}"
    fi
    case "$answer" in
        y | Y | yes | YES | Yes) return 0 ;;
        *) return 1 ;;
    esac
}

# confirm_destructive QUESTION: interactive only, default no, ignores --yes.
confirm_destructive() {
    local answer=""
    if [ ! -t 0 ]; then
        return 1
    fi
    read -r -p "    $1 [y/N] " answer || answer=""
    case "$answer" in
        y | Y | yes | YES | Yes) return 0 ;;
        *) return 1 ;;
    esac
}

# quote_cmd ARGS...: print a command with shell quoting, for display and bash -c.
quote_cmd() {
    local out="" arg
    for arg in "$@"; do
        if [[ "$arg" =~ ^[A-Za-z0-9_./:,+=@%-]+$ ]]; then
            out+="$arg "
        else
            out+="$(printf '%q' "$arg") "
        fi
    done
    printf '%s' "${out% }"
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --from)
                [ $# -ge 2 ] || die "--from needs a file argument"
                FROM="$2"
                shift 2
                ;;
            --from=*)
                FROM="${1#*=}"
                shift
                ;;
            --no-sudo) NO_SUDO=1; shift ;;
            --with-opencv) WITH_OPENCV=1; shift ;;
            --with-view) WITH_VIEW=1; shift ;;
            --wheel) USE_WHEEL=1; shift ;;
            --dev) DEV=1; shift ;;
            --uninstall) UNINSTALL=1; shift ;;
            -y | --yes) ASSUME_YES=1; shift ;;
            -h | --help) usage; exit 0 ;;
            *) die "unknown option: $1 (see bash install.bash --help)" ;;
        esac
    done
    if [ "$DEV" -eq 1 ] && [ "$USE_WHEEL" -eq 1 ]; then
        die "--dev and --wheel cannot be combined"
    fi
    if [ "$WITH_OPENCV" -eq 1 ] && [ "$WITH_VIEW" -eq 1 ]; then
        die "--with-opencv and --with-view cannot be combined (both install the cv2 module); --with-view also writes PNG files"
    fi
    if [ -n "$FROM" ]; then
        [ -f "$FROM" ] || die "--from: no such file: $FROM"
        FROM="$(cd -- "$(dirname -- "$FROM")" && pwd -P)/$(basename -- "$FROM")"
    fi
    if [ "$(id -u)" -ne 0 ]; then
        SUDO=(sudo)
    fi
}

check_platform() {
    say "Checking the operating system"
    local kernel
    kernel="$(uname -s)"
    case "$kernel" in
        Linux) ;;
        Darwin) die "macOS is not supported by install.bash (the vendor's macOS SDK is not packaged yet); see README.md" ;;
        MINGW* | MSYS* | CYGWIN*) die "Windows is not supported by install.bash; follow the Windows section of README.md" ;;
        *) die "unsupported operating system '$kernel'; see README.md" ;;
    esac
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        OS_ID="$(. /etc/os-release && printf '%s' "${ID:-unknown}")"
        # shellcheck disable=SC1091
        OS_LIKE="$(. /etc/os-release && printf '%s' "${ID_LIKE:-}")"
        # shellcheck disable=SC1091
        OS_NAME="$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-Linux}")"
    fi
    case " $OS_ID $OS_LIKE " in
        *" debian "* | *" ubuntu "*) IS_DEBIAN=1 ;;
    esac
    if [ "$IS_DEBIAN" -eq 1 ]; then
        info "$OS_NAME (Debian family: fully supported)"
    else
        info "$OS_NAME (not Debian or Ubuntu: best effort; system packages must be installed by hand)"
    fi
}

detect_arch() {
    say "Detecting the CPU architecture"
    local machine
    machine="$(uname -m)"
    case "$machine" in
        x86_64 | amd64) SDK_ARCH="x64" ;;
        aarch64 | arm64) SDK_ARCH="arm64" ;;
        armv7l | armv7* | armv8l) SDK_ARCH="arm" ;;
        i686 | i586 | i486 | i386) SDK_ARCH="x86" ;;
        *) die "unsupported CPU architecture '$machine'; the vendor SDK supports x86_64, aarch64, armv7l, and i686" ;;
    esac
    if [ -n "${GCAM_MVSDK_ARCH:-}" ]; then
        info "GCAM_MVSDK_ARCH overrides the mapping: lib/$GCAM_MVSDK_ARCH"
        SDK_ARCH="$GCAM_MVSDK_ARCH"
    fi
    info "$machine -> SDK library directory lib/$SDK_ARCH"
}

python_version_ok() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
}

python_venv_ok() {
    "$1" -c 'import venv, ensurepip' >/dev/null 2>&1
}

ensure_python() {
    say "Checking for Python >= $MIN_PY with the venv module ($PYTHON)"
    if ! command -v "$PYTHON" >/dev/null 2>&1; then
        if [ "$IS_DEBIAN" -eq 1 ]; then
            die "$PYTHON not found; install it with: sudo apt-get install -y python3 python3-venv python3-pip"
        fi
        die "$PYTHON not found; install Python $MIN_PY or newer with your package manager, or set PYTHON=/path/to/python3"
    fi
    if ! python_version_ok "$PYTHON"; then
        die "$("$PYTHON" -V 2>&1) is too old; Python $MIN_PY or newer is required (set PYTHON=/path/to/python3.x)"
    fi
    local version
    version="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if ! python_venv_ok "$PYTHON"; then
        local cmd=(apt-get install -y python3-venv python3-pip)
        if [ "$IS_DEBIAN" -ne 1 ]; then
            die "the venv/ensurepip module of Python $version is missing; install your distribution's python3 venv package"
        fi
        info "The venv module is missing. Fix:"
        info "  sudo apt-get update && sudo $(quote_cmd "${cmd[@]}")"
        if [ "$NO_SUDO" -eq 1 ]; then
            die "--no-sudo given; run the command above, then rerun install.bash"
        fi
        if ! confirm "Run it now with sudo?" Y; then
            die "Python venv support is required; run the command above, then rerun install.bash"
        fi
        ${SUDO[@]+"${SUDO[@]}"} bash -c "apt-get update && $(quote_cmd "${cmd[@]}")"
        if ! python_venv_ok "$PYTHON"; then
            die "venv is still unavailable; also install python${version}-venv (sudo apt-get install -y python${version}-venv)"
        fi
    fi
    info "$("$PYTHON" -V 2>&1) at $(command -v "$PYTHON")"
}

make_venv() {
    say "Preparing the virtual environment $VENV_DIR"
    case "$VENV_DIR" in
        */py-venv) ;;
        *) die "refusing to manage unexpected venv path $VENV_DIR" ;;
    esac
    if [ -e "$VENV_DIR" ] && [ ! -f "$VENV_DIR/pyvenv.cfg" ]; then
        die "$VENV_DIR exists but is not a virtual environment; move it away and rerun"
    fi
    if [ -x "$VENV_PY" ] && [ ! -L "$VENV_PY" ] && python_version_ok "$VENV_PY"; then
        info "reusing the existing environment ($("$VENV_PY" -V 2>&1))"
    else
        if [ -e "$VENV_DIR" ]; then
            info "existing environment is unusable or uses symlinks; recreating it"
            rm -rf -- "$VENV_DIR"
        fi
        mkdir -p -- "$GCAM_MVSDK_HOME"
        "$PYTHON" -m venv --copies "$VENV_DIR"
        info "created with --copies, so bin/python3 is a private file that setcap may modify"
    fi
    printf '%s\n' "$GCAM_MVSDK_HOME" >"$HOME_MARKER"
    say "Upgrading pip inside the virtual environment"
    if ! "$VENV_PY" -m pip install --quiet --disable-pip-version-check --upgrade pip; then
        warn "could not upgrade pip (offline?); continuing with the bundled version"
    fi
}

install_package() {
    local extras="" spec target newest="" wheel
    if [ "$DEV" -eq 1 ]; then
        extras="dev"
    fi
    if [ "$WITH_OPENCV" -eq 1 ]; then
        extras="${extras:+$extras,}opencv"
    fi
    if [ "$WITH_VIEW" -eq 1 ]; then
        extras="${extras:+$extras,}view"
    fi
    if [ "$USE_WHEEL" -eq 1 ]; then
        for wheel in "$SCRIPT_DIR"/dist/"$MODULE"-*-py3-none-any.whl; do
            [ -e "$wheel" ] || continue
            if [ -z "$newest" ] || [ "$wheel" -nt "$newest" ]; then
                newest="$wheel"
            fi
        done
        [ -n "$newest" ] || die "--wheel: no $MODULE-*-py3-none-any.whl in $SCRIPT_DIR/dist (build it with: python3 -m build)"
        target="$newest"
    else
        [ -f "$SCRIPT_DIR/pyproject.toml" ] || die "$SCRIPT_DIR is not a $PKG source tree (pyproject.toml missing)"
        target="$SCRIPT_DIR"
    fi
    spec="$target${extras:+[$extras]}"
    if [ "$DEV" -eq 1 ]; then
        say "Installing $PKG in editable mode from $target${extras:+ (extras: $extras)}"
        "$VENV_PY" -m pip install --quiet --disable-pip-version-check --upgrade -e "$spec"
    else
        say "Installing $PKG from $target${extras:+ (extras: $extras)}"
        "$VENV_PY" -m pip install --quiet --disable-pip-version-check --upgrade "$spec"
    fi
    PKG_VERSION="$("$VENV_PY" -c "import $MODULE; print($MODULE.__version__)")"
    [ -x "$VENV_CLI" ] || die "the console script $VENV_CLI was not created"
    info "$PKG $PKG_VERSION installed"
}

link_cli() {
    say "Linking the command into $BIN_DIR"
    mkdir -p -- "$BIN_DIR"
    if [ -e "$LINK" ] && [ ! -L "$LINK" ]; then
        die "$LINK exists and is not a symlink; move it away and rerun"
    fi
    ln -sfn -- "$VENV_CLI" "$LINK"
    info "$LINK -> $VENV_CLI"
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            PATH_HINT=1
            warn "$BIN_DIR is not on your PATH. Add this line to ~/.bashrc (and run it now):"
            # shellcheck disable=SC2016  # $PATH is printed literally for the user to paste.
            printf '        export PATH="%s:$PATH"\n' "$BIN_DIR"
            ;;
    esac
}

manual_sdk_instructions() {
    local url="" name="" sha=""
    if read -r url name sha < <("$VENV_PY" -c "
from $MODULE.setup_cmd import available_releases
r = available_releases()[0]
print(r.url, r.filename.replace(' ', '%20'), r.sha256 or '-')
" 2>/dev/null); then
        :
    fi
    {
        echo
        echo "The SDK could not be installed automatically. To install it by hand:"
        echo "  1. Download the Linux SDK in a browser or on another machine:"
        echo "       ${url:-http://huatengvision.com/download/1/}"
        [ -n "$sha" ] && [ "$sha" != "-" ] && echo "     Expected SHA-256: $sha"
        echo "  2. Copy it to this machine and run:"
        echo "       bash $(quote_cmd "$SCRIPT_DIR/install.bash") --from '/path/to/${name:-linuxSDK_V<version>.tar.gz}'"
        echo "  Or point the package at an SDK that is already extracted:"
        echo "       export GCAM_MVSDK_DIR=/path/to/linuxSDK_V<version>"
    } >&2
}

locate_sdk() {
    local line
    if ! line="$(cd -- "$RUN_DIR" && "$VENV_PY" -c "
from $MODULE import find_library
loc = find_library()
if loc is not None and loc.sdk_root is not None:
    print(loc.sdk_root.name + '|' + str(loc.sdk_root))
" 2>/dev/null)"; then
        line=""
    fi
    if [ -n "$line" ]; then
        SDK_VERSION="${line%%|*}"
        SDK_ROOT="${line#*|}"
    fi
}

install_sdk() {
    local dest="$GCAM_MVSDK_HOME"
    if [ "$DEV" -eq 1 ]; then
        dest="$SCRIPT_DIR/vendor"
    fi
    local args=(setup --dest "$dest")
    if [ -n "$FROM" ]; then
        args+=(--from "$FROM")
        say "Installing the HuaTeng SDK from $FROM into $dest"
    else
        say "Downloading and verifying the HuaTeng SDK into $dest"
    fi
    if ! "$VENV_CLI" "${args[@]}"; then
        manual_sdk_instructions
        exit 1
    fi
    locate_sdk
    if [ -z "$SDK_ROOT" ]; then
        warn "the SDK was installed but the loader cannot find lib/$SDK_ARCH; set GCAM_MVSDK_ARCH if this board needs another build"
    fi
}

# Path of the interpreter that the console script runs (the file setcap must target).
script_interpreter() {
    local first second
    first="$(head -n 1 "$VENV_CLI")"
    if [ "$first" = "#!/bin/sh" ]; then
        # pip writes a /bin/sh trampoline when the interpreter path is long:
        # line 2 is  '''exec' /path/python3 "$0" "$@"  (path quoted if it has spaces)
        second="$(sed -n 2p "$VENV_CLI")"
        second="${second#"'''exec' "}"
        if [[ "$second" == \"* ]]; then
            second="${second#\"}"
            second="${second%%\"*}"
        else
            second="${second%% *}"
        fi
        printf '%s\n' "$second"
    else
        first="${first#\#!}"
        printf '%s\n' "${first%% *}"
    fi
}

has_net_raw() {
    "$1" -c "
import sys
from $MODULE._doctor import CAP_NET_RAW, has_capability, is_root
sys.exit(0 if (is_root() or has_capability(CAP_NET_RAW)) else 1)
" >/dev/null 2>&1
}

configure_privileges() {
    local interp setcap_cmd=() udev_cmds=() staged_dir="$GCAM_MVSDK_HOME/udev-rules" rule name all_present
    interp="$(script_interpreter)"
    [ -n "$interp" ] || interp="$VENV_PY"

    say "Checking raw-socket access (CAP_NET_RAW) for GigE discovery"
    if has_net_raw "$interp"; then
        CAP_STATE="granted"
        info "already granted to $interp"
    elif [ -L "$interp" ] || [ ! -f "$interp" ]; then
        CAP_STATE="not granted ($interp is not a private copy)"
        warn "$interp is a symlink or missing; not applying setcap to a shared interpreter"
    else
        CAP_STATE="not granted"
        setcap_cmd=(setcap "cap_net_raw,cap_net_admin+ep" "$interp")
        info "not granted yet to $interp"
    fi

    say "Checking the USB udev rules"
    local staged=()
    all_present=1
    if [ -n "$SDK_ROOT" ]; then
        for name in 88-mvusb.rules 99-mvusb.rules; do
            rule="$SDK_ROOT/$name"
            [ -f "$rule" ] || continue
            mkdir -p -- "$staged_dir"
            # The vendor files use CRLF line endings; udev expects LF.
            tr -d '\r' <"$rule" >"$staged_dir/$name"
            staged+=("$staged_dir/$name")
            if ! cmp -s "$staged_dir/$name" "/etc/udev/rules.d/$name"; then
                all_present=0
            fi
        done
    fi
    if [ ${#staged[@]} -eq 0 ]; then
        UDEV_STATE="skipped (no rules found in the SDK)"
        info "no udev rules found in the SDK; skipping"
    elif [ "$all_present" -eq 1 ]; then
        UDEV_STATE="installed"
        info "already installed in /etc/udev/rules.d"
    else
        UDEV_STATE="not installed"
        info "not installed yet"
        udev_cmds=(
            "$(quote_cmd install -m 0644 "${staged[@]}" /etc/udev/rules.d/)"
            "$(quote_cmd udevadm control --reload-rules)"
            "$(quote_cmd udevadm trigger)"
        )
    fi

    local cmds=()
    if [ ${#setcap_cmd[@]} -gt 0 ]; then
        if ! command -v setcap >/dev/null 2>&1 && [ ! -x /usr/sbin/setcap ] && [ ! -x /sbin/setcap ] && [ "$IS_DEBIAN" -eq 1 ]; then
            cmds+=("$(quote_cmd apt-get install -y libcap2-bin)")
        fi
        cmds+=("$(quote_cmd "${setcap_cmd[@]}")")
    fi
    if [ ${#udev_cmds[@]} -gt 0 ]; then
        cmds+=("${udev_cmds[@]}")
    fi
    if [ ${#cmds[@]} -eq 0 ]; then
        return 0
    fi

    say "Privileged setup: GigE raw sockets and USB udev rules"
    local prefix="" c
    if [ ${#SUDO[@]} -gt 0 ]; then
        prefix="sudo "
    fi
    info "These commands need root:"
    for c in "${cmds[@]}"; do
        info "  $prefix$c"
    done
    if [ "$NO_SUDO" -eq 1 ]; then
        info "--no-sudo given: not running them. Run them yourself later for GigE discovery and USB access."
        return 0
    fi
    if ! confirm "Run them now (one sudo prompt)?" Y; then
        info "Skipped. Run them later; until then use: sudo -E $LINK list"
        return 0
    fi
    local joined
    joined="$(printf '%s && ' "${cmds[@]}")"
    joined="${joined% && }"
    if ${SUDO[@]+"${SUDO[@]}"} bash -c "$joined"; then
        if [ ${#setcap_cmd[@]} -gt 0 ]; then
            if "$interp" -c "import numpy, $MODULE" >/dev/null 2>&1 && has_net_raw "$interp"; then
                CAP_STATE="granted"
                info "CAP_NET_RAW is now effective for $interp"
            else
                CAP_STATE="setcap applied but not effective"
                warn "the interpreter does not work as expected with capabilities; undo with: sudo setcap -r $interp"
            fi
        fi
        if [ ${#udev_cmds[@]} -gt 0 ]; then
            UDEV_STATE="installed"
        fi
    else
        warn "the privileged commands failed; run them by hand (see above)"
    fi
}

final_checks() {
    local rc_doctor=0 rc_list=0
    say "Running $PKG doctor"
    (cd -- "$RUN_DIR" && "$VENV_CLI" doctor) || rc_doctor=$?
    say "Running $PKG list"
    (cd -- "$RUN_DIR" && "$VENV_CLI" list) || rc_list=$?

    say "Summary"
    info "Package       $PKG $PKG_VERSION in $VENV_DIR"
    info "Command       $LINK"
    if [ -n "$SDK_ROOT" ]; then
        info "SDK           $SDK_VERSION at $SDK_ROOT (lib/$SDK_ARCH)"
    else
        info "SDK           not found by the loader"
    fi
    info "GigE access   CAP_NET_RAW $CAP_STATE"
    info "USB access    udev rules $UDEV_STATE"
    if [ "$DEV" -eq 1 ]; then
        info "Dev mode      run commands from $SCRIPT_DIR so ./vendor is found, or export GCAM_MVSDK_DIR=$SDK_ROOT"
    fi
    if [ "$PATH_HINT" -eq 1 ]; then
        info "PATH          add: export PATH=\"$BIN_DIR:\$PATH\""
    fi
    echo
    echo "Next steps:"
    echo "  $PKG list                              # find your cameras (user name, serial, IP)"
    echo "  $PKG grab <NAME or SN> -n 1 -o frames  # save a test frame as PNG"
    if [ "$rc_doctor" -ne 0 ] || [ "$rc_list" -ne 0 ]; then
        echo
        echo "install.bash: the final checks reported failures (doctor exit $rc_doctor, list exit $rc_list)." >&2
        return 1
    fi
    return 0
}

uninstall() {
    say "Removing the command link $LINK"
    if [ -L "$LINK" ]; then
        local target
        target="$(readlink -- "$LINK")"
        case "$target" in
            "$VENV_DIR"/*) rm -f -- "$LINK"; info "removed" ;;
            *) warn "$LINK points to $target, not to this installation; left in place" ;;
        esac
    else
        info "not present"
    fi

    say "Removing the virtual environment $VENV_DIR"
    if [ -d "$VENV_DIR" ]; then
        [ -f "$VENV_DIR/pyvenv.cfg" ] || die "$VENV_DIR is not a virtual environment; refusing to delete it"
        rm -rf -- "$VENV_DIR"
        info "removed"
    else
        info "not present"
    fi

    say "Checking for downloaded SDK files in $GCAM_MVSDK_HOME"
    local found=() d
    if [ -d "$GCAM_MVSDK_HOME" ]; then
        for d in "$GCAM_MVSDK_HOME"/*/; do
            [ -d "$d" ] || continue
            d="${d%/}"
            if [ -d "$d/lib" ] || [ -f "$d/manifest.json" ] || [ "$(basename -- "$d")" = "udev-rules" ]; then
                found+=("$d")
            fi
        done
        [ -d "$GCAM_MVSDK_HOME/.downloads" ] && found+=("$GCAM_MVSDK_HOME/.downloads")
    fi
    if [ ${#found[@]} -eq 0 ]; then
        info "none"
    else
        for d in "${found[@]}"; do
            info "  $d"
        done
        info "The Rust tool gcam-mvsdk-rs uses the same SDK files."
        if confirm_destructive "Delete these SDK files as well?"; then
            rm -rf -- "${found[@]}"
            rmdir -- "$GCAM_MVSDK_HOME" 2>/dev/null || true
            info "deleted"
        else
            info "kept; delete them later with: rm -rf $(quote_cmd "${found[@]}")"
        fi
    fi
    if [ -f /etc/udev/rules.d/99-mvusb.rules ] || [ -f /etc/udev/rules.d/88-mvusb.rules ]; then
        info "USB udev rules remain; remove them with: sudo rm -f /etc/udev/rules.d/88-mvusb.rules /etc/udev/rules.d/99-mvusb.rules"
    fi
    if [ -d "$SCRIPT_DIR/vendor" ]; then
        info "The developer SDK copy in $SCRIPT_DIR/vendor is untouched."
    fi
    say "Uninstalled $PKG"
}

main() {
    parse_args "$@"
    if [ "$UNINSTALL" -eq 1 ]; then
        uninstall
        return 0
    fi
    check_platform
    detect_arch
    ensure_python
    make_venv
    install_package
    link_cli
    if [ "$DEV" -eq 1 ]; then
        RUN_DIR="$SCRIPT_DIR"
    else
        RUN_DIR="$GCAM_MVSDK_HOME"
    fi
    install_sdk
    configure_privileges
    if ! final_checks; then
        exit 1
    fi
}

main "$@"
