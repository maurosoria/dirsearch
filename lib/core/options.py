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

from __future__ import annotations

import math
import os
import sys
import time
from optparse import Values
from typing import Any
from lib.core.settings import (
    AUTHENTICATION_TYPES,
    COMMON_EXTENSIONS,
    DEFAULT_SESSION_DIR,
    DEFAULT_TOR_PROXIES,
    FILE_BASED_OUTPUT_FORMATS,
    SCRIPT_PATH,
    WORDLIST_CATEGORIES,
    WORDLIST_CATEGORY_DIR,
)
from lib.core.request_backend import (
    REQUEST_BACKENDS,
    get_async_request_backend_error,
    get_native_request_backend_error,
)
from lib.core.native_runtime import (
    get_native_python_version_error,
    get_native_runtime_error,
)
from lib.core.filters import (
    parse_numeric_ranges,
    parse_size,
    parse_size_list,
    parse_time_filters,
    validate_regex,
)
from lib.core.wordlist_backend import WORDLIST_BACKENDS
from lib.parse.cmdline import parse_arguments
from lib.parse.config import ConfigParser
from lib.parse.headers import HeadersParser
from lib.utils import safe_xml
from lib.utils.cli import fail as _fail
from lib.utils.cli import print_diagnostic as _print_diagnostic
from lib.utils.common import iprange, read_stdin, strip_and_uniquify
from lib.utils.file import File, FileUtils
from lib.parse.nmap import parse_nmap


def validate_random_agent_headers(opt: Any) -> None:
    if opt.random_agents and any(
        name.lower() == "user-agent" for name in opt.headers
    ):
        _fail(
            "--random-agent cannot be combined with a fixed User-Agent "
            "from --user-agent, request headers, raw requests, or configuration"
        )


