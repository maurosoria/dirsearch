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

import urllib.error
import urllib.parse
import urllib.request

from lib.utils.file_utils import File
from thirdparty.oset import *


class Dictionary(object):

    def __init__(self, path, extensions, lowercase=False, forced_extensions=False):
        self.entries = []
        self.current_index = 0
        self.condition = threading.Lock()
        self._extensions = extensions
        self._path = path
        self._forced_extensions = forced_extensions
        self.lowercase = lowercase
        self.dictionary_file = File(self.path)
        self.generate()

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

    """
    Dictionary.generate() behaviour

    Classic dirsearch wordlist:
      1. If %EXT% keyword is present, append one with each extension REPLACED.
      2. If the special word is no present, append line unmodified.

    Forced extensions wordlist (NEW):
      This type of wordlist processing is a mix between classic processing
      and DirBuster processing.
          1. If %EXT% keyword is present in the line, immediately process as "classic dirsearch" (1).
          2. If the line does not include the special word AND is NOT terminated by a slash,
            append one with each extension APPENDED (line.ext) and ONLYE ONE with a slash.
          3. If the line does not include the special word and IS ALREADY terminated by slash,
            append line unmodified.
    """

    def generate(self):
        result = []
        for line in self.dictionary_file.get_lines():

            # Skip comments
            if line.lstrip().startswith("#"):
                continue

            # Classic dirsearch wordlist processing (with %EXT% keyword)
            if '%EXT%' in line or '%ext%' in line:
                for extension in self._extensions:
                    if '%EXT%' in line:
                        newline = line.replace('%EXT%', extension)

                    if '%ext%' in line:
                        newline = line.replace('%ext%', extension)

                    quote = self.quote(newline)
                    result.append(quote)

            # If forced extensions is used and the path is not a directory ... (terminated by /)
            # process line like a forced extension.
            elif self._forced_extensions and not line.rstrip().endswith("/"):
                quoted = self.quote(line)

                for extension in self._extensions:
                    # Why? check https://github.com/maurosoria/dirsearch/issues/70
                    if extension.strip() == '':
                        result.append(quoted)
                    else:
                        result.append(quoted + '.' + extension)

                if quoted.strip() not in ['']:
                    result.append(quoted + "/")

            # Append line unmodified.
            else:
                result.append(self.quote(line))

        # oset library provides inserted ordered and unique collection.
        if self.lowercase:
            self.entries = list(oset(map(lambda l: l.lower(), result)))

        else:
            self.entries = list(oset(result))

        del result

    def regenerate(self):
        self.generate(lowercase=self.lowercase)
        self.reset()

    def next_with_index(self, base_path=None):
        self.condition.acquire()

        try:
            result = self.entries[self.current_index]

        except IndexError:
            self.condition.release()
            raise StopIteration

        self.current_index = self.current_index + 1
        current_index = self.current_index
        self.condition.release()
        return current_index, result

    def __next__(self, base_path=None):
        _, path = self.next_with_index(base_path)
        return path

    def reset(self):
        self.condition.acquire()
        self.current_index = 0
        self.condition.release()

    def __len__(self):
        return len(self.entries)
