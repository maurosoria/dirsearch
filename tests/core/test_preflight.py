import threading
import time
from unittest import IsolatedAsyncioTestCase, TestCase

from lib.connection.response import NativeResponse
from lib.core.data import blacklists, options
from lib.core.fingerprint import FingerprintResult
from lib.core.fuzzer import Fuzzer
from lib.core.preflight import (
    AsyncPreflightCalibrator,
    NativePreflightCalibrator,
    PreflightObservation,
    PreflightProfile,
    PreflightSample,
    SyncPreflightCalibrator,
    finalize_profile_observations,
    sample_preflight_paths,
)


class DummyDictionary:
    def __init__(self, paths):
        self.paths = list(paths)
        self.index = 0

    def __iter__(self):
        return iter(self.paths)

    def __next__(self):
        if self.index >= len(self.paths):
            raise StopIteration
        self.index += 1
        return self.paths[self.index - 1]

    def __len__(self):
        return len(self.paths)


class FakeScanner:
    context = "fake"

    def classify(self, path, response):
        if response.status == 404:
            return "wildcard"
        return "unique"


def response(path, status=200, body=b"blocked", headers=None):
    return NativeResponse(
        f"https://example.com/{path}",
        status,
        list((headers or {"content-type": "text/plain"}).items()),
        body,
    )


class BurstRequester:
    _url = "https://example.com/"

    def request(self, path):
        if options["thread_count"] > 1 and options["delay"] == 0:
            return response(path, 200, b"burst block", {"server": "cloudflare"})
        return response(path, 404, b"missing")


class RateLimitRequester:
    _url = "https://example.com/"

    def request(self, path):
        if options["max_rate"] == 0 or options["max_rate"] > 2:
            return response(
                path,
                429,
                b"Too Many Requests",
                {"server": "cloudflare"},
            )
        return response(path, 404, b"missing")


class ChallengeBodyRequester:
    _url = "https://example.com/"

    def request(self, path):
        if options["thread_count"] > 1:
            return response(
                path,
                200,
                b"Please complete the captcha challenge to continue.",
            )
        return response(path, 404, b"missing")


class ConcurrencySensitiveRequester:
    _url = "https://example.com/"

    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def request(self, path):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

        try:
            time.sleep(0.02)
            if self.active > 1 and options["delay"] == 0:
                return response(path, 200, b"burst block", {"server": "cloudflare"})
            return response(path, 404, b"missing")
        finally:
            with self.lock:
                self.active -= 1


class AsyncBurstRequester(BurstRequester):
    async def request(self, path):
        return super().request(path)


class AsyncRateLimitRequester(RateLimitRequester):
    async def request(self, path):
        return super().request(path)


class FakeNativeBackend:
    def __init__(self):
        self.calls = []

    def scan(self, base_url, paths, query="", *, apply_filters=True):
        self.calls.append((base_url, list(paths), query, apply_filters))
        del base_url, query
        for path in paths:
            if options["thread_count"] > 1 and options["delay"] == 0:
                yield path, response(path, 200, b"burst block"), None
            else:
                yield path, response(path, 404, b"missing"), None


class FakeNativeRateLimitBackend:
    def __init__(self):
        self.calls = []

    def scan(self, base_url, paths, query="", *, apply_filters=True):
        self.calls.append((base_url, list(paths), query, apply_filters))
        del base_url, query
        for path in paths:
            if options["max_rate"] == 0 or options["max_rate"] > 2:
                yield path, response(path, 429, b"Too Many Requests"), None
            else:
                yield path, response(path, 404, b"missing"), None


class FakeSyncPreflightCalibrator(SyncPreflightCalibrator):
    def _build_scanners(self):
        return {"default": {"fake": FakeScanner()}, "prefixes": {}, "suffixes": {}}


class FakeAsyncPreflightCalibrator(AsyncPreflightCalibrator):
    async def _build_scanners(self):
        return {"default": {"fake": FakeScanner()}, "prefixes": {}, "suffixes": {}}


