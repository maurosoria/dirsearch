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

try:
    from bs4 import BeautifulSoup
except ImportError:
    raise Exception("BeautifulSoup pip package must be installed")

from urllib.parse import urljoin


# This is unused yet
class PageHandler(object):
    def __init__(self, content):
        self.content = content
        self.soup = BeautifulSoup(self.content)

    def text(self):
        return self.soup.get_text()

    def extract(self):
        href = self.soup.find_all(["a", "base", "link"])
        src = self.soup.find_all(["script", "img"])

        for href_ in href:
            href_ = href_.get("href")
            if href_:
                yield urljoin(self.url, href_)

        for src_ in src:
            src_ = src.get("src")
            if src_:
                yield urljoin(self.url, src_)

    def scrape(self):
        relink = r"https?:\/\/[a-zA-Z0-9\.=\/\?@#&%-_:;\[\]\{\}]{4,70}"
        return re.findall(relink, self.content)

    def crawl(self):
        return self.extract + self.scrape
