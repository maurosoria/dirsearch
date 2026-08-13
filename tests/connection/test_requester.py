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

import http.server
import re
import ssl
import socketserver
import threading
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import httpx
import requests

from lib.connection import requester as requester_module
from lib.connection.native import NativeHTTPBackend
from lib.connection.requester import (
    AsyncRequester,
    Requester,
    _find_ssl_error,
    _format_ssl_error,
)
from lib.core.data import options
from lib.core.exceptions import RequestException


REQUEST_TARGET_CASES = (
    ("shift-jis-overlap", "admin/%83%5c/..", b"/admin/%83%5C/.."),
    ("malformed-percent-backslash-star", "admin%3d..%1\\*", b"/admin%3D..%1\\*"),
    ("utf16-le-bom", "%FF%FEadmin", b"/%FF%FEadmin"),
    ("utf16-be-bom", "%FE%FFadmin", b"/%FE%FFadmin"),
    ("rtl-override", "admin/\u202eexe.txt/", b"/admin/%E2%80%AEexe.txt/"),
    ("german-eszett", "test-straße", b"/test-stra%C3%9Fe"),
    ("space-and-cjk", "admin space/测试", b"/admin%20space/%E6%B5%8B%E8%AF%95"),
    ("reserved-punctuation", "admin=..\\*;:@&+$,()", b"/admin=..\\*;:@&+$,()"),
    (
        "query-character-encoding",
        "admin?x=1 y=ñ&raw=%1\\*",
        b"/admin?x=1%20y=%C3%B1&raw=%1\\*",
    ),
    ("turkish-i-exact-case", "ADMIN", b"/ADMIN"),
    ("cjk", "admin/测试", b"/admin/%E6%B5%8B%E8%AF%95"),
)


class RequestTargetTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class RequestTargetHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.targets.append(self.raw_requestline.split(b" ")[1])
        self.server.proxy_authorizations.append(
            self.headers.get("Proxy-Authorization")
        )
        body = b"ok"
        self.send_response(200)
        self.send_header("content-type", "text/plain")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class RequestTargetServer:
    def __enter__(self):
        self.server = RequestTargetTCPServer(("127.0.0.1", 0), RequestTargetHandler)
        self.server.targets = []
        self.server.proxy_authorizations = []
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.05),
            daemon=True,
        )
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def url(self):
        host, port = self.server.server_address
        return f"http://{host}:{port}/"

    @property
    def targets(self):
        return self.server.targets

    @property
    def proxy_authorizations(self):
        return self.server.proxy_authorizations


def normalize_percent_hex(target: bytes) -> bytes:
    return re.sub(
        rb"%[0-9a-fA-F]{2}",
        lambda match: match.group(0).upper(),
        target,
    )


def _with_cause(exc: Exception, cause: Exception) -> Exception:
    exc.__cause__ = cause
    return exc


def _with_context(exc: Exception, context: Exception) -> Exception:
    exc.__context__ = context
    return exc


class DummySyncResponse:
    status_code = 200
    headers = {"content-type": "text/plain"}
    history = []
    encoding = "utf-8"

    @staticmethod
    def iter_content(chunk_size):
        del chunk_size
        yield b"body"


class DummySyncSession:
    @staticmethod
    def prepare_request(request):
        return SimpleNamespace(url=request.url)

    def __init__(self, response):
        self.response = response

    def send(self, prep, **kwargs):
        del prep, kwargs
        return self.response


class DummyAsyncResponse:
    status_code = 200
    headers = {"content-type": "text/plain"}
    history = []
    encoding = "utf-8"

    def __init__(self):
        self.closed = False

    @staticmethod
    async def aiter_bytes(chunk_size):
        del chunk_size
        yield b"body"

    async def aclose(self):
        self.closed = True


class DummyAsyncSession:
    @staticmethod
    def build_request(*args, **kwargs):
        del args, kwargs
        return object()

    def __init__(self, response):
        self.response = response

    async def send(self, request, **kwargs):
        del request, kwargs
        return self.response


class BaseRequesterTestCase(TestCase):
    def setUp(self) -> None:
        self.original_options = dict(options)
        options["proxies"] = []
        options["headers"] = {}
        options["data"] = None
        options["cert_file"] = None
        options["key_file"] = None
        options["network_interface"] = None
        options["random_agents"] = False
        options["auth"] = None
        options["auth_type"] = None
        options["max_retries"] = 0
        options["max_rate"] = 0
        options["thread_count"] = 1
        options["follow_redirects"] = False
        options["http_method"] = "GET"
        options["timeout"] = 1
        options["proxy_auth"] = None

    def tearDown(self) -> None:
        options.clear()
        options.update(self.original_options)


