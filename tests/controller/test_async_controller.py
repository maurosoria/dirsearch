import asyncio
import time
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.exceptions import QuitInterrupt, SkipTargetInterrupt


class BlockingAsyncFuzzer:
    def __init__(self):
        self.started = asyncio.Event()
        self.task = None

    async def start(self):
        self.task = asyncio.current_task()
        self.started.set()
        await asyncio.Event().wait()


class RecordingAsyncFuzzer:
    def __init__(self):
        self.started = False

    async def start(self):
        self.started = True


def create_controller(fuzzer):
    controller = object.__new__(Controller)
    controller.loop = asyncio.get_running_loop()
    controller.pause_future = controller.loop.create_future()
    controller.fuzzer = fuzzer
    controller._pause_requested = False
    controller._handling_pause = False
    return controller


class RecordingLoop:
    def __init__(self):
        self.closed = False

    def run_until_complete(self, awaitable):
        return asyncio.run(awaitable)

    def close(self):
        self.closed = True


class RecordingAsyncRequester:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class TestControllerCleanup(TestCase):
    def test_sync_requester_closes_after_run_failure(self):
        requester = Mock()

        def fail_run(controller):
            controller.requester = requester
            raise RuntimeError("scan failed")

        with (
            patch.dict(options, {"session_file": None}),
            patch.object(Controller, "setup"),
            patch.object(Controller, "run", new=fail_run),
            self.assertRaisesRegex(RuntimeError, "scan failed"),
        ):
            Controller()

        requester.close.assert_called_once_with()

    def test_async_requester_and_event_loop_close_after_run_failure(self):
        requester = RecordingAsyncRequester()
        loop = RecordingLoop()

        def fail_run(controller):
            controller.requester = requester
            controller.loop = loop
            raise RuntimeError("scan failed")

        with (
            patch.dict(options, {"session_file": None}),
            patch.object(Controller, "setup"),
            patch.object(Controller, "run", new=fail_run),
            self.assertRaisesRegex(RuntimeError, "scan failed"),
        ):
            Controller()

        self.assertTrue(requester.closed)
        self.assertTrue(loop.closed)


class TestAsyncController(IsolatedAsyncioTestCase):
    async def test_pause_request_is_serviced_by_async_orchestration_task(self):
        controller = create_controller(BlockingAsyncFuzzer())
        controller.start_time = time.time()
        pause_handled = asyncio.Event()

        def handle_pause():
            controller._pause_requested = False
            pause_handled.set()

        controller.handle_pause = Mock(side_effect=handle_pause)

        with patch.dict(options, {"max_time": 0, "target_max_time": 0}):
            run_task = controller.loop.create_task(
                controller.start_coroutines(time.time())
            )
            await controller.fuzzer.started.wait()
            controller._pause_requested = True
            await asyncio.wait_for(pause_handled.wait(), timeout=1)
            controller.pause_future.set_exception(QuitInterrupt("quit"))

            with self.assertRaisesRegex(QuitInterrupt, "quit"):
                await run_task

        controller.handle_pause.assert_called_once_with()
        self.assertTrue(controller.fuzzer.task.done())
        self.assertTrue(controller.fuzzer.task.cancelled())

    async def test_quit_drains_cancelled_fuzzer_task(self):
        controller = create_controller(BlockingAsyncFuzzer())
        controller.start_time = time.time()

        with patch.dict(options, {"max_time": 0, "target_max_time": 0}):
            run_task = controller.loop.create_task(
                controller.start_coroutines(time.time())
            )
            await controller.fuzzer.started.wait()
            controller.pause_future.set_exception(QuitInterrupt("quit"))

            with self.assertRaisesRegex(QuitInterrupt, "quit"):
                await run_task

        self.assertTrue(controller.fuzzer.task.done())
        self.assertTrue(controller.fuzzer.task.cancelled())

    async def test_expired_scan_deadline_stops_before_starting_fuzzer(self):
        fuzzer = RecordingAsyncFuzzer()
        controller = create_controller(fuzzer)
        controller.start_time = 90

        with (
            patch.dict(options, {"max_time": 5, "target_max_time": 0}),
            patch("lib.controller.controller.time.time", return_value=100),
        ):
            with self.assertRaisesRegex(
                QuitInterrupt, "Runtime exceeded the maximum set by the user"
            ):
                await controller.start_coroutines(start_time=100)

        self.assertFalse(fuzzer.started)

    async def test_expired_target_deadline_stops_before_starting_fuzzer(self):
        fuzzer = RecordingAsyncFuzzer()
        controller = create_controller(fuzzer)
        controller.start_time = 100

        with (
            patch.dict(options, {"max_time": 0, "target_max_time": 5}),
            patch("lib.controller.controller.time.time", return_value=100),
        ):
            with self.assertRaisesRegex(
                SkipTargetInterrupt,
                "Runtime for target exceeded the maximum set by the user",
            ):
                await controller.start_coroutines(start_time=90)

        self.assertFalse(fuzzer.started)

    async def test_expired_scan_deadline_wins_over_remaining_target_deadline(self):
        fuzzer = RecordingAsyncFuzzer()
        controller = create_controller(fuzzer)
        controller.start_time = 90

        with (
            patch.dict(options, {"max_time": 5, "target_max_time": 20}),
            patch("lib.controller.controller.time.time", return_value=100),
        ):
            with self.assertRaises(QuitInterrupt):
                await controller.start_coroutines(start_time=95)

        self.assertFalse(fuzzer.started)
