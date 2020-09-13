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

from lib.utils.DefaultConfigParser import DefaultConfigParser
from lib.utils.FileUtils import File
from lib.utils.FileUtils import FileUtils
from thirdparty.oset import *


class ArgumentParser(object):
    def __init__(self, script_path):
        self.script_path = script_path
        self.parseConfig()

        options = self.parseArguments()

        self.clean_view = options.clean_view
        self.full_url = options.full_url
        
        if options.url == None:

            if options.urlList != None:

                with File(options.urlList) as urlList:

                    if not urlList.exists():
                        print("The file with URLs does not exist")
                        exit(0)

                    if not urlList.isValid():
                        print("The file with URLs is invalid")
                        exit(0)

                    if not urlList.canRead():
                        print("The file with URLs cannot be read")
                        exit(0)

                    self.urlList = list(urlList.getLines())

            elif options.url == None:
                print("URL target is missing, try using -u <url> ")
                exit(0)

        else:
            self.urlList = [options.url]


        if not options.extensions and not options.defaultExtensions:
            print('No extension specified. You must specify at least one extension or try using default extension list.')
            exit(0)

        if not options.extensions and options.defaultExtensions:
            options.extensions = self.defaultExtensions

        # Enable to use multiple dictionaries at once
        for dictFile in options.wordlist.split(','):
            with File(dictFile) as wordlist:
                if not wordlist.exists():
                    print('The wordlist file does not exist')
                    exit(1)

                if not wordlist.isValid():
                    print('The wordlist is invalid')
                    exit(1)

                if not wordlist.canRead():
                    print('The wordlist cannot be read')
                    exit(1)

        if options.proxyList is not None:
            with File(options.proxyList) as plist:
                if not plist.exists():
                    print('The proxylist file does not exist')
                    exit(1)

                if not plist.isValid():
                    print('The proxylist is invalid')
                    exit(1)

                if not plist.canRead():
                    print('The proxylist cannot be read')
                    exit(1)

            self.proxylist = open(options.proxyList).read().splitlines()


        elif options.httpProxy is not None:
            if options.httpProxy.startswith("http://"):
                self.proxy = options.httpProxy
            else:
                self.proxy = "http://{0}".format(options.httpProxy)

        else:
            self.proxy = None

        if options.headers is not None:
            try:
                self.headers = dict(
                    (key.strip(), value.strip())
                    for (key, value) in (
                        header.split(":", 1) for header in options.headers
                    )
                )
            except Exception as e:
                print("Invalid headers")
                exit(0)

        else:
            self.headers = {}

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
                            excludeTexts.strip() if excludeTexts else None
                            for excludeTexts in options.excludeTexts.split(",")
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
                            excludeRegexps.strip() if excludeRegexps else None
                            for excludeRegexps in options.excludeRegexps.split(",")
                        ]
                    )
                )

            except ValueError:
                self.excludeRegexps = []
        else:
            self.excludeRegexps = []


        self.suffixes = [] if not options.suffixes else list(oset([suffix.strip() for suffix in options.suffixes.split(',')]))
        self.wordlist = list(oset([wordlist.strip() for wordlist in options.wordlist.split(',')]))

        self.lowercase = options.lowercase
        self.uppercase = options.uppercase
        self.forceExtensions = options.forceExtensions
        self.data = options.data
        self.noDotExtensions = options.noDotExtensions
        self.simpleOutputFile = options.simpleOutputFile
        self.plainTextOutputFile = options.plainTextOutputFile
        self.jsonOutputFile = options.jsonOutputFile
        self.quietMode = options.quietMode
        self.delay = options.delay
        self.timeout = options.timeout
        self.ip = options.ip
        self.maxRetries = options.maxRetries
        self.recursive = options.recursive
        self.suppressEmpty = options.suppressEmpty
        self.minimumResponseSize = options.minimumResponseSize
        self.maximumResponseSize = options.maximumResponseSize


        if options.scanSubdirs is not None:
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

        if not self.recursive and options.excludeSubdirs is not None:
            print("--exclude-subdir argument can only be used with -r|--recursive")
            exit(0)


        elif options.excludeSubdirs is not None:
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

        self.redirect = options.noFollowRedirects
        self.requestByHostname = options.requestByHostname
        self.httpmethod = options.httpmethod

        self.recursive_level_max = options.recursive_level_max

    def parseConfig(self):
        config = DefaultConfigParser()
        configPath = FileUtils.buildPath(self.script_path, "default.conf")
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
        self.defaultExtensions = config.safe_get("general", "default-extensions", "php,asp,aspx,jsp,jspx,html,htm,js,txt")

        # Reports
        self.quietMode = config.safe_get("reports", "quiet-mode", False)
        self.autoSave = config.safe_getboolean("reports", "autosave-report", False)
        self.autoSaveFormat = config.safe_get(
            "reports", "autosave-report-format", "plain", ["plain", "json", "simple"]
        )
        # Dictionary
        self.wordlist = config.safe_get(
            "dictionary",
            "wordlist",
            FileUtils.buildPath(self.script_path, "db", "dicc.txt"),
        )
        self.lowercase = config.safe_getboolean("dictionary", "lowercase", False)
        self.uppercase = config.safe_getboolean("dictionary", "uppercase", False)
        self.forceExtensions = config.safe_get("dictionary", "force-extensions", False)
        self.noDotExtensions = config.safe_get("dictionary", "no-dot-extensions", False)

        # Connection
        self.useRandomAgents = config.safe_get(
            "connection", "random-user-agents", False
        )
        self.useragent = config.safe_get("connection", "user-agent", None)
        self.delay = config.safe_get("connection", "delay", 0)
        self.timeout = config.safe_getint("connection", "timeout", 20)
        self.maxRetries = config.safe_getint("connection", "max-retries", 5)
        self.proxy = config.safe_get("connection", "http-proxy", None)
        self.proxylist = config.safe_get("connection", "http-proxy-list", None)
        self.httpmethod = config.safe_get(
            "connection", "httpmethod", "get", ["get", "head", "post", "put", "delete", "trace", "options"]
        )
        self.requestByHostname = config.safe_get(
            "connection", "request-by-hostname", False
        )

    def parseArguments(self):
        usage = "Usage: %prog [-u|--url] target [-e|--extensions] extensions [options]"
        parser = OptionParser(usage)
        # Mandatory arguments

        mandatory = OptionGroup(parser, 'Mandatory')
        mandatory.add_option('-u', '--url', help='URL target', action='store', type='string', dest='url', default=None)
        mandatory.add_option('-L', '--url-list', help='URL list target', action='store', type='string', dest='urlList',
                             default=None)
        mandatory.add_option('-e', '--extensions', help='Extension list separated by comma (Example: php,asp)',
                             action='store', dest='extensions', default=None)
        mandatory.add_option('-E', '--extensions-list', help='Use predefined list of common extensions',
                             action='store_true', dest='defaultExtensions', default=False)
        mandatory.add_option('-X', '--exclude-extensions',
                              help='Exclude extensions list, separated by comma (Example: asp,jsp)',
                              action='store', dest='excludeExtensions', default=None)

        connection = OptionGroup(parser, 'Connection Settings')
        connection.add_option('--timeout', action='store', dest='timeout', type='int',
                              default=self.timeout,
                              help='Connection timeout')
        connection.add_option('--ip', action='store', dest='ip', default=None,
                              help='Resolve name to IP address')
        connection.add_option('--proxy', '--http-proxy', action='store', dest='httpProxy', type='string',
                              default=self.proxy, help='Http Proxy (example: localhost:8080)')
        connection.add_option('--proxylist', '--http-proxy-list', action='store', dest='proxyList', type='string',
                              default=self.proxylist, help='Path to file containg http proxy servers.' )
        connection.add_option('-m', '--http-method', action='store', dest='httpmethod', type='string',
                              default=self.httpmethod, help='Method to use, default: GET')
        connection.add_option('--max-retries', action='store', dest='maxRetries', type='int',
                              default=self.maxRetries)
        connection.add_option('-b', '--request-by-hostname',
                              help='By default dirsearch will request by IP for speed. This forces requests by hostname',
                              action='store_true', dest='requestByHostname', default=self.requestByHostname)

        # Dictionary settings
        dictionary = OptionGroup(parser, 'Dictionary Settings')
        dictionary.add_option('-w', '--wordlist', action='store', dest='wordlist',
                              help='Customize wordlist (separated by comma)',
                              default=self.wordlist)
        dictionary.add_option('-l', '--lowercase', action='store_true', dest='lowercase', default=self.lowercase)
        dictionary.add_option('-U', '--uppercase', action='store_true', dest='uppercase', default=self.uppercase)
        dictionary.add_option('--suff', '--suffixes',
                             help='Add custom suffixes to all files, ignores directories (example.%EXT%%SUFFIX%)',
                             action='store', dest='suffixes', default=None)

        dictionary.add_option('-f', '--force-extensions',
                              help='Force extensions for every wordlist entry',
                              action='store_true', dest='forceExtensions', default=self.forceExtensions)
        dictionary.add_option('--nd', '--no-dot-extensions',
                              help='Don\'t add a \'.\' character before extensions', action='store_true',
                              dest='noDotExtensions', default=self.noDotExtensions)

        # Optional Settings
        general = OptionGroup(parser, 'General Settings')
        general.add_option('-d', '--data', help='HTTP request data (POST, PUT, ... body)', action='store', dest='data',
                           type='str', default=None)
        general.add_option('-s', '--delay', help='Delay between requests (float number)', action='store', dest='delay',
                           type='float', default=self.delay)
        general.add_option('-r', '--recursive', help='Bruteforce recursively', action='store_true', dest='recursive',
                           default=self.recursive)
        general.add_option('-R', '--recursive-level-max',
                           help='Max recursion level (subdirs) (Default: 1 [only rootdir + 1 dir])', action='store', type='int',
                           dest='recursive_level_max',
                           default=self.recursive_level_max)

        general.add_option('--suppress-empty', "--suppress-empty", action="store_true", dest='suppressEmpty')
        general.add_option('--min', action='store', dest='minimumResponseSize', type='int', default=None,
                           help='Minimal response length')
        general.add_option('--max', action='store', dest='maximumResponseSize', type='int', default=None,
                           help='Maximal response length')

        general.add_option('--scan-subdir', '--scan-subdirs',
                           help='Scan subdirectories of the given -u|--url (separated by comma)', action='store',
                           dest='scanSubdirs',
                           default=None)
        general.add_option('--exclude-subdir', '--exclude-subdirs',
                           help='Exclude the following subdirectories during recursive scan (separated by comma)',
                           action='store', dest='excludeSubdirs',
                           default=None)
        general.add_option('-t', '--threads', help='Number of Threads', action='store', type='int', dest='threadsCount'
                           , default=self.threadsCount)
        general.add_option('-i', '--include-status', help='Show only included status codes, separated by comma (example: 301, 500)'
                           , action='store', dest='includeStatusCodes', default=self.includeStatusCodes)
        general.add_option('-x', '--exclude-status', help='Exclude status code, separated by comma (example: 301, 500)'
                           , action='store', dest='excludeStatusCodes', default=self.excludeStatusCodes)
        general.add_option('--exclude-texts', help='Exclude responses by texts, separated by comma (example: "Not found", "Error")'
                           , action='store', dest='excludeTexts', default=None)
        general.add_option('--exclude-regexps', help='Exclude responses by regexps, separated by comma (example: "Not foun[a-z]{1}", "^Error$")'
                           , action='store', dest='excludeRegexps', default=None)
        general.add_option('-c', '--cookie', action='store', type='string', dest='cookie', default=None)
        general.add_option('--ua', '--user-agent', action='store', type='string', dest='useragent',
                           default=self.useragent)
        general.add_option('-F', '--follow-redirects', action='store_true', dest='noFollowRedirects'
                           , default=self.redirect)
        general.add_option('-H', '--header',
                           help='Headers to add (example: --header "Referer: example.com" --header "User-Agent: IE")',
                           action='append', type='string', dest='headers', default=None)
        general.add_option('--random-agents', '--random-user-agents', action="store_true", dest='useRandomAgents')
        general.add_option('--clean-view', '--clean-view', action='store_true', dest='clean_view')
        general.add_option('--full-url', '--full-url', action='store_true', dest='full_url')

        reports = OptionGroup(parser, 'Reports')
        reports.add_option('--simple-report', action='store', help="Only found paths",
                           dest='simpleOutputFile', default=None)
        reports.add_option('--plain-text-report', action='store',
                           help="Found paths with status codes", dest='plainTextOutputFile', default=None)
        reports.add_option('--json-report', action='store', dest='jsonOutputFile', default=None)
        reports.add_option('-q', '--quiet-mode', help='Disable output to console (only to reports)', action='store_true',
                           dest='quietMode', default=self.quietMode)


        parser.add_option_group(mandatory)
        parser.add_option_group(dictionary)
        parser.add_option_group(general)
        parser.add_option_group(connection)
        parser.add_option_group(reports)
        options, arguments = parser.parse_args()
        return options
