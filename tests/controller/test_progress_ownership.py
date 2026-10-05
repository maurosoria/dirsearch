from functools import partial
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.target_progress import TargetProgress
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.execution_config import ScanEngine
from lib.core.result_config import ResultConfig
from lib.core.scan_run_state import ScanRunState
from lib.core.wordlist_config import WordlistConfig
from tests.controller.test_session_resume_queue import RecordingAsyncFuzzer, RecordingFuzzer


class TestProgressOwnership(TestCase):
    def _controller(self):
        controller = object.__new__(Controller)
        controller.run_state = ScanRunState()
        controller.target_progress = TargetProgress()
        controller.result_config = ResultConfig()
        controller.wordlist_config = WordlistConfig()
        controller.dictionary = Dictionary(controller.wordlist_config)
        controller.dictionary.__setstate__((["one", "two"], 0, [], 0))
        controller.start_time = 0
        controller.run_state.jobs_processed = 3
        controller.run_state.errors = 7
        controller.run_state.consecutive_errors = 2
        controller.logger = Mock()
        controller.interface = Mock()
        controller.reporter = Mock()
        controller._reporter_finished = False
        controller.response_stores = ()
        controller.loop = None
        controller._native_worker = None
        return controller

    def test_run_totals_and_directory_deduplication_survive_target_transitions(self):
        for engine in ScanEngine:
            with self.subTest(engine=engine):
                controller = self._controller()
                records = []
                observed_targets = []
                set_target = controller.set_target

                def observe_target(url):
                    set_target(url)
                    observed_targets.append((controller.target_progress.url, controller.target_progress.base_path))

                controller.set_target = observe_target
                with (
                    patch.dict(options, {
                        "urls": ["http://first.test/base/", "http://first.test/base/", "http://second.test/other/"],
                        "request_backend": "native" if engine is ScanEngine.NATIVE else "python",
                        "async_mode": engine is ScanEngine.ASYNC,
                        "subdirs": [""], "exclude_subdirs": [], "recursion_depth": 0,
                        "max_time": 0, "target_max_time": 0, "session_file": None, "crawl": False,
                    }),
                    patch("lib.connection.requester.Requester"),
                    patch("lib.connection.requester.AsyncRequester"),
                    patch("lib.connection.native.NativeRequester"),
                    patch("lib.core.fuzzer.Fuzzer", partial(RecordingFuzzer, records=records)),
                    patch("lib.core.fuzzer.AsyncFuzzer", partial(RecordingAsyncFuzzer, records=records)),
                    patch("lib.core.fuzzer.NativeFuzzer", partial(RecordingFuzzer, records=records)),
                    patch("lib.controller.controller.signal.signal"),
                ):
                    try:
                        controller.run()
                    finally:
                        if controller.loop is not None:
                            controller.loop.close()
                self.assertEqual(records, [("base/", ["one", "two"]), ("other/", ["one", "two"])])
                self.assertEqual(observed_targets, [
                    ("http://first.test/", "base/"), ("http://first.test/", "base/"),
                    ("http://second.test/", "other/"),
                ])
                self.assertEqual(controller.run_state.passed_urls, {"http://first.test/base/", "http://second.test/other/"})
                self.assertEqual(controller.run_state.jobs_processed, 5)
                self.assertEqual(controller.run_state.errors, 7)
                self.assertEqual(controller.run_state.consecutive_errors, 2)
                self.assertFalse(controller.run_state.old_session)
                self.assertEqual(controller.target_progress.directories, [])
                self.assertEqual(controller.run_state.snapshot_targets(), [])
