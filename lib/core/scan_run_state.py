"""Target ordering and cumulative progress of one sequential controller run."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .task_spec import TaskSpec


@dataclass(frozen=True, slots=True)
class _TaskPosition:
    """Publish input, pending cursor and active target in one transition."""

    tasks: tuple[TaskSpec, ...] = ()
    next_index: int = 0
    active_task: TaskSpec | None = None


class ScanRunState:
    """Separate pending input from the target currently being processed.

    The controller owns all transitions; this is not a thread-safe work queue.
    Only one target may be active, regardless of the request engine's worker
    count. URLs are copied without parsing, sorting or deduplication.
    """

    def __init__(self, targets: Iterable[str] = ()) -> None:
        self._position = _TaskPosition(tuple(TaskSpec(target) for target in targets))
        # These values retain their historical run-wide scope. In particular,
        # passed_urls records scheduled directory URLs, not successful targets;
        # duplicate targets must not reset it or the completed-job/error totals.
        self.passed_urls: set[str] = set()
        self.jobs_processed = 0
        self.errors = 0
        self.consecutive_errors = 0
        # Existing session-presentation flag, consumed after a directory job.
        # It can survive a handled target exit before a job starts.
        self.old_session = False

    def prepare_targets(self, targets: Iterable[str]) -> None:
        """Set input before workers/signals start, preserving restored totals.

        This is controller preparation, not a live queue-editing API. A target
        must not be replaced while active. Materialize input before mutating the
        queue so a failed iterable leaves both ordering and progress untouched.
        """
        if self.active_task is not None:
            raise RuntimeError("Cannot prepare targets while a target is active")
        self._position = _TaskPosition(tuple(TaskSpec(target) for target in targets))

    @property
    def active_task(self) -> TaskSpec | None:
        return self._position.active_task

    @property
    def pending_count(self) -> int:
        """Targets not yet activated, excluding the current target."""
        position = self._position
        return len(position.tasks) - position.next_index

    def activate_next(self) -> TaskSpec | None:
        """Activate the oldest pending target, or return None when exhausted.

        An unfinished active target must never be silently replaced, even when
        there are no pending targets left.
        """
        position = self._position
        if position.active_task is not None:
            raise RuntimeError("Finish the active target before activating another")
        if position.next_index == len(position.tasks):
            return None
        task = position.tasks[position.next_index]
        # A signal handler can save a checkpoint between Python instructions.
        # Publish both changes once: pop-then-assign could lose a target, while
        # assign-then-pop could duplicate it in a reentrant snapshot.
        self._position = _TaskPosition(position.tasks, position.next_index + 1, task)
        return task

    def finish_active(self) -> None:
        """End the current attempt, including handled failures and skipped targets.

        This does not record success. A quit-and-save checkpoint is taken before
        the controller unwinds the active attempt.
        """
        position = self._position
        if position.active_task is None:
            raise RuntimeError("There is no active target to finish")
        self._position = _TaskPosition(position.tasks, position.next_index)

    def snapshot_tasks(self) -> tuple[TaskSpec, ...]:
        """Capture immutable remaining input: active first, then pending.

        Including the active target lets resume retry its unfinished dictionary
        entries. Storage, not this queue, converts descriptors to wire fields.
        """
        position = self._position
        tasks = position.tasks[position.next_index:]
        if position.active_task is not None:
            tasks = (position.active_task, *tasks)
        return tasks
