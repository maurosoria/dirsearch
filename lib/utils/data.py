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

from urllib.parse import quote

def safequote(string):
    return quote(string, safe="!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

def uniq(string_list, filt=False):
    unique = dict.fromkeys(string_list)
    return list(filter(None, unique)) if filt else list(unique)

# Some characters are denied in file name by Windows
def cleanfilename(string):
    special_chars = ["\\", "/", "*", "?", ":", '"', "<", ">", "|"]
    for char in special_chars:
        string = string.replace(char, "-")

    return string

def lowercase(data):
    if isinstance(data, str):
        return data.lower()
    elif isinstance(data, list):
        return [i.lower() for i in data if isinstance(i, str)]
    elif isinstance(data, list):
        return dict((key.lower(), value) for key, value in data.items())
    elif isinstance(data, tuple):
        return tuple(i.lower() for i in data if isinstance(i, str))
    else:
        return data
