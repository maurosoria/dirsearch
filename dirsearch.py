#!/usr/bin/env python3
#
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

import sys

from lib.core.api import (
    DirsearchFuzzer,
    FuzzerConfig,
    FuzzerResult,
    PreflightResult,
    Wordlist,
    WordlistState,
    WordlistTemplate,
)
from lib.core.data import options
from lib.core.exceptions import WordlistLimitError
from lib.core.options import parse_options

__all__ = [
    "main",
    "DirsearchFuzzer",
    "FuzzerConfig",
    "FuzzerResult",
    "PreflightResult",
    "Wordlist",
    "WordlistState",
    "WordlistTemplate",
]

if sys.version_info < (3, 11):
    sys.stderr.write("Sorry, dirsearch requires Python 3.11 or higher\n")
    sys.exit(1)


def main():
    options.update(parse_options())

    if options["wordlist_status"]:
        from lib.core.dictionary import Dictionary

        try:
            dictionary = Dictionary(files=options["wordlists"])
        except WordlistLimitError as error:
            print(str(error))
            sys.exit(1)

        print("Wordlist status")
        print(f"Files: {len(options['wordlists'])}")
        for wordlist in options["wordlists"]:
            print(f"- {wordlist}")
        print(f"Generated entries: {len(dictionary)}")
        print(f"Generation limit: {options['wordlist_max_size']}")
        sys.exit(0)

    if options["session_file"]:
        print("Loading a session file will override current options.")
        if input("[c]ontinue / [q]uit: ") != "c":
            exit(1)

    from lib.controller.controller import Controller

    Controller()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
