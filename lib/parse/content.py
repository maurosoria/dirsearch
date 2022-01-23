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

import re

from urllib.parse import unquote


class SimilarityParser(object):
    def __init__(self, string1, string2):
        self.regex = self.regex_generator(string1, string2)
        self.unquote = False
        self.ignorecase = False

    def regex_generator(self, string1, string2):
        start = "^"
        end = "$"

        for f, s in zip(string1, string2):
            if f == s:
                start += re.escape(f)
            else:
                start += ".*"
                break

        if start.endswith(".*"):
            for f, s in zip(string1[::-1], string2[::-1]):
                if f == s:
                    end = re.escape(f) + end
                else:
                    break

        return start + end

    def compare(self, regex, new_string):
        if not regex:
            regex = self.regex

        if self.unquote:
            regex = unquote(regex)
            new_string = unquote(new_string)
        if self.ignorecase:
            regex, new_string = regex.lower(), new_string.lower()

        similar = re.match(regex, new_string)
        return False if similar is None else True
