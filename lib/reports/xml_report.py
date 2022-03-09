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

from xml.dom import minidom
from xml.etree import ElementTree as ET

from lib.core.decorators import locked
from lib.core.settings import DEFAULT_ENCODING
from lib.reports.base import FileBaseReport


class XMLReport(FileBaseReport):
    def generate(self):
        result = ET.Element("scan", args=" ".join(sys.argv), time=time.ctime())

        for entry in self.entries:
            header_name = (
                f"{entry.protocol}://{entry.host}:{entry.port}/{entry.base_path}"
            )
            target = ET.SubElement(result, "target", url=header_name)

            for result_ in entry.results:
                path = ET.SubElement(target, "info", path="/" + result_.path)
                ET.SubElement(path, "status").text = str(result_.status)
                ET.SubElement(path, "contentLength").text = str(result_.response.length)
                ET.SubElement(path, "contentType").text = result_.response.type
                ET.SubElement(path, "redirect").text = result_.response.redirect

        result = ET.tostring(result, encoding=DEFAULT_ENCODING, method="xml")
        return minidom.parseString(result).toprettyxml()

    @locked
    def save(self):
        self.file.seek(0)
        self.file.truncate(0)
        self.file.flush()
        self.file.writelines(self.generate())
        self.file.flush()
