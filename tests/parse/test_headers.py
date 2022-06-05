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

from lib.parse.headers import HeadersParser


class TestHeadersParser(TestCase):
    def test_str_to_dict(self):
        test_str = """
Header1: foo
Header2:bar
Header3:
        """
        expected_dict = {"Header1": "foo", "Header2": "bar", "Header3": ""}
        self.assertEqual(HeadersParser.str_to_dict(test_str.strip()), expected_dict, "Raw headers to dictionary converter gives unexpected result")

    def test_dict_to_str(self):
        test_dict = {"foo": "bar"}
        expected_str = "foo: bar"
        self.assertEqual(HeadersParser.dict_to_str(test_dict), expected_str, "Headers dictionary to raw converter gives unexpected result")
