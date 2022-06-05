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

from lib.connection.dns import cache_dns, cached_getaddrinfo
from lib.core.settings import DUMMY_DOMAIN


class TestDNS(TestCase):
    def test_cache_dns(self):
        cache_dns(DUMMY_DOMAIN, 80, "127.0.0.1")
        self.assertEqual(
            cached_getaddrinfo(DUMMY_DOMAIN, 80),
            getaddrinfo("127.0.0.1", 80),
            "Adding DNS cache doesn't work",
        )
