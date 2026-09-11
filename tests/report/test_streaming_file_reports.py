# -*- coding: utf-8 -*-

import os
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from lib.report.csv_report import CSVReport
from lib.report.markdown_report import MarkdownReport
from lib.report.plain_text_report import PlainTextReport
from lib.report.simple_report import SimpleReport


APPENDABLE_REPORTS = (
    (SimpleReport, "txt"),
    (PlainTextReport, "txt"),
    (MarkdownReport, "md"),
    (CSVReport, "csv"),
)


def make_result(url):
    return SimpleNamespace(
        datetime="2026-09-11 06:00:00",
        url=url,
        status=200,
        length=42,
        type="text/plain",
        redirect="",
        elapsed=0.25,
    )


class TestStreamingFileReports(TestCase):
    def test_saves_do_not_reparse_or_replace_appendable_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in APPENDABLE_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"report-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)

                    with patch.object(
                        report,
                        "parse",
                        side_effect=AssertionError("save reparsed the report"),
                    ), patch.object(
                        report,
                        "write",
                        side_effect=AssertionError("save replaced the report"),
                    ):
                        report.save(
                            destination,
                            make_result("https://example.test/first"),
                        )
                        report.save(
                            destination,
                            make_result("https://example.test/second"),
                        )

                    report.validate(destination)
                    with open(destination, encoding="utf-8") as report_file:
                        contents = report_file.read()
                    self.assertLess(
                        contents.index("https://example.test/first"),
                        contents.index("https://example.test/second"),
                    )

                    resumed_report = report_class()
                    resumed_report.initiate(destination)
                    with patch.object(
                        resumed_report,
                        "parse",
                        side_effect=AssertionError("save reparsed the report"),
                    ), patch.object(
                        resumed_report,
                        "write",
                        side_effect=AssertionError("save replaced the report"),
                    ):
                        resumed_report.save(
                            destination,
                            make_result("https://example.test/third"),
                        )

                    resumed_report.validate(destination)
                    with open(destination, encoding="utf-8") as report_file:
                        resumed_contents = report_file.read()
                    self.assertLess(
                        resumed_contents.index("https://example.test/second"),
                        resumed_contents.index("https://example.test/third"),
                    )
