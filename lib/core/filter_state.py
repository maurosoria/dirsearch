"""Mutable filtering observations owned by one target's fuzzer."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.core.scanner import BaseScanner


@dataclass(slots=True)
class FilterState:
    """Never share this state between targets, even with the same FilterConfig.

    Counters span directories within a target, as before. Their check/increment
    operations use one lock in every engine, without I/O or awaits inside its
    short critical sections. Scanner profiles are prepared before
    response workers start and stay within this target's calibration group.
    """

    filter_fingerprints: dict[int, int] = field(default_factory=dict)
    similar_fingerprints: dict[tuple, int] = field(default_factory=dict)
    auto_calibrated_fingerprints: set[tuple] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    scanners: dict[str, dict[str, BaseScanner]] = field(default_factory=lambda: {
        "default": {}, "prefixes": {}, "suffixes": {},
    })
