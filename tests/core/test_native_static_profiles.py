import importlib.util
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest import TestCase, skipUnless
from unittest.mock import patch

from lib.connection.native import NativeHTTPBackend, NativeScanChunk, NativeScanEvent
from lib.connection.response import NativeResponse
from lib.core.filter_config import FilterConfig
from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig
from lib.core.exceptions import RequestException, SkipTargetInterrupt
from lib.core.fuzzer import NativeFuzzer
from lib.core.native_runtime import NATIVE_EXTENSION_VERSION, get_native_extension_version_error
from lib.core.request_config import RequestConfig
from lib.core.scanner import Scanner
from lib.core.settings import WILDCARD_TEST_POINT_MARKER
from tests.connection.test_native_backend import FakeNativeModule
from tests.core.test_native_fuzzer import DummyDictionary, DummyRequester


class ProbeRequester:
    def __init__(self, samples):
        self.samples = samples
        self.count = 0

    def request(self, path):
        values = self.samples[min(self.count, len(self.samples) - 1)]
        self.count += 1
        return NativeResponse(f"http://example.com/{path}", **values)


class TestStaticProfiles(TestCase):
    def sample(self, **changes):
        values = dict(status=404, headers=[("content-type", "text/plain")], body=b"Missing page.")
        values.update(changes)
        return values

    def scanner(self, samples, **options):
        return Scanner(
            ProbeRequester(samples), filter_config=FilterConfig(**options),
            delay=0, path=WILDCARD_TEST_POINT_MARKER,
        )

    def test_two_complete_identical_missing_probes_form_a_profile(self):
        scanner = self.scanner([self.sample(), self.sample()])
        self.assertEqual(scanner.static_response_profile, (404, "text/plain", b"Missing page."))

    def test_changed_or_incomplete_probe_does_not_form_a_profile(self):
        changes = (
            {"status": 403},
            {"body": b"A different page."},
            {"headers": [("content-type", "application/json")]},
            {"headers": [("content-type", "text/plain"), ("location", "/login")]},
            {"history": ["http://example.com/before"]},
            {"body_complete": False},
            {"body": b""},
            {"body": b"x" * 65537},
        )
        for change in changes:
            with self.subTest(change=list(change)):
                scanner = self.scanner([self.sample(), self.sample(**change)])
                self.assertIsNone(scanner.static_response_profile)

    def test_later_calibration_sample_invalidates_an_exact_profile(self):
        scanner = self.scanner(
            [self.sample(), self.sample(), self.sample(body=b"Temporarily unavailable.")],
            auto_calibration=True,
        )
        self.assertIsNone(scanner.static_response_profile)

    def test_a_single_duplicate_probe_does_not_inherit_a_static_profile(self):
        original = self.scanner([self.sample()])
        duplicate = Scanner(
            ProbeRequester([self.sample()]), filter_config=FilterConfig(), delay=0,
            path=WILDCARD_TEST_POINT_MARKER + "/", tested={"default": {"random": original}},
        )
        self.assertEqual(duplicate.sample_count, 1)
        self.assertIsNone(duplicate.static_response_profile)

    def test_older_extension_requires_a_rebuild(self):
        module = FakeNativeModule(results=[])
        module.__version__ = "0.2.20"
        with (
            patch.dict("sys.modules", {"dirsearch_native": module}),
            self.assertRaisesRegex(
                RequestException,
                rf"expected {re.escape(NATIVE_EXTENSION_VERSION)}, found 0\.2\.20.*dirsearch-build-native",
            ),
        ):
            NativeHTTPBackend(RequestConfig(), filter_config=FilterConfig())
        self.assertEqual(module.engines, [])

    def test_profile_configuration_is_explicit_and_calibration_stays_unfiltered(self):
        module = FakeNativeModule(results=[])
        profile = (404, "text/plain", b"Missing page.")
        with patch.dict("sys.modules", {"dirsearch_native": module}):
            backend = NativeHTTPBackend(RequestConfig(), filter_config=FilterConfig())
            backend.set_static_response_profile(profile)
            backend.scan_chunks("http://example.com/", ["missing"], lambda chunk: None)
            backend.scan_unfiltered("http://example.com/", "calibration")
            backend.set_static_response_profile(None)
            backend.scan_chunks("http://example.com/", ["next"], lambda chunk: None)
        calls = module.engines[0].chunk_calls
        self.assertEqual(calls[0][1]["filter_config"].static_response_profile, profile)
        self.assertIsNone(module.engines[0].calls[0][1]["filter_config"].static_response_profile)
        self.assertIsNone(calls[1][1]["filter_config"].static_response_profile)


class ProfileBackend:
    def __init__(self):
        self.profile = None
        self.used_profiles = []
        self.body = b"Missing page. " * 40

    def set_static_response_profile(self, profile):
        self.profile = profile

    def reset_cancel(self):
        pass

    def scan_chunks(self, url, paths, callback, query=""):
        self.used_profiles.append(self.profile)
        events = []
        for index, path in enumerate(paths):
            body = b"Unique diagnostic information." if path.endswith("distinct") else self.body
            if self.profile == (404, "text/plain", body):
                continue
            response = NativeResponse(url + path, 404, [("content-type", "text/plain")], body)
            events.append(NativeScanEvent(index, path, response, None))
        callback(NativeScanChunk(0, len(paths), tuple(events)))
        return len(paths)


