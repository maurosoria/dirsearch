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

from lib.reports import *


class JSONReport(FileBaseReport):
    def generate(self):
        report = {"info":{"time": time.ctime()}, "results": []}

        for entry in self.entries:
            result = {}
            headerName = "{0}://{1}:{2}/{3}".format(
                entry.protocol, entry.host, entry.port, entry.basePath
            )
            result[headerName] = []
            
            for e in entry.results:
                pathEntry = {
                    "status": e.status,
                    "path": "/" + e.path,
                    "content-length": e.getContentLength(),
                    "redirect": e.response.redirect,
                }
                result[headerName].append(pathEntry)

            report["results"].append(result)

        return json.dumps(report, sort_keys=True, indent=4)
