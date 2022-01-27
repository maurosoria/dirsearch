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

import string

from thirdparty.colorama import init, Fore, Back, Style
from thirdparty.pyparsing import Literal, Word, Combine, Optional, Suppress, delimitedList, oneOf


FORE_TABLE = {
    "red": Fore.RED,
    "green": Fore.GREEN,
    "yellow": Fore.YELLOW,
    "blue": Fore.BLUE,
    "magenta": Fore.MAGENTA,
    "cyan": Fore.CYAN,
    "white": Fore.WHITE
}

BACK_TABLE = {
    "red": Back.RED,
    "green": Back.GREEN,
    "yellow": Back.YELLOW,
    "blue": Back.BLUE,
    "magenta": Back.MAGENTA,
    "cyan": Back.CYAN,
    "white": Back.WHITE
}


class ColorOutput(object):
    def __init__(self, colors=True):
        self.colors = colors
        self.escape_seq = None
        self.prepare_sequence_escaper()
        init()

    def color(self, msg, fore=None, back=None, bright=False):
        if not self.colors:
            return msg

        if bright:
            msg = Style.BRIGHT + msg
        if fore:
            msg = FORE_TABLE[fore] + msg
        if back:
            msg = BACK_TABLE[back] + msg

        return msg + Style.RESET_ALL

    # Credit: https://stackoverflow.com/a/2187024/12238982
    def prepare_sequence_escaper(self):
        ESC = Literal("\x1b")
        self.escape_seq = Combine(
            ESC + "[" + Optional(
                delimitedList(Word(string.digits), ";")
            ) + oneOf(list(string.ascii_letters))
        )

    def clean(self, msg):
        return Suppress(self.escape_seq).transformString(msg)
