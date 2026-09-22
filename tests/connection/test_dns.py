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

import asyncio
import subprocess
import sys
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlsplit

from urllib3.exceptions import InsecureRequestWarning

from lib.connection.ip_overrides import IPOverrides
from lib.connection.requester import AsyncRequester, Requester
from lib.core.data import options
from tests.connection.proxy_server import ProxyTestStack


FORCED_HOST = "forced-origin.invalid"


class TestIPOverrideIsolation(TestCase):
    def test_importing_requester_does_not_replace_socket_getaddrinfo(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import socket; original = socket.getaddrinfo; "
                "import lib.connection.requester; "
                "raise SystemExit(socket.getaddrinfo is not original)",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_overrides_are_isolated_by_requester_and_port(self):
        first = IPOverrides()
        second = IPOverrides()
        first.set_override(FORCED_HOST, 443, "192.0.2.10")

        self.assertEqual(first.get_override(FORCED_HOST, 443), "192.0.2.10")
        self.assertIsNone(first.get_override(FORCED_HOST, 80))
        self.assertIsNone(second.get_override(FORCED_HOST, 443))

    def test_override_lookup_does_not_resolve_dns(self):
        overrides = IPOverrides()
        overrides.set_override(FORCED_HOST, 443, "192.0.2.10")

        with patch("socket.getaddrinfo") as getaddrinfo:
            self.assertEqual(overrides.get_override(FORCED_HOST, 443), "192.0.2.10")
            self.assertIsNone(overrides.get_override(FORCED_HOST, 80))

        getaddrinfo.assert_not_called()

    def test_override_lookup_does_not_serialize_connection_workers(self):
        barrier = threading.Barrier(2)

        class ConcurrentReadMapping(dict):
            def get(self, key, default=None):
                barrier.wait(timeout=2)
                return super().get(key, default)

        overrides = IPOverrides()
        overrides.set_override(FORCED_HOST, 443, "192.0.2.10")
        overrides._overrides = ConcurrentReadMapping(overrides._overrides)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: overrides.get_override(FORCED_HOST, 443),
                    range(2),
                )
            )

        self.assertEqual(results, ["192.0.2.10", "192.0.2.10"])


class TestIPOverrideIntegration(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack_context = ProxyTestStack()
        cls.stack = cls.stack_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.stack_context.__exit__(None, None, None)

    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "proxies": [],
                "headers": {},
                "data": None,
                "cert_file": None,
                "key_file": None,
                "network_interface": None,
                "random_agents": False,
                "auth": None,
                "auth_type": None,
                "max_retries": 0,
                "max_rate": 0,
                "thread_count": 2,
                "follow_redirects": False,
                "http_method": "GET",
                "timeout": 3,
                "proxy_auth": None,
            }
        )

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    @staticmethod
    def forced_url(target):
        parsed = urlsplit(target.url)
        return f"{parsed.scheme}://{FORCED_HOST}:{parsed.port}/"

    def test_sync_requester_scopes_ip_override_to_its_own_connections(self):
        for target in self.stack.targets:
            with self.subTest(scheme=target.scheme):
                target.clear_events()
                requester = Requester()
                requester.set_ip(FORCED_HOST, urlsplit(target.url).port, "127.0.0.1")
                requester.set_url(self.forced_url(target))
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", InsecureRequestWarning)
                        response = requester.request("sync-ip-override")
                finally:
                    requester.close()

                self.assertEqual(response.status, 200)
                self.assertEqual(
                    target.events,
                    [("GET", "/sync-ip-override")],
                )
                self.assertEqual(
                    target.host_headers,
                    [f"{FORCED_HOST}:{urlsplit(target.url).port}"],
                )
                if target.scheme == "https":
                    self.assertEqual(target.server_names, [FORCED_HOST])

    def test_async_requester_scopes_ip_override_to_its_own_connections(self):
        asyncio.run(self._test_async_requester_ip_override())

    async def _test_async_requester_ip_override(self):
        for target in self.stack.targets:
            with self.subTest(scheme=target.scheme):
                target.clear_events()
                requester = AsyncRequester()
                requester.set_ip(FORCED_HOST, urlsplit(target.url).port, "127.0.0.1")
                requester.set_url(self.forced_url(target))
                try:
                    response = await requester.request("async-ip-override")
                finally:
                    await requester.close()

                self.assertEqual(response.status, 200)
                self.assertEqual(
                    target.events,
                    [("GET", "/async-ip-override")],
                )
                self.assertEqual(
                    target.host_headers,
                    [f"{FORCED_HOST}:{urlsplit(target.url).port}"],
                )
                if target.scheme == "https":
                    self.assertEqual(target.server_names, [FORCED_HOST])
