dirsearch
=========

Current Release: v0.4.0 (2020.9.25)


Overview
--------
dirsearch is an advanced command line tool designed to brute force directories and files in webservers.


Installation & Usage
------------

```
git clone https://github.com/maurosoria/dirsearch.git
cd dirsearch
python3 dirsearch.py -u <URL> -e <EXTENSION>
```

you can also use this alias to send directly to proxy
`python3 /path/to/dirsearch/dirsearch.py --http-proxy=localhost:8080`


Options
-------


```
Options:
  -h, --help            show this help message and exit

  Mandatory:
    -u URL, --url=URL   URL target
    -l URLLIST, --url-list=URLLIST
                        URL list target
    -e EXTENSIONS, --extensions=EXTENSIONS
                        Extensions list separated by comma (Example: php,asp)
    -E, --extensions-list
                        Use predefined list of common extensions
    -X EXCLUDEEXTENSIONS, --exclude-extensions=EXCLUDEEXTENSIONS
                        Exclude extensions list, separated by comma (Example:
                        asp,jsp)

  Dictionary Settings:
    -w WORDLIST, --wordlist=WORDLIST
                        Customize wordlist (separated by comma)
    --prefixes=PREFIXES
                        Add custom prefixes to all entries (separated by
                        comma)
    --suffixes=SUFFIXES
                        Add custom suffixes to all entries, ignores
                        directories (separated by comma)
    -f, --force-extensions
                        Force extensions for every wordlist entry. Add
                        %NOFORCE% at the end of the entry in the wordlist that
                        you do not want to force
    --no-extension      Remove extensions in all entries (Example: admin.php
                        -> admin)
    --no-dot-extensions
                        Remove the "." character before extensions
    -U, --uppercase     Uppercase wordlist
    -L, --lowercase     Lowercase wordlist
    -C, --capitalization
                        Capital wordlist

  General Settings:
    -d DATA, --data=DATA
                        HTTP request data (POST, PUT, ... body)
    -s DELAY, --delay=DELAY
                        Delay between requests (support float number)
    -r, --recursive     Bruteforce recursively
    -R RECURSIVE_LEVEL_MAX, --recursive-level-max=RECURSIVE_LEVEL_MAX
                        Max recursion level (subdirs) (Default: 1 [only
                        rootdir + 1 dir])
    --suppress-empty    Suppress empty responses
    --minimal=MINIMUMRESPONSESIZE
                        Minimal response length
    --maximal=MAXIMUMRESPONSESIZE
                        Maximal response length
    --scan-subdir=SCANSUBDIRS, --scan-subdirs=SCANSUBDIRS
                        Scan subdirectories of the given URL (separated by
                        comma)
    --exclude-subdir=EXCLUDESUBDIRS, --exclude-subdirs=EXCLUDESUBDIRS
                        Exclude the following subdirectories during recursive
                        scan (separated by comma)
    -t THREADSCOUNT, --threads=THREADSCOUNT
                        Number of Threads
    -i INCLUDESTATUSCODES, --include-status=INCLUDESTATUSCODES
                        Show only included status codes, separated by comma
                        (example: 301, 500)
    -x EXCLUDESTATUSCODES, --exclude-status=EXCLUDESTATUSCODES
                        Do not show excluded status codes, separated by comma
                        (example: 301, 500)
    --exclude-texts=EXCLUDETEXTS
                        Exclude responses by texts, separated by comma
                        (example: "Not found", "Error")
    --exclude-regexps=EXCLUDEREGEXPS
                        Exclude responses by regexps, separated by comma
                        (example: "Not foun[a-z]{1}", "^Error$")
    -c COOKIE, --cookie=COOKIE
    --user-agent=USERAGENT
    -F, --follow-redirects
    -H HEADERS, --header=HEADERS
                        HTTP request headers, support multiple flags (example:
                        --header "Referer: example.com" --header "User-Agent:
                        IE")
    --full-url          Print the full URL in the output
    --random-agents, --random-user-agents
    -q, --quite-mode

  Connection Settings:
    --timeout=TIMEOUT   Connection timeout
    --ip=IP             Resolve name to IP address
    --proxy=HTTPPROXY, --http-proxy=HTTPPROXY
                        HTTP Proxy (example: localhost:8080)
    --proxylist=PROXYLIST, --http-proxy-list=PROXYLIST
                        File containg HTTP proxy servers
    -m HTTPMETHOD, --http-method=HTTPMETHOD
                        HTTP method, default: GET
    --max-retries=MAXRETRIES
    -b, --request-by-hostname
                        By default dirsearch will request by IP for speed.
                        This will force requests by hostname

  Reports:
    --simple-report=SIMPLEOUTPUTFILE
                        Only found paths
    --plain-text-report=PLAINTEXTOUTPUTFILE
                        Found paths with status codes
    --json-report=JSONOUTPUTFILE
```

 NOTE: 
 You can change the dirsearch default configurations (default extensions, timeout, wordlist location, ...) by editing the "default.conf" file.

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
- Support for every HTTP method
- Support for HTTP request data
- Extensions excluding
- Reporting (plain text, JSON)
- Heuristically detects invalid web pages
- Recursive brute forcing
- Subdirectories brute forcing
- Force extensions
- HTTP proxy support
- HTTP cookies and headers support
- User agent randomization
- Batch processing
- Request delaying
- Multiple wordlist formats (lowercase, uppercase, capitalization)
- Quiet mode
- Option to force requests by hostname
- Option to exclude responses by texts
- Option to exclude responses by regexps (example: "Not foun[a-z]{1}")
- Option to remove dot from extension when forcing
- Options to display only items with response length from range
- Option to whitelist response codes (-i 200,500)
- Option to blacklist response codes (-x 404,403)
- Option to add custom suffixes and prefixes
- ...


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


