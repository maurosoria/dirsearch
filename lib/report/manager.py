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
from lib.core.settings import STANDARD_PORTS, START_TIME
from lib.report.csv_report import CSVReport
from lib.report.html_report import HTMLReport
from lib.report.json_report import JSONReport
from lib.report.markdown_report import MarkdownReport
from lib.report.plain_text_report import PlainTextReport
from lib.report.simple_report import SimpleReport
from lib.report.sqlite_report import SQLiteReport
from lib.report.xml_report import XMLReport
from lib.utils.file import FileUtils

# Store option keys so restored session destinations are resolved at manager creation.
output_handlers = {
    "simple": (SimpleReport, ("output_file",)),
    "plain": (PlainTextReport, ("output_file",)),
    "json": (JSONReport, ("output_file",)),
    "xml": (XMLReport, ("output_file",)),
    "md": (MarkdownReport, ("output_file",)),
    "csv": (CSVReport, ("output_file",)),
    "html": (HTMLReport, ("output_file",)),
    "sqlite": (SQLiteReport, ("output_file", "output_table")),
    "mysql": (
        "lib.report.mysql_report",
        "MySQLReport",
        ("mysql_url", "output_table"),
    ),
    "postgresql": (
        "lib.report.postgresql_report",
        "PostgreSQLReport",
        ("postgres_url", "output_table"),
    ),
}


class ReportManager:
    def __init__(self, formats):
        self.reports = []

        for format in formats:
            # No output location provided
            handler = output_handlers[format]
            sources = [options[key] for key in handler[-1]]
            if any(not _ for _ in sources):
                continue
            self.reports.append((self._load_report(handler)(), sources))

    def _load_report(self, handler):
        if len(handler) == 2:
            return handler[0]

        from importlib import import_module

        module_name, class_name, _ = handler
        module = import_module(module_name)
        return getattr(module, class_name)

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

    def flush(self):
        for reporter, sources in self.reports:
            reporter.flush()

    def finish(self):
        for reporter, sources in self.reports:
            reporter.finish()

    def format(self, string, target, handler):
        parsed = urlparse(target)

        return string.format(
            datetime=FileUtils.format_datetime_for_path(START_TIME),
            date=START_TIME.split()[0],
            host=parsed.hostname,
            scheme=parsed.scheme,
            port=parsed.port or STANDARD_PORTS[parsed.scheme],
            format=handler.__format__,
            extension=handler.__extension__,
        )
