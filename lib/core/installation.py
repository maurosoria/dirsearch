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
import subprocess
from importlib import metadata
from packaging import requirements, version

from lib.core.exceptions import FailedDependenciesInstallation, DistributionNotFound, VersionConflict


def get_dependencies():
    """Get list of required dependencies from requirements.txt"""
    deps = []
    try:
        with open("requirements.txt", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    deps.append(line)
    except FileNotFoundError:
        pass
    
    return deps


def check_dependencies() -> None:
    """Check if all required dependencies are installed with correct versions"""
    deps = get_dependencies()
    missing = []
    conflicts = []
    
    for dep_str in deps:
        try:
            # Parse the requirement
            req = requirements.Requirement(dep_str)
            
            try:
                # Check if the package is installed
                dist = metadata.distribution(req.name)
                installed_version = version.parse(dist.version)
                
                # Check if the installed version satisfies the requirement
                if req.specifier and installed_version not in req.specifier:
                    conflicts.append(f"{req.name} {req.specifier} is required but {installed_version} is installed")
                    
            except metadata.PackageNotFoundError:
                missing.append(str(req))
                
        except Exception as e:
            # If we can't parse the requirement, skip it
            print(f"Warning: Could not parse requirement '{dep_str}': {e}")
            continue
    
    if missing:
        raise DistributionNotFound(f"Missing required dependencies: {', '.join(missing)}")
    
    if conflicts:
        raise VersionConflict(f"Version conflicts found: {'; '.join(conflicts)}")


def install_dependencies() -> None:
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    except subprocess.CalledProcessError:
        raise FailedDependenciesInstallation
