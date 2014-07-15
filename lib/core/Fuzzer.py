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
from config import *
from .Path import *
from lib.connection import *
from FuzzerDictionary import *
from NotFoundTester import *
from ReportManager import *
from lib.reports import *
import threading
import time


class Fuzzer(object):

    def __init__(self, requester, dictionary, threads=1, recursive=True, reportManager=None, blacklists={},
                 excludeStatusCodes=[]):
        self.requester = requester
        self.dictionary = dictionary
        self.testedPaths = Queue()
        self.blacklists = blacklists
        self.basePath = self.requester.basePath
        #self.output = output
        self.threads = []
        self.threadsCount = threads
        self.running = False
        self.testers = {}
        self.recursive = recursive
        #self.reportManager = (ReportManager() if reportManager is None else reportManager)

    def wait(self):
        for thread in self.threads:
            thread.join()

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
        # Setting up testers
        self.testersSetup()
        # Setting up threads
        self.threadsSetup()
        self.index = 0
        self.dictionary.reset()
        self.runningThreadsCount = len(self.threads)
        self.running = True
        self.finishedEvent = threading.Event()
        self.finishedThreadCondition = threading.Condition()
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
                #print("Pausing " + str(thread.getName()))
                self.pausedSemaphore.acquire()
        #print("FINISHED PAUSE\n")

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
        return self.testedPaths.get()

    def thread_proc(self):
        self.playEvent.wait()
        try:
            path = self.dictionary.next()
            while path is not None:
                try:
                    status, response = self.testPath(path)
                    #if status is not 0:
                        #if status not in self.excludeStatusCodes and (self.blacklists.get(status) is None or path
                        #        not in self.blacklists.get(status)):
                        #    
                        #    self.output.printStatusReport(path, response)
                        #    self.addDirectory(path)
                        #    self.reportManager.addPath(status, self.currentDirectory + path)
                    #print ("Attemping to " + str(threading.currentThread().getName()) + " Added path")
                    #sys.stdout.flush()
                    self.testedPaths.put(Path(path=path, status=status, response=response))
                    #print (str(threading.currentThread().getName()) + " Added path")
                    #sys.stdout.flush()
                    path = self.dictionary.next()
                    if not self.playEvent.isSet():
                        #print (str(threading.currentThread().getName()) + " caught pause")
                        #sys.stdout.flush()
                        self.pausedSemaphore.release()
                        self.playEvent.wait()
                    if not self.running:
                        break
                    if path is None:
                        self.running = False
                        self.finishThreads()
                except RequestException, e:
                    # self.output.printError('Unexpected error:\n{0}'.format(e.args[0]['message']))
                    continue
        except KeyboardInterrupt, SystemExit:
            pass


