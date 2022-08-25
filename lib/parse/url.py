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

from lib.utils.common import lstrip_once


def clean_path(path, keep_queries=False, keep_fragment=False):
    if not keep_fragment:
        path = path.split("#")[0]
    if not keep_queries:
        path = path.split("?")[0]

    return path


def parse_path(value):
    try:
        scheme, url = value.split("//", 1)
        if (
            scheme and (not scheme.endswith(":") or "/" in scheme)
            or url.startswith("/")
        ):
            raise ValueError

        return "/".join(url.split("/")[1:])
    except Exception:
        return lstrip_once(value, "/")
