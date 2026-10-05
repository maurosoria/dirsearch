import asyncio
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.target_progress import TargetProgress
from lib.core.scan_run_state import ScanRunState
from lib.core.data import options
from lib.core.result_config import ResultConfig
from lib.core.dictionary import Dictionary
from lib.core.wordlist_config import WordlistConfig


class RecordingFuzzer:
    def __init__(self, _requester, dictionary, records, *args, **kwargs):
        self.dictionary = dictionary
        self.records = records
        self.base_path = ""

    def set_base_path(self, path):
        self.base_path = path

    def prepare_start(self):
        return None

    def _record_job(self):
        paths = []
        while True:
            try:
                paths.append(next(self.dictionary))
            except StopIteration:
                break
        self.records.append((self.base_path, paths))

    def start(self):
        self._record_job()

    def is_finished(self):
        return True

    def stop(self, _timeout):
        return True


class RecordingAsyncFuzzer(RecordingFuzzer):
    async def start(self):
        self._record_job()


class TestSessionResumeQueue(TestCase):
    def _controller(self):
        controller = object.__new__(Controller)
        controller.run_state = ScanRunState()
        controller.target_progress = TargetProgress()
        controller.result_config = ResultConfig()
        controller.logger = Mock()
        controller.interface = Mock()
        controller.start_time = 0
        controller.run_state.passed_urls = set()
        controller.target_progress.directories = ["current/", "next/"]
        controller.run_state.jobs_processed = 3
        controller.run_state.errors = 0
        controller.run_state.consecutive_errors = 0
        controller.target_progress.base_path = "first/"
        controller.target_progress.url = "https://first.example/"
        controller.run_state.old_session = True
        controller.dictionary = Dictionary(WordlistConfig.from_options(options))
        controller.dictionary.__setstate__(
            (["done", "in-flight", "later"], 2, ["in-flight"], 0)
        )
        controller.output_history = []
        controller.response_stores = ()
        controller._native_worker = None
        controller.loop = None
        controller.reporter = Mock()
        controller.crawl_target = Mock()

        def set_target(url):
            controller.target_progress.url = url
            controller.target_progress.base_path = (
                "first/" if url == "https://first.example/" else "second/"
            )

        controller.set_target = set_target
        return controller

    def test_current_job_resumes_and_later_work_uses_full_wordlist(self):
        stack_cases = (
            ("threaded", False, "python", RecordingFuzzer),
            ("async", True, "python", RecordingAsyncFuzzer),
            ("native", False, "native", RecordingFuzzer),
        )

        for stack, async_mode, request_backend, fuzzer_class in stack_cases:
            with self.subTest(stack=stack):
                controller = self._controller()
                records = []

                def create_fuzzer(*args, **kwargs):
                    return fuzzer_class(*args, records, **kwargs)

                run_options = {
                    "urls": [
                        "https://first.example/",
                        "https://second.example/",
                    ],
                    "request_backend": request_backend,
                    "async_mode": async_mode,
                    "subdirs": [""],
                    "exclude_subdirs": [],
                    "recursion_depth": 0,
                    "max_time": 0,
                    "target_max_time": 0,
                    "session_file": None,
                }
                original_urls = list(run_options["urls"])

                with (
                    patch.dict(options, run_options),
                    patch.dict("sys.modules", {"dirsearch_native": None}),
                    patch(
                        "lib.connection.requester.Requester",
                        return_value=Mock(),
                    ),
                    patch(
                        "lib.connection.requester.AsyncRequester",
                        return_value=Mock(),
                    ),
                    patch("lib.core.fuzzer.Fuzzer", create_fuzzer),
                    patch("lib.core.fuzzer.AsyncFuzzer", create_fuzzer),
                    patch("lib.core.fuzzer.NativeFuzzer", create_fuzzer),
                    patch("lib.controller.controller.signal.signal"),
                ):
                    try:
                        controller.wordlist_config = WordlistConfig.from_options(options)
                        controller.run()
                    finally:
                        if isinstance(controller.loop, asyncio.AbstractEventLoop):
                            controller.loop.close()

                self.assertEqual(
                    records,
                    [
                        ("current/", ["in-flight", "later"]),
                        ("next/", ["done", "in-flight", "later"]),
                        ("second/", ["done", "in-flight", "later"]),
                    ],
                )
                self.assertEqual(controller.run_state.jobs_processed, 6)
                self.assertEqual(controller.target_progress.directories, [])
                self.assertEqual(run_options["urls"], original_urls)
