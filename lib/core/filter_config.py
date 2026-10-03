"""Immutable matching policy shared by Python filtering and the native adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from lib.core.filters import NumericRange, TimeFilter


@dataclass(frozen=True, slots=True)
class FilterConfig:
    """One run's policy, snapshotted after CLI parsing or session restoration.

    Blacklist entries are immutable data, not live Dictionary iterators. Counts,
    locks and learned wildcard profiles belong to a target's FilterState instead.
    No field is read back from global options after construction.
    """

    include_status_codes: frozenset[int] = frozenset()
    exclude_status_codes: frozenset[int] = frozenset()
    exclude_sizes: frozenset[int] = frozenset()
    minimum_response_size: int = 0
    maximum_response_size: int = 0
    exclude_texts: tuple[str, ...] = ()
    exclude_regex: str | None = None
    exclude_redirect: str | None = None
    exclude_response: str | None = None
    filter_threshold: int = 0
    auto_calibration: bool = False
    matcher_mode: str = "or"
    filter_mode: str = "or"
    match_status_codes: frozenset[int] = frozenset()
    filter_status_codes: frozenset[int] = frozenset()
    match_sizes: tuple[NumericRange, ...] = ()
    filter_sizes: tuple[NumericRange, ...] = ()
    match_words: tuple[NumericRange, ...] = ()
    filter_words: tuple[NumericRange, ...] = ()
    match_lines: tuple[NumericRange, ...] = ()
    filter_lines: tuple[NumericRange, ...] = ()
    match_regex: str | None = None
    filter_regex: str | None = None
    match_headers: tuple[str, ...] = ()
    filter_headers: tuple[str, ...] = ()
    match_header_regex: str | None = None
    filter_header_regex: str | None = None
    match_time: tuple[TimeFilter, ...] = ()
    filter_time: tuple[TimeFilter, ...] = ()
    blacklists: Mapping[int, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Also detach mutable inputs supplied by direct API callers. Convert the
        # nested pairs, not just the outer sequence (sessions decode JSON lists).
        object.__setattr__(self, "include_status_codes", frozenset(self.include_status_codes))
        object.__setattr__(self, "exclude_status_codes", frozenset(self.exclude_status_codes))
        object.__setattr__(self, "exclude_sizes", frozenset(self.exclude_sizes))
        object.__setattr__(self, "exclude_texts", tuple(self.exclude_texts))
        object.__setattr__(self, "match_status_codes", frozenset(self.match_status_codes))
        object.__setattr__(self, "filter_status_codes", frozenset(self.filter_status_codes))
        object.__setattr__(self, "match_sizes", tuple((a, b) for a, b in self.match_sizes))
        object.__setattr__(self, "filter_sizes", tuple((a, b) for a, b in self.filter_sizes))
        object.__setattr__(self, "match_words", tuple((a, b) for a, b in self.match_words))
        object.__setattr__(self, "filter_words", tuple((a, b) for a, b in self.filter_words))
        object.__setattr__(self, "match_lines", tuple((a, b) for a, b in self.match_lines))
        object.__setattr__(self, "filter_lines", tuple((a, b) for a, b in self.filter_lines))
        object.__setattr__(self, "match_headers", tuple(self.match_headers))
        object.__setattr__(self, "filter_headers", tuple(self.filter_headers))
        object.__setattr__(self, "match_time", tuple((op, n) for op, n in self.match_time))
        object.__setattr__(self, "filter_time", tuple((op, n) for op, n in self.filter_time))
        object.__setattr__(self, "blacklists", MappingProxyType({
            status: tuple(paths) for status, paths in self.blacklists.items()
        }))

    @classmethod
    def from_options(
        cls, values: Mapping[str, Any], *,
        blacklists: Mapping[int, Iterable[str]] | None = None,
    ) -> FilterConfig:
        """Adapt normalized CLI/session data once, at the controller boundary."""
        return cls(
            include_status_codes=values["include_status_codes"],
            exclude_status_codes=values["exclude_status_codes"],
            exclude_sizes=values["exclude_sizes"],
            minimum_response_size=values["minimum_response_size"],
            maximum_response_size=values["maximum_response_size"],
            exclude_texts=values["exclude_texts"] or (),
            exclude_regex=values["exclude_regex"],
            exclude_redirect=values["exclude_redirect"],
            exclude_response=values["exclude_response"],
            filter_threshold=values["filter_threshold"],
            auto_calibration=values["auto_calibration"],
            matcher_mode=values["matcher_mode"],
            filter_mode=values["filter_mode"],
            match_status_codes=values["match_status_codes"],
            filter_status_codes=values["filter_status_codes"],
            match_sizes=values["match_sizes"],
            filter_sizes=values["filter_sizes"],
            match_words=values["match_words"],
            filter_words=values["filter_words"],
            match_lines=values["match_lines"],
            filter_lines=values["filter_lines"],
            match_regex=values["match_regex"],
            filter_regex=values["filter_regex"],
            match_headers=values["match_headers"],
            filter_headers=values["filter_headers"],
            match_header_regex=values["match_header_regex"],
            filter_header_regex=values["filter_header_regex"],
            match_time=values["match_time"],
            filter_time=values["filter_time"],
            blacklists=blacklists if blacklists is not None else {},
        )

    def native_options(self) -> dict[str, Any]:
        """Translate the existing Rust-supported subset at lazy engine creation.

        Python still applies the remaining policy and target-local calibration.
        Unfiltered calibration/replay requests deliberately bypass this adapter.
        """
        return {
            "include_status_codes": sorted(self.include_status_codes),
            "exclude_status_codes": sorted(self.exclude_status_codes),
            "minimum_response_size": self.minimum_response_size,
            "maximum_response_size": self.maximum_response_size,
            "matcher_mode": self.matcher_mode,
            "filter_mode": self.filter_mode,
            "match_status_codes": sorted(self.match_status_codes),
            "filter_status_codes": sorted(self.filter_status_codes),
            "match_sizes": list(self.match_sizes),
            "filter_sizes": list(self.filter_sizes),
            "match_words": list(self.match_words),
            "filter_words": list(self.filter_words),
            "match_lines": list(self.match_lines),
            "filter_lines": list(self.filter_lines),
            "match_regex": self.match_regex,
            "filter_regex": self.filter_regex,
            "match_headers": list(self.match_headers),
            "filter_headers": list(self.filter_headers),
            "match_header_regex": self.match_header_regex,
            "filter_header_regex": self.filter_header_regex,
            "match_time": list(self.match_time),
            "filter_time": list(self.filter_time),
        }
