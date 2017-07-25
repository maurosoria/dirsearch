dirsearch
=========

Current Release: v0.3.8 (2017.07.25)


Overview
--------
dirsearch is a simple command line tool designed to brute force directories and files in websites.


Operating Systems supported
---------------------------
- Windows XP/7/8/10
- GNU/Linux
- MacOSX

Features
--------
- Multithreaded
- Keep alive connections
- Support for multiple extensions (-e|--extensions asp,php)
- Reporting (plain text, JSON)
- Heuristically detects invalid web pages
- Recursive brute forcing
- HTTP proxy support
- User agent randomization
- Batch processing
- Request delaying

About wordlists
---------------
Dictionaries must be text files. Each line will be processed as such, except that the special word %EXT% is used, which will generate one entry for each extension (-e | --extension) passed as an argument.

Example:
- example/
- example.%EXT%

Passing the extensions "asp" and "aspx" will generate the following dictionary:
- example/
- example.asp
- example.aspx

You can also use -f | --force-extensions switch to append extensions to every word in the wordlists (like DirBuster).

License
-------
Copyright (C) Mauro Soria (maurosoria at gmail dot com)

License: GNU General Public License, version 2


Contributors
---------
Special thanks for these people.

- Bo0oM
- liamosaur
- redshark1802
- SUHAR1K
- FireFart
- k2l8m11n2
- vlohacks
