import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import TestCase

from lib.connection.native import NativeRequester
from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig
from lib.core.filter_config import FilterConfig
from lib.core.fuzzer import NativeFuzzer
from lib.core.native_runtime import get_native_extension_version_error
from lib.core.request_config import RequestConfig
from tests.core.test_native_fuzzer import DummyDictionary


class TestNativeCalibrationProbes(TestCase):
    @classmethod
    def setUpClass(cls):
        from unittest import SkipTest
        try:
            import dirsearch_native
        except ImportError:
            raise SkipTest('native extension not installed')
        if error := get_native_extension_version_error(dirsearch_native):
            raise SkipTest(error)

    def measure(self, config, set_cookie=False):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                with self.server.state_lock:
                    self.server.active += 1
                    self.server.maximum = max(self.server.maximum, self.server.active)
                    self.server.requests += 1
                try:
                    time.sleep(0.025)
                    self.send_response(404)
                    self.send_header('Content-Length', '7')
                    if set_cookie:
                        self.send_header('Set-Cookie', 'session=test; Path=/')
                    self.end_headers()
                    self.wfile.write(b'missing')
                finally:
                    with self.server.state_lock:
                        self.server.active -= 1

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.state_lock = threading.Lock()
        server.active = server.maximum = server.requests = 0
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        requester = NativeRequester(config, filter_config=FilterConfig())
        requester.set_url(f'http://127.0.0.1:{server.server_port}/')
        requester.get_backend()
        fuzzer = NativeFuzzer(requester, DummyDictionary([]), filter_config=FilterConfig(),
                              discovery_config=DiscoveryConfig(prefixes=('one', 'two', 'three', 'four', 'five')),
                              execution_config=ExecutionConfig(), match_callbacks=(), not_found_callbacks=(),
                              error_callbacks=(), filtered_chunk_callbacks=(lambda count: None,))
        try:
            profile_count = len(list(fuzzer._scanner_specs()))
            fuzzer.setup_scanners()
            self.assertEqual(server.requests, profile_count + 1)
            return server.maximum
        finally:
            requester.close()
            server.shutdown()
            server.server_close()
            thread.join(3)
            self.assertFalse(thread.is_alive())

    def test_plain_get_first_probes_are_bounded_and_keep_probe_budget(self):
        maximum = self.measure(RequestConfig(concurrency=8, timeout=3))
        self.assertGreater(maximum, 1)
        self.assertLessEqual(maximum, 4)

    def test_server_cookie_preserves_sequential_calibration(self):
        self.assertEqual(self.measure(RequestConfig(concurrency=8, timeout=3), set_cookie=True), 1)

    def test_explicit_cookie_and_rate_limit_preserve_sequential_calibration(self):
        with_cookie = RequestConfig(concurrency=8, timeout=3, headers=(('Cookie', 'session=test'),))
        self.assertEqual(self.measure(with_cookie), 1)
        self.assertEqual(self.measure(RequestConfig(concurrency=8, timeout=3, max_rate=1000)), 1)
