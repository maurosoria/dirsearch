<img src="static/logo.png" alt="dirsearch" width="675px">

dirsearch - Web path discovery
=========

![Build](https://img.shields.io/badge/Built%20with-Python-Blue)
![License](https://img.shields.io/badge/license-GNU_General_Public_License-_red.svg)
![Stars](https://img.shields.io/github/stars/maurosoria/dirsearch.svg)
[![Release](https://img.shields.io/github/release/maurosoria/dirsearch.svg)](https://github.com/maurosoria/dirsearch/releases)
[![Sponsors](https://img.shields.io/github/sponsors/maurosoria)](https://github.com/sponsors/maurosoria)
[![Discord](https://img.shields.io/discord/992276296669339678.svg?logo=discord)](https://discord.gg/2N22ZdAJRj)
[![Twitter](https://img.shields.io/twitter/follow/_dirsearch?label=Follow)](https://twitter.com/_dirsearch)


> An advanced web path brute-forcer

**dirsearch** is being actively developed by [@maurosoria](https://twitter.com/_maurosoria) and [@shelld3v](https://twitter.com/shells3c_)

*Reach to our [Discord server](https://discord.gg/2N22ZdAJRj) to communicate with the team at best*


Table of Contents
------------
* [Installation](#installation--usage)
* [Wordlists](#wordlists-important)
* [Options](#options)
* [Configuration](#configuration)
* [How to use](#how-to-use)
  * [Simple usage](#simple-usage)
  * [Pausing progress](#pausing-progress)
  * [Recursion](#recursion)
  * [Threads](#threads)
  * [Prefixes / Suffixes](#prefixes--suffixes)
  * [Blacklist](#blacklist)
  * [Filters](#filters)
  * [Raw request](#raw-request)
  * [Wordlist formats](#wordlist-formats)
  * [Exclude extensions](#exclude-extensions)
  * [Scan sub-directories](#scan-sub-directories)
  * [Proxies](#proxies)
  * [Reports](#reports)
  * [More example commands](#more-example-commands)
* [Support Docker](#support-docker)
  * [Install Docker Linux](#install-docker-linux)
  * [Build Image dirsearch](#build-image-dirsearch)
  * [Using dirsearch](#using-dirsearch)
* [References](#references)
* [Tips](#tips)
* [Contribution](#contribution)
* [License](#license)


Installation & Usage
------------

**Requirement: python 3.7 or higher**

Choose one of these installation options:

- Install with **git**: `git clone https://github.com/maurosoria/dirsearch.git --depth 1` (**RECOMMENDED**)
- Install with ZIP file: [Download here](https://github.com/maurosoria/dirsearch/archive/master.zip)
- Install with Docker: `docker build -t "dirsearch:v0.4.3" .` (more information can be found [here](https://github.com/maurosoria/dirsearch#support-docker))
- Install with PyPi: `pip3 install dirsearch` or `pip install dirsearch`
- Install with Kali Linux: `sudo apt-get install dirsearch` (deprecated)


Wordlists (IMPORTANT)
---------------
**Summary:**
  - Wordlist is a text file, each line is a path.
  - About extensions, unlike other tools, dirsearch only replaces the `%EXT%` keyword with extensions from **-e** flag.
  - For wordlists without `%EXT%` (like [SecLists](https://github.com/danielmiessler/SecLists)), **-f | --force-extensions** switch is required to append extensions to every word in wordlist, as well as the `/`.
  - To apply your extensions to wordlist entries that have extensions already, use **-O** | **--overwrite-extensions** (Note: some extensions are excluded from being overwritted such as *.log*, *.json*, *.xml*, ... or media extensions like *.jpg*, *.png*)
  - To use multiple wordlists, you can separate your wordlists with commas. Example: `wordlist1.txt,wordlist2.txt`.

**Examples:**

- *Normal extensions*:
```
index.%EXT%
```

Passing **asp** and **aspx** as extensions will generate the following dictionary:

```
index
index.asp
index.aspx
```

- *Force extensions*:
```
admin
```

Passing **php** and **html** as extensions with **-f**/**--force-extensions** flag will generate the following dictionary:

```
admin
admin.php
admin.html
admin/
```

- *Overwrite extensions*:
```
login.html
```

Passing **jsp** and **jspa** as extensions with **-O**/**--overwrite-extensions** flag will generate the following dictionary:

```
login.html
login.jsp
login.jspa
```


Options
-------

```
Usage: dirsearch.py [-u|--url] target [-e|--extensions] extensions [options]

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit

  Mandatory:
    -u URL, --url=URL   Target URL(s), can use multiple flags
    -l PATH, --url-file=PATH
                        URL list file
    --stdin             Read URL(s) from STDIN
    --cidr=CIDR         Target CIDR
    --raw=PATH          Load raw HTTP request from file (use '--scheme' flag
                        to set the scheme)
    -s SESSION_FILE, --session=SESSION_FILE
                        Session file
    --config=PATH       Path to configuration file (Default:
                        'DIRSEARCH_CONFIG' environment variable, otherwise
                        'config.ini')

  Dictionary Settings:
    -w WORDLISTS, --wordlists=WORDLISTS
                        Customize wordlists (separated by commas)
    -e EXTENSIONS, --extensions=EXTENSIONS
                        Extension list separated by commas (e.g. php,asp)
    -f, --force-extensions
                        Add extensions to the end of every wordlist entry. By
                        default dirsearch only replaces the %EXT% keyword with
                        extensions
    -O, --overwrite-extensions
                        Overwrite other extensions in the wordlist with your
                        extensions (selected via `-e`)
    --exclude-extensions=EXTENSIONS
                        Exclude extension list separated by commas (e.g.
                        asp,jsp)
    --remove-extensions
                        Remove extensions in all paths (e.g. admin.php ->
                        admin)
    --prefixes=PREFIXES
                        Add custom prefixes to all wordlist entries (separated
                        by commas)
    --suffixes=SUFFIXES
                        Add custom suffixes to all wordlist entries, ignore
                        directories (separated by commas)
    -U, --uppercase     Uppercase wordlist
    -L, --lowercase     Lowercase wordlist
    -C, --capital       Capital wordlist

  General Settings:
    -t THREADS, --threads=THREADS
                        Number of threads
    -r, --recursive     Brute-force recursively
    --deep-recursive    Perform recursive scan on every directory depth (e.g.
                        api/users -> api/)
    --force-recursive   Do recursive brute-force for every found path, not
                        only directories
    -R DEPTH, --max-recursion-depth=DEPTH
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
                        ranges (e.g. 200,300-399)
    -x CODES, --exclude-status=CODES
                        Exclude status codes, separated by commas, support
                        ranges (e.g. 301,500-599)
    --exclude-sizes=SIZES
                        Exclude responses by sizes, separated by commas (e.g.
                        0B,4KB)
    --exclude-text=TEXTS
                        Exclude responses by text, can use multiple flags
    --exclude-regex=REGEX
                        Exclude responses by regular expression
    --exclude-redirect=STRING
                        Exclude responses if this regex (or text) matches
                        redirect URL (e.g. '/index.html')
    --exclude-response=PATH
                        Exclude responses similar to response of this page,
                        path as input (e.g. 404.html)
    --skip-on-status=CODES
                        Skip target whenever hit one of these status codes,
                        separated by commas, support ranges
    --min-response-size=LENGTH
                        Minimum response length
    --max-response-size=LENGTH
                        Maximum response length
    --max-time=SECONDS  Maximum runtime for the scan
    --exit-on-error     Exit whenever an error occurs

  Request Settings:
    -m METHOD, --http-method=METHOD
                        HTTP method (default: GET)
    -d DATA, --data=DATA
                        HTTP request data
    --data-file=PATH    File contains HTTP request data
    -H HEADERS, --header=HEADERS
                        HTTP request header, can use multiple flags
    --header-file=PATH  File contains HTTP request headers
    -F, --follow-redirects
                        Follow HTTP redirects
    --random-agent      Choose a random User-Agent for each request
    --auth=CREDENTIAL   Authentication credential (e.g. user:password or
                        bearer token)
    --auth-type=TYPE    Authentication type (basic, digest, bearer, ntlm, jwt,
                        oauth2)
    --cert-file=PATH    File contains client-side certificate
    --key-file=PATH     File contains client-side certificate private key
                        (unencrypted)
    --user-agent=USER_AGENT
    --cookie=COOKIE

  Connection Settings:
    --timeout=TIMEOUT   Connection timeout
    --delay=DELAY       Delay between requests
    --proxy=PROXY       Proxy URL (HTTP/SOCKS), can use multiple flags
    --proxy-file=PATH   File contains proxy servers
    --proxy-auth=CREDENTIAL
                        Proxy authentication credential
    --replay-proxy=PROXY
                        Proxy to replay with found paths
    --tor               Use Tor network as proxy
    --scheme=SCHEME     Scheme for raw request or if there is no scheme in the
                        URL (Default: auto-detect)
    --max-rate=RATE     Max requests per second
    --retries=RETRIES   Number of retries for failed requests
    --ip=IP             Server IP address

  Advanced Settings:
    --crawl             Crawl for new paths in responses

  View Settings:
    --full-url          Full URLs in the output (enabled automatically in
                        quiet mode)
    --redirects-history
                        Show redirects history
    --no-color          No colored output
    -q, --quiet-mode    Quiet mode

  Output Settings:
    -o PATH, --output=PATH
                        Output file
    --format=FORMAT     Report format (Available: simple, plain, json, xml,
                        md, csv, html, sqlite)
    --log=PATH          Log file
```


Configuration
---------------

By default, `config.ini` inside your dirsearch directory is used as the configuration file but you can select another file via `--config` flag or `DIRSEARCH_CONFIG` environment variable.

```ini
# If you want to edit dirsearch default configurations, you can
# edit values in this file. Everything after `#` is a comment
# and won't be applied

[general]
threads = 25
recursive = False
deep-recursive = False
force-recursive = False
recursion-status = 200-399,401,403
max-recursion-depth = 0
exclude-subdirs = %%ff/,.;/,..;/,;/,./,../,%%2e/,%%2e%%2e/
random-user-agents = False
max-time = 0
exit-on-error = False
# subdirs = /,api/
# include-status = 200-299,401
# exclude-status = 400,500-999
# exclude-sizes = 0b,123gb
# exclude-text = "Not found"
# exclude-regex = "^403$"
# exclude-redirect = "*/error.html"
# exclude-response = 404.html
# skip-on-status = 429,999

[dictionary]
default-extensions = php,aspx,jsp,html,js
force-extensions = False
overwrite-extensions = False
lowercase = False
uppercase = False
capitalization = False
# exclude-extensions = old,log
# prefixes = .,admin
# suffixes = ~,.bak
# wordlists = /path/to/wordlist1.txt,/path/to/wordlist2.txt

[request]
http-method = get
follow-redirects = False
# headers-file = /path/to/headers.txt
# user-agent = MyUserAgent
# cookie = SESSIONID=123

[connection]
timeout = 7.5
delay = 0
max-rate = 0
max-retries = 1
## By disabling `scheme` variable, dirsearch will automatically identify the URI scheme
# scheme = http
# proxy = localhost:8080
# proxy-file = /path/to/proxies.txt
# replay-proxy = localhost:8000

[advanced]
crawl = False

[view]
full-url = False
quiet-mode = False
color = True
show-redirects-history = False

[output]
## Support: plain, simple, json, xml, md, csv, html, sqlite
report-format = plain
autosave-report = True
autosave-report-folder = reports/
# log-file = /path/to/dirsearch.log
# log-file-size = 50000000
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

---
### Pausing progress
dirsearch allows you to pause the scanning progress with CTRL+C, from here, you can save the progress (and continue later), skip the current target, or skip the current sub-directory.

<img src="static/pause.png" alt="Pausing dirsearch" width="475px">

----
### Recursion
- Recursive brute-force is brute-forcing continuously the after of found directories. For example, if dirsearch finds `admin/`, it will brute-force `admin/*` (`*` is where it brute forces). To enable this feature, use **-r** (or **--recursive**) flag

```
python3 dirsearch.py -e php,html,js -u https://target -r
```
- You can set the max recursion depth with **--max-recursion-depth**, and status codes to recurse with **--recursion-status**

```
python3 dirsearch.py -e php,html,js -u https://target -r --max-recursion-depth 3 --recursion-status 200-399
```
- There are 2 more options: **--force-recursive** and **--deep-recursive**
  - **Force recursive**: Brute force recursively all found paths, not just paths end with `/`
  - **Deep recursive**: Recursive brute-force all depths of a path (`a/b/c` => add `a/`, `a/b/`)

- If there are sub-directories that you do not want to brute-force recursively, use `--exclude-subdirs`

```
python3 dirsearch.py -e php,html,js -u https://target -r --exclude-subdirs image/,media/,css/
```

----
### Threads
The thread number (**-t | --threads**) reflects the number of separated brute force processes. And so the bigger the thread number is, the faster dirsearch runs. By default, the number of threads is 25, but you can increase it if you want to speed up the progress.

In spite of that, the speed still depends a lot on the response time of the server. And as a warning, we advise you to keep the threads number not too big because it can cause DoS (Denial of Service).

```
python3 dirsearch.py -e php,htm,js,bak,zip,tgz,txt -u https://target -t 20
```

----
### Prefixes / Suffixes
- **--prefixes**: Add custom prefixes to all entries

```
python3 dirsearch.py -e php -u https://target --prefixes .,admin,_
```
Wordlist:

```
tools
```
Generated with prefixes:

```
tools
.tools
admintools
_tools
```

- **--suffixes**: Add custom suffixes to all entries

```
python3 dirsearch.py -e php -u https://target --suffixes ~
```
Wordlist:

```
index.php
internal
```
Generated with suffixes:

```
index.php
internal
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

For more advanced filters: **--exclude-sizes**, **--exclude-texts**, **--exclude-regexps**, **--exclude-redirects** and **--exclude-response**

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
python3 dirsearch.py -e php,html,js -u https://target --exclude-response /error.html
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

Since there is no way for dirsearch to know what the URI scheme is, you need to set it using the `--scheme` flag. By default, dirsearch automatically detects the scheme.

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
Use **-X | --exclude-extensions** with an extension list will remove all paths in the wordlist that contains the given extensions

`python3 dirsearch.py -u https://target -X jsp`

Wordlist:

```
admin.php
test.jsp
```
After:

```
admin.php
```

----
### Scan sub-directories
- From an URL, you can scan a list of sub-directories with **--subdirs**.

```
python3 dirsearch.py -e php,html,js -u https://target --subdirs /,admin/,folder/
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
Supported report formats: **simple**, **plain**, **json**, **xml**, **md**, **csv**,  **html**, **sqlite**

```
python3 dirsearch.py -e php -l URLs.txt --format plain -o report.txt
```

```
python3 dirsearch.py -e php -u https://target --format html -o target.json
```

----
### More example commands
```
cat urls.txt | python3 dirsearch.py --stdin
```

```
python3 dirsearch.py -u https://target --max-time 360
```

```
python3 dirsearch.py -u https://target --auth admin:pass --auth-type basic
```

```
python3 dirsearch.py -u https://target --header-list rate-limit-bypasses.txt
```

**There are more to discover, try yourself!**


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
docker build -t "dirsearch:v0.4.3" .
```

> **dirsearch** is the name of the image and **v0.4.3** is the version

### Using dirsearch
For using
```sh
docker run -it --rm "dirsearch:v0.4.3" -u target -e php,html,js,zip
```


References
---------------
- [Comprehensive Guide on Dirsearch](https://www.hackingarticles.in/comprehensive-guide-on-dirsearch/) by Shubham Sharma
- [Comprehensive Guide on Dirsearch Part 2](https://www.hackingarticles.in/comprehensive-guide-on-dirsearch-part-2/) by Shubham Sharma
- [How to Find Hidden Web Directories with Dirsearch](https://www.geeksforgeeks.org/how-to-find-hidden-web-directories-with-dirsearch/) by GeeksforGeeks
- [GUÍA COMPLETA SOBRE EL USO DE DIRSEARCH](https://esgeeks.com/guia-completa-uso-dirsearch/?feed_id=5703&_unique_id=6076249cc271f) by ESGEEKS
- [How to use Dirsearch to detect web directories](https://www.ehacking.net/2020/01/how-to-find-hidden-web-directories-using-dirsearch.html) by EHacking
- [dirsearch how to](https://vk9-sec.com/dirsearch-how-to/) by VK9 Security
- [Find Hidden Web Directories with Dirsearch](https://null-byte.wonderhowto.com/how-to/find-hidden-web-directories-with-dirsearch-0201615/) by Wonder How To
- [Brute force directories and files in webservers using dirsearch](https://upadhyayraj.medium.com/brute-force-directories-and-files-in-webservers-using-dirsearch-613e4a7fa8d5) by Raj Upadhyay
- [Live Bug Bounty Recon Session on Yahoo (Amass, crts.sh, dirsearch) w/ @TheDawgyg](https://www.youtube.com/watch?v=u4dUnJ1U0T4) by Nahamsec
- [Dirsearch to find Hidden Web Directories](https://medium.com/@irfaanshakeel/dirsearch-to-find-hidden-web-directories-d0357fbe47b0) by Irfan Shakeel
- [Getting access to 25000 employees details](https://medium.com/@ehsahil/getting-access-to-25k-employees-details-c085d18b73f0) by Sahil Ahamad
- [Best Tools For Directory Bruteforcing](https://secnhack.in/multiple-ways-to-find-hidden-directory-on-web-server/) by Shubham Goyal
- [Discover hidden files & directories on a webserver - dirsearch full tutorial](https://www.youtube.com/watch?v=jVxs5at0gxg) by CYBER BYTES


Tips
---------------
- The server has requests limit? That's bad, but feel free to bypass it, by randomizing proxy with `--proxy-list`
- Want to find out config files or backups? Try `--suffixes ~` and `--prefixes .`
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
