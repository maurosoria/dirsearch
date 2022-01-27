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

from lib.core.settings import SCRIPT_PATH, COMMON_EXTENSIONS, OUTPUT_FORMATS, AUTHENTICATION_TYPES, MAX_NUMBER_OF_THREADS
from lib.parse.cmdline import parse_arguments
from lib.parse.config import ConfigParser
from lib.parse.headers import HeadersParser
from lib.utils.file import File, FileUtils
from lib.utils.fmt import uniq
from lib.utils.ip import iprange


class Options(object):
    def __init__(self):
        options = self.parse_config(parse_arguments())
        self.__dict__.update(options.__dict__)

        self.httpmethod = self.httpmethod.upper()
        self.url_list = []

        if options.url:
            self.url_list = [options.url]
        elif options.url_list:
            file = self.access_file(options.url_list, "file contains URLs")
            self.url_list = file.get_lines()
        elif options.cidr:
            self.url_list = iprange(options.cidr)
        elif options.stdin_urls:
            self.url_list = sys.stdin.read().splitlines(0)

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

        if options.proxy_list:
            file = self.access_file(options.proxy_list, "proxylist file")
            self.proxylist = file.get_lines()

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

        if options.no_extension:
            self.extensions = ''

        self.include_status_codes = self.parse_status_codes(options.include_status_codes)
        self.exclude_status_codes = self.parse_status_codes(options.exclude_status_codes)
        self.recursion_status_codes = self.parse_status_codes(options.recursion_status_codes)
        self.skip_on_status = self.parse_status_codes(options.skip_on_status)
        self.prefixes = uniq([prefix.strip() for prefix in self.prefixes.split(",")])
        self.suffixes = uniq([suffix.strip() for suffix in self.suffixes.split(",")])
        self.extensions = uniq([extension.lstrip(' .') for extension in options.extensions.split(",")])
        self.exclude_extensions = uniq([
            exclude_extension.lstrip(' .') for exclude_extension in options.exclude_extensions.split(",")
        ])
        self.exclude_sizes = uniq([
            exclude_size.strip().upper() for exclude_size in options.exclude_sizes.split(",")
        ])
        self.exclude_texts = uniq([
            exclude_text.strip() for exclude_text in options.exclude_texts.split(",")
        ])
        self.scan_subdirs = [
            subdir.strip().ljust(len(subdir) + 1, "/").lstrip("/")
            for subdir in options.scan_subdirs.split(",")
        ]
        self.exclude_subdirs = [
            subdir.strip().ljust(len(subdir) + 1, "/").lstrip("/")
            for subdir in options.exclude_subdirs.split(",")
        ]

        if not options.wordlist:
            print("No wordlist was provided, try using -w <wordlist>")
            exit(1)

        self.wordlist = uniq([wordlist.strip() for wordlist in options.wordlist.split(",")])

        if options.auth and not options.auth_type:
            print("Please select the authentication type with --auth-type")
            exit(1)
        elif options.auth_type and not options.auth:
            print("No authentication credential found")
            exit(1)
        elif options.auth and options.auth_type not in AUTHENTICATION_TYPES:
            print("'{}' is not in available authentication types: {}".format(options.auth_type, ", ".join(AUTHENTICATION_TYPES)))
            exit(1)

        if set(self.extensions).intersection(self.exclude_extensions):
            print("Exclude extension list can not contain any extension that has already in the extension list")
            exit(1)

        if self.output_format and self.output_format not in OUTPUT_FORMATS:
            print("Select one of the following output formats: {}".format(", ".join(OUTPUT_FORMATS)))
            exit(1)

    def parse_status_codes(self, str_):
        if not str_:
            return []

        status_codes = []

        for status_code in str_.split(","):
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
            "mandatory", "default-extensions"
        )
        options.exclude_extensions = options.exclude_extensions or config.safe_get(
            "mandatory", "exclude-extensions"
        )
        options.force_extensions = options.force_extensions or config.safe_getboolean(
            "mandatory", "force-extensions"
        )

        # General
        options.threads_count = options.threads_count or config.safe_getint(
            "general", "threads", 25, range(1, MAX_NUMBER_OF_THREADS)
        )
        options.include_status_codes = options.include_status_codes or config.safe_get(
            "general", "include-status"
        )
        options.exclude_status_codes = options.exclude_status_codes or config.safe_get(
            "general", "exclude-status"
        )
        options.exclude_sizes = options.exclude_sizes or config.safe_get("general", "exclude-sizes")
        options.exclude_texts = options.exclude_texts or config.safe_get("general", "exclude-texts")
        options.exclude_regex = options.exclude_regex or config.safe_get("general", "exclude-regex")
        options.exclude_redirect = options.exclude_redirect or config.safe_get("general", "exclude-redirect")
        options.exclude_response = options.exclude_response or config.safe_get("general", "exclude-response")
        options.recursive = options.recursive or config.safe_getboolean("general", "recursive")
        options.deep_recursive = options.deep_recursive or config.safe_getboolean("general", "deep-recursive")
        options.force_recursive = options.force_recursive or config.safe_getboolean("general", "force-recursive")
        options.recursion_depth = options.recursion_depth or config.safe_getint("general", "recursion-depth")
        options.recursion_status_codes = options.recursion_status_codes or config.safe_get(
            "general", "recursion-status", "100-999"
        )
        options.scan_subdirs = options.scan_subdirs or config.safe_get("general", "subdirs")
        options.exclude_subdirs = options.exclude_subdirs or config.safe_get("general", "exclude-subdirs")
        options.skip_on_status = options.skip_on_status or config.safe_get("general", "skip-on-status")
        options.maxtime = options.maxtime or config.safe_getint("general", "max-time")
        options.full_url = options.full_url or config.safe_getboolean("general", "full-url")
        options.color = options.color or config.safe_getboolean("general", "color", True)
        options.quiet = options.quiet or config.safe_getboolean("general", "quiet-mode")
        options.redirects_history = options.redirects_history or config.safe_getboolean(
            "general", "show-redirects-history"
        )

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

        # Output
        self.output_location = config.safe_get("output", "report-output-folder")
        self.autosave_report = config.safe_getboolean("output", "autosave-report")
        options.log_file = options.log_file or config.safe_get("output", "log-file")
        options.output_format = options.output_format or config.safe_get(
            "output", "report-format", "plain", OUTPUT_FORMATS
        )

        return options
