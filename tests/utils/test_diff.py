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

from lib.utils.diff import DynamicContentParser, generate_matching_regex, normalize_dynamic_content


class TestDiff(TestCase):
    def test_generate_matching_regex(self):
        self.assertEqual(generate_matching_regex("add.php", "abc.php"), "^a.*\\.php$", "Matching regex isn't correct")

    def test_dynamic_content_parser(self):
        self.assertEqual(DynamicContentParser("a b c", "a b d")._static_patterns, ["a", "b"], "Static patterns are not right")
        self.assertTrue(DynamicContentParser("abc.php not found", "def.php not found").compare_to("nothing.php not found"))
        self.assertTrue(DynamicContentParser("abc.php not found", "def.php not found").compare_to("zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz.php not found"))

    def test_dynamic_content_parser_normalizes_common_tokens(self):
        parser = DynamicContentParser(
            "missing abc token 2026-05-29T10:11:12Z id 550e8400-e29b-41d4-a716-446655440000",
            "missing def token 2026-05-29T10:12:12Z id 550e8400-e29b-41d4-a716-446655440001",
        )

        self.assertTrue(
            parser.compare_to(
                "missing xyz token 2026-05-29T10:13:12Z id 550e8400-e29b-41d4-a716-446655440002"
            )
        )
        self.assertIn("__DYNAMIC__", normalize_dynamic_content("trace=550e8400-e29b-41d4-a716-446655440000"))

    def test_dynamic_content_parser_normalizes_each_sample_once(self):
        samples = (
            "missing alpha with stable template words",
            "missing beta with stable template words",
            "missing gamma with stable template words",
        )

        with patch(
            "lib.utils.diff.normalize_dynamic_content",
            wraps=normalize_dynamic_content,
        ) as normalize:
            parser = DynamicContentParser(samples[0], samples[1])
            parser.add_sample(samples[2])

        self.assertEqual(normalize.call_count, len(samples))
