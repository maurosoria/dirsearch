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

from lib.core.decorators import locked
from lib.reports.base import FileBaseReport
from lib.utils.common import human_size


class HTMLReport(FileBaseReport):
    def generate(self):
        file_loader = FileSystemLoader(os.path.dirname(os.path.realpath(__file__)) + "/templates/")
        env = Environment(loader=file_loader)

        template = env.get_template("html_report_template.html")

        metadata = {
            "command": self.get_command(),
            "date": time.ctime()
        }
        results = []
        for entry in self.entries:
            header_name = f"{entry.protocol}://{entry.host}:{entry.port}/{entry.base_path}"

            for result in entry.results:
                status_color_class = ''
                if result.status >= 200 and result.status <= 299:
                    status_color_class = "text-success"
                elif result.status >= 300 and result.status <= 399:
                    status_color_class = "text-warning"
                elif result.status >= 400 and result.status <= 599:
                    status_color_class = "text-danger"

                results.append({
                    "url": header_name + result.path,
                    "path": result.path,
                    "status": result.status,
                    "statusColorClass": status_color_class,
                    "contentLength": human_size(result.response.length),
                    "contentType": result.response.type,
                    "redirect": result.response.redirect
                })

        return template.render(metadata=metadata, results=results)

    def get_command(self):
        command = ' '.join(sys.argv)
        if "[[" in command or "]]" in command:
            return "Dirsearch"
        else:
            return command

    @locked
    def save(self):
        self.file.seek(0)
        self.file.truncate(0)
        self.file.flush()
        self.file.writelines(self.generate())
        self.file.flush()
