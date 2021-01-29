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
import email

from optparse import OptionParser, OptionGroup
from ipaddress import IPv4Network
from io import StringIO

from lib.utils.default_config_parser import DefaultConfigParser
from lib.utils.file_utils import File
from lib.utils.file_utils import FileUtils
from thirdparty.oset import oset


class ArgumentParser(object):
    def __init__(self, script_path):
        self.script_path = script_path
        self.parseConfig()

        options = self.parseArguments()

        self.quiet = options.quiet
        self.full_url = options.full_url
        self.urlList = None
        self.raw_file = None

        if not options.url:

            if options.urlList:

                with File(options.urlList) as urlList:

                    if not urlList.exists():
                        print("The file with URLs does not exist")
                        exit(1)

                    if not urlList.is_valid():
                        print("The file with URLs is invalid")
                        exit(1)

                    if not urlList.can_read():
                        print("The file with URLs cannot be read")
                        exit(1)

                    self.urlList = list(urlList.get_lines())

            elif options.cidr:
                self.urlList = [str(ip) for ip in IPv4Network(options.cidr)]

            elif options.stdin_urls:
                self.urlList = sys.stdin.read().splitlines()

            elif options.raw_file:
                with File(options.raw_file) as raw_content:
                    if not raw_content.exists():
                        print("The file with the raw request does not exist")
                        exit(1)

                    if not raw_content.is_valid():
                        print("The file with the raw request is invalid")
                        exit(1)

                    if not raw_content.can_read():
                        print("The file with the raw request cannot be read")
                        exit(1)

                self.raw_file = options.raw_file

            else:
                print("URL target is missing, try using -u <url>")
                exit(1)

        else:
            self.urlList = [options.url]

        if not options.extensions and not options.noExtension:
            print("WARNING: No extension was specified!")

        if options.noExtension:
            options.extensions = str()

        # Enable to use multiple dictionaries at once
        for dictFile in options.wordlist.split(","):
            with File(dictFile) as wordlist:
                if not wordlist.exists():
                    print("The wordlist file does not exist")
                    exit(1)

                if not wordlist.is_valid():
                    print("The wordlist is invalid")
                    exit(1)

                if not wordlist.can_read():
                    print("The wordlist cannot be read")
                    exit(1)

        if options.proxyList:
            with File(options.proxyList) as plist:
                if not plist.exists():
                    print("The proxylist file does not exist")
                    exit(1)

                if not plist.is_valid():
                    print("The proxylist is invalid")
                    exit(1)

                if not plist.can_read():
                    print("The proxylist cannot be read")
                    exit(1)

            self.proxylist = open(options.proxyList).read().splitlines()

            options.requestByHostname = True

        elif options.proxy:
            self.proxy = options.proxy
            options.requestByHostname = True

        else:
            self.proxy = None

        if options.replay_proxy:
            self.replay_proxy = options.replay_proxy
            options.requestByHostname = True

        else:
            self.replay_proxy = None

        if options.headers:
            try:
                self.headers = dict(
                    email.message_from_file(StringIO("\r\n".join(options.headers)))
                )
            except Exception:
                print("Invalid headers")
                exit(1)

        else:
            self.headers = {}

        if options.headerList:
            try:
                with File(options.headerList) as hlist:
                    if not hlist.exists():
                        print("The header list file does not exist")
                        exit(1)

                    if not hlist.is_valid():
                        print("The header list file is invalid")
                        exit(1)

                    if not hlist.can_read():
                        print("The header list cannot be read")
                        exit(1)

                    headers = dict(
                        email.message_from_file(StringIO(hlist.read()))
                    )

                    for key, value in headers.items():
                        self.headers[key] = value
            except Exception as e:
                print("Error in headers file: " + str(e))
                exit(1)

        if options.extensions == "*":
            self.extensions = [
                "php", "inc.php", "jsp", "jsf", "asp", "aspx", "do", "action", "cgi",
                "pl", "html", "htm", "js", "css", "json", "txt", "tar.gz", "tgz"
            ]
        elif options.extensions == "CHANGELOG.md":
            print("A weird extension was provided: CHANGELOG.md. Please do not use * as the extension or enclose it in double quotes")
            exit(0)
        else:
            self.extensions = list(
                oset([extension.lstrip(' .') for extension in options.extensions.split(",")])
            )

        if options.excludeExtensions:
            self.excludeExtensions = list(
                oset([excludeExtension.lstrip(' .') for excludeExtension in options.excludeExtensions.split(",")])
            )
        else:
            self.excludeExtensions = []

        self.useragent = options.useragent
        self.useRandomAgents = options.useRandomAgents
        self.cookie = options.cookie

        if options.threadsCount < 1:
            print("Threads number must be greater than zero")
            exit(1)

        self.threadsCount = options.threadsCount

        self.includeStatusCodes = []

        if options.includeStatusCodes:
            for statusCode in options.includeStatusCodes.split(","):
                try:
                    if "-" in statusCode:
                        statusCodes = [
                            i for i in range(
                                int(statusCode.split("-")[0].strip()),
                                int(statusCode.split("-")[1].strip()) + 1
                            )
                        ]
                        self.includeStatusCodes.extend(statusCodes)

                    else:
                        self.includeStatusCodes.append(int(statusCode.strip()))

                except ValueError:
                    print("Invalid status code or status code range: {0}".format(statusCode))
                    exit(1)

        self.excludeStatusCodes = []

        if options.excludeStatusCodes:
            for statusCode in options.excludeStatusCodes.split(","):
                try:
                    if "-" in statusCode:
                        statusCodes = [
                            i for i in range(
                                int(statusCode.split("-")[0].strip()),
                                int(statusCode.split("-")[1].strip()) + 1
                            )
                        ]
                        self.excludeStatusCodes.extend(statusCodes)

                    else:
                        self.excludeStatusCodes.append(int(statusCode.strip()))

                except ValueError:
                    print("Invalid status code or status code range: {0}".format(statusCode))
                    exit(1)

        if options.excludeSizes:
            try:
                self.excludeSizes = list(
                    oset(
                        [
                            excludeSize.strip().upper() if excludeSize else None
                            for excludeSize in options.excludeSizes.split(",")
                        ]
                    )
                )

            except ValueError:
                self.excludeSizes = []
        else:
            self.excludeSizes = []

        if options.excludeTexts:
            try:
                self.excludeTexts = list(
                    oset(
                        [
                            excludeText.strip() if excludeText else None
                            for excludeText in options.excludeTexts.split(",")
                        ]
                    )
                )

            except ValueError:
                self.excludeTexts = []
        else:
            self.excludeTexts = []

        if options.excludeRegexps:
            try:
                self.excludeRegexps = list(
                    oset(
                        [
                            excludeRegexp.strip() if excludeRegexp else None
                            for excludeRegexp in options.excludeRegexps.split(",")
                        ]
                    )
                )

            except ValueError:
                self.excludeRegexps = []
        else:
            self.excludeRegexps = []

        if options.excludeRedirects:
            try:
                self.excludeRedirects = list(
                    oset(
                        [
                            excludeRedirect.strip() if excludeRedirect else None
                            for excludeRedirect in options.excludeRedirects.split(",")
                        ]
                    )
                )

            except ValueError:
                self.excludeRedirects = []
        else:
            self.excludeRedirects = []

        self.prefixes = [] if not options.prefixes else list(oset([prefix.strip() for prefix in options.prefixes.split(",")]))
        self.suffixes = [] if not options.suffixes else list(oset([suffix.strip() for suffix in options.suffixes.split(",")]))
        if options.wordlist:
            self.wordlist = list(oset([wordlist.strip() for wordlist in options.wordlist.split(",")]))
        else:
            print("No wordlist was provided, try using -w <wordlist>")
            exit(1)

        self.lowercase = options.lowercase
        self.uppercase = options.uppercase
        self.capitalization = options.capitalization
        self.forceExtensions = options.forceExtensions
        self.data = options.data
        self.testFailPath = options.testFailPath
        self.color = options.color
        self.delay = options.delay
        self.timeout = options.timeout
        self.ip = options.ip
        self.maxRetries = options.maxRetries
        self.recursive = options.recursive
        self.minimumResponseSize = options.minimumResponseSize
        self.maximumResponseSize = options.maximumResponseSize
        self.noExtension = options.noExtension
        self.onlySelected = options.onlySelected
        self.simpleOutputFile = options.simpleOutputFile
        self.plainTextOutputFile = options.plainTextOutputFile
        self.jsonOutputFile = options.jsonOutputFile
        self.xmlOutputFile = options.xmlOutputFile
        self.markdownOutputFile = options.markdownOutputFile
        self.csvOutputFile = options.csvOutputFile

        if options.scanSubdirs:
            self.scanSubdirs = list(
                oset(
                    [subdir.strip(" /") + "/" for subdir in options.scanSubdirs.split(",")]
                )
            )

        else:
            self.scanSubdirs = []

        if options.excludeSubdirs:
            self.excludeSubdirs = list(
                oset(
                    [subdir.strip(" /") + "/" for subdir in options.excludeSubdirs.split(",")]
                )
            )

        else:
            self.excludeSubdirs = None

        if len(set(self.extensions).intersection(self.excludeExtensions)):
            print("Exclude extension list can not contain any extension that has already in the extension list")
            exit(1)

        self.redirect = options.followRedirects
        self.httpmethod = options.httpmethod
        self.scheme = options.scheme
        self.requestByHostname = options.requestByHostname
        self.exit_on_error = options.exit_on_error
        self.skip_on_429 = options.skip_on_429
        self.debug = options.debug

        self.recursion_depth = options.recursion_depth

        if self.scheme not in ["http", "https"]:
            print("Invalid URI scheme: {0}".format(self.scheme))
            exit(1)

    def parseConfig(self):
        config = DefaultConfigParser()
        configPath = FileUtils.build_path(self.script_path, "default.conf")
        config.read(configPath)

        # Mandatory
        self.defaultExtensions = config.safe_get("mandatory", "default-extensions", str())
        self.excludeExtensions = config.safe_get("mandatory", "exclude-extensions", None)
        self.forceExtensions = config.safe_getboolean("mandatory", "force-extensions", False)

        # General
        self.threadsCount = config.safe_getint(
            "general", "threads", 30, list(range(1, 300))
        )
        self.includeStatusCodes = config.safe_get("general", "include-status", None)
        self.excludeStatusCodes = config.safe_get("general", "exclude-status", None)
        self.excludeSizes = config.safe_get("general", "exclude-sizes", None)
        self.excludeTexts = config.safe_get("general", "exclude-texts", None)
        self.excludeRegexps = config.safe_get("general", "exclude-regexps", None)
        self.excludeRedirects = config.safe_get("general", "exclude-redirects", None)
        self.recursive = config.safe_getboolean("general", "recursive", False)
        self.recursion_depth = config.safe_getint("general", "recursion-depth", 0)
        self.testFailPath = config.safe_get("general", "calibration-path", "").strip()
        self.saveHome = config.safe_getboolean("general", "save-logs-home", False)
        self.excludeSubdirs = config.safe_get("general", "exclude-subdirs", None)
        self.useRandomAgents = config.safe_get(
            "general", "random-user-agents", False
        )
        self.skip_on_429 = config.safe_getboolean("general", "skip-on-429", False)
        self.full_url = config.safe_getboolean("general", "full-url", False)
        self.color = config.safe_getboolean("general", "color", True)
        self.quiet = config.safe_getboolean("general", "quiet-mode", False)

        # Reports
        self.autoSave = config.safe_getboolean("reports", "autosave-report", False)
        self.autoSaveFormat = config.safe_get(
            "reports", "autosave-report-format", "txt", ["txt", "simple", "json", "xml", "md", "csv"]
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
        self.headerList = config.safe_get("request", "headers-file", None)
        self.redirect = config.safe_getboolean("request", "follow-redirects", False)
        self.useragent = config.safe_get("request", "user-agent", None)
        self.cookie = config.safe_get("request", "cookie", None)

        # Connection
        self.delay = config.safe_getfloat("connection", "delay", 0)
        self.timeout = config.safe_getint("connection", "timeout", 10)
        self.maxRetries = config.safe_getint("connection", "max-retries", 3)
        self.proxy = config.safe_get("connection", "proxy", None)
        self.proxylist = config.safe_get("connection", "proxy-list", None)
        self.scheme = config.safe_get("connection", "scheme", "http", ["http", "https"])
        self.replay_proxy = config.safe_get("connection", "replay-proxy", None)
        self.requestByHostname = config.safe_getboolean(
            "connection", "request-by-hostname", False
        )
        self.exit_on_error = config.safe_getboolean("connection", "exit-on-error", False)
        self.debug = config.safe_getboolean("connection", "debug", False)

    def parseArguments(self):
        usage = "Usage: %prog [-u|--url] target [-e|--extensions] extensions [options]"
        parser = OptionParser(usage, version="dirsearch v0.4.1",
                              epilog="""
You can change the dirsearch default configurations (default extensions,
timeout, wordlist location, ...) by editing the "default.conf" file. More
information at https://github.com/maurosoria/dirsearch.""")

        # Mandatory arguments
        mandatory = OptionGroup(parser, "Mandatory")
        mandatory.add_option("-u", "--url", help="Target URL", action="store", type="string", dest="url", default=None)
        mandatory.add_option("-l", "--url-list", help="URL list file", action="store", type="string", dest="urlList",
                             default=None, metavar="FILE")
        mandatory.add_option("--stdin", help="URL list from STDIN", action="store_true", dest="stdin_urls")
        mandatory.add_option("--cidr", help="Target CIDR", action="store", type="string", dest="cidr", default=None)
        mandatory.add_option("--raw", help="File contains the raw request (use `--scheme` flag to set the scheme)", action="store",
                             dest="raw_file", metavar="FILE")
        mandatory.add_option("-e", "--extensions", help="Extension list separated by commas (Example: php,asp)",
                             action="store", dest="extensions", default=self.defaultExtensions)
        mandatory.add_option("-X", "--exclude-extensions", action="store", dest="excludeExtensions", default=self.excludeExtensions,
                             help="Exclude extension list separated by commas (Example: asp,jsp)", metavar="EXTENSIONS")
        mandatory.add_option("-f", "--force-extensions", action="store_true", dest="forceExtensions", default=self.forceExtensions,
                             help="Add extensions to the end of every wordlist entry. By default dirsearch only replaces the %EXT% keyword with extensions")

        # Dictionary Settings
        dictionary = OptionGroup(parser, "Dictionary Settings")
        dictionary.add_option("-w", "--wordlists", action="store", dest="wordlist",
                              help="Customize wordlists (separated by commas)",
                              default=self.wordlist)
        dictionary.add_option("--prefixes", action="store", dest="prefixes", default=self.prefixes,
                              help="Add custom prefixes to all entries (separated by commas)")
        dictionary.add_option("--suffixes", action="store", dest="suffixes", default=self.suffixes,
                              help="Add custom suffixes to all entries, ignore directories (separated by commas)")
        dictionary.add_option("--only-selected", dest="onlySelected", action="store_true",
                              help="Only directories + files with selected extensions (or no extension)")
        dictionary.add_option("--remove-extensions", dest="noExtension", action="store_true",
                              help="Remove extensions in all wordlist entries (Example: admin.php -> admin)")
        dictionary.add_option("-U", "--uppercase", action="store_true", dest="uppercase", default=self.uppercase,
                              help="Uppercase wordlist")
        dictionary.add_option("-L", "--lowercase", action="store_true", dest="lowercase", default=self.lowercase,
                              help="Lowercase wordlist")
        dictionary.add_option("-C", "--capital", action="store_true", dest="capitalization", default=self.capitalization,
                              help="Capital wordlist")

        # Optional Settings
        general = OptionGroup(parser, "General Settings")
        general.add_option("-r", "--recursive", help="Bruteforce recursively", action="store_true", dest="recursive",
                           default=self.recursive)
        general.add_option("-R", "--recursion-depth", help="Maximum recursion depth", action="store",
                           type="int", dest="recursion_depth", default=self.recursion_depth, metavar="DEPTH")
        general.add_option("-t", "--threads", help="Number of threads", action="store", type="int", dest="threadsCount",
                           default=self.threadsCount, metavar="THREADS")
        general.add_option("--subdirs", help="Scan sub-directories of the given URL[s] (separated by commas)", action="store",
                           dest="scanSubdirs", default=None, metavar="SUBDIRS")
        general.add_option("--exclude-subdirs", help="Exclude the following subdirectories during recursive scan (separated by commas)",
                           action="store", dest="excludeSubdirs", default=self.excludeSubdirs, metavar="SUBDIRS")
        general.add_option("-i", "--include-status", help="Include status codes, separated by commas, support ranges (Example: 200,300-399)",
                           action="store", dest="includeStatusCodes", default=self.includeStatusCodes, metavar="STATUS")
        general.add_option("-x", "--exclude-status", help="Exclude status codes, separated by commas, support ranges (Example: 301,500-599)",
                           action="store", dest="excludeStatusCodes", default=self.excludeStatusCodes, metavar="STATUS")
        general.add_option("--exclude-sizes", help="Exclude responses by sizes, separated by commas (Example: 123B,4KB)",
                           action="store", dest="excludeSizes", default=self.excludeSizes, metavar="SIZES")
        general.add_option("--exclude-texts", help="Exclude responses by texts, separated by commas (Example: 'Not found', 'Error')",
                           action="store", dest="excludeTexts", default=self.excludeTexts, metavar="TEXTS")
        general.add_option("--exclude-regexps", help="Exclude responses by regexps, separated by commas (Example: 'Not foun[a-z]{1}', '^Error$')",
                           action="store", dest="excludeRegexps", default=self.excludeRegexps, metavar="REGEXPS")
        general.add_option("--exclude-redirects", help="Exclude responses by redirect regexps or texts, separated by commas (Example: 'https://okta.com/*')",
                           action="store", dest="excludeRedirects", default=self.excludeRedirects, metavar="REGEXPS")
        general.add_option("--calibration", help="Path to test for calibration", action="store",
                           dest="testFailPath", default=self.testFailPath, metavar="PATH")
        general.add_option("--random-agent", help="Choose a random User-Agent for each request",
                           action="store_true", dest="useRandomAgents",)
        general.add_option("--minimal", action="store", dest="minimumResponseSize", type="int", default=None,
                           help="Minimal response length", metavar="LENGTH")
        general.add_option("--maximal", action="store", dest="maximumResponseSize", type="int", default=None,
                           help="Maximal response length", metavar="LENGTH")
        general.add_option("--skip-on-429", action="store_true", dest="skip_on_429",
                           help="Skip target whenever 429 status code is returned", default=self.skip_on_429)
        general.add_option("-q", "--quiet-mode", action="store_true", dest="quiet",
                           help="Quiet mode", default=self.quiet)
        general.add_option("--full-url", action="store_true", dest="full_url",
                           help="Print full URLs in the output", default=self.full_url)
        general.add_option("--no-color", help="No colored output", action="store_false",
                           dest="color", default=self.color)

        # Request Settings
        request = OptionGroup(parser, "Request Settings")
        request.add_option("-m", "--http-method", action="store", dest="httpmethod", type="string",
                           default=self.httpmethod, help="HTTP method (default: GET)", metavar="METHOD")
        request.add_option("-d", "--data", help="HTTP request data", action="store", dest="data",
                           type="str", default=None)
        request.add_option("-H", "--header", help="HTTP request header, support multiple flags (Example: -H 'Referer: example.com' -H 'Accept: */*')",
                           action="append", type="string", dest="headers", default=None)
        request.add_option("--header-list", help="File contains HTTP request headers", type="string",
                           dest="headerList", default=self.headerList, metavar="FILE")
        request.add_option("-F", "--follow-redirects", help="Follow HTTP redirects",
                           action="store_true", dest="followRedirects", default=self.redirect)
        request.add_option("--user-agent", action="store", type="string", dest="useragent",
                           default=self.useragent)
        request.add_option("--cookie", action="store", type="string", dest="cookie", default=self.cookie)

        # Connection Settings
        connection = OptionGroup(parser, "Connection Settings")
        connection.add_option("--timeout", action="store", dest="timeout", type="float",
                              default=self.timeout, help="Connection timeout")
        connection.add_option("--ip", action="store", dest="ip", default=None,
                              help="Server IP address")
        connection.add_option("-s", "--delay", help="Delay between requests", action="store", dest="delay",
                              type="float", default=self.delay)
        connection.add_option("--proxy", action="store", dest="proxy", type="string", default=self.proxy,
                              help="Proxy URL, support HTTP and SOCKS proxies (Example: localhost:8080, socks5://localhost:8088)", metavar="PROXY")
        connection.add_option("--proxy-list", action="store", dest="proxyList", type="string",
                              default=self.proxylist, help="File contains proxy servers", metavar="FILE")
        connection.add_option("--replay-proxy", action="store", dest="replay_proxy", type="string", default=self.replay_proxy,
                              help="Proxy to replay with found paths", metavar="PROXY")
        connection.add_option("--scheme", help="Default scheme (for raw request or if there is no scheme in the URL)", action="store",
                              default=self.scheme, dest="scheme", metavar="SCHEME")
        connection.add_option("--max-retries", action="store", dest="maxRetries", type="int",
                              default=self.maxRetries, metavar="RETRIES")
        connection.add_option("-b", "--request-by-hostname",
                              help="By default dirsearch requests by IP for speed. This will force requests by hostname",
                              action="store_true", dest="requestByHostname", default=self.requestByHostname)
        connection.add_option("--exit-on-error", action="store_true", dest="exit_on_error", default=self.exit_on_error,
                              help="Exit whenever an error occurs")
        connection.add_option("--debug", action="store_true", dest="debug", default=self.debug,
                              help="Debug mode")

        # Report Settings
        reports = OptionGroup(parser, "Reports")
        reports.add_option("--simple-report", action="store", dest="simpleOutputFile", default=None, metavar="OUTPUTFILE")
        reports.add_option("--plain-text-report", action="store", dest="plainTextOutputFile", default=None, metavar="OUTPUTFILE")
        reports.add_option("--json-report", action="store", dest="jsonOutputFile", default=None, metavar="OUTPUTFILE")
        reports.add_option("--xml-report", action="store", dest="xmlOutputFile", default=None, metavar="OUTPUTFILE")
        reports.add_option("--markdown-report", action="store", dest="markdownOutputFile", default=None, metavar="OUTPUTFILE")
        reports.add_option("--csv-report", action="store", dest="csvOutputFile", default=None, metavar="OUTPUTFILE")

        parser.add_option_group(mandatory)
        parser.add_option_group(dictionary)
        parser.add_option_group(general)
        parser.add_option_group(request)
        parser.add_option_group(connection)
        parser.add_option_group(reports)
        options, arguments = parser.parse_args()

        return options
