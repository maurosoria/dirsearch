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

import re
import sys
import threading
import time
import urllib.parse

from lib.utils.file_utils import FileUtils
from lib.utils.terminal_size import get_terminal_size
from thirdparty.colorama import init, Fore, Back, Style

if sys.platform in ["win32", "msys"]:
    from thirdparty.colorama.win32 import (FillConsoleOutputCharacter,
                                           GetConsoleScreenBufferInfo,
                                           STDOUT)


class NoColor:
    RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = WHITE = BRIGHT = RESET_ALL = ''


class CLIOutput(object):
    def __init__(self, color):
        init()
        self.last_length = 0
        self.last_output = ""
        self.last_in_line = False
        self.mutex = threading.Lock()
        self.blacklists = {}
        self.base_path = None
        self.errors = 0
        if not color:
            self.disable_colors()

    @staticmethod
    def percentage(x, y):
        return float(x) / float(y) * 100

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
        content_length = None
        status = response.status

        # Format message
        try:
            size = int(response.headers["content-length"])

        except (KeyError, ValueError):
            size = response.length

        finally:
            content_length = FileUtils.size_human(size)

        show_path = "/" + self.base_path + path

        if full_url:
            parsed = urllib.parse.urlparse(self.target)
            show_path = "{0}://{1}{2}".format(parsed.scheme, parsed.netloc, show_path)

        message = "[{0}] {1} - {2} - {3}".format(
            time.strftime("%H:%M:%S"),
            status,
            content_length.rjust(6, " "),
            show_path,
        )

        if status in [200, 201, 204]:
            message = Fore.GREEN + message + Style.RESET_ALL

        elif status == 401:
            message = Fore.YELLOW + message + Style.RESET_ALL

        elif status == 403:
            message = Fore.BLUE + message + Style.RESET_ALL

        elif status in range(500, 600):
            message = Fore.RED + message + Style.RESET_ALL

        elif status in range(300, 400):
            message = Fore.CYAN + message + Style.RESET_ALL
            if "location" in [h.lower() for h in response.headers]:
                message += "  ->  {0}".format(response.headers["location"])

        else:
            message = Fore.MAGENTA + message + Style.RESET_ALL

        if added_to_queue:
            message += "     (Added to queue)"

        with self.mutex:
            self.new_line(message)

    def last_path(self, path, index, length, current_job, all_jobs, rate, show_rate):
        terminal_len, _ = get_terminal_size()
        if terminal_len <= 45:
            return

        message = "{0:.2f}%{1} - ".format(
            self.percentage(index, length),
            " | {} req/s".format(rate) if show_rate else ""
        )

        if all_jobs > 1:
            message += "Job: {0}/{1} - ".format(current_job, all_jobs)

        if self.errors:
            message += "Errors: {0} - ".format(self.errors)

        message += "Last request to: {0}".format(path)

        if len(message) >= terminal_len:
            message = message[:terminal_len - 1]

        with self.mutex:
            self.in_line(message)

    def add_connection_error(self):
        self.errors += 1

    def error(self, reason):
        with self.mutex:
            stripped = reason.strip()
            message = "\n" if reason.startswith("\n") else ""
            message += Style.BRIGHT + Fore.WHITE + Back.RED + stripped + Style.RESET_ALL

            self.new_line(message)

    def warning(self, message):
        with self.mutex:
            message = Style.BRIGHT + Fore.YELLOW + message + Style.RESET_ALL
            self.new_line(message)

    def header(self, message):
        message = Style.BRIGHT + Fore.MAGENTA + message + Style.RESET_ALL
        self.new_line(message)

    def add_config(self, key, value, msg):
        l, _ = get_terminal_size()
        # Escape colours in text to get the real length
        escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|\n")
        particle = Fore.YELLOW + key + ": " + Fore.CYAN + value

        if len(escape.sub("", msg)) == 0:
            separator = ""
        elif len(escape.sub("", msg.splitlines()[-1] + particle)) + 3 > l:
            separator = "\n"
        else:
            separator = Fore.MAGENTA + " | " + Fore.YELLOW

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

        config = Style.BRIGHT
        config += self.add_config("Extensions", extensions, config)

        if prefixes:
            config += self.add_config("Prefixes", prefixes, config)

        if suffixes:
            config += self.add_config("Suffixes", suffixes, config)

        config += self.add_config("HTTP method", method.upper(), config)
        config += self.add_config("Threads", threads, config)
        config += self.add_config("Wordlist size", wordlist_size, config)
        config += Style.RESET_ALL

        self.new_line(config)

    def set_target(self, target, scheme):
        if not target.startswith(("http://", "https://")) and "://" not in target:
            target = "{0}://{1}".format(scheme, target)

        self.target = target

        config = Style.BRIGHT
        config += "\n" + self.add_config("Target", target, config) + "\n"
        config += Style.RESET_ALL

        self.new_line(config)

    def output_file(self, target):
        self.new_line("\nOutput File: {0}".format(target))

    def error_log_file(self, target):
        self.new_line("\nError Log: {0}".format(target))

    def debug(self, info):
        with self.mutex:
            line = "[{0}] - {1}".format(time.strftime("%H:%M:%S"), info)
            self.new_line(line)

    def disable_colors(self):
        global Fore
        global Style
        global Back

        Fore = Style = Back = NoColor
