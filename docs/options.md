# CLI Options

```text
Usage: dirsearch.py [-u|--url] target [-e|--extensions] extensions [options]

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit

  Mandatory:
    -u URL, --url=URL   Target URL(s), can use multiple flags
    -l PATH, --urls-file=PATH
                        URL list file
    --stdin             Read URL(s) from STDIN
    --cidr=CIDR         Target CIDR
    --raw=PATH          Load raw HTTP request from file (use '--scheme' flag
                        to set the scheme)
    --nmap-report=PATH  Load targets from nmap report (Ensure the inclusion of
                        the -sV flag during nmap scan for comprehensive
                        results)
    -s SESSION_FILE, --session=SESSION_FILE
                        Session file
    --session-id=ID     Load session by numeric id (use --list-sessions to see
                        ids)
    --config=PATH       Path to configuration file (Default:
                        'DIRSEARCH_CONFIG' environment variable, otherwise
                        'config.ini')

  Dictionary Settings:
    -w WORDLISTS, --wordlists=WORDLISTS
                        Wordlist files or directories contain wordlists
                        (separated by commas)
    --wordlist-categories=WORDLIST_CATEGORIES
                        Comma-separated wordlist category names (e.g.
                        common,conf,web). Use 'all' to include all bundled
                        categories
    --wordlist-backend=BACKEND
                        Wordlist generation backend: auto, python, native
                        (default: auto)
    --wordlist-status   Show resolved wordlist files and generated entry
                        count, then exit
    --wordlist-max-size=COUNT
                        Maximum generated wordlist entries before aborting
                        (default: 500000)
    -e EXTENSIONS, --extensions=EXTENSIONS
                        Extension list, separated by commas (e.g. php,asp)
    -f, --force-extensions
                        Add extensions to the end of every wordlist entry. By
                        default dirsearch only replaces the %EXT% keyword with
                        extensions
    --overwrite-extensions
                        Overwrite other extensions in the wordlist with your
                        extensions (selected via `-e`)
    --exclude-extensions=EXTENSIONS
                        Exclude extension list, separated by commas (e.g.
                        asp,jsp)
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
    --preflight         Calibrate target concurrency and delay before scanning
    --list-sessions     List resumable sessions and exit
    --sessions-dir=PATH
                        Directory to search for resumable sessions (default:
                        dirsearch path /sessions, or $HOME/.dirsearch/sessions
                        when bundled)
    -a, --async         Enable asynchronous mode
    --sync, --no-async  Use synchronous Python mode
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
    --filter-threshold=THRESHOLD
                        Maximum number of results with duplicate responses
                        before getting filtered out
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
    --target-max-time=SECONDS
                        Maximum runtime for a target
    --exit-on-error     Exit whenever an error occurs

  Advanced Filtering:
    --auto-calibration  Force extra wildcard calibration from the beginning
    --matcher-mode=MODE, --mmode=MODE
                        Advanced matcher operator: and, or
    --filter-mode=MODE, --fmode=MODE
                        Advanced filter operator: and, or
    --match-status=CODES, --mc=CODES
                        Advanced matcher for status codes, separated by
                        commas, support ranges
    --filter-status=CODES, --fc=CODES
                        Advanced filter for status codes, separated by commas,
                        support ranges
    --match-size=SIZES, --ms=SIZES
                        Advanced matcher for response length, separated by
                        commas, support ranges
    --filter-size=SIZES, --fs=SIZES
                        Advanced filter for response length, separated by
                        commas, support ranges
    --match-words=WORDS, --mw=WORDS
                        Advanced matcher for response word count, separated by
                        commas, support ranges
    --filter-words=WORDS, --fw=WORDS
                        Advanced filter for response word count, separated by
                        commas, support ranges
    --match-lines=LINES, --ml=LINES
                        Advanced matcher for response line count, separated by
                        commas, support ranges
    --filter-lines=LINES, --fl=LINES
                        Advanced filter for response line count, separated by
                        commas, support ranges
    --match-regex=REGEX, --mr=REGEX
                        Advanced matcher for response body regular expression
    --filter-regex=REGEX, --fr=REGEX
                        Advanced filter for response body regular expression
    --match-time=TIME, --mt=TIME
                        Advanced matcher for elapsed milliseconds, e.g. >100
                        or <100
    --filter-time=TIME, --ft=TIME
                        Advanced filter for elapsed milliseconds, e.g. >100 or
                        <100

  Request Settings:
    -m METHOD, --http-method=METHOD
                        HTTP method (default: GET)
    --request-backend=BACKEND
                        Request backend: python, native (default: python)
    -d DATA, --data=DATA
                        HTTP request data
    --data-file=PATH    File contains HTTP request data
    -H HEADERS, --header=HEADERS
                        HTTP request header, can use multiple flags
    --headers-file=PATH
                        File contains HTTP request headers
    -F, --follow-redirects
                        Follow HTTP redirects
    --random-agent      Choose a random User-Agent for each request
    --auth=CREDENTIAL   Authentication credential (e.g. user:password or
                        bearer token)
    --auth-type=TYPE    Authentication type (basic, digest, bearer, ntlm, jwt)
    --cert-file=PATH    File contains client-side certificate
    --key-file=PATH     File contains client-side certificate private key
                        (unencrypted)
    --user-agent=USER_AGENT
    --cookie=COOKIE

  Connection Settings:
    --timeout=TIMEOUT   Connection timeout
    --delay=DELAY       Delay between requests
    -p PROXY, --proxy=PROXY
                        Proxy URL (HTTP/SOCKS), can use multiple flags
    --proxies-file=PATH
                        File contains proxy servers
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
    --interface=NETWORK_INTERFACE
                        Network interface to use

  Advanced Settings:
    --crawl             Crawl for new paths in responses

  View Settings:
    --full-url          Full URLs in the output (enabled automatically in
                        quiet mode)
    --redirects-history
                        Show redirects history
    --no-color          No colored output
    -q, --quiet-mode    Quiet mode
    --disable-cli       Turn off command-line output
    -v, --verbose       Show verbose output with response time and content
                        type

  Output Settings:
    -O FORMAT, --output-formats=FORMAT
                        Report formats, separated by commas (Available:
                        simple, plain, json, xml, md, csv, html, sqlite)
    -o PATH, --output-file=PATH
                        Output file location
    --mysql-url=URL     Database URL for MySQL output (Format:
                        mysql://[username:password@]host[:port]/database-name)
    --postgres-url=URL  Database URL for PostgreSQL output (Format:
                        postgres://[username:password@]host[:port]/database-
                        name)
    --log=PATH          Log file

See 'config.ini' for the example configuration file
```
