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
import hashlib
import http.server
import json
import os
import re
import socket
import ssl
import socketserver
import tempfile
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import httpx
import requests
from requests.packages import urllib3

from lib.connection import requester as requester_module
from lib.connection import response as response_module
from lib.connection.native import NativeHTTPBackend, NativeRequester
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
from lib.core.settings import MAX_REDIRECTS
from lib.controller.controller import Controller
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
    ("encoded/ascii-gzip", "ascii", b"plain ascii response"),
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
AUTHENTICATION_CASES = (
    ("basic", "user:password", "Basic dXNlcjpwYXNzd29yZA=="),
    ("bearer", "opaque-token", "Bearer opaque-token"),
    ("jwt", "header.payload.signature", "Bearer header.payload.signature"),
)


def valid_digest_authorization(
    authorization: str,
    method: str,
    username: str,
    password: str,
) -> bool:
    if not authorization.startswith("Digest "):
        return False
    fields = requests.utils.parse_dict_header(authorization[7:])
    required = {"realm", "nonce", "uri", "response", "cnonce", "nc", "qop"}
    if not required.issubset(fields):
        return False
    ha1 = hashlib.md5(
        f"{username}:{fields['realm']}:{password}".encode()
    ).hexdigest()
    ha2 = hashlib.md5(f"{method}:{fields['uri']}".encode()).hexdigest()
    expected = hashlib.md5(
        (
            f"{ha1}:{fields['nonce']}:{fields['nc']}:"
            f"{fields['cnonce']}:{fields['qop']}:{ha2}"
        ).encode()
    ).hexdigest()
    return fields["username"] == username and fields["response"] == expected


class RequestTargetTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class RequestTargetHandler(http.server.BaseHTTPRequestHandler):
    def _handle_with_body(self):
        content_length = int(self.headers.get("content-length", "0"))
        self.server.request_bodies.append(self.rfile.read(content_length))
        self.do_GET()

    def do_POST(self):
        self._handle_with_body()

    def do_PUT(self):
        self._handle_with_body()

    def do_PATCH(self):
        self._handle_with_body()

    def do_DELETE(self):
        self._handle_with_body()

    def do_GET(self):
        target = self.raw_requestline.split(b" ")[1]
        self.server.request_methods.append(self.command)
        self.server.targets.append(target)
        self.server.authorizations.append(self.headers.get("Authorization"))
        self.server.cookies.append(self.headers.get("Cookie"))
        self.server.proxy_authorizations.append(
            self.headers.get("Proxy-Authorization")
        )
        route_target = target
        if target.startswith((b"http://", b"https://")):
            parsed_target = urlsplit(target.decode("ascii"))
            route_target = parsed_target.path.encode("ascii")
            if parsed_target.query:
                route_target += b"?" + parsed_target.query.encode("ascii")

        attempt = self.server.target_counts.get(route_target, 0) + 1
        self.server.target_counts[route_target] = attempt
        if route_target in (
            b"/cookie/retry-body",
            b"/cookie/retry-body%1",
        ):
            if attempt == 1:
                self.send_response(200)
                self.send_header("set-cookie", "retry=native; Path=/")
                self.send_header("content-length", "4")
                self.end_headers()
                self.wfile.write(b"no")
                self.wfile.flush()
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_WR)
                return
            body = b"cookie accepted"
            self.send_response(
                200 if "retry=native" in (self.headers.get("cookie") or "") else 401
            )
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route_target in (b"/retry-body", b"/retry-body%1") and attempt == 1:
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", "4")
            self.end_headers()
            self.wfile.write(b"no")
            self.wfile.flush()
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_WR)
            return

        if route_target == b"/cookie/set":
            body = b"cookie stored"
            self.send_response(200)
            self.send_header("set-cookie", "session=native; Path=/")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if route_target == b"/cookie/scoped/set":
            body = b"scoped cookie stored"
            self.send_response(200)
            self.send_header("set-cookie", "scoped=native; Path=/cookie/scoped/")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if route_target in (b"/cookie/secure-set", b"/cookie/secure-set%1"):
            body = b"secure cookie offered"
            self.send_response(200)
            self.send_header("set-cookie", "secure=native; Secure; Path=/")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if route_target == b"/cookie/fixed-seed":
            body = b"jar cookie stored"
            self.send_response(200)
            self.send_header("set-cookie", "jar=native; Path=/")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        cookie_to_set = None
        if route_target == b"/cookie/path-root-set":
            cookie_to_set = "id=root; Path=/"
        elif route_target == b"/cookie/scoped/path-set":
            cookie_to_set = "id=scoped; Path=/cookie/scoped/"
        elif route_target == b"/cookie/domain-super-set":
            cookie_to_set = "super=native; Domain=com; Path=/"
        elif route_target == b"/cookie/domain-parent-set":
            cookie_to_set = "parent=native; Domain=example.com; Path=/"
        if cookie_to_set is not None:
            body = b"cookie offered"
            self.send_response(200)
            self.send_header("set-cookie", cookie_to_set)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if route_target == b"/cookie/redirect":
            self.send_response(302)
            self.send_header("location", "/cookie/redirected")
            self.send_header("set-cookie", "redirect=native; Path=/")
            self.send_header("content-length", "0")
            self.end_headers()
            return

        if route_target == b"/cookie/scoped/redirect-outside":
            self.send_response(302)
            self.send_header("location", "/cookie/outside")
            self.send_header("content-length", "0")
            self.end_headers()
            return

        if route_target == b"/cookie/fixed-redirect":
            self.send_response(302)
            self.send_header("location", "/cookie/fixed-final")
            self.send_header("content-length", "0")
            self.end_headers()
            return

        required_cookie = None
        if route_target in (b"/cookie/required", b"/cookie/required%1"):
            required_cookie = "session=native"
        elif route_target in (
            b"/cookie/scoped/required",
            b"/cookie/scoped/required%1",
        ):
            required_cookie = "scoped=native"
        elif route_target == b"/cookie/redirected":
            required_cookie = "redirect=native"
        elif route_target == b"/cookie/fixed-final":
            required_cookie = "jar=native"
        if required_cookie is not None:
            body = b"cookie accepted"
            self.send_response(
                200 if required_cookie in (self.headers.get("cookie") or "") else 401
            )
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if route_target == b"/redirect":
            self.send_response(302)
            self.send_header("location", "/final")
            self.end_headers()
            return

        if route_target == b"/external-redirect":
            self.send_response(302)
            self.send_header("location", self.server.external_redirect_url)
            self.end_headers()
            return

        if route_target == b"/digest-auth":
            authorization = self.headers.get("Authorization", "")
            if not valid_digest_authorization(
                authorization,
                self.command,
                "digest-user",
                "digest-password",
            ):
                self.send_response(401)
                self.send_header(
                    "www-authenticate",
                    'Digest realm="dirsearch-test", nonce="abcdef0123456789", '
                    'algorithm=MD5, qop="auth"',
                )
                self.send_header("content-length", "0")
                self.end_headers()
                return

        if route_target == b"/malformed-digest-auth":
            self.send_response(401)
            self.send_header("www-authenticate", 'Digest realm="missing-nonce"')
            self.send_header("content-length", "0")
            self.end_headers()
            return

        if route_target.startswith(b"/redirect-count/"):
            redirects_left = int(route_target.rsplit(b"/", 1)[1])
            if redirects_left:
                self.send_response(302)
                self.send_header(
                    "location",
                    f"/redirect-count/{redirects_left - 1}",
                )
                self.end_headers()
                return

        redirect_chain = {
            b"/redirect-chain/start?first=%2F": "middle?step=%2F",
            b"/redirect-chain/middle?step=%2F": "final?done=%2F#ignored",
        }
        if route_target in redirect_chain:
            self.send_response(302)
            self.send_header("location", redirect_chain[route_target])
            self.end_headers()
            return

        if route_target.lower() == b"/digest-auth%3d..%1\\*":
            if self.headers.get("Authorization") is None:
                self.send_response(401)
                self.send_header(
                    "www-authenticate",
                    'Digest realm="dirsearch-test", nonce="abcdef0123456789", '
                    'algorithm=MD5, qop="auth"',
                )
            else:
                self.send_response(302)
                self.send_header("location", "/final")
            self.send_header("content-length", "0")
            self.end_headers()
            return

        if target == b"/repeated-headers":
            body = b"repeated headers"
            self.send_response(200)
            self.send_header("x-repeat", "one")
            self.send_header("x-repeat", "two")
            self.send_header("set-cookie", "first=1; Path=/")
            self.send_header("set-cookie", "second=2; Path=/")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if target == b"/regex-backreference":
            body = b"repeat repeat"
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
        self.server.authorizations = []
        self.server.cookies = []
        self.server.proxy_authorizations = []
        self.server.request_bodies = []
        self.server.request_methods = []
        self.server.target_counts = {}
        self.server.external_redirect_url = None
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
    def localhost_url(self):
        _, port = self.server.server_address
        return f"http://localhost:{port}/"

    @property
    def targets(self):
        return self.server.targets

    @property
    def proxy_authorizations(self):
        return self.server.proxy_authorizations

    @property
    def authorizations(self):
        return self.server.authorizations

    @property
    def cookies(self):
        return self.server.cookies

    @property
    def request_bodies(self):
        return self.server.request_bodies

    @property
    def request_methods(self):
        return self.server.request_methods

    @property
    def target_counts(self):
        return self.server.target_counts


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
    def prepare_request(self, request):
        self.request_headers = dict(request.headers)
        return SimpleNamespace(url=request.url)

    def __init__(self, response):
        self.response = response
        self.request_headers = None

    def send(self, prep, **kwargs):
        del prep, kwargs
        return self.response


