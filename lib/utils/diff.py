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

import difflib
import re


class DynamicContentParser:
    def __init__(self, content1, content2):
        self._differ = difflib.Differ()
        self._is_static = content1 == content2
        self._base_content = content1

        if not self._is_static:
            self._static_patterns = self.remove_dynamic_patterns(
                self._differ.compare(content1.split(), content2.split())
            )

    def remove_dynamic_patterns(self, patterns):
        return [pattern for pattern in patterns if not pattern.startswith(("-", "+"))]

    def compare_to(self, content):
        if self._is_static:
            return content == self._base_content

        diff = self._differ.compare(self._base_content.split(), content.split())
        return self._static_patterns == self.remove_dynamic_patterns(diff)


def generate_matching_regex(string1, string2):
    start = "^"
    end = "$"

    for char1, char2 in zip(string1, string2):
        if char1 != char2:
            start += ".*"
            break

        start += re.escape(char1)

    if start.endswith(".*"):
        for char1, char2 in zip(string1[::-1], string2[::-1]):
            if char1 != char2:
                break

            end = re.escape(char1) + end

    return start + end
