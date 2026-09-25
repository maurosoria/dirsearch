from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from lib.core.native_runtime import (
    MIN_NATIVE_PYTHON,
    format_python_version,
    get_native_python_version_error,
)


NATIVE_SOURCE_FILES = (
    "pyproject.toml",
    "Cargo.toml",
    "Cargo.lock",
    "src/lib.rs",
)


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def native_source_dir(root: Path | None = None) -> Path:
    return (root or package_root()) / "native"


def read_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')

    return values


def install_hint(os_release: dict[str, str] | None = None) -> str:
    release = os_release if os_release is not None else read_os_release()
    distro_ids = {
        release.get("ID", "").lower(),
        *release.get("ID_LIKE", "").lower().split(),
    }

    if distro_ids & {"ubuntu", "debian"}:
        return (
            "Ubuntu/Debian prerequisites: sudo apt-get install -y "
            "build-essential python3.14-dev cargo rustc"
        )
    if distro_ids & {"fedora", "rhel", "centos"}:
        return (
            "Fedora/Red Hat prerequisites: sudo dnf install -y "
            "gcc gcc-c++ make python3.14-devel cargo rust"
        )

    return (
        "Install Python 3.14 development headers, Rust 1.86 or newer, and a C compiler "
        "with your system package manager."
    )


def python_headers_available() -> bool:
    include_dir = sysconfig.get_config_var("INCLUDEPY")
    if not include_dir:
        return False

    return Path(include_dir, "Python.h").exists()


def pip_available() -> bool:
    return (
        subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def native_sources_available(source_dir: Path) -> bool:
    return all((source_dir / file_name).is_file() for file_name in NATIVE_SOURCE_FILES)


def get_prerequisite_errors(
    source_dir: Path | None = None,
    version_info: Sequence[int] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    has_pip: bool | None = None,
    has_python_headers: bool | None = None,
) -> list[str]:
    errors: list[str] = []

    if version_error := get_native_python_version_error(version_info):
        errors.append(version_error)

    source = source_dir or native_source_dir()
    if not native_sources_available(source):
        errors.append(
            "Native Rust sources are missing from this installation. "
            "Reinstall dirsearch from the latest package or GitHub source."
        )

    if has_pip is None:
        has_pip = pip_available()
    if not has_pip:
        errors.append(f"pip is not available for Python {format_python_version()}.")

    for command in ("cargo", "rustc"):
        if which(command) is None:
            errors.append(f"Required command not found: {command}")

    if not any(which(command) for command in ("cc", "gcc", "clang")):
        errors.append("Required C compiler not found: cc, gcc, or clang")

    if has_python_headers is None:
        has_python_headers = python_headers_available()
    if not has_python_headers:
        major, minor = MIN_NATIVE_PYTHON
        errors.append(
            f"Python development headers not found for Python {major}.{minor}."
        )

    return errors


def copy_native_sources(source_dir: Path, build_root: Path) -> Path:
    destination = build_root / "native"
    shutil.copytree(
        source_dir,
        destination,
        ignore=shutil.ignore_patterns("target", "__pycache__", "*.pyc"),
    )
    return destination


def run(command: list[str]) -> None:
    print("+ " + shlex.join(command), flush=True)
    subprocess.run(command, check=True)


def build_native_engine(source_dir: Path, force_reinstall: bool = True) -> None:
    with tempfile.TemporaryDirectory(prefix="dirsearch-native-build-") as temp_dir:
        build_source = copy_native_sources(source_dir, Path(temp_dir))
        command = [sys.executable, "-m", "pip", "install"]
        if force_reinstall:
            command.append("--force-reinstall")
        command.append(str(build_source))

        run(command)

    run([sys.executable, "-c", "import dirsearch_native"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and install the dirsearch native Rust engine"
    )
    parser.add_argument(
        "--no-force-reinstall",
        action="store_true",
        help="Do not pass --force-reinstall to pip",
    )
    args = parser.parse_args(argv)

    source_dir = native_source_dir()
    errors = get_prerequisite_errors(source_dir=source_dir)
    if errors:
        print("Cannot build dirsearch native Rust engine:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        print(install_hint(), file=sys.stderr)
        return 1

    try:
        build_native_engine(
            source_dir,
            force_reinstall=not args.no_force_reinstall,
        )
    except subprocess.CalledProcessError as error:
        return error.returncode
    except OSError as error:
        print(f"Native Rust engine build failed: {error}", file=sys.stderr)
        return 1

    print("Native Rust engine installed: dirsearch_native", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
