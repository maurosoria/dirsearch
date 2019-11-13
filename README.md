dirsearch
=========

Current Release: v0.3.8 (2017.07.25)


Overview
--------
dirsearch is a simple command line tool designed to brute force directories and files in websites.


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
    -L URLLIST, --url-list=URLLIST
                        URL list target
    -e EXTENSIONS, --extensions=EXTENSIONS
                        Extension list separated by comma (Example: php,asp)

  Dictionary Settings:
    -w WORDLIST, --wordlist=WORDLIST
    -l, --lowercase     
    -f, --force-extensions
                        Force extensions for every wordlist entry (like in
                        DirBuster)

  General Settings:
    -s DELAY, --delay=DELAY
                        Delay between requests (float number)
    -r, --recursive     Bruteforce recursively
    --suppress-empty, --suppress-empty
    --scan-subdir=SCANSUBDIRS, --scan-subdirs=SCANSUBDIRS
                        Scan subdirectories of the given -u|--url (separated
                        by comma)
    --exclude-subdir=EXCLUDESUBDIRS, --exclude-subdirs=EXCLUDESUBDIRS
                        Exclude the following subdirectories during recursive
                        scan (separated by comma)
    --exclude-texts='Not found', 'Error'
                        Exclude results by text in response        
    --exclude-regexps='Not foun[a-z]{1}', '^Error$'
                        Exclude results by text regexp in response                             
    -t THREADSCOUNT, --threads=THREADSCOUNT
                        Number of Threads
    -x EXCLUDESTATUSCODES, --exclude-status=EXCLUDESTATUSCODES
                        Exclude status code, separated by comma (example: 301,
                        500)
    -c COOKIE, --cookie=COOKIE
    --ua=USERAGENT, --user-agent=USERAGENT
    -F, --follow-redirects
    -H HEADERS, --header=HEADERS
                        Headers to add (example: --header "Referer:
                        example.com" --header "User-Agent: IE"
    --random-agents, --random-user-agents

  Connection Settings:
    --timeout=TIMEOUT   Connection timeout
    --ip=IP             Resolve name to IP address
    --proxy=HTTPPROXY, --http-proxy=HTTPPROXY
                        Http Proxy (example: localhost:8080
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
Copyright (C) Mauro Soria (maurosoria at gmail dot com)

License: GNU General Public License, version 2


Contributors
---------
Special thanks for these people.

- mzfr
- Damian89
- Bo0oM
- liamosaur
- redshark1802
- SUHAR1K
- FireFart
- k2l8m11n2
- vlohacks
- r0p0s3c
