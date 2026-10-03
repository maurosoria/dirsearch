from dataclasses import FrozenInstanceError
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.connection.response import NativeResponse
from lib.core.data import options
from lib.core.discovery_config import DiscoveryConfig
from lib.core.filter_config import FilterConfig
from lib.core.fuzzer import AsyncFuzzer, Fuzzer, NativeFuzzer
from lib.core.settings import DEFAULT_TEST_PREFIXES, DEFAULT_TEST_SUFFIXES


class TestDiscoveryConfig(TestCase):
    def test_mutable_collections_are_detached(self):
        prefixes = ["first-"]
        suffixes = ["~"]
        extensions = ["txt"]
        subdirs = ["", "base/"]
        excluded = ["private/"]
        statuses = {200, 301}
        config = DiscoveryConfig(
            prefixes=prefixes, suffixes=suffixes, extensions=extensions,
            subdirs=subdirs, exclude_subdirs=excluded, recursion_status_codes=statuses,
        )
        for values in (prefixes, suffixes, extensions, subdirs, excluded, statuses):
            values.clear()

        self.assertEqual(config.prefixes, ("first-",))
        self.assertEqual(config.suffixes, ("~",))
        self.assertEqual(config.extensions, ("txt",))
        self.assertEqual(config.subdirs, ("", "base/"))
        self.assertEqual(config.exclude_subdirs, ("private/",))
        self.assertEqual(config.recursion_status_codes, frozenset({200, 301}))
        with self.assertRaises(FrozenInstanceError):
            config.crawl = True

    def test_adapter_preserves_every_field_without_reading_globals(self):
        supplied = {
            "crawl": True, "find_backup": True,
            "recursive": True, "deep_recursive": True, "force_recursive": True,
            "recursion_depth": 2, "recursion_status_codes": {200, 403},
            "prefixes": ["first-", "first-"], "suffixes": ["~"],
            "extensions": ["txt"], "subdirs": ["", "base/"],
            "exclude_subdirs": ["private/"],
        }
        with patch.dict(options, {}, clear=True):
            actual = DiscoveryConfig.from_options(supplied)
        self.assertEqual(actual, DiscoveryConfig(**supplied))
        # This adapter freezes normalized input; it does not reorder, deduplicate
        # or reinterpret paths and therefore does not replace CLI validation.
        self.assertEqual(actual.prefixes, ("first-", "first-"))
        self.assertEqual(actual.subdirs[0], "")


class CalibrationRequester:
    backend = None

    def request(self, path):
        return NativeResponse(
            f"http://example.test/{path}", 200,
            [("Content-Type", "text/plain")], b"fixed wildcard content",
        )


class AsyncCalibrationRequester:
    async def request(self, path):
        return CalibrationRequester().request(path)


class TestCalibrationDiscoveryConfig(IsolatedAsyncioTestCase):
    async def test_existing_profile_construction_multiplicity_is_preserved(self):
        policy = DiscoveryConfig(
            prefixes=("first-", "first-"), suffixes=(".txt",), extensions=("txt",),
        )
        with patch.dict(options, {"delay": 0}, clear=True):
            for engine in (Fuzzer, AsyncFuzzer, NativeFuzzer):
                with self.subTest(engine=engine.__name__):
                    fuzzer = engine(
                        CalibrationRequester(), None, filter_config=FilterConfig(),
                        discovery_config=policy,
                        match_callbacks=(), not_found_callbacks=(), error_callbacks=(),
                    )
                    fuzzer.set_base_path("base/")
                    asynchronous = engine is AsyncFuzzer
                    factory = AsyncMock() if asynchronous else Mock()
                    factory_path = (
                        "lib.core.fuzzer.AsyncScanner.create"
                        if asynchronous else "lib.core.fuzzer.Scanner"
                    )
                    with patch(factory_path, factory):
                        if asynchronous:
                            await fuzzer.setup_scanners()
                        else:
                            fuzzer.setup_scanners()

                    paths = [call.kwargs["path"] for call in factory.call_args_list]
                    # Threaded/native deduplicate explicit profile prefixes;
                    # async currently iterates them. This refactor preserves both.
                    self.assertEqual(
                        sum(path.startswith("base/first-") for path in paths),
                        2 if asynchronous else 1,
                    )
                    # An explicit .txt suffix already provides this profile;
                    # the extension loop must not create another one.
                    self.assertEqual(sum(path.endswith(".txt") for path in paths), 1)
                    self.assertEqual(len(paths), 8 if asynchronous else 7)

    async def test_profile_variants_are_owned_by_each_fuzzer(self):
        policies = (
            DiscoveryConfig(prefixes=["first-"], suffixes=["~"], extensions=["txt"]),
            DiscoveryConfig(prefixes=["second-"], suffixes=[".old"], extensions=["html"]),
        )
        # Pacing is still a separate migration. No discovery options are present.
        with patch.dict(options, {"delay": 0}, clear=True):
            for engine in (Fuzzer, AsyncFuzzer, NativeFuzzer):
                with self.subTest(engine=engine.__name__):
                    fuzzers = []
                    for policy in policies:
                        requester = (
                            AsyncCalibrationRequester()
                            if engine is AsyncFuzzer else CalibrationRequester()
                        )
                        fuzzer = engine(
                            requester, None, filter_config=FilterConfig(),
                            discovery_config=policy,
                            match_callbacks=(), not_found_callbacks=(), error_callbacks=(),
                        )
                        fuzzer.set_base_path("base/")
                        if engine is AsyncFuzzer:
                            await fuzzer.setup_scanners()
                        else:
                            fuzzer.setup_scanners()
                        fuzzers.append(fuzzer)

                    for fuzzer, policy in zip(fuzzers, policies):
                        profiles = fuzzer.filter_state.scanners
                        self.assertEqual(
                            set(profiles["prefixes"]),
                            set(DEFAULT_TEST_PREFIXES) | set(policy.prefixes),
                        )
                        self.assertEqual(
                            set(profiles["suffixes"]),
                            set(DEFAULT_TEST_SUFFIXES) | set(policy.suffixes)
                            | {f".{extension}" for extension in policy.extensions},
                        )
                    self.assertIsNot(fuzzers[0].filter_state, fuzzers[1].filter_state)
