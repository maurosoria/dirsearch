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

import email

from io import StringIO

from lib.utils.fmt import lowercase


class HeadersParser(object):
    def __init__(self, headers):
        self.headers = {}
        self.raw = None

        if isinstance(headers, str):
            self.headers = self.raw_to_headers(headers)
            self.raw = headers
        elif isinstance(headers, (dict, list)):
            self.raw = self.headers_to_raw(headers)
            self.headers = self.raw_to_headers(self.raw)

        self.lower_headers = lowercase(self.headers)

    @staticmethod
    def raw_to_headers(raw):
        if not raw:
            return {}

        return dict(
            email.message_from_file(StringIO(raw))
        )

    @staticmethod
    def headers_to_raw(headers):
        if not headers:
            return

        if isinstance(headers, dict):
            return "\r\n".join(
                "{0}: {1}".format(key, value) for key, value in headers.items()
            )
        elif isinstance(headers, list):
            return "\r\n".join(headers)
        else:
            return
