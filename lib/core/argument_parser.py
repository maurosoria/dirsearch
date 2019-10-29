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

        if not options.url:

            if options.url_list:

                with File(options.url_list) as url_list:

                    if not url_list.exists():
                        print("The file with URLs does not exist")
                        exit(0)

                    if not url_list.is_valid():
                        print('The wordlist is invalid')
                        exit(0)

                    if not url_list.can_read():
                        print('The wordlist cannot be read')
                        exit(0)

                    self.url_list = list(url_list.get_lines())

            elif not options.url:
                print('URL target is missing, try using -u <url> ')
                exit(0)

        else:
            self.url_list = [options.url]

        if not options.extensions:
            print('No extension specified. You must specify at least one extension')
            exit(0)

        with File(options.wordlist) as wordlist:
            if not wordlist.exists():
                print('The wordlist file does not exist')
                exit(0)

            if not wordlist.is_valid():
                print('The wordlist is invalid')
                exit(0)

            if not wordlist.can_read():
                print('The wordlist cannot be read')
                exit(0)

        if options.http_proxy is not None:

            if options.http_proxy.startswith('http://'):
                self.proxy = options.http_proxy
            else:
                self.proxy = 'http://{0}'.format(options.http_proxy)

        else:
            self.proxy = None

        if options.headers is not None:
            try:
                self.headers = dict((key.strip(), value.strip()) for (key, value) in (header.split(':', 1)
                                                                                      for header in options.headers))
            except Exception:
                print('Invalid headers')
                exit(0)

        else:
            self.headers = {}

        self.extensions = list(oset([extension.strip() for extension in options.extensions.split(',')]))
        self.useragent = options.useragent
        self.use_random_agents = options.use_random_agentss
        self.cookie = options.cookie

        if options.threadsCount < 1:
            print('Threads number must be a number greater than zero')
            exit(0)

        self.threads_count = options.threadsCount

        if options.excludeStatusCodes is not None:

            try:
                self.exclude_status_codes = list(
                    oset([int(excludeStatusCode.strip()) if excludeStatusCode else None for excludeStatusCode in
                          options.excludeStatusCodes.split(',')]))
            except ValueError:
                self.exclude_status_codes = []

        else:
            self.exclude_status_codes = []

        if options.exclude_texts is not None:
            try:
                self.exclude_texts = list(
                    oset([exclude_texts.strip() if exclude_texts else None for exclude_texts in
                          options.exclude_texts.split(',')]))
            except ValueError:
                self.exclude_texts = []
        else:
            self.exclude_texts = []

        if options.excludeRegexps is not None:
            try:
                self.exclude_regexps = list(
                    oset([exclude_regexps.strip() if exclude_regexps else None for exclude_regexps in
                          options.excludeRegexps.split(',')]))
            except ValueError:
                self.exclude_regexps = []
        else:
            self.exclude_regexps = []

        self.wordlist = options.wordlist
        self.lowercase = options.lowercase
        self.force_extensions = options.force_extensions
        self.simple_output_file = options.imple_output_file
        self.plain_text_output_file = options.plain_text_output_file
        self.json_output_file = options.json_output_file
        self.delay = options.delay
        self.timeout = options.timeout
        self.ip = options.ip
        self.max_retries = options.max_retries
        self.recursive = options.recursive
        self.suppress_empty = options.suppress_empty

        if options.scan_subdirs is not None:
            self.scan_subdirs = list(oset([subdir.strip() for subdir in options.scan_subdirs.split(',')]))

            for i in range(len(self.scan_subdirs)):

                while self.scan_subdirs[i].startswith("/"):
                    self.scan_subdirs[i] = self.scan_subdirs[i][1:]

                while self.scan_subdirs[i].endswith("/"):
                    self.scan_subdirs[i] = self.scan_subdirs[i][:-1]

            self.scan_subdirs = list(oset([subdir + "/" for subdir in self.scan_subdirs]))

        else:
            self.scan_subdirs = None

        if not self.recursive and options.exclude_subdirs is not None:
            print('--exclude-subdir argument can only be used with -r|--recursive')
            exit(0)

        elif options.exclude_subdirs is not None:
            self.exclude_subdirs = list(oset([subdir.strip() for subdir in options.exclude_subdirs.split(',')]))

            for i in range(len(self.exclude_subdirs)):

                while self.exclude_subdirs[i].startswith("/"):
                    self.exclude_subdirs[i] = self.exclude_subdirs[i][1:]

                while self.exclude_subdirs[i].endswith("/"):
                    self.exclude_subdirs[i] = self.exclude_subdirs[i][:-1]
            self.exclude_subdirs = list(oset(self.exclude_subdirs))

        else:
            self.exclude_subdirs = None

        self.redirect = options.noFollowRedirects
        self.request_by_hostname = options.request_by_hostname
        self.httpmethod = options.httpmethod

        self.recursive_level_max = options.recursive_level_max

        # set in parse_config
        self.test_fail_path = None
        self.save_home = None
        self.auto_save = None
        self.auto_save_format = None

    def parse_config(self):
        config = DefaultConfigParser()
        config_path = FileUtils.build_path(self.script_path, "default.conf")
        config.read(config_path)

        # General
        self.threads_count = config.safe_getint("general", "threads", 10, list(range(1, 50)))
        self.exclude_status_codes = config.safe_get("general", "exclude-status", None)
        self.redirect = config.safe_getboolean("general", "follow-redirects", False)
        self.recursive = config.safe_getboolean("general", "recursive", False)
        self.recursive_level_max = config.safe_getint("general", "recursive-level-max", 1)
        self.suppress_empty = config.safe_getboolean("general", "suppress-empty", False)
        self.test_fail_path = config.safe_get("general", "scanner-fail-path", "").strip()
        self.save_home = config.safe_getboolean("general", "save-logs-home", False)

        # Reports
        self.auto_save = config.safe_getboolean("reports", "autosave-report", False)
        self.auto_save_format = config.safe_get("reports", "autosave-report-format", "plain", ["plain", "json", "simple"])
        # Dictionary
        self.wordlist = config.safe_get("dictionary", "wordlist",
                                        FileUtils.build_path(self.script_path, "db", "dicc.txt"))
        self.lowercase = config.safe_getboolean("dictionary", "lowercase", False)
        self.force_extensions = config.safe_get("dictionary", "force-extensions", False)

        # Connection
        self.use_random_agents = config.safe_get("connection", "random-user-agents", False)
        self.useragent = config.safe_get("connection", "user-agent", None)
        self.delay = config.safe_get("connection", "delay", 0)
        self.timeout = config.safe_getint("connection", "timeout", 30)
        self.max_retries = config.safe_getint("connection", "max-retries", 5)
        self.proxy = config.safe_get("connection", "http-proxy", None)
        self.httpmethod = config.safe_get("connection", "httpmethod", "get", ["get", "head", "post"])
        self.request_by_hostname = config.safe_get("connection", "request-by-hostname", False)

    def parse_arguments(self):
        usage = 'Usage: %prog [-u|--url] target [-e|--extensions] extensions [options]'
        parser = OptionParser(usage)
        # Mandatory arguments
        mandatory = OptionGroup(parser, 'Mandatory')
        mandatory.add_option('-u', '--url', help='URL target', action='store', type='string', dest='url', default=None)
        mandatory.add_option('-L', '--url-list', help='URL list target', action='store', type='string', dest='url_list',
                             default=None)
        mandatory.add_option('-e', '--extensions', help='Extension list separated by comma (Example: php,asp)',
                             action='store', dest='extensions', default=None)

        connection = OptionGroup(parser, 'Connection Settings')
        connection.add_option('--timeout', action='store', dest='timeout', type='int',
                              default=self.timeout,
                              help='Connection timeout')
        connection.add_option('--ip', action='store', dest='ip', default=None,
                              help='Resolve name to IP address')
        connection.add_option('--proxy', '--http-proxy', action='store', dest='http_proxy', type='string',
                              default=self.proxy, help='Http Proxy (example: localhost:8080')
        connection.add_option('--http-method', action='store', dest='httpmethod', type='string',
                              default=self.httpmethod, help='Method to use, default: GET, possible also: HEAD;POST')
        connection.add_option('--max-retries', action='store', dest='max_retries', type='int',
                              default=self.max_retries)
        connection.add_option('-b', '--request-by-hostname',
                              help='By default dirsearch will request by IP for speed. This forces requests by hostname',
                              action='store_true', dest='request_by_hostname', default=self.request_by_hostname)

        # Dictionary settings
        dictionary = OptionGroup(parser, 'Dictionary Settings')
        dictionary.add_option('-w', '--wordlist', action='store', dest='wordlist',
                              default=self.wordlist)
        dictionary.add_option('-l', '--lowercase', action='store_true', dest='lowercase', default=self.lowercase)

        dictionary.add_option('-f', '--force-extensions',
                              help='Force extensions for every wordlist entry (like in DirBuster)',
                              action='store_true', dest='force_extensions', default=self.force_extensions)

        # Optional Settings
        general = OptionGroup(parser, 'General Settings')
        general.add_option('-s', '--delay', help='Delay between requests (float number)', action='store', dest='delay',
                           type='float', default=self.delay)
        general.add_option('-r', '--recursive', help='Bruteforce recursively', action='store_true', dest='recursive',
                           default=self.recursive)
        general.add_option('-R', '--recursive-level-max',
                           help='Max recursion level (subdirs) (Default: 1 [only rootdir + 1 dir])', action='store', type="int",
                           dest='recursive_level_max',
                           default=self.recursive_level_max)

        general.add_option('--suppress-empty', "--suppress-empty", action="store_true", dest='suppress_empty')

        general.add_option('--scan-subdir', '--scan-subdirs',
                           help='Scan subdirectories of the given -u|--url (separated by comma)', action='store',
                           dest='scan_subdirs',
                           default=None)
        general.add_option('--exclude-subdir', '--exclude-subdirs',
                           help='Exclude the following subdirectories during recursive scan (separated by comma)',
                           action='store', dest='exclude_subdirs',
                           default=None)
        general.add_option('-t', '--threads', help='Number of Threads', action='store', type='int', dest='threadsCount',
                           default=self.threads_count)
        general.add_option('-x', '--exclude-status', help='Exclude status code, separated by comma (example: 301, 500)',
                           action='store', dest='excludeStatusCodes', default=self.exclude_status_codes)
        general.add_option('--exclude-texts', help='Exclude responses by texts, separated by comma (example: "Not found", "Error")',
                           action='store', dest='exclude_texts', default=None)
        general.add_option('--exclude-regexps', help='Exclude responses by regexps, separated by comma (example: "Not foun[a-z]{1}", "^Error$")',
                           action='store', dest='excludeRegexps', default=None)
        general.add_option('-c', '--cookie', action='store', type='string', dest='cookie', default=None)
        general.add_option('--ua', '--user-agent', action='store', type='string', dest='useragent',
                           default=self.useragent)
        general.add_option('-F', '--follow-redirects', action='store_true', dest='noFollowRedirects',
                           default=self.redirect)
        general.add_option('-H', '--header',
                           help='Headers to add (example: --header "Referer: example.com" --header "User-Agent: IE"',
                           action='append', type='string', dest='headers', default=None)
        general.add_option('--random-agents', '--random-user-agents', action="store_true", dest='use_random_agentss')

        reports = OptionGroup(parser, 'Reports')
        reports.add_option('--simple-report', action='store', help="Only found paths",
                           dest='imple_output_file', default=None)
        reports.add_option('--plain-text-report', action='store',
                           help="Found paths with status codes", dest='plain_text_output_file', default=None)
        reports.add_option('--json-report', action='store', dest='json_output_file', default=None)
        parser.add_option_group(mandatory)
        parser.add_option_group(dictionary)
        parser.add_option_group(general)
        parser.add_option_group(connection)
        parser.add_option_group(reports)
        options, arguments = parser.parse_args()
        return options
