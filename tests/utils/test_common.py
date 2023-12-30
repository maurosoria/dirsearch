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

from lib.utils.common import merge_path, strip_and_uniquify, get_valid_filename


class TestCommonUtils(TestCase):
    def test_strip_and_uniquify(self):
        self.assertEqual(strip_and_uniquify(["foo", "bar", " bar ", "foo"]), ["foo", "bar"], "The results are not stripped or contain duplicates or in wrong order")

    def test_get_valid_filename(self):
        self.assertEqual(get_valid_filename("http://example.com:80/foobar"), "http___example.com_80_foobar", "Invalid filename for Windows")

    def test_merge_path(self):
        self.assertEqual(merge_path("http://example.com/foo", "bar"), "http://example.com/bar")
        self.assertEqual(merge_path("http://example.com/folder/", "foo/../bar/./"), "http://example.com/folder/bar/")
