# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

from unittest import TestCase
from unittest.mock import patch

from lib.connection.response import NativeResponse, Response
from lib.core.data import options
from lib.core.fuzzer import BaseFuzzer
from lib.core.scanner import BaseScanner
from lib.core.settings import REFLECTED_PATH_MARKER, WILDCARD_TEST_POINT_MARKER
from lib.utils.diff import DynamicContentParser, normalize_dynamic_content


class DynamicSoft404Requester:
    def __init__(self):
        self.count = 0

    def request(self, path):
        self.count += 1
        body = (
            f"Not found: {path}. "
            f"Request id 550e8400-e29b-41d4-a716-{self.count:012d}. "
            "Please check the URL and try again."
        ).encode()
        return NativeResponse(
            f"https://example.com/{path}",
            200,
            [("content-type", "text/html")],
            body,
        )


class ChunkedResponse:
    status_code = 200
    history = []
    encoding = None

    def __init__(self, chunks):
        self._chunks = chunks
        self.headers = {
            "content-type": "application/octet-stream",
            "content-length": str(sum(map(len, chunks))),
        }

    def iter_content(self, chunk_size):
        del chunk_size
        yield from self._chunks


class TestScanner(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        options.update({"delay": 0, "auto_calibration": False})

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def test_generate_redirect_regex(self):
        self.assertEqual(
            BaseScanner.generate_redirect_regex(
                "http://example.com/abc/foo/xyz",
                "foo",
                "http://example.com/abc/bar/zyx",
                "bar",
            ),
            rf"^http://example\.com/abc{REFLECTED_PATH_MARKER}/.*$",
            "Redirect regex generator gives unexpected result"
        )

    def test_auto_calibration_filters_dynamic_soft_404(self):
        from lib.core.scanner import Scanner

        options["auto_calibration"] = True
        requester = DynamicSoft404Requester()
        scanner = Scanner(requester, path=WILDCARD_TEST_POINT_MARKER)
        response = requester.request("admin")

        self.assertGreater(scanner.sample_count, 2)
        self.assertFalse(scanner.check("admin", response))

    def test_dynamic_soft_404_does_not_hide_distinct_content(self):
        from lib.core.scanner import Scanner

        options["auto_calibration"] = True
        requester = DynamicSoft404Requester()
        scanner = Scanner(requester, path=WILDCARD_TEST_POINT_MARKER)
        response = NativeResponse(
            "https://example.com/admin",
            200,
            [("content-type", "text/html")],
            b"Admin dashboard with unique controls and a stable login form.",
        )

        self.assertTrue(scanner.check("admin", response))

    def test_binary_prefix_match_does_not_hide_distinct_response(self):
        prefix = b"\x00" + b"a" * 15
        scanner = BaseScanner(None)
        scanner.response = Response(
            "https://example.com/wildcard.bin",
            ChunkedResponse([prefix, b"LEFT"]),
        )
        response = Response(
            "https://example.com/admin.bin",
            ChunkedResponse([prefix, b"RGHT"]),
        )

        self.assertEqual(scanner.response.body, response.body)
        self.assertEqual(scanner.classify("admin.bin", response), "unique")
        self.assertEqual(scanner.reason, "response is unique enough")

    def test_binary_fingerprint_still_matches_identical_responses(self):
        prefix = b"\x00" + b"a" * 15
        scanner = BaseScanner(None)
        scanner.response = Response(
            "https://example.com/wildcard.bin",
            ChunkedResponse([prefix, b"SAME"]),
        )
        response = Response(
            "https://example.com/admin.bin",
            ChunkedResponse([prefix, b"SAME"]),
        )

        self.assertEqual(scanner.classify("admin.bin", response), "wildcard")
        self.assertEqual(scanner.reason, "matches wildcard profile")

    def test_response_normalization_is_reused_across_filter_and_scanner(self):
        base_content = "missing one two three four five six seven eight nine random"
        candidate_content = "missing one two three four five six seven eight nine admin"
        scanner = BaseScanner(None)
        scanner.response = NativeResponse(
            "https://example.com/random",
            200,
            [("content-type", "text/html")],
            base_content.encode(),
        )
        scanner.content_parser = DynamicContentParser(base_content, base_content)
        response = NativeResponse(
            "https://example.com/admin",
            200,
            [("content-type", "text/html")],
            candidate_content.encode(),
        )

        with patch(
            "lib.connection.response.normalize_dynamic_content",
            wraps=normalize_dynamic_content,
        ) as normalize:
            BaseFuzzer.response_fingerprint(response)
            self.assertEqual(scanner.classify("admin", response), "wildcard")

        normalize.assert_called_once_with(candidate_content)

    def test_probable_wildcard_skips_expensive_similarity_for_large_bodies(self):
        class DummyParser:
            static_patterns = ()
            is_ambiguous = True

            def similarity_to(self, *_args):
                raise AssertionError("expensive similarity should be skipped")

        large_body = b"a" * 270000
        scanner = BaseScanner(None)
        scanner.response = NativeResponse(
            "https://example.com/random",
            200,
            [("content-type", "text/html")],
            large_body,
        )
        scanner.content_parser = DummyParser()
        response = NativeResponse(
            "https://example.com/admin",
            200,
            [("content-type", "text/html")],
            large_body,
        )

        self.assertFalse(scanner.is_probable_wildcard("admin", response))

    def test_probable_wildcard_keeps_similarity_for_medium_bodies(self):
        class DummyParser:
            static_patterns = ()
            is_ambiguous = True

            def __init__(self):
                self.similarity_calls = []

            def similarity_to(self, *args):
                self.similarity_calls.append(args)
                return 1

        medium_body = b"a" * 70000
        scanner = BaseScanner(None)
        scanner.response = NativeResponse(
            "https://example.com/random",
            200,
            [("content-type", "text/html")],
            medium_body,
        )
        parser = DummyParser()
        scanner.content_parser = parser
        response = NativeResponse(
            "https://example.com/admin",
            200,
            [("content-type", "text/html")],
            medium_body,
        )

        self.assertTrue(scanner.is_probable_wildcard("admin", response))

        self.assertEqual(len(parser.similarity_calls), 1)
