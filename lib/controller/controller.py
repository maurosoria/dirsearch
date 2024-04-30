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

import gc
import os
import psycopg
import re
import time
import mysql.connector

from urllib.parse import urlparse

from lib.connection.dns import cache_dns
from lib.connection.requester import Requester
from lib.core.data import blacklists, options
from lib.core.decorators import locked
from lib.core.dictionary import Dictionary, get_blacklists
from lib.core.exceptions import (
    InvalidRawRequest,
    InvalidURLException,
    RequestException,
    SkipTargetInterrupt,
    QuitInterrupt,
    UnpicklingError,
)
from lib.core.fuzzer import Fuzzer
from lib.core.logger import enable_logging, logger
from lib.core.settings import (
    BANNER,
    DEFAULT_HEADERS,
    DEFAULT_SESSION_FILE,
    EXTENSION_RECOGNITION_REGEX,
    MAX_CONSECUTIVE_REQUEST_ERRORS,
    NEW_LINE,
    SCRIPT_PATH,
    STANDARD_PORTS,
    UNKNOWN,
)
from lib.parse.rawrequest import parse_raw
from lib.parse.url import clean_path, parse_path
from lib.reports.csv_report import CSVReport
from lib.reports.html_report import HTMLReport
from lib.reports.json_report import JSONReport
from lib.reports.markdown_report import MarkdownReport
from lib.reports.mysql_report import MySQLReport
from lib.reports.plain_text_report import PlainTextReport
from lib.reports.postgresql_report import PostgreSQLReport
from lib.reports.simple_report import SimpleReport
from lib.reports.sqlite_report import SQLiteReport
from lib.reports.xml_report import XMLReport
from lib.utils.common import get_valid_filename, lstrip_once
from lib.utils.file import FileUtils
from lib.utils.pickle import pickle, unpickle
from lib.utils.schemedet import detect_scheme
from lib.view.terminal import interface


