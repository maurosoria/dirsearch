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
from lib.utils.FileUtils import *
from thirdparty.colorama import *
import platform
if platform.system() == 'Windows':
    from ctypes import windll, create_string_buffer
    from thirdparty.colorama.win32 import *


class CLIOutput(object):

    def __init__(self):
        init()
        self.lastLength = 0
        self.lastOutput = ''
        self.lastInLine = False
        self.mutex = threading.Lock()
        self.checkedPaths = []
        self.blacklists = {}
        self.mutexCheckedPaths = threading.Lock()
        self.basePath = None

    def printInLine(self, string):
        self.eraseLine()
        sys.stdout.write(string)
        sys.stdout.flush()
        self.lastInLine = True

    def eraseLine(self):
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

    def printNewLine(self, string):
        if self.lastInLine == True:
            self.eraseLine()
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

    def printStatusReport(self, path, response):
        status = response.status

        # Check blacklist
        if status in self.blacklists and path in self.blacklists[status]:
            return


        # Format message
        contentLength = None
        try:
            contentLength = FileUtils.sizeHuman(int(response.headers['content-length']))
        except (KeyError, ValueError):
            contentLength = FileUtils.sizeHuman(len(response.body))

        message = '[{0}] {1} - {2} - {3}'.format(
            time.strftime('%H:%M:%S'), 
            status,
            contentLength.rjust(6, ' '),
            ('/{0}'.format(path) if self.basePath is None 
                else '{0}{1}'.format(self.basePath, path)))
    
        try:
            self.mutexCheckedPaths.acquire()
            if path in self.checkedPaths:
                self.mutexCheckedPaths.release()
                return
        except (KeyboardInterrupt, SystemExit), e:
            raise e
        finally:
            self.mutexCheckedPaths.release()

        if status == 200:
            message = Style.BRIGHT + Fore.GREEN + message + Style.RESET_ALL
        elif status == 403:
            message = Style.BRIGHT + Fore.BLUE + message + Style.RESET_ALL
        # Check if redirect
        elif status in [301, 302, 307] and 'location' in response.headers:
            message = Style.BRIGHT + Fore.CYAN + message + Style.RESET_ALL
            message += '  ->  {0}'.format(response.headers['location'])

        self.printNewLine(message)


    def printLastPathEntry(self, path, index, length):
        percentage = lambda x, y: float(x) / float(y) * 100
        message = '{1:.2f}% - Last request to: {0}'.format(path, percentage(index, length))
        self.printInLine(message)

    def printError(self, reason):
        stripped = reason.strip()
        start = reason.find(stripped[0])
        end = reason.find(stripped[-1]) + 1
        message = reason[0:start]
        message += Style.BRIGHT + Fore.WHITE + Back.RED
        message += reason[start:end]
        message += Style.RESET_ALL
        message += reason[end:]
        self.printNewLine(message)

    def printWarning(self, reason):
        message = Style.BRIGHT + Fore.YELLOW + reason + Style.RESET_ALL
        self.printNewLine(message)

    def printHeader(self, text):
        message = Style.BRIGHT + Fore.MAGENTA + text + Style.RESET_ALL
        self.printNewLine(message)


