import json
import weakref
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.target_progress import TargetProgress
from lib.controller.session import SessionStore
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.execution_config import ScanEngine
from lib.core.scan_run_state import ScanRunState
from lib.core.wordlist_config import WordlistConfig


class TestSessionSnapshot(TestCase):
    def _controller(self):
        controller = object.__new__(Controller)
        controller.run_state = ScanRunState()
        controller.target_progress = TargetProgress()
        controller.start_time = 123.5
        controller.run_state.passed_urls = {"http://done.test/"}
        controller.target_progress.directories = ["current/", "next/"]
        controller.run_state.jobs_processed = 2
        controller.run_state.errors = 1
        controller.run_state.consecutive_errors = 0
        controller.target_progress.base_path = "/"
        controller.target_progress.url = "http://active.test/"
        controller.run_state.old_session = True
        controller.wordlist_config = WordlistConfig()
        controller.dictionary = Dictionary(controller.wordlist_config)
        controller.dictionary.__setstate__((["done", "pending"], 1, ["extra"], 0))
        controller.output_history = [{"start_time": 100, "output": "previous"}]
        controller.run_state.prepare_targets([controller.target_progress.url, "http://next.test/"])
        controller.run_state.activate_next()
        controller._session_options = {"headers": {"X-Test": "prepared"}}
        controller.interface = Mock(buffer="current\n")
        controller.reporter = Mock()
        return controller

    def test_snapshot_detaches_all_mutable_inputs_before_storage(self):
        controller = self._controller()
        prepared = {
            "headers": {"X-Test": "original"}, "urls": [controller.target_progress.url],
            "data": b"\x80\r\n", "extensions": ("html",),
            "include_status_codes": {200}, "proxies": ["http://proxy.test/"],
        }
        snapshot = controller._snapshot_session(prepared, "current")
        controller.target_progress.directories.clear()
        controller.run_state.passed_urls.clear()
        controller.dictionary.reset()
        controller.output_history[0]["output"] = "changed"
        prepared["headers"]["X-Test"] = "changed"
        prepared["urls"].clear()
        prepared["include_status_codes"].add(404)
        prepared["proxies"].clear()

        with TemporaryDirectory() as directory:
            store = SessionStore()
            store.save(snapshot, directory)
            payload = store.load(directory)
        restored_options = store.restore_options(payload["options"])
        self.assertEqual(payload["controller"]["directories"], ["current/", "next/"])
        self.assertEqual(payload["controller"]["passed_urls"], ["http://done.test/"])
        self.assertEqual(payload["dictionary"]["index"], 1)
        self.assertEqual(payload["dictionary"]["extra"], ["extra"])
        self.assertEqual(restored_options, {
            "headers": {"X-Test": "original"}, "urls": [controller.target_progress.url],
            "data": b"\x80\r\n", "extensions": ("html",),
            "include_status_codes": {200}, "proxies": ["http://proxy.test/"],
        })
        self.assertEqual(payload["output_history"], [
            {"start_time": 100, "output": "previous"},
            {"start_time": 123.5, "output": "current"},
        ])

    def test_snapshot_can_be_changed_without_mutating_the_controller(self):
        controller = self._controller()
        snapshot = controller._snapshot_session(controller._session_options, "")
        snapshot.controller["directories"].clear()
        snapshot.dictionary["items"].clear()
        snapshot.options["headers"].clear()
        snapshot.output_history[0]["output"] = "changed"
        self.assertEqual(controller.target_progress.directories, ["current/", "next/"])
        self.assertEqual(controller.dictionary.__getstate__()[0], ["done", "pending"])
        self.assertEqual(controller._session_options["headers"], {"X-Test": "prepared"})
        self.assertEqual(controller.output_history[0]["output"], "previous")

    def test_snapshot_repr_does_not_expose_values(self):
        snapshot = self._controller()._snapshot_session({"auth": "user:private-value"}, "secret-output")
        self.assertEqual(repr(snapshot), "SessionSnapshot()")

    def test_storage_needs_no_live_controller_or_resources(self):
        controller = self._controller()
        reference = weakref.ref(controller)
        snapshot = controller._snapshot_session({}, "")
        del controller
        self.assertIsNone(reference())
        with TemporaryDirectory() as directory, patch("lib.controller.controller.ReportManager") as reports:
            store = SessionStore()
            store.save(snapshot, directory)
            self.assertEqual(store.load(directory)["controller"], snapshot.controller)
            reports.assert_not_called()

    def test_export_does_not_read_global_options(self):
        controller = self._controller()
        with TemporaryDirectory() as directory, patch.dict(options, {
            "headers": {"X-Test": "unrelated"},
        }):
            controller._export(directory)
            checkpoint = Path(directory, SessionStore.CHECKPOINT_FILE)
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        self.assertEqual(payload["options"]["headers"], {"X-Test": "prepared"})

    def test_restore_keeps_legacy_output_and_detaches_runtime_containers(self):
        for history in (None, [], [{"start_time": 90, "output": "older"}]):
            with self.subTest(history=history), TemporaryDirectory() as directory:
                saved = deepcopy(options)
                saved.update(
                    wordlists=[], wordlist_backend="python", raw_file=None,
                    log_file=None, output_formats=[], session_file=None,
                    save_response=None, save_response_jsonl=None,
                )
                store = SessionStore()
                store.save(self._controller()._snapshot_session(saved, "previous output"), directory)
                payload = store.load(directory)
                if history is None:
                    payload.pop("output_history")
                else:
                    payload["output_history"] = deepcopy(history)
                expected_history = history or [{"start_time": 123.5, "output": "previous output"}]
                with (
                    patch.dict(options, {"session_file": directory}),
                    patch.object(SessionStore, "load", return_value=payload),
                    patch.object(Controller, "_confirm_session_overwrite"),
                    patch.object(Controller, "run"),
                ):
                    restored = Controller(output=StringIO())
                self.assertEqual(restored.output_history, expected_history)
                payload["controller"]["directories"].clear()
                payload["dictionary"]["items"].clear()
                payload["dictionary"]["extra"].clear()
                if history:
                    payload["output_history"][0]["output"] = "changed"
                self.assertEqual(restored.target_progress.directories, ["current/", "next/"])
                self.assertEqual(restored.dictionary.__getstate__(), (["done", "pending"], 1, ["extra"], 0))
                self.assertEqual(restored.output_history, expected_history)

    def test_wire_schema_and_repeated_snapshot_writes_are_unchanged(self):
        controller = self._controller()
        snapshot = controller._snapshot_session({"urls": [controller.target_progress.url]}, "current")
        before = deepcopy(snapshot)
        with TemporaryDirectory() as directory:
            store = SessionStore()
            store.save(snapshot, directory)
            checkpoint = Path(directory, SessionStore.CHECKPOINT_FILE)
            first = checkpoint.read_bytes()
            store.save(snapshot, directory)
            self.assertEqual(checkpoint.read_bytes(), first)
            payload = json.loads(first)
        self.assertEqual(snapshot, before)
        self.assertEqual(payload, {
            "version": 1,
            "controller": {
                "start_time": 123.5, "passed_urls": ["http://done.test/"],
                "directories": ["current/", "next/"], "jobs_processed": 2,
                "errors": 1, "consecutive_errors": 0, "base_path": "/",
                "url": "http://active.test/", "old_session": True,
            },
            "dictionary": {"items": ["done", "pending"], "index": 1, "extra": ["extra"], "extra_index": 0},
            "options": {"urls": ["http://active.test/"]},
            "last_output": "current",
            "output_history": [{"start_time": 100, "output": "previous"}, {"start_time": 123.5, "output": "current"}],
        })

    def test_failed_export_preserves_history_and_checkpoint_then_can_retry(self):
        controller = self._controller()
        with TemporaryDirectory() as directory:
            controller._export(directory)
            checkpoint = Path(directory, SessionStore.CHECKPOINT_FILE)
            before = checkpoint.read_bytes()
            history = deepcopy(controller.output_history)
            controller.interface.buffer = "next output"
            for boundary in ("lib.controller.session.json.dump", "lib.utils.file.os.replace"):
                with self.subTest(boundary=boundary), patch(boundary, side_effect=OSError("write failed")):
                    with self.assertRaisesRegex(OSError, "write failed"):
                        controller._export(directory)
                self.assertEqual(checkpoint.read_bytes(), before)
                self.assertEqual(controller.output_history, history)
            controller._export(directory)
            self.assertEqual(controller.output_history, history + [
                {"start_time": 123.5, "output": "next output"},
            ])
            self.assertEqual(SessionStore().load(directory)["output_history"], controller.output_history)

    def test_report_flush_failure_prevents_checkpoint_write(self):
        controller = self._controller()
        controller.reporter.flush.side_effect = OSError("flush failed")
        with TemporaryDirectory() as directory, patch.object(SessionStore, "save") as save:
            with self.assertRaisesRegex(OSError, "flush failed"):
                controller._export(directory)
            save.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_raw_preparation_precedes_snapshot_and_fresh_history_is_not_inherited(self):
        with TemporaryDirectory() as directory:
            # A fresh execution owns its history even when reusing a destination.
            store = SessionStore()
            store.save(self._controller()._snapshot_session({}, "unrelated history"), directory)
            raw_headers = {"X-Raw": "prepared"}

            def run(controller):
                self.assertEqual(controller.output_history, [])
                controller.run_state.prepare_targets(options["urls"])
                controller.run_state.activate_next()
                controller.target_progress.url = "http://raw.test/"
                controller.target_progress.base_path = "/"
                raw_headers["X-Raw"] = "changed"
                controller._export(directory)

            with (
                patch.dict(options, {
                    "session_file": None, "raw_file": "request.txt", "wordlists": [],
                    "wordlist_backend": "python", "request_backend": "python",
                    "log_file": None, "output_formats": [],
                    "save_response": None, "save_response_jsonl": None,
                }),
                patch("lib.controller.controller.parse_raw", return_value=(
                    ["http://raw.test/"], "POST", raw_headers, b"\x80\r\n",
                )),
                patch.object(Controller, "run", new=run),
            ):
                Controller(output=StringIO())
            payload = store.load(directory)
            restored = store.restore_options(payload["options"])
            self.assertEqual(restored["headers"], {"X-Raw": "prepared"})
            self.assertEqual(restored["data"], b"\x80\r\n")
            self.assertEqual(restored["http_method"], "POST")
            self.assertEqual(restored["urls"], ["http://raw.test/"])
            self.assertNotIn("unrelated history", str(payload["output_history"]))

    def test_export_uses_prepared_options_after_fresh_setup_or_resume_for_each_engine(self):
        for engine in ScanEngine:
            for resume in (False, True):
                with self.subTest(engine=engine, resume=resume), TemporaryDirectory() as directory:
                    checkpoint = str(Path(directory, "input"))
                    saved = deepcopy(options)
                    saved.update(
                        request_backend="native" if engine is ScanEngine.NATIVE else "python",
                        async_mode=engine is ScanEngine.ASYNC, wordlist_backend="python",
                        urls=["http://active.test/", "http://next.test/"], wordlists=[],
                        raw_file=None, log_file=None, output_formats=[], session_file=None,
                        headers={"X-Test": "prepared"}, auth="user:prepared-value", data=b"\x80\r\n",
                        save_response=None, save_response_jsonl=None,
                    )
                    if resume:
                        SessionStore().save(self._controller()._snapshot_session(saved, ""), checkpoint)
                    current = deepcopy(saved)
                    if resume:
                        current.update(session_file=checkpoint, headers={"X-Test": "cli-value"}, auth="cli:value")

                    def run(controller):
                        controller.run_state.prepare_targets(saved["urls"])
                        controller.run_state.activate_next()
                        controller.target_progress.url = saved["urls"][0]
                        controller.target_progress.base_path = "/"
                        options["headers"]["X-Test"] = "unrelated"
                        options.update(auth="wrong:value", data="wrong", urls=["http://unrelated.test/"])
                        controller._export(str(Path(directory, "output")))

                    with (
                        patch.dict(options, current, clear=True),
                        patch.object(Controller, "run", new=run),
                        patch.object(Controller, "_confirm_session_overwrite"),
                    ):
                        Controller(output=StringIO())
                    restored = SessionStore().load(str(Path(directory, "output")))
                    restored_options = SessionStore().restore_options(restored["options"])
                    self.assertEqual(restored_options["headers"]["X-Test"], "prepared")
                    self.assertEqual(restored_options["auth"], "user:prepared-value")
                    self.assertEqual(restored_options["data"], b"\x80\r\n")
                    self.assertEqual(restored_options["urls"], saved["urls"])
                    self.assertEqual(restored_options["request_backend"], saved["request_backend"])
                    self.assertEqual(restored_options["async_mode"], saved["async_mode"])
