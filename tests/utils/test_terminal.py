# -*- coding: utf-8 -*-

import os
import stat
from io import StringIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from lib.core.data import options
from lib.view.terminal import CLI, safe_display_text


class TestTerminalOutput(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        options["color"] = True
        options["verbose"] = False

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def test_safe_display_text_strips_controls_and_truncates(self):
        value = "admin/\u202eexe.txt/" + ("👨‍👩‍👧‍👦" * 500)
        rendered = safe_display_text(value)

        self.assertNotIn("\u202e", rendered)
        self.assertNotIn("\u200d", rendered)
        self.assertLessEqual(len(rendered), 240)

    def test_status_report_sanitizes_path_and_redirect(self):
        family = "👨‍👩‍👧‍👦" * 500
        response = SimpleNamespace(
            datetime="2026-05-29 12:00:00",
            status=200,
            size="1B",
            full_path=f"admin/\u202eexe.txt/{family}",
            url=f"http://example.com/admin/\u202eexe.txt/{family}",
            redirect=f"/next/\u202eexe.txt/{family}",
            history=[f"http://example.com/old/\u202eexe.txt/{family}"],
            elapsed=0,
            type="text/plain",
        )
        cli = CLI()
        self.addCleanup(cli.close)

        with patch.object(cli, "new_line") as new_line:
            cli.status_report(response, False)

        message = new_line.call_args.args[0]
        self.assertNotIn("\u202e", message)
        self.assertNotIn("\u200d", message)
        self.assertLess(len(message), 900)

    def test_output_history_rolls_to_disk_without_losing_text(self):
        with (
            patch("lib.view.terminal.TERMINAL_HISTORY_MEMORY_LIMIT", 32),
            patch("lib.view.terminal.sys.stdout", new_callable=StringIO),
        ):
            cli = CLI()
            self.addCleanup(cli.close)
            cli.new_line("café\r\nfirst")
            cli.new_line("β" * 32)
            first_read = cli.buffer
            cli.new_line("last")
            cli.new_line("not retained", do_save=False)

        self.assertTrue(cli._output_buffer._rolled)
        self.assertEqual(first_read, "café\r\nfirst\n" + ("β" * 32) + "\n")
        self.assertEqual(cli.buffer, first_read + "last\n")
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(os.fstat(cli._output_buffer.fileno()).st_mode),
                0o600,
            )
