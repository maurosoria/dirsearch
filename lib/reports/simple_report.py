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


class SimpleReport(FileBaseReport):
    def generate(self):
        result = ''

        for entry in self.entries:
            for result in entry.results:
                if (entry.protocol, entry.host, entry.port, entry.base_path, result.path) not in self.written_entries:
                    result += "{.protocol}://{.host}:{.port}/".format(entry)
                    result += (
                        result.path
                        if not entry.base_path
                        else f"{entry.base_path}/{result.path}"
                    )
                    result += NEW_LINE
                    self.written_entries.append((entry.protocol, entry.host, entry.port, entry.base_path, result.path))

        return result
