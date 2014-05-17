# -*- coding: utf-8 -*-
import threading
from lib.utils.FileUtils import File


class FuzzerDictionary(object):

    def __init__(self, path, extensions, lowercase=False):
        self.extensions = []
        self.entries = []
        self.currentIndex = 0
        self.condition = threading.Condition()
        self._extensions = extensions
        self._path = path
        self.lowercase = lowercase
        self.dictionaryFile = File(self.path)
        self.generate(lowercase=self.lowercase)


    @property
    def extensions(self):
        return self._extensions

    @extensions.setter
    def extensions(self, value):
        self._extensions = value

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, path):
        self._path = path

    def generate(self, lowercase=False):
        self.entries = []
        for line in self.dictionaryFile.getLines():
            if '%EXT%' in line:
                for extension in self.extensions:
                    self.entries.append(line.replace('%EXT%', extension))
            else:
                self.entries.append(line)
        if lowercase == True:
            self.entries = list(set([entry.lower() for entry in self.entries]))

    def regenerate(self):
        self.generate(lowercase=self.lowercase)
        self.reset()

    def nextWithIndex(self, basePath=None):
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

    def next(self, basePath=None):
        _, path = self.nextWithIndex(basePath)
        return path

    def reset(self):
        self.condition.acquire()
        self.currentIndex = 0
        self.condition.release()

    def __len__(self):
        return len(self.entries)


