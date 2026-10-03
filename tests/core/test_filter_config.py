from dataclasses import FrozenInstanceError
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from lib.core.data import options
from lib.core.discovery_config import DiscoveryConfig
from lib.core.filter_config import FilterConfig
from lib.core.fuzzer import AsyncFuzzer, Fuzzer, NativeFuzzer
from lib.core.scanner import AsyncScanner, BaseScanner, Scanner
from lib.core.settings import WILDCARD_TEST_POINT_MARKER
from tests.core.test_advanced_filters import DummyDictionary, response


class NativeRequesterStub:
    backend = None


class TestFilterConfig(TestCase):
    def test_collections_are_detached_and_deeply_immutable(self):
        statuses = {200}
        ranges = [[1, 10]]
        headers = ["X-Result: found"]
        blacklists = {403: ["/denied"]}
        config = FilterConfig(
            include_status_codes=statuses, match_sizes=ranges,
            match_headers=headers, blacklists=blacklists,
        )
        statuses.add(404)
        ranges[0][1] = 99
        headers.clear()
        blacklists[403].append("/allowed")

        self.assertEqual(config.include_status_codes, frozenset({200}))
        self.assertEqual(config.match_sizes, ((1, 10),))
        self.assertEqual(config.match_headers, ("X-Result: found",))
        self.assertEqual(config.blacklists, {403: ("/denied",)})
        with self.assertRaises(FrozenInstanceError):
            config.auto_calibration = True
        with self.assertRaises(TypeError):
            config.blacklists[403] = ()

    def test_options_adapter_reads_only_its_argument(self):
        values = dict(options)
        values.update(exclude_texts=["private"], filter_regex="missing")
        with patch.dict(options, {}, clear=True):
            config = FilterConfig.from_options(values, blacklists={404: ["/missing"]})
        values["exclude_texts"].clear()
        self.assertEqual(config.exclude_texts, ("private",))
        self.assertEqual(config.filter_regex, "missing")
        self.assertEqual(config.blacklists, {404: ("/missing",)})

    def test_native_adapter_returns_fresh_collections(self):
        config = FilterConfig(include_status_codes={201, 200}, match_sizes=[[1, 10]])
        first = config.native_options()
        first["include_status_codes"].append(404)
        first["match_sizes"].clear()
        second = config.native_options()
        self.assertEqual(second["include_status_codes"], [200, 201])
        self.assertEqual(second["match_sizes"], [(1, 10)])

    def test_filter_policy_and_state_are_isolated_in_every_engine(self):
        config = FilterConfig(filter_threshold=1, blacklists={403: ["/denied"]})
        for engine in (Fuzzer, AsyncFuzzer, NativeFuzzer):
            with self.subTest(engine=engine.__name__), patch.dict(options, {}, clear=True):
                def make_fuzzer(policy):
                    return engine(
                        NativeRequesterStub(), DummyDictionary(), filter_config=policy,
                        discovery_config=DiscoveryConfig(),
                        match_callbacks=(), not_found_callbacks=(), error_callbacks=(),
                    )

                first = make_fuzzer(config)
                second = make_fuzzer(config)
                other_policy = make_fuzzer(FilterConfig())
                denied = response(path="denied", status=403)
                self.assertTrue(first.is_excluded(denied))
                self.assertTrue(second.is_excluded(denied))
                self.assertFalse(other_policy.is_excluded(denied))
                candidate = response()
                self.assertFalse(first.is_filter_threshold_reached(candidate))
                self.assertTrue(first.is_filter_threshold_reached(candidate))
                self.assertFalse(second.is_filter_threshold_reached(candidate))
                self.assertIsNot(first.filter_state.lock, second.filter_state.lock)
                first.filter_state.scanners["default"]["sentinel"] = object()
                self.assertEqual(second.filter_state.scanners["default"], {})

    def test_calibration_counts_do_not_leak_between_targets(self):
        config = FilterConfig(auto_calibration=True)
        candidate = response(body=b"a repeated template long enough for calibration")
        for engine in (Fuzzer, AsyncFuzzer, NativeFuzzer):
            with self.subTest(engine=engine.__name__), patch.dict(options, {}, clear=True):
                fuzzers = [
                    engine(
                        NativeRequesterStub(), DummyDictionary(), filter_config=config,
                        discovery_config=DiscoveryConfig(),
                        match_callbacks=(), not_found_callbacks=(), error_callbacks=(),
                    )
                    for _ in range(2)
                ]
                self.assertFalse(fuzzers[0].is_auto_calibrated(candidate))
                self.assertFalse(fuzzers[0].is_auto_calibrated(candidate))
                self.assertTrue(fuzzers[0].is_auto_calibrated(candidate))
                self.assertFalse(fuzzers[1].is_auto_calibrated(candidate))

    def test_scanner_defaults_do_not_share_profiles(self):
        config = FilterConfig()
        first = BaseScanner(None, filter_config=config, delay=0)
        second = BaseScanner(None, filter_config=config, delay=0)
        first.tested["default"] = {}
        self.assertEqual(second.tested, {})
        shared = {}
        explicit = BaseScanner(None, filter_config=config, delay=0, tested=shared)
        self.assertIs(explicit.tested, shared)


class FixedResponseRequester:
    def request(self, path):
        return response(path=path, body=b"a fixed missing page with stable text")


class AsyncFixedResponseRequester:
    async def request(self, path):
        return FixedResponseRequester().request(path)


class TestScannerFilterConfig(IsolatedAsyncioTestCase):
    async def test_calibration_uses_explicit_policy_without_global_options(self):
        with patch.dict(options, {}, clear=True):
            for forced in (False, True):
                with self.subTest(forced=forced):
                    config = FilterConfig(auto_calibration=forced)
                    sync = Scanner(
                        FixedResponseRequester(), filter_config=config, delay=0,
                        path=WILDCARD_TEST_POINT_MARKER,
                    )
                    asynchronous = await AsyncScanner.create(
                        AsyncFixedResponseRequester(), filter_config=config, delay=0,
                        path=WILDCARD_TEST_POINT_MARKER,
                    )
                    for scanner in (sync, asynchronous):
                        self.assertEqual(scanner.sample_count, 4 if forced else 2)
                        self.assertFalse(scanner.check("missing", FixedResponseRequester().request("missing")))
                    self.assertIsNot(sync.tested, asynchronous.tested)
