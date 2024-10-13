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

import sqlite3

from lib.report.factory import BaseReport, SQLReportMixin

from lib.utils.file import FileUtils


class SQLiteReport(SQLReportMixin, BaseReport):
    __format__ = "sql"
    __extension__ = "sqlite"
    __reuse = False

    def get_create_table_query(self, table):
        return (f'''CREATE TABLE "{table}" (
            time DATETIME,
            url TEXT,
            status_code INTEGER,
            content_length INTEGER,
            content_type TEXT,
            redirect TEXT
        );''',)

    def get_insert_table_query(self, table, values):
        return (f'INSERT INTO "{table}" VALUES (?, ?, ?, ?, ?, ?);', values)

    def connect(self, file):
        FileUtils.create_dir(FileUtils.parent(file))

        return sqlite3.connect(file, check_same_thread=False)
