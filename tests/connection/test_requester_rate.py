"""Offline display-rate contracts; pacing remains the limiter's responsibility."""

import threading
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from lib.connection.rate_limiter import RequestRateLimiter
from lib.connection.requester import AsyncRequester, BaseRequester, Requester
from lib.core.request_config import RequestConfig
from lib.core.settings import RATE_UPDATE_DELAY


class SampleRateMeter:
    def __init__(self, value=0):
        self.sample = Mock(return_value=value)

    @property
    def rate(self):
        return self.sample()


class TestRequesterRate(TestCase):
    def setUp(self):
        clock_patch = patch("lib.connection.requester.time.monotonic", return_value=0.0)
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.requester = BaseRequester(RequestConfig())
        self.meter = SampleRateMeter(4)
        self.requester._rate_limiter = self.meter

    def test_snapshot_expires_at_the_display_interval(self):
        self.assertEqual(RATE_UPDATE_DELAY, 0.15)
        self.assertEqual(self.requester.rate, 4)
        self.meter.sample.return_value = 7

        self.clock.return_value = RATE_UPDATE_DELAY - 0.001
        self.assertEqual(self.requester.rate, 4)
        self.meter.sample.assert_called_once_with()

        self.clock.return_value = RATE_UPDATE_DELAY
        self.assertEqual(self.requester.rate, 7)
        self.assertEqual(self.meter.sample.call_count, 2)

    def test_zero_is_a_cached_sample(self):
        self.meter.sample.return_value = 0
        self.assertEqual(self.requester.rate, 0)
        self.meter.sample.return_value = 3
        self.assertEqual(self.requester.rate, 0)
        self.meter.sample.assert_called_once_with()

    def test_instances_have_independent_samples(self):
        other = BaseRequester(RequestConfig())
        other._rate_limiter = SampleRateMeter(9)

        self.assertEqual(self.requester.rate, 4)
        self.assertEqual(other.rate, 9)
        self.assertEqual(self.requester.rate, 4)
        self.meter.sample.assert_called_once_with()
        other._rate_limiter.sample.assert_called_once_with()

    def test_refresh_does_not_use_wall_clock(self):
        with patch("time.time", side_effect=AssertionError("wall clock used")):
            self.assertEqual(self.requester.rate, 4)
            self.clock.return_value = RATE_UPDATE_DELAY
            self.meter.sample.return_value = 8
            self.assertEqual(self.requester.rate, 8)

    def test_failed_sample_can_be_retried(self):
        self.meter.sample.side_effect = [RuntimeError("sample failed"), 6]

        with self.assertRaisesRegex(RuntimeError, "sample failed"):
            _ = self.requester.rate
        self.assertEqual(self.requester.rate, 6)
        self.assertEqual(self.requester.rate, 6)
        self.assertEqual(self.meter.sample.call_count, 2)

    def test_failed_refresh_does_not_extend_a_stale_snapshot(self):
        self.meter.sample.side_effect = [4, RuntimeError("sample failed"), 8]
        self.assertEqual(self.requester.rate, 4)
        self.clock.return_value = RATE_UPDATE_DELAY

        with self.assertRaisesRegex(RuntimeError, "sample failed"):
            _ = self.requester.rate
        self.assertEqual(self.requester.rate, 8)
        self.assertEqual(self.meter.sample.call_count, 3)

    def test_display_snapshot_does_not_change_rate_accounting(self):
        limiter = RequestRateLimiter(clock=self.clock)
        self.requester._rate_limiter = limiter
        self.assertEqual(self.requester.rate, 0)

        limiter.wait(max_rate=0)
        self.assertEqual(limiter.rate, 1)
        self.assertEqual(self.requester.rate, 0)

        self.clock.return_value = RATE_UPDATE_DELAY
        self.assertEqual(self.requester.rate, 1)
        self.clock.return_value = 1.0
        self.assertEqual(self.requester.rate, 0)

    def test_slow_sample_does_not_block_another_requester(self):
        entered = threading.Event()
        release = threading.Event()
        other_finished = threading.Event()
        results = {}
        errors = []
        other = BaseRequester(RequestConfig())
        other._rate_limiter = SampleRateMeter(9)

        def slow_sample():
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError("sample was not released")
            return 4

        def read_rate(name, requester, finished=None):
            try:
                results[name] = requester.rate
            except Exception as error:
                errors.append(error)
            finally:
                if finished is not None:
                    finished.set()

        self.meter.sample.side_effect = slow_sample
        first = threading.Thread(target=read_rate, args=("first", self.requester))
        second = threading.Thread(
            target=read_rate, args=("second", other, other_finished)
        )
        first.start()
        try:
            self.assertTrue(entered.wait(timeout=2))
            second.start()
            self.assertTrue(other_finished.wait(timeout=2))
            self.assertEqual(results["second"], 9)
        finally:
            release.set()
            first.join(timeout=2)
            if second.ident is not None:
                second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, {"first": 4, "second": 9})


class TestPythonRequesterRateParity(IsolatedAsyncioTestCase):
    async def test_threaded_and_async_use_the_same_display_interval(self):
        sync_requester = Requester(RequestConfig())
        self.addCleanup(sync_requester.session.close)
        async_requester = AsyncRequester(RequestConfig())
        self.addAsyncCleanup(async_requester.session.aclose)

        for requester in (sync_requester, async_requester):
            with self.subTest(requester=type(requester).__name__):
                with patch("lib.connection.requester.time.monotonic", return_value=0.0) as clock:
                    meter = SampleRateMeter(2)
                    requester._rate_limiter = meter
                    self.assertEqual(requester.rate, 2)
                    meter.sample.return_value = 5
                    self.assertEqual(requester.rate, 2)
                    clock.return_value = RATE_UPDATE_DELAY
                    self.assertEqual(requester.rate, 5)
                    self.assertEqual(meter.sample.call_count, 2)
