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

import base64
import gzip
import http.server
import json
import os
import re
import ssl
import socketserver
import tempfile
import threading
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import httpx
import requests

from lib.connection import requester as requester_module
from lib.connection import response as response_module
from lib.connection.native import NativeHTTPBackend
from lib.connection.rate_limiter import RequestRateLimiter
from lib.connection.requester import (
    AsyncRequester,
    PathPreservingAsyncHTTPTransport,
    PathPreservingHTTPConnectionPool,
    PathPreservingHTTPSConnectionPool,
    PathPreservingSOCKSConnectionPool,
    PathPreservingSOCKSHTTPSConnectionPool,
    ProxyRoatingTransport,
    Requester,
    _find_ssl_error,
    _format_ssl_error,
)
from lib.core.data import options
from lib.core.exceptions import RequestException
from lib.report.jsonl_response_store import JsonlResponseStore
from lib.report.response_store import ResponseArtifact


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

CHINESE_TEXT = "简体中文，繁體中文：你好世界"
ARABIC_TEXT = "العربية: مرحبا بالعالم"
INDIC_TEXT = (
    "हिन्दी: नमस्ते दुनिया | "
    "বাংলা: নমস্কার পৃথিবী | "
    "தமிழ்: வணக்கம் உலகம்"
)
MULTISCRIPT_TEXT = f"{CHINESE_TEXT} | {ARABIC_TEXT} | {INDIC_TEXT}"
ENCODED_RESPONSE_CASES = (
    (
        "encoded/normal-gzip",
        "utf-8",
        b"normal native gzip response",
    ),
    ("encoded/multiscript-utf8%1", "utf-8", MULTISCRIPT_TEXT.encode("utf-8")),
    (
        "encoded/chinese-gb18030%1",
        "gb18030",
        CHINESE_TEXT.encode("gb18030"),
    ),
    (
        "encoded/arabic-windows-1256%1",
        "windows-1256",
        ARABIC_TEXT.encode("cp1256"),
    ),
    (
        "encoded/indic-utf16%1",
        "utf-16",
        INDIC_TEXT.encode("utf-16"),
    ),
    ("encoded/unknown-binary%1", "x-dirsearch-unknown", bytes(range(256))),
)
ENCODED_RESPONSES_BY_TARGET = {
    f"/{path}".encode(): (charset, body, gzip.compress(body, mtime=0))
    for path, charset, body in ENCODED_RESPONSE_CASES
}
REQUEST_BODY_CASES = (
    ("ascii", b"name=plain&line=two\r\n"),
    ("utf-8", "value=\u00e9&city=\u6771\u4eac\r\n".encode("utf-8")),
    ("windows-1252", "value=\u00e9&currency=\u20ac\r\n".encode("cp1252")),
)


class RequestTargetTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class RequestTargetHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("content-length", "0"))
        self.server.request_bodies.append(self.rfile.read(content_length))
        self.do_GET()

    def do_GET(self):
        target = self.raw_requestline.split(b" ")[1]
        self.server.targets.append(target)
        self.server.proxy_authorizations.append(
            self.headers.get("Proxy-Authorization")
        )
        if target == b"/redirect":
            self.send_response(302)
            self.send_header("location", "/final")
            self.end_headers()
            return

        encoded_response = ENCODED_RESPONSES_BY_TARGET.get(target)
        if encoded_response is not None:
            charset, _, wire_body = encoded_response
            self.send_response(200)
            self.send_header(
                "content-type",
                f"text/plain; charset={charset}",
            )
            self.send_header("content-encoding", "gzip")
            self.send_header("content-length", str(len(wire_body)))
            self.end_headers()
            self.wfile.write(wire_body)
            return

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
        self.server.request_bodies = []
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

    @property
    def request_bodies(self):
        return self.server.request_bodies


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

    def __init__(self, error=None):
        self.closed = False
        self.error = error

    def iter_content(self, chunk_size):
        del chunk_size
        yield b"body"
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


class MultiChunkSyncResponse(DummySyncResponse):
    def __init__(self):
        super().__init__()
        self.read_second_chunk = False

    def iter_content(self, chunk_size):
        del chunk_size
        yield b"body"
        self.read_second_chunk = True
        yield b"should-not-be-read"


