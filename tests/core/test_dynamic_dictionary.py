import asyncio
import time
from unittest import IsolatedAsyncioTestCase, TestCase

from lib.connection.response import NativeResponse
from lib.controller.controller import Controller
from lib.core.data import blacklists, options
from lib.core.dictionary import Dictionary
from lib.core.fuzzer import AsyncFuzzer, Fuzzer, NativeFuzzer


def make_dictionary(paths: list[str]) -> Dictionary:
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__((list(paths), 0, [], 0))
    return dictionary


def response_for(path: str) -> NativeResponse:
    return NativeResponse(
        f"https://example.com/{path}",
        200,
        [("content-type", "text/plain")],
        b"found",
    )


def crawled_paths_response() -> NativeResponse:
    return NativeResponse(
        "https://example.com/",
        200,
        [("content-type", "text/html")],
        (
            b'<a href="/private/secret">private</a>'
            b'<a href="/nested/private/secret">nested private</a>'
            b'<a href="/privateer/allowed">prefix neighbor</a>'
            b'<a href="/public/allowed?next=/private/secret">public</a>'
        ),
    )


def add_crawled_paths(dictionary: Dictionary) -> None:
    controller = object.__new__(Controller)
    controller.base_path = ""
    controller.dictionary = dictionary
    controller.add_crawled_paths(crawled_paths_response())


class RecordingSyncRequester:
    def __init__(self):
        self.paths = []

    def request(self, path):
        self.paths.append(path)
        return response_for(path)


class RecordingAsyncRequester:
    def __init__(self):
        self.paths = []

    async def request(self, path):
        self.paths.append(path)
        await asyncio.sleep(0)
        return response_for(path)


class DummyNativeRequester:
    _url = "https://example.com/"


class RecordingNativeBackend:
    def __init__(self):
        self.calls = []

    def scan(self, base_url, paths, query=""):
        del base_url
        del query
        self.calls.append(list(paths))
        for path in paths:
            yield path, response_for(path), None


class MembershipTrackingList(list):
    def __init__(self, values=()):
        super().__init__(values)
        self.contains_calls = 0

    def __contains__(self, value):
        self.contains_calls += 1
        return super().__contains__(value)


class DynamicDictionaryOptionsMixin:
    def setUp(self):
        self._original_options = dict(options)
        self._original_blacklists = dict(blacklists)
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
                "match_headers": [],
                "filter_headers": [],
                "match_header_regex": None,
                "filter_header_regex": None,
                "match_time": (),
                "filter_time": (),
                "auto_calibration": False,
                "exclude_subdirs": ["private/"],
            }
        )
        blacklists.clear()

    def tearDown(self):
        options.clear()
        options.update(self._original_options)
        blacklists.clear()
        blacklists.update(self._original_blacklists)

    @staticmethod
    def add_dynamic_path(dictionary):
        def callback(response):
            if response.full_path == "index.php":
                dictionary.add_extra("index.php.bak")

        return callback


class TestDynamicDictionaryMembership(DynamicDictionaryOptionsMixin, TestCase):
    def test_wordlist_membership_index_is_lazy_and_reused_after_reset(self):
        dictionary = make_dictionary(["seed"])

        self.assertIsNone(dictionary._item_membership)

        dictionary.add_extra("dynamic")
        membership = dictionary._item_membership
        dictionary.reset()

        self.assertIs(dictionary._item_membership, membership)

    def test_add_extra_does_not_scan_wordlist_or_dynamic_queue(self):
        dictionary = make_dictionary([])
        dictionary._items = MembershipTrackingList(["seed", "existing"])
        dictionary._extra = MembershipTrackingList()

        dictionary.add_extra("dynamic-one")
        dictionary.add_extra("dynamic-two")
        dictionary.add_extra("dynamic-one")
        dictionary.add_extra("existing")

        self.assertEqual(dictionary._items.contains_calls, 0)
        self.assertEqual(dictionary._extra.contains_calls, 0)
        self.assertEqual(dictionary._extra, ["dynamic-one", "dynamic-two"])

    def test_membership_indexes_follow_session_restore_and_reset(self):
        dictionary = make_dictionary(["seed"])
        dictionary.add_extra("dynamic")

        restored = object.__new__(Dictionary)
        restored.__setstate__(dictionary.__getstate__())
        restored.add_extra("seed")
        restored.add_extra("dynamic")
        restored.add_extra("fresh")

        self.assertEqual(restored._extra, ["dynamic", "fresh"])

        restored.reset()
        restored.add_extra("dynamic")

        self.assertEqual(restored._extra, ["dynamic"])


