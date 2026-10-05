"""Target progress owned by one sequential controller run."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _TargetPosition:
    """Publish the pending cursor and active target together at each transition."""

    next_index: int = 0
    active_target: str | None = None


class ScanRunState:
    """Separate pending input from the target currently being processed.

    The controller owns all transitions; this is not a thread-safe work queue.
    Only one target may be active, regardless of the request engine's worker
    count. URLs are copied without parsing, sorting or deduplication.
    """

    def __init__(self, targets: Iterable[str] = ()) -> None:
        self._targets = tuple(targets)
        self._position = _TargetPosition()

    @property
    def active_target(self) -> str | None:
        return self._position.active_target

    @property
    def pending_count(self) -> int:
        """Targets not yet activated, excluding the current target."""
        return len(self._targets) - self._position.next_index

    def activate_next(self) -> str | None:
        """Activate the oldest pending target, or return None when exhausted.

        An unfinished active target must never be silently replaced, even when
        there are no pending targets left.
        """
        position = self._position
        if position.active_target is not None:
            raise RuntimeError("Finish the active target before activating another")
        if position.next_index == len(self._targets):
            return None
        target = self._targets[position.next_index]
        # A signal handler can save a checkpoint between Python instructions.
        # Publish both changes once: pop-then-assign could lose a target, while
        # assign-then-pop could duplicate it in a reentrant snapshot.
        self._position = _TargetPosition(position.next_index + 1, target)
        return target

    def finish_active(self) -> None:
        """End the current attempt, including handled failures and skipped targets.

        This does not record success. A quit-and-save checkpoint is taken before
        the controller unwinds the active attempt.
        """
        position = self._position
        if position.active_target is None:
            raise RuntimeError("There is no active target to finish")
        self._position = _TargetPosition(position.next_index)

    def snapshot_targets(self) -> list[str]:
        """Copy remaining work in the session format: active first, then pending.

        Including the active target lets resume retry its unfinished dictionary
        entries. Neither saving nor mutating the returned list consumes work.
        """
        position = self._position
        targets = list(self._targets[position.next_index:])
        if position.active_target is not None:
            targets.insert(0, position.active_target)
        return targets
