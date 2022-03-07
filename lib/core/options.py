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

from lib.core.settings import (
    AUTHENTICATION_TYPES, COMMON_EXTENSIONS, DEFAULT_TOR_PROXIES,
    OUTPUT_FORMATS, SCRIPT_PATH
)
from lib.core.structures import AttributeDict
from lib.parse.cmdline import parse_arguments
from lib.parse.config import ConfigParser
from lib.parse.headers import HeadersParser
from lib.utils.common import iprange, uniq
from lib.utils.file import File, FileUtils


def options():
    opt = parse_config(parse_arguments())

    if opt.session_file:
        return AttributeDict(vars(opt))

    opt.httpmethod = opt.httpmethod.upper()

    if opt.url_list:
        fd = access_file(opt.url_list, "file contains URLs")
        opt.urls = fd.get_lines()
    elif opt.cidr:
        opt.urls = iprange(opt.cidr)
    elif opt.stdin_urls:
        opt.urls = sys.stdin.read().splitlines(0)

    opt.urls = uniq(opt.urls)

    if opt.raw_file:
        access_file(opt.raw_file, "file with raw request")
    elif not opt.urls:
        print("URL target is missing, try using -u <url>")
        exit(1)

    if not opt.extensions and not opt.no_extension:
        print("WARNING: No extension was specified!")

    for dict_file in opt.wordlist.split(','):
        access_file(dict_file, "wordlist")

    if opt.threads_count < 1:
        print("Threads number must be greater than zero")
        exit(1)

    if opt.tor:
        opt.proxylist = DEFAULT_TOR_PROXIES
    elif opt.proxylist:
        fd = access_file(opt.proxylist, "proxylist file")
        opt.proxylist = fd.get_lines()

    headers = {}

    if opt.header_list:
        try:
            fd = access_file(opt.header_list, "header list file")
            headers.update(
                HeadersParser(fd.read()).headers
            )
        except Exception as e:
            print("Error in headers file: " + str(e))
            exit(1)

    if opt.headers:
        try:
            headers.update(
                HeadersParser(opt.headers).headers
            )
        except Exception:
            print("Invalid headers")
            exit(1)

    opt.headers = headers

    opt.include_status_codes = parse_status_codes(opt.include_status_codes)
    opt.exclude_status_codes = parse_status_codes(opt.exclude_status_codes)
    opt.recursion_status_codes = parse_status_codes(opt.recursion_status_codes)
    opt.skip_on_status = parse_status_codes(opt.skip_on_status)
    opt.prefixes = set(prefix.strip() for prefix in opt.prefixes.split(","))
    opt.suffixes = set(suffix.strip() for suffix in opt.suffixes.split(","))
    opt.exclude_extensions = uniq([
        exclude_extension.lstrip(" .") for exclude_extension in opt.exclude_extensions.split(",")
    ])
    opt.exclude_sizes = uniq([
        exclude_size.strip().upper() for exclude_size in opt.exclude_sizes.split(",")
    ])
    opt.exclude_texts = uniq([
        exclude_text.strip() for exclude_text in opt.exclude_texts.split(",")
    ])
    opt.scan_subdirs = [
        subdir.lstrip(" /") + ('' if not subdir or subdir.endswith('/') else '/')
        for subdir in opt.scan_subdirs.split(',')
    ]
    opt.exclude_subdirs = [
        subdir.lstrip(" /") + ('' if not subdir or subdir.endswith('/') else '/')
        for subdir in opt.exclude_subdirs.split(',')
    ]

    if opt.no_extension:
        opt.extensions = ''
    elif opt.extensions == '*':
        opt.extensions = COMMON_EXTENSIONS
    elif opt.extensions == "CHANGELOG.md":
        print("A weird extension was provided: 'CHANGELOG.md'. Please do not use * as the extension or enclose it in double quotes")
        exit(0)
    else:
        opt.extensions = uniq([extension.lstrip(" .") for extension in opt.extensions.split(",")])

    if not opt.wordlist:
        print("No wordlist was provided, try using -w <wordlist>")
        exit(1)

    opt.wordlist = uniq([wordlist.strip() for wordlist in opt.wordlist.split(",")])

    if opt.auth and not opt.auth_type:
        print("Please select the authentication type with --auth-type")
        exit(1)
    elif opt.auth_type and not opt.auth:
        print("No authentication credential found")
        exit(1)
    elif opt.auth and opt.auth_type not in AUTHENTICATION_TYPES:
        print(f"'{opt.auth_type}' is not in available authentication types: {', '.join(AUTHENTICATION_TYPES)}")
        exit(1)

    if set(opt.extensions).intersection(opt.exclude_extensions):
        print("Exclude extension list can not contain any extension that has already in the extension list")
        exit(1)

    if opt.output_format not in OUTPUT_FORMATS:
        print(f"Select one of the following output formats: {', '.join(OUTPUT_FORMATS)}")
        exit(1)

    return AttributeDict(vars(opt))


def parse_status_codes(str_):
    if not str_:
        return []

    status_codes = set()

    for status_code in str_.split(","):
        try:
            if "-" in status_code:
                start, end = status_code.strip().split("-")
                status_codes.update(
                    range(int(start), int(end) + 1)
                )
            else:
                status_codes.add(int(status_code.strip()))
        except ValueError:
            print(f"Invalid status code or status code range: {status_code}")
            exit(1)

    return status_codes


