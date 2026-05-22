from __future__ import annotations

import re
from typing import Protocol

from lib.core.data import options
from lib.core.exceptions import WordlistBackendUnavailableError, WordlistLimitError
from lib.core.settings import (
    EXCLUDE_OVERWRITE_EXTENSIONS,
    EXTENSION_RECOGNITION_REGEX,
    EXTENSION_TAG,
)
from lib.core.structures import OrderedSet
from lib.core.wordlist_template import TOKEN_RE, expand_template_line
from lib.parse.url import clean_path
from lib.utils.common import lstrip_once
from lib.utils.file import FileUtils


WORDLIST_BACKENDS = ("auto", "python", "native")


class WordlistBackend(Protocol):
    name: str

    def generate(self, files: list[str], is_blacklist: bool = False) -> list[str]:
        pass


class PythonWordlistBackend:
    name = "python"

    def generate(self, files: list[str], is_blacklist: bool = False) -> list[str]:
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
                        and not line.endswith(options["extensions"] + EXCLUDE_OVERWRITE_EXTENSIONS)
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
            raise WordlistBackendUnavailableError(
                "Native wordlist backend is not available. "
                "Build it with: python3 -m maturin develop --manifest-path native/Cargo.toml"
            ) from e

        self._native = dirsearch_native

    def generate(self, files: list[str], is_blacklist: bool = False) -> list[str]:
        if is_blacklist or self._requires_python_template_expansion(files):
            return PythonWordlistBackend().generate(files, is_blacklist=is_blacklist)

        return self._native.generate_wordlist(
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

    def _requires_python_template_expansion(self, files: list[str]) -> bool:
        extension_token = EXTENSION_TAG.strip("%").upper()
        for dict_file in files:
            with open(dict_file, "r", errors="replace") as handle:
                for line in handle:
                    if "%" not in line:
                        continue

                    tokens = {token.upper() for token in TOKEN_RE.findall(line)}
                    if any(token != extension_token for token in tokens):
                        return True

        return False


def get_wordlist_backend(name: str | None = None) -> WordlistBackend:
    backend = name or options["wordlist_backend"]
    if backend in ("auto", "python"):
        return PythonWordlistBackend()
    if backend == "native":
        return NativeWordlistBackend()
    raise ValueError(f"Unknown wordlist backend: {backend}")
