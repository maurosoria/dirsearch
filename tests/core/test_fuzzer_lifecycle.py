import asyncio
import threading
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import RequestException, SkipTargetInterrupt
from lib.core.fuzzer import AsyncFuzzer, Fuzzer


class LifecycleDictionary:
    def __init__(self, paths):
        self.paths = list(paths)
        self.index = 0
        self.claimed = []

    def __next__(self):
        if self.index >= len(self.paths):
            raise StopIteration

        path = self.paths[self.index]
        self.index += 1
        return path

    def __len__(self):
        return len(self.paths)

    def claim_next(self):
        path = next(self)
        self.claimed.append(path)
        return path

    def release_claim(self, path):
        self.claimed.remove(path)


class CoordinatedSyncRequester:
    def __init__(self):
        self.paths = []
        self.blocked_request_started = threading.Event()
        self.release_blocked_request = threading.Event()

    def request(self, path):
        self.paths.append(path)

        if path == "fail":
            if not self.blocked_request_started.wait(timeout=2):
                raise AssertionError("sibling request did not start")
        elif path == "blocked":
            self.blocked_request_started.set()
            if not self.release_blocked_request.wait(timeout=2):
                raise AssertionError("blocked request was not released")

        raise RequestException(path)


class BlockingSyncRequester:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def request(self, path):
        self.started.set()
        if not self.release.wait(timeout=2):
            raise AssertionError("blocked request was not released")
        raise RequestException(path)


class CoordinatedAsyncRequester:
    def __init__(self):
        self.paths = []
        self.blocked_request_started = asyncio.Event()
        self.blocked_request_cancelled = asyncio.Event()

    async def request(self, path):
        self.paths.append(path)

        if path == "fail":
            await self.blocked_request_started.wait()
            raise RequestException(path)

        self.blocked_request_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.blocked_request_cancelled.set()
            raise


class TestThreadedFuzzerLifecycle(TestCase):
    def test_saved_state_retries_in_flight_path(self):
        dictionary = object.__new__(Dictionary)
        dictionary.__setstate__((["blocked", "later"], 0, [], 0))
        requester = BlockingSyncRequester()
        fuzzer = Fuzzer(
            requester,
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer.setup_scanners = lambda: None

        with patch.dict(options, {"thread_count": 1, "delay": 0}):
            fuzzer.start()
            try:
                self.assertTrue(requester.started.wait(timeout=2))
                saved_state = dictionary.__getstate__()
            finally:
                fuzzer.quit()
                requester.release.set()
                for worker in fuzzer._threads:
                    worker.join(timeout=2)

        self.assertFalse(any(worker.is_alive() for worker in fuzzer._threads))
        resumed = object.__new__(Dictionary)
        resumed.__setstate__(saved_state)
        self.assertEqual([next(resumed), next(resumed)], ["blocked", "later"])
        with self.assertRaises(StopIteration):
            next(resumed)

        completed = object.__new__(Dictionary)
        completed.__setstate__(dictionary.__getstate__())
        self.assertEqual(next(completed), "later")
        with self.assertRaises(StopIteration):
            next(completed)

    def test_terminal_callback_failure_stops_intake_and_drains_siblings(self):
        requester = CoordinatedSyncRequester()
        callback_failed = threading.Event()

        def stop_scan(error):
            if str(error) == "fail":
                callback_failed.set()
                raise SkipTargetInterrupt("stop target")

        fuzzer = Fuzzer(
            requester,
            LifecycleDictionary(["fail", "blocked", "after"]),
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(stop_scan,),
        )
        fuzzer.setup_scanners = lambda: None

        with patch.dict(options, {"thread_count": 2, "delay": 0}):
            fuzzer.start()
            try:
                self.assertTrue(callback_failed.wait(timeout=2))
                try:
                    finished = fuzzer.is_finished()
                except SkipTargetInterrupt:
                    self.fail("terminal failure surfaced before siblings drained")
                self.assertFalse(finished)
            finally:
                requester.release_blocked_request.set()
                for thread in fuzzer._threads:
                    thread.join(timeout=2)

        self.assertFalse(any(thread.is_alive() for thread in fuzzer._threads))
        self.assertEqual(requester.paths, ["fail", "blocked"])
        with self.assertRaisesRegex(SkipTargetInterrupt, "stop target"):
            fuzzer.is_finished()


class TestAsyncFuzzerLifecycle(IsolatedAsyncioTestCase):
    async def test_terminal_callback_failure_cancels_and_drains_siblings(self):
        requester = CoordinatedAsyncRequester()

        def stop_scan(error):
            if str(error) == "fail":
                raise SkipTargetInterrupt("stop target")

        fuzzer = AsyncFuzzer(
            requester,
            LifecycleDictionary(["fail", "blocked"]),
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(stop_scan,),
        )

        async def skip_scanners():
            return None

        fuzzer.setup_scanners = skip_scanners

        with patch.dict(options, {"thread_count": 2, "delay": 0}):
            with self.assertRaisesRegex(SkipTargetInterrupt, "stop target"):
                await asyncio.wait_for(fuzzer.start(), timeout=2)

        remaining_tasks = tuple(fuzzer._background_tasks)
        try:
            self.assertTrue(requester.blocked_request_cancelled.is_set())
            self.assertFalse(any(not task.done() for task in remaining_tasks))
        finally:
            fuzzer.quit()
            await asyncio.gather(*remaining_tasks, return_exceptions=True)
