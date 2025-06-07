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
import warnings

from lib.core.data import options
from lib.core.exceptions import FailedDependenciesInstallation
from lib.core.installation import check_dependencies, install_dependencies
from lib.core.settings import OPTIONS_FILE
from lib.parse.config import ConfigParser

if sys.version_info < (3, 9):
    sys.stderr.write("Sorry, dirsearch requires Python 3.9 or higher\n")
    sys.exit(1)

# silence pkg_resources deprecation warnings

# Import custom exceptions instead of pkg_resources
from lib.core.exceptions import DistributionNotFound, VersionConflict  # noqa: E402


def main():
    config = ConfigParser()
    config.read(OPTIONS_FILE)

    if config.safe_getboolean("options", "check-dependencies", False):
        try:
            check_dependencies()
        except (DistributionNotFound, VersionConflict):
            option = input("Missing required dependencies to run.\n"
                           "Do you want dirsearch to automatically install them? [Y/n] ")

            if option.lower() == 'y':
                print("Installing required dependencies...")

                try:
                    install_dependencies()
                except FailedDependenciesInstallation:
                    sys.stderr.write("Failed to install dirsearch dependencies, try doing it manually.\n")
                    sys.exit(1)
            else:
                # Do not check for dependencies in the future
                config.set("options", "check-dependencies", "False")

                with open(OPTIONS_FILE, "w") as fh:
                    config.write(fh)

    from lib.core.options import parse_options

    options.update(parse_options())

    if options["session_file"]:
        print("WARNING: Running an untrusted session file might lead to unwanted code execution!")
        if input("[c]ontinue / [q]uit: ") != "c":
            exit(1)

    from lib.controller.controller import Controller

    Controller()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