class TestSyncDynamicDictionary(DynamicDictionaryOptionsMixin, TestCase):
    def test_excluded_crawled_subdirectories_are_not_scanned(self):
        dictionary = make_dictionary(["seed"])
        add_crawled_paths(dictionary)
        requester = RecordingSyncRequester()
        fuzzer = Fuzzer(
            requester,
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer.setup_scanners = lambda: None

        fuzzer.start()
        deadline = time.time() + 2
        while not fuzzer.is_finished() and time.time() < deadline:
            time.sleep(0.01)

        self.assertTrue(fuzzer.is_finished())
        self.assertEqual(
            set(requester.paths),
            {
                "seed",
                "privateer/allowed",
                "public/allowed?next=/private/secret",
            },
        )

    def test_scans_path_added_by_match_callback(self):
        dictionary = make_dictionary(["index.php"])
        requester = RecordingSyncRequester()
        fuzzer = Fuzzer(
            requester,
            dictionary,
            match_callbacks=(self.add_dynamic_path(dictionary),),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer.setup_scanners = lambda: None

        fuzzer.start()
        deadline = time.time() + 2
        while not fuzzer.is_finished() and time.time() < deadline:
            time.sleep(0.01)

        self.assertTrue(fuzzer.is_finished())
        self.assertEqual(requester.paths, ["index.php", "index.php.bak"])


class TestAsyncDynamicDictionary(
    DynamicDictionaryOptionsMixin,
    IsolatedAsyncioTestCase,
):
    async def test_excluded_crawled_subdirectories_are_not_scanned(self):
        dictionary = make_dictionary(["seed"])
        add_crawled_paths(dictionary)
        requester = RecordingAsyncRequester()
        fuzzer = AsyncFuzzer(
            requester,
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )

        async def setup_scanners():
            return None

        fuzzer.setup_scanners = setup_scanners
        await fuzzer.start()

        self.assertEqual(
            set(requester.paths),
            {
                "seed",
                "privateer/allowed",
                "public/allowed?next=/private/secret",
            },
        )

    async def test_scans_path_added_by_match_callback(self):
        dictionary = make_dictionary(["index.php"])
        requester = RecordingAsyncRequester()
        fuzzer = AsyncFuzzer(
            requester,
            dictionary,
            match_callbacks=(self.add_dynamic_path(dictionary),),
            not_found_callbacks=(),
            error_callbacks=(),
        )

        async def setup_scanners():
            return None

        fuzzer.setup_scanners = setup_scanners
        await fuzzer.start()

        self.assertEqual(requester.paths, ["index.php", "index.php.bak"])


class TestNativeDynamicDictionary(DynamicDictionaryOptionsMixin, TestCase):
    def test_excluded_crawled_subdirectories_are_not_scanned(self):
        dictionary = make_dictionary(["seed"])
        add_crawled_paths(dictionary)
        backend = RecordingNativeBackend()
        fuzzer = NativeFuzzer(
            DummyNativeRequester(),
            dictionary,
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer._native_backend = backend
        fuzzer.setup_scanners = lambda: None

        fuzzer.start()

        self.assertEqual(
            set(backend.calls[0]),
            {
                "seed",
                "privateer/allowed",
                "public/allowed?next=/private/secret",
            },
        )

    def test_scans_path_added_by_match_callback_in_next_chunk(self):
        dictionary = make_dictionary(["index.php"])
        backend = RecordingNativeBackend()
        fuzzer = NativeFuzzer(
            DummyNativeRequester(),
            dictionary,
            match_callbacks=(self.add_dynamic_path(dictionary),),
            not_found_callbacks=(),
            error_callbacks=(),
        )
        fuzzer._native_backend = backend
        fuzzer.setup_scanners = lambda: None

        fuzzer.start()

        self.assertEqual(backend.calls, [["index.php"], ["index.php.bak"]])
