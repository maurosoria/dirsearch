import os
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, call, patch

from lib.core.run_config import RunConfig
from lib.controller.run_resources import RunResources
from lib.controller.controller import Controller
from lib.core.target_progress import TargetProgress
from lib.core.scan_run_state import ScanRunState
from lib.controller.session import SessionStore
from lib.controller.session_options import SessionOptions
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import InvalidURLException
from lib.core.execution_config import ScanEngine
from lib.core.target_config import TargetConfig
from lib.core.wordlist_config import WordlistConfig


class TestControllerTargetConfig(TestCase):
    def test_prepared_routing_survives_global_changes_for_all_engines(self):
        for engine, requester_path in (
            (ScanEngine.THREADED, "lib.connection.requester.Requester"),
            (ScanEngine.ASYNC, "lib.connection.requester.AsyncRequester"),
            (ScanEngine.NATIVE, "lib.connection.native.NativeRequester"),
        ):
            with self.subTest(engine=engine):
                controller = object.__new__(Controller)
                controller.resources = RunResources(interface=Mock(), logger=Mock())
                controller.config = RunConfig()
                controller.run_state = ScanRunState()
                controller.target_progress = TargetProgress()
                controller.dictionary = Mock()
                controller.target_progress.directories = []
                controller.run_state.old_session = False
                controller.resources.reporter = Mock()
                controller.crawl_target = Mock()
                controller.start = Mock()
                requester = Mock()

                def create_requester(*args, **kwargs):
                    options.update(
                        scheme="http", ip="198.51.100.9", proxies=[], tor=False,
                    )
                    return requester

                with (
                    patch.dict(options, {
                        "urls": ["first.test/path?one=1", "http://second.test:8080/"],
                        "scheme": "https",
                        "ip": "192.0.2.7",
                        "proxies": ["http://proxy.test:8080"],
                        "tor": False,
                        "request_backend": "native" if engine is ScanEngine.NATIVE else "python",
                        "async_mode": engine is ScanEngine.ASYNC,
                        "subdirs": [],
                        "session_file": None,
                    }),
                    patch(requester_path, side_effect=create_requester),
                    patch("lib.core.fuzzer.Fuzzer"),
                    patch("lib.core.fuzzer.AsyncFuzzer"),
                    patch("lib.core.fuzzer.NativeFuzzer"),
                    patch("lib.controller.controller.detect_scheme") as detect,
                    patch("lib.controller.controller.signal.signal"),
                ):
                    try:
                        controller._prepare_config(options)
                        controller._run_targets()
                    finally:
                        if controller.resources.loop is not None:
                            controller.resources.loop.close()

                self.assertEqual(requester.set_url.call_args_list, [
                    call("https://first.test/"), call("http://second.test:8080/"),
                ])
                self.assertEqual(requester.set_ip.call_args_list, [
                    call("first.test", 443, "192.0.2.7"),
                    call("second.test", 8080, "192.0.2.7"),
                ])
                self.assertEqual(requester.set_query.call_args_list, [call("one=1"), call("")])
                self.assertEqual(controller.start.call_count, 2)
                detect.assert_not_called()

    def test_independent_target_policies_work_with_global_options_empty(self):
        first = object.__new__(Controller)
        first.resources = RunResources(interface=Mock(), logger=Mock())
        first.config = RunConfig(target=TargetConfig("https", "192.0.2.7", True))
        first.run_state = ScanRunState()
        first.target_progress = TargetProgress()
        first.resources.requester = Mock()
        second = object.__new__(Controller)
        second.resources = RunResources(interface=Mock(), logger=Mock())
        second.config = RunConfig(target=TargetConfig("http"))
        second.run_state = ScanRunState()
        second.target_progress = TargetProgress()
        second.resources.requester = Mock()
        with patch.dict(options, {}, clear=True):
            first.set_target("example.test/private?next=%2Fhome")
            second.set_target("example.test/public")
            first.set_target("example.test/other")

        self.assertEqual(first.target_progress.url, "https://example.test/")
        self.assertEqual(second.target_progress.url, "http://example.test/")
        self.assertEqual(first.target_progress.base_path, "other/")
        self.assertEqual(second.target_progress.base_path, "public/")
        self.assertEqual(first.resources.requester.set_ip.call_args_list, [
            call("example.test", 443, "192.0.2.7"),
            call("example.test", 443, "192.0.2.7"),
        ])
        self.assertEqual(first.resources.requester.set_query.call_args_list, [call("next=%2Fhome"), call("")])
        second.resources.requester.set_ip.assert_not_called()

    def test_frozen_proxy_guard_rejects_before_probe_or_requester_mutation(self):
        controller = object.__new__(Controller)
        controller.resources = RunResources(interface=Mock(), logger=Mock())
        controller.config = RunConfig(target=TargetConfig(proxy_configured=True))
        controller.run_state = ScanRunState()
        controller.target_progress = TargetProgress()
        controller.resources.requester = Mock()
        with (
            patch.dict(options, {"scheme": "https", "proxies": [], "tor": False}, clear=True),
            patch("lib.controller.controller.detect_scheme") as detect,
            self.assertRaisesRegex(InvalidURLException, "Cannot auto-detect the scheme"),
        ):
            controller.set_target("user:password@example.test")
        detect.assert_not_called()
        self.assertEqual(controller.resources.requester.mock_calls, [])

    def test_autodetection_and_ip_override_use_the_same_frozen_connect_host(self):
        for target, answers, probes, port in (
            ("example.test", [ValueError, "https"], [None, 443], 443),
            ("example.test:8443", ["https"], [8443], 8443),
        ):
            with self.subTest(target=target):
                controller = object.__new__(Controller)
                controller.resources = RunResources(interface=Mock(), logger=Mock())
                controller.config = RunConfig(target=TargetConfig(connect_host="2001:db8::7"))
                controller.run_state = ScanRunState()
                controller.target_progress = TargetProgress()
                controller.resources.requester = Mock()
                with (
                    patch.dict(options, {}, clear=True),
                    patch("lib.controller.controller.detect_scheme", side_effect=answers) as detect,
                ):
                    controller.set_target(target)
                self.assertEqual(detect.call_args_list, [
                    call("example.test", probe, connect_host="2001:db8::7") for probe in probes
                ])
                controller.resources.requester.set_ip.assert_called_once_with("example.test", port, "2001:db8::7")

    def test_real_checkpoint_restoration_precedes_target_policy_snapshot(self):
        for engine, requester_path in (
            (ScanEngine.THREADED, "lib.connection.requester.Requester"),
            (ScanEngine.ASYNC, "lib.connection.requester.AsyncRequester"),
            (ScanEngine.NATIVE, "lib.connection.native.NativeRequester"),
        ):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as directory:
                saved_options = dict(options)
                saved_options.update(
                    urls=["first.test/private?one=1", "second.test:8443/"],
                    scheme="https", ip="2001:db8::7",
                    proxies=["http://proxy.test:8080"], tor=False,
                    request_backend="native" if engine is ScanEngine.NATIVE else "python",
                    async_mode=engine is ScanEngine.ASYNC,
                    subdirs=[], output_formats=[], log_file=None,
                    save_response=None, save_response_jsonl=None, session_file=None,
                )
                saved_controller = SimpleNamespace(
                    start_time=0, run_state=ScanRunState(saved_options["urls"]), target_progress=TargetProgress(),
                    output_history=[], dictionary=Dictionary(WordlistConfig()),
                )
                saved_controller.run_state.old_session = True
                checkpoint = os.path.join(directory, "checkpoint")
                SessionStore().save(
                    Controller._snapshot_session(saved_controller, SessionOptions.from_options(saved_options), ""), checkpoint
                )
                requester = Mock(backend=None)
                if engine is ScanEngine.ASYNC:
                    requester.close = AsyncMock()

                with (
                    patch.dict(options, {
                        "session_file": checkpoint, "scheme": "http", "ip": None,
                        "proxies": [], "tor": False,
                    }),
                    patch.object(Controller, "_confirm_session_overwrite"),
                    patch.object(Controller, "crawl_target"),
                    patch.object(Controller, "start"),
                    patch("lib.controller.controller.ReportManager", return_value=Mock(reports=())),
                    patch(requester_path, return_value=requester),
                    patch("lib.core.fuzzer.Fuzzer"),
                    patch("lib.core.fuzzer.AsyncFuzzer"),
                    patch("lib.core.fuzzer.NativeFuzzer"),
                    patch("lib.controller.controller.detect_scheme") as detect,
                    patch("lib.controller.controller.signal.signal"),
                    patch("lib.controller.controller.create_terminal"),
                ):
                    controller = Controller()
                    controller.run()
                self.assertEqual(controller.config.target, TargetConfig("https", "2001:db8::7", True))
                self.assertEqual(controller.config.request.proxies, ("http://proxy.test:8080",))
                self.assertEqual(requester.set_url.call_args_list, [
                    call("https://first.test/"), call("https://second.test:8443/"),
                ])
                self.assertEqual(requester.set_ip.call_args_list, [
                    call("first.test", 443, "2001:db8::7"),
                    call("second.test", 8443, "2001:db8::7"),
                ])
                detect.assert_not_called()
