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

from lib.reports import FileBaseReport
from xml.dom import minidom

import xml.etree.cElementTree as ET
import time
import sys


class XMLReport(FileBaseReport):
    def generate(self):
        result = ET.Element("dirsearchscan", args=" ".join(sys.argv), time=time.ctime())

        for entry in self.entries:
            header_name = "{0}://{1}:{2}/{3}".format(
                entry.protocol, entry.host, entry.port, entry.base_path
            )
            target = ET.SubElement(result, "target", url=header_name)

            for e in entry.results:
                path = ET.SubElement(target, "info", path="/" + e.path)
                ET.SubElement(path, "status").text = str(e.status)
                ET.SubElement(path, "contentlength").text = str(e.get_content_length())
                ET.SubElement(path, "redirect").text = e.response.redirect if e.response.redirect else ""

        result = ET.tostring(result, encoding="utf-8", method="xml")
        return minidom.parseString(result).toprettyxml()

    def save(self):
        self.file.seek(0)
        self.file.truncate(0)
        self.file.flush()
        self.file.writelines(self.generate())
        self.file.flush()
