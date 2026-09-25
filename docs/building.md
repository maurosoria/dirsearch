# Building

dirsearch release builds produce two downloadable formats:

- PyInstaller single-file binaries for quick use.
- Portable folders that bundle CPython, Python dependencies, optional DB drivers, and the Rust native module when selected.

PyInstaller binaries are convenient, but some antivirus engines flag PyInstaller bootloaders heuristically. Use the portable folder archives when a single-file executable is blocked.

## Supported Release Targets

| Platform | Architecture | PyInstaller | Portable folder | Docker |
|----------|--------------|-------------|-----------------|--------|
| Windows | x64 | Yes | Yes | No |
| Linux | x64 | Yes | Yes | GHCR image |
| Linux | ARM64 | Yes | Yes | No |
| macOS | Intel x86_64 | Yes | Yes | No |
| macOS | Apple Silicon ARM64 | Yes | Yes | No |

Each non-Docker target is built in three default-stack variants:

| Variant | Defaults | Purpose |
|---------|----------|---------|
| `async` | `async = True`, `request-backend = python` | Recommended default runtime |
| `threaded` | `async = False`, `request-backend = python` | Legacy threaded Python runtime |
| `native-rust` | `async = False`, `request-backend = native`, `wordlist-backend = native` | Rust request and wordlist backend |

## Local PyInstaller Build

Requirements:

- Python 3.14 for release-equivalent builds.
- PyInstaller 6.20.0.
- Rust 1.86 or newer when building `native-rust`; build scripts install maturin as needed.

Native Rust builds use `scripts/build_native.py` to build one wheel, install that exact wheel path, and verify `import dirsearch_native`. This avoids shell-specific wildcard behavior on Windows and keeps Docker, PyInstaller, and portable builds on the same path. The native wheel is packaged with `requires-python >=3.14` and retains PyO3's `cp313-abi3` feature so the security upgrade does not change the extension's established stable-ABI contract.

Build the current platform:

```sh
pyinstaller/build.sh async
pyinstaller/build.sh threaded
pyinstaller/build.sh native-rust
```

Build all three variants for the current platform:

```sh
pyinstaller/build.sh all
```

Artifacts are written to `pyinstaller/dist/` with names such as:

```text
dirsearch-v0.5.0-rc1-linux-x64-async
dirsearch-v0.5.0-rc1-windows-x64-native-rust.exe
```

## Local Portable Build

Portable builds use CPython from `python-build-standalone` and install wheels into the bundled interpreter.

```sh
python3 scripts/build_portable.py --target linux-x64 --stack async
python3 scripts/build_portable.py --target linux-x64 --stack native-rust
```

Valid targets are:

- `windows-x64`
- `linux-x64`
- `linux-arm64`
- `macos-intel`
- `macos-silicon`

Portable artifacts are written to `portable/dist/` as `.zip` on Windows and `.tar.gz` on Linux/macOS.

## GitHub Workflows

| Workflow | Trigger | Description |
|----------|---------|-------------|
| Inspection (CI) | Push, PR | Tests, linting, and codespell |
| PyInstaller Linux | Manual, workflow call | Builds Linux x64 and ARM64 PyInstaller artifacts |
| PyInstaller Windows | Manual, workflow call | Builds Windows x64 PyInstaller artifacts |
| PyInstaller macOS Intel | Manual, workflow call | Builds macOS Intel PyInstaller artifacts |
| PyInstaller macOS Silicon | Manual, workflow call | Builds macOS Apple Silicon PyInstaller artifacts |
| Portable Builds | Manual, workflow call | Builds portable folder archives for all OS/arch targets |
| Docker Images | Push, PR, manual, workflow call | Builds Linux x64 Docker images and can push GHCR tags |
| v0.5.0 Prerelease | Manual | Builds all release assets and creates a draft GitHub prerelease |

## Creating the v0.5.0 Prerelease

1. Go to Actions > v0.5.0 Prerelease.
2. Click Run workflow.
3. Use tag `v0.5.0-rc1`.
4. Keep prerelease enabled.
5. Review the draft release, checksums, and GHCR image tags before publishing.

The release workflow publishes Docker images to GitHub Container Registry for Linux x64 only:

```text
ghcr.io/<owner>/dirsearch:v0.5.0-rc1-async
ghcr.io/<owner>/dirsearch:v0.5.0-rc1-threaded
ghcr.io/<owner>/dirsearch:v0.5.0-rc1-native-rust
```
