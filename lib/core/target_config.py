"""Immutable target preparation policy for one controller run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TargetConfig:
    """Run-wide hints, not the current target or its resolved connection state.

    ``connect_host`` is the explicit --ip override, not a DNS lookup result.
    ``proxy_configured`` preserves the existing proxy/Tor scheme-detection guard;
    it is not a transport routing decision and does not inspect the environment.
    Proxy URLs and credentials remain in RequestConfig, not this policy.
    """

    default_scheme: str | None = None
    connect_host: str | None = None
    proxy_configured: bool = False

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> TargetConfig:
        """Copy normalized CLI/session input without reading global options."""
        return cls(
            default_scheme=values["scheme"],
            connect_host=values["ip"],
            proxy_configured=bool(values["proxies"] or values["tor"]),
        )
