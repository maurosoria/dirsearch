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

from __future__ import annotations

from email.parser import BytesParser

from lib.core.settings import NEW_LINE
from lib.core.structures import CaseInsensitiveDict


class HeadersParser:
    def __init__(self, headers: str | dict[str, str]) -> None:
        self.str = self.dict = headers

        if isinstance(headers, str):
            self.dict = self.str_to_dict(headers)
        elif isinstance(headers, dict):
            self.str = self.dict_to_str(headers)
            self.dict = self.str_to_dict(self.str)

        self.headers = CaseInsensitiveDict(self.dict)

    def get(self, key: str) -> str:
        return self.headers[key]

    @staticmethod
    def str_to_dict(headers: str) -> dict[str, str]:
        if not headers:
            return {}

        return dict(BytesParser().parsebytes(headers.encode()))

    @staticmethod
    def dict_to_str(headers: dict[str, str]) -> str:
        if not headers:
            return

        return NEW_LINE.join(f"{key}: {value}" for key, value in headers.items())

    def __iter__(self):
        return iter(self.headers.items())

    def __str__(self) -> str:
        return self.str
