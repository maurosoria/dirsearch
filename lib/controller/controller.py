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
import time
import re
import threading

from urllib.parse import urljoin, urlparse
from queue import Queue

from lib.connection.requester import Requester
from lib.connection.exception import RequestException
from lib.controller.exception import SkipTargetInterrupt
from lib.core.dictionary import Dictionary
from lib.core.fuzzer import Fuzzer
from lib.core.report_manager import Report, ReportManager
from lib.core.settings import SCRIPT_PATH, BANNER, NEW_LINE, DEFAULT_HEADERS
from lib.parse.raw import RawParser
from lib.utils.file import FileUtils
from lib.utils.fmt import get_valid_filename, human_size


class EmptyReportManager:
    def __init__(self):
        pass

    def update_report(self, *args):
        pass


class EmptyReport:
    def __init__(self):
        pass

    def add_result(self, *args):
        pass


class Controller(object):
    def __init__(self, options, output):
        self.directories = Queue()
        self.output = output
        self.options = options
        self.pass_dirs = ["/"]

        if options.raw_file:
            raw = RawParser(options.raw_file)
            self.url_list = [raw.url]
            self.httpmethod = raw.method
            self.data = raw.body
            self.headers = raw.headers
        else:
            self.url_list = options.url_list
            self.httpmethod = options.httpmethod
            self.data = options.httpmethod
            self.headers = {**DEFAULT_HEADERS, **options.headers}
            if options.cookie:
                self.headers["Cookie"] = options.cookie
            if options.useragent:
                self.headers["User-Agent"] = options.useragent

        self.random_agents = None
        if options.use_random_agents:
            self.random_agents = FileUtils.get_lines(
                FileUtils.build_path(SCRIPT_PATH, "db", "user-agents.txt")
            )

        self.blacklists = Dictionary.generate_blacklists(options.extensions)
        self.dictionary = Dictionary(
            paths=options.wordlist,
            extensions=options.extensions,
            suffixes=options.suffixes,
            prefixes=options.prefixes,
            lowercase=options.lowercase,
            uppercase=options.uppercase,
            capitalization=options.capitalization,
            force_extensions=options.force_extensions,
            exclude_extensions=options.exclude_extensions,
            no_extension=options.no_extension,
            only_selected=options.only_selected
        )

        self.jobs_count = len(self.url_list) * (
            len(options.scan_subdirs) if options.scan_subdirs else 1
        )
        self.current_job = 0
        self.batch = False
        self.batch_session = None
        self.exit = None

        self.threads_lock = threading.Lock()
        self.report_manager = EmptyReportManager()
        self.report = EmptyReport()
        self.start_time = time.time()

        self.output.header(BANNER)
        self.print_config()

        if options.autosave_report or options.output_file:
            if options.autosave_report:
                self.report_path = options.output_location or FileUtils.build_path(SCRIPT_PATH, "reports")
                self.create_dir(self.report_path)

            self.setup_reports()

        if options.log_file:
            self.create_dir(FileUtils.parent(options.log_file))
            self.output.log_file(FileUtils.get_abs_path(options.log_file))

        try:
            for url in self.url_list:
                try:
                    gc.collect()

                    try:
                        self.requester = Requester(
                            url if url.endswith("/") else url + "/",
                            max_pool=options.threads_count,
                            max_retries=options.max_retries,
                            timeout=options.timeout,
                            ip=options.ip,
                            proxy=options.proxy,
                            proxylist=options.proxylist,
                            redirect=options.follow_redirects,
                            request_by_hostname=options.request_by_hostname,
                            httpmethod=self.httpmethod,
                            data=self.data,
                            scheme=options.scheme,
                            random_agents=self.random_agents,
                        )

                        self.output.set_target(self.requester.base_url + self.requester.base_path)
                        self.requester.setup()

                        for key, value in self.headers.items():
                            self.requester.set_header(key, value)

                        if options.auth:
                            self.requester.set_auth(options.auth_type, options.auth)

                        # Test request to check if server is up
                        self.requester.request("")
                        self.write_log("Test request sent for: {}".format(self.requester.base_url))

                        self.output.url = self.requester.base_url[:-1]

                        if options.autosave_report or options.output_file:
                            self.report = Report(self.requester.host, self.requester.port, self.requester.scheme, self.requester.base_path)

                    except RequestException as e:
                        self.output.error(e.args[0])
                        raise SkipTargetInterrupt

                    self.skip = None

                    if not options.scan_subdirs:
                        self.directories.put("")

                    for subdir in options.scan_subdirs:
                        self.directories.put(subdir)
                        self.pass_dirs.append(subdir)

                    match_callbacks = [self.match_callback, self.append_log]
                    not_found_callbacks = [self.not_found_callback, self.append_log]
                    error_callbacks = [self.error_callback, self.append_error_log]
                    self.fuzzer = Fuzzer(
                        self.requester,
                        self.dictionary,
                        suffixes=options.suffixes,
                        prefixes=options.prefixes,
                        exclude_response=options.exclude_response,
                        threads=options.threads_count,
                        delay=options.delay,
                        maxrate=options.maxrate,
                        match_callbacks=match_callbacks,
                        not_found_callbacks=not_found_callbacks,
                        error_callbacks=error_callbacks,
                    )

                    try:
                        self.prepare()
                    except RequestException as e:
                        self.output.error(e.args[0])
                        raise SkipTargetInterrupt

                except SkipTargetInterrupt:
                    self.report.completed = True
                    continue

        except KeyboardInterrupt:
            self.close("Canceled by the user")

        self.output.warning("\nTask Completed")

    # Print dirsearch metadata (threads, HTTP method, ...)
    def print_config(self):
        self.output.config(
            ', '.join(self.options.extensions),
            ', '.join(self.options.prefixes),
            ', '.join(self.options.suffixes),
            str(self.options.threads_count),
            str(len(self.dictionary)),
            str(self.httpmethod),
        )

    # Create batch report folder
    def setup_batch_reports(self):
        self.batch = True
        if not self.options.output_file:
            self.batch_session = "BATCH-{0}".format(time.strftime("%y-%m-%d_%H-%M-%S"))
            self.batch_directory_path = FileUtils.build_path(
                self.report_path, self.batch_session
            )

            if not FileUtils.exists(self.batch_directory_path):
                FileUtils.create_directory(self.batch_directory_path)

                if not FileUtils.exists(self.batch_directory_path):
                    self.output.error(
                        "Couldn't create batch folder at {}".format(self.batch_directory_path)
                    )
                    exit(1)

    # Get file extension for report format
    def get_output_extension(self):
        if self.options.output_format not in ("plain", "simple"):
            return ".{0}".format(self.options.output_format)
        else:
            return ".txt"

    # Create report file
    def setup_reports(self):
        if self.options.output_file:
            output_file = FileUtils.get_abs_path(self.options.output_file)
            self.output.output_file(output_file)
        else:
            if len(self.url_list) > 1:
                self.setup_batch_reports()
                filename = "BATCH"
                filename += self.get_output_extension()
                directory_path = self.batch_directory_path
            else:
                parsed = urlparse(self.url_list[0])
                filename = (
                    "{}_".format(parsed.path)
                )
                filename += time.strftime("%y-%m-%d_%H-%M-%S")
                filename += self.get_output_extension()
                directory_path = FileUtils.build_path(
                    self.report_path, get_valid_filename(parsed.netloc)
                )

            filename = get_valid_filename(filename)
            output_file = FileUtils.build_path(directory_path, filename)

            if FileUtils.exists(output_file):
                i = 2
                while FileUtils.exists(output_file + "_" + str(i)):
                    i += 1

                output_file += "_" + str(i)

            if not FileUtils.exists(directory_path):
                FileUtils.create_directory(directory_path)

                if not FileUtils.exists(directory_path):
                    self.output.error(
                        "Couldn't create the reports folder at {}".format(directory_path)
                    )
                    exit(1)

            self.output.output_file(output_file)

        if self.options.output_format:
            self.report_manager = ReportManager(self.options.output_format, self.options.output_file or output_file)
        else:
            self.report_manager = ReportManager("plain", output_file)

    # Create and check if output directory is writable
    def create_dir(self, path):
        if not FileUtils.exists(path):
            self.create_dir(FileUtils.parent(path))
        if not FileUtils.is_dir(path):
            self.output.error("{0} is a file, should be a directory".format(path))
            exit(1)
        if not FileUtils.can_write(path):
            self.output.error("Directory {0} is not writable".format(path))
            exit(1)

        FileUtils.create_directory(path)

    # Validate the response by different filters
    def is_valid(self, path, res):
        if res.status in self.options.exclude_status_codes:
            return False

        if res.status not in (self.options.include_status_codes or range(100, 1000)):
            return False

        if self.blacklists.get(res.status) and path in self.blacklists.get(res.status):
            return False

        if human_size(res.length) in self.options.exclude_sizes:
            return False

        if res.length < self.options.minimum_response_size:
            return False

        if res.length > self.options.maximum_response_size != 0:
            return False

        for exclude_text in self.options.exclude_texts:
            if exclude_text in res.content:
                return False

        for exclude_regexp in self.options.exclude_regexps:
            if re.search(exclude_regexp, res.content) is not None:
                return False

        for exclude_redirect in self.options.exclude_redirects:
            if res.redirect and exclude_redirect in res.redirect or (
                    re.match(exclude_redirect, res.redirect)
            ):
                return False

        return True

    # Callback for found paths
    def match_callback(self, path, response):
        self.index += 1

        if response.status in self.options.skip_on_status:
            self.skip = "Skipped the target due to {} status code".format(response.status)
            return

        if not self.is_valid(path, response):
            return

        added_to_queue = False

        if response.status in self.options.recursion_status_codes and any(
            (self.options.recursive, self.options.deep_recursive, self.options.force_recursive)
        ):
            if response.redirect:
                added_to_queue = self.add_redirect_directory(path, response)
            else:
                added_to_queue = self.add_directory(path)

        self.output.status_report(response, self.options.full_url, added_to_queue)

        if self.options.replay_proxy:
            self.requester.request(path, proxy=self.options.replay_proxy)

        self.report.add_result(self.current_directory + path, response)
        self.report_manager.update_report(self.report)

    # Callback for invalid paths
    def not_found_callback(self, *args):
        self.index += 1
        self.output.last_path(
            self.index,
            len(self.dictionary),
            self.current_job,
            self.jobs_count,
            self.fuzzer.stand_rate,
        )

    # Callback for errors while fuzzing
    def error_callback(self, path, error_msg):
        if self.options.exit_on_error:
            self.exit = "Canceled due to an error"

        self.output.add_connection_error()

    def write_log(self, msg):
        if not self.options.log_file:
            return

        line = time.strftime("[%y-%m-%d %H:%M:%S] ")
        line += msg + NEW_LINE
        FileUtils.write_lines(self.options.log_file, line)

    # Write request to log file
    def append_log(self, path, response):
        msg = "{} {} {} {}".format(
            self.requester.ip or "0",
            response.status,
            self.httpmethod,
            self.requester.base_url[:-1] + response.path
        )

        if response.redirect:
            msg += " - REDIRECT TO: {}".format(response.redirect)
        msg += " (LENGTH: {})".format(response.length)

        with self.threads_lock:
            self.write_log(msg)

    # Write error to log file
    def append_error_log(self, path, error_msg):
        url = self.requester.base_url + self.requester.base_path + self.current_directory + path
        msg = "ERROR: {} {}".format(self.httpmethod, url)
        msg += NEW_LINE + " " * 4 + error_msg
        with self.threads_lock:
            self.write_log(msg)

    # Handle CTRL+C
    def handle_pause(self):
        self.output.warning("CTRL+C detected: Pausing threads, please wait...")
        self.fuzzer.pause()

        _ = 0
        while _ < 7:
            if self.fuzzer.is_stopped():
                break

            time.sleep(0.35)
            _ += 0.35

        while True:
            msg = "[q]uit / [c]ontinue"

            if not self.directories.empty():
                msg += " / [n]ext"

            if len(self.url_list) > 1:
                msg += " / [s]kip target"

            self.output.in_line(msg + ": ")

            option = input()

            if option.lower() == "q":
                self.close("Canceled by the user")

            elif option.lower() == "c":
                self.fuzzer.resume()
                return

            elif option.lower() == "n" and not self.directories.empty():
                self.fuzzer.stop()
                return

            elif option.lower() == "s" and len(self.url_list) > 1:
                raise SkipTargetInterrupt

    # Monitor the fuzzing process
    def process(self):
        while True:
            try:
                while not self.fuzzer.wait(0.3):
                    if time.time() - self.start_time > self.options.maxtime != 0:
                        self.skip = "Canceled because the runtime exceeded the maximum set by user"

                    if self.skip:
                        self.close(self.skip, skip=True)
                    elif self.exit:
                        self.close(self.exit)
                        break
                break

            except KeyboardInterrupt:
                self.handle_pause()

    # Preparation between subdirectory scans
    def prepare(self):
        while not self.directories.empty():
            gc.collect()
            self.current_job += 1
            self.index = 0
            self.current_directory = self.directories.get()
            self.output.warning(
                "\n[{1}] Starting: {0}".format(
                    self.current_directory, time.strftime("%H:%M:%S")
                )
            )
            self.fuzzer.requester.base_path = self.requester.base_path + self.current_directory
            self.fuzzer.start()
            self.process()

        self.report.completed = True

    # Add directory to the recursion queue
    def add_directory(self, path):
        dirs = []
        added = False
        # Remove parameters and fragment from the URL
        path = path.split("?")[0].split("#")[0]
        full_path = self.current_directory + path

        if any((path.startswith(directory) for directory in self.options.exclude_subdirs)):
            return False

        if self.options.force_recursive and not full_path.endswith("/"):
            full_path += "/"

        if self.options.deep_recursive:
            i = 0
            for _ in range(path.count("/")):
                i = path.index("/", i) + 1
                dirs.append(self.current_directory + path[:i])
        elif self.options.recursive and full_path.endswith("/"):
            dirs.append(full_path)

        for dir in dirs:
            if dir in self.pass_dirs:
                continue
            elif dir.count("/") > self.options.recursion_depth != 0:
                continue

            self.directories.put(dir)
            self.pass_dirs.append(dir)

            self.jobs_count += 1
            added = True

        return added

    # Resolve the redirect and add the path to the recursion queue
    # if it's a subdirectory of the current URL
    def add_redirect_directory(self, path, response):
        redirect_url = urljoin(self.requester.base_url, response.redirect)
        redirect_path = urlparse(redirect_url).path

        if redirect_path == response.path + "/":
            path = redirect_path[len(self.requester.base_path + self.current_directory) + 1:]
            return self.add_directory(path)

        return False

    def close(self, msg=None, skip=False):
        self.fuzzer.stop()
        self.output.error(msg)
        if skip:
            raise SkipTargetInterrupt

        self.report_manager.update_report(self.report)
        exit(0)
