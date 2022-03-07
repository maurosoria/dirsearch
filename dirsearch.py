#!/usr/bin/env python3
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

from pkg_resources import DistributionNotFound, VersionConflict

from lib.core.exceptions import FailedDependenciesInstallation
from lib.core.installation import check_dependencies, install_dependencies

if sys.version_info < (3, 7):
    sys.stdout.write("Sorry, dirsearch requires Python 3.7 or higher\n")
    sys.exit(1)

try:
    check_dependencies()
except (DistributionNotFound, VersionConflict):
    print("Installing required dependencies to run dirsearch...")

    try:
        install_dependencies()
    except FailedDependenciesInstallation:
        msg = "Failed to install required dependencies, try doing "
        msg += "it manually by: pip install -r requirements.txt"
        print(msg)
        exit(1)


def main():
    from lib.core.options import options

    options = options()

    from lib.controller.controller import Controller

    if options["quiet"]:
        from lib.output.silent import Output
    else:
        from lib.output.verbose import Output

    output = Output(options["color"])

    Controller(options, output)


if __name__ == "__main__":
    main()
