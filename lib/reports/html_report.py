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

import os
import sys
import time

from jinja2 import Environment, FileSystemLoader

from lib.reports.base import FileBaseReport
from lib.utils.common import human_size


class HTMLReport(FileBaseReport):
    def generate(self, entries):
        file_loader = FileSystemLoader(
            os.path.dirname(os.path.realpath(__file__)) + "/templates/"
        )
        env = Environment(loader=file_loader)
        template = env.get_template("html_report_template.html")
        metadata = {"command": " ".join(sys.argv), "date": time.ctime()}
        results = []

        for entry in entries:
            status_color_class = ""
            if entry.status >= 200 and entry.status <= 299:
                status_color_class = "text-success"
            elif entry.status >= 300 and entry.status <= 399:
                status_color_class = "text-warning"
            elif entry.status >= 400 and entry.status <= 599:
                status_color_class = "text-danger"

            results.append(
                {
                    "url": entry.url,
                    "status": entry.status,
                    "statusColorClass": status_color_class,
                    "contentLength": human_size(entry.length),
                    "contentType": entry.type,
                    "redirect": entry.redirect,
                }
            )

        return template.render(metadata=metadata, results=results)
