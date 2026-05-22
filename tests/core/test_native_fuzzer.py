from unittest import TestCase
from lib.connection.response import NativeResponse
from lib.core.data import blacklists, options
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


class DummyRequester:
    _url = "https://example.com/"


class FakeNativeBackend:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def scan(self, base_url, paths):
        self.calls.append((base_url, list(paths)))
        yield from self.items


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

        self.assertTrue(fuzzer.is_finished())
        self.assertEqual(dictionary.index, 1)
        self.assertEqual(matches, [response])
        self.assertEqual(misses, [])
        self.assertEqual(errors, [])
        self.assertEqual(backend.calls, [("https://example.com/", ["admin"])])

    def test_native_fuzzer_routes_backend_errors(self):
        error = RequestException("boom")
        backend = FakeNativeBackend([("admin", None, error)])
        dictionary = DummyDictionary(["admin"])
        matches = []
        misses = []
        errors = []

        fuzzer = self.make_fuzzer(backend, dictionary, matches, misses, errors)
        fuzzer.start()

        self.assertEqual(matches, [])
        self.assertEqual(misses, [])
        self.assertEqual(errors, [error])
