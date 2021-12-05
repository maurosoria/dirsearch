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

from lib.parse.headers import HeadersParser
from lib.utils.file import File


class Raw(object):
    def __init__(self, raw_file):
        with File(raw_file) as raw_content:
            self.raw_content = raw_content.read()
        self.parse()

    def parse(self):
        # Parse for 2 situations: \n as a newline or \r\n as a newline
        self.parsed = self.raw_content.split("\n\n")
        if len(self.parsed) == 1:
            self.parsed = self.raw_content.split("\r\n\r\n")

        self.startline = self.parsed[0].splitlines()[0]

        try:
            self.headers_parser = HeadersParser(self.parsed[0].splitlines()[1:])
        except Exception:
            print("Invalid headers in the raw request")
            exit(1)

        try:
            self.body = self.parsed[1] if self.parsed[1] else None
        except IndexError:
            self.body = None

        try:
            self.host = self.headers_parser.lower_headers["host"].strip()
        except KeyError:
            print("Can't find the Host header in the raw request")
            exit(1)

        self.path = self.startline.split(" ")[1]

    @property
    def url(self):
        return "{0}{1}".format(self.host, self.path)

    @property
    def method(self):
        return self.startline.split(" ")[0]

    @property
    def headers(self):
        return self.headers_parser.headers
