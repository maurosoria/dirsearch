#!/bin/bash
# Build script for dirsearch PyInstaller binaries
# Builds for the current platform
#
# Usage:
#   ./build.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Create dist directory
mkdir -p "$SCRIPT_DIR/dist"

build() {
    log_info "Building for current platform..."
    cd "$PROJECT_ROOT"

    # Determine platform suffix
    PLATFORM=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)

    if [[ "$PLATFORM" == "darwin" ]]; then
        if [[ "$ARCH" == "arm64" ]]; then
            SUFFIX="macos-silicon"
        else
            SUFFIX="macos-intel"
        fi
    elif [[ "$PLATFORM" == "linux" ]]; then
        SUFFIX="linux-amd64"
    elif [[ "$PLATFORM" == "mingw"* ]] || [[ "$PLATFORM" == "msys"* ]]; then
        SUFFIX="windows-x64"
    else
        SUFFIX="$PLATFORM-$ARCH"
    fi

    # Check for Python
    if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
        log_error "Python 3 is required"
        exit 1
    fi

    PYTHON_CMD=$(command -v python3 || command -v python)

    # Install dependencies
    log_info "Installing dependencies..."
    $PYTHON_CMD -m pip install --upgrade pip setuptools wheel
    $PYTHON_CMD -m pip install -r requirements.txt
    $PYTHON_CMD -m pip install pyinstaller==6.3.0

    # Build
    log_info "Running PyInstaller..."
    $PYTHON_CMD -m PyInstaller \
        --onefile \
        --name dirsearch \
        --paths=. \
        --collect-submodules=lib \
        --add-data "db:db" \
        --add-data "config.ini:." \
        --add-data "lib/report:lib/report" \
        --hidden-import=lib \
        --hidden-import=lib.core \
        --hidden-import=lib.core.settings \
        --hidden-import=lib.core.options \
        --hidden-import=lib.controller \
        --hidden-import=lib.connection \
        --hidden-import=lib.parse \
        --hidden-import=lib.report \
        --hidden-import=lib.utils \
        --hidden-import=lib.view \
        --hidden-import=requests \
        --hidden-import=httpx \
        --hidden-import=urllib3 \
        --hidden-import=charset_normalizer \
        --hidden-import=certifi \
        --hidden-import=PySocks \
        --hidden-import=socks \
        --hidden-import=jinja2 \
        --hidden-import=defusedxml \
        --hidden-import=OpenSSL \
        --hidden-import=ntlm_auth \
        --hidden-import=requests_ntlm \
        --hidden-import=bs4 \
        --hidden-import=colorama \
        --hidden-import=defusedcsv \
        --hidden-import=httpx_ntlm \
        --hidden-import=httpcore \
        --hidden-import=h11 \
        --hidden-import=anyio \
        --hidden-import=sniffio \
        --hidden-import=socksio \
        --strip \
        --clean \
        dirsearch.py

    # Move and rename binary
    if [[ "$SUFFIX" == "windows"* ]]; then
        mv dist/dirsearch.exe "$SCRIPT_DIR/dist/dirsearch-$SUFFIX.exe"
        log_info "Binary created: pyinstaller/dist/dirsearch-$SUFFIX.exe"
    else
        mv dist/dirsearch "$SCRIPT_DIR/dist/dirsearch-$SUFFIX"
        chmod +x "$SCRIPT_DIR/dist/dirsearch-$SUFFIX"
        log_info "Binary created: pyinstaller/dist/dirsearch-$SUFFIX"
    fi
}

show_help() {
    echo "dirsearch PyInstaller Build Script"
    echo ""
    echo "Usage: $0"
    echo ""
    echo "Builds a standalone executable for the current platform."
    echo ""
    echo "Supported platforms:"
    echo "  - Linux AMD64"
    echo "  - macOS Intel / Silicon"
    echo "  - Windows x64"
}

case "${1:-build}" in
    build|"")
        build
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac

log_info "Build complete!"
ls -la "$SCRIPT_DIR/dist/"
