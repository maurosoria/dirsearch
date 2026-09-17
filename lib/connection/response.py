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

import hashlib
import time
from codecs import lookup
from collections.abc import Iterable, Iterator, Mapping
from functools import cached_property
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx
    import requests

from lib.core.settings import (
    DEFAULT_ENCODING,
    ITER_CHUNK_SIZE,
    MAX_RESPONSE_SIZE,
    UNKNOWN,
)
from lib.parse.url import clean_path, parse_path
from lib.utils.common import (
    get_readable_size,
    get_response_length,
    is_binary,
    replace_path,
)
from lib.utils.diff import normalize_dynamic_content


def _decoded_content_length(headers) -> int | None:
    if headers.get("transfer-encoding"):
        return None

    content_encoding = headers.get("content-encoding", "").strip().lower()
    if content_encoding and content_encoding != "identity":
        return None

    try:
        length = int(headers.get("content-length"))
    except (TypeError, ValueError):
        return None

    return length if length >= 0 else None


def _declared_charset(headers) -> str | None:
    content_type = headers.get("content-type")
    if not content_type:
        return None

    for parameter in content_type.split(";")[1:]:
        name, separator, value = parameter.partition("=")
        if separator and name.strip().strip("'\"").lower() == "charset":
            return value.strip().strip("'\"") or None

    return None


def _is_known_charset(charset: str | None) -> bool:
    if charset is None:
        return False

    try:
        lookup(charset)
    except LookupError:
        return False

    return True


def _has_textual_media_type(headers) -> bool:
    content_type = (
        headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    return (
        content_type.startswith("text/")
        or content_type in {"application/json", "application/xml"}
        or content_type.endswith(("+json", "+xml"))
    )


def _should_decode_binary_text(headers, declared_charset: str | None) -> bool:
    return _has_textual_media_type(headers) and _is_known_charset(declared_charset)


def _decode_response_body(
    body: bytes,
    encoding: str | None,
    decode_binary_text: bool,
) -> str:
    if is_binary(body) and not decode_binary_text:
        return ""

    try:
        return body.decode(encoding or DEFAULT_ENCODING, errors="replace")
    except LookupError:
        return body.decode(DEFAULT_ENCODING, errors="replace")


class ResponseHeaders(Mapping[str, str]):
    """Read-only, case-insensitive response headers owned by dirsearch."""

    __slots__ = ("_items", "_names", "_values")

    def __init__(self, headers: Iterable[tuple[str, str]] = ()) -> None:
        items = tuple(headers)
        names: dict[str, str] = {}
        values: dict[str, list[str]] = {}

        for name, value in items:
            normalized_name = name.lower()
            names.setdefault(normalized_name, name)
            values.setdefault(normalized_name, []).append(value)

        self._items = items
        self._names = names
        self._values = values

    def __getitem__(self, name: str) -> str:
        values = self._values[name.lower()]
        if len(values) == 1:
            return values[0]
        return ", ".join(values)

    def __iter__(self) -> Iterator[str]:
        return iter(self._names.values())

    def __len__(self) -> int:
        return len(self._values)

    def get_list(self, name: str) -> list[str]:
        """Return every value for a header without combining duplicates."""
        return list(self._values.get(name.lower(), ()))

    def multi_items(self) -> list[tuple[str, str]]:
        """Return header pairs in their original order, including duplicates."""
        return list(self._items)


class _BodyCapture:
    """Keep response bodies bounded while retaining a complete binary digest."""

    def __init__(self, headers, capture_full_body: bool) -> None:
        self.body = bytearray()
        self.complete = False
        self.digest = None
        self._capture_full_body = capture_full_body
        self._headers = headers
        self._read_length = 0

    def add(self, chunk: bytes) -> bool:
        remaining = MAX_RESPONSE_SIZE - self._read_length
        captured = chunk[:remaining]
        self._read_length += len(captured)

        if self.digest is not None:
            self.digest.update(captured)
        else:
            self.body.extend(captured)
            if (
                not self._capture_full_body
                and self._headers.get("content-length") is not None
                and is_binary(self.body)
            ):
                # Keep only the captured binary prefix, but digest later chunks
                # so wildcard checks never treat that prefix as the whole body.
                self.digest = hashlib.sha256(self.body)

        if len(captured) < len(chunk) or self._read_length >= MAX_RESPONSE_SIZE:
            self.complete = (
                len(captured) == len(chunk)
                and _decoded_content_length(self._headers) == self._read_length
            )
            return False

        return True

    def finish(self) -> None:
        self.complete = True

    @property
    def body_digest(self) -> bytes | None:
        if self.digest is None:
            return None

        return self.digest.digest()


class BaseResponse:
    def __init__(
        self,
        url: str,
        status: int,
        headers: Iterable[tuple[str, str]],
        elapsed: float = 0.0,
        history: Iterable[str] = (),
    ) -> None:
        self.datetime = time.strftime("%Y-%m-%d %H:%M:%S")
        self.url = url
        self.full_path = parse_path(self.url)
        self.path = clean_path(self.full_path)
        self.status = status
        self.headers = ResponseHeaders(headers)
        self.redirect = self.headers.get("location", "")
        self.history = list(history)
        self.elapsed = elapsed
        self.content = ""
        self.body = b""
        self._body_complete = True
        self._body_digest = None

    @property
    def type(self) -> str:
        if ct := self.headers.get("content-type"):
            return ct.split(";")[0]

        return UNKNOWN

    @property
    def length(self) -> int:
        return get_response_length(self.headers, len(self.body))

    @property
    def size(self) -> str:
        return get_readable_size(self.length)

    @property
    def body_complete(self) -> bool:
        """Return whether the captured body contains the complete response."""
        return self._body_complete

    @property
    def body_truncated(self) -> bool:
        """Return whether response capture stopped before the body was complete."""
        return not self.body_complete

    @property
    def text(self) -> str:
        if self.content:
            return self.content

        return self.body.decode(DEFAULT_ENCODING, errors="ignore")

    @cached_property
    def normalized_content(self) -> str:
        """Return cached text with volatile response values normalized."""
        return normalize_dynamic_content(self.text)

    @property
    def words(self) -> int:
        return len(self.text.split())

    @property
    def lines(self) -> int:
        if not self.text:
            return 0

        return self.text.count("\n") + 1

    def __hash__(self) -> int:
        return hash((self.status, self.redirect, self._body_fingerprint))

    @cached_property
    def filter_fingerprint(self) -> int:
        """Return a path-agnostic fingerprint for --filter-threshold."""
        body = (
            replace_path(self.content, self.full_path.split("#")[0], "")
            if self.content
            else self._body_fingerprint
        )
        return hash((self.status, body))

    @cached_property
    def _body_fingerprint(self) -> bytes:
        if self._body_digest is not None:
            return self._body_digest

        return hashlib.sha256(self.body).digest()

    def has_same_body(self, other: BaseResponse) -> bool:
        """Return whether both responses contain the same complete body."""
        if self is other:
            return True

        return (
            self._body_complete
            and other._body_complete
            and (
                self.body == other.body
                if self._body_digest is None and other._body_digest is None
                else self._body_fingerprint == other._body_fingerprint
            )
        )

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, BaseResponse):
            return NotImplemented

        return (
            self.status == other.status
            and self.redirect == other.redirect
            and self.has_same_body(other)
        )


