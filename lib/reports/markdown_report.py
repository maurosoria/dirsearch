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

from lib.reports import *
import time
import sys


class MarkdownReport(FileBaseReport):
    def __init__(self, outputFileName, entries=[]):
        self.output = outputFileName
        self.entries = entries
        self.headerWritten = False
        self.writtenEntries = []
        self.printedTargetHeaderList = []
        self.completedHosts = []

        self.open()

    def generateHeader(self):
        if self.headerWritten is False:
            self.headerWritten = True
            result = "### Info\n"
            result += "Args: {0}\n".format(' '.join(sys.argv))
            result += "Time: {0}\n".format(time.ctime())
            result += "\n"
            return result
        else:
            return ""

    def generate(self):
        result = self.generateHeader()

        for entry in self.entries:
            headerName = "{0}://{1}:{2}/{3}".format(
                entry.protocol, entry.host, entry.port, entry.basePath
            )
            if (entry.protocol, entry.host, entry.port, entry.basePath) not in self.printedTargetHeaderList:
                result += "### Target: {0}\n\n".format(headerName)
                result += "Path | Status | Size | Redirection\n"
                result += "-----|--------|------|------------\n"
                self.printedTargetHeaderList.append((entry.protocol, entry.host, entry.port, entry.basePath))

            for e in entry.results:
                if (entry.protocol, entry.host, entry.port, entry.basePath, e.path) not in self.writtenEntries:
                    result += "[/{0}]({1}) | ".format(e.path, headerName + e.path)
                    result += "{0} | ".format(e.status)
                    result += "{0} | ".format(e.getContentLength())
                    result += "{0}\n".format(e.response.redirect)

                    self.writtenEntries.append((entry.protocol, entry.host, entry.port, entry.basePath, e.path))

            if entry.completed and entry not in self.completedHosts:
                result += "\n"
                self.completedHosts.append(entry)

        return result
