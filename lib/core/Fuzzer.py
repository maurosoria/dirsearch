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
import logging
import sys
import signal
from lib.utils.Queue import Queue
from .Path import *
from lib.connection import *
from .FuzzerDictionary import *
from .NotFoundTester import *
from .ReportManager import *
from lib.reports import *
import threading
import time


class Fuzzer(object):

    def __init__(self, requester, dictionary, testFailPath="youCannotBeHere7331", threads=1):
        self.requester = requester
        self.dictionary = dictionary
        self.testFailPath = testFailPath
        self.testedPaths = Queue()
        self.basePath = self.requester.basePath
        self.threads = []    
        self.threadsCount = threads if len(self.dictionary) >= threads else len(self.dictionary)
        self.running = False
        self.testers = {}

    def wait(self):
        for thread in self.threads:
            thread.join()

    def testersSetup(self):
        if len(self.testers) != 0:
            self.testers = {}
        self.testers['/'] = NotFoundTester(self.requester, '{0}/'.format(self.testFailPath))
        for extension in self.dictionary.extensions:
            self.testers[extension] = NotFoundTester(self.requester, '{0}.{1}'.format(self.testFailPath, extension))

    def threadsSetup(self):
        if len(self.threads) != 0:
            self.threads = []
        for thread in range(self.threadsCount):
            newThread = threading.Thread(target=self.thread_proc)
            newThread.daemon = True
            self.threads.append(newThread)

    def getTester(self, path):
        for extension in list(self.testers.keys()):
            if path.endswith(extension):
                return self.testers[extension]
        # By default, returns folder tester
        return self.testers['/']

    def start(self):
        # Setting up testers
        self.testersSetup()
        # Setting up threads
        self.threadsSetup()
        self.index = 0
        self.dictionary.reset()
        self.runningThreadsCount = len(self.threads)
        self.running = True
        self.playEvent = threading.Event()
        self.pausedSemaphore = threading.Semaphore(0)
        self.playEvent.clear()
        self.exit = False
        for thread in self.threads:
            thread.start()
        self.play()

    def play(self):
        self.playEvent.set()

    def pause(self):
        self.playEvent.clear()
        for thread in self.threads:
            if thread.is_alive():
                self.pausedSemaphore.acquire()

    def stop(self):
        self.running = False
        self.play()

    def testPath(self, path):
        response = self.requester.request(path)
        result = 0
        if self.getTester(path).test(response):
            result = (0 if response.status == 404 else response.status)
        return result, response

    def isRunning(self):
        return self.running

    def finishThreads(self):
        self.running = False
        self.finishedEvent.set()

    def getPath(self):
        path = None
        if not self.empty():
            path = self.testedPaths.get()  
        if not self.isFinished():
            path = self.testedPaths.get()  
        return path

    def qsize(self):
        return self.testedPaths.qsize()

    def empty(self):
        return self.testedPaths.empty()

    def isFinished(self):
        return self.runningThreadsCount == 0

    def thread_proc(self):
        self.playEvent.wait()
        path = next(self.dictionary)
        while path is not None:
            try:
                status, response = self.testPath(path)
                self.testedPaths.put(Path(path=path, status=status, response=response))
            except RequestException as e:
                print('\nUnexpected error:\n{0}\n'.format(e.args[0]['message']))
                sys.stdout.flush()
                continue
            finally:
                
                if not self.playEvent.isSet():
                    self.pausedSemaphore.release()
                    self.playEvent.wait()

                path = next(self.dictionary)

                if not self.running or path is None:
                    self.runningThreadsCount -= 1
                    if self.runningThreadsCount is 0:
                        self.testedPaths.put(None)
                    break



