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

import re
import threading
import urllib.parse

from lib.utils.file_utils import File


class Dictionary(object):

    def __init__(
        self,
        paths,
        extensions,
        suffixes=None,
        prefixes=None,
        lowercase=False,
        uppercase=False,
        capitalization=False,
        forcedExtensions=False,
        excludeExtensions=[],
        noExtension=False,
        onlySelected=False,
    ):

        self.entries = []
        self.currentIndex = 0
        self.condition = threading.Lock()
        self._extensions = extensions
        self._excludeExtensions = excludeExtensions
        self._prefixes = prefixes
        self._suffixes = suffixes
        self._paths = paths
        self._forcedExtensions = forcedExtensions
        self._noExtension = noExtension
        self._onlySelected = onlySelected
        self.lowercase = lowercase
        self.uppercase = uppercase
        self.capitalization = capitalization
        self.dictionaryFiles = [File(path) for path in self.paths]
        self.generate()

    @property
    def extensions(self):
        return self._extensions

    @extensions.setter
    def extensions(self, value):
        self._extensions = value

    @property
    def paths(self):
        return self._paths

    @paths.setter
    def paths(self, paths):
        self._paths = paths

    @classmethod
    def quote(cls, string):
        return urllib.parse.quote(string, safe="!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

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
        reext = re.compile(r"\%ext\%", re.IGNORECASE).sub
        renoforce = re.compile(r"\%noforce\%", re.IGNORECASE).sub
        find = re.findall
        custom = []
        result = []

        # Enable to use multiple dictionaries at once
        for dictFile in self.dictionaryFiles:
            for line in list(filter(None, dict.fromkeys(dictFile.get_lines()))):
                # Skip comments
                if line.lstrip().startswith("#"):
                    continue

                if line.startswith("/"):
                    line = line[1:]

                if self._noExtension:
                    line = line[0] + line[1:].split(".")[0]

                # Check if the line is having the %NOFORCE% keyword
                if "%noforce%" in line.lower():
                    noforce = True
                    line = renoforce("", line)
                else:
                    noforce = False

                # Skip if the path contains excluded extensions
                if self._excludeExtensions:
                    if any(
                        [find("." + extension, line) for extension in self._excludeExtensions]
                    ):
                        continue

                # Classic dirsearch wordlist processing (with %EXT% keyword)
                if "%ext%" in line.lower():
                    for extension in self._extensions:
                        newline = reext(extension, line)

                        quoted = self.quote(newline)
                        result.append(quoted)

                # If forced extensions is used and the path is not a directory ... (terminated by /)
                # process line like a forced extension.
                elif self._forcedExtensions and not line.rstrip().endswith("/") and not noforce:
                    quoted = self.quote(line)

                    for extension in self._extensions:
                        # Why? Check https://github.com/maurosoria/dirsearch/issues/70
                        if not extension.strip():
                            result.append(quoted)
                        else:
                            result.append(quoted + "." + extension)

                    result.append(quoted)
                    result.append(quoted + "/")

                # Append line unmodified.
                else:
                    quoted = self.quote(line)

                    if self._onlySelected and not line.rstrip().endswith("/") and "." in line:
                        for extension in self._extensions:
                            if line.endswith("." + extension):
                                result.append(quoted)
                                break

                    else:
                        result.append(quoted)

        # Adding prefixes for finding config files etc
        if self._prefixes:
            for res in list(dict.fromkeys(result)):
                for pref in self._prefixes:
                    if not res.startswith(pref):
                        custom.append(pref + res)

        # Adding suffixes for finding backups etc
        if self._suffixes:
            for res in list(dict.fromkeys(result)):
                if not res.rstrip().endswith("/"):
                    for suff in self._suffixes:
                        if not res.rstrip().endswith(suff):
                            custom.append(res + suff)

        result = custom if custom else result

        if self.lowercase:
            self.entries = list(dict.fromkeys(map(lambda l: l.lower(), result)))

        elif self.uppercase:
            self.entries = list(dict.fromkeys(map(lambda l: l.upper(), result)))

        elif self.capitalization:
            self.entries = list(dict.fromkeys(map(lambda l: l.capitalize(), result)))

        else:
            self.entries = list(dict.fromkeys(result))

        del custom
        del result

    def regenerate(self):
        self.generate()
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
