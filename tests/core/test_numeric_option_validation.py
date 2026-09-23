# -*- coding: utf-8 -*-

import io
import sys
import tempfile

from contextlib import redirect_stderr
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from lib.controller.controller import Controller
from lib.controller.session import SessionStore
from lib.core.data import options as runtime_options
from lib.core.options import parse_options


class TestNumericOptionValidation(TestCase):
    BASE_ARGUMENTS = ["dirsearch.py", "--wordlist-status", "-e", "php"]

    def parse(self, *arguments):
        with patch.object(sys, "argv", [*self.BASE_ARGUMENTS, *arguments]):
            return parse_options()

    def assert_rejected(self, arguments, message):
        output = io.StringIO()
        with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
            self.parse(*arguments)

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(output.getvalue(), message + "\n")

    def test_invalid_cli_values_are_rejected(self):
        cases = (
            (("--timeout", "0"), "--timeout must be finite and greater than zero"),
            (("--timeout", "-1"), "--timeout must be finite and greater than zero"),
            (("--timeout", "nan"), "--timeout must be finite and greater than zero"),
            (("--timeout", "inf"), "--timeout must be finite and greater than zero"),
            (("--delay", "-1"), "--delay must be finite and zero or greater"),
            (("--delay", "nan"), "--delay must be finite and zero or greater"),
            (("--delay", "inf"), "--delay must be finite and zero or greater"),
            (("--retries", "-1"), "--retries must be zero or greater"),
            (("--max-rate", "-1"), "--max-rate must be zero or greater"),
            (
                ("--max-recursion-depth", "-1"),
                "--max-recursion-depth must be zero or greater",
            ),
        )

        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                self.assert_rejected(arguments, message)

    def test_invalid_config_values_are_rejected(self):
        cases = (
            (
                "[connection]\ntimeout = 0\n",
                "--timeout must be finite and greater than zero",
            ),
            (
                "[connection]\ntimeout = nan\n",
                "--timeout must be finite and greater than zero",
            ),
            (
                "[connection]\ndelay = -1\n",
                "--delay must be finite and zero or greater",
            ),
            (
                "[connection]\ndelay = inf\n",
                "--delay must be finite and zero or greater",
            ),
            (
                "[connection]\nmax-retries = -1\n",
                "--retries must be zero or greater",
            ),
            (
                "[connection]\nmax-rate = -1\n",
                "--max-rate must be zero or greater",
            ),
            (
                "[general]\nmax-recursion-depth = -1\n",
                "--max-recursion-depth must be zero or greater",
            ),
        )

        for config_text, message in cases:
            with self.subTest(config_text=config_text), tempfile.TemporaryDirectory() as directory:
                config_path = Path(directory) / "config.ini"
                config_path.write_text(config_text, encoding="utf-8")
                self.assert_rejected(("--config", str(config_path)), message)

    def test_valid_boundaries_remain_accepted(self):
        options = self.parse(
            "--timeout",
            "0.001",
            "--delay",
            "0",
            "--retries",
            "0",
            "--max-rate",
            "0",
            "--max-recursion-depth",
            "0",
        )

        self.assertEqual(options["timeout"], 0.001)
        self.assertEqual(options["delay"], 0.0)
        self.assertEqual(options["max_retries"], 0)
        self.assertEqual(options["max_rate"], 0)
        self.assertEqual(options["recursion_depth"], 0)

    def test_invalid_restored_session_value_is_rejected(self):
        payload = {"options": {"delay": -1}}
        output = io.StringIO()
        controller = object.__new__(Controller)

        with (
            patch.dict(runtime_options),
            patch.object(SessionStore, "load", return_value=payload),
            redirect_stderr(output),
            self.assertRaises(SystemExit) as raised,
        ):
            controller._import("session.json")

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(
            output.getvalue(),
            "--delay must be finite and zero or greater\n",
        )
