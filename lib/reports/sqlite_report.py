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
import time

from lib.core.decorators import locked
from lib.reports.base import FileBaseReport


class SQLiteReport(FileBaseReport):
    def open(self):
        self.file = sqlite3.connect(self.output, check_same_thread=False)
        self.cursor = self.file.cursor()

    def generate(self):
        commands = []
        if not self.entries:
            return []

        base = self.entries[0]
        table = f"{base.protocol}_{base.host}:{base.port}/{base.base_path}"
        commands.append([f"DROP TABLE IF EXISTS `{table}`"])
        commands.append(
            [
                f"""CREATE TABLE `{table}`
                ([time] TEXT, [path] TEXT, [status_code] INTEGER, [content_length] INTEGER, [content_type] TEXT, [redirect] TEXT)
             """
            ]
        )

        for entry in self.entries:
            for result in entry.results:
                path = "/" + entry.base_path + result.path
                commands.append(
                    [
                        f"""
                    INSERT INTO `{table}` (time, path, status_code, content_length, content_type, redirect)
                        VALUES
                        (?, ?, ?, ?, ?, ?)
                                """,
                        (
                            time.ctime(),
                            path,
                            result.status,
                            result.response.length,
                            result.response.type,
                            result.response.redirect,
                        ),
                    ]
                )

        return commands

    @locked
    def save(self):
        for command in self.generate():
            self.cursor.execute(*command)

        self.file.commit()
