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
import sys

from lib.core.settings import NEW_LINE
from lib.reports.base import FileBaseReport


class MarkdownReport(FileBaseReport):
    def get_header(self):
        header = "### Information" + NEW_LINE
        header += f"Command: {chr(32).join(sys.argv)}"
        header += NEW_LINE
        header += f"Time: {time.ctime()}"
        header += NEW_LINE * 2
        header += "URL | Status | Size | Content Type | Redirection" + NEW_LINE
        header += "----|--------|------|--------------|------------" + NEW_LINE
        return header

    def generate(self, entries):
        output = self.get_header()

        for entry in entries:
            output += f"{entry.url} | {entry.status} | {entry.length} | {entry.type} | {entry.redirect}" + NEW_LINE

        return output