class TestStaticProfileFuzzer(TestCase):
    def make_fuzzer(self, *, method="GET", skip_status=(), logging_enabled=False):
        backend = ProfileBackend()
        requester = DummyRequester(backend)
        requester.config = RequestConfig(method=method)
        matches, misses, filtered = [], [], []
        fuzzer = NativeFuzzer(
            requester, DummyDictionary([f"missing-{i}" for i in range(1009)] + ["distinct"]),
            filter_config=FilterConfig(), discovery_config=DiscoveryConfig(),
            execution_config=ExecutionConfig(concurrency=2, skip_on_status=skip_status),
            match_callbacks=(matches.append,), not_found_callbacks=(misses.append,),
            error_callbacks=(self.fail,), filtered_chunk_callbacks=(filtered.append,),
        )

        def setup_scanners():
            fuzzer.filter_state.scanners["default"]["random"] = Scanner(
                ProbeRequester([dict(status=404, headers=[("content-type", "text/plain")], body=backend.body)]),
                filter_config=FilterConfig(), delay=0, path=WILDCARD_TEST_POINT_MARKER,
            )
        fuzzer.setup_scanners = setup_scanners
        if logging_enabled:
            fuzzer.logger.addHandler(logging.NullHandler())
        return fuzzer, backend, matches, misses, filtered

    def test_fast_path_waits_for_learning_and_keeps_distinct_404(self):
        fuzzer, backend, matches, misses, filtered = self.make_fuzzer()
        fuzzer.start()
        self.assertIsNone(backend.used_profiles[0])
        self.assertIsNotNone(backend.used_profiles[1])
        self.assertEqual([response.path for response in matches], ["distinct"])
        self.assertEqual(len(misses), 1000)
        self.assertEqual(sum(filtered), 9)
        self.assertEqual(fuzzer._dictionary.index, 1010)

    def test_new_directory_clears_previous_profile_before_learning(self):
        fuzzer, backend, matches, _misses, _filtered = self.make_fuzzer()
        fuzzer.start()
        backend.body = b"Another directory's missing page. " * 30
        fuzzer._dictionary = DummyDictionary(["missing", "distinct"])
        fuzzer.set_base_path("other/")
        fuzzer.start()
        self.assertIsNone(backend.used_profiles[-1])
        self.assertEqual(matches[-1].path, "other/distinct")

    def test_head_keeps_normal_callbacks(self):
        fuzzer, backend, matches, misses, filtered = self.make_fuzzer(method="HEAD")
        fuzzer.start()
        self.assertEqual(backend.used_profiles, [None, None])
        self.assertEqual(len(matches), 1)
        self.assertEqual(len(misses), 1009)
        self.assertEqual(filtered, [])

    def test_stop_status_is_delivered_before_static_suppression(self):
        fuzzer, backend, matches, misses, filtered = self.make_fuzzer(skip_status=(404,))
        with self.assertRaisesRegex(SkipTargetInterrupt, "due to 404 status code"):
            fuzzer.start()
        self.assertEqual(backend.used_profiles, [None])
        self.assertEqual(matches, [])
        self.assertEqual(misses, [])
        self.assertEqual(filtered, [])

    def test_logging_keeps_static_profile_compaction(self):
        fuzzer, backend, matches, misses, filtered = self.make_fuzzer(logging_enabled=True)
        fuzzer.start()
        self.assertIsNone(backend.used_profiles[0])
        self.assertIsNotNone(backend.used_profiles[1])
        self.assertEqual([response.path for response in matches], ["distinct"])
        self.assertEqual(len(misses), 1000)
        self.assertEqual(sum(filtered), 9)


@skipUnless(importlib.util.find_spec("dirsearch_native"), "native extension is not installed")
class TestNativeStaticProfileContract(TestCase):
    def setUp(self):
        import dirsearch_native
        if version_error := get_native_extension_version_error(dirsearch_native):
            self.skipTest(version_error)

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                body = b"Missing page."
                status = 404
                content_type = "text/plain"
                if self.path == "/distinct":
                    body = b"A real diagnostic page with status 404."
                elif self.path == "/different-status":
                    status = 200
                elif self.path == "/different-type":
                    content_type = "application/json"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                if self.path == "/redirect":
                    self.send_header("Location", "/login")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        self.backend = NativeHTTPBackend(RequestConfig(concurrency=2, timeout=2), filter_config=FilterConfig())
        self.backend.set_static_response_profile((404, "text/plain", b"Missing page."))

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())

    def test_only_exact_missing_responses_are_omitted(self):
        paths = ["missing", "distinct", "different-status", "different-type", "redirect"]
        chunks = []
        self.assertEqual(self.backend.scan_chunks(self.url, paths, chunks.append), len(paths))
        self.assertEqual([event.path for chunk in chunks for event in chunk.events], paths[1:])
        self.assertEqual(chunks[-1].end_index, len(paths))

    def test_calibration_and_next_directory_do_not_reuse_the_profile(self):
        response, error = self.backend.scan_unfiltered(self.url, "missing")
        self.assertIsNone(error)
        self.assertEqual(response.body, b"Missing page.")
        self.backend.set_static_response_profile(None)
        chunks = []
        self.backend.scan_chunks(self.url, ["missing"], chunks.append)
        self.assertEqual(chunks[0].events[0].response.body, b"Missing page.")

    def test_truncated_body_matching_a_profile_prefix_is_kept(self):
        self.backend.set_static_response_profile((404, "text/plain", b"Missi"))
        chunks = []
        with patch("lib.connection.native.MAX_RESPONSE_SIZE", 5):
            self.backend.scan_chunks(self.url, ["missing"], chunks.append)
        response = chunks[0].events[0].response
        self.assertEqual(response.body, b"Missi")
        self.assertFalse(response.body_complete)
