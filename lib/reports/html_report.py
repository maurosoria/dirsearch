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

from lib.reports.base import FileBaseReport
from lib.utils.size import human_size
from thirdparty.jinja2 import Environment, FileSystemLoader


class HTMLReport(FileBaseReport):
    def generate(self):
        file_loader = FileSystemLoader(os.path.dirname(os.path.realpath(__file__)) + '/templates/')
        env = Environment(loader=file_loader)

        template = env.get_template('html_report_template.html')

        metadata = {
            "command": self.get_command(),
            "date": time.ctime()
        }
        results = []
        for entry in self.entries:
            for e in entry.results:
                header_name = "{0}://{1}:{2}/{3}".format(
                    entry.protocol, entry.host, entry.port, entry.base_path
                )

                status_color_class = ''
                if e.status >= 200 and e.status <= 299:
                    status_color_class = 'text-success'
                elif e.status >= 300 and e.status <= 399:
                    status_color_class = 'text-warning'
                elif e.status >= 400 and e.status <= 599:
                    status_color_class = 'text-danger'

                results.append({
                    "url": header_name + e.path,
                    "path": e.path,
                    "status": e.status,
                    "statusColorClass": status_color_class,
                    "contentLength": human_size(e.response.length),
                    "contentType": e.get_content_type(),
                    "redirect": e.response.redirect
                })

        return template.render(metadata=metadata, results=results)

    def get_command(self):
        command = " ".join(sys.argv)
        if '[[' in command or ']]' in command:
            return 'Dirsearch'
        else:
            return command

    def save(self):
        self.file.seek(0)
        self.file.truncate(0)
        self.file.flush()
        self.file.writelines(self.generate())
        self.file.flush()
