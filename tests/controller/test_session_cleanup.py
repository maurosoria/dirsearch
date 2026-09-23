import os
import sqlite3
import tempfile
from contextlib import closing
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.controller.session import SessionStore
from lib.core.data import options
from lib.report.sqlite_report import SQLiteReport


class DummyFuzzer:
    def __init__(self, *args, **kwargs):
        pass


class TestSessionCleanup(TestCase):
    def setUp(self):
        self.original_options = dict(options)

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def _complete_scan(self, session_path):
        controller = object.__new__(Controller)
        controller.response_stores = ()
        controller.reporter = Mock()
        controller.dictionary = Mock()
        controller.directories = []
        controller.base_path = ""
        controller.old_session = True
        controller.url = "https://example.test/"
        controller.set_target = Mock()
        controller.crawl_target = Mock()
        controller.start = Mock()

        options.update(
            {
                "urls": ["https://example.test/"],
                "request_backend": "python",
                "async_mode": False,
                "subdirs": [],
                "session_file": session_path,
            }
        )

        with (
            patch("lib.connection.requester.Requester", return_value=Mock()),
            patch("lib.core.fuzzer.Fuzzer", DummyFuzzer),
            patch("lib.controller.controller.signal.signal"),
            patch("lib.controller.controller.interface"),
        ):
            controller.run()

    def test_completed_session_preserves_unrelated_directory_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            os.makedirs(session_dir)
            owned_files = (
                *SessionStore.FILES.values(),
                SessionStore.CHECKPOINT_FILE,
            )
            for file_name in owned_files:
                with open(os.path.join(session_dir, file_name), "w", encoding="utf-8"):
                    pass
            unrelated_path = os.path.join(session_dir, "keep.txt")
            with open(unrelated_path, "w", encoding="utf-8") as file_handle:
                file_handle.write("unrelated")

            self._complete_scan(session_dir)

            self.assertTrue(os.path.isfile(unrelated_path))
            for file_name in owned_files:
                self.assertFalse(os.path.exists(os.path.join(session_dir, file_name)))

    def test_completed_session_removes_empty_owned_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            os.makedirs(session_dir)
            for file_name in (
                *SessionStore.FILES.values(),
                SessionStore.CHECKPOINT_FILE,
            ):
                with open(os.path.join(session_dir, file_name), "w", encoding="utf-8"):
                    pass

            self._complete_scan(session_dir)

            self.assertFalse(os.path.exists(session_dir))

    def test_completed_legacy_session_removes_single_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_file = os.path.join(tmpdir, "session.json")
            with open(session_file, "w", encoding="utf-8"):
                pass

            self._complete_scan(session_file)

            self.assertFalse(os.path.exists(session_file))

    def test_session_export_flushes_reports_before_saving_checkpoint(self):
        controller = object.__new__(Controller)
        controller.reporter = Mock()
        events = []
        controller.reporter.flush.side_effect = lambda: events.append("report")

        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = os.path.join(tmpdir, "session")
            with (
                patch.object(
                    SessionStore,
                    "save",
                    side_effect=lambda *args: events.append("session"),
                ),
            ):
                controller._export(session_path)

        self.assertEqual(events, ["report", "session"])

    def test_run_failure_finishes_report_and_commits_pending_sqlite_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database = os.path.join(tmpdir, "report.sqlite")
            report = SQLiteReport(commit_batch_size=10)

            def setup(controller):
                controller.reporter = report
                report.initiate(database, "results")
                report.save(
                    database,
                    "results",
                    SimpleNamespace(
                        datetime="2026-09-23 07:30:00",
                        url="https://example.test/admin",
                        status=200,
                        length=42,
                        type="text/plain",
                        redirect="",
                    ),
                )

            def fail_run(controller):
                raise RuntimeError("scan failed")

            try:
                with (
                    patch.dict(options, {"session_file": None}),
                    patch.object(Controller, "setup", new=setup),
                    patch.object(Controller, "run", new=fail_run),
                    self.assertRaisesRegex(RuntimeError, "scan failed"),
                ):
                    Controller()

                with closing(sqlite3.connect(database)) as connection:
                    rows = connection.execute(
                        'SELECT url FROM "results" ORDER BY rowid'
                    ).fetchall()

                self.assertEqual(rows, [("https://example.test/admin",)])
            finally:
                report.finish()
