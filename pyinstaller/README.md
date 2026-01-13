# PyInstaller Build Configuration

This directory contains the configuration for building standalone dirsearch executables using PyInstaller.

## Supported Platforms

| Platform | Architecture | Runner |
|----------|--------------|--------|
| Linux | AMD64 | ubuntu-latest |
| Windows | x64 | windows-latest |
| macOS | Intel (x86_64) | macos-13 |
| macOS | Silicon (ARM64) | macos-14 |

## Quick Start

### Build for Current Platform

```bash
# Install dependencies
pip install -r requirements.txt pyinstaller==6.3.0

# Run PyInstaller
pyinstaller pyinstaller/dirsearch.spec
```

### Using Build Script

```bash
chmod +x pyinstaller/build.sh
./pyinstaller/build.sh
```

## GitHub Actions

The workflow automatically builds for all platforms when:
- A version tag is pushed (e.g., `v0.4.4RC1`)
- Manually triggered via workflow_dispatch

### Triggering a Release

```bash
git tag v0.4.4RC1
git push origin v0.4.4RC1
```

This creates a GitHub Release with binaries for all platforms.

## Files

| File | Description |
|------|-------------|
| `dirsearch.spec` | PyInstaller specification file |
| `build.sh` | Build script for local builds |

## Output

Binaries are created in `dist/`:

```
dist/
├── dirsearch-linux-amd64
├── dirsearch-windows-x64.exe
├── dirsearch-macos-intel
└── dirsearch-macos-silicon
```

## Troubleshooting

### Missing modules
Add hidden imports to the PyInstaller command or `.spec` file:
```
--hidden-import=module_name
```

### macOS code signing
For distribution, sign binaries with:
```bash
codesign --sign "Developer ID" dirsearch-macos-*
```
