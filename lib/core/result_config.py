"""Immutable policy for presenting, capturing and replaying matched results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ResultConfig:
    """One run's result destinations, not open stores or callback progress.

    Snapshot after raw-input preparation or session restoration. Requesters need
    only the derived full-body flag; paths and replay selection stay with the
    controller. A replay proxy may contain credentials, so omit it from repr.
    """

    response_directory: str | None = None
    response_jsonl_file: str | None = None
    full_url: bool = False
    replay_proxy: str | None = field(default=None, repr=False)

    @property
    def capture_full_body(self) -> bool:
        """Either response destination requires preserving the full body."""
        return bool(self.response_directory or self.response_jsonl_file)

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> ResultConfig:
        return cls(
            response_directory=values["save_response"],
            response_jsonl_file=values["save_response_jsonl"],
            full_url=values["full_url"],
            replay_proxy=values["replay_proxy"],
        )
