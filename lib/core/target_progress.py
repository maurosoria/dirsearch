"""Mutable working progress of the sequential controller's current target."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TargetProgress:
    """Separate target-local work from run-wide counters and input policy.

    ``url`` is the prepared origin, while ``base_path`` is its starting path.
    ``directories`` preserves the existing ordered queue: its first entry is
    the current job and remains present until that job's workers have drained.

    This is the current controller's working slot, not a schedulable task or a
    thread-safe queue. Target preparation updates it and normal completion or
    handled target errors drain/clear its directories. Run-wide deduplication,
    error streaks and totals deliberately do not belong here.
    """

    url: str = ""
    base_path: str = ""
    directories: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.directories = list(self.directories)