class BinaryMultiChunkSyncResponse(DummySyncResponse):
    headers = {
        "content-type": "application/octet-stream",
        "content-length": "8",
    }

    def iter_content(self, chunk_size):
        del chunk_size
        yield b"\x00abc"
        yield b"defg"


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

    def __init__(self, error=None):
        self.closed = False
        self.error = error

    async def aiter_bytes(self, chunk_size):
        del chunk_size
        yield b"body"
        if self.error:
            raise self.error

    async def aclose(self):
        self.closed = True


class MultiChunkAsyncResponse(DummyAsyncResponse):
    def __init__(self):
        super().__init__()
        self.read_second_chunk = False

    async def aiter_bytes(self, chunk_size):
        del chunk_size
        yield b"body"
        self.read_second_chunk = True
        yield b"should-not-be-read"


class BinaryMultiChunkAsyncResponse(DummyAsyncResponse):
    headers = {
        "content-type": "application/octet-stream",
        "content-length": "8",
    }

    async def aiter_bytes(self, chunk_size):
        del chunk_size
        yield b"\x00abc"
        yield b"defg"


class DummyAsyncSession:
    @staticmethod
    def build_request(*args, **kwargs):
        del args, kwargs
        return object()

    def __init__(self, response):
        self.response = response
        self.closed = False

    async def send(self, request, **kwargs):
        del request, kwargs
        return self.response

    async def aclose(self):
        self.closed = True


class RecordingAsyncTransport:
    def __init__(self, close_error=None):
        self.close_error = close_error
        self.close_calls = 0

    async def aclose(self):
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


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
    def test_sync_origin_407_remains_a_response_without_a_proxy(self):
        requester = Requester()
        requester.set_url("http://example.com/")
        response = DummySyncResponse()
        response.status_code = 407

        try:
            with patch.object(requester.session, "send", return_value=response):
                result = requester.request("admin")
        finally:
            requester.session.close()

        self.assertEqual(result.status, 407)

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
        requester._rate_limiter = RequestRateLimiter()
        requester._url = "https://example.com/"
        requester.proxy_cred = None
        requester.headers = {}
        requester.agents = []
        requester.session = DummySyncSession(DummySyncResponse())

        with patch.object(requester_module.time, "perf_counter", side_effect=[10.0, 10.25]):
            with patch.object(requester_module.logger, "info"):
                response = requester.request("admin")

        self.assertEqual(response.elapsed, 0.25, "Sync elapsed should measure the full streamed request lifecycle")


class TestRequesterRateLimiting(BaseRequesterTestCase):
    def test_unlimited_requests_do_not_spawn_timer_threads(self):
        requester = Requester()
        requester.set_url("http://example.com/")

        try:
            with (
                patch.object(
                    requester.session,
                    "send",
                    return_value=DummySyncResponse(),
                ),
                patch.object(requester_module.threading, "Timer") as timer,
            ):
                for path in ("first", "second", "third"):
                    requester.request(path)
        finally:
            requester.session.close()

        timer.assert_not_called()


class TestRequesterResponseCleanup(BaseRequesterTestCase):
    def test_sync_save_response_option_captures_full_binary_body(self):
        options["save_response"] = "responses"
        requester = Requester()
        requester.set_url("http://example.com/")
        origin_response = BinaryMultiChunkSyncResponse()

        try:
            with patch.object(
                requester.session, "send", return_value=origin_response
            ):
                response = requester.request("binary")
        finally:
            requester.session.close()

        self.assertEqual(response.body, b"\x00abcdefg")
        self.assertTrue(origin_response.closed)

    def test_sync_response_closes_after_early_bounded_parse(self):
        requester = Requester()
        requester.set_url("http://example.com/")
        origin_response = MultiChunkSyncResponse()

        try:
            with (
                patch.object(
                    requester.session, "send", return_value=origin_response
                ),
                patch.object(response_module, "MAX_RESPONSE_SIZE", 4),
            ):
                response = requester.request("admin")
        finally:
            requester.session.close()

        self.assertEqual(response.body, b"body")
        self.assertFalse(origin_response.read_second_chunk)
        self.assertTrue(origin_response.closed)

    def test_sync_response_closes_when_body_parse_fails(self):
        requester = Requester()
        requester.set_url("http://example.com/")
        origin_response = DummySyncResponse(
            requests.exceptions.ChunkedEncodingError("incomplete body")
        )

        try:
            with patch.object(
                requester.session, "send", return_value=origin_response
            ):
                with self.assertRaisesRegex(
                    RequestException, "Failed to read response body"
                ):
                    requester.request("admin")
        finally:
            requester.session.close()

        self.assertTrue(origin_response.closed)


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


