# Installation

## Supported Platforms

dirsearch runs on Python 3.11-3.14 and is distributed as source, installable from GitHub with pip, Docker image, PyInstaller binary, or portable folder. Release-equivalent native builds use Python 3.14.

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
- GitHub with pip, Python stack: `pip3 install git+https://github.com/maurosoria/dirsearch.git`.
- Docker: `docker pull ghcr.io/maurosoria/dirsearch:v0.5.0-rc1-async`.
- Kali Linux: `sudo apt-get install dirsearch` (deprecated).

## Choose an Install Path

- Use release artifacts when you do not want to compile anything. Single-file PyInstaller binaries and portable archives are available for Windows x64, Linux x64, Linux ARM64, macOS Intel, and macOS Apple Silicon.
- Use the Python-only pip install when you want the current GitHub source and the default Python request backend. This works on Python 3.11-3.14 and does not compile the Rust native engine.
- Use the native Rust pip install when you want `--request-backend native` or `--wordlist-backend native`. This requires Python 3.14, Rust 1.86 or newer, Python development headers, and a C compiler.
- Use the source checkout build only when developing or producing release artifacts. Normal native installs do not require manually cloning the repository.

## Python-Only Install from GitHub

Requirement: Python 3.11 or higher.

### Ubuntu and Debian, amd64 or arm64

```sh
sudo apt-get update
sudo apt-get install -y git ca-certificates python3 python3-venv python3-pip
python3 -m venv ~/.venvs/dirsearch
. ~/.venvs/dirsearch/bin/activate
python -m pip install --upgrade pip
python -m pip install "git+https://github.com/maurosoria/dirsearch.git"
dirsearch --version
```

### Red Hat and Fedora, amd64 or arm64

```sh
sudo dnf install -y git ca-certificates python3 python3-pip
python3 -m venv ~/.venvs/dirsearch
. ~/.venvs/dirsearch/bin/activate
python -m pip install --upgrade pip
python -m pip install "git+https://github.com/maurosoria/dirsearch.git"
dirsearch --version
```

## Native Rust Install from GitHub

Requirement: Python 3.14 or higher. The native engine is not built by the normal `pip install git+...` command; build it explicitly with `dirsearch-build-native` after installing dirsearch into the same virtual environment.

### Ubuntu and Debian, amd64 or arm64

```sh
sudo apt-get update
sudo apt-get install -y \
  git ca-certificates build-essential \
  python3.14 python3.14-venv python3.14-dev \
  cargo rustc

python3.14 -m venv ~/.venvs/dirsearch-native
. ~/.venvs/dirsearch-native/bin/activate
python -m pip install --upgrade pip
python -m pip install "git+https://github.com/maurosoria/dirsearch.git"
dirsearch-build-native

printf 'admin
login
' > /tmp/dirsearch-wordlist.txt
dirsearch -u https://example.com -w /tmp/dirsearch-wordlist.txt \
  --request-backend native --wordlist-backend native -q
```

If your Ubuntu or Debian release does not package Python 3.14 yet, install Python 3.14 from your platform's supported Python distribution or use a prebuilt `native-rust` release artifact instead.

### Red Hat and Fedora, amd64 or arm64

```sh
sudo dnf install -y \
  git ca-certificates gcc gcc-c++ make \
  python3.14 python3.14-devel \
  cargo rust

python3.14 -m venv ~/.venvs/dirsearch-native
. ~/.venvs/dirsearch-native/bin/activate
python -m pip install --upgrade pip
python -m pip install "git+https://github.com/maurosoria/dirsearch.git"
dirsearch-build-native

printf 'admin
login
' > /tmp/dirsearch-wordlist.txt
dirsearch -u https://example.com -w /tmp/dirsearch-wordlist.txt \
  --request-backend native --wordlist-backend native -q
```

If your Red Hat-compatible distribution does not package Python 3.14 yet, install Python 3.14 from your platform's supported Python distribution or use a prebuilt `native-rust` release artifact instead.

### macOS 26, Apple Silicon or Intel, with Homebrew

```sh
brew install python git rust
python3.14 -m venv ~/.venvs/dirsearch-native
. ~/.venvs/dirsearch-native/bin/activate
python -m pip install --upgrade pip
python -m pip install "git+https://github.com/maurosoria/dirsearch.git"
dirsearch-build-native
```

### Windows 10 and 11, x64

For no-compile installs, download the Windows x64 PyInstaller `.exe` or portable `.zip` from the Releases page. The portable archive bundles dependencies and can be preferable when antivirus software flags PyInstaller bootloaders.

Before building the native Rust backend, install Python 3.14 for x64, Git for Windows, Microsoft C++ Build Tools with the Desktop development with C++ workload and a Windows SDK, then install Rust through rustup. If `winget` is unavailable, download and run `rustup-init.exe` from rustup.rs.

```powershell
winget install --id Python.Python.3.14 -e
winget install --id Rustlang.Rustup -e
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install "git+https://github.com/maurosoria/dirsearch.git"
dirsearch-build-native
dirsearch --version
```

Open a new PowerShell session if `rustup`, `cargo`, or `dirsearch-build-native` is not found immediately after installation.

## Native Rust from a Source Checkout

Use this path when developing dirsearch or building release artifacts from a clone. Normal users can install from GitHub with pip and run `dirsearch-build-native` instead.

```sh
git clone https://github.com/maurosoria/dirsearch.git --depth 1
cd dirsearch
python3.14 -m venv .venv-native
. .venv-native/bin/activate
python -m pip install --upgrade pip
python -m pip install .
python scripts/build_native.py --out dist/native-wheels
python dirsearch.py -u https://example.com -w tests/static/wordlist.txt \
  --request-backend native --wordlist-backend native -q
```

Without the native engine, source installs keep the Python request backend and automatic Python wordlist fallback defaults.

Optional MySQL and PostgreSQL report dependencies are separate from the scanner runtime. Install them only when needed:

```sh
python -m pip install "dirsearch[db] @ git+https://github.com/maurosoria/dirsearch.git"
```

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
