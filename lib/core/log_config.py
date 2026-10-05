"""Immutable logging policy; the controller owns the corresponding resource."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class LogConfig:
    """Snapshot after input preparation, before attaching any log consumer.

    Credentials are used only for redaction and are excluded from repr. Changing
    another invocation's options must never change an existing log's policy.
    """

    file_path: str | None = None
    max_bytes: int = 0
    proxy_auth: str | None = field(default=None, repr=False)

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> LogConfig:
        return cls(
            file_path=values["log_file"], max_bytes=values["log_file_size"],
            proxy_auth=values["proxy_auth"],
        )
