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
    def __init__(self, output_file_name, entries=None):
        if IS_WINDOWS:
            from os.path import normpath, dirname
            from os import makedirs

            output_file_name = normpath(output_file_name)
            makedirs(dirname(output_file_name), exist_ok=True)

        self.output = output_file_name
        self.entries = entries or []
        self.header_written = False
        self.written_entries = []

        self.open()

    def open(self):
        self.file = open(self.output, 'w+')

    @locked
    def save(self):
        self.file.writelines(self.generate())
        self.file.flush()

    def close(self):
        self.file.close()

    def generate(self):
        raise NotImplementedError
