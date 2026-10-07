import json
import weakref
from copy import deepcopy
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from lib.core.run_config import RunConfig
from lib.controller.controller import Controller
from lib.core.target_progress import TargetProgress
from lib.controller.session import SessionStore
from lib.controller.session_options import SessionOptions
from lib.controller.session_snapshot import RunCheckpoint, SessionSnapshot
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.execution_config import ScanEngine
from lib.core.native_runtime import is_native_backend_available
from lib.core.run_metadata import RunMetadata
from lib.core.scan_run_state import ScanRunState
from lib.core.task_spec import TaskSpec
from lib.core.wordlist_backend import NativeWordlistChunk
from lib.core.wordlist_config import WordlistConfig


class TestSessionSnapshot(TestCase):
    def _controller(self):
        controller = object.__new__(Controller)
        controller.config = RunConfig()
        controller.metadata = RunMetadata("dirsearch", "2026-10-06 12:00:00")
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
        controller.dictionary = Dictionary(controller.config.wordlist)
        controller.dictionary.__setstate__((["done", "pending"], 1, ["extra"], 0))
        controller.output_history = [{"start_time": 100, "output": "previous"}]
        controller.run_state.prepare_targets([controller.target_progress.url, "http://next.test/"])
        controller.run_state.activate_next()
        controller.session_options = SessionOptions({"headers": {"X-Test": "prepared"}})
        controller.interface = Mock(buffer="current\n")
        controller.reporter = Mock()
        return controller

    def test_snapshot_detaches_all_mutable_inputs_before_storage(self):
        controller = self._controller()
        prepared = {
            "headers": {"X-Test": "original"},
            "urls": ["http://unrelated-input.test/"],
            "data": b"\x80\r\n", "extensions": ("html",),
            "include_status_codes": {200}, "proxies": ["http://proxy.test/"],
        }
        snapshot = controller._snapshot_session(SessionOptions.from_options(prepared), "current")
        controller.target_progress.directories.clear()
        controller.run_state.passed_urls.clear()
        controller.run_state.finish_active()
        controller.run_state.prepare_targets([])
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
        restored_options = payload.options.to_options()
        self.assertEqual(payload.task_checkpoint.directories, ("current/", "next/"))
        self.assertEqual(payload.run.passed_urls, ("http://done.test/",))
        self.assertEqual(payload.task_checkpoint.dictionary.index, 1)
        self.assertEqual(payload.task_checkpoint.dictionary.extra, ("extra",))
        self.assertEqual([task.target for task in payload.remaining_tasks], ["http://active.test/", "http://next.test/"])
        self.assertEqual(restored_options, {
            "headers": {"X-Test": "original"},
            "data": b"\x80\r\n", "extensions": ("html",),
            "include_status_codes": {200}, "proxies": ["http://proxy.test/"],
        })
        self.assertEqual(payload.output_history, [
            {"start_time": 100, "output": "previous"},
            {"start_time": 123.5, "output": "current"},
        ])

    def test_snapshot_can_be_changed_without_mutating_the_controller(self):
        controller = self._controller()
        snapshot = controller._snapshot_session(controller.session_options, "")
        snapshot.task_checkpoint = replace(snapshot.task_checkpoint, directories=())
        snapshot.task_checkpoint = replace(snapshot.task_checkpoint, dictionary=replace(snapshot.task_checkpoint.dictionary, items=()))
        snapshot.options = SessionOptions({"headers": {}})
        snapshot.output_history[0]["output"] = "changed"
        self.assertEqual(controller.target_progress.directories, ["current/", "next/"])
        self.assertEqual(controller.dictionary.__getstate__()[0], ["done", "pending"])
        self.assertEqual(controller.session_options.to_options()["headers"], {"X-Test": "prepared"})
        self.assertEqual(controller.output_history[0]["output"], "previous")

    def test_snapshot_repr_does_not_expose_values(self):
        snapshot = self._controller()._snapshot_session(SessionOptions({"auth": "user:private-value"}), "secret-output")
        self.assertEqual(repr(snapshot), "SessionSnapshot()")

    def test_storage_needs_no_live_controller_or_resources(self):
        controller = self._controller()
        reference = weakref.ref(controller)
        snapshot = controller._snapshot_session(SessionOptions(), "")
        del controller
        self.assertIsNone(reference())
        with TemporaryDirectory() as directory, patch("lib.controller.controller.ReportManager") as reports:
            store = SessionStore()
            store.save(snapshot, directory)
            self.assertEqual(store.load(directory), snapshot)
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

    def test_export_uses_invocation_date_without_changing_checkpoint_clock(self):
        controller = self._controller()
        controller.metadata = RunMetadata("dirsearch", "2026-10-05 23:59:59")
        with TemporaryDirectory() as directory:
            path = str(Path(directory, "session-{date}-{datetime}"))
            with patch("time.strftime", return_value="2026-10-06 00:00:01"):
                controller._export(path)
            expected = Path(directory, "session-2026-10-05-2026-10-05_23-59-59")
            snapshot = SessionStore().load(str(expected))
            wire = json.loads((expected / SessionStore.CHECKPOINT_FILE).read_text(encoding="utf-8"))
        self.assertEqual(snapshot.run.start_time, 123.5)
        self.assertEqual(snapshot.task_checkpoint.dictionary.index, 1)
        self.assertNotIn("metadata", wire)

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
                store.save(self._controller()._snapshot_session(SessionOptions.from_options(saved), "previous output"), directory)
                checkpoint = Path(directory, SessionStore.CHECKPOINT_FILE)
                payload = json.loads(checkpoint.read_text(encoding="utf-8"))
                if history is None:
                    payload.pop("output_history")
                else:
                    payload["output_history"] = deepcopy(history)
                checkpoint.write_text(json.dumps(payload), encoding="utf-8")
                snapshot = store.load(directory)
                expected_history = history or [{"start_time": 123.5, "output": "previous output"}]
                with (
                    patch.dict(options, {"session_file": directory}),
                    patch.object(SessionStore, "load", return_value=snapshot),
                    patch.object(Controller, "_confirm_session_overwrite"),
                    patch.object(Controller, "run"),
                ):
                    restored = Controller(output=StringIO())
                self.assertEqual(restored.output_history, expected_history)
                snapshot.task_checkpoint = replace(snapshot.task_checkpoint, directories=())
                snapshot.task_checkpoint = replace(snapshot.task_checkpoint, dictionary=replace(snapshot.task_checkpoint.dictionary, items=(), extra=()))
                if history:
                    snapshot.output_history[0]["output"] = "changed"
                self.assertEqual(restored.target_progress.directories, ["current/", "next/"])
                self.assertEqual(restored.dictionary.__getstate__(), (["done", "pending"], 1, ["extra"], 0))
                self.assertEqual(restored.output_history, expected_history)

    def test_wire_schema_and_repeated_snapshot_writes_are_unchanged(self):
        controller = self._controller()
        snapshot = controller._snapshot_session(SessionOptions(), "current")
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
            "options": {"urls": ["http://active.test/", "http://next.test/"]},
            "last_output": "current",
            "output_history": [{"start_time": 100, "output": "previous"}, {"start_time": 123.5, "output": "current"}],
        })

    def test_option_wire_types_and_unknown_fields_survive_repeated_load_save(self):
        values = {
            "data": b"\x80\r\n", "headers": {"X-Unicode": "café"},
            "auth": None, "include_status_codes": {200}, "extensions": ("html",),
            "match_sizes": [[1, 3]], "proxies": [],
            "unknown_option": {"nested": [None, False, "retained"]},
        }
        snapshot = self._controller()._snapshot_session(SessionOptions(values), "")
        expected = {
            **values,
            "data": {SessionStore.SESSION_BYTES_MARKER: "gA0K"},
            "include_status_codes": [200], "extensions": ["html"],
            "urls": ["http://active.test/", "http://next.test/"],
        }
        with TemporaryDirectory() as directory:
            store = SessionStore()
            store.save(snapshot, directory)
            checkpoint = Path(directory, store.CHECKPOINT_FILE)
            before = checkpoint.read_bytes()
            self.assertEqual(json.loads(before)["options"], expected)
            loaded = store.load(directory)
            self.assertEqual(loaded.options.to_options(), values)
            self.assertIsInstance(loaded.options.to_options()["include_status_codes"], set)
            self.assertIsInstance(loaded.options.to_options()["extensions"], tuple)
            # Restoration receives disposable input, never the persistence owner.
            exported = loaded.options.to_options()
            exported["headers"].clear()
            exported["unknown_option"]["nested"].clear()
            exported["data"] = b"changed"
            store.save(loaded, directory)
            self.assertEqual(checkpoint.read_bytes(), before)
            self.assertEqual(store.load(directory), snapshot)

    def test_changing_save_destination_does_not_rewrite_captured_options(self):
        controller = self._controller()
        controller.session_options = SessionOptions({"session_file": "old", "headers": {"X-Test": "yes"}})
        captured = controller._snapshot_session(controller.session_options, "")
        self.assertIs(captured.options, controller.session_options)
        controller.session_options = controller.session_options.with_session_file(None)
        current = controller._snapshot_session(controller.session_options, "")
        with TemporaryDirectory() as directory:
            store = SessionStore()
            store.save(captured, directory)
            self.assertEqual(store.load(directory).options.to_options()["session_file"], "old")
            store.save(current, directory)
            self.assertIsNone(store.load(directory).options.to_options()["session_file"])
        self.assertEqual(captured.options.to_options()["headers"], {"X-Test": "yes"})

    def test_snapshot_rejects_untyped_option_payloads(self):
        snapshot = self._controller()._snapshot_session(SessionOptions(), "")
        for values in ({}, {"auth": "private-value"}, [], None):
            with self.subTest(type=type(values)), self.assertRaisesRegex(
                TypeError, "^SessionSnapshot.options must be SessionOptions$"
            ):
                replace(snapshot, options=values)

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
            self.assertEqual(SessionStore().load(directory).output_history, controller.output_history)

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
            store.save(self._controller()._snapshot_session(SessionOptions(), "unrelated history"), directory)
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
            restored = payload.options.to_options()
            self.assertEqual(restored["headers"], {"X-Raw": "prepared"})
            self.assertEqual(restored["data"], b"\x80\r\n")
            self.assertEqual(restored["http_method"], "POST")
            self.assertEqual([task.target for task in payload.remaining_tasks], ["http://raw.test/"])
            self.assertNotIn("unrelated history", str(payload.output_history))

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
                        SessionStore().save(self._controller()._snapshot_session(SessionOptions.from_options(saved), ""), checkpoint)
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
                    restored_options = restored.options.to_options()
                    self.assertEqual(restored_options["headers"]["X-Test"], "prepared")
                    self.assertEqual(restored_options["auth"], "user:prepared-value")
                    self.assertEqual(restored_options["data"], b"\x80\r\n")
                    self.assertEqual([task.target for task in restored.remaining_tasks], saved["urls"])
                    self.assertEqual(restored_options["request_backend"], saved["request_backend"])
                    self.assertEqual(restored_options["async_mode"], saved["async_mode"])

    def test_restoring_twice_does_not_share_runtime_progress(self):
        source = self._controller()
        snapshot = source._snapshot_session(SessionOptions(), "")
        before = deepcopy(snapshot)
        restored = []
        for _ in range(2):
            controller = self._controller()
            controller._restore_session(snapshot)
            self.addCleanup(controller.reporter.finish)
            restored.append(controller)
        restored[0].target_progress.directories.clear()
        restored[0].run_state.passed_urls.clear()
        restored[0].run_state.jobs_processed = 99
        restored[0].dictionary.add_extra("new")
        restored[0].dictionary.reset()

        self.assertEqual(snapshot, before)
        self.assertEqual(restored[1].target_progress.directories, ["current/", "next/"])
        self.assertEqual(restored[1].run_state.passed_urls, {"http://done.test/"})
        self.assertEqual(restored[1].run_state.jobs_processed, 2)
        self.assertEqual(restored[1].run_state.snapshot_tasks(), snapshot.remaining_tasks)
        self.assertEqual(restored[1].dictionary.__getstate__(), (["done", "pending"], 1, ["extra"], 0))
        self.assertEqual(restored[1]._snapshot_session(snapshot.options, ""), snapshot)

    def test_load_returns_typed_values_and_legacy_defaults(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory, "legacy.json")
            checkpoint.write_text(json.dumps({
                "version": 1, "controller": {"start_time": 12},
                "dictionary": {"items": ["a", "a", "b"], "index": 1},
                "options": {"extensions": ["html"], "include_status_codes": [200]},
            }), encoding="utf-8")
            snapshot = SessionStore().load(str(checkpoint))
        self.assertIsInstance(snapshot, SessionSnapshot)
        self.assertEqual(snapshot.run, RunCheckpoint(12, old_session=True))
        self.assertEqual(snapshot.task_checkpoint.url, "")
        self.assertEqual(snapshot.task_checkpoint.base_path, "")
        self.assertEqual(snapshot.task_checkpoint.directories, ())
        self.assertEqual(snapshot.task_checkpoint.dictionary.to_state(), (["a", "a", "b"], 1, [], 0))
        self.assertEqual(snapshot.options.to_options(), {"extensions": ("html",), "include_status_codes": {200}})
        self.assertEqual(snapshot.last_output, "")
        self.assertEqual(snapshot.output_history, [])

    def test_task_input_round_trip_is_distinct_from_prepared_origin(self):
        targets = [
            "https://user:p%40ss@[2001:db8::1]:8443/a%2Fb?next=/home",
            "https://example.test/café", "", "https://example.test/café",
        ]
        source = self._controller()
        source.run_state = ScanRunState(targets)
        source.run_state.activate_next()
        source.target_progress.url = "https://[2001:db8::1]:8443/"
        source.target_progress.base_path = "a%2Fb"
        source.target_progress.directories = ["a%2Fb"]
        snapshot = source._snapshot_session(SessionOptions.from_options({"urls": ["unrelated"], "headers": {}}), "")
        self.assertNotIn("urls", snapshot.options.to_options())
        self.assertEqual(snapshot.remaining_tasks, tuple(TaskSpec(target) for target in targets))
        with TemporaryDirectory() as directory:
            store = SessionStore()
            store.save(snapshot, directory)
            payload = json.loads(Path(directory, store.CHECKPOINT_FILE).read_text(encoding="utf-8"))
            self.assertEqual(payload["options"]["urls"], targets)
            self.assertEqual(payload["controller"]["url"], "https://[2001:db8::1]:8443/")
            restored = store.load(directory)
            self.assertEqual(restored, snapshot)
        self.assertEqual(restored.task_checkpoint.base_path, "a%2Fb")
        self.assertEqual(restored.task_checkpoint.directories, ("a%2Fb",))
        self.assertEqual(restored.task_checkpoint.dictionary.index, 1)

    def test_snapshot_owns_task_sequence_and_rejects_ambiguous_input(self):
        original = self._controller()._snapshot_session(SessionOptions(), "")
        tasks = [TaskSpec("first"), TaskSpec("first"), TaskSpec("last")]
        snapshot = replace(original, remaining_tasks=tasks)
        tasks.clear()
        self.assertEqual(snapshot.remaining_tasks, (TaskSpec("first"), TaskSpec("first"), TaskSpec("last")))
        with self.assertRaisesRegex(TypeError, "must be SessionOptions"):
            replace(snapshot, options={"urls": ["conflicting"]})

    def test_legacy_task_input_is_decoded_from_options_only(self):
        for targets in (None, [], ["first?x=1", "first?x=1", ""]):
            with self.subTest(targets=targets), TemporaryDirectory() as directory:
                path = Path(directory, "legacy.json")
                path.write_text(json.dumps({
                    "version": 1,
                    "controller": {"start_time": 0, "url": "https://prepared.test/"},
                    "dictionary": {"items": [], "index": 0},
                    "options": {"urls": targets, "data": "body"},
                }), encoding="utf-8")
                snapshot = SessionStore().load(str(path))
                self.assertEqual([task.target for task in snapshot.remaining_tasks], targets or [])
                self.assertEqual(snapshot.options.to_options(), {"data": "body"})
                # A prepared origin must never be invented as missing input.
                self.assertEqual(snapshot.task_checkpoint.url, "https://prepared.test/")

    @skipUnless(is_native_backend_available(), "native extension is not installed")
    def test_real_native_partial_claim_round_trips_without_retaining_handles(self):
        with TemporaryDirectory() as directory:
            wordlist = Path(directory, "words.txt")
            wordlist.write_text("zero\none\ntwo\nlater\n", encoding="utf-8")
            source = self._controller()
            source.dictionary = Dictionary(
                WordlistConfig(backend="native", native_corpus=True), files=[str(wordlist)],
            )
            chunk = source.dictionary.claim_native_many(3, "current/")
            self.assertIsInstance(chunk, NativeWordlistChunk)
            source.dictionary.release_native_claims(chunk, 1)
            source.dictionary.add_extra("dynamic")
            captured = source._snapshot_session(SessionOptions(), "")
            source.dictionary.release_native_claims(chunk, 2)
            source.dictionary.reset()
            store = SessionStore()
            store.save(captured, str(Path(directory, "checkpoint")))
            loaded = store.load(str(Path(directory, "checkpoint")))
        self.assertEqual(loaded, captured)
        self.assertEqual(loaded.task_checkpoint.dictionary.index, 1)
        for native_corpus in (False, True):
            with self.subTest(native_corpus=native_corpus):
                # Resume does not regenerate the corpus or need its source file.
                dictionary = Dictionary(WordlistConfig(native_corpus=native_corpus))
                dictionary.__setstate__(loaded.task_checkpoint.dictionary.to_state())
                self.assertEqual([next(dictionary) for _ in range(4)], ["dynamic", "one", "two", "later"])
                with self.assertRaises(StopIteration):
                    next(dictionary)
                dictionary.reset()
                self.assertEqual([next(dictionary) for _ in range(4)], ["zero", "one", "two", "later"])
