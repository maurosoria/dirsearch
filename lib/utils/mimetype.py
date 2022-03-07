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

import re
import json

from defusedxml import ElementTree

from lib.core.settings import QUERY_STRING_REGEX


class MimeTypeUtils:
    @staticmethod
    def is_json(content):
        try:
            json.loads(content)
            return True
        except json.decoder.JSONDecodeError:
            return False

    @staticmethod
    def is_xml(content):
        try:
            ElementTree.fromstring(content)
            return True
        except ElementTree.ParseError:
            return False
        except Exception:
            return True

    @staticmethod
    def is_query_string(content):
        if re.match(QUERY_STRING_REGEX, content):
            return True

        return False


def guess_mimetype(content):
    if MimeTypeUtils.is_json(content):
        return "application/json"
    elif MimeTypeUtils.is_xml(content):
        return "application/xml"
    elif MimeTypeUtils.is_query_string(content):
        return "application/x-www-form-urlencoded"
    else:
        return "text/plain"
