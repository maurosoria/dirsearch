"""Immutable presentation metadata captured at an invocation boundary."""

from __future__ import annotations

import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from lib.utils.command import redact_command


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """A redacted command and local-time label, not execution progress.

    Capture once and share with the run's reports and session path formatter.
    The numeric start time used for deadlines and checkpoint continuation is
    separate: resuming work must not replace it with this invocation's label.
    Direct constructors expect an already redacted command; prefer ``capture``
    when adapting argv. Raw arguments are never retained in this value.
    """

    command: str = field(repr=False)
    start_time: str

    @classmethod
    def capture(cls, arguments: Sequence[str] | None = None) -> RunMetadata:
        """Read ambient argv/clock only when a caller starts a new invocation.

        An explicit empty argument sequence is meaningful and stays empty.
        Standalone report APIs may capture their own metadata; a controller
        passes one shared value so lazy report creation cannot change it.
        """
        return cls(
            command=redact_command(sys.argv if arguments is None else arguments),
            start_time=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