class DummyAsyncResponse:
    status_code = 200
    headers = httpx.Headers({"content-type": "text/plain"})
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
    headers = httpx.Headers(
        {
            "content-type": "application/octet-stream",
            "content-length": "8",
        }
    )

    async def aiter_bytes(self, chunk_size):
        del chunk_size
        yield b"\x00abc"
        yield b"defg"


class DummyAsyncSession:
    def build_request(self, *args, **kwargs):
        del args
        self.request_headers = dict(kwargs["headers"])
        return object()

    def __init__(self, response):
        self.response = response
        self.closed = False
        self.request_headers = None

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

    def test_sync_wrapped_dns_failure_uses_dns_message(self):
        requester = Requester()
        requester.set_url("http://example.com/")
        resolution_error = urllib3.exceptions.NameResolutionError(
            "example.com",
            None,
            socket.gaierror(socket.EAI_NONAME, "Name or service not known"),
        )
        error = requests.exceptions.ConnectionError(
            urllib3.exceptions.MaxRetryError(
                None,
                "/admin",
                resolution_error,
            )
        )

        with patch.object(requester.session, "send", side_effect=error):
            with self.assertRaises(RequestException) as ctx:
                requester.request("admin")

        self.assertEqual(str(ctx.exception), "Couldn't resolve DNS")

    def test_sync_invalid_url_uses_specific_message(self):
        requester = Requester()
        requester.set_url("http://example.com/")

        with patch.object(
            requester.session,
            "send",
            side_effect=requests.exceptions.InvalidURL("bad target"),
        ):
            with self.assertRaises(RequestException) as ctx:
                requester.request("admin")

        self.assertEqual(
            str(ctx.exception),
            "Invalid URL: http://example.com/admin",
        )

    def test_sync_invalid_proxy_url_uses_specific_message(self):
        requester = Requester()
        requester.set_url("http://example.com/")

        with patch.object(
            requester.session,
            "send",
            side_effect=requests.exceptions.InvalidProxyURL("bad proxy"),
        ):
            with self.assertRaises(RequestException) as ctx:
                requester.request("admin", proxy="http://proxy.invalid")

        self.assertEqual(
            str(ctx.exception),
            "Invalid proxy URL: http://proxy.invalid",
        )

    def test_sync_connection_error_uses_specific_message(self):
        requester = Requester()
        requester.set_url("http://example.com/")

        with patch.object(
            requester.session,
            "send",
            side_effect=requests.exceptions.ConnectionError(
                "connection refused"
            ),
        ):
            with self.assertRaises(RequestException) as ctx:
                requester.request("admin")

        self.assertEqual(str(ctx.exception), "Cannot connect to: example.com")

    def test_sync_error_class_names_in_unrelated_text_stay_generic(self):
        requester = Requester()
        requester.set_url("http://example.com/")

        for message in ("InvalidURL", "InvalidProxyURL", "ConnectionError"):
            with self.subTest(message=message):
                with patch.object(
                    requester.session,
                    "send",
                    side_effect=RuntimeError(message),
                ):
                    with self.assertRaises(RequestException) as ctx:
                        requester.request("admin")

                self.assertEqual(
                    str(ctx.exception),
                    "There was a problem in the request to: "
                    "http://example.com/admin",
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
    def test_random_agent_is_request_local(self):
        requester = object.__new__(Requester)
        requester._rate_limiter = RequestRateLimiter()
        requester._url = "https://example.com/"
        requester._query = ""
        requester.proxy_cred = None
        requester.headers = {"x-base": "preserved"}
        requester.agents = ["random-agent"]
        requester.session = DummySyncSession(DummySyncResponse())

        with (
            patch.object(
                requester_module.random,
                "choice",
                side_effect=[IndexError, "random-agent"],
            ),
            patch.object(requester_module.logger, "info"),
        ):
            requester.request("admin")

        self.assertEqual(requester.headers, {"x-base": "preserved"})
        self.assertEqual(
            requester.session.request_headers["user-agent"],
            "random-agent",
        )

    def test_request_elapsed_includes_stream_read(self):
        requester = object.__new__(Requester)
        requester._rate_limiter = RequestRateLimiter()
        requester._url = "https://example.com/"
        requester._query = ""
        requester.proxy_cred = None
        requester.headers = {}
        requester.agents = []
        requester.session = DummySyncSession(DummySyncResponse())

        with patch.object(requester_module.time, "perf_counter", side_effect=[10.0, 10.25]):
            with patch.object(requester_module.logger, "info"):
                response = requester.request("admin")

        self.assertEqual(response.elapsed, 0.25, "Sync elapsed should measure the full streamed request lifecycle")

    def test_retry_elapsed_reports_only_the_successful_attempt(self):
        requester = object.__new__(Requester)
        requester._rate_limiter = RequestRateLimiter()
        requester._url = "https://example.com/"
        requester._query = ""
        requester.proxy_cred = None
        requester.headers = {}
        requester.agents = []
        failed = DummySyncResponse(
            requests.exceptions.ChunkedEncodingError("incomplete body")
        )
        successful = DummySyncResponse()
        requester.session = DummySyncSession(successful)

        with (
            patch.dict(options, {"max_retries": 1}),
            patch.object(
                requester.session,
                "send",
                side_effect=[failed, successful],
            ),
            patch.object(
                requester_module.time,
                "perf_counter",
                side_effect=[1.0, 10.0, 10.25],
            ),
            patch.object(requester_module.logger, "info"),
            patch.object(requester_module.logger, "exception"),
        ):
            response = requester.request("admin")

        self.assertEqual(response.elapsed, 0.25)
        self.assertTrue(failed.closed)
        self.assertTrue(successful.closed)


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

    def test_sync_requester_uses_redirect_target_after_raw_initial_target(self):
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                response = requester.request("redirect")
            finally:
                requester.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.history, [f"{server.url}redirect"])
            self.assertEqual(server.targets, [b"/redirect", b"/final"])

    def test_sync_requester_follows_shared_redirect_limit(self):
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                response = requester.request(
                    f"redirect-count/{MAX_REDIRECTS}"
                )
            finally:
                requester.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(len(response.history), MAX_REDIRECTS)

    def test_sync_requester_rejects_redirects_above_shared_limit(self):
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                with self.assertRaisesRegex(
                    RequestException,
                    "Too many redirects",
                ):
                    requester.request(f"redirect-count/{MAX_REDIRECTS + 1}")
            finally:
                requester.close()

    def test_sync_requester_retries_response_body_read_failures(self):
        options["max_retries"] = 1

        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                response = requester.request("retry-body")
            finally:
                requester.close()

            self.assertEqual(response.body, b"ok")
            self.assertEqual(server.target_counts[b"/retry-body"], 2)


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


