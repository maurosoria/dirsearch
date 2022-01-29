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

import sys

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
        self.buffer = ''
        self.mutex = Lock()
        self.blacklists = {}
        self.mutex_checked_paths = Lock()
        self.url = None
        self.errors = 0
        self.colorizer = ColorOutput(colors)

    def header(self, text):
        pass

    def in_line(self, string):
        self.erase()
        sys.stdout.write(string)
        sys.stdout.flush()

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

    def new_line(self, string=''):
        self.buffer += string
        self.buffer += '\n'

        sys.stdout.write(string + '\n')
        sys.stdout.flush()

    def status_report(self, response, full_url, added_to_queue):
        status = response.status
        content_length = human_size(response.length)
        message = "{0} - {1} - {2}".format(
            status, content_length.rjust(6, ' '), self.url + response.path
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
        pass

    def add_connection_error(self):
        self.errors += 1

    def error(self, reason):
        with self.mutex:
            stripped = reason.strip()
            message = self.colorizer.color(stripped, fore="white", back="red", bright=True)

            self.new_line(message)

    def warning(self, reason, save=True):
        pass

    def config(
        self,
        extensions,
        prefixes,
        suffixes,
        threads,
        wordlist_size,
        method,
    ):
        pass

    def set_target(self, target):
        self.target = target

    def output_file(self, target):
        pass

    def log_file(self, target):
        pass

    def export(self):
        return self.buffer.rstrip()
