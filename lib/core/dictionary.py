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
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterator

from lib.core.settings import SCRIPT_PATH
from lib.core.wordlist_backend import (
    NativeWordlistBatch,
    NativeWordlistCorpus,
    get_wordlist_backend,
    is_valid_path,
)
from lib.utils.file import FileUtils


@dataclass
class _NativeClaim:
    batch: NativeWordlistBatch
    start: int
    released: int = 0


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
        self._lock = threading.Lock()
        self._index = 0
        self._items = self.generate(**kwargs)
        self._item_membership: set[str] | None = None
        # Items in self._extra will be cleared when self.reset() is called
        self._extra_index = 0
        self._extra = []
        self._extra_membership: set[str] = set()
        self._claimed = []
        self._native_claim: _NativeClaim | None = None

    @property
    def index(self) -> int:
        with self._lock:
            return self._index

    def __next__(self) -> str:
        with self._lock:
            if len(self._extra) > self._extra_index:
                self._extra_index += 1
                return self._extra[self._extra_index - 1]
            elif len(self._items) > self._index:
                self._index += 1
                return self._items[self._index - 1]
            else:
                raise StopIteration

    def claim_next(self) -> str:
        """Return the next path and keep it recoverable until released."""
        with self._lock:
            if len(self._extra) > self._extra_index:
                path = self._extra[self._extra_index]
                self._claimed.append(path)
                self._extra_index += 1
                return path
            elif len(self._items) > self._index:
                path = self._items[self._index]
                self._claimed.append(path)
                self._index += 1
                return path
            else:
                raise StopIteration

    def claim_many(self, maximum: int) -> list[str]:
        """Claim up to maximum paths atomically, preserving queue order."""
        if maximum <= 0:
            return []

        with self._lock:
            extra_count = min(maximum, len(self._extra) - self._extra_index)
            if extra_count:
                extra_end = self._extra_index + extra_count
                paths = self._extra[self._extra_index:extra_end]
                self._extra_index = extra_end
            else:
                paths = []

            item_count = min(
                maximum - len(paths),
                len(self._items) - self._index,
            )
            if item_count:
                item_end = self._index + item_count
                items = self._items[self._index:item_end]
                if paths:
                    paths.extend(items)
                else:
                    paths = items
                self._index = item_end

            self._claimed.extend(paths)
            return paths

    def claim_native_many(
        self,
        maximum: int,
        base_path: str,
    ) -> list[str] | NativeWordlistBatch:
        """Claim a Rust-owned range without materializing its Python strings."""
        if maximum <= 0:
            return []

        with self._lock:
            if self._native_claim is not None:
                raise RuntimeError("native dictionary claim is still active")

            if not isinstance(self._items, NativeWordlistCorpus):
                extra_count = min(maximum, len(self._extra) - self._extra_index)
                if extra_count:
                    extra_end = self._extra_index + extra_count
                    paths = self._extra[self._extra_index:extra_end]
                    self._extra_index = extra_end
                else:
                    paths = []

                item_count = min(
                    maximum - len(paths),
                    len(self._items) - self._index,
                )
                if item_count:
                    item_end = self._index + item_count
                    items = self._items[self._index:item_end]
                    if paths:
                        paths.extend(items)
                    else:
                        paths = items
                    self._index = item_end
                self._claimed.extend(paths)
                return paths

            # Dynamic discoveries retain priority and stay on the established
            # Python claim path. The next iteration resumes the native corpus.
            extra_count = min(maximum, len(self._extra) - self._extra_index)
            if extra_count:
                extra_end = self._extra_index + extra_count
                paths = self._extra[self._extra_index:extra_end]
                self._extra_index = extra_end
                self._claimed.extend(paths)
                return paths

            item_count = min(maximum, len(self._items) - self._index)
            if not item_count:
                return []
            start = self._index
            batch = self._items.batch(start, item_count, base_path)
            self._index += item_count
            self._native_claim = _NativeClaim(batch, start)
            return batch

    def release_native_claims(
        self,
        batch: NativeWordlistBatch,
        count: int,
    ) -> None:
        """Release an ordered prefix from the active Rust-owned claim."""
        if count <= 0:
            return

        with self._lock:
            claim = self._native_claim
            if claim is None or claim.batch is not batch:
                raise ValueError("native wordlist batch is not claimed")
            if claim.released + count > len(batch):
                raise ValueError("native wordlist release exceeds claimed batch")
            claim.released += count
            if claim.released == len(batch):
                self._native_claim = None

    def release_claim(self, path: str) -> None:
        with self._lock:
            self._claimed.remove(path)

    def release_claims(self, paths: list[str]) -> None:
        """Release several completed claims in one bounded lock operation."""
        if not paths:
            return

        with self._lock:
            count = len(paths)
            # Native batches normally complete in claim order. Removing the
            # prefix avoids a separate linear search for every path.
            if count == len(self._claimed) and self._claimed == paths:
                self._claimed.clear()
                return
            if self._claimed[:count] == paths:
                del self._claimed[:count]
                return

            # Pause/cancellation can leave an out-of-order subset. Preserve
            # unmatched claims so session recovery can requeue them.
            pending = Counter(paths)
            claimed = []
            for path in self._claimed:
                if pending[path]:
                    pending[path] -= 1
                else:
                    claimed.append(path)

            if any(pending.values()):
                raise ValueError("list.remove(x): x not in list")
            self._claimed = claimed

    def requeue_claims(self) -> None:
        """Make outstanding claims available again in their original order."""
        with self._lock:
            if not self._claimed and self._native_claim is None:
                return

            if self._claimed:
                self._extra[self._extra_index:self._extra_index] = self._claimed
                self._claimed.clear()
            if self._native_claim is not None:
                claim = self._native_claim
                # NativeFuzzer has one synchronous batch in flight, so no later
                # corpus claim can exist when cancellation rewinds this range.
                self._index = claim.start + claim.released
                self._native_claim = None

    def __contains__(self, item: str) -> bool:
        return item in self._items

    def __getstate__(self) -> tuple[list[str], int, list[str], int]:
        with self._lock:
            extra = (
                self._extra[:self._extra_index]
                + self._claimed
                + self._extra[self._extra_index:]
            )
            index = self._index
            if self._native_claim is not None:
                index = self._native_claim.start + self._native_claim.released
            items = (
                self._items.to_list()
                if isinstance(self._items, NativeWordlistCorpus)
                else list(self._items)
            )
            return items, index, extra, self._extra_index

    def __setstate__(self, state: tuple[list[str], int, list[str], int]) -> None:
        if not hasattr(self, "_lock"):
            self._lock = threading.Lock()
        with self._lock:
            self._items, self._index, self._extra, self._extra_index = state
            self._item_membership = None
            self._extra_membership = set(self._extra)
            self._claimed = []
            self._native_claim = None

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def generate(
        self,
        files: list[str] = [],
        is_blacklist: bool = False,
    ) -> list[str] | NativeWordlistCorpus:
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

        return get_wordlist_backend().generate(files, is_blacklist=is_blacklist)

    def is_valid(self, path: str) -> bool:
        return is_valid_path(path)

    def add_extra(self, path: str) -> None:
        """Queue a valid dynamically discovered path once."""
        if not self.is_valid(path):
            return

        with self._lock:
            if (
                self._item_membership is None
                and not isinstance(self._items, NativeWordlistCorpus)
            ):
                self._item_membership = set(self._items)

            in_items = (
                path in self._items
                if isinstance(self._items, NativeWordlistCorpus)
                else path in self._item_membership
            )
            if in_items or path in self._extra_membership:
                return

            self._extra.append(path)
            self._extra_membership.add(path)

    def reset(self) -> None:
        with self._lock:
            self._index = self._extra_index = 0
            self._extra.clear()
            self._extra_membership.clear()
            self._claimed.clear()
            self._native_claim = None