class TestRequesterAuthenticationParity(BaseRequesterTestCase):
    def test_sync_requester_sends_supported_preemptive_authentication(self):
        with RequestTargetServer() as server:
            for auth_type, credential, expected in AUTHENTICATION_CASES:
                with self.subTest(auth_type=auth_type):
                    options["auth"] = credential
                    options["auth_type"] = auth_type
                    requester = Requester()
                    requester.set_url(server.url)
                    try:
                        requester.request(auth_type)
                    finally:
                        requester.close()
                    self.assertEqual(server.authorizations[-1], expected)

    def test_sync_requester_answers_digest_challenge(self):
        options["auth"] = "digest-user:digest-password"
        options["auth_type"] = "digest"

        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                response = requester.request("digest-auth")
            finally:
                requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(server.authorizations[0], None)
        self.assertTrue(
            valid_digest_authorization(
                server.authorizations[1],
                "GET",
                "digest-user",
                "digest-password",
            )
        )

    def test_sync_requester_strips_authentication_on_cross_origin_redirect(self):
        options["auth"] = "redirect-token"
        options["auth_type"] = "bearer"
        options["follow_redirects"] = True

        with RequestTargetServer() as origin, RequestTargetServer() as destination:
            origin.server.external_redirect_url = destination.url + "final"
            requester = Requester()
            requester.set_url(origin.url)
            try:
                response = requester.request("external-redirect")
            finally:
                requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(origin.authorizations, ["Bearer redirect-token"])
        self.assertEqual(destination.authorizations, [None])


class TestAsyncRequesterAuthenticationParity(
    BaseRequesterTestCase, IsolatedAsyncioTestCase
):
    async def test_async_requester_sends_supported_preemptive_authentication(self):
        with RequestTargetServer() as server:
            for auth_type, credential, expected in AUTHENTICATION_CASES:
                with self.subTest(auth_type=auth_type):
                    options["auth"] = credential
                    options["auth_type"] = auth_type
                    requester = AsyncRequester()
                    requester.set_url(server.url)
                    try:
                        await requester.request(auth_type)
                    finally:
                        await requester.close()
                    self.assertEqual(server.authorizations[-1], expected)

    async def test_async_requester_answers_digest_challenge(self):
        options["auth"] = "digest-user:digest-password"
        options["auth_type"] = "digest"

        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                response = await requester.request("digest-auth")
            finally:
                await requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(server.authorizations[0], None)
        self.assertTrue(
            valid_digest_authorization(
                server.authorizations[1],
                "GET",
                "digest-user",
                "digest-password",
            )
        )

    async def test_async_requester_strips_authentication_on_cross_origin_redirect(self):
        options["auth"] = "redirect-token"
        options["auth_type"] = "bearer"
        options["follow_redirects"] = True

        with RequestTargetServer() as origin, RequestTargetServer() as destination:
            origin.server.external_redirect_url = destination.url + "final"
            requester = AsyncRequester()
            requester.set_url(origin.url)
            try:
                response = await requester.request("external-redirect")
            finally:
                await requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(origin.authorizations, ["Bearer redirect-token"])
        self.assertEqual(destination.authorizations, [None])


