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

from defusedcsv import csv

from lib.core.decorators import locked
from lib.report.factory import BaseReport, FileReportMixin


class CSVReport(FileReportMixin, BaseReport):
    __format__ = "csv"
    __extension__ = "csv"

    def new(self):
        return [["URL", "Status", "Size", "Content Type", "Redirection"]]

    def parse(self, file):
        with open(file) as fh:
            rows = list(csv.reader(fh, delimiter=",", quotechar='"'))
            # Not a dirsearch CSV report
            if rows[0] != self.new()[0]:
                raise Exception

            return rows

    @locked
    def save(self, file, result):
        rows = self.parse(file)
        rows.append([result.url, result.status, result.length, result.type, result.redirect])
        self.write(file, rows)

    def write(self, file, rows):
        with open(file, "w") as fh:
            writer = csv.writer(fh, delimiter=",", quotechar='"')
            for row in rows:
                writer.writerow(row)
