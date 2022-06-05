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

from lib.core.settings import DUMMY_DOMAIN
from lib.utils.schemedet import detect_scheme


class TestSchemedet(TestCase):
    def test_detect_scheme(self):
        self.assertEqual(detect_scheme(DUMMY_DOMAIN, 443), "https", "Incorrect scheme detected")
        self.assertEqual(detect_scheme(DUMMY_DOMAIN, 80), "http", "Incorrect scheme detected")
        self.assertEqual(detect_scheme(DUMMY_DOMAIN, 1234), "http", "Incorrect scheme detected")
