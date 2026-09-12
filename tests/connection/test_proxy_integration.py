import asyncio
import base64
import re
import time
import warnings
from unittest import TestCase, skipUnless

from urllib3.exceptions import InsecureRequestWarning

from lib.connection.native import NativeHTTPBackend
from lib.connection.requester import AsyncRequester, Requester
from lib.core.data import options
from lib.core.exceptions import RequestException
from tests.connection.proxy_server import ProxyTestStack


try:
    import dirsearch_native
except ImportError:
    dirsearch_native = None


PROXY_CREDENTIAL = "proxy-user:proxy-password"
RESERVED_PROXY_CREDENTIAL = "proxy/user:p@ss/word?#%:tail"
PROXY_CREDENTIALS = (PROXY_CREDENTIAL, RESERVED_PROXY_CREDENTIAL)
INVALID_PROXY_CREDENTIAL = "wrong:credentials"
PROXY_AUTHORIZATION = "Basic " + base64.b64encode(
    PROXY_CREDENTIAL.encode()
).decode()
PROXY_FAILURE_TIMEOUT = 0.2
PROXY_CASE_DEADLINE = 2
RAW_REQUEST_TARGET_CASES = (
    ("malformed escape", "admin%3d..%1\\*", "/admin%3D..%1\\*"),
    ("encoded backslash", "admin/%83%5c/..", "/admin/%83%5C/.."),
    (
        "query and unicode",
        "admin?x=1 y=ñ&raw=%1\\*",
        "/admin?x=1%20y=%C3%B1&raw=%1\\*",
    ),
)


def normalize_percent_hex(target: str) -> str:
    return re.sub(
        r"%[0-9a-fA-F]{2}",
        lambda match: match.group(0).upper(),
        target,
    )


