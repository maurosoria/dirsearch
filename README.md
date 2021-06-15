<img src="https://user-images.githubusercontent.com/59408894/120434511-c6aac580-c3a6-11eb-8d93-bf96e529fb94.png" width=675>


dirsearch - Web path discovery
=========

![Build](https://img.shields.io/badge/Built%20with-Python-Blue)
![License](https://img.shields.io/badge/license-GNU_General_Public_License-_red.svg)
![Release](https://img.shields.io/github/release/maurosoria/dirsearch.svg)
![Stars](https://img.shields.io/github/stars/maurosoria/dirsearch.svg)
<a href="https://twitter.com/intent/tweet?text=dirsearch%20-%20Web%20path%20scanner%20by%20@_maurosoria%0A%0Ahttps://github.com/maurosoria/dirsearch">
    ![Tweet](https://img.shields.io/twitter/url?url=https%3A%2F%2Fgithub.com%2Fmaurosoria%2Fdirsearch)
</a>

**Current Release: v0.4.2 (2021.7.21)**

An advanced command-line tool designed to brute force directories and files in webservers, AKA web path scanner

**dirsearch** is being actively developed by [@maurosoria](https://twitter.com/_maurosoria) and [@shelld3v](https://twitter.com/shells3c_)


Table of Contents
------------
* [Kali Linux](#Kali-Linux)
* [Installation](#Installation--Usage)
* [Wordlists](#Wordlists-IMPORTANT)
* [Options](#Options)
* [Configuration](#Configuration)
* [How to use](#How-to-use)
  * [Simple usage](#Simple-usage)
  * [Recursive scan](#Recursive-scan)
  * [Threads](#Threads)
  * [Prefixes / Suffixes](#Prefixes--Suffixes)
  * [Blacklist](#Blacklist)
  * [Filters](#Filters)
  * [Raw request](#Raw-request)
  * [Wordlist formats](#Wordlist-formats)
  * [Exclude extensions](#Exclude-extensions)
  * [Scan sub-directories](#Scan-sub-directories)
  * [Proxies](#Proxies)
  * [Reports](#Reports)
  * [Some others commands](#Some-others-commands)
* [Support Docker](#Support-Docker)
* [References](#References)
* [Tips](#Tips)
* [Contribution](#Contribution)
* [License](#License)


Kali Linux
------------
#### dirsearch is now available in official Kali Linux packages

![Kali Linux](https://www.redeszone.net/app/uploads-redeszone.net/2020/11/kali-linux-2020-4.jpg)


Installation & Usage
------------

**Requirement: python 3.7 or higher**

Choose one of these installation options:

- Install with git: `git clone https://github.com/maurosoria/dirsearch.git`
- Install with ZIP file: [Download here](https://github.com/maurosoria/dirsearch/archive/master.zip)
- Install with Docker: `docker build -t "dirsearch:v0.4.1"` ([more information](https://github.com/maurosoria/dirsearch#support-docker))
- Install with Kali Linux: `sudo apt-get install dirsearch`
- Install with PyPi: `pip3 install dirsearch`

Note: *To can use SOCKS proxy feature, please install packages with **requirements.txt**: `pip3 install -r requirements.txt`*

**All in one:**
```
git clone https://github.com/maurosoria/dirsearch.git
cd dirsearch
pip3 install -r requirements.txt
python3 dirsearch.py -u <URL> -e <EXTENSIONS>
```


Wordlists (IMPORTANT)
---------------
**Summary:**
  - Wordlist is a text file, each line is a path.
  - About extensions, unlike other tools, dirsearch only replaces the `%EXT%` keyword with extensions from **-e** flag.
  - For wordlists without `%EXT%` (like [SecLists](https://github.com/danielmiessler/SecLists)), **-f | --force-extensions** switch is required to append extensions to every word in wordlist, as well as the `/`. And for entries in wordlist that you do not want to append extensions, add `%NOFORCE%` at the end of them.
  - To use multiple wordlists, you can separate your wordlists with commas. Example: `wordlist1.txt,wordlist2.txt`.

**Examples:**

- Normal extensions
```
index.%EXT%
```

Passing **asp** and **aspx** extensions will generate the following dictionary:

```
index
index.asp
index.aspx
```

- Force extensions
```
admin
api%NOFORCE%
```

Passing "php" and "html" extensions with **-f**/**--force-extensions** flag will generate the following dictionary:

```
admin
admin.php
admin.html
admin/
api
```


Options
-------

```
Usage: dirsearch.py [-u|--url] target [-e|--extensions] extensions [options]

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit

  Mandatory:
    -u URL, --url=URL   Target URL
    -l FILE, --url-list=FILE
                        Target URL list file
    --stdin             Target URL list from STDIN
    --cidr=CIDR         Target CIDR
    --raw=FILE          Load raw HTTP request from file (use `--scheme` flag
                        to set the scheme)
    -e EXTENSIONS, --extensions=EXTENSIONS
                        Extension list separated by commas (Example: php,asp)
    -X EXTENSIONS, --exclude-extensions=EXTENSIONS
                        Exclude extension list separated by commas (Example:
                        asp,jsp)
    -f, --force-extensions
                        Add extensions to every wordlist entry. By default
                        dirsearch only replaces the %EXT% keyword with
                        extensions

  Dictionary Settings:
    -w WORDLIST, --wordlists=WORDLIST
                        Customize wordlists (separated by commas)
    --prefixes=PREFIXES
                        Add custom prefixes to all wordlist entries (separated
                        by commas)
    --suffixes=SUFFIXES
                        Add custom suffixes to all wordlist entries, ignore
                        directories (separated by commas)
    --only-selected     Remove paths have different extensions from selected
                        ones via `-e` (keep entries don't have extensions)
    --remove-extensions
                        Remove extensions in all paths (Example: admin.php ->
                        admin)
    -U, --uppercase     Uppercase wordlist
    -L, --lowercase     Lowercase wordlist
    -C, --capital       Capital wordlist

  General Settings:
    -t THREADS, --threads=THREADS
                        Number of threads
    -r, --recursive     Brute-force recursively
    --deep-recursive    Perform recursive scan on every directory depth
                        (Example: api/users -> api/)
    --force-recursive   Do recursive brute-force for every found path, not
                        only paths end with slash
    --recursion-depth=DEPTH
                        Maximum recursion depth
    --recursion-status=CODES
                        Valid status codes to perform recursive scan, support
                        ranges (separated by commas)
    --subdirs=SUBDIRS   Scan sub-directories of the given URL[s] (separated by
                        commas)
    --exclude-subdirs=SUBDIRS
                        Exclude the following subdirectories during recursive
                        scan (separated by commas)
    -i CODES, --include-status=CODES
                        Include status codes, separated by commas, support
                        ranges (Example: 200,300-399)
    -x CODES, --exclude-status=CODES
                        Exclude status codes, separated by commas, support
                        ranges (Example: 301,500-599)
    --exclude-sizes=SIZES
                        Exclude responses by sizes, separated by commas
                        (Example: 123B,4KB)
    --exclude-texts=TEXTS
                        Exclude responses by texts, separated by commas
                        (Example: 'Not found', 'Error')
    --exclude-regexps=REGEXPS
                        Exclude responses by regexps, separated by commas
                        (Example: 'Not foun[a-z]{1}', '^Error$')
    --exclude-redirects=REGEXPS
                        Exclude responses by redirect regexps or texts,
                        separated by commas (Example: 'https://okta.com/*')
    --exclude-content=PATH
                        Exclude responses by response content of this path
    --skip-on-status=CODES
                        Skip target whenever hit one of these status codes,
                        separated by commas, support ranges
    --minimal=LENGTH    Minimal response length
    --maximal=LENGTH    Maximal response length
    --max-time=SECONDS  Maximal runtime for the scan
    -q, --quiet-mode    Quiet mode
    --full-url          Full URLs in the output (enabled automatically in
                        quiet mode)
    --no-color          No colored output

  Request Settings:
    -m METHOD, --http-method=METHOD
                        HTTP method (default: GET)
    -d DATA, --data=DATA
                        HTTP request data
    -H HEADERS, --header=HEADERS
                        HTTP request header, support multiple flags (Example:
                        -H 'Referer: example.com')
    --header-list=FILE  File contains HTTP request headers
    -F, --follow-redirects
                        Follow HTTP redirects
    --random-agent      Choose a random User-Agent for each request
    --auth-type=TYPE    Authentication type (basic, digest, bearer, ntlm)
    --auth=CREDENTIAL   Authentication credential (user:password or bearer
                        token)
    --user-agent=USERAGENT
    --cookie=COOKIE

  Connection Settings:
    --timeout=TIMEOUT   Connection timeout
    -s DELAY, --delay=DELAY
                        Delay between requests
    --proxy=PROXY       Proxy URL, support HTTP and SOCKS proxies (Example:
                        localhost:8080, socks5://localhost:8088)
    --proxy-list=FILE   File contains proxy servers
    --replay-proxy=PROXY
                        Proxy to replay with found paths
    --scheme=SCHEME     Default scheme (for raw request or if there is no
                        scheme in the URL)
    --max-rate=RATE     Max requests per second
    --retries=RETRIES   Number of retries for failed requests
    -b, --request-by-hostname
                        By default dirsearch requests by IP for speed. This
                        will force dirsearch to request by hostname
    --ip=IP             Server IP address
    --exit-on-error     Exit whenever an error occurs

  Reports:
    -o FILE, --output=FILE
                        Output file
    --format=FORMAT     Report format (Available: simple, plain, json, xml,
                        md, csv, html)
```


Configuration
---------------

Default values for dirsearch flags can be edited in the configuration file: `default.conf`

```ini
# If you want to edit dirsearch default configurations, you can
# edit values in this file. Everything after `#` is a comment
# and won't be applied

[mandatory]
default-extensions = php,aspx,jsp,html,js
force-extensions = False
# exclude-extensions = old,log

[general]
threads = 30
recursive = False
deep-recursive = False
force-recursive = False
recursion-depth = 0
exclude-subdirs = %%ff/
random-user-agents = False
max-time = 0
full-url = False
quiet-mode = False
color = True
recursion-status = 200-399,401,403
# include-status = 200-299,401
# exclude-status = 400,500-999
# exclude-sizes = 0b,123gb
# exclude-texts = "Not found"
# exclude-regexps = "403 [a-z]{1,25}"
# exclude-content = 404.html
# skip-on-status = 429,999

[reports]
report-format = plain
autosave-report = True
# report-output-folder = /home/user
# logs-location = /tmp
## Supported: plain, simple, json, xml, md, csv, html

[dictionary]
lowercase = False
uppercase = False
capitalization = False
# prefixes = .,admin
# suffixes = ~,.bak
# wordlist = db/dicc.txt

[request]
httpmethod = get
## Lowercase only
follow-redirects = False
# headers-file = headers.txt
# user-agent = MyUserAgent
# cookie = SESSIONID=123

[connection]
timeout = 5
delay = 0
scheme = http
maxrate = 0
retries = 2
request-by-hostname = False
exit-on-error = False
# proxy = localhost:8080
# proxy-list = proxies.txt
# replay-proxy = localhost:8000
```


How to use
---------------

[![Dirsearch demo](https://asciinema.org/a/380112.svg)](https://asciinema.org/a/380112)

Some examples for how to use dirsearch - those are the most common arguments. If you need all, just use the **-h** argument.

### Simple usage
```
python3 dirsearch.py -u https://target
```

```
python3 dirsearch.py -e php,html,js -u https://target
```

```
python3 dirsearch.py -e php,html,js -u https://target -w /path/to/wordlist
```

----
### Recursive scan
- By using the **-r | --recursive** argument, dirsearch will brute-force recursively all directories.

```
python3 dirsearch.py -e php,html,js -u https://target -r
```
- You can set the max recursion depth with **--recursion-depth**, and status-codes to recurse with **--recursion-status**

```
python3 dirsearch.py -e php,html,js -u https://target -r --recursion-depth 3 --recursion-status 200-399
```
- There are 2 more options: **--force-recursive** and **--deep-recursive**
  - **Force recursive**: Brute force recursively all found paths, not just paths end with `/`
  - **Deep recursive**: Recursive brute-force all depths of a path (`a/b/c` => add `a/`, `a/b/`)

----
### Threads
The thread number (**-t | --threads**) reflects the number of separated brute force processes. And so the bigger the thread number is, the faster dirsearch runs. By default, the number of threads is 30, but you can increase it if you want to speed up the progress.

In spite of that, the speed still depends a lot on the response time of the server. And as a warning, we advise you to keep the threads number not too big because it can cause DoS.

```
python3 dirsearch.py -e php,htm,js,bak,zip,tgz,txt -u https://target -t 20
```

----
### Prefixes / Suffixes
- **--prefixes**: Add custom prefixes to all entries

```
python3 dirsearch.py -e php -u https://target --prefixes .,admin,_
```
Base wordlist:

```
tools
```
Generated with prefixes:

```
.tools
admintools
_tools
```

- **--suffixes**: Add custom suffixes to all entries

```
python3 dirsearch.py -e php -u https://target --suffixes ~
```
Base wordlist:

```
index.php
internal
```
Generated with suffixes:

```
index.php~
internal~
```

----
### Blacklist
Inside the `db/` folder, there are several "blacklist files". Paths in those files will be filtered from the scan result if they have the same status as mentioned in the filename.

Example: If you add `admin.php` into `db/403_blacklist.txt`, whenever you do a scan that `admin.php` returns 403, it will be filtered from the result.

----
### Filters
Use **-i | --include-status** and **-x | --exclude-status** to select allowed and not allowed response status-codes

For more advanced filters: **--exclude-sizes**, **--exclude-texts**, **--exclude-regexps**, **--exclude-redirects** and **--exclude-content**

```
python3 dirsearch.py -e php,html,js -u https://target --exclude-sizes 1B,243KB
```

```
python3 dirsearch.py -e php,html,js -u https://target --exclude-texts "403 Forbidden"
```

```
python3 dirsearch.py -e php,html,js -u https://target --exclude-regexps "^Error$"
```

```
python3 dirsearch.py -e php,html,js -u https://target --exclude-redirects "https://(.*).okta.com/*"
```

```
python3 dirsearch.py -e php,html,js -u https://target --exclude-content /error.html
```

----
### Raw request
dirsearch allows you to import the raw request from a file. The content would be something looked like this:

```http
GET /admin HTTP/1.1
Host: admin.example.com
Cache-Control: max-age=0
Accept: */*
```

Since there is no way for dirsearch to know what the URI scheme is, you need to set it using the `--scheme` flag. By default, the scheme is `http`, which can cause a lot of false negatives.

----
### Wordlist formats
Supported wordlist formats: uppercase, lowercase, capitalization

#### Lowercase:

```
admin
index.html
```
#### Uppercase:

```
ADMIN
INDEX.HTML
```
#### Capital:

```
Admin
Index.html
```

----
### Exclude extensions
- Use **-X | --exclude-extensions** with an extension list will remove all paths in the wordlist that contains the given extensions

`python3 dirsearch.py -u https://target -X jsp`

Base wordlist:

```
admin.php
test.jsp
```
After:

```
admin.php
```
- If you want to exclude ALL extensions, except for the ones you selected in the `-e` flag, use **--only-selected**

`python3 dirsearch.py -e html -u https://target --only-selected`

Base wordlist:

```
index.html
admin.php
```
After:

```
index.html
```

----
### Scan sub-directories
- From an URL, you can scan a list of sub-directories with **--subdirs**.

```
python3 dirsearch.py -e php,html,js -u https://target --subdirs admin/,folder/,/
```

- The reverse version of this is **--exclude-subdirs**, which prevents dirsearch from scan recursively the given sub-directories.

```
python3 dirsearch.py -e php,html,js -u https://target --recursive --exclude-subdirs image/,css/
```

----
### Proxies
dirsearch supports SOCKS and HTTP proxy, with two options: a proxy server or a list of proxy servers.

```
python3 dirsearch.py -e php,html,js -u https://target --proxy 127.0.0.1:8080
```

```
python3 dirsearch.py -e php,html,js -u https://target --proxy socks5://10.10.0.1:8080
```

```
python3 dirsearch.py -e php,html,js -u https://target --proxylist proxyservers.txt
```

----
### Reports
Supported report formats: **simple**, **plain**, **json**, **xml**, **md**, **csv**,  **html**

```
python3 dirsearch.py -e php -l URLs.txt --format plain -o report.txt
```

```
python3 dirsearch.py -e php -u https://target --format html -o target.json
```

----
### Some others commands
```
python3 dirsearch.py -u https://target -t 100 -m POST --data "username=admin"
```

```
python3 dirsearch.py -u https://target --random-agent --cookie "isAdmin=1" -F
```

```
python3 dirsearch.py -u https://target --format json -o target.json
```

```
python3 dirsearch.py -u https://target --auth admin:pass --auth-type basic
```

```
python3 dirsearch.py -u https://target --header-list rate-limit-bypasses.txt
```

```
python3 dirsearch.py -u https://target -q --stop-on-error --max-time 360
```

```
python3 dirsearch.py -u https://target --full-url --max-rate 100
```

```
python3 dirsearch.py -u https://target --remove-extensions
```

**There are more features and you will need to discover them by yourself**


Support Docker
---------------
### Install Docker Linux
Install Docker

```sh
curl -fsSL https://get.docker.com | bash
```

> To use docker you need superuser power

### Build Image dirsearch
To create image

```sh
docker build -t "dirsearch:v0.4.2" .
```

> **dirsearch** is the name of the image and **v0.4.2** is the version

### Using dirsearch
For using
```sh
docker run -it --rm "dirsearch:v0.4.2" -u target -e php,html,js,zip
```


References
---------------
- [Comprehensive Guide on Dirsearch](https://www.hackingarticles.in/comprehensive-guide-on-dirsearch/) by Shubham Sharma
- [Comprehensive Guide on Dirsearch Part 2](https://www.hackingarticles.in/comprehensive-guide-on-dirsearch-part-2/) by Shubham Sharma
- [GUÍA COMPLETA SOBRE EL USO DE DIRSEARCH](https://esgeeks.com/guia-completa-uso-dirsearch/?feed_id=5703&_unique_id=6076249cc271f) by ESGEEKS
- [How to use Dirsearch to detect web directories](https://www.ehacking.net/2020/01/how-to-find-hidden-web-directories-using-dirsearch.html) by EHacking
- [dirsearch how to](https://vk9-sec.com/dirsearch-how-to/) by VK9 Security
- [Find Hidden Web Directories with Dirsearch](https://null-byte.wonderhowto.com/how-to/find-hidden-web-directories-with-dirsearch-0201615/) by Wonder How To
- [Brute force directories and files in webservers using dirsearch](https://upadhyayraj.medium.com/brute-force-directories-and-files-in-webservers-using-dirsearch-613e4a7fa8d5) by Raj Upadhyay
- [Live Bug Bounty Recon Session on Yahoo (Amass, crts.sh, dirsearch) w/ @TheDawgyg](https://www.youtube.com/watch?v=u4dUnJ1U0T4) by Nahamsec
- [Dirsearch to find Hidden Web Directories](https://medium.com/@irfaanshakeel/dirsearch-to-find-hidden-web-directories-d0357fbe47b0) by Irfan Shakeel
- [Getting access to 25000 employees details](https://medium.com/@ehsahil/getting-access-to-25k-employees-details-c085d18b73f0) by Sahil Ahamad
- [Best Tools For Directory Bruteforcing](https://secnhack.in/multiple-ways-to-find-hidden-directory-on-web-server/) by Shubham Goyal


Tips
---------------
- The server has requests limit? That's bad, but feel free to bypass it, by randomizing proxy with `--proxy-list`
- Want to find out config files or backups? Try `--suffixes ~` and `--prefixes .`
- For some endpoints that you do not want to force extensions, add `%NOFORCE%` at the end of them
- Want to find only folders/directories? Why not combine `--remove-extensions` and `--suffixes /`!
- The mix of `--cidr`, `-F`, `-q` and will reduce most of noises + false negatives when brute-forcing with a CIDR
- Scan a list of URLs, but don't want to see a 429 flood? `--skip-on-status 429` will help you to skip a target whenever it returns 429
- The server contains large files that slow down the scan? You *might* want to use `HEAD` HTTP method instead of `GET`
- Brute-forcing CIDR is slow? Probably you forgot to reduce request timeout and request retries. Suggest: `--timeout 3 --retries 1`


Contribution
---------------
We have been receiving a lot of helps from many people around the world to improve this tool. Thanks so much to everyone who have helped us so far!
See [CONTRIBUTORS.md](https://github.com/maurosoria/dirsearch/blob/master/CONTRIBUTORS.md) to know who they are.

#### Pull requests and feature requests are welcomed


License
---------------
Copyright (C) Mauro Soria (maurosoria@gmail.com)

License: GNU General Public License, version 2
