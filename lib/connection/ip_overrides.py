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


class IPOverrides:
    """Requester-owned connection IPs configured by the --ip option.

    This mapping does not resolve DNS or collect a hostname's A/AAAA records.
    Without an override, the HTTP transport resolves the hostname normally.
    The controller configures overrides before workers start, and workers only
    read the mapping, so the connection hot path needs no synchronization.
    """

    def __init__(self) -> None:
        self._overrides: dict[tuple[str, int], str] = {}

    @staticmethod
    def _key(host: str, port: int) -> tuple[str, int]:
        return host.rstrip(".").casefold(), port

    def set_override(self, host: str, port: int, ip_address: str) -> None:
        self._overrides[self._key(host, port)] = ip_address

    def get_override(self, host: str, port: int) -> str | None:
        """Return one forced connection IP, or None for normal DNS lookup."""
        return self._overrides.get(self._key(host, port))