class TestProxyIntegration(TestCase):
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

    def test_sync_engine_uses_http_and_https_proxies_for_both_targets(self):
        for proxy, target in self._cases():
            with self.subTest(proxy=proxy.scheme, target=target.scheme):
                path = f"sync-{proxy.scheme}-proxy-{target.scheme}-target"
                self._prepare_case(proxy, target)
                response, error, _ = self._sync_request(proxy, target, path)

                self.assertIsNone(error)
                self._assert_case(proxy, target, path, response)

    def test_async_engine_uses_http_and_https_proxies_for_both_targets(self):
        asyncio.run(self._test_async_engine())

    async def _test_async_engine(self):
        for proxy, target in self._cases():
            with self.subTest(proxy=proxy.scheme, target=target.scheme):
                path = f"async-{proxy.scheme}-proxy-{target.scheme}-target"
                self._prepare_case(proxy, target)
                response, error, _ = await self._async_request(proxy, target, path)

                self.assertIsNone(error)
                self._assert_case(proxy, target, path, response)

    def test_sync_engine_preserves_raw_targets_through_proxies(self):
        for name, path, expected in RAW_REQUEST_TARGET_CASES:
            for proxy, target in self._cases():
                with self.subTest(
                    case=name,
                    proxy=proxy.scheme,
                    target=target.scheme,
                ):
                    self._prepare_case(proxy, target)
                    response, error, _ = self._sync_request(proxy, target, path)

                    self.assertIsNone(error)
                    self._assert_raw_target(target, expected, response)

    def test_async_engine_preserves_raw_targets_through_proxies(self):
        asyncio.run(self._test_async_engine_raw_targets())

    async def _test_async_engine_raw_targets(self):
        for name, path, expected in RAW_REQUEST_TARGET_CASES:
            for proxy, target in self._cases():
                with self.subTest(
                    case=name,
                    proxy=proxy.scheme,
                    target=target.scheme,
                ):
                    self._prepare_case(proxy, target)
                    response, error, _ = await self._async_request(
                        proxy, target, path
                    )

                    self.assertIsNone(error)
                    self._assert_raw_target(target, expected, response)

    def test_async_replay_preserves_raw_targets_through_proxies(self):
        asyncio.run(self._test_async_replay_raw_targets())

    async def _test_async_replay_raw_targets(self):
        for name, path, expected in RAW_REQUEST_TARGET_CASES:
            for proxy, target in self._cases():
                with self.subTest(
                    case=name,
                    proxy=proxy.scheme,
                    target=target.scheme,
                ):
                    self._prepare_case(proxy, target)
                    response, error = await self._async_replay_request(
                        proxy, target, path
                    )

                    self.assertIsNone(error)
                    self._assert_raw_target(target, expected, response)

    @skipUnless(
        dirsearch_native is not None
        and hasattr(dirsearch_native, "NativeHttpEngine"),
        "native extension is not installed",
    )
    def test_native_engine_uses_http_and_https_proxies_for_both_targets(self):
        for proxy, target in self._cases():
            with self.subTest(proxy=proxy.scheme, target=target.scheme):
                path = f"native-{proxy.scheme}-proxy-{target.scheme}-target"
                self._prepare_case(proxy, target)
                response, error, _ = self._native_request(proxy, target, path)
                self.assertIsNone(error)
                self._assert_case(proxy, target, path, response)

    def test_sync_engine_authenticates_http_and_https_proxies(self):
        for credential in PROXY_CREDENTIALS:
            for proxy, target in self._cases():
                with self.subTest(
                    credential=credential,
                    proxy=proxy.scheme,
                    target=target.scheme,
                ):
                    path = f"sync-auth-{proxy.scheme}-{target.scheme}"
                    authorization = self._prepare_authenticated_case(
                        proxy,
                        target,
                        credential,
                    )
                    options["proxy_auth"] = credential
                    try:
                        response, error, _ = self._sync_request(proxy, target, path)
                    finally:
                        proxy.configure_proxy()

                    self.assertIsNone(error)
                    self._assert_case(proxy, target, path, response)
                    self.assertEqual(
                        proxy.proxy_authorizations,
                        [authorization],
                    )

    def test_async_engine_authenticates_http_and_https_proxies(self):
        asyncio.run(self._test_async_engine_authentication())

    async def _test_async_engine_authentication(self):
        for credential in PROXY_CREDENTIALS:
            for proxy, target in self._cases():
                with self.subTest(
                    credential=credential,
                    proxy=proxy.scheme,
                    target=target.scheme,
                ):
                    path = f"async-auth-{proxy.scheme}-{target.scheme}"
                    authorization = self._prepare_authenticated_case(
                        proxy,
                        target,
                        credential,
                    )
                    options["proxy_auth"] = credential
                    try:
                        response, error, _ = await self._async_request(
                            proxy, target, path
                        )
                    finally:
                        proxy.configure_proxy()

                    self.assertIsNone(error)
                    self._assert_case(proxy, target, path, response)
                    self.assertEqual(
                        proxy.proxy_authorizations,
                        [authorization],
                    )

    @skipUnless(
        dirsearch_native is not None
        and hasattr(dirsearch_native, "NativeHttpEngine"),
        "native extension is not installed",
    )
    def test_native_engine_authenticates_http_and_https_proxies(self):
        for credential in PROXY_CREDENTIALS:
            for proxy, target in self._cases():
                with self.subTest(
                    credential=credential,
                    proxy=proxy.scheme,
                    target=target.scheme,
                ):
                    path = f"native-auth-{proxy.scheme}-{target.scheme}"
                    authorization = self._prepare_authenticated_case(
                        proxy,
                        target,
                        credential,
                    )
                    options["proxy_auth"] = credential
                    try:
                        response, error, _ = self._native_request(
                            proxy,
                            target,
                            path,
                        )
                    finally:
                        proxy.configure_proxy()

                    self.assertIsNone(error)
                    self._assert_case(proxy, target, path, response)
                    self.assertEqual(
                        proxy.proxy_authorizations,
                        [authorization],
                    )

    def test_sync_engine_rejects_missing_and_invalid_proxy_credentials(self):
        for credential in (None, INVALID_PROXY_CREDENTIAL):
            for proxy, target in self._cases():
                with self.subTest(
                    credential=credential,
                    proxy=proxy.scheme,
                    target=target.scheme,
                ):
                    path = f"sync-rejected-auth-{proxy.scheme}-{target.scheme}"
                    self._prepare_authenticated_case(proxy, target)
                    options["proxy_auth"] = credential
                    try:
                        response, error, _ = self._sync_request(proxy, target, path)
                    finally:
                        proxy.configure_proxy()

                    self._assert_authentication_rejected(
                        proxy, target, response, error
                    )

    def test_async_engine_rejects_missing_and_invalid_proxy_credentials(self):
        asyncio.run(self._test_async_engine_rejected_authentication())

    async def _test_async_engine_rejected_authentication(self):
        for credential in (None, INVALID_PROXY_CREDENTIAL):
            for proxy, target in self._cases():
                with self.subTest(
                    credential=credential,
                    proxy=proxy.scheme,
                    target=target.scheme,
                ):
                    path = f"async-rejected-auth-{proxy.scheme}-{target.scheme}"
                    self._prepare_authenticated_case(proxy, target)
                    options["proxy_auth"] = credential
                    try:
                        response, error, _ = await self._async_request(
                            proxy, target, path
                        )
                    finally:
                        proxy.configure_proxy()

                    self._assert_authentication_rejected(
                        proxy, target, response, error
                    )

    @skipUnless(
        dirsearch_native is not None
        and hasattr(dirsearch_native, "NativeHttpEngine"),
        "native extension is not installed",
    )
    def test_native_engine_rejects_missing_and_invalid_proxy_credentials(self):
        for credential in (None, INVALID_PROXY_CREDENTIAL):
            for proxy, target in self._cases():
                with self.subTest(
                    credential=credential,
                    proxy=proxy.scheme,
                    target=target.scheme,
                ):
                    path = f"native-rejected-auth-{proxy.scheme}-{target.scheme}"
                    self._prepare_authenticated_case(proxy, target)
                    options["proxy_auth"] = credential
                    try:
                        response, error, _ = self._native_request(
                            proxy, target, path
                        )
                    finally:
                        proxy.configure_proxy()

                    self._assert_authentication_rejected(
                        proxy,
                        target,
                        response,
                        error,
                        connect_status_available=False,
                    )

    def test_sync_engine_bounds_proxy_failures_and_handles_429(self):
        for behavior, proxy, target in self._failure_cases():
            with self.subTest(
                behavior=behavior,
                proxy=proxy.scheme,
                target=target.scheme,
            ):
                path = f"sync-{behavior}-{proxy.scheme}-{target.scheme}"
                self._prepare_failure_case(proxy, target, behavior)
                try:
                    result = self._sync_request(proxy, target, path)
                finally:
                    proxy.configure_proxy()

                self._assert_failure_case(behavior, proxy, target, result)

    def test_async_engine_bounds_proxy_failures_and_handles_429(self):
        asyncio.run(self._test_async_engine_proxy_failures())

    async def _test_async_engine_proxy_failures(self):
        for behavior, proxy, target in self._failure_cases():
            with self.subTest(
                behavior=behavior,
                proxy=proxy.scheme,
                target=target.scheme,
            ):
                path = f"async-{behavior}-{proxy.scheme}-{target.scheme}"
                self._prepare_failure_case(proxy, target, behavior)
                try:
                    result = await self._async_request(proxy, target, path)
                finally:
                    proxy.configure_proxy()

                self._assert_failure_case(behavior, proxy, target, result)

    @skipUnless(
        dirsearch_native is not None
        and hasattr(dirsearch_native, "NativeHttpEngine"),
        "native extension is not installed",
    )
    def test_native_engine_bounds_proxy_failures_and_handles_429(self):
        for behavior, proxy, target in self._failure_cases():
            with self.subTest(
                behavior=behavior,
                proxy=proxy.scheme,
                target=target.scheme,
            ):
                path = f"native-{behavior}-{proxy.scheme}-{target.scheme}"
                self._prepare_failure_case(proxy, target, behavior)
                try:
                    result = self._native_request(proxy, target, path)
                finally:
                    proxy.configure_proxy()

                self._assert_failure_case(
                    behavior,
                    proxy,
                    target,
                    result,
                    connect_status_available=False,
                )

    def _cases(self):
        for proxy in self.stack.proxies:
            for target in self.stack.targets:
                yield proxy, target

    def _failure_cases(self):
        for behavior in ("timeout", "drop", "rate_limit"):
            for proxy, target in self._cases():
                yield behavior, proxy, target

    @staticmethod
    def _prepare_case(proxy, target):
        proxy.configure_proxy()
        proxy.clear_events()
        target.clear_events()
        options["proxy_auth"] = None

    def _prepare_authenticated_case(
        self,
        proxy,
        target,
        credential=PROXY_CREDENTIAL,
    ):
        self._prepare_case(proxy, target)
        options["max_retries"] = 1
        authorization = "Basic " + base64.b64encode(credential.encode()).decode()
        proxy.configure_proxy(required_authorization=authorization)
        return authorization

    def _prepare_failure_case(self, proxy, target, behavior):
        self._prepare_case(proxy, target)
        options["timeout"] = PROXY_FAILURE_TIMEOUT
        options["max_retries"] = 1
        proxy.configure_proxy(behavior=behavior)

    @staticmethod
    def _sync_request(proxy, target, path):
        options["proxies"] = [proxy.url]
        requester = Requester()
        requester.set_url(target.url)
        started = time.monotonic()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                try:
                    return requester.request(path), None, time.monotonic() - started
                except RequestException as error:
                    return None, error, time.monotonic() - started
        finally:
            requester.session.close()

    @staticmethod
    async def _async_request(proxy, target, path):
        options["proxies"] = [proxy.url]
        requester = AsyncRequester()
        requester.set_url(target.url)
        started = time.monotonic()
        try:
            try:
                response = await requester.request(path)
                return response, None, time.monotonic() - started
            except RequestException as error:
                return None, error, time.monotonic() - started
        finally:
            await requester.session.aclose()

    @staticmethod
    async def _async_replay_request(proxy, target, path):
        options["proxies"] = []
        requester = AsyncRequester()
        requester.set_url(target.url)
        try:
            try:
                return await requester.replay_request(path, proxy.url), None
            except RequestException as error:
                return None, error
        finally:
            await requester.close()

    @staticmethod
    def _native_request(proxy, target, path):
        options["proxies"] = [proxy.url]
        backend = NativeHTTPBackend()
        started = time.monotonic()
        rows = list(backend.scan(target.url, [path]))
        elapsed = time.monotonic() - started

        if len(rows) != 1:
            raise AssertionError(f"Expected one native result, got {len(rows)}")
        _, response, error = rows[0]
        return response, error, elapsed

    def _assert_case(self, proxy, target, path, response):
        self.assertIsNotNone(response)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, f"reached:/{path}".encode())
        self.assertEqual(target.events, [("GET", f"/{path}")])
        self.assertEqual(target.proxy_authorizations, [None])

        self.assertEqual(proxy.events, [self._expected_proxy_event(target, path)])

    def _assert_raw_target(self, target, expected, response):
        self.assertIsNotNone(response)
        self.assertEqual(response.status, 200)
        self.assertEqual(
            [normalize_percent_hex(path) for _, path in target.events],
            [expected],
        )

    def _assert_authentication_rejected(
        self,
        proxy,
        target,
        response,
        error,
        connect_status_available=True,
    ):
        self.assertIsNone(response)
        self.assertIsNotNone(error)
        if target.scheme == "https" and not connect_status_available:
            self.assertEqual(str(error), "Proxy CONNECT request was rejected")
        else:
            self.assertEqual(str(error), "Proxy authentication required")
        self.assertEqual(target.events, [])
        self.assertEqual(len(proxy.events), 1, "Proxy rejection must not be retried")

    def _assert_failure_case(
        self,
        behavior,
        proxy,
        target,
        result,
        connect_status_available=True,
    ):
        response, error, elapsed = result
        self.assertLess(elapsed, PROXY_CASE_DEADLINE)
        self.assertEqual(target.events, [])
        expected_attempts = 2 if behavior in ("timeout", "drop") else 1
        self.assertEqual(len(proxy.events), expected_attempts)

        if behavior == "rate_limit" and target.scheme == "http":
            self.assertIsNone(error)
            self.assertIsNotNone(response)
            self.assertEqual(response.status, 429)
            self.assertEqual(response.headers.get("retry-after"), "1")
            self.assertIn("connection_limit", response.headers.get("proxy-status"))
            return

        self.assertIsNone(response)
        self.assertIsNotNone(error)
        if behavior == "timeout":
            self.assertIn("timeout", str(error).lower().replace("timed out", "timeout"))
        elif behavior == "rate_limit":
            expected = (
                "Proxy connection failed with HTTP 429"
                if connect_status_available
                else "Proxy CONNECT request was rejected"
            )
            self.assertEqual(str(error), expected)

    @staticmethod
    def _expected_proxy_event(target, path):
        if target.scheme == "http":
            return "GET", target.url + path
        return "CONNECT", target.authority