def parse_options() -> dict[str, Any]:
    opt = merge_config(parse_arguments())

    def _session_debug(message: str) -> None:
        if not os.environ.get("DIRSEARCH_SESSIONS_DEBUG"):
            return
        try:
            sys.stderr.write(f"[sessions] {message}\n")
            sys.stderr.flush()
        except Exception:
            return

    if opt.list_sessions:
        from lib.controller.session import SessionStore

        base_dir = opt.sessions_dir or DEFAULT_SESSION_DIR
        _session_debug(f"--list-sessions enabled base_dir={base_dir!r}")
        session_store = SessionStore({})
        sessions = session_store.list_sessions(base_dir)
        _session_debug(f"--list-sessions completed total={len(sessions)}")

        if not sessions:
            print(f"No resumable sessions found in {base_dir}")
            sys.exit(0)

        print(f"Resumable sessions in {base_dir}:")
        for index, session in enumerate(sessions, 1):
            modified = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(session["modified"])
            )
            url = session["url"] or "(unknown target)"
            print(
                f"{index}. {session['path']} | {url} | "
                f"targets left: {session['targets_left']} | "
                f"dirs left: {session['directories_left']} | "
                f"jobs done: {session['jobs_processed']} | "
                f"errors: {session['errors']} | "
                f"modified: {modified}"
            )
        sys.exit(0)

    if opt.session_id and opt.session_file:
        _fail("Use either --session or --session-id, not both.")

    if opt.session_id:
        from lib.controller.session import SessionStore

        base_dir = opt.sessions_dir or DEFAULT_SESSION_DIR
        _session_debug(f"--session-id enabled base_dir={base_dir!r}")
        session_store = SessionStore({})
        sessions = session_store.list_sessions(base_dir)
        _session_debug(f"--session-id sessions found total={len(sessions)}")
        if not sessions:
            _fail(f"No resumable sessions found in {base_dir}")
        try:
            session_index = int(str(opt.session_id), 10)
        except ValueError:
            _fail(f"Invalid session id: {opt.session_id}")
        _session_debug(f"--session-id parsed index={session_index}")
        if session_index < 1 or session_index > len(sessions):
            _fail(
                f"Session id out of range: {session_index} (1-{len(sessions)})"
            )
        opt.session_file = sessions[session_index - 1]["path"]
        _session_debug(f"--session-id resolved path={opt.session_file!r}")

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
    elif opt.nmap_report:
        try:
            opt.urls = parse_nmap(opt.nmap_report)
        except (
            OSError,
            AttributeError,
            TypeError,
            safe_xml.ParseError,
            safe_xml.UnsafeXML,
        ) as e:
            _fail("Error while parsing Nmap report: " + str(e))
    elif not opt.urls and not opt.wordlist_status:
        _fail("URL target is missing, try using -u <url>")

    if opt.wordlist_status and not opt.urls:
        opt.urls = []
    elif not opt.raw_file:
        opt.urls = strip_and_uniquify(
            filter(
                lambda url: not url.startswith("#"),
                opt.urls,
            )
        )

    if not opt.extensions:
        _print_diagnostic("WARNING: No extension was specified!")

    opt.wordlists = _resolve_wordlists(opt)

    if opt.thread_count < 1:
        _fail("Threads number must be greater than zero")

    if opt.wordlist_max_size < 1:
        _fail("--wordlist-max-size must be greater than zero")

    validate_numeric_options(opt)

    if opt.wordlist_backend not in WORDLIST_BACKENDS:
        _fail("--wordlist-backend must be one of: " + ", ".join(WORDLIST_BACKENDS))

    if opt.request_backend == "native" and not _is_cli_flag_present("-a", "--async"):
        opt.async_mode = False

    if opt.request_backend not in REQUEST_BACKENDS:
        _fail("--request-backend must be one of: " + ", ".join(REQUEST_BACKENDS))

    if (
        opt.request_backend == "native" or opt.wordlist_backend == "native"
    ) and (error := get_native_python_version_error()):
        _fail(error)

    if opt.tor:
        opt.proxies = list(DEFAULT_TOR_PROXIES)
    elif opt.proxies_file:
        fd = _access_file(opt.proxies_file)
        opt.proxies = fd.get_lines()

    if opt.data_file:
        fd = _access_file(opt.data_file)
        opt.data = FileUtils.read_bytes(fd.path)

    if opt.cert_file:
        _access_file(opt.cert_file)

    if opt.key_file:
        _access_file(opt.key_file)

    headers = {}

    if opt.headers_file:
        try:
            fd = _access_file(opt.headers_file)
            headers.update(dict(HeadersParser(fd.read())))
        except (OSError, UnicodeError, ValueError) as e:
            _fail("Error in headers file: " + str(e))

    if opt.headers:
        try:
            headers.update(dict(HeadersParser("\n".join(opt.headers))))
        except (UnicodeError, ValueError):
            _fail("Invalid headers")

    opt.headers = headers

    if opt.user_agent:
        opt.headers["user-agent"] = opt.user_agent

    if opt.cookie:
        opt.headers["cookie"] = opt.cookie

    validate_random_agent_headers(opt)

    opt.include_status_codes = _parse_status_codes(opt.include_status_codes)
    opt.exclude_status_codes = _parse_status_codes(opt.exclude_status_codes)
    opt.recursion_status_codes = _parse_status_codes(opt.recursion_status_codes)
    opt.skip_on_status = _parse_status_codes(opt.skip_on_status)
    opt.match_status_codes = _parse_status_codes(opt.match_status_codes)
    opt.filter_status_codes = _parse_status_codes(opt.filter_status_codes)
    opt.match_sizes = _parse_advanced_ranges(opt.match_sizes, "--match-size")
    opt.filter_sizes = _parse_advanced_ranges(opt.filter_sizes, "--filter-size")
    opt.match_words = _parse_advanced_ranges(opt.match_words, "--match-words")
    opt.filter_words = _parse_advanced_ranges(opt.filter_words, "--filter-words")
    opt.match_lines = _parse_advanced_ranges(opt.match_lines, "--match-lines")
    opt.filter_lines = _parse_advanced_ranges(opt.filter_lines, "--filter-lines")
    opt.match_time = _parse_advanced_times(opt.match_time, "--match-time")
    opt.filter_time = _parse_advanced_times(opt.filter_time, "--filter-time")
    _validate_advanced_mode(opt.matcher_mode, "--matcher-mode")
    _validate_advanced_mode(opt.filter_mode, "--filter-mode")
    validate_regex_options(opt)
    opt.prefixes = tuple(strip_and_uniquify(opt.prefixes.split(",")))
    opt.suffixes = tuple(strip_and_uniquify(opt.suffixes.split(",")))
    opt.subdirs = [
        subdir.lstrip("/")
        for subdir in strip_and_uniquify(
            [
                subdir if subdir.endswith("/") else subdir + "/"
                for subdir in opt.subdirs.split(",")
            ]
        )
    ]
    opt.exclude_subdirs = [
        subdir.lstrip("/")
        for subdir in strip_and_uniquify(
            [
                subdir if subdir.endswith("/") else subdir + "/"
                for subdir in opt.exclude_subdirs.split(",")
            ]
        )
    ]
    opt.exclude_sizes = _parse_size_list(opt.exclude_sizes, "--exclude-sizes")
    opt.minimum_response_size = _parse_size(
        opt.minimum_response_size,
        "--min-response-size",
    )
    opt.maximum_response_size = _parse_size(
        opt.maximum_response_size,
        "--max-response-size",
    )

    if opt.extensions == "*":
        opt.extensions = COMMON_EXTENSIONS
    else:
        opt.extensions = tuple(
            strip_and_uniquify(
                [extension.lstrip(".") for extension in opt.extensions.split(",")]
            )
        )

    opt.exclude_extensions = tuple(
        strip_and_uniquify(
            [
                exclude_extension.lstrip(".")
                for exclude_extension in opt.exclude_extensions.split(",")
            ]
        )
    )

    if opt.auth and not opt.auth_type:
        _fail("Please select the authentication type with --auth-type")
    elif opt.auth_type and not opt.auth:
        _fail("No authentication credential found")
    elif opt.auth and opt.auth_type not in AUTHENTICATION_TYPES:
        _fail(
            f"'{opt.auth_type}' is not in available authentication "
            f"types: {', '.join(AUTHENTICATION_TYPES)}"
        )

    if set(opt.extensions).intersection(opt.exclude_extensions):
        _fail(
            "Exclude extension list can not contain any extension "
            "that has already in the extension list"
        )

    opt.output_formats = [format.strip() for format in opt.output_formats.split(",") if format]

    invalid_formats = set(opt.output_formats).difference(FILE_BASED_OUTPUT_FORMATS)
    if invalid_formats:
        _fail(f"Invalid output format(s): {', '.join(invalid_formats)}")

    if not len(opt.output_formats) and opt.output_file:
        _fail("Please provide output formats (use '-O')")

    # There are multiple file-based output formats but no variable to separate output files for different formats
    if (
        opt.output_file
        and "{format}" not in opt.output_file
        and len(opt.output_formats) > 1
        and (
            "{extension}" not in opt.output_file
            # "plain" and "simple" have the same file extension (txt)
            or {"plain", "simple"}.issubset(opt.output_formats)
        )
    ):
        _fail("Found at least 2 output formats sharing the same output file, make sure you use '{format}' and '{extension} variables in your output file")

    if opt.mysql_url:
        opt.output_formats.append("mysql")

    if opt.postgres_url:
        opt.output_formats.append("postgresql")

    if opt.log_file:
        opt.log_file = FileUtils.get_abs_path(opt.log_file)

    if opt.output_file:
        opt.output_file = FileUtils.get_abs_path(opt.output_file)

    if opt.save_response:
        opt.save_response = FileUtils.get_abs_path(opt.save_response)

    if opt.save_response_jsonl:
        opt.save_response_jsonl = FileUtils.get_abs_path(opt.save_response_jsonl)

    if opt.request_backend == "native":
        if error := get_native_request_backend_error(opt):
            _fail(error)
    elif error := get_async_request_backend_error(opt):
        _fail(error)

    if error := get_native_runtime_error(
        opt.request_backend, opt.wordlist_backend
    ):
        _fail(error)

    return vars(opt)