class TestRequesterBodyPreservation(BaseRequesterTestCase):
    def test_sync_requester_preserves_data_file_encodings(self):
        options["http_method"] = "POST"

        with RequestTargetServer() as server:
            for name, body in REQUEST_BODY_CASES:
                with self.subTest(encoding=name):
                    options["data"] = body
                    requester = Requester()
                    requester.set_url(server.url)
                    try:
                        requester.request(name)
                    finally:
                        requester.close()

        self.assertEqual(
            server.request_bodies,
            [body for _, body in REQUEST_BODY_CASES],
        )


class TestRequesterProxyRouting(BaseRequesterTestCase):
    def test_proxy_managers_keep_path_preserving_connection_pools(self):
        requester = Requester()
        adapter = requester.session.get_adapter("http://")
        try:
            cases = (
                (
                    "http://proxy.invalid:8080",
                    PathPreservingHTTPConnectionPool,
                    PathPreservingHTTPSConnectionPool,
                ),
                (
                    "socks5h://proxy.invalid:1080",
                    PathPreservingSOCKSConnectionPool,
                    PathPreservingSOCKSHTTPSConnectionPool,
                ),
            )
            for proxy, http_pool, https_pool in cases:
                with self.subTest(proxy=proxy):
                    manager = adapter.proxy_manager_for(proxy)
                    self.assertIs(manager.pool_classes_by_scheme["http"], http_pool)
                    self.assertIs(
                        manager.pool_classes_by_scheme["https"], https_pool
                    )
        finally:
            requester.close()

    def test_proxy_scheme_never_bypasses_target_scheme(self):
        for proxy_scheme in ("http", "https"):
            proxy_url = f"{proxy_scheme}://proxy.invalid:8080"
            options["proxies"] = [proxy_url]

            for target_scheme in ("http", "https"):
                with self.subTest(
                    proxy_scheme=proxy_scheme,
                    target_scheme=target_scheme,
                ):
                    requester = Requester()
                    requester.set_url(f"{target_scheme}://origin.invalid/")

                    with (
                        patch.object(requester, "wait_for_rate_limit"),
                        patch.object(
                            requester.session,
                            "send",
                            return_value=DummySyncResponse(),
                        ) as send,
                    ):
                        requester.request("admin")

                    prepared_request = send.call_args.args[0]
                    proxies = send.call_args.kwargs["proxies"]
                    self.assertEqual(
                        requests.utils.select_proxy(prepared_request.url, proxies),
                        proxy_url,
                    )


