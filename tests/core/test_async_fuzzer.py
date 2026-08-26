import asyncio
from unittest import IsolatedAsyncioTestCase

from lib.connection.response import NativeResponse
from lib.core.data import blacklists, options
from lib.core.dictionary import Dictionary
from lib.core.fuzzer import AsyncFuzzer


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

    def release_claim(self, path):
        return None


class DummyAsyncRequester:
    async def request(self, path):
        if path in ("", "home.html"):
            return NativeResponse(
                f"https://example.com/{path}",
                200,
                [("Content-Type", "text/plain")],
                b"same homepage body",
            )

        return NativeResponse(
            f"https://example.com/{path}",
            404,
            [("Content-Type", "text/plain")],
            b"not found",
        )


class BlockingAsyncRequester:
    def __init__(self):
        self.started = asyncio.Event()

    async def request(self, path):
        self.started.set()
        await asyncio.Event().wait()


def make_dictionary(paths):
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__((list(paths), 0, [], 0))
    return dictionary


class TestAsyncFuzzer(IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_options = dict(options)
        self.original_blacklists = dict(blacklists)
        options.update(
            {
                "thread_count": 1,
                "delay": 0,
                "exclude_response": None,
                "exclude_status_codes": set(),
                "include_status_codes": {200},
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
            }
        )
        blacklists.clear()

    def tearDown(self):
        options.clear()
        options.update(self.original_options)
        blacklists.clear()
        blacklists.update(self.original_blacklists)

    async def test_does_not_filter_response_matching_index_page(self):
        dictionary = DummyDictionary(["home.html"])
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

        await fuzzer.start()

        self.assertEqual(dictionary.index, 1)
        self.assertEqual([response.full_path for response in matches], ["home.html"])
        self.assertEqual(misses, [])
        self.assertEqual(errors, [])

    async def test_saved_state_retries_cancelled_in_flight_path(self):
        dictionary = make_dictionary(["admin", "login"])
        requester = BlockingAsyncRequester()
        fuzzer = AsyncFuzzer(
            requester,
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )

        async def skip_scanners():
            return None

        fuzzer.setup_scanners = skip_scanners
        run_task = asyncio.create_task(fuzzer.start())
        await requester.started.wait()

        saved_state = dictionary.__getstate__()
        run_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await run_task

        resumed = object.__new__(Dictionary)
        resumed.__setstate__(saved_state)
        self.assertEqual([next(resumed), next(resumed)], ["admin", "login"])
        with self.assertRaises(StopIteration):
            next(resumed)

    async def test_awaits_async_match_callbacks(self):
        dictionary = DummyDictionary(["home.html"])
        callback_finished = asyncio.Event()

        async def save_match(response):
            await asyncio.sleep(0)
            callback_finished.set()

        fuzzer = AsyncFuzzer(
            DummyAsyncRequester(),
            dictionary,
            match_callbacks=(save_match,),
            not_found_callbacks=(),
            error_callbacks=(),
        )

        await fuzzer.start()

        self.assertTrue(callback_finished.is_set())
