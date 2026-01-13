# PyInstaller Build Configuration

This directory contains the configuration for building standalone dirsearch executables using PyInstaller.

## Supported Platforms

| Platform | Architecture | Build Method |
|----------|--------------|--------------|
| Linux | AMD64 | Docker + BuildKit |
| Windows | x64 | Docker + BuildKit + Wine |
| macOS | Intel (x86_64) | Native (GitHub Actions) |
| macOS | Silicon (ARM64) | Native (GitHub Actions) |

## Quick Start

### Using Docker Compose (Linux/Windows)

```bash
# Build all platforms
cd pyinstaller
DOCKER_BUILDKIT=1 docker compose build

# Build specific platform
docker compose build linux
docker compose build windows

# Extract binaries
docker compose run --rm linux-builder
docker compose run --rm windows-builder
```

### Using Build Script

```bash
# Make script executable
chmod +x pyinstaller/build.sh

# Build all Docker-based platforms
./pyinstaller/build.sh all

# Build specific platform
./pyinstaller/build.sh linux
./pyinstaller/build.sh windows

# Build for current platform (no Docker needed)
./pyinstaller/build.sh native
```

### Manual Build (Current Platform)

```bash
# Install dependencies
pip install -r requirements.txt pyinstaller

# Run PyInstaller
pyinstaller pyinstaller/dirsearch.spec
```

## GitHub Actions

The workflow automatically builds for all platforms when:
- A version tag is pushed (e.g., `v0.4.3`)
- Manually triggered via workflow_dispatch

### Triggering a Release

```bash
# Tag and push
git tag v0.4.3
git push origin v0.4.3
```

This creates a GitHub Release with binaries for all platforms.

## Files

| File | Description |
|------|-------------|
| `dirsearch.spec` | PyInstaller specification file |
| `Dockerfile.linux` | Docker build for Linux AMD64 |
| `Dockerfile.windows` | Docker build for Windows x64 (Wine) |
| `docker-compose.yml` | Docker Compose with BuildKit |
| `build.sh` | Build script for local builds |

## BuildKit Features Used

- **Layer caching**: Faster rebuilds with `--mount=type=cache`
- **Multi-stage builds**: Smaller final images
- **Build cache export**: GitHub Actions cache integration
- **Parallel builds**: Independent builds run concurrently

## Output

Binaries are created in `pyinstaller/dist/`:

```
dist/
├── dirsearch-linux-amd64
├── dirsearch-windows-x64.exe
├── dirsearch-macos-intel
└── dirsearch-macos-silicon
```

## Troubleshooting

### Wine build is slow
First build downloads and installs Python in Wine. Subsequent builds use cached layers.

### Missing modules
Add hidden imports to the PyInstaller command or `.spec` file:
```python
--hidden-import=module_name
```

### macOS code signing
For distribution, sign binaries with:
```bash
codesign --sign "Developer ID" dirsearch-macos-*
```
