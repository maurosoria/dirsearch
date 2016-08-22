dirsearch
=========

Current Release: v0.3.7 (2016.08.22)


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

Changelog
---------
- 0.3.7 - 2016.08.22 Force extensions switch added.
- 0.3.6 - 2016.02.14 Bugfixes
- 0.3.5 - 2016.01.29 Improved heuristic, replaced urllib3 for requests, error logs, batch reports, user agent randomization, bugfixes
- 0.3.0 - 2015.02.05 Fixed issue3, fixed timeout exception, ported to Python3, other bugfixes
- 0.2.7 - 2014.11.21 Added Url List feature (-L). Changed output. Minor Fixes
- 0.2.6 - 2014.9.12 Fixed bug when dictionary size is greater than threads count. Fixed URL encoding bug (issue2).
- 0.2.5 - 2014.9.2 Shows Content-Length in output and reports, added default.conf file (for setting defaults) and report auto save feature added.
- 0.2.4 - 2014.7.17 Added Windows support, --scan-subdir|--scan-subdirs argument added, --exclude-subdir|--exclude-subdirs added, --header argument added, dirbuster dictionaries added, fixed some concurrency bugs, MVC refactoring
- 0.2.3 - 2014.7.7 Fixed some bugs, minor refactorings, exclude status switch, "pause/next directory" feature, changed help structure, expaded default dictionary
- 0.2.2 - 2014.7.2 Fixed some bugs, showing percentage of tested paths and added report generation feature
- 0.2.1 - 2014.5.1 Fixed some bugs and added recursive option
- 0.2.0 - 2014.1.31 Initial public release

Contributors
---------
- Bo0oM


