import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from lib.controller.session import SessionStore
from lib.core.data import options
from lib.report.manager import ReportManager


class DummyReport:
    __format__ = "dummy"
    __extension__ = "txt"


def make_result(url):
    return SimpleNamespace(
        datetime="2026-09-05 23:45:00",
        url=url,
        status=200,
        length=42,
        type="text/plain",
        redirect="",
        elapsed=0.25,
    )


class TestReportManagerDestinations(TestCase):
    def setUp(self):
        self.original_options = dict(options)

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def test_uses_destinations_restored_after_report_module_import(self):
        output_file = "/tmp/restored-{format}.{extension}"
        output_table = "restored_results"
        mysql_url = "mysql://user:pass@example.test/db"
        postgres_url = "postgresql://user:pass@example.test/db"
        restored = SessionStore({}).restore_options(
            {
                "output_file": output_file,
                "output_table": output_table,
                "mysql_url": mysql_url,
                "postgres_url": postgres_url,
            }
        )
        options.update(restored)
        expected_sources = {
            "simple": [output_file],
            "plain": [output_file],
            "json": [output_file],
            "xml": [output_file],
            "md": [output_file],
            "csv": [output_file],
            "html": [output_file],
            "sqlite": [output_file, output_table],
            "mysql": [mysql_url, output_table],
            "postgresql": [postgres_url, output_table],
        }

        with patch.object(ReportManager, "_load_report", return_value=DummyReport):
            for report_format, sources in expected_sources.items():
                with self.subTest(report_format=report_format):
                    manager = ReportManager([report_format])
                    self.assertEqual(len(manager.reports), 1)
                    self.assertEqual(manager.reports[0][1], sources)

    def test_sqlite_report_uses_configured_commit_batch_size(self):
        options.update(
            {
                "output_file": "/tmp/report.sqlite",
                "output_table": "results",
                "sqlite_commit_batch_size": 25,
            }
        )

        manager = ReportManager(["sqlite"])

        self.assertEqual(manager.reports[0][0]._commit_batch_size, 25)

    @patch("lib.report.manager.START_TIME", "2026-09-13 07:30:45")
    def test_datetime_token_is_safe_for_windows_paths(self):
        manager = ReportManager([])

        destination = manager.format(
            "report-{datetime}.{extension}",
            "https://example.test/",
            DummyReport,
        )

        self.assertEqual(destination, "report-2026-09-13_07-30-45.txt")

    def test_restored_file_and_sqlite_reports_persist_results(self):
        with TemporaryDirectory() as directory:
            output_file = str(Path(directory, "report-{format}.{extension}"))
            options.update(
                SessionStore({}).restore_options(
                    {
                        "output_file": output_file,
                        "output_table": "results",
                    }
                )
            )
            manager = ReportManager(["json", "sqlite"])

            self.assertEqual(len(manager.reports), 2)
            manager.prepare("https://example.test/")
            manager.save(make_result("https://example.test/admin"))
            manager.finish()

            json_path = Path(directory, "report-json.json")
            sqlite_path = Path(directory, "report-sql.sqlite")
            json_results = json.loads(json_path.read_text(encoding="utf-8"))[
                "results"
            ]
            with closing(sqlite3.connect(sqlite_path)) as connection:
                sqlite_rows = connection.execute(
                    'SELECT url, status_code FROM "results"'
                ).fetchall()

        self.assertEqual(
            json_results,
            [
                {
                    "contentLength": 42,
                    "contentType": "text/plain",
                    "elapsed": 0.25,
                    "redirect": "",
                    "status": 200,
                    "url": "https://example.test/admin",
                }
            ],
        )
        self.assertEqual(sqlite_rows, [("https://example.test/admin", 200)])

    def test_formats_without_a_current_destination_are_skipped(self):
        options.update(
            {
                "output_file": None,
                "output_table": "results",
                "mysql_url": None,
            }
        )

        with patch.object(ReportManager, "_load_report") as load_report:
            manager = ReportManager(["json", "mysql"])

        self.assertEqual(manager.reports, [])
        load_report.assert_not_called()