How to use
---------------

Some examples how to use dirsearch - those are the most common arguments. If you need all, just use the "-h" argument.
```
python3 dirsearch.py -E -u https://target
```

```
python3 dirsearch.py -E -u https://target --recursive -R 2
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --recursive -R 4 --scan-subdirs=/,/wp-content/
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --exclude-texts="404 Not Found"
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt -H "User-Agent: IE" -f
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt -t 40 -f
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --random-agents
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --json-report=reports/target.json
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --simple-report=reports/target-paths.txt
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --json-report=reports/report.json
```

Tips
---------------
- Want to run dirsearch with a rate of requests per second? Try `-t <rate> -s 1`
- Want to findout config files or backups? Try `--suffixes ~` and `--prefixes .`
- Don't want to force extensions on some endpoints? Add `%NOFORCE` at the end of them so dirsearch won't do that

## Support Docker
### Install Docker Linux
Install Docker
```sh
curl -fsSL https://get.docker.com | bash
```
> To use docker you need superuser power

### Build Image dirsearch
To create image
```sh
docker build -t "dirsearch:v0.3.8" .
```
> **dirsearch** this is name the image and **v0.3.8** is version

### Using dirsearch
For using
```sh
docker run -it --rm "dirsearch:v0.3.8" -u target -e php,html,png,js,jpg
```
> target is the site or IP


License
-------
Copyright (C) Mauro Soria (maurosoria@gmail.com)

License: GNU General Public License, version 2


Contributors
---------
Main: @maurosoria and @shelld3v

Special thanks for these people:

- @V-Rico
- @mzfr
- @DustinTheGreat
- @danritter
- @Bo0oM
- @liamosaur
- @redshark1802
- @SUHAR1K
- @FireFart
- @k2l8m11n2
- @vlohacks
- @r0p0s3c
- @russtone
- @jsav0
- @serhattsnmz
- @ricardojba
- @Anon-Exploiter
- @ColdFusionX
