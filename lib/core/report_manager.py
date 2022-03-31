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

from lib.reports.csv_report import CSVReport
from lib.reports.html_report import HTMLReport
from lib.reports.json_report import JSONReport
from lib.reports.markdown_report import MarkdownReport
from lib.reports.plain_text_report import PlainTextReport
from lib.reports.simple_report import SimpleReport
from lib.reports.xml_report import XMLReport
from lib.reports.sqlite_report import SQLiteReport


class Result:
    def __init__(self, path, response):
        self.path = path
        self.status = response.status
        self.response = response


class Report:
    def __init__(self, host, port, protocol, base_path):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.base_path = base_path[:-1]
        self.results = []
        self.completed = False

    def add_result(self, path, response):
        result = Result(path, response)
        self.results.append(result)


class ReportManager:
    def __init__(self, save_format, output_file):
        self.format = save_format
        self.reports = []
        self.report_obj = None
        self.file = output_file

    def update_report(self, report):
        if not self.file:
            return

        self.write_report()

    def write_report(self):
        if self.report_obj is None:
            if self.format == "plain":
                report = PlainTextReport(self.file, self.reports)
            elif self.format == "json":
                report = JSONReport(self.file, self.reports)
            elif self.format == "xml":
                report = XMLReport(self.file, self.reports)
            elif self.format == "md":
                report = MarkdownReport(self.file, self.reports)
            elif self.format == "csv":
                report = CSVReport(self.file, self.reports)
            elif self.format == "html":
                report = HTMLReport(self.file, self.reports)
            elif self.format == "sqlite":
                report = SQLiteReport(self.file, self.reports)
            else:
                report = SimpleReport(self.file, self.reports)

            self.report_obj = report

        self.report_obj.save()

    def close(self):
        self.report_obj.close()
