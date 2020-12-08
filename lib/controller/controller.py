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

import gc
import os
import sys
import time
import re
import urllib.parse
from threading import Lock

from queue import Queue

from lib.connection import Requester, RequestException
from lib.core import Dictionary, Fuzzer, ReportManager
from lib.reports import JSONReport, XMLReport, PlainTextReport, SimpleReport, MarkdownReport, CSVReport
from lib.utils import FileUtils


class SkipTargetInterrupt(Exception):
    pass


MAYOR_VERSION = 0
MINOR_VERSION = 4
REVISION = 1
VERSION = {
    "MAYOR_VERSION": MAYOR_VERSION,
    "MINOR_VERSION": MINOR_VERSION,
    "REVISION": REVISION,
}


class Controller(object):
    def __init__(self, script_path, arguments, output):
        global VERSION
        program_banner = (
            open(FileUtils.build_path(script_path, "lib", "controller", "banner.txt"))
            .read()
            .format(**VERSION)
        )

        self.directories = Queue()
        self.script_path = script_path
        self.exit = False
        self.arguments = arguments
        self.output = output
        self.savePath = self.script_path
        self.doneDirs = []

        self.urlList = list(filter(None, dict.fromkeys(self.arguments.urlList)))

        self.recursive_level_max = self.arguments.recursive_level_max

        if self.arguments.httpmethod.lower() not in [
            "get", "head", "post", "put", "patch", "options", "delete", "trace", "debug", "connect"
        ]:
            self.output.error("Invalid HTTP method")
            exit(1)

        self.httpmethod = self.arguments.httpmethod.lower()

        if self.arguments.saveHome:
            savePath = self.getSavePath()

            if not FileUtils.exists(savePath):
                FileUtils.create_directory(savePath)

            if FileUtils.exists(savePath) and not FileUtils.is_dir(savePath):
                self.output.error(
                    "Cannot use {} because is a file. Should be a directory".format(
                        savePath
                    )
                )
                exit(1)

            if not FileUtils.can_write(savePath):
                self.output.error("Directory {} is not writable".format(savePath))
                exit(1)

            logs = FileUtils.build_path(savePath, "logs")

            if not FileUtils.exists(logs):
                FileUtils.create_directory(logs)

            reports = FileUtils.build_path(savePath, "reports")

            if not FileUtils.exists(reports):
                FileUtils.create_directory(reports)

            self.savePath = savePath

        self.reportsPath = FileUtils.build_path(self.savePath, "logs")
        self.blacklists = self.getBlacklists()
        self.includeStatusCodes = self.arguments.includeStatusCodes
        self.excludeStatusCodes = self.arguments.excludeStatusCodes
        self.excludeSizes = self.arguments.excludeSizes
        self.excludeTexts = self.arguments.excludeTexts
        self.excludeRegexps = self.arguments.excludeRegexps
        self.recursive = self.arguments.recursive
        self.minimumResponseSize = self.arguments.minimumResponseSize
        self.maximumResponseSize = self.arguments.maximumResponseSize
        self.scanSubdirs = arguments.scanSubdirs
        self.excludeSubdirs = (
            arguments.excludeSubdirs if arguments.excludeSubdirs else []
        )

        self.dictionary = Dictionary(
            self.arguments.wordlist,
            self.arguments.extensions,
            self.arguments.suffixes,
            self.arguments.prefixes,
            self.arguments.lowercase,
            self.arguments.uppercase,
            self.arguments.capitalization,
            self.arguments.forceExtensions,
            self.arguments.excludeExtensions,
            self.arguments.noExtension,
            self.arguments.onlySelected
        )

        self.allJobs = len(self.urlList) * (len(self.scanSubdirs) if self.scanSubdirs else 1)
        self.currentJob = 0
        self.errorLog = None
        self.errorLogPath = None
        self.threadsLock = Lock()
        self.batch = False
        self.batchSession = None
        self.got429 = False

        self.output.header(program_banner)
        self.printConfig()
        self.setupErrorLogs()
        self.output.errorLogFile(self.errorLogPath)

        if self.arguments.autoSave and len(self.urlList) > 1:
            self.setupBatchReports()
            self.output.newLine("\nAutoSave path: {0}".format(self.batchDirectoryPath))

        if self.arguments.useRandomAgents:
            self.randomAgents = FileUtils.get_lines(
                FileUtils.build_path(script_path, "db", "user-agents.txt")
            )

        try:
            for url in self.urlList:
                try:
                    gc.collect()
                    self.reportManager = ReportManager()
                    self.currentUrl = url
                    self.output.setTarget(self.currentUrl)
                    self.ignore429 = False

                    try:
                        self.requester = Requester(
                            url,
                            cookie=self.arguments.cookie,
                            useragent=self.arguments.useragent,
                            maxPool=self.arguments.threadsCount,
                            maxRetries=self.arguments.maxRetries,
                            timeout=self.arguments.timeout,
                            ip=self.arguments.ip,
                            proxy=self.arguments.proxy,
                            proxylist=self.arguments.proxylist,
                            redirect=self.arguments.redirect,
                            requestByHostname=self.arguments.requestByHostname,
                            httpmethod=self.httpmethod,
                            data=self.arguments.data,
                        )

                        self.requester.request("")

                    except RequestException as e:
                        self.output.error(e.args[0]["message"])
                        raise SkipTargetInterrupt

                    if self.arguments.useRandomAgents:
                        self.requester.setRandomAgents(self.randomAgents)

                    for key, value in arguments.headers.items():
                        self.requester.setHeader(key, value)

                    # Initialize directories Queue with start Path
                    self.basePath = self.requester.basePath

                    if self.scanSubdirs:
                        for subdir in self.scanSubdirs:
                            self.directories.put(subdir)

                    else:
                        self.directories.put("")

                    self.setupReports(self.requester)

                    matchCallbacks = [self.matchCallback]
                    notFoundCallbacks = [self.notFoundCallback]
                    errorCallbacks = [self.errorCallback, self.appendErrorLog]

                    self.fuzzer = Fuzzer(
                        self.requester,
                        self.dictionary,
                        testFailPath=self.arguments.testFailPath,
                        threads=self.arguments.threadsCount,
                        delay=self.arguments.delay,
                        matchCallbacks=matchCallbacks,
                        notFoundCallbacks=notFoundCallbacks,
                        errorCallbacks=errorCallbacks,
                    )
                    try:
                        self.wait()
                    except RequestException as e:
                        self.output.error(
                            "Fatal error during site scanning: " + e.args[0]["message"]
                        )
                        raise SkipTargetInterrupt

                except SkipTargetInterrupt:
                    continue

        except KeyboardInterrupt:
            self.output.error("\nCanceled by the user")
            exit(0)

        finally:
            if not self.errorLog.closed:
                self.errorLog.close()

            self.reportManager.close()

        self.output.warning("\nTask Completed")

    def printConfig(self):

        self.output.config(
            ', '.join(self.arguments.extensions),
            ', '.join(self.arguments.prefixes),
            ', '.join(self.arguments.suffixes),
            str(self.arguments.threadsCount),
            str(len(self.dictionary)),
            str(self.httpmethod),
        )

    def getSavePath(self):
        basePath = None
        dirPath = None
        basePath = os.path.expanduser("~")

        if os.name == "nt":
            dirPath = "dirsearch"
        else:
            dirPath = ".dirsearch"

        return FileUtils.build_path(basePath, dirPath)

    def getBlacklists(self):
        reext = re.compile(r'\%ext\%', re.IGNORECASE)
        blacklists = {}

        for status in [400, 403, 500]:
            blacklistFileName = FileUtils.build_path(self.script_path, "db")
            blacklistFileName = FileUtils.build_path(
                blacklistFileName, "{}_blacklist.txt".format(status)
            )

            if not FileUtils.can_read(blacklistFileName):
                # Skip if cannot read file
                continue

            blacklists[status] = []

            for line in FileUtils.get_lines(blacklistFileName):
                # Skip comments
                if line.lstrip().startswith("#"):
                    continue

                if line.startswith("/"):
                    line = line[1:]

                # Classic dirsearch blacklist processing (with %EXT% keyword)
                if "%ext%" in line.lower():
                    for extension in self.arguments.extensions:
                        entry = reext.sub(extension, line)

                        blacklists[status].append(entry)

                # Forced extensions is not used here because -r is only used for wordlist,
                # applying in blacklist may create false negatives

                else:
                    blacklists[status].append(line)

        return blacklists

    def setupErrorLogs(self):
        fileName = "errors-{0}.log".format(time.strftime("%y-%m-%d_%H-%M-%S"))
        self.errorLogPath = FileUtils.build_path(
            FileUtils.build_path(self.savePath, "logs", fileName)
        )
        self.errorLog = open(self.errorLogPath, "w")

    def setupBatchReports(self):
        self.batch = True
        self.batchSession = "BATCH-{0}".format(time.strftime("%y-%m-%d_%H-%M-%S"))
        self.batchDirectoryPath = FileUtils.build_path(
            self.savePath, "reports", self.batchSession
        )

        if not FileUtils.exists(self.batchDirectoryPath):
            FileUtils.create_directory(self.batchDirectoryPath)

            if not FileUtils.exists(self.batchDirectoryPath):
                self.output.error(
                    "Couldn't create batch folder {}".format(self.batchDirectoryPath)
                )
                sys.exit(1)

        if FileUtils.can_write(self.batchDirectoryPath):
            FileUtils.create_directory(self.batchDirectoryPath)
            targetsFile = FileUtils.build_path(self.batchDirectoryPath, "TARGETS.txt")
            FileUtils.write_lines(targetsFile, self.urlList)

        else:
            self.output.error(
                "Couldn't create batch folder {}.".format(self.batchDirectoryPath)
            )
            sys.exit(1)

    def setupReports(self, requester):
        if self.arguments.autoSave:

            basePath = requester.basePath
            basePath = basePath.replace(os.path.sep, ".")[:-1]
            fileName = None
            directoryPath = None

            if self.batch:
                fileName = requester.host
                directoryPath = self.batchDirectoryPath

            else:

                fileName = ('{}_'.format(basePath))
                fileName += time.strftime('%y-%m-%d_%H-%M-%S')
                fileName += ".{0}".format(self.arguments.autoSaveFormat)
                directoryPath = FileUtils.build_path(self.savePath, 'reports', requester.host)

            outputFile = FileUtils.build_path(directoryPath, fileName)

            self.output.outputFile(outputFile)

            if FileUtils.exists(outputFile):
                i = 2

                while FileUtils.exists(outputFile + "_" + str(i)):
                    i += 1

                outputFile += "_" + str(i)

            if not FileUtils.exists(directoryPath):
                FileUtils.create_directory(directoryPath)

                if not FileUtils.exists(directoryPath):
                    self.output.error(
                        "Couldn't create reports folder {}".format(directoryPath)
                    )
                    sys.exit(1)
            if FileUtils.can_write(directoryPath):
                report = None

                if self.arguments.autoSaveFormat == "simple":
                    report = SimpleReport(
                        requester.host,
                        requester.port,
                        requester.protocol,
                        requester.basePath,
                        outputFile,
                        self.batch,
                    )
                elif self.arguments.autoSaveFormat == "json":
                    report = JSONReport(
                        requester.host,
                        requester.port,
                        requester.protocol,
                        requester.basePath,
                        outputFile,
                        self.batch,
                    )
                elif self.arguments.autoSaveFormat == "xml":
                    report = XMLReport(
                        requester.host,
                        requester.port,
                        requester.protocol,
                        requester.basePath,
                        outputFile,
                        self.batch,
                    )
                elif self.arguments.autoSaveFormat == "md":
                    report = MarkdownReport(
                        requester.host,
                        requester.port,
                        requester.protocol,
                        requester.basePath,
                        outputFile,
                        self.batch,
                    )
                elif self.arguments.autoSaveFormat == "csv":
                    report = CSVReport(
                        requester.host,
                        requester.port,
                        requester.protocol,
                        requester.basePath,
                        outputFile,
                        self.batch,
                    )
                else:
                    report = PlainTextReport(
                        requester.host,
                        requester.port,
                        requester.protocol,
                        requester.basePath,
                        outputFile,
                        self.batch
                    )

                self.reportManager.addOutput(report)

            else:
                self.output.error("Can't write reports to {}".format(directoryPath))
                sys.exit(1)

        # TODO: format, refactor code
        if self.arguments.simpleOutputFile:
            self.reportManager.addOutput(
                SimpleReport(
                    requester.host, requester.port, requester.protocol,
                    requester.basePath, self.arguments.simpleOutputFile, self.batch
                )
            )

        if self.arguments.plainTextOutputFile:
            self.reportManager.addOutput(
                PlainTextReport(
                    requester.host, requester.port, requester.protocol,
                    requester.basePath, self.arguments.plainTextOutputFile, self.batch
                )
            )

        if self.arguments.jsonOutputFile:
            self.reportManager.addOutput(
                JSONReport(
                    requester.host, requester.port, requester.protocol,
                    requester.basePath, self.arguments.jsonOutputFile, self.batch
                )
            )

        if self.arguments.xmlOutputFile:
            self.reportManager.addOutput(
                XMLReport(
                    requester.host, requester.port, requester.protocol,
                    requester.basePath, self.arguments.xmlOutputFile, self.batch
                )
            )

        if self.arguments.markdownOutputFile:
            self.reportManager.addOutput(
                MarkdownReport(
                    requester.host, requester.port, requester.protocol,
                    requester.basePath, self.arguments.markdownOutputFile, self.batch
                )
            )
        if self.arguments.csvOutputFile:
            self.reportManager.addOutput(
                CSVReport(
                    requester.host, requester.port, requester.protocol,
                    requester.basePath, self.arguments.csvOutputFile, self.batch
                )
            )

    # TODO: Refactor, this function should be a decorator for all the filters
    def matchCallback(self, path):
        self.index += 1

        if path.status:

            if path.status == 429:
                if self.ignore429:
                    return
                else:
                    self.handle429()

            if path.status not in self.excludeStatusCodes and (
                    not self.includeStatusCodes or path.status in self.includeStatusCodes
            ) and (
                    not self.blacklists.get(path.status) or path.path not in self.blacklists.get(path.status)
            ) and (
                    not self.excludeSizes or FileUtils.size_human(len(path.response.body)).strip() not in self.excludeSizes
            ) and (
                    not self.minimumResponseSize or self.minimumResponseSize < len(path.response.body)
            ) and (
                    not self.maximumResponseSize or self.maximumResponseSize > len(path.response.body)
            ):

                for excludeText in self.excludeTexts:
                    if excludeText in path.response.body.decode('iso8859-1'):
                        del path
                        return

                for excludeRegexp in self.excludeRegexps:
                    if (
                        re.search(excludeRegexp, path.response.body.decode('iso8859-1'))
                        is not None
                    ):
                        del path
                        return

                pathIsInScanSubdirs = False
                addedToQueue = False

                if self.scanSubdirs:
                    for subdir in self.scanSubdirs:
                        if subdir == path.path + "/":
                            pathIsInScanSubdirs = True

                if not self.recursive and not pathIsInScanSubdirs and "?" not in path.path:
                    if path.response.redirect:
                        addedToQueue = self.addRedirectDirectory(path)

                    else:
                        addedToQueue = self.addDirectory(path.path)

                self.output.statusReport(
                    path.path, path.response, self.arguments.full_url, addedToQueue
                )

                if self.arguments.matches_proxy:
                    self.requester.request(path.path, proxy=self.arguments.matches_proxy)

                newPath = "{}{}".format(self.currentDirectory, path.path)

                self.reportManager.addPath(newPath, path.status, path.response)

                self.reportManager.save()

                del path

    def notFoundCallback(self, path):
        self.index += 1
        self.output.lastPath(path, self.index, len(self.dictionary), self.currentJob, self.allJobs)
        del path

    def errorCallback(self, path, errorMsg):
        if self.arguments.exit_on_error:
            self.exit = True
            self.fuzzer.stop()
            self.output.error("\nCanceled due to an error")
            exit(1)

        else:
            if self.arguments.debug:
                self.output.debug(errorMsg)

            self.output.addConnectionError()

    def appendErrorLog(self, path, errorMsg):
        with self.threadsLock:
            line = time.strftime("[%y-%m-%d %H:%M:%S] - ")
            line += self.currentUrl + " - " + path + " - " + errorMsg
            self.errorLog.write(os.linesep + line)
            self.errorLog.flush()

    def handleInterrupt(self):
        self.output.warning("CTRL+C detected: Pausing threads, please wait...")
        self.fuzzer.pause()

    def handle429(self):
        self.output.warning("429 Too Many Requests detected: Server is blocking requests")
        # Assumes you will either accept the 429 codes or exit
        self.got429 = True
        self.fuzzer.pause()

    def handlePause(self):
        while True:
            msg = "[e]xit / [c]ontinue"

            if not self.directories.empty():
                msg += " / [n]ext"

            if self.got429:
                msg += " / [i]gnore"

            if len(self.urlList) > 1:
                msg += " / [s]kip target"

            self.output.inLine(msg + ": ")

            option = input()

            if self.got429:
                self.got429 = False

                if option.lower() == "i":
                    self.ignore429 = True

            if option.lower() == "e":
                self.exit = True
                self.fuzzer.stop()
                self.output.error("\nCanceled by the user")
                exit(0)

            elif option.lower() == "c":
                self.fuzzer.resume()
                return

            elif option.lower() == "n" and not self.directories.empty():
                self.fuzzer.stop()
                return

            elif option.lower() == "s" and len(self.urlList) > 1:
                raise SkipTargetInterrupt

            else:
                continue

    def processPaths(self):
        while True:
            try:
                while not self.fuzzer.wait(0.3):
                    if self.fuzzer.isPaused():
                        self.handlePause()
                    continue
                break
            except (KeyboardInterrupt):
                self.handleInterrupt()

    def wait(self):
        while not self.directories.empty():
            gc.collect()
            self.currentJob += 1
            self.index = 0
            self.currentDirectory = self.directories.get()
            self.output.warning(
                "[{1}] Starting: {0}".format(
                    self.currentDirectory, time.strftime("%H:%M:%S")
                )
            )
            self.fuzzer.requester.basePath = self.basePath + self.currentDirectory
            self.output.basePath = self.basePath + self.currentDirectory
            self.fuzzer.start()
            self.processPaths()

        return

    def addDirectory(self, path):
        if path.endswith("/"):
            if path in [directory + "/" for directory in self.excludeSubdirs]:
                return False

            dir = self.currentDirectory + path

            if dir in self.doneDirs:
                return False

            if self.recursive_level_max and dir.count("/") > self.recursive_level_max:
                return False

            self.directories.put(dir)
            self.allJobs += 1

            self.doneDirs.append(dir)

            return True

        else:
            return False

    def addRedirectDirectory(self, path):
        # Resolve the redirect header relative to the current URL and add the
        # path to self.directories if it is a subdirectory of the current URL

        baseUrl = self.currentUrl.rstrip("/") + "/" + self.currentDirectory

        baseUrl = baseUrl.rstrip("/") + "/"

        absoluteUrl = urllib.parse.urljoin(baseUrl, path.response.redirect)

        if absoluteUrl.startswith(baseUrl) and absoluteUrl != baseUrl and absoluteUrl.endswith("/"):
            dir = absoluteUrl[len(self.currentUrl.rstrip("/")) + 1:]

            if dir in self.doneDirs:
                return False

            if self.recursive_level_max and dir.count("/") > self.recursive_level_max:
                return False

            self.directories.put(dir)
            self.allJobs += 1

            self.doneDirs.append(dir)

            return True

        return False
