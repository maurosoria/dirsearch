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

from lib.core.exceptions import InvalidURLException
from lib.reports.base import SQLBaseReport


class PostgreSQLReport(SQLBaseReport):
    def connect(self, url):
        if not url.startswith("postgresql://"):
            raise InvalidURLException("Provided PostgreSQL URL does not start with postgresql://")

        self.conn = psycopg.connect(url)
        self.cursor = self.conn.cursor()