class TestAsyncRequesterProxyRouting(
    BaseRequesterTestCase, IsolatedAsyncioTestCase
):
    async def test_requester_close_closes_every_rotating_proxy_transport(self):
        options["proxies"] = [
            "http://proxy-one.invalid:8080",
            "http://proxy-two.invalid:8080",
        ]
        children = [RecordingAsyncTransport(), RecordingAsyncTransport()]

        with patch(
            "lib.connection.requester.PathPreservingAsyncHTTPTransport",
            side_effect=children,
        ):
            requester = AsyncRequester()

        await requester.close()

        self.assertEqual([child.close_calls for child in children], [1, 1])

    async def test_rotating_proxy_close_continues_after_child_failure(self):
        failure = RuntimeError("first transport close failed")
        children = [
            RecordingAsyncTransport(close_error=failure),
            RecordingAsyncTransport(
                close_error=RuntimeError("second transport close failed")
            ),
            RecordingAsyncTransport(),
        ]
        transport = object.__new__(ProxyRoatingTransport)
        transport._transports = children

        with self.assertRaisesRegex(RuntimeError, "first transport close failed"):
            await transport.aclose()

        self.assertEqual([child.close_calls for child in children], [1, 1, 1])

    async def test_explicit_proxy_overrides_environment_proxy_rules(self):
        options["proxies"] = ["http://cli.invalid:8080"]
        environments = (
            (
                "uppercase",
                {
                    "HTTP_PROXY": "http://environment.invalid:9001",
                    "HTTPS_PROXY": "http://environment.invalid:9002",
                    "ALL_PROXY": "http://environment.invalid:9003",
                    "NO_PROXY": "bypass.invalid",
                },
            ),
            (
                "lowercase",
                {
                    "http_proxy": "http://environment.invalid:9001",
                    "https_proxy": "http://environment.invalid:9002",
                    "all_proxy": "http://environment.invalid:9003",
                    "no_proxy": "bypass.invalid",
                },
            ),
        )

        for environment_case, environment in environments:
            with self.subTest(environment_case=environment_case):
                with patch.dict(os.environ, environment, clear=True):
                    requester = AsyncRequester()

                try:
                    for url in (
                        "http://target.invalid/",
                        "https://target.invalid/",
                        "https://bypass.invalid/",
                    ):
                        with self.subTest(url=url):
                            selected = requester.session._transport_for_url(
                                httpx.URL(url)
                            )
                            self.assertIsInstance(selected, ProxyRoatingTransport)
                finally:
                    await requester.close()

    async def test_environment_proxy_remains_enabled_without_explicit_proxy(self):
        with RequestTargetServer() as environment_proxy:
            environment = {
                "HTTP_PROXY": environment_proxy.url,
                "HTTPS_PROXY": "",
                "ALL_PROXY": "",
                "NO_PROXY": "",
            }
            with patch.dict(os.environ, environment, clear=True):
                requester = AsyncRequester()

            requester.set_url("http://origin.invalid/")
            try:
                await requester.request("admin")
            finally:
                await requester.close()

        self.assertEqual(len(environment_proxy.targets), 1)

    async def test_replay_proxy_overrides_environment_proxy_rules(self):
        environment = {
            "HTTP_PROXY": "http://environment.invalid:9001",
            "HTTPS_PROXY": "http://environment.invalid:9002",
            "ALL_PROXY": "http://environment.invalid:9003",
            "NO_PROXY": "bypass.invalid",
        }
        with patch.dict(os.environ, environment, clear=True):
            requester = AsyncRequester()
            with patch.object(
                requester,
                "request",
                new=AsyncMock(return_value=object()),
            ) as request:
                await requester.replay_request(
                    "admin", proxy="http://replay.invalid:8080"
                )

        try:
            replay_session = request.await_args.args[1]
            for url in (
                "http://target.invalid/",
                "https://target.invalid/",
                "https://bypass.invalid/",
            ):
                with self.subTest(url=url):
                    selected = replay_session._transport_for_url(httpx.URL(url))
                    self.assertIsInstance(
                        selected,
                        PathPreservingAsyncHTTPTransport,
                    )
        finally:
            await requester.close()


class TestAsyncRequesterSSLHandling(BaseRequesterTestCase, IsolatedAsyncioTestCase):
    async def test_async_origin_407_remains_a_response_without_a_proxy(self):
        requester = AsyncRequester()
        requester.set_url("http://example.com/")
        response = DummyAsyncResponse()
        response.status_code = 407
        requester.session.send = AsyncMock(return_value=response)

        try:
            result = await requester.request("admin")
        finally:
            await requester.session.aclose()

        self.assertEqual(result.status, 407)

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
        requester._rate_limiter = RequestRateLimiter()
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


