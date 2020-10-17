Dirsearch
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
- For shorter command (Unix):

```
chmod +x dirsearch.py
./dirsearch.py -u <URL> -e <EXTENSION>
```
If you are using Windows and don't have git, you can install the ZIP file [here](https://github.com/maurosoria/dirsearch/archive/master.zip), then extract and run

**Dirsearch only supports python 3 or greater**


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

 **NOTE**: 
 You can change the dirsearch default configurations (default extensions, timeout, wordlist location, ...) by editing the "default.conf" file.

Operating Systems supported
---------------------------
- Windows XP/7/8/10
- GNU/Linux
- MacOSX

Features
--------
- Fast
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
- Proxy host randomization
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
Wordlist must be a text file. Each line will be processed as such, except when the special keyword %EXT% is used, it will generate one entry for each extension (-e | --extension) passed as an argument.

Example:
- sample/
- example.%EXT%

Passing the extensions "asp" and "aspx" will generate the following dictionary:
- sample/
- example
- example.asp
- example.aspx

You can also use -f | --force-extensions switch to append extensions to every word in the wordlists.

To use multiple wordlists, you can seperate your wordlists with comma. Example: -w wordlist1.txt,wordlist2.txt

How to use
---------------

Some examples for how to use dirsearch - those are the most common arguments. If you need all, just use the "-h" argument.

### Simple usage
```
python3 dirsearch.py -E -u https://target
```

```
python3 dirsearch.py -e php,html,js -u https://target
```

```
python3 dirsearch.py -e php,html,js -u https://target -w /path/to/wordlist
```

### Recursive scan
By adding "-r | --recursive" argument, dirsearch will automatically brute-force the after of directories that it found.

```
python3 dirsearch.py -e php,html,js -u https://target -r
```
You can set the max recursion depth with "-R" or "--recursive-level-max"

```
python3 dirsearch.py -e php,html,js -u https://target -r -R 3
```

### Exclude extensions
Sometimes your wordlist may contains many extensions, for many cases like `.asp`, `.aspx`, `.php`, `.jsp`, ... But if you found the core application behind it, ASP.NET for example, many of those endpoints will be useless right? Don't worry, try "-X <exclude-extensions>" and all endpoints with extensions you selected will be removed.

```
python3 dirsearch.py -e asp,aspx,html,htm,js -u https://target -X php,jsp,jspx
```

### Prefixes / Suffixes
- "--prefixes": Adding custom prefixes to all entries

```
python3 dirsearch.py -e php -u https://target --prefixes .,admin,_,~
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
~tools
```

- "--suffixes": Adding custom suffixes to all entries

```
python3 dirsearch.py -e php -u https://target --suffixes ~,/
```
Base wordlist:

```
index.php
internal
```
Generated with suffixes:

```
index.php~
index.php/
internal~
internal/
```

### Wordlist formats
Supported wordlist formats: uppercase, lowercase, capitalization

```
python3 dirsearch.py -e html -u https://target --lowercase
```
```
admin
index.html
test
```
---------
```
python3 dirsearch.py -e html -u https://target --uppercase
```
```
ADMIN
INDEX.HTML
TEST
```
---------
```
python3 dirsearch.py -e html -u https://target --capitalization
```
```
Admin
Index.html
Test
```

### Filters
Use "-i | --include-status" and "-x | --exclude-status" to select allowed and not allowed response status codes

```
python3 dirsearch.py -E -u https://target -i 200,204,400,403 -x 500,502,429
```

"--exclude-texts" and "--exclude-regexps" are also supported for more advanced filter

```
python3 dirsearch.py -e php,html,js -u https://target --exclude-texts "403 Forbidden"
```

```
python3 dirsearch.py -e php,html,js -u https://target --exclude-regexps "^Error$"
```

### Scan sub-directories
From an URL, you can scan sub-dirsearctories with "--scan-subdirs".

```
python3 dirsearch.py -e php,html,js -u https://target --scan-subdirs admin/,folder/,/
```

A reverse version of this feature is "--exclude-subdir | --exclude-subdirs", which to prevent dirsearch from brute-forcing directories that should not be brute-forced when doing a recursive scan.

```
python3 dirsearch.py -e php,html,js -u https://target --recursive -R 2 --exclude-subdirs "server-status/,%3f/"
```

### Proxies
dirsearch supports HTTP proxy, with two options: a proxy server or a list of proxy servers.

```
python3 dirsearch.py -e php,html,js -u https://target --proxy 127.0.0.1:8080
```

```
python3 dirsearch.py -e php,html,js -u https://target --proxylist proxyservers.txt
```

### Some others commands
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

**There are more features and you will need to discover it by your self**

Tips
---------------
- Want to run dirsearch with a rate of requests per second? Try `-t <rate> -s 1`
- Want to findout config files or backups? Try out `--suffixes ~` and `--prefixes .`
- Don't want to force extensions on some endpoints? Add `%NOFORCE%` at the end of them so dirsearch won't do that
- Want to find only folders/directories? Combine `--no-extension` and `--suffixes /` then done!

Keep updating ...

#### Alerts
- Don't use `-e *`, it won't replace `*` with all extensions as what you are thinking

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
docker build -t "dirsearch:v0.4.0" .
```
> **dirsearch** this is name the image and **v0.4.0** is version

### Using dirsearch
For using
```sh
docker run -it --rm "dirsearch:v0.4.0" -u target -e php,html,js,zip
```
> target is the site or IP


License
---------------
Copyright (C) Mauro Soria (maurosoria@gmail.com)

License: GNU General Public License, version 2


Contributors
---------------
Main: @maurosoria and @shelld3v

Special thanks for these people:

- @V-Rico
- @random-robbie
- @mzfr
- @DustinTheGreat
- @liamosaur
- @Anon-Exploiter
- @tkisason
- @ricardojba
- @Sjord
- @danritter
- @shahril96
- @drego85
- @Bo0oM
- @exploide
- @redshark180
- @zrquan
- @SUHAR1K
- @eur0pa
- @FireFart
- @telnet22
- @sysevil
- @mazen160
- @k2l8m11n2
- @vlohacks
- @russtone
- @jsav0
- @serhattsnmz
- @ColdFusionX
- @gdattacker

#### Feeling excited? Just [tweet](https://twitter.com/intent/tweet?text=I%20just%20installed%20dirsearch%20v0.4.0%20-%20A%20Web%20Path%20Scanner%20https%3A%2F%2Fgithub.com%2Fmaurosoria%2Fdirsearch%20%23fuzzer%20%23bugbounty%20%23dirsearch%20%23pentesting%20%23security) about it!