class FakeNativePreflightCalibrator(NativePreflightCalibrator):
    def __init__(self, requester, dictionary, base_path=""):
        SyncPreflightCalibrator.__init__(self, requester, dictionary, base_path=base_path)
        self.native_backend = FakeNativeBackend()

    def _build_scanners(self):
        return {"default": {"fake": FakeScanner()}, "prefixes": {}, "suffixes": {}}


class FakeNativeRateLimitPreflightCalibrator(FakeNativePreflightCalibrator):
    def __init__(self, requester, dictionary, base_path=""):
        SyncPreflightCalibrator.__init__(self, requester, dictionary, base_path=base_path)
        self.native_backend = FakeNativeRateLimitBackend()


class PreflightOptionsMixin:
    def setUp(self):
        self.original_options = dict(options)
        self.original_blacklists = dict(blacklists)
        options.update(
            {
                "thread_count": 8,
                "delay": 0,
                "max_rate": 0,
                "preflight": True,
                "extensions": ("php",),
                "prefixes": (),
                "suffixes": (),
                "exclude_response": None,
                "exclude_status_codes": set(),
                "include_status_codes": set(),
                "exclude_sizes": set(),
                "minimum_response_size": 0,
                "maximum_response_size": 0,
                "exclude_texts": [],
                "exclude_regex": None,
                "exclude_redirect": None,
                "filter_threshold": 0,
                "auto_calibration": False,
                "matcher_mode": "or",
                "filter_mode": "or",
                "match_status_codes": set(),
                "filter_status_codes": set(),
                "match_sizes": (),
                "filter_sizes": (),
                "match_words": (),
                "filter_words": (),
                "match_lines": (),
                "filter_lines": (),
                "match_regex": None,
                "filter_regex": None,
                "match_time": (),
                "filter_time": (),
            }
        )
        blacklists.clear()

    def tearDown(self):
        options.clear()
        options.update(self.original_options)
        blacklists.clear()
        blacklists.update(self.original_blacklists)


