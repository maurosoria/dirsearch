import io
from contextlib import redirect_stderr, redirect_stdout
from unittest import TestCase

from lib.parse.cmdline import parse_arguments


class TestCommandLineHelp(TestCase):
    def _help_output(self, *arguments: str) -> str:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            parse_arguments(list(arguments))

        self.assertEqual(raised.exception.code, 0)
        return output.getvalue()

    def test_common_help_aliases_match(self):
        self.assertEqual(self._help_output("-h"), self._help_output("--help"))

    def test_common_help_uses_explicit_option_selection(self):
        output = self._help_output("-h")

        self.assertIn("--wordlists", output)
        self.assertIn("--threads", output)
        self.assertIn("--output-file", output)
        self.assertIn("--save-response", output)
        self.assertIn("--save-response-jsonl", output)
        self.assertIn("Use '-hh' or '--help-all' to show every option", output)
        self.assertNotIn("--wordlist-backend", output)
        self.assertNotIn("--match-header-regex", output)
        self.assertNotIn("--mysql-url", output)

    def test_full_help_aliases_match(self):
        short_output = self._help_output("-hh")
        long_output = self._help_output("--help-all")

        self.assertEqual(short_output, long_output)
        self.assertIn("--wordlist-backend", short_output)
        self.assertIn("--match-header-regex", short_output)
        self.assertIn("--mysql-url", short_output)
        self.assertIn("--sqlite-commit-batch-size", short_output)
        self.assertIn("--find-backup", short_output)
        self.assertIn(
            "Read request body from file without encoding or newline conversion",
            short_output.replace("\n                        ", " "),
        )
        normalized_output = short_output.replace("\n                        ", " ")
        self.assertIn("may lose up to COUNT-1 recent rows", normalized_output)
        self.assertIn("Maximum recursion depth (0 means unlimited)", normalized_output)
        self.assertIn(
            "Connection timeout in seconds (greater than 0)",
            normalized_output,
        )
        self.assertIn(
            "Delay between requests in seconds (0 or greater)",
            normalized_output,
        )
        self.assertIn(
            "Maximum requests per second (0 means unlimited)",
            normalized_output,
        )
        self.assertIn(
            "Number of retries for failed requests (0 or greater)",
            normalized_output,
        )
        self.assertIn("use quoted '*' for common extensions", normalized_output)

    def test_help_change_does_not_affect_normal_parsing(self):
        parsed = parse_arguments(
            ["-u", "https://example.com", "-w", "words.txt", "-t", "20"]
        )

        self.assertEqual(parsed.urls, ["https://example.com"])
        self.assertEqual(parsed.wordlists, "words.txt")
        self.assertEqual(parsed.thread_count, 20)

    def test_help_alias_can_still_be_an_option_value(self):
        parsed = parse_arguments(["-H", "-hh"])

        self.assertEqual(parsed.headers, ["-hh"])

    def test_shell_expanded_extension_wildcard_is_rejected(self):
        error = io.StringIO()

        with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            parse_arguments(
                [
                    "-u",
                    "https://example.com",
                    "-e",
                    "AGENTS.md",
                    "CHANGELOG.md",
                    "Dockerfile",
                ]
            )

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unexpected positional argument", error.getvalue())
        self.assertIn("quote shell wildcards", error.getvalue())
