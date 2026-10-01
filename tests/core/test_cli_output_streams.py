import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from lib.controller.session import SessionStore
from lib.core.options import parse_options


class TestCLIOutputStreams(TestCase):
    def test_validation_errors_do_not_pollute_stdout(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        arguments = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--timeout",
            "0",
        ]

        with (
            patch.object(sys, "argv", arguments),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            parse_options()

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            stderr.getvalue(),
            "--timeout must be finite and greater than zero\n",
        )

    def test_warnings_do_not_pollute_stdout(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory, "empty.ini")
            config_path.write_text("", encoding="utf-8")
            arguments = [
                "dirsearch.py",
                "--wordlist-status",
                "--config",
                str(config_path),
            ]

            with (
                patch.object(sys, "argv", arguments),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                parse_options()

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "WARNING: No extension was specified!\n")

    def test_multiline_errors_stay_together_on_stderr(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        arguments = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--wordlist-categories",
            "unknown-category",
        ]

        with (
            patch.object(sys, "argv", arguments),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            parse_options()

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(
            stderr.getvalue().startswith(
                "Unknown wordlist categories: unknown-category\n"
                "Available categories: "
            )
        )

    def test_requested_session_listing_remains_on_stdout(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        arguments = ["dirsearch.py", "--list-sessions"]

        with (
            patch.object(sys, "argv", arguments),
            patch.object(SessionStore, "list_sessions", return_value=[]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            parse_options()

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("No resumable sessions found", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_session_listing_reports_bad_checkpoint_without_crashing(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            session_dir = Path(directory, "damaged")
            session_dir.mkdir()
            checkpoint = session_dir / SessionStore.CHECKPOINT_FILE
            checkpoint.write_text(json.dumps([]), encoding="utf-8")
            arguments = [
                "dirsearch.py",
                "--list-sessions",
                "--sessions-dir",
                directory,
            ]

            with (
                patch.object(sys, "argv", arguments),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                parse_options()

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("No resumable sessions found", stdout.getvalue())
        self.assertIn("Skipping invalid session", stderr.getvalue())
        self.assertIn("Session JSON root must be an object", stderr.getvalue())
