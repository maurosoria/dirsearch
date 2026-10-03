"""Immutable discovery policy for controller decisions and calibration profiles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DiscoveryConfig:
    """One run's discovery settings, detached from normalized CLI/session data.

    This contains policy, not the mutable directory queue, visited URLs or
    dictionary claims. Prefixes, suffixes and extensions describe calibration
    variants here; wordlist generation still has its own configuration boundary.
    """

    crawl: bool = False
    find_backup: bool = False
    recursive: bool = False
    deep_recursive: bool = False
    force_recursive: bool = False
    recursion_depth: int = 0
    recursion_status_codes: frozenset[int] = frozenset()
    subdirs: tuple[str, ...] = ()
    exclude_subdirs: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Preserve ordering, duplicates and empty root entries. Normalization
        # belongs to the existing parser, not this ownership-only snapshot.
        object.__setattr__(self, "recursion_status_codes", frozenset(self.recursion_status_codes))
        object.__setattr__(self, "subdirs", tuple(self.subdirs))
        object.__setattr__(self, "exclude_subdirs", tuple(self.exclude_subdirs))
        object.__setattr__(self, "prefixes", tuple(self.prefixes))
        object.__setattr__(self, "suffixes", tuple(self.suffixes))
        object.__setattr__(self, "extensions", tuple(self.extensions))

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> DiscoveryConfig:
        """Adapt normalized input after setup or restoration without globals."""
        return cls(
            crawl=values["crawl"],
            find_backup=values["find_backup"],
            recursive=values["recursive"],
            deep_recursive=values["deep_recursive"],
            force_recursive=values["force_recursive"],
            recursion_depth=values["recursion_depth"],
            recursion_status_codes=values["recursion_status_codes"],
            subdirs=values["subdirs"],
            exclude_subdirs=values["exclude_subdirs"],
            prefixes=values["prefixes"],
            suffixes=values["suffixes"],
            extensions=values["extensions"],
        )
