"""Detached data at the boundary between a controller and session storage."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, TypedDict


class ControllerProgress(TypedDict):
    start_time: float
    passed_urls: list[str]
    directories: list[str]
    jobs_processed: int
    errors: int
    consecutive_errors: int
    base_path: str
    url: str
    old_session: bool


class DictionaryProgress(TypedDict):
    items: list[str]
    index: int
    extra: list[str]
    extra_index: int


@dataclass(slots=True)
class SessionSnapshot:
    """Owned, data-only input to one checkpoint write.

    Mutable containers are copied together so serialization cannot borrow live
    controller state. This is detached data, not a deeply immutable object or a
    synchronization mechanism: callers capture progress at the existing paused
    save boundary. No requester, reporter or engine handle belongs here.

    Options retain their normalized Python types until the store encodes them
    into the existing version-1 JSON schema. Replacing that transitional mapping
    with an aggregate configuration is a separate refactor. Secret-bearing data
    and terminal output are deliberately excluded from the generated repr.
    """

    controller: ControllerProgress = field(repr=False)
    dictionary: DictionaryProgress = field(repr=False)
    options: dict[str, Any] = field(repr=False)
    last_output: str = field(default="", repr=False)
    output_history: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.controller, self.dictionary, self.options, self.output_history = deepcopy(
            (self.controller, self.dictionary, self.options, self.output_history)
        )
