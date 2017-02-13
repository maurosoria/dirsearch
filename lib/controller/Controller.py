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

import os
from queue import Queue
import time
import sys
import gc
from threading import Lock

from lib.connection import Requester, RequestException
from lib.core import Dictionary, Fuzzer, ReportManager
from lib.reports import JSONReport, PlainTextReport, SimpleReport
from lib.utils import FileUtils


class SkipTargetInterrupt(Exception):
    pass


MAYOR_VERSION = 0
MINOR_VERSION = 3
REVISION = 7
VERSION = {
    "MAYOR_VERSION": MAYOR_VERSION,
    "MINOR_VERSION": MINOR_VERSION,
    "REVISION": REVISION
}

class Controller(object):
    def __init__(self, script_path, arguments, output):
        global VERSION
        PROGRAM_BANNER = open(FileUtils.buildPath(script_path, "lib", "controller", "banner.txt")).read().format(
            **VERSION)
        self.script_path = script_path
        self.exit = False
        self.arguments = arguments
        self.output = output
        self.savePath = self.script_path
        if self.arguments.saveHome:
            savePath = self.getSavePath()
            if not FileUtils.exists(savePath):
                FileUtils.createDirectory(savePath)
            if FileUtils.exists(savePath) and not FileUtils.isDir(savePath):
                self.output.error('Cannot use {} because is a file. Should be a directory'.format(savePath))
                exit(1)
            if not FileUtils.canWrite(savePath):
                self.output.error('Directory {} is not writable'.format(savePath))
                exit(1)
            logs = FileUtils.buildPath(savePath, "logs")
            if not FileUtils.exists(logs):
                FileUtils.createDirectory(logs)
            reports = FileUtils.buildPath(savePath, "reports")
            if not FileUtils.exists(reports):
                FileUtils.createDirectory(reports)
            self.savePath = savePath
        self.reportsPath = FileUtils.buildPath(self.savePath, "logs")
        self.blacklists = self.getBlacklists()
        self.fuzzer = None
        self.excludeStatusCodes = self.arguments.excludeStatusCodes
        self.recursive = self.arguments.recursive
        self.directories = Queue()
        self.excludeSubdirs = (arguments.excludeSubdirs if arguments.excludeSubdirs is not None else [])
        self.output.header(PROGRAM_BANNER)
        self.dictionary = Dictionary(self.arguments.wordlist, self.arguments.extensions,
                                     self.arguments.lowercase, self.arguments.forceExtensions)
        self.printConfig()
        self.errorLog = None
        self.errorLogPath = None
        self.errorLogLock = Lock()
        self.batch = False
        self.batchSession = None
        self.setupErrorLogs()
        self.output.newLine("\nError Log: {0}".format(self.errorLogPath))
        if self.arguments.autoSave and len(self.arguments.urlList) > 1:
            self.setupBatchReports()
            self.output.newLine("\nAutoSave path: {0}".format(self.batchDirectoryPath))
        if self.arguments.useRandomAgents:
            self.randomAgents = FileUtils.getLines(FileUtils.buildPath(script_path, "db", "user-agents.txt"))
        try:
            for url in self.arguments.urlList:
                try:
                    gc.collect()
                    self.reportManager = ReportManager()
                    self.currentUrl = url
                    self.output.target(self.currentUrl)
                    try:
                        self.requester = Requester(url, cookie=self.arguments.cookie,
                                               useragent=self.arguments.useragent, maxPool=self.arguments.threadsCount,
                                               maxRetries=self.arguments.maxRetries, timeout=self.arguments.timeout,
                                               ip=self.arguments.ip, proxy=self.arguments.proxy,
                                               redirect=self.arguments.redirect, 
                                               requestByHostname=self.arguments.requestByHostname)
                        self.requester.request("/")
                    except RequestException as e:
                        self.output.error(e.args[0]['message'])
                        raise SkipTargetInterrupt
                    if self.arguments.useRandomAgents:
                        self.requester.setRandomAgents(self.randomAgents)
                    for key, value in arguments.headers.items():
                        self.requester.setHeader(key, value)
                    # Initialize directories Queue with start Path
                    self.basePath = self.requester.basePath
                    if self.arguments.scanSubdirs is not None:
                        for subdir in self.arguments.scanSubdirs:
                            self.directories.put(subdir)
                    else:
                        self.directories.put('')
                    self.setupReports(self.requester)
                    matchCallbacks = [self.matchCallback]
                    notFoundCallbacks = [self.notFoundCallback]
                    errorCallbacks = [self.errorCallback, self.appendErrorLog]
                    self.fuzzer = Fuzzer(self.requester, self.dictionary, testFailPath=self.arguments.testFailPath,
                                         threads=self.arguments.threadsCount, matchCallbacks=matchCallbacks,
                                         notFoundCallbacks=notFoundCallbacks, errorCallbacks=errorCallbacks)
                    self.wait()
                except SkipTargetInterrupt:
                    continue
                finally:
                    self.reportManager.save()
        except KeyboardInterrupt:
            self.output.error('\nCanceled by the user')
            exit(0)
        finally:
            if not self.errorLog.closed:
                self.errorLog.close()
            self.reportManager.close()

        self.output.warning('\nTask Completed')

    def printConfig(self):
        self.output.config(', '.join(self.arguments.extensions), str(self.arguments.threadsCount),
                                str(len(self.dictionary)))

    def getSavePath(self):
        basePath = None
        dirPath = None
        basePath = os.path.expanduser('~')
        if os.name == 'nt':
            dirPath = "dirsearch"
        else:
            dirPath = ".dirsearch"
        return FileUtils.buildPath(basePath, dirPath)

    def getBlacklists(self):
        blacklists = {}
        for status in [400, 403, 500]:
            blacklistFileName = FileUtils.buildPath(self.script_path, 'db')
            blacklistFileName = FileUtils.buildPath(blacklistFileName, '{}_blacklist.txt'.format(status))
            if not FileUtils.canRead(blacklistFileName):
                # Skip if cannot read file
                continue
            blacklists[status] = []
            for line in FileUtils.getLines(blacklistFileName):
                # Skip comments
                if line.lstrip().startswith('#'):
                    continue
                blacklists[status].append(line)
        return blacklists

    def setupErrorLogs(self):
        fileName = "errors-{0}.log".format(time.strftime('%y-%m-%d_%H-%M-%S'))
        self.errorLogPath = FileUtils.buildPath(FileUtils.buildPath(self.savePath, "logs", fileName))
        self.errorLog = open(self.errorLogPath, "w")

    def setupBatchReports(self):
        self.batch = True
        self.batchSession = "BATCH-{0}".format(time.strftime('%y-%m-%d_%H-%M-%S'))
        self.batchDirectoryPath = FileUtils.buildPath(self.savePath, "reports", self.batchSession)
        if not FileUtils.exists(self.batchDirectoryPath):
            FileUtils.createDirectory(self.batchDirectoryPath)
            if not FileUtils.exists(self.batchDirectoryPath):
                self.output.error("Couldn't create batch folder {}".format(self.batchDirectoryPath))
                sys.exit(1)
        if FileUtils.canWrite(self.batchDirectoryPath):
            FileUtils.createDirectory(self.batchDirectoryPath)
            targetsFile = FileUtils.buildPath(self.batchDirectoryPath, "TARGETS.txt")
            FileUtils.writeLines(targetsFile, self.arguments.urlList)
        else:
            self.output.error("Couldn't create batch folder {}.".format(self.batchDirectoryPath))
            sys.exit(1)

    def setupReports(self, requester):
        if self.arguments.autoSave:
            basePath = ('/' if requester.basePath is '' else requester.basePath)
            basePath = basePath.replace(os.path.sep, '.')[1:-1]
            fileName = None
            directoryPath = None
            if self.batch:
                fileName = requester.host
                directoryPath = self.batchDirectoryPath
            else:
                fileName = ('{}_'.format(basePath) if basePath is not '' else '')
                fileName += time.strftime('%y-%m-%d_%H-%M-%S')
                directoryPath = FileUtils.buildPath(self.savePath,'reports', requester.host)
            outputFile = FileUtils.buildPath(directoryPath, fileName)

            if FileUtils.exists(outputFile):
                i = 2
                while FileUtils.exists(outputFile + "_" + str(i)):
                    i += 1
                outputFile += "_" + str(i)
            if not FileUtils.exists(directoryPath):
                FileUtils.createDirectory(directoryPath)
                if not FileUtils.exists(directoryPath):
                    self.output.error("Couldn't create reports folder {}".format(directoryPath))
                    sys.exit(1)
            if FileUtils.canWrite(directoryPath):
                report = None
                if self.arguments.autoSaveFormat == 'simple':
                    report = SimpleReport(requester.host, requester.port, requester.protocol, requester.basePath,
                                          outputFile)
                if self.arguments.autoSaveFormat == 'json':
                    report = JSONReport(requester.host, requester.port, requester.protocol, requester.basePath,
                                        outputFile)
                else:
                    report = PlainTextReport(requester.host, requester.port, requester.protocol, requester.basePath,
                                             outputFile)
                self.reportManager.addOutput(report)
            else:
                self.output.error("Can't write reports to {}".format(directoryPath))
                sys.exit(1)
        if self.arguments.simpleOutputFile is not None:
            self.reportManager.addOutput(SimpleReport(requester.host, requester.port, requester.protocol,
                                                      requester.basePath, self.arguments.simpleOutputFile))
        if self.arguments.plainTextOutputFile is not None:
            self.reportManager.addOutput(PlainTextReport(requester.host, requester.port, requester.protocol,
                                                         requester.basePath, self.arguments.plainTextOutputFile))
        if self.arguments.jsonOutputFile is not None:
            self.reportManager.addOutput(JSONReport(requester.host, requester.port, requester.protocol,
                                                    requester.basePath, self.arguments.jsonOutputFile))

    def matchCallback(self, path):
        self.index += 1
        if path.status is not None:
            if path.status not in self.excludeStatusCodes and (
                            self.blacklists.get(path.status) is None or path.path not in self.blacklists.get(
                        path.status)):
                self.output.statusReport(path.path, path.response)
                self.addDirectory(path.path)
                self.reportManager.addPath(self.currentDirectory + path.path, path.status, path.response)
                self.reportManager.save()
                del path

    def notFoundCallback(self, path):
        self.index += 1
        self.output.lastPath(path, self.index, len(self.dictionary))
        del path

    def errorCallback(self, path, errorMsg):
        self.output.addConnectionError()
        del path

    def appendErrorLog(self, path, errorMsg):
        with self.errorLogLock:
            line = time.strftime('[%y-%m-%d %H:%M:%S] - ')
            line += self.currentUrl + " - " + path + " - " + errorMsg
            self.errorLog.write(os.linesep + line)
            self.errorLog.flush()

    def handleInterrupt(self):
        self.output.warning('CTRL+C detected: Pausing threads, please wait...')
        self.fuzzer.pause()
        try:
            while True:
                msg = "[e]xit / [c]ontinue"
                if not self.directories.empty():
                    msg += " / [n]ext"
                if len(self.arguments.urlList) > 1:
                    msg += " / [s]kip target"
                self.output.inLine(msg + ': ')

                option = input()
                if option.lower() == 'e':
                    self.exit = True
                    self.fuzzer.stop()
                    raise KeyboardInterrupt
                elif option.lower() == 'c':
                    self.fuzzer.play()
                    return
                elif not self.directories.empty() and option.lower() == 'n':
                    self.fuzzer.stop()
                    return
                elif len(self.arguments.urlList) > 1 and option.lower() == 's':
                    raise SkipTargetInterrupt
                else:
                    continue
        except KeyboardInterrupt as SystemExit:
            self.exit = True
            raise KeyboardInterrupt


    def processPaths(self):
        while True:
            try:
                while not self.fuzzer.wait(0.3):
                    continue
                break
            except (KeyboardInterrupt, SystemExit) as e:
                self.handleInterrupt()

    def wait(self):
        while not self.directories.empty():
            self.index = 0
            self.currentDirectory = self.directories.get()
            self.output.warning('[{1}] Starting: {0}'.format(self.currentDirectory, time.strftime('%H:%M:%S')))
            self.fuzzer.requester.basePath = self.basePath + self.currentDirectory
            self.output.basePath = self.basePath + self.currentDirectory
            self.fuzzer.start()
            self.processPaths()
        return

    def addDirectory(self, path):
        if not self.recursive:
            return False
        if path.endswith('/'):
            if path in [directory + '/' for directory in self.excludeSubdirs]:
                return False
            self.directories.put(self.currentDirectory + path)
            return True
        else:
            return False
