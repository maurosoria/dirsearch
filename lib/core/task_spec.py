"""Immutable target input, separate from prepared state and live resources."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """One original target entry in the sequential run's input order.

    Preserve spelling, query, credentials and even invalid/empty input until
    the existing target-preparation boundary validates it. A prepared origin
    cannot reconstruct this input. Exclude it from repr because it may contain
    secrets.

    Equal specs describe equal input, not the same execution attempt: duplicate
    occurrences remain distinct queue positions. This is not a globally unique
    task ID, a scheduler message or a runnable context. Policies are still
    run-wide, and no transport, worker or mutable progress belongs here.
    """

    target: str = field(repr=False)
