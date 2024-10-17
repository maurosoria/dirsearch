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

from lib.core.decorators import locked
from lib.core.settings import (
    COMMAND,
    NEW_LINE,
    START_TIME,
)
from lib.report.factory import BaseReport, FileReportMixin
from lib.utils.common import get_readable_size


class PlainTextReport(FileReportMixin, BaseReport):
    __format__ = "plain"
    __extension__ = "txt"

    def new(self):
        return f"# Dirsearch started {START_TIME} as: {COMMAND}" + NEW_LINE * 2

    @locked
    def save(self, file, result):
        readable_size = get_readable_size(result.length)
        data = self.parse(file)
        data += f"{result.status} {readable_size.rjust(6, chr(32))} {result.url}"

        if result.redirect:
            data += f"  ->  {result.redirect}"

        data += NEW_LINE

        self.write(file, data)
