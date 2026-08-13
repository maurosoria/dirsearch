#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
RELEASE_TAG="${RELEASE_TAG:-v0.5.0-rc1}"
PYINSTALLER_VERSION="${PYINSTALLER_VERSION:-6.20.0}"
STACK="${1:-async}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

python_cmd() {
    if [[ -n "${PYTHON_CMD:-}" ]]; then
        echo "$PYTHON_CMD"
        return
    fi
    if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
        echo "$VIRTUAL_ENV/bin/python"
        return
    fi
    command -v python3 || command -v python
}

platform_suffix() {
    local platform arch
    platform="$(uname -s | tr '[:upper:]' '[:lower:]')"
    arch="$(uname -m)"

    case "$platform:$arch" in
        darwin:arm64) echo "macos-silicon" ;;
        darwin:*) echo "macos-intel" ;;
        linux:aarch64|linux:arm64) echo "linux-arm64" ;;
        linux:*) echo "linux-x64" ;;
        mingw*:*) echo "windows-x64" ;;
        msys*:*) echo "windows-x64" ;;
        *) echo "$platform-$arch" ;;
    esac
}

configure_stack() {
    local stack="$1"
    "$PYTHON_CMD" scripts/configure_stack.py config.ini "$stack"
}

install_dependencies() {
    log_info "Installing Python dependencies..."
    "$PYTHON_CMD" -m pip install --upgrade pip setuptools wheel
    "$PYTHON_CMD" -m pip install --only-binary=:all: -r requirements.txt -r requirements/db.txt
    "$PYTHON_CMD" -m pip install "pyinstaller==$PYINSTALLER_VERSION"
}

build_native() {
    log_info "Building native Rust extension..."
    if command -v rustup >/dev/null 2>&1; then
        rustup default stable
    fi
    "$PYTHON_CMD" -m pip install --only-binary=:all: maturin
    "$PYTHON_CMD" scripts/build_native.py --python "$PYTHON_CMD" --out dist/native-wheels
}

build_stack() {
    local stack="$1"
    local suffix="$2"

    log_info "Building $suffix ($stack)..."
    configure_stack "$stack"

    if [[ "$stack" == "native-rust" ]]; then
        build_native
    fi

    "$PYTHON_CMD" -m PyInstaller --clean pyinstaller/dirsearch.spec

    mkdir -p "$SCRIPT_DIR/dist"
    if [[ "$suffix" == "windows-x64" ]]; then
        mv dist/dirsearch.exe "$SCRIPT_DIR/dist/dirsearch-$RELEASE_TAG-$suffix-$stack.exe"
        log_info "Binary created: pyinstaller/dist/dirsearch-$RELEASE_TAG-$suffix-$stack.exe"
    else
        mv dist/dirsearch "$SCRIPT_DIR/dist/dirsearch-$RELEASE_TAG-$suffix-$stack"
        chmod +x "$SCRIPT_DIR/dist/dirsearch-$RELEASE_TAG-$suffix-$stack"
        log_info "Binary created: pyinstaller/dist/dirsearch-$RELEASE_TAG-$suffix-$stack"
    fi
}

show_help() {
    echo "dirsearch PyInstaller Build Script"
    echo
    echo "Usage: $0 [threaded|async|native-rust|all]"
    echo
    echo "Environment:"
    echo "  RELEASE_TAG=$RELEASE_TAG"
    echo "  PYINSTALLER_VERSION=$PYINSTALLER_VERSION"
}

case "$STACK" in
    threaded|async|native-rust|all|help|--help|-h) ;;
    *)
        log_error "Unknown stack: $STACK"
        show_help
        exit 1
        ;;
esac

if [[ "$STACK" == "help" || "$STACK" == "--help" || "$STACK" == "-h" ]]; then
    show_help
    exit 0
fi

cd "$PROJECT_ROOT"
PYTHON_CMD="$(python_cmd)"

if [[ -z "$PYTHON_CMD" ]]; then
    log_error "Python 3.14 is required"
    exit 1
fi

if ! "$PYTHON_CMD" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))'; then
    log_warn "Release builds use Python 3.14; continuing with $("$PYTHON_CMD" --version)"
fi

CONFIG_BACKUP="$(mktemp)"
cp config.ini "$CONFIG_BACKUP"
trap 'cp "$CONFIG_BACKUP" config.ini; rm -f "$CONFIG_BACKUP"' EXIT

install_dependencies
SUFFIX="$(platform_suffix)"

if [[ "$STACK" == "all" ]]; then
    build_stack threaded "$SUFFIX"
    build_stack async "$SUFFIX"
    build_stack native-rust "$SUFFIX"
else
    build_stack "$STACK" "$SUFFIX"
fi

log_info "Build complete!"
ls -la "$SCRIPT_DIR/dist/"