class TestRequesterProxyRouting(BaseRequesterTestCase):
    def test_replay_proxy_preserves_auth_and_cookies(self):
        options["auth"] = "sync-user:sync-password"
        options["auth_type"] = "basic"
        requester = Requester()
        requester.set_url("http://example.com/")
        requester.session.cookies.set(
            "primary",
            "sync",
            domain="example.com",
            path="/",
        )

        try:
            with patch.object(
                requester.session,
                "send",
                return_value=DummySyncResponse(),
            ) as send:
                requester.request(
                    "admin",
                    proxy="http://replay.invalid:8080",
                )
        finally:
            requester.close()

        prepared_request = send.call_args.args[0]
        self.assertEqual(
            prepared_request.headers["Authorization"],
            "Basic c3luYy11c2VyOnN5bmMtcGFzc3dvcmQ=",
        )
        self.assertEqual(prepared_request.headers["Cookie"], "primary=sync")

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
    async def test_socks5_proxies_build_async_socks_transports(self):
        for scheme in ("socks5", "socks5h"):
            with self.subTest(scheme=scheme):
                options["proxies"] = [f"{scheme}://proxy.invalid:1080"]
                requester = AsyncRequester()
                try:
                    transport = requester.session._transport_for_url(
                        httpx.URL("https://target.invalid/")
                    )
                    self.assertIsInstance(transport, ProxyRoatingTransport)
                    self.assertEqual(
                        type(transport._transports[0]._pool).__name__,
                        "AsyncSOCKSProxy",
                    )
                finally:
                    await requester.close()

    async def test_only_replay_uses_proxy_with_matching_auth_and_cookies(self):
        options["auth"] = "first-user:first-password"
        options["auth_type"] = "basic"
        with RequestTargetServer() as origin, RequestTargetServer() as replay_proxy:
            requester = AsyncRequester()
            requester.set_url(origin.url)
            requester.session.cookies.set(
                "primary",
                "first",
                domain="127.0.0.1",
                path="/",
            )

            try:
                await requester.request("first")
                await requester.replay_request(
                    "first",
                    proxy=replay_proxy.url,
                )

                requester.set_auth("bearer", "second-token")
                requester.session.cookies.clear()
                requester.session.cookies.set(
                    "primary",
                    "second",
                    domain="127.0.0.1",
                    path="/",
                )
                requester.replay_session.cookies.set(
                    "stale",
                    "replay-only",
                    domain="127.0.0.1",
                    path="/",
                )
                await requester.request("second")
                await requester.replay_request(
                    "second",
                    proxy=replay_proxy.url,
                )
            finally:
                await requester.close()

        self.assertEqual(origin.targets, [b"/first", b"/second"])
        self.assertEqual(
            replay_proxy.targets,
            [
                f"{origin.url}first".encode(),
                f"{origin.url}second".encode(),
            ],
        )
        self.assertEqual(
            origin.authorizations,
            [
                "Basic Zmlyc3QtdXNlcjpmaXJzdC1wYXNzd29yZA==",
                "Bearer second-token",
            ],
        )
        self.assertEqual(replay_proxy.authorizations, origin.authorizations)
        self.assertEqual(
            origin.cookies,
            ["primary=first", "primary=second"],
        )
        self.assertEqual(replay_proxy.cookies, origin.cookies)

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
        with patch("httpx._utils.getproxies", return_value={}):
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

    async def test_async_connect_error_with_dns_cause_uses_dns_message(self):
        requester = AsyncRequester()
        requester.set_url("https://example.com/")
        error = _with_cause(
            httpx.ConnectError("lookup failed"),
            socket.gaierror(socket.EAI_NONAME, "Name or service not known"),
        )
        requester.session.send = AsyncMock(side_effect=error)

        with self.assertRaises(RequestException) as ctx:
            await requester.request("admin")

        self.assertEqual(str(ctx.exception), "Couldn't resolve DNS")

    async def test_async_legacy_dns_message_remains_supported(self):
        requester = AsyncRequester()
        requester.set_url("https://example.com/")
        requester.session.send = AsyncMock(
            side_effect=httpx.ConnectError(
                "[Errno -2] Name or service not known"
            )
        )

        with self.assertRaises(RequestException) as ctx:
            await requester.request("admin")

        self.assertEqual(str(ctx.exception), "Couldn't resolve DNS")

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
    async def test_random_agent_is_request_local(self):
        requester = object.__new__(AsyncRequester)
        requester._rate_limiter = RequestRateLimiter()
        requester._url = "https://example.com/"
        requester._query = ""
        requester.proxy_cred = None
        requester.headers = {"x-base": "preserved"}
        requester.agents = ["random-agent"]
        requester._inherited_proxy_transports = set()
        requester.session = DummyAsyncSession(DummyAsyncResponse())

        with (
            patch.object(
                requester_module.random,
                "choice",
                return_value="random-agent",
            ),
            patch.object(requester_module.logger, "info"),
        ):
            await requester.request("admin")

        self.assertEqual(requester.headers, {"x-base": "preserved"})
        self.assertEqual(
            requester.session.request_headers["user-agent"],
            "random-agent",
        )

    async def test_request_elapsed_waits_for_stream_close(self):
        requester = object.__new__(AsyncRequester)
        requester._rate_limiter = RequestRateLimiter()
        requester._url = "https://example.com/"
        requester._query = ""
        requester.proxy_cred = None
        requester.headers = {}
        requester.agents = []
        requester.session = DummyAsyncSession(DummyAsyncResponse())

        with patch.object(requester_module.time, "perf_counter", side_effect=[20.0, 20.5]):
            with patch.object(requester_module.logger, "info"):
                response = await requester.request("admin")

        self.assertEqual(response.elapsed, 0.5, "Async elapsed should measure the full streamed request lifecycle")
        self.assertTrue(requester.session.response.closed, "Streamed async responses should be closed before elapsed is used")

    async def test_retry_elapsed_reports_only_the_successful_attempt(self):
        requester = object.__new__(AsyncRequester)
        requester._rate_limiter = RequestRateLimiter()
        requester._url = "https://example.com/"
        requester._query = ""
        requester.proxy_cred = None
        requester.headers = {}
        requester.agents = []
        requester._inherited_proxy_transports = set()
        failed = DummyAsyncResponse(httpx.ReadError("incomplete body"))
        successful = DummyAsyncResponse()
        requester.session = DummyAsyncSession(successful)
        requester.session.send = AsyncMock(side_effect=[failed, successful])

        with (
            patch.dict(options, {"max_retries": 1}),
            patch.object(
                requester_module.time,
                "perf_counter",
                side_effect=[1.0, 10.0, 10.25],
            ),
            patch.object(requester_module.logger, "info"),
            patch.object(requester_module.logger, "exception"),
        ):
            response = await requester.request("admin")

        self.assertEqual(response.elapsed, 0.25)
        self.assertTrue(failed.closed)
        self.assertTrue(successful.closed)


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

    async def test_async_requester_uses_redirect_target_after_raw_initial_target(self):
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                response = await requester.request("redirect")
            finally:
                await requester.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.history, [f"{server.url}redirect"])
            self.assertEqual(server.targets, [b"/redirect", b"/final"])

    async def test_async_requester_preserves_multi_hop_redirect_history(self):
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                response = await requester.request(
                    "redirect-chain/start?first=%2F"
                )
            finally:
                await requester.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(
                response.history,
                [
                    f"{server.url}redirect-chain/start?first=%2F",
                    f"{server.url}redirect-chain/middle?step=%2F",
                ],
            )
            self.assertEqual(
                server.targets,
                [
                    b"/redirect-chain/start?first=%2F",
                    b"/redirect-chain/middle?step=%2F",
                    b"/redirect-chain/final?done=%2F",
                ],
            )

    async def test_async_requester_follows_shared_redirect_limit(self):
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                response = await requester.request(
                    f"redirect-count/{MAX_REDIRECTS}"
                )
            finally:
                await requester.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(len(response.history), MAX_REDIRECTS)

    async def test_async_requester_rejects_redirects_above_shared_limit(self):
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                with self.assertRaisesRegex(
                    RequestException,
                    "Too many redirects",
                ):
                    await requester.request(
                        f"redirect-count/{MAX_REDIRECTS + 1}"
                    )
            finally:
                await requester.close()

    async def test_async_requester_retries_response_body_read_failures(self):
        options["max_retries"] = 1

        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                response = await requester.request("retry-body")
            finally:
                await requester.close()

            self.assertEqual(response.body, b"ok")
            self.assertEqual(server.target_counts[b"/retry-body"], 2)

    async def test_async_requester_follows_redirect_with_dns_override(self):
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            parsed_url = urlsplit(server.url)
            forced_host = "redirect.invalid"
            forced_url = f"http://{forced_host}:{parsed_url.port}/"
            requester = AsyncRequester()
            requester.set_ip(forced_host, parsed_url.port, "127.0.0.1")
            requester.set_url(forced_url)
            try:
                response = await requester.request("redirect")
            finally:
                await requester.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.history, [f"{forced_url}redirect"])
            self.assertEqual(server.targets, [b"/redirect", b"/final"])

    async def test_async_requester_keeps_raw_target_for_auth_retry_then_redirect(self):
        options["auth"] = "user:password"
        options["auth_type"] = "digest"
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                response = await requester.request("digest-auth%3d..%1\\*")
            finally:
                await requester.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(
                server.targets,
                [
                    b"/digest-auth%3d..%1\\*",
                    b"/digest-auth%3d..%1\\*",
                    b"/final",
                ],
            )
            self.assertIsNone(server.authorizations[0])
            self.assertTrue(server.authorizations[1].startswith("Digest "))

    async def test_async_requester_does_not_follow_redirects_when_disabled(self):
        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                response = await requester.request("redirect")
            finally:
                await requester.close()

            self.assertEqual(response.status, 302)
            self.assertEqual(response.redirect, "/final")
            self.assertEqual(response.history, [])
            self.assertEqual(server.targets, [b"/redirect"])

    async def test_async_proxy_uses_redirect_target_after_raw_initial_target(self):
        options["follow_redirects"] = True

        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            requester = AsyncRequester()
            requester.set_url("http://origin.invalid/")
            try:
                response = await requester.request("redirect")
            finally:
                await requester.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(
                response.history,
                ["http://origin.invalid/redirect"],
            )
            self.assertEqual(
                proxy.targets,
                [
                    b"http://origin.invalid/redirect",
                    b"http://origin.invalid/final",
                ],
            )

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


