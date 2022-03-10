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

import subprocess
import sys
import pkg_resources

from lib.core.exceptions import FailedDependenciesInstallation
from lib.core.settings import SCRIPT_PATH
from lib.utils.file import FileUtils

REQUIREMENTS_FILE = f"{SCRIPT_PATH}/requirements.txt"


def get_dependencies():
    try:
        return FileUtils.get_lines(REQUIREMENTS_FILE)
    except FileNotFoundError:
        print("Can't find requirements.txt")
        exit(1)


# Check if all dependencies are satisfied
def check_dependencies():
    pkg_resources.require(get_dependencies())


def install_dependencies():
    try:
        subprocess.check_output(
            [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS_FILE],
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError:
        raise FailedDependenciesInstallation
