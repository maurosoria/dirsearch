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
import threading
from abc import ABC, abstractmethod

from lib.core.decorators import locked
from lib.core.exceptions import (
    CannotConnectException,
    FileExistsException,
    InvalidURLException,
)
from lib.core.settings import DEFAULT_ENCODING
from lib.utils import safe_xml
from lib.utils.file import FileUtils


REPORT_PARSE_ERRORS = (
    OSError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
    safe_xml.ParseError,
    safe_xml.UnsafeXML,
)

SQL_CONNECTION_ERRORS = (
    OSError,
    ValueError,
    ImportError,
    sqlite3.DatabaseError,
    InvalidURLException,
)


class BaseReport(ABC):
    def __init__(self):
        self._operation_lock = threading.Lock()

    @abstractmethod
    def initiate(self):
        raise NotImplementedError

    @abstractmethod
    def save(self, result):
        raise NotImplementedError

    def flush(self):
        pass


class FileReportMixin:
    _newline = None

    def initiate(self, file):
        FileUtils.create_dir(FileUtils.parent(file))
        if FileUtils.exists(file) and not FileUtils.is_empty(file):
            self.validate(file)
        else:
            self.write(file, self.new())

    def validate(self, file):
        try:
            self.parse(file)
        except REPORT_PARSE_ERRORS as error:
            raise FileExistsException(f"Output file {file} already exists") from error

    def parse(self, file):
        with open(file, "r", encoding=DEFAULT_ENCODING) as file_handle:
            return file_handle.read()

    def _atomic_writer(self, file):
        return FileUtils.atomic_write_private_text(
            file,
            encoding=DEFAULT_ENCODING,
            newline=self._newline,
        )

    def write(self, file, data):
        with self._atomic_writer(file) as fh:
            fh.write(data)

    def append(self, file, data):
        FileUtils.append_private_text(
            file,
            data,
            encoding=DEFAULT_ENCODING,
            newline=self._newline,
        )

    def finish(self):
        pass


class SQLReportMixin:
    # Reuse the connection
    _conn = None
    _conn_database = None

    def get_connection(self, database):
        # Reuse the old connection
        if not self._reuse:
            return self.connect(database)

        if self._conn is not None and self._conn_database != database:
            self._close_connection()

        if self._conn is None:
            self._conn = self.connect(database)
            self._conn_database = database

        return self._conn

    def _commit(self, conn):
        conn.commit()

    def _after_save(self, conn):
        self._commit(conn)

    def _close_connection(self):
        conn = self._conn
        if conn is None:
            return

        try:
            self._commit(conn)
        finally:
            try:
                conn.close()
            finally:
                self._conn = None
                self._conn_database = None

    def get_create_table_query(self, table):
        return (f'''CREATE TABLE IF NOT EXISTS "{table}" (
            time TIMESTAMP,
            url TEXT,
            status_code INTEGER,
            content_length INTEGER,
            content_type TEXT,
            redirect TEXT
        );''',)

    def get_insert_table_query(self, table, values):
        return (f'''INSERT INTO "{table}" (time, url, status_code, content_length, content_type, redirect)
                    VALUES
                    (%s, %s, %s, %s, %s, %s);''', values)

    def initiate(self, database, table):
        try:
            conn = self.get_connection(database)
        except SQL_CONNECTION_ERRORS as e:
            raise CannotConnectException(f"Cannot connect to the SQL database: {str(e)}") from e

        cursor = conn.cursor()

        cursor.execute(*self.get_create_table_query(table))
        self._commit(conn)

        if not self._reuse:
            conn.close()

    @locked
    def save(self, database, table, result):
        conn = self.get_connection(database)
        cursor = conn.cursor()

        cursor.execute(
            *self.get_insert_table_query(
                table,
                (
                    result.datetime,
                    result.url,
                    result.status,
                    result.length,
                    result.type,
                    result.redirect,
                ),
            )
        )
        self._after_save(conn)

        if not self._reuse:
            conn.close()

    @locked
    def flush(self):
        if self._conn is not None:
            self._commit(self._conn)

    @locked
    def finish(self):
        self._close_connection()
