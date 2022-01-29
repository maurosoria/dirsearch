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
import shutil

from threading import Lock

from lib.core.settings import IS_WINDOWS
from lib.utils.fmt import human_size
from lib.output.colors import ColorOutput

if IS_WINDOWS:
    from thirdparty.colorama.win32 import (FillConsoleOutputCharacter,
                                           GetConsoleScreenBufferInfo,
                                           STDOUT)


class Output(object):
    def __init__(self, colors):
        self.last_length = 0
        self.last_in_line = False
        self.buffer = ''
        self.mutex = Lock()
        self.blacklists = {}
        self.url = None
        self.errors = 0
        self.colorizer = ColorOutput(colors)

    def in_line(self, string):
        self.erase()
        sys.stdout.write(string)
        sys.stdout.flush()
        self.last_in_line = True

    def erase(self):
        if IS_WINDOWS:
            csbi = GetConsoleScreenBufferInfo()
            line = '\b' * int(csbi.dwCursorPosition.X)
            sys.stdout.write(line)
            width = csbi.dwCursorPosition.X
            csbi.dwCursorPosition.X = 0
            FillConsoleOutputCharacter(STDOUT, ' ', width, csbi.dwCursorPosition)
            sys.stdout.write(line)
            sys.stdout.flush()

        else:
            sys.stdout.write("\033[1K")
            sys.stdout.write("\033[0G")

    def new_line(self, string='', save=True):
        if save:
            self.buffer += string
            self.buffer += '\n'

        if self.last_in_line:
            self.erase()

        if IS_WINDOWS:
            sys.stdout.write(string)
            sys.stdout.flush()
            sys.stdout.write('\n')
            sys.stdout.flush()

        else:
            sys.stdout.write(string + '\n')

        sys.stdout.flush()
        self.last_in_line = False
        sys.stdout.flush()

    def status_report(self, response, full_url, added_to_queue):
        status = response.status
        content_length = human_size(response.length)
        show_path = self.url + response.path if full_url else response.path
        message = "[{0}] {1} - {2} - {3}".format(
            time.strftime("%H:%M:%S"),
            status,
            content_length.rjust(6, ' '),
            show_path,
        )

        if status in (200, 201, 204):
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

        for redirect in response.history:
            message += "\n-->  {0}".format(redirect)

        with self.mutex:
            self.new_line(message)

    def last_path(self, index, length, current_job, all_jobs, rate):
        percentage = int(index / length * 100)
        task = self.colorizer.color('#', fore="cyan", bright=True) * int(percentage / 5)
        task += ' ' * (20 - int(percentage / 5))
        progress = "{}/{}".format(index, length)

        jobs = "{0}:{1}/{2}".format(
            self.colorizer.color("job", fore="green", bright=True),
            current_job,
            all_jobs
        )

        errors = "{0}:{1}".format(
            self.colorizer.color("errors", fore="red", bright=True),
            self.errors
        )

        progress_bar = "[{0}] {1}% {2} {3}/s       {4} {5}".format(
            task,
            str(percentage).rjust(2, ' '),
            progress.rjust(12, ' '),
            str(rate).rjust(9, ' '),
            jobs.ljust(21, ' '),
            errors
        )

        if len(self.colorizer.clean(progress_bar)) >= shutil.get_terminal_size()[0]:
            return

        with self.mutex:
            self.in_line(progress_bar)

    def add_connection_error(self):
        self.errors += 1

    def error(self, reason):
        with self.mutex:
            stripped = reason.strip()
            message = self.colorizer.color(stripped, fore="white", back="red", bright=True)

            self.new_line('\n' + message)

    def warning(self, message, save=True):
        with self.mutex:
            message = self.colorizer.color(message, fore="yellow", bright=True)
            self.new_line(message, save=save)

    def header(self, message):
        message = self.colorizer.color(message, fore="magenta", bright=True)
        self.new_line(message, save=False)

    def print_header(self, entries, save=False):
        msg = ''

        for key, value in entries.items():
            new = self.colorizer.color(key + ": ", fore="yellow", bright=True)
            new += self.colorizer.color(value, fore="cyan", bright=True)

            if not msg:
                msg += new
                continue

            new_line = msg.splitlines()[-1] + " | " + new

            if len(self.colorizer.clean(new_line)) >= shutil.get_terminal_size()[0]:
                msg += '\n'
            else:
                msg += self.colorizer.color(" | ", fore="magenta", bright=True)

            msg += new

        self.new_line(msg, save=save)

    def config(
        self,
        extensions,
        prefixes,
        suffixes,
        threads,
        wordlist_size,
        method,
    ):

        config = {}
        config["Extensions"] = extensions

        if prefixes:
            config["Prefixes"] = prefixes
        if suffixes:
            config["Suffixes"] = suffixes

        config["HTTP method"] = method
        config["Threads"] = threads
        config["Wordlist size"] = wordlist_size

        self.print_header(config)

    def set_target(self, target):
        self.target = target
        self.new_line()
        self.print_header({"Target": target}, save=True)

    def output_file(self, target):
        self.new_line("\nOutput File: {0}".format(target), save=False)

    def log_file(self, target):
        self.new_line("\nLog File: {0}".format(target), save=False)

    def export(self):
        return self.buffer.rstrip()
