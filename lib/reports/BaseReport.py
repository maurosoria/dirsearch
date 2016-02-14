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

class BaseReport(object):

    def __init__(self, host, port, protocol, basePath, output):
        self.output = output
        self.port = port
        self.host = host
        self.protocol = protocol
        self.basePath = basePath
        if self.basePath.endswith('/'):
            self.basePath = self.basePath[:-1]
        if self.basePath.startswith('/'):
            self.basePath = self.basePath[1:]
        self.pathList = []
        self.open()

    def addPath(self, path, status, response):
        contentLength = None
        try:
            contentLength = int(response.headers['content-length'])
        except (KeyError, ValueError):
            contentLength = len(response.body)
        self.pathList.append((path, status, contentLength))

    def open(self):
        self.file = open(self.output, 'w+')

    def save(self):
        self.file.seek(0)
        self.file.truncate(0)
        self.file.flush()
        self.file.writelines(self.generate())
        self.file.flush()

    def close(self):
        self.file.close()

    def generate(self):
        raise NotImplementedError


