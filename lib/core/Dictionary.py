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
import urllib.request, urllib.parse, urllib.error
from lib.utils.FileUtils import File
from thirdparty.oset import *


class Dictionary(object):

    def __init__(self, path, extensions, lowercase=False, forcedExtensions=False):
        self.entries = []
        self.currentIndex = 0
        self.condition = threading.Lock()
        self._extensions = extensions
        self._path = path
        self._forcedExtensions = forcedExtensions
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

    @classmethod
    def quote(cls, string):
        return urllib.parse.quote(string, safe=":/~?%&+-=$")

    def generate(self, lowercase=False):
        self.entries = []
        for line in self.dictionaryFile.getLines():
            # Skip comments
            entry = line
            if line.lstrip().startswith("#"): continue
            if '%EXT%' in line:
                for extension in self._extensions:
                    self.entries.append(self.quote(line.replace('%EXT%', extension)))
            else:
                if self._forcedExtensions:
                    for extension in self._extensions:
                        self.entries.append(self.quote(line) + '.' + extension)
                quote = self.quote(line)
                self.entries.append(quote)
        if lowercase == True:
            self.entries = list(oset([entry.lower() for entry in self.entries]))

    def regenerate(self):
        self.generate(lowercase=self.lowercase)
        self.reset()

    def nextWithIndex(self, basePath=None):
        self.condition.acquire()
        try:
            result = self.entries[self.currentIndex]
        except IndexError:
            self.condition.release()
            raise StopIteration
        self.currentIndex = self.currentIndex + 1
        currentIndex = self.currentIndex
        self.condition.release()
        return currentIndex, result

    def __next__(self, basePath=None):
        _, path = self.nextWithIndex(basePath)
        return path

    def reset(self):
        self.condition.acquire()
        self.currentIndex = 0
        self.condition.release()

    def __len__(self):
        return len(self.entries)


