from dataclasses import replace
import os
import tempfile
from io import StringIO
from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import Mock, call, patch

from lib.controller.run_resources import RunResources
from lib.controller.controller import Controller
from lib.core.target_progress import TargetProgress
from lib.controller.session import SessionStore
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.discovery_config import DiscoveryConfig
from lib.core.exceptions import InvalidURLException, QuitInterrupt, SkipTargetInterrupt
from lib.core.execution_config import ScanEngine
from lib.core.scan_run_state import ScanRunState
from lib.core.run_metadata import RunMetadata


class TestControllerRunState(TestCase):
    def _controller(self):
        controller = object.__new__(Controller)
        controller.resources = RunResources(interface=Mock(buffer=""), logger=Mock())
        controller._prepare_config(options)
        controller.metadata = RunMetadata("dirsearch", "2026-10-06 12:00:00")
        controller.run_state = ScanRunState()
        controller.target_progress = TargetProgress()
        controller._terminal_stream = StringIO()
        self.addCleanup(lambda: controller.resources.interface.close())
        controller.start_time = 0
        controller.run_state.passed_urls = set()
        controller.target_progress.directories = []
        controller.run_state.jobs_processed = 0
        controller.run_state.errors = 0
        controller.run_state.consecutive_errors = 0
        controller.target_progress.base_path = ""
        controller.target_progress.url = ""
        controller.run_state.old_session = False
        controller.dictionary = Dictionary(controller.config.wordlist)
        controller.output_history = []
        controller._native_worker = None
        controller.resources.reporter = Mock()
        controller.set_target = Mock(side_effect=lambda url: setattr(controller.target_progress, "url", url))
        controller.crawl_target = Mock()
        controller.start = Mock()

        def close_loop():
            if controller.resources.loop is not None:
                controller.resources.loop.close()

        self.addCleanup(close_loop)
        return controller

    @contextmanager
    def _environment(self, engine, targets):
        # The controller lifecycle is real; no requests or worker threads run.
        with (
            patch.dict(options, {
                "urls": targets,
                "request_backend": "native" if engine is ScanEngine.NATIVE else "python",
                "async_mode": engine is ScanEngine.ASYNC,
                "subdirs": [],
                "session_file": None,
                "output_formats": [],
                "log_file": None,
                "save_response": None,
                "save_response_jsonl": None,
            }),
            patch("lib.connection.requester.Requester"),
            patch("lib.connection.requester.AsyncRequester"),
            patch("lib.connection.native.NativeRequester"),
            patch("lib.core.fuzzer.Fuzzer"),
            patch("lib.core.fuzzer.AsyncFuzzer"),
            patch("lib.core.fuzzer.NativeFuzzer"),
            patch("lib.controller.controller.signal.signal"),
        ):
            yield

    def test_later_global_changes_cannot_replace_pending_targets(self):
        for engine in ScanEngine:
            targets = ["http://first.test/", "http://next.test/", "http://first.test/"]
            expected = list(targets)
            with self.subTest(engine=engine), self._environment(engine, targets):
                controller = self._controller()
                observations = []

                def start():
                    observations.append((
                        controller.run_state.active_task.target,
                        controller.run_state.pending_count,
                        [task.target for task in controller.run_state.snapshot_tasks()],
                    ))
                    options["urls"] = ["http://unrelated.test/"]

                controller.start.side_effect = start
                controller.run()
                self.assertEqual(controller.set_target.call_args_list, list(map(call, expected)))
                self.assertEqual(observations, [
                    (target, len(expected) - index - 1, expected[index:])
                    for index, target in enumerate(expected)
                ])
                self.assertEqual(targets, expected)
                self.assertEqual(options["urls"], ["http://unrelated.test/"])
                self.assertIsNone(controller.run_state.active_task)
                self.assertEqual([task.target for task in controller.run_state.snapshot_tasks()], [])

    def test_empty_run_never_activates_a_target(self):
        for engine in ScanEngine:
            with self.subTest(engine=engine), self._environment(engine, []):
                controller = self._controller()
                controller.run()
                controller.set_target.assert_not_called()
                controller.start.assert_not_called()
                controller.resources.reporter.finish.assert_called_once_with()
                self.assertEqual([task.target for task in controller.run_state.snapshot_tasks()], [])

    def test_handled_target_exit_advances_once(self):
        for engine in ScanEngine:
            for error in (InvalidURLException, SkipTargetInterrupt, KeyboardInterrupt):
                targets = ["http://first.test/", "http://next.test/"]
                with (
                    self.subTest(engine=engine, error=error),
                    self._environment(engine, targets),
                ):
                    controller = self._controller()
                    controller.start.side_effect = [error("interrupted"), None]
                    controller.run()
                    self.assertEqual(controller.set_target.call_args_list, list(map(call, targets)))
                    self.assertEqual(controller.start.call_count, 2)
                    self.assertEqual([task.target for task in controller.run_state.snapshot_tasks()], [])

    def test_fuzzer_setup_failure_does_not_activate_later_targets(self):
        for engine, fuzzer_name in (
            (ScanEngine.THREADED, "Fuzzer"),
            (ScanEngine.ASYNC, "AsyncFuzzer"),
            (ScanEngine.NATIVE, "NativeFuzzer"),
        ):
            targets = ["http://first.test/", "http://next.test/"]
            with (
                self.subTest(engine=engine),
                self._environment(engine, targets),
                patch(f"lib.core.fuzzer.{fuzzer_name}", side_effect=RuntimeError("setup failed")),
            ):
                controller = self._controller()
                with self.assertRaisesRegex(RuntimeError, "setup failed"):
                    controller.run()
                controller.set_target.assert_not_called()
                self.assertEqual(controller.run_state.active_task.target, targets[0])
                self.assertEqual(controller.run_state.pending_count, 1)
                self.assertEqual([task.target for task in controller.run_state.snapshot_tasks()], targets)

    def test_progress_counts_pending_targets_without_global_urls(self):
        controller = self._controller()
        controller.run_state = ScanRunState(["done", "active", "next", "last"])
        controller.run_state.activate_next()
        controller.run_state.finish_active()
        controller.run_state.activate_next()
        controller.config = replace(controller.config, discovery=DiscoveryConfig(subdirs=["", "api/"]))
        controller.target_progress.directories = ["current/", "queued/"]
        controller.run_state.jobs_processed = 3
        controller.resources.requester = Mock(rate=7)
        for callback in (controller.update_progress_bar, controller.update_progress_bar_batch):
            with (
                self.subTest(callback=callback.__name__),
                patch.dict(options, {}, clear=True),
                patch.object(controller.resources, "interface") as interface,
            ):
                callback(None)
                interface.last_path.assert_called_once_with(0, 0, 4, 9, 7, 0)

    def test_saved_quit_preserves_active_and_pending_for_every_engine(self):
        for engine in ScanEngine:
            targets = ["http://done.test/", "http://active.test/", "http://pending.test/"]
            with (
                self.subTest(engine=engine),
                tempfile.TemporaryDirectory() as directory,
                self._environment(engine, targets),
            ):
                controller = self._controller()
                checkpoint = os.path.join(directory, "checkpoint.json")

                def start():
                    if controller.run_state.active_task.target == targets[1]:
                        # Changing global input must not leak into persistence.
                        options["urls"] = ["http://unrelated.test/"]
                        controller._export(checkpoint)
                        raise QuitInterrupt("saved")

                controller.start.side_effect = start
                with self.assertRaises(SystemExit) as stopped:
                    controller.run()
                self.assertEqual(stopped.exception.code, 0)
                payload = SessionStore().load(checkpoint)
                self.assertEqual([task.target for task in payload.remaining_tasks], targets[1:])
                self.assertEqual(payload.task_checkpoint.url, targets[1])
                self.assertEqual(controller.set_target.call_args_list, list(map(call, targets[:2])))
                self.assertEqual(options["urls"], ["http://unrelated.test/"])
                self.assertIsNone(controller.run_state.active_task)
                self.assertEqual([task.target for task in controller.run_state.snapshot_tasks()], targets[2:])

                # A real JSON checkpoint can resume through any engine. Engine
                # overrides belong to the caller, not the serialized queue.
                for resume_engine in ScanEngine:
                    with self.subTest(resume_engine=resume_engine):
                        resumed = self._controller()
                        restored_targets = [task.target for task in payload.remaining_tasks]
                        with self._environment(resume_engine, restored_targets):
                            resumed._prepare_config(options)
                            resumed._restore_session(payload)
                            self.addCleanup(resumed.resources.reporter.finish)
                            resumed.run()
                            self.assertEqual(
                                resumed.set_target.call_args_list, list(map(call, targets[1:]))
                            )
                            self.assertEqual(restored_targets, targets[1:])

    def test_failed_save_changes_neither_input_nor_progress(self):
        targets = ["http://first.test/", "http://next.test/"]
        with (
            tempfile.TemporaryDirectory() as directory,
            self._environment(ScanEngine.THREADED, targets),
        ):
            controller = self._controller()
            controller.run_state = ScanRunState(targets)
            controller.run_state.activate_next()
            controller.target_progress.url = targets[0]
            checkpoint = os.path.join(directory, "checkpoint.json")
            controller._export(checkpoint)
            before = SessionStore().load(checkpoint)
            controller.run_state.finish_active()
            controller.run_state.activate_next()
            controller.target_progress.url = targets[1]
            with (
                patch("lib.utils.file.os.replace", side_effect=OSError("write failed")),
                self.assertRaisesRegex(OSError, "write failed"),
            ):
                controller._export(checkpoint)
            self.assertEqual(SessionStore().load(checkpoint), before)
            self.assertEqual(controller.run_state.active_task.target, targets[1])
            self.assertEqual([task.target for task in controller.run_state.snapshot_tasks()], targets[1:])
            self.assertEqual(options["urls"], targets)

    def test_import_rebuilds_remaining_work_from_checkpoint_not_cli_input(self):
        for engine in ScanEngine:
            targets = ["http://done.test/", "http://active.test/", "http://pending.test/"]
            with (
                self.subTest(engine=engine),
                tempfile.TemporaryDirectory() as directory,
                self._environment(engine, targets),
                patch("lib.controller.controller.ReportManager", return_value=Mock()),
                patch.object(Controller, "_confirm_session_overwrite"),
            ):
                saved = self._controller()
                saved.run_state = ScanRunState(targets)
                saved.run_state.activate_next()
                saved.run_state.finish_active()
                saved.run_state.activate_next()
                saved.target_progress.url = targets[1]
                checkpoint = os.path.join(directory, "checkpoint.json")
                saved._export(checkpoint)

                options["urls"] = ["http://unrelated.test/"]
                resumed = self._controller()
                resumed._import(checkpoint)
                resumed.run()
                self.assertEqual(resumed.set_target.call_args_list, list(map(call, targets[1:])))
                self.assertEqual(options["urls"], targets[1:])
                self.assertEqual([task.target for task in resumed.run_state.snapshot_tasks()], [])
