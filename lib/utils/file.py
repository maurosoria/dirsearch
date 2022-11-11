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


class File:
    def __init__(self, *path_components):
        self._path = FileUtils.build_path(*path_components)

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

    def get_lines(self):
        return FileUtils.get_lines(self.path)

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        pass


class FileUtils:
    @staticmethod
    def build_path(*path_components):
        if path_components:
            path = os.path.join(*path_components)
        else:
            path = ""

        return path

    @staticmethod
    def get_abs_path(file_name):
        return os.path.abspath(file_name)

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

    @classmethod
    def can_write(cls, path):
        while not cls.exists(path):
            path = cls.parent(path)

        return os.access(path, os.W_OK)

    @staticmethod
    def read(file_name):
        return open(file_name, "r").read()

    @classmethod
    def get_files(cls, directory):
        files = []

        for path in os.listdir(directory):
            path = os.path.join(directory, path)
            if cls.is_dir(path):
                files.extend(cls.get_files(path))
            else:
                files.append(path)

        return files

    @staticmethod
    def get_lines(file_name):
        with open(file_name, "r", errors="replace") as fd:
            return fd.read().splitlines()

    @staticmethod
    def is_dir(path):
        return os.path.isdir(path)

    @staticmethod
    def is_file(path):
        return os.path.isfile(path)

    @staticmethod
    def parent(path, depth=1):
        for _ in range(depth):
            path = os.path.dirname(path)

        return path

    @classmethod
    def create_dir(cls, directory):
        if not cls.exists(directory):
            os.makedirs(directory)

    @staticmethod
    def write_lines(file_name, lines, overwrite=False):
        if isinstance(lines, list):
            lines = os.linesep.join(lines)
        with open(file_name, "w" if overwrite else "a") as f:
            f.writelines(lines)
