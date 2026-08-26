import threading
import time
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import RequestException
from lib.core.fuzzer import Fuzzer, NativeFuzzer


TEST_TIMEOUT = 5


def make_dictionary(paths):
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__((list(paths), 0, [], 0))
    return dictionary


def remaining_paths(state):
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__(state)
    paths = []
    while True:
        try:
            path = dictionary.claim_next()
        except StopIteration:
            return paths
        dictionary.release_claim(path)
        paths.append(path)


class BlockingNativeBackend:
    def __init__(self):
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def scan(self, _base_url, _paths, _query=""):
        self.started.set()
        if not self.cancelled.wait(timeout=TEST_TIMEOUT):
            raise TimeoutError("native test backend was not cancelled")
        return
        yield

    def cancel(self):
        self.cancelled.set()


class ResumableNativeBackend:
    def __init__(self):
        self.calls = []
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def scan(self, _base_url, paths, _query=""):
        paths = list(paths)
        self.calls.append(paths)
        if len(self.calls) == 1:
            self.started.set()
            if not self.cancelled.wait(timeout=TEST_TIMEOUT):
                raise TimeoutError("native test backend was not cancelled")
            return

        for path in paths:
            yield path, None, RequestException("expected test response")

    def cancel(self):
        self.cancelled.set()


class UncooperativeNativeBackend:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def scan(self, _base_url, _paths, _query=""):
        self.started.set()
        if not self.release.wait(timeout=TEST_TIMEOUT):
            raise TimeoutError("native test backend was not released")
        return
        yield

    def cancel(self):
        pass


