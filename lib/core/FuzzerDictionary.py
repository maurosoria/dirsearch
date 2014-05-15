import threading

class FuzzerDictionary:
    def __init__(self, path, extensions, lowercase = False):
        self.extensions = []
        self.entries = []
        self.currentIndex = 0
        self.condition = threading.Condition()
        self.setExtensions(extensions)
        self.setPath(path)
        self.lowercase = lowercase
        self.generateDictionary(lowercase = self.lowercase)


    def setExtensions(self, extensions):
        self.extensions = extensions


    def getExtensions(self):
        return self.extensions


    def setPath(self, path):
        self.path = path


    def generateDictionary(self, lowercase = False):
        self.entries = []
        dictionary_file = open(self.path, 'r')
        for line in dictionary_file:
            if '%EXT%' in line:
                for extension in self.extensions:
                    self.entries.append(line.replace('%EXT%', extension).replace('\n', ''))
            else:
                self.entries.append(line.replace('\n', ''))
        if (lowercase == True):
            self.entries = list(set([entry.lower() for entry in self.entries]))


    def regenerateDictionary(self):
        self.generateDictionary(lowercase = self.lowercase)
        self.reset()


    def getNextPathWithIndex(self, basePath=None):
        self.condition.acquire()
        try:
            result = self.entries[self.currentIndex]
        except IndexError:
            self.condition.release()
            return None, None
        self.currentIndex = self.currentIndex + 1
        currentIndex = self.currentIndex
        self.condition.release()

        return currentIndex, result


    def getNextPath(self, basePath=None):
        _, path = self.getNextPathWithIndex(basePath)
        return path



    def __len__(self):
        return len(self.entries)


    def reset(self):
        self.condition.acquire()
        self.currentIndex = 0
        self.condition.release()
