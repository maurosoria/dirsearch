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

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from lib.core.exceptions import InvalidRawRequest
from lib.parse.headers import HeadersParser
from lib.utils.file import FileUtils


HEADER_ENCODING = "iso-8859-1"


@dataclass(frozen=True)
class RawRequest:
    url: str
    method: str
    headers: dict[str, str]
    body: bytes | None


def _raw_bytes(raw_content: str | bytes) -> bytes:
    if isinstance(raw_content, bytes):
        return raw_content

    return raw_content.encode()


def _split_head_body(raw_content: bytes) -> tuple[bytes, bytes | None]:
    for separator in (b"\r\n\r\n", b"\n\n"):
        if separator in raw_content:
            return raw_content.split(separator, 1)

    return raw_content.strip(b"\r\n"), None


def _origin_form_target(target: str, host: str, scheme: str | None) -> str:
    parsed = urlsplit(target)
    path = parsed.path if parsed.path.startswith("/") else f"/{parsed.path}"

    if scheme:
        return urlunsplit((scheme, host, path, parsed.query, ""))

    return host + urlunsplit(("", "", path, parsed.query, ""))


def _absolute_form_target(target: str) -> str | None:
    parsed = urlsplit(target)
    if not parsed.scheme or not parsed.netloc:
        return None

    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _target_from_request_line(
    target: str,
    headers: HeadersParser,
    *,
    scheme: str | None = None,
) -> str:
    absolute_target = _absolute_form_target(target)
    if absolute_target:
        return absolute_target

    try:
        host = headers.get("host")
    except KeyError:
        raise InvalidRawRequest("Can't find the Host header in the raw request")

    return _origin_form_target(target, host, scheme)


def parse_raw_content(
    raw_content: str | bytes,
    *,
    scheme: str | None = None,
) -> RawRequest:
    head, body = _split_head_body(_raw_bytes(raw_content))

    try:
        head_lines = head.splitlines()
        method, target = head_lines[0].decode(HEADER_ENCODING).split()[:2]
        headers = HeadersParser(
            b"\n".join(head_lines[1:]).decode(HEADER_ENCODING)
        )
        url = _target_from_request_line(target, headers, scheme=scheme)
    except (IndexError, UnicodeError, ValueError) as e:
        raise InvalidRawRequest("The raw request is formatively invalid") from e

    return RawRequest(url, method, dict(headers), body)


def parse_raw(
    raw_file: str,
    *,
    scheme: str | None = None,
) -> tuple[list[str], str, dict[str, str], bytes | None]:
    request = parse_raw_content(FileUtils.read_bytes(raw_file), scheme=scheme)
    return [request.url], request.method, request.headers, request.body
