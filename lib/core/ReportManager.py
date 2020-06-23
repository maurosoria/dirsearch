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

import threading


class ReportManager(object):
    def __init__(self):
        self.outputs = []
        self.lock = threading.Lock()

    def addOutput(self, output):
        self.outputs.append(output)

    def addPath(self, path, status, response):
        with self.lock:
            for output in self.outputs:
                output.addPath(path, status, response)

    def save(self):
        with self.lock:
            for output in self.outputs:
                output.save()

    def close(self):
        for output in self.outputs:
            output.close()
