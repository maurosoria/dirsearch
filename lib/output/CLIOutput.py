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

if sys.platform in ["win32", "msys"]:
    from thirdparty.colorama.win32 import *


class CLIOutput(object):
    def __init__(self):
        init()
        self.lastLength = 0
        self.lastOutput = ""
        self.lastInLine = False
        self.mutex = threading.Lock()
        self.blacklists = {}
        self.mutexCheckedPaths = threading.Lock()
        self.basePath = None
        self.errors = 0

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
        if self.lastInLine == True:
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
                if full_url:
                    showPath = (self.target[:-1] if self.target.endswith("/") else self.target) + showPath
                
            message = "[{0}] {1} - {2} - {3}".format(
                time.strftime("%H:%M:%S"), 
                status, 
                contentLength.rjust(6, " "), 
                showPath,
            )

            if status == 200:
                message = Fore.GREEN + message + Style.RESET_ALL
                
            elif status == 400:
                message = Fore.MAGENTA + message + Style.RESET_ALL

            elif status == 401:
                message = Fore.YELLOW + message + Style.RESET_ALL
                
            elif status == 403:
                message = Fore.BLUE + message + Style.RESET_ALL
                
            elif status == 500:
                message = Fore.RED + message + Style.RESET_ALL

            # Check if redirect
            elif status in [301, 302, 303, 307, 308] and "location" in [
                h.lower() for h in response.headers
            ]:
                message = Fore.CYAN + message + Style.RESET_ALL
                message += "  ->  {0}".format(response.headers["location"])
                
            if addedToQueue:
                message += "     (Added to queue)"

            self.newLine(message)

    def lastPath(self, path, index, length, currentJob, allJobs):
        with self.mutex:
            percentage = lambda x, y: float(x) / float(y) * 100

            x, y = get_terminal_size()

            message = "{0:.2f}% - ".format(percentage(index, length))
            

            if allJobs > 1:
                message += "Job: {0}/{1} - ".format(currentJob, allJobs)

            if self.errors > 0:
                message += "Errors: {0} - ".format(self.errors)

            message += "Last request to: {0}".format(path)

            if len(message) > x:
                message = message[:x-1]

            self.inLine(message)

    def addConnectionError(self):
        self.errors += 1

    def error(self, reason):
        with self.mutex:
            stripped = reason.strip()
            message = "\n" if "\n" in reason else ""
            message += Style.BRIGHT + Fore.WHITE + Back.RED
            message += stripped
            message += Style.RESET_ALL
            self.newLine(message)

    def warning(self, reason):
        message = Style.BRIGHT + Fore.YELLOW + reason + Style.RESET_ALL
        self.newLine(message)

    def header(self, text):
        message = Style.BRIGHT + Fore.MAGENTA + text + Style.RESET_ALL
        self.newLine(message)


    def config(
        self,
        extensions,
        prefixes,
        suffixes,
        threads,
        wordlist_size,
        method,
        recursive,
        recursion_level,
    ):
        separator = Fore.MAGENTA + " | " + Fore.YELLOW

        config = Style.BRIGHT + Fore.YELLOW
        config += "Extensions: {0}".format(Fore.CYAN + extensions + Fore.YELLOW)
        config += separator

        config += "HTTP method: {0}".format(Fore.CYAN + method.upper() + Fore.YELLOW)
        config += separator


        if prefixes != '':
            config += 'Prefixes: {0}'.format(Fore.CYAN + prefixes + Fore.YELLOW)
            config += separator

        if suffixes != '':
            config += 'Suffixes: {0}'.format(Fore.CYAN + suffixes + Fore.YELLOW)
            config += separator

        config += "Threads: {0}".format(Fore.CYAN + threads + Fore.YELLOW)
        config += separator
        config += "Wordlist size: {0}".format(Fore.CYAN + wordlist_size + Fore.YELLOW)

        if recursive == True:
            config += separator
            config += "Recursion level: {0}".format(
                Fore.CYAN + recursion_level + Fore.YELLOW
            )

        config += Style.RESET_ALL

        self.newLine(config)

    def target(self, target):
        self.target = target

        config = Style.BRIGHT + Fore.YELLOW
        config += "\nTarget: {0}\n".format(Fore.CYAN + target + Fore.YELLOW)
        config += Style.RESET_ALL

        self.newLine(config)
        
    def outputFile(self, target):
        self.newLine("Output File: {0}\n".format(target))
        
    def errorLogFile(self, target):
        self.newLine("\nError Log: {0}".format(target))

    def debug(self, info):
        line = "[{0}] - {1}".format(time.strftime("%H:%M:%S"), info)
        self.newLine(line)
