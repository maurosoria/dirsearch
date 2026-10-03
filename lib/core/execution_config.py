"""Immutable worker, pacing and stop policy for one run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from lib.core.request_backend import NATIVE_ASYNC_ERROR, REQUEST_BACKENDS


class ScanEngine(Enum):
    """One execution model, resolved from the existing CLI/session flags."""

    THREADED = "threaded"
    ASYNC = "async"
    NATIVE = "native"

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> ScanEngine:
        backend = values["request_backend"]
        if backend == "native":
            if values["async_mode"]:
                raise ValueError(NATIVE_ASYNC_ERROR)
            return cls.NATIVE
        if backend == "python":
            return cls.ASYNC if values["async_mode"] else cls.THREADED
        raise ValueError("--request-backend must be one of: " + ", ".join(REQUEST_BACKENDS))


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """Execution settings, not live workers, deadlines or cancellation state.

    Construct after CLI/session preparation and share across target fuzzers.
    RequestConfig separately owns transport concurrency and native pacing;
    both snapshots come from the same normalized inputs at the run boundary.
    Engine selection is resolved once after preparation, not recomputed by
    individual callbacks or when advancing to another target.
    """

    engine: ScanEngine = ScanEngine.THREADED
    concurrency: int = 25
    delay: float = 0.0
    max_time: float = 0.0
    target_max_time: float = 0.0
    skip_on_status: frozenset[int] = frozenset()
    exit_on_error: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.engine, ScanEngine):
            raise TypeError("engine must be a ScanEngine")
        object.__setattr__(self, "skip_on_status", frozenset(self.skip_on_status))

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> ExecutionConfig:
        """Freeze normalized options without consulting process-wide state."""
        return cls(
            engine=ScanEngine.from_options(values),
            concurrency=values["thread_count"],
            delay=values["delay"],
            max_time=values["max_time"],
            target_max_time=values["target_max_time"],
            skip_on_status=values["skip_on_status"],
            exit_on_error=values["exit_on_error"],
        )
