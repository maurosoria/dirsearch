#!/bin/bash
# Build script for creating ARM64 executable using Docker cross-compilation
#
# This script builds an ARM64 executable of dirsearch using Docker,
# allowing you to cross-compile from x86_64 to ARM64.
#
# Usage:
#   ./build-arm64.sh
#
# Requirements:
#   - Docker installed and running
#   - Docker must support multi-platform builds
#   - For x86_64 hosts: Docker needs binfmt_misc support for ARM64
#
# Setup binfmt_misc for cross-platform builds (run once):
#   docker run --privileged --rm tonistiigi/binfmt --install all

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

# Check if Docker is installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running. Please start Docker first."
        exit 1
    fi
}

# Check if QEMU/binfmt_misc is configured for ARM64
check_binfmt() {
    log_step "Checking binfmt_misc support for ARM64..."

    if docker run --rm --platform linux/arm64 alpine:latest uname -m &> /dev/null; then
        log_info "ARM64 emulation is configured and working."
        return 0
    else
        log_warn "ARM64 emulation may not be configured properly."
        log_warn "Run the following command to enable multi-platform support:"
        echo ""
        echo "  docker run --privileged --rm tonistiigi/binfmt --install all"
        echo ""
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
        return 1
    fi
}

# Build ARM64 executable using Docker
build_arm64() {
    log_step "Building ARM64 Docker image..."

    cd "$PROJECT_ROOT"

    # Build Docker image and extract binary
    log_info "This may take several minutes (first run will be slower)..."

    # Build the Docker image and run it to extract the binary
    docker buildx build \
        --platform linux/arm64 \
        --file pyinstaller/Dockerfile.arm64 \
        --tag dirsearch-arm64-builder \
        --load \
        .

    # Extract the binary from the image
    log_step "Extracting ARM64 binary..."

    # Create output directory
    mkdir -p "$SCRIPT_DIR/dist"

    # Create a temporary container to extract the binary
    CONTAINER_ID=$(docker create dirsearch-arm64-builder)
    docker cp "$CONTAINER_ID:/dirsearch-arm64" "$SCRIPT_DIR/dist/dirsearch-arm64"
    docker rm "$CONTAINER_ID"

    # Make the binary executable
    chmod +x "$SCRIPT_DIR/dist/dirsearch-arm64"

    log_info "Binary created: pyinstaller/dist/dirsearch-arm64"
}

# Verify the binary
verify_binary() {
    log_step "Verifying ARM64 binary..."

    if [ -f "$SCRIPT_DIR/dist/dirsearch-arm64" ]; then
        ARCH=$(file "$SCRIPT_DIR/dist/dirsearch-arm64")
        log_info "Binary architecture: $ARCH"

        if echo "$ARCH" | grep -q "ARM aarch64"; then
            log_info "✓ Successfully built ARM64 executable!"
        else
            log_warn "Binary may not be ARM64. Please check."
        fi

        # Check if it's executable
        if [ -x "$SCRIPT_DIR/dist/dirsearch-arm64" ]; then
            log_info "✓ Binary is executable"
        else
            log_warn "Binary is not executable. This is expected if you're on a different platform."
        fi
    else
        log_error "Binary not found at: $SCRIPT_DIR/dist/dirsearch-arm64"
        exit 1
    fi
}

# Show usage
show_help() {
    echo "ARM64 Build Script for dirsearch"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  build       Build ARM64 executable (default)"
    echo "  help        Show this help message"
    echo ""
    echo "Requirements:"
    echo "  - Docker installed and running"
    echo "  - Docker must support multi-platform builds"
    echo ""
    echo "First-time setup (if not already done):"
    echo "  docker run --privileged --rm tonistiigi/binfmt --install all"
    echo ""
    echo "Output:"
    echo "  pyinstaller/dist/dirsearch-arm64"
}

# Main execution
main() {
    check_docker
    check_binfmt || true
    build_arm64
    verify_binary

    echo ""
    log_info "Build complete!"
    echo ""
    echo "ARM64 binary location: $SCRIPT_DIR/dist/dirsearch-arm64"
    echo ""
    echo "To run on ARM64 device:"
    echo "  ./pyinstaller/dist/dirsearch-arm64 --help"
}

case "${1:-build}" in
    build|"")
        main
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
