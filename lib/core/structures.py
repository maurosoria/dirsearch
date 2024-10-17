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

from __future__ import annotations

from typing import Any, Iterator


class CaseInsensitiveDict(dict):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._convert_keys()

    def __setitem__(self, key: Any, value: Any) -> None:
        if isinstance(key, str):
            key = key.lower()

        super().__setitem__(key.lower(), value)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            key = key.lower()

        return super().__getitem__(key.lower())

    def _convert_keys(self) -> None:
        for key in list(self.keys()):
            value = super().pop(key)
            self.__setitem__(key, value)


class OrderedSet:
    def __init__(self, items: list[Any] = []) -> None:
        self._data: dict[Any, Any] = dict()

        for item in items:
            self._data[item] = None

    def __contains__(self, item: Any) -> bool:
        return item in self._data

    def __eq__(self, other: Any) -> bool:
        return self._data.keys() == other._data.keys()

    def __iter__(self) -> Iterator[Any]:
        return iter(list(self._data))

    def __len__(self) -> int:
        return len(self._data)

    def add(self, item: Any) -> None:
        self._data[item] = None

    def clear(self) -> None:
        self._data.clear()

    def discard(self, item: Any) -> None:
        self._data.pop(item, None)

    def pop(self) -> None:
        self._data.popitem()

    def remove(self, item: Any) -> None:
        del self._data[item]

    def update(self, items: list[Any]) -> None:
        for item in items:
            self.add(item)
