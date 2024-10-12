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

import threading

from functools import wraps
from time import time
from typing import Any, Callable, TypeVar
from typing_extensions import ParamSpec

_lock = threading.Lock()
_cache: dict[int, tuple[float, Any]] = {}
_cache_lock = threading.Lock()

# https://mypy.readthedocs.io/en/stable/generics.html#declaring-decorators
P = ParamSpec("P")
T = TypeVar("T")


def cached(timeout: int | float = 100) -> Callable[..., Any]:
    def _cached(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        def with_caching(*args: P.args, **kwargs: P.kwargs) -> T:
            key = id(func)
            for arg in args:
                key += id(arg)
            for k, v in kwargs.items():
                key += id(k) + id(v)

            # If it was cached and the cache timeout hasn't been reached
            if key in _cache and time() - _cache[key][0] < timeout:
                return _cache[key][1]

            with _cache_lock:
                result = func(*args, **kwargs)
                _cache[key] = (time(), result)

            return result

        return with_caching

    return _cached


def locked(func: Callable[P, T]) -> Callable[P, T]:
    def with_locking(*args: P.args, **kwargs: P.kwargs) -> T:
        with _lock:
            return func(*args, **kwargs)

    return with_locking
