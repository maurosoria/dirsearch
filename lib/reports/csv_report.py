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


class CSVReport(FileBaseReport):
    def generateHeader(self):
        if self.headerWritten is False:
            self.headerWritten = True
            return "URL,Status,Size,Redirection\n"
        else:
            return ""

    def generate(self):
        result = self.generateHeader()
        insecureChars = ("+", "-", "=", "@")

        for entry in self.entries:
            if (entry.protocol, entry.host, entry.port, entry.basePath) not in self.writtenEntries:
                for e in entry.results:
                    path = e.path
                    status = e.status
                    contentLength = e.getContentLength()
                    redirect = e.response.redirect

                    result += "{0}://{1}:{2}/{3}{4},".format(entry.protocol, entry.host, entry.port, entry.basePath, path)
                    result += "{0},".format(status)
                    result += "{0},".format(contentLength)
                    if redirect:
                        # Preventing CSV injection. More info: https://www.exploit-db.com/exploits/49370
                        if redirect.startswith(insecureChars):
                            redirect = "'" + redirect

                        redirect = redirect.replace("\"", "\"\"")
                        result += "\"{0}\"".format(redirect)

                    result += "\n"
                self.writtenEntries.append((entry.protocol, entry.host, entry.port, entry.basePath))

        return result
