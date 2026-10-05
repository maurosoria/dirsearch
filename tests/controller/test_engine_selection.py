import asyncio
import io
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.execution_config import ExecutionConfig, ScanEngine
from lib.core.settings import THREADED_WORKER_SHUTDOWN_TIMEOUT


class TestEngineSelection(TestCase):
    def test_invalid_restored_engine_fails_before_requester_or_loop_creation(self):
        for backend, async_mode, message in (
            ("native", True, "--request-backend native cannot be combined with --async"),
            ("unknown", False, "--request-backend must be one of: python, native"),
        ):
            def restore(_controller, _path):
                options.update(request_backend=backend, async_mode=async_mode)

            with (
                self.subTest(backend=backend),
                patch.dict(options, {"session_file": "checkpoint.json"}),
                patch.object(Controller, "_import", new=restore),
                patch("lib.connection.requester.Requester") as threaded,
                patch("lib.connection.requester.AsyncRequester") as asynchronous,
                patch("lib.connection.native.NativeRequester") as native,
                patch("lib.controller.controller.asyncio.new_event_loop") as make_loop,
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
                self.assertRaises(SystemExit) as stopped,
            ):
                Controller()
            self.assertEqual(stopped.exception.code, 1)
            self.assertEqual(stderr.getvalue(), message + "\n")
            threaded.assert_not_called()
            asynchronous.assert_not_called()
            native.assert_not_called()
            make_loop.assert_not_called()

    def test_directory_dispatch_and_worker_drain_ignore_global_flags(self):
        for engine in ScanEngine:
            with self.subTest(engine=engine):
                controller = object.__new__(Controller)
                controller.interface = Mock()
                controller.execution_config = ExecutionConfig(engine=engine)
                controller.directories = ["first/", "second/"]
                controller.old_session = True
                controller.fuzzer = Mock()
                controller.dictionary = Mock()
                controller._native_worker = None
                controller.jobs_processed = 0
                controller.process = Mock()
                controller.start_native_fuzzer = Mock()
                controller.start_coroutines = AsyncMock()
                controller.loop = asyncio.new_event_loop() if engine is ScanEngine.ASYNC else None
                try:
                    with patch.dict(options, {}, clear=True):
                        controller.start()
                    self.assertEqual(controller.dictionary.reset.call_count, 2)
                    self.assertEqual(controller.jobs_processed, 2)
                    self.assertEqual(controller.directories, [])
                    self.assertEqual(
                        [call.args[0] for call in controller.fuzzer.set_base_path.call_args_list],
                        ["first/", "second/"],
                    )
                    self.assertEqual(controller.process.call_count, 2 if engine is ScanEngine.THREADED else 0)
                    self.assertEqual(controller.fuzzer.start.call_count, 2 if engine is ScanEngine.THREADED else 0)
                    self.assertEqual(controller.fuzzer.stop.call_count, 2 if engine is ScanEngine.THREADED else 0)
                    if engine is ScanEngine.THREADED:
                        controller.fuzzer.stop.assert_called_with(THREADED_WORKER_SHUTDOWN_TIMEOUT)
                    self.assertEqual(controller.start_native_fuzzer.call_count, 2 if engine is ScanEngine.NATIVE else 0)
                    self.assertEqual(controller.start_coroutines.await_count, 2 if engine is ScanEngine.ASYNC else 0)
                finally:
                    if controller.loop is not None:
                        controller.loop.close()