def _parse_status_codes(str_: str) -> set[int]:
    if not str_:
        return set()

    status_codes: set[int] = set()

    for status_code in str_.split(","):
        try:
            if "-" in status_code:
                start, end = status_code.strip().split("-")
                status_codes.update(range(int(start), int(end) + 1))
            else:
                status_codes.add(int(status_code.strip()))
        except ValueError:
            _fail(f"Invalid status code or status code range: {status_code}")

    return status_codes


def _parse_advanced_ranges(value: str | None, option_name: str) -> tuple[tuple[int, int], ...]:
    try:
        return parse_numeric_ranges(value)
    except ValueError as error:
        _fail(f"{option_name}: {error}")


def _parse_advanced_times(value: str | None, option_name: str) -> tuple[tuple[str, float], ...]:
    try:
        return parse_time_filters(value)
    except ValueError as error:
        _fail(f"{option_name}: {error}")


def _parse_size(value: str | int | None, option_name: str) -> int:
    try:
        return parse_size(value)
    except ValueError as error:
        _fail(f"{option_name}: {error}")


def _parse_size_list(value: str | None, option_name: str) -> set[int]:
    try:
        return parse_size_list(value)
    except ValueError as error:
        _fail(f"{option_name}: {error}")


def _validate_regex_option(pattern: str | None, option_name: str) -> None:
    try:
        validate_regex(pattern, option_name)
    except ValueError as error:
        _fail(error)


