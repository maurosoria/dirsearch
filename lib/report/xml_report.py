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

from xml.dom import minidom
from xml.etree import ElementTree as ET

from lib.core.decorators import locked
from lib.core.settings import (
    COMMAND,
    DEFAULT_ENCODING,
    START_TIME,
)
from lib.report.factory import BaseReport, FileReportMixin


class XMLReport(FileReportMixin, BaseReport):
    __format__ = "xml"
    __extension__ = "xml"

    def new(self):
        return ET.Element("dirsearchscan", args=COMMAND, time=START_TIME)

    def parse(self, file):
        return ET.parse(file).getroot()

    @locked
    def save(self, file, result):
        root = self.parse(file)
        target = ET.SubElement(root, "result", url=result.url)
        ET.SubElement(target, "status").text = str(result.status)
        ET.SubElement(target, "contentLength").text = str(result.length)
        ET.SubElement(target, "contentType").text = result.type
        ET.SubElement(target, "redirect").text = result.redirect

    def write(self, file, root):
        xml_ = ET.tostring(root, encoding=DEFAULT_ENCODING, method="xml")
        # Beautify XML output
        xml_ = minidom.parseString(xml_).toprettyxml()

        super().write(file, xml_)
