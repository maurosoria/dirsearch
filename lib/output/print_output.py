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
import threading
import urllib.parse

from lib.utils.file_utils import *
from thirdparty.colorama import init, Fore, Style

if sys.platform in ["win32", "msys"]:
    from thirdparty.colorama.win32 import *


class PrintOutput(object):
    def __init__(self, color):
        init()
        self.mutex = threading.Lock()
        self.blacklists = {}
        self.mutexCheckedPaths = threading.Lock()
        self.basePath = None
        self.errors = 0
        self.color = color

    def header(self, text):
        pass

    def inLine(self, string):
        self.erase()
        sys.stdout.write(string)
        sys.stdout.flush()

    def erase(self):
        if sys.platform in ["win32", "cygwin", "msys"]:
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
        sys.stdout.write(string + "\n")
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

        parsed = urllib.parse.urlparse(self.target)
        showPath = "{0}://{1}{2}".format(parsed.scheme, parsed.netloc, showPath)

        message = "{0} - {1} - {2}".format(
            status, contentLength.rjust(6, " "), showPath
        )

        if self.color:
            if status == 200:
                message = Fore.GREEN + message + Style.RESET_ALL

            elif status == 401:
                message = Fore.YELLOW + message + Style.RESET_ALL

            elif status == 403:
                message = Fore.BLUE + message + Style.RESET_ALL

            elif status == 500:
                message = Fore.RED + message + Style.RESET_ALL

        # Check if redirect
        if status in [301, 302, 307] and "location" in [
            h.lower() for h in response.headers
        ]:
            if self.color:
                message = Fore.CYAN + message + Style.RESET_ALL
            message += "  ->  {0}".format(response.headers["location"])

        if addedToQueue:
            message += "     (Added to queue)"

        with self.mutex:
            self.newLine(message)

    def lastPath(self, path, index, length, currentJob, allJobs):
        pass

    def addConnectionError(self):
        self.errors += 1

    def error(self, reason):
        pass

    def warning(self, reason):
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

    def setTarget(self, target):
        if not target.startswith("http://") and not target.startswith("https://") and "://" not in target:
            target = "http://" + target

        self.target = target

    def outputFile(self, target):
        pass

    def errorLogFile(self, target):
        pass

    def debug(self, info):
        with self.mutex:
            self.newLine(info)
