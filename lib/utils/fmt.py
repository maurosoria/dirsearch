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

import string

from chardet import detect
from urllib.parse import quote

from lib.core.settings import INVALID_CHARS_FOR_WINDOWS_FILENAME, DEFAULT_ENCODING


def safequote(string_):
    return quote(string_, safe=string.punctuation)


def get_encoding_type(content):
    return detect(content)["encoding"] or DEFAULT_ENCODING


def uniq(string_list, filt=False):
    if not string_list:
        return string_list

    unique = dict.fromkeys(string_list)
    return list(filter(None, unique)) if filt else list(unique)


# Some characters are denied in file name by Windows
def clean_filename(string):
    for char in INVALID_CHARS_FOR_WINDOWS_FILENAME:
        string = string.replace(char, "-")

    return string


def human_size(num):
    base = 1024
    for x in ["B ", "KB", "MB", "GB"]:
        if num < base and num > -base:
            return "%3.0f%s" % (num, x)
        num /= base
    return "%3.0f %s" % (num, "TB")
