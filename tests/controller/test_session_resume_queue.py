import asyncio
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.dictionary import Dictionary


class RecordingFuzzer:
    def __init__(self, _requester, dictionary, records, *args, **kwargs):
        self.dictionary = dictionary
        self.records = records
        self.base_path = ""

    def set_base_path(self, path):
        self.base_path = path

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
        controller.start_time = 0
        controller.passed_urls = set()
        controller.directories = ["current/", "next/"]
        controller.jobs_processed = 3
        controller.errors = 0
        controller.consecutive_errors = 0
        controller.base_path = "first/"
        controller.url = "https://first.example/"
        controller.old_session = True
        controller.dictionary = object.__new__(Dictionary)
        controller.dictionary.__setstate__(
            (["done", "in-flight", "later"], 2, ["in-flight"], 0)
        )
        controller.output_history = []
        controller.response_stores = ()
        controller.reporter = Mock()
        controller.crawl_target = Mock()

        def set_target(url):
            controller.url = url
            controller.base_path = (
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

                with (
                    patch.dict(options, run_options),
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
                    patch("lib.controller.controller.interface"),
                ):
                    try:
                        controller.run()
                    finally:
                        loop = getattr(controller, "loop", None)
                        if isinstance(loop, asyncio.AbstractEventLoop):
                            loop.close()

                self.assertEqual(
                    records,
                    [
                        ("current/", ["in-flight", "later"]),
                        ("next/", ["done", "in-flight", "later"]),
                        ("second/", ["done", "in-flight", "later"]),
                    ],
                )
                self.assertEqual(controller.jobs_processed, 6)
                self.assertEqual(controller.directories, [])
