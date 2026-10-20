"""HTTP adapters must expose the same text before any native discard."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest import TestCase

import httpx
import requests

from lib.connection.native import NativeHTTPBackend
from lib.connection.response import AsyncResponse, NativeResponse, Response
from lib.core.filter_config import FilterConfig
from lib.core.native_runtime import get_native_extension_version_error
from lib.core.request_config import RequestConfig
from lib.core.scanner import Scanner
from lib.core.settings import WILDCARD_TEST_POINT_MARKER


CASES = {
    "latin1": (b"caf\xe9", "text/html", "caf\xe9"),
    "distinct": (b"caf\xf1", "text/html", "caf\xf1"),
    "utf8": ("caf\xe9".encode(), "text/html; charset=utf-8", "caf\xe9"),
    "json": ("caf\xe9".encode(), "application/json", "caf\xe9"),
    "utf16": ("hello world".encode("utf-16"), "text/plain; charset=utf-16", "hello world"),
    "unknown": (b"abc", "text/plain; charset=unknown-test-codec", "abc"),
    "binary": (b"a\x00\xffb", "application/octet-stream", "a\x00b"),
    "words": (b"admin\x1csecret", "text/plain", "admin\x1csecret"),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        body, media_type, _ = CASES[self.path.lstrip("/")]
        self.send_response(404)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class ProbeRequester:
    def __init__(self, response):
        self.response = response

    def request(self, _path):
        return self.response


class TestResponseTextContract(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)
        if cls.thread.is_alive():
            raise AssertionError("HTTP fixture did not stop")

    def native_backend(self, policy=FilterConfig()):
        try:
            import dirsearch_native
        except ImportError:
            self.skipTest("native extension is not installed")
        if error := get_native_extension_version_error(dirsearch_native):
            self.skipTest(error)
        backend = NativeHTTPBackend(RequestConfig(concurrency=2, timeout=2), filter_config=policy)
        self.addCleanup(backend.close)
        return backend

    async def async_response(self, name):
        async with httpx.AsyncClient(trust_env=False) as client:
            async with client.stream("GET", self.url + name) as response:
                return await AsyncResponse.create(self.url + name, response)

    def test_sync_async_and_native_share_encoding_and_binary_text_rules(self):
        session = requests.Session()
        session.trust_env = False
        self.addCleanup(session.close)
        for name, (body, media_type, expected) in CASES.items():
            with self.subTest(name=name), session.get(self.url + name, stream=True) as raw:
                sync = Response(self.url + name, raw)
                asynchronous = asyncio.run(self.async_response(name))
                native = NativeResponse(self.url + name, 404, [("content-type", media_type)], body)
                for response in (sync, asynchronous, native):
                    self.assertEqual(response.body, body)
                    self.assertEqual(response.text, expected)
                    self.assertEqual(response.words, len(expected.split()))

    def test_distinct_unlabelled_pages_do_not_collapse_into_one_wildcard(self):
        backend = self.native_backend()
        first, error = backend.scan_unfiltered(self.url, "latin1")
        self.assertIsNone(error)
        candidate, error = backend.scan_unfiltered(self.url, "distinct")
        self.assertIsNone(error)
        scanner = Scanner(ProbeRequester(first), filter_config=FilterConfig(), delay=0,
                          path=WILDCARD_TEST_POINT_MARKER)
        self.assertEqual(scanner.classify("distinct", candidate), "unique")

    def test_native_word_filter_keeps_python_two_word_control_separator(self):
        backend = self.native_backend(FilterConfig(match_words=((2, 2),)))
        response = list(backend.scan(self.url, ["words"]))[0][1]
        self.assertFalse(response.filtered)
        self.assertEqual(response.words, 2)

    def test_native_binary_regex_defers_to_common_text_decoding(self):
        backend = self.native_backend(FilterConfig(match_regex=r"a\x00b"))
        response = list(backend.scan(self.url, ["binary"]))[0][1]
        self.assertFalse(response.filtered)
        self.assertEqual(response.text, "a\x00b")

    def test_native_unlabelled_latin1_regex_is_not_rejected_before_decoding(self):
        backend = self.native_backend(FilterConfig(match_regex="caf\xe9"))
        response = list(backend.scan(self.url, ["latin1"]))[0][1]
        self.assertFalse(response.filtered)
        self.assertEqual(response.text, "caf\xe9")
