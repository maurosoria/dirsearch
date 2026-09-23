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

from lib.core.data import options
from lib.report.factory import BaseReport, SQLReportMixin
from lib.utils.file import FileUtils


class SQLiteReport(SQLReportMixin, BaseReport):
    __format__ = "sql"
    __extension__ = "sqlite"
    _reuse = True

    def __init__(self, commit_batch_size=None):
        super().__init__()
        if commit_batch_size is None:
            commit_batch_size = options.get("sqlite_commit_batch_size", 1)
        if not isinstance(commit_batch_size, int) or commit_batch_size < 1:
            raise ValueError("SQLite commit batch size must be a positive integer")

        self._commit_batch_size = commit_batch_size
        self._pending_writes = 0

    def _commit(self, conn):
        conn.commit()
        self._pending_writes = 0

    def _after_save(self, conn):
        self._pending_writes += 1
        if self._pending_writes >= self._commit_batch_size:
            self._commit(conn)

    def get_create_table_query(self, table):
        return (f'''CREATE TABLE IF NOT EXISTS "{table}" (
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
        conn = sqlite3.connect(file, check_same_thread=False)
        # Check if the file is a proper sqlite database
        try:
            conn.cursor().execute("PRAGMA integrity_check")
        except sqlite3.DatabaseError as error:
            conn.close()
            raise ValueError(
                f"{file} is not empty or is not a valid SQLite database"
            ) from error
        else:
            return conn
