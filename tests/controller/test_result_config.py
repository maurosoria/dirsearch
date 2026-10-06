"""Result delivery uses prepared policy, not another invocation's options."""

import base64
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.connection.response import NativeResponse
from lib.controller.controller import Controller
from lib.core.target_progress import TargetProgress
from lib.core.scan_run_state import ScanRunState
from lib.controller.session import SessionStore
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig, ScanEngine
from lib.core.fuzzer import AsyncFuzzer
from lib.core.result_config import ResultConfig
from lib.core.wordlist_config import WordlistConfig


def controller_for(config, engine=ScanEngine.THREADED):
    controller = object.__new__(Controller)
    controller.run_state = ScanRunState()
    controller.target_progress = TargetProgress()
    controller.result_config = config
    controller.execution_config = ExecutionConfig(engine=engine)
    controller.discovery_config = DiscoveryConfig()
    controller.interface = Mock()
    controller.logger = Mock()
    controller.requester = Mock()
    controller.requester.replay_request = AsyncMock()
    controller.response_stores = ()
    return controller


def response_for():
    return NativeResponse(
        "http://example.test/item?key=value", 200,
        [("Content-Type", "application/octet-stream")], b"\x00\xffbody\r\n",
    )


class TestControllerResultConfig(IsolatedAsyncioTestCase):
    async def test_prepared_presentation_and_replay_ignore_later_options_in_all_engines(self):
        response = response_for()
        for engine in ScanEngine:
            for enabled in (False, True):
                with self.subTest(engine=engine, enabled=enabled):
                    proxy = "http://prepared.example.test:8080" if enabled else None
                    controller = controller_for(ResultConfig(full_url=enabled, replay_proxy=proxy), engine)
                    with patch.dict(options, {
                        "full_url": not enabled, "replay_proxy": "http://unrelated.example.test:8080",
                    }, clear=True):
                        if engine is ScanEngine.ASYNC:
                            await AsyncFuzzer.run_callbacks((controller.match_callback,), response)
                        else:
                            self.assertIsNone(controller.match_callback(response))
                    controller.interface.status_report.assert_called_once_with(response, enabled)
                    if enabled and engine is ScanEngine.ASYNC:
                        controller.requester.replay_request.assert_awaited_once_with(response.full_path, proxy=proxy)
                        controller.requester.request.assert_not_called()
                    elif enabled:
                        controller.requester.request.assert_called_once_with(response.full_path, proxy=proxy)
                        controller.requester.replay_request.assert_not_called()
                    else:
                        controller.requester.request.assert_not_called()
                        controller.requester.replay_request.assert_not_called()

    async def test_independent_capture_destinations_work_with_global_options_empty(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        controllers = []
        response = response_for()
        for label, engine in (("sync", ScanEngine.THREADED), ("async", ScanEngine.ASYNC)):
            config = ResultConfig(str(directory / label), str(directory / f"{label}.jsonl"))
            controller = controller_for(config, engine)
            controllers.append(controller)
            self.addCleanup(controller._close_response_stores)
            with patch.dict(options, {}, clear=True):
                controller._prepare_response_stores()
                if engine is ScanEngine.ASYNC:
                    await controller.save_response_async(response)
                else:
                    controller.save_response(response)

        controllers[0]._close_response_stores()
        await controllers[1].save_response_async(response)
        controllers[1]._close_response_stores()
        for label, expected in (("sync", 1), ("async", 2)):
            files = list((directory / label).iterdir())
            self.assertEqual(len(files), expected)
            self.assertTrue(all(path.read_bytes() == response.body for path in files))
            records = [json.loads(line) for line in (directory / f"{label}.jsonl").read_text().splitlines()]
            self.assertEqual(len(records), expected)
            for record in records:
                self.assertEqual(base64.b64decode(record["body"]), response.body)
                self.assertEqual(record["bodyComplete"], response.body_complete)
                self.assertEqual(record["bodyTruncated"], response.body_truncated)

    def test_disabled_capture_does_not_create_stores_from_global_destinations(self):
        controller = controller_for(ResultConfig())
        with (
            patch.dict(options, {"save_response": "unrelated", "save_response_jsonl": "unrelated.jsonl"}),
            patch("lib.controller.controller.create_response_stores", return_value=()) as factory,
        ):
            controller._prepare_response_stores()
        factory.assert_called_once_with(None, None)
        self.assertEqual(controller.response_stores, ())


class TestResultPreparation(TestCase):
    def test_setup_and_real_resume_share_policy_with_transport_across_targets(self):
        for engine, requester_path in (
            (ScanEngine.THREADED, "lib.connection.requester.Requester"),
            (ScanEngine.ASYNC, "lib.connection.requester.AsyncRequester"),
            (ScanEngine.NATIVE, "lib.connection.native.NativeRequester"),
        ):
            for capture in (False, True):
                for resumed in (False, True):
                    with self.subTest(engine=engine, capture=capture, resumed=resumed), TemporaryDirectory() as root:
                        directory = Path(root)
                        raw_directory = directory / "responses"
                        jsonl_file = directory / "responses.jsonl"
                        saved = dict(options)
                        saved.update(
                            session_file=None, raw_file=None, log_file=None,
                            wordlist_backend="python", wordlists=[], output_formats=[],
                            urls=["http://first.test/", "http://second.test/"], subdirs=[],
                            request_backend="native" if engine is ScanEngine.NATIVE else "python",
                            async_mode=engine is ScanEngine.ASYNC,
                            save_response=str(raw_directory) if capture else None,
                            save_response_jsonl=str(jsonl_file) if capture else None,
                            full_url=True, replay_proxy="http://prepared.example.test:8080",
                            crawl=False, find_backup=False, recursive=False,
                            deep_recursive=False, force_recursive=False, skip_on_status=set(),
                        )
                        expected = ResultConfig.from_options(saved)
                        checkpoint = str(directory / "checkpoint.json")
                        if resumed:
                            saved_controller = SimpleNamespace(
                                start_time=0, run_state=ScanRunState(),
                                target_progress=TargetProgress(), output_history=[],
                                dictionary=Dictionary(WordlistConfig()),
                            )
                            SessionStore().save(
                                Controller._snapshot_session(saved_controller, saved, ""), checkpoint
                            )

                        current = dict(saved)
                        if resumed:
                            current.update(
                                session_file=checkpoint, full_url=False, replay_proxy=None,
                                save_response=None, save_response_jsonl=None,
                            )
                        requester = Mock(backend=None)
                        requester.replay_request = AsyncMock()
                        if engine is ScanEngine.ASYNC:
                            requester.close = AsyncMock()
                        original_run = Controller.run
                        policies = []

                        def run(controller):
                            self.assertEqual(controller.result_config, expected)
                            # Contradict capture between store creation and
                            # transport composition, then again between targets.
                            options.update(
                                save_response=None if capture else str(directory / "wrong"),
                                save_response_jsonl=None, full_url=False,
                                replay_proxy="http://unrelated.example.test:8080",
                            )
                            original_run(controller)

                        def set_target(controller, url):
                            controller.target_progress.url = url
                            controller.target_progress.base_path = ""

                        def start(controller):
                            policies.append(controller.result_config)
                            self.assertIs(controller.request_config.capture_full_body, capture)
                            response = NativeResponse(controller.target_progress.url + "item", 200, [], b"\x00body")
                            replay = controller.match_callback(response)
                            if engine is ScanEngine.ASYNC:
                                controller.loop.run_until_complete(replay)
                                controller.loop.run_until_complete(controller.save_response_async(response))
                            else:
                                self.assertIsNone(replay)
                                controller.save_response(response)
                            options.update(full_url=False, replay_proxy=None)

                        with (
                            patch.dict(options, current),
                            patch.object(Controller, "run", new=run),
                            patch.object(Controller, "start", new=start),
                            patch.object(Controller, "set_target", new=set_target),
                            patch.object(Controller, "crawl_target"),
                            patch.object(Controller, "_confirm_session_overwrite"),
                            patch(requester_path, return_value=requester) as factory,
                            patch("lib.controller.controller.signal.signal"),
                            patch("lib.controller.controller.create_terminal"),
                        ):
                            controller = Controller()
                        self.assertEqual(len(policies), 2)
                        self.assertIs(policies[0], policies[1])
                        self.assertIs(factory.call_args.args[0].capture_full_body, capture)
                        self.assertEqual(
                            [call.args[1] for call in controller.interface.status_report.call_args_list],
                            [True, True],
                        )
                        replay_calls = (
                            requester.replay_request.await_args_list if engine is ScanEngine.ASYNC
                            else requester.request.call_args_list
                        )
                        self.assertEqual([call.kwargs["proxy"] for call in replay_calls], [expected.replay_proxy] * 2)
                        self.assertTrue(all(store.closed for store in controller.response_stores))
                        self.assertFalse((directory / "wrong").exists())
                        if capture:
                            self.assertEqual(len(list(raw_directory.iterdir())), 2)
                            records = [json.loads(line) for line in jsonl_file.read_text().splitlines()]
                            self.assertEqual([row["url"] for row in records], [url + "item" for url in saved["urls"]])
                        else:
                            self.assertFalse(raw_directory.exists())
                            self.assertFalse(jsonl_file.exists())

    def test_result_policy_is_prepared_after_raw_input(self):
        expected = ResultConfig(full_url=True, replay_proxy="http://prepared.example.test:8080")

        def parse(_path):
            options.update(full_url=True, replay_proxy=expected.replay_proxy)
            return ["http://example.test/"], "POST", {}, b""

        with (
            patch.dict(options, {
                "session_file": None, "raw_file": "request.txt", "wordlists": [],
                "log_file": None, "output_formats": [], "save_response": None,
                "save_response_jsonl": None, "full_url": False, "replay_proxy": None,
            }),
            patch("lib.controller.controller.parse_raw", side_effect=parse),
            patch.object(Controller, "run"),
        ):
            controller = Controller(output=StringIO())
        self.assertEqual(controller.result_config, expected)

    def test_store_preparation_failure_aborts_before_transport_creation(self):
        with TemporaryDirectory() as root:
            # Creating the first store succeeds, but the JSONL destination is
            # a directory. The existing factory must close the first resource.
            first_store = Mock()
            with (
                patch.dict(options, {
                    "session_file": None, "raw_file": None, "wordlists": [],
                    "log_file": None, "output_formats": [],
                    "save_response": str(Path(root, "responses")), "save_response_jsonl": root,
                }),
                patch("lib.report.directory_response_store.DirectoryResponseStore", return_value=first_store),
                patch.object(Controller, "run") as run,
                self.assertRaises(SystemExit) as stopped,
            ):
                Controller(output=StringIO())
            self.assertEqual(stopped.exception.code, 1)
            first_store.close.assert_called_once_with()
            run.assert_not_called()
