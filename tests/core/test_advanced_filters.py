from unittest import TestCase

from lib.connection.response import NativeResponse
from lib.core.data import blacklists, options
from lib.core.filters import (
    parse_numeric_ranges,
    parse_size,
    parse_size_list,
    parse_time_filters,
)
from lib.core.fuzzer import BaseFuzzer


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
        self.original_options = dict(options)
        self.original_blacklists = dict(blacklists)
        options.update(
            {
                "exclude_status_codes": set(),
                "include_status_codes": set(),
                "exclude_sizes": set(),
                "minimum_response_size": 0,
                "maximum_response_size": 0,
                "exclude_texts": [],
                "exclude_regex": None,
                "exclude_redirect": None,
                "filter_threshold": 0,
                "auto_calibration": False,
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
            }
        )
        blacklists.clear()
        self.fuzzer = BaseFuzzer(
            None,
            DummyDictionary(),
            match_callbacks=(),
            not_found_callbacks=(),
            error_callbacks=(),
        )

    def tearDown(self):
        options.clear()
        options.update(self.original_options)
        blacklists.clear()
        blacklists.update(self.original_blacklists)

    def test_match_status_is_opt_in(self):
        options["match_status_codes"] = {200}

        self.assertFalse(self.fuzzer.is_excluded(response(status=200)))
        self.assertTrue(self.fuzzer.is_excluded(response(status=404)))

    def test_filter_regex_excludes_response_body(self):
        options["filter_regex"] = "not found"

        self.assertTrue(self.fuzzer.is_excluded(response(body=b"not found")))
        self.assertFalse(self.fuzzer.is_excluded(response(body=b"admin panel")))

    def test_header_text_matchers_are_case_insensitive(self):
        options["match_headers"] = ["etag: w/\"123"]

        self.assertFalse(
            self.fuzzer.is_excluded(
                response(headers=[("ETag", 'W/"123-abc"')])
            )
        )
        self.assertTrue(
            self.fuzzer.is_excluded(
                response(headers=[("X-Cache", "real")])
            )
        )

    def test_header_text_filters_exclude_matching_responses(self):
        options["filter_headers"] = ["x-cache: fallback"]

        self.assertTrue(
            self.fuzzer.is_excluded(
                response(headers=[("X-Cache", "fallback")])
            )
        )
        self.assertFalse(
            self.fuzzer.is_excluded(
                response(headers=[("X-Cache", "real")])
            )
        )

    def test_header_regex_matchers_and_filters(self):
        options["match_header_regex"] = r"ETag: W/\"[0-9]+"
        options["filter_header_regex"] = r"X-Cache: fallback-[0-9]+"

        self.assertFalse(
            self.fuzzer.is_excluded(
                response(
                    headers=[
                        ("ETag", 'W/"123-abc"'),
                        ("X-Cache", "real"),
                    ]
                )
            )
        )
        self.assertTrue(
            self.fuzzer.is_excluded(
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

    def test_exclude_sizes_match_raw_bytes_and_units(self):
        options["exclude_sizes"] = parse_size_list("1024,2KB")

        self.assertTrue(self.fuzzer.is_excluded(response(body=b"x" * 1024)))
        self.assertTrue(self.fuzzer.is_excluded(response(body=b"x" * 2048)))
        self.assertFalse(self.fuzzer.is_excluded(response(body=b"x" * 1536)))

    def test_min_and_max_response_sizes_use_parsed_bytes(self):
        options["minimum_response_size"] = parse_size("1KB")
        options["maximum_response_size"] = parse_size("2KB")

        self.assertTrue(self.fuzzer.is_excluded(response(body=b"x" * 1023)))
        self.assertFalse(self.fuzzer.is_excluded(response(body=b"x" * 1024)))
        self.assertFalse(self.fuzzer.is_excluded(response(body=b"x" * 2048)))
        self.assertTrue(self.fuzzer.is_excluded(response(body=b"x" * 2049)))

    def test_size_words_lines_and_time_filters(self):
        options["match_sizes"] = parse_numeric_ranges("10-20")
        options["match_words"] = parse_numeric_ranges("2")
        options["match_lines"] = parse_numeric_ranges("1")
        options["match_time"] = parse_time_filters(">100")
        options["matcher_mode"] = "and"

        self.assertFalse(
            self.fuzzer.is_excluded(
                response(body=b"admin panel", elapsed=0.2)
            )
        )
        self.assertTrue(
            self.fuzzer.is_excluded(
                response(body=b"admin panel", elapsed=0.05)
            )
        )

    def test_forced_auto_calibration_filters_repeated_reflected_responses(self):
        options["auto_calibration"] = True
        repeated = [
            response(path=f"missing-{index}", body=f"missing missing-{index} soft 404 body with repeated template content".encode())
            for index in range(3)
        ]

        self.assertFalse(self.fuzzer.is_excluded(repeated[0]))
        self.assertFalse(self.fuzzer.is_excluded(repeated[1]))
        self.assertTrue(self.fuzzer.is_excluded(repeated[2]))