class TestPreflight(PreflightOptionsMixin, TestCase):
    def test_sample_paths_do_not_consume_dictionary(self):
        dictionary = DummyDictionary(["admin", "login"])

        samples = sample_preflight_paths(dictionary, extensions=("php",))

        self.assertEqual(dictionary.index, 0)
        self.assertTrue(any(sample.expected_missing for sample in samples))
        self.assertTrue(any(not sample.expected_missing for sample in samples))

    def test_sync_preflight_selects_safer_profile(self):
        result = FakeSyncPreflightCalibrator(
            BurstRequester(),
            DummyDictionary(["admin", "login"]),
        ).run()

        self.assertTrue(result.adjusted)
        self.assertLess(result.applied_profile.thread_count, 8)
        self.assertGreater(result.applied_profile.delay, 0)
        self.assertEqual(result.fingerprint.provider, "cloudflare")
        self.assertIn("scanner_false_positive_burst", result.behavior_tags)
        self.assertIn("max-rate=", result.summary())

    def test_sync_preflight_selects_rate_limited_profile(self):
        result = FakeSyncPreflightCalibrator(
            RateLimitRequester(),
            DummyDictionary(["admin", "login"]),
        ).run()

        self.assertTrue(result.adjusted)
        self.assertEqual(result.applied_profile.max_rate, 2)
        self.assertIn("waf_rate_limit", result.behavior_tags)
        self.assertTrue(
            any(observation.denial_reason == "status_429" for observation in result.observations)
        )

    def test_sync_preflight_detects_challenge_body(self):
        result = FakeSyncPreflightCalibrator(
            ChallengeBodyRequester(),
            DummyDictionary(["admin", "login"]),
        ).run()

        self.assertEqual(result.applied_profile.thread_count, 1)
        self.assertIn("waf_challenge", result.behavior_tags)
        self.assertTrue(
            any(
                (observation.denial_reason or "").startswith("waf_body:")
                for observation in result.observations
            )
        )

    def test_preflight_marks_sustained_fingerprint_shift(self):
        profile = PreflightProfile("test", 4, 0, 0)
        observations = finalize_profile_observations(
            [
                PreflightObservation(
                    profile,
                    "clean-1",
                    True,
                    404,
                    ("fake:wildcard",),
                    False,
                    FingerprintResult(),
                    ("clean",),
                ),
                PreflightObservation(
                    profile,
                    "clean-2",
                    True,
                    404,
                    ("fake:wildcard",),
                    False,
                    FingerprintResult(),
                    ("clean",),
                ),
                PreflightObservation(
                    profile,
                    "shift-1",
                    True,
                    404,
                    ("fake:wildcard",),
                    False,
                    FingerprintResult(),
                    ("shift",),
                ),
                PreflightObservation(
                    profile,
                    "shift-2",
                    True,
                    404,
                    ("fake:wildcard",),
                    False,
                    FingerprintResult(),
                    ("shift",),
                ),
            ]
        )

        self.assertEqual(
            [
                observation.denial_reason
                for observation in observations
                if observation.path.startswith("shift")
            ],
            ["response_fingerprint_shift", "response_fingerprint_shift"],
        )

    def test_sync_preflight_runs_samples_concurrently(self):
        requester = ConcurrencySensitiveRequester()
        result = FakeSyncPreflightCalibrator(
            requester,
            DummyDictionary(["admin", "login"]),
        ).run()

        self.assertGreater(requester.max_active, 1)
        self.assertTrue(result.adjusted)

    def test_native_preflight_uses_native_burst_runner(self):
        calibrator = FakeNativePreflightCalibrator(
            BurstRequester(),
            DummyDictionary(["admin", "login"]),
        )
        result = calibrator.run()

        self.assertTrue(result.adjusted)
        self.assertLess(result.applied_profile.thread_count, 8)
        self.assertTrue(calibrator.native_backend.calls)
        self.assertTrue(
            all(not call[3] for call in calibrator.native_backend.calls)
        )

    def test_native_preflight_recommends_max_rate_without_support(self):
        result = FakeNativeRateLimitPreflightCalibrator(
            RateLimitRequester(),
            DummyDictionary(["admin", "login"]),
        ).run()

        self.assertEqual(result.applied_profile.max_rate, 2)
        self.assertFalse(result.max_rate_supported)
        self.assertIn("recommended-not-applied", result.summary())

    def test_recalibration_filters_future_repeated_matches(self):
        matches = []
        misses = []
        fuzzer = Fuzzer(
            BurstRequester(),
            DummyDictionary([]),
            match_callbacks=(matches.append,),
            not_found_callbacks=(misses.append,),
            error_callbacks=(),
        )
        fuzzer.setup_scanners = lambda: None

        for index in range(8):
            fuzzer.process_response(f"block-{index}", response(f"block-{index}"))
        fuzzer.process_response("block-final", response("block-final"))

        self.assertEqual(len(matches), 8)
        self.assertEqual(len(misses), 1)
        self.assertEqual(fuzzer.recalibration_events, ["repeated_match_fingerprint"])


class TestAsyncPreflight(PreflightOptionsMixin, IsolatedAsyncioTestCase):
    async def test_async_preflight_selects_safer_profile(self):
        result = await FakeAsyncPreflightCalibrator(
            AsyncBurstRequester(),
            DummyDictionary(["admin", "login"]),
        ).run()

        self.assertTrue(result.adjusted)
        self.assertLess(result.applied_profile.thread_count, 8)
        self.assertTrue(result.runtime_fingerprints)

    async def test_async_preflight_selects_rate_limited_profile(self):
        result = await FakeAsyncPreflightCalibrator(
            AsyncRateLimitRequester(),
            DummyDictionary(["admin", "login"]),
        ).run()

        self.assertEqual(result.applied_profile.max_rate, 2)
        self.assertIn("waf_rate_limit", result.behavior_tags)
