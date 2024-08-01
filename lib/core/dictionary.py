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

import urllib.parse

from lib.core.data import options
from lib.core.decorators import locked
from lib.core.settings import (
    SCRIPT_PATH,
    DOMAIN_TAG,
    EXTENSION_TAG,
    EXCLUDE_OVERWRITE_EXTENSIONS,
    EXTENSION_RECOGNITION_REGEX,
)
from lib.core.structures import OrderedSet
from lib.parse.url import clean_path
from lib.utils.common import lstrip_once
from lib.utils.file import FileUtils


# Get ignore paths for status codes.
# Reference: https://github.com/maurosoria/dirsearch#Blacklist
def get_blacklists():
    blacklists = {}

    for status in [400, 403, 500]:
        blacklist_file_name = FileUtils.build_path(SCRIPT_PATH, "db")
        blacklist_file_name = FileUtils.build_path(
            blacklist_file_name, f"{status}_blacklist.txt"
        )

        if not FileUtils.can_read(blacklist_file_name):
            # Skip if cannot read file
            continue

        blacklists[status] = Dictionary(
            files=[blacklist_file_name],
            is_blacklist=True,
        )

    return blacklists


class Dictionary:
    def __init__(self, **kwargs):
        self._index = 0
        self._items = self.generate(**kwargs)

    @property
    def index(self):
        return self._index

    @locked
    def __next__(self):
        try:
            path = self._items[self._index]
        except IndexError:
            raise StopIteration

        self._index += 1

        return path

    def __contains__(self, item):
        return item in self._items

    def __getstate__(self):
        return self._items, self._index

    def __setstate__(self, state):
        self._items, self._index = state

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def generate(self, files=[], is_blacklist=False):
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
                append one with each extension APPENDED (line.ext) and ONLY ONE with a slash.
              3. If the line does not include the special word and IS ALREADY terminated by slash,
                append line unmodified.
        """

        wordlist = OrderedSet()
        re_ext_tag = re.compile(EXTENSION_TAG, re.IGNORECASE)

        # Prepare the list of hostnames from the URLs
        hostnames = set()
        for url in options['urls']:
            parsed = urllib.parse.urlparse(url)
            if parsed is None:
                continue

            hostnames.add(parsed.hostname)

        for dict_file in files:
            for line in FileUtils.get_lines(dict_file):
                # Removing leading "/" to work with prefixes later
                line = lstrip_once(line, "/")

                if options["remove_extensions"]:
                    line = line.split(".")[0]

                if not self.is_valid(line):
                    continue

                new_lines = [line]
                extension_tag_triggered = False
                domain_tag_triggered = False

                # We need this to know that EXTENSION_TAG was used
                #  and not to trigger the complementary function that
                #  handles when it is not
                if EXTENSION_TAG in line.lower():
                    extension_tag_triggered = True

                if DOMAIN_TAG in line:
                    domain_tag_triggered = True

                final_lines = []
                if domain_tag_triggered:
                    for new_line in new_lines:
                        # If %DOMAIN% is found, replace it with self.urls (insert as many as they exist)
                        if DOMAIN_TAG in new_line:
                            for hostname in hostnames:
                                split_hostnames = hostname.split(".")
                                final_line = new_line.replace(DOMAIN_TAG, hostname)
                                final_lines.append(final_line)

                                if len(split_hostnames) > 1:
                                    # We go from 1 dot to .. n .. as we want to return from www.somesite.co.uk:
                                    #  www.somesite.co.uk, somesite.co.uk, co.uk
                                    for dots in range(1, len(split_hostnames)):
                                        new_hostname = ".".join(split_hostnames[dots:])
                                        final_line = new_line.replace(DOMAIN_TAG, new_hostname)
                                        final_lines.append(final_line)

                                    # We go from n dot to .. 1 .. as we want to return from www.somesite.co.uk:
                                    #  www.somesite.co, www.somesite, www
                                    for dots in range(1, len(split_hostnames)):
                                        new_hostname = ".".join(split_hostnames[:dots])
                                        final_line = new_line.replace(DOMAIN_TAG, new_hostname)
                                        final_lines.append(final_line)

                    new_lines = final_lines[:]

                if extension_tag_triggered:
                    # Remove the items from the list, as we re-generate them here

                    final_lines = []
                    # Classic dirsearch wordlist processing (with %EXT% keyword)
                    for new_line in new_lines:
                        if EXTENSION_TAG in new_line.lower():
                            for extension in options["extensions"]:
                                final_line = re_ext_tag.sub(extension, new_line)
                                final_lines.append(final_line)

                # If neither was triggered, just copy new_lines to our final outcome
                if not domain_tag_triggered and not extension_tag_triggered:
                    final_lines = new_lines

                # Go over the new_lines generated
                for final_line in final_lines:
                    wordlist.add(final_line)

                    # This keeps original code, that would do an else (i.e if EXTENSION_TAG)
                    #  is not triggered
                    if extension_tag_triggered:
                        continue

                    # "Forcing extensions" and "overwriting extensions" shouldn't apply to
                    # blacklists otherwise it might cause false negatives
                    if is_blacklist:
                        continue

                    # If "forced extensions" is used and the path is not a directory
                    # (terminated by /) or has had an extension already, append
                    # extensions to the path
                    if (
                        options["force_extensions"]
                        and "." not in final_line
                        and not final_line.endswith("/")
                    ):
                        wordlist.add(final_line + "/")

                        for extension in options["extensions"]:
                            wordlist.add(f"{final_line}.{extension}")
                    # Overwrite unknown extensions with selected ones (but also keep the origin)
                    elif (
                        options["overwrite_extensions"]
                        and not final_line.endswith(options["extensions"] + EXCLUDE_OVERWRITE_EXTENSIONS)
                        # Paths that have queries in wordlist are usually used for exploiting
                        # disclosed vulnerabilities of services, skip such paths
                        and "?" not in final_line
                        and "#" not in final_line
                        and re.search(EXTENSION_RECOGNITION_REGEX, final_line)
                    ):
                        base = final_line.split(".")[0]

                        for extension in options["extensions"]:
                            wordlist.add(f"{base}.{extension}")

        if not is_blacklist:
            # Appending prefixes and suffixes
            altered_wordlist = OrderedSet()

            for path in wordlist:
                for pref in options["prefixes"]:
                    if (
                        not path.startswith(("/", pref))
                    ):
                        altered_wordlist.add(pref + path)
                for suff in options["suffixes"]:
                    if (
                        not path.endswith(("/", suff))
                        # Appending suffixes to the URL fragment is useless
                        and "?" not in path
                        and "#" not in path
                    ):
                        altered_wordlist.add(path + suff)

            if altered_wordlist:
                wordlist = altered_wordlist

        if options["lowercase"]:
            return list(map(str.lower, wordlist))
        elif options["uppercase"]:
            return list(map(str.upper, wordlist))
        elif options["capitalization"]:
            return list(map(str.capitalize, wordlist))
        else:
            return list(wordlist)

    def is_valid(self, path):
        # Skip comments and empty lines
        if not path or path.startswith("#"):
            return False

        # Skip if the path has excluded extensions
        cleaned_path = clean_path(path)
        if cleaned_path.endswith(
            tuple(f".{extension}" for extension in options["exclude_extensions"])
        ):
            return False

        return True

    def reset(self):
        self._index = 0
