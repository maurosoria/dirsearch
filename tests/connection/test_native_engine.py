import gzip
import os
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import TestCase, skipUnless

try:
    import dirsearch_native
except ImportError:
    dirsearch_native = None


class NativeScanInterrupted(Exception):
    pass


class StalledHTTPServer:
    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.release = threading.Event()
        self.accepted = threading.Event()
        self.peer_closed = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def url(self):
        host, port = self.listener.getsockname()
        return f"http://{host}:{port}/"

    def _serve(self):
        try:
            connection, _ = self.listener.accept()
            with connection:
                self.accepted.set()
                connection.settimeout(0.05)
                while not self.release.is_set():
                    try:
                        if connection.recv(4096) == b"":
                            self.peer_closed.set()
                            return
                    except TimeoutError:
                        continue
        except OSError:
            pass

    def close(self):
        self.release.set()
        self.listener.close()
        self.thread.join(timeout=1)


class RawResponseServer:
    def __init__(self, response):
        self.response = response
        self.request_target = None
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def url(self):
        host, port = self.listener.getsockname()
        return f"http://{host}:{port}/"

    def _serve(self):
        try:
            connection, _ = self.listener.accept()
            with connection:
                request = bytearray()
                while b"\r\n\r\n" not in request:
                    chunk = connection.recv(4096)
                    if not chunk:
                        return
                    request.extend(chunk)
                self.request_target = request.split(b" ", 2)[1].decode("ascii")
                connection.sendall(self.response)
        except OSError:
            pass

    def close(self):
        self.listener.close()
        self.thread.join(timeout=1)


class SlowBodyServer(RawResponseServer):
    def __init__(self):
        super().__init__(b"")

    def _serve(self):
        try:
            connection, _ = self.listener.accept()
            with connection:
                request = bytearray()
                while b"\r\n\r\n" not in request:
                    chunk = connection.recv(4096)
                    if not chunk:
                        return
                    request.extend(chunk)
                connection.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n"
                )
                for _ in range(100):
                    connection.sendall(b"x")
                    time.sleep(0.05)
        except OSError:
            pass


class KeepAliveHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *args):
        return None


class CountingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), KeepAliveHandler)
        self.connection_count = 0
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def get_request(self):
        request = super().get_request()
        self.connection_count += 1
        return request

    @property
    def url(self):
        host, port = self.server_address
        return f"http://{host}:{port}/"

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=1)


