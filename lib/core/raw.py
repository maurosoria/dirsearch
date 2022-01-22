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

from lib.core.settings import NEW_LINE
from lib.parse.headers import HeadersParser
from lib.utils.file import File


class Raw(object):
    def __init__(self, raw_file):
        with File(raw_file) as raw_content:
            self.raw_content = raw_content.read()

        self.parse()

    def parse(self):
        self.head = self.raw_content.split(NEW_LINE * 2)[0].splitlines(0)

        try:
            self.headers_ = HeadersParser(self.head[1:])
        except Exception:
            print("Invalid headers in the raw request")
            exit(1)

        try:
            self.body = self.raw_content.split(NEW_LINE * 2)[1]
        except IndexError:
            self.body = None

        try:
            self.host = self.headers_.get("host").strip()
        except KeyError:
            print("Can't find the Host header in the raw request")
            exit(1)

        self.method, self.path = self.head[0].split()[:2]

    @property
    def url(self):
        return "{0}{1}".format(self.host, self.path)

    @property
    def headers(self):
        return dict(self.headers_)
