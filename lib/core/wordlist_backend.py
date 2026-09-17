from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, Protocol

from lib.core.data import options
from lib.core.exceptions import WordlistBackendUnavailableError, WordlistLimitError
from lib.core.native_runtime import (
    get_native_backend_install_error,
    get_native_extension_version_error,
)
from lib.core.settings import (
    EXCLUDE_OVERWRITE_EXTENSIONS,
    EXTENSION_RECOGNITION_REGEX,
    EXTENSION_TAG,
)
from lib.core.structures import OrderedSet
from lib.core.wordlist_template import (
    TOKEN_RE,
    expand_template_line,
    is_template_token,
)
from lib.parse.url import clean_path
from lib.utils.common import lstrip_once
from lib.utils.file import FileUtils


WORDLIST_BACKENDS = ("auto", "python", "native")


class NativeWordlistBatch:
    """Python ownership token for a range that remains stored in Rust."""

    def __init__(self, native_batch: Any) -> None:
        self.native = native_batch

    def __len__(self) -> int:
        return self.native.len()

    def path_at(self, index: int) -> str:
        return self.native.path_at(index)

    def to_list(self) -> list[str]:
        return self.native.to_list()


class NativeWordlistCorpus:
    """Sequence facade that materializes Python strings only when requested."""

    def __init__(self, native_wordlist: Any) -> None:
        self.native = native_wordlist

    def __len__(self) -> int:
        return self.native.len()

    def __getitem__(self, index: int | slice) -> str | list[str]:
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step == 1:
                return self.native.slice(start, stop)
            return [self.native.get(item_index) for item_index in range(start, stop, step)]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError("native wordlist index out of range")
        return self.native.get(index)

    def __iter__(self) -> Iterator[str]:
        for index in range(len(self)):
            yield self.native.get(index)

    def __contains__(self, path: object) -> bool:
        return isinstance(path, str) and self.native.contains(path)

    def to_list(self) -> list[str]:
        return self.native.to_list()

    def batch(self, start: int, count: int, base_path: str) -> NativeWordlistBatch:
        return NativeWordlistBatch(self.native.batch(start, count, base_path))


class WordlistBackend(Protocol):
    name: str

    def generate(
        self, files: list[str], is_blacklist: bool = False
    ) -> list[str] | NativeWordlistCorpus:
        pass

    def is_valid(self, path: str) -> bool:
        pass


def is_valid_path(path: str) -> bool:
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


class PythonWordlistBackend:
    name = "python"

    def generate(
        self, files: list[str], is_blacklist: bool = False
    ) -> list[str] | NativeWordlistCorpus:
        wordlist = OrderedSet()
        for dict_file in files:
            for line in FileUtils.get_lines(dict_file):
                # Removing leading "/" to work with prefixes later
                line = lstrip_once(line, "/")

                for line in expand_template_line(
                    line,
                    extensions=options["extensions"],
                ):
                    if not self.is_valid(line):
                        continue

                    self._add_wordlist_entry(wordlist, line)

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
                        self._add_wordlist_entry(wordlist, line + "/")

                        for extension in options["extensions"]:
                            self._add_wordlist_entry(wordlist, f"{line}.{extension}")
                    # Overwrite unknown extensions with selected ones (but also keep the origin)
                    elif (
                        options["overwrite_extensions"]
                        and not line.endswith(
                            options["extensions"] + EXCLUDE_OVERWRITE_EXTENSIONS
                        )
                        # Paths that have queries in wordlist are usually used for exploiting
                        # disclosed vulnerabilities of services, skip such paths
                        and "?" not in line
                        and "#" not in line
                        and re.search(EXTENSION_RECOGNITION_REGEX, line)
                    ):
                        base = line.split(".")[0]

                        for extension in options["extensions"]:
                            self._add_wordlist_entry(wordlist, f"{base}.{extension}")

        if not is_blacklist:
            # Appending prefixes and suffixes
            altered_wordlist = OrderedSet()

            for path in wordlist:
                for pref in options["prefixes"]:
                    if not path.startswith(("/", pref)):
                        self._add_wordlist_entry(altered_wordlist, pref + path)
                for suff in options["suffixes"]:
                    if (
                        not path.endswith(("/", suff))
                        # Appending suffixes to the URL fragment is useless
                        and "?" not in path
                        and "#" not in path
                    ):
                        self._add_wordlist_entry(altered_wordlist, path + suff)

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
        return is_valid_path(path)

    def _add_wordlist_entry(self, wordlist: OrderedSet, path: str) -> None:
        wordlist.add(path)
        max_size = options["wordlist_max_size"]
        if max_size and len(wordlist) > max_size:
            raise WordlistLimitError(
                f"Generated wordlist exceeded --wordlist-max-size ({max_size})"
            )


class NativeWordlistBackend:
    name = "native"

    def __init__(self) -> None:
        try:
            import dirsearch_native
        except ImportError as e:
            raise WordlistBackendUnavailableError(get_native_backend_install_error()) from e

        if version_error := get_native_extension_version_error(dirsearch_native):
            raise WordlistBackendUnavailableError(version_error)

        self._native = dirsearch_native

    def generate(
        self, files: list[str], is_blacklist: bool = False
    ) -> list[str] | NativeWordlistCorpus:
        if is_blacklist or self._requires_python_template_expansion(files):
            return PythonWordlistBackend().generate(files, is_blacklist=is_blacklist)

        generate = (
            self._native.generate_wordlist_owned
            if options["request_backend"] == "native"
            else self._native.generate_wordlist
        )
        wordlist = generate(
            files,
            list(options["extensions"]),
            force_extensions=options["force_extensions"],
            prefixes=list(options["prefixes"]),
            suffixes=list(options["suffixes"]),
            exclude_extensions=list(options["exclude_extensions"]),
            overwrite_exclude_extensions=list(EXCLUDE_OVERWRITE_EXTENSIONS),
            lowercase=options["lowercase"],
            uppercase=options["uppercase"],
            capitalization=options["capitalization"],
            overwrite_extensions=options["overwrite_extensions"],
            max_size=options["wordlist_max_size"],
        )
        if options["request_backend"] == "native":
            return NativeWordlistCorpus(wordlist)
        return wordlist

    def is_valid(self, path: str) -> bool:
        return is_valid_path(path)

    def _requires_python_template_expansion(self, files: list[str]) -> bool:
        extension_token = EXTENSION_TAG.strip("%").upper()
        for dict_file in files:
            with open(dict_file, "r", errors="replace") as handle:
                for line in handle:
                    if "%" not in line:
                        continue

                    tokens = {
                        token.upper()
                        for token in TOKEN_RE.findall(line)
                        if is_template_token(token)
                    }
                    if any(token != extension_token for token in tokens):
                        return True

        return False


def get_wordlist_backend(name: str | None = None) -> WordlistBackend:
    backend = name or options["wordlist_backend"]
    if backend == "auto" and options["request_backend"] == "native":
        try:
            return NativeWordlistBackend()
        except WordlistBackendUnavailableError:
            # Requester initialization owns the actionable native install error.
            # Keeping auto wordlist selection non-fatal preserves that lazy path.
            return PythonWordlistBackend()
    if backend in ("auto", "python"):
        return PythonWordlistBackend()
    if backend == "native":
        return NativeWordlistBackend()
    raise ValueError(f"Unknown wordlist backend: {backend}")
