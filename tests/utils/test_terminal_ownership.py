"""Presentation policy must not leak between terminal instances."""

from types import SimpleNamespace
from io import StringIO
import subprocess
import sys
import threading
from unittest import TestCase
from unittest.mock import patch

from lib.core.data import options
from lib.core.terminal_config import TerminalConfig
from lib.view.colors import BACK_COLORS, FORE_COLORS, STYLES, clean_color
from lib.view.terminal import CLI, EmptyCLI, QuietCLI, create_terminal


def response_for(status=200):
    return SimpleNamespace(
        datetime="2026-01-01 12:00:00", status=status, size="1B",
        url="http://example.test/item", full_path="item",
        elapsed=0.123, type="text/plain", redirect="", history=[],
    )


class TestTerminalOwnership(TestCase):
    def make_terminal(self, **settings):
        terminal = CLI(TerminalConfig(**settings), stream=StringIO())
        self.addCleanup(terminal.close)
        return terminal

    def test_plain_terminal_does_not_disable_another_terminals_colors(self):
        colored = self.make_terminal(color=True)
        plain = self.make_terminal(color=False)
        with (
            patch.object(colored, "new_line") as colored_line,
            patch.object(plain, "new_line") as plain_line,
        ):
            colored.header("colored")
            plain.header("plain")
        self.assertIn("\x1b[35m", colored_line.call_args.args[0])
        self.assertEqual(plain_line.call_args.args[0], "plain")

    def test_verbose_policy_is_captured_by_the_instance(self):
        verbose = self.make_terminal(color=False, verbose=True)
        with patch.dict(options, verbose=False), patch.object(verbose, "new_line") as line:
            verbose.status_report(response_for(), False)
        self.assertIn("(123ms, text/plain)", line.call_args.args[0])

    def test_configuration_summary_never_reads_global_options(self):
        terminal = self.make_terminal(
            color=False, extensions=["html"], prefixes=["api/"], suffixes=["~"],
            method="POST", concurrency=7,
        )
        with patch.dict(options, {}, clear=True):
            terminal.print_config(12)
        self.assertIn("Extensions: html", terminal.buffer)
        self.assertIn("Prefixes: api/", terminal.buffer)
        self.assertIn("Suffixes: ~", terminal.buffer)
        self.assertIn("HTTP method: POST", terminal.buffer)
        self.assertIn("Threads: 7", terminal.buffer)
        self.assertIn("Wordlist size: 12", terminal.buffer)

    def test_color_tables_are_read_only(self):
        for table in (BACK_COLORS, FORE_COLORS, STYLES):
            with self.subTest(table=table), self.assertRaises(TypeError):
                table["new-style"] = "value"

    def test_status_colors_preserve_existing_mapping(self):
        terminal = self.make_terminal(color=True)
        for status, color in (
            (200, "green"), (201, "green"), (204, "green"),
            (401, "yellow"), (403, "blue"), (500, "red"),
            (302, "cyan"), (404, "magenta"),
        ):
            with self.subTest(status=status), patch.object(terminal, "new_line") as line:
                terminal.status_report(response_for(status), False)
                self.assertTrue(line.call_args.args[0].startswith(FORE_COLORS[color]))

    def test_distinct_streams_and_history_do_not_share_output(self):
        first_stream, second_stream = StringIO(), StringIO()
        first = CLI(TerminalConfig(color=False), stream=first_stream)
        second = CLI(TerminalConfig(color=False), stream=second_stream)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        first.new_line("first")
        second.new_line("second")
        first.new_line("transient", do_save=False)
        self.assertEqual(first_stream.getvalue(), "first\ntransient\n")
        self.assertEqual(second_stream.getvalue(), "second\n")
        self.assertEqual(first.buffer, "first\n")
        self.assertEqual(second.buffer, "second\n")

    def test_non_tty_output_strips_ansi_but_history_keeps_rendered_text(self):
        stream = StringIO()
        terminal = CLI(TerminalConfig(color=True), stream=stream)
        self.addCleanup(terminal.close)
        terminal.header("title")
        self.assertEqual(stream.getvalue(), "title\n")
        self.assertEqual(clean_color(terminal.buffer), "title\n")
        self.assertIn("\x1b[35m", terminal.buffer)

    def test_close_releases_history_but_never_closes_the_borrowed_stream(self):
        stream = StringIO()
        terminal = CLI(TerminalConfig(), stream=stream)
        terminal.close()
        terminal.close()
        self.assertTrue(terminal._output_buffer.closed)
        self.assertFalse(stream.closed)
        for write in (terminal.new_line, terminal.in_line):
            with self.subTest(write=write), self.assertRaisesRegex(ValueError, "closed"):
                write("late output")
        self.assertEqual(stream.getvalue(), "")

    def test_factory_modes_and_quiet_full_url_behavior(self):
        for config, expected_type in (
            (TerminalConfig(), CLI),
            (TerminalConfig(quiet=True), QuietCLI),
            (TerminalConfig(disabled=True), EmptyCLI),
            (TerminalConfig(disabled=True, quiet=True), EmptyCLI),
        ):
            with self.subTest(config=config):
                stream = StringIO()
                terminal = create_terminal(config, stream=stream)
                self.addCleanup(terminal.close)
                self.assertIs(type(terminal), expected_type)
                terminal.header("banner")
                terminal.warning("warning")
                terminal.status_report(response_for(), False)
                rendered = stream.getvalue()
                if expected_type is EmptyCLI:
                    self.assertEqual(rendered, "")
                elif expected_type is QuietCLI:
                    self.assertEqual(rendered, "[12:00:00] 200 -     1B - http://example.test/item\n")
                else:
                    self.assertIn("banner\nwarning\n", rendered)
                    self.assertIn(" - /item\n", rendered)

    def test_stream_failure_releases_the_terminal_lock(self):
        stream = StringIO()
        terminal = CLI(TerminalConfig(), stream=stream)
        # Teardown must not block if the regression leaves the lock acquired.
        self.addCleanup(terminal._output_buffer.close)
        with patch.object(stream, "write", side_effect=OSError("write failed")):
            with self.assertRaisesRegex(OSError, "write failed"):
                terminal.new_line("failed")
        self.assertTrue(terminal._operation_lock.acquire(timeout=1))
        terminal._operation_lock.release()
        terminal.new_line("recovered")
        self.assertEqual(terminal.buffer, "recovered\n")

    def test_slow_stream_does_not_block_another_terminal(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()

        class SlowStream(StringIO):
            def write(self, text):
                entered.set()
                if not release.wait(timeout=5):
                    raise RuntimeError("stream was not released")
                return super().write(text)

        first = CLI(TerminalConfig(), stream=SlowStream())
        second_stream = StringIO()
        second = CLI(TerminalConfig(), stream=second_stream)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        errors = []

        def write(terminal, done=None):
            try:
                terminal.new_line("message")
            except Exception as error:
                errors.append(error)
            finally:
                if done is not None:
                    done.set()

        first_thread = threading.Thread(target=write, args=(first,))
        second_thread = threading.Thread(target=write, args=(second, finished))
        first_thread.start()
        try:
            self.assertTrue(entered.wait(timeout=2))
            second_thread.start()
            self.assertTrue(finished.wait(timeout=2))
        finally:
            release.set()
            first_thread.join(timeout=2)
            if second_thread.ident is not None:
                second_thread.join(timeout=2)
        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(second_stream.getvalue(), "message\n")

    def test_import_does_not_create_buffers_or_replace_process_streams(self):
        script = """
import sys
from unittest.mock import patch
original = sys.stdout, sys.stderr
with patch('tempfile.SpooledTemporaryFile', side_effect=AssertionError('buffer allocated')):
    import lib.view.terminal
    import lib.controller.session
    import lib.controller.controller
assert (sys.stdout, sys.stderr) == original
"""
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
