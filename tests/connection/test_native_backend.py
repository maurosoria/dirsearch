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


class FakeNativeEngine:
    def __init__(self, **config):
        self.config = config
        self.calls = []
        self.cancelled = False

    def scan(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return [FakeNativeResult()]

    def cancel(self):
        self.cancelled = True

    def reset_cancel(self):
        self.cancelled = False


class FakeNativeModule:
    def __init__(self):
        self.engines = []

    def NativeHttpEngine(self, **config):
        engine = FakeNativeEngine(**config)
        self.engines.append(engine)
        return engine


class TestNativeHTTPBackend(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "thread_count": 7,
                "timeout": 3.5,
                "headers": {"user-agent": "dirsearch-test"},
                "proxies": ["127.0.0.1:8080"],
                "proxy_auth": "user:password",
                "max_retries": 2,
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

        self.assertEqual(len(fake_native.engines), 1)
        engine = fake_native.engines[0]
        self.assertEqual(engine.config["concurrency"], 7)
        self.assertEqual(engine.config["timeout_secs"], 3.5)
        self.assertEqual(
            engine.config["proxies"],
            ["http://user:password@127.0.0.1:8080"],
        )

        args, kwargs = engine.calls[0]
        self.assertEqual(args[:2], ("https://example.com/", ["missing%20page"]))
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

    def test_proxy_urls_encode_reserved_credentials(self):
        options["proxy_auth"] = "proxy/user:p@ss/word?#%:tail"

        self.assertEqual(
            NativeHTTPBackend._proxy_urls(),
            [
                "http://proxy%2Fuser:p%40ss%2Fword%3F%23%25%3Atail"
                "@127.0.0.1:8080"
            ],
        )

    def test_reuses_engine_across_chunks_and_forwards_cancellation(self):
        fake_native = FakeNativeModule()

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            list(backend.scan("https://example.com/", ["first"]))
            list(backend.scan("https://example.com/", ["second"]))
            backend.cancel()

        self.assertEqual(len(fake_native.engines), 1)
        self.assertEqual(len(fake_native.engines[0].calls), 2)
        self.assertTrue(fake_native.engines[0].cancelled)

    def test_cancellation_before_engine_creation_is_forwarded_to_first_scan(self):
        fake_native = FakeNativeModule()

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            backend.cancel()
            list(backend.scan("https://example.com/", ["first"]))

        self.assertEqual(len(fake_native.engines), 1)
        self.assertTrue(fake_native.engines[0].cancelled)
        self.assertEqual(len(fake_native.engines[0].calls), 1)

    def test_reset_cancel_discards_cancellation_from_previous_lifecycle(self):
        fake_native = FakeNativeModule()

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            backend.cancel()
            backend.reset_cancel()
            list(backend.scan("https://example.com/", ["first"]))

        self.assertEqual(len(fake_native.engines), 1)
        self.assertFalse(fake_native.engines[0].cancelled)
        self.assertEqual(len(fake_native.engines[0].calls), 1)

    def test_origin_407_remains_a_response_without_a_proxy(self):
        fake_native = FakeNativeModule()
        options["proxies"] = []

        with (
            patch.dict("sys.modules", {"dirsearch_native": fake_native}),
            patch.object(FakeNativeResult, "status", 407),
        ):
            backend = NativeHTTPBackend()
            rows = list(backend.scan("https://example.com/", ["admin"]))

        self.assertEqual(len(rows), 1)
        _, response, error = rows[0]
        self.assertIsNone(error)
        self.assertEqual(response.status, 407)
