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

from bs4 import BeautifulSoup
from functools import lru_cache

from lib.core.settings import (
    CRAWL_ATTRIBUTES, CRAWL_TAGS,
    MEDIA_EXTENSIONS, URI_REGEX,
)
from lib.parse.url import parse_root_url, parse_path


def _filter(paths):
    return {path for path in paths if not path.endswith(MEDIA_EXTENSIONS)}


def merge_path(url, path):
    parts = url.split("/")
    parts[-1] = path

    return "/".join(parts)


@lru_cache(maxsize=None)
def crawl(url, response):
    if "text/html" in response.headers.get("content-type", ""):
        return html_crawl(url, response.content)
    elif response.path == "robots.txt":
        return robots_crawl(url, response.content)

    results = []
    scope = parse_root_url(url)
    regex = re.escape(scope) + "[a-zA-Z0-9-._~!$&*+,;=:@?%]+"

    for match in re.findall(regex, response.content):
        results.append(match[len(scope):])

    return _filter(results)


def html_crawl(url, html):
    results = []
    scope = parse_root_url(url)
    soup = BeautifulSoup(html, 'html.parser')

    for tag in CRAWL_TAGS:
        for found in soup.find_all(tag):
            for attr in CRAWL_ATTRIBUTES:
                value = found.get(attr)

                if not value:
                    continue

                if value.startswith("/"):
                    results.append(value[1:])
                elif value.startswith(scope):
                    results.append(value[len(scope):])
                elif not re.search(URI_REGEX, value):
                    new_url = merge_path(url, value)
                    results.append(parse_path(new_url, fragment=False))

    return _filter(results)


def robots_crawl(url, txt):
    return _filter(
        [
            line[line.find("/") + 1:] for line in txt.splitlines(0)
            if line.startswith(("Disallow:", "Allow:"))
        ]
    )
