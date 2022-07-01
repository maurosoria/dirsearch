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

import threading

from functools import wraps
from time import time

_lock = threading.Lock()
_cache = {}
_cache_lock = threading.Lock()


def cached(timeout=100):
    def _cached(func):
        @wraps(func)
        def with_caching(*args, **kwargs):
            key = id(func)
            for arg in args:
                key += id(arg)
            for k, v in kwargs:
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


def locked(func):
    def with_locking(*args, **kwargs):
        with _lock:
            return func(*args, **kwargs)

    return with_locking
