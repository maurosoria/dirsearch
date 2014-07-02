# -*- coding: utf-8 -*-
import os
import sys
from lib.core import *
from lib.reports import *
from lib.utils import *
import time


class Controller(object):

    def __init__(self, script_path, arguments, output):
        self.script_path = script_path
        self.arguments = arguments
        self.output = output
        self.blacklists = self.getBlacklists()
        try:
            requester = Requester(self.arguments.url, cookie=self.arguments.cookie, useragent=self.arguments.useragent,
                                  maxPool=self.arguments.threadsCount, maxRetries=self.arguments.maxRetries,
                                  timeout=self.arguments.timeout, ip=self.arguments.ip, proxy=self.arguments.proxy,
                                  redirect=self.arguments.redirect)
            self.reportManager = ReportManager()
            self.setupReports(requester)
            self.dictionary = FuzzerDictionary(self.arguments.wordlist, self.arguments.extensions,
                                               self.arguments.lowercase)
            self.printConfig()
            fuzzer = Fuzzer(requester, self.dictionary, output, threads=self.arguments.threadsCount,
                            recursive=self.arguments.recursive, reportManager=self.reportManager,
                            blacklists=self.blacklists, excludeInternalServerError=self.arguments.exclude500)
            fuzzer.start()
            fuzzer.wait()
        except RequestException, e:
            self.output.printError('Unexpected error:\n{0}'.format(e.args[0]['message']))
            exit(0)
        except KeyboardInterrupt, SystemExit:
            self.output.printError('\nCanceled by the user')
            exit(0)
        self.output.printWarning('\nTask Completed')

    def printConfig(self):
        self.output.printWarning('- Searching in: {0}'.format(self.arguments.url))
        self.output.printWarning('- For extensions: {0}'.format(', '.join(self.arguments.extensions)))
        self.output.printWarning('- Number of Threads: {0}'.format(self.arguments.threadsCount))
        self.output.printWarning('- Wordlist size: {0}'.format(len(self.dictionary)))
        self.output.printWarning('\n')

    def getBlacklists(self):
        blacklists = {}
        for status in [400, 403]:
            blacklistFileName = '%s/db/%d_blacklist.txt' % (self.script_path, status)
            if not FileUtils.canRead(blacklistFileName):
                continue
            blacklists[status] = []
            for line in FileUtils.getLines(blacklistFileName):
                blacklists[status].append(line)
        return blacklists

    def setupReports(self, requester):
        if self.arguments.outputFile is not None:
            self.reportManager.addOutput(ListReport(requester.host, requester.port, requester.protocol,
                                         requester.basePath, self.arguments.outputFile))
        if self.arguments.jsonOutputFile is not None:
            self.reportManager.addOutput(JSONReport(requester.host, requester.port, requester.protocol,
                                         requester.basePath, self.arguments.jsonOutputFile))


