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
from lib.core import Dictionary, Fuzzer, Report, ReportManager, Raw
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

        if arguments.raw_file:
            # Overwrite python-requests default headers
            default_headers = {
                "User-Agent": None,
                "Accept-Encoding": None,
                "Accept": None,
            }

            _raw = Raw(arguments.raw_file, arguments.scheme)
            self.urlList = [_raw.url()]
            self.httpmethod = _raw.method()
            self.data = _raw.data()
            self.headers = {**default_headers, **_raw.headers()}
            self.headers["Cookie"] = _raw.cookie()
            self.headers["User-Agent"] = _raw.user_agent()
        else:
            default_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36",
                "Accept-Language": "*",
                "Accept-Encoding": "*",
                "Keep-Alive": "300",
                "Cache-Control": "max-age=0",
            }

            self.urlList = list(filter(None, dict.fromkeys(arguments.urlList)))
            self.httpmethod = arguments.httpmethod.lower()
            self.data = arguments.data
            self.headers = {**default_headers, **arguments.headers}
            self.headers["Cookie"] = arguments.cookie
            self.headers["User-Agent"] = arguments.useragent

        self.recursion_depth = arguments.recursion_depth

        if arguments.saveHome:
            savePath = self.getSavePath()

            if not FileUtils.exists(savePath):
                FileUtils.create_directory(savePath)

            if FileUtils.exists(savePath) and not FileUtils.is_dir(savePath):
                self.output.error(
                    "Cannot use {} because it's a file. Should be a directory".format(
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
        self.includeStatusCodes = arguments.includeStatusCodes
        self.excludeStatusCodes = arguments.excludeStatusCodes
        self.excludeSizes = arguments.excludeSizes
        self.excludeTexts = arguments.excludeTexts
        self.excludeRegexps = arguments.excludeRegexps
        self.excludeRedirects = arguments.excludeRedirects
        self.recursive = arguments.recursive
        self.deep_recursive = arguments.deep_recursive
        self.force_recursive = arguments.force_recursive
        self.recursionStatusCodes = arguments.recursionStatusCodes
        self.minimumResponseSize = arguments.minimumResponseSize
        self.maximumResponseSize = arguments.maximumResponseSize
        self.maxtime = arguments.maxtime
        self.scanSubdirs = arguments.scanSubdirs
        self.excludeSubdirs = (
            arguments.excludeSubdirs if arguments.excludeSubdirs else []
        )

        self.dictionary = Dictionary(
            paths=arguments.wordlist,
            extensions=arguments.extensions,
            suffixes=arguments.suffixes,
            prefixes=arguments.prefixes,
            lowercase=arguments.lowercase,
            uppercase=arguments.uppercase,
            capitalization=arguments.capitalization,
            forcedExtensions=arguments.forceExtensions,
            excludeExtensions=arguments.excludeExtensions,
            noExtension=arguments.noExtension,
            onlySelected=arguments.onlySelected
        )

        self.allJobs = len(self.scanSubdirs) if self.scanSubdirs else 1
        self.currentJob = 0
        self.startTime = time.time()
        self.errorLog = None
        self.errorLogPath = None
        self.threadsLock = Lock()
        self.batch = False
        self.batchSession = None

        self.output.header(program_banner)
        self.printConfig()

        if arguments.autoSave and len(self.urlList) > 1:
            self.setupBatchReports()
            self.output.newLine("AutoSave path: {0}\n".format(self.batchDirectoryPath))

        if arguments.useRandomAgents:
            self.randomAgents = FileUtils.get_lines(
                FileUtils.build_path(script_path, "db", "user-agents.txt")
            )

        self.setupReports()
        self.setupErrorLogs()
        self.output.errorLogFile(self.errorLogPath)
        try:
            for url in self.urlList:
                try:
                    gc.collect()
                    self.currentUrl = url if url.endswith("/") else url + "/"
                    self.output.setTarget(self.currentUrl, self.arguments.scheme)

                    try:
                        self.requester = Requester(
                            url,
                            maxPool=arguments.threadsCount,
                            maxRetries=arguments.maxRetries,
                            timeout=arguments.timeout,
                            ip=arguments.ip,
                            proxy=arguments.proxy,
                            proxylist=arguments.proxylist,
                            redirect=arguments.redirect,
                            requestByHostname=arguments.requestByHostname,
                            httpmethod=self.httpmethod,
                            data=self.data,
                            scheme=arguments.scheme,
                        )

                        for key, value in self.headers.items():
                            self.requester.setHeader(key, value)

                        self.requester.request("")
                        self.report = Report(self.requester.host, self.requester.port, self.requester.protocol, self.requester.basePath)

                    except RequestException as e:
                        self.output.error(e.args[0]["message"])
                        raise SkipTargetInterrupt

                    if arguments.useRandomAgents:
                        self.requester.setRandomAgents(self.randomAgents)

                    # Initialize directories Queue with start Path
                    self.basePath = self.requester.basePath
                    self.status_skip = None

                    if self.scanSubdirs:
                        for subdir in self.scanSubdirs:
                            self.directories.put(subdir)

                    else:
                        self.directories.put("")

                    matchCallbacks = [self.matchCallback]
                    notFoundCallbacks = [self.notFoundCallback]
                    errorCallbacks = [self.errorCallback, self.appendErrorLog]

                    self.fuzzer = Fuzzer(
                        self.requester,
                        self.dictionary,
                        suffixes=arguments.suffixes,
                        prefixes=arguments.prefixes,
                        excludeContent=arguments.excludeContent,
                        threads=arguments.threadsCount,
                        delay=arguments.delay,
                        maxrate=arguments.maxrate,
                        matchCallbacks=matchCallbacks,
                        notFoundCallbacks=notFoundCallbacks,
                        errorCallbacks=errorCallbacks,
                    )
                    try:
                        self.prepare()
                    except RequestException as e:
                        self.output.error(e.args[0]["message"])
                        raise SkipTargetInterrupt

                except SkipTargetInterrupt:
                    self.report.completed = True
                    continue

        except KeyboardInterrupt:
            self.output.error("\nCanceled by the user")
            exit(0)

        finally:
            if not self.errorLog.closed:
                self.errorLog.close()

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

        try:
            self.errorLog = open(self.errorLogPath, "w")
        except PermissionError:
            self.output.error(
                "Couldn't create the error log. Try running again with highest permission"
            )
            sys.exit(1)

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
                    "Couldn't create batch folder at {}".format(self.batchDirectoryPath)
                )
                sys.exit(1)

        if FileUtils.can_write(self.batchDirectoryPath):
            FileUtils.create_directory(self.batchDirectoryPath)
            targetsFile = FileUtils.build_path(self.batchDirectoryPath, "TARGETS.txt")
            FileUtils.write_lines(targetsFile, self.urlList)

        else:
            self.output.error(
                "Couldn't create batch folder at {}".format(self.batchDirectoryPath)
            )
            sys.exit(1)

    def getOutputExtension(self):
        if self.arguments.outputFormat:
            if self.arguments.outputFormat == 'plain' or self.arguments.outputFormat == 'simple':
                return ".txt"
            else:
                return ".{0}".format(self.arguments.outputFormat)
        elif self.arguments.autoSaveFormat:
            if self.arguments.autoSaveFormat == 'plain' or self.arguments.autoSaveFormat == 'simple':
                return ".txt"
            else:
                return ".{0}".format(self.arguments.autoSaveFormat)
        else:
            return ".txt"

    def setupReports(self):
        if self.arguments.outputFile is not None:
            outputFile = FileUtils.get_abs_path(self.arguments.outputFile)
            self.output.outputFile(outputFile)
        else:
            if self.batch:
                fileName = "BATCH"
                fileName += self.getOutputExtension()
                directoryPath = self.batchDirectoryPath
            else:
                localRequester = Requester(self.urlList[0])
                fileName = ('{}_'.format(localRequester.basePath.replace(os.path.sep, ".")[:-1]))
                fileName += time.strftime('%y-%m-%d_%H-%M-%S')
                fileName += self.getOutputExtension()
                directoryPath = FileUtils.build_path(self.savePath, 'reports', localRequester.host)

            outputFile = FileUtils.build_path(directoryPath, fileName)

            if FileUtils.exists(outputFile):
                i = 2

                while FileUtils.exists(outputFile + "_" + str(i)):
                    i += 1

                outputFile += "_" + str(i)

            if not FileUtils.exists(directoryPath):
                FileUtils.create_directory(directoryPath)

                if not FileUtils.exists(directoryPath):
                    self.output.error(
                        "Couldn't create the reports folder at {}".format(directoryPath)
                    )
                    sys.exit(1)

            self.output.outputFile(outputFile)

        if self.arguments.outputFile and self.arguments.outputFormat:
            self.reportManager = ReportManager(self.arguments.outputFormat, self.arguments.outputFile)
        elif self.arguments.outputFormat:
            self.reportManager = ReportManager(self.arguments.outputFormat, outputFile)
        else:
            if self.arguments.autoSaveFormat:
                self.reportManager = ReportManager(self.arguments.autoSaveFormat, outputFile)
            else:
                self.reportManager = ReportManager("plain", outputFile)

    # TODO: Refactor, this function should be a decorator for all the filters
    def matchCallback(self, path):
        self.index += 1

        for status in self.arguments.skip_on_status:
            if path.status == status:
                self.status_skip = status
                return

        if (
                path.status and path.status not in self.excludeStatusCodes
        ) and (
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

            for excludeRedirect in self.excludeRedirects:
                if path.response.redirect and (
                    (
                        re.match(excludeRedirect, path.response.redirect.decode('iso8859-1'))
                        is not None
                    ) or (
                        excludeRedirect in path.response.redirect
                    )
                ):
                    del path
                    return

            addedToQueue = False

            if (
                    any([self.recursive, self.deep_recursive, self.force_recursive])
            ) and (
                    not self.recursionStatusCodes or path.status in self.recursionStatusCodes
            ):
                if path.response.redirect:
                    addedToQueue = self.addRedirectDirectory(path)
                else:
                    addedToQueue = self.addDirectory(path.path)

            self.output.statusReport(
                path.path, path.response, self.arguments.full_url, addedToQueue
            )

            if self.arguments.replay_proxy:
                self.requester.request(path.path, proxy=self.arguments.replay_proxy)

            newPath = self.currentDirectory + path.path

            self.report.addResult(newPath, path.status, path.response)
            self.reportManager.updateReport(self.report)

            del path

    def notFoundCallback(self, path):
        self.index += 1
        self.output.lastPath(path, self.index, len(self.dictionary), self.currentJob, self.allJobs, self.fuzzer.rate)
        del path

    def errorCallback(self, path, errorMsg):
        if self.arguments.exit_on_error:
            self.exit = True
            self.fuzzer.stop()
            self.output.error("\nCanceled due to an error")
            exit(1)

        else:
            self.output.addConnectionError()

    def appendErrorLog(self, path, errorMsg):
        with self.threadsLock:
            line = time.strftime("[%y-%m-%d %H:%M:%S] - ")
            line += self.currentUrl + " - " + path + " - " + errorMsg
            self.errorLog.write(os.linesep + line)
            self.errorLog.flush()

    def handlePause(self, message):
        self.output.warning(message)
        self.fuzzer.pause()

        # If one of the tasks is broken, don't let the user wait forever
        for i in range(300):
            if self.fuzzer.stopped == len(self.fuzzer.threads):
                break
            time.sleep(0.025)

        self.fuzzer.stopped = 0

        while True:
            msg = "[e]xit / [c]ontinue"

            if not self.directories.empty():
                msg += " / [n]ext"

            if len(self.urlList) > 1:
                msg += " / [s]kip target"

            self.output.inLine(msg + ": ")

            option = input()

            if option.lower() == "e":
                self.exit = True
                self.fuzzer.stop()
                self.output.error("\nCanceled by the user")
                self.reportManager.updateReport(self.report)
                exit(0)

            elif option.lower() == "c":
                self.fuzzer.resume()
                return

            elif option.lower() == "n" and not self.directories.empty():
                self.fuzzer.stop()
                return

            elif option.lower() == "s" and len(self.urlList) > 1:
                self.output.newLine()
                raise SkipTargetInterrupt

            else:
                continue

    def processPaths(self):
        while True:
            try:
                while not self.fuzzer.wait(0.25):
                    # Check if the "skip status code" was returned
                    if self.status_skip:
                        self.fuzzer.pause()
                        while self.fuzzer.stopped != len(self.fuzzer.threads):
                            pass

                        self.output.error(
                            "\nSkipped the target due to {0} status code".format(self.status_skip)
                        )

                        raise SkipTargetInterrupt

                    elif self.maxtime and time.time() - self.startTime > self.maxtime:
                        self.output.error(
                            "\nCanceled because the runtime exceeded the maximal set by user"
                        )
                        exit(0)

                break

            except (KeyboardInterrupt):
                self.handlePause("CTRL+C detected: Pausing threads, please wait...")

    def prepare(self):
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
            self.fuzzer.requester.basePath = self.output.basePath = self.basePath + self.currentDirectory
            self.fuzzer.start()
            self.processPaths()

        self.report.completed = True
        self.reportManager.updateReport(self.report)
        self.report = None

        return

    def addPort(self, url):
        parsed = urllib.parse.urlparse(url)
        if ":" not in parsed.netloc:
            port = "443" if parsed.scheme == "https" else "80"
            url = url.replace(parsed.netloc, parsed.netloc + ":" + port)

        return url

    def addDirectory(self, path, fullPath=None):
        added = False
        path = path.split("?")[0].split("#")[0]

        if path.rstrip("/") in [directory for directory in self.excludeSubdirs]:
            return False

        fullPath = self.currentDirectory + path if not fullPath else fullPath

        dirs = []

        if self.deep_recursive:
            for i in range(1, path.count("/") + 1):
                dir = fullPath.replace(path, "") + "/".join(path.split("/")[:i])
                dirs.append(dir.rstrip("/") + "/")
        if self.force_recursive:
            if not fullPath.endswith("/"):
                fullPath += "/"
            dirs.append(fullPath)
        elif self.recursive and fullPath.endswith("/"):
            dirs.append(fullPath)

        for dir in dirs:
            if self.scanSubdirs and dir in self.scanSubdirs:
                continue
            elif dir in self.doneDirs:
                continue
            elif self.recursion_depth and dir.count("/") > self.recursion_depth:
                continue

            self.directories.put(dir)
            self.doneDirs.append(dir)

            self.allJobs += 1
            added = True

        return added

    def addRedirectDirectory(self, path):
        # Resolve the redirect header relative to the current URL and add the
        # path to self.directories if it is a subdirectory of the current URL

        baseUrl = self.currentUrl + self.currentDirectory
        baseUrl = self.addPort(baseUrl)

        absoluteUrl = urllib.parse.urljoin(baseUrl, path.response.redirect)
        absoluteUrl = self.addPort(absoluteUrl)

        if absoluteUrl.startswith(baseUrl) and absoluteUrl != baseUrl:
            path = absoluteUrl[len(baseUrl):]
            fullPath = absoluteUrl[len(self.addPort(self.currentUrl)):]

            return self.addDirectory(path, fullPath)

        return False