class TestFuzzerLifecycle(TestCase):
    def test_threaded_snapshot_retries_active_request(self):
        dictionary = make_dictionary(["admin"])
        request_started = threading.Event()
        release_request = threading.Event()
        fuzzer = Fuzzer(
            Mock(),
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer.setup_scanners = lambda: None

        def scan(_path):
            request_started.set()
            if not release_request.wait(timeout=TEST_TIMEOUT):
                raise TimeoutError("threaded test request was not released")

        fuzzer.scan = scan

        with patch.dict(options, {"thread_count": 1, "delay": 0}):
            fuzzer.start()
            self.assertTrue(request_started.wait(timeout=TEST_TIMEOUT))
            saved_state = dictionary.__getstate__()
            release_request.set()
            self.assertTrue(fuzzer.wait(timeout=TEST_TIMEOUT))

        self.assertEqual(remaining_paths(saved_state), ["admin"])

    def test_native_start_is_non_blocking_and_pause_requeues_chunk(self):
        paths = ["admin", "login"]
        dictionary = make_dictionary(paths)
        backend = BlockingNativeBackend()
        fuzzer = NativeFuzzer(
            Mock(_url="https://example.com/"),
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer._native_backend = backend
        fuzzer.setup_scanners = lambda: None
        start_returned = threading.Event()

        def start_fuzzer():
            fuzzer.start()
            start_returned.set()

        starter = threading.Thread(target=start_fuzzer)
        with patch.dict(options, {"thread_count": 1}):
            starter.start()
            try:
                self.assertTrue(backend.started.wait(timeout=TEST_TIMEOUT))
                returned_without_scan = start_returned.wait(timeout=1)
                paused = fuzzer.pause()
                saved_state = dictionary.__getstate__()
            finally:
                fuzzer.quit()
                backend.cancel()
                starter.join(timeout=TEST_TIMEOUT)
                fuzzer.wait(timeout=TEST_TIMEOUT)

        self.assertTrue(returned_without_scan)
        self.assertTrue(paused)
        self.assertEqual(remaining_paths(saved_state), paths)
        self.assertFalse(starter.is_alive())
        self.assertTrue(fuzzer.is_finished())

    def test_threaded_pause_uses_one_overall_deadline(self):
        dictionary = make_dictionary([])
        fuzzer = Fuzzer(
            Mock(),
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer._threads = [Mock(is_alive=Mock(return_value=True)) for _ in range(4)]

        started = time.monotonic()
        with patch("lib.core.fuzzer.PAUSE_TIMEOUT_SECONDS", 0.05):
            paused = fuzzer.pause()
        elapsed = time.monotonic() - started

        self.assertFalse(paused)
        self.assertLess(elapsed, 0.2)

    def test_threaded_pause_continue_drains_workers(self):
        dictionary = make_dictionary(["first", "second"])
        first_started = threading.Event()
        release_first = threading.Event()
        pause_result = []
        fuzzer = Fuzzer(
            Mock(),
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer.setup_scanners = lambda: None

        def scan(path):
            if path == "first":
                first_started.set()
                release_first.wait(timeout=TEST_TIMEOUT)

        fuzzer.scan = scan

        with patch.dict(options, {"thread_count": 1, "delay": 0}):
            fuzzer.start()
            pauser = threading.Thread(target=lambda: pause_result.append(fuzzer.pause()))
            try:
                self.assertTrue(first_started.wait(timeout=TEST_TIMEOUT))
                pauser.start()
                deadline = time.monotonic() + TEST_TIMEOUT
                while fuzzer._play_event.is_set() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertFalse(fuzzer._play_event.is_set())
                release_first.set()
                pauser.join(timeout=TEST_TIMEOUT)
                self.assertEqual(pause_result, [True])
                self.assertTrue(fuzzer._threads[0].is_alive())

                fuzzer.play()
                self.assertTrue(fuzzer.wait(timeout=TEST_TIMEOUT))
            finally:
                release_first.set()
                fuzzer.quit()
                pauser.join(timeout=TEST_TIMEOUT)
                fuzzer.wait(timeout=TEST_TIMEOUT)

        self.assertTrue(fuzzer.is_finished())
        self.assertTrue(all(not thread.is_alive() for thread in fuzzer._threads))

    def test_threaded_pause_does_not_reuse_late_acknowledgement(self):
        dictionary = make_dictionary(["first", "second"])
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()
        release_second = threading.Event()
        fuzzer = Fuzzer(
            Mock(),
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer.setup_scanners = lambda: None

        def scan(path):
            if path == "first":
                first_started.set()
                release_first.wait(timeout=TEST_TIMEOUT)
            else:
                second_started.set()
                release_second.wait(timeout=TEST_TIMEOUT)

        fuzzer.scan = scan

        with (
            patch.dict(options, {"thread_count": 1, "delay": 0}),
            patch("lib.core.fuzzer.PAUSE_TIMEOUT_SECONDS", 0.05),
        ):
            fuzzer.start()
            try:
                self.assertTrue(first_started.wait(timeout=TEST_TIMEOUT))
                self.assertFalse(fuzzer.pause())
                release_first.set()
                with fuzzer._pause_condition:
                    acknowledged = fuzzer._pause_condition.wait_for(
                        lambda: fuzzer._paused_workers.get(
                            fuzzer._threads[0].ident
                        )
                        == 1,
                        timeout=TEST_TIMEOUT,
                    )
                self.assertTrue(acknowledged)

                fuzzer.play()
                self.assertTrue(second_started.wait(timeout=TEST_TIMEOUT))
                self.assertFalse(fuzzer.pause())
            finally:
                release_first.set()
                release_second.set()
                fuzzer.quit()
                self.assertTrue(fuzzer.wait(timeout=TEST_TIMEOUT))

        self.assertTrue(fuzzer.is_finished())
        self.assertTrue(all(not thread.is_alive() for thread in fuzzer._threads))

    def test_native_pause_continue_retries_exact_unreturned_chunk(self):
        paths = ["admin", "login"]
        dictionary = make_dictionary(paths)
        backend = ResumableNativeBackend()
        fuzzer = NativeFuzzer(
            Mock(_url="https://example.com/"),
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer._native_backend = backend
        fuzzer.setup_scanners = lambda: None

        with patch.dict(options, {"thread_count": 1}):
            fuzzer.start()
            try:
                self.assertTrue(backend.started.wait(timeout=TEST_TIMEOUT))
                self.assertTrue(fuzzer.pause())
                self.assertEqual(remaining_paths(dictionary.__getstate__()), paths)
                fuzzer.play()
                self.assertTrue(fuzzer.wait(timeout=TEST_TIMEOUT))
            finally:
                fuzzer.quit()
                backend.cancel()
                fuzzer.wait(timeout=TEST_TIMEOUT)

        self.assertEqual(backend.calls, [paths, paths])
        self.assertEqual(remaining_paths(dictionary.__getstate__()), [])
        self.assertTrue(all(not thread.is_alive() for thread in fuzzer._threads))

    def test_native_pause_timeout_preserves_claims_and_shutdown_drains_worker(self):
        paths = ["admin", "login"]
        dictionary = make_dictionary(paths)
        backend = UncooperativeNativeBackend()
        fuzzer = NativeFuzzer(
            Mock(_url="https://example.com/"),
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer._native_backend = backend
        fuzzer.setup_scanners = lambda: None

        with (
            patch.dict(options, {"thread_count": 1}),
            patch("lib.core.fuzzer.PAUSE_TIMEOUT_SECONDS", 0.05),
        ):
            fuzzer.start()
            try:
                self.assertTrue(backend.started.wait(timeout=TEST_TIMEOUT))
                started = time.monotonic()
                self.assertFalse(fuzzer.pause())
                self.assertLess(time.monotonic() - started, 0.2)
                self.assertEqual(remaining_paths(dictionary.__getstate__()), paths)
            finally:
                backend.release.set()
                fuzzer.quit()
                self.assertTrue(fuzzer.wait(timeout=TEST_TIMEOUT))

        self.assertTrue(all(not thread.is_alive() for thread in fuzzer._threads))
