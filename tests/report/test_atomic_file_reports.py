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


class PartialWriteFailure:
    def __init__(self, file_handle):
        self._file_handle = file_handle

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self._file_handle.close()

    def __getattr__(self, name):
        return getattr(self._file_handle, name)

    def write(self, data):
        self._file_handle.write(data[:3])
        self._file_handle.flush()
        raise OSError("injected report write failure")


class TestAtomicFileReports(TestCase):
    def test_failed_save_preserves_previous_report_for_every_file_format(self):
        real_open = builtins.open
        real_fdopen = os.fdopen

        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in FILE_REPORTS:
                with self.subTest(report=report_class.__name__):
                    report = report_class()
                    destination = os.path.join(
                        directory,
                        f"report-{report_class.__name__}.{extension}",
                    )
                    first_url = "https://example.test/first"
                    second_url = "https://example.test/second"
                    report.initiate(destination)
                    report.save(destination, make_result(first_url))
                    original = Path(destination).read_bytes()

                    def faulting_open(file, mode="r", *args, **kwargs):
                        file_handle = real_open(file, mode, *args, **kwargs)
                        if os.fspath(file) == destination and "w" in mode:
                            return PartialWriteFailure(file_handle)
                        return file_handle

                    def faulting_fdopen(descriptor, mode="r", *args, **kwargs):
                        file_handle = real_fdopen(descriptor, mode, *args, **kwargs)
                        if "w" in mode:
                            return PartialWriteFailure(file_handle)
                        return file_handle

                    with patch("builtins.open", new=faulting_open), patch(
                        "lib.utils.file.os.fdopen",
                        new=faulting_fdopen,
                    ):
                        with self.assertRaisesRegex(
                            OSError,
                            "injected report write failure",
                        ):
                            report.save(destination, make_result(second_url))

                    self.assertEqual(Path(destination).read_bytes(), original)
                    self.assertIn(first_url, original.decode())
                    self.assertNotIn(second_url, original.decode())
                    self.assertEqual(
                        list(Path(directory).glob(f".{Path(destination).name}.*.tmp")),
                        [],
                    )
                    report.validate(destination)

                    report.save(destination, make_result(second_url))
                    recovered = Path(destination).read_text()
                    self.assertIn(first_url, recovered)
                    self.assertIn(second_url, recovered)
