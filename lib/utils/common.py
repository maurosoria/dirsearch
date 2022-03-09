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

try:
    import cPickle as _pickle
except ModuleNotFoundError:
    import pickle as _pickle

from ipaddress import IPv4Network, IPv6Network
from urllib.parse import quote

from lib.core.settings import (
    INVALID_CHARS_FOR_WINDOWS_FILENAME, INSECURE_CSV_CHARS,
    INVALID_FILENAME_CHAR_REPLACEMENT, ALLOWED_PICKLE_MODULES,
    UNSAFE_PICKLE_BUILTINS, URL_SAFE_CHARS, TEXT_CHARS,
)


def safequote(string_):
    return quote(string_, safe=URL_SAFE_CHARS)


def uniq(string_list):
    if not string_list:
        return string_list

    return list(filter(None, dict.fromkeys(string_list)))


# Some characters are denied in file name by Windows
def get_valid_filename(string):
    for char in INVALID_CHARS_FOR_WINDOWS_FILENAME:
        string = string.replace(char, INVALID_FILENAME_CHAR_REPLACEMENT)

    return string


def human_size(num):
    base = 1024
    for x in ["B ", "KB", "MB", "GB"]:
        if -base < num < base:
            return "%3.0f%s" % (num, x)
        num /= base
    return "%3.0f %s" % (num, "TB")


def is_ipv6(ip):
    return ip.count(":") >= 2


def iprange(subnet):
    network = IPv4Network(subnet)
    if is_ipv6(subnet):
        network = IPv6Network(subnet)

    return [str(ip) for ip in network]


def is_binary(bytes):
    return bool(bytes.translate(None, TEXT_CHARS))


# Prevent CSV injection. Reference: https://www.exploit-db.com/exploits/49370
def escape_csv(text):
    if text.startswith(INSECURE_CSV_CHARS):
        text = "'" + text

    return text.replace('"', '""')


# Reference: https://docs.python.org/3.4/library/pickle.html#restricting-globals
class RestrictedUnpickler(_pickle.Unpickler):
    def find_class(self, module, name):
        if (
            module in ALLOWED_PICKLE_MODULES
            or module == "builtins"
            and name not in UNSAFE_PICKLE_BUILTINS
            or any(
                module.startswith(f"{module_}.") for module_ in ALLOWED_PICKLE_MODULES
            )
        ):
            return super().find_class(module, name)

        raise _pickle.UnpicklingError()


def unpickle(*args, **kwargs):
    return RestrictedUnpickler(*args, **kwargs).load()


def pickle(obj, *args, **kwargs):
    return _pickle.Pickler(*args, **kwargs).dump(obj)
