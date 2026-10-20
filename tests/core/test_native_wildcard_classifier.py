import random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest import TestCase

from lib.connection.native import NativeHTTPBackend
from lib.connection.response import NativeResponse
from lib.core.filter_config import FilterConfig
from lib.core.native_runtime import get_native_extension_version_error
from lib.core.request_config import RequestConfig
from lib.core.scanner import Scanner
from lib.core.settings import WILDCARD_TEST_POINT_MARKER
from lib.utils.diff import DynamicContentParser, normalize_dynamic_content


def body(value):
    return f"Missing resource stable site page content nonce='{value}' trailing template text"


class ProbeRequester:
    def __init__(self):
        self.number = 0

    def request(self, path):
        self.number += 1
        return NativeResponse('http://example.invalid/' + path, 404,
                              [('Content-Type', 'text/html; charset=utf-8')], body(str(self.number)).encode())


class TestNativeWildcardClassifier(TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import dirsearch_native
        except ImportError:
            from unittest import SkipTest
            raise SkipTest('native extension not installed')
        if error := get_native_extension_version_error(dirsearch_native):
            from unittest import SkipTest
            raise SkipTest(error)
        cls.native = dirsearch_native

    def profile(self, first, second):
        parser = DynamicContentParser(first, second)
        return parser, self.native.NativeWildcardProfile(
            404, 'text/html', first, parser._normalized_contents, parser.static_patterns,
            parser._is_static, parser.is_ambiguous, len(first), 'default', 'random')

    def test_compiled_pattern_comparison_matches_python(self):
        rng = random.Random(20261022)
        for _ in range(300):
            first = ' '.join(rng.choices(['a', 'b', 'c', 'missing', 'stable'], k=rng.randrange(1, 45)))
            second = first.replace('a', 'other', 1)
            candidate = rng.choice([first, second, first + ' extra', first[::-1], 'different page'])
            parser, profile = self.profile(first, second)
            self.assertEqual(profile.compare(candidate, normalize_dynamic_content(candidate)), parser.compare_to(candidate))

    def test_invalid_profile_encoding_is_rejected(self):
        with self.assertRaises(ValueError):
            self.profile('café', 'café')

    def test_target_states_are_separate_and_thresholds_preserve_record_rules(self):
        first = self.native.NativeCalibrationState(auto_calibration=True)
        second = self.native.NativeCalibrationState(auto_calibration=True)
        key = (404, 'text/plain', '', 'missing')
        self.assertFalse(first.observe(*key, False))
        self.assertFalse(first.observe(*key, True))
        self.assertFalse(first.observe(*key, True))
        self.assertTrue(first.observe(*key, True))
        self.assertTrue(first.observe(*key, False))
        self.assertFalse(second.is_learned(*key))

    def test_fallback_observations_commit_before_later_native_misses(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                value = 'ñ' if self.path == '/fallback' else self.path
                data = body(value).encode()
                self.send_response(404)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        backend = NativeHTTPBackend(RequestConfig(concurrency=3, timeout=2), filter_config=FilterConfig())
        try:
            scanner = Scanner(ProbeRequester(), filter_config=FilterConfig(), delay=0, path=WILDCARD_TEST_POINT_MARKER)
            state = backend.new_calibration_state(True)
            backend.set_wildcard_classifier(backend.make_wildcard_classifier(
                {'default': {'random': scanner}}, state, '', ()))
            normalized = normalize_dynamic_content(body('first'))
            key = (404, 'text/html', '', normalized)
            delivered = []

            def receive(chunk):
                next_index = chunk.start_index
                for event in chunk.events:
                    state.commit_range(next_index, event.request_index)
                    delivered.append(event.path)
                    self.assertEqual(event.path, 'fallback')
                    self.assertFalse(state.is_learned(*key))
                    self.assertFalse(state.observe(*key, True))
                    next_index = event.request_index + 1
                state.commit_range(next_index, chunk.end_index)

            backend.scan_chunks(f'http://127.0.0.1:{server.server_port}/',
                                ['first', 'fallback', 'last'], receive)
            self.assertEqual(delivered, ['fallback'])
            self.assertTrue(state.is_learned(*key))
        finally:
            backend.close()
            server.shutdown()
            server.server_close()
            thread.join(3)
            self.assertFalse(thread.is_alive())

    def test_redirect_or_unicode_profiles_keep_python_classification(self):
        backend = NativeHTTPBackend(RequestConfig(), filter_config=FilterConfig())
        try:
            scanner = Scanner(ProbeRequester(), filter_config=FilterConfig(), delay=0, path=WILDCARD_TEST_POINT_MARKER)
            scanner.response.history.append('http://example.invalid/before')
            self.assertIsNone(backend.make_wildcard_classifier(
                {'default': {'random': scanner}}, backend.new_calibration_state(False), '', ()))
        finally:
            backend.close()
