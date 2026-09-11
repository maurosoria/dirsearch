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

from lib.core.settings import DUMMY_URL
from lib.parse.url import (
    append_query_string,
    clean_path,
    ensure_trailing_path_slash,
    parse_path,
    same_origin,
    same_origin_path,
)


class TestURLParsers(TestCase):
    def test_clean_path(self):
        self.assertEqual(clean_path("/foo?a=1#a=1"), "/foo")
        self.assertEqual(clean_path("/foo?a=1#a=1", keep_queries=True), "/foo?a=1")

    def test_parse_path(self):
        self.assertEqual(
            parse_path("foo/bar"),
            "foo/bar",
            "Path parser gives unexpected result")
        self.assertEqual(
            parse_path("/foo/bar"),
            "foo/bar",
            "Path parser gives unexpected result")
        self.assertEqual(
            parse_path(f"{DUMMY_URL}foo/bar"),
            "foo/bar",
            "Path parser gives unexpected result",
        )

    def test_ensure_trailing_path_slash_preserves_query(self):
        self.assertEqual(
            ensure_trailing_path_slash("https://example.com/admin?debug=true"),
            "https://example.com/admin/?debug=true",
        )

    def test_append_query_string(self):
        self.assertEqual(append_query_string("admin", "debug=true"), "admin?debug=true")
        self.assertEqual(
            append_query_string("admin?existing=true", "debug=true"),
            "admin?existing=true",
        )

    def test_same_origin_normalizes_host_case_and_default_ports(self):
        self.assertTrue(
            same_origin(
                "https://example.com/path",
                "https://EXAMPLE.COM:443/other",
            )
        )
        self.assertTrue(
            same_origin(
                "http://[2001:db8::1]/path",
                "http://[2001:DB8::1]:80/other",
            )
        )

    def test_same_origin_rejects_origin_changes_and_invalid_ports(self):
        base_url = "https://example.com/path"

        for url in (
            "https://other.example/path",
            "http://example.com/path",
            "https://example.com:444/path",
            "https://example.com:0/path",
            "https://example.com:invalid/path",
            "https://[invalid/path",
        ):
            with self.subTest(url=url):
                self.assertFalse(same_origin(base_url, url))

    def test_same_origin_path_resolves_relative_and_protocol_relative_urls(self):
        base_url = "https://example.com/admin"

        self.assertEqual(same_origin_path(base_url, "admin/"), "admin/")
        self.assertEqual(same_origin_path(base_url, "/admin/"), "admin/")
        self.assertIsNone(same_origin_path(base_url, "//other.example/admin/"))
