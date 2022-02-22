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
    def __init__(self, output_file_name, entries=[]):
        self.output = output_file_name
        self.entries = entries
        self.header_written = False
        self.written_entries = []
        self.printed_target_header_list = []
        self.completed_hosts = []

        self.open()

    def generate_header(self):
        if self.header_written:
            return ''

        self.header_written = True
        header = "### Info" + NEW_LINE
        header += f"Args: {chr(32).join(sys.argv)}"
        header += NEW_LINE
        header += f"Time: {time.ctime()}"
        header += NEW_LINE * 2
        return header

    def generate(self):
        output = self.generate_header()

        for entry in self.entries:
            header = "{.protocol}://{.host}:{.port}/{.base_path}".format(entry)

            if (entry.protocol, entry.host, entry.port, entry.base_path) not in self.printed_target_header_list:
                output += f"### Target: {header_name}"
                output += NEW_LINE * 2
                output += "Path | Status | Size | Content Type | Redirection" + NEW_LINE
                output += "-----|--------|------|--------------|------------" + NEW_LINE
                self.printed_target_header_list.append((entry.protocol, entry.host, entry.port, entry.base_path))

            for result in entry.results:
                if (entry.protocol, entry.host, entry.port, entry.base_path, result.path) not in self.written_entries:
                    output += "[/{.path}]({header}{.path}) | {.status} | {.response.length} ".format(result, header=header)
                    output += "| {.content_type} | {.response.redirect}".format(result)
                    output += NEW_LINE

                    self.written_entries.append((entry.protocol, entry.host, entry.port, entry.base_path, result.path))

            if entry.completed and entry not in self.completed_hosts:
                output += NEW_LINE
                self.completed_hosts.append(entry)

        return output
