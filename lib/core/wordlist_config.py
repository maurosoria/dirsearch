"""Immutable policy for wordlist generation and dynamic-path validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WordlistConfig:
    """One dictionary's policy, independent of CLI globals and queue state.

    Backend selection and corpus ownership are separate: the native request
    engine prefers a Rust-owned corpus, but explicitly Python generation and
    named templates still use the existing Python representation.
    """

    backend: str = "auto"
    native_corpus: bool = False
    extensions: tuple[str, ...] = ()
    exclude_extensions: tuple[str, ...] = ()
    force_extensions: bool = False
    overwrite_extensions: bool = False
    prefixes: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    lowercase: bool = False
    uppercase: bool = False
    capitalization: bool = False
    max_size: int = 500000

    def __post_init__(self) -> None:
        # Detach mutable inputs without changing parser normalization, ordering
        # or duplicates. Generation retains its existing deduplication rules.
        object.__setattr__(self, "extensions", tuple(self.extensions))
        object.__setattr__(self, "exclude_extensions", tuple(self.exclude_extensions))
        object.__setattr__(self, "prefixes", tuple(self.prefixes))
        object.__setattr__(self, "suffixes", tuple(self.suffixes))

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> WordlistConfig:
        """Adapt normalized CLI or restored session options at the entrypoint."""
        return cls(
            backend=values["wordlist_backend"],
            native_corpus=values["request_backend"] == "native",
            extensions=values["extensions"],
            exclude_extensions=values["exclude_extensions"],
            force_extensions=values["force_extensions"],
            overwrite_extensions=values["overwrite_extensions"],
            prefixes=values["prefixes"],
            suffixes=values["suffixes"],
            lowercase=values["lowercase"],
            uppercase=values["uppercase"],
            capitalization=values["capitalization"],
            max_size=values["wordlist_max_size"],
        )