class Controller:
    def __init__(self):
        if options["session_file"]:
            self._import(options["session_file"])
            self.old_session = True
        else:
            self.setup()
            self.old_session = False

        self.run()

    def _import(self, session_file):
        try:
            with open(session_file, "rb") as fd:
                indict, last_output, opt = unpickle(fd)
                options.update(opt)
        except UnpicklingError:
            interface.error(
                f"{session_file} is not a valid session file or it's in an old format"
            )
            exit(1)

        self.__dict__ = {**indict, **vars(self)}
        print(last_output)

    def _export(self, session_file):
        # Save written output
        last_output = interface.buffer.rstrip()

        # Can't pickle Fuzzer class due to _thread.lock objects
        del self.fuzzer

        with open(session_file, "wb") as fd:
            pickle((vars(self), last_output, options), fd)

    def setup(self):
        blacklists.update(get_blacklists())

        if options["raw_file"]:
            try:
                options.update(
                    zip(
                        ["urls", "http_method", "headers", "data"],
                        parse_raw(options["raw_file"]),
                    )
                )
            except InvalidRawRequest as e:
                print(str(e))
                exit(1)
        else:
            options["headers"] = {**DEFAULT_HEADERS, **options["headers"]}

            if options["user_agent"]:
                options["headers"]["user-agent"] = options["user_agent"]

            if options["cookie"]:
                options["headers"]["cookie"] = options["cookie"]

        self.requester = Requester()
        self.dictionary = Dictionary(files=options["wordlists"])
        self.results = []
        self.start_time = time.time()
        self.passed_urls = set()
        self.directories = []
        self.report = None
        self.batch = False
        self.jobs_processed = 0
        self.errors = 0
        self.consecutive_errors = 0

        if options["auth"]:
            self.requester.set_auth(options["auth_type"], options["auth"])

        if options["proxy_auth"]:
            self.requester.set_proxy_auth(options["proxy_auth"])

        if options["log_file"]:
            options["log_file"] = FileUtils.get_abs_path(options["log_file"])

            try:
                FileUtils.create_dir(FileUtils.parent(options["log_file"]))
                if not FileUtils.can_write(options["log_file"]):
                    raise Exception

                enable_logging()

            except Exception:
                interface.error(
                    f'Couldn\'t create log file at {options["log_file"]}'
                )
                exit(1)

        if options["autosave_report"]:
            self.report_path = options["output_path"] or FileUtils.build_path(
                SCRIPT_PATH, "reports"
            )

            try:
                FileUtils.create_dir(self.report_path)
                if not FileUtils.can_write(self.report_path):
                    raise Exception

            except Exception:
                interface.error(
                    f"Couldn't create report folder at {self.report_path}"
                )
                exit(1)

        interface.header(BANNER)
        interface.config(len(self.dictionary))

        try:
            self.setup_reports()
        except (
            InvalidURLException,
            mysql.connector.Error,
            psycopg.Error,
        ) as e:
            logger.exception(e)
            interface.error(str(e))
            exit(1)

        if options["log_file"]:
            interface.log_file(options["log_file"])

    def run(self):
        # match_callbacks and not_found_callbacks callback values:
        #  - *args[0]: lib.connection.Response() object
        #
        # error_callbacks callback values:
        #  - *args[0]: exception
        match_callbacks = (
            self.match_callback, self.reset_consecutive_errors
        )
        not_found_callbacks = (
            self.update_progress_bar, self.reset_consecutive_errors
        )
        error_callbacks = (self.raise_error, self.append_error_log)

        while options["urls"]:
            url = options["urls"][0]
            self.fuzzer = Fuzzer(
                self.requester,
                self.dictionary,
                match_callbacks=match_callbacks,
                not_found_callbacks=not_found_callbacks,
                error_callbacks=error_callbacks,
            )

            try:
                self.set_target(url)

                if not self.directories:
                    for subdir in options["subdirs"]:
                        self.add_directory(self.base_path + subdir)

                if not self.old_session:
                    interface.target(self.url)

                self.start()

            except (
                InvalidURLException,
                RequestException,
                SkipTargetInterrupt,
                KeyboardInterrupt,
            ) as e:
                self.directories.clear()
                self.dictionary.reset()

                if e.args:
                    interface.error(str(e))

            except QuitInterrupt as e:
                interface.error(e.args[0])
                exit(0)

            finally:
                options["urls"].pop(0)

        interface.warning("\nTask Completed")

        if options["session_file"]:
            try:
                os.remove(options["session_file"])
            except Exception:
                interface.error("Failed to delete old session file, remove it to free some space")

    def start(self):
        while self.directories:
            try:
                gc.collect()

                current_directory = self.directories[0]

                if not self.old_session:
                    current_time = time.strftime("%H:%M:%S")
                    msg = f"{NEW_LINE}[{current_time}] Starting: {current_directory}"

                    interface.warning(msg)

                self.fuzzer.set_base_path(current_directory)
                self.fuzzer.start()
                self.process()

            except KeyboardInterrupt:
                pass

            finally:
                self.dictionary.reset()
                self.directories.pop(0)

                self.jobs_processed += 1
                self.old_session = False

    def set_target(self, url):
        # If no scheme specified, unset it first
        if "://" not in url:
            url = f'{options["scheme"] or UNKNOWN}://{url}'
        if not url.endswith("/"):
            url += "/"

        parsed = urlparse(url)
        self.base_path = lstrip_once(parsed.path, "/")

        # Credentials in URL
        if "@" in parsed.netloc:
            cred, parsed.netloc = parsed.netloc.split("@")
            self.requester.set_auth("basic", cred)

        host = parsed.netloc.split(":")[0]

        if parsed.scheme not in (UNKNOWN, "https", "http"):
            raise InvalidURLException(f"Unsupported URI scheme: {parsed.scheme}")

        # If no port specified, set default (80, 443)
        try:
            port = int(parsed.netloc.split(":")[1])

            if not 0 < port < 65536:
                raise ValueError
        except IndexError:
            port = STANDARD_PORTS.get(parsed.scheme, None)
        except ValueError:
            port = parsed.netloc.split(":")[1]
            raise InvalidURLException(f"Invalid port number: {port}")

        if options["ip"]:
            cache_dns(host, port, options["ip"])

        try:
            # If no scheme is found, detect it by port number
            scheme = (
                parsed.scheme
                if parsed.scheme != UNKNOWN
                else detect_scheme(host, port)
            )
        except ValueError:
            # If the user neither provides the port nor scheme, guess them based
            # on standard website characteristics
            scheme = detect_scheme(host, 443)
            port = STANDARD_PORTS[scheme]

        self.url = f"{scheme}://{host}"

        if port != STANDARD_PORTS[scheme]:
            self.url += f":{port}"

        self.url += "/"

        self.requester.set_url(self.url)

    def setup_batch_reports(self):
        """Create batch report folder"""

        self.batch = True
        current_time = time.strftime("%y-%m-%d_%H-%M-%S")
        batch_session = f"BATCH-{current_time}"
        batch_directory_path = FileUtils.build_path(self.report_path, batch_session)

        try:
            FileUtils.create_dir(batch_directory_path)
        except Exception:
            interface.error(f"Couldn't create batch folder at {batch_directory_path}")
            exit(1)

        return batch_directory_path

    def get_output_extension(self):
        if options["output_format"] in ("plain", "simple"):
            return "txt"

        return options["output_format"]

    def setup_reports(self):
        """Create report file"""

        output = options["output"]

        if options["autosave_report"] and not output and options["output_format"] not in ("mysql", "postgresql"):
            if len(options["urls"]) > 1:
                directory_path = self.setup_batch_reports()
                filename = "BATCH." + self.get_output_extension()
            else:
                self.set_target(options["urls"][0])

                parsed = urlparse(self.url)

                if not parsed.netloc:
                    parsed = urlparse(f"//{options['urls'][0]}")

                filename = get_valid_filename(f"{parsed.path}_")
                filename += time.strftime("%y-%m-%d_%H-%M-%S")
                filename += f".{self.get_output_extension()}"
                directory_path = FileUtils.build_path(
                    self.report_path, get_valid_filename(f"{parsed.scheme}_{parsed.netloc}")
                )

            output = FileUtils.get_abs_path((FileUtils.build_path(directory_path, filename)))

            if FileUtils.exists(output):
                i = 2
                while FileUtils.exists(f"{output}_{i}"):
                    i += 1

                output += f"_{i}"

            try:
                FileUtils.create_dir(directory_path)
            except Exception:
                interface.error(
                    f"Couldn't create the reports folder at {directory_path}"
                )
                exit(1)

        if not output:
            return

        if options["output_format"] == "plain":
            self.report = PlainTextReport(output)
        elif options["output_format"] == "json":
            self.report = JSONReport(output)
        elif options["output_format"] == "xml":
            self.report = XMLReport(output)
        elif options["output_format"] == "md":
            self.report = MarkdownReport(output)
        elif options["output_format"] == "csv":
            self.report = CSVReport(output)
        elif options["output_format"] == "html":
            self.report = HTMLReport(output)
        elif options["output_format"] == "sqlite":
            self.report = SQLiteReport(output)
        elif options["output_format"] == "mysql":
            self.report = MySQLReport(output)
        elif options["output_format"] == "postgresql":
            self.report = PostgreSQLReport(output)
        else:
            self.report = SimpleReport(output)

        interface.output_location(output)

    def reset_consecutive_errors(self, response):
        self.consecutive_errors = 0

    def match_callback(self, response):
        if response.status in options["skip_on_status"]:
            raise SkipTargetInterrupt(
                f"Skipped the target due to {response.status} status code"
            )

        interface.status_report(response, options["full_url"])

        if response.status in options["recursion_status_codes"] and any(
            (
                options["recursive"],
                options["deep_recursive"],
                options["force_recursive"],
            )
        ):
            if response.redirect:
                new_path = clean_path(parse_path(response.redirect))
                added_to_queue = self.recur_for_redirect(response.path, new_path)
            elif len(response.history):
                old_path = clean_path(parse_path(response.history[0]))
                added_to_queue = self.recur_for_redirect(old_path, response.path)
            else:
                added_to_queue = self.recur(response.path)

            if added_to_queue:
                interface.new_directories(added_to_queue)

        if options["replay_proxy"]:
            # Replay the request with new proxy
            self.requester.request(response.full_path, proxy=options["replay_proxy"])

        if self.report:
            self.results.append(response)
            self.report.save(self.results)

    def update_progress_bar(self, response):
        jobs_count = (
            # Jobs left for unscanned targets
            len(options["subdirs"]) * (len(options["urls"]) - 1)
            # Jobs left for the current target
            + len(self.directories)
            # Finished jobs
            + self.jobs_processed
        )

        interface.last_path(
            self.dictionary.index,
            len(self.dictionary),
            self.jobs_processed + 1,
            jobs_count,
            self.requester.rate,
            self.errors,
        )

    def raise_error(self, exception):
        if options["exit_on_error"]:
            raise QuitInterrupt("Canceled due to an error")

        self.errors += 1
        self.consecutive_errors += 1

        if self.consecutive_errors > MAX_CONSECUTIVE_REQUEST_ERRORS:
            raise SkipTargetInterrupt("Too many request errors")

    def append_error_log(self, exception):
        logger.exception(exception)

    def handle_pause(self):
        interface.warning(
            "CTRL+C detected: Pausing threads, please wait...", do_save=False
        )
        self.fuzzer.pause()

        while True:
            msg = "[q]uit / [c]ontinue"

            if len(self.directories) > 1:
                msg += " / [n]ext"

            if len(options["urls"]) > 1:
                msg += " / [s]kip target"

            interface.in_line(msg + ": ")

            option = input()

            if option.lower() == "q":
                interface.in_line("[s]ave / [q]uit without saving: ")

                option = input()

                if option.lower() == "s":
                    msg = f'Save to file [{options["session_file"] or DEFAULT_SESSION_FILE}]: '

                    interface.in_line(msg)

                    session_file = (
                        input() or options["session_file"] or DEFAULT_SESSION_FILE
                    )

                    self._export(session_file)
                    raise QuitInterrupt(f"Session saved to: {session_file}")
                elif option.lower() == "q":
                    raise QuitInterrupt("Canceled by the user")

            elif option.lower() == "c":
                self.fuzzer.play()
                break

            elif option.lower() == "n" and len(self.directories) > 1:
                self.fuzzer.quit()
                break

            elif option.lower() == "s" and len(options["urls"]) > 1:
                raise SkipTargetInterrupt("Target skipped by the user")

    def is_timed_out(self):
        return time.time() - self.start_time > options["max_time"] > 0

    def process(self):
        while True:
            try:
                while not self.fuzzer.is_finished():
                    if self.is_timed_out():
                        raise SkipTargetInterrupt(
                            "Runtime exceeded the maximum set by the user"
                        )

                break

            except KeyboardInterrupt:
                self.handle_pause()

    def add_directory(self, path):
        """Add directory to the recursion queue"""

        # Pass if path is in exclusive directories
        if any(
            "/" + dir in path for dir in options["exclude_subdirs"]
        ):
            return

        url = self.url + path

        if (
            path.count("/") - self.base_path.count("/") > options["recursion_depth"] > 0
            or url in self.passed_urls
        ):
            return

        self.directories.append(path)
        self.passed_urls.add(url)

    @locked
    def recur(self, path):
        dirs_count = len(self.directories)
        path = clean_path(path)

        if options["force_recursive"] and not path.endswith("/"):
            path += "/"

        if options["deep_recursive"]:
            i = 0
            for _ in range(path.count("/")):
                i = path.index("/", i) + 1
                self.add_directory(path[:i])
        elif (
            options["recursive"]
            and path.endswith("/")
            and re.search(EXTENSION_RECOGNITION_REGEX, path[:-1]) is None
        ):
            self.add_directory(path)

        # Return newly added directories
        return self.directories[dirs_count:]

    def recur_for_redirect(self, path, redirect_path):
        if redirect_path == path + "/":
            return self.recur(redirect_path)

        return []
