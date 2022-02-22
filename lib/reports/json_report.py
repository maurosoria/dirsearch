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
import time
import sys

from lib.core.decorators import locked
from lib.reports.base import FileBaseReport


class JSONReport(FileBaseReport):
    def generate(self):
        report = {"info": {"args": ' '.join(sys.argv), "time": time.ctime()}, "results": []}

        for entry in self.entries:
            result = {}
            header_name = "{.protocol}://{.host}:{.port}/{.base_path}".format(entry)
            result[header_name] = []

            for result in entry.results:
                path_entry = {
                    "status": result.status,
                    "path": "/" + result.path,
                    "content-length": result.response.length,
                    "content-type": result.content_type,
                    "redirect": result.response.redirect,
                }
                result[header_name].append(path_entry)

            report["results"].append(result)

        return json.dumps(report, sort_keys=True, indent=4)

    @locked
    def save(self):
        self.file.seek(0)
        self.file.truncate(0)
        self.file.flush()
        self.file.writelines(self.generate())
        self.file.flush()
