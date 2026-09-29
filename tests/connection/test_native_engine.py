import gzip
import os
import signal
import socket
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import TestCase, skipUnless

from lib.core.native_runtime import NATIVE_EXTENSION_VERSION


ZSTD_HELLO_WORLD = bytes(
    [
        0x28,
        0xB5,
        0x2F,
        0xFD,
        0x04,
        0x58,
        0x59,
        0x00,
        0x00,
        0x68,
        0x65,
        0x6C,
        0x6C,
        0x6F,
        0x20,
        0x77,
        0x6F,
        0x72,
        0x6C,
        0x64,
        0x68,
        0x69,
        0x1E,
        0xB2,
    ]
)

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
        self.request_headers = None
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
                self.request_headers = bytes(request).split(b"\r\n\r\n", 1)[0]
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
        with self.server.request_count_lock:
            self.server.request_count += 1
            if self.server.request_count >= 20:
                self.server.twenty_requests.set()
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            # Cancellation may close a request while this fixture responds.
            pass

    def log_message(self, _format, *args):
        return None


class UserAgentCaptureHandler(KeepAliveHandler):
    def do_GET(self):
        with self.server.user_agents_lock:
            self.server.user_agents.append(self.headers.get("User-Agent"))
        super().do_GET()


class RequestTimeCaptureHandler(KeepAliveHandler):
    def do_GET(self):
        with self.server.request_times_lock:
            self.server.request_times.append(time.monotonic())
        super().do_GET()


class ControlledStreamHandler(KeepAliveHandler):
    def do_GET(self):
        if self.path == "/slow":
            self.server.slow_started.set()
            if not self.server.release_slow.wait(timeout=2):
                return
        super().do_GET()


class MixedStatusHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        status = 200 if self.path == "/match" else 404
        body = b"ok"
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *args):
        return None


class RedirectChainHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", "/middle")
            body = b""
        elif self.path == "/middle":
            self.send_response(307)
            self.send_header("Location", "/final?ok=1")
            body = b""
        else:
            self.send_response(200)
            body = b"ok"
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *args):
        return None


class ProxyAuthenticationRequiredHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        body = b"proxy authentication required"
        self.send_response(407)
        self.send_header("Proxy-Authenticate", 'Basic realm="dirsearch-test"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *args):
        return None


class CookieSessionHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        cookie = self.headers.get("Cookie")
        self.server.cookies.append(cookie)
        if self.path == "/set":
            status = 200
            headers = {"Set-Cookie": "session=native; Path=/"}
        elif self.path == "/redirect":
            status = 302
            headers = {
                "Location": "/redirected",
                "Set-Cookie": "redirect=native; Path=/",
            }
        elif self.path == "/redirected":
            status = 200 if cookie and "redirect=native" in cookie else 401
            headers = {}
        else:
            status = 200 if cookie and "session=native" in cookie else 401
            headers = {}
        body = b"ok"
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *args):
        return None


class CountingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, handler=KeepAliveHandler):
        super().__init__(("127.0.0.1", 0), handler)
        self.connection_count = 0
        self.cookies = []
        self.user_agents = []
        self.user_agents_lock = threading.Lock()
        self.request_times = []
        self.request_times_lock = threading.Lock()
        self.request_count = 0
        self.request_count_lock = threading.Lock()
        self.twenty_requests = threading.Event()
        self.slow_started = threading.Event()
        self.release_slow = threading.Event()
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
    def test_extension_version_matches_python_contract(self):
        self.assertEqual(dirsearch_native.__version__, NATIVE_EXTENSION_VERSION)

    def test_invalid_request_delay_is_rejected_at_the_python_boundary(self):
        for delay in (-0.1, float("nan"), float("inf")):
            with (
                self.subTest(delay=delay),
                self.assertRaisesRegex(
                    RuntimeError,
                    "request delay must be a finite, non-negative number",
                ),
            ):
                dirsearch_native.NativeHttpEngine(delay_secs=delay)

    def test_invalid_client_identity_is_rejected_at_the_python_boundary(self):
        for certificate, key in (
            (b"not a certificate", b"not a private key"),
            (b"", b"not a private key"),
            (b"not a certificate", b""),
        ):
            with (
                self.subTest(certificate=certificate, key=key),
                self.assertRaisesRegex(
                    RuntimeError,
                    "Invalid client certificate or private key",
                ),
            ):
                dirsearch_native.NativeHttpEngine(
                    client_certificate=certificate,
                    client_key=key,
                )

    def test_invalid_native_session_is_rejected_at_the_python_boundary(self):
        with self.assertRaises(TypeError):
            dirsearch_native.NativeHttpEngine(session=object())

    def test_invalid_connection_overrides_are_rejected_at_the_python_boundary(self):
        for override, message in (
            (
                [("example.test", 443, "not-an-ip")],
                "Invalid --ip value",
            ),
            (
                [("127.0.0.2", 443, "127.0.0.1")],
                "cannot reroute an IP-literal target",
            ),
        ):
            with (
                self.subTest(override=override),
                self.assertRaisesRegex(RuntimeError, message),
            ):
                dirsearch_native.NativeHttpEngine(
                    connection_overrides=override
                )

        with self.assertRaisesRegex(
            RuntimeError,
            "cannot be combined with a proxy",
        ):
            dirsearch_native.NativeHttpEngine(
                proxies=["http://127.0.0.1:8080"],
                connection_overrides=[
                    ("example.test", 443, "127.0.0.1")
                ],
            )

    def test_random_agents_reject_a_fixed_user_agent_header(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "Random User-Agent values cannot be combined with a fixed "
            "User-Agent header",
        ):
            dirsearch_native.NativeHttpEngine(
                headers=[("User-Agent", "fixed-agent")],
                random_user_agents=["random-agent"],
            )

    def test_invalid_random_agent_value_is_rejected_at_the_python_boundary(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "Invalid random User-Agent value",
        ):
            dirsearch_native.NativeHttpEngine(
                random_user_agents=["valid-agent", "invalid\r\nheader"]
            )

    def test_native_engine_prepares_raw_paths_and_query(self):
        server = RawResponseServer(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
        )
        engine = dirsearch_native.NativeHttpEngine(concurrency=1)

        try:
            results = engine.scan(
                server.url,
                ["missing page/测试"],
                query="scope=hello world",
            )
        finally:
            server.close()

        expected = "missing%20page/%E6%B5%8B%E8%AF%95?scope=hello%20world"
        self.assertEqual(server.request_target, f"/{expected}")
        self.assertEqual(results[0].path, expected)

    def test_raw_path_request_receives_request_local_random_agent(self):
        server = RawResponseServer(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
            b"Connection: close\r\n\r\nok"
        )
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            random_user_agents=["raw-path-agent"],
        )

        try:
            results = engine.scan(server.url, ["malformed%1"])
        finally:
            server.close()

        self.assertEqual(results[0].status, 200)
        self.assertIn(
            b"\r\nUser-Agent: raw-path-agent\r\n",
            b"\r\n" + server.request_headers + b"\r\n",
        )

    def test_followed_redirects_preserve_every_requested_url_in_history(self):
        server = CountingHTTPServer(RedirectChainHandler)
        base_url = server.url
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            follow_redirects=True,
        )

        try:
            result = engine.scan(base_url, ["start"])[0]
        finally:
            server.close()

        self.assertEqual(result.status, 200)
        self.assertEqual(
            result.history,
            [f"{base_url}start", f"{base_url}middle"],
        )

    def test_session_cookie_is_reused_by_later_scan(self):
        server = CountingHTTPServer(CookieSessionHandler)
        engine = dirsearch_native.NativeHttpEngine(concurrency=1)

        try:
            first = engine.scan(server.url, ["set"])[0]
            second = engine.scan(server.url, ["required"])[0]
        finally:
            server.close()

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(server.cookies, [None, "session=native"])

    def test_explicit_session_is_shared_across_engine_rebuilds(self):
        server = CountingHTTPServer(CookieSessionHandler)
        session = dirsearch_native.NativeHttpSession()
        first_engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            session=session,
        )
        rebuilt_engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            follow_redirects=True,
            session=session,
        )

        try:
            stored = first_engine.scan(server.url, ["set"])[0]
            reused = rebuilt_engine.scan(server.url, ["required"])[0]
        finally:
            server.close()

        self.assertEqual(stored.status, 200)
        self.assertEqual(reused.status, 200)
        self.assertEqual(server.cookies, [None, "session=native"])

    def test_default_sessions_are_isolated_between_engines(self):
        server = CountingHTTPServer(CookieSessionHandler)
        first_engine = dirsearch_native.NativeHttpEngine(concurrency=1)
        separate_engine = dirsearch_native.NativeHttpEngine(concurrency=1)

        try:
            stored = first_engine.scan(server.url, ["set"])[0]
            isolated = separate_engine.scan(server.url, ["required"])[0]
        finally:
            server.close()

        self.assertEqual(stored.status, 200)
        self.assertEqual(isolated.status, 401)
        self.assertEqual(server.cookies, [None, None])

    def test_session_cookie_is_reused_by_raw_fallback(self):
        server = CountingHTTPServer(CookieSessionHandler)
        engine = dirsearch_native.NativeHttpEngine(concurrency=1)

        try:
            first = engine.scan(server.url, ["set"])[0]
            second = engine.scan(server.url, ["required%1"])[0]
        finally:
            server.close()

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(server.cookies, [None, "session=native"])

    def test_redirect_response_cookie_is_applied_to_next_hop(self):
        server = CountingHTTPServer(CookieSessionHandler)
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            follow_redirects=True,
        )

        try:
            result = engine.scan(server.url, ["redirect"])[0]
        finally:
            server.close()

        self.assertEqual(result.status, 200)
        self.assertEqual(server.cookies, [None, "redirect=native"])

    def test_chunks_deliver_an_ordered_prefix_before_scan_finishes(self):
        server = CountingHTTPServer(ControlledStreamHandler)
        engine = dirsearch_native.NativeHttpEngine(concurrency=2)
        chunks = []
        first_chunk = threading.Event()
        scan_finished = threading.Event()
        scan_errors = []

        def callback(start_index, end_index, results):
            chunks.append((start_index, end_index, results))
            first_chunk.set()

        def scan():
            try:
                engine.scan_chunks(
                    server.url,
                    ["fast", "slow"],
                    callback,
                    chunk_size=1,
                )
            except BaseException as error:
                scan_errors.append(error)
            finally:
                scan_finished.set()

        worker = threading.Thread(target=scan)
        worker.start()
        try:
            self.assertTrue(server.slow_started.wait(timeout=1))
            self.assertTrue(first_chunk.wait(timeout=1))
            self.assertFalse(scan_finished.is_set())
            self.assertEqual(chunks[0][0:2], (0, 1))
            self.assertEqual(
                [result.request_index for result in chunks[0][2]],
                [0],
            )
        finally:
            server.release_slow.set()
            worker.join(timeout=1)
            server.close()

        self.assertFalse(worker.is_alive())
        self.assertEqual(scan_errors, [])
        self.assertEqual(chunks[-1][0:2], (1, 2))

    def test_chunks_compact_filtered_misses_into_progress_only(self):
        server = CountingHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(concurrency=2)
        chunks = []

        try:
            processed_count = engine.scan_chunks(
                server.url,
                ["zero", "one", "two"],
                lambda start, end, results: chunks.append(
                    (start, end, results)
                ),
                filter_config=dirsearch_native.NativeFilterConfig(
                    include_status_codes=[201]
                ),
            )
        finally:
            server.close()

        self.assertEqual(processed_count, 3)
        self.assertEqual(chunks[0][0], 0)
        self.assertEqual(chunks[-1][1], 3)
        self.assertEqual(
            [start for start, _end, _results in chunks[1:]],
            [end for _start, end, _results in chunks[:-1]],
        )
        self.assertTrue(all(not results for _start, _end, results in chunks))

    def test_chunks_wait_for_missing_prefix_before_delivering(self):
        server = CountingHTTPServer(ControlledStreamHandler)
        engine = dirsearch_native.NativeHttpEngine(concurrency=2)
        chunks = []
        chunk_received = threading.Event()

        def callback(start_index, end_index, results):
            chunks.append((start_index, end_index, results))
            chunk_received.set()

        worker = threading.Thread(
            target=lambda: engine.scan_chunks(
                server.url,
                ["slow", "fast"],
                callback,
                chunk_size=1,
            )
        )
        worker.start()
        try:
            self.assertTrue(server.slow_started.wait(timeout=1))
            self.assertFalse(chunk_received.wait(timeout=0.1))
            server.release_slow.set()
            self.assertTrue(chunk_received.wait(timeout=1))
        finally:
            server.release_slow.set()
            worker.join(timeout=1)
            server.close()

        self.assertFalse(worker.is_alive())
        self.assertEqual(
            [(start, end) for start, end, _results in chunks],
            [(0, 1), (1, 2)],
        )
        self.assertEqual(
            [
                result.request_index
                for _start, _end, results in chunks
                for result in results
            ],
            [0, 1],
        )

    def test_chunk_backpressure_bounds_work_while_callback_is_blocked(self):
        server = CountingHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(concurrency=2)
        callback_started = threading.Event()
        release_callback = threading.Event()
        scan_errors = []

        def callback(_start_index, _processed_count, _results):
            callback_started.set()
            if not release_callback.wait(timeout=2):
                raise AssertionError("chunk callback was not released")

        def scan():
            try:
                engine.scan_chunks(
                    server.url,
                    [f"path-{index}" for index in range(50)],
                    callback,
                    chunk_size=1,
                )
            except BaseException as error:
                scan_errors.append(error)

        worker = threading.Thread(target=scan)
        worker.start()
        try:
            self.assertTrue(callback_started.wait(timeout=1))
            self.assertFalse(server.twenty_requests.wait(timeout=0.2))
            with server.request_count_lock:
                self.assertLess(server.request_count, 20)
        finally:
            release_callback.set()
            worker.join(timeout=5)
            server.close()

        self.assertFalse(worker.is_alive())
        self.assertEqual(scan_errors, [])

    def test_chunks_propagate_callback_errors_and_stop_workers(self):
        server = CountingHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(concurrency=2)

        def fail_callback(_start_index, _processed_count, _results):
            raise NativeScanInterrupted("stop incremental delivery")

        try:
            with self.assertRaisesRegex(
                NativeScanInterrupted,
                "stop incremental delivery",
            ):
                engine.scan_chunks(
                    server.url,
                    [f"path-{index}" for index in range(200)],
                    fail_callback,
                    chunk_size=1,
                )
        finally:
            server.close()

        with server.request_count_lock:
            self.assertLess(server.request_count, 200)

    def test_chunks_reject_invalid_callback_and_chunk_size(self):
        engine = dirsearch_native.NativeHttpEngine(concurrency=1)

        with self.assertRaisesRegex(TypeError, "callback must be callable"):
            engine.scan_chunks("http://127.0.0.1/", [], object())
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            engine.scan_chunks(
                "http://127.0.0.1/",
                [],
                lambda *_args: None,
                chunk_size=0,
            )

    def test_removed_legacy_scan_entrypoints_are_not_exported(self):
        engine = dirsearch_native.NativeHttpEngine(concurrency=1)
        wordlist = dirsearch_native.generate_wordlist_owned(
            ["tests/static/wordlist.txt"],
            ["php"],
        )

        self.assertFalse(hasattr(dirsearch_native, "scan_http"))
        self.assertFalse(hasattr(dirsearch_native, "NativeWordlistBatch"))
        self.assertFalse(hasattr(engine, "scan_owned"))
        self.assertFalse(hasattr(engine, "scan_batch"))
        self.assertFalse(hasattr(engine, "scan_owned_batch"))
        self.assertFalse(hasattr(wordlist, "batch"))

    def test_chunks_preserve_filtered_proxy_authentication_responses(self):
        proxy = CountingHTTPServer(ProxyAuthenticationRequiredHandler)
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            proxies=[proxy.url],
        )
        chunks = []

        try:
            processed_count = engine.scan_chunks(
                "http://example.test/",
                ["zero", "one", "two"],
                lambda start, end, results: chunks.append(
                    (start, end, results)
                ),
                filter_config=dirsearch_native.NativeFilterConfig(
                    include_status_codes=[200]
                ),
            )
        finally:
            proxy.close()

        results = [
            result
            for _start, _end, chunk_results in chunks
            for result in chunk_results
        ]
        self.assertEqual(processed_count, 3)
        self.assertEqual([result.request_index for result in results], [0, 1, 2])
        self.assertTrue(all(result.status == 407 for result in results))
        self.assertTrue(all(result.filtered for result in results))

    def test_chunks_preserve_status_filtered_body_decode_errors(self):
        server = RawResponseServer(
            b"HTTP/1.1 404 Not Found\r\n"
            b"Content-Encoding: gzip\r\n"
            b"Content-Length: 4\r\n"
            b"Connection: close\r\n\r\n"
            b"nope"
        )
        engine = dirsearch_native.NativeHttpEngine(concurrency=1)
        chunks = []

        try:
            engine.scan_chunks(
                server.url,
                ["broken"],
                lambda start, end, results: chunks.append(
                    (start, end, results)
                ),
                filter_config=dirsearch_native.NativeFilterConfig(
                    include_status_codes=[200]
                ),
            )
        finally:
            server.close()

        result = chunks[0][2][0]
        self.assertEqual(result.path, "broken")
        self.assertIsNotNone(result.error)
        self.assertIn("decode", result.error.lower())

    def test_owned_wordlist_batch_supports_chunk_delivery(self):
        wordlist = dirsearch_native.generate_wordlist_owned(
            ["tests/static/wordlist.txt"],
            ["php"],
        )
        chunk = wordlist.chunk(0, 2, "api/")
        server = CountingHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(concurrency=1)
        chunks = []

        try:
            processed_count = engine.scan_owned_chunks(
                server.url,
                chunk,
                lambda start, end, results: chunks.append(
                    (start, end, results)
                ),
                query="scope=one",
                chunk_size=1,
            )
        finally:
            server.close()

        self.assertEqual(processed_count, 2)
        self.assertEqual(
            [(start, end) for start, end, _results in chunks],
            [(0, 1), (1, 2)],
        )
        self.assertEqual(
            [
                result.path
                for _start, _end, results in chunks
                for result in results
            ],
            ["api/index.php?scope=one", "api/home.html?scope=one"],
        )

    def test_owned_wordlist_chunks_prepare_path_and_query_on_demand(self):
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
        ) as wordlist_file:
            wordlist_file.write("missing page/测试#part\n")
            wordlist_file.flush()
            wordlist = dirsearch_native.generate_wordlist_owned(
                [wordlist_file.name],
                [],
            )
            chunk = wordlist.chunk(0, 1, "api/")

            server = RawResponseServer(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
                b"Connection: close\r\n\r\nok"
            )
            engine = dirsearch_native.NativeHttpEngine(concurrency=1)
            chunks = []

            try:
                processed_count = engine.scan_owned_chunks(
                    server.url,
                    chunk,
                    lambda start, end, results: chunks.append(
                        (start, end, results)
                    ),
                    query="scope=hello world",
                    chunk_size=1,
                )
            finally:
                server.close()

        expected = (
            "api/missing%20page/%E6%B5%8B%E8%AF%95"
            "?scope=hello%20world#part"
        )
        self.assertEqual(processed_count, 1)
        self.assertEqual(
            server.request_target,
            "/api/missing%20page/%E6%B5%8B%E8%AF%95"
            "?scope=hello%20world",
        )
        self.assertEqual(chunks[0][2][0].path, expected)
        self.assertEqual(chunk.path_at(0), "api/missing page/测试#part")

    def test_owned_wordlist_chunks_compact_filtered_paths(self):
        wordlist = dirsearch_native.generate_wordlist_owned(
            ["tests/static/wordlist.txt"],
            ["php"],
        )
        chunk = wordlist.chunk(0, 2, "api/")
        server = CountingHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(concurrency=2)
        chunks = []

        try:
            processed_count = engine.scan_owned_chunks(
                server.url,
                chunk,
                lambda start, end, results: chunks.append(
                    (start, end, results)
                ),
                filter_config=dirsearch_native.NativeFilterConfig(
                    include_status_codes=[201]
                ),
                chunk_size=1,
            )
        finally:
            server.close()

        self.assertEqual(processed_count, 2)
        self.assertEqual(
            [(start, end) for start, end, _results in chunks],
            [(0, 1), (1, 2)],
        )
        self.assertTrue(all(not results for _start, _end, results in chunks))

    def test_owned_wordlist_chunks_preserve_error_path(self):
        wordlist = dirsearch_native.generate_wordlist_owned(
            ["tests/static/wordlist.txt"],
            ["php"],
        )
        chunk = wordlist.chunk(0, 1, "api/")
        server = RawResponseServer(
            b"HTTP/1.1 404 Not Found\r\n"
            b"Content-Encoding: gzip\r\n"
            b"Content-Length: 4\r\n"
            b"Connection: close\r\n\r\n"
            b"nope"
        )
        engine = dirsearch_native.NativeHttpEngine(concurrency=1)
        chunks = []

        try:
            processed_count = engine.scan_owned_chunks(
                server.url,
                chunk,
                lambda start, end, results: chunks.append(
                    (start, end, results)
                ),
                filter_config=dirsearch_native.NativeFilterConfig(
                    include_status_codes=[200]
                ),
                chunk_size=1,
            )
        finally:
            server.close()

        self.assertEqual(processed_count, 1)
        self.assertEqual(chunks[0][2][0].path, "api/index.php")
        self.assertIsNotNone(chunks[0][2][0].error)
        self.assertIn("decode", chunks[0][2][0].error.lower())

    def test_owned_wordlist_chunk_cancellation_stops_pending_request(self):
        wordlist = dirsearch_native.generate_wordlist_owned(
            ["tests/static/wordlist.txt"],
            ["php"],
        )
        chunk = wordlist.chunk(0, 1)
        server = StalledHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            timeout_secs=5,
        )
        cancel_timer = threading.Timer(0.1, engine.cancel)

        try:
            cancel_timer.start()
            started = time.monotonic()
            processed_count = engine.scan_owned_chunks(
                server.url,
                chunk,
                lambda *_args: None,
                chunk_size=1,
            )
            elapsed = time.monotonic() - started
            self.assertTrue(server.peer_closed.wait(timeout=1))
        finally:
            cancel_timer.join(timeout=1)
            server.close()

        self.assertEqual(processed_count, 0)
        self.assertLess(elapsed, 2)

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

    def test_delay_spaces_a_worker_across_scans(self):
        server = CountingHTTPServer(RequestTimeCaptureHandler)
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            delay_secs=0.15,
        )

        try:
            first = engine.scan(server.url, ["first"])
            second = engine.scan(server.url, ["second"])
        finally:
            server.close()

        self.assertEqual([first[0].status, second[0].status], [200, 200])
        self.assertEqual(len(server.request_times), 2)
        self.assertGreaterEqual(
            server.request_times[1] - server.request_times[0],
            0.12,
        )

    def test_rate_limit_is_shared_by_engines_in_one_session(self):
        server = CountingHTTPServer(RequestTimeCaptureHandler)
        session = dirsearch_native.NativeHttpSession()
        first_engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            max_rate=1,
            session=session,
        )
        rebuilt_engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            max_rate=1,
            follow_redirects=True,
            session=session,
        )

        try:
            first = first_engine.scan(server.url, ["first"])
            second = rebuilt_engine.scan(server.url, ["second"])
        finally:
            server.close()

        self.assertEqual([first[0].status, second[0].status], [200, 200])
        self.assertEqual(len(server.request_times), 2)
        self.assertGreaterEqual(
            server.request_times[1] - server.request_times[0],
            0.9,
        )
        self.assertEqual(rebuilt_engine.rate(), 1)

    def test_rate_limit_is_shared_by_concurrent_workers(self):
        server = CountingHTTPServer(RequestTimeCaptureHandler)
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=4,
            max_rate=2,
        )

        try:
            results = engine.scan(server.url, ["one", "two", "three"])
        finally:
            server.close()

        self.assertEqual(len(results), 3)
        self.assertEqual(len(server.request_times), 3)
        self.assertGreaterEqual(
            max(server.request_times) - min(server.request_times),
            0.9,
        )

    def test_unlimited_requests_are_reported_by_the_rate_meter(self):
        server = CountingHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(concurrency=2)

        try:
            results = engine.scan(server.url, ["first", "second"])
        finally:
            server.close()

        self.assertEqual(len(results), 2)
        self.assertEqual(engine.rate(), 2)

    def test_cancellation_interrupts_a_pending_worker_delay(self):
        server = CountingHTTPServer(RequestTimeCaptureHandler)
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            delay_secs=1.0,
        )
        engine.scan(server.url, ["first"])
        cancel_timer = threading.Timer(0.1, engine.cancel)

        try:
            cancel_timer.start()
            started = time.monotonic()
            results = engine.scan(server.url, ["cancelled"])
            elapsed = time.monotonic() - started
        finally:
            cancel_timer.join(timeout=1)
            server.close()

        self.assertEqual(results, [])
        self.assertEqual(len(server.request_times), 1)
        self.assertLess(elapsed, 0.5)

    def test_cancellation_interrupts_a_pending_rate_slot(self):
        server = CountingHTTPServer(RequestTimeCaptureHandler)
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=1,
            max_rate=1,
        )
        engine.scan(server.url, ["first"])
        cancel_timer = threading.Timer(0.1, engine.cancel)

        try:
            cancel_timer.start()
            started = time.monotonic()
            results = engine.scan(server.url, ["cancelled"])
            elapsed = time.monotonic() - started
        finally:
            cancel_timer.join(timeout=1)
            server.close()

        self.assertEqual(results, [])
        self.assertEqual(len(server.request_times), 1)
        self.assertLess(elapsed, 0.5)

    def test_concurrent_requests_keep_random_agents_request_local(self):
        server = CountingHTTPServer(UserAgentCaptureHandler)
        agents = ["native-agent-one", "native-agent-two"]
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=8,
            random_user_agents=agents,
        )

        try:
            results = engine.scan(
                server.url,
                [f"request-{index}" for index in range(32)],
            )
        finally:
            server.close()

        self.assertEqual(len(results), 32)
        self.assertEqual(len(server.user_agents), 32)
        self.assertTrue(
            all(user_agent in agents for user_agent in server.user_agents)
        )

    def test_every_proxy_client_receives_request_local_random_agents(self):
        first_proxy = CountingHTTPServer(UserAgentCaptureHandler)
        second_proxy = CountingHTTPServer(UserAgentCaptureHandler)
        engine = dirsearch_native.NativeHttpEngine(
            concurrency=4,
            proxies=[first_proxy.url, second_proxy.url],
            random_user_agents=["proxy-agent"],
        )

        try:
            results = engine.scan(
                "http://example.test/",
                [f"proxy-request-{index}" for index in range(4)],
            )
        finally:
            first_proxy.close()
            second_proxy.close()

        self.assertEqual(len(results), 4)
        self.assertEqual(first_proxy.user_agents, ["proxy-agent"] * 2)
        self.assertEqual(second_proxy.user_agents, ["proxy-agent"] * 2)

    def test_explicit_cancellation_interrupts_active_scan(self):
        server = StalledHTTPServer()
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=5)
        cancel_timer = threading.Timer(0.1, engine.cancel)

        try:
            cancel_timer.start()
            started = time.monotonic()
            results = engine.scan(server.url, ["slow"])
            elapsed = time.monotonic() - started
            self.assertTrue(server.peer_closed.wait(timeout=1))
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
                filter_config=dirsearch_native.NativeFilterConfig(
                    matcher_mode="and",
                    match_words=[(2, 2)],
                    match_regex="hello world",
                ),
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
                filter_config=dirsearch_native.NativeFilterConfig(
                    matcher_mode="and",
                    match_words=[(2, 2)],
                    match_regex="hello world",
                ),
            )
        finally:
            server.close()

        self.assertIsNone(results[0].error)
        self.assertFalse(results[0].filtered)
        self.assertEqual(results[0].body, b"hello world")

    def test_client_decodes_zstd_before_body_matching(self):
        server = RawResponseServer(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Encoding: zstd\r\n"
            + f"Content-Length: {len(ZSTD_HELLO_WORLD)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + ZSTD_HELLO_WORLD
        )
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=1)

        try:
            results = engine.scan(
                server.url,
                ["zstd"],
                filter_config=dirsearch_native.NativeFilterConfig(
                    matcher_mode="and",
                    match_words=[(2, 2)],
                    match_regex="hello world",
                ),
            )
        finally:
            server.close()

        self.assertIsNone(results[0].error)
        self.assertFalse(results[0].filtered)
        self.assertEqual(results[0].body, b"hello world")
        self.assertEqual(results[0].length, len(ZSTD_HELLO_WORLD))

    def test_raw_fallback_decodes_zstd_before_body_matching(self):
        server = RawResponseServer(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Encoding: zstd\r\n"
            + f"Content-Length: {len(ZSTD_HELLO_WORLD)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + ZSTD_HELLO_WORLD
        )
        engine = dirsearch_native.NativeHttpEngine(timeout_secs=1)

        try:
            results = engine.scan(
                server.url,
                ["zstd%1"],
                filter_config=dirsearch_native.NativeFilterConfig(
                    matcher_mode="and",
                    match_words=[(2, 2)],
                    match_regex="hello world",
                ),
            )
        finally:
            server.close()

        self.assertIsNone(results[0].error)
        self.assertFalse(results[0].filtered)
        self.assertEqual(results[0].body, b"hello world")
        self.assertEqual(results[0].length, len(ZSTD_HELLO_WORLD))

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
            self.assertTrue(server.peer_closed.wait(timeout=1))
        finally:
            signal_timer.join(timeout=1)
            signal.signal(signal.SIGINT, previous_handler)
            server.close()

        self.assertLess(elapsed, 2)
