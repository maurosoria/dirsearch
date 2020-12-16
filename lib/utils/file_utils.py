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

import os
import os.path


class File(object):
    def __init__(self, *path_components):
        self._path = FileUtils.build_path(*path_components)
        self.content = None

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, value):
        raise NotImplementedError

    def is_valid(self):
        return FileUtils.is_file(self.path)

    def exists(self):
        return FileUtils.exists(self.path)

    def can_read(self):
        return FileUtils.can_read(self.path)

    def can_write(self):
        return FileUtils.can_write(self.path)

    def read(self):
        return FileUtils.read(self.path)

    def update(self):
        self.content = self.read()

    def content(self):
        if not self.content:
            self.content = FileUtils.read()
        return self.content()

    def get_lines(self):
        for line in FileUtils.get_lines(self.path):
            yield line

    def __cmp__(self, other):
        if not isinstance(other, File):
            raise NotImplementedError
        if self.content() < other.content():
            return -1
        elif self.content() > other.content():
            return 1
        else:
            return 0

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        pass


class FileUtils(object):
    @staticmethod
    def build_path(*path_components):
        if path_components:
            path = os.path.join(*path_components)
        else:
            path = ""
        return path

    @staticmethod
    def exists(file_name):
        return os.access(file_name, os.F_OK)

    @staticmethod
    def can_read(file_name):
        try:
            with open(file_name):
                pass
        except IOError:
            return False
        return True

    @staticmethod
    def can_write(file_name):
        return os.access(file_name, os.W_OK)

    @staticmethod
    def read(file_name):
        return open(file_name, "r").read()

    @staticmethod
    def get_lines(file_name):
        with open(file_name, "r", errors="replace") as fd:
            return fd.read().splitlines()

    @staticmethod
    def is_dir(file_name):
        return os.path.isdir(file_name)

    @staticmethod
    def is_file(file_name):
        return os.path.isfile(file_name)

    @staticmethod
    def create_directory(directory):
        if not FileUtils.exists(directory):
            os.makedirs(directory)

    @staticmethod
    def size_human(num):
        base = 1024
        for x in ["B ", "KB", "MB", "GB"]:
            if num < base and num > -base:
                return "%3.0f%s" % (num, x)
            num /= base
        return "%3.0f %s" % (num, "TB")

    @staticmethod
    def write_lines(file_name, lines):
        if type(lines) is list:
            content = "\n".join(lines)
        else:
            content = lines
        with open(file_name, "w") as f:
            f.writelines(content)
