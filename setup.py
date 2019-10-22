#!/usr/bin/env python3

from setuptools import setup
import setuptools
import io
import os
import sys

# Package meta-data
NAME = 'dirsearch'
DESCRIPTION = 'A simple command line tool designed to brute force directories and files in websites.'
URL = 'https://github.com/maurosoria/dirsearch'
AUTHOR = 'Mauro Soria'
VERSION = '0.3.8'

here = os.path.abspath(os.path.dirname(__file__))

with io.open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = '\n' + f.read()

setup(
    name=NAME,
    version=VERSION,
    description=DESCRIPTION,
    long_description=long_description,
    long_description_content_type="text/markdown",
    author=AUTHOR,
    url=URL,
    packages=setuptools.find_packages(),
    data_files=[
        ('', ['default.conf']), 
        ('db', [
            'db/400_blacklist.txt',
            'db/403_blacklist.txt',
            'db/500_blacklist.txt',
            'db/dicc.txt',
            'db/user-agents.txt'
            ]
        ),
        ('lib/controller', ['lib/controller/banner.txt'])
    ],
    entry_points={
        'console_scripts':[
            'dirsearch = lib.cli:run_as_command',
        ],
    },
    license='GPLv2',
    classifiers=[
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
    ],
)