class Response(BaseResponse):
    def __init__(
        self,
        url,
        response: requests.Response,
        elapsed: float = 0.0,
        capture_full_body: bool = False,
    ) -> None:
        super().__init__(
            url,
            response.status_code,
            response.headers.items(),
            elapsed,
            (str(item.url) for item in response.history),
        )
        declared_charset = _declared_charset(self.headers)
        decode_binary_text = _should_decode_binary_text(
            self.headers,
            declared_charset,
        )
        capture = _BodyCapture(
            self.headers,
            capture_full_body or decode_binary_text,
        )

        for chunk in response.iter_content(chunk_size=ITER_CHUNK_SIZE):
            if not capture.add(chunk):
                break
        else:
            capture.finish()

        self.body = bytes(capture.body)
        self._body_complete = capture.complete
        self._body_digest = capture.body_digest
        self.content = _decode_response_body(
            self.body,
            declared_charset or response.encoding,
            decode_binary_text,
        )


class AsyncResponse(BaseResponse):
    @classmethod
    async def create(
        cls,
        url,
        response: httpx.Response,
        elapsed: float = 0.0,
        capture_full_body: bool = False,
    ) -> AsyncResponse:
        self = cls(
            url,
            response.status_code,
            response.headers.multi_items(),
            elapsed,
            (str(item.url) for item in response.history),
        )
        declared_charset = _declared_charset(self.headers)
        decode_binary_text = _should_decode_binary_text(
            self.headers,
            declared_charset,
        )
        capture = _BodyCapture(
            self.headers,
            capture_full_body or decode_binary_text,
        )
        async for chunk in response.aiter_bytes(chunk_size=ITER_CHUNK_SIZE):
            if not capture.add(chunk):
                break
        else:
            capture.finish()

        self.body = bytes(capture.body)
        self._body_complete = capture.complete
        self._body_digest = capture.body_digest
        self.content = _decode_response_body(
            self.body,
            declared_charset or response.encoding,
            decode_binary_text,
        )

        return self


class NativeResponse(BaseResponse):
    def __init__(
        self,
        url: str,
        status: int,
        headers: list[tuple[str, str]],
        body: bytes | bytearray | list[int],
        elapsed: float = 0.0,
        length: int | None = None,
        filtered: bool = False,
        filter_reason: str | None = None,
        body_complete: bool | None = None,
    ) -> None:
        # Native previously exposed HTTPX's lowercase header iteration. Keep
        # that stable while using dirsearch's transport-neutral header model.
        super().__init__(
            url,
            status,
            ((name.lower(), value) for name, value in headers),
            elapsed,
        )

        self._length = length
        self.filtered = filtered
        self.filter_reason = filter_reason
        self.body = bytes(body)
        if body_complete is not None:
            self._body_complete = body_complete
        elif self._length is not None:
            self._body_complete = self._length == len(self.body)
        declared_charset = _declared_charset(self.headers)
        self.content = _decode_response_body(
            self.body,
            declared_charset,
            _should_decode_binary_text(self.headers, declared_charset),
        )

    @property
    def length(self) -> int:
        if self._length is not None:
            return self._length

        return super().length
