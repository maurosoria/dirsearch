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

from urllib.parse import unquote, urlparse

from lib.core.exceptions import InvalidURLException
from lib.core.settings import DB_CONNECTION_TIMEOUT
from lib.report.factory import BaseReport, SQLReportMixin


class MySQLReport(SQLReportMixin, BaseReport):
    __format__ = "sql"
    __extension__ = None
    _reuse = True

    def is_valid(self, url):
        return url.startswith("mysql://")

    def connect(self, url):
        if not self.is_valid(url):
            raise InvalidURLException("Provided MySQL URL does not start with mysql://")

        import mysql.connector
        from mysql.connector.constants import SQLMode

        parsed = urlparse(url)
        try:
            conn = mysql.connector.connect(
                host=parsed.hostname,
                port=parsed.port or 3306,
                user=unquote(parsed.username) if parsed.username is not None else None,
                password=(
                    unquote(parsed.password) if parsed.password is not None else None
                ),
                database=unquote(parsed.path.lstrip("/")),
                connection_timeout=DB_CONNECTION_TIMEOUT,
            )
        except mysql.connector.Error as error:
            raise OSError(str(error)) from error
        conn.sql_mode = [SQLMode.ANSI_QUOTES]

        return conn
