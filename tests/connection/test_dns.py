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

from unittest import TestCase
from socket import getaddrinfo
from unittest.mock import patch

from lib.connection.dns import (
    DNSResolution,
    _resolution_cache,
    cache_dns,
    cached_getaddrinfo,
    resolve_host_records,
)
from lib.core.settings import DUMMY_DOMAIN


class TestDNS(TestCase):
    def test_cache_dns(self):
        cache_dns(DUMMY_DOMAIN, 80, "127.0.0.1")
        self.assertEqual(
            cached_getaddrinfo(DUMMY_DOMAIN, 80),
            getaddrinfo("127.0.0.1", 80),
            "Adding DNS cache doesn't work",
        )

    def test_resolve_host_records_uses_explicit_ip(self):
        self.assertEqual(
            resolve_host_records("example.com", explicit_ip="203.0.113.10"),
            DNSResolution(ips=("203.0.113.10",)),
        )

    def test_resolve_host_records_failure_returns_empty_resolution(self):
        _resolution_cache.clear()
        with patch("lib.connection.dns.dns_resolver", object()), patch(
            "lib.connection.dns._resolve_with_dnspython",
            side_effect=RuntimeError("dns failed"),
        ):
            self.assertEqual(
                resolve_host_records("failure.example", timeout=0.1),
                DNSResolution(),
            )
