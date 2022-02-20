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

from functools import cached_property

from lib.core.settings import CHUNK_SIZE, DEFAULT_ENCODING
from lib.parse.url import parse_path, parse_full_path


class Response(object):
    def __init__(self, response, redirects):
        self.path = parse_path(response.url)
        self.full_path = parse_full_path(response.url)
        self.status = response.status_code
        self.headers = response.headers
        self.redirect = self.headers.get("location")
        self.history = redirects
        self.body = b''

        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            self.body += chunk

        self.content = self.body.decode(response.encoding or DEFAULT_ENCODING, errors="ignore")

    def __eq__(self, other):
        return self.status == other.status and self.body == other.body

    def __cmp__(self, other):
        return (self.body > other) - (self.body < other)

    def __len__(self):
        return len(self.body)

    def __hash__(self):
        return hash(self.body)

    @cached_property
    def length(self):
        if "content-length" in dict(self.headers):
            return int(self.headers.get("content-length"))

        return len(self.body)
