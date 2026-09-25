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

from xml.etree import ElementTree as ET

from lib.core.decorators import locked
from lib.core.settings import (
    COMMAND,
    DEFAULT_ENCODING,
    START_TIME,
)
from lib.report.factory import BaseReport, StructuredFileReportMixin


class XMLReport(StructuredFileReportMixin, BaseReport):
    __format__ = "xml"
    __extension__ = "xml"

    def new(self):
        return ET.Element("dirsearchscan", args=COMMAND, time=START_TIME)

    def parse(self, file):
        return ET.parse(file).getroot()

    def _state_for_journal(self, root):
        def serialize_element(element):
            text = element.text
            if text is not None and not text.strip():
                text = None
            return {
                "attributes": dict(element.attrib),
                "children": [serialize_element(child) for child in element],
                "tag": element.tag,
                "text": text,
            }

        return serialize_element(root)

    @staticmethod
    def _apply_entry(root, entry):
        target = ET.SubElement(root, "result", url=entry["url"])
        ET.SubElement(target, "status").text = str(entry["status"])
        ET.SubElement(target, "contentLength").text = str(entry["contentLength"])
        ET.SubElement(target, "contentType").text = entry["contentType"]
        ET.SubElement(target, "redirect").text = entry["redirect"]
        if "elapsed" in entry:
            ET.SubElement(target, "elapsed").text = str(entry["elapsed"])

    @locked
    def save(self, file, result):
        entry = {
            "url": result.url,
            "status": result.status,
            "contentLength": result.length,
            "contentType": result.type,
            "redirect": result.redirect,
        }
        if result.elapsed:
            entry["elapsed"] = round(result.elapsed, 3)
        self.save_entry(file, entry)

    def write(self, file, root):
        ET.indent(root)
        xml_ = ET.tostring(root, encoding=DEFAULT_ENCODING, method="xml").decode()
        super().write(file, xml_)
