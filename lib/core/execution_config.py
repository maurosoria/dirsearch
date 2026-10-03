"""Immutable worker, pacing and stop policy for one run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """Execution settings, not live workers, deadlines or cancellation state.

    Construct after CLI/session preparation and share across target fuzzers.
    RequestConfig separately owns transport concurrency and native pacing;
    both snapshots come from the same normalized inputs at the run boundary.
    """

    concurrency: int = 25
    delay: float = 0.0
    max_time: float = 0.0
    target_max_time: float = 0.0
    skip_on_status: frozenset[int] = frozenset()
    exit_on_error: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "skip_on_status", frozenset(self.skip_on_status))

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> ExecutionConfig:
        """Freeze normalized options without consulting process-wide state."""
        return cls(
            concurrency=values["thread_count"],
            delay=values["delay"],
            max_time=values["max_time"],
            target_max_time=values["target_max_time"],
            skip_on_status=values["skip_on_status"],
            exit_on_error=values["exit_on_error"],
        )
