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

import time

from lib.core.decorators import locked
from lib.core.settings import NEW_LINE
from lib.utils.file import FileUtils


@locked
def log(file, type, msg):
    if not file:
        return

    line = time.strftime("[%y-%m-%d %H:%M:%S]")
    line += "[{}] ".format(type.upper())
    line += msg
    line += NEW_LINE
    FileUtils.write_lines(file, line)
