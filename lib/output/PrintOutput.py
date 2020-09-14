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
import time

from posixpath import join as urljoin

from lib.utils.FileUtils import *
from lib.utils.TerminalSize import get_terminal_size
from thirdparty.colorama import *

if sys.platform in ["win32", "cygwin", "msys"]:
    from thirdparty.colorama.win32 import *


class PrintOutput(object):
    def __init__(self):
        init()
        self.mutex = threading.Lock()
        self.blacklists = {}
        self.mutexCheckedPaths = threading.Lock()
        self.basePath = None
        self.errors = 0
        
    def header(self, s):
        pass

    def inLine(self, string):
        pass

    def erase(self):
        pass

    def newLine(self, string):
        sys.stdout.write(string + "\n")
        sys.stdout.flush()
        

    def statusReport(self, path, response, full_url):
        with self.mutex:
            contentLength = None
            status = response.status

            # Check blacklist
            if status in self.blacklists and path in self.blacklists[status]:
                return

            # Format message
            try:
                size = int(response.headers["content-length"])

            except (KeyError, ValueError):
                size = len(response.body)

            finally:
                contentLength = FileUtils.sizeHuman(size)

            if self.basePath is None:
                showPath = urljoin("/", path)

            else:
                showPath = urljoin("/", self.basePath)
                showPath = urljoin(showPath, path)
                showPath = (self.target[:-1] if self.target.endswith("/") else self.target) + showPath
            message = "{0} - {1} - {2}".format(
                status, contentLength.rjust(6, " "), showPath
            )

            if status == 200:
                message = Fore.GREEN + message + Style.RESET_ALL

            elif status == 401:
                message = Fore.YELLOW + message + Style.RESET_ALL
                
            elif status == 403:
                message = Fore.BLUE + message + Style.RESET_ALL
                
            elif status == 500:
                message = Fore.RED + message + Style.RESET_ALL

            # Check if redirect
            elif status in [301, 302, 307] and "location" in [
                h.lower() for h in response.headers
            ]:
                message = Fore.CYAN + message + Style.RESET_ALL
                message += "  ->  {0}".format(response.headers["location"])

            self.newLine(message)

    def lastPath(self, path, index, length):
        pass

    def addConnectionError(self):
        self.errors += 1

    def error(self, reason):
        pass

    def warning(self, reason):
        pass

    def header(self, text):
        pass


    def config(
        self,
        extensions,
        suffixes,
        threads,
        wordlist_size,
        method,
        recursive,
        recursion_level,
    ):
        pass


    def target(self, target):
        self.target = target

    def outputFile(self, target):
        pass
    
    def errorLogFile(self, target):
        pass

    def debug(self, info):
        pass