class TestSSLHelpers(BaseRequesterTestCase):
    def test_find_ssl_error_direct(self):
        ssl_exc = ssl.SSLError("wrong version number")
        self.assertIs(_find_ssl_error(ssl_exc), ssl_exc)

    def test_find_ssl_error_from_cause(self):
        ssl_exc = ssl.SSLError("wrong version number")
        wrapped = _with_cause(httpx.ConnectError("handshake failed"), ssl_exc)
        self.assertIs(_find_ssl_error(wrapped), ssl_exc)

    def test_find_ssl_error_from_context(self):
        ssl_exc = ssl.SSLError("wrong version number")
        wrapped = _with_context(RuntimeError("wrapper"), ssl_exc)
        self.assertIs(_find_ssl_error(wrapped), ssl_exc)

    def test_format_ssl_error_for_certificate_failure(self):
        cert_exc = ssl.SSLCertVerificationError(
            1,
            "certificate verify failed: self signed certificate",
        )
        self.assertEqual(
            _format_ssl_error(cert_exc, "https://example.com/"),
            "SSL certificate verification failed (self-signed certificate): https://example.com/",
        )


class TestRequesterSSLHandling(BaseRequesterTestCase):
    def test_sync_requests_ssl_error_uses_specific_message(self):
        requester = Requester()
        requester.set_url("https://example.com/")
        error = requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")

        with patch.object(requester.session, "send", side_effect=error):
            with self.assertRaises(RequestException) as ctx:
                requester.request("admin")

        self.assertEqual(
            str(ctx.exception),
            "SSL certificate verification failed: https://example.com/admin",
        )

    def test_sync_wrapped_certificate_error_uses_specific_message(self):
        requester = Requester()
        requester.set_url("https://example.com/")
        cert_exc = ssl.SSLCertVerificationError(
            1,
            "certificate verify failed: self signed certificate",
        )
        error = _with_cause(requests.exceptions.ConnectionError("boom"), cert_exc)

        with patch.object(requester.session, "send", side_effect=error):
            with self.assertRaises(RequestException) as ctx:
                requester.request("admin")

        self.assertEqual(
            str(ctx.exception),
            "SSL certificate verification failed (self-signed certificate): https://example.com/admin",
        )


class TestRequesterErrorClassification(BaseRequesterTestCase):
    def test_sync_too_many_redirects_uses_specific_message(self):
        requester = Requester()
        requester.set_url("http://example.com/")

        with patch.object(
            requester.session,
            "send",
            side_effect=requests.exceptions.TooManyRedirects("exceeded"),
        ):
            with self.assertRaises(RequestException) as ctx:
                requester.request("admin")

        self.assertEqual(
            str(ctx.exception),
            "Too many redirects: http://example.com/admin",
        )

    def test_sync_wrapped_read_timeout_uses_timeout_message(self):
        requester = Requester()
        requester.set_url("http://example.com/")
        error = requests.exceptions.ConnectionError("Read timed out.")

        with patch.object(requester.session, "send", side_effect=error):
            with self.assertRaises(RequestException) as ctx:
                requester.request("admin")

        self.assertEqual(
            str(ctx.exception),
            "Request timeout: http://example.com/admin",
        )

    def test_sync_chunked_encoding_error_uses_read_error_message(self):
        requester = Requester()
        requester.set_url("http://example.com/")
        error = requests.exceptions.ChunkedEncodingError("incomplete body")

        with patch.object(requester.session, "send", side_effect=error):
            with self.assertRaises(RequestException) as ctx:
                requester.request("admin")

        self.assertEqual(
            str(ctx.exception),
            "Failed to read response body: http://example.com/admin",
        )


class TestRequesterElapsed(TestCase):
    def test_request_elapsed_includes_stream_read(self):
        requester = object.__new__(Requester)
        requester._rate = 0
        requester._url = "https://example.com/"
        requester.proxy_cred = None
        requester.headers = {}
        requester.agents = []
        requester.session = DummySyncSession(DummySyncResponse())

        with patch.object(requester_module.time, "perf_counter", side_effect=[10.0, 10.25]):
            with patch.object(requester_module.logger, "info"):
                response = requester.request("admin")

        self.assertEqual(response.elapsed, 0.25, "Sync elapsed should measure the full streamed request lifecycle")


class TestRequesterPathPreservation(BaseRequesterTestCase):
    def test_sync_requester_preserves_encoded_edge_case_targets(self):
        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)

            for _, path, _ in REQUEST_TARGET_CASES:
                requester.request(path)

            self.assertEqual(
                [normalize_percent_hex(target) for target in server.targets],
                [expected for _, _, expected in REQUEST_TARGET_CASES],
            )

    def test_sync_requester_appends_base_query(self):
        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            requester.set_query("debug=true")
            requester.request("admin")

            self.assertEqual(server.targets, [b"/admin?debug=true"])


