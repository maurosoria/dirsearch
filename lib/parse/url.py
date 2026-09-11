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

from urllib.parse import urljoin, urlsplit, urlunsplit

from lib.utils.common import lstrip_once


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(value: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    if not scheme or hostname is None:
        return None

    return (
        scheme,
        hostname.lower(),
        port if port is not None else _DEFAULT_PORTS.get(scheme),
    )


def same_origin(first: str, second: str) -> bool:
    first_origin = _origin(first)
    return first_origin is not None and first_origin == _origin(second)


def same_origin_path(base_url: str, location: str) -> str | None:
    try:
        resolved = urljoin(base_url, location)
    except ValueError:
        return None

    if not same_origin(base_url, resolved):
        return None

    return parse_path(resolved)


def clean_path(path: str, keep_queries: bool = False, keep_fragment: bool = False) -> str:
    if not keep_fragment:
        path = path.split("#")[0]
    if not keep_queries:
        path = path.split("?")[0]

    return path


def parse_path(value: str) -> str:
    try:
        scheme, url = value.split("//", 1)
        if (
            scheme and (not scheme.endswith(":") or "/" in scheme)
            or url.startswith("/")
        ):
            raise ValueError

        return "/".join(url.split("/")[1:])
    except ValueError:
        return lstrip_once(value, "/")


def ensure_trailing_path_slash(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path
    if not path.endswith("/"):
        path += "/"

    return urlunsplit(parsed._replace(path=path))


def append_query_string(value: str, query: str) -> str:
    if not query or "?" in value:
        return value

    path, separator, fragment = value.partition("#")
    value = f"{path}?{query}"
    if separator:
        value += f"#{fragment}"

    return value
