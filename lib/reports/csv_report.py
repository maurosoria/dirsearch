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

from lib.core.settings import NEW_LINE
from lib.reports.base import FileBaseReport
from lib.utils.common import escape_csv


class CSVReport(FileBaseReport):
    def generate_header(self):
        if self.header_written is False:
            self.header_written = True
            return "URL,Status,Size,Content Type,Redirection" + NEW_LINE

        return ""

    def generate(self):
        output = self.generate_header()

        for entry in self.entries:
            for result in entry.results:
                if (
                    entry.protocol,
                    entry.host,
                    entry.port,
                    entry.base_path,
                    result.path,
                ) not in self.written_entries:
                    output += f"{entry.protocol}://{entry.host}:{entry.port}/{entry.base_path}{result.path},"
                    output += f"{result.status},{result.response.length},{result.response.type}"

                    if result.response.redirect:
                        output += f'"{escape_csv(result.response.redirect)}"'

                    output += NEW_LINE
                    self.written_entries.append(
                        (
                            entry.protocol,
                            entry.host,
                            entry.port,
                            entry.base_path,
                            result.path,
                        )
                    )

        return output
