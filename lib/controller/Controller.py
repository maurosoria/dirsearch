import os
import sys
from lib.core import *
from lib.reports import *

class Controller(object):
    def __init__(self, script_path, arguments, output):
        self.script_path = script_path
        self.arguments = arguments
        self.output = output
        try:
            with open("%s/db/403_blacklist.txt" % (self.script_path)): pass
            output.setStatusBlacklist(403, "%s/db/403_blacklist.txt" % (self.script_path))
        except IOError:
            pass
        output.printWarning("- Searching in: {0}".format(self.arguments.url))
        output.printWarning("- For extensions: {0}".format(', '.join(self.arguments.extensions)))
        output.printWarning("- Number of Threads: {0}\n".format(self.arguments.threadsCount))
        try:
            requester = Requester(self.arguments.url, cookie = self.arguments.cookie, useragent = self.arguments.useragent, maxPool = self.arguments.threadsCount, maxRetries = self.arguments.maxRetries, timeout = self.arguments.timeout, ip = self.arguments.ip)

            reportManager = ReportManager()
            if self.arguments.outputFile is not None:
                reportManager.addOutput(ListReport(requester.host, requester.port, requester.protocol, requester.basePath, self.arguments.outputFile))
            if self.arguments.jsonOutputFile is not None:
                reportManager.addOutput(JSONReport(requester.host, requester.port, requester.protocol, requester.basePath, self.arguments.jsonOutputFile))
            dictionary = FuzzerDictionary(self.arguments.wordlist, self.arguments.extensions, self.arguments.lowercase)
            fuzzer = Fuzzer(requester, dictionary, output, threads = self.arguments.threadsCount, \
                recursive = self.arguments.recursive, reportManager= reportManager, excludeInternalServerError = self.arguments.exclude500)
            fuzzer.start()
            fuzzer.wait()
        except RequestException as e:
            output.printError("Unexpected error:\n{0}".format(e.args[0]['message']))
            exit(0)
        except KeyboardInterrupt:
            output.printError("\nCanceled by the user")
            exit(0)
        output.printWarning("\nTask Completed")