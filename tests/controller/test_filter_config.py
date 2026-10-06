from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.result_config import ResultConfig
from lib.core.wordlist_config import WordlistConfig
from lib.core.fuzzer import AsyncFuzzer, Fuzzer, NativeFuzzer
from tests.core.test_advanced_filters import response


class TestControllerFilterConfig(TestCase):
    def test_preparation_builds_one_policy_and_fresh_state_for_each_target(self):
        for backend, async_mode, requester_path, fuzzer_class in (
            ("python", False, "lib.connection.requester.Requester", Fuzzer),
            ("python", True, "lib.connection.requester.AsyncRequester", AsyncFuzzer),
            ("native", False, "lib.connection.native.NativeRequester", NativeFuzzer),
        ):
            for resumed in (False, True):
                with self.subTest(backend=backend, async_mode=async_mode, resumed=resumed):
                    fuzzers = []
                    blacklists = {403: ["/denied"]}
                    prepared = []

                    def prepare(controller, *_args):
                        prepared.append(True)
                        options.update(
                            include_status_codes={200, 403}, filter_threshold=1,
                            exclude_texts=[], session_file=None, subdirs=[],
                            urls=["http://first.test/", "http://second.test/"],
                        )
                        controller.wordlist_config = WordlistConfig.from_options(options)
                        controller.result_config = ResultConfig.from_options(options)
                        controller.reporter = Mock(reports=())
                        controller.dictionary = Mock()
                        controller.target_progress.directories = []

                    def load_blacklists(wordlist_config):
                        self.assertEqual(prepared, [True])
                        self.assertIsInstance(wordlist_config, WordlistConfig)
                        return blacklists

                    def set_target(controller, url):
                        controller.target_progress.url = url

                    def start(controller):
                        fuzzer = controller.fuzzer
                        fuzzers.append(fuzzer)
                        self.assertIsInstance(fuzzer, fuzzer_class)
                        self.assertIs(fuzzer.filter_config, controller.filter_config)
                        # Changing option storage and the original source must
                        # not alter an already configured run or its next target.
                        options["include_status_codes"].clear()
                        options["filter_threshold"] = 0
                        blacklists[403].clear()
                        self.assertTrue(fuzzer.is_excluded(response(status=404)))
                        self.assertTrue(fuzzer.is_excluded(response(path="denied", status=403)))
                        candidate = response()
                        self.assertFalse(fuzzer.is_filter_threshold_reached(candidate))
                        self.assertTrue(fuzzer.is_filter_threshold_reached(candidate))

                    requester = Mock(backend=None)
                    if async_mode:
                        requester.close = AsyncMock()
                    with (
                        patch.dict(options, {
                            "request_backend": backend, "async_mode": async_mode,
                            "session_file": "session.json" if resumed else None,
                            "include_status_codes": set(), "filter_threshold": 0,
                        }),
                        patch.object(Controller, "setup", new=prepare),
                        patch.object(Controller, "_import", new=prepare),
                        patch.object(Controller, "set_target", new=set_target),
                        patch.object(Controller, "crawl_target"),
                        patch.object(Controller, "start", new=start),
                        patch(requester_path, return_value=requester) as factory,
                        patch("lib.controller.controller.get_blacklists", side_effect=load_blacklists) as loader,
                        patch("lib.controller.controller.signal.signal"),
                        patch("lib.controller.controller.create_terminal"),
                    ):
                        controller = Controller()

                    loader.assert_called_once_with(controller.wordlist_config)
                    self.assertEqual(len(fuzzers), 2)
                    self.assertIsNot(fuzzers[0].filter_state, fuzzers[1].filter_state)
                    if backend == "native":
                        self.assertIs(factory.call_args.kwargs["filter_config"], controller.filter_config)