class TestAsyncRequesterSSLHandling(BaseRequesterTestCase, IsolatedAsyncioTestCase):
    async def test_async_connect_error_with_ssl_cause_uses_ssl_message(self):
        requester = AsyncRequester()
        requester.set_url("https://example.com/")
        error = _with_cause(
            httpx.ConnectError("connect failed"),
            ssl.SSLError("wrong version number"),
        )
        requester.session.send = AsyncMock(side_effect=error)

        with self.assertRaises(RequestException) as ctx:
            await requester.request("admin")

        self.assertEqual(
            str(ctx.exception),
            "SSL protocol version mismatch: https://example.com/admin",
        )

    async def test_async_connect_error_without_ssl_cause_stays_connect_error(self):
        requester = AsyncRequester()
        requester.set_url("https://example.com/")
        requester.session.send = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with self.assertRaises(RequestException) as ctx:
            await requester.request("admin")

        self.assertEqual(str(ctx.exception), "Cannot connect to: example.com")

    async def test_async_connect_error_with_cert_context_uses_cert_message(self):
        requester = AsyncRequester()
        requester.set_url("https://example.com/")
        cert_exc = ssl.SSLCertVerificationError(
            1,
            "certificate verify failed: self signed certificate",
        )
        error = _with_context(httpx.ConnectError("connect failed"), cert_exc)
        requester.session.send = AsyncMock(side_effect=error)

        with self.assertRaises(RequestException) as ctx:
            await requester.request("admin")

        self.assertEqual(
            str(ctx.exception),
            "SSL certificate verification failed (self-signed certificate): https://example.com/admin",
        )

    async def test_async_remote_protocol_error_uses_read_error_message(self):
        requester = AsyncRequester()
        requester.set_url("http://example.com/")
        requester.session.send = AsyncMock(
            side_effect=httpx.RemoteProtocolError("bad Content-Length")
        )

        with self.assertRaises(RequestException) as ctx:
            await requester.request("admin")

        self.assertEqual(
            str(ctx.exception),
            "Failed to read response body: http://example.com/admin",
        )


class TestAsyncRequesterElapsed(IsolatedAsyncioTestCase):
    async def test_request_elapsed_waits_for_stream_close(self):
        requester = object.__new__(AsyncRequester)
        requester._rate = 0
        requester._url = "https://example.com/"
        requester.proxy_cred = None
        requester.headers = {}
        requester.agents = []
        requester.session = DummyAsyncSession(DummyAsyncResponse())

        with patch.object(requester_module.time, "perf_counter", side_effect=[20.0, 20.5]):
            with patch.object(requester_module.logger, "info"):
                response = await requester.request("admin")

        self.assertEqual(response.elapsed, 0.5, "Async elapsed should measure the full streamed request lifecycle")
        self.assertTrue(requester.session.response.closed, "Streamed async responses should be closed before elapsed is used")


class TestAsyncRequesterPathPreservation(BaseRequesterTestCase, IsolatedAsyncioTestCase):
    async def test_async_requester_preserves_encoded_edge_case_targets(self):
        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                for _, path, _ in REQUEST_TARGET_CASES:
                    await requester.request(path)
            finally:
                await requester.session.aclose()

            self.assertEqual(
                [normalize_percent_hex(target) for target in server.targets],
                [expected for _, _, expected in REQUEST_TARGET_CASES],
            )

    async def test_async_requester_appends_base_query(self):
        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            requester.set_query("debug=true")
            try:
                await requester.request("admin")
            finally:
                await requester.session.aclose()

            self.assertEqual(server.targets, [b"/admin?debug=true"])


class TestNativeRequesterPathPreservation(BaseRequesterTestCase):
    def test_native_requester_preserves_encoded_edge_case_targets(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            results = list(
                backend.scan(
                    server.url,
                    [path for _, path, _ in REQUEST_TARGET_CASES],
                )
            )

            self.assertEqual([error for _, _, error in results], [None] * len(results))
            self.assertCountEqual(
                [normalize_percent_hex(target) for target in server.targets],
                [expected for _, _, expected in REQUEST_TARGET_CASES],
            )

    def test_native_requester_uses_authenticated_http_proxy(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            options["proxy_auth"] = "user:password"
            results = list(
                backend.scan("http://origin.invalid/", ["admin"])
            )

            self.assertEqual([error for _, _, error in results], [None])
            self.assertEqual(
                proxy.targets,
                [b"http://origin.invalid/admin"],
            )
            self.assertEqual(
                proxy.proxy_authorizations,
                ["Basic dXNlcjpwYXNzd29yZA=="],
            )

    def test_native_requester_appends_base_query(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            results = list(backend.scan(server.url, ["admin"], "debug=true"))

            self.assertEqual([error for _, _, error in results], [None])
            self.assertEqual(server.targets, [b"/admin?debug=true"])
