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
    --pref=PREFIXES, --prefixes=PREFIXES
                        Add custom prefixes to all entries (separated by
                        comma)
    --suff=SUFFIXES, --suffixes=SUFFIXES
                        Add custom suffixes to all entries, ignores
                        directories (separated by comma)
    -f, --force-extensions
                        Force extensions for every wordlist entry. Add
                        %NOFORCE% at the end of the entry that you do not want
                        to force in the wordlist
    --nd, --no-dot-extensions
                        Don't add a '.' character before extensions
    -L, --lowercase
    -U, --uppercase

  General Settings:
    -d DATA, --data=DATA
                        HTTP request data (POST, PUT, ... body)
    -s DELAY, --delay=DELAY
                        Delay between requests (float number)
    -r, --recursive     Bruteforce recursively
    -R RECURSIVE_LEVEL_MAX, --recursive-level-max=RECURSIVE_LEVEL_MAX
                        Max recursion level (subdirs) (Default: 1 [only
                        rootdir + 1 dir])
    --suppress-empty, --suppress-empty
    --min=MINIMUMRESPONSESIZE
                        Minimal response length
    --max=MAXIMUMRESPONSESIZE
                        Maximal response length
    --scan-subdir=SCANSUBDIRS, --scan-subdirs=SCANSUBDIRS
                        Scan subdirectories of the given -u|--url (separated
                        by comma)
    --exclude-subdir=EXCLUDESUBDIRS, --exclude-subdirs=EXCLUDESUBDIRS
                        Exclude the following subdirectories during recursive
                        scan (separated by comma)
    -t THREADSCOUNT, --threads=THREADSCOUNT
                        Number of Threads
    -i INCLUDESTATUSCODES, --include-status=INCLUDESTATUSCODES
                        Show only included status codes, separated by comma
                        (example: 301, 500)
    -x EXCLUDESTATUSCODES, --exclude-status=EXCLUDESTATUSCODES
                        Exclude status code, separated by comma (example: 301,
                        500)
    --exclude-texts=EXCLUDETEXTS
                        Exclude responses by texts, separated by comma
                        (example: "Not found", "Error")
    --exclude-regexps=EXCLUDEREGEXPS
                        Exclude responses by regexps, separated by comma
                        (example: "Not foun[a-z]{1}", "^Error$")
    -c COOKIE, --cookie=COOKIE
    --ua=USERAGENT, --user-agent=USERAGENT
    -F, --follow-redirects
    -H HEADERS, --header=HEADERS
                        Headers to add (example: --header "Referer:
                        example.com" --header "User-Agent: IE")
    --random-agents, --random-user-agents
    --clean-view, --clean-view
    --full-url, --full-url

  Connection Settings:
    --timeout=TIMEOUT   Connection timeout
    --ip=IP             Resolve name to IP address
    --proxy=HTTPPROXY, --http-proxy=HTTPPROXY
                        Http Proxy (example: localhost:8080)
    --proxylist=PROXYLIST, --http-proxy-list=PROXYLIST
                        Path to file containg http proxy servers.
    -m HTTPMETHOD, --http-method=HTTPMETHOD
                        Method to use, default: GET
    --max-retries=MAXRETRIES
    -b, --request-by-hostname
                        By default dirsearch will request by IP for speed.
                        This forces requests by hostname

  Reports:
    --simple-report=SIMPLEOUTPUTFILE
                        Only found paths
    --plain-text-report=PLAINTEXTOUTPUTFILE
                        Found paths with status codes
    --json-report=JSONOUTPUTFILE
```


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
- Quiet mode
- Option to force requests by hostname
- Option to exclude responses by texts
- Option to exclude responses by regexps (example: "Not foun[a-z]{1}")
- Option to remove dot from extension when forcing (--nd, example%EXT% instead of example.%EXT%)
- Options to display only items with response length from range (--min & --max)
- Option to whitelist response codes (-i 200,500)
- Option to blacklist response codes (-x 404,403)
- Option to remove output from console (-q, keeps output to files)
- Option to add custom suffixes to filenames without dots (--suff .BAK,.old, example.%EXT%%SUFFIX%)

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
python3 dirsearch.py -E -u https://target -w db/dicc.txt
```

```
python3 dirsearch.py -E -u https://target --recursive -R 2
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --recursive -R 4 --scan-subdirs=/,/wp-content/,/wp-admin/
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --exclude-texts=This,AndThat
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt -H "User-Agent: IE"
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt -t 20
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
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --plain-text-report=reports/target-paths-and-status.json
```

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

Special thanks for these people.

- @mzfr
- @V-Rico
- @Damian89
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
