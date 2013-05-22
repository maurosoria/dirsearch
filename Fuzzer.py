import threading
import logging
from Request import *
from FuzzerDictionary import *

class Fuzzer:
    def __init__(self, requester, dictionary, output, threads=1, excludeInternalServerError=False):
        self.requester = requester
        self.dictionary = dictionary
        self.output = output
        self.excludeInternalServerError = excludeInternalServerError
        self.threads = []
        self.running = False
        for thread in range(threads):
            newThread = threading.Thread(target=self.thread_proc)
            self.threads.append(newThread)
    
    def start(self):
        self.dictionary.reset()
        self.runningThreadsCount = len(self.threads)
        self.isRunningCondition = threading.Condition()
        self.finishedCondition = threading.Condition()
        self.runningThreadsCountCondition = threading.Condition()
        self.stoppedByUser = False
        self.running = True
        for thread in self.threads:
            thread.start()

    def stop(self):
        if self.running == False:
            return
        self.running = False
        self.stoppedByUser = True
        self.finishedCondition.acquire()
        while (self.runningThreadsCount > 0):
            self.finishedCondition.wait()
        self.finishedCondition.release()
        self.isRunningCondition.acquire()
        self.isRunningCondition.notify()
        self.isRunningCondition.release()

    def wait(self):
        self.isRunningCondition.acquire()
        self.isRunningCondition.wait()
        self.isRunningCondition.release()

    def testPath(self, path):
        response = self.requester.request(path)
        if (response.status == 404) or (response.status == 301 ) or ((response.status >= 500) and self.excludeInternalServerError):
            return 0

        return response.status

    def thread_proc(self):
        try:
            while self.running:
                path = self.dictionary.getNextPath()

                if(path == None):
                    self.running = False
                    break
                status = self.testPath(path)
                if status != 0:
                    self.output.printStatusReport(path, status)
                self.output.printLastPathEntry(path)
            self.finishedCondition.acquire()
            self.runningThreadsCountCondition.acquire()
            self.runningThreadsCount = self.runningThreadsCount - 1
            self.runningThreadsCountCondition.release()
            self.finishedCondition.notify()
            self.finishedCondition.release()
            if self.stoppedByUser == False and self.runningThreadsCount == 0:
                self.isRunningCondition.acquire()
                self.isRunningCondition.notify()
                self.isRunningCondition.release()
        except KeyboardInterrupt:
            return
        except RequestException as e:
            self.output.printError("Unexpected error:\n{0}".format(e.args[0]['message']))
            pass
