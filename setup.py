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

import ast
from pathlib import Path

import setuptools


ROOT = Path(__file__).resolve().parent
PACKAGE_DATA_EXCLUDED_NAMES = {"__pycache__", "target"}
PACKAGE_DATA_EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pyd"}


def package_files(directory: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if set(relative.parts) & PACKAGE_DATA_EXCLUDED_NAMES:
            continue
        if path.suffix in PACKAGE_DATA_EXCLUDED_SUFFIXES:
            continue
        if path.is_file():
            files.append(str(path.relative_to(ROOT)))
    return files


def package_names() -> list[str]:
    packages = ["dirsearch"]
    packages.extend(
        f"dirsearch.{package}"
        for package in setuptools.find_packages(include=("lib", "lib.*"))
    )
    return packages


def read_version(path: Path) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "VERSION":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str):
                        return value
    raise RuntimeError(f"Unable to find VERSION in {path}")


def read_requirements(path: Path) -> list[str]:
    requirements: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        requirement = line.strip()
        if requirement and not requirement.startswith("#"):
            requirements.append(requirement)
    return requirements


setuptools.setup(
    name="dirsearch",
    description="Advanced web path scanner",
    version=read_version(ROOT / "lib/core/settings.py"),
    python_requires=">=3.11",
    classifiers=[
        "Programming Language :: Python",
        "Environment :: Console",
        "Intended Audience :: Information Technology",
        "Operating System :: OS Independent",
        "Topic :: Security",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ],
    install_requires=read_requirements(ROOT / "requirements/runtime.txt"),
    extras_require={
        "mysql": ["mysql-connector-python==9.6.0"],
        "postgresql": ["psycopg[binary]==3.3.3"],
        "db": read_requirements(ROOT / "requirements/db.txt"),
    },
    entry_points={
        "console_scripts": [
            "dirsearch=dirsearch.dirsearch:main",
            "dirsearch-build-native=dirsearch.lib.core.native_builder:main",
        ]
    },
    packages=package_names(),
    package_dir={
        "dirsearch": ".",
        "dirsearch.lib": "lib",
    },
    package_data={
        "dirsearch": [
            "config.ini",
            *package_files(ROOT / "db"),
            *package_files(ROOT / "native"),
        ],
        "dirsearch.lib.report": ["templates/*.html"],
    },
    include_package_data=False,
)
