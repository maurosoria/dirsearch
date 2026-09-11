import queue
import threading
import time
from types import SimpleNamespace
from unittest import TestCase

from lib.report.simple_report import SimpleReport


TEST_TIMEOUT = 2.0
INDEPENDENT_COMPLETION_TIMEOUT = 0.5


def join_threads(test_case, threads):
    deadline = time.monotonic() + TEST_TIMEOUT
    for thread in threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    test_case.assertFalse(
        any(thread.is_alive() for thread in threads),
        "report locking test leaked a worker thread",
    )


class MemorySimpleReport(SimpleReport):
    def __init__(self, entered=None, release=None):
        super().__init__()
        self._entered = entered
        self._release = release
        self._blocked = False
        self.contents = ""

    def append(self, _file, data):
        if self._entered is not None and not self._blocked:
            self._blocked = True
            self._entered.set()
            if not self._release.wait(timeout=TEST_TIMEOUT):
                raise TimeoutError("test did not release blocked report")
        self.contents += data


class TestReportLocking(TestCase):
    def test_independent_reports_do_not_share_operation_lock(self):
        first_entered = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        second_finished = threading.Event()
        errors = queue.Queue()
        first = MemorySimpleReport(first_entered, release_first)
        second = MemorySimpleReport()

        def save(report, url, started=None, finished=None):
            if started is not None:
                started.set()
            try:
                report.save("unused", SimpleNamespace(url=url))
            except Exception as error:
                errors.put(error)
            finally:
                if finished is not None:
                    finished.set()

        first_thread = threading.Thread(target=save, args=(first, "first"))
        second_thread = threading.Thread(
            target=save,
            args=(second, "second", second_started, second_finished),
        )
        first_thread.start()

        try:
            self.assertTrue(first_entered.wait(timeout=TEST_TIMEOUT))
            second_thread.start()
            self.assertTrue(second_started.wait(timeout=TEST_TIMEOUT))
            completed_independently = second_finished.wait(
                timeout=INDEPENDENT_COMPLETION_TIMEOUT
            )
        finally:
            release_first.set()
            join_threads(self, [first_thread, second_thread])

        self.assertTrue(
            completed_independently,
            "an unrelated report was blocked by the process-wide lock",
        )
        self.assertTrue(errors.empty())
        self.assertIn("second", second.contents)

    def test_same_report_keeps_operation_lock(self):
        first_entered = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        second_finished = threading.Event()
        errors = queue.Queue()
        report = MemorySimpleReport(first_entered, release_first)

        def save(url, started=None, finished=None):
            if started is not None:
                started.set()
            try:
                report.save("unused", SimpleNamespace(url=url))
            except Exception as error:
                errors.put(error)
            finally:
                if finished is not None:
                    finished.set()

        first_thread = threading.Thread(target=save, args=("first",))
        second_thread = threading.Thread(
            target=save,
            args=("second", second_started, second_finished),
        )
        first_thread.start()

        try:
            self.assertTrue(first_entered.wait(timeout=TEST_TIMEOUT))
            second_thread.start()
            self.assertTrue(second_started.wait(timeout=TEST_TIMEOUT))
            completed_while_first_was_blocked = second_finished.wait(
                timeout=INDEPENDENT_COMPLETION_TIMEOUT
            )
        finally:
            release_first.set()
            join_threads(self, [first_thread, second_thread])

        self.assertFalse(
            completed_while_first_was_blocked,
            "writes through the same report instance were not serialized",
        )
        self.assertTrue(errors.empty())
        self.assertEqual(report.contents.splitlines(), ["first", "second"])
