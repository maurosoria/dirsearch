# Changelog

## [0.4.3]
- Automatically detect the URI scheme (http or https) if no scheme is provided

## [0.4.2] - 2021.9.12
- More accurate
- Exclude responses by redirects
- URLs from STDIN
- Fixed the CSV Injection vulnerability (https://www.exploit-db.com/exploits/49370)
- Raw request supported
- Can setup the default URL scheme (will be used when there is no scheme in the URL)
- Added max runtime option
- Recursion on specified status codes
- Max request rate
- Support several authentication types
- Deep/forced recursive scan
- HTML report format
- Option to skip target by specified status codes
- Bug fixes

## [0.4.1] - 2020.12.8
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

## [0.4.0] - 2020.09.27
- Exclude extensions argument added
- No dot extensions option
- Support HTTP request data
- Added minimal response length and maximal response length arguments
- Added include status codes and exclude status codes arguments
- Added --clean-view option
- Added option to print the full URL in the output
- Added Prefixes and Suffixes arguments
- Multiple bugfixes

## [0.3.9] - 2019.11.26
- Added default extensions argument (-E).
- Added suppress empty responses.
- Recursion max depth.
- Exclude responses with text and regexes.
- Multiple fixes.

## [0.3.8] - 2017.07.25
- Delay argument added.
- Request by hostname switch added.
- Suppress empty switch added.
- Added Force Extensions switch.
- Multiple bugfixes.

## [0.3.7] - 2016.08.22
- Force extensions switch added

## [0.3.6] - 2016.02.14
- Bugfixes

## [0.3.5] - 2016.01.29
- Improved heuristic
- Replaced urllib3 for requests 
- Error logs
- Batch reports 
- User agent randomization 
- bugfixes

## [0.3.0] - 2015.02.05
- Fixed issue3
- Fixed timeout exception
- Ported to Python3
- Other bugfixes

## [0.2.7] - 2014.11.21
- Added Url List feature (-l)
- Changed output
- Minor Fixes

## [0.2.6] - 2014.9.12
- Fixed bug when dictionary size is greater than threads count
- Fixed URL encoding bug

## [0.2.5] - 2014.9.2
- Shows Content-Length in output and reports
- Added default.conf file (for setting defaults)
- Report auto save feature added.

## [0.2.4] - 2014.7.17
- Added Windows support
- `--scan-subdirs` argument added
- `--exclude-subdirs` added
- `--header` argument added
- Dirbuster dictionaries added
- Fixed some concurrency bugs
- MVC refactoring

## [0.2.3] - 2014.7.7
- Fixed some bugs
- Minor refactorings
- Exclude status switch
- Pause/next directory feature
- Changed help structure
- Expaded default dictionary

## [0.2.2] - 2014.7.2
- Fixed some bugs
- Showing percentage of tested paths and added report generation feature

## 0.2.1 - 2014.5.1
- Fixed some bugs and added recursive option

## 0.2.0 - 2014.1.31
- Initial public release

[Unreleased]: https://github.com/maurosoria/dirsearch/tree/master
[0.4.1]: https://github.com/maurosoria/dirsearch/tree/v0.4.1
[0.4.0]: https://github.com/maurosoria/dirsearch/tree/v0.4.0
[0.3.9]: https://github.com/maurosoria/dirsearch/tree/v0.3.9
[0.3.8]: https://github.com/maurosoria/dirsearch/tree/v0.3.8
[0.3.7]: https://github.com/maurosoria/dirsearch/tree/v0.3.7
[0.3.6]: https://github.com/maurosoria/dirsearch/tree/v0.3.6
[0.3.5]: https://github.com/maurosoria/dirsearch/tree/v0.3.5
[0.3.0]: https://github.com/maurosoria/dirsearch/tree/v0.3.0
[0.2.7]: https://github.com/maurosoria/dirsearch/tree/v0.2.7
[0.2.6]: https://github.com/maurosoria/dirsearch/tree/v0.2.6
[0.2.5]: https://github.com/maurosoria/dirsearch/tree/v0.2.5
[0.2.4]: https://github.com/maurosoria/dirsearch/tree/v0.2.4
[0.2.3]: https://github.com/maurosoria/dirsearch/tree/v0.2.3
[0.2.2]: https://github.com/maurosoria/dirsearch/tree/v0.2.2
