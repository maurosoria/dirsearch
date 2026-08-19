import asyncio
import time
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.exceptions import QuitInterrupt


class BlockingAsyncFuzzer:
    def __init__(self):
        self.started = asyncio.Event()
        self.task = None

    async def start(self):
        self.task = asyncio.current_task()
        self.started.set()
        await asyncio.Event().wait()


class TestAsyncController(IsolatedAsyncioTestCase):
    async def test_quit_drains_cancelled_fuzzer_task(self):
        controller = object.__new__(Controller)
        controller.loop = asyncio.get_running_loop()
        controller.pause_future = controller.loop.create_future()
        controller.start_time = time.time()
        controller.fuzzer = BlockingAsyncFuzzer()

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
