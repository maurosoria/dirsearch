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

from thirdparty.colorama import init, Fore, Back, Style


class ColorOutput(object):
    def __init__(self, colors=True):
        self.colors = colors
        self.fore_table = {
            "red": Fore.RED,
            "green": Fore.GREEN,
            "yellow": Fore.YELLOW,
            "blue": Fore.BLUE,
            "magenta": Fore.MAGENTA,
            "cyan": Fore.CYAN,
            "white": Fore.WHITE
        }
        self.back_table = {
            "red": Back.RED,
            "green": Back.GREEN,
            "yellow": Back.YELLOW,
            "blue": Back.BLUE,
            "magenta": Back.MAGENTA,
            "cyan": Back.CYAN,
            "white": Back.WHITE
        }

        init()

    def color(self, msg, fore=None, back=None, bright=False):
        if not self.colors:
            return msg

        if bright:
            msg = Style.BRIGHT + msg
        if fore:
            msg = self.fore_table[fore] + msg
        if back:
            msg = self.back_table[back] + msg

        msg += Style.RESET_ALL
        return msg
