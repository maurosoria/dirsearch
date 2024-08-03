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

import psycopg

from lib.core.decorators import locked
from lib.core.exceptions import InvalidURLException
from lib.report.factory import BaseReport, SQLReportMixin


class PostgreSQLReport(SQLReportMixin, BaseReport):
    __format__ = "sql"
    __extension__ = None
    __reuse = True

    def is_valid(self, url):
        return url.startswith(("postgres://", "postgresql://"))

    def connect(self, url):
        if not self.is_valid(url):
            raise InvalidURLException("Provided PostgreSQL URL does not start with postgresql://")

        return psycopg.connect(url)
