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
from lib.reports import *


class Result(object):
    def __init__(self, path, status, response):
        self.path = path
        self.status = status
        self.response = response

    def getContentLength(self):
        try:
            contentLength = int(self.response.headers["content-length"])
        except (KeyError, ValueError):
            contentLength = len(self.response.body)
        return contentLength


class Report(object):
    def __init__(self, host, port, protocol, basePath):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.basePath = basePath
        self.results = []

        if self.basePath.endswith("/"):
            self.basePath = self.basePath[:-1]

        if self.basePath.startswith("/"):
            self.basePath = self.basePath[1:]

    def addResult(self, path, status, response):
        result = Result(path, status, response)
        self.results.append(result)


class ReportManager(object):
    def __init__(self, saveFormat, outputFile):
        self.format = saveFormat
        self.report = []
        self.reportObj = None
        self.output = outputFile
        self.lock = threading.Lock()

    def updateReport(self, report):
        self.report.append(report)
        self.writeReport()

    def writeReport(self):
        if self.reportObj == None:
            if self.format == "simple":
                report = SimpleReport(self.output, self.report)
            elif self.format == "json":
                report = JSONReport(self.output, self.report)
            elif self.format == "xml":
                report = XMLReport(self.output, self.report)
            elif self.format == "md":
                report = MarkdownReport(self.output, self.report)
            elif self.format == "csv":
                report = CSVReport(self.output, self.report)
            else:
                report = PlainTextReport(self.output, self.report)

            self.reportObj = report
            
        self.reportObj.save()

    def save(self):
        with self.lock:
            self.output.save()

    def close(self):
        self.output.close()
