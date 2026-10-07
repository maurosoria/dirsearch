"""Logging is prepared once and closed after all controller borrowers."""

import asyncio
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.controller.controller import Controller
from lib.controller.run_resources import RunResources
from lib.controller.session_snapshot import RunCheckpoint, SessionSnapshot
from lib.controller.session_options import SessionOptions
from lib.core.task_checkpoint import DictionaryCheckpoint, TaskCheckpoint
from lib.core.data import options
from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig
from lib.core.filter_config import FilterConfig
from lib.core.fuzzer import AsyncFuzzer, Fuzzer, NativeFuzzer
from lib.core.logger import RunLogger
from lib.core.scanner import AsyncScanner, Scanner


class TestControllerLoggingOwnership(TestCase):
    def setUp(self):
        # Only composition still adapts CLI/session options. The logger itself
        # is covered without patching globals in tests/core/test_run_logger.py.
        self.options_patch = patch.dict(options, {
            "session_file": None, "raw_file": None, "wordlists": [], "urls": [],
            "wordlist_backend": "python", "color": False, "quiet": True,
            "disable_cli": False, "log_file": None, "log_file_size": 0,
            "proxy_auth": None, "save_response": None, "save_response_jsonl": None,
            "output_formats": [],
        })
        self.options_patch.start()
        self.addCleanup(self.options_patch.stop)

    def test_raw_preparation_precedes_logging_snapshot(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, "raw.log")
            options["raw_file"] = "request.txt"

            def parse(_path):
                options.update(log_file=str(path), proxy_auth="user:raw/secret")
                return ["http://example.test/"], "POST", {}, b""

            def run(controller):
                options.update(log_file=None, proxy_auth="user:unrelated")
                controller.resources.logger.info("raw user:raw/secret@proxy.example.test")

            with (
                patch("lib.controller.controller.parse_raw", side_effect=parse),
                patch.object(Controller, "run", new=run),
            ):
                controller = Controller(output=StringIO())
            self.assertIn("raw <redacted>@proxy.example.test", path.read_text())
            self.assertFalse(controller.resources.logger.handlers)

    def test_restored_logging_policy_replaces_current_cli_policy(self):
        with TemporaryDirectory() as directory:
            restored = Path(directory, "restored.log")
            cli = Path(directory, "cli.log")
            options.update(session_file="checkpoint.json", log_file=str(cli))

            def run(controller):
                controller.resources.logger.info("restored user:restored/secret@proxy.example.test")

            with (
                patch("lib.controller.controller.SessionStore") as store,
                patch.object(Controller, "_confirm_session_overwrite"),
                patch.object(Controller, "run", new=run),
                patch.object(Controller, "_restore_session"),
            ):
                store.return_value.load.return_value = SessionSnapshot(
                    run=RunCheckpoint(0), task_checkpoint=TaskCheckpoint(DictionaryCheckpoint((), 0)),
                    options=SessionOptions({"log_file": str(restored), "proxy_auth": "user:restored/secret"}),
                )
                controller = Controller(output=StringIO())
            self.assertFalse(cli.exists())
            self.assertIn("restored <redacted>@proxy.example.test", restored.read_text())
            self.assertFalse(controller.resources.logger.handlers)

    def test_handler_closes_on_execution_and_cleanup_failures(self):
        for owner, phase in (
            (Controller, "run"), (RunResources, "finish_reports"),
            (RunResources, "_close_requester"), (RunResources, "_close_response_stores"),
        ):
            with self.subTest(phase=phase), TemporaryDirectory() as directory:
                path = Path(directory, "run.log")
                options["log_file"] = str(path)
                handlers = []

                def fail(resources):
                    handlers.extend(resources.logger.handlers)
                    resources.logger.info("failure boundary")
                    raise RuntimeError("injected failure")

                def fail_run(controller):
                    fail(controller.resources)

                with (
                    patch.object(Controller, "run"),
                    patch.object(owner, phase, new=fail_run if owner is Controller else fail),
                    self.assertRaisesRegex(RuntimeError, "injected failure"),
                ):
                    Controller(output=StringIO())
                self.assertEqual(len(handlers), 1)
                self.assertIsNone(handlers[0].stream)
                self.assertIn("failure boundary", path.read_text())

    def test_terminal_close_failure_still_closes_logging(self):
        with TemporaryDirectory() as directory:
            options["log_file"] = str(Path(directory, "run.log"))
            handlers = []

            def run(controller):
                handlers.extend(controller.resources.logger.handlers)
                close = controller.resources.interface.close
                self.addCleanup(close)
                controller.resources.interface.close = Mock(side_effect=RuntimeError("terminal failure"))

            with patch.object(Controller, "run", new=run), self.assertRaisesRegex(RuntimeError, "terminal failure"):
                Controller(output=StringIO())
            self.assertEqual(len(handlers), 1)
            self.assertIsNone(handlers[0].stream)

    def test_log_open_failure_reports_error_and_never_runs(self):
        with TemporaryDirectory() as directory:
            options["log_file"] = directory  # A directory cannot be the log file.
            output = StringIO()
            with patch.object(Controller, "run") as run, self.assertRaises(SystemExit) as stopped:
                Controller(output=output)
            self.assertEqual(stopped.exception.code, 1)
            self.assertIn("Couldn't create log file", output.getvalue())
            run.assert_not_called()


class TestLoggingConsumers(TestCase):
    def test_all_fuzzer_variants_forward_the_borrowed_logger_to_scanners(self):
        for fuzzer_class in (Fuzzer, AsyncFuzzer, NativeFuzzer):
            with self.subTest(fuzzer=fuzzer_class.__name__):
                logger = RunLogger()
                self.addCleanup(logger.close)
                fuzzer = fuzzer_class(
                    Mock(backend=None), Mock(), filter_config=FilterConfig(),
                    discovery_config=DiscoveryConfig(extensions=("txt",)),
                    execution_config=ExecutionConfig(), match_callbacks=(),
                    not_found_callbacks=(), error_callbacks=(), logger=logger,
                )
                with patch.object(Scanner, "setup"), patch.object(AsyncScanner, "setup", new_callable=AsyncMock):
                    if fuzzer_class is AsyncFuzzer:
                        asyncio.run(fuzzer.setup_scanners())
                    else:
                        fuzzer.setup_scanners()
                self.assertIs(fuzzer.logger, logger)
                scanners = [
                    scanner for group in fuzzer.filter_state.scanners.values()
                    for scanner in group.values()
                ]
                self.assertTrue(scanners)
                self.assertTrue(all(scanner.logger is logger for scanner in scanners))
