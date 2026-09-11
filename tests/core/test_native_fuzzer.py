import threading
import time
from unittest import TestCase
from unittest.mock import patch
from lib.connection.response import NativeResponse
from lib.core.data import blacklists, options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import RequestException
from lib.core.fuzzer import NativeFuzzer


class DummyDictionary:
    def __init__(self, paths):
        self.paths = paths
        self.index = 0

    def __next__(self):
        if self.index >= len(self.paths):
            raise StopIteration
        self.index += 1
        return self.paths[self.index - 1]

    def __len__(self):
        return len(self.paths)

    def claim_next(self):
        return next(self)

    def release_claim(self, path):
        return None

    def requeue_claims(self):
        return None


class DummyRequester:
    _url = "https://example.com/"


class FakeNativeBackend:
    def __init__(self, items):
        self.items = items
        self.calls = []
        self.cancelled = False

    def scan(self, base_url, paths, query=""):
        self.calls.append((base_url, list(paths), query))
        yield from self.items

    def cancel(self):
        self.cancelled = True


class CoordinatedNativeBackend:
    def __init__(self):
        self.calls = []
        self.cancelled = threading.Event()
        self.waiting_for_cancel = threading.Event()

    def scan(self, _base_url, paths, query=""):
        paths = list(paths)
        self.calls.append(paths)

        if len(self.calls) == 1:
            yield paths[0], None, RequestException(paths[0])
            self.waiting_for_cancel.set()
            if not self.cancelled.wait(timeout=2):
                raise AssertionError("native scan was not cancelled while pausing")

            # A cancelled backend may still deliver a result that was already
            # ready. It must not cross the pause acknowledgement boundary.
            yield paths[1], None, RequestException(f"late-{paths[1]}")
            return

        for path in paths:
            yield path, None, RequestException(path)

    def cancel(self):
        self.cancelled.set()


class UncooperativeNativeBackend:
    def __init__(self):
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.release = threading.Event()

    def scan(self, _base_url, _paths, query=""):
        self.started.set()
        self.release.wait(timeout=2)
        if False:
            yield

    def cancel(self):
        self.cancelled.set()


class CancelAwareNativeBackend:
    def __init__(self):
        self.cancelled = threading.Event()

    def scan(self, _base_url, _paths, query=""):
        if not self.cancelled.wait(timeout=1):
            raise AssertionError("native scan was not cancelled")
        if False:
            yield

    def cancel(self):
        self.cancelled.set()


def make_dictionary(paths):
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__((list(paths), 0, [], 0))
    return dictionary


def restored_paths(state):
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__(state)
    paths = []
    while True:
        try:
            paths.append(next(dictionary))
        except StopIteration:
            return paths


def run_fuzzer(fuzzer, errors):
    try:
        fuzzer.start()
    except BaseException as error:
        errors.append(error)


