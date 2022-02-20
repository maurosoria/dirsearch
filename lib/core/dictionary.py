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
from lib.utils.fmt import safequote, uniq
from lib.utils.file import File, FileUtils


class Dictionary(object):

    def __init__(
        self,
        paths=[],
        extensions=[],
        suffixes=[],
        prefixes=[],
        lowercase=False,
        uppercase=False,
        capitalization=False,
        force_extensions=False,
        exclude_extensions=[],
        no_extension=False,
        only_selected=False,
    ):

        self.entries = ()
        self.index = 0
        self._extensions = extensions
        self._exclude_extensions = exclude_extensions
        self._prefixes = prefixes
        self._suffixes = suffixes
        self._paths = paths
        self._force_extensions = force_extensions
        self._no_extension = no_extension
        self._only_selected = only_selected
        self.lowercase = lowercase
        self.uppercase = uppercase
        self.capitalization = capitalization
        self.dictionary_files = (File(path) for path in self.paths)
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
        for dict_file in self.dictionary_files:
            for line in uniq(dict_file.get_lines()):
                if line.startswith("/"):
                    line = line[1:]

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                if self._no_extension:
                    line = line[0] + line[1:].split(".")[0]
                    # Skip dummy paths
                    if line == ".":
                        continue

                # Skip if the path contains excluded extensions
                if self._exclude_extensions and (
                    any(("." + extension in line for extension in self._exclude_extensions))
                ):
                    continue

                # Classic dirsearch wordlist processing (with %EXT% keyword)
                if EXTENSION_TAG in line.lower():
                    for extension in self._extensions:
                        newline = reext.sub(extension, line)
                        result.append(newline)

                # If "forced extensions" is used and the path is not a directory (terminated by /) or has
                # had an extension already, append extensions to the path
                elif self._force_extensions and not line.endswith("/") and not re.search(EXTENSION_REGEX, line):
                    for extension in self._extensions:
                        result.append(line + "." + extension)

                    result.append(line)
                    result.append(line + "/")

                # Append line unmodified.
                else:
                    if not self._only_selected or any(
                        [line.endswith("." + extension) for extension in self.extensions]
                    ):
                        result.append(line)

        # Re-add dictionary with prefixes
        result.extend(
            [pref + path for path in result for pref in self._prefixes if not path.startswith(pref)]
        )
        # Re-add dictionary with suffixes
        result.extend(
            [path + suff for path in result for suff in self._suffixes if not path.endswith(("/", suff))]
        )

        if self.lowercase:
            self.entries = tuple(entry.lower() for entry in uniq(result))
        elif self.uppercase:
            self.entries = tuple(entry.upper() for entry in uniq(result))
        elif self.capitalization:
            self.entries = tuple(entry.capitalize() for entry in uniq(result))
        else:
            self.entries = tuple(uniq(result))

        del result

    # Get ignore paths for status codes.
    # More information: https://github.com/maurosoria/dirsearch#Blacklist
    @staticmethod
    def generate_blacklists(extensions):
        blacklists = {}

        for status in [400, 403, 500]:
            blacklist_file_name = FileUtils.build_path(SCRIPT_PATH, "db")
            blacklist_file_name = FileUtils.build_path(
                blacklist_file_name, "{}_blacklist.txt".format(status)
            )

            if not FileUtils.can_read(blacklist_file_name):
                # Skip if cannot read file
                continue

            blacklists[status] = list(Dictionary([blacklist_file_name], extensions))

        return blacklists

    def reset(self):
        self.index = 0

    @locked
    def __next__(self):
        try:
            path = self.entries[self.index]
        except IndexError:
            raise StopIteration

        self.index += 1

        return safequote(path)

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)
