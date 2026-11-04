import random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest import TestCase
from tempfile import TemporaryDirectory
from pathlib import Path
from lib.core.logger import RunLogger
from lib.core.log_config import LogConfig
from unittest.mock import patch

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
    def __init__(self, content_type='text/html; charset=utf-8'):
        self.number = 0
        self.headers = [] if content_type is None else [('Content-Type', content_type)]

    def request(self, path):
        self.number += 1
        return NativeResponse('http://example.invalid/' + path, 404,
                              self.headers, body(str(self.number)).encode())


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
        snapshot = parser.comparison_profile
        return parser, self.native.NativeWildcardProfile(
            404, 'text/html', first, snapshot.normalized_contents, snapshot.static_patterns,
            snapshot.is_static, snapshot.is_ambiguous, len(first), 'default', 'random')

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
        self.assertTrue(first.has_learned_status(404))
        self.assertFalse(first.has_learned_status(200))

    def test_state_preserves_isolated_surrogates_without_aliasing_other_text(self):
        state = self.native.NativeCalibrationState(True)
        for text in ['\ud800', '\udfff', '\\ud800', '\ufffd', '\U00010000', '\ud800\udc00']:
            key = (404, 'text/plain', '', text)
            self.assertFalse(state.is_learned(*key))
            self.assertFalse(state.observe(*key, True))
            self.assertFalse(state.observe(*key, True))
            self.assertTrue(state.observe(*key, True))
            self.assertTrue(state.is_learned(*key))

    def test_decoded_surrogate_fallback_matches_python_calibration(self):
        native = self.make_fuzzer()
        reference = self.make_fuzzer()
        native._native_calibration_state = self.native.NativeCalibrationState()
        response = NativeResponse(
            'http://example.invalid/account', 404,
            [('Content-Type', 'text/plain; charset=unicode_escape')],
            b'Account \\ud800 document with unique content and permission details')
        self.assertIn('\ud800', response.text)
        for _ in range(8):
            self.assertEqual(native.is_auto_calibrated(response), reference.is_auto_calibrated(response))
        self.assertTrue(native.is_auto_calibrated(response))

    def make_fuzzer(self):
        from lib.connection.native import NativeRequester
        from lib.core.discovery_config import DiscoveryConfig
        from lib.core.execution_config import ExecutionConfig
        from lib.core.fuzzer import NativeFuzzer
        from tests.core.test_native_fuzzer import DummyDictionary
        requester = NativeRequester(RequestConfig(), filter_config=FilterConfig())
        requester.set_url('http://example.invalid/')
        requester.get_backend()
        self.addCleanup(requester.close)
        return NativeFuzzer(requester, DummyDictionary([]), filter_config=FilterConfig(),
                            discovery_config=DiscoveryConfig(), execution_config=ExecutionConfig(),
                            match_callbacks=(), not_found_callbacks=(), error_callbacks=(),
                            filtered_chunk_callbacks=(lambda count: None,))

    def test_unrecorded_status_without_learned_keys_avoids_body_fingerprint(self):
        fuzzer = self.make_fuzzer()
        fuzzer._native_calibration_state = self.native.NativeCalibrationState()
        response = NativeResponse('http://example.invalid/endpoint', 201, [], b'A distinct account document')
        with patch.object(fuzzer, '_native_fingerprint_values', side_effect=AssertionError('unnecessary fingerprint')):
            self.assertFalse(fuzzer.is_auto_calibrated(response))

    def test_unsupported_first_directory_can_enable_later_without_losing_counts(self):
        fuzzer = self.make_fuzzer()
        scanner = Scanner(ProbeRequester(), filter_config=FilterConfig(), delay=0, path=WILDCARD_TEST_POINT_MARKER)
        scanner.response = NativeResponse('http://example.invalid/probe', 404, [], b'\x00\xff')
        fuzzer.filter_state.scanners['default']['random'] = scanner
        fuzzer._update_wildcard_classifier(clear=True)
        fuzzer._update_wildcard_classifier()
        state = fuzzer._native_calibration_state
        self.assertIsNotNone(state)
        self.assertIsNone(fuzzer._native_backend._wildcard_classifier)
        candidate = NativeResponse('http://example.invalid/path', 404, [], b'other document ' * 4)
        for _ in range(7):
            self.assertFalse(fuzzer.is_auto_calibrated(candidate))
        fuzzer.set_base_path('later/')
        fuzzer._update_wildcard_classifier(clear=True)
        fuzzer.filter_state.scanners['default']['random'] = Scanner(
            ProbeRequester(), filter_config=FilterConfig(), delay=0, path=WILDCARD_TEST_POINT_MARKER)
        fuzzer._update_wildcard_classifier()
        self.assertIs(fuzzer._native_calibration_state, state)
        self.assertIsNotNone(fuzzer._native_backend._wildcard_classifier)
        self.assertTrue(fuzzer.is_auto_calibrated(candidate))

    def test_existing_python_counts_are_not_discarded_to_enable_native(self):
        fuzzer = self.make_fuzzer()
        candidate = NativeResponse('http://example.invalid/path', 404, [], b'other document ' * 4)
        self.assertFalse(fuzzer.is_auto_calibrated(candidate))
        fuzzer.filter_state.scanners['default']['random'] = Scanner(
            ProbeRequester(), filter_config=FilterConfig(), delay=0, path=WILDCARD_TEST_POINT_MARKER)
        fuzzer._update_wildcard_classifier()
        self.assertIsNone(fuzzer._native_calibration_state)
        for _ in range(6):
            self.assertFalse(fuzzer.is_auto_calibrated(candidate))
        self.assertTrue(fuzzer.is_auto_calibrated(candidate))

    def test_native_fallback_logs_threshold_and_learned_fingerprint(self):
        fuzzer = self.make_fuzzer()
        fuzzer._native_calibration_state = self.native.NativeCalibrationState()
        with TemporaryDirectory() as directory:
            log = Path(directory, 'scan.log')
            with_logger = RunLogger(LogConfig(str(log)))
            try:
                fuzzer.logger = with_logger
                candidate = NativeResponse('http://example.invalid/account', 404, [], b'other document ' * 4)
                for _ in range(7):
                    self.assertFalse(fuzzer.is_auto_calibrated(candidate))
                self.assertTrue(fuzzer.is_auto_calibrated(candidate))
                self.assertTrue(fuzzer.is_auto_calibrated(candidate))
            finally:
                with_logger.close()
            text = log.read_text()
            self.assertIn('repeated response auto-calibration (threshold=8)', text)
            self.assertIn('filtered by auto-calibration fingerprint', text)

    def test_logged_wildcards_keep_compact_delivery_and_ordered_decisions(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                data = body(self.path).encode()
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
        fuzzer = self.make_fuzzer()
        fuzzer._requester.set_url(f'http://127.0.0.1:{server.server_port}/')
        fuzzer.filter_state.scanners['default']['random'] = Scanner(
            ProbeRequester(), filter_config=FilterConfig(), delay=0, path=WILDCARD_TEST_POINT_MARKER)
        paths = [f'missing-{i}' for i in range(12)]
        with TemporaryDirectory() as directory:
            log = Path(directory, 'scan.log')
            logger = RunLogger(LogConfig(str(log)))
            fuzzer.logger = fuzzer._native_backend.logger = logger
            try:
                fuzzer._update_wildcard_classifier()
                self.assertIsNotNone(fuzzer._native_backend._wildcard_classifier)
                fuzzer.play()
                with patch('lib.connection.native.NativeResponse', side_effect=AssertionError('wildcard decoded')):
                    processed = fuzzer._native_backend.scan_chunks(
                        server_url := f'http://127.0.0.1:{server.server_port}/', paths,
                        lambda chunk: fuzzer._process_native_chunk(paths, chunk))
                self.assertEqual(processed, len(paths))
            finally:
                logger.close()
                server.shutdown()
                server.server_close()
                thread.join(3)
            text = log.read_text()
            self.assertEqual(text.count('native_filter=wildcard'), len(paths))
            self.assertIn('repeated response auto-calibration (threshold=8)', text)
            self.assertIn('filtered by auto-calibration fingerprint', text)
            self.assertIn('decision=excluded', text)
            self.assertIn(server_url + paths[-1], text)
            self.assertFalse(thread.is_alive())

    def test_fallback_observations_commit_before_later_native_misses(self):
        self.check_fallback_order('text/html; charset=utf-8')

    def test_missing_content_type_uses_the_shared_unknown_fingerprint_type(self):
        self.check_fallback_order(None)

    def check_fallback_order(self, content_type):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                value = 'ñ' if self.path == '/fallback' else self.path
                data = body(value).encode()
                self.send_response(404)
                if content_type is not None:
                    self.send_header('Content-Type', content_type)
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
            scanner = Scanner(ProbeRequester(content_type), filter_config=FilterConfig(), delay=0, path=WILDCARD_TEST_POINT_MARKER)
            state = backend.new_calibration_state(True)
            backend.set_wildcard_classifier(backend.make_wildcard_classifier(
                {'default': {'random': scanner}}, state, '', ()))
            normalized = normalize_dynamic_content(body('first'))
            key = (404, scanner.response.type, '', normalized)
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

    def test_checked_findings_reuse_worker_comparison_and_normalization(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                data = ('A distinct account document with valuable unique details ' * 3).encode()
                if self.path == '/unicode':
                    data += 'ñ'.encode()
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
        fuzzer = self.make_fuzzer()
        scanner = Scanner(ProbeRequester(), filter_config=FilterConfig(), delay=0,
                          path=WILDCARD_TEST_POINT_MARKER)
        fuzzer.filter_state.scanners['default']['random'] = scanner
        fuzzer.match_callbacks = (lambda response: None,)
        fuzzer.not_found_callbacks = (lambda response: None,)
        fuzzer._update_wildcard_classifier()
        events = []
        try:
            fuzzer._native_backend.scan_chunks(
                f'http://127.0.0.1:{server.server_port}/', ['unique', 'unicode'],
                lambda chunk: events.extend(chunk.events))
            self.assertEqual([event.path for event in events], ['unique', 'unicode'])
            unique, unicode = [event.response for event in events]
            self.assertTrue(unique.wildcard_checked)
            self.assertEqual(unique.normalized_content, normalize_dynamic_content(unique.text))
            self.assertFalse(unicode.wildcard_checked)
            with patch.object(scanner, 'check', side_effect=AssertionError('duplicate comparison')):
                self.assertEqual(fuzzer.response_callbacks('unique', unique), fuzzer.match_callbacks)
                with patch.object(fuzzer, 'is_auto_calibrated', return_value=True):
                    self.assertEqual(fuzzer.response_callbacks('unique', unique), fuzzer.not_found_callbacks)
                with patch.object(fuzzer, 'is_filter_threshold_reached', return_value=True):
                    self.assertEqual(fuzzer.response_callbacks('unique', unique), fuzzer.not_found_callbacks)
            with patch.object(scanner, 'check', return_value=True) as compare:
                self.assertEqual(fuzzer.response_callbacks('unicode', unicode), fuzzer.match_callbacks)
                compare.assert_called_once_with('unicode', unicode)
        finally:
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
