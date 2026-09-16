import queue
import threading
import time
from unittest import TestCase

from lib.core.dictionary import Dictionary


TEST_TIMEOUT = 2.0
CONTAINS_TIMEOUT = 0.5


def make_dictionary(items=()) -> Dictionary:
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__((list(items), 0, [], 0))
    return dictionary


def join_threads(test_case: TestCase, threads: list[threading.Thread]) -> None:
    deadline = time.monotonic() + TEST_TIMEOUT
    for thread in threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    test_case.assertFalse(
        any(thread.is_alive() for thread in threads),
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


class CoordinatedExtras(list):
    def __init__(self, workers: int) -> None:
        super().__init__()
        self._contains_barrier = threading.Barrier(workers)

    def __contains__(self, item: object) -> bool:
        result = super().__contains__(item)
        try:
            self._contains_barrier.wait(timeout=CONTAINS_TIMEOUT)
        except threading.BrokenBarrierError:
            pass
        return result


class BlockingSnapshotExtras(list):
    def __init__(
        self,
        items: list[str],
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        super().__init__(items)
        self._entered = entered
        self._release = release
        self._blocked = False

    def __getitem__(self, item):
        result = super().__getitem__(item)
        if isinstance(item, slice) and not self._blocked:
            self._blocked = True
            self._entered.set()
            if not self._release.wait(timeout=TEST_TIMEOUT):
                raise TimeoutError("test did not release dictionary snapshot")
        return result


def remaining_paths(state: tuple[list[str], int, list[str], int]) -> list[str]:
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__(state)
    paths = []
    while True:
        try:
            paths.append(next(dictionary))
        except StopIteration:
            return paths


class TestDictionaryConcurrency(TestCase):
    def test_release_claims_removes_a_completed_batch_atomically(self):
        dictionary = make_dictionary(["zero", "one", "two"])
        self.assertEqual(
            [dictionary.claim_next() for _ in range(3)],
            ["zero", "one", "two"],
        )

        dictionary.release_claims(["zero", "one", "two"])

        self.assertEqual(remaining_paths(dictionary.__getstate__()), [])

    def test_release_claims_leaves_state_unchanged_when_a_path_is_missing(self):
        dictionary = make_dictionary(["zero", "one"])
        dictionary.claim_next()
        state = dictionary.__getstate__()

        with self.assertRaises(ValueError):
            dictionary.release_claims(["missing"])

        self.assertEqual(dictionary.__getstate__(), state)

    def test_independent_dictionaries_do_not_share_operation_lock(self):
        first_entered = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        second_finished = threading.Event()
        errors = queue.Queue()
        first = make_dictionary()
        first._items = BlockingItems(["first"], first_entered, release_first)
        second = make_dictionary(["second"])

        def claim(dictionary: Dictionary, started=None, finished=None) -> None:
            if started is not None:
                started.set()
            try:
                path = dictionary.claim_next()
                dictionary.release_claim(path)
            except Exception as error:
                errors.put(error)
            finally:
                if finished is not None:
                    finished.set()

        first_thread = threading.Thread(target=claim, args=(first,))
        second_thread = threading.Thread(
            target=claim,
            args=(second, second_started, second_finished),
        )
        first_thread.start()

        try:
            self.assertTrue(first_entered.wait(timeout=TEST_TIMEOUT))
            second_thread.start()
            self.assertTrue(second_started.wait(timeout=TEST_TIMEOUT))
            completed_independently = second_finished.wait(timeout=CONTAINS_TIMEOUT)
        finally:
            release_first.set()
            join_threads(self, [first_thread, second_thread])

        self.assertTrue(
            completed_independently,
            "an unrelated dictionary was blocked by the process-wide lock",
        )
        self.assertTrue(errors.empty())

    def test_concurrent_duplicate_extras_are_enqueued_once(self):
        worker_count = 8
        dictionary = make_dictionary()
        dictionary._extra = CoordinatedExtras(worker_count)
        start = threading.Barrier(worker_count + 1)
        errors = queue.Queue()

        def add_candidate() -> None:
            try:
                start.wait(timeout=TEST_TIMEOUT)
                dictionary.add_extra("dynamic/admin.bak")
            except Exception as error:
                errors.put(error)

        threads = [threading.Thread(target=add_candidate) for _ in range(worker_count)]
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
        self.assertEqual(dictionary._extra, ["dynamic/admin.bak"])

    def test_session_snapshot_cannot_interleave_with_reset(self):
        snapshot_entered = threading.Event()
        release_snapshot = threading.Event()
        reset_started = threading.Event()
        reset_finished = threading.Event()
        snapshot_state = []
        errors = queue.Queue()
        dictionary = make_dictionary(["base"])
        dictionary._extra = BlockingSnapshotExtras(
            ["dynamic"],
            snapshot_entered,
            release_snapshot,
        )
        self.assertEqual(next(dictionary), "dynamic")

        def snapshot() -> None:
            try:
                snapshot_state.append(dictionary.__getstate__())
            except Exception as error:
                errors.put(error)

        def reset() -> None:
            reset_started.set()
            try:
                dictionary.reset()
            except Exception as error:
                errors.put(error)
            finally:
                reset_finished.set()

        snapshot_thread = threading.Thread(target=snapshot)
        reset_thread = threading.Thread(target=reset)
        snapshot_thread.start()

        try:
            self.assertTrue(snapshot_entered.wait(timeout=TEST_TIMEOUT))
            reset_thread.start()
            self.assertTrue(reset_started.wait(timeout=TEST_TIMEOUT))
            reset_finished.wait(timeout=CONTAINS_TIMEOUT)
        finally:
            release_snapshot.set()
            join_threads(self, [snapshot_thread, reset_thread])

        self.assertTrue(errors.empty())
        self.assertEqual(len(snapshot_state), 1)
        self.assertEqual(remaining_paths(snapshot_state[0]), ["base"])
