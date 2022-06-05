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

from lib.utils.diff import DynamicContentParser, generate_matching_regex


class TestDiff(TestCase):
    def test_generate_matching_regex(self):
        self.assertEqual(generate_matching_regex("add.php", "abc.php"), "^a.*\\.php$", "Matching regex isn't correct")

    def test_dynamic_content_parser(self):
        self.assertEqual(DynamicContentParser("a b c", "a b d")._static_patterns, ["  a", "  b"], "Static patterns are not right")
        self.assertTrue(DynamicContentParser("a b c", "a b d").compare_to("a b ef"))
