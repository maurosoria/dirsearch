# -*- coding: utf-8 -*-
import threading
import time
import sys


class Output(object):

    HEADER = '\033[95m'
    HEADERBOLD = '\033[1;95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    OKBLUEBOLD = '\033[1;94m'
    OKGREENBOLD = '\033[1;92m'
    WARNING = '\033[93m'
    WARNINGBOLD = '\033[1;93m'
    FAIL = '\033[91m'
    FAILBOLD = '\033[1;91m'
    ENDC = '\033[0;0m'

    def __init__(self):
        self.lastLength = 0
        self.lastOutput = ''
        self.lastInLine = False
        self.mutex = threading.Lock()
        self.checkedPaths = []
        self.blacklists = {}
        self.mutexCheckedPaths = threading.Lock()
        self.basePath = None

    def setStatusBlacklist(self, status, file):
        blacklistFile = open(file, 'r')

        # Test if blacklists exists, if not, initializes
        try:
            test = self.blacklists[status]
        except KeyError:
            self.blacklists[status] = []
        for line in blacklistFile:
            self.blacklists[status].append(line.replace('\n', ''))

    def printInLine(self, string):
        self.mutex.acquire()
        sys.stdout.write('\033[1K')
        sys.stdout.write('\033[0G')
        sys.stdout.write(string)
        sys.stdout.flush()
        self.lastInLine = True
        self.mutex.release()

    def printNewLine(self, string):
        self.mutex.acquire()
        if self.lastInLine == True:
            sys.stdout.write('\033[1K')
            sys.stdout.write('\033[0G')
        sys.stdout.write(string + '\n')
        sys.stdout.flush()
        self.lastInLine = False
        self.mutex.release()

    def printStatusReport(self, path, response):
        status = response.status
        try:
            if path in self.blacklists[status]:
                return
        except KeyError:
            pass
        message = '[{0}]  {1}: {2}'.format(time.strftime('%H:%M:%S'), status, ('/{0}'.format(path) if self.basePath
                                           == None else '{0}{1}'.format(self.basePath, path)))
        if status in [301, 302, 307]:
            try:
                message += '  ->  {0}'.format(response.headers['location'])
            except KeyError:
                pass
        self.mutexCheckedPaths.acquire()
        if path in self.checkedPaths:
            self.mutexCheckedPaths.release()
            return
        if status == 200:
            message = self.OKGREENBOLD + message + self.ENDC
        elif status == 403:
            message = self.OKBLUEBOLD + message + self.ENDC
        self.printNewLine(message)
        self.mutexCheckedPaths.release()

    def printLastPathEntry(self, path, index, length):
        percentage = lambda x, y: float(x) / float(y) * 100
        message = '{1:.2f}% - Last request to: {0}'.format(path, percentage(index, length))
        self.printInLine(message)

    def printError(self, reason):
        message = self.FAILBOLD + reason + self.ENDC
        self.printNewLine(message)

    def printWarning(self, reason):
        message = self.WARNINGBOLD + reason + self.ENDC
        self.printNewLine(message)

    def printHeader(self, text):
        message = self.HEADERBOLD + text + self.ENDC
        self.printNewLine(message)


