"""Immutable report destinations and persistence policy for one run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ReportConfig:
    """Report settings, not open files, connections or pending writes.

    Build after CLI preparation or session restoration. Destination templates
    remain unexpanded until the manager has a target URL. Database URLs may
    contain credentials and are deliberately excluded from ``repr``.
    """

    formats: tuple[str, ...] = ()
    output_file: str | None = None
    output_table: str | None = None
    mysql_url: str | None = field(default=None, repr=False)
    postgres_url: str | None = field(default=None, repr=False)
    sqlite_commit_batch_size: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "formats", tuple(self.formats))

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> ReportConfig:
        """Snapshot normalized CLI/session input without reading global state."""
        return cls(
            formats=values["output_formats"] or (),
            output_file=values["output_file"],
            output_table=values["output_table"],
            mysql_url=values["mysql_url"],
            postgres_url=values["postgres_url"],
            sqlite_commit_batch_size=values["sqlite_commit_batch_size"],
        )
