"""System proxy exceptions must affect routing, including redirect destinations."""

import asyncio
from contextlib import contextmanager
import os
from unittest import TestCase
from unittest.mock import patch
from urllib import request as urllib_request
from urllib.parse import urlsplit

import httpx

from lib.connection.requester import AsyncRequester
from lib.core.exceptions import RequestException
from lib.core.request_config import RequestConfig
from tests.connection.proxy_server import ProxyTestStack


class TestMacOSProxyExceptions(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack_context = ProxyTestStack()
        cls.stack = cls.stack_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.stack_context.__exit__(None, None, None)

    def setUp(self):
        self.proxy = self.stack.http_proxy
        self.settings = {"http": self.proxy.url, "https": self.proxy.url}
        self._clear_events()

    def _clear_events(self):
        self.proxy.clear_events()
        for target in self.stack.targets:
            target.clear_events()

    @contextmanager
    def _system_proxy(self, exceptions=(), exclude_simple=False, environment=None, platform="darwin"):
        settings = {"exceptions": exceptions, "exclude_simple": exclude_simple}
        with (
            patch.dict(os.environ, environment or {}, clear=True),
            patch("sys.platform", platform),
            patch("httpx._utils.getproxies", return_value=self.settings),
            patch(
                "urllib.request.proxy_bypass",
                side_effect=lambda host: urllib_request._proxy_bypass_macosx_sysconf(host, settings),
            ) as bypass,
        ):
            yield bypass

    def test_system_exceptions_bypass_proxy_and_keep_ip_override_and_raw_path(self):
        asyncio.run(self._test_system_exceptions())

    async def _test_system_exceptions(self):
        cases = (
            ("127.0.0.2", ("127.0.0.0/8",), False),
            ("service.local", ("*.local",), False),
            ("service.test", ("service.test",), False),
            ("intranet", (), True),
        )
        for target in self.stack.targets:
            port = urlsplit(target.url).port
            for host, exceptions, exclude_simple in cases:
                with self.subTest(scheme=target.scheme, host=host):
                    self._clear_events()
                    with self._system_proxy(exceptions, exclude_simple):
                        requester = AsyncRequester(RequestConfig(timeout=2, max_retries=0))
                        requester.set_url(f"{target.scheme}://{host}:{port}/")
                        requester.set_ip(host, port, "127.0.0.1")
                        try:
                            response = await requester.request("admin%1\\*")
                        finally:
                            await requester.close()

                    self.assertEqual(response.body, b"reached:/admin%1\\*")
                    self.assertEqual(target.events, [("GET", "/admin%1\\*")])
                    self.assertEqual(self.proxy.events, [])

    def test_without_inherited_proxies_skips_system_exception_checks(self):
        asyncio.run(self._test_without_inherited_proxies())

    async def _test_without_inherited_proxies(self):
        target = self.stack.http_target
        self.settings.clear()
        with self._system_proxy(("127.0.0.0/8",)) as bypass:
            requester = AsyncRequester(RequestConfig(timeout=2, max_retries=0))
            requester.set_url(target.url)
            try:
                response = await requester.request("direct")
            finally:
                await requester.close()
            bypass.assert_not_called()

        self.assertEqual(response.body, b"reached:/direct")
        self.assertEqual(self.proxy.events, [])

    def test_nonexcluded_targets_keep_forward_proxy_and_connect_formats(self):
        asyncio.run(self._test_nonexcluded_targets())

    async def _test_nonexcluded_targets(self):
        for target in self.stack.targets:
            with self.subTest(scheme=target.scheme):
                self._clear_events()
                with self._system_proxy(("*.local",)):
                    requester = AsyncRequester(RequestConfig(timeout=2, max_retries=0))
                    requester.set_url(target.url)
                    try:
                        response = await requester.request("known.html")
                    finally:
                        await requester.close()

                self.assertEqual(response.body, b"reached:/known.html")
                expected = (
                    ("GET", target.url + "known.html")
                    if target.scheme == "http"
                    else ("CONNECT", target.authority)
                )
                self.assertEqual(self.proxy.events, [expected])

    def test_environment_proxies_take_precedence_over_system_exceptions(self):
        asyncio.run(self._test_environment_precedence())

    async def _test_environment_precedence(self):
        target = self.stack.http_target
        for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "ALL_PROXY"):
            with self.subTest(variable=key):
                self._clear_events()
                with self._system_proxy(("127.0.0.0/8",), environment={key: self.proxy.url}) as bypass:
                    requester = AsyncRequester(RequestConfig(timeout=2, max_retries=0))
                    requester.set_url(target.url)
                    try:
                        response = await requester.request("environment")
                    finally:
                        await requester.close()
                    bypass.assert_not_called()

                self.assertEqual(response.body, b"reached:/environment")
                self.assertEqual(self.proxy.events, [("GET", target.url + "environment")])

    def test_no_proxy_keeps_its_existing_bypass(self):
        asyncio.run(self._test_no_proxy())

    async def _test_no_proxy(self):
        target = self.stack.http_target
        self.settings["no"] = "127.0.0.1"
        with self._system_proxy(environment={"HTTP_PROXY": self.proxy.url, "NO_PROXY": "127.0.0.1"}) as bypass:
            requester = AsyncRequester(RequestConfig(timeout=2, max_retries=0))
            requester.set_url(target.url)
            try:
                response = await requester.request("no-proxy")
            finally:
                await requester.close()
            bypass.assert_not_called()

        self.assertEqual(response.body, b"reached:/no-proxy")
        self.assertEqual(self.proxy.events, [])

    def test_explicit_proxy_and_replay_ignore_system_exceptions(self):
        asyncio.run(self._test_explicit_proxy_and_replay())

    async def _test_explicit_proxy_and_replay(self):
        target = self.stack.http_target
        for replay in (False, True):
            with self.subTest(replay=replay):
                self._clear_events()
                proxies = () if replay else (self.proxy.url,)
                with self._system_proxy(("127.0.0.0/8",)) as bypass:
                    requester = AsyncRequester(RequestConfig(proxies=proxies, timeout=2, max_retries=0))
                    requester.set_url(target.url)
                    try:
                        response = (
                            await requester.replay_request("explicit", self.proxy.url)
                            if replay else await requester.request("explicit")
                        )
                    finally:
                        await requester.close()
                    bypass.assert_not_called()

                self.assertEqual(response.body, b"reached:/explicit")
                self.assertEqual(self.proxy.events, [("GET", target.url + "explicit")])

    def test_bypassed_origin_407_is_a_target_response(self):
        asyncio.run(self._test_origin_407())

    async def _test_origin_407(self):
        target = self.stack.http_target
        with self._system_proxy(("127.0.0.0/8",)):
            requester = AsyncRequester(RequestConfig(timeout=2, max_retries=0))
            requester.set_url(target.url)
            try:
                response = await requester.request("origin-407")
            finally:
                await requester.close()

        self.assertEqual(response.status, 407)
        self.assertEqual(target.events, [("GET", "/origin-407")])
        self.assertEqual(self.proxy.events, [])

    def test_nonexcluded_proxy_407_is_an_authentication_error(self):
        asyncio.run(self._test_proxy_407())

    async def _test_proxy_407(self):
        self.proxy.configure_proxy(required_authorization="Basic required")
        try:
            with self._system_proxy(("*.local",)):
                requester = AsyncRequester(RequestConfig(timeout=2, max_retries=0))
                requester.set_url(self.stack.http_target.url)
                try:
                    with self.assertRaisesRegex(RequestException, "Proxy authentication required"):
                        await requester.request("proxy-407")
                finally:
                    await requester.close()
        finally:
            self.proxy.configure_proxy()

        self.assertEqual(self.stack.http_target.events, [])
        self.assertEqual(len(self.proxy.events), 1)

    def test_other_platforms_keep_existing_routing(self):
        asyncio.run(self._test_other_platforms())

    async def _test_other_platforms(self):
        target = self.stack.http_target
        for platform in ("linux", "win32"):
            with self.subTest(platform=platform):
                self._clear_events()
                with self._system_proxy(("127.0.0.0/8",), platform=platform) as bypass:
                    requester = AsyncRequester(RequestConfig(timeout=2, max_retries=0))
                    requester.set_url(target.url)
                    try:
                        response = await requester.request("unchanged")
                    finally:
                        await requester.close()
                    bypass.assert_not_called()

                self.assertEqual(response.body, b"reached:/unchanged")
                self.assertEqual(self.proxy.events, [("GET", target.url + "unchanged")])

    def test_redirects_recheck_exceptions_in_both_directions(self):
        asyncio.run(self._test_redirects())

    async def _test_redirects(self):
        for start, destination in (("service.local", "service.test"), ("service.test", "service.local")):
            with self.subTest(start=start):
                routes = []

                def make_transport(**kwargs):
                    route = "proxy" if kwargs.get("proxy") else "direct"

                    def handle(request):
                        routes.append((route, request.url.host, request.url.path))
                        if request.url.path == "/redirect":
                            return httpx.Response(302, headers={"Location": f"http://{destination}/final"})
                        return httpx.Response(200, content=b"redirect reached")

                    return httpx.MockTransport(handle)

                with (
                    self._system_proxy(("*.local",)),
                    patch("httpx.AsyncHTTPTransport", side_effect=make_transport),
                    patch("lib.connection.requester.PathPreservingAsyncHTTPTransport", side_effect=make_transport),
                ):
                    requester = AsyncRequester(RequestConfig(follow_redirects=True, max_retries=0))
                    requester.set_url(f"http://{start}/")
                    try:
                        response = await requester.request("redirect")
                    finally:
                        await requester.close()

                self.assertEqual(response.body, b"redirect reached")
                self.assertEqual(routes, [
                    ("direct" if start.endswith(".local") else "proxy", start, "/redirect"),
                    ("direct" if destination.endswith(".local") else "proxy", destination, "/final"),
                ])
