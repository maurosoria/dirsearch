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

from lib.core.settings import NEW_LINE
from lib.core.structures import CaseInsensitiveDict


class HeadersParser(object):
    def __init__(self, headers):
        self.str = self.dict = headers
        if isinstance(headers, str):
            self.dict = self.str_to_dict(headers)
        elif isinstance(headers, (dict, list)):
            self.str = self.dict_list_to_str(headers)
            self.dict = self.str_to_dict(self.str)

        self.headers = CaseInsensitiveDict(self.dict)

    def get(self, key):
        return self.headers[key]

    @staticmethod
    def str_to_dict(headers):
        if not headers:
            return {}

        return dict(
            email.message_from_file(StringIO(headers))
        )

    @staticmethod
    def dict_list_to_str(headers):
        if not headers:
            return

        if isinstance(headers, dict):
            return NEW_LINE.join(
                f"{key}: {value}" for key, value in headers.items()
            )
        elif isinstance(headers, list):
            return NEW_LINE.join(headers)

    def __iter__(self):
        return iter(self.headers)

    def __str__(self):
        return self.str
