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
        if self.header_written is False:
            self.header_written = True
            result = "### Info" + NEW_LINE
            result += "Args: {0}".format(' '.join(sys.argv)) + NEW_LINE
            result += "Time: {0}".format(time.ctime()) + NEW_LINE
            result += NEW_LINE
            return result
        else:
            return ''

    def generate(self):
        result = self.generate_header()

        for entry in self.entries:
            header_name = "{0}://{1}:{2}/{3}".format(
                entry.protocol, entry.host, entry.port, entry.base_path
            )
            if (entry.protocol, entry.host, entry.port, entry.base_path) not in self.printed_target_header_list:
                result += "### Target: {0}".format(header_name) + NEW_LINE * 2
                result += "Path | Status | Size | Redirection" + NEW_LINE
                result += "-----|--------|------|------------" + NEW_LINE
                self.printed_target_header_list.append((entry.protocol, entry.host, entry.port, entry.base_path))

            for e in entry.results:
                if (entry.protocol, entry.host, entry.port, entry.base_path, e.path) not in self.written_entries:
                    result += "[/{0}]({1}) | ".format(e.path, header_name + e.path)
                    result += "{0} | ".format(e.status)
                    result += "{0} | ".format(e.response.length)
                    result += "{0}".format(e.response.redirect) + NEW_LINE

                    self.written_entries.append((entry.protocol, entry.host, entry.port, entry.base_path, e.path))

            if entry.completed and entry not in self.completed_hosts:
                result += NEW_LINE
                self.completed_hosts.append(entry)

        return result
