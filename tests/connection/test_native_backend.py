from unittest import TestCase
from unittest.mock import patch

from lib.connection.native import NativeHTTPBackend
from lib.core.data import options


class FakeNativeResult:
    path = "missing%20page"
    status = 404
    length = 64
    elapsed_ms = 125.0
    error = None
    filtered = True
    filter_reason = "advanced_filter"
    headers = [("content-type", "text/plain")]
    body = []


class FakeNativeModule:
    def __init__(self):
        self.calls = []

    def scan_http(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return [FakeNativeResult()]


class TestNativeHTTPBackend(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "thread_count": 7,
                "timeout": 3.5,
                "headers": {"user-agent": "dirsearch-test"},
                "max_retries": 2,
                "delay": 0.25,
                "max_rate": 3,
                "follow_redirects": False,
                "include_status_codes": {200, 204},
                "exclude_status_codes": {500},
                "minimum_response_size": 10,
                "maximum_response_size": 200,
                "matcher_mode": "and",
                "filter_mode": "or",
                "match_status_codes": {200},
                "filter_status_codes": {404},
                "match_sizes": ((10, 100),),
                "filter_sizes": ((0, 0),),
                "match_words": ((2, 10),),
                "filter_words": ((0, 0),),
                "match_lines": ((1, 5),),
                "filter_lines": ((0, 0),),
                "match_regex": "admin",
                "filter_regex": "not found",
                "match_headers": ["etag: w/"],
                "filter_headers": ["x-cache: fallback"],
                "match_header_regex": "etag: .+",
                "filter_header_regex": "x-cache: fallback-[0-9]+",
                "match_time": ((">", 100.0),),
                "filter_time": ((">", 2000.0),),
            }
        )

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def test_scan_passes_filter_options_and_builds_filtered_response(self):
        fake_native = FakeNativeModule()

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            rows = list(backend.scan("https://example.com/", ["missing page"]))

        self.assertEqual(len(rows), 1)
        path, response, error = rows[0]
        self.assertEqual(path, "missing page")
        self.assertIsNone(error)
        self.assertTrue(response.filtered)
        self.assertEqual(response.filter_reason, "advanced_filter")
        self.assertEqual(response.body, b"")
        self.assertEqual(response.length, 64)

        args, kwargs = fake_native.calls[0]
        self.assertEqual(args[:2], ("https://example.com/", ["missing%20page"]))
        self.assertEqual(kwargs["concurrency"], 7)
        self.assertEqual(kwargs["timeout_secs"], 3.5)
        self.assertEqual(kwargs["delay_secs"], 0.25)
        self.assertEqual(kwargs["max_rate"], 3)
        self.assertEqual(kwargs["include_status_codes"], [200, 204])
        self.assertEqual(kwargs["exclude_status_codes"], [500])
        self.assertEqual(kwargs["minimum_response_size"], 10)
        self.assertEqual(kwargs["maximum_response_size"], 200)
        self.assertEqual(kwargs["matcher_mode"], "and")
        self.assertEqual(kwargs["filter_mode"], "or")
        self.assertEqual(kwargs["match_status_codes"], [200])
        self.assertEqual(kwargs["filter_status_codes"], [404])
        self.assertEqual(kwargs["match_sizes"], [(10, 100)])
        self.assertEqual(kwargs["filter_regex"], "not found")
        self.assertEqual(kwargs["match_headers"], ["etag: w/"])
        self.assertEqual(kwargs["filter_headers"], ["x-cache: fallback"])
        self.assertEqual(kwargs["match_header_regex"], "etag: .+")
        self.assertEqual(kwargs["filter_header_regex"], "x-cache: fallback-[0-9]+")
        self.assertEqual(kwargs["match_time"], [(">", 100.0)])

    def test_scan_can_disable_filter_options(self):
        fake_native = FakeNativeModule()

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            list(
                backend.scan(
                    "https://example.com/",
                    ["missing page"],
                    apply_filters=False,
                )
            )

        _, kwargs = fake_native.calls[0]
        self.assertEqual(kwargs["include_status_codes"], [])
        self.assertEqual(kwargs["exclude_status_codes"], [])
        self.assertEqual(kwargs["minimum_response_size"], 0)
        self.assertEqual(kwargs["maximum_response_size"], 0)
        self.assertEqual(kwargs["matcher_mode"], "or")
        self.assertEqual(kwargs["filter_mode"], "or")
        self.assertEqual(kwargs["match_status_codes"], [])
        self.assertEqual(kwargs["filter_status_codes"], [])
        self.assertEqual(kwargs["match_sizes"], [])
        self.assertEqual(kwargs["filter_sizes"], [])
        self.assertEqual(kwargs["match_regex"], None)
        self.assertEqual(kwargs["filter_regex"], None)
        self.assertEqual(kwargs["match_time"], [])
        self.assertEqual(kwargs["filter_time"], [])
