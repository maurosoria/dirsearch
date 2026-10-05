# -*- coding: utf-8 -*-

from unittest import TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.exceptions import QuitInterrupt, SkipTargetInterrupt
from lib.core.execution_config import ExecutionConfig, ScanEngine
from lib.core.scan_run_state import ScanRunState


class RecordingForceQuitHandler:
    def __init__(self):
        self.pause_starts = 0
        self.resumes = 0
        self.force_quit_checks = 0

    def check_force_quit(self):
        self.force_quit_checks += 1
        return False

    def on_pause_start(self):
        self.pause_starts += 1

    def on_resume(self):
        self.resumes += 1


class RecordingPauseFuture:
    def __init__(self):
        self.error = None

    def set_exception(self, error):
        self.error = error


class TestPauseState(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        self.reset_controller()

    def reset_controller(self):
        self.controller = object.__new__(Controller)
        self.controller.execution_config = ExecutionConfig.from_options(options)
        self.controller.run_state = ScanRunState(options["urls"])
        self.controller.run_state.activate_next()
        self.controller._handling_pause = False
        self.controller._force_quit_handler = RecordingForceQuitHandler()
        self.controller.fuzzer = Mock()
        self.controller.fuzzer.pause.return_value = True
        self.controller.directories = ["first/", "second/"]

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def exercise_second_pause(self, first_option, second_option="c"):
        with patch("builtins.input", side_effect=(first_option, second_option)), patch(
            "lib.controller.controller.interface"
        ):
            self.controller.handle_pause()
            self.controller.handle_pause()

    def assert_pause_state_was_rearmed(self):
        self.assertFalse(self.controller._handling_pause)
        self.assertEqual(self.controller._force_quit_handler.force_quit_checks, 0)
        self.assertEqual(self.controller._force_quit_handler.pause_starts, 2)
        self.assertEqual(self.controller._force_quit_handler.resumes, 2)
        self.assertEqual(self.controller.fuzzer.pause.call_count, 2)
        self.controller.fuzzer.play.assert_called_once_with()

    def test_next_directory_rearms_pause_for_every_engine(self):
        engine_options = (
            {"request_backend": "python", "async_mode": False},
            {"request_backend": "python", "async_mode": True},
            {"request_backend": "native", "async_mode": False},
        )

        for run_options in engine_options:
            with self.subTest(options=run_options), patch.dict(
                options,
                {**run_options, "urls": ["https://example.test"]},
            ):
                self.reset_controller()
                self.exercise_second_pause("n")
                self.assert_pause_state_was_rearmed()
                self.controller.fuzzer.quit.assert_called_once_with()

    def test_quit_save_and_skip_follow_frozen_engine_after_flags_change(self):
        for engine in ScanEngine:
            for answers, error_type in (
                (("q", "q"), QuitInterrupt),
                (("q", "s", "checkpoint"), QuitInterrupt),
                (("s",), SkipTargetInterrupt),
            ):
                with (
                    self.subTest(engine=engine, answers=answers),
                    patch.dict(options, {
                        "urls": ["http://first.test/", "http://second.test/"],
                        "session_file": None,
                    }),
                    patch("builtins.input", side_effect=answers),
                    patch("lib.controller.controller.interface"),
                ):
                    self.reset_controller()
                    self.controller.execution_config = ExecutionConfig(engine=engine)
                    self.controller.pause_future = RecordingPauseFuture()
                    self.controller._export = Mock()
                    options.update(request_backend="python", async_mode=engine is not ScanEngine.ASYNC)
                    if engine is ScanEngine.ASYNC:
                        self.controller.handle_pause()
                        self.assertIsInstance(self.controller.pause_future.error, error_type)
                    else:
                        with self.assertRaises(error_type):
                            self.controller.handle_pause()
                        self.assertIsNone(self.controller.pause_future.error)
                    if answers == ("q", "s", "checkpoint"):
                        self.controller._export.assert_called_once_with("checkpoint")
                    else:
                        self.controller._export.assert_not_called()

    def test_skip_target_rearms_pause_for_threaded_and_native_engines(self):
        for request_backend in ("python", "native"):
            with self.subTest(request_backend=request_backend), patch.dict(
                options,
                {
                    "request_backend": request_backend,
                    "async_mode": False,
                    "urls": ["https://first.test", "https://second.test"],
                },
            ), patch(
                "builtins.input",
                side_effect=("s", "c"),
            ), patch(
                "lib.controller.controller.interface"
            ):
                self.reset_controller()
                with self.assertRaises(SkipTargetInterrupt):
                    self.controller.handle_pause()
                self.controller.handle_pause()

                self.assert_pause_state_was_rearmed()
                self.controller.fuzzer.quit.assert_not_called()

    def test_skip_target_rearms_pause_for_async_engine(self):
        with patch.dict(
            options,
            {
                "request_backend": "python",
                "async_mode": True,
                "urls": ["https://first.test", "https://second.test"],
            },
        ):
            self.reset_controller()
            self.controller.pause_future = RecordingPauseFuture()
            self.controller.execution_config = ExecutionConfig(engine=ScanEngine.ASYNC)
            self.exercise_second_pause("s")

        self.assertIsInstance(
            self.controller.pause_future.error,
            SkipTargetInterrupt,
        )
        self.assert_pause_state_was_rearmed()
        self.controller.fuzzer.quit.assert_not_called()

    def test_skip_uses_pending_state_even_if_global_urls_are_empty(self):
        for engine in ScanEngine:
            with (
                self.subTest(engine=engine),
                patch.dict(options, {"urls": []}),
                patch("builtins.input", return_value="s"),
                patch("lib.controller.controller.interface") as interface,
            ):
                self.reset_controller()
                self.controller.execution_config = ExecutionConfig(engine=engine)
                self.controller.pause_future = RecordingPauseFuture()
                self.controller.run_state = ScanRunState(["first", "pending"])
                self.controller.run_state.activate_next()
                if engine is ScanEngine.ASYNC:
                    self.controller.handle_pause()
                    self.assertIsInstance(self.controller.pause_future.error, SkipTargetInterrupt)
                else:
                    with self.assertRaises(SkipTargetInterrupt):
                        self.controller.handle_pause()
                self.assertIn("[s]kip target", interface.in_line.call_args.args[0])
                # The menu signals the exit; only run() finishes the attempt.
                self.assertEqual(self.controller.run_state.active_target, "first")

    def test_last_active_target_cannot_skip_to_stale_global_urls(self):
        for engine in ScanEngine:
            with (
                self.subTest(engine=engine),
                patch.dict(options, {"urls": ["stale", "also-stale"]}),
                patch("builtins.input", side_effect=("s", "c")),
                patch("lib.controller.controller.interface") as interface,
            ):
                self.reset_controller()
                self.controller.execution_config = ExecutionConfig(engine=engine)
                self.controller.run_state = ScanRunState(["last"])
                self.controller.run_state.activate_next()
                self.controller.handle_pause()
                for call in interface.in_line.call_args_list:
                    self.assertNotIn("[s]kip target", call.args[0])
                self.controller.fuzzer.play.assert_called_once_with()
