# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Publlic License as published by
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

import sys
import time

from threading import Lock
from urllib.parse import urlparse

from lib.utils.data import human_size
from lib.utils.terminal_size import get_terminal_size
from .colors import ColorOutput

if sys.platform in ["win32", "msys"]:
    from thirdparty.colorama.win32 import (FillConsoleOutputCharacter,
                                           GetConsoleScreenBufferInfo,
                                           STDOUT)


class CLIOutput(object):
    def __init__(self, color):
        self.last_length = 0
        self.last_output = ""
        self.last_in_line = False
        self.mutex = Lock()
        self.blacklists = {}
        self.base_path = None
        self.errors = 0
        self.colorizer = ColorOutput(color)

    def in_line(self, string):
        self.erase()
        sys.stdout.write(string)
        sys.stdout.flush()
        self.last_in_line = True

    def erase(self):
        if sys.platform in ["win32", "msys"]:
            csbi = GetConsoleScreenBufferInfo()
            line = "\b" * int(csbi.dwCursorPosition.X)
            sys.stdout.write(line)
            width = csbi.dwCursorPosition.X
            csbi.dwCursorPosition.X = 0
            FillConsoleOutputCharacter(STDOUT, " ", width, csbi.dwCursorPosition)
            sys.stdout.write(line)
            sys.stdout.flush()

        else:
            sys.stdout.write("\033[1K")
            sys.stdout.write("\033[0G")

    def new_line(self, string=''):
        if self.last_in_line:
            self.erase()

        if sys.platform in ["win32", "msys"]:
            sys.stdout.write(string)
            sys.stdout.flush()
            sys.stdout.write("\n")
            sys.stdout.flush()

        else:
            sys.stdout.write(string + "\n")

        sys.stdout.flush()
        self.last_in_line = False
        sys.stdout.flush()

    def status_report(self, path, response, full_url, added_to_queue):
        status = response.status
        content_length = human_size(response.length)

        show_path = "/" + self.base_path + path

        if full_url:
            parsed = urlparse(self.target)
            show_path = "{0}://{1}{2}".format(parsed.scheme, parsed.netloc, show_path)

        message = "[{0}] {1} - {2} - {3}".format(
            time.strftime("%H:%M:%S"),
            status,
            content_length.rjust(6, " "),
            show_path,
        )

        if status in [200, 201, 204]:
            message = self.colorizer.color(message, fore="green")

        elif status == 401:
            message = self.colorizer.color(message, fore="yellow")

        elif status == 403:
            message = self.colorizer.color(message, fore="blue")

        elif status in range(500, 600):
            message = self.colorizer.color(message, fore="red")

        elif status in range(300, 400):
            message = self.colorizer.color(message, fore="cyan")

        else:
            message = self.colorizer.color(message, fore="magenta")

        if response.redirect:
            message += "  ->  {0}".format(response.redirect)
        if added_to_queue:
            message += "     (Added to queue)"

        with self.mutex:
            self.new_line(message)

    def last_path(self, index, length, current_job, all_jobs, rate):
        percentage = int(index / length * 100)
        progress = self.colorizer.color("#", fore="cyan", bright=True) * int(percentage / 5)
        progress += " " * (20 - int(percentage / 5))

        message = "[{0}] {1}% {2} {3}/s       ".format(
            progress,
            percentage,
            "{}/{}".format(index, length).rjust(12, " "),
            str(rate).rjust(9, " "),
        )

        message += "{0}:{1}/{2}  ".format(
            self.colorizer.color("job", fore="green", bright=True),
            current_job,
            all_jobs
        )

        message += "{0}:{1}".format(
            self.colorizer.color("errors", fore="red", bright=True),
            self.errors
        )

        l, _ = get_terminal_size()
        if len(self.colorizer.clean_color(message)) >= l:
            return

        with self.mutex:
            self.in_line(message)

    def add_connection_error(self):
        self.errors += 1

    def error(self, reason):
        with self.mutex:
            stripped = reason.strip()
            message = "\n" if reason.startswith("\n") else ""
            message += self.colorizer.color(stripped, fore="white", back="red", bright=True)

            self.new_line(message)

    def warning(self, message):
        with self.mutex:
            message = self.colorizer.color(message, fore="yellow", bright=True)
            self.new_line(message)

    def header(self, message):
        message = self.colorizer.color(message, fore="magenta", bright=True)
        self.new_line(message)

    def add_config(self, key, value, msg):
        l, _ = get_terminal_size()
        particle = self.colorizer.color(key + ": ", fore="yellow", bright=True)
        particle += self.colorizer.color(value, fore="cyan", bright=True)

        if len(self.colorizer.clean_color(msg)) == 0:
            separator = ""
        elif len(self.colorizer.clean_color(msg.splitlines()[-1] + particle)) + 3 > l:
            separator = "\n"
        else:
            separator = self.colorizer.color(" | ", fore="magenta", bright=True)

        return separator + particle

    def config(
        self,
        extensions,
        prefixes,
        suffixes,
        threads,
        wordlist_size,
        method,
    ):

        config = self.add_config("Extensions", extensions, "")

        if prefixes:
            config += self.add_config("Prefixes", prefixes, config)

        if suffixes:
            config += self.add_config("Suffixes", suffixes, config)

        config += self.add_config("HTTP method", method.upper(), config)
        config += self.add_config("Threads", threads, config)
        config += self.add_config("Wordlist size", wordlist_size, config)

        self.new_line(config)

    def set_target(self, target, scheme):
        if not target.startswith(("http://", "https://")) and "://" not in target:
            target = "{0}://{1}".format(scheme, target)

        self.target = target

        header = "\n" + self.add_config("Target", target, "") + "\n"
        header = self.colorizer.color(header, bright=True)

        self.new_line(header)

    def output_file(self, target):
        self.new_line("\nOutput File: {0}".format(target))

    def error_log_file(self, target):
        self.new_line("\nError Log: {0}".format(target))

    def debug(self, info):
        with self.mutex:
            line = "[{0}] - {1}".format(time.strftime("%H:%M:%S"), info)
            self.new_line(line)
