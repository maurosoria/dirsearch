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

import re
import string
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from lib.core.settings import (
    CRAWL_ATTRIBUTES, CRAWL_TAGS,
    MEDIA_EXTENSIONS, ROBOTS_TXT_REGEX,
)
from lib.parse.url import clean_path, same_origin_path


_ESCAPED_SLASH_REGEX = re.compile(r"\\(?:/|u002f|x2f)", re.IGNORECASE)
_MEDIA_SUFFIXES = tuple(f".{extension}" for extension in MEDIA_EXTENSIONS)
# RFC 3986 URI characters plus brackets used by common array query syntax.
_TEXT_URL_CHARS = frozenset(
    string.ascii_letters + string.digits + "-._~%!$&'()*+,;=:@/?#[]"
)
_TEXT_URL_QUOTES = frozenset("\"'`")
_ASCII_WHITESPACE = frozenset("\t\n\f\r ")


def _filter(paths):
    results = set()

    for path in paths:
        path = clean_path(path, keep_queries=True)
        resource_path = path.split("?", 1)[0]

        if not path or resource_path.lower().endswith(_MEDIA_SUFFIXES):
            continue

        results.add(path)

    return results


def _trim_unquoted_url(path):
    path = path.rstrip(".,")

    for opening, closing in (("(", ")"), ("[", "]")):
        excess = max(0, path.count(closing) - path.count(opening))
        trailing = len(path) - len(path.rstrip(closing))
        trim_count = min(excess, trailing)
        if trim_count:
            path = path[:-trim_count]

    return path


def _extract_scoped_paths(scope, content):
    content = _ESCAPED_SLASH_REGEX.sub("/", content)
    scope_regex = re.compile(re.escape(scope), re.IGNORECASE)

    for match in scope_regex.finditer(content):
        preceding = content[match.start() - 1] if match.start() else ""
        quote = preceding if preceding in _TEXT_URL_QUOTES else None
        path = []

        for char in content[match.end():]:
            if char == quote or char not in _TEXT_URL_CHARS:
                break
            path.append(char)

        path = "".join(path)
        if quote is None:
            path = _trim_unquoted_url(path)

        if path:
            yield path


def _srcset_urls(value):
    """Yield URL tokens from an HTML srcset value."""
    position = 0
    length = len(value)

    while position < length:
        while (
            position < length
            and (value[position] in _ASCII_WHITESPACE or value[position] == ",")
        ):
            position += 1

        if position >= length:
            return

        start = position
        while position < length and value[position] not in _ASCII_WHITESPACE:
            position += 1

        url = value[start:position]
        if url.endswith(","):
            url = url.rstrip(",")
            if url:
                yield url
            continue

        if url:
            yield url

        parentheses = 0
        while position < length:
            character = value[position]
            position += 1

            if character == "(":
                parentheses += 1
            elif character == ")" and parentheses:
                parentheses -= 1
            elif character == "," and not parentheses:
                break


def _browser_url_value(value):
    """Normalize reverse solidus in an HTTP URL path like a browser."""
    query = value.find("?")
    fragment = value.find("#")
    suffixes = [position for position in (query, fragment) if position >= 0]
    path_end = min(suffixes) if suffixes else len(value)

    return value[:path_end].replace("\\", "/") + value[path_end:]


def _document_base_url(url, soup):
    base = soup.find("base", href=True)
    if base is None:
        return url

    href = base.get("href")
    if not isinstance(href, str):
        return url

    try:
        resolved = urljoin(url, _browser_url_value(href.strip()))
        parsed = urlsplit(resolved)
        parsed.port
    except ValueError:
        return url

    if not parsed.scheme or parsed.scheme.lower() in ("data", "javascript"):
        return url

    return resolved


def _same_origin_crawl_path(scope, base_url, value):
    if not isinstance(value, str):
        return None

    try:
        resolved = urljoin(base_url, _browser_url_value(value.strip()))
        parsed = urlsplit(resolved)
        parsed.port
    except ValueError:
        return None

    if not parsed.scheme or parsed.hostname is None:
        return None

    return same_origin_path(scope, resolved)


class Crawler:
    @classmethod
    def crawl(cls, response):
        scope = "/".join(response.url.split("/")[:3]) + "/"

        if "text/html" in response.headers.get("content-type", ""):
            return cls.html_crawl(response.url, scope, response.content)
        elif response.path == "robots.txt":
            return cls.robots_crawl(response.url, scope, response.content)
        else:
            return cls.text_crawl(response.url, scope, response.content)

    @staticmethod
    def text_crawl(url, scope, content):
        return _filter(_extract_scoped_paths(scope, content))

    @staticmethod
    def html_crawl(url, scope, content):
        results = []
        soup = BeautifulSoup(content, 'html.parser')
        base_url = _document_base_url(url, soup)

        for tag in CRAWL_TAGS:
            for found in soup.find_all(tag):
                if found.name == "base":
                    continue

                for attr in CRAWL_ATTRIBUTES:
                    value = found.get(attr)

                    if not isinstance(value, str) or not value:
                        continue

                    values = _srcset_urls(value) if attr == "srcset" else (value,)
                    for candidate in values:
                        path = _same_origin_crawl_path(
                            scope,
                            base_url,
                            candidate,
                        )
                        if path is not None:
                            results.append(path)

        return _filter(results)

    @staticmethod
    def robots_crawl(url, scope, content):
        return _filter(re.findall(ROBOTS_TXT_REGEX, content))
