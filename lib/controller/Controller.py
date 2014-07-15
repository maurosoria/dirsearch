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
import sys
from lib.utils import *
from lib.core import *
from lib.reports import *
from lib.utils import *
import time


class Controller(object):

    def __init__(self, script_path, arguments, output):
        self.script_path = script_path
        self.exit = False
        self.arguments = arguments
        self.output = output
        self.blacklists = self.getBlacklists()
        self.fuzzer = None
        self.recursive = self.arguments.recursive
        self.excludeStatusCodes = self.arguments.excludeStatusCodes
        self.recursive = self.arguments.recursive
        self.directories = Queue()
        try:
            self.requester = Requester(self.arguments.url, cookie=self.arguments.cookie, useragent=self.arguments.useragent,
                                  maxPool=self.arguments.threadsCount, maxRetries=self.arguments.maxRetries,
                                  timeout=self.arguments.timeout, ip=self.arguments.ip, proxy=self.arguments.proxy,
                                  redirect=self.arguments.redirect)
            # Initialize directories Queue with start Path
            self.basePath = self.requester.basePath
            self.directories.put("")
            self.reportManager = ReportManager()
            self.setupReports(self.requester)
            self.dictionary = FuzzerDictionary(self.arguments.wordlist, self.arguments.extensions,
                                               self.arguments.lowercase)
            self.printConfig()
            self.fuzzer = Fuzzer(self.requester, self.dictionary, threads=self.arguments.threadsCount)
            #self.fuzzer.start()
            self.wait()
        except RequestException, e:
            self.output.printError('Unexpected error:\n{0}'.format(e.args[0]['message']))
            exit(0)
        except KeyboardInterrupt, SystemExit:
            self.output.printError('\nCanceled by the user')
            exit(0)
        finally:
            self.reportManager.save()
            self.reportManager.close()
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

    def handleInterrupt(self):
        self.output.printWarning('CTRL+C detected: Pausing threads...')
        self.fuzzer.pause()
        try:
            while True:
                if self.recursive and not self.directories.empty():
                    self.output.printInLine('[e]xit / [c]ontinue / [n]ext: ')
                    pass
                else:
                    self.output.printInLine('[e]xit / [c]ontinue: ')
                    pass
                option = raw_input()
                if option.lower() == 'e':
                    self.exit = True
                    self.fuzzer.stop()
                    raise KeyboardInterrupt
                elif option.lower() == 'c':
                    self.fuzzer.play()
                    return
                elif self.recursive and not self.directories.empty() and option.lower() == 'n':
                    self.fuzzer.stop()
                    return
                else:
                    continue
        except KeyboardInterrupt, SystemExit:
            self.exit = True
            raise KeyboardInterrupt

    def processPaths(self):
        try:
            while self.fuzzer.isRunning():
                try:
                    path = self.fuzzer.getPath()
                    if path.status is not 0:
                        if path.status not in self.excludeStatusCodes and (self.blacklists.get(path.status) is None or path.path
                                not in self.blacklists.get(path.status)):
                            self.output.printStatusReport(path.path, path.response)
                            self.addDirectory(path.path)
                            self.reportManager.addPath(path.status, self.currentDirectory + path.path)
                    self.index += 1
                    self.output.printLastPathEntry(path, self.index, len(self.dictionary))
                except (KeyboardInterrupt, SystemExit), e:
                    self.handleInterrupt()
                    if self.exit: raise e 
                    else: pass
        except (KeyboardInterrupt, SystemExit), e:
            if self.exit: raise e
            self.handleInterrupt()
            if self.exit: raise e 
            else: pass
        self.fuzzer.wait()

    def wait(self):
        #self.waitThreads()
        while not self.directories.empty():
            self.index = 0
            self.currentDirectory = self.directories.get()
            self.output.printWarning('\nScanning in directory: {0}'.format(self.currentDirectory))
            self.fuzzer.requester.basePath = '{0}{1}'.format(self.basePath, self.currentDirectory)
            self.output.basePath = '{0}{1}'.format(self.basePath, self.currentDirectory)
            #self.testersSetup()
            #self.threadsSetup()
            self.fuzzer.start()
            self.processPaths()
        return

    def addDirectory(self, path):
        if self.recursive == False:
            return False
        if path.endswith('/'):
            if self.currentDirectory == "":
                self.directories.put(path)
            else:
                self.directories.put('{0}{1}'.format(self.currentDirectory, path))

            return True
        else:
            return False