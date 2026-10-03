"""Immutable request policy shared by the Python and native transports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RequestConfig:
    """One run's transport settings, detached from CLI/session option storage.

    Construct this after raw-request parsing or session restoration. Target URL,
    query, cookies, IP overrides and target authentication remain requester-owned
    state; they do not change this configured baseline. Replay and calibration
    share the same snapshot. Secret-bearing fields are omitted from ``repr``.
    """

    method: str = "GET"
    body: str | bytes | None = field(default=None, repr=False)
    headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    auth_type: str | None = None
    auth: str | None = field(default=None, repr=False)
    proxies: tuple[str, ...] = field(default=(), repr=False)
    proxy_auth: str | None = field(default=None, repr=False)
    cert_file: str | None = None
    key_file: str | None = field(default=None, repr=False)
    network_interface: str | None = None
    random_agents: bool = False
    follow_redirects: bool = False
    concurrency: int = 25
    timeout: float = 10
    max_retries: int = 1
    max_rate: int = 0
    delay: float = 0.0
    capture_full_body: bool = False

    def __post_init__(self) -> None:
        # Detach even when a caller supplies lists or a mutable byte buffer.
        # Keep str bodies as str: each transport retains its existing encoding.
        object.__setattr__(self, "headers", tuple((k, v) for k, v in self.headers))
        object.__setattr__(self, "proxies", tuple(self.proxies))
        if self.body is not None and not isinstance(self.body, str):
            object.__setattr__(self, "body", bytes(self.body))

    @classmethod
    def from_options(cls, values: Mapping[str, Any]) -> RequestConfig:
        """Adapt normalized CLI/session options without reading global state."""
        return cls(
            method=values["http_method"],
            body=values["data"],
            headers=tuple(values["headers"].items()),
            auth_type=values["auth_type"],
            auth=values["auth"],
            proxies=tuple(values["proxies"]),
            proxy_auth=values["proxy_auth"],
            cert_file=values["cert_file"],
            key_file=values["key_file"],
            network_interface=values["network_interface"],
            random_agents=values["random_agents"],
            follow_redirects=values["follow_redirects"],
            concurrency=values["thread_count"],
            timeout=values["timeout"],
            max_retries=values["max_retries"],
            max_rate=values["max_rate"],
            delay=values["delay"],
            capture_full_body=bool(
                values["save_response"] or values["save_response_jsonl"]
            ),
        )
