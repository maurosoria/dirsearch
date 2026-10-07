"""Exercise real preparation and cleanup; no requests or workers are started."""

from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.controller.controller import Controller
from lib.controller.session import SessionStore
from lib.controller.session_options import SessionOptions
from lib.controller.session_snapshot import RunCheckpoint, SessionSnapshot
from lib.core.data import options
from lib.core.execution_config import ScanEngine
from lib.core.logger import RunLogger
from lib.core.run_config import RunConfig
from lib.core.task_checkpoint import DictionaryCheckpoint, TaskCheckpoint
from lib.view.terminal import create_terminal


class TestControllerRunConfig(TestCase):
    def setUp(self):
        values = deepcopy(options)
        values.update(
            urls=[], wordlists=[], wordlist_backend="python",
            session_file=None, raw_file=None, output_formats=[],
            log_file=None, save_response=None, save_response_jsonl=None,
            request_backend="python", async_mode=False,
            color=False, quiet=False, disable_cli=False,
        )
        state = patch.dict(options, values, clear=True)
        state.start()
        self.addCleanup(state.stop)

    def test_resources_and_transport_share_one_preparation_for_all_engines(self):
        for engine in ScanEngine:
            with self.subTest(engine=engine), patch.dict(options, deepcopy(options), clear=True):
                options.update(
                    request_backend="native" if engine is ScanEngine.NATIVE else "python",
                    async_mode=engine is ScanEngine.ASYNC,
                    headers={"X-Prepared": "yes"}, http_method="POST", thread_count=3,
                )
                terminals, prepared = [], []

                def terminal_factory(config, **kwargs):
                    terminal = create_terminal(config, **kwargs)
                    terminals.append(terminal)
                    if len(terminals) == 2:
                        prepared.append(deepcopy(options))
                        # This runs after policy capture but before Dictionary,
                        # logger, reports and requester construction.
                        options.update(
                            request_backend="invalid", async_mode=True,
                            http_method="DELETE", headers={}, thread_count=99,
                            extensions=("wrong",), prefixes=("wrong-",),
                            include_status_codes={500}, scheme="https",
                            output_formats=["unknown"], log_file="must-not-open.log",
                            save_response="must-not-create", wordlists=["absent.txt"],
                        )
                    return terminal

                requester = Mock()
                if engine is ScanEngine.ASYNC:
                    requester.close = AsyncMock()
                with (
                    patch("lib.controller.controller.create_terminal", side_effect=terminal_factory),
                    patch("lib.controller.controller.RunLogger", wraps=RunLogger) as logger,
                    patch("lib.controller.controller.get_blacklists", return_value={}),
                    patch("lib.controller.controller.signal.signal"),
                    patch("lib.connection.requester.Requester", return_value=requester) as threaded,
                    patch("lib.connection.requester.AsyncRequester", return_value=requester) as asynchronous,
                    patch("lib.connection.native.NativeRequester", return_value=requester) as native,
                ):
                    controller = Controller(output=StringIO())
                self.assertEqual(controller.config, RunConfig.from_options(prepared[0]))
                self.assertEqual(controller.session_options, SessionOptions.from_options(prepared[0]))
                self.assertIs(controller.dictionary.config, controller.config.wordlist)
                self.assertIs(controller.interface.config, controller.config.terminal)
                self.assertIs(controller.reporter.config, controller.config.reports)
                self.assertIs(logger.call_args.args[0], controller.config.logging)
                for selected, factory in (
                    (ScanEngine.THREADED, threaded), (ScanEngine.ASYNC, asynchronous),
                    (ScanEngine.NATIVE, native),
                ):
                    if selected is engine:
                        self.assertEqual(factory.call_count, 1)
                        self.assertIs(factory.call_args.args[0], controller.config.request)
                        if selected is ScanEngine.NATIVE:
                            self.assertIs(factory.call_args.kwargs["filter_config"], controller.config.filters)
                    else:
                        factory.assert_not_called()
                requester.close.assert_called_once_with()
                if engine is ScanEngine.ASYNC:
                    requester.close.assert_awaited_once_with()
                    self.assertTrue(controller.loop.is_closed())
                self.assertTrue(all(terminal._output_buffer.closed for terminal in terminals))

    def test_raw_file_precedes_all_policy_and_session_capture(self):
        with TemporaryDirectory() as directory:
            raw = Path(directory, "request.txt")
            raw.write_bytes(
                b"POST /api?next=%2Fhome HTTP/1.1\r\nHost: example.test\r\n"
                b"Authorization: Bearer private-value\r\n\r\n\x80body\r\n"
            )
            options.update(raw_file=str(raw), http_method="GET", data="ignored")
            with patch.object(Controller, "run"):
                controller = Controller(output=StringIO())
        self.assertEqual(controller.config.request.method, "POST")
        self.assertEqual(controller.config.terminal.method, "POST")
        self.assertEqual(controller.config.request.body, b"\x80body\r\n")
        self.assertIn(("authorization", "Bearer private-value"), controller.config.request.headers)
        saved_options = controller.session_options.to_options()
        self.assertEqual(saved_options["http_method"], "POST")
        self.assertEqual(saved_options["data"], b"\x80body\r\n")
        self.assertNotIn("urls", saved_options)
        self.assertEqual(options["urls"], ["example.test/api?next=%2Fhome"])

    def test_resume_prepares_saved_policy_once_and_keeps_overwrite_choice(self):
        for engine in ScanEngine:
            for choice in ("o", "n"):
                with (
                    self.subTest(engine=engine, choice=choice),
                    TemporaryDirectory() as directory,
                    patch.dict(options, deepcopy(options), clear=True),
                ):
                    saved = deepcopy(options)
                    saved.pop("urls")
                    saved.update(
                        request_backend="native" if engine is ScanEngine.NATIVE else "python",
                        async_mode=engine is ScanEngine.ASYNC,
                        http_method="POST", headers={"X-Saved": "yes"}, thread_count=3,
                    )
                    checkpoint = str(Path(directory, "checkpoint.json"))
                    SessionStore().save(SessionSnapshot(
                        run=RunCheckpoint(0),
                        task_checkpoint=TaskCheckpoint(DictionaryCheckpoint((), 0)),
                        options=SessionOptions(saved),
                    ), checkpoint)
                    options.update(session_file=checkpoint, http_method="DELETE", thread_count=99)

                    def answer():
                        options.update(http_method="PATCH", thread_count=7)
                        options["headers"].clear()
                        return choice

                    with patch("builtins.input", side_effect=answer), patch.object(Controller, "run"):
                        controller = Controller(output=StringIO())
                    self.assertEqual(controller.config, RunConfig.from_options(saved))
                    self.assertIs(controller.config.execution.engine, engine)
                    self.assertIs(controller.reporter.config, controller.config.reports)
                    self.assertIs(controller.interface.config, controller.config.terminal)
                    prepared = controller.session_options.to_options()
                    self.assertEqual(prepared["headers"], {"X-Saved": "yes"})
                    self.assertEqual(prepared["http_method"], "POST")
                    self.assertEqual(prepared["thread_count"], 3)
                    self.assertEqual(prepared["session_file"], checkpoint if choice == "o" else None)

    def test_invalid_engine_stops_before_opening_prepared_resources(self):
        options.update(request_backend="native", async_mode=True)
        terminals = []

        def record_terminal(*args, **kwargs):
            terminal = create_terminal(*args, **kwargs)
            terminals.append(terminal)
            return terminal

        with (
            patch("lib.controller.controller.create_terminal", side_effect=record_terminal),
            patch("lib.controller.controller.Dictionary") as dictionary,
            patch("lib.controller.controller.ReportManager") as reports,
            patch.object(Controller, "_prepare_logging") as logging,
            patch.object(Controller, "_prepare_response_stores") as stores,
            patch.object(Controller, "run") as run,
            patch("sys.stderr", new_callable=StringIO),
            self.assertRaises(SystemExit) as stopped,
        ):
            Controller(output=StringIO())
        self.assertEqual(stopped.exception.code, 1)
        for resource in (dictionary, reports, logging, stores, run):
            resource.assert_not_called()
        self.assertEqual(len(terminals), 1)
        self.assertTrue(terminals[0]._output_buffer.closed)

    def test_failed_preparation_does_not_publish_a_partial_configuration(self):
        controller = object.__new__(Controller)
        controller._prepare_config(options)
        previous, previous_options = controller.config, controller.session_options
        invalid = deepcopy(options)
        invalid.update(request_backend="unknown")
        with patch("sys.stderr", new_callable=StringIO), self.assertRaises(SystemExit):
            controller._prepare_config(invalid)
        self.assertIs(controller.config, previous)
        self.assertIs(controller.session_options, previous_options)

    def test_local_preparation_input_cannot_mutate_policies_or_persistence(self):
        values = deepcopy(options)
        values.update(headers={"X-Test": "prepared"}, wordlists=["words.txt"], urls=["target"])
        controller = object.__new__(Controller)
        local_input = controller._prepare_config(values)
        values["headers"].clear()
        values["wordlists"].clear()
        self.assertEqual(local_input["wordlists"], ["words.txt"])
        local_input["headers"].clear()
        local_input["wordlists"].clear()
        local_input["http_method"] = "DELETE"
        self.assertEqual(controller.config.request.headers, (("X-Test", "prepared"),))
        self.assertEqual(controller.session_options.to_options()["headers"], {"X-Test": "prepared"})
        self.assertEqual(controller.session_options.to_options()["wordlists"], ["words.txt"])
        self.assertNotIn("urls", controller.session_options.to_options())
