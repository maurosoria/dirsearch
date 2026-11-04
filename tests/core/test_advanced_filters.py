from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.connection.response import NativeResponse
from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig
from lib.core.filter_config import FilterConfig
from lib.core.filters import (
    parse_numeric_ranges,
    parse_size,
    parse_size_list,
    parse_time_filters,
)
from lib.core.fuzzer import BaseFuzzer
from lib.core.log_config import LogConfig
from lib.core.logger import RunLogger


class DummyDictionary:
    def __next__(self):
        raise StopIteration


def response(path="admin", status=200, body=b"admin panel", elapsed=0.0, headers=None):
    return NativeResponse(
        f"https://example.com/{path}",
        status,
        headers or [("content-type", "text/plain")],
        body,
        elapsed=elapsed,
    )


class TestAdvancedFilters(TestCase):
    def setUp(self):
        self.filter_options = {}

    def make_fuzzer(self):
        return BaseFuzzer(
            None,
            DummyDictionary(),
            filter_config=FilterConfig(**self.filter_options),
            discovery_config=DiscoveryConfig(),
            execution_config=ExecutionConfig(),
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )

    def test_match_status_is_opt_in(self):
        self.filter_options["match_status_codes"] = {200}

        fuzzer = self.make_fuzzer()
        self.assertFalse(fuzzer.is_excluded(response(status=200)))
        self.assertTrue(fuzzer.is_excluded(response(status=404)))

    def test_filter_regex_excludes_response_body(self):
        self.filter_options["filter_regex"] = "not found"

        fuzzer = self.make_fuzzer()
        self.assertTrue(fuzzer.is_excluded(response(body=b"not found")))
        self.assertFalse(fuzzer.is_excluded(response(body=b"admin panel")))

    def test_header_text_matchers_are_case_insensitive(self):
        self.filter_options["match_headers"] = ["etag: w/\"123"]

        fuzzer = self.make_fuzzer()
        self.assertFalse(
            fuzzer.is_excluded(
                response(headers=[("ETag", 'W/"123-abc"')])
            )
        )
        self.assertTrue(
            fuzzer.is_excluded(
                response(headers=[("X-Cache", "real")])
            )
        )

    def test_header_text_filters_exclude_matching_responses(self):
        self.filter_options["filter_headers"] = ["x-cache: fallback"]

        fuzzer = self.make_fuzzer()
        self.assertTrue(
            fuzzer.is_excluded(
                response(headers=[("X-Cache", "fallback")])
            )
        )
        self.assertFalse(
            fuzzer.is_excluded(
                response(headers=[("X-Cache", "real")])
            )
        )

    def test_header_regex_matchers_and_filters(self):
        self.filter_options["match_header_regex"] = r"ETag: W/\"[0-9]+"
        self.filter_options["filter_header_regex"] = r"X-Cache: fallback-[0-9]+"

        fuzzer = self.make_fuzzer()
        self.assertFalse(
            fuzzer.is_excluded(
                response(
                    headers=[
                        ("ETag", 'W/"123-abc"'),
                        ("X-Cache", "real"),
                    ]
                )
            )
        )
        self.assertTrue(
            fuzzer.is_excluded(
                response(
                    headers=[
                        ("ETag", 'W/"123-abc"'),
                        ("X-Cache", "fallback-404"),
                    ]
                )
            )
        )

    def test_parse_response_sizes(self):
        self.assertEqual(parse_size("1024"), 1024)
        self.assertEqual(parse_size("1024B"), 1024)
        self.assertEqual(parse_size("1KB"), 1024)
        self.assertEqual(parse_size("2MB"), 2 * 1024 * 1024)
        self.assertEqual(parse_size(" 3 gb "), 3 * 1024 ** 3)
        self.assertEqual(parse_size_list("1024,1KB,2MB"), {1024, 2 * 1024 * 1024})

    def test_parse_response_size_rejects_invalid_units(self):
        with self.assertRaises(ValueError):
            parse_size("12XB")

    def test_parse_response_sizes_preserves_every_unit(self):
        for power, unit in enumerate(("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")):
            with self.subTest(unit=unit):
                self.assertEqual(parse_size(f"2{unit}"), 2 * 1024 ** power)
                self.assertEqual(parse_size(f" 2 {unit.lower()} "), 2 * 1024 ** power)

    def test_exclude_sizes_match_raw_bytes_and_units(self):
        self.filter_options["exclude_sizes"] = parse_size_list("1024,2KB")

        fuzzer = self.make_fuzzer()
        self.assertTrue(fuzzer.is_excluded(response(body=b"x" * 1024)))
        self.assertTrue(fuzzer.is_excluded(response(body=b"x" * 2048)))
        self.assertFalse(fuzzer.is_excluded(response(body=b"x" * 1536)))

    def test_min_and_max_response_sizes_use_parsed_bytes(self):
        self.filter_options["minimum_response_size"] = parse_size("1KB")
        self.filter_options["maximum_response_size"] = parse_size("2KB")

        fuzzer = self.make_fuzzer()
        self.assertTrue(fuzzer.is_excluded(response(body=b"x" * 1023)))
        self.assertFalse(fuzzer.is_excluded(response(body=b"x" * 1024)))
        self.assertFalse(fuzzer.is_excluded(response(body=b"x" * 2048)))
        self.assertTrue(fuzzer.is_excluded(response(body=b"x" * 2049)))

    def test_size_words_lines_and_time_filters(self):
        self.filter_options["match_sizes"] = parse_numeric_ranges("10-20")
        self.filter_options["match_words"] = parse_numeric_ranges("2")
        self.filter_options["match_lines"] = parse_numeric_ranges("1")
        self.filter_options["match_time"] = parse_time_filters(">100")
        self.filter_options["matcher_mode"] = "and"

        fuzzer = self.make_fuzzer()
        self.assertFalse(
            fuzzer.is_excluded(
                response(body=b"admin panel", elapsed=0.2)
            )
        )
        self.assertTrue(
            fuzzer.is_excluded(
                response(body=b"admin panel", elapsed=0.05)
            )
        )

    def test_header_text_matcher_disables_auto_calibration(self):
        self.filter_options["auto_calibration"] = True
        self.filter_options["match_headers"] = ["x-result: found"]
        candidate = response(
            body=b"repeated response body that is long enough for calibration",
            headers=[("X-Result", "found")],
        )

        fuzzer = self.make_fuzzer()
        self.assertFalse(fuzzer.should_record_auto_calibration(candidate))

    def test_header_regex_matcher_disables_auto_calibration(self):
        self.filter_options["auto_calibration"] = True
        self.filter_options["match_header_regex"] = r"X-Result: found-[0-9]+"
        candidate = response(
            body=b"repeated response body that is long enough for calibration",
            headers=[("X-Result", "found-42")],
        )

        fuzzer = self.make_fuzzer()
        self.assertFalse(fuzzer.should_record_auto_calibration(candidate))

    def test_forced_auto_calibration_filters_repeated_reflected_responses(self):
        self.filter_options["auto_calibration"] = True
        repeated = [
            response(path=f"missing-{index}", body=f"missing missing-{index} soft 404 body with repeated template content".encode())
            for index in range(3)
        ]

        fuzzer = self.make_fuzzer()
        self.assertFalse(fuzzer.is_excluded(repeated[0]))
        self.assertFalse(fuzzer.is_excluded(repeated[1]))
        self.assertTrue(fuzzer.is_excluded(repeated[2]))

    def test_forced_auto_calibration_keeps_distinct_pages_after_a_shared_prefix(self):
        self.filter_options["auto_calibration"] = True
        fuzzer = self.make_fuzzer()
        prefix = b"shared-layout-word " * 300
        for path, tail in (("billing", b"Billing information."), ("support", b"Support information."), ("account/login", b"Account credentials.")):
            with self.subTest(path=path):
                candidate = response(path=path, body=prefix + tail)
                self.assertFalse(fuzzer.is_excluded(candidate))

    def test_duplicate_threshold_log_explains_discard_without_exposing_query_or_body(self):
        self.filter_options["filter_threshold"] = 1
        fuzzer = self.make_fuzzer()
        candidate = response(path="account/login?token=query-secret", body=b"private response body")
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "scan.log"
            logger = RunLogger(LogConfig(str(destination)))
            fuzzer.logger = logger
            try:
                self.assertFalse(fuzzer.is_filter_threshold_reached(candidate))
                self.assertTrue(fuzzer.is_filter_threshold_reached(candidate))
            finally:
                logger.close()
            contents = destination.read_text(encoding="utf-8")

        self.assertIn("filtered by duplicate response threshold", contents)
        self.assertIn("threshold=1, status=200", contents)
        self.assertIn("length=21, decoded_length=21", contents)
        self.assertIn("?token=<redacted>", contents)
        self.assertNotIn("query-secret", contents)
        self.assertNotIn("private response body", contents)

    def test_response_decision_logs_distinguish_matching_and_exclusion_stages(self):
        for decision in ("excluded", "wildcard", "duplicate", "match"):
            with self.subTest(decision=decision), TemporaryDirectory() as directory:
                fuzzer = self.make_fuzzer()
                candidate = response(path="account/login?token=query-secret", body=b"private body")
                destination = Path(directory, "scan.log")
                fuzzer.logger = RunLogger(LogConfig(str(destination)))
                scanner = Mock()
                scanner.check.return_value = decision != "wildcard"
                try:
                    with (
                        patch.object(fuzzer, "is_excluded", return_value=decision == "excluded"),
                        patch.object(fuzzer, "get_scanners_for", return_value=iter([scanner])),
                        patch.object(fuzzer, "is_filter_threshold_reached", return_value=decision == "duplicate"),
                    ):
                        fuzzer.response_callbacks(candidate.path, candidate)
                finally:
                    fuzzer.logger.close()
                contents = destination.read_text()
                self.assertIn(f"decision={decision}", contents)
                self.assertEqual(contents.count("decision="), 1)
                self.assertNotIn("query-secret", contents)
                self.assertNotIn("private body", contents)
