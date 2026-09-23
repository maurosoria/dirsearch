from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence


MIN_NATIVE_PYTHON = (3, 14)
NATIVE_EXTENSION_VERSION = "0.2.7"


def format_python_version(version_info: Sequence[int] | None = None) -> str:
    version = version_info or sys.version_info
    return ".".join(str(part) for part in version[:3])


def get_native_python_version_error(
    version_info: Sequence[int] | None = None,
) -> str | None:
    version = version_info or sys.version_info
    if tuple(version[:2]) >= MIN_NATIVE_PYTHON:
        return None

    return (
        "Native Rust backend requires Python 3.14 or newer "
        f"(current: Python {format_python_version(version)}). "
        "Create a Python 3.14 environment, install dirsearch there, "
        "then run: dirsearch-build-native"
    )


def is_native_backend_available() -> bool:
    return importlib.util.find_spec("dirsearch_native") is not None


def get_native_backend_install_error(
    version_info: Sequence[int] | None = None,
) -> str:
    version_error = get_native_python_version_error(version_info)
    if version_error:
        return version_error

    return (
        "Native Rust backend is not installed in this Python environment. "
        "Install dirsearch, then compile the native engine with: "
        "dirsearch-build-native. "
        "The build requires Python 3.14 development headers, Rust/Cargo, "
        "and a C compiler."
    )


def get_native_extension_version_error(native_module: object) -> str | None:
    installed_version = getattr(native_module, "__version__", None)
    if installed_version == NATIVE_EXTENSION_VERSION:
        return None

    found = installed_version if installed_version is not None else "unversioned"
    return (
        "Native Rust backend version is incompatible with this dirsearch build "
        f"(expected {NATIVE_EXTENSION_VERSION}, found {found}). "
        "Rebuild it with: dirsearch-build-native"
    )


def get_native_runtime_error(
    request_backend: str = "python",
    wordlist_backend: str = "auto",
    version_info: Sequence[int] | None = None,
) -> str | None:
    if request_backend != "native" and wordlist_backend != "native":
        return None

    version_error = get_native_python_version_error(version_info)
    if version_error:
        return version_error

    if not is_native_backend_available():
        return get_native_backend_install_error(version_info)

    return None
