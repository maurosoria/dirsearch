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

from optparse import OptionParser, OptionGroup

from lib.utils.default_config_parser import DefaultConfigParser
from lib.utils.file_utils import File
from lib.utils.file_utils import FileUtils
from thirdparty.oset import *


class ArgumentParser(object):
    def __init__(self, script_path):
        self.script_path = script_path
        self.parse_config()

        options = self.parse_arguments()

        self.quiet = options.quiet
        self.full_url = options.full_url

        if not options.url:

            if options.url_list:

                with File(options.url_list) as url_list:

                    if not url_list.exists():
                        print("The file with URLs does not exist")
                        exit(0)

                    if not url_list.is_valid():
                        print("The file with URLs is invalid")
                        exit(0)

                    if not url_list.can_read():
                        print("The file with URLs cannot be read")
                        exit(0)

                    self.url_list = list(url_list.get_lines())

            elif not options.url:
                print("URL target is missing, try using -u <url> ")
                exit(0)

        else:
            self.url_list = [options.url]

        if not options.extensions and not options.default_extensions and not options.no_extension:
            print('No extension specified. You must specify at least one extension or try using default extension list.')
            exit(0)

        if not options.extensions and options.default_extensions:
            options.extensions = self.default_extensions
        if options.no_extension:
            options.extensions = ""

        # Enable to use multiple dictionaries at once
        for dictFile in options.wordlist.split(','):
            with File(dictFile) as wordlist:
                if not wordlist.exists():
                    print('The wordlist file does not exist')
                    exit(1)

                if not wordlist.is_valid():
                    print('The wordlist is invalid')
                    exit(1)

                if not wordlist.can_read():
                    print('The wordlist cannot be read')
                    exit(1)

        if options.proxy_list:
            with File(options.proxy_list) as plist:
                if not plist.exists():
                    print('The proxylist file does not exist')
                    exit(1)

                if not plist.is_valid():
                    print('The proxylist is invalid')
                    exit(1)

                if not plist.can_read():
                    print('The proxylist cannot be read')
                    exit(1)

            self.proxylist = open(options.proxy_list).read().splitlines()

        elif options.http_proxy:
            if options.http_proxy.startswith("http://") or options.http_proxy.startswith("https://") or options.http_proxy.startswith("socks5://"):
                self.proxy = options.http_proxy
            else:
                self.proxy = "http://{0}".format(options.http_proxy)

        else:
            self.proxy = None

        if options.headers:
            try:
                self.headers = dict(
                    (key, value)
                    for (key, value) in (
                        header.split(":", 1) for header in options.headers
                    )
                )
            except Exception:
                print("Invalid headers")
                exit(0)

        else:
            self.headers = {}

        if options.header_list:
            try:
                with File(options.header_list) as hlist:
                    if not hlist.exists():
                        print('The header list file does not exist')
                        exit(1)

                    if not hlist.is_valid():
                        print('The header list file is invalid')
                        exit(1)

                    if not hlist.can_read():
                        print('The header list cannot be read')
                        exit(1)

                    lines = hlist.get_lines()
                    for line in lines:
                        key, value = line.split(":")[0], line.split(":")[1]
                        self.headers[key] = value
            except Exception as e:
                print("Error in headers file: " + str(e))
                exit(0)

        self.extensions = list(
            oset([extension.strip() for extension in options.extensions.split(",")])
        )
        self.useragent = options.useragent
        self.use_random_agents = options.use_random_agents
        self.cookie = options.cookie

        if options.thread_count < 1:
            print('Threads number must be greater than zero')
            exit(1)

        self.thread_count = options.thread_count

        if options.include_status_codes:

            try:
                self.include_status_codes = list(
                    oset([int(include_status_code.strip()) if include_status_code else None for include_status_code in
                          options.include_status_codes.split(',')]))

            except ValueError:
                self.include_status_codes = []

        else:
            self.include_status_codes = []

        if options.exclude_extensions:

            try:
                self.exclude_extensions = list(
                    oset(
                        [
                            exclude_extension.strip() if exclude_extension else None
                            for exclude_extension in options.exclude_extensions.split(",")
                        ]
                    )
                )

            except ValueError:
                self.exclude_extensions = []

        else:
            self.exclude_extensions = []

        if options.exclude_status_codes:

            try:
                self.exclude_status_codes = list(
                    oset(
                        [
                            int(exclude_status_code.strip())
                            if exclude_status_code
                            else None
                            for exclude_status_code in options.exclude_status_codes.split(
                                ","
                            )
                        ]
                    )
                )

            except ValueError:
                self.exclude_status_codes = []

        else:
            self.exclude_status_codes = []

        if options.exclude_sizes:
            try:
                self.exclude_sizes = list(

                    oset(
                        [
                            exclude_size.strip().upper() if exclude_size else None
                            for exclude_size in options.exclude_sizes.split(",")
                        ]
                    )
                )

            except ValueError:
                self.exclude_sizes = []
        else:
            self.exclude_sizes = []

        if options.exclude_strings:
            try:
                self.exclude_strings = list(

                    oset(
                        [
                            exclude_strings.strip() if exclude_strings else None
                            for exclude_strings in options.exclude_strings.split(",")
                        ]
                    )
                )

            except ValueError:
                self.exclude_strings = []
        else:
            self.exclude_strings = []

        if options.exclude_regexps:
            try:
                self.exclude_regexps = list(
                    oset(
                        [
                            exclude_regexp.strip() if exclude_regexp else None
                            for exclude_regexp in options.exclude_regexps.split(",")
                        ]
                    )
                )

            except ValueError:
                self.exclude_regexps = []
        else:
            self.exclude_regexps = []

        self.prefixes = [] if not options.prefixes else list(oset([prefix.strip() for prefix in options.prefixes.split(',')]))
        self.suffixes = [] if not options.suffixes else list(oset([suffix.strip() for suffix in options.suffixes.split(',')]))
        self.wordlist = list(oset([wordlist.strip() for wordlist in options.wordlist.split(',')]))

        self.lowercase = options.lowercase
        self.uppercase = options.uppercase
        self.capitalization = options.capitalization
        self.force_extensions = options.force_extensions
        self.data = options.data
        self.no_dot_extensions = options.no_dot_extensions
        self.simple_output_file = options.simple_output_file
        self.plain_text_output_file = options.plain_text_output_file
        self.json_output_file = options.json_output_file
        self.xml_output_file = options.xml_output_file
        self.delay = options.delay
        self.timeout = options.timeout
        self.ip = options.ip
        self.max_retries = options.max_retries
        self.recursive = options.recursive
        self.suppress_empty = options.suppress_empty
        self.minimum_response_size = options.minimum_response_size
        self.maximum_response_size = options.maximum_response_size
        self.no_extension = options.no_extension

        if options.scanSubdirs:
            self.scan_subdirs = list(
                oset([subdir.strip() for subdir in options.scanSubdirs.split(",")])
            )

            for i in range(len(self.scan_subdirs)):

                while self.scan_subdirs[i].startswith("/"):
                    self.scan_subdirs[i] = self.scan_subdirs[i][1:]

                while self.scan_subdirs[i].endswith("/"):
                    self.scan_subdirs[i] = self.scan_subdirs[i][:-1]

            self.scan_subdirs = list(oset([subdir + "/" for subdir in self.scan_subdirs]))

        else:
            self.scan_subdirs = None

        if not self.recursive and options.exclude_subdirs:
            self.exclude_subdirs = None

        elif options.exclude_subdirs:
            self.exclude_subdirs = list(
                oset([subdir.strip() for subdir in options.exclude_subdirs.split(",")])
            )

            for i in range(len(self.exclude_subdirs)):

                while self.exclude_subdirs[i].startswith("/"):
                    self.exclude_subdirs[i] = self.exclude_subdirs[i][1:]

                while self.exclude_subdirs[i].endswith("/"):
                    self.exclude_subdirs[i] = self.exclude_subdirs[i][:-1]
            self.exclude_subdirs = list(oset(self.exclude_subdirs))

        else:
            self.exclude_subdirs = None

        if len(set(self.extensions).intersection(self.exclude_extensions)):
            print("Exclude extensions can not contain any extension that has already in the extensions")
            exit(0)

        self.redirect = options.no_follow_redirects
        self.request_by_hostname = options.request_by_hostname
        self.stop = options.stop
        self.httpmethod = options.httpmethod

        self.recursive_level_max = options.recursive_level_max

    def parse_config(self):
        config = DefaultConfigParser()
        config_path = FileUtils.build_path(self.script_path, "default.conf")
        config.read(config_path)

        # General
        self.thread_count = config.safe_getint(
            "general", "threads", 20, list(range(1, 200))
        )

        self.include_status_codes = config.safe_get("general", "include-status", None)

        self.exclude_status_codes = config.safe_get("general", "exclude-status", None)
        self.exclude_strings = config.safe_get("general", "exclude-texts", None)
        self.redirect = config.safe_getboolean("general", "follow-redirects", False)
        self.recursive = config.safe_getboolean("general", "recursive", False)
        self.recursive_level_max = config.safe_getint(
            "general", "recursive-level-max", 0
        )
        self.header_list = config.safe_get("general", "headers-file", None)
        self.suppress_empty = config.safe_getboolean("general", "suppress-empty", False)
        self.testFailPath = config.safe_get("general", "scanner-fail-path", "").strip()
        self.saveHome = config.safe_getboolean("general", "save-logs-home", False)
        self.default_extensions = config.safe_get(
            "general", "default-extensions", "php,asp,aspx,jsp,html,htm,js"
        )
        self.exclude_subdirs = config.safe_get("general", "exclude-subdirs", None)
        self.full_url = config.safe_getboolean("general", "full-url", False)
        self.quiet = config.safe_getboolean("general", "quiet-mode", False)

        # Reports
        self.auto_save = config.safe_getboolean("reports", "autosave-report", False)
        self.autoSaveFormat = config.safe_get(
            "reports", "autosave-report-format", "plain", ["plain", "simple", "json", "xml"]
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
        self.force_extensions = config.safe_getboolean("dictionary", "force-extensions", False)
        self.no_dot_extensions = config.safe_getboolean("dictionary", "no-dot-extensions", False)

        # Connection
        self.use_random_agents = config.safe_get(
            "connection", "random-user-agents", False
        )
        self.useragent = config.safe_get("connection", "user-agent", None)
        self.delay = config.safe_getfloat("connection", "delay", 0)
        self.timeout = config.safe_getint("connection", "timeout", 10)
        self.max_retries = config.safe_getint("connection", "max-retries", 3)
        self.proxy = config.safe_get("connection", "http-proxy", None)
        self.proxylist = config.safe_get("connection", "http-proxy-list", None)
        self.httpmethod = config.safe_get(
            "connection", "httpmethod", "get", ["get", "head", "post", "put", "patch", "delete", "trace", "options", "debug"]
        )
        self.request_by_hostname = config.safe_getboolean(
            "connection", "request-by-hostname", False
        )
        self.stop = config.safe_getboolean("connection", "stop-on-error", False)

    def parse_arguments(self):
        usage = "Usage: %prog [-u|--url] target [-e|--extensions] extensions [options]"
        parser = OptionParser(usage, epilog='''
You can change the dirsearch default configurations (default extensions, timeout, wordlist location, ...) by editing the "default.conf" file. More information at https://github.com/maurosoria/dirsearch.
''')

        # Mandatory arguments
        mandatory = OptionGroup(parser, 'Mandatory')
        mandatory.add_option('-u', '--url', help='URL target', action='store', type='string', dest='url', default=None)
        mandatory.add_option('-l', '--url-list', help='URL list file', action='store', type='string', dest='url_list',
                             default=None)
        mandatory.add_option('-e', '--extensions', help='Extension list separated by commas (Example: php,asp)',
                             action='store', dest='extensions', default=None)
        mandatory.add_option('-E', '--extensions-list', help='Use predefined list of common extensions',
                             action='store_true', dest='default_extensions', default=False)
        mandatory.add_option('-X', '--exclude-extensions',
                             help='Exclude extension list separated by commas (Example: asp,jsp)',
                             action='store', dest='exclude_extensions', default=None)

        # Dictionary Settings
        dictionary = OptionGroup(parser, 'Dictionary Settings')
        dictionary.add_option('-w', '--wordlist', action='store', dest='wordlist',
                              help='Customize wordlist (separated by commas)',
                              default=self.wordlist)
        dictionary.add_option('--prefixes', action='store', dest='prefixes', default=self.prefixes,
                              help='Add custom prefixes to all entries (separated by commas)')
        dictionary.add_option('--suffixes', action='store', dest='suffixes', default=self.suffixes,
                              help='Add custom suffixes to all entries, ignores directories (separated by commas)')
        dictionary.add_option('-f', '--force-extensions', action='store_true', dest='force_extensions', default=self.force_extensions,
                              help='Force extensions for every wordlist entry. Add %NOFORCE% at the end of the entry in the wordlist that you do not want to force')
        dictionary.add_option('--no-extension', dest='no_extension', action='store_true',
                              help='Remove extensions in all wordlist entries (Example: admin.php -> admin)')
        dictionary.add_option('--no-dot-extensions', dest='no_dot_extensions', default=self.no_dot_extensions,
                              help='Remove the "." character before extensions', action='store_true')
        dictionary.add_option('-C', '--capitalization', action='store_true', dest='capitalization', default=self.capitalization,
                              help='Capital wordlist')
        dictionary.add_option('-U', '--uppercase', action='store_true', dest='uppercase', default=self.uppercase,
                              help='Uppercase wordlist')
        dictionary.add_option('-L', '--lowercase', action='store_true', dest='lowercase', default=self.lowercase,
                              help='Lowercase wordlist')

        # Optional Settings
        general = OptionGroup(parser, 'General Settings')
        general.add_option('-d', '--data', help='HTTP request data', action='store', dest='data',
                           type='str', default=None)
        general.add_option('-r', '--recursive', help='Bruteforce recursively', action='store_true', dest='recursive',
                           default=self.recursive)
        general.add_option('-R', '--recursive-level-max',
                           help='Max recursion level (subdirs) (Default: 0 [infinity])', action='store', type='int',
                           dest='recursive_level_max',
                           default=self.recursive_level_max)
        general.add_option('--suppress-empty', action='store_true', dest='suppress_empty',
                           help='Suppress empty responses', default=self.suppress_empty)
        general.add_option('--minimal', action='store', dest='minimum_response_size', type='int', default=None,
                           help='Minimal response length')
        general.add_option('--maximal', action='store', dest='maximum_response_size', type='int', default=None,
                           help='Maximal response length')
        general.add_option('--scan-subdirs', help='Scan subdirectories of the given URL (separated by commas)', action='store',
                           dest='scanSubdirs', default=None)
        general.add_option('--exclude-subdirs', help='Exclude the following subdirectories during recursive scan (separated by commas)',
                           action='store', dest='exclude_subdirs', default=self.exclude_subdirs)
        general.add_option('-t', '--threads', help='Number of threads', action='store', type='int', dest='thread_count',
                           default=self.thread_count)
        general.add_option('-i', '--include-status', help='Show only included status codes, separated by commas (Example: 301, 500)',
                           action='store', dest='include_status_codes', default=self.include_status_codes)
        general.add_option('-x', '--exclude-status', help='Do not show excluded status codes, separated by commas (Example: 301, 500)',
                           action='store', dest='exclude_status_codes', default=self.exclude_status_codes)
        general.add_option('--exclude-sizes', help='Exclude responses by sizes, separated by commas (Example: 123B,4KB)',
                           action='store', dest='exclude_sizes', default=None)
        general.add_option('--exclude-texts', help='Exclude responses based on contained strings, separated by commas (Example: "Not found", "Error")',
                           action='store', dest='exclude_strings', default=None)
        general.add_option('--exclude-regexps', help='Exclude responses by regexps, separated by commas (Example: "Not foun[a-z]{1}", "^Error$")',
                           action='store', dest='exclude_regexps', default=None)
        general.add_option('-H', '--header', help='HTTP request header, support multiple flags (Example: -H "Referer: example.com" -H "Accept: */*")',
                           action='append', type='string', dest='headers', default=None)
        general.add_option('--header-list', help="File contains HTTP request headers", type='string',
                           dest='header_list', default=self.header_list)
        general.add_option('--user-agent', action='store', type='string', dest='useragent',
                           default=self.useragent)
        general.add_option('--random-agent', '--random-user-agent', action='store_true', dest='use_random_agents')
        general.add_option('--cookie', action='store', type='string', dest='cookie', default=None)
        general.add_option('-F', '--follow-redirects', action='store_true', dest='no_follow_redirects',
                           default=self.redirect)
        general.add_option('--full-url', action='store_true', dest='full_url',
                           help='Print the full URL in the output', default=self.full_url)
        general.add_option('-q', '--quiet-mode', action='store_true', dest='quiet', default=self.quiet)

        # Connection Settings
        connection = OptionGroup(parser, 'Connection Settings')
        connection.add_option('--timeout', action='store', dest='timeout', type='int',
                              default=self.timeout, help='Connection timeout')
        connection.add_option('--ip', action='store', dest='ip', default=None,
                              help='Server IP address')
        connection.add_option('-s', '--delay', help='Delay between requests (support float number)', action='store', dest='delay',
                              type='float', default=self.delay)
        connection.add_option('--proxy', action='store', dest='http_proxy', type='string',
                              default=self.proxy, help='Proxy URL, support HTTP and SOCKS proxy (Example: localhost:8080, socks5://localhost:8088)')
        connection.add_option('--proxy-list', action='store', dest='proxy_list', type='string',
                              default=self.proxylist, help='File contains proxy servers')
        connection.add_option('-m', '--http-method', action='store', dest='httpmethod', type='string',
                              default=self.httpmethod, help='HTTP method, default: GET')
        connection.add_option('--max-retries', action='store', dest='max_retries', type='int',
                              default=self.max_retries)
        connection.add_option('-b', '--request-by-hostname',
                              help='By default dirsearch will request by IP for speed. This will force requests by hostname',
                              action='store_true', dest='request_by_hostname', default=self.request_by_hostname)
        connection.add_option('--stop-on-error', action='store_true', dest='stop', default=self.stop,
                              help='Stop whenever an error occurs')

        # Report Settings
        reports = OptionGroup(parser, 'Reports')
        reports.add_option('--simple-report', action='store', help='Only found paths',
                           dest='simple_output_file', default=None)
        reports.add_option('--plain-text-report', action='store',
                           help='Found paths with status codes', dest='plain_text_output_file', default=None)
        reports.add_option('--json-report', action='store', dest='json_output_file', default=None)
        reports.add_option('--xml-report', action='store', dest='xml_output_file', default=None)

        parser.add_option_group(mandatory)
        parser.add_option_group(dictionary)
        parser.add_option_group(general)
        parser.add_option_group(connection)
        parser.add_option_group(reports)
        options, arguments = parser.parse_args()
        return options
