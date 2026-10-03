import threading
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.wordlist_config import WordlistConfig
from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig
from tests.core.test_backup_discovery import response_for


def policy_controller(policy):
    controller = object.__new__(Controller)
    controller.execution_config = ExecutionConfig()
    controller.discovery_config = policy
    controller._operation_lock = threading.Lock()
    controller.url = "http://example.test/"
    controller.base_path = ""
    controller.directories = []
    controller.passed_urls = set()
    controller.dictionary = Mock()
    return controller


class TestControllerDiscoveryConfig(TestCase):
    def test_recursion_depth_exclusions_and_deduplication_are_instance_owned(self):
        first = policy_controller(DiscoveryConfig(
            deep_recursive=True, recursion_depth=2, exclude_subdirs=["private/"],
        ))
        second = policy_controller(DiscoveryConfig(recursive=True, recursion_depth=1))
        with patch.dict(options, {}, clear=True):
            self.assertEqual(first.recur("public/nested/deeper/"), ["public/", "public/nested/"])
            self.assertEqual(first.recur("public/nested/deeper/"), [])
            self.assertEqual(first.recur("private/nested/"), [])
            self.assertEqual(second.recur("public/nested/"), [])
            self.assertEqual(second.recur("private/"), ["private/"])

    def test_forced_recursion_and_relative_depth_keep_existing_behavior(self):
        controller = policy_controller(DiscoveryConfig(
            recursive=True, force_recursive=True, recursion_depth=1,
        ))
        controller.base_path = "base/"
        with patch.dict(options, {}, clear=True):
            self.assertEqual(controller.recur("base/child"), ["base/child/"])
            self.assertEqual(controller.recur("base/child/deeper"), [])
            self.assertEqual(controller.recur("base/child"), [])

    def test_match_discovery_flags_ignore_later_global_mutations(self):
        enabled = policy_controller(DiscoveryConfig(crawl=True, find_backup=True))
        disabled = policy_controller(DiscoveryConfig())
        enabled.add_crawled_paths = Mock()
        disabled.add_crawled_paths = Mock()
        response = response_for("file.txt")
        with (
            patch.dict(options, {
                "skip_on_status": set(), "full_url": False, "replay_proxy": None,
            }, clear=True),
            patch("lib.controller.controller.interface"),
        ):
            enabled.match_callback(response)
            disabled.match_callback(response)

        enabled.add_crawled_paths.assert_called_once_with(response)
        enabled.dictionary.add_extra.assert_any_call("file.txt.bak")
        disabled.add_crawled_paths.assert_not_called()
        disabled.dictionary.add_extra.assert_not_called()

    def test_policy_is_built_after_setup_or_restore_and_shared_across_targets(self):
        for backend, async_mode, requester_path in (
            ("python", False, "lib.connection.requester.Requester"),
            ("python", True, "lib.connection.requester.AsyncRequester"),
            ("native", False, "lib.connection.native.NativeRequester"),
        ):
            for resumed in (False, True):
                with self.subTest(backend=backend, async_mode=async_mode, resumed=resumed):
                    fuzzers = []

                    def prepare(controller, *_args):
                        options.update(
                            prefixes=["restored-"], subdirs=["base/"],
                            recursive=True, recursion_depth=2,
                            exclude_subdirs=["private/"],
                            urls=["http://first.test/", "http://second.test/"],
                            session_file=None,
                        )
                        controller.wordlist_config = WordlistConfig.from_options(options)
                        controller.reporter = Mock(reports=())
                        controller.dictionary = Mock()
                        controller.directories = []
                        controller.passed_urls = set()

                    def set_target(controller, url):
                        controller.url = url
                        controller.base_path = ""

                    def start(controller):
                        fuzzers.append(controller.fuzzer)
                        self.assertIs(controller.fuzzer.discovery_config, controller.discovery_config)
                        self.assertEqual(controller.directories, ["base/"])
                        controller.directories.clear()
                        options["subdirs"].clear()
                        options["prefixes"].clear()
                        options["recursion_depth"] = 99

                    requester = Mock(backend=None)
                    if async_mode:
                        requester.close = AsyncMock()
                    with (
                        patch.dict(options, {
                            "request_backend": backend, "async_mode": async_mode,
                            "session_file": "session.json" if resumed else None,
                            "prefixes": [], "crawl": False,
                        }),
                        patch.object(Controller, "setup", new=prepare),
                        patch.object(Controller, "_import", new=prepare),
                        patch.object(Controller, "set_target", new=set_target),
                        patch.object(Controller, "crawl_target"),
                        patch.object(Controller, "start", new=start),
                        patch(requester_path, return_value=requester),
                        patch("lib.controller.controller.get_blacklists", return_value={}),
                        patch("lib.controller.controller.signal.signal"),
                        patch("lib.controller.controller.interface"),
                    ):
                        controller = Controller()

                    self.assertEqual(len(fuzzers), 2)
                    self.assertEqual(controller.discovery_config.prefixes, ("restored-",))
                    self.assertEqual(controller.discovery_config.recursion_depth, 2)
