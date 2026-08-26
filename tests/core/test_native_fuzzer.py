from unittest import TestCase
from lib.connection.response import NativeResponse
from lib.core.data import blacklists, options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import RequestException
from lib.core.fuzzer import NativeFuzzer


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


class DummyRequester:
    _url = "https://example.com/"


class FakeNativeBackend:
    def __init__(self, items):
        self.items = items
        self.calls = []
        self.cancelled = False

    def scan(self, base_url, paths, query=""):
        self.calls.append((base_url, list(paths), query))
        yield from self.items

    def cancel(self):
        self.cancelled = True


def make_dictionary(paths):
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__((list(paths), 0, [], 0))
    return dictionary


class TestNativeFuzzer(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        self.original_blacklists = dict(blacklists)
        options.update(
            {
                "thread_count": 2,
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
                "match_time": (),
                "filter_time": (),
                "auto_calibration": False,
            }
        )
        blacklists.clear()

    def tearDown(self):
        options.clear()
        options.update(self.original_options)
        blacklists.clear()
        blacklists.update(self.original_blacklists)

    def make_fuzzer(self, backend, dictionary, matches, misses, errors):
        fuzzer = NativeFuzzer(
            DummyRequester(),
            dictionary,
            match_callbacks=(matches.append,),
            not_found_callbacks=(misses.append,),
            error_callbacks=(errors.append,),
        )
        fuzzer._native_backend = backend
        fuzzer.setup_scanners = lambda: None
        return fuzzer

    def test_native_fuzzer_processes_native_responses(self):
        response = NativeResponse(
            "https://example.com/admin",
            200,
            [("content-type", "text/plain")],
            b"ok",
        )
        backend = FakeNativeBackend([("admin", response, None)])
        dictionary = DummyDictionary(["admin"])
        matches = []
        misses = []
        errors = []

        fuzzer = self.make_fuzzer(backend, dictionary, matches, misses, errors)
        fuzzer.start()

        self.assertTrue(fuzzer.wait(timeout=5))
        self.assertTrue(fuzzer.is_finished())
        self.assertEqual(dictionary.index, 1)
        self.assertEqual(matches, [response])
        self.assertEqual(misses, [])
        self.assertEqual(errors, [])
        self.assertEqual(backend.calls, [("https://example.com/", ["admin"], "")])

    def test_native_fuzzer_routes_backend_errors(self):
        error = RequestException("boom")
        backend = FakeNativeBackend([("admin", None, error)])
        dictionary = DummyDictionary(["admin"])
        matches = []
        misses = []
        errors = []

        fuzzer = self.make_fuzzer(backend, dictionary, matches, misses, errors)
        fuzzer.start()

        self.assertTrue(fuzzer.wait(timeout=5))
        self.assertEqual(matches, [])
        self.assertEqual(misses, [])
        self.assertEqual(errors, [error])

    def test_native_fuzzer_routes_filtered_results_to_not_found_callbacks(self):
        response = NativeResponse(
            "https://example.com/missing",
            404,
            [("content-type", "text/plain")],
            [],
            length=64,
            filtered=True,
            filter_reason="advanced_filter",
        )
        backend = FakeNativeBackend([("missing", response, None)])
        dictionary = DummyDictionary(["missing"])
        matches = []
        misses = []
        errors = []

        fuzzer = self.make_fuzzer(backend, dictionary, matches, misses, errors)
        fuzzer.start()

        self.assertTrue(fuzzer.wait(timeout=5))
        self.assertEqual(matches, [])
        self.assertEqual(misses, [response])
        self.assertEqual(errors, [])
        self.assertEqual(response.length, 64)

    def test_saved_state_retries_unreturned_chunk_paths(self):
        dictionary = make_dictionary(["admin", "login"])
        backend = FakeNativeBackend([])
        fuzzer = self.make_fuzzer(backend, dictionary, [], [], [])

        fuzzer.start()
        self.assertTrue(fuzzer.wait(timeout=5))
        saved_state = dictionary.__getstate__()

        resumed = object.__new__(Dictionary)
        resumed.__setstate__(saved_state)
        self.assertEqual([next(resumed), next(resumed)], ["admin", "login"])
        with self.assertRaises(StopIteration):
            next(resumed)

    def test_quit_cancels_active_native_engine(self):
        backend = FakeNativeBackend([])
        fuzzer = self.make_fuzzer(backend, DummyDictionary([]), [], [], [])

        fuzzer.quit()

        self.assertTrue(backend.cancelled)