class TestCookieSessionParity(BaseRequesterTestCase, IsolatedAsyncioTestCase):
    def test_sync_requester_reuses_response_cookies(self):
        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                requester.request("cookie/set")
                response = requester.request("cookie/required")
            finally:
                requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(server.cookies, [None, "session=native"])

    async def test_async_requester_reuses_response_cookies(self):
        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                await requester.request("cookie/set")
                response = await requester.request("cookie/required")
            finally:
                await requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(server.cookies, [None, "session=native"])

    def test_sync_retry_reuses_cookie_from_truncated_response(self):
        options["max_retries"] = 1
        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                response = requester.request("cookie/retry-body")
            finally:
                requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(server.cookies, [None, "retry=native"])

    async def test_async_retry_reuses_cookie_from_truncated_response(self):
        options["max_retries"] = 1
        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                response = await requester.request("cookie/retry-body")
            finally:
                await requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(server.cookies, [None, "retry=native"])

    def test_sync_fixed_cookie_yields_to_jar_on_redirect(self):
        options["headers"] = {"Cookie": "fixed=manual"}
        options["follow_redirects"] = True
        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                requester.request("cookie/fixed-seed")
                response = requester.request("cookie/fixed-redirect")
            finally:
                requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(
            server.cookies,
            ["fixed=manual", "fixed=manual", "jar=native"],
        )

    async def test_async_fixed_cookie_yields_to_jar_on_redirect(self):
        options["headers"] = {"Cookie": "fixed=manual"}
        options["follow_redirects"] = True
        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                await requester.request("cookie/fixed-seed")
                response = await requester.request("cookie/fixed-redirect")
            finally:
                await requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(
            server.cookies,
            ["fixed=manual", "fixed=manual", "jar=native"],
        )

    def test_sync_does_not_send_secure_cookie_over_loopback_http(self):
        for host in ("address", "localhost"):
            with self.subTest(host=host), RequestTargetServer() as server:
                requester = Requester()
                requester.set_url(
                    server.url if host == "address" else server.localhost_url
                )
                try:
                    requester.request("cookie/secure-set")
                    requester.request("cookie/secure-check")
                finally:
                    requester.close()

                self.assertEqual(server.cookies, [None, None])

    async def test_async_does_not_send_secure_cookie_over_loopback_http(self):
        for host in ("address", "localhost"):
            with self.subTest(host=host), RequestTargetServer() as server:
                requester = AsyncRequester()
                requester.set_url(
                    server.url if host == "address" else server.localhost_url
                )
                try:
                    await requester.request("cookie/secure-set")
                    await requester.request("cookie/secure-check")
                finally:
                    await requester.close()

                self.assertEqual(server.cookies, [None, None])

    def test_sync_cookie_header_uses_longest_path_first(self):
        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                requester.request("cookie/path-root-set")
                requester.request("cookie/scoped/path-set")
                requester.request("cookie/scoped/path-check")
            finally:
                requester.close()

        self.assertEqual(
            server.cookies,
            [None, "id=root", "id=scoped; id=root"],
        )

    async def test_async_cookie_header_uses_longest_path_first(self):
        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                await requester.request("cookie/path-root-set")
                await requester.request("cookie/scoped/path-set")
                await requester.request("cookie/scoped/path-check")
            finally:
                await requester.close()

        self.assertEqual(
            server.cookies,
            [None, "id=root", "id=scoped; id=root"],
        )

    def test_sync_cookie_domain_rules_match_existing_session_behavior(self):
        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            requester = Requester()
            try:
                requester.set_url("http://foo.com/")
                requester.request("cookie/domain-super-set")
                requester.set_url("http://bar.com/")
                requester.request("cookie/domain-check")
            finally:
                requester.close()
        self.assertEqual(proxy.cookies, [None, None])

        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            requester = Requester()
            try:
                requester.set_url("http://api.example.com/")
                requester.request("cookie/domain-parent-set")
                requester.set_url("http://www.example.com/")
                requester.request("cookie/domain-check")
            finally:
                requester.close()
        self.assertEqual(proxy.cookies, [None, "parent=native"])

    async def test_async_cookie_domain_rules_match_existing_session_behavior(self):
        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            requester = AsyncRequester()
            try:
                requester.set_url("http://foo.com/")
                await requester.request("cookie/domain-super-set")
                requester.set_url("http://bar.com/")
                await requester.request("cookie/domain-check")
            finally:
                await requester.close()
        self.assertEqual(proxy.cookies, [None, None])

        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            requester = AsyncRequester()
            try:
                requester.set_url("http://api.example.com/")
                await requester.request("cookie/domain-parent-set")
                requester.set_url("http://www.example.com/")
                await requester.request("cookie/domain-check")
            finally:
                await requester.close()
        self.assertEqual(proxy.cookies, [None, "parent=native"])


