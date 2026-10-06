"""Detached data at the boundary between a controller and session storage."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ..core.task_checkpoint import TaskCheckpoint


@dataclass(frozen=True, slots=True)
class RunCheckpoint:
    """Cumulative values whose lifetime extends beyond the current target.

    passed_urls contains scheduled directory URLs, not completed target IDs.
    The resume-presentation flag retains its existing run-wide lifetime.
    """

    start_time: float
    passed_urls: tuple[str, ...] = field(default=(), repr=False)
    jobs_processed: int = 0
    errors: int = 0
    consecutive_errors: int = 0
    old_session: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "passed_urls", tuple(self.passed_urls))


@dataclass(slots=True)
class SessionSnapshot:
    """Owned, data-only boundary for both session loading and saving.

    Run and task checkpoints are immutable values; options and output history
    are copied together. The whole snapshot is detached, not deeply immutable
    or a synchronization mechanism: callers capture progress at the existing
    paused save boundary. No requester, reporter or engine handle belongs here.

    Options retain their normalized Python types until the store encodes them
    into the existing version-1 JSON schema. Replacing that transitional mapping
    with an aggregate configuration is a separate refactor. Secret-bearing data
    and terminal output are deliberately excluded from the generated repr.
    """

    run: RunCheckpoint = field(repr=False)
    task: TaskCheckpoint = field(repr=False)
    options: dict[str, Any] = field(repr=False)
    last_output: str = field(default="", repr=False)
    output_history: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.options, self.output_history = deepcopy(
            (self.options, self.output_history)
        )
