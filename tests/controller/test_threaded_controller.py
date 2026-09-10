import threading
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import QuitInterrupt, RequestException
from lib.core.fuzzer import Fuzzer


def create_dictionary():
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__((["one", "two"], 0, [], 0))
    return dictionary


def create_controller(fuzzer, dictionary):
    controller = object.__new__(Controller)
    controller.start_time = 90
    controller.directories = [""]
    controller.old_session = True
    controller.dictionary = dictionary
    controller.fuzzer = fuzzer
    controller.jobs_processed = 0
    return controller


class TestThreadedControllerDeadlines(TestCase):
    def test_deadline_drains_workers_before_resetting_dictionary(self):
        entered = threading.Event()
        dictionary = create_dictionary()
        requester = Mock()

        def request(_path):
            entered.set()
            if not fuzzer._quit_event.wait(timeout=2):
                raise AssertionError("test fuzzer was not asked to stop")
            raise RequestException("cancelled request")

        requester.request.side_effect = request
        fuzzer = Fuzzer(
            requester,
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer.setup_scanners = lambda: None
        controller = create_controller(fuzzer, dictionary)
        original_start = fuzzer.start

        def coordinated_start():
            original_start()
            if not entered.wait(timeout=2):
                raise AssertionError("test worker did not start")

        fuzzer.start = coordinated_start
        reset_observations = []
        original_reset = dictionary.reset

        def record_reset():
            reset_observations.append(
                any(worker.is_alive() for worker in fuzzer._threads)
            )
            original_reset()

        dictionary.reset = record_reset

        with (
            patch.dict(
                options,
                {
                    "async_mode": False,
                    "request_backend": "python",
                    "thread_count": 1,
                    "delay": 0,
                    "max_time": 5,
                    "target_max_time": 0,
                },
            ),
            patch("lib.controller.controller.time.time", return_value=100),
        ):
            try:
                with self.assertRaisesRegex(
                    QuitInterrupt,
                    "Runtime exceeded the maximum set by the user",
                ):
                    controller.start()
            finally:
                fuzzer.quit()
                for worker in fuzzer._threads:
                    worker.join(timeout=2)

        self.assertFalse(any(worker.is_alive() for worker in fuzzer._threads))
        self.assertEqual(reset_observations, [False])

    def test_uncooperative_worker_preserves_live_dictionary_state(self):
        entered = threading.Event()
        release = threading.Event()
        dictionary = create_dictionary()
        dictionary.reset = Mock(wraps=dictionary.reset)
        requester = Mock()

        def request(_path):
            entered.set()
            if not release.wait(timeout=2):
                raise AssertionError("test worker was not released")
            raise RequestException("released request")

        requester.request.side_effect = request
        fuzzer = Fuzzer(
            requester,
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer.setup_scanners = lambda: None
        controller = create_controller(fuzzer, dictionary)
        original_start = fuzzer.start

        def coordinated_start():
            original_start()
            if not entered.wait(timeout=2):
                raise AssertionError("test worker did not start")

        fuzzer.start = coordinated_start

        try:
            with (
                patch.dict(
                    options,
                    {
                        "async_mode": False,
                        "request_backend": "python",
                        "thread_count": 1,
                        "delay": 0,
                        "max_time": 5,
                        "target_max_time": 0,
                    },
                ),
                patch("lib.controller.controller.time.time", return_value=100),
                patch(
                    "lib.controller.controller.THREADED_WORKER_SHUTDOWN_TIMEOUT",
                    0.05,
                ),
                self.assertRaisesRegex(
                    QuitInterrupt,
                    "Threaded scan did not stop safely",
                ),
            ):
                controller.start()
        finally:
            release.set()
            fuzzer.quit()
            for worker in fuzzer._threads:
                worker.join(timeout=2)

        self.assertFalse(any(worker.is_alive() for worker in fuzzer._threads))
        controller.dictionary.reset.assert_not_called()
        self.assertEqual(controller.directories, [""])
