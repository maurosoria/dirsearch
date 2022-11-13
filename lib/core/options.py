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

from lib.core.settings import (
    AUTHENTICATION_TYPES,
    COMMON_EXTENSIONS,
    DEFAULT_TOR_PROXIES,
    OUTPUT_FORMATS,
    SCRIPT_PATH,
)
from lib.parse.cmdline import parse_arguments
from lib.parse.config import ConfigParser
from lib.parse.headers import HeadersParser
from lib.utils.common import iprange, read_stdin, uniq
from lib.utils.file import File, FileUtils


def parse_options():
    opt = parse_config(parse_arguments())

    if opt.session_file:
        return vars(opt)

    opt.http_method = opt.http_method.upper()

    if opt.urls_file:
        fd = _access_file(opt.urls_file)
        opt.urls = fd.get_lines()
    elif opt.cidr:
        opt.urls = iprange(opt.cidr)
    elif opt.stdin_urls:
        opt.urls = read_stdin().splitlines(0)
    elif opt.raw_file:
        _access_file(opt.raw_file)
    elif not opt.urls:
        print("URL target is missing, try using -u <url>")
        exit(1)

    if not opt.raw_file:
        opt.urls = uniq(opt.urls)

    if not opt.extensions and not opt.remove_extensions:
        print("WARNING: No extension was specified!")

    if not opt.wordlists:
        print("No wordlist was provided, try using -w <wordlist>")
        exit(1)

    opt.wordlists = [wordlist.strip() for wordlist in opt.wordlists.split(",")]

    for wordlist in opt.wordlists:
        if FileUtils.is_dir(wordlist):
            opt.wordlists.remove(wordlist)
            opt.wordlists.extend(FileUtils.get_files(wordlist))
        else:
            _access_file(wordlist)

    if opt.thread_count < 1:
        print("Threads number must be greater than zero")
        exit(1)

    if opt.tor:
        opt.proxies = list(DEFAULT_TOR_PROXIES)
    elif opt.proxies_file:
        fd = _access_file(opt.proxies_file)
        opt.proxies = fd.get_lines()

    if opt.data_file:
        fd = _access_file(opt.data_file)
        opt.data = fd.get_lines()

    if opt.cert_file:
        _access_file(opt.cert_file)

    if opt.key_file:
        _access_file(opt.key_file)

    headers = {}

    if opt.headers_file:
        try:
            fd = _access_file(opt.headers_file)
            headers.update(dict(HeadersParser(fd.read())))
        except Exception as e:
            print("Error in headers file: " + str(e))
            exit(1)

    if opt.headers:
        try:
            headers.update(dict(HeadersParser("\n".join(opt.headers))))
        except Exception:
            print("Invalid headers")
            exit(1)

    opt.headers = headers

    opt.include_status_codes = _parse_status_codes(opt.include_status_codes)
    opt.exclude_status_codes = _parse_status_codes(opt.exclude_status_codes)
    opt.recursion_status_codes = _parse_status_codes(opt.recursion_status_codes)
    opt.skip_on_status = _parse_status_codes(opt.skip_on_status)
    opt.prefixes = uniq([prefix.strip() for prefix in opt.prefixes.split(",") if prefix], tuple)
    opt.suffixes = uniq([suffix.strip() for suffix in opt.suffixes.split(",") if suffix], tuple)
    opt.subdirs = [
        subdir.lstrip(" /") + ("" if not subdir or subdir.endswith("/") else "/")
        for subdir in opt.subdirs.split(",")
    ]
    opt.exclude_subdirs = [
        subdir.lstrip(" /") + ("" if not subdir or subdir.endswith("/") else "/")
        for subdir in opt.exclude_subdirs.split(",")
    ]
    opt.exclude_sizes = {size.strip().upper() for size in opt.exclude_sizes.split(",")}

    if opt.remove_extensions:
        opt.extensions = ("",)
    elif opt.extensions == "*":
        opt.extensions = COMMON_EXTENSIONS
    elif opt.extensions == "CHANGELOG.md":
        print("A weird extension was provided: 'CHANGELOG.md'. Please do not use * as the "
              "extension or enclose it in double quotes")
        exit(0)
    else:
        opt.extensions = uniq(
            [extension.lstrip(" .") for extension in opt.extensions.split(",")],
            tuple,
        )

    opt.exclude_extensions = uniq(
        [
            exclude_extension.lstrip(" .")
            for exclude_extension in opt.exclude_extensions.split(",")
        ], tuple
    )

    if opt.auth and not opt.auth_type:
        print("Please select the authentication type with --auth-type")
        exit(1)
    elif opt.auth_type and not opt.auth:
        print("No authentication credential found")
        exit(1)
    elif opt.auth and opt.auth_type not in AUTHENTICATION_TYPES:
        print(f"'{opt.auth_type}' is not in available authentication "
              f"types: {', '.join(AUTHENTICATION_TYPES)}")
        exit(1)

    if set(opt.extensions).intersection(opt.exclude_extensions):
        print("Exclude extension list can not contain any extension "
              "that has already in the extension list")
        exit(1)

    if opt.output_format not in OUTPUT_FORMATS:
        print("Select one of the following output formats: "
              f"{', '.join(OUTPUT_FORMATS)}")
        exit(1)

    return vars(opt)


