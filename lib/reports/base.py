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

from lib.core.decorators import locked
from lib.core.settings import IS_WINDOWS


class FileBaseReport:
    def __init__(self, output_file):
        if IS_WINDOWS:
            from os.path import normpath

            output_file = normpath(output_file)

        self.output_file = output_file

    @locked
    def save(self, entries):
        if not entries:
            return

        with open(self.output_file, "w") as fd:
            fd.writelines(self.generate(entries))
            fd.flush()

    def generate(self, entries):
        raise NotImplementedError
