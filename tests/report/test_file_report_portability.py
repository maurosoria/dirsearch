# -*- coding: utf-8 -*-

import builtins
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from lib.report.csv_report import CSVReport
from lib.report.html_report import HTMLReport
from lib.report.json_report import JSONReport
from lib.report.markdown_report import MarkdownReport
from lib.report.plain_text_report import PlainTextReport
from lib.report.simple_report import SimpleReport
from lib.report.xml_report import XMLReport


FILE_REPORTS = (
    (SimpleReport, "txt"),
    (PlainTextReport, "txt"),
    (JSONReport, "json"),
    (XMLReport, "xml"),
    (MarkdownReport, "md"),
    (CSVReport, "csv"),
    (HTMLReport, "html"),
)

TEXT_PARSE_REPORTS = (
    (SimpleReport, "txt"),
    (PlainTextReport, "txt"),
    (JSONReport, "json"),
    (MarkdownReport, "md"),
    (CSVReport, "csv"),
    (HTMLReport, "html"),
)


def make_result():
    return SimpleNamespace(
        datetime="2026-09-13 07:30:00",
        url="https://example.test/测试/🙂",
        status=200,
        length=42,
        type="text/plain",
        redirect="/café",
        elapsed=0.25,
    )


class TestFileReportPortability(TestCase):
    def test_reports_write_utf8_when_platform_default_is_ascii(self):
        real_fdopen = os.fdopen

        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in FILE_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"report-{report_class.__name__}.{extension}",
                    )
                    encodings = []

                    def ascii_default_fdopen(descriptor, mode="r", *args, **kwargs):
                        if "b" not in mode:
                            encodings.append(kwargs.get("encoding"))
                            if kwargs.get("encoding") is None:
                                kwargs["encoding"] = "ascii"
                        return real_fdopen(descriptor, mode, *args, **kwargs)

                    report = report_class()
                    with patch(
                        "lib.utils.file.os.fdopen",
                        new=ascii_default_fdopen,
                    ):
                        report.initiate(destination)
                        report.save(destination, make_result())

                    self.assertTrue(encodings)
                    self.assertEqual(set(encodings), {"utf-8"})
                    Path(destination).read_text(encoding="utf-8")

    def test_reports_read_utf8_when_platform_default_is_ascii(self):
        real_open = builtins.open

        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in TEXT_PARSE_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"report-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    report.save(destination, make_result())
                    encodings = []

                    def ascii_default_open(file, mode="r", *args, **kwargs):
                        if os.fspath(file) == destination and "b" not in mode:
                            encodings.append(kwargs.get("encoding"))
                            if kwargs.get("encoding") is None:
                                kwargs["encoding"] = "ascii"
                        return real_open(file, mode, *args, **kwargs)

                    with patch("builtins.open", new=ascii_default_open):
                        report.validate(destination)

                    self.assertTrue(encodings)
                    self.assertEqual(set(encodings), {"utf-8"})

    def test_csv_disables_windows_newline_translation(self):
        real_fdopen = os.fdopen

        with tempfile.TemporaryDirectory() as directory:
            destination = os.path.join(directory, "report.csv")

            def windows_fdopen(descriptor, mode="r", *args, **kwargs):
                if "b" not in mode and kwargs.get("newline") is None:
                    kwargs["newline"] = "\r\n"
                return real_fdopen(descriptor, mode, *args, **kwargs)

            report = CSVReport()
            with patch("lib.utils.file.os.fdopen", new=windows_fdopen):
                report.initiate(destination)
                report.save(destination, make_result())

            contents = Path(destination).read_bytes()
            self.assertNotIn(b"\r\r\n", contents)
            self.assertEqual(contents.count(b"\r\n"), 2)
