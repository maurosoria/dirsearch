import re
from unittest import TestCase
from unittest.mock import patch

from lib.connection.native import (
    NativeHTTPBackend,
    NativeRequester,
)
from lib.core.data import options
from lib.core.exceptions import RequestException
from lib.core.native_runtime import NATIVE_EXTENSION_VERSION
from lib.core.wordlist_backend import NativeWordlistBatch


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
    body_complete = True
    history = ["https://example.com/before"]
    final_url = "https://example.com/missing%20page"


class HistoryTrackingNativeResult(FakeNativeResult):
    def __init__(self, history):
        self._history = history
        self.history_reads = 0

    @property
    def history(self):
        self.history_reads += 1
        return self._history


class FakeNativeEngine:
    def __init__(self, results=None, **config):
        self.config = config
        self.calls = []
        self.owned_calls = []
        self.cancelled = False
        self.results = results

    def scan(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.results if self.results is not None else [FakeNativeResult()]

    def scan_owned_batch(self, *args, **kwargs):
        self.owned_calls.append((args, kwargs))
        return self.results if self.results is not None else [FakeNativeResult()]

    def cancel(self):
        self.cancelled = True

    def reset_cancel(self):
        self.cancelled = False


class FakeNativeModule:
    __version__ = NATIVE_EXTENSION_VERSION

    def __init__(self, results=None):
        self.engines = []
        self.filter_configs = []
        self.results = results

    def NativeHttpEngine(self, **config):
        engine = FakeNativeEngine(self.results, **config)
        self.engines.append(engine)
        return engine

    def NativeFilterConfig(self, **config):
        filter_config = type("FakeNativeFilterConfig", (), {"config": config})()
        self.filter_configs.append(filter_config)
        return filter_config


class IndexedNativeResult:
    def __init__(self, request_index, *, filtered, status=404, error=None):
        self.request_index = request_index
        self.path = f"path-{request_index}"
        self.status = status
        self.length = 2
        self.elapsed_ms = 1.0
        self.error = error
        self.filtered = filtered
        self.filter_reason = "advanced_filter" if filtered else None
        self.headers = [("content-type", "text/plain")]
        self.body = [] if filtered else [111, 107]
        self.body_complete = True
        self.history = []
        self.final_url = f"https://example.com/{self.path}"


class FakeOwnedBatch:
    def __init__(self, paths):
        self.paths = paths
        self.path_calls = []

    def len(self):
        return len(self.paths)

    def path_at(self, index):
        self.path_calls.append(index)
        return self.paths[index]

    def to_list(self):
        return list(self.paths)


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

    def test_rejects_an_incompatible_native_extension(self):
        fake_native = FakeNativeModule()
        fake_native.__version__ = "0.2.7"

        with (
            patch.dict("sys.modules", {"dirsearch_native": fake_native}),
            self.assertRaisesRegex(
                RequestException,
                rf"expected {re.escape(NATIVE_EXTENSION_VERSION)}, found 0\.2\.7",
            ),
        ):
            NativeHTTPBackend()

    def test_disabled_redirects_do_not_materialize_native_history(self):
        result = HistoryTrackingNativeResult(
            ["https://example.com/unexpected-redirect"]
        )
        fake_native = FakeNativeModule([result])

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            response = list(backend.scan("https://example.com/", ["admin"]))[0][1]

        self.assertEqual(result.history_reads, 0)
        self.assertEqual(response.history, [])

    def test_enabled_redirects_materialize_native_history_once(self):
        options["follow_redirects"] = True
        history = ["https://example.com/before"]
        result = HistoryTrackingNativeResult(history)
        fake_native = FakeNativeModule([result])

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            response = list(backend.scan("https://example.com/", ["admin"]))[0][1]

        self.assertEqual(result.history_reads, 1)
        self.assertEqual(response.history, history)

    def test_scan_reuses_native_filter_config_and_builds_filtered_response(self):
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
        self.assertEqual(response.history, [])

        self.assertEqual(len(fake_native.engines), 1)
        engine = fake_native.engines[0]
        self.assertEqual(engine.config["concurrency"], 7)
        self.assertEqual(engine.config["timeout_secs"], 3.5)
        self.assertEqual(engine.config["max_redirects"], 30)
        self.assertEqual(
            engine.config["proxies"],
            ["http://user:password@127.0.0.1:8080"],
        )

        args, kwargs = engine.calls[0]
        self.assertEqual(args[:2], ("https://example.com/", ["missing page"]))
        self.assertEqual(kwargs["query"], "")
        self.assertEqual(len(fake_native.filter_configs), 1)
        filter_options = fake_native.filter_configs[0].config
        self.assertIs(kwargs["filter_config"], fake_native.filter_configs[0])
        self.assertEqual(filter_options["include_status_codes"], [200, 204])
        self.assertEqual(filter_options["exclude_status_codes"], [500])
        self.assertEqual(filter_options["minimum_response_size"], 10)
        self.assertEqual(filter_options["maximum_response_size"], 200)
        self.assertEqual(filter_options["matcher_mode"], "and")
        self.assertEqual(filter_options["filter_mode"], "or")
        self.assertEqual(filter_options["match_status_codes"], [200])
        self.assertEqual(filter_options["filter_status_codes"], [404])
        self.assertEqual(filter_options["match_sizes"], [(10, 100)])
        self.assertEqual(filter_options["filter_regex"], "not found")
        self.assertEqual(filter_options["match_headers"], ["etag: w/"])
        self.assertEqual(filter_options["filter_headers"], ["x-cache: fallback"])
        self.assertEqual(filter_options["match_header_regex"], "etag: .+")
        self.assertEqual(
            filter_options["filter_header_regex"], "x-cache: fallback-[0-9]+"
        )
        self.assertEqual(filter_options["match_time"], [(">", 100.0)])

    def test_scan_batch_only_materializes_actionable_results(self):
        fake_native = FakeNativeModule(
            [
                IndexedNativeResult(1, filtered=False, status=200),
                IndexedNativeResult(2, filtered=True),
            ]
        )

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            batch = backend.scan_batch(
                "https://example.com/", ["zero", "one", "two"]
            )

        self.assertEqual(batch.processed_count, 3)
        self.assertEqual(len(batch.events), 1)
        event = batch.events[0]
        self.assertEqual((event.request_index, event.path), (1, "one"))
        self.assertEqual(event.response.status, 200)
        self.assertIsNone(event.error)
        self.assertTrue(fake_native.engines[0].calls[0][1]["compact_filtered"])

    def test_scan_batch_keeps_owned_wordlist_batch_native(self):
        fake_native = FakeNativeModule(
            [
                IndexedNativeResult(1, filtered=False, status=200),
                IndexedNativeResult(2, filtered=True),
            ]
        )
        native_batch = FakeOwnedBatch(["zero", "one", "two"])
        paths = NativeWordlistBatch(native_batch)

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            batch = backend.scan_batch("https://example.com/", paths)

        engine = fake_native.engines[0]
        self.assertEqual(engine.calls, [])
        self.assertEqual(len(engine.owned_calls), 1)
        self.assertIs(engine.owned_calls[0][0][1], native_batch)
        self.assertEqual(native_batch.path_calls, [1])
        self.assertEqual(batch.events[0].path, "one")

    def test_scan_batch_preserves_proxy_authentication_errors(self):
        fake_native = FakeNativeModule(
            [IndexedNativeResult(0, filtered=True, status=407)]
        )

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            batch = backend.scan_batch("https://example.com/", ["admin"])

        self.assertEqual(batch.processed_count, 1)
        self.assertEqual(len(batch.events), 1)
        self.assertIsNone(batch.events[0].response)
        self.assertEqual(str(batch.events[0].error), "Proxy authentication required")

    def test_native_requester_uses_unfiltered_native_engine_for_calibration(self):
        fake_native = FakeNativeModule(
            [IndexedNativeResult(0, filtered=False, status=404)]
        )

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            requester = NativeRequester()
            requester.set_url("https://example.com/")
            requester.set_query("scope=one")
            response = requester.request("missing page")

        self.assertEqual(response.status, 404)
        args, kwargs = fake_native.engines[0].calls[0]
        self.assertEqual(args[:2], ("https://example.com/", ["missing page"]))
        self.assertEqual(kwargs["query"], "scope=one")
        self.assertFalse(kwargs["compact_filtered"])
        self.assertIs(kwargs["filter_config"], fake_native.filter_configs[0])

    def test_response_url_uses_the_target_prepared_by_native(self):
        result = FakeNativeResult()
        result.path = "missing%20page?scope=one"
        fake_native = FakeNativeModule([result])

        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            backend = NativeHTTPBackend()
            rows = list(
                backend.scan(
                    "https://example.com/",
                    ["different raw path"],
                    "scope=one",
                )
            )

        self.assertEqual(
            rows[0][1].url,
            "https://example.com/missing%20page?scope=one",
        )

    def test_native_requester_defers_extension_import_until_first_request(self):
        with patch.dict("sys.modules", {"dirsearch_native": None}):
            requester = NativeRequester()
            requester.set_url("https://example.com/")

            with self.assertRaisesRegex(RequestException, "Native Rust backend"):
                requester.request("admin")

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
        self.assertEqual(len(fake_native.filter_configs), 1)
        self.assertIs(
            fake_native.engines[0].calls[0][1]["filter_config"],
            fake_native.engines[0].calls[1][1]["filter_config"],
        )
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
