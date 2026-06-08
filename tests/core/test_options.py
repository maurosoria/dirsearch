import io
from contextlib import redirect_stdout
from unittest import TestCase
from unittest.mock import patch

from lib.core.options import parse_options


class TestOptions(TestCase):
    def test_response_size_options_accept_raw_bytes_and_units(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--exclude-sizes",
            "512,1KB,2MB",
            "--min-response-size",
            "1KB",
            "--max-response-size",
            "2MB",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertEqual(parsed["exclude_sizes"], {512, 1024, 2 * 1024 * 1024})
        self.assertEqual(parsed["minimum_response_size"], 1024)
        self.assertEqual(parsed["maximum_response_size"], 2 * 1024 * 1024)

    def test_response_size_options_accept_bytes_suffix(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--exclude-sizes",
            "1024B",
            "--min-response-size",
            "512B",
            "--max-response-size",
            "2048B",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertEqual(parsed["exclude_sizes"], {1024})
        self.assertEqual(parsed["minimum_response_size"], 512)
        self.assertEqual(parsed["maximum_response_size"], 2048)

    def test_header_filter_options_are_parsed(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--match-header",
            "etag: w/",
            "--filter-header",
            "x-cache: fallback",
            "--match-header-regex",
            "etag: .+",
            "--filter-header-regex",
            "x-cache: fallback-[0-9]+",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertEqual(parsed["match_headers"], ["etag: w/"])
        self.assertEqual(parsed["filter_headers"], ["x-cache: fallback"])
        self.assertEqual(parsed["match_header_regex"], "etag: .+")
        self.assertEqual(parsed["filter_header_regex"], "x-cache: fallback-[0-9]+")

    def test_invalid_header_regex_exits(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--filter-header-regex",
            "(",
        ]

        with patch("sys.argv", args), redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            parse_options()
