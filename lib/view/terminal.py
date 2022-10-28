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
import time
import shutil

from lib.core.data import options
from lib.core.decorators import locked
from lib.core.settings import IS_WINDOWS
from lib.utils.common import human_size
from lib.view.colors import set_color, clean_color, disable_color

if IS_WINDOWS:
    from colorama.win32 import (
        FillConsoleOutputCharacter,
        GetConsoleScreenBufferInfo,
        STDOUT,
    )


class CLI:
    def __init__(self):
        self.last_in_line = False
        self.buffer = ""

        if not options["color"]:
            disable_color()

    @staticmethod
    def erase():
        if IS_WINDOWS:
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

    @locked
    def in_line(self, string):
        self.erase()
        sys.stdout.write(string)
        sys.stdout.flush()
        self.last_in_line = True

    @locked
    def new_line(self, string="", do_save=True):
        if self.last_in_line:
            self.erase()

        if IS_WINDOWS:
            sys.stdout.write(string)
            sys.stdout.flush()
            sys.stdout.write("\n")
            sys.stdout.flush()

        else:
            sys.stdout.write(string + "\n")

        sys.stdout.flush()
        self.last_in_line = False
        sys.stdout.flush()

        if do_save:
            self.buffer += string
            self.buffer += "\n"

    def status_report(self, response, full_url):
        status = response.status
        length = human_size(response.length)
        target = response.url if full_url else "/" + response.full_path
        current_time = time.strftime("%H:%M:%S")
        message = f"[{current_time}] {status} - {length.rjust(6, ' ')} - {target}"

        if status in (200, 201, 204):
            message = set_color(message, fore="green")
        elif status == 401:
            message = set_color(message, fore="yellow")
        elif status == 403:
            message = set_color(message, fore="blue")
        elif status in range(500, 600):
            message = set_color(message, fore="red")
        elif status in range(300, 400):
            message = set_color(message, fore="cyan")
        else:
            message = set_color(message, fore="magenta")

        if response.redirect:
            message += f"  ->  {response.redirect}"

        for redirect in response.history:
            message += f"\n-->  {redirect}"

        self.new_line(message)

    def last_path(self, index, length, current_job, all_jobs, rate, errors):
        percentage = int(index / length * 100)
        task = set_color("#", fore="cyan", style="bright") * int(percentage / 5)
        task += " " * (20 - int(percentage / 5))
        progress = f"{index}/{length}"

        grean_job = set_color("job", fore="green", style="bright")
        jobs = f"{grean_job}:{current_job}/{all_jobs}"

        red_error = set_color("errors", fore="red", style="bright")
        errors = f"{red_error}:{errors}"

        progress_bar = f"[{task}] {str(percentage).rjust(2, chr(32))}% "
        progress_bar += f"{progress.rjust(12, chr(32))} "
        progress_bar += f"{str(rate).rjust(9, chr(32))}/s       "
        progress_bar += f"{jobs.ljust(21, chr(32))} {errors}"

        if len(clean_color(progress_bar)) >= shutil.get_terminal_size()[0]:
            return

        self.in_line(progress_bar)

    def new_directories(self, directories):
        message = set_color(
            f"Added to the queue: {', '.join(directories)}", fore="yellow", style="dim"
        )
        self.new_line(message)

    def error(self, reason):
        message = set_color(reason, fore="white", back="red", style="bright")
        self.new_line("\n" + message)

    def warning(self, message, do_save=True):
        message = set_color(message, fore="yellow", style="bright")
        self.new_line(message, do_save=do_save)

    def header(self, message):
        message = set_color(message, fore="magenta", style="bright")
        self.new_line(message)

    def print_header(self, headers):
        msg = []

        for key, value in headers.items():
            new = set_color(key + ": ", fore="yellow", style="bright")
            new += set_color(value, fore="cyan", style="bright")

            if (
                not msg
                or len(clean_color(msg[-1]) + clean_color(new)) + 3
                >= shutil.get_terminal_size()[0]
            ):
                msg.append("")
            else:
                msg[-1] += set_color(" | ", fore="magenta", style="bright")

            msg[-1] += new

        self.new_line("\n".join(msg))

    def config(self, wordlist_size):

        config = {}
        config["Extensions"] = ", ".join(options["extensions"])

        if options["prefixes"]:
            config["Prefixes"] = ", ".join(options["prefixes"])
        if options["suffixes"]:
            config["Suffixes"] = ", ".join(options["suffixes"])

        config.update({
            "HTTP method": options["http_method"],
            "Threads": str(options["thread_count"]),
            "Wordlist size": str(wordlist_size),
        })

        self.print_header(config)

    def target(self, target):
        self.new_line()
        self.print_header({"Target": target})

    def output_location(self, file):
        self.new_line(f"\nOutput: {file}")

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

    def config(*args):
        pass

    def target(*args):
        pass

    def output_location(*args):
        pass

    def log_file(*args):
        pass


interface = QuietCLI() if options["quiet"] else CLI()
