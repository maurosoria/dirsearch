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

from lib.utils import File


class Raw(object):
    def __init__(self, raw_file, protocol):
        with File(raw_file) as raw_content:
            self.raw_content = raw_content.read()

        self.protocol = protocol
        self.parse()

    def parse(self):
        # Parse for 2 situations: \n as a newline or \r\n as a newline
        self.parsed = self.raw_content.split("\n\n")
        if len(self.parsed) == 1:
            self.parsed = self.raw_content.split("\r\n\r\n")

        self.header = self.parsed[0].splitlines()

        try:
            self.http_headers = dict(
                (key, value)
                for (key, value) in (
                    header.split(":", 1) for header in self.header[1:]
                )
            )
        except Exception:
            print("Invalid headers in the raw request")
            exit(1)

        try:
            self.body = self.parsed[1] if self.parsed[1] else None
        except IndexError:
            self.body = None

        self.http_headers_lowercase = dict(
            (key.lower(), value) for key, value in self.http_headers
        )

        try:
            self.host = self.http_headers_lowercase["host"]
        except KeyError:
            print("Can't find the Host header in the raw request")
            exit(1)
        self.basePath = self.header[0].split(" ")[1]

    def url(self):
        return ["{0}://{1}{2}".format(self.protocol, self.host, self.basePath)]

    def method(self):
        return self.header[0].split(" ")[0]

    def headers(self):
        return self.http_headers

    def data(self):
        return self.body

    def user_agent(self):
        if "user-agent" in self.http_headers_lowercase.keys:
            return self.http_headers_lowercase["user-agent"]
        else:
            return None

    def cookie(self)
        if "cookie" in self.http_headers_lowercase.keys:
            return self.http_headers_lowercase["cookie"]
        else:
            return None
