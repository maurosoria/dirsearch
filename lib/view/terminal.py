# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

import shutil
import sys
import tempfile
import threading
import unicodedata
from typing import TextIO

from colorama import AnsiToWin32

from lib.core.decorators import locked
from lib.core.settings import IS_WINDOWS
from lib.core.terminal_config import TerminalConfig
from lib.view.colors import set_color, clean_color


if IS_WINDOWS:
    from colorama.win32 import (
        FillConsoleOutputCharacter,
        GetConsoleScreenBufferInfo,
        STDOUT,
    )


MAX_DISPLAY_TEXT_LENGTH = 240
TERMINAL_HISTORY_MEMORY_LIMIT = 1024 * 1024


def safe_display_text(value, max_length=MAX_DISPLAY_TEXT_LENGTH):
    text = str(value)
    text = "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("C")
    )

    if len(text) > max_length:
        return text[:max_length - 3] + "..."

    return text


class CLI:
    def __init__(self, config: TerminalConfig, *, stream: TextIO | None = None):
        self.config = config
        # Colorama adapts only this borrowed stream; never replace sys.stdout.
        output = sys.stdout if stream is None else stream
        adapter = AnsiToWin32(output)
        self._stream = adapter.stream if adapter.should_wrap() else output
        self._operation_lock = threading.Lock()
        self.last_in_line = False
        self._output_buffer = tempfile.SpooledTemporaryFile(
            max_size=TERMINAL_HISTORY_MEMORY_LIMIT,
            mode="w+",
            encoding="utf-8",
            newline="",
        )

    def _color(self, message, fore="none", back="none", style="normal"):
        return set_color(message, fore, back, style, enabled=self.config.color)

    @property
    @locked
    def buffer(self):
        position = self._output_buffer.tell()
        self._output_buffer.seek(0)
        content = self._output_buffer.read()
        self._output_buffer.seek(position)

        return content

    @locked
    def close(self):
        """Close owned history, not the caller's output stream; safe to repeat."""
        self._output_buffer.close()

    def erase(self):
        if not self._stream.isatty():
            return
        if IS_WINDOWS:
            csbi = GetConsoleScreenBufferInfo()
            line = "\b" * int(csbi.dwCursorPosition.X)
            self._stream.write(line)
            width = csbi.dwCursorPosition.X
            csbi.dwCursorPosition.X = 0
            FillConsoleOutputCharacter(STDOUT, " ", width, csbi.dwCursorPosition)
            self._stream.write(line)
            self._stream.flush()

        else:
            self._stream.write("\033[1K")
            self._stream.write("\033[0G")

    @locked
    def in_line(self, string):
        if self._output_buffer.closed:
            raise ValueError("Terminal is closed")
        self.erase()
        self._stream.write(string)
        self._stream.flush()
        self.last_in_line = True

    @locked
    def new_line(self, string="", do_save=True):
        if self._output_buffer.closed:
            raise ValueError("Terminal is closed")
        if self.last_in_line:
            self.erase()

        if IS_WINDOWS:
            self._stream.write(string)
            self._stream.flush()
            self._stream.write("\n")
            self._stream.flush()

        else:
            self._stream.write(string + "\n")

        self._stream.flush()
        self.last_in_line = False
        self._stream.flush()

        if do_save:
            self._output_buffer.write(string)
            self._output_buffer.write("\n")

    def status_report(self, response, full_url):
        target = safe_display_text(response.url if full_url else "/" + response.full_path)
        # Get time from datetime string
        time = response.datetime.split()[1]
        message = f"[{time}] {response.status} - {response.size.rjust(6, ' ')} - {target}"

        if self.config.verbose:
            elapsed_ms = int(response.elapsed * 1000) if response.elapsed else 0
            content_type = response.type
            message += f"  ({elapsed_ms}ms, {content_type})"

        if response.status in (200, 201, 204):
            message = self._color(message, fore="green")
        elif response.status == 401:
            message = self._color(message, fore="yellow")
        elif response.status == 403:
            message = self._color(message, fore="blue")
        elif response.status in range(500, 600):
            message = self._color(message, fore="red")
        elif response.status in range(300, 400):
            message = self._color(message, fore="cyan")
        else:
            message = self._color(message, fore="magenta")

        if response.redirect:
            message += f"  ->  {safe_display_text(response.redirect)}"

        for redirect in response.history:
            message += f"\n-->  {safe_display_text(redirect)}"

        self.new_line(message)

    def last_path(self, index, length, current_job, all_jobs, rate, errors):
        percentage = int(index / length * 100)
        task = self._color("#", fore="cyan", style="bright") * int(percentage / 5)
        task += " " * (20 - int(percentage / 5))
        progress = f"{index}/{length}"

        grean_job = self._color("job", fore="green", style="bright")
        jobs = f"{grean_job}:{current_job}/{all_jobs}"

        red_error = self._color("errors", fore="red", style="bright")
        errors = f"{red_error}:{errors}"

        progress_bar = f"[{task}] {str(percentage).rjust(2, chr(32))}% "
        progress_bar += f"{progress.rjust(12, chr(32))} "
        progress_bar += f"{str(rate).rjust(9, chr(32))}/s       "
        progress_bar += f"{jobs.ljust(21, chr(32))} {errors}"

        if len(clean_color(progress_bar)) >= shutil.get_terminal_size()[0]:
            return

        self.in_line(progress_bar)

    def new_directories(self, directories):
        message = self._color(
            f"Added to the queue: {safe_display_text(', '.join(directories))}",
            fore="yellow",
            style="dim",
        )
        self.new_line(message)

    def error(self, reason):
        message = self._color(reason, fore="white", back="red", style="bright")
        self.new_line("\n" + message)

    def warning(self, message, do_save=True):
        message = self._color(message, fore="yellow", style="bright")
        self.new_line(message, do_save=do_save)

    def header(self, message):
        message = self._color(message, fore="magenta", style="bright")
        self.new_line(message)

    def print_header(self, headers):
        msg = []

        for key, value in headers.items():
            new = self._color(key + ": ", fore="yellow", style="bright")
            new += self._color(value, fore="cyan", style="bright")

            if (
                not msg
                or len(clean_color(msg[-1]) + clean_color(new)) + 3
                >= shutil.get_terminal_size()[0]
            ):
                msg.append("")
            else:
                msg[-1] += self._color(" | ", fore="magenta", style="bright")

            msg[-1] += new

        self.new_line("\n".join(msg))

    def print_config(self, wordlist_size):

        config = {}
        config["Extensions"] = ", ".join(self.config.extensions)

        if self.config.prefixes:
            config["Prefixes"] = ", ".join(self.config.prefixes)
        if self.config.suffixes:
            config["Suffixes"] = ", ".join(self.config.suffixes)

        config.update({
            "HTTP method": self.config.method,
            "Threads": str(self.config.concurrency),
            "Wordlist size": str(wordlist_size),
        })

        self.print_header(config)

    def target(self, target):
        self.new_line()
        self.print_header({"Target": target})

    def log_file(self, file):
        self.new_line(f"\nLog File: {file}")


class QuietCLI(CLI):
    def status_report(self, response, full_url):
        super().status_report(response, True)

    def last_path(*args):
        pass

    def new_directories(*args):
        pass

    def warning(*args, **kwargs):
        pass

    def header(*args):
        pass

    def print_config(*args):
        pass

    def target(*args):
        pass

    def log_file(*args):
        pass


class EmptyCLI(QuietCLI):
    def status_report(*args):
        pass

    def error(*args):
        pass


def create_terminal(config: TerminalConfig, *, stream: TextIO | None = None) -> CLI:
    """Create one explicitly owned output mode; importing this module creates none."""
    terminal_type = EmptyCLI if config.disabled else QuietCLI if config.quiet else CLI
    return terminal_type(config, stream=stream)
