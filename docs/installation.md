# Installation

## Supported Platforms

dirsearch runs on Python 3.11-3.14 and is distributed as source, installable from GitHub with pip, Docker image, PyInstaller binary, or portable folder.

| Platform | Architecture | PyInstaller | Portable folder |
|----------|--------------|-------------|-----------------|
| Windows | x64 | Yes | Yes |
| Linux | x64 | Yes | Yes |
| Linux | ARM64 | Yes | Yes |
| macOS | Intel x86_64 | Yes | Yes |
| macOS | Apple Silicon ARM64 | Yes | Yes |

## Install from Source

Requirement: Python 3.11 or higher.

```sh
git clone https://github.com/maurosoria/dirsearch.git --depth 1
cd dirsearch
python3 dirsearch.py -u https://example.com -w tests/static/wordlist.txt -q
```

## Other Install Methods

- ZIP archive: [Download the master branch](https://github.com/maurosoria/dirsearch/archive/master.zip).
- GitHub with pip: `pip3 install git+https://github.com/maurosoria/dirsearch.git`.
- Docker: `docker pull ghcr.io/maurosoria/dirsearch:v0.5.0-rc1-async`.
- Kali Linux: `sudo apt-get install dirsearch` (deprecated).

## Release Artifacts

Pre-built release assets are available on the [Releases page](https://github.com/maurosoria/dirsearch/releases).

Each platform has three stack variants:

| Variant | Default behavior |
|---------|------------------|
| `async` | Recommended Python async runtime |
| `threaded` | Legacy threaded Python runtime |
| `native-rust` | Rust request and wordlist backends |

PyInstaller examples:

```text
dirsearch-v0.5.0-rc1-linux-x64-async
dirsearch-v0.5.0-rc1-linux-arm64-native-rust
dirsearch-v0.5.0-rc1-windows-x64-threaded.exe
dirsearch-v0.5.0-rc1-macos-intel-async
dirsearch-v0.5.0-rc1-macos-silicon-native-rust
```

Portable examples:

```text
dirsearch-v0.5.0-rc1-linux-x64-async-portable.tar.gz
dirsearch-v0.5.0-rc1-windows-x64-native-rust-portable.zip
```

PyInstaller binaries are single files. Portable archives are larger, but bundle CPython and compiled dependencies and are less likely to trigger antivirus false positives caused by PyInstaller bootloader heuristics.

Linux and macOS PyInstaller usage:

```sh
chmod +x dirsearch-v0.5.0-rc1-linux-x64-async
./dirsearch-v0.5.0-rc1-linux-x64-async -u https://target
```

Windows PyInstaller usage:

```sh
dirsearch-v0.5.0-rc1-windows-x64-async.exe -u https://target
```

Portable usage:

```sh
tar -xzf dirsearch-v0.5.0-rc1-linux-x64-async-portable.tar.gz
./dirsearch-v0.5.0-rc1-linux-x64-async-portable/dirsearch -u https://target
```

On Windows, extract the `.zip` and run `dirsearch.cmd`.

## Docker

Docker images are published for Linux x64 in GitHub Container Registry:

```sh
docker pull ghcr.io/maurosoria/dirsearch:v0.5.0-rc1-async
docker run -it --rm ghcr.io/maurosoria/dirsearch:v0.5.0-rc1-async -u target -e php,html,js,zip
```

Available tags for the prerelease:

- `ghcr.io/maurosoria/dirsearch:v0.5.0-rc1-async`
- `ghcr.io/maurosoria/dirsearch:v0.5.0-rc1-threaded`
- `ghcr.io/maurosoria/dirsearch:v0.5.0-rc1-native-rust`

Build locally:

```sh
docker build --build-arg DIRSEARCH_STACK=async -t dirsearch:v0.5.0-rc1-async .
docker build --build-arg DIRSEARCH_STACK=native-rust -t dirsearch:v0.5.0-rc1-native-rust .
```
