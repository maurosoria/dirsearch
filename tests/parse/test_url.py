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
from lib.parse.url import parse_path, join_path


class TestURLParsers(TestCase):
    def test_parse_path(self):
        self.assertEqual(
            parse_path(f"{DUMMY_URL}///foo/bar?query=1#fragment"),
            "///foo/bar?query=1#fragment",
            "Full path parser gives unexpected result",
        )
        self.assertEqual(
            parse_path(f"{DUMMY_URL}///foo/bar?query=1#fragment", queries=False),
            "///foo/bar",
            "Full path parser gives unexpected result",
        )
        self.assertEqual(
            parse_path(f"{DUMMY_URL}///foo/bar?query=1#fragment", fragment=False),
            "///foo/bar?query=1",
            "Full path parser gives unexpected result",
        )

    def test_join_path(self):
        self.assertEqual(
            join_path("foo", "bar", "/foo", "bar/", "///foobar"),
            "foo/bar/foo/bar///foobar",
            "Paths joiner gives unexpected result",
        )
