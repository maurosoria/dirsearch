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

from lib.utils.file_utils import *
from lib.utils.terminal_size import get_terminal_size
from thirdparty.colorama import init, Fore, Back, Style

if sys.platform in ["win32", "msys"]:
    from thirdparty.colorama.win32 import *


class NoColor:
    RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = WHITE = BRIGHT = RESET_ALL = ''


class CLIOutput(object):
    def __init__(self, color):
        init()
        self.lastLength = 0
        self.lastOutput = ""
        self.lastInLine = False
        self.mutex = threading.Lock()
        self.blacklists = {}
        self.basePath = None
        self.errors = 0
        if not color:
            self.disableColors()

    @staticmethod
    def percentage(x, y):
        return float(x) / float(y) * 100

    def inLine(self, string):
        self.erase()
        sys.stdout.write(string)
        sys.stdout.flush()
        self.lastInLine = True

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

    def newLine(self, string):
        if self.lastInLine:
            self.erase()

        if sys.platform in ["win32", "msys"]:
            sys.stdout.write(string)
            sys.stdout.flush()
            sys.stdout.write("\n")
            sys.stdout.flush()

        else:
            sys.stdout.write(string + "\n")

        sys.stdout.flush()
        self.lastInLine = False
        sys.stdout.flush()

    def statusReport(self, path, response, full_url, addedToQueue):
        contentLength = None
        status = response.status

        # Format message
        try:
            size = int(response.headers["content-length"])

        except (KeyError, ValueError):
            size = len(response.body)

        finally:
            contentLength = FileUtils.size_human(size)

        showPath = "/" + self.basePath + path

        if full_url:
            parsed = urllib.parse.urlparse(self.target)
            showPath = "{0}://{1}{2}".format(parsed.scheme, parsed.netloc, showPath)

        message = "[{0}] {1} - {2} - {3}".format(
            time.strftime("%H:%M:%S"),
            status,
            contentLength.rjust(6, " "),
            showPath,
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

        if addedToQueue:
            message += "     (Added to queue)"

        with self.mutex:
            self.newLine(message)

    def lastPath(self, path, index, length, currentJob, allJobs, rate):
        l, h = get_terminal_size()

        message = "{0:.2f}% | {1} req/s - ".format(self.percentage(index, length), rate)

        if allJobs > 1:
            message += "Job: {0}/{1} - ".format(currentJob, allJobs)

        if self.errors:
            message += "Errors: {0} - ".format(self.errors)

        message += "Last request to: {0}".format(path)

        if len(message) >= l:
            message = message[:l - 1]

        with self.mutex:
            self.inLine(message)

    def addConnectionError(self):
        self.errors += 1

    def error(self, reason):
        with self.mutex:
            stripped = reason.strip()
            message = "\n" if reason.startswith("\n") else ""
            message += Style.BRIGHT + Fore.WHITE + Back.RED + stripped + Style.RESET_ALL

            self.newLine(message)

    def warning(self, message):
        with self.mutex:
            message = Style.BRIGHT + Fore.YELLOW + message + Style.RESET_ALL
            self.newLine(message)

    def header(self, message):
        message = Style.BRIGHT + Fore.MAGENTA + message + Style.RESET_ALL
        self.newLine(message)

    def addConfig(self, key, value, msg):
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
        config += self.addConfig("Extensions", extensions, config)

        if prefixes:
            config += self.addConfig("Prefixes", prefixes, config)

        if suffixes:
            config += self.addConfig("Suffixes", suffixes, config)

        config += self.addConfig("HTTP method", method.upper(), config)
        config += self.addConfig("Threads", threads, config)
        config += self.addConfig("Wordlist size", wordlist_size, config)
        config += Style.RESET_ALL
        config += "\n"

        self.newLine(config)

    def setTarget(self, target, scheme):
        if not target.startswith(("http://", "https://")) and "://" not in target:
            target = "{0}://{1}".format(scheme, target)

        self.target = target

        config = Style.BRIGHT
        config += self.addConfig("Target", target, config) + "\n"
        config += Style.RESET_ALL

        self.newLine(config)

    def outputFile(self, target):
        self.newLine("Output File: {0}\n".format(target))

    def errorLogFile(self, target):
        self.newLine("Error Log: {0}\n".format(target))

    def debug(self, info):
        with self.mutex:
            line = "[{0}] - {1}".format(time.strftime("%H:%M:%S"), info)
            self.newLine(line)

    def disableColors(self):
        global Fore
        global Style
        global Back

        Fore = Style = Back = NoColor