def access_file(path, name):
    with File(path) as fd:
        if not fd.exists():
            print(f"The {name} does not exist")
            exit(1)

        if not fd.is_valid():
            print(f"The {name} is invalid")
            exit(1)

        if not fd.can_read():
            print(f"The {name} cannot be read")
            exit(1)

        return fd


def parse_config(opt):
    config = ConfigParser()
    config.read(opt.config)

    # Mandatory
    opt.extensions = opt.extensions or config.safe_get(
        "mandatory", "default-extensions"
    )
    opt.exclude_extensions = opt.exclude_extensions or config.safe_get(
        "mandatory", "exclude-extensions"
    )
    opt.force_extensions = opt.force_extensions or config.safe_getboolean(
        "mandatory", "force-extensions"
    )

    # General
    opt.threads_count = opt.threads_count or config.safe_getint(
        "general", "threads", 25
    )
    opt.include_status_codes = opt.include_status_codes or config.safe_get(
        "general", "include-status"
    )
    opt.exclude_status_codes = opt.exclude_status_codes or config.safe_get(
        "general", "exclude-status"
    )
    opt.exclude_sizes = opt.exclude_sizes or config.safe_get("general", "exclude-sizes")
    opt.exclude_texts = opt.exclude_texts or config.safe_get("general", "exclude-texts")
    opt.exclude_regex = opt.exclude_regex or config.safe_get("general", "exclude-regex")
    opt.exclude_redirect = opt.exclude_redirect or config.safe_get("general", "exclude-redirect")
    opt.exclude_response = opt.exclude_response or config.safe_get("general", "exclude-response")
    opt.recursive = opt.recursive or config.safe_getboolean("general", "recursive")
    opt.deep_recursive = opt.deep_recursive or config.safe_getboolean("general", "deep-recursive")
    opt.force_recursive = opt.force_recursive or config.safe_getboolean("general", "force-recursive")
    opt.recursion_depth = opt.recursion_depth or config.safe_getint("general", "recursion-depth")
    opt.recursion_status_codes = opt.recursion_status_codes or config.safe_get(
        "general", "recursion-status", "100-999"
    )
    opt.scan_subdirs = opt.scan_subdirs or config.safe_get("general", "subdirs")
    opt.exclude_subdirs = opt.exclude_subdirs or config.safe_get("general", "exclude-subdirs")
    opt.skip_on_status = opt.skip_on_status or config.safe_get("general", "skip-on-status")
    opt.maxtime = opt.maxtime or config.safe_getint("general", "max-time")
    opt.full_url = opt.full_url or config.safe_getboolean("general", "full-url")
    opt.color = opt.color or config.safe_getboolean("general", "color", True)
    opt.quiet = opt.quiet or config.safe_getboolean("general", "quiet-mode")
    opt.redirects_history = opt.redirects_history or config.safe_getboolean(
        "general", "show-redirects-history"
    )

    # Dictionary
    opt.wordlist = opt.wordlist or config.safe_get(
        "dictionary", "wordlist", FileUtils.build_path(SCRIPT_PATH, "db", "dicc.txt"),
    )
    opt.prefixes = opt.prefixes or config.safe_get("dictionary", "prefixes",)
    opt.suffixes = opt.suffixes or config.safe_get("dictionary", "suffixes")
    opt.lowercase = opt.lowercase or config.safe_getboolean("dictionary", "lowercase")
    opt.uppercase = opt.uppercase or config.safe_getboolean("dictionary", "uppercase")
    opt.capitalization = opt.capitalization or config.safe_getboolean("dictionary", "capitalization")

    # Request
    opt.httpmethod = opt.httpmethod or config.safe_get("request", "httpmethod", "get")
    opt.header_list = opt.header_list or config.safe_get("request", "headers-file")
    opt.follow_redirects = opt.follow_redirects or config.safe_getboolean("request", "follow-redirects")
    opt.use_random_agents = opt.use_random_agents or config.safe_getboolean("request", "random-user-agents")
    opt.useragent = opt.useragent or config.safe_get("request", "user-agent")
    opt.cookie = opt.cookie or config.safe_get("request", "cookie")

    # Connection
    opt.delay = opt.delay or config.safe_getfloat("connection", "delay")
    opt.timeout = opt.timeout or config.safe_getfloat("connection", "timeout", 7.5)
    opt.max_retries = opt.max_retries or config.safe_getint("connection", "retries", 1)
    opt.maxrate = opt.maxrate or config.safe_getint("connection", "max-rate")
    opt.proxy = opt.proxy or config.safe_get("connection", "proxy")
    opt.proxylist = config.safe_get("connection", "proxy-list")
    opt.scheme = opt.scheme or config.safe_get("connection", "scheme", None, ["http", "https"])
    opt.replay_proxy = opt.replay_proxy or config.safe_get("connection", "replay-proxy")
    opt.exit_on_error = opt.exit_on_error or config.safe_getboolean("connection", "exit-on-error")

    # Output
    opt.output_path = config.safe_get("output", "report-output-folder")
    opt.autosave_report = config.safe_getboolean("output", "autosave-report")
    opt.log_file = opt.log_file or config.safe_get("output", "log-file")
    opt.output_format = opt.output_format or config.safe_get(
        "output", "report-format", "plain", OUTPUT_FORMATS
    )

    return opt
