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

import threading
import time
import sys
import platform
import urllib.parse

from lib.utils.FileUtils import *
from thirdparty.colorama import *
from lib.utils.TerminalSize import get_terminal_size

if platform.system() == 'Windows':
    from thirdparty.colorama.win32 import *


class CLIOutput(object):
    def __init__(self):
        init()
        self.lastLength = 0
        self.lastOutput = ''
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
        if platform.system() == 'Windows':
            csbi = GetConsoleScreenBufferInfo()
            line = "\b" * int(csbi.dwCursorPosition.X)
            sys.stdout.write(line)
            width = csbi.dwCursorPosition.X
            csbi.dwCursorPosition.X = 0
            FillConsoleOutputCharacter(STDOUT, ' ', width, csbi.dwCursorPosition)
            sys.stdout.write(line)
            sys.stdout.flush()
        else:
            sys.stdout.write('\033[1K')
            sys.stdout.write('\033[0G')

    def newLine(self, string):
        if self.lastInLine == True:
            self.erase()
        if platform.system() == 'Windows':
            sys.stdout.write(string)
            sys.stdout.flush()
            sys.stdout.write('\n')
            sys.stdout.flush()
        else:
            sys.stdout.write(string + '\n')
        sys.stdout.flush()
        self.lastInLine = False
        sys.stdout.flush()

    def statusReport(self, path, response):
        with self.mutex:
            contentLength = None
            status = response.status

            # Check blacklist
            if status in self.blacklists and path in self.blacklists[status]:
                return

            # Format message
            try:
                size = int(response.headers['content-length'])
            except (KeyError, ValueError):
                size = len(response.body)
            finally:
                contentLength = FileUtils.sizeHuman(size)

            if self.basePath is None:
                showPath = urllib.parse.urljoin("/", path)
            else:
                showPath = urllib.parse.urljoin("/", self.basePath)
                showPath = urllib.parse.urljoin(showPath, path)
            message = '[{0}] {1} - {2} - {3}'.format(
                time.strftime('%H:%M:%S'),
                status,
                contentLength.rjust(6, ' '),
                showPath
            )

            if status == 200:
                message = Fore.GREEN + message + Style.RESET_ALL
            elif status == 403:
                message = Fore.BLUE + message + Style.RESET_ALL
            elif status == 401:
                message = Fore.YELLOW + message + Style.RESET_ALL
            # Check if redirect
            elif status in [301, 302, 307] and 'location' in [h.lower() for h in response.headers]:
                message = Fore.CYAN + message + Style.RESET_ALL
                message += '  ->  {0}'.format(response.headers['location'])

            self.newLine(message)

    def lastPath(self, path, index, length):
        with self.mutex:
            percentage = lambda x, y: float(x) / float(y) * 100
            x, y = get_terminal_size()
            message = '{0:.2f}% - '.format(percentage(index, length))
            if self.errors > 0:
                message += Style.BRIGHT + Fore.RED
                message += 'Errors: {0}'.format(self.errors)
                message += Style.RESET_ALL
                message += ' - '
            message += 'Last request to: {0}'.format(path)
            if len(message) > x:
                message = message[:x]
            self.inLine(message)

    def addConnectionError(self):
        self.errors += 1

    def error(self, reason):
        with self.mutex:
            stripped = reason.strip()
            start = reason.find(stripped[0])
            end = reason.find(stripped[-1]) + 1
            message = reason[0:start]
            message += Style.BRIGHT + Fore.WHITE + Back.RED
            message += reason[start:end]
            message += Style.RESET_ALL
            message += reason[end:]
            self.newLine(message)

    def warning(self, reason):
        message = Style.BRIGHT + Fore.YELLOW + reason + Style.RESET_ALL
        self.newLine(message)

    def header(self, text):
        message = Style.BRIGHT + Fore.MAGENTA + text + Style.RESET_ALL
        self.newLine(message)

    def config(self, extensions, threads, wordlistSize):
        separator = Fore.MAGENTA + ' | ' + Fore.YELLOW
        config = Style.BRIGHT + Fore.YELLOW
        config += 'Extensions: {0}'.format(Fore.CYAN + extensions + Fore.YELLOW)
        config += separator
        config += 'Threads: {0}'.format(Fore.CYAN + threads + Fore.YELLOW)
        config += separator
        config += 'Wordlist size: {0}'.format(Fore.CYAN + wordlistSize + Fore.YELLOW)
        config += Style.RESET_ALL
        self.newLine(config)

    def target(self, target):
        config = Style.BRIGHT + Fore.YELLOW
        config += '\nTarget: {0}\n'.format(Fore.CYAN + target + Fore.YELLOW)
        config += Style.RESET_ALL
        self.newLine(config)

    def debug(self, info):
        line = "[{0}] - {1}".format(time.strftime('%H:%M:%S'), info)
        self.newLine(line)