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

class BaseReport(object):
    def save(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class FileBaseReport(BaseReport):
    def __init__(self, output_file_name, entries=[]):
        self.output = output_file_name
        self.entries = entries
        self.header_written = False
        self.written_entries = []

        self.open()

    def open(self):
        from os import name as os_name

        if os_name == "nt":
            from os.path import normpath, dirname
            from os import makedirs

            output = normpath(self.output)
            makedirs(dirname(output), exist_ok=True)

            self.output = output

        self.file = open(self.output, 'w+')

    def save(self):
        self.file.writelines(self.generate())
        self.file.flush()

    def close(self):
        self.file.close()

    def generate(self):
        raise NotImplementedError
