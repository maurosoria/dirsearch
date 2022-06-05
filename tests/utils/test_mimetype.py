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

from unittest import TestCase

from lib.utils.mimetype import MimeTypeUtils


class TestMimeTypeUtils(TestCase):
    def test_is_json(self):
        self.assertTrue(MimeTypeUtils.is_json('{"foo": "bar"}'), "Failed to detect JSON mimetype")

    def test_is_xml(self):
        self.assertTrue(MimeTypeUtils.is_xml('<?xml version="1.0" encoding="UTF-8"?><foo>bar</foo>'), "Failed to detect XML mimetype")

    def test_is_query_string(self):
        self.assertTrue(MimeTypeUtils.is_query_string("foo=1&bar=&foobar=2"), "Failed to detect query string")
