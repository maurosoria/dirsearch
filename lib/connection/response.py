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


class Response(object):
    def __init__(self, status, reason, headers, body):
        self.status = status
        self.reason = reason
        self.headers = headers
        self.body = body

    def __str__(self):
        return self.body

    def __int__(self):
        return self.status

    def __eq__(self, other):
        return self.status == other.status and self.body == other.body

    def __cmp__(self, other):
        return (self.body > other) - (self.body < other)

    def __len__(self):
        return len(self.body)

    def __hash__(self):
        return hash(self.body)

    def __del__(self):
        del self.body
        del self.headers
        del self.status
        del self.reason

    @property
    def redirect(self):
        headers = dict((key.lower(), value) for key, value in self.headers.items())
        return headers.get("location")

    @property
    def pretty(self):
        try:
            # Python 3 is only able to download BeautifulSoup4
            from bs4 import BeautifulSoup
        except ImportError:
            raise Exception("BeautifulSoup pip package must be installed")

        html = BeautifulSoup(self.body)
        return html.prettify()
