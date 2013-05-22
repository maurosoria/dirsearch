import threading, time, sys

class Output:
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
        self.mutexCheckedPaths = threading.Lock()
        
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

        if (self.lastInLine == True):
            sys.stdout.write('\033[1K')
            sys.stdout.write('\033[0G')
        sys.stdout.write(string + '\n')
        sys.stdout.flush()
        self.lastInLine = False
        self.mutex.release()

    def printStatusReport(self, path, status):
        message = "[{0}]  {1}: {2}".format(time.strftime("%H:%M:%S"), status, path)
        self.mutexCheckedPaths.acquire()
        if path in self.checkedPaths:
            self.mutexCheckedPaths.release()
            return
        self.mutexCheckedPaths.release()
        if status == 200:
            message = self.OKGREENBOLD + message + self.ENDC
        elif (status == 403):
            message = self.OKBLUEBOLD + message + self.ENDC
        self.printNewLine(message)

    def printLastPathEntry(self, path):
        message = "- Last request to: {0}".format(path)
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