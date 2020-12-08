# Changelog

v0.4.1 (2020.12.8)
---------
- Faster
- Allow to brute force through a CIDR notation
- Exclude responses by human readable sizes
- Provide headers from a file
- Match/filter status codes by ranges
- Detect 429 response status code
- Support SOCKS proxy
- XML, Markdown and CSV report formats
- Capital wordlist format
- Option to replay proxy with found paths
- Option to remove all extensions in the wordlist
- Option to exit whenever an error occurs
- Option to disable colored output
- Debug mode
- Multiple bugfixes

---------

0.4.0 - 2020.09.27
---------
- Exclude extensions argument added
- No dot extensions option
- Support HTTP request data
- Added minimal response length and maximal response length arguments
- Added include status codes and exclude status codes arguments
- Added --clean-view option
- Added option to print the full URL in the output
- Added Prefixes and Suffixes arguments
- Multiple bugfixes

---------

0.3.9 - 2019.11.26
---------
- Added default extensions argument (-E).
- Added suppress empty responses.
- Recursion max depth.
- Exclude responses with text and regexes.
- Multiple fixes.

---------

0.3.8 - 2017.07.25
---------
- Delay argument added.
- Request by hostname switch added.
- Suppress empty switch added.
- Added Force Extensions switch.
- Multiple bugfixes.

---------

0.3.7 - 2016.08.22
---------
- Force extensions switch added

---------

0.3.6 - 2016.02.14
---------
- Bugfixes

---------

0.3.5 - 2016.01.29
---------
- Improved heuristic
- Replaced urllib3 for requests 
- Error logs
- Batch reports 
- User agent randomization 
- bugfixes

---------

0.3.0 - 2015.02.05
---------
- Fixed issue3
- Fixed timeout exception
- Ported to Python3
- Other bugfixes

---------

0.2.7 - 2014.11.21
---------
- Added Url List feature (-l)
- Changed output
- Minor Fixes

---------

- 0.2.6 - 2014.9.12 Fixed bug when dictionary size is greater than threads count. Fixed URL encoding bug (issue2).
- 0.2.5 - 2014.9.2 Shows Content-Length in output and reports, added default.conf file (for setting defaults) and report auto save feature added.
- 0.2.4 - 2014.7.17 Added Windows support, --scan-subdir|--scan-subdirs argument added, --exclude-subdir|--exclude-subdirs added, --header argument added, dirbuster dictionaries added, fixed some concurrency bugs, MVC refactoring
- 0.2.3 - 2014.7.7 Fixed some bugs, minor refactorings, exclude status switch, "pause/next directory" feature, changed help structure, expaded default dictionary
- 0.2.2 - 2014.7.2 Fixed some bugs, showing percentage of tested paths and added report generation feature
- 0.2.1 - 2014.5.1 Fixed some bugs and added recursive option
- 0.2.0 - 2014.1.31 Initial public release
