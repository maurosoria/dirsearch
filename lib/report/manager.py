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

from urllib.parse import urlparse

from lib.core.data import options
from lib.core.settings import STANDARD_PORTS, START_DATETIME
from lib.report.csv_report import CSVReport
from lib.report.html_report import HTMLReport
from lib.report.json_report import JSONReport
from lib.report.markdown_report import MarkdownReport
from lib.report.mysql_report import MySQLReport
from lib.report.plain_text_report import PlainTextReport
from lib.report.postgresql_report import PostgreSQLReport
from lib.report.simple_report import SimpleReport
from lib.report.sqlite_report import SQLiteReport
from lib.report.xml_report import XMLReport


output_handlers = {
    "simple": (SimpleReport, [options["output_file"]]),
    "plain": (PlainTextReport, [options["output_file"]]),
    "json": (JSONReport, [options["output_file"]]),
    "xml": (XMLReport, [options["output_file"]]),
    "md": (MarkdownReport, [options["output_file"]]),
    "csv": (CSVReport, [options["output_file"]]),
    "html": (HTMLReport, [options["output_file"]]),
    "sqlite": (SQLiteReport, [options["output_file"], options["output_table"]]),
    "mysql": (MySQLReport, [options["mysql_url"], options["output_table"]]),
    "postgresql": (PostgreSQLReport, [options["postgres_url"], options["output_table"]]),
}


class ReportManager:
    def __init__(self, formats):
        self.reports = []

        for format in formats:
            # No output location provided
            if any(not _ for _ in output_handlers[format][1]):
                continue
            self.reports.append((output_handlers[format][0](), output_handlers[format][1]))

    def prepare(self, target):
        for reporter, sources in self.reports:
            reporter.initiate(
                *map(
                    lambda s: self.format(s, target, reporter),
                    sources,
                )
            )

    def save(self, result):
        for reporter, sources in self.reports:
            reporter.save(
                *map(
                    lambda s: self.format(s, result.url, reporter),
                    sources,
                ),
                result,
            )

    def finish(self):
        for reporter, sources in self.reports:
            reporter.finish()

    def format(self, string, target, handler):
        parsed = urlparse(target)

        return string.format(
            # Get date from datetime string
            date=START_DATETIME.split()[0],
            host=parsed.hostname,
            scheme=parsed.scheme,
            port=parsed.port or STANDARD_PORTS[parsed.scheme],
            format=handler.__format__,
            extension=handler.__extension__,
        )
