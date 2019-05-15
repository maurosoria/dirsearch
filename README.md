# Dirsearch fork by damian89

This is my own fork of [dirsearch](https://github.com/maurosoria/dirsearch) (original author:  [maurosoria](https://github.com/maurosoria))

## Whats different

1. using "--http-method" you can specify which request method to use, since there is more than GET
2. using "--recursive-level-max" you can specify - when using recursive crawling - what the maximum level of recursion is - here I have the default value of 1 which means: only within root + (1 level)
3. not only %EXT% is replaced, but also %ext% - some wordlist tend to use lowercase
4. When scanning recursivly dirsearch now checks if a subdir is already in queue

## Help section
```

Usage: dirsearch.py [-u|--url] target [-e|--extensions] extensions [options]

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
    -R RECURSIVE_LEVEL_MAX, --recursive-level-max=RECURSIVE_LEVEL_MAX
                        Max recursion level (subdirs) (Default: 1 [only
                        rootdir + 1 dir])
    --suppress-empty, --suppress-empty
    --scan-subdir=SCANSUBDIRS, --scan-subdirs=SCANSUBDIRS
                        Scan subdirectories of the given -u|--url (separated
                        by comma)
    --exclude-subdir=EXCLUDESUBDIRS, --exclude-subdirs=EXCLUDESUBDIRS
                        Exclude the following subdirectories during recursive
                        scan (separated by comma)
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
    --http-method=HTTPMETHOD
                        Method to use, default: GET, possible also: HEAD;POST
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
