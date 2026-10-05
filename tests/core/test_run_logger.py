"""Owned log destinations, redaction snapshots and late-write fencing."""

import logging
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.core.log_config import LogConfig
from lib.core.logger import RunLogger


class TestRunLogger(TestCase):
    def make_logger(self, config=LogConfig()):
        logger = RunLogger(config)
        self.addCleanup(logger.close)
        return logger

    def test_policy_is_immutable_detached_and_hides_credentials_in_repr(self):
        values = {"log_file": "run.log", "log_file_size": 256, "proxy_auth": "user:secret"}
        config = LogConfig.from_options(values)
        values.update(log_file="other.log", proxy_auth="other:secret")
        self.assertEqual(config.file_path, "run.log")
        self.assertEqual(config.max_bytes, 256)
        self.assertEqual(config.proxy_auth, "user:secret")
        self.assertNotIn("user:secret", repr(config))
        with self.assertRaises(FrozenInstanceError):
            config.max_bytes = 1024

    def test_two_runs_keep_destinations_redaction_and_lifetimes_separate(self):
        directory = self.enterContext(TemporaryDirectory())
        first_path = Path(directory, "first.log")
        second_path = Path(directory, "second.log")
        first = self.make_logger(LogConfig(str(first_path), proxy_auth="user:first/secret"))
        first.info("first-before")
        second = self.make_logger(LogConfig(str(second_path), proxy_auth="user:second/secret"))
        first.info("first-after user:first/secret@proxy.example.test")
        second.info("second-before user:second/secret@proxy.example.test")
        first.close()
        first.close()
        first.info("closed-record")
        second.info("second-after")
        second.close()

        first_text = first_path.read_text()
        second_text = second_path.read_text()
        self.assertIn("first-before", first_text)
        self.assertIn("first-after <redacted>@proxy.example.test", first_text)
        self.assertNotIn("second", first_text)
        self.assertNotIn("closed-record", first_text)
        self.assertNotIn("first", second_text)
        self.assertIn("second-before <redacted>@proxy.example.test", second_text)
        self.assertIn("second-after", second_text)
        self.assertFalse(first.handlers)
        self.assertFalse(second.handlers)

    def test_no_file_is_disabled_and_no_run_propagates_to_host_logging(self):
        directory = self.enterContext(TemporaryDirectory())
        disabled = self.make_logger()
        enabled = self.make_logger(LogConfig(str(Path(directory, "run.log"))))
        host_handler = Mock(level=logging.DEBUG)
        with patch.object(logging.root, "handlers", [host_handler]):
            disabled.error("no output")
            enabled.error("only the owned file")
        self.assertTrue(disabled.disabled)
        self.assertFalse(disabled.handlers)
        self.assertFalse(enabled.propagate)
        host_handler.handle.assert_not_called()
        self.assertNotIn(enabled, logging.Logger.manager.loggerDict.values())

    def test_a_record_already_dispatched_before_close_cannot_reopen_the_file(self):
        directory = self.enterContext(TemporaryDirectory())
        path = Path(directory, "run.log")
        logger = self.make_logger(LogConfig(str(path)))
        handler = logger.handlers[0]
        entered = Event()
        release = Event()
        errors = []

        def hold_record(record):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("record was not released")
            return True

        def write():
            try:
                logger.info("late record")
            except Exception as error:
                errors.append(error)

        handler.addFilter(hold_record)
        writer = Thread(target=write)
        writer.start()
        try:
            self.assertTrue(entered.wait(5))
            logger.close()
            self.assertIsNone(handler.stream)
        finally:
            release.set()
            writer.join(5)
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(path.read_bytes(), b"")
        self.assertIsNone(handler.stream)

    def test_open_failure_does_not_close_another_run(self):
        directory = self.enterContext(TemporaryDirectory())
        path = Path(directory, "run.log")
        logger = self.make_logger(LogConfig(str(path)))
        with self.assertRaises(OSError):
            RunLogger(LogConfig(str(Path(directory, "missing", "run.log"))))
        logger.info("still active")
        logger.close()
        self.assertIn("still active", path.read_text())
