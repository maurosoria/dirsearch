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

from lib.core.decorators import locked
from lib.core.settings import SCRIPT_PATH, EXTENSION_TAG, EXTENSION_REGEX
from lib.utils.common import uniq
from lib.utils.file import FileUtils


class Dictionary(object):
    def __init__(self, **kwargs):
        self._entries = ()
        self._index = 0
        self._dictionary_files = kwargs.get("paths", [])
        self.extensions = kwargs.get("extensions", [])
        self.exclude_extensions = kwargs.get("exclude_extensions", [])
        self.prefixes = kwargs.get("prefixes", [])
        self.suffixes = kwargs.get("suffixes", [])
        self.force_extensions = kwargs.get("force_extensions", False)
        self.no_extension = kwargs.get("no_extension", False)
        self.only_selected = kwargs.get("only_selected", False)
        self.lowercase = kwargs.get("lowercase", False)
        self.uppercase = kwargs.get("uppercase", False)
        self.capitalization = kwargs.get("capitalization", False)
        self.generate()

    @property
    def index(self):
        return self._index

    '''
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
    '''

    def generate(self):
        reext = re.compile(EXTENSION_TAG, re.IGNORECASE)
        result = []

        # Enable to use multiple dictionaries at once
        for dict_file in self._dictionary_files:
            for line in FileUtils.get_lines(dict_file):
                if line.startswith('/'):
                    line = line[1:]

                if self.no_extension:
                    line = line.split('.')[0]

                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue

                # Skip if the path contains excluded extensions
                if any('.' + extension in line for extension in self.exclude_extensions):
                    continue

                # Classic dirsearch wordlist processing (with %EXT% keyword)
                if EXTENSION_TAG in line.lower():
                    for extension in self.extensions:
                        newline = reext.sub(extension, line)
                        result.append(newline)
                # If "forced extensions" is used and the path is not a directory (terminated by /) or has
                # had an extension already, append extensions to the path
                elif self.force_extensions and not line.endswith('/') and not re.search(EXTENSION_REGEX, line):
                    for extension in self.extensions:
                        result.append(line + f".{extension}")

                    result.append(line)
                    result.append(line + '/')
                # Append line unmodified.
                elif not self.only_selected or any(
                    line.endswith(f".{extension}") for extension in self.extensions
                ):
                    result.append(line)

        # Re-add dictionary with prefixes
        result.extend(
            [pref + path for path in result for pref in self.prefixes if not path.startswith(pref)]
        )
        # Re-add dictionary with suffixes
        result.extend(
            [path + suff for path in result for suff in self.suffixes if not path.endswith(("/", suff))]
        )

        if self.lowercase:
            self._entries = tuple(entry.lower() for entry in uniq(result))
        elif self.uppercase:
            self._entries = tuple(entry.upper() for entry in uniq(result))
        elif self.capitalization:
            self._entries = tuple(entry.capitalize() for entry in uniq(result))
        else:
            self._entries = tuple(uniq(result))

        del result

    # Get ignore paths for status codes.
    # More information: https://github.com/maurosoria/dirsearch#Blacklist
    @staticmethod
    def generate_blacklists(extensions):
        blacklists = {}

        for status in [400, 403, 500]:
            blacklist_file_name = FileUtils.build_path(SCRIPT_PATH, "db")
            blacklist_file_name = FileUtils.build_path(
                blacklist_file_name, f"{status}_blacklist.txt"
            )

            if not FileUtils.can_read(blacklist_file_name):
                # Skip if cannot read file
                continue

            blacklists[status] = set(Dictionary(paths=[blacklist_file_name], extensions=extensions))

        return blacklists

    def reset(self):
        self._index = 0

    def __getstate__(self):
        return (self._entries, self._index, self.extensions)

    def __setstate__(self, state):
        self._entries, self._index, self.extensions = state

    @locked
    def __next__(self):
        try:
            path = self._entries[self._index]
        except IndexError:
            raise StopIteration

        self._index += 1

        return path

    def __iter__(self):
        return iter(self._entries)

    def __len__(self):
        return len(self._entries)
