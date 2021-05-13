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


class XMLReport(FileBaseReport):
    def generate(self):
        result = "<?xml version=\"1.0\"?>\n"
        result += "<dirsearchScan args=\"{0}\" time=\"{1}\">\n".format(" ".join(sys.argv), time.ctime())

        for entry in self.entries:
            header_name = "{0}://{1}:{2}/{3}".format(
                entry.protocol, entry.host, entry.port, entry.base_path
            )
            result += " <target url=\"{0}\">\n".format(header_name)

            for e in entry.results:
                result += "  <info path=\"/{0}\">\n".format(e.path)
                result += "   <status>{0}</status>\n".format(e.status)
                result += "   <contentLength>{0}</contentLength>\n".format(e.get_content_length())
                result += "   <redirect>{0}</redirect>\n".format("" if e.response.redirect is None else e.response.redirect)
                result += "  </info>\n"

            result += " </target>\n"
        result += "</dirsearchScan>\n"

        return result

    def save(self):
        self.file.seek(0)
        self.file.truncate(0)
        self.file.flush()
        self.file.writelines(self.generate())
        self.file.flush()
