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

from lib.connection.response import NativeResponse
from lib.core.data import options
from lib.core.scanner import BaseScanner
from lib.core.settings import REFLECTED_PATH_MARKER, WILDCARD_TEST_POINT_MARKER


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

    def test_probable_wildcard_skips_expensive_similarity_for_large_bodies(self):
        class DummyParser:
            static_patterns = ()
            is_ambiguous = True

        scanner = BaseScanner(None)
        scanner.response = NativeResponse(
            "https://example.com/random",
            200,
            [("content-type", "text/html")],
            b"a" * 9000,
        )
        scanner.content_parser = DummyParser()
        response = NativeResponse(
            "https://example.com/admin",
            200,
            [("content-type", "text/html")],
            b"a" * 9000,
        )

        with patch(
            "lib.core.scanner.content_similarity",
            side_effect=AssertionError("expensive similarity should be skipped"),
        ):
            self.assertFalse(scanner.is_probable_wildcard("admin", response))
