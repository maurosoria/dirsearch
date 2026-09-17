import time
from unittest import IsolatedAsyncioTestCase, TestCase

from lib.connection.native import NativeScanBatch, NativeScanEvent
from lib.connection.response import NativeResponse
from lib.core.data import blacklists, options
from lib.core.fuzzer import AsyncFuzzer, Fuzzer, NativeFuzzer


class DummyDictionary:
    def __init__(self, paths):
        self.paths = paths
        self.index = 0

    def __next__(self):
        if self.index >= len(self.paths):
            raise StopIteration
        self.index += 1
        return self.paths[self.index - 1]

    def __len__(self):
        return len(self.paths)

    def claim_next(self):
        return next(self)

    def claim_many(self, maximum):
        start = self.index
        self.index = min(len(self.paths), start + maximum)
        return self.paths[start:self.index]

    def claim_native_many(self, maximum, _base_path):
        return self.claim_many(maximum)

    def release_claim(self, path):
        return None

    def release_claims(self, paths):
        return None

    def release_native_claims(self, _batch, _count):
        return None


def stack_response(path, body, *, filtered=False, filter_reason=None):
    return NativeResponse(
        f"https://example.com/{path}",
        200,
        [("content-type", "text/plain")],
        [] if filtered else body,
        length=len(body),
        filtered=filtered,
        filter_reason=filter_reason,
    )


class DummySyncRequester:
    def request(self, path):
        if path == "keep":
            return stack_response(path, b"keep admin panel")

        return stack_response(path, b"not found")


class DummyAsyncRequester:
    async def request(self, path):
        if path == "keep":
            return stack_response(path, b"keep admin panel")

        return stack_response(path, b"not found")


class DummyNativeRequester:
    _url = "https://example.com/"
    _query = ""

    def __init__(self, backend):
        self.backend = backend

    def get_backend(self):
        return self.backend


class FilteringNativeBackend:
    def scan_batch(self, base_url, paths, query=""):
        del base_url
        del query
        events = []
        for index, path in enumerate(paths):
            response = (
                stack_response(path, b"keep admin panel")
                if path == "keep"
                else stack_response(
                    path,
                    b"not found",
                    filtered=True,
                    filter_reason="advanced_filter",
                )
            )
            events.append(NativeScanEvent(index, path, response, None))
        return NativeScanBatch(len(paths), tuple(events))

    def reset_cancel(self):
        return None


class FilterStackOptionsMixin:
    def setUp(self):
        self.original_options = dict(options)
        self.original_blacklists = dict(blacklists)
        options.update(
            {
                "thread_count": 1,
                "delay": 0,
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
                "prefixes": (),
                "suffixes": (),
                "extensions": (),
                "auto_calibration": False,
                "matcher_mode": "and",
                "filter_mode": "or",
                "match_status_codes": {200},
                "filter_status_codes": set(),
                "match_sizes": (),
                "filter_sizes": (),
                "match_words": ((2, 3),),
                "filter_words": (),
                "match_lines": (),
                "filter_lines": (),
                "match_regex": None,
                "filter_regex": "not found",
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


class TestSyncFuzzerFilterStack(FilterStackOptionsMixin, TestCase):
    def test_filter_threshold_groups_path_reflections(self):
        options["filter_threshold"] = 1
        matches = []
        misses = []
        fuzzer = Fuzzer(
            DummySyncRequester(),
            DummyDictionary([]),
            match_callbacks=(matches.append,),
            not_found_callbacks=(misses.append,),
            error_callbacks=(),
        )
        first = stack_response("first", b"missing /first")
        second = stack_response("second", b"missing /second")

        self.assertEqual(fuzzer.response_callbacks("first", first), (matches.append,))
        self.assertEqual(fuzzer.response_callbacks("second", second), (misses.append,))

    def test_advanced_filters_apply_in_sync_stack(self):
        dictionary = DummyDictionary(["keep", "drop"])
        matches = []
        misses = []
        errors = []
        fuzzer = Fuzzer(
            DummySyncRequester(),
            dictionary,
            match_callbacks=(matches.append,),
            not_found_callbacks=(misses.append,),
            error_callbacks=(errors.append,),
        )
        fuzzer.setup_scanners = lambda: None

        fuzzer.start()
        deadline = time.time() + 2
        while not fuzzer.is_finished() and time.time() < deadline:
            time.sleep(0.01)

        self.assertTrue(fuzzer.is_finished())
        self.assertEqual([response.full_path for response in matches], ["keep"])
        self.assertEqual([response.full_path for response in misses], ["drop"])
        self.assertEqual(errors, [])


class TestAsyncFuzzerFilterStack(FilterStackOptionsMixin, IsolatedAsyncioTestCase):
    async def test_advanced_filters_apply_in_async_stack(self):
        async def setup_scanners():
            return None

        dictionary = DummyDictionary(["keep", "drop"])
        matches = []
        misses = []
        errors = []
        fuzzer = AsyncFuzzer(
            DummyAsyncRequester(),
            dictionary,
            match_callbacks=(matches.append,),
            not_found_callbacks=(misses.append,),
            error_callbacks=(errors.append,),
        )
        fuzzer.setup_scanners = setup_scanners

        await fuzzer.start()

        self.assertEqual([response.full_path for response in matches], ["keep"])
        self.assertEqual([response.full_path for response in misses], ["drop"])
        self.assertEqual(errors, [])


class TestNativeFuzzerFilterStack(FilterStackOptionsMixin, TestCase):
    def test_pushed_down_advanced_filters_apply_in_native_stack(self):
        dictionary = DummyDictionary(["keep", "drop"])
        matches = []
        misses = []
        errors = []
        backend = FilteringNativeBackend()
        fuzzer = NativeFuzzer(
            DummyNativeRequester(backend),
            dictionary,
            match_callbacks=(matches.append,),
            not_found_callbacks=(misses.append,),
            error_callbacks=(errors.append,),
        )
        fuzzer.setup_scanners = lambda: None

        fuzzer.start()

        self.assertEqual([response.full_path for response in matches], ["keep"])
        self.assertEqual([response.full_path for response in misses], ["drop"])
        self.assertTrue(misses[0].filtered)
        self.assertEqual(misses[0].filter_reason, "advanced_filter")
        self.assertEqual(misses[0].body, b"")
        self.assertEqual(errors, [])