@skipUnless(
    dirsearch_native is not None
    and hasattr(dirsearch_native, "NativeHttpEngine"),
    "native extension is not installed",
)
class TestNativeHttpEngine(TestCase):
    def test_reuses_http_connection_across_scans(self):
        server = CountingHTTPServer()
        engine = dirsearch_native.NativeHttpEngine()

        try:
            first = engine.scan(server.url, ["first"])
            second = engine.scan(server.url, ["second"])
        finally:
            server.close()

        self.assertEqual([first[0].status, second[0].status], [200, 200])
        self.assertEqual(server.connection_count, 1)

    def test_compatibility_function_reuses_http_connection(self):
        server = CountingHTTPServer()

        try:
            first = dirsearch_native.scan_http(server.url, ["first"])
            second = dirsearch_native.scan_http(server.url, ["second"])
        finally:
            server.close()

        self.assertEqual([first[0].status, second[0].status], [200, 200])
        self.assertEqual(server.connection_count, 1)

    def test_explicit_cancellation_interrupts_active_scan(self):
        server = StalledHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=5)
        cancel_timer = threading.Timer(0.1, engine.cancel)

        try:
            cancel_timer.start()
            started = time.monotonic()
            results = engine.scan(server.url, ["slow"])
            elapsed = time.monotonic() - started
        finally:
            cancel_timer.join(timeout=1)
            server.close()

        self.assertEqual(results, [])
        self.assertLess(elapsed, 2)

    def test_cancellation_before_scan_is_consumed_without_sending_requests(self):
        server = CountingHTTPServer()
        engine = dirsearch_native.NativeHttpEngine()
        engine.cancel()

        try:
            cancelled = engine.scan(server.url, ["cancelled"])
            resumed = engine.scan(server.url, ["resumed"])
        finally:
            server.close()

        self.assertEqual(cancelled, [])
        self.assertEqual(resumed[0].status, 200)
        self.assertEqual(server.connection_count, 1)

    def test_reset_cancel_allows_scan_after_lifecycle_shutdown(self):
        server = CountingHTTPServer()
        engine = dirsearch_native.NativeHttpEngine()
        engine.cancel()
        engine.reset_cancel()

        try:
            results = engine.scan(server.url, ["resumed"])
        finally:
            server.close()

        self.assertEqual(results[0].status, 200)
        self.assertEqual(server.connection_count, 1)

    def test_explicit_cancellation_closes_raw_fallback_socket(self):
        server = StalledHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=5)
        cancel_timer = threading.Timer(0.1, engine.cancel)

        try:
            cancel_timer.start()
            started = time.monotonic()
            results = engine.scan(server.url, ["slow%1"])
            elapsed = time.monotonic() - started
            peer_closed = server.peer_closed.wait(timeout=1)
        finally:
            cancel_timer.join(timeout=1)
            server.close()

        self.assertEqual(results, [])
        self.assertLess(elapsed, 2)
        self.assertTrue(peer_closed)

    def test_raw_fallback_uses_end_to_end_timeout(self):
        server = StalledHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=0.2)

        try:
            started = time.monotonic()
            results = engine.scan(server.url, ["slow%1"])
            elapsed = time.monotonic() - started
        finally:
            server.close()

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].error)
        self.assertIn("timed out", results[0].error.lower())
        self.assertLess(elapsed, 2)

    def test_raw_fallback_timeout_is_not_reset_by_slow_body_bytes(self):
        server = SlowBodyServer()
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=0.2)

        try:
            started = time.monotonic()
            results = engine.scan(server.url, ["slow%1"])
            elapsed = time.monotonic() - started
        finally:
            server.close()

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].error)
        self.assertIn("timed out", results[0].error.lower())
        self.assertLess(elapsed, 1)

    def test_raw_fallback_decodes_chunked_body_before_capping(self):
        server = RawResponseServer(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
            b"4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n"
        )
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=1)

        try:
            results = engine.scan(server.url, ["chunked%1"], max_body_size=4)
        finally:
            server.close()

        self.assertEqual(server.request_target, "/chunked%1")
        self.assertIsNone(results[0].error)
        self.assertEqual(results[0].body, b"Wiki")
        self.assertEqual(results[0].length, 9)

    def test_raw_fallback_decodes_gzip_before_body_matching(self):
        compressed = bytes(
            [
                31,
                139,
                8,
                0,
                0,
                0,
                0,
                0,
                2,
                3,
                203,
                72,
                205,
                201,
                201,
                87,
                40,
                207,
                47,
                202,
                73,
                1,
                0,
                133,
                17,
                74,
                13,
                11,
                0,
                0,
                0,
            ]
        )
        server = RawResponseServer(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Encoding: gzip\r\n"
            + f"Content-Length: {len(compressed)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + compressed
        )
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=1)

        try:
            results = engine.scan(
                server.url,
                ["gzip%1"],
                matcher_mode="and",
                match_words=[(2, 2)],
                match_regex="hello world",
            )
        finally:
            server.close()

        self.assertIsNone(results[0].error)
        self.assertFalse(results[0].filtered)
        self.assertEqual(results[0].body, b"hello world")

    def test_client_decodes_gzip_before_body_matching(self):
        compressed = gzip.compress(b"hello world", mtime=0)
        server = RawResponseServer(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Encoding: gzip\r\n"
            + f"Content-Length: {len(compressed)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + compressed
        )
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=1)

        try:
            results = engine.scan(
                server.url,
                ["gzip"],
                matcher_mode="and",
                match_words=[(2, 2)],
                match_regex="hello world",
            )
        finally:
            server.close()

        self.assertIsNone(results[0].error)
        self.assertFalse(results[0].filtered)
        self.assertEqual(results[0].body, b"hello world")

    def test_python_signal_interrupts_active_scan(self):
        server = StalledHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=5)
        previous_handler = signal.getsignal(signal.SIGINT)
        signal_timer = threading.Timer(
            0.1, lambda: os.kill(os.getpid(), signal.SIGINT)
        )

        def interrupt_scan(_signum, _frame):
            raise NativeScanInterrupted("stop native scan")

        try:
            signal.signal(signal.SIGINT, interrupt_scan)
            signal_timer.start()
            started = time.monotonic()
            with self.assertRaisesRegex(NativeScanInterrupted, "stop native scan"):
                engine.scan(server.url, ["slow"])
            elapsed = time.monotonic() - started
        finally:
            signal_timer.join(timeout=1)
            signal.signal(signal.SIGINT, previous_handler)
            server.close()

        self.assertLess(elapsed, 2)
