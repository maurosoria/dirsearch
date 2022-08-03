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
    MEDIA_EXTENSIONS, ROBOTS_TXT_REGEX,
    URI_REGEX,
)
from lib.parse.url import clean_path, parse_path
from lib.utils.common import merge_path


def _filter(paths):
    return {clean_path(path, keep_queries=True) for path in paths if not path.endswith(MEDIA_EXTENSIONS)}


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
    @lru_cache(maxsize=None)
    def text_crawl(url, scope, content):
        results = []
        regex = re.escape(scope) + "[a-zA-Z0-9-._~!$&*+,;=:@?%]+"

        for match in re.findall(regex, content):
            results.append(match[len(scope):])

        return _filter(results)

    @staticmethod
    @lru_cache(maxsize=None)
    def html_crawl(url, scope, content):
        results = []
        soup = BeautifulSoup(content, 'html.parser')

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
                        results.append(parse_path(new_url))

        return _filter(results)

    @staticmethod
    @lru_cache(maxsize=None)
    def robots_crawl(url, scope, content):
        return _filter(re.findall(ROBOTS_TXT_REGEX, content))
