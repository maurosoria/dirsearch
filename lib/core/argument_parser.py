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

from lib.parse.configparser import ConfigParser
from lib.parse.headers import HeadersParser
from lib.utils.file import File
from lib.utils.file import FileUtils
from lib.utils.fmt import uniq
from lib.utils.range import get_range
from lib.utils.ip import iprange


class ArgumentParser(object):
    def __init__(self, script_path):
        self.script_path = script_path
        self.parse_config()

        options = self.parse_arguments()

        self.quiet = options.quiet
        self.full_url = options.full_url
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
            self.raw_file = options.raw_file
        elif not len(self.url_list):
            print("URL target is missing, try using -u <url>")
            exit(1)

        self.url_list = uniq(self.url_list)

        if not options.extensions and not options.no_extension:
            print("WARNING: No extension was specified!")

        if options.no_extension:
            options.extensions = str()

        for dict_file in options.wordlist.split(","):
            self.access_file(dict_file, "wordlist")

        if options.proxy_list:
            file = self.access_file(options.proxy_list, "proxylist file")
            self.proxylist = file.read().splitlines()

            options.request_by_hostname = True

        elif options.proxy:
            self.proxy = options.proxy
            options.request_by_hostname = True

        else:
            self.proxy = None

        if options.replay_proxy:
            self.replay_proxy = options.replay_proxy
            options.request_by_hostname = True

        else:
            self.replay_proxy = None

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
            self.extensions = [
                "php", "jsp", "asp", "aspx", "do", "action", "cgi",
                "pl", "html", "htm", "js", "json", "tar.gz", "bak"
            ]
        elif options.extensions == "banner.txt":
            print("A weird extension was provided: 'banner.txt'. Please do not use * as the extension or enclose it in double quotes")
            exit(0)
        else:
            self.extensions = uniq([extension.lstrip(' .') for extension in options.extensions.split(",")])

        if options.exclude_extensions:
            self.exclude_extensions = uniq(
                [exclude_extension.lstrip(' .') for exclude_extension in options.exclude_extensions.split(",")]
            )
        else:
            self.exclude_extensions = []

        self.useragent = options.useragent
        self.use_random_agents = options.use_random_agents
        self.cookie = options.cookie

        if options.threads_count < 1:
            print("Threads number must be greater than zero")
            exit(1)

        self.threads_count = options.threads_count

        if options.include_status_codes:
            self.include_status_codes = self.parse_status_codes(options.include_status_codes)
        else:
            self.include_status_codes = []

        if options.exclude_status_codes:
            self.exclude_status_codes = self.parse_status_codes(options.exclude_status_codes)
        else:
            self.exclude_status_codes = []

        if options.recursion_status_codes:
            self.recursion_status_codes = self.parse_status_codes(options.recursion_status_codes)
        else:
            self.recursion_status_codes = []

        if options.exclude_sizes:
            try:
                self.exclude_sizes = uniq([
                    exclude_size.strip().upper() if exclude_size else None
                    for exclude_size in options.exclude_sizes.split(",")
                ])

            except ValueError:
                self.exclude_sizes = []
        else:
            self.exclude_sizes = []

        if options.exclude_texts:
            try:
                self.exclude_texts = uniq([
                    exclude_text.strip() if exclude_text else None
                    for exclude_text in options.exclude_texts.split(",")
                ])

            except ValueError:
                self.exclude_texts = []
        else:
            self.exclude_texts = []

        if options.exclude_regexps:
            try:
                self.exclude_regexps = uniq([
                    exclude_regexp.strip() if exclude_regexp else None
                    for exclude_regexp in options.exclude_regexps.split(",")
                ])

            except ValueError:
                self.exclude_regexps = []
        else:
            self.exclude_regexps = []

        if options.exclude_redirects:
            try:
                self.exclude_redirects = uniq([
                    exclude_redirect.strip() if exclude_redirect else None
                    for exclude_redirect in options.exclude_redirects.split(",")
                ])

            except ValueError:
                self.exclude_redirects = []
        else:
            self.exclude_redirects = []

        self.prefixes = uniq([prefix.strip() for prefix in options.prefixes.split(",")]) if options.prefixes else []
        self.suffixes = uniq([suffix.strip() for suffix in options.suffixes.split(",")]) if options.suffixes else []
        if options.wordlist:
            self.wordlist = uniq([wordlist.strip() for wordlist in options.wordlist.split(",")])
        else:
            print("No wordlist was provided, try using -w <wordlist>")
            exit(1)

        self.lowercase = options.lowercase
        self.uppercase = options.uppercase
        self.capitalization = options.capitalization
        self.force_extensions = options.force_extensions
        self.data = options.data
        self.exclude_response = options.exclude_response
        self.color = options.color
        self.delay = options.delay
        self.timeout = options.timeout
        self.ip = options.ip
        self.max_retries = options.max_retries
        self.recursive = options.recursive
        self.deep_recursive = options.deep_recursive
        self.force_recursive = options.force_recursive
        self.minimum_response_size = options.minimum_response_size
        self.maximum_response_size = options.maximum_response_size
        self.no_extension = options.no_extension
        self.only_selected = options.only_selected
        self.output_file = options.output_file
        self.output_format = options.output_format

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
        else:
            self.skip_on_status = []

        if options.auth and options.auth_type and (
            options.auth_type not in ["basic", "digest", "bearer", "ntlm"]
        ):
            print("'{0}' is not in available authentication types: basic, digest, bearer, ntlm".format(options.auth_type))
            exit(1)
        elif options.auth and not options.auth_type:
            print("Please select the authentication type with --auth-type")
            exit(1)
        elif options.auth_type and not options.auth:
            print("No authentication credential found")
            exit(1)

        if len(set(self.extensions).intersection(self.exclude_extensions)):
            print("Exclude extension list can not contain any extension that has already in the extension list")
            exit(1)

        self.auth_type = options.auth_type
        self.auth = options.auth
        self.redirect = options.follow_redirects
        self.httpmethod = options.httpmethod
        self.scheme = options.scheme
        self.request_by_hostname = options.request_by_hostname
        self.exit_on_error = options.exit_on_error
        self.maxrate = options.maxrate
        self.maxtime = options.maxtime

        self.recursion_depth = options.recursion_depth

        if self.output_format and self.output_format not in ["simple", "plain", "json", "xml", "md", "csv", "html"]:
            print("Select one of the following output formats: simple, plain, json, xml, md, csv, html")
            exit(1)

    def parse_status_codes(self, raw_status_codes):
        status_codes = []
        for status_code in raw_status_codes.split(","):
            try:
                if "-" in status_code:
                    status_codes.extend(get_range(status_code))

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

    def parse_config(self):
        config = ConfigParser()
        config_path = FileUtils.build_path(self.script_path, "default.conf")
        config.read(config_path)

        # Mandatory
        self.default_extensions = config.safe_get("mandatory", "default-extensions", str())
        self.exclude_extensions = config.safe_get("mandatory", "exclude-extensions", None)
        self.force_extensions = config.safe_getboolean("mandatory", "force-extensions", False)

        # General
        self.threads_count = config.safe_getint(
            "general", "threads", 30, list(range(1, 300))
        )
        self.include_status_codes = config.safe_get("general", "include-status", None)
        self.exclude_status_codes = config.safe_get("general", "exclude-status", None)
        self.exclude_sizes = config.safe_get("general", "exclude-sizes", None)
        self.exclude_texts = config.safe_get("general", "exclude-texts", None)
        self.exclude_regexps = config.safe_get("general", "exclude-regexps", None)
        self.exclude_redirects = config.safe_get("general", "exclude-redirects", None)
        self.exclude_response = config.safe_get("general", "exclude-response", "")
        self.recursive = config.safe_getboolean("general", "recursive", False)
        self.deep_recursive = config.safe_getboolean("general", "deep-recursive", False)
        self.force_recursive = config.safe_getboolean("general", "force-recursive", False)
        self.recursion_depth = config.safe_getint("general", "recursion-depth", 0)
        self.recursion_status_codes = config.safe_get("general", "recursion-status", None)
        self.scan_subdirs = config.safe_get("general", "subdirs", None)
        self.exclude_subdirs = config.safe_get("general", "exclude-subdirs", None)
        self.skip_on_status = config.safe_get("general", "skip-on-status", None)
        self.maxtime = config.safe_getint("general", "max-time", 0)
        self.full_url = config.safe_getboolean("general", "full-url", False)
        self.color = config.safe_getboolean("general", "color", True)
        self.quiet = config.safe_getboolean("general", "quiet-mode", False)

        # Reports
        self.output_location = config.safe_get("reports", "report-output-folder", None)
        self.autosave_report = config.safe_getboolean("reports", "autosave-report", False)
        self.logs_location = config.safe_get("reports", "logs-location", None)
        self.output_format = config.safe_get(
            "reports", "report-format", "plain", ["plain", "simple", "json", "xml", "md", "csv", "html"]
        )

        # Dictionary
        self.wordlist = config.safe_get(
            "dictionary",
            "wordlist",
            FileUtils.build_path(self.script_path, "db", "dicc.txt"),
        )
        self.prefixes = config.safe_get("dictionary", "prefixes", None)
        self.suffixes = config.safe_get("dictionary", "suffixes", None)
        self.lowercase = config.safe_getboolean("dictionary", "lowercase", False)
        self.uppercase = config.safe_getboolean("dictionary", "uppercase", False)
        self.capitalization = config.safe_getboolean("dictionary", "capitalization", False)

        # Request
        self.httpmethod = config.safe_get(
            "request", "httpmethod", "get"
        )
        self.header_list = config.safe_get("request", "headers-file", None)
        self.redirect = config.safe_getboolean("request", "follow-redirects", False)
        self.use_random_agents = config.safe_get("request", "random-user-agents", False)
        self.useragent = config.safe_get("request", "user-agent", "")
        self.cookie = config.safe_get("request", "cookie", "")

        # Connection
        self.delay = config.safe_getfloat("connection", "delay", 0)
        self.timeout = config.safe_getfloat("connection", "timeout", 7.5)
        self.max_retries = config.safe_getint("connection", "retries", 1)
        self.maxrate = config.safe_getint("connection", "max-rate", 0)
        self.proxy = config.safe_get("connection", "proxy", None)
        self.proxylist = config.safe_get("connection", "proxy-list", None)
        self.scheme = config.safe_get("connection", "scheme", None, ["http", "https"])
        self.replay_proxy = config.safe_get("connection", "replay-proxy", None)
        self.request_by_hostname = config.safe_getboolean(
            "connection", "request-by-hostname", False
        )
        self.exit_on_error = config.safe_getboolean("connection", "exit-on-error", False)

    def parse_arguments(self):
        usage = "Usage: %prog [-u|--url] target [-e|--extensions] extensions [options]"
        parser = OptionParser(usage, version="dirsearch v0.4.2",
                              epilog="""
You can change the dirsearch default configurations (default extensions,
timeout, wordlist location, ...) by editing the "default.conf" file. More
information at https://github.com/maurosoria/dirsearch.""")

        # Mandatory arguments
        mandatory = OptionGroup(parser, "Mandatory")
        mandatory.add_option("-u", "--url", help="Target URL", action="store", type="string", dest="url", default=None)
        mandatory.add_option("-l", "--url-list", help="Target URL list file", action="store", type="string", dest="url_list",
                             default=None, metavar="FILE")
        mandatory.add_option("--stdin", help="Target URL list from STDIN", action="store_true", dest="stdin_urls")
        mandatory.add_option("--cidr", help="Target CIDR", action="store", type="string", dest="cidr", default=None)
        mandatory.add_option("--raw", help="Load raw HTTP request from file (use `--scheme` flag to set the scheme)", action="store",
                             dest="raw_file", metavar="FILE")
        mandatory.add_option("-e", "--extensions", help="Extension list separated by commas (Example: php,asp)",
                             action="store", dest="extensions", default=self.default_extensions)
        mandatory.add_option("-X", "--exclude-extensions", action="store", dest="exclude_extensions", default=self.exclude_extensions,
                             help="Exclude extension list separated by commas (Example: asp,jsp)", metavar="EXTENSIONS")
        mandatory.add_option("-f", "--force-extensions", action="store_true", dest="force_extensions", default=self.force_extensions,
                             help="Add extensions to every wordlist entry. By default dirsearch only replaces the %EXT% keyword with extensions")

        # Dictionary Settings
        dictionary = OptionGroup(parser, "Dictionary Settings")
        dictionary.add_option("-w", "--wordlists", action="store", dest="wordlist",
                              help="Customize wordlists (separated by commas)",
                              default=self.wordlist)
        dictionary.add_option("--prefixes", action="store", dest="prefixes", default=self.prefixes,
                              help="Add custom prefixes to all wordlist entries (separated by commas)")
        dictionary.add_option("--suffixes", action="store", dest="suffixes", default=self.suffixes,
                              help="Add custom suffixes to all wordlist entries, ignore directories (separated by commas)")
        dictionary.add_option("--only-selected", dest="only_selected", action="store_true",
                              help="Remove paths have different extensions from selected ones via `-e` (keep entries don't have extensions)")
        dictionary.add_option("--remove-extensions", dest="no_extension", action="store_true",
                              help="Remove extensions in all paths (Example: admin.php -> admin)")
        dictionary.add_option("-U", "--uppercase", action="store_true", dest="uppercase", default=self.uppercase,
                              help="Uppercase wordlist")
        dictionary.add_option("-L", "--lowercase", action="store_true", dest="lowercase", default=self.lowercase,
                              help="Lowercase wordlist")
        dictionary.add_option("-C", "--capital", action="store_true", dest="capitalization", default=self.capitalization,
                              help="Capital wordlist")

        # Optional Settings
        general = OptionGroup(parser, "General Settings")
        general.add_option("-t", "--threads", help="Number of threads", action="store", type="int", dest="threads_count",
                           default=self.threads_count, metavar="THREADS")
        general.add_option("-r", "--recursive", help="Brute-force recursively", action="store_true", dest="recursive",
                           default=self.recursive)
        general.add_option("--deep-recursive", help="Perform recursive scan on every directory depth (Example: api/users -> api/)", action="store_true", dest="deep_recursive",
                           default=self.deep_recursive)
        general.add_option("--force-recursive", help="Do recursive brute-force for every found path, not only paths end with slash", action="store_true", dest="force_recursive",
                           default=self.force_recursive)
        general.add_option("-R", "--recursion-depth", help="Maximum recursion depth", action="store",
                           type="int", dest="recursion_depth", default=self.recursion_depth, metavar="DEPTH")
        general.add_option("--recursion-status", help="Valid status codes to perform recursive scan, support ranges (separated by commas)",
                           action="store", dest="recursion_status_codes", default=self.recursion_status_codes, metavar="CODES")
        general.add_option("--subdirs", help="Scan sub-directories of the given URL[s] (separated by commas)", action="store",
                           dest="scan_subdirs", default=self.scan_subdirs, metavar="SUBDIRS")
        general.add_option("--exclude-subdirs", help="Exclude the following subdirectories during recursive scan (separated by commas)",
                           action="store", dest="exclude_subdirs", default=self.exclude_subdirs, metavar="SUBDIRS")
        general.add_option("-i", "--include-status", help="Include status codes, separated by commas, support ranges (Example: 200,300-399)",
                           action="store", dest="include_status_codes", default=self.include_status_codes, metavar="CODES")
        general.add_option("-x", "--exclude-status", help="Exclude status codes, separated by commas, support ranges (Example: 301,500-599)",
                           action="store", dest="exclude_status_codes", default=self.exclude_status_codes, metavar="CODES")
        general.add_option("--exclude-sizes", help="Exclude responses by sizes, separated by commas (Example: 123B,4KB)",
                           action="store", dest="exclude_sizes", default=self.exclude_sizes, metavar="SIZES")
        general.add_option("--exclude-texts", help="Exclude responses by texts, separated by commas (Example: 'Not found', 'Error')",
                           action="store", dest="exclude_texts", default=self.exclude_texts, metavar="TEXTS")
        general.add_option("--exclude-regexps", help="Exclude responses by regexps, separated by commas (Example: 'Not foun[a-z]{1}', '^Error$')",
                           action="store", dest="exclude_regexps", default=self.exclude_regexps, metavar="REGEXPS")
        general.add_option("--exclude-redirects", help="Exclude responses by redirect regexps or texts, separated by commas (Example: 'https://okta.com/*')",
                           action="store", dest="exclude_redirects", default=self.exclude_redirects, metavar="REGEXPS")
        general.add_option("--exclude-response", help="Exclude responses by response of this page (path as input)", action="store",
                           dest="exclude_response", default=self.exclude_response, metavar="PATH")
        general.add_option("--skip-on-status", action="store", dest="skip_on_status", default=self.skip_on_status,
                           help="Skip target whenever hit one of these status codes, separated by commas, support ranges", metavar="CODES")
        general.add_option("--minimal", action="store", dest="minimum_response_size", type="int", default=None,
                           help="Minimal response length", metavar="LENGTH")
        general.add_option("--maximal", action="store", dest="maximum_response_size", type="int", default=None,
                           help="Maximal response length", metavar="LENGTH")
        general.add_option("--max-time", action="store", dest="maxtime", type="int", default=self.maxtime,
                           help="Maximal runtime for the scan", metavar="SECONDS")
        general.add_option("-q", "--quiet-mode", action="store_true", dest="quiet",
                           help="Quiet mode", default=self.quiet)
        general.add_option("--full-url", action="store_true", dest="full_url",
                           help="Full URLs in the output (enabled automatically in quiet mode)", default=self.full_url)
        general.add_option("--no-color", help="No colored output", action="store_false",
                           dest="color", default=self.color)

        # Request Settings
        request = OptionGroup(parser, "Request Settings")
        request.add_option("-m", "--http-method", action="store", dest="httpmethod", type="string",
                           default=self.httpmethod, help="HTTP method (default: GET)", metavar="METHOD")
        request.add_option("-d", "--data", help="HTTP request data", action="store", dest="data",
                           type="str", default=None)
        request.add_option("-H", "--header", help="HTTP request header, support multiple flags (Example: -H 'Referer: example.com')",
                           action="append", type="string", dest="headers", default=None)
        request.add_option("--header-list", help="File contains HTTP request headers", type="string",
                           dest="header_list", default=self.header_list, metavar="FILE")
        request.add_option("-F", "--follow-redirects", help="Follow HTTP redirects",
                           action="store_true", dest="follow_redirects", default=self.redirect)
        request.add_option("--random-agent", help="Choose a random User-Agent for each request",
                           default=self.use_random_agents, action="store_true", dest="use_random_agents")
        request.add_option("--auth-type", help="Authentication type (basic, digest, bearer, ntlm)",
                           action="store", dest="auth_type", metavar="TYPE")
        request.add_option("--auth", help="Authentication credential (user:password or bearer token)",
                           action="store", dest="auth", metavar="CREDENTIAL")
        request.add_option("--user-agent", action="store", type="string", dest="useragent",
                           default=self.useragent)
        request.add_option("--cookie", action="store", type="string", dest="cookie", default=self.cookie)

        # Connection Settings
        connection = OptionGroup(parser, "Connection Settings")
        connection.add_option("--timeout", action="store", dest="timeout", type="float",
                              default=self.timeout, help="Connection timeout")
        connection.add_option("-s", "--delay", help="Delay between requests", action="store", dest="delay",
                              type="float", default=self.delay)
        connection.add_option("--proxy", action="store", dest="proxy", type="string", default=self.proxy,
                              help="Proxy URL, support HTTP and SOCKS proxies (Example: localhost:8080, socks5://localhost:8088)", metavar="PROXY")
        connection.add_option("--proxy-list", action="store", dest="proxy_list", type="string",
                              default=self.proxylist, help="File contains proxy servers", metavar="FILE")
        connection.add_option("--replay-proxy", action="store", dest="replay_proxy", type="string", default=self.replay_proxy,
                              help="Proxy to replay with found paths", metavar="PROXY")
        connection.add_option("--scheme", help="Default scheme for raw request or if there is no scheme in the URL (Default: auto-detect)", action="store",
                              default=self.scheme, dest="scheme", metavar="SCHEME")
        connection.add_option("--max-rate", help="Max requests per second", action="store", dest="maxrate",
                              type="int", default=self.maxrate, metavar="RATE")
        connection.add_option("--retries", help="Number of retries for failed requests", action="store",
                              dest="max_retries", type="int", default=self.max_retries, metavar="RETRIES")
        connection.add_option("-b", "--request-by-hostname",
                              help="By default dirsearch requests by IP for speed. This will force dirsearch to request by hostname",
                              action="store_true", dest="request_by_hostname", default=self.request_by_hostname)
        connection.add_option("--ip", action="store", dest="ip", default=None,
                              help="Server IP address")
        connection.add_option("--exit-on-error", action="store_true", dest="exit_on_error", default=self.exit_on_error,
                              help="Exit whenever an error occurs")

        # Report Settings
        reports = OptionGroup(parser, "Reports")
        reports.add_option("-o", "--output", action="store", dest="output_file", default=None, metavar="FILE", help="Output file")
        reports.add_option("--format", action="store", dest="output_format", default=self.output_format, metavar="FORMAT",
                           help="Report format (Available: simple, plain, json, xml, md, csv, html)")

        parser.add_option_group(mandatory)
        parser.add_option_group(dictionary)
        parser.add_option_group(general)
        parser.add_option_group(request)
        parser.add_option_group(connection)
        parser.add_option_group(reports)
        options, arguments = parser.parse_args()

        return options
