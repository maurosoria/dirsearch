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

import time

from lib.core.decorators import locked
from lib.core.settings import IS_WINDOWS


class FileBaseReport:
    def __init__(self, output_file):
        if IS_WINDOWS:
            from os.path import normpath

            output_file = normpath(output_file)

        self.output_file = output_file

    def generate(self, entries):
        raise NotImplementedError

    @locked
    def save(self, entries):
        if not entries:
            return

        with open(self.output_file, "w") as fd:
            fd.writelines(self.generate(entries))
            fd.flush()


class SQLBaseReport:
    def __init__(self, database):
        self.conn = None
        self.cursor = None

        self.connect(database)

    def connect(self, database):
        raise NotImplementedError

    def drop_table_query(self, table):
        return (f'DROP TABLE IF EXISTS "{table}"',)

    def create_table_query(self, table):
        return (f'''CREATE TABLE "{table}" (
            time TIMESTAMP,
            url TEXT,
            status_code INTEGER,
            content_length INTEGER,
            content_type TEXT,
            redirect TEXT
        );''',)

    def insert_table_query(self, table, values):
        return (f'''INSERT INTO "{table}" (time, url, status_code, content_length, content_type, redirect)
                    VALUES
                    (%s, %s, %s, %s, %s, %s)''', (time.strftime("%Y-%m-%d %H:%M:%S"), *values))

    def generate(self, entries):
        queries = []
        created_tables = []

        for entry in entries:
            host = entry.url.split("/")[2]
            if host not in created_tables:
                queries.append(self.drop_table_query(host))
                queries.append(self.create_table_query(host))
                created_tables.append(host)

            queries.append(
                self.insert_table_query(
                    host, (entry.url, entry.status, entry.length, entry.type, entry.redirect)
                )
            )

        return queries

    @locked
    def save(self, entries):
        for query in self.generate(entries):
            self.cursor.execute(*query)

        self.conn.commit()
