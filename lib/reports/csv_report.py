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

import time

from lib.reports import *


class CSVReport(FileBaseReport):

    def addPath(self, path, status, response):
        contentLength = None

        try:
            contentLength = int(response.headers["content-length"])

        except (KeyError, ValueError):
            contentLength = len(response.body)

        self.storeData((path, status, contentLength, response.redirect))

    def generate(self):
        result = "Time,URL,Status,Size,Redirection\n"

        for path, status, contentLength, redirect in self.pathList:
            result += "{0},".format(time.ctime())
            result += "{0}://{1}:{2}/{3}{4},".format(self.protocol, self.host, self.port, self.basePath, path)
            result += "{0},".format(status)
            result += "{0},".format(contentLength)
            if redirect:
                result += "{0}".format(redirect)

            result += "\n"

        return result
