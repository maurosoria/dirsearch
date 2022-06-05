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

from lib.core.settings import DEFAULT_ENCODING
from lib.reports.base import FileBaseReport


class XMLReport(FileBaseReport):
    def generate(self, entries):
        tree = ET.Element("dirsearchscan", args=" ".join(sys.argv), time=time.ctime())

        for entry in entries:
            target = ET.SubElement(tree, "target", url=entry.url)
            ET.SubElement(target, "status").text = str(entry.status)
            ET.SubElement(target, "contentLength").text = str(entry.length)
            ET.SubElement(target, "contentType").text = entry.type
            if entry.redirect:
                ET.SubElement(target, "redirect").text = entry.redirect

        output = ET.tostring(tree, encoding=DEFAULT_ENCODING, method="xml")
        # Beautify XML output
        return minidom.parseString(output).toprettyxml()