def validate_regex_options(opt: Any) -> None:
    regex_options = (
        ("exclude_regex", "--exclude-regex"),
        ("exclude_redirect", "--exclude-redirect"),
        ("match_regex", "--match-regex"),
        ("filter_regex", "--filter-regex"),
        ("match_header_regex", "--match-header-regex"),
        ("filter_header_regex", "--filter-header-regex"),
    )

    for option_key, option_name in regex_options:
        _validate_regex_option(getattr(opt, option_key), option_name)


def _validate_advanced_mode(value: str, option_name: str) -> None:
    if value in ("and", "or"):
        return

    _fail(f"{option_name} must be either 'and' or 'or'")


def validate_numeric_options(opt: Any) -> None:
    if not math.isfinite(opt.timeout) or opt.timeout <= 0:
        _fail("--timeout must be finite and greater than zero")

    if not math.isfinite(opt.delay) or opt.delay < 0:
        _fail("--delay must be finite and zero or greater")

    if opt.sqlite_commit_batch_size < 1:
        _fail("--sqlite-commit-batch-size must be greater than zero")

    for attribute, option_name in (
        ("max_retries", "--retries"),
        ("max_rate", "--max-rate"),
        ("recursion_depth", "--max-recursion-depth"),
    ):
        if getattr(opt, attribute) < 0:
            _fail(f"{option_name} must be zero or greater")


def _is_cli_flag_present(*flags: str) -> bool:
    return any(argument in flags for argument in sys.argv[1:])


def _access_file(path: str) -> File:
    with File(path) as fd:
        if not fd.exists():
            _fail(f"{path} does not exist")

        if not fd.is_valid():
            _fail(f"{path} is not a file")

        if not fd.can_read():
            _fail(f"{path} cannot be read")

        return fd


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [entry.strip() for entry in value.split(",") if entry.strip()]


def _resolve_wordlist_categories(categories: list[str]) -> list[str]:
    if not categories:
        return []

    normalized = [category.strip() for category in categories if category.strip()]
    include_all = any(category.lower() in ("all", "*") for category in normalized)

    if include_all:
        return [
            FileUtils.build_path(WORDLIST_CATEGORY_DIR, filename)
            for filename in WORDLIST_CATEGORIES.values()
        ]

    resolved = []
    unknown = []
    for category in normalized:
        key = category.lower()
        if key.endswith("*"):
            prefix = key[:-1]
            matches = [
                filename
                for name, filename in WORDLIST_CATEGORIES.items()
                if name.startswith(prefix)
            ]
            if matches:
                resolved.extend(
                    FileUtils.build_path(WORDLIST_CATEGORY_DIR, filename)
                    for filename in matches
                )
                continue

        filename = WORDLIST_CATEGORIES.get(key)
        if filename:
            resolved.append(FileUtils.build_path(WORDLIST_CATEGORY_DIR, filename))
        else:
            unknown.append(category)

    if unknown:
        _fail(
            f"Unknown wordlist categories: {', '.join(unknown)}",
            "Available categories: " + ", ".join(sorted(WORDLIST_CATEGORIES.keys())),
        )

    return resolved


