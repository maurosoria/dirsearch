import threading
import time
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.exceptions import QuitInterrupt, SkipTargetInterrupt


class BlockingNativeFuzzer:
    def __init__(self):
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.base_paths = []
        self.quit_calls = 0
        self.prepare_calls = 0

    def prepare_start(self):
        self.prepare_calls += 1

    def set_base_path(self, path):
        self.base_paths.append(path)

    def start(self):
        self.started.set()
        if not self.stopped.wait(timeout=2):
            raise TimeoutError("native test fuzzer was not stopped")

    def is_finished(self):
        return self.stopped.is_set()

    def quit(self):
        self.quit_calls += 1
        self.stopped.set()


class SuppressedTimer:
    def __init__(self, _timeout, _callback):
        self.daemon = False

    def start(self):
        pass

    def cancel(self):
        pass

    def join(self):
        pass


class UncooperativeNativeFuzzer(BlockingNativeFuzzer):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def start(self):
        self.started.set()
        self.release.wait(timeout=2)

    def quit(self):
        self.quit_calls += 1


def create_controller(fuzzer):
    controller = object.__new__(Controller)
    controller.start_time = time.time()
    controller.directories = [""]
    controller.old_session = True
    controller.fuzzer = fuzzer
    controller.dictionary = Mock()
    controller.jobs_processed = 0
    controller._native_worker = None
    return controller


class TestNativeControllerDeadlines(TestCase):
    def assert_deadline_stops_native_fuzzer(
        self, *, max_time, target_max_time, error_type, message
    ):
        fuzzer = BlockingNativeFuzzer()
        controller = create_controller(fuzzer)
        errors = []

        def run_controller():
            try:
                controller.start()
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=run_controller)
        with patch.dict(
            options,
            {
                "async_mode": False,
                "request_backend": "native",
                "max_time": max_time,
                "target_max_time": target_max_time,
            },
        ):
            worker.start()
            try:
                self.assertTrue(fuzzer.started.wait(timeout=1))
                worker.join(timeout=0.5)
                completed_at_deadline = not worker.is_alive()
            finally:
                fuzzer.quit()
                worker.join(timeout=1)

        self.assertTrue(completed_at_deadline, "native scan ignored its deadline")
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], error_type)
        self.assertEqual(str(errors[0]), message)
        self.assertGreaterEqual(fuzzer.quit_calls, 1)
        controller.dictionary.reset.assert_called_once_with()

    def test_completed_native_scan_is_not_cancelled(self):
        fuzzer = BlockingNativeFuzzer()
        fuzzer.stopped.set()
        controller = create_controller(fuzzer)

        with patch.dict(
            options,
            {
                "async_mode": False,
                "request_backend": "native",
                "max_time": 1,
                "target_max_time": 0,
            },
        ):
            controller.start()

        self.assertEqual(fuzzer.quit_calls, 0)
        self.assertEqual(fuzzer.prepare_calls, 1)
        controller.dictionary.reset.assert_called_once_with()

    def test_expired_max_time_stops_before_starting_native_fuzzer(self):
        fuzzer = BlockingNativeFuzzer()
        controller = create_controller(fuzzer)
        controller.start_time -= 1

        with (
            patch.dict(
                options,
                {
                    "async_mode": False,
                    "request_backend": "native",
                    "max_time": 0.05,
                    "target_max_time": 0,
                },
            ),
            self.assertRaisesRegex(
                QuitInterrupt, "Runtime exceeded the maximum set by the user"
            ),
        ):
            controller.start()

        self.assertFalse(fuzzer.started.is_set())
        self.assertEqual(fuzzer.quit_calls, 0)
        controller.dictionary.reset.assert_called_once_with()

    def test_late_native_completion_cannot_beat_delayed_timer_callback(self):
        fuzzer = BlockingNativeFuzzer()
        fuzzer.stopped.set()
        controller = create_controller(fuzzer)
        controller.start_time = 0

        with (
            patch.dict(options, {"max_time": 1, "target_max_time": 0}),
            patch("lib.controller.controller.threading.Timer", SuppressedTimer),
            patch("lib.controller.controller.time.time", side_effect=[0, 2]),
            self.assertRaisesRegex(
                QuitInterrupt, "Runtime exceeded the maximum set by the user"
            ),
        ):
            controller.start_native_fuzzer(start_time=0)

        self.assertEqual(fuzzer.quit_calls, 0)

    def test_max_time_interrupts_active_native_scan(self):
        self.assert_deadline_stops_native_fuzzer(
            max_time=0.05,
            target_max_time=0,
            error_type=QuitInterrupt,
            message="Runtime exceeded the maximum set by the user",
        )

    def test_target_max_time_interrupts_active_native_scan(self):
        self.assert_deadline_stops_native_fuzzer(
            max_time=0,
            target_max_time=0.05,
            error_type=SkipTargetInterrupt,
            message="Runtime for target exceeded the maximum set by the user",
        )

    def test_native_scan_does_not_occupy_controller_thread(self):
        fuzzer = BlockingNativeFuzzer()
        controller = create_controller(fuzzer)
        controller_thread_ids = []
        fuzzer_thread_ids = []
        errors = []
        original_start = fuzzer.start

        def record_fuzzer_thread():
            fuzzer_thread_ids.append(threading.get_ident())
            original_start()

        def run_controller():
            controller_thread_ids.append(threading.get_ident())
            try:
                controller.start_native_fuzzer(start_time=time.time())
            except BaseException as error:
                errors.append(error)

        fuzzer.start = record_fuzzer_thread
        worker = threading.Thread(target=run_controller)
        with patch.dict(options, {"max_time": 0, "target_max_time": 0}):
            worker.start()
            try:
                self.assertTrue(fuzzer.started.wait(timeout=1))
                self.assertNotEqual(fuzzer_thread_ids, controller_thread_ids)
            finally:
                fuzzer.quit()
                worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    def test_uncooperative_deadline_preserves_live_dictionary_state(self):
        fuzzer = UncooperativeNativeFuzzer()
        controller = create_controller(fuzzer)

        try:
            with (
                patch.dict(
                    options,
                    {
                        "async_mode": False,
                        "request_backend": "native",
                        "max_time": 0.1,
                        "target_max_time": 0,
                    },
                ),
                patch(
                    "lib.controller.controller.NATIVE_WORKER_SHUTDOWN_TIMEOUT",
                    0.05,
                ),
                self.assertRaisesRegex(
                    QuitInterrupt, "Native scan did not stop safely"
                ),
            ):
                controller.start()
        finally:
            fuzzer.release.set()
            native_worker = controller._native_worker
            if native_worker is not None:
                native_worker.join(timeout=1)

        controller.dictionary.reset.assert_not_called()
        self.assertEqual(controller.directories, [""])
