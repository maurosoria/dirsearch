import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from lib.controller.controller import Controller
from lib.controller.session import SessionStore
from lib.core.data import options as runtime_options
from lib.core.options import parse_options


class TestRegexOptionValidation(TestCase):
    BASE_ARGUMENTS = ["dirsearch.py", "--wordlist-status", "-e", "php"]
    EXCLUSION_OPTIONS = (
        ("--exclude-regex", "exclude-regex", "exclude_regex"),
        ("--exclude-redirect", "exclude-redirect", "exclude_redirect"),
    )
    INVALID_PATTERNS = ("[", "(", "*", "trailing\\")

    def assert_rejected(self, arguments, option_name):
        output = io.StringIO()
        with (
            patch.object(sys, "argv", [*self.BASE_ARGUMENTS, *arguments]),
            redirect_stdout(output),
            self.assertRaises(SystemExit) as raised,
        ):
            parse_options()

        self.assertEqual(raised.exception.code, 1)
        self.assertTrue(
            output.getvalue().startswith(
                f"Invalid --{option_name} regular expression:"
            ),
            output.getvalue(),
        )

    def test_invalid_cli_exclusion_regexes_are_rejected(self):
        for cli_option, option_name, _ in self.EXCLUSION_OPTIONS:
            for pattern in self.INVALID_PATTERNS:
                with self.subTest(cli_option=cli_option, pattern=pattern):
                    self.assert_rejected((cli_option, pattern), option_name)

    def test_invalid_config_exclusion_regexes_are_rejected(self):
        for _, option_name, _ in self.EXCLUSION_OPTIONS:
            with self.subTest(option_name=option_name), tempfile.TemporaryDirectory() as directory:
                config_path = Path(directory, "config.ini")
                config_path.write_text(
                    f"[general]\n{option_name} = [\n",
                    encoding="utf-8",
                )
                self.assert_rejected(("--config", str(config_path)), option_name)

    def test_invalid_restored_session_regexes_are_rejected(self):
        for _, option_name, option_key in self.EXCLUSION_OPTIONS:
            with self.subTest(option_key=option_key):
                output = io.StringIO()
                controller = object.__new__(Controller)
                payload = {"options": {option_key: "["}}

                with (
                    patch.dict(runtime_options),
                    patch.object(SessionStore, "load", return_value=payload),
                    redirect_stdout(output),
                    self.assertRaises(SystemExit) as raised,
                ):
                    controller._import("session.json")

                self.assertEqual(raised.exception.code, 1)
                self.assertTrue(
                    output.getvalue().startswith(
                        f"Invalid --{option_name} regular expression:"
                    ),
                    output.getvalue(),
                )

    def test_valid_exclusion_regexes_are_preserved(self):
        arguments = (
            "--exclude-regex",
            r"not\s+found",
            "--exclude-redirect",
            r"/login(?:\?.*)?$",
        )

        with patch.object(sys, "argv", [*self.BASE_ARGUMENTS, *arguments]):
            parsed = parse_options()

        self.assertEqual(parsed["exclude_regex"], r"not\s+found")
        self.assertEqual(parsed["exclude_redirect"], r"/login(?:\?.*)?$")
