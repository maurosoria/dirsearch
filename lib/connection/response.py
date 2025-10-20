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

from typing import Any

import time
import httpx
import requests

from lib.core.settings import (
    DEFAULT_ENCODING,
    ITER_CHUNK_SIZE,
    MAX_RESPONSE_SIZE,
    UNKNOWN,
)
from lib.parse.url import clean_path, parse_path
from lib.utils.common import get_readable_size, is_binary, replace_path


class BaseResponse:
    def __init__(self, url, response: requests.Response | httpx.Response) -> None:
        self.datetime = time.strftime("%Y-%m-%d %H:%M:%S")
        self.url = url
        self.full_path = parse_path(self.url)
        self.path = clean_path(self.full_path)
        self.status = response.status_code
        self.headers = response.headers
        self.redirect = self.headers.get("location", "")
        self.history = [str(res.url) for res in response.history]
        self.content = ""
        self.body = b""

    @property
    def type(self) -> str:
        if ct := self.headers.get("content-type"):
            return ct.split(";")[0]

        return UNKNOWN

    @property
    def length(self) -> int:
        if cl := self.headers.get("content-length"):
            return int(cl)

        return len(self.body)

    @property
    def size(self) -> str:
        return get_readable_size(self.length)

    def __hash__(self) -> int:
        # Hash the static parts of the response only.
        # See https://github.com/maurosoria/dirsearch/pull/1436#issuecomment-2476390956
        body = replace_path(self.content, self.full_path.split("#")[0], "") if self.content else self.body
        return hash((self.status, body))

    def __eq__(self, other: Any) -> bool:
        return (self.status, self.body, self.redirect) == (
            other.status,
            other.body,
            other.redirect,
        )


class Response(BaseResponse):
    def __init__(self, url, response: requests.Response) -> None:
        super().__init__(url, response)

        for chunk in response.iter_content(chunk_size=ITER_CHUNK_SIZE):
            self.body += chunk

            if len(self.body) >= MAX_RESPONSE_SIZE or (
                "content-length" in self.headers and is_binary(self.body)
            ):
                break

        if not is_binary(self.body):
            try:
                self.content = self.body.decode(
                    response.encoding or DEFAULT_ENCODING, errors="ignore"
                )
            except LookupError:
                self.content = self.body.decode(DEFAULT_ENCODING, errors="ignore")


class AsyncResponse(BaseResponse):
    @classmethod
    async def create(cls, url, response: httpx.Response) -> AsyncResponse:
        self = cls(url, response)
        async for chunk in response.aiter_bytes(chunk_size=ITER_CHUNK_SIZE):
            self.body += chunk

            if len(self.body) >= MAX_RESPONSE_SIZE or (
                "content-length" in self.headers and is_binary(self.body)
            ):
                break

        if not is_binary(self.body):
            try:
                self.content = self.body.decode(
                    response.encoding or DEFAULT_ENCODING, errors="ignore"
                )
            except LookupError:
                self.content = self.body.decode(DEFAULT_ENCODING, errors="ignore")

        return self