def _resolve_wordlists(opt: Values) -> list[str]:
    wordlists = []
    wordlists.extend(_split_csv(opt.wordlists))
    wordlists.extend(
        _resolve_wordlist_categories(_split_csv(opt.wordlist_categories))
    )

    if not wordlists:
        wordlists = [FileUtils.build_path(SCRIPT_PATH, "db", "dicc.txt")]

    expanded = []
    for wordlist in wordlists:
        if FileUtils.is_dir(wordlist):
            expanded.extend(FileUtils.get_files(wordlist))
        else:
            expanded.append(wordlist)

    unique = []
    seen = set()
    for path in expanded:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)

    for path in unique:
        _access_file(path)

    return unique


def merge_config(opt: Values) -> Values:
    config = ConfigParser()
    config.read(opt.config)

    # General
    opt.thread_count = opt.thread_count or config.safe_getint("general", "threads", 25)
    opt.async_mode = (
        config.safe_getboolean("general", "async", True)
        if opt.async_mode is None
        else opt.async_mode
    )
    opt.filter_threshold = (
        config.safe_getint("general", "filter-threshold", 0)
        if opt.filter_threshold is None
        else opt.filter_threshold
    )
    opt.include_status_codes = opt.include_status_codes or config.safe_get(
        "general", "include-status"
    )
    opt.exclude_status_codes = opt.exclude_status_codes or config.safe_get(
        "general", "exclude-status"
    )
    opt.exclude_sizes = opt.exclude_sizes or config.safe_get(
        "general", "exclude-sizes", ""
    )
    opt.exclude_texts = opt.exclude_texts or config.safe_getlist(
        "general", "exclude-texts"
    )
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
    opt.recursion_depth = (
        config.safe_getint("general", "max-recursion-depth")
        if opt.recursion_depth is None
        else opt.recursion_depth
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
    opt.auto_calibration = opt.auto_calibration or config.safe_getboolean(
        "general", "auto-calibration"
    )
    opt.matcher_mode = opt.matcher_mode or config.safe_get(
        "advanced-filtering", "matcher-mode", "or", ("and", "or")
    )
    opt.filter_mode = opt.filter_mode or config.safe_get(
        "advanced-filtering", "filter-mode", "or", ("and", "or")
    )
    opt.match_status_codes = opt.match_status_codes or config.safe_get(
        "advanced-filtering", "match-status", ""
    )
    opt.filter_status_codes = opt.filter_status_codes or config.safe_get(
        "advanced-filtering", "filter-status", ""
    )
    opt.match_sizes = opt.match_sizes or config.safe_get(
        "advanced-filtering", "match-size", ""
    )
    opt.filter_sizes = opt.filter_sizes or config.safe_get(
        "advanced-filtering", "filter-size", ""
    )
    opt.match_words = opt.match_words or config.safe_get(
        "advanced-filtering", "match-words", ""
    )
    opt.filter_words = opt.filter_words or config.safe_get(
        "advanced-filtering", "filter-words", ""
    )
    opt.match_lines = opt.match_lines or config.safe_get(
        "advanced-filtering", "match-lines", ""
    )
    opt.filter_lines = opt.filter_lines or config.safe_get(
        "advanced-filtering", "filter-lines", ""
    )
    opt.match_regex = opt.match_regex or config.safe_get(
        "advanced-filtering", "match-regex"
    )
    opt.filter_regex = opt.filter_regex or config.safe_get(
        "advanced-filtering", "filter-regex"
    )
    opt.match_headers = opt.match_headers or config.safe_getlist(
        "advanced-filtering", "match-header"
    )
    opt.filter_headers = opt.filter_headers or config.safe_getlist(
        "advanced-filtering", "filter-header"
    )
    opt.match_header_regex = opt.match_header_regex or config.safe_get(
        "advanced-filtering", "match-header-regex"
    )
    opt.filter_header_regex = opt.filter_header_regex or config.safe_get(
        "advanced-filtering", "filter-header-regex"
    )
    opt.match_time = opt.match_time or config.safe_get(
        "advanced-filtering", "match-time", ""
    )
    opt.filter_time = opt.filter_time or config.safe_get(
        "advanced-filtering", "filter-time", ""
    )
    opt.max_time = (
        config.safe_getint("general", "max-time")
        if opt.max_time is None
        else opt.max_time
    )
    opt.target_max_time = (
        config.safe_getint("general", "target-max-time")
        if opt.target_max_time is None
        else opt.target_max_time
    )
    opt.exit_on_error = opt.exit_on_error or config.safe_getboolean(
        "general", "exit-on-error"
    )

    # Dictionary
    opt.wordlists = opt.wordlists or config.safe_get("dictionary", "wordlists")
    opt.wordlist_categories = opt.wordlist_categories or config.safe_get(
        "dictionary", "wordlist-categories"
    )
    opt.wordlist_backend = opt.wordlist_backend or config.safe_get(
        "dictionary", "wordlist-backend", "auto"
    )
    opt.wordlist_max_size = opt.wordlist_max_size or config.safe_getint(
        "dictionary", "wordlist-max-size", 500000
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
    opt.capital = opt.capital or config.safe_getboolean(
        "dictionary", "capital"
    )

    # Request
    opt.http_method = opt.http_method or config.safe_get(
        "request", "http-method", "get"
    )
    opt.request_backend = opt.request_backend or config.safe_get(
        "request", "request-backend", "python"
    )
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
    opt.delay = (
        config.safe_getfloat("connection", "delay")
        if opt.delay is None
        else opt.delay
    )
    opt.timeout = (
        config.safe_getfloat("connection", "timeout", 7.5)
        if opt.timeout is None
        else opt.timeout
    )
    opt.max_retries = (
        config.safe_getint("connection", "max-retries", 1)
        if opt.max_retries is None
        else opt.max_retries
    )
    opt.max_rate = (
        config.safe_getint("connection", "max-rate")
        if opt.max_rate is None
        else opt.max_rate
    )
    opt.proxies = opt.proxies or config.safe_getlist("connection", "proxies")
    opt.proxies_file = opt.proxies_file or config.safe_get("connection", "proxies-file")
    opt.scheme = opt.scheme or config.safe_get(
        "connection", "scheme", None, ("http", "https")
    )
    opt.replay_proxy = opt.replay_proxy or config.safe_get("connection", "replay-proxy")
    opt.network_interface = opt.network_interface or config.safe_get(
        "connection", "network-interface"
    )

    # Advanced
    opt.crawl = opt.crawl or config.safe_getboolean("advanced", "crawl")
    opt.find_backup = opt.find_backup or config.safe_getboolean(
        "advanced", "find-backup"
    )

    # View
    opt.full_url = opt.full_url or config.safe_getboolean("view", "full-url")
    opt.color = opt.color if opt.color is False else config.safe_getboolean("view", "color", True)
    opt.quiet = opt.quiet or config.safe_getboolean("view", "quiet-mode")
    opt.disable_cli = opt.disable_cli or config.safe_getboolean("view", "disable-cli")
    opt.verbose = opt.verbose or config.safe_getboolean("view", "verbose")
    opt.redirects_history = opt.redirects_history or config.safe_getboolean(
        "view", "show-redirects-history"
    )

    # Output
    opt.output_file = opt.output_file or config.safe_get("output", "output-file")
    opt.mysql_url = opt.mysql_url or config.safe_get("output", "mysql-url")
    opt.postgres_url = opt.postgres_url or config.safe_get("output", "postgres-url")
    opt.output_table = config.safe_get("output", "output-sql-table")
    opt.output_formats = opt.output_formats or config.safe_get(
        "output", "output-formats", "plain"
    )
    opt.sqlite_commit_batch_size = (
        config.safe_getint("output", "sqlite-commit-batch-size", 1)
        if opt.sqlite_commit_batch_size is None
        else opt.sqlite_commit_batch_size
    )
    opt.save_response = opt.save_response or config.safe_get(
        "output", "save-response"
    )
    opt.save_response_jsonl = opt.save_response_jsonl or config.safe_get(
        "output", "save-response-jsonl"
    )
    opt.log_file = opt.log_file or config.safe_get("output", "log-file")
    opt.log_file_size = config.safe_getint("output", "log-file-size")

    return opt
