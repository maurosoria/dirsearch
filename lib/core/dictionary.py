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

from __future__ import annotations

import hashlib
import re
import threading
from typing import Any, Callable, Iterator, Optional

from lib.core.data import options
from lib.core.decorators import locked
from lib.core.settings import (
    SCRIPT_PATH,
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
def get_blacklists() -> dict[int, Dictionary]:
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
    def __init__(self, **kwargs: Any) -> None:
        self._index = 0
        self._wordlist_files = kwargs.get("files", [])
        self._items = self.generate(**kwargs)
        # Items in self._extra will be cleared when self.reset() is called
        self._extra_index = 0
        self._extra: list[str] = []
        # Thread checkpoint tracking (patator-style)
        self._thread_indices: dict[int, int] = {}
        self._checkpoint_callback: Optional[Callable[[int, int], None]] = None
        self._checkpoint_interval = 100  # Save checkpoint every N items
        self._items_since_checkpoint = 0

    @property
    def index(self) -> int:
        return self._index

    @property
    def extra_index(self) -> int:
        return self._extra_index

    @property
    def extra_items(self) -> list[str]:
        return self._extra.copy()

    @property
    def wordlist_files(self) -> list[str]:
        return self._wordlist_files

    def get_wordlist_hash(self) -> str:
        """Generate a hash of wordlist files for verification on resume."""
        hasher = hashlib.sha256()
        for filepath in sorted(self._wordlist_files):
            hasher.update(filepath.encode())
            try:
                with open(filepath, "rb") as f:
                    # Hash first 64KB for speed
                    hasher.update(f.read(65536))
            except (OSError, IOError):
                pass
        return hasher.hexdigest()[:16]

    def set_checkpoint_callback(
        self, callback: Callable[[int, int], None], interval: int = 100
    ) -> None:
        """
        Set callback for checkpoint notifications.
        Callback receives (thread_id, current_index).
        """
        self._checkpoint_callback = callback
        self._checkpoint_interval = interval

    def get_thread_indices(self) -> dict[int, int]:
        """Get copy of thread indices for checkpoint saving."""
        return self._thread_indices.copy()

    def get_min_safe_index(self) -> int:
        """
        Get minimum index across all threads - safe resume point.
        All items before this index have been processed by all threads.
        """
        if not self._thread_indices:
            return self._index
        return min(self._thread_indices.values())

    @locked
    def __next__(self) -> str:
        thread_id = threading.get_ident()

        if len(self._extra) > self._extra_index:
            self._extra_index += 1
            item = self._extra[self._extra_index - 1]
        elif len(self._items) > self._index:
            self._index += 1
            item = self._items[self._index - 1]
        else:
            raise StopIteration

        # Track index per thread
        self._thread_indices[thread_id] = self._index

        # Trigger checkpoint callback periodically
        self._items_since_checkpoint += 1
        if (
            self._checkpoint_callback
            and self._items_since_checkpoint >= self._checkpoint_interval
        ):
            self._items_since_checkpoint = 0
            self._checkpoint_callback(thread_id, self._index)

        return item

    def __contains__(self, item: str) -> bool:
        return item in self._items

    def __getstate__(self) -> tuple[list[str], int, list[str], int]:
        return self._items, self._index, self._extra, self._extra_index

    def __setstate__(self, state: tuple[list[str], int, list[str], int]) -> None:
        self._items, self._index, self._extra, self._extra_index = state
        self._thread_indices = {}
        self._checkpoint_callback = None
        self._checkpoint_interval = 100
        self._items_since_checkpoint = 0

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def set_state(
        self,
        main_index: int,
        extra_index: int = 0,
        extra_items: Optional[list[str]] = None,
    ) -> None:
        """Restore dictionary state from saved checkpoint."""
        self._index = main_index
        self._extra_index = extra_index
        if extra_items:
            self._extra = extra_items
        self._thread_indices.clear()

    def generate(self, files: list[str] = [], is_blacklist: bool = False) -> list[str]:
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

        for dict_file in files:
            for line in FileUtils.get_lines(dict_file):
                # Removing leading "/" to work with prefixes later
                line = lstrip_once(line, "/")

                if not self.is_valid(line):
                    continue

                # Classic dirsearch wordlist processing (with %EXT% keyword)
                if EXTENSION_TAG in line.lower():
                    for extension in options["extensions"]:
                        newline = re_ext_tag.sub(extension, line)
                        wordlist.add(newline)
                else:
                    wordlist.add(line)

                    # "Forcing extensions" and "overwriting extensions" shouldn't apply to
                    # blacklists otherwise it might cause false negatives
                    if is_blacklist:
                        continue

                    # If "forced extensions" is used and the path is not a directory (terminated by /)
                    # or has had an extension already, append extensions to the path
                    if (
                        options["force_extensions"]
                        and "." not in line
                        and not line.endswith("/")
                    ):
                        wordlist.add(line + "/")

                        for extension in options["extensions"]:
                            wordlist.add(f"{line}.{extension}")
                    # Overwrite unknown extensions with selected ones (but also keep the origin)
                    elif (
                        options["overwrite_extensions"]
                        and not line.endswith(options["extensions"] + EXCLUDE_OVERWRITE_EXTENSIONS)
                        # Paths that have queries in wordlist are usually used for exploiting
                        # disclosed vulnerabilities of services, skip such paths
                        and "?" not in line
                        and "#" not in line
                        and re.search(EXTENSION_RECOGNITION_REGEX, line)
                    ):
                        base = line.split(".")[0]

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

    def is_valid(self, path: str) -> bool:
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

    def add_extra(self, path) -> None:
        if path in self._items or path in self._extra:
            return

        self._extra.append(path)

    def reset(self) -> None:
        self._index = self._extra_index = 0
        self._extra.clear()
        self._thread_indices.clear()
        self._items_since_checkpoint = 0
