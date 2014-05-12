import os
import sys
from lib.core import *
from lib.reports import *

class Controller(object):
    def __init__(self, script_path, arguments, output):
        self.script_path = script_path
        self.arguments = arguments
        self.output = output
        self.setupBlacklist()
        self.printConfig()

        try:
            requester = Requester(self.arguments.url, cookie = self.arguments.cookie, useragent = self.arguments.useragent, maxPool = self.arguments.threadsCount, maxRetries = self.arguments.maxRetries, timeout = self.arguments.timeout, ip = self.arguments.ip)
            self.reportManager = ReportManager()
            self.setupReports(requester)
            dictionary = FuzzerDictionary(self.arguments.wordlist, self.arguments.extensions, self.arguments.lowercase)
            fuzzer = Fuzzer(requester, dictionary, output, threads = self.arguments.threadsCount, \
                recursive = self.arguments.recursive, reportManager= self.reportManager, excludeInternalServerError = self.arguments.exclude500)
            fuzzer.start()
            fuzzer.wait()
        except RequestException as e:
            self.output.printError("Unexpected error:\n{0}".format(e.args[0]['message']))
            exit(0)
        except KeyboardInterrupt:
            self.output.printError("\nCanceled by the user")
            exit(0)
        self.output.printWarning("\nTask Completed")


    def printConfig(self):
        self.output.printWarning("- Searching in: {0}".format(self.arguments.url))
        self.output.printWarning("- For extensions: {0}".format(', '.join(self.arguments.extensions)))
        self.output.printWarning("- Number of Threads: {0}\n".format(self.arguments.threadsCount))


    def setupBlacklist(self):
        try:
            with open("%s/db/403_blacklist.txt" % (self.script_path)): pass
            self.output.setStatusBlacklist(403, "%s/db/403_blacklist.txt" % (self.script_path))
        except IOError:
            pass


    def setupReports(self, requester):
        if self.arguments.outputFile is not None:
            self.reportManager.addOutput(ListReport(requester.host, requester.port, requester.protocol, requester.basePath, self.arguments.outputFile))
        if self.arguments.jsonOutputFile is not None:
            self.reportManager.addOutput(JSONReport(requester.host, requester.port, requester.protocol, requester.basePath, self.arguments.jsonOutputFile))