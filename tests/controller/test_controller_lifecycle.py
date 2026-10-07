"""Construction is inert; explicit execution owns preparation and cleanup."""

from io import StringIO
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.run_metadata import RunMetadata
from lib.core.terminal_config import TerminalConfig
from lib.view.terminal import create_terminal


class TestControllerLifecycle(TestCase):
    def setUp(self):
        # These tests stop at preparation/target-loop seams, so only bootstrap
        # presentation and the fresh/resume selector need normalized input.
        self.enterContext(patch.dict(options, {
            "color": False, "quiet": False, "disable_cli": False,
            "verbose": False, "extensions": (), "prefixes": (), "suffixes": (),
            "http_method": "GET", "thread_count": 1, "session_file": None,
        }, clear=True))

    def test_construction_neither_reads_cli_options_nor_opens_or_runs_resources(self):
        output = StringIO()
        metadata = RunMetadata("dirsearch", "2026-10-07 12:00:00")
        with (
            patch.dict(options, {}, clear=True),
            patch("lib.controller.controller.create_terminal") as terminal,
            patch("lib.controller.controller.RunLogger") as logger,
            patch.object(Controller, "setup") as setup,
            patch.object(Controller, "_import") as restore,
            patch.object(Controller, "run") as run,
            patch("lib.controller.controller.signal.signal") as register_signal,
        ):
            controller = Controller(output=output, metadata=metadata)
        self.assertIsNone(controller.resources)
        self.assertIs(controller.metadata, metadata)
        self.assertEqual(output.getvalue(), "")
        self.assertFalse(output.closed)
        for dependency in (terminal, logger, setup, restore, run, register_signal):
            dependency.assert_not_called()

    def test_run_selects_preparation_before_execution_and_closes_afterward(self):
        for session_file in (None, "checkpoint.json"):
            with self.subTest(session_file=session_file):
                events = []
                terminal = Mock(close=lambda: events.append("terminal-close"))
                logger = Mock(close=lambda: events.append("logger-close"))
                controller = Controller(output=StringIO())
                controller.run_state.old_session = not bool(session_file)

                def restore(path):
                    self.assertEqual(path, session_file)
                    self.assertTrue(controller.run_state.old_session)
                    events.append("restore")

                def execute():
                    self.assertEqual(controller.run_state.old_session, bool(session_file))
                    self.assertIs(controller.resources.interface, terminal)
                    self.assertIs(controller.resources.logger, logger)
                    events.append("execute")

                with (
                    patch.dict(options, session_file=session_file),
                    patch("lib.controller.controller.create_terminal", return_value=terminal) as make_terminal,
                    patch("lib.controller.controller.RunLogger", return_value=logger) as make_logger,
                    patch.object(controller, "setup", side_effect=lambda: events.append("setup")) as setup,
                    patch.object(controller, "_import", side_effect=restore) as load,
                    patch.object(controller, "_run_targets", side_effect=execute),
                ):
                    self.assertIsNone(controller.run())
                make_terminal.assert_called_once()
                make_logger.assert_called_once_with()
                self.assertEqual(setup.call_count, 0 if session_file else 1)
                self.assertEqual(load.call_count, 1 if session_file else 0)
                self.assertEqual(events, [
                    "restore" if session_file else "setup", "execute", "terminal-close", "logger-close",
                ])

    def test_second_run_is_rejected_after_success_or_any_lifecycle_failure(self):
        for phase in (None, "setup", "restore", "execute", "terminal-close", "logger-close"):
            with self.subTest(phase=phase):
                error = RuntimeError("injected failure")
                terminal, logger = Mock(), Mock()
                if phase == "terminal-close":
                    terminal.close.side_effect = error
                if phase == "logger-close":
                    logger.close.side_effect = error
                controller = Controller(output=StringIO())
                with (
                    patch.dict(options, session_file="checkpoint.json" if phase == "restore" else None),
                    patch("lib.controller.controller.create_terminal", return_value=terminal) as make_terminal,
                    patch("lib.controller.controller.RunLogger", return_value=logger) as make_logger,
                    patch.object(controller, "setup", side_effect=error if phase == "setup" else None) as setup,
                    patch.object(controller, "_import", side_effect=error if phase == "restore" else None) as restore,
                    patch.object(controller, "_run_targets", side_effect=error if phase == "execute" else None) as execute,
                ):
                    if phase is None:
                        controller.run()
                    else:
                        with self.assertRaisesRegex(RuntimeError, "injected failure"):
                            controller.run()
                    if phase in ("setup", "restore"):
                        execute.assert_not_called()
                    calls_before = (setup.call_count, restore.call_count, execute.call_count)
                    # Rejection must precede even reading options or opening files.
                    with patch.dict(options, {}, clear=True), self.assertRaisesRegex(RuntimeError, "only be called once"):
                        controller.run()
                    self.assertEqual(calls_before, (setup.call_count, restore.call_count, execute.call_count))
                    make_terminal.assert_called_once()
                    make_logger.assert_called_once_with()
                terminal.close.assert_called_once_with()
                logger.close.assert_called_once_with()

    def test_terminal_creation_failure_does_not_prepare_or_allow_retry(self):
        controller = Controller(output=StringIO())
        with (
            patch("lib.controller.controller.create_terminal", side_effect=OSError("terminal failed")) as terminal,
            patch("lib.controller.controller.RunLogger") as logger,
            patch.object(controller, "_prepare") as prepare,
            patch.object(controller, "_run_targets") as execute,
        ):
            with self.assertRaisesRegex(OSError, "terminal failed"):
                controller.run()
            with self.assertRaisesRegex(RuntimeError, "only be called once"):
                controller.run()
        self.assertIsNone(controller.resources)
        terminal.assert_called_once()
        for dependency in (logger, prepare, execute):
            dependency.assert_not_called()

    def test_bootstrap_logging_failure_closes_terminal_without_closing_borrowed_output(self):
        for error in (OSError("logger failed"), KeyboardInterrupt(), SystemExit(2)):
            with self.subTest(error=type(error).__name__):
                output = StringIO()
                terminal = create_terminal(TerminalConfig(color=False), stream=output)
                self.addCleanup(terminal.close)
                controller = Controller(output=output)
                with (
                    patch("lib.controller.controller.create_terminal", return_value=terminal) as factory,
                    patch("lib.controller.controller.RunLogger", side_effect=error) as logger,
                    patch.object(controller, "_prepare") as prepare,
                    patch.object(controller, "_run_targets") as execute,
                ):
                    with self.assertRaises(type(error)) as raised:
                        controller.run()
                    self.assertIs(raised.exception, error)
                    with self.assertRaisesRegex(RuntimeError, "only be called once"):
                        controller.run()
                factory.assert_called_once()
                logger.assert_called_once_with()
                prepare.assert_not_called()
                execute.assert_not_called()
                self.assertIsNone(controller.resources)
                self.assertTrue(terminal._output_buffer.closed)
                self.assertFalse(output.closed)

    def test_interruptions_during_preparation_still_close_resources(self):
        for error in (KeyboardInterrupt(), SystemExit(3)):
            with self.subTest(error=type(error).__name__):
                terminal, logger = Mock(), Mock()
                with (
                    patch("lib.controller.controller.create_terminal", return_value=terminal),
                    patch("lib.controller.controller.RunLogger", return_value=logger),
                    patch.object(Controller, "_prepare", side_effect=error),
                    patch.object(Controller, "_run_targets") as execute,
                ):
                    with self.assertRaises(type(error)) as raised:
                        Controller(output=StringIO()).run()
                self.assertIs(raised.exception, error)
                execute.assert_not_called()
                terminal.close.assert_called_once_with()
                logger.close.assert_called_once_with()

    def test_reentrant_run_cannot_acquire_a_second_set_of_resources(self):
        for phase in ("_prepare", "_run_targets"):
            with self.subTest(phase=phase):
                controller = Controller(output=StringIO())
                terminal, logger = Mock(), Mock()
                with (
                    patch("lib.controller.controller.create_terminal", return_value=terminal) as factory,
                    patch("lib.controller.controller.RunLogger", return_value=logger) as make_logger,
                    patch.object(controller, "_prepare"),
                    patch.object(controller, "_run_targets"),
                    patch.object(controller, phase, side_effect=controller.run),
                    self.assertRaisesRegex(RuntimeError, "only be called once"),
                ):
                    controller.run()
                factory.assert_called_once()
                make_logger.assert_called_once_with()
                terminal.close.assert_called_once_with()
                logger.close.assert_called_once_with()

    def test_metadata_and_stream_are_captured_at_construction_options_only_at_run(self):
        metadata = RunMetadata("dirsearch", "2026-10-07 12:00:00")
        output, unrelated_output = StringIO(), StringIO()
        terminal = Mock()
        with (
            patch("lib.controller.controller.RunMetadata.capture", return_value=metadata) as capture,
            patch("sys.stdout", output),
        ):
            controller = Controller()
            capture.assert_called_once_with()
            with (
                patch("sys.stdout", unrelated_output),
                patch.dict(options, quiet=True),
                patch("lib.controller.controller.create_terminal", return_value=terminal) as factory,
                patch.object(controller, "_prepare"),
                patch.object(controller, "_run_targets"),
            ):
                controller.run()
            capture.assert_called_once_with()
        self.assertIs(controller.metadata, metadata)
        self.assertIs(factory.call_args.kwargs["stream"], output)
        self.assertTrue(factory.call_args.args[0].quiet)

    def test_failed_owner_does_not_initialize_or_close_another_controller(self):
        first_output, second_output = StringIO(), StringIO()
        first, second = Controller(output=first_output), Controller(output=second_output)
        with (
            patch.object(first, "_prepare"),
            patch.object(first, "_run_targets", side_effect=RuntimeError("first failed")),
            self.assertRaisesRegex(RuntimeError, "first failed"),
        ):
            first.run()
        self.assertTrue(first.resources.interface._output_buffer.closed)
        self.assertIsNone(second.resources)
        self.assertEqual(second_output.getvalue(), "")
        with patch.object(second, "_prepare"), patch.object(second, "_run_targets") as execute:
            second.run()
        execute.assert_called_once_with()
        self.assertIsNot(first.resources, second.resources)
        self.assertTrue(second.resources.interface._output_buffer.closed)
        self.assertFalse(first_output.closed)
        self.assertFalse(second_output.closed)
