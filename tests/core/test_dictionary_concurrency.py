import queue
import threading
import time
from unittest import TestCase

from lib.core.dictionary import Dictionary


TEST_TIMEOUT = 5


def make_dictionary(items=()) -> Dictionary:
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__((list(items), 0, [], 0))
    return dictionary


def drain(dictionary: Dictionary) -> list[str]:
    paths = []
    while True:
        try:
            path = dictionary.claim_next()
        except StopIteration:
            return paths
        dictionary.release_claim(path)
        paths.append(path)


def join_threads(test_case: TestCase, threads: list[threading.Thread]) -> None:
    deadline = time.monotonic() + TEST_TIMEOUT
    for thread in threads:
        thread.join(timeout=max(0, deadline - time.monotonic()))
    test_case.assertTrue(
        all(not thread.is_alive() for thread in threads),
        "dictionary concurrency test leaked a worker thread",
    )


class BlockingItems(list):
    def __init__(
        self,
        items: list[str],
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        super().__init__(items)
        self._entered = entered
        self._release = release

    def __len__(self) -> int:
        self._entered.set()
        if not self._release.wait(timeout=TEST_TIMEOUT):
            raise TimeoutError("test did not release blocked dictionary")
        return super().__len__()


class TestDictionaryConcurrency(TestCase):
    def test_independent_dictionaries_do_not_share_operation_lock(self):
        first_entered = threading.Event()
        release_first = threading.Event()
        second_finished = threading.Event()
        results = queue.Queue()
        first = make_dictionary()
        first._items = BlockingItems(
            ["first"],
            first_entered,
            release_first,
        )
        second = make_dictionary(["second"])

        def claim(dictionary: Dictionary, finished=None) -> None:
            try:
                path = dictionary.claim_next()
                dictionary.release_claim(path)
                results.put((path, None))
            except Exception as error:
                results.put((None, error))
            finally:
                if finished is not None:
                    finished.set()

        first_thread = threading.Thread(target=claim, args=(first,))
        second_thread = threading.Thread(
            target=claim,
            args=(second, second_finished),
        )
        started_threads = [first_thread]
        first_thread.start()

        try:
            self.assertTrue(first_entered.wait(timeout=TEST_TIMEOUT))
            second_thread.start()
            started_threads.append(second_thread)
            completed_independently = second_finished.wait(timeout=1)
        finally:
            release_first.set()
            join_threads(self, started_threads)

        completed = [results.get_nowait() for _ in range(2)]
        self.assertTrue(completed_independently)
        self.assertTrue(all(error is None for _, error in completed))
        self.assertEqual({path for path, _ in completed}, {"first", "second"})

    def test_concurrent_duplicate_extras_are_scheduled_once(self):
        worker_count = 16
        candidates = [f"dynamic/{index}" for index in range(64)]
        dictionary = make_dictionary()
        start = threading.Barrier(worker_count + 1)
        errors = queue.Queue()

        def add_candidates(offset: int) -> None:
            try:
                start.wait(timeout=TEST_TIMEOUT)
                for index in range(len(candidates)):
                    dictionary.add_extra(
                        candidates[(index + offset) % len(candidates)]
                    )
            except Exception as error:
                errors.put(error)

        threads = [
            threading.Thread(target=add_candidates, args=(worker,))
            for worker in range(worker_count)
        ]
        for thread in threads:
            thread.start()
        try:
            start.wait(timeout=TEST_TIMEOUT)
        except BaseException:
            start.abort()
            raise
        finally:
            join_threads(self, threads)

        self.assertTrue(errors.empty())
        scheduled = drain(dictionary)
        self.assertEqual(len(scheduled), len(candidates))
        self.assertEqual(set(scheduled), set(candidates))

    def test_concurrent_producer_and_consumer_preserve_every_path(self):
        rounds = 64
        initial_paths = [f"initial/{index}" for index in range(rounds)]
        extra_paths = [f"extra/{index}" for index in range(rounds)]
        dictionary = make_dictionary(initial_paths)
        round_barrier = threading.Barrier(2)
        processed = queue.Queue()
        errors = queue.Queue()

        def produce() -> None:
            try:
                for path in extra_paths:
                    round_barrier.wait(timeout=TEST_TIMEOUT)
                    dictionary.add_extra(path)
                    round_barrier.wait(timeout=TEST_TIMEOUT)
            except Exception as error:
                errors.put(error)

        def consume() -> None:
            try:
                for _ in range(rounds):
                    round_barrier.wait(timeout=TEST_TIMEOUT)
                    path = dictionary.claim_next()
                    dictionary.release_claim(path)
                    processed.put(path)
                    round_barrier.wait(timeout=TEST_TIMEOUT)
            except Exception as error:
                errors.put(error)

        threads = [
            threading.Thread(target=produce),
            threading.Thread(target=consume),
        ]
        for thread in threads:
            thread.start()
        join_threads(self, threads)

        self.assertTrue(errors.empty())
        consumed = [processed.get_nowait() for _ in range(rounds)]
        all_paths = consumed + drain(dictionary)
        expected = initial_paths + extra_paths
        self.assertEqual(len(all_paths), len(expected))
        self.assertEqual(set(all_paths), set(expected))

    def test_snapshot_retries_all_active_claims_once(self):
        worker_count = 8
        paths = [f"path/{index}" for index in range(32)]
        dictionary = make_dictionary(paths)
        all_claimed = threading.Barrier(worker_count + 1)
        release_claims = threading.Event()
        errors = queue.Queue()

        def hold_claim() -> None:
            path = None
            try:
                path = dictionary.claim_next()
                all_claimed.wait(timeout=TEST_TIMEOUT)
                if not release_claims.wait(timeout=TEST_TIMEOUT):
                    raise TimeoutError("test did not release dictionary claim")
                dictionary.release_claim(path)
            except Exception as error:
                errors.put(error)

        threads = [
            threading.Thread(target=hold_claim)
            for _ in range(worker_count)
        ]
        for thread in threads:
            thread.start()

        try:
            all_claimed.wait(timeout=TEST_TIMEOUT)
            saved_state = dictionary.__getstate__()
        except BaseException:
            all_claimed.abort()
            raise
        finally:
            release_claims.set()
            join_threads(self, threads)

        self.assertTrue(errors.empty())
        resumed = object.__new__(Dictionary)
        resumed.__setstate__(saved_state)
        remaining = drain(resumed)
        self.assertEqual(len(remaining), len(paths))
        self.assertEqual(set(remaining), set(paths))
