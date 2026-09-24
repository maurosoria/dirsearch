import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from lib.controller.session import SessionStore
from lib.core.data import options
from lib.report.manager import ReportManager


class DummyReport:
    __format__ = "dummy"
    __extension__ = "txt"


class BlockingReport(DummyReport):
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def save(self, _destination, _result):
        self.entered.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test did not release blocked report write")
        self.finished.set()


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

    def test_finish_attempts_every_report_before_reraising_first_error(self):
        first = Mock()
        second = Mock()
        first.finish.side_effect = OSError("first close failed")
        manager = ReportManager([])
        manager.reports = [(first, []), (second, [])]

        with self.assertRaisesRegex(OSError, "first close failed"):
            manager.finish()

        first.finish.assert_called_once_with()
        second.finish.assert_called_once_with()


class TestAsyncReportManager(IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_options = dict(options)

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    async def test_async_save_without_reports_avoids_thread_handoff(self):
        manager = ReportManager([])

        with patch(
            "lib.report.manager.asyncio.to_thread",
            side_effect=AssertionError("empty report manager used a thread"),
        ):
            await manager.save_async(
                make_result("https://example.test/admin")
            )

    async def test_concurrent_async_saves_preserve_file_and_sqlite_results(self):
        with TemporaryDirectory() as directory:
            options.update(
                {
                    "output_file": str(
                        Path(directory, "report-{format}.{extension}")
                    ),
                    "output_table": "results",
                }
            )
            manager = ReportManager(["json", "sqlite"])
            manager.prepare("https://example.test/")
            urls = {
                f"https://example.test/result-{index}"
                for index in range(8)
            }

            await asyncio.gather(
                *(manager.save_async(make_result(url)) for url in urls)
            )
            manager.finish()

            json_path = Path(directory, "report-json.json")
            sqlite_path = Path(directory, "report-sql.sqlite")
            json_urls = {
                result["url"]
                for result in json.loads(
                    json_path.read_text(encoding="utf-8")
                )["results"]
            }
            with closing(sqlite3.connect(sqlite_path)) as connection:
                sqlite_urls = {
                    row[0]
                    for row in connection.execute(
                        'SELECT url FROM "results"'
                    ).fetchall()
                }

        self.assertEqual(json_urls, urls)
        self.assertEqual(sqlite_urls, urls)

    async def test_async_save_keeps_event_loop_responsive(self):
        manager = ReportManager([])
        report = BlockingReport()
        manager.reports = [(report, ["unused"])]
        entered_waiter = asyncio.create_task(
            asyncio.to_thread(report.entered.wait, 2)
        )
        await asyncio.sleep(0)

        save_task = asyncio.create_task(
            manager.save_async(make_result("https://example.test/admin"))
        )
        try:
            self.assertTrue(await entered_waiter)
            probe = asyncio.Event()
            asyncio.get_running_loop().call_soon(probe.set)
            await asyncio.wait_for(probe.wait(), timeout=0.5)
            self.assertFalse(save_task.done())
        finally:
            report.release.set()
            await asyncio.wait_for(
                asyncio.gather(save_task, return_exceptions=True),
                timeout=2,
            )

        self.assertTrue(report.finished.is_set())

    async def test_async_save_cancellation_drains_started_write(self):
        manager = ReportManager([])
        report = BlockingReport()
        manager.reports = [(report, ["unused"])]
        save_task = asyncio.create_task(
            manager.save_async(make_result("https://example.test/admin"))
        )

        try:
            self.assertTrue(await asyncio.to_thread(report.entered.wait, 2))
            save_task.cancel()
            await asyncio.sleep(0)
            save_task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(
                save_task.done(),
                "repeated cancellation returned while the report write was active",
            )
        finally:
            report.release.set()

        results = await asyncio.wait_for(
            asyncio.gather(save_task, return_exceptions=True),
            timeout=2,
        )
        self.assertIsInstance(results[0], asyncio.CancelledError)
        self.assertTrue(report.finished.is_set())
