import asyncio
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.connection.response import NativeResponse
from lib.core.run_config import RunConfig
from lib.controller.run_resources import RunResources
from lib.controller.controller import Controller
from lib.core.target_progress import TargetProgress
from lib.core.scan_run_state import ScanRunState
from lib.core.data import options
from lib.core.discovery_config import DiscoveryConfig
from lib.core.exceptions import RequestException
from lib.core.execution_config import ExecutionConfig, ScanEngine


class RecordingDictionary:
    def __init__(self):
        self.extra = []

    def is_valid(self, path):
        return path != "ignored"

    def add_extra(self, path):
        if not self.is_valid(path):
            return

        if path not in self.extra:
            self.extra.append(path)


class DummyFuzzer:
    def __init__(self, *args, **kwargs):
        pass


def root_response():
    return NativeResponse(
        "https://example.test/base/",
        200,
        [("Content-Type", "text/html")],
        (
            b'<a href="/base/root-only">root-only</a>'
            b'<a href="/base/ignored">ignored</a>'
        ),
    )


def resolved_html_response():
    return NativeResponse(
        "https://example.test/base/page",
        200,
        [("Content-Type", "text/html")],
        (
            b'<base href="/base/assets/">'
            b'<a href="api">API</a>'
            b'<a href="//other.test/external">external</a>'
            b'<img srcset="/base/render?size=1 1x, /base/render?size=2 2x">'
        ),
    )


def create_controller(requester, *, crawl=False, engine=ScanEngine.THREADED):
    controller = object.__new__(Controller)
    controller.resources = RunResources(interface=Mock(), logger=Mock())
    controller.config = RunConfig(execution=ExecutionConfig(engine=engine), discovery=DiscoveryConfig(crawl=crawl))
    controller.run_state = ScanRunState()
    controller.target_progress = TargetProgress()
    controller.resources.requester = requester
    controller.dictionary = RecordingDictionary()
    controller.target_progress.base_path = "base/"
    controller.raise_error = Mock()
    controller.append_error_log = Mock()
    return controller


class TestRootCrawl(TestCase):
    def setUp(self):
        self.original_options = dict(options)

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def test_run_seeds_paths_from_target_root_before_scan(self):
        requester = Mock()
        requester.request.return_value = root_response()
        controller = create_controller(requester)
        controller.resources.reporter = Mock()
        controller.target_progress.directories = []
        controller.run_state.passed_urls = set()
        controller.run_state.old_session = True
        controller.start = Mock()

        options.update(
            {
                "urls": ["https://example.test/base/"],
                "request_backend": "python",
                "async_mode": False,
                "subdirs": [""],
                "exclude_subdirs": [],
                "recursion_depth": 0,
                "session_file": None,
                "scheme": None,
                "ip": None,
                "crawl": True,
            }
        )

        with (
            patch("lib.connection.requester.Requester", return_value=requester),
            patch("lib.core.fuzzer.Fuzzer", DummyFuzzer),
            patch("lib.controller.controller.signal.signal"),
        ):
            controller._prepare_config(options)
            controller.run()

        requester.request.assert_called_once_with("base/")
        self.assertEqual(controller.dictionary.extra, ["root-only"])
        controller.start.assert_called_once_with()

    def test_async_root_request_is_awaited(self):
        requester = Mock()
        requester.request = AsyncMock(return_value=root_response())
        controller = create_controller(requester, crawl=True, engine=ScanEngine.ASYNC)
        controller.resources.loop = asyncio.new_event_loop()

        try:
            with patch.dict(options, {}, clear=True):
                controller.crawl_target()
        finally:
            controller.resources.loop.close()

        requester.request.assert_awaited_once_with("base/")
        self.assertEqual(controller.dictionary.extra, ["root-only"])

    def test_crawled_html_paths_are_resolved_before_queueing(self):
        controller = create_controller(Mock())

        controller.add_crawled_paths(resolved_html_response())

        self.assertEqual(
            set(controller.dictionary.extra),
            {"assets/api", "render?size=1", "render?size=2"},
        )

    def test_threaded_and_native_root_requests_ignore_global_flags(self):
        for engine in (ScanEngine.THREADED, ScanEngine.NATIVE):
            with self.subTest(engine=engine):
                requester = Mock()
                requester.request.return_value = root_response()
                controller = create_controller(requester, crawl=True, engine=engine)
                with patch.dict(options, {}, clear=True):
                    controller.crawl_target()
                requester.request.assert_called_once_with("base/")
                self.assertEqual(controller.dictionary.extra, ["root-only"])

    def test_disabled_crawl_does_not_request_target_root(self):
        requester = Mock()
        controller = create_controller(requester)

        with patch.dict(options, {"async_mode": False, "crawl": False}):
            controller.crawl_target()

        requester.request.assert_not_called()
        self.assertEqual(controller.dictionary.extra, [])

    def test_root_request_failure_uses_scan_error_callbacks(self):
        error = RequestException("root request failed")
        requester = Mock()
        requester.request.side_effect = error
        controller = create_controller(requester, crawl=True)

        with patch.dict(options, {"async_mode": False, "crawl": True}):
            controller.crawl_target()

        controller.raise_error.assert_called_once_with(error)
        controller.append_error_log.assert_called_once_with(error)
        self.assertEqual(controller.dictionary.extra, [])
