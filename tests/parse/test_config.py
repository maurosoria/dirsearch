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

import io

from unittest import TestCase

from lib.parse.config import ConfigParser


config_data = """
[test]
string = foo
integer = 1
float = 2.7
boolean = True
list = ["foo", "bar"]
list2 = test
"""
config = ConfigParser()
config.read_file(io.StringIO(config_data))


class TestConfigParser(TestCase):
    def test_safe_get(self):
        self.assertEqual(config.safe_get("test", "string"), "foo")
        self.assertEqual(config.safe_get("non-existent", "string", default="default"), "default")
        self.assertEqual(config.safe_get("test", "non-existent", default="default"), "default")
        self.assertEqual(config.safe_get("test", "string", default="default", allowed=("bar",)), "default")

    def test_safe_getint(self):
        self.assertEqual(config.safe_getint("test", "integer"), 1)

    def test_safe_getfloat(self):
        self.assertEqual(config.safe_getfloat("test", "float"), 2.7)

    def test_safe_getboolean(self):
        self.assertEqual(config.safe_getboolean("test", "boolean"), True)

    def test_safe_getlist(self):
        self.assertEqual(config.safe_getlist("test", "list"), ["foo", "bar"])
        self.assertEqual(config.safe_getlist("test", "list2"), ["test"])
        self.assertEqual(config.safe_getlist("test", "list", default=["default"], allowed=("foo",)), ["default"])
