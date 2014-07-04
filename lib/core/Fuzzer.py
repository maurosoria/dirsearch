# -*- coding: utf-8 -*-
import threading
import logging
import signal
from Queue import Queue
from config import *
from lib.connection import *
from FuzzerDictionary import *
from NotFoundTester import *
from ReportManager import *
from lib.reports import *
import threading
import time


class Fuzzer(object):

    def __init__(self, requester, dictionary, output, threads=1, recursive=True, reportManager=None, blacklists={},
                 excludeStatusCodes=[]):
        self.requester = requester
        self.dictionary = dictionary
        self.blacklists = blacklists
        self.basePath = self.requester.basePath
        self.output = output
        self.excludeStatusCodes = excludeStatusCodes
        self.threads = []
        self.threadsCount = threads
        self.running = False
        self.directories = Queue()
        self.testers = {}
        self.recursive = recursive
        self.currentDirectory = ''
        self.indexMutex = threading.Lock()
        self.index = 0
        # Setting up testers
        self.testersSetup()
        # Setting up threads
        self.threadsSetup()
        self.reportManager = (ReportManager() if reportManager is None else reportManager)

    def testersSetup(self):
        if len(self.testers) != 0:
            self.testers = {}
        self.testers['/'] = NotFoundTester(self.requester, '{0}/'.format(NOT_FOUND_PATH))
        for extension in self.dictionary.extensions:
            self.testers[extension] = NotFoundTester(self.requester, '{0}.{1}'.format(NOT_FOUND_PATH, extension))

    def threadsSetup(self):
        if len(self.threads) != 0:
            self.threads = []
        for thread in range(self.threadsCount):
            newThread = threading.Thread(target=self.thread_proc)
            newThread.daemon = True
            self.threads.append(newThread)

    def getTester(self, path):
        for extension in self.testers.keys():
            if path.endswith(extension):
                return self.testers[extension]
        # By default, returns folder tester
        return self.testers['/']

    def start(self):
        self.index = 0
        self.dictionary.reset()
        self.runningThreadsCount = len(self.threads)
        self.running = True
        self.finishedEvent = threading.Event()
        self.finishedThreadCondition = threading.Condition()
        self.playEvent = threading.Event()
        self.pausedSemaphore = threading.Semaphore(0)
        self.playEvent.set()
        for thread in self.threads:
            thread.start()

    def play(self):
        self.playEvent.set()

    def pause(self):
        self.playEvent.clear()
        for thread in self.threads:
            if thread.is_alive():
                self.pausedSemaphore.acquire()

    def handleInterrupt(self):
        self.output.printWarning('CTRL+C detected: Pausing threads...')
        self.pause()
        try:
            while True:
                if self.recursive and not self.directories.empty():
                    self.output.printInLine('[e]xit / [c]ontinue / [n]ext: ')
                else:
                    self.output.printInLine('[e]xit / [c]ontinue: ')
                option = raw_input()
                if option.lower() == 'e':
                    self.running = False
                    self.exit = True
                    self.play()
                    raise KeyboardInterrupt
                elif option.lower() == 'c':
                    self.play()
                    return
                elif self.recursive and not self.directories.empty() and option.lower() == 'n':
                    self.running = False
                    self.play()
                    return
                else:
                    continue
        except KeyboardInterrupt, SystemExit:
            self.exit = True
            raise KeyboardInterrupt

    def waitThreads(self):
        try:
            while self.running:
                try:
                    self.finishedEvent.wait(0.3)
                except (KeyboardInterrupt, SystemExit), e:
                    self.handleInterrupt()
                    if self.exit:
                        raise e
                    else:
                        pass
        except (KeyboardInterrupt, SystemExit), e:
            if self.exit:
                raise e
            self.handleInterrupt()
            if self.exit:
                raise e
            else:
                pass
        for thread in self.threads:
            thread.join()

    def wait(self):
        self.exit = False
        self.waitThreads()
        while not self.directories.empty():
            self.currentDirectory = self.directories.get()
            self.output.printWarning('\nSwitching to founded directory: {0}'.format(self.currentDirectory))
            self.requester.basePath = '{0}{1}'.format(self.basePath, self.currentDirectory)
            self.output.basePath = '{0}{1}'.format(self.basePath, self.currentDirectory)
            self.testersSetup()
            self.threadsSetup()
            self.start()
            self.waitThreads()
        self.reportManager.save()
        self.reportManager.close()
        return

    def testPath(self, path):
        response = self.requester.request(path)
        result = 0
        if self.getTester(path).test(response):
            result = (0 if response.status == 404 else response.status)
        return result, response

    def addDirectory(self, path):
        if self.recursive == False:
            return False
        if path.endswith('/'):
            if self.currentDirectory == '':
                self.directories.put(path)
            else:
                self.directories.put('{0}{1}'.format(self.currentDirectory, path))
            return True
        else:
            return False

    def finishThreads(self):
        self.running = False
        self.finishedEvent.set()

    def thread_proc(self):
        try:
            path = self.dictionary.next()
            while path is not None:
                try:
                    status, response = self.testPath(path)
                    if status is not 0:
                        if status not in self.excludeStatusCodes and (self.blacklists.get(status) is None or path
                                not in self.blacklists.get(status)):
                            self.output.printStatusReport(path, response)
                            self.addDirectory(path)
                            self.reportManager.addPath(status, self.currentDirectory + path)
                    self.indexMutex.acquire()
                    self.index += 1
                    self.output.printLastPathEntry(path, self.index, len(self.dictionary))
                    self.indexMutex.release()
                    path = self.dictionary.next()
                    if not self.playEvent.isSet():
                        self.pausedSemaphore.release()
                        self.playEvent.wait()
                    if not self.running:
                        break
                    if path is None:
                        self.running = False
                        self.finishThreads()
                except RequestException, e:
                    self.output.printError('Unexpected error:\n{0}'.format(e.args[0]['message']))
                    continue
        except KeyboardInterrupt, SystemExit:
            if self.exit:
                raise e
            self.handleInterrupt()
            if self.exit:
                raise e
            pass


