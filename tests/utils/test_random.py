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

from unittest import TestCase

from lib.utils.random import rand_string


class TestRandom(TestCase):
    def test_rand_string(self):
        test_omit = "abcde"
        self.assertEqual(len(rand_string(9)), 9, "Incorrect random string length")
        for x, y in zip(rand_string(5, omit=test_omit), test_omit):
            self.assertNotEqual(x, y, "Random string's characters are not distinct from omit")
