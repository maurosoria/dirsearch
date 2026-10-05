"""Immutable presentation policy, independent of process-wide option storage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TerminalConfig:
    """One terminal's output mode and configuration summary.

    Build after raw-request parsing or session restoration so the summary uses
    the effective settings. The stream and output history are live resources,
    not configuration, and are owned separately by the terminal/controller.
    """

    color: bool = True
    quiet: bool = False
    disabled: bool = False
    verbose: bool = False
    extensions: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    method: str = "GET"
    concurrency: int = 25

    def __post_init__(self) -> None:
        object.__setattr__(self, "extensions", tuple(self.extensions))
        object.__setattr__(self, "prefixes", tuple(self.prefixes))
        object.__setattr__(self, "suffixes", tuple(self.suffixes))

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> TerminalConfig:
        """Adapt normalized settings without importing global options."""
        return cls(
            color=values["color"], quiet=values["quiet"],
            disabled=values["disable_cli"], verbose=values["verbose"],
            extensions=values["extensions"], prefixes=values["prefixes"],
            suffixes=values["suffixes"], method=values["http_method"],
            concurrency=values["thread_count"],
        )
