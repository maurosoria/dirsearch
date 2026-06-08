# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

from __future__ import annotations

from dataclasses import dataclass
from socket import getaddrinfo
from typing import Any

from lib.core.data import options

try:
    import dns.exception as dns_exception
    import dns.resolver as dns_resolver
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    dns_exception = None
    dns_resolver = None

_dns_cache: dict[tuple[str, int], list[Any]] = {}
_resolution_cache: dict[tuple[str, float, str | None], "DNSResolution"] = {}


@dataclass(frozen=True)
class DNSResolution:
    cnames: tuple[str, ...] = ()
    ips: tuple[str, ...] = ()


def cache_dns(domain: str, port: int, addr: str) -> None:
    _dns_cache[domain, port] = getaddrinfo(addr, port)


def cached_getaddrinfo(*args: Any, **kwargs: int) -> list[Any]:
    """
    Replacement for socket.getaddrinfo, they are the same but this function
    does cache the answer to improve the performance
    """

    host, port = args[:2]
    if (host, port) not in _dns_cache:
        _dns_cache[host, port] = getaddrinfo(*args, **kwargs)

    return _dns_cache[host, port]


def resolve_host_records(
    host: str | None,
    *,
    timeout: float | None = None,
    explicit_ip: str | None = None,
) -> DNSResolution:
    if explicit_ip:
        return DNSResolution(ips=(str(explicit_ip),))
    if not host:
        return DNSResolution()

    timeout = _dns_timeout(timeout)
    normalized_host = _normalize_hostname(host)
    cache_key = (normalized_host, timeout, explicit_ip)
    if cache_key in _resolution_cache:
        return _resolution_cache[cache_key]

    try:
        if dns_resolver is not None:
            resolution = _resolve_with_dnspython(normalized_host, timeout)
        else:
            resolution = DNSResolution()
    except Exception:
        resolution = DNSResolution()

    _resolution_cache[cache_key] = resolution
    return resolution


def _resolve_with_dnspython(host: str, timeout: float) -> DNSResolution:
    resolver = dns_resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout

    cnames: list[str] = []
    current = host
    for _ in range(8):
        try:
            answers = resolver.resolve(current, "CNAME", raise_on_no_answer=False)
        except dns_exception.DNSException:
            break

        targets = [_normalize_hostname(answer.target.to_text()) for answer in answers]
        targets = [target for target in targets if target]
        if not targets:
            break
        target = targets[0]
        if target in cnames:
            break
        cnames.append(target)
        current = target

    ips: list[str] = []
    for record_type in ("A", "AAAA"):
        try:
            answers = resolver.resolve(host, record_type, raise_on_no_answer=False)
        except dns_exception.DNSException:
            continue

        canonical = _normalize_hostname(str(getattr(answers, "canonical_name", "")))
        if canonical and canonical != host and canonical not in cnames:
            cnames.append(canonical)
        for answer in answers:
            value = str(answer).strip()
            if value:
                ips.append(value)

    return DNSResolution(
        cnames=tuple(dict.fromkeys(cnames)),
        ips=tuple(dict.fromkeys(ips)),
    )


def _resolve_with_socket(host: str) -> DNSResolution:
    ips = []
    for result in getaddrinfo(host, None):
        sockaddr = result[4]
        if sockaddr:
            ips.append(str(sockaddr[0]))
    return DNSResolution(ips=tuple(dict.fromkeys(ips)))


def _dns_timeout(timeout: float | None) -> float:
    if timeout is None:
        timeout = options.get("timeout", 5)
    try:
        return max(0.1, min(float(timeout), 5.0))
    except (TypeError, ValueError):
        return 5.0


def _normalize_hostname(hostname: str) -> str:
    return str(hostname).strip().lower().rstrip(".")
