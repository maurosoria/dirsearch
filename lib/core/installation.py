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

from __future__ import annotations

import subprocess
import sys
import importlib.metadata

from lib.core.exceptions import FailedDependenciesInstallation, MissingDependencies
from lib.core.settings import SCRIPT_PATH
from lib.utils.file import FileUtils

REQUIREMENTS_FILE = f"{SCRIPT_PATH}/requirements.txt"


# Return 1 if a > b, -1 if a < b and 0 if a == b
def compare_versions(a, b):
    pa = [int(x) for x in a.split(".")]
    pb = [int(x) for x in b.split(".")]
    return (pa > pb) - (pa < pb)


def get_dependencies() -> list[str]:
    try:
        return [
            line.replace(" ", "")
            for line in FileUtils.get_lines(REQUIREMENTS_FILE)
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except FileNotFoundError:
        print("Can't find requirements.txt")
        exit(1)


# Check if all dependencies are satisfied
def check_dependencies() -> None:
    for pkg in get_dependencies():
        pkg_name = pkg.split("[")[0]

        try:
            installed_version = importlib.metadata.version(pkg_name)
        except importlib.metadata.PackageNotFoundError:
            raise MissingDependencies

        # Check if installed version satisfies the requirement
        required_version = pkg.split("]")[-1].split(pkg_name)[-1].lstrip("<>!=~")
        if (
            ("=" in pkg and "!" not in pkg and required_version == installed_version)
            or (">" in pkg and compare_versions(required_version, installed_version) == 1)
            or ("<" in pkg and compare_versions(required_version, installed_version) == -1)
            or (
                "~" in pkg
                and compare_versions(required_version, installed_version) == 1
                and required_version.split(".")[0] == installed_version.split(".")[0]
            )
        ):
            continue

        raise MissingDependencies


def install_dependencies() -> None:
    try:
        subprocess.check_output(
            [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS_FILE],
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError:
        raise FailedDependenciesInstallation
