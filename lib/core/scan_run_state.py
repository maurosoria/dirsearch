"""Target ordering and cumulative progress of one sequential controller run."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _TargetPosition:
    """Publish input, pending cursor and active target in one transition."""

    targets: tuple[str, ...] = ()
    next_index: int = 0
    active_target: str | None = None


class ScanRunState:
    """Separate pending input from the target currently being processed.

    The controller owns all transitions; this is not a thread-safe work queue.
    Only one target may be active, regardless of the request engine's worker
    count. URLs are copied without parsing, sorting or deduplication.
    """

    def __init__(self, targets: Iterable[str] = ()) -> None:
        self._position = _TargetPosition(tuple(targets))
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
        if self.active_target is not None:
            raise RuntimeError("Cannot prepare targets while a target is active")
        self._position = _TargetPosition(tuple(targets))

    @property
    def active_target(self) -> str | None:
        return self._position.active_target

    @property
    def pending_count(self) -> int:
        """Targets not yet activated, excluding the current target."""
        position = self._position
        return len(position.targets) - position.next_index

    def activate_next(self) -> str | None:
        """Activate the oldest pending target, or return None when exhausted.

        An unfinished active target must never be silently replaced, even when
        there are no pending targets left.
        """
        position = self._position
        if position.active_target is not None:
            raise RuntimeError("Finish the active target before activating another")
        if position.next_index == len(position.targets):
            return None
        target = position.targets[position.next_index]
        # A signal handler can save a checkpoint between Python instructions.
        # Publish both changes once: pop-then-assign could lose a target, while
        # assign-then-pop could duplicate it in a reentrant snapshot.
        self._position = _TargetPosition(position.targets, position.next_index + 1, target)
        return target

    def finish_active(self) -> None:
        """End the current attempt, including handled failures and skipped targets.

        This does not record success. A quit-and-save checkpoint is taken before
        the controller unwinds the active attempt.
        """
        position = self._position
        if position.active_target is None:
            raise RuntimeError("There is no active target to finish")
        self._position = _TargetPosition(position.targets, position.next_index)

    def snapshot_targets(self) -> list[str]:
        """Copy remaining work in the session format: active first, then pending.

        Including the active target lets resume retry its unfinished dictionary
        entries. Neither saving nor mutating the returned list consumes work.
        """
        position = self._position
        targets = list(position.targets[position.next_index:])
        if position.active_target is not None:
            targets.insert(0, position.active_target)
        return targets