class TestNativeRequesterPathPreservation(BaseRequesterTestCase):
    def native_requester_or_skip(self):
        requester = NativeRequester()
        try:
            requester.get_backend()
        except RequestException as error:
            self.skipTest(str(error))
        return requester

    def test_native_requester_sends_preemptive_authentication_from_rust(self):
        cases = AUTHENTICATION_CASES + (
            ("basic", "usér:päss:tail", "Basic dXPDqXI6cMOkc3M6dGFpbA=="),
            ("basic", "user", "Basic dXNlcjo="),
        )

        with RequestTargetServer() as server:
            for auth_type, credential, expected in cases:
                with self.subTest(auth_type=auth_type, credential=credential):
                    options["auth"] = credential
                    options["auth_type"] = auth_type
                    requester = self.native_requester_or_skip()
                    requester.set_url(server.url)
                    path = "raw%1" if credential == "user" else auth_type
                    requester.request(path)
                    self.assertEqual(server.authorizations[-1], expected)

    def test_native_digest_authentication_validates_the_challenge(self):
        options["auth"] = "digest-user:digest-password"
        options["auth_type"] = "digest"

        with RequestTargetServer() as server:
            requester = self.native_requester_or_skip()
            requester.set_url(server.url)
            response = requester.request("digest-auth")

        self.assertEqual(response.status, 200)
        self.assertEqual(server.authorizations[0], None)
        self.assertTrue(server.authorizations[1].startswith("Digest "))
        self.assertTrue(
            valid_digest_authorization(
                server.authorizations[1],
                "GET",
                "digest-user",
                "digest-password",
            )
        )

    def test_native_digest_wrong_credentials_remain_unauthorized(self):
        options["auth"] = "digest-user:wrong-password"
        options["auth_type"] = "digest"

        with RequestTargetServer() as server:
            requester = self.native_requester_or_skip()
            requester.set_url(server.url)
            response = requester.request("digest-auth")

        self.assertEqual(response.status, 401)
        self.assertEqual(len(server.authorizations), 2)
        self.assertTrue(server.authorizations[1].startswith("Digest "))

    def test_native_digest_resends_non_get_request_bodies(self):
        body = b"name=value&line=two\r\n"
        options["auth"] = "digest-user:digest-password"
        options["auth_type"] = "digest"
        options["http_method"] = "POST"
        options["data"] = body

        with RequestTargetServer() as server:
            requester = self.native_requester_or_skip()
            requester.set_url(server.url)
            response = requester.request("digest-auth")

        self.assertEqual(response.status, 200)
        self.assertEqual(server.request_methods, ["POST", "POST"])
        self.assertEqual(server.request_bodies, [body, body])
        self.assertTrue(
            valid_digest_authorization(
                server.authorizations[1],
                "POST",
                "digest-user",
                "digest-password",
            )
        )

    def test_native_malformed_digest_challenge_fails_without_secret_leakage(self):
        credential = "digest-user:do-not-leak-this-password"
        options["auth"] = credential
        options["auth_type"] = "digest"

        with RequestTargetServer() as server:
            requester = self.native_requester_or_skip()
            requester.set_url(server.url)
            with self.assertRaisesRegex(
                RequestException,
                "Invalid Digest authentication challenge",
            ) as raised:
                requester.request("malformed-digest-auth")

        self.assertNotIn(credential, str(raised.exception))
        self.assertNotIn("do-not-leak-this-password", str(raised.exception))

    def test_native_origin_authentication_survives_an_http_proxy(self):
        options["auth"] = "origin-user:origin-password"
        options["auth_type"] = "basic"
        options["proxy_auth"] = "proxy-user:proxy-password"

        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            result = list(backend.scan("http://origin.invalid/", ["admin"]))[0]

        self.assertIsNone(result[2])
        self.assertEqual(
            proxy.authorizations,
            ["Basic b3JpZ2luLXVzZXI6b3JpZ2luLXBhc3N3b3Jk"],
        )
        self.assertEqual(
            proxy.proxy_authorizations,
            ["Basic cHJveHktdXNlcjpwcm94eS1wYXNzd29yZA=="],
        )

    def test_native_cross_origin_redirect_strips_authentication(self):
        options["auth"] = "redirect-token"
        options["auth_type"] = "bearer"
        options["follow_redirects"] = True

        with RequestTargetServer() as origin, RequestTargetServer() as destination:
            origin.server.external_redirect_url = destination.url + "final"
            requester = self.native_requester_or_skip()
            requester.set_url(origin.url)
            response = requester.request("external-redirect")

        self.assertEqual(response.status, 200)
        self.assertEqual(origin.authorizations, ["Bearer redirect-token"])
        self.assertEqual(destination.authorizations, [None])

    def test_native_same_origin_redirect_keeps_preemptive_authentication(self):
        options["auth"] = "redirect-token"
        options["auth_type"] = "bearer"
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            requester = self.native_requester_or_skip()
            requester.set_url(server.url)
            response = requester.request("redirect")

        self.assertEqual(response.status, 200)
        self.assertEqual(
            server.authorizations,
            ["Bearer redirect-token", "Bearer redirect-token"],
        )

    def test_native_digest_answers_a_same_origin_redirect_challenge(self):
        options["auth"] = "digest-user:digest-password"
        options["auth_type"] = "digest"
        options["follow_redirects"] = True

        with RequestTargetServer() as server:
            server.server.external_redirect_url = server.url + "digest-auth"
            requester = self.native_requester_or_skip()
            requester.set_url(server.url)
            response = requester.request("external-redirect")

        self.assertEqual(response.status, 200)
        self.assertEqual(server.authorizations[:2], [None, None])
        self.assertTrue(server.authorizations[2].startswith("Digest "))
        self.assertTrue(
            valid_digest_authorization(
                server.authorizations[2],
                "GET",
                "digest-user",
                "digest-password",
            )
        )

    def test_native_digest_does_not_answer_a_cross_origin_challenge(self):
        options["auth"] = "digest-user:digest-password"
        options["auth_type"] = "digest"
        options["follow_redirects"] = True

        with RequestTargetServer() as origin, RequestTargetServer() as destination:
            origin.server.external_redirect_url = destination.url + "digest-auth"
            requester = self.native_requester_or_skip()
            requester.set_url(origin.url)
            response = requester.request("external-redirect")

        self.assertEqual(response.status, 401)
        self.assertEqual(origin.authorizations, [None])
        self.assertEqual(destination.authorizations, [None])

    def test_native_target_authentication_is_restored_for_the_next_target(self):
        options["auth"] = "configured-token"
        options["auth_type"] = "bearer"

        with RequestTargetServer() as server:
            requester = self.native_requester_or_skip()
            controller = object.__new__(Controller)
            controller.requester = requester
            target_with_credentials = server.url.replace(
                "http://",
                "http://target-user:p%40ss%3Atail@",
            )

            controller.set_target(target_with_credentials)
            requester.request("first")
            controller.set_target(server.url)
            requester.request("second")

        self.assertEqual(
            server.authorizations,
            [
                "Basic dGFyZ2V0LXVzZXI6cEBzczp0YWls",
                "Bearer configured-token",
            ],
        )

    def test_native_digest_rejects_raw_targets_instead_of_skipping_auth(self):
        options["auth"] = "digest-user:digest-password"
        options["auth_type"] = "digest"

        with RequestTargetServer() as server:
            requester = self.native_requester_or_skip()
            requester.set_url(server.url)
            with self.assertRaisesRegex(
                RequestException,
                "Digest authentication cannot be used with a byte-preserving",
            ):
                requester.request("raw%1")

        self.assertEqual(server.targets, [])

    def test_native_replay_proxy_copies_origin_session_cookies(self):
        requester = NativeRequester()
        with RequestTargetServer() as server:
            requester.set_url(server.url)
            try:
                requester.request("cookie/set")
                response = requester.request("cookie/required", proxy=server.url)
            except RequestException as error:
                self.skipTest(str(error))
            finally:
                requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(server.cookies, [None, "session=native"])

    def test_native_replay_proxy_reapplies_cookie_scope_on_redirect(self):
        options["follow_redirects"] = True
        requester = NativeRequester()
        with RequestTargetServer() as server:
            requester.set_url(server.url)
            try:
                requester.request("cookie/scoped/set")
                response = requester.request(
                    "cookie/scoped/redirect-outside",
                    proxy=server.url,
                )
            except RequestException as error:
                self.skipTest(str(error))
            finally:
                requester.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(server.cookies, [None, "scoped=native", None])

    def test_native_requester_reuses_response_cookies(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            first = list(backend.scan(server.url, ["cookie/set"]))[0]
            second = list(backend.scan(server.url, ["cookie/required"]))[0]

        self.assertIsNone(first[2])
        self.assertIsNone(second[2])
        self.assertEqual(second[1].status, 200)
        self.assertEqual(server.cookies, [None, "session=native"])

    def test_native_retries_reuse_cookie_from_truncated_response(self):
        options["max_retries"] = 1
        for path in ("cookie/retry-body", "cookie/retry-body%1"):
            with self.subTest(path=path), RequestTargetServer() as server:
                try:
                    backend = NativeHTTPBackend()
                except RequestException as error:
                    self.skipTest(str(error))
                result = list(backend.scan(server.url, [path]))[0]

                self.assertIsNone(result[2])
                self.assertEqual(result[1].status, 200)
                self.assertEqual(server.cookies, [None, "retry=native"])

    def test_native_raw_fallback_reuses_response_cookies(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            first = list(backend.scan(server.url, ["cookie/set"]))[0]
            second = list(backend.scan(server.url, ["cookie/required%1"]))[0]

        self.assertIsNone(first[2])
        self.assertIsNone(second[2])
        self.assertEqual(second[1].status, 200)
        self.assertEqual(server.cookies, [None, "session=native"])

    def test_native_redirect_applies_response_cookie_to_next_hop(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        options["follow_redirects"] = True
        with RequestTargetServer() as server:
            result = list(backend.scan(server.url, ["cookie/redirect"]))[0]

        self.assertIsNone(result[2])
        self.assertEqual(result[1].status, 200)
        self.assertEqual(server.cookies, [None, "redirect=native"])

    def test_native_cookie_jar_is_shared_across_rotating_proxy_clients(self):
        options["thread_count"] = 1
        with RequestTargetServer() as first_proxy, RequestTargetServer() as second_proxy:
            options["proxies"] = [first_proxy.url, second_proxy.url]
            try:
                backend = NativeHTTPBackend()
            except RequestException as error:
                self.skipTest(str(error))
            results = list(
                backend.scan(
                    "http://origin.invalid/",
                    ["cookie/set", "cookie/required"],
                )
            )

        self.assertEqual([error for _, _, error in results], [None, None])
        self.assertEqual([response.status for _, response, _ in results], [200, 200])
        self.assertEqual(first_proxy.cookies, [None])
        self.assertEqual(second_proxy.cookies, ["session=native"])

    def test_native_cookie_jar_does_not_cross_target_hosts(self):
        options["thread_count"] = 1
        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            try:
                backend = NativeHTTPBackend()
            except RequestException as error:
                self.skipTest(str(error))
            stored = list(
                backend.scan("http://first-origin.invalid/", ["cookie/set"])
            )[0]
            isolated = list(
                backend.scan("http://second-origin.invalid/", ["cookie/required"])
            )[0]

        self.assertIsNone(stored[2])
        self.assertIsNone(isolated[2])
        self.assertEqual(isolated[1].status, 401)
        self.assertEqual(proxy.cookies, [None, None])

    def test_native_cookie_jar_survives_internal_engine_rebuild(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            stored = list(backend.scan(server.url, ["cookie/set"]))[0]
            options["follow_redirects"] = True
            reused = list(backend.scan(server.url, ["cookie/required"]))[0]

        self.assertIsNone(stored[2])
        self.assertIsNone(reused[2])
        self.assertEqual(reused[1].status, 200)
        self.assertEqual(server.cookies, [None, "session=native"])

    def test_native_raw_fallback_honors_cookie_path_scope(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            stored = list(backend.scan(server.url, ["cookie/scoped/set"]))[0]
            allowed = list(
                backend.scan(server.url, ["cookie/scoped/required%1"])
            )[0]
            outside = list(backend.scan(server.url, ["cookie/outside%1"]))[0]

        self.assertIsNone(stored[2])
        self.assertIsNone(allowed[2])
        self.assertIsNone(outside[2])
        self.assertEqual(allowed[1].status, 200)
        self.assertEqual(
            server.cookies,
            [None, "scoped=native", None],
        )

    def test_native_explicit_cookie_header_takes_precedence_over_session(self):
        options["headers"] = {"Cookie": "fixed=manual"}
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            stored = list(backend.scan(server.url, ["cookie/set"]))[0]
            normal = list(backend.scan(server.url, ["cookie/required"]))[0]
            raw = list(backend.scan(server.url, ["cookie/required%1"]))[0]

        self.assertIsNone(stored[2])
        self.assertIsNone(normal[2])
        self.assertIsNone(raw[2])
        self.assertEqual(normal[1].status, 401)
        self.assertEqual(raw[1].status, 401)
        self.assertEqual(server.cookies, ["fixed=manual"] * 3)

    def test_native_fixed_cookie_yields_to_jar_on_redirect(self):
        options["headers"] = {"Cookie": "fixed=manual"}
        options["follow_redirects"] = True
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            stored = list(backend.scan(server.url, ["cookie/fixed-seed"]))[0]
            redirected = list(
                backend.scan(server.url, ["cookie/fixed-redirect"])
            )[0]

        self.assertIsNone(stored[2])
        self.assertIsNone(redirected[2])
        self.assertEqual(redirected[1].status, 200)
        self.assertEqual(
            server.cookies,
            ["fixed=manual", "fixed=manual", "jar=native"],
        )

    def test_native_fixed_cookie_is_request_local_under_concurrency(self):
        options["headers"] = {"Cookie": "fixed=manual"}
        options["thread_count"] = 8
        options["timeout"] = 5
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        paths = [f"cookie/concurrent/{index}" for index in range(16)]
        with RequestTargetServer() as server:
            results = list(backend.scan(server.url, paths))

        self.assertTrue(all(error is None for _, _, error in results))
        self.assertEqual(server.cookies, ["fixed=manual"] * len(paths))

    def test_native_does_not_send_secure_cookie_over_loopback_http(self):
        for host in ("address", "localhost"):
            with self.subTest(host=host), RequestTargetServer() as server:
                try:
                    backend = NativeHTTPBackend()
                except RequestException as error:
                    self.skipTest(str(error))
                base_url = server.url if host == "address" else server.localhost_url
                stored = list(backend.scan(base_url, ["cookie/secure-set"]))[0]
                normal = list(backend.scan(base_url, ["cookie/secure-check"]))[0]
                raw = list(backend.scan(base_url, ["cookie/secure-check%1"]))[0]

                self.assertIsNone(stored[2])
                self.assertIsNone(normal[2])
                self.assertIsNone(raw[2])
                self.assertEqual(server.cookies, [None, None, None])

    def test_native_does_not_send_secure_cookie_over_proxied_http_origin(self):
        options["thread_count"] = 1
        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            try:
                backend = NativeHTTPBackend()
            except RequestException as error:
                self.skipTest(str(error))
            stored = list(
                backend.scan("http://origin.invalid/", ["cookie/secure-set"])
            )[0]
            checked = list(
                backend.scan("http://origin.invalid/", ["cookie/secure-check"])
            )[0]

        self.assertIsNone(stored[2])
        self.assertIsNone(checked[2])
        self.assertEqual(proxy.cookies, [None, None])

    def test_native_cookie_header_uses_longest_path_first(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            root = list(backend.scan(server.url, ["cookie/path-root-set"]))[0]
            scoped = list(
                backend.scan(server.url, ["cookie/scoped/path-set"])
            )[0]
            normal = list(
                backend.scan(server.url, ["cookie/scoped/path-check"])
            )[0]
            raw = list(
                backend.scan(server.url, ["cookie/scoped/path-check%1"])
            )[0]

        self.assertTrue(all(row[2] is None for row in (root, scoped, normal, raw)))
        self.assertEqual(
            server.cookies,
            [
                None,
                "id=root",
                "id=scoped; id=root",
                "id=scoped; id=root",
            ],
        )

    def test_native_cookie_domain_rules_match_other_sessions(self):
        options["thread_count"] = 1
        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            try:
                backend = NativeHTTPBackend()
            except RequestException as error:
                self.skipTest(str(error))
            supercookie = list(
                backend.scan("http://foo.com/", ["cookie/domain-super-set"])
            )[0]
            isolated = list(
                backend.scan("http://bar.com/", ["cookie/domain-check"])
            )[0]

        self.assertIsNone(supercookie[2])
        self.assertIsNone(isolated[2])
        self.assertEqual(proxy.cookies, [None, None])

        with RequestTargetServer() as proxy:
            options["proxies"] = [proxy.url]
            backend = NativeHTTPBackend()
            parent = list(
                backend.scan(
                    "http://api.example.com/",
                    ["cookie/domain-parent-set"],
                )
            )[0]
            shared = list(
                backend.scan("http://www.example.com/", ["cookie/domain-check"])
            )[0]

        self.assertIsNone(parent[2])
        self.assertIsNone(shared[2])
        self.assertEqual(proxy.cookies, [None, "parent=native"])

    def test_native_requester_preserves_methods_and_request_body_bytes(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        cases = (
            ("POST", "ascii", b"name=plain&line=two\r\n"),
            ("PATCH", "raw%1", b"value=\xff\r\nnext=line\n"),
            ("PUT", "unicode", "value=\u00e9"),
        )
        with RequestTargetServer() as server:
            for method, path, body in cases:
                with self.subTest(method=method, path=path):
                    options["http_method"] = method
                    options["data"] = body
                    result = list(backend.scan(server.url, [path]))[0]
                    self.assertIsNone(result[2])

        self.assertEqual(server.request_methods, [method for method, _, _ in cases])
        self.assertEqual(
            server.request_bodies,
            [body.encode() if isinstance(body, str) else body for _, _, body in cases],
        )

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
            self.assertEqual(results[0][1].history, [f"{server.url}redirect"])
            self.assertEqual(server.targets, [b"/redirect", b"/final"])

    def test_native_requester_preserves_multi_hop_redirect_history(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        options["follow_redirects"] = True
        with RequestTargetServer() as server:
            results = list(
                backend.scan(
                    server.url,
                    ["redirect-chain/start?first=%2F"],
                )
            )

            self.assertEqual([error for _, _, error in results], [None])
            self.assertEqual(results[0][1].status, 200)
            self.assertEqual(
                results[0][1].history,
                [
                    f"{server.url}redirect-chain/start?first=%2F",
                    f"{server.url}redirect-chain/middle?step=%2F",
                ],
            )
            self.assertEqual(
                server.targets,
                [
                    b"/redirect-chain/start?first=%2F",
                    b"/redirect-chain/middle?step=%2F",
                    b"/redirect-chain/final?done=%2F",
                ],
            )

    def test_native_requester_follows_shared_redirect_limit(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        options["follow_redirects"] = True
        with RequestTargetServer() as server:
            result = list(
                backend.scan(
                    server.url,
                    [f"redirect-count/{MAX_REDIRECTS}"],
                )
            )[0]

            self.assertIsNone(result[2])
            self.assertEqual(result[1].status, 200)
            self.assertEqual(
                len(result[1].history),
                MAX_REDIRECTS,
            )

    def test_native_requester_rejects_redirects_above_shared_limit(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        options["follow_redirects"] = True
        with RequestTargetServer() as server:
            result = list(
                backend.scan(
                    server.url,
                    [f"redirect-count/{MAX_REDIRECTS + 1}"],
                )
            )[0]

            self.assertIsNone(result[1])
            self.assertIsNotNone(result[2])
            self.assertIn("too many redirects", str(result[2]).lower())

    def test_native_requester_retries_response_body_read_failures(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        options["max_retries"] = 1
        with RequestTargetServer() as server:
            result = list(backend.scan(server.url, ["retry-body"]))[0]

            self.assertIsNone(result[2])
            self.assertEqual(result[1].body, b"ok")
            self.assertEqual(server.target_counts[b"/retry-body"], 2)

    def test_native_raw_request_retries_response_body_read_failures(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        options["max_retries"] = 1
        with RequestTargetServer() as server:
            result = list(backend.scan(server.url, ["retry-body%1"]))[0]

            self.assertIsNone(result[2])
            self.assertEqual(result[1].body, b"ok")
            self.assertEqual(server.target_counts[b"/retry-body%1"], 2)

    def test_native_requester_does_not_retry_body_reads_when_disabled(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            results = list(
                backend.scan(
                    server.url,
                    ["retry-body", "retry-body%1"],
                )
            )

            self.assertEqual([response for _, response, _ in results], [None, None])
            self.assertTrue(all(error is not None for _, _, error in results))
            self.assertEqual(server.target_counts[b"/retry-body"], 1)
            self.assertEqual(server.target_counts[b"/retry-body%1"], 1)

    def test_native_batch_filters_advanced_python_regexes_in_rust(self):
        with RequestTargetServer() as server:
            cases = (
                ("lookahead", "admin", r"(?=ok)ok"),
                (
                    "named-backreference",
                    "regex-backreference",
                    r"\b(?P<word>[a-z]+)\s+(?P=word)\b",
                ),
            )
            for name, path, pattern in cases:
                with self.subTest(name=name):
                    options["filter_regex"] = pattern
                    try:
                        backend = NativeHTTPBackend()
                    except RequestException as error:
                        self.skipTest(str(error))
                    batch = backend.scan_batch(server.url, [path])

                    self.assertEqual(batch.processed_count, 1)
                    self.assertEqual(batch.events, ())

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
    def _assert_repeated_headers(self, response):
        self.assertEqual(response.headers.get("x-repeat"), "one, two")
        self.assertEqual(
            response.headers.get("set-cookie"),
            "first=1; Path=/, second=2; Path=/",
        )

    def test_sync_repeated_response_headers_are_preserved(self):
        with RequestTargetServer() as server:
            requester = Requester()
            requester.set_url(server.url)
            try:
                response = requester.request("repeated-headers")
            finally:
                requester.close()

        self._assert_repeated_headers(response)

    async def test_async_repeated_response_headers_are_preserved(self):
        with RequestTargetServer() as server:
            requester = AsyncRequester()
            requester.set_url(server.url)
            try:
                response = await requester.request("repeated-headers")
            finally:
                await requester.close()

        self._assert_repeated_headers(response)

    def test_native_repeated_response_headers_are_preserved(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with RequestTargetServer() as server:
            results = list(backend.scan(server.url, ["repeated-headers"]))

        self.assertEqual(len(results), 1)
        _, response, error = results[0]
        self.assertIsNone(error)
        self.assertIsNotNone(response)
        self._assert_repeated_headers(response)

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
                self.assertTrue(record["bodyComplete"])
                self.assertFalse(record["bodyTruncated"])
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

    def _assert_response_text(self, responses):
        for response, (_, charset, body) in zip(
            responses, ENCODED_RESPONSE_CASES
        ):
            with self.subTest(charset=charset):
                expected = (
                    ""
                    if charset == "x-dirsearch-unknown"
                    else body.decode(charset)
                )
                self.assertEqual(response.content, expected)

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
        self._assert_response_text(responses)
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
        self._assert_response_text(responses)
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
        self._assert_response_text(responses)
        self._assert_jsonl_round_trip(responses)

    def test_native_non_utf8_matcher_is_deferred_until_after_decoding(self):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        options["match_regex"] = ARABIC_TEXT
        with RequestTargetServer() as server:
            results = list(
                backend.scan(server.url, ["encoded/arabic-windows-1256%1"])
            )

        self.assertEqual(len(results), 1)
        _, response, error = results[0]
        self.assertIsNone(error)
        self.assertIsNotNone(response)
        self.assertFalse(response.filtered)
        self.assertEqual(response.content, ARABIC_TEXT)