class TestNativeFuzzer(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        self.original_blacklists = dict(blacklists)
        options.update(
            {
                "thread_count": 2,
                "exclude_status_codes": set(),
                "include_status_codes": set(),
                "exclude_sizes": set(),
                "minimum_response_size": 0,
                "maximum_response_size": 0,
                "exclude_texts": [],
                "exclude_regex": None,
                "exclude_redirect": None,
                "filter_threshold": 0,
                "prefixes": (),
                "suffixes": (),
                "extensions": (),
                "matcher_mode": "or",
                "filter_mode": "or",
                "match_status_codes": set(),
                "filter_status_codes": set(),
                "match_sizes": (),
                "filter_sizes": (),
                "match_words": (),
                "filter_words": (),
                "match_lines": (),
                "filter_lines": (),
                "match_regex": None,
                "filter_regex": None,
                "match_time": (),
                "filter_time": (),
                "auto_calibration": False,
            }
        )
        blacklists.clear()

    def tearDown(self):
        options.clear()
        options.update(self.original_options)
        blacklists.clear()
        blacklists.update(self.original_blacklists)

    def make_fuzzer(self, backend, dictionary, matches, misses, errors):
        fuzzer = NativeFuzzer(
            DummyRequester(),
            dictionary,
            match_callbacks=(matches.append,),
            not_found_callbacks=(misses.append,),
            error_callbacks=(errors.append,),
        )
        fuzzer._native_backend = backend
        fuzzer.setup_scanners = lambda: None
        return fuzzer

    def test_native_fuzzer_processes_native_responses(self):
        response = NativeResponse(
            "https://example.com/admin",
            200,
            [("content-type", "text/plain")],
            b"ok",
        )
        backend = FakeNativeBackend([("admin", response, None)])
        dictionary = DummyDictionary(["admin"])
        matches = []
        misses = []
        errors = []

        fuzzer = self.make_fuzzer(backend, dictionary, matches, misses, errors)
        fuzzer.start()

        self.assertTrue(fuzzer.is_finished())
        self.assertEqual(dictionary.index, 1)
        self.assertEqual(matches, [response])
        self.assertEqual(misses, [])
        self.assertEqual(errors, [])
        self.assertEqual(backend.calls, [("https://example.com/", ["admin"], "")])

    def test_native_fuzzer_routes_backend_errors(self):
        error = RequestException("boom")
        backend = FakeNativeBackend([("admin", None, error)])
        dictionary = DummyDictionary(["admin"])
        matches = []
        misses = []
        errors = []

        fuzzer = self.make_fuzzer(backend, dictionary, matches, misses, errors)
        fuzzer.start()

        self.assertEqual(matches, [])
        self.assertEqual(misses, [])
        self.assertEqual(errors, [error])

    def test_native_fuzzer_routes_filtered_results_to_not_found_callbacks(self):
        response = NativeResponse(
            "https://example.com/missing",
            404,
            [("content-type", "text/plain")],
            [],
            length=64,
            filtered=True,
            filter_reason="advanced_filter",
        )
        backend = FakeNativeBackend([("missing", response, None)])
        dictionary = DummyDictionary(["missing"])
        matches = []
        misses = []
        errors = []

        fuzzer = self.make_fuzzer(backend, dictionary, matches, misses, errors)
        fuzzer.start()

        self.assertEqual(matches, [])
        self.assertEqual(misses, [response])
        self.assertEqual(errors, [])
        self.assertEqual(response.length, 64)

    def test_saved_state_retries_unreturned_chunk_paths(self):
        dictionary = make_dictionary(["admin", "login"])
        backend = FakeNativeBackend([])
        fuzzer = self.make_fuzzer(backend, dictionary, [], [], [])

        fuzzer.start()
        saved_state = dictionary.__getstate__()

        resumed = object.__new__(Dictionary)
        resumed.__setstate__(saved_state)
        self.assertEqual([next(resumed), next(resumed)], ["admin", "login"])
        with self.assertRaises(StopIteration):
            next(resumed)

        resumed.reset()
        self.assertEqual([next(resumed), next(resumed)], ["admin", "login"])
        with self.assertRaises(StopIteration):
            next(resumed)

    def test_quit_cancels_active_native_engine(self):
        backend = FakeNativeBackend([])
        fuzzer = self.make_fuzzer(backend, DummyDictionary([]), [], [], [])

        fuzzer.quit()

        self.assertTrue(backend.cancelled)

    def test_pause_retries_only_results_not_delivered_before_acknowledgement(self):
        dictionary = make_dictionary(["admin", "login"])
        backend = CoordinatedNativeBackend()
        callback_errors = []
        first_result_processed = threading.Event()

        def record_error(error):
            callback_errors.append(str(error))
            first_result_processed.set()

        fuzzer = NativeFuzzer(
            DummyRequester(),
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(record_error,),
        )
        fuzzer._native_backend = backend
        fuzzer.setup_scanners = lambda: None
        worker_errors = []
        worker = threading.Thread(target=run_fuzzer, args=(fuzzer, worker_errors))
        worker.start()

        try:
            self.assertTrue(first_result_processed.wait(timeout=1))
            self.assertTrue(backend.waiting_for_cancel.wait(timeout=1))
            self.assertTrue(fuzzer.pause())
            self.assertTrue(backend.cancelled.is_set())

            saved_state = dictionary.__getstate__()
            self.assertEqual(restored_paths(saved_state), ["login"])
            self.assertEqual(callback_errors, ["admin"])

            fuzzer.play()
            worker.join(timeout=1)
        finally:
            fuzzer.quit()
            backend.cancelled.set()
            worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(worker_errors, [])
        self.assertEqual(backend.calls, [["admin", "login"], ["login"]])
        self.assertEqual(callback_errors, ["admin", "login"])
        self.assertEqual(restored_paths(dictionary.__getstate__()), [])

    def test_pause_reports_timeout_when_native_scan_does_not_acknowledge(self):
        dictionary = make_dictionary(["blocked"])
        backend = UncooperativeNativeBackend()
        fuzzer = self.make_fuzzer(backend, dictionary, [], [], [])
        worker_errors = []
        worker = threading.Thread(target=run_fuzzer, args=(fuzzer, worker_errors))
        worker.start()

        try:
            self.assertTrue(backend.started.wait(timeout=1))
            started_at = time.monotonic()
            with patch("lib.core.fuzzer.NATIVE_PAUSE_TIMEOUT", 0.05, create=True):
                paused = fuzzer.pause()
            elapsed = time.monotonic() - started_at

            self.assertFalse(paused)
            self.assertTrue(backend.cancelled.is_set())
            self.assertLess(elapsed, 0.5)
            self.assertTrue(worker.is_alive())
        finally:
            backend.release.set()
            fuzzer.quit()
            worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(worker_errors, [])

    def test_pause_during_startup_is_not_overwritten_by_fuzzer_initialization(self):
        dictionary = make_dictionary(["admin"])
        backend = CancelAwareNativeBackend()
        setup_started = threading.Event()
        release_setup = threading.Event()
        fuzzer = self.make_fuzzer(backend, dictionary, [], [], [])

        def setup_scanners():
            setup_started.set()
            if not release_setup.wait(timeout=1):
                raise AssertionError("native setup was not released")

        fuzzer.setup_scanners = setup_scanners
        worker_errors = []
        worker = threading.Thread(target=run_fuzzer, args=(fuzzer, worker_errors))
        pause_results = []
        pauser = threading.Thread(target=lambda: pause_results.append(fuzzer.pause()))
        worker.start()

        try:
            self.assertTrue(setup_started.wait(timeout=1))
            pauser.start()
            release_setup.set()
            pauser.join(timeout=1)

            self.assertEqual(pause_results, [True])
            self.assertTrue(worker.is_alive())
        finally:
            fuzzer.quit()
            pauser.join(timeout=1)
            worker.join(timeout=1)

        self.assertFalse(pauser.is_alive())
        self.assertFalse(worker.is_alive())
        self.assertEqual(worker_errors, [])
