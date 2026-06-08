import time
from unittest import IsolatedAsyncioTestCase, TestCase

from lib.connection.response import NativeResponse
from lib.core.data import blacklists, options
from lib.core.exceptions import RequestException
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


class ErrorRequester:
    def request(self, path):
        raise RequestException(f"boom: {path}")


class DummyAsyncRequester:
    async def request(self, path):
        if path == "keep":
            return stack_response(path, b"keep admin panel")

        return stack_response(path, b"not found")


class DummyNativeRequester:
    _url = "https://example.com/"


class FilteringNativeBackend:
    def scan(self, base_url, paths, query=""):
        del base_url
        del query
        for path in paths:
            if path == "keep":
                yield path, stack_response(path, b"keep admin panel"), None
            else:
                yield (
                    path,
                    stack_response(
                        path,
                        b"not found",
                        filtered=True,
                        filter_reason="advanced_filter",
                    ),
                    None,
                )


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

    def test_runtime_filter_is_disabled_by_default(self):
        dictionary = DummyDictionary([])
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

        for index in range(9):
            fuzzer.process_response(
                f"block-{index}",
                stack_response(
                    f"block-{index}",
                    f"burst block /block-{index}".encode(),
                ),
            )

        self.assertEqual(len(matches), 9)
        self.assertEqual(misses, [])
        self.assertEqual(errors, [])
        self.assertEqual(fuzzer.recalibration_events, [])

    def test_runtime_filter_recalibrates_when_preflight_is_enabled(self):
        options["preflight"] = True
        dictionary = DummyDictionary([])
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

        for index in range(8):
            fuzzer.process_response(
                f"block-{index}",
                stack_response(
                    f"block-{index}",
                    f"burst block /block-{index}".encode(),
                ),
            )
        final_response = stack_response("block-final", b"burst block /block-final")
        fuzzer.process_response("block-final", final_response)

        self.assertEqual(len(matches), 8)
        self.assertEqual(misses, [final_response])
        self.assertEqual(errors, [])
        self.assertEqual(fuzzer.recalibration_events, ["repeated_match_fingerprint"])

    def test_runtime_filter_resets_match_streak_on_error(self):
        options["preflight"] = True
        dictionary = DummyDictionary([])
        matches = []
        misses = []
        errors = []
        fuzzer = Fuzzer(
            ErrorRequester(),
            dictionary,
            match_callbacks=(matches.append,),
            not_found_callbacks=(misses.append,),
            error_callbacks=(errors.append,),
        )

        for index in range(7):
            fuzzer.process_response(
                f"block-{index}",
                stack_response(
                    f"block-{index}",
                    f"burst block /block-{index}".encode(),
                ),
            )
        fuzzer.scan("boom")
        final_response = stack_response("block-final", b"burst block /block-final")
        fuzzer.process_response("block-final", final_response)

        self.assertEqual(len(matches), 8)
        self.assertEqual(misses, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(fuzzer.recalibration_events, [])


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
        fuzzer = NativeFuzzer(
            DummyNativeRequester(),
            dictionary,
            match_callbacks=(matches.append,),
            not_found_callbacks=(misses.append,),
            error_callbacks=(errors.append,),
        )
        fuzzer._native_backend = FilteringNativeBackend()
        fuzzer.setup_scanners = lambda: None

        fuzzer.start()

        self.assertEqual([response.full_path for response in matches], ["keep"])
        self.assertEqual([response.full_path for response in misses], ["drop"])
        self.assertTrue(misses[0].filtered)
        self.assertEqual(misses[0].filter_reason, "advanced_filter")
        self.assertEqual(misses[0].body, b"")
        self.assertEqual(errors, [])
