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

from socket import getaddrinfo
from typing import Any

_dns_cache: dict[tuple[str, int], list[Any]] = {}


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