def _parse_status_codes(str_):
    if not str_:
        return set()

    status_codes = set()

    for status_code in str_.split(","):
        try:
            if "-" in status_code:
                start, end = status_code.strip().split("-")
                status_codes.update(range(int(start), int(end) + 1))
            else:
                status_codes.add(int(status_code.strip()))
        except ValueError:
            print(f"Invalid status code or status code range: {status_code}")
            exit(1)

    return status_codes


def _access_file(path):
    with File(path) as fd:
        if not fd.exists():
            print(f"{path} does not exist")
            exit(1)

        if not fd.is_valid():
            print(f"{path} is not a file")
            exit(1)

        if not fd.can_read():
            print(f"{path} cannot be read")
            exit(1)

        return fd


def parse_config(opt):
    config = ConfigParser()
    config.read(opt.config)

    # General
    opt.thread_count = opt.thread_count or config.safe_getint(
        "general", "threads", 25
    )
    opt.include_status_codes = opt.include_status_codes or config.safe_get(
        "general", "include-status"
    )
    opt.exclude_status_codes = opt.exclude_status_codes or config.safe_get(
        "general", "exclude-status"
    )
    opt.exclude_sizes = opt.exclude_sizes or config.safe_get("general", "exclude-sizes", "")
    opt.exclude_texts = opt.exclude_texts or config.safe_getlist("general", "exclude-texts")
    opt.exclude_regex = opt.exclude_regex or config.safe_get("general", "exclude-regex")
    opt.exclude_redirect = opt.exclude_redirect or config.safe_get(
        "general", "exclude-redirect"
    )
    opt.exclude_response = opt.exclude_response or config.safe_get(
        "general", "exclude-response"
    )
    opt.recursive = opt.recursive or config.safe_getboolean("general", "recursive")
    opt.deep_recursive = opt.deep_recursive or config.safe_getboolean(
        "general", "deep-recursive"
    )
    opt.force_recursive = opt.force_recursive or config.safe_getboolean(
        "general", "force-recursive"
    )
    opt.recursion_depth = opt.recursion_depth or config.safe_getint(
        "general", "max-recursion-depth"
    )
    opt.recursion_status_codes = opt.recursion_status_codes or config.safe_get(
        "general", "recursion-status", "100-999"
    )
    opt.subdirs = opt.subdirs or config.safe_get("general", "subdirs", "")
    opt.exclude_subdirs = opt.exclude_subdirs or config.safe_get(
        "general", "exclude-subdirs", ""
    )
    opt.skip_on_status = opt.skip_on_status or config.safe_get(
        "general", "skip-on-status", ""
    )
    opt.max_time = opt.max_time or config.safe_getint("general", "max-time")
    opt.exit_on_error = opt.exit_on_error or config.safe_getboolean(
        "general", "exit-on-error"
    )

    # Dictionary
    opt.wordlists = opt.wordlists or config.safe_get(
        "dictionary",
        "wordlists",
        FileUtils.build_path(SCRIPT_PATH, "db", "dicc.txt"),
    )
    opt.extensions = opt.extensions or config.safe_get(
        "dictionary", "default-extensions", ""
    )
    opt.force_extensions = opt.force_extensions or config.safe_getboolean(
        "dictionary", "force-extensions"
    )
    opt.overwrite_extensions = opt.overwrite_extensions or config.safe_getboolean(
        "dictionary", "overwrite-extensions"
    )
    opt.exclude_extensions = opt.exclude_extensions or config.safe_get(
        "dictionary", "exclude-extensions", ""
    )
    opt.prefixes = opt.prefixes or config.safe_get("dictionary", "prefixes", "")
    opt.suffixes = opt.suffixes or config.safe_get("dictionary", "suffixes", "")
    opt.lowercase = opt.lowercase or config.safe_getboolean("dictionary", "lowercase")
    opt.uppercase = opt.uppercase or config.safe_getboolean("dictionary", "uppercase")
    opt.capitalization = opt.capitalization or config.safe_getboolean(
        "dictionary", "capitalization"
    )

    # Request
    opt.http_method = opt.http_method or config.safe_get("request", "http-method", "get")
    opt.headers = opt.headers or config.safe_getlist("request", "headers")
    opt.headers_file = opt.headers_file or config.safe_get("request", "headers-file")
    opt.follow_redirects = opt.follow_redirects or config.safe_getboolean(
        "request", "follow-redirects"
    )
    opt.random_agents = opt.random_agents or config.safe_getboolean(
        "request", "random-user-agents"
    )
    opt.user_agent = opt.user_agent or config.safe_get("request", "user-agent")
    opt.cookie = opt.cookie or config.safe_get("request", "cookie")

    # Connection
    opt.delay = opt.delay or config.safe_getfloat("connection", "delay")
    opt.timeout = opt.timeout or config.safe_getfloat("connection", "timeout", 7.5)
    opt.max_retries = opt.max_retries or config.safe_getint("connection", "max-retries", 1)
    opt.max_rate = opt.max_rate or config.safe_getint("connection", "max-rate")
    opt.proxies = opt.proxies or config.safe_getlist("connection", "proxies")
    opt.proxies_file = opt.proxies_file or config.safe_get("connection", "proxies-file")
    opt.scheme = opt.scheme or config.safe_get(
        "connection", "scheme", None, ("http", "https")
    )
    opt.replay_proxy = opt.replay_proxy or config.safe_get("connection", "replay-proxy")

    # Advanced
    opt.crawl = opt.crawl or config.safe_getboolean("advanced", "crawl")

    # View
    opt.full_url = opt.full_url or config.safe_getboolean("view", "full-url")
    opt.color = opt.color or config.safe_getboolean("view", "color", True)
    opt.quiet = opt.quiet or config.safe_getboolean("view", "quiet-mode")
    opt.redirects_history = opt.redirects_history or config.safe_getboolean(
        "view", "show-redirects-history"
    )

    # Output
    opt.output_path = config.safe_get("output", "autosave-report-folder")
    opt.autosave_report = config.safe_getboolean("output", "autosave-report")
    opt.log_file_size = config.safe_getint("output", "log-file-size")
    opt.log_file = opt.log_file or config.safe_get("output", "log-file")
    opt.output_format = opt.output_format or config.safe_get(
        "output", "report-format", "plain", OUTPUT_FORMATS
    )

    return opt
