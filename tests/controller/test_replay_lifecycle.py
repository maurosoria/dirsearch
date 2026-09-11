import asyncio
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from lib.connection.response import NativeResponse
from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.exceptions import RequestException
from lib.core.fuzzer import AsyncFuzzer


def matched_response() -> NativeResponse:
    return NativeResponse(
        "https://example.test/admin",
        200,
        [("Content-Type", "text/plain")],
        b"found",
    )


class ReplayOptionsMixin:
    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "skip_on_status": set(),
                "full_url": False,
                "recursion_status_codes": set(),
                "recursive": False,
                "deep_recursive": False,
                "force_recursive": False,
                "replay_proxy": "http://replay.test:8080",
                "crawl": False,
                "find_backup": False,
            }
        )

    def tearDown(self):
        options.clear()
        options.update(self.original_options)


class RecordingAsyncRequester:
    def __init__(self):
        self.completed = False
        self.calls = []

    async def replay_request(self, path: str, proxy: str):
        self.calls.append((path, proxy))
        await asyncio.sleep(0)
        self.completed = True


class BlockingAsyncRequester:
    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.task = None

    async def replay_request(self, path: str, proxy: str):
        del path, proxy
        self.task = asyncio.current_task()
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class FailingAsyncRequester:
    async def replay_request(self, path: str, proxy: str):
        del path, proxy
        await asyncio.sleep(0)
        raise RequestException("replay failed")


class TestAsyncReplayLifecycle(ReplayOptionsMixin, IsolatedAsyncioTestCase):
    async def test_match_callback_waits_for_replay_to_finish(self):
        options["async_mode"] = True
        requester = RecordingAsyncRequester()
        controller = object.__new__(Controller)
        controller.loop = asyncio.get_running_loop()
        controller.requester = requester

        with patch("lib.controller.controller.interface"):
            await AsyncFuzzer.run_callbacks(
                (controller.match_callback,),
                matched_response(),
            )

        completed_when_callback_returned = requester.completed
        await asyncio.sleep(0)

        self.assertTrue(completed_when_callback_returned)
        self.assertEqual(
            requester.calls,
            [("admin", "http://replay.test:8080")],
        )

    async def test_cancelling_callback_cancels_in_progress_replay(self):
        options["async_mode"] = True
        requester = BlockingAsyncRequester()
        controller = object.__new__(Controller)
        controller.loop = asyncio.get_running_loop()
        controller.requester = requester

        with patch("lib.controller.controller.interface"):
            callback_task = asyncio.create_task(
                AsyncFuzzer.run_callbacks(
                    (controller.match_callback,),
                    matched_response(),
                )
            )
            await asyncio.wait_for(requester.started.wait(), timeout=1)
            callback_task.cancel()
            await asyncio.gather(callback_task, return_exceptions=True)

        cancelled_with_callback = requester.cancelled.is_set()
        if requester.task is not None and not requester.task.done():
            requester.task.cancel()
            await asyncio.gather(requester.task, return_exceptions=True)

        self.assertTrue(cancelled_with_callback)

    async def test_replay_failure_is_observed_by_callback_runner(self):
        options["async_mode"] = True
        controller = object.__new__(Controller)
        controller.loop = asyncio.get_running_loop()
        controller.requester = FailingAsyncRequester()

        with (
            patch("lib.controller.controller.interface"),
            self.assertRaisesRegex(RequestException, "replay failed"),
        ):
            await AsyncFuzzer.run_callbacks(
                (controller.match_callback,),
                matched_response(),
            )


class TestSyncReplayLifecycle(ReplayOptionsMixin, TestCase):
    def test_match_callback_replays_inline(self):
        options["async_mode"] = False
        requester = Mock()
        controller = object.__new__(Controller)
        controller.requester = requester

        with patch("lib.controller.controller.interface"):
            result = controller.match_callback(matched_response())

        self.assertIsNone(result)
        requester.request.assert_called_once_with(
            "admin",
            proxy="http://replay.test:8080",
        )
