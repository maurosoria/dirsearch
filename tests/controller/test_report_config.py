import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from lib.connection.response import NativeResponse
from lib.controller.controller import Controller
from lib.core.scan_run_state import ScanRunState
from lib.core.target_progress import TargetProgress
from lib.controller.session import SessionStore
from lib.controller.session_snapshot import RunCheckpoint, SessionSnapshot
from lib.core.task_checkpoint import DictionaryCheckpoint, TaskCheckpoint
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.report_config import ReportConfig
from lib.core.wordlist_config import WordlistConfig


class TestSessionReportConfiguration(TestCase):
    def test_restore_uses_supplied_report_policy_not_process_globals(self):
        saved_options = {
            "output_formats": ["sqlite"],
            "output_file": "saved.sqlite",
            "output_table": "saved_results",
            "mysql_url": None,
            "postgres_url": None,
            "sqlite_commit_batch_size": 3,
        }
        payload = SessionSnapshot(
            run=RunCheckpoint(0), task_checkpoint=TaskCheckpoint(DictionaryCheckpoint((), 0)), options={},
        )
        controller = object.__new__(Controller)
        controller.wordlist_config = WordlistConfig()
        with patch.dict(options, {
            "output_file": "other.sqlite",
            "output_table": "other_results",
            "sqlite_commit_batch_size": 99,
        }):
            controller._restore_session(payload, ReportConfig.from_options(saved_options))
        try:
            self.assertEqual(len(controller.reporter.reports), 1)
            reporter, sources = controller.reporter.reports[0]
            self.assertEqual(sources, ["saved.sqlite", "saved_results"])
            self.assertEqual(reporter._commit_batch_size, 3)
        finally:
            controller.reporter.finish()

    def test_setup_and_real_checkpoint_restore_keep_report_policy_across_targets(self):
        for backend, async_mode in (("python", False), ("python", True), ("native", False)):
            for resumed in (False, True):
                with self.subTest(backend=backend, async_mode=async_mode, resumed=resumed), TemporaryDirectory() as directory:
                    saved_options = dict(options)
                    saved_options.update(
                        request_backend=backend, async_mode=async_mode,
                        session_file=None, wordlist_backend="python", wordlists=[],
                        raw_file=None, log_file=None, save_response=None, save_response_jsonl=None,
                        urls=["https://first.test/", "https://second.test/"],
                        output_formats=["json", "sqlite"],
                        output_file=str(Path(directory, "report-{host}-{format}.{extension}")),
                        output_table="saved_results", sqlite_commit_batch_size=3,
                        mysql_url=None, postgres_url=None,
                    )
                    checkpoint = str(Path(directory, "checkpoint.json"))
                    if resumed:
                        saved_controller = SimpleNamespace(
                            start_time=0, run_state=ScanRunState(saved_options["urls"]),
                            target_progress=TargetProgress(), output_history=[],
                            dictionary=Dictionary(WordlistConfig()),
                        )
                        SessionStore().save(
                            Controller._snapshot_session(saved_controller, saved_options, ""), checkpoint
                        )

                    def run(controller):
                        self.assertEqual(controller.reporter.config, ReportConfig.from_options(saved_options))
                        options.update(
                            output_formats=[], output_file=str(Path(directory, "wrong")),
                            output_table="wrong_table", sqlite_commit_batch_size=99,
                        )
                        for host in ("first.test", "second.test"):
                            target = "https://" + host + "/"
                            controller.reporter.prepare(target)
                            controller.reporter.save(NativeResponse(
                                target + "item", 200, [("Content-Type", "text/plain")], b"found",
                            ))
                        controller.reporter.flush()

                    current_options = dict(saved_options)
                    if resumed:
                        current_options.update(
                            session_file=checkpoint, output_formats=[],
                            output_file=str(Path(directory, "wrong")),
                            output_table="wrong_table", sqlite_commit_batch_size=99,
                        )
                    with (
                        patch.dict(options, current_options),
                        patch.object(Controller, "run", new=run),
                        patch.object(Controller, "_confirm_session_overwrite"),
                        patch("lib.controller.controller.Dictionary", return_value=Dictionary(WordlistConfig())),
                        patch("lib.controller.controller.create_terminal"),
                    ):
                        controller = Controller()
                    for host in ("first.test", "second.test"):
                        expected_url = "https://" + host + "/item"
                        json_path = Path(directory, f"report-{host}-json.json")
                        rows = json.loads(json_path.read_text(encoding="utf-8"))["results"]
                        self.assertEqual([row["url"] for row in rows], [expected_url])
                        with closing(sqlite3.connect(Path(directory, f"report-{host}-sql.sqlite"))) as connection:
                            self.assertEqual(
                                connection.execute('SELECT url FROM "saved_results"').fetchall(),
                                [(expected_url,)],
                            )
                    self.assertFalse(Path(directory, "wrong").exists())
                    self.assertIsNone(controller.reporter.reports[1][0]._conn)
