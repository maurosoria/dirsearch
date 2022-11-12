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
import sys

from ipaddress import IPv4Network, IPv6Network
from urllib.parse import quote, urljoin

from lib.core.settings import (
    INVALID_CHARS_FOR_WINDOWS_FILENAME,
    INSECURE_CSV_CHARS,
    INVALID_FILENAME_CHAR_REPLACEMENT,
    IS_WINDOWS,
    URL_SAFE_CHARS,
    SCRIPT_PATH,
    TEXT_CHARS,
)
from lib.utils.file import FileUtils


def get_config_file():
    return os.environ.get("DIRSEARCH_CONFIG") or FileUtils.build_path(SCRIPT_PATH, "config.ini")


def safequote(string_):
    return quote(string_, safe=URL_SAFE_CHARS)


def uniq(array, type_=list):
    return type_(filter(None, dict.fromkeys(array)))


def lstrip_once(string, pattern):
    if string.startswith(pattern):
        return string[len(pattern):]

    return string


def rstrip_once(string, pattern):
    if string.endswith(pattern):
        return string[:-len(pattern)]

    return string


# Some characters are denied in file name by Windows
def get_valid_filename(string):
    for char in INVALID_CHARS_FOR_WINDOWS_FILENAME:
        string = string.replace(char, INVALID_FILENAME_CHAR_REPLACEMENT)

    return string


def human_size(num):
    base = 1024
    for unit in ["B ", "KB", "MB", "GB"]:
        if -base < num < base:
            return f"{num}{unit}"
        num = round(num / base)

    return f"{num}TB"


def is_binary(bytes):
    return bool(bytes.translate(None, TEXT_CHARS))


def is_ipv6(ip):
    return ip.count(":") >= 2


def iprange(subnet):
    network = IPv4Network(subnet)
    if is_ipv6(subnet):
        network = IPv6Network(subnet)

    return [str(ip) for ip in network]


# Prevent CSV injection. Reference: https://www.exploit-db.com/exploits/49370
def escape_csv(text):
    if text.startswith(INSECURE_CSV_CHARS):
        text = "'" + text

    return text.replace('"', '""')


# The browser direction behavior when you click on <a href="bar">link</a>
# (https://website.com/folder/foo -> https://website.com/folder/bar)
def merge_path(url, path):
    parts = url.split("/")
    # Normalize path like the browser does (dealing with ../ and ./)
    path = urljoin("/", path).lstrip("/")
    parts[-1] = path

    return "/".join(parts)


# Reference: https://stackoverflow.com/questions/46129898/conflict-between-sys-stdin-and-input-eoferror-eof-when-reading-a-line
def read_stdin():
    buffer = sys.stdin.read()

    try:
        if IS_WINDOWS:
            tty = "CON:"
        else:
            tty = os.ttyname(sys.stdout.fileno())

        sys.stdin = open(tty)
    except OSError:
        pass

    return buffer
