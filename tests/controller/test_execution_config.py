import os
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.connection.response import NativeResponse
from lib.core.run_config import RunConfig
from lib.controller.controller import Controller
from lib.core.target_progress import TargetProgress
from lib.core.scan_run_state import ScanRunState
from lib.controller.session import SessionStore
from lib.controller.session_options import SessionOptions
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import QuitInterrupt, RequestException, SkipTargetInterrupt
from lib.core.execution_config import ExecutionConfig, ScanEngine
from lib.core.fuzzer import AsyncFuzzer, Fuzzer, NativeFuzzer
from lib.core.settings import MAX_CONSECUTIVE_REQUEST_ERRORS
from lib.core.wordlist_config import WordlistConfig


def make_controller(config):
    controller = object.__new__(Controller)
    controller.config = RunConfig(execution=config)
    controller.run_state = ScanRunState()
    controller.target_progress = TargetProgress()
    controller.interface = Mock()
    controller.start_time = 0
    controller.run_state.errors = 0
    controller.run_state.consecutive_errors = 0
    return controller


class TestControllerExecutionConfig(TestCase):
    def test_time_limits_keep_zero_disabled_and_earliest_deadline_semantics(self):
        cases = (
            (0, 0, None, None),
            (10, 0, 9, QuitInterrupt),
            (0, 4, 3, SkipTargetInterrupt),
            (10, 4, 3, SkipTargetInterrupt),
            (4, 10, 3, QuitInterrupt),
            (4, 4, 3, QuitInterrupt),
        )
        with patch.dict(options, {}, clear=True), patch("lib.controller.controller.time.time", return_value=1):
            for total, target, remaining, error_type in cases:
                with self.subTest(total=total, target=target):
                    controller = make_controller(ExecutionConfig(max_time=total, target_max_time=target))
                    timeout, error = controller.get_time_limit(start_time=0)
                    self.assertEqual(timeout, remaining)
                    if error_type is None:
                        self.assertIsNone(error)
                    else:
                        self.assertIsInstance(error, error_type)

    def test_expired_limit_precedence_does_not_depend_on_global_options(self):
        with patch.dict(options, {}, clear=True), patch("lib.controller.controller.time.time", return_value=4):
            for total, target, error in ((4, 4, QuitInterrupt), (10, 4, SkipTargetInterrupt)):
                with self.subTest(total=total, target=target):
                    controller = make_controller(ExecutionConfig(max_time=total, target_max_time=target))
                    with self.assertRaises(error):
                        controller.get_time_limit(start_time=0)

    def test_threaded_polling_keeps_existing_strict_deadline_boundary(self):
        cases = (
            (4, 0, 4, None), (4, 0, 5, QuitInterrupt),
            (0, 4, 4, None), (0, 4, 5, SkipTargetInterrupt),
            (4, 4, 5, QuitInterrupt),
        )
        for total, target, now, error in cases:
            with self.subTest(total=total, target=target, now=now):
                controller = make_controller(ExecutionConfig(max_time=total, target_max_time=target))
                controller.fuzzer = Mock()
                controller.fuzzer.is_finished.side_effect = [False, True]
                with (
                    patch.dict(options, {}, clear=True),
                    patch("lib.controller.controller.time.time", return_value=now),
                    patch("lib.controller.controller.time.sleep") as sleep,
                ):
                    if error is None:
                        controller.process(start_time=0)
                        sleep.assert_called_once_with(0.5)
                    else:
                        with self.assertRaises(error):
                            controller.process(start_time=0)
                        sleep.assert_not_called()

    def test_skip_and_error_policies_are_instance_owned(self):
        statuses = {429}
        stopped = make_controller(ExecutionConfig(skip_on_status=statuses, exit_on_error=True))
        continuing = make_controller(ExecutionConfig())
        statuses.clear()
        response = NativeResponse("http://example.test/item", 429, [], b"")
        error = RequestException("synthetic request failure")
        with patch.dict(options, {}, clear=True):
            with self.assertRaises(SkipTargetInterrupt):
                stopped.match_callback(response)
            with self.assertRaises(QuitInterrupt):
                stopped.raise_error(error)
            continuing.raise_error(error)
        self.assertEqual(stopped.run_state.errors, 0)
        self.assertEqual(continuing.run_state.errors, 1)
        self.assertEqual(continuing.run_state.consecutive_errors, 1)
        continuing.run_state.consecutive_errors = MAX_CONSECUTIVE_REQUEST_ERRORS
        with patch.dict(options, {}, clear=True), self.assertRaises(SkipTargetInterrupt):
            continuing.raise_error(error)
        with (
            patch.dict(options, {"skip_on_status": {429}}, clear=True),
            patch.object(continuing, "interface") as interface,
        ):
            self.assertIsNone(continuing.match_callback(response))
        interface.status_report.assert_called_once_with(response, False)

    def test_prepared_policy_is_shared_across_targets_and_agrees_with_transport(self):
        for backend, async_mode, engine, requester_path in (
            ("python", False, ScanEngine.THREADED, "lib.connection.requester.Requester"),
            ("python", True, ScanEngine.ASYNC, "lib.connection.requester.AsyncRequester"),
            ("native", False, ScanEngine.NATIVE, "lib.connection.native.NativeRequester"),
        ):
            for resumed in (False, True):
                with self.subTest(backend=backend, async_mode=async_mode, resumed=resumed):
                    policies = []
                    targets = []

                    def prepare(controller, *_args):
                        options.update(
                            request_backend=backend, async_mode=async_mode,
                            thread_count=3, delay=0.125, max_time=30, target_max_time=4,
                            skip_on_status={429}, exit_on_error=True, session_file=None,
                            urls=["http://first.test/", "http://second.test/"], subdirs=[],
                        )
                        controller._prepare_config(options)
                        controller.reporter = Mock(reports=(object(),))
                        controller.response_stores = (Mock(),)
                        controller.dictionary = Mock()
                        controller.target_progress.directories = []

                    def start(controller):
                        self.assertIs(controller.fuzzer.logger, controller.logger)
                        policies.append(controller.fuzzer.execution_config)
                        self.assertIs(policies[-1], controller.config.execution)
                        expected_fuzzer = {
                            ScanEngine.THREADED: Fuzzer,
                            ScanEngine.ASYNC: AsyncFuzzer,
                            ScanEngine.NATIVE: NativeFuzzer,
                        }[engine]
                        self.assertIs(type(controller.fuzzer), expected_fuzzer)
                        self.assertEqual(controller.fuzzer.match_callbacks, (
                            controller.match_callback,
                            controller.reporter.save_async if async_mode else controller.reporter.save,
                            controller.save_response_async if async_mode else controller.save_response,
                            controller.reset_consecutive_errors,
                        ))
                        if engine is ScanEngine.NATIVE:
                            self.assertEqual(controller.fuzzer.filtered_chunk_callbacks, (
                                controller.update_progress_bar_batch,
                                controller.reset_consecutive_errors_batch,
                            ))
                        options.update(thread_count=99, delay=0, max_time=0, target_max_time=0, exit_on_error=False)
                        options["skip_on_status"].clear()

                    def set_target(controller, url):
                        controller.target_progress.url = url
                        targets.append(url)

                    requester = Mock(backend=None)
                    if async_mode:
                        requester.close = AsyncMock()

                    def make_requester(*_args, **_kwargs):
                        # Deliberately contradict the prepared flags before loop
                        # creation and before either target's fuzzer is built.
                        options.update(
                            request_backend="python" if backend == "native" else "native",
                            async_mode=not async_mode,
                            urls=["http://unrelated.test/"],
                        )
                        return requester

                    with (
                        patch.dict(options, {
                            "request_backend": "python" if backend == "native" else "native",
                            "async_mode": False,
                            "session_file": "session.json" if resumed else None,
                        }),
                        patch.object(Controller, "setup", new=prepare),
                        patch.object(Controller, "_import", new=prepare),
                        patch.object(Controller, "set_target", new=set_target),
                        patch.object(Controller, "crawl_target"),
                        patch.object(Controller, "start", new=start),
                        patch(requester_path, side_effect=make_requester) as factory,
                        patch("lib.controller.controller.get_blacklists", return_value={}),
                        patch("lib.controller.controller.signal.signal"),
                        patch("lib.controller.controller.create_terminal"),
                    ):
                        controller = Controller()
                    self.assertEqual(len(policies), 2)
                    self.assertEqual(targets, ["http://first.test/", "http://second.test/"])
                    self.assertIs(policies[0], policies[1])
                    self.assertEqual(controller.config.execution, ExecutionConfig(
                        engine=engine,
                        concurrency=3, delay=0.125, max_time=30, target_max_time=4,
                        skip_on_status={429}, exit_on_error=True,
                    ))
                    transport = factory.call_args.args[0]
                    self.assertEqual(transport.concurrency, controller.config.execution.concurrency)
                    self.assertEqual(transport.delay, controller.config.execution.delay)
                    self.assertEqual(factory.call_count, 1)
                    self.assertEqual(factory.call_args.kwargs, (
                        {"filter_config": controller.config.filters}
                        if engine is ScanEngine.NATIVE else {"logger": controller.logger}
                    ))
                    if async_mode:
                        requester.close.assert_awaited_once_with()
                        self.assertTrue(controller.loop.is_closed())
                    else:
                        requester.close.assert_called_once_with()
                        self.assertIsNone(controller.loop)

    def test_real_checkpoint_restore_uses_saved_execution_policy(self):
        for backend, async_mode, engine, requester_path in (
            ("python", False, ScanEngine.THREADED, "lib.connection.requester.Requester"),
            ("python", True, ScanEngine.ASYNC, "lib.connection.requester.AsyncRequester"),
            ("native", False, ScanEngine.NATIVE, "lib.connection.native.NativeRequester"),
        ):
            with self.subTest(backend=backend, async_mode=async_mode), tempfile.TemporaryDirectory() as directory:
                saved_options = dict(options)
                saved_options.update(
                    request_backend=backend, async_mode=async_mode, urls=[],
                    thread_count=3, delay=0.125, max_time=30, target_max_time=4,
                    skip_on_status={429}, exit_on_error=True,
                    session_file=None, output_formats=[], log_file=None,
                    save_response=None, save_response_jsonl=None,
                )
                saved_controller = SimpleNamespace(
                    start_time=100, run_state=ScanRunState(saved_options["urls"]),
                    target_progress=TargetProgress(), output_history=[],
                    dictionary=Dictionary(WordlistConfig()),
                )
                checkpoint = os.path.join(directory, "checkpoint")
                SessionStore().save(
                    Controller._snapshot_session(saved_controller, SessionOptions.from_options(saved_options), ""), checkpoint
                )
                requester = Mock(backend=None)
                if async_mode:
                    requester.close = AsyncMock()
                with (
                    patch.dict(options, {
                        "session_file": checkpoint, "thread_count": 99, "delay": 0,
                        "max_time": 0, "target_max_time": 0, "skip_on_status": set(),
                        "exit_on_error": False,
                        "request_backend": "python" if backend == "native" else "native",
                        "async_mode": False,
                    }),
                    patch.object(Controller, "_confirm_session_overwrite"),
                    patch(requester_path, return_value=requester),
                    patch("lib.controller.controller.get_blacklists", return_value={}),
                    patch("lib.controller.controller.ReportManager", return_value=Mock(reports=())),
                    patch("lib.controller.controller.signal.signal"),
                    patch("lib.controller.controller.create_terminal"),
                ):
                    controller = Controller()
                self.assertEqual(controller.config.execution, ExecutionConfig(
                    engine=engine,
                    concurrency=3, delay=0.125, max_time=30, target_max_time=4,
                    skip_on_status={429}, exit_on_error=True,
                ))
                self.assertEqual(controller.config.request.concurrency, 3)
                self.assertEqual(controller.config.request.delay, 0.125)
