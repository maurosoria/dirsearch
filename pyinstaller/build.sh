#!/bin/bash
# Build script for dirsearch PyInstaller binaries
# Uses Docker with BuildKit for cross-platform builds
#
# Usage:
#   ./build.sh              # Build all platforms
#   ./build.sh linux        # Build Linux only
#   ./build.sh windows      # Build Windows only
#   ./build.sh all          # Build all platforms

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Enable BuildKit
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create dist directory
mkdir -p "$SCRIPT_DIR/dist"

build_linux() {
    log_info "Building Linux AMD64 binary..."
    cd "$SCRIPT_DIR"

    docker buildx build \
        --file Dockerfile.linux \
        --target builder \
        --load \
        --tag dirsearch-builder-linux \
        "$PROJECT_ROOT"

    # Extract binary
    docker run --rm \
        -v "$SCRIPT_DIR/dist:/output" \
        dirsearch-builder-linux \
        cp /app/dist/dirsearch /output/dirsearch-linux-amd64

    chmod +x "$SCRIPT_DIR/dist/dirsearch-linux-amd64"
    log_info "Linux binary created: dist/dirsearch-linux-amd64"
}

build_windows() {
    log_info "Building Windows x64 binary (via Wine)..."
    log_warn "This may take a while on first run (Wine + Python installation)"
    cd "$SCRIPT_DIR"

    docker buildx build \
        --file Dockerfile.windows \
        --target builder \
        --load \
        --tag dirsearch-builder-windows \
        "$PROJECT_ROOT"

    # Extract binary
    docker run --rm \
        -v "$SCRIPT_DIR/dist:/output" \
        dirsearch-builder-windows \
        cp /app/dist/dirsearch.exe /output/dirsearch-windows-x64.exe

    log_info "Windows binary created: dist/dirsearch-windows-x64.exe"
}

build_native() {
    log_info "Building native binary for current platform..."
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
    else
        SUFFIX="$PLATFORM-$ARCH"
    fi

    # Check for Python and pip
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required"
        exit 1
    fi

    # Install dependencies
    log_info "Installing dependencies..."
    python3 -m pip install -r requirements.txt pyinstaller

    # Build
    log_info "Running PyInstaller..."
    python3 -m PyInstaller \
        --onefile \
        --name "dirsearch-$SUFFIX" \
        --add-data "db:db" \
        --add-data "config.ini:." \
        --add-data "lib/report:lib/report" \
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

    # Move to pyinstaller/dist
    mv "dist/dirsearch-$SUFFIX" "$SCRIPT_DIR/dist/"
    log_info "Native binary created: pyinstaller/dist/dirsearch-$SUFFIX"
}

show_help() {
    echo "dirsearch PyInstaller Build Script"
    echo ""
    echo "Usage: $0 [target]"
    echo ""
    echo "Targets:"
    echo "  linux      Build Linux AMD64 binary using Docker"
    echo "  windows    Build Windows x64 binary using Docker + Wine"
    echo "  native     Build binary for current platform (no Docker)"
    echo "  all        Build all Docker-based platforms (linux, windows)"
    echo "  help       Show this help message"
    echo ""
    echo "Environment variables:"
    echo "  DOCKER_BUILDKIT=1           Enable BuildKit (default)"
    echo "  COMPOSE_DOCKER_CLI_BUILD=1  Use Docker CLI for Compose (default)"
    echo ""
    echo "Examples:"
    echo "  $0 linux           # Build Linux binary"
    echo "  $0 windows         # Build Windows binary"
    echo "  $0 native          # Build for current OS"
    echo "  $0 all             # Build all platforms"
}

# Main
case "${1:-all}" in
    linux)
        build_linux
        ;;
    windows)
        build_windows
        ;;
    native)
        build_native
        ;;
    all)
        build_linux
        build_windows
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown target: $1"
        show_help
        exit 1
        ;;
esac

log_info "Build complete! Binaries are in: $SCRIPT_DIR/dist/"
ls -la "$SCRIPT_DIR/dist/"
