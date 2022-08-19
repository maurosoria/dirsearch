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

class CaseInsensitiveDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._convert_keys()

    def __setitem__(self, key, value):
        if isinstance(key, str):
            key = key.lower()

        super().__setitem__(key.lower(), value)

    def __getitem__(self, key):
        if isinstance(key, str):
            key = key.lower()

        return super().__getitem__(key.lower())

    def _convert_keys(self):
        for key in list(self.keys()):
            value = super().pop(key)
            self.__setitem__(key, value)


class OrderedSet():
    def __init__(self, items=[]):
        self._data = dict()

        for item in items:
            self._data[item] = None

    def __contains__(self, item):
        return item in self._data

    def __eq__(self, other):
        return self._data.keys() == other._data.keys()

    def __iter__(self):
        return iter(list(self._data))

    def __len__(self):
        return len(self._data)

    def add(self, item):
        self._data[item] = None

    def clear(self):
        self._data.clear()

    def discard(self, item):
        self._data.pop(item, None)

    def pop(self):
        self._data.popitem()

    def remove(self, item):
        del self._data[item]

    def update(self, items):
        for item in items:
            self.add(item)
