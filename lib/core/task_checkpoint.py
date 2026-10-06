"""Engine-independent continuation data, never live execution resources."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DictionaryCheckpoint:
    """An owned corpus and its resumable cursors at a paused save boundary.

    The dictionary's existing capture operation folds outstanding claims into
    this representation. Keeping the full corpus is necessary: the current job
    resumes at these cursors, but later jobs reset and reuse the complete input.
    Neither a Python dictionary object nor a native wordlist handle is retained.
    """

    items: tuple[str, ...] = field(repr=False)
    index: int
    extra: tuple[str, ...] = field(default=(), repr=False)
    extra_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "extra", tuple(self.extra))

    def to_state(self) -> tuple[list[str], int, list[str], int]:
        """Give each restored dictionary its own mutable containers."""
        return list(self.items), self.index, list(self.extra), self.extra_index


@dataclass(frozen=True, slots=True)
class TaskCheckpoint:
    """Continuation of the sequential controller's current target slot.

    The first directory is the unfinished job; dictionary progress belongs to
    it. Later directories start with reset cursors. Before target preparation,
    the slot may be empty; an empty queue is not a successful-completion marker.

    The enclosing session's first remaining TaskSpec retains original target
    input. Its prepared origin here is not a replacement for that input. This
    is not a runnable task descriptor: ordering, run-wide deduplication, counters
    and prepared options remain in the enclosing session.
    It contains no engine choice, requester, reporter, lock or worker, and is
    unrelated to Rust's internal ScanTask. Capture still requires paused workers.
    """

    dictionary: DictionaryCheckpoint = field(repr=False)
    url: str = field(default="", repr=False)
    base_path: str = field(default="", repr=False)
    directories: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "directories", tuple(self.directories))
