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
        self.parseConfig()

        options = self.parseArguments()

        self.quiet = options.quiet
        self.full_url = options.full_url

        if not options.url:

            if options.urlList:

                with File(options.urlList) as urlList:

                    if not urlList.exists():
                        print("The file with URLs does not exist")
                        exit(0)

                    if not urlList.is_valid():
                        print("The file with URLs is invalid")
                        exit(0)

                    if not urlList.can_read():
                        print("The file with URLs cannot be read")
                        exit(0)

                    self.urlList = list(urlList.get_lines())

            elif not options.url:
                print("URL target is missing, try using -u <url> ")
                exit(0)

        else:
            self.urlList = [options.url]

        if not options.extensions and not options.defaultExtensions and not options.noExtension:
            print('No extension specified. You must specify at least one extension or try using default extension list.')
            exit(0)

        if not options.extensions and options.defaultExtensions:
            options.extensions = self.defaultExtensions
        if options.noExtension:
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

        if options.proxyList:
            with File(options.proxyList) as plist:
                if not plist.exists():
                    print('The proxylist file does not exist')
                    exit(1)

                if not plist.is_valid():
                    print('The proxylist is invalid')
                    exit(1)

                if not plist.can_read():
                    print('The proxylist cannot be read')
                    exit(1)

            self.proxylist = open(options.proxyList).read().splitlines()

        elif options.httpProxy:
            if options.httpProxy.startswith("http://") or options.httpProxy.startswith("https://") or options.httpProxy.startswith("socks5://"):
                self.proxy = options.httpProxy
            else:
                self.proxy = "http://{0}".format(options.httpProxy)

        else:
            self.proxy = None

        if options.headers:
            try:
                self.headers = dict(
                    (key.strip(), value.strip())
                    for (key, value) in (
                        header.split(":", 1) for header in options.headers
                    )
                )
            except Exception:
                print("Invalid headers")
                exit(0)

        else:
            self.headers = {}

        if options.headerList:
            try:
                with File(options.headerList) as hlist:
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
                        line = line.strip()
                        key, value = line.split(":")[0].strip(), line.split(":")[1].strip()
                        self.headers[key] = value
            except Exception as e:
                print("Error in headers file: " + str(e))
                exit(0)

        self.extensions = list(
            oset([extension.strip() for extension in options.extensions.split(",")])
        )
        self.useragent = options.useragent
        self.useRandomAgents = options.useRandomAgents
        self.cookie = options.cookie

        if options.threadsCount < 1:
            print('Threads number must be a number greater than zero')
            exit(1)

        self.threadsCount = options.threadsCount

        if options.includeStatusCodes:

            try:
                self.includeStatusCodes = list(
                    oset([int(includeStatusCode.strip()) if includeStatusCode else None for includeStatusCode in
                          options.includeStatusCodes.split(',')]))

            except ValueError:
                self.includeStatusCodes = []

        else:
            self.includeStatusCodes = []

        if options.excludeExtensions:

            try:
                self.excludeExtensions = list(
                    oset(
                        [
                            excludeExtension.strip() if excludeExtension else None
                            for excludeExtension in options.excludeExtensions.split(",")
                        ]
                    )
                )

            except ValueError:
                self.excludeExtensions = []

        else:
            self.excludeExtensions = []

        if options.excludeStatusCodes:

            try:
                self.excludeStatusCodes = list(
                    oset(
                        [
                            int(excludeStatusCode.strip())
                            if excludeStatusCode
                            else None
                            for excludeStatusCode in options.excludeStatusCodes.split(
                                ","
                            )
                        ]
                    )
                )

            except ValueError:
                self.excludeStatusCodes = []

        else:
            self.excludeStatusCodes = []

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

        self.prefixes = [] if not options.prefixes else list(oset([prefix.strip() for prefix in options.prefixes.split(',')]))
        self.suffixes = [] if not options.suffixes else list(oset([suffix.strip() for suffix in options.suffixes.split(',')]))
        self.wordlist = list(oset([wordlist.strip() for wordlist in options.wordlist.split(',')]))

        self.lowercase = options.lowercase
        self.uppercase = options.uppercase
        self.capitalization = options.capitalization
        self.forceExtensions = options.forceExtensions
        self.data = options.data
        self.noDotExtensions = options.noDotExtensions
        self.simpleOutputFile = options.simpleOutputFile
        self.plainTextOutputFile = options.plainTextOutputFile
        self.jsonOutputFile = options.jsonOutputFile
        self.delay = options.delay
        self.timeout = options.timeout
        self.ip = options.ip
        self.maxRetries = options.maxRetries
        self.recursive = options.recursive
        self.suppressEmpty = options.suppressEmpty
        self.minimumResponseSize = options.minimumResponseSize
        self.maximumResponseSize = options.maximumResponseSize
        self.noExtension = options.noExtension

        if options.scanSubdirs:
            self.scanSubdirs = list(
                oset([subdir.strip() for subdir in options.scanSubdirs.split(",")])
            )

            for i in range(len(self.scanSubdirs)):

                while self.scanSubdirs[i].startswith("/"):
                    self.scanSubdirs[i] = self.scanSubdirs[i][1:]

                while self.scanSubdirs[i].endswith("/"):
                    self.scanSubdirs[i] = self.scanSubdirs[i][:-1]

            self.scanSubdirs = list(oset([subdir + "/" for subdir in self.scanSubdirs]))

        else:
            self.scanSubdirs = None

        if not self.recursive and options.excludeSubdirs:
            self.excludeSubdirs = None

        elif options.excludeSubdirs:
            self.excludeSubdirs = list(
                oset([subdir.strip() for subdir in options.excludeSubdirs.split(",")])
            )

            for i in range(len(self.excludeSubdirs)):

                while self.excludeSubdirs[i].startswith("/"):
                    self.excludeSubdirs[i] = self.excludeSubdirs[i][1:]

                while self.excludeSubdirs[i].endswith("/"):
                    self.excludeSubdirs[i] = self.excludeSubdirs[i][:-1]
            self.excludeSubdirs = list(oset(self.excludeSubdirs))

        else:
            self.excludeSubdirs = None

        if len(set(self.extensions).intersection(self.excludeExtensions)):
            print("Exclude extensions can not contain any extension that has already in the extensions")
            exit(0)

        self.redirect = options.noFollowRedirects
        self.requestByHostname = options.requestByHostname
        self.stop = options.stop
        self.httpmethod = options.httpmethod

        self.recursive_level_max = options.recursive_level_max

    def parseConfig(self):
        config = DefaultConfigParser()
        configPath = FileUtils.build_path(self.script_path, "default.conf")
        config.read(configPath)

        # General
        self.threadsCount = config.safe_getint(
            "general", "threads", 20, list(range(1, 200))
        )

        self.includeStatusCodes = config.safe_get("general", "include-status", None)

        self.excludeStatusCodes = config.safe_get("general", "exclude-status", None)
        self.excludeTexts = config.safe_get("general", "exclude-texts", None)
        self.redirect = config.safe_getboolean("general", "follow-redirects", False)
        self.recursive = config.safe_getboolean("general", "recursive", False)
        self.recursive_level_max = config.safe_getint(
            "general", "recursive-level-max", 1
        )
        self.suppressEmpty = config.safe_getboolean("general", "suppress-empty", False)
        self.testFailPath = config.safe_get("general", "scanner-fail-path", "").strip()
        self.saveHome = config.safe_getboolean("general", "save-logs-home", False)
        self.defaultExtensions = config.safe_get(
            "general", "default-extensions", "php,asp,aspx,jsp,html,htm,js"
        )
        self.excludeSubdirs = config.safe_get("general", "exclude-subdirs", None)
        self.full_url = config.safe_getboolean("general", "full-url", False)
        self.quiet = config.safe_getboolean("general", "quiet-mode", False)

        # Reports
        self.autoSave = config.safe_getboolean("reports", "autosave-report", False)
        self.autoSaveFormat = config.safe_get(
            "reports", "autosave-report-format", "plain", ["plain", "json", "simple"]
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
        self.forceExtensions = config.safe_getboolean("dictionary", "force-extensions", False)
        self.noDotExtensions = config.safe_getboolean("dictionary", "no-dot-extensions", False)

        # Connection
        self.useRandomAgents = config.safe_get(
            "connection", "random-user-agents", False
        )
        self.useragent = config.safe_get("connection", "user-agent", None)
        self.delay = config.safe_getfloat("connection", "delay", 0)
        self.timeout = config.safe_getint("connection", "timeout", 10)
        self.maxRetries = config.safe_getint("connection", "max-retries", 3)
        self.proxy = config.safe_get("connection", "http-proxy", None)
        self.proxylist = config.safe_get("connection", "http-proxy-list", None)
        self.httpmethod = config.safe_get(
            "connection", "httpmethod", "get", ["get", "head", "post", "put", "patch", "delete", "trace", "options", "debug"]
        )
        self.requestByHostname = config.safe_getboolean(
            "connection", "request-by-hostname", False
        )
        self.stop = config.safe_getboolean("connection", "stop-on-error", False)

    def parseArguments(self):
        usage = "Usage: %prog [-u|--url] target [-e|--extensions] extensions [options]"
        parser = OptionParser(usage, epilog='''
You can change the dirsearch default configurations (default extensions, timeout, wordlist location, ...) by editing the "default.conf" file. More information at https://github.com/maurosoria/dirsearch.
''')

        # Mandatory arguments
        mandatory = OptionGroup(parser, 'Mandatory')
        mandatory.add_option('-u', '--url', help='URL target', action='store', type='string', dest='url', default=None)
        mandatory.add_option('-l', '--url-list', help='URL list file', action='store', type='string', dest='urlList',
                             default=None)
        mandatory.add_option('-e', '--extensions', help='Extension list separated by commas (Example: php,asp)',
                             action='store', dest='extensions', default=None)
        mandatory.add_option('-E', '--extensions-list', help='Use predefined list of common extensions',
                             action='store_true', dest='defaultExtensions', default=False)
        mandatory.add_option('-X', '--exclude-extensions',
                             help='Exclude extension list separated by commas (Example: asp,jsp)',
                             action='store', dest='excludeExtensions', default=None)

        # Dictionary Settings
        dictionary = OptionGroup(parser, 'Dictionary Settings')
        dictionary.add_option('-w', '--wordlist', action='store', dest='wordlist',
                              help='Customize wordlist (separated by commas)',
                              default=self.wordlist)
        dictionary.add_option('--prefixes', action='store', dest='prefixes', default=self.prefixes,
                              help='Add custom prefixes to all entries (separated by commas)')
        dictionary.add_option('--suffixes', action='store', dest='suffixes', default=self.suffixes,
                              help='Add custom suffixes to all entries, ignores directories (separated by commas)')
        dictionary.add_option('-f', '--force-extensions', action='store_true', dest='forceExtensions', default=self.forceExtensions,
                              help='Force extensions for every wordlist entry. Add %NOFORCE% at the end of the entry in the wordlist that you do not want to force')
        dictionary.add_option('--no-extension', dest='noExtension', action='store_true',
                              help='Remove extensions in all wordlist entries (Example: admin.php -> admin)')
        dictionary.add_option('--no-dot-extensions', dest='noDotExtensions', default=self.noDotExtensions,
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
                           help='Max recursion level (subdirs) (Default: 1 [only rootdir + 1 dir])', action='store', type='int',
                           dest='recursive_level_max',
                           default=self.recursive_level_max)
        general.add_option('--suppress-empty', action='store_true', dest='suppressEmpty',
                           help='Suppress empty responses', default=self.suppressEmpty)
        general.add_option('--minimal', action='store', dest='minimumResponseSize', type='int', default=None,
                           help='Minimal response length')
        general.add_option('--maximal', action='store', dest='maximumResponseSize', type='int', default=None,
                           help='Maximal response length')
        general.add_option('--scan-subdir', '--scan-subdirs',
                           help='Scan subdirectories of the given URL (separated by commas)', action='store',
                           dest='scanSubdirs',
                           default=None)
        general.add_option('--exclude-subdir', '--exclude-subdirs',
                           help='Exclude the following subdirectories during recursive scan (separated by commas)',
                           action='store', dest='excludeSubdirs',
                           default=self.excludeSubdirs)
        general.add_option('-t', '--threads', help='Number of threads', action='store', type='int', dest='threadsCount',
                           default=self.threadsCount)
        general.add_option('-i', '--include-status', help='Show only included status codes, separated by commas (Example: 301, 500)',
                           action='store', dest='includeStatusCodes', default=self.includeStatusCodes)
        general.add_option('-x', '--exclude-status', help='Do not show excluded status codes, separated by commas (Example: 301, 500)',
                           action='store', dest='excludeStatusCodes', default=self.excludeStatusCodes)
        general.add_option('--exclude-texts', help='Exclude responses by texts, separated by commas (Example: "Not found", "Error")',
                           action='store', dest='excludeTexts', default=None)
        general.add_option('--exclude-regexps', help='Exclude responses by regexps, separated by commas (Example: "Not foun[a-z]{1}", "^Error$")',
                           action='store', dest='excludeRegexps', default=None)
        general.add_option('-c', '--cookie', action='store', type='string', dest='cookie', default=None)
        general.add_option('--user-agent', action='store', type='string', dest='useragent',
                           default=self.useragent)
        general.add_option('-F', '--follow-redirects', action='store_true', dest='noFollowRedirects',
                           default=self.redirect)
        general.add_option('-H', '--header',
                           help='HTTP request header, support multiple flags (Example: -H "Referer: example.com" -H "Accept: */*")',
                           action='append', type='string', dest='headers', default=None)
        general.add_option('--header-list',
                           help="File contains HTTP request headers", type='string',
                           dest='headerList', default=None)
        general.add_option('--full-url', action='store_true', dest='full_url',
                           help='Print the full URL in the output', default=self.full_url)
        general.add_option('-q', '--quiet-mode', action='store_true', dest='quiet', default=self.quiet)
        general.add_option('--random-agents', '--random-user-agents', action='store_true', dest='useRandomAgents')
        

        # Connection Settings
        connection = OptionGroup(parser, 'Connection Settings')
        connection.add_option('--timeout', action='store', dest='timeout', type='int',
                              default=self.timeout, help='Connection timeout')
        connection.add_option('--ip', action='store', dest='ip', default=None,
                              help='Server IP address')
        connection.add_option('-s', '--delay', help='Delay between requests (support float number)', action='store', dest='delay',
                              type='float', default=self.delay)
        connection.add_option('--proxy', action='store', dest='httpProxy', type='string',
                              default=self.proxy, help='Proxy URL, support HTTP and SOCKS proxy (Example: localhost:8080, socks5://localhost:8088)')
        connection.add_option('--proxy-list', action='store', dest='proxyList', type='string',
                              default=self.proxylist, help='File contains proxy servers')
        connection.add_option('-m', '--http-method', action='store', dest='httpmethod', type='string',
                              default=self.httpmethod, help='HTTP method, default: GET')
        connection.add_option('--max-retries', action='store', dest='maxRetries', type='int',
                              default=self.maxRetries)
        connection.add_option('-b', '--request-by-hostname',
                              help='By default dirsearch will request by IP for speed. This will force requests by hostname',
                              action='store_true', dest='requestByHostname', default=self.requestByHostname)
        connection.add_option('--stop-on-error', action='store_true', dest='stop', default=self.stop,
                              help='Stop whenever an error occurs')

        # Report Settings
        reports = OptionGroup(parser, 'Reports')
        reports.add_option('--simple-report', action='store', help='Only found paths',
                           dest='simpleOutputFile', default=None)
        reports.add_option('--plain-text-report', action='store',
                           help='Found paths with status codes', dest='plainTextOutputFile', default=None)
        reports.add_option('--json-report', action='store', dest='jsonOutputFile', default=None)

        parser.add_option_group(mandatory)
        parser.add_option_group(dictionary)
        parser.add_option_group(general)
        parser.add_option_group(connection)
        parser.add_option_group(reports)
        options, arguments = parser.parse_args()
        return options
