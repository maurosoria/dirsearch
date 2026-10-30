"""Safe response evidence in the existing log, across real local transports."""

import asyncio
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import requests

from lib.connection.native import NativeHTTPBackend, NativeRequester
from lib.connection.requester import AsyncRequester, Requester
from lib.connection.response import NativeResponse, Response
from lib.core.filter_config import FilterConfig
from lib.core.log_config import LogConfig
from lib.core.logger import MAX_LOG_DIGEST_BYTES, RunLogger
from lib.core.native_runtime import is_native_backend_available
from lib.core.request_config import RequestConfig
from tests.connection.test_native_engine import CountingHTTPServer


BODY = b"private account page, not loggable as plaintext" * 100
COMPRESSED_BODY = gzip.compress(BODY, mtime=0)


class DiagnosticHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.send_response(404 if self.path.startswith("/missing") else 200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(COMPRESSED_BODY)))
        self.send_header("Set-Cookie", "secret-cookie=private")
        self.end_headers()
        self.wfile.write(COMPRESSED_BODY)

    def log_message(self, _format, *args):
        pass


class HTTP10DiagnosticHandler(DiagnosticHandler):
    protocol_version = "HTTP/1.0"


class TestResponseDiagnostics(IsolatedAsyncioTestCase):
    def make_log(self):
        directory = self.enterContext(TemporaryDirectory())
        destination = Path(directory, "scan.log")
        logger = RunLogger(LogConfig(str(destination)))
        self.addCleanup(logger.close)
        return logger, destination

    def test_disabled_logging_never_hashes_or_reads_response(self):
        logger = RunLogger()
        with patch("lib.core.logger.hashlib.sha256") as digest:
            logger.response("GET", None, backend="threaded")
        digest.assert_not_called()

    def test_custom_requests_adapter_without_http_version_logs_unknown(self):
        # requests supports adapter-provided file-like bodies, not only urllib3.
        raw = requests.Response()
        raw.status_code = 200
        raw.url = "https://example.test/item"
        raw.raw = BytesIO(b"adapter response")
        raw.headers["Content-Type"] = "text/plain"
        response = Response(raw.url, raw)
        logger, destination = self.make_log()
        try:
            logger.response("GET", response, backend="threaded")
        finally:
            raw.close()
            logger.close()
        self.assertIsNone(response.http_version)
        self.assertEqual(response.body, b"adapter response")
        self.assertIn("http_version=unknown", destination.read_text())

    def test_metadata_distinguishes_encoded_length_and_retained_decoded_bytes(self):
        logger, destination = self.make_log()
        response = NativeResponse(
            "https://user:password@example.test/account/login?token=query-secret#fragment-secret",
            200,
            [("Content-Encoding", "gzip"), ("Content-Length", "53"),
             ("Set-Cookie", "session=cookie-secret"), ("Authorization", "auth-secret")],
            BODY,
            http_version="HTTP/2",
            final_url="https://example.test/account/login?token=final-secret#fragment-secret",
        )
        logger.response("GET", response, backend="native")
        logger.close()
        contents = destination.read_text()
        self.assertIn("backend=native http_version=HTTP/2 content_encoding=gzip", contents)
        self.assertIn("200 - 53B", contents)
        self.assertNotIn("reported_length=", contents)
        self.assertIn(f"retained_length={len(BODY)} body_complete=true", contents)
        self.assertIn(f"retained_sha256={hashlib.sha256(BODY).hexdigest()}", contents)
        self.assertIn("?token=<redacted>", contents)
        self.assertIn("final_url=https://example.test/account/login?token=<redacted>", contents)
        for secret in ("user:password", "query-secret", "final-secret", "fragment-secret", "cookie-secret", "auth-secret", BODY.decode()):
            self.assertNotIn(secret, contents)

    def test_large_capture_hashes_only_an_explicit_bounded_prefix(self):
        logger, destination = self.make_log()
        body = b"x" * (MAX_LOG_DIGEST_BYTES * 3) + b"different tail"
        response = NativeResponse("https://example.test/large", 200, [], body)
        with patch("lib.core.logger.hashlib.sha256", wraps=hashlib.sha256) as digest:
            logger.response("GET", response, backend="async")
        digest.assert_called_once()
        self.assertEqual(bytes(digest.call_args.args[0]), body[:MAX_LOG_DIGEST_BYTES])
        logger.close()
        contents = destination.read_text()
        self.assertIn("retained_sha256=unavailable", contents)
        self.assertIn(f"sample_sha256={hashlib.sha256(body[:MAX_LOG_DIGEST_BYTES]).hexdigest()}", contents)
        self.assertIn(f"hashed_length={MAX_LOG_DIGEST_BYTES}", contents)

    def test_partial_hash_is_explicitly_a_retained_capture_not_complete_body(self):
        logger, destination = self.make_log()
        response = NativeResponse("https://example.test/item", 200, [], b"prefix", body_complete=False)
        logger.response("GET", response, backend="threaded")
        logger.close()
        contents = destination.read_text()
        self.assertIn("http_version=unknown", contents)
        self.assertIn("retained_length=6 body_complete=false", contents)
        self.assertIn(f"retained_sha256={hashlib.sha256(b'prefix').hexdigest()}", contents)

    def test_native_body_omission_is_not_hashed_as_an_empty_response(self):
        logger, destination = self.make_log()
        response = NativeResponse("https://example.test/missing", 404, [], b"", body_complete=False)
        with patch("lib.core.logger.hashlib.sha256") as digest:
            logger.response("GET", response, backend="native", filter_reason="exclude_status")
        logger.close()
        digest.assert_not_called()
        contents = destination.read_text()
        self.assertIn("retained_sha256=unavailable", contents)
        self.assertIn("native_filter=exclude_status", contents)

    def test_unrecognized_encoding_header_is_not_logged_verbatim(self):
        logger, destination = self.make_log()
        response = NativeResponse("https://example.test/item", 200,
                                  [("Content-Encoding", "private-header-value\nforged log")], b"")
        logger.response("GET", response, backend="async")
        logger.close()
        contents = destination.read_text()
        self.assertIn("content_encoding=other", contents)
        self.assertNotIn("private-header-value", contents)
        self.assertNotIn("forged log", contents)

    def test_existing_redirect_location_is_preserved_with_redacted_credentials(self):
        logger, destination = self.make_log()
        response = NativeResponse("https://example.test/item", 302,
                                  [("Location", "https://user:password@example.test/login?token=redirect-secret#fragment-secret")], b"")
        logger.response("GET", response, backend="threaded")
        logger.close()
        contents = destination.read_text()
        self.assertIn(" - LOCATION: https://<redacted>@example.test/login?token=<redacted>", contents)
        for secret in ("user:password", "redirect-secret", "fragment-secret"):
            self.assertNotIn(secret, contents)

    async def test_local_http10_and_http11_metadata_across_available_engines(self):
        for handler in (HTTP10DiagnosticHandler, DiagnosticHandler):
            server = CountingHTTPServer(handler)
            try:
                engines = ["threaded", "async"]
                if is_native_backend_available():
                    engines.append("native")
                for engine in engines:
                    with self.subTest(engine=engine, protocol=handler.protocol_version):
                        logger, destination = self.make_log()
                        config = RequestConfig(timeout=2, max_retries=0)
                        if engine == "async":
                            requester = AsyncRequester(config, logger=logger)
                            try:
                                requester.set_url(server.url)
                                response = await requester.request("account/login?token=query-secret")
                            finally:
                                await requester.close()
                        else:
                            requester = (NativeRequester(config, filter_config=FilterConfig(), logger=logger)
                                         if engine == "native" else Requester(config, logger=logger))
                            try:
                                requester.set_url(server.url)
                                response = requester.request("account/login?token=query-secret")
                            finally:
                                requester.close()
                        logger.close()
                        contents = destination.read_text()
                        self.assertEqual(response.body, BODY)
                        self.assertEqual(response.http_version, handler.protocol_version)
                        self.assertIn(f"backend={engine} http_version={handler.protocol_version}", contents)
                        self.assertIn(f"200 - {len(COMPRESSED_BODY)}B", contents)
                        self.assertIn(f"retained_length={len(BODY)} body_complete=true", contents)
                        self.assertIn(f"retained_sha256={hashlib.sha256(BODY).hexdigest()}", contents)
                        self.assertNotIn("query-secret", contents)
                        self.assertNotIn("secret-cookie", contents)
            finally:
                await asyncio.to_thread(server.close)
                self.assertFalse(server.thread.is_alive())

    def test_logged_exact_static_profile_avoids_response_construction(self):
        if not is_native_backend_available():
            self.skipTest("native extension is not installed")
        logger, destination = self.make_log()
        server = CountingHTTPServer(DiagnosticHandler)
        backend = NativeHTTPBackend(RequestConfig(timeout=2, max_retries=0),
                                    filter_config=FilterConfig(), logger=logger)
        backend.set_static_response_profile((404, "text/plain", BODY))
        chunks = []
        try:
            with patch("lib.connection.native.NativeResponse", side_effect=AssertionError("static body decoded")):
                processed = backend.scan_chunks(server.url, ["missing"], chunks.append)
        finally:
            backend.close()
            server.close()
            logger.close()
        self.assertEqual(processed, 1)
        self.assertEqual(sum(len(chunk.events) for chunk in chunks), 0)
        self.assertIn("native_filter=static_response", destination.read_text())
        self.assertFalse(server.thread.is_alive())

    def test_native_prefilters_log_reason_without_delivering_filtered_events(self):
        if not is_native_backend_available():
            self.skipTest("native extension is not installed")
        logger, destination = self.make_log()
        server = CountingHTTPServer(DiagnosticHandler)
        backend = NativeHTTPBackend(RequestConfig(timeout=2, max_retries=0),
                                    filter_config=FilterConfig(exclude_status_codes=(404,)), logger=logger)
        chunks = []
        try:
            with patch("lib.connection.native.NativeResponse", side_effect=AssertionError("filtered body decoded")):
                processed = backend.scan_chunks(server.url, ["missing?token=query-secret"], chunks.append)
        finally:
            backend.close()
            server.close()
            logger.close()
        self.assertFalse(server.thread.is_alive())
        self.assertEqual(processed, 1)
        self.assertEqual(sum(len(chunk.events) for chunk in chunks), 0)
        contents = destination.read_text()
        self.assertIn("backend=native http_version=HTTP/1.1 content_encoding=gzip", contents)
        self.assertIn("native_filter=exclude_status", contents)
        self.assertIn("retained_sha256=unavailable", contents)
        self.assertNotIn("query-secret", contents)
