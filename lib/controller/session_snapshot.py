"""Detached data at the boundary between a controller and session storage."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ..core.task_checkpoint import TaskCheckpoint
from ..core.task_spec import TaskSpec


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

    remaining_tasks preserves active-first input. The task_checkpoint describes
    continuation for its first entry; later entries start with reset dictionary
    cursors. Missing input is never reconstructed from the prepared origin.
    Before preparation the working slot can still be empty or retain the last
    origin, so it is not an independent identity/completion record.

    Options retain their normalized Python types until the store encodes them
    into the existing version-1 JSON schema, excluding the separately owned
    target queue. Replacing that transitional mapping
    with an aggregate configuration is a separate refactor. Secret-bearing data
    and terminal output are deliberately excluded from the generated repr.
    """

    run: RunCheckpoint = field(repr=False)
    task_checkpoint: TaskCheckpoint = field(repr=False)
    options: dict[str, Any] = field(repr=False)
    remaining_tasks: tuple[TaskSpec, ...] = field(default=(), repr=False)
    last_output: str = field(default="", repr=False)
    output_history: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        # One authoritative input queue. The version-1 options.urls field is
        # only a wire representation, reconstructed by SessionStore.save().
        if "urls" in self.options:
            raise ValueError("Session targets belong in remaining_tasks, not options")
        self.remaining_tasks = tuple(self.remaining_tasks)
        self.options, self.output_history = deepcopy(
            (self.options, self.output_history)
        )
