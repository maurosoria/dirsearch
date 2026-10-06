"""Controller-owned presentation across preparation, resume and cleanup."""

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch, sentinel

from lib.controller.session_snapshot import RunCheckpoint, SessionSnapshot
from lib.core.task_checkpoint import DictionaryCheckpoint, TaskCheckpoint
from lib.controller.controller import (
    Controller, PyInstallerLinuxForceQuitHandler, StandardForceQuitHandler,
    _create_force_quit_handler,
)
from lib.core.data import options
from lib.core.exceptions import InvalidURLException
from lib.core.settings import SIGINT_FORCE_QUIT_THRESHOLD
from lib.view.terminal import QuietCLI, create_terminal


class TestControllerTerminalOwnership(TestCase):
    def setUp(self):
        self.options_patch = patch.dict(options, {
            "session_file": None, "raw_file": None, "wordlists": [],
            "wordlist_backend": "python", "color": False, "quiet": False,
            "disable_cli": False, "log_file": None, "save_response": None,
            "save_response_jsonl": None, "output_formats": [], "urls": [],
        })
        self.options_patch.start()
        self.addCleanup(self.options_patch.stop)
        self.terminals = []

        def record_terminal(*args, **kwargs):
            terminal = create_terminal(*args, **kwargs)
            self.terminals.append(terminal)
            self.addCleanup(terminal.close)
            return terminal

        factory = patch("lib.controller.controller.create_terminal", side_effect=record_terminal)
        factory.start()
        self.addCleanup(factory.stop)

    def assert_all_terminals_closed(self):
        self.assertTrue(self.terminals)
        self.assertTrue(all(terminal._output_buffer.closed for terminal in self.terminals))

    def test_raw_request_summary_uses_prepared_method(self):
        output = StringIO()
        options["raw_file"] = "request.txt"
        with (
            patch("lib.controller.controller.parse_raw", return_value=(
                ["http://example.test/"], "POST", {}, "body",
            )),
            patch.object(Controller, "run"),
        ):
            controller = Controller(output=output)
        self.assertEqual(controller.interface.config.method, "POST")
        self.assertIn("HTTP method: POST", output.getvalue())
        self.assertNotIn("HTTP method: GET", output.getvalue())
        self.assert_all_terminals_closed()
        self.assertFalse(output.closed)

    def test_fresh_and_resumed_runs_keep_separate_streams_and_histories(self):
        for backend, async_mode in (("python", False), ("python", True), ("native", False)):
            with self.subTest(backend=backend, async_mode=async_mode), TemporaryDirectory() as directory:
                checkpoint = str(Path(directory, "checkpoint.json"))
                options.update(
                    session_file=None, quiet=True, verbose=True,
                    request_backend=backend, async_mode=async_mode,
                )
                original_output = StringIO()

                def save(controller):
                    controller.target_progress.base_path = ""
                    controller.target_progress.url = ""
                    controller.interface.new_line("first run")
                    controller._export(checkpoint)

                with patch.object(Controller, "run", new=save):
                    original = Controller(output=original_output)
                options.update(session_file=checkpoint, quiet=False, verbose=False)
                resumed_output = StringIO()

                def resume(controller):
                    self.assertIsInstance(controller.interface, QuietCLI)
                    self.assertTrue(controller.interface.config.verbose)
                    self.assertEqual(controller.interface.buffer, "")
                    controller.interface.new_line("resumed run")
                    self.assertEqual(controller.interface.buffer, "resumed run\n")

                with (
                    patch.object(Controller, "run", new=resume),
                    patch.object(Controller, "_confirm_session_overwrite"),
                ):
                    resumed = Controller(output=resumed_output)
                self.assertIsNot(original.interface, resumed.interface)
                self.assertEqual(original_output.getvalue(), "first run\n")
                self.assertIn("first run", resumed_output.getvalue())
                self.assertIn("resumed run", resumed_output.getvalue())
                self.assert_all_terminals_closed()

    def test_history_is_closed_when_preparation_or_execution_fails(self):
        for phase in ("setup", "run"):
            with self.subTest(phase=phase), patch.object(Controller, phase, side_effect=RuntimeError(phase)):
                output = StringIO()
                with self.assertRaisesRegex(RuntimeError, phase):
                    Controller(output=output)
                self.assert_all_terminals_closed()
                self.assertFalse(output.closed)

    def test_history_is_closed_even_when_another_cleanup_raises(self):
        for cleanup in ("_close_reporter", "_close_requester", "_close_response_stores"):
            with (
                self.subTest(cleanup=cleanup),
                patch.object(Controller, "setup"),
                patch.object(Controller, "run"),
                patch.object(Controller, cleanup, side_effect=OSError("cleanup failed")),
            ):
                with self.assertRaisesRegex(OSError, "cleanup failed"):
                    Controller(output=StringIO())
                self.assert_all_terminals_closed()

    def test_failed_replacement_keeps_bootstrap_available_for_cleanup(self):
        bootstrap = Mock()
        with patch("lib.controller.controller.create_terminal", side_effect=[
            bootstrap, OSError("terminal failed"),
        ]):
            with self.assertRaisesRegex(OSError, "terminal failed"):
                Controller(output=StringIO())
        bootstrap.close.assert_called_once_with()

    def test_restore_report_error_is_rendered_by_the_owning_controller(self):
        options["session_file"] = "checkpoint.json"
        output = StringIO()
        with (
            patch("lib.controller.controller.SessionStore") as store_factory,
            patch.object(Controller, "run") as run,
            patch.object(Controller, "_restore_session", side_effect=InvalidURLException("invalid report URL")),
        ):
            store = store_factory.return_value
            store.load.return_value = SessionSnapshot(
                run=RunCheckpoint(0), task_checkpoint=TaskCheckpoint(DictionaryCheckpoint((), 0)), options={},
            )
            with self.assertRaises(SystemExit) as stopped:
                Controller(output=output)
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn("invalid report URL", output.getvalue())
        run.assert_not_called()
        self.assert_all_terminals_closed()

    def test_force_quit_handlers_use_the_supplied_terminal(self):
        terminal = Mock()
        with patch("lib.controller.controller.os._exit") as exit_process:
            self.assertTrue(StandardForceQuitHandler().check_force_quit(terminal))
        terminal.warning.assert_called_once_with("\nForce quit!", do_save=False)
        exit_process.assert_called_once_with(1)

        terminal.reset_mock()
        handler = PyInstallerLinuxForceQuitHandler()
        with (
            # Exercise Linux strategy with an explicit platform boundary even
            # on Windows, where the real signal module has no SIGKILL.
            patch("lib.controller.controller.signal", SimpleNamespace(SIGKILL=sentinel.sigkill)),
            patch("lib.controller.controller.time.monotonic", return_value=10),
            patch("lib.controller.controller.os.getpid", return_value=123),
            patch("lib.controller.controller.os.kill") as kill,
            patch("lib.controller.controller.os._exit") as exit_process,
        ):
            handler.on_pause_start()
            for _ in range(SIGINT_FORCE_QUIT_THRESHOLD - 1):
                handler.check_force_quit(terminal)
        terminal.warning.assert_called_once_with("\nForce quit!", do_save=False)
        kill.assert_called_once_with(123, sentinel.sigkill)
        exit_process.assert_called_once_with(1)

    def test_force_quit_factory_selects_linux_strategy_only_for_frozen_linux(self):
        for platform, frozen, expected in (
            ("win32", False, StandardForceQuitHandler),
            ("win32", True, StandardForceQuitHandler),
            ("linux", False, StandardForceQuitHandler),
            ("linux", True, PyInstallerLinuxForceQuitHandler),
            ("darwin", True, StandardForceQuitHandler),
        ):
            with (
                self.subTest(platform=platform, frozen=frozen),
                patch("lib.controller.controller.sys", SimpleNamespace(platform=platform, frozen=frozen)),
            ):
                self.assertIsInstance(_create_force_quit_handler(), expected)
