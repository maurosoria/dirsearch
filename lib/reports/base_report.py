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

from multiprocessing import Queue, Lock
import queue


class BaseReport(object):

    def addPath(selg, path, status, response):
        raise NotImplementedError

    def save(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class FileBaseReport(BaseReport):

    def __init__(self, host, port, protocol, basePath, output, batch):
        self.output = output
        self.port = port
        self.host = host
        self.protocol = protocol
        self.basePath = basePath
        self.batch = batch

        if self.basePath.endswith("/"):
            self.basePath = self.basePath[:-1]

        if self.basePath.startswith("/"):
            self.basePath = self.basePath[1:]

        self.pathList = []
        self.open()

    def addPath(self, path, status, response):
        contentLength = None

        try:
            contentLength = int(response.headers["content-length"])

        except (KeyError, ValueError):
            contentLength = len(response.body)

        self.storeData((path, status, contentLength,))

    def storeData(self, data):
        self.pathList.append(data)

    def open(self):
        from os import name as os_name

        if os_name == "nt":
            from os.path import normpath, dirname
            from os import makedirs

            output = normpath(self.output)
            makedirs(dirname(output), exist_ok=True)

            self.output = output

        if self.batch:
            self.file = open(self.output, 'a+')

        else:
            self.file = open(self.output, 'w+')

    def save(self):
        if self.batch:
            self.file.seek(0)
            self.file.flush()
            self.file.writelines(self.generate())
            self.file.flush()
        else:
            self.file.seek(0)
            self.file.truncate(0)
            self.file.flush()
            self.file.writelines(self.generate())
            self.file.flush()

    def close(self):
        self.file.close()

    def generate(self):
        raise NotImplementedError


class TailableFileBaseReport(FileBaseReport):
    def __init__(self, host, port, protocol, basePath, output, batch):
        super().__init__(host, port, protocol, basePath, output, batch)
        self.writeQueue = Queue()
        self.saveMutex = Lock()

    def save(self):
        data = self.generate()
        self.file.write(data)
        self.file.flush()

    def storeData(self, data):
        self.writeQueue.put(data)
        self.save()

    def getPathIterator(self):
        while True:
            try:
                yield self.writeQueue.get(False)
            except queue.Empty:
                break
