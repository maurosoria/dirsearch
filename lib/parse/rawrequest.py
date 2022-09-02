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

from lib.core.exceptions import InvalidRawRequest
from lib.core.logger import logger
from lib.parse.headers import HeadersParser
from lib.utils.file import File


def parse_raw(raw_file):
    with File(raw_file) as fd:
        raw_content = fd.read()

    try:
        head, body = raw_content.split("\n\n", 1)
    except ValueError:
        try:
            head, body = raw_content.split("\r\n\r\n", 1)
        except ValueError:
            head = raw_content.strip("\n")
            body = None

    try:
        method, path = head.splitlines()[0].split()[:2]
        headers = HeadersParser("\n".join(head.splitlines()[1:]))
        host = headers.get("host")
    except KeyError:
        raise InvalidRawRequest("Can't find the Host header in the raw request")
    except Exception as e:
        logger.exception(e)
        raise InvalidRawRequest("The raw request is formatively invalid")

    return [host + path], method, dict(headers), body
