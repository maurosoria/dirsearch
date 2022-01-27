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
from lib.utils.fmt import human_size


class PlainTextReport(FileBaseReport):
    def generate_header(self):
        if self.header_written is False:
            self.header_written = True
            return "# Dirsearch started {0} as: {1}".format(time.ctime(), ' '.join(sys.argv)) + NEW_LINE * 2
        else:
            return ''

    def generate(self):
        result = self.generate_header()

        for entry in self.entries:
            for e in entry.results:
                if (entry.protocol, entry.host, entry.port, entry.base_path, e.path) not in self.written_entries:
                    result += "{0}  ".format(e.status)
                    result += "{0}  ".format(human_size(e.response.length).rjust(6, ' '))
                    result += "{0}://{1}:{2}/".format(entry.protocol, entry.host, entry.port)
                    result += (
                        "{0}".format(e.path)
                        if entry.base_path == ''
                        else "{0}/{1}".format(entry.base_path, e.path)
                    )
                    location = e.response.redirect
                    if location:
                        result += "    -> REDIRECTS TO: {0}".format(location)

                    result += NEW_LINE
                    self.written_entries.append((entry.protocol, entry.host, entry.port, entry.base_path, e.path))

        return result
