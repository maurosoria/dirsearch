"""Real local lifecycles must not borrow another invocation's state.

These are loopback integration tests, not mocked controller-phase tests. The
only substituted policy is the resume overwrite question; no process globals,
requesters, fuzzers, persistence operations or cleanup methods are patched.
"""

import asyncio
import base64
import json
import signal
import sys
import threading
import time
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from urllib.parse import urlsplit

from lib.controller.controller import Controller
from lib.controller.session import SessionStore
from lib.controller.session_options import SessionOptions
from lib.controller.session_snapshot import RunCheckpoint, SessionSnapshot
from lib.core.option_defaults import default_options
from lib.core.execution_config import ScanEngine
from lib.core.run_metadata import RunMetadata
from lib.core.task_checkpoint import DictionaryCheckpoint, TaskCheckpoint
from lib.core.task_spec import TaskSpec
from tests.controller.test_backend_e2e_contract import (
    BackendContractHandler,
    BackendContractServer,
    NATIVE_AVAILABLE,
)


class LifecycleHandler(BackendContractHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(2)
        with self.server.seen_lock:
            self.server.request_threads.append(threading.current_thread())

    def do_GET(self):
        with self.server.seen_lock:
            self.server.seen_paths.append(self.path)
            self.server.seen_headers.append((self.path, self.headers.get("X-Run")))
        if self.path.endswith("/hold"):
            self.server.hold_started.set()
            # Bound the fixture even if cancellation never reaches the client.
            if not self.server.release_hold.wait(timeout=8):
                return
        word = self.path.rsplit("/", 1)[-1]
        body = ("local response for " + self.path).encode("utf-8")
        try:
            self.send_body(body, status=201 if word in ("hit", "done", "later", "hold") else 404)
        except (BrokenPipeError, ConnectionResetError):
            # Async/native deadlines can close a held request before release.
            pass


class LifecycleServer(BackendContractServer):
    def __init__(self):
        super().__init__(LifecycleHandler)
        self.server.seen_headers = []
        self.server.request_threads = []
        self.server.hold_started = threading.Event()
        self.server.release_hold = threading.Event()

    def __exit__(self, *args):
        self.server.release_hold.set()
        super().__exit__(*args)
        for thread in self.server.request_threads:
            thread.join(timeout=3)
            if thread.is_alive():
                raise RuntimeError("lifecycle request handler did not stop")


class ResumeController(Controller):
    def _confirm_session_overwrite(self, session_file):
        # Select "new" at this instance's interactive seam. Restoration and
        # completion still use the real store, queue, reporters and requesters.
        self._options["session_file"] = None


class FailingOutput(StringIO):
    def write(self, value):
        if "/broken/hit" in value:
            raise OSError("borrowed output failed")
        return super().write(value)


class LifecycleScenarios(TestCase):
    def engines(self):
        yield "threaded"
        yield "async"
        if NATIVE_AVAILABLE:
            yield "native"

    def values(self, root, server, name, engine, words="hit\n"):
        root = Path(root, name)
        root.mkdir()
        wordlist = root / "words.txt"
        wordlist.write_text(words, encoding="utf-8")
        values = default_options()
        values.update(
            urls=[server.url + name + "/"], wordlists=[str(wordlist)],
            wordlist_backend="python", request_backend="native" if engine == "native" else "python",
            async_mode=engine == "async", subdirs=[""], thread_count=1,
            headers={"X-Run": name}, include_status_codes={201},
            output_file=str(root / "report.json"), output_formats=["json"],
            save_response_jsonl=str(root / "responses.jsonl"),
            log_file=str(root / "scan.log"), color=False, quiet=True,
            timeout=2, max_retries=0,
        )
        return values

    def controller(self, values, *, output=None, owner=Controller):
        return owner(
            values, output=StringIO() if output is None else output,
            metadata=RunMetadata("local lifecycle acceptance", "2026-10-18 12:00:00"),
        )

    def assert_closed(self, controller):
        self.assert_resources_closed(controller)
        resources = controller.resources
        self.assertIsNone(controller._native_worker)
        if resources.loop is not None:
            self.assertFalse(controller.fuzzer._background_tasks)
        if controller.config.execution.engine is ScanEngine.THREADED:
            self.assertTrue(all(not worker.is_alive() for worker in controller.fuzzer._threads))
        elif controller.config.execution.engine is ScanEngine.NATIVE:
            self.assertIsNone(resources.requester.backend)

    def assert_resources_closed(self, controller):
        resources = controller.resources
        self.assertTrue(resources.interface._output_buffer.closed)
        self.assertFalse(resources.logger.handlers)
        self.assertTrue(resources.logger.disabled)
        self.assertTrue(all(store.closed for store in resources.response_stores))
        if resources.loop is not None:
            self.assertTrue(resources.loop.is_closed())
            self.assertFalse(asyncio.all_tasks(resources.loop))
            self.assertTrue(resources.requester.session.is_closed)
        # Closure must fence late records and leave no append handles borrowed
        # from another invocation. This also catches handler re-opening bugs.
        path = Path(controller.config.logging.file_path)
        before = path.read_bytes()
        controller.resources.logger.info("late record after closure")
        self.assertEqual(path.read_bytes(), before)

    def assert_results(self, values, expected_paths):
        report = json.loads(Path(values["output_file"]).read_text(encoding="utf-8"))
        records = [
            json.loads(line)
            for line in Path(values["save_response_jsonl"]).read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual({urlsplit(row["url"]).path for row in report["results"]}, expected_paths)
        self.assertEqual({urlsplit(row["url"]).path for row in records}, expected_paths)
        self.assertEqual(len(report["results"]), len(expected_paths))
        self.assertEqual(len(records), len(expected_paths))
        for record in records:
            self.assertEqual(record["status"], 201)
            self.assertTrue(record["bodyComplete"])
            self.assertFalse(record["bodyTruncated"])
            self.assertEqual(
                base64.b64decode(record["body"]),
                ("local response for " + urlsplit(record["url"]).path).encode("utf-8"),
            )

    def test_complete_runs_keep_input_output_reports_and_resources_independent(self):
        previous_signals = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
        previous_stdout = sys.stdout
        for engine in self.engines():
            with self.subTest(engine=engine), LifecycleServer() as server, TemporaryDirectory() as root:
                first_values = self.values(root, server, "alpha", engine)
                second_values = self.values(root, server, "beta", engine)
                first_output, second_output = StringIO(), StringIO()
                first = self.controller(first_values, output=first_output)
                second = self.controller(second_values, output=second_output)
                first_values["headers"]["X-Run"] = "caller mutation"
                first_values["urls"].clear()
                first.run()
                self.assert_closed(first)
                self.assertIsNone(second.resources)
                self.assertEqual(second_output.getvalue(), "")
                before = first_output.getvalue()
                second.run()
                self.assert_closed(second)
                self.assert_results(first_values, {"/alpha/hit"})
                self.assert_results(second_values, {"/beta/hit"})
                self.assertEqual(first_output.getvalue(), before)
                self.assertNotIn("/beta/", before)
                self.assertNotIn("/alpha/", second_output.getvalue())
                self.assertFalse(first_output.closed)
                self.assertFalse(second_output.closed)
                self.assertIsNot(first.resources, second.resources)
                self.assertEqual(first.run_state.jobs_processed, 1)
                self.assertEqual(second.run_state.jobs_processed, 1)
                self.assertTrue(server.server.seen_headers)
                for path, header in server.server.seen_headers:
                    self.assertEqual(header, path.split("/")[1])
                for number, handler in previous_signals.items():
                    self.assertIs(signal.getsignal(number), handler)
                self.assertIs(sys.stdout, previous_stdout)

    def test_callback_output_failure_closes_real_resources_and_does_not_poison_next_run(self):
        for engine in self.engines():
            with self.subTest(engine=engine), LifecycleServer() as server, TemporaryDirectory() as root:
                broken_values = self.values(root, server, "broken", engine)
                good_values = self.values(root, server, "healthy", engine)
                output = FailingOutput()
                broken = self.controller(broken_values, output=output)
                healthy = self.controller(good_values)
                with self.assertRaisesRegex(OSError, "borrowed output failed"):
                    broken.run()
                self.assert_closed(broken)
                self.assert_results(broken_values, set())
                self.assertFalse(output.closed)
                self.assertIsNone(healthy.resources)
                healthy.run()
                self.assert_closed(healthy)
                self.assert_results(good_values, {"/healthy/hit"})

    def test_failed_storage_preparation_closes_acquired_resources_without_starting_requests(self):
        with LifecycleServer() as server, TemporaryDirectory() as root:
            values = self.values(root, server, "invalid-store", "async")
            records = Path(values["save_response_jsonl"])
            records.write_text("not a response record\n", encoding="utf-8")
            broken = self.controller(values)
            healthy_values = self.values(root, server, "after-startup-failure", "threaded")
            healthy = self.controller(healthy_values)
            with self.assertRaises(SystemExit) as stopped:
                broken.run()
            self.assertEqual(stopped.exception.code, 1)
            self.assert_resources_closed(broken)
            self.assertIsNone(broken.resources.requester)
            self.assertIsNone(broken.resources.loop)
            self.assertEqual(server.seen_paths, set())
            self.assertEqual(records.read_text(encoding="utf-8"), "not a response record\n")
            self.assertIsNone(healthy.resources)
            healthy.run()
            self.assert_closed(healthy)
            self.assert_results(healthy_values, {"/after-startup-failure/hit"})

    def test_deadline_drains_workers_before_a_different_engine_runs(self):
        for engine in self.engines():
            with self.subTest(engine=engine), LifecycleServer() as server, TemporaryDirectory() as root:
                values = self.values(root, server, "deadline", engine, "hold\nlater\n")
                values.update(max_time=2, timeout=3)
                output = StringIO()
                controller = self.controller(values, output=output)
                failures = []

                def run():
                    try:
                        controller.run()
                    except BaseException as error:
                        failures.append(error)

                worker = threading.Thread(target=run, name="lifecycle-deadline-owner")
                worker.start()
                try:
                    self.assertTrue(server.server.hold_started.wait(timeout=5))
                    worker.join(timeout=8)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(len(failures), 1)
                    self.assertIsInstance(failures[0], SystemExit)
                    self.assertEqual(failures[0].code, 0)
                    self.assertIn("Runtime exceeded", output.getvalue())
                    self.assert_closed(controller)
                    self.assertNotIn("/deadline/later", server.seen_paths)
                    before = output.getvalue()
                    healthy_values = self.values(root, server, "after-deadline", "async" if engine == "threaded" else "threaded")
                    healthy = self.controller(healthy_values)
                    healthy.run()
                    self.assert_closed(healthy)
                    self.assert_results(healthy_values, {"/after-deadline/hit"})
                    self.assertEqual(output.getvalue(), before)
                finally:
                    server.server.release_hold.set()
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive())

    def test_saved_continuation_resumes_current_job_then_resets_for_later_work(self):
        for engine in self.engines():
            with self.subTest(engine=engine), LifecycleServer() as server, TemporaryDirectory() as root:
                values = self.values(root, server, "resume", engine, "done\nhit\nlater\n")
                snapshot = SessionSnapshot(
                    run=RunCheckpoint(time.time(), jobs_processed=4, old_session=True),
                    task_checkpoint=TaskCheckpoint(
                        DictionaryCheckpoint(("done", "hit", "later"), 2, ("hit",)),
                        url=server.url, base_path="resume/",
                        directories=("resume/", "next/"),
                    ),
                    remaining_tasks=(TaskSpec(server.url + "resume/"), TaskSpec(server.url + "last/")),
                    options=SessionOptions.from_options(values),
                    last_output="saved owner output",
                )
                session = str(Path(root, "checkpoint"))
                SessionStore().save(snapshot, session)
                checkpoint = Path(session, SessionStore.CHECKPOINT_FILE)
                saved = checkpoint.read_bytes()
                other_values = self.values(root, server, "unrelated", "threaded")
                other = self.controller(other_values)
                resume_values = default_options()
                resume_values.update(
                    session_file=str(checkpoint) if engine == "async" else session,
                    color=False, urls=["invalid://unused"],
                )
                resumed = self.controller(resume_values, owner=ResumeController)
                resumed.run()
                self.assert_closed(resumed)
                self.assertIsNone(other.resources)
                expected = {"/resume/hit", "/resume/later"}
                expected.update("/" + directory + "/" + word for directory in ("next", "last") for word in ("done", "hit", "later"))
                self.assert_results(values, expected)
                self.assertNotIn("/resume/done", server.seen_paths)
                self.assertEqual(resumed.run_state.jobs_processed, 7)
                self.assertIn("saved owner output", resumed._terminal_stream.getvalue())
                self.assertEqual(checkpoint.read_bytes(), saved)
                other.run()
                self.assert_closed(other)
                self.assert_results(other_values, {"/unrelated/hit"})
                self.assertNotIn("saved owner output", other._terminal_stream.getvalue())


if __name__ == "__main__":
    main()
