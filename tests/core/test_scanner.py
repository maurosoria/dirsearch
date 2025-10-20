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

from lib.core.scanner import BaseScanner
from lib.core.settings import REFLECTED_PATH_MARKER


class TestScanner(TestCase):
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
