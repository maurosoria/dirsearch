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

from lib.core.decorators import locked
from lib.core.settings import COMMAND, DEFAULT_ENCODING, START_TIME
from lib.report.factory import BaseReport, StructuredFileReportMixin


class JSONReport(StructuredFileReportMixin, BaseReport):
    __format__ = "json"
    __extension__ = "json"

    def new(self):
        return {
            "info": {"args": COMMAND, "time": START_TIME},
            "results": [],
        }

    def parse(self, file):
        with open(file, encoding=DEFAULT_ENCODING) as fh:
            return json.load(fh)

    @staticmethod
    def _apply_entry(data, entry):
        data["results"].append(entry)

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

    def write(self, file, data):
        with self._atomic_writer(file) as fh:
            json.dump(data, fh, sort_keys=True, indent=4)
