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
from os import makedirs
from os import name as os_name
from os.path import normpath, dirname

from lib.reports.base import FileBaseReport


class SQLiteReport(FileBaseReport):
    def open(self):
        if os_name == "nt":
            output = normpath(self.output)
            makedirs(dirname(output), exist_ok=True)

            self.output = output

        self.file = sqlite3.connect(self.output, check_same_thread=False)
        self.cursor = self.file.cursor()

    def generate(self):
        commands = []
        if not self.entries:
            return []

        table = "{}_{}_{}".format(self.entries[0].protocol, self.entries[0].host, self.entries[0].port)
        commands.append(["DROP TABLE IF EXISTS `{}`".format(table)])
        commands.append(['''
            CREATE TABLE `{}`
            ([time] TEXT, [path] TEXT, [status_code] INTEGER, [content_length] INTEGER, [redirect] TEXT)
                        '''.format(table)
            ]
        )

        for entry in self.entries:
            for e in entry.results:
                path = "/" + entry.base_path + e.path
                commands.append(['''
                    INSERT INTO `{}` (time, path, status_code, content_length, redirect)
                        VALUES
                        (?, ?, ?, ?, ?)
                                '''.format(table), (
                    time.ctime(), path, e.status, e.response.length, e.response.redirect
                )])

        return commands

    def save(self):
        for command in self.generate():
            self.cursor.execute(*command)
        self.file.commit()