class TestAsyncRequesterResponseCleanup(
    BaseRequesterTestCase, IsolatedAsyncioTestCase
):
    async def test_async_save_response_option_captures_full_binary_body(self):
        options["save_response_jsonl"] = "responses.jsonl"
        requester = AsyncRequester()
        requester.set_url("http://example.com/")
        origin_response = BinaryMultiChunkAsyncResponse()
        requester.session.send = AsyncMock(return_value=origin_response)

        try:
            response = await requester.request("binary")
        finally:
            await requester.session.aclose()

        self.assertEqual(response.body, b"\x00abcdefg")
        self.assertTrue(origin_response.closed)

    async def test_async_response_closes_when_body_parse_fails(self):
        requester = AsyncRequester()
        requester.set_url("http://example.com/")
        origin_response = DummyAsyncResponse(
            httpx.RemoteProtocolError("incomplete body")
        )
        requester.session.send = AsyncMock(return_value=origin_response)

        try:
            with self.assertRaisesRegex(
                RequestException, "Failed to read response body"
            ):
                await requester.request("admin")
        finally:
            await requester.session.aclose()

        self.assertTrue(origin_response.closed)

    async def test_async_response_closes_after_early_bounded_parse(self):
        requester = AsyncRequester()
        requester.set_url("http://example.com/")
        origin_response = MultiChunkAsyncResponse()
        requester.session.send = AsyncMock(return_value=origin_response)

        try:
            with patch.object(response_module, "MAX_RESPONSE_SIZE", 4):
                response = await requester.request("admin")
        finally:
            await requester.session.aclose()

        self.assertEqual(response.body, b"body")
        self.assertFalse(origin_response.read_second_chunk)
        self.assertTrue(origin_response.closed)

    async def test_close_closes_primary_and_replay_sessions(self):
        requester = object.__new__(AsyncRequester)
        requester.session = DummyAsyncSession(DummyAsyncResponse())
        requester.replay_session = DummyAsyncSession(DummyAsyncResponse())

        await requester.close()

        self.assertTrue(requester.session.closed)
        self.assertTrue(requester.replay_session.closed)


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

    async def test_async_requester_preserves_data_file_encodings(self):
        options["http_method"] = "POST"

        with RequestTargetServer() as server:
            for name, body in REQUEST_BODY_CASES:
                with self.subTest(encoding=name):
                    options["data"] = body
                    requester = AsyncRequester()
                    requester.set_url(server.url)
                    try:
                        await requester.request(name)
                    finally:
                        await requester.close()

        self.assertEqual(
            server.request_bodies,
            [body for _, body in REQUEST_BODY_CASES],
        )

    async def test_async_requester_preserves_inline_unicode_text(self):
        options["http_method"] = "POST"
        options["data"] = "value=\u00e9"

        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                await requester.request("inline")
            finally:
                await requester.close()

        self.assertEqual(server.request_bodies, [options["data"].encode("utf-8")])


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

    def test_native_requester_follows_redirects(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        options["follow_redirects"] = True
        with RequestTargetServer() as server:
            results = list(backend.scan(server.url, ["redirect"]))

            self.assertEqual([error for _, _, error in results], [None])
            self.assertEqual(results[0][1].status, 200)
            self.assertEqual(server.targets, [b"/redirect", b"/final"])

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


class TestResponseStoreTransportIntegration(
    BaseRequesterTestCase, IsolatedAsyncioTestCase
):
    def _assert_jsonl_round_trip(self, responses):
        with tempfile.TemporaryDirectory() as directory:
            file_path = os.path.join(directory, "responses.jsonl")
            store = JsonlResponseStore(file_path)
            try:
                for response in responses:
                    store.save(ResponseArtifact.from_response(response))
            finally:
                store.close()

            with open(file_path, encoding="utf-8") as file_handle:
                records = [json.loads(line) for line in file_handle]

        self.assertEqual(len(records), len(ENCODED_RESPONSE_CASES))
        for record, (_, charset, expected_body) in zip(
            records, ENCODED_RESPONSE_CASES
        ):
            with self.subTest(charset=charset):
                self.assertEqual(
                    base64.b64decode(record["body"], validate=True),
                    expected_body,
                )
                self.assertEqual(
                    record["capturedBodyLength"], len(expected_body)
                )
                self.assertEqual(record["headers"]["content-encoding"], "gzip")
                self.assertEqual(
                    record["headers"]["content-type"],
                    f"text/plain; charset={charset}",
                )

    def _assert_response_bodies(self, responses):
        self.assertEqual(
            [response.body for response in responses],
            [body for _, _, body in ENCODED_RESPONSE_CASES],
        )

    def test_sync_gzip_multiscript_charsets_round_trip(self):
        options["save_response_jsonl"] = "responses.jsonl"
        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                responses = [
                    requester.request(path)
                    for path, _, _ in ENCODED_RESPONSE_CASES
                ]
            finally:
                requester.close()

        self._assert_response_bodies(responses)
        self._assert_jsonl_round_trip(responses)

    async def test_async_gzip_multiscript_charsets_round_trip(self):
        options["save_response_jsonl"] = "responses.jsonl"
        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                responses = []
                for path, _, _ in ENCODED_RESPONSE_CASES:
                    responses.append(await requester.request(path))
            finally:
                await requester.close()

        self._assert_response_bodies(responses)
        self._assert_jsonl_round_trip(responses)

    def test_native_gzip_multiscript_charsets_round_trip(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            results = list(
                backend.scan(
                    server.url,
                    [path for path, _, _ in ENCODED_RESPONSE_CASES],
                )
            )

        self.assertEqual(len(results), len(ENCODED_RESPONSE_CASES))
        self.assertEqual([error for _, _, error in results], [None] * len(results))
        responses = [response for _, response, _ in results]
        self.assertTrue(all(response is not None for response in responses))
        self._assert_response_bodies(responses)
        self._assert_jsonl_round_trip(responses)
