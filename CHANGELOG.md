# Changelog

## [Unreleased]

## [0.4.3] - October 2nd, 2022
- Automatically detect the URI scheme (`http` or `https`) if no scheme is provided
- SQLite report format
- Option to overwrite unwanted extensions with selected extensions
- Option to view redirects history when following redirects
- Option to crawl web paths in the responses
- HTTP traffic is saved inside log file
- Capability to save progress and resume later
- Support client certificate
- Maximum size of the log file via configuration

## [0.4.2] - September 12, 2021
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

## [0.4.1] - August 12, 2020
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

## [0.4.0] - September 27, 2020
- Exclude extensions argument added
- No dot extensions option
- Support HTTP request data
- Added minimal response length and maximal response length arguments
- Added include status codes and exclude status codes arguments
- Added --clean-view option
- Added option to print the full URL in the output
- Added Prefixes and Suffixes arguments
- Multiple bugfixes

## [0.3.9] - November 26, 2019
- Added default extensions argument (-E).
- Added suppress empty responses.
- Recursion max depth.
- Exclude responses with text and regexes.
- Multiple fixes.

## [0.3.8] - July 25, 2017
- Delay argument added.
- Request by hostname switch added.
- Suppress empty switch added.
- Added Force Extensions switch.
- Multiple bugfixes.

## [0.3.7] - August 22, 2016
- Force extensions switch added

## [0.3.6] - February 14, 2016
- Bugfixes

## [0.3.5] - January 29, 2016
- Improved heuristic
- Replaced urllib3 for requests 
- Error logs
- Batch reports 
- User agent randomization 
- bugfixes

## [0.3.0] - February 5, 2015
- Fixed issue3
- Fixed timeout exception
- Ported to Python3
- Other bugfixes

## [0.2.7] - November 21, 2014
- Added Url List feature (-l)
- Changed output
- Minor Fixes

## [0.2.6] - September 12, 2014
- Fixed bug when dictionary size is greater than threads count
- Fixed URL encoding bug

## [0.2.5] - September 2, 2014
- Shows Content-Length in output and reports
- Added default.conf file (for setting defaults)
- Report auto save feature added.

## [0.2.4] - July 17, 2014
- Added Windows support
- `--scan-subdirs` argument added
- `--exclude-subdirs` added
- `--header` argument added
- Dirbuster dictionaries added
- Fixed some concurrency bugs
- MVC refactoring

## 0.2.3 - July 7, 2014
- Fixed some bugs
- Minor refactorings
- Exclude status switch
- Pause/next directory feature
- Changed help structure
- Expaded default dictionary

## 0.2.2 - July 2, 2014
- Fixed some bugs
- Showing percentage of tested paths and added report generation feature

## 0.2.1 - May 1, 2014
- Fixed some bugs and added recursive option

## 0.2.0 - January 31, 2014
- Initial public release

[Unreleased]: https://github.com/maurosoria/dirsearch/tree/master
[0.4.3]: https://github.com/maurosoria/dirsearch/tree/v0.4.3
[0.4.2]: https://github.com/maurosoria/dirsearch/tree/v0.4.2
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
