# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

import sys

from optparse import OptionParser, OptionGroup

from lib.core.settings import VERSION, SCRIPT_PATH, COMMON_EXTENSIONS, OUTPUT_FORMATS, AUTHENTICATION_TYPES
from lib.parse.configparser import ConfigParser
from lib.parse.headers import HeadersParser
from lib.utils.file import File, FileUtils
from lib.utils.fmt import uniq
from lib.utils.ip import iprange


class ArgumentParser(object):
    def __init__(self):
        options = self.parse_config(self.parse_arguments())
        self.__dict__.update(options.__dict__)

        self.httpmethod = self.httpmethod.lower()
        self.url_list = []
        self.raw_file = None

        if options.url:
            self.url_list = [options.url]
        elif options.url_list:
            file = self.access_file(options.url_list, "file contains URLs")
            self.url_list = list(file.get_lines())
        elif options.cidr:
            self.url_list = iprange(options.cidr)
        elif options.stdin_urls:
            self.url_list = sys.stdin.read().splitlines()

        if options.raw_file:
            self.access_file(options.raw_file, "file with raw request")
        elif not len(self.url_list):
            print("URL target is missing, try using -u <url>")
            exit(1)

        self.url_list = uniq(self.url_list)

        if not options.extensions and not options.no_extension:
            print("WARNING: No extension was specified!")

        for dict_file in options.wordlist.split(","):
            self.access_file(dict_file, "wordlist")

        if options.threads_count < 1:
            print("Threads number must be greater than zero")
            exit(1)

        if options.no_extension:
            self.extensions = ""

        if options.proxy_list:
            file = self.access_file(options.proxy_list, "proxylist file")
            self.proxylist = file.read().splitlines()

        if self.proxy or self.proxylist or self.replay_proxy:
            self.request_by_hostname = True

        self.headers = {}
        if options.header_list:
            try:
                file = self.access_file(options.header_list, "header list file")
                self.headers.update(
                    HeadersParser(file.read()).headers
                )
            except Exception as e:
                print("Error in headers file: " + str(e))
                exit(1)

        if options.headers:
            try:
                self.headers.update(
                    HeadersParser(options.headers).headers
                )
            except Exception:
                print("Invalid headers")
                exit(1)

        if options.extensions == "*":
            self.extensions = COMMON_EXTENSIONS
        elif options.extensions == "banner.txt":
            print("A weird extension was provided: 'banner.txt'. Please do not use * as the extension or enclose it in double quotes")
            exit(0)
        else:
            self.extensions = uniq([extension.lstrip(' .') for extension in options.extensions.split(",")])

        if options.exclude_extensions:
            self.exclude_extensions = uniq(
                [exclude_extension.lstrip(' .') for exclude_extension in options.exclude_extensions.split(",")]
            )

        if options.include_status_codes:
            self.include_status_codes = self.parse_status_codes(options.include_status_codes)

        if options.exclude_status_codes:
            self.exclude_status_codes = self.parse_status_codes(options.exclude_status_codes)

        if options.recursion_status_codes:
            self.recursion_status_codes = self.parse_status_codes(options.recursion_status_codes)

        if options.exclude_sizes:
            try:
                self.exclude_sizes = uniq([
                    exclude_size.strip().upper() if exclude_size else None
                    for exclude_size in options.exclude_sizes.split(",")
                ])

            except ValueError:
                pass

        if options.exclude_texts:
            try:
                self.exclude_texts = uniq([
                    exclude_text.strip() if exclude_text else None
                    for exclude_text in options.exclude_texts.split(",")
                ])

            except ValueError:
                pass

        if options.exclude_regexps:
            try:
                self.exclude_regexps = uniq([
                    exclude_regexp.strip() if exclude_regexp else None
                    for exclude_regexp in options.exclude_regexps.split(",")
                ])

            except ValueError:
                pass

        if options.exclude_redirects:
            try:
                self.exclude_redirects = uniq([
                    exclude_redirect.strip() if exclude_redirect else None
                    for exclude_redirect in options.exclude_redirects.split(",")
                ])

            except ValueError:
                pass

        self.prefixes = uniq([prefix.strip() for prefix in self.prefixes.split(",")]) if options.prefixes else []
        self.suffixes = uniq([suffix.strip() for suffix in self.suffixes.split(",")]) if options.suffixes else []
        if options.wordlist:
            self.wordlist = uniq([wordlist.strip() for wordlist in options.wordlist.split(",")])
        else:
            print("No wordlist was provided, try using -w <wordlist>")
            exit(1)

        self.scan_subdirs = []
        if options.scan_subdirs:
            for subdir in options.scan_subdirs.split(","):
                subdir = subdir.strip(" ")
                if subdir.startswith("/"):
                    subdir = subdir[1:]
                if not subdir.endswith("/"):
                    subdir += "/"
                self.scan_subdirs.append(subdir)

        self.exclude_subdirs = []
        if options.exclude_subdirs:
            for subdir in options.exclude_subdirs.split(","):
                subdir = subdir.strip(" ")
                if subdir.startswith("/"):
                    subdir = subdir[1:]
                if not subdir.endswith("/"):
                    subdir += "/"
                self.exclude_subdirs.append(subdir)

        if options.skip_on_status:
            self.skip_on_status = self.parse_status_codes(options.skip_on_status)

        if options.auth and not options.auth_type:
            print("Please select the authentication type with --auth-type")
            exit(1)
        elif options.auth_type and not options.auth:
            print("No authentication credential found")
            exit(1)
        elif options.auth and options.auth_type not in AUTHENTICATION_TYPES:
            print("'{}' is not in available authentication types: {}".format(options.auth_type, ", ".join(AUTHENTICATION_TYPES)))
            exit(1)

        if len(set(self.extensions).intersection(self.exclude_extensions)):
            print("Exclude extension list can not contain any extension that has already in the extension list")
            exit(1)

        if self.output_format not in [None, ""] + list(OUTPUT_FORMATS):
            print("Select one of the following output formats: {}".format(", ".join(OUTPUT_FORMATS)))
            exit(1)

    def parse_status_codes(self, raw_status_codes):
        status_codes = []
        for status_code in raw_status_codes.split(","):
            try:
                if "-" in status_code:
                    s, e = status_code.strip().split("-")
                    status_codes.extend(range(int(s), int(e) + 1))
                else:
                    status_codes.append(int(status_code.strip()))

            except ValueError:
                print("Invalid status code or status code range: {0}".format(status_code))
                exit(1)

        return uniq(status_codes)

    def access_file(self, path, name):
        with File(path) as file:
            if not file.exists():
                print("The {} does not exist".format(name))
                exit(1)

            if not file.is_valid():
                print("The {} is invalid".format(name))
                exit(1)

            if not file.can_read():
                print("The {} cannot be read".format(name))
                exit(1)

            return file

    def parse_config(self, options):
        config = ConfigParser()
        config.read(options.config)

        # Mandatory
        options.extensions = options.extensions or config.safe_get(
            "mandatory", "default-extensions", ""
        )
        options.exclude_extensions = options.exclude_extensions or config.safe_get(
            "mandatory", "exclude-extensions", []
        )
        options.force_extensions = options.force_extensions or config.safe_getboolean(
            "mandatory", "force-extensions", []
        )

        # General
        options.threads_count = options.threads_count or config.safe_getint(
            "general", "threads", 25, list(range(1, 300))
        )
        options.include_status_codes = options.include_status_codes or config.safe_get(
            "general", "include-status", []
        )
        options.exclude_status_codes = options.exclude_status_codes or config.safe_get(
            "general", "exclude-status", []
        )
        options.exclude_sizes = options.exclude_sizes or config.safe_get("general", "exclude-sizes", [])
        options.exclude_texts = options.exclude_texts or config.safe_get("general", "exclude-texts", [])
        options.exclude_regexps = options.exclude_regexps or config.safe_get("general", "exclude-regexps", [])
        options.exclude_redirects = options.exclude_regexps or config.safe_get("general", "exclude-redirects", [])
        options.exclude_response = options.exclude_response or config.safe_get("general", "exclude-response", "")
        options.recursive = options.recursive or config.safe_getboolean("general", "recursive")
        options.deep_recursive = options.deep_recursive or config.safe_getboolean("general", "deep-recursive")
        options.force_recursive = options.force_recursive or config.safe_getboolean("general", "force-recursive")
        options.recursion_depth = options.recursion_depth or config.safe_getint("general", "recursion-depth")
        options.recursion_status_codes = options.recursion_status_codes or config.safe_get(
            "general", "recursion-status", []
        )
        options.scan_subdirs = options.scan_subdirs or config.safe_get("general", "subdirs")
        options.exclude_subdirs = options.exclude_subdirs or config.safe_get("general", "exclude-subdirs")
        options.skip_on_status = options.skip_on_status or config.safe_get("general", "skip-on-status", [])
        options.maxtime = options.maxtime or config.safe_getint("general", "max-time")
        options.full_url = options.full_url or config.safe_getboolean("general", "full-url")
        options.color = options.color or config.safe_getboolean("general", "color", True)
        options.quiet = options.quiet or config.safe_getboolean("general", "quiet-mode")
        options.redirects_history = options.redirects_history or config.safe_getboolean("general", "redirects-history")

        # Dictionary
        options.wordlist = options.wordlist or config.safe_get(
            "dictionary", "wordlist", FileUtils.build_path(SCRIPT_PATH, "db", "dicc.txt"),
        )
        options.prefixes = options.prefixes or config.safe_get("dictionary", "prefixes",)
        options.suffixes = options.suffixes or config.safe_get("dictionary", "suffixes")
        options.lowercase = options.lowercase or config.safe_getboolean("dictionary", "lowercase")
        options.uppercase = options.uppercase or config.safe_getboolean("dictionary", "uppercase")
        options.capitalization = options.capitalization or config.safe_getboolean("dictionary", "capitalization")

        # Request
        options.httpmethod = options.httpmethod or config.safe_get("request", "httpmethod", "get")
        options.header_list = options.header_list or config.safe_get("request", "headers-file")
        options.follow_redirects = options.follow_redirects or config.safe_getboolean("request", "follow-redirects")
        options.use_random_agents = options.use_random_agents or config.safe_getboolean("request", "random-user-agents")
        options.useragent = options.useragent or config.safe_get("request", "user-agent")
        options.cookie = options.cookie or config.safe_get("request", "cookie")

        # Connection
        options.delay = options.delay or config.safe_getfloat("connection", "delay")
        options.timeout = options.timeout or config.safe_getfloat("connection", "timeout", 7.5)
        options.max_retries = options.max_retries or config.safe_getint("connection", "retries", 1)
        options.maxrate = options.maxrate or config.safe_getint("connection", "max-rate")
        options.proxy = options.proxy or config.safe_get("connection", "proxy")
        options.proxylist = config.safe_get("connection", "proxy-list")
        options.scheme = options.scheme or config.safe_get("connection", "scheme", None, ["http", "https"])
        options.replay_proxy = options.replay_proxy or config.safe_get("connection", "replay-proxy")
        options.exit_on_error = options.exit_on_error or config.safe_getboolean("connection", "exit-on-error")
        options.request_by_hostname = options.request_by_hostname or config.safe_getboolean(
            "connection", "request-by-hostname"
        )

        # Reports
        self.output_location = config.safe_get("reports", "report-output-folder")
        self.logs_location = config.safe_get("reports", "logs-folder")
        self.autosave_report = config.safe_getboolean("reports", "autosave-report")
        options.output_format = options.output_format or config.safe_get(
            "reports", "report-format", "plain", OUTPUT_FORMATS
        )

        return options

    def parse_arguments(self):
        usage = "Usage: %prog [-u|--url] target [-e|--extensions] extensions [options]"
        parser = OptionParser(usage, version="dirsearch v{}".format(VERSION))

        # Mandatory arguments
        mandatory = OptionGroup(parser, "Mandatory")
        mandatory.add_option("-u", "--url", action="store", dest="url", help="Target URL")
        mandatory.add_option("-l", "--url-list", action="store", dest="url_list", metavar="FILE", help="Target URL list file")
        mandatory.add_option("--stdin", action="store_true", dest="stdin_urls", help="Target URL list from STDIN")
        mandatory.add_option("--cidr", action="store", dest="cidr", help="Target CIDR")
        mandatory.add_option("--raw", action="store", dest="raw_file", metavar="FILE",
                             help="Load raw HTTP request from file (use `--scheme` flag to set the scheme)")
        mandatory.add_option("-e", "--extensions", action="store", dest="extensions",
                             help="Extension list separated by commas (Example: php,asp)")
        mandatory.add_option("-X", "--exclude-extensions", action="store", dest="exclude_extensions", metavar="EXTENSIONS",
                             help="Exclude extension list separated by commas (Example: asp,jsp)")
        mandatory.add_option("-f", "--force-extensions", action="store_true", dest="force_extensions",
                             help="Add extensions to every wordlist entry. By default dirsearch only replaces the %EXT% keyword with extensions")
        mandatory.add_option("--config", action="store", dest="config", default=FileUtils.build_path(SCRIPT_PATH, "default.conf"), metavar="FILE",
                             help="Full path to config file, see 'default.conf' for example (Default: default.conf)")

        # Dictionary Settings
        dictionary = OptionGroup(parser, "Dictionary Settings")
        dictionary.add_option("-w", "--wordlists", action="store", dest="wordlist", help="Customize wordlists (separated by commas)")
        dictionary.add_option("--prefixes", action="store", dest="prefixes",
                              help="Add custom prefixes to all wordlist entries (separated by commas)")
        dictionary.add_option("--suffixes", action="store", dest="suffixes",
                              help="Add custom suffixes to all wordlist entries, ignore directories (separated by commas)")
        dictionary.add_option("--only-selected", action="store_true", dest="only_selected",
                              help="Remove paths have different extensions from selected ones via `-e` (keep entries don't have extensions)")
        dictionary.add_option("--remove-extensions", action="store_true", dest="no_extension",
                              help="Remove extensions in all paths (Example: admin.php -> admin)")
        dictionary.add_option("-U", "--uppercase", action="store_true", dest="uppercase", help="Uppercase wordlist")
        dictionary.add_option("-L", "--lowercase", action="store_true", dest="lowercase", help="Lowercase wordlist")
        dictionary.add_option("-C", "--capital", action="store_true", dest="capitalization", help="Capital wordlist")

        # Optional Settings
        general = OptionGroup(parser, "General Settings")
        general.add_option("-t", "--threads", action="store", type="int", dest="threads_count", metavar="THREADS",
                           help="Number of threads")
        general.add_option("-r", "--recursive", action="store_true", dest="recursive", help="Brute-force recursively")
        general.add_option("--deep-recursive", action="store_true", dest="deep_recursive",
                           help="Perform recursive scan on every directory depth (Example: api/users -> api/)")
        general.add_option("--force-recursive", action="store_true", dest="force_recursive",
                           help="Do recursive brute-force for every found path, not only paths end with slash")
        general.add_option("-R", "--recursion-depth", action="store", type="int", dest="recursion_depth", metavar="DEPTH",
                           help="Maximum recursion depth")
        general.add_option("--recursion-status", action="store", dest="recursion_status_codes", metavar="CODES",
                           help="Valid status codes to perform recursive scan, support ranges (separated by commas)")
        general.add_option("--subdirs", action="store", dest="scan_subdirs", metavar="SUBDIRS",
                           help="Scan sub-directories of the given URL[s] (separated by commas)")
        general.add_option("--exclude-subdirs", action="store", dest="exclude_subdirs", metavar="SUBDIRS",
                           help="Exclude the following subdirectories during recursive scan (separated by commas)")
        general.add_option("-i", "--include-status", action="store", dest="include_status_codes", metavar="CODES",
                           help="Include status codes, separated by commas, support ranges (Example: 200,300-399)")
        general.add_option("-x", "--exclude-status", action="store", dest="exclude_status_codes", metavar="CODES",
                           help="Exclude status codes, separated by commas, support ranges (Example: 301,500-599)")
        general.add_option("--exclude-sizes", action="store", dest="exclude_sizes", metavar="SIZES",
                           help="Exclude responses by sizes, separated by commas (Example: 123B,4KB)")
        general.add_option("--exclude-texts", action="store", dest="exclude_texts", metavar="TEXTS",
                           help="Exclude responses by texts, separated by commas (Example: 'Not found', 'Error')")
        general.add_option("--exclude-regexps", action="store", dest="exclude_regexps", metavar="REGEXPS",
                           help="Exclude responses by regexps, separated by commas (Example: 'Not foun[a-z]{1}', '^Error$')")
        general.add_option("--exclude-redirects", action="store", dest="exclude_redirects", metavar="REGEXPS",
                           help="Exclude responses by redirect regexps or texts, separated by commas (Example: 'https://okta.com/*')",)
        general.add_option("--exclude-response", action="store", dest="exclude_response", metavar="PATH",
                           help="Exclude responses by response of this page (path as input)")
        general.add_option("--skip-on-status", action="store", dest="skip_on_status", metavar="CODES",
                           help="Skip target whenever hit one of these status codes, separated by commas, support ranges")
        general.add_option("--minimal", action="store", type="int", dest="minimum_response_size",
                           help="Minimal response length", metavar="LENGTH")
        general.add_option("--maximal", action="store", type="int", dest="maximum_response_size",
                           help="Maximal response length", metavar="LENGTH")
        general.add_option("--redirects-history", action="store_true", dest="redirects_history",
                           help="Show redirects history (when following redirects is enabled)")
        general.add_option("--max-time", action="store", type="int", dest="maxtime", metavar="SECONDS",
                           help="Maximal runtime for the scan")
        general.add_option("-q", "--quiet-mode", action="store_true", dest="quiet", help="Quiet mode")
        general.add_option("--full-url", action="store_true", dest="full_url",
                           help="Full URLs in the output (enabled automatically in quiet mode)")
        general.add_option("--no-color", action="store_false", dest="color", help="No colored output")

        # Request Settings
        request = OptionGroup(parser, "Request Settings")
        request.add_option("-m", "--http-method", action="store", dest="httpmethod", metavar="METHOD",
                           help="HTTP method (default: GET)")
        request.add_option("-d", "--data", action="store", dest="data", help="HTTP request data")
        request.add_option("-H", "--header", action="append", dest="headers",
                           help="HTTP request header, support multiple flags (Example: -H 'Referer: example.com')")
        request.add_option("--header-list", dest="header_list", metavar="FILE", help="File contains HTTP request headers")
        request.add_option("-F", "--follow-redirects", action="store_true", dest="follow_redirects", help="Follow HTTP redirects")
        request.add_option("--random-agent", action="store_true", dest="use_random_agents",
                           help="Choose a random User-Agent for each request")
        request.add_option("--auth-type", action="store", dest="auth_type", metavar="TYPE",
                           help="Authentication type (basic, digest, bearer, ntlm)")
        request.add_option("--auth", action="store", dest="auth", metavar="CREDENTIAL",
                           help="Authentication credential ([user]:[password] or bearer token)")
        request.add_option("--user-agent", action="store", dest="useragent")
        request.add_option("--cookie", action="store", dest="cookie")

        # Connection Settings
        connection = OptionGroup(parser, "Connection Settings")
        connection.add_option("--timeout", action="store", type="float", dest="timeout", help="Connection timeout")
        connection.add_option("-s", "--delay", action="store", type="float", dest="delay", help="Delay between requests")
        connection.add_option("--proxy", action="store", dest="proxy", metavar="PROXY",
                              help="Proxy URL, support HTTP and SOCKS proxies (Example: localhost:8080, socks5://localhost:8088)")
        connection.add_option("--proxy-list", action="store", type="string", dest="proxy_list",
                              help="File contains proxy servers", metavar="FILE")
        connection.add_option("--replay-proxy", action="store", dest="replay_proxy", metavar="PROXY",
                              help="Proxy to replay with found paths")
        connection.add_option("--scheme", action="store", dest="scheme", metavar="SCHEME",
                              help="Default scheme for raw request or if there is no scheme in the URL (Default: auto-detect)")
        connection.add_option("--max-rate", action="store", type="int", dest="maxrate", metavar="RATE", help="Max requests per second")
        connection.add_option("--retries", action="store", type="int", dest="max_retries", metavar="RETRIES",
                              help="Number of retries for failed requests")
        connection.add_option("-b", "--request-by-hostname", action="store_true", dest="request_by_hostname",
                              help="By default dirsearch requests by IP for speed. This will force dirsearch to request by hostname")
        connection.add_option("--ip", action="store", dest="ip", help="Server IP address")
        connection.add_option("--exit-on-error", action="store_true", dest="exit_on_error", help="Exit whenever an error occurs")

        # Report Settings
        reports = OptionGroup(parser, "Reports")
        reports.add_option("-o", "--output", action="store", dest="output_file", metavar="FILE", help="Output file")
        reports.add_option("--format", action="store", dest="output_format", metavar="FORMAT",
                           help="Report format (Available: simple, plain, json, xml, md, csv, html, sqlite)")

        parser.add_option_group(mandatory)
        parser.add_option_group(dictionary)
        parser.add_option_group(general)
        parser.add_option_group(request)
        parser.add_option_group(connection)
        parser.add_option_group(reports)
        options, arguments = parser.parse_args()

        return options
