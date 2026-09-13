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

import json
import os

from jinja2 import Environment, FileSystemLoader

from lib.core.decorators import locked
from lib.core.settings import COMMAND, DEFAULT_ENCODING, START_TIME
from lib.report.factory import BaseReport, FileReportMixin


class HTMLReport(FileReportMixin, BaseReport):
    __format__ = "html"
    __extension__ = "html"

    def new(self):
        return self.generate([])

    def parse(self, file):
        with open(file, encoding=DEFAULT_ENCODING) as fh:
            while True:
                line = fh.readline()
                if not line:
                    raise ValueError("HTML report does not contain resources data")
                if line.startswith("        resources: "):
                    return json.loads(line[19:-2])

    @locked
    def save(self, file, result):
        results = self.parse(file)
        entry = {
            "url": result.url,
            "status": result.status,
            "contentLength": result.length,
            "contentType": result.type,
            "redirect": result.redirect,
        }
        if result.elapsed:
            entry["elapsed"] = round(result.elapsed, 3)
        results.append(entry)
        self.write(file, self.generate(results))

    def generate(self, results):
        file_loader = FileSystemLoader(
            os.path.dirname(os.path.realpath(__file__)) + "/templates/"
        )
        env = Environment(loader=file_loader)
        template = env.get_template("html_report_template.html")
        return template.render(
            metadata={"command": COMMAND, "date": START_TIME},
            results=results,
        )
