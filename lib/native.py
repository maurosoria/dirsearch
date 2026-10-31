"""Dependency-free compatibility metadata shared with the optional extension."""

from collections.abc import Sequence


NATIVE_EXTENSION_VERSION = "0.2.27"
NATIVE_DIFFER_VERSIONS = frozenset({(3, 14), (3, 15)})


def supports_native_differ(version_info: Sequence[int]) -> bool:
    """Only replace Differ on Python minors covered by differential CI tests."""
    return tuple(version_info[:2]) in NATIVE_DIFFER_VERSIONS


def get_native_extension_version_error(native_module: object) -> str | None:
    # Optional third-party modules expose their version dynamically.
    installed_version = getattr(native_module, "__version__", None)
    if installed_version == NATIVE_EXTENSION_VERSION:
        return None
    found = installed_version if installed_version is not None else "unversioned"
    return (
        "Native Rust backend version is incompatible with this dirsearch build "
        f"(expected {NATIVE_EXTENSION_VERSION}, found {found}). "
        "Rebuild it with: dirsearch-build-native"
    )
