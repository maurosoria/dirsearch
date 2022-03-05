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

from collections import deque
from urllib.parse import urlparse

from lib.connection.requester import Requester
from lib.core.dictionary import Dictionary
from lib.core.exceptions import (
    InvalidURLException, RequestException, SkipTargetInterrupt,
    GenericException, QuitInterrupt
)
from lib.core.fuzzer import Fuzzer
from lib.core.logger import log
from lib.core.report_manager import Report, ReportManager
from lib.core.settings import (
    SCRIPT_PATH, BANNER, DEFAULT_HEADERS, DEFAULT_SESSION_FILE,
    EXTENSION_REGEX, MAX_CONSECUTIVE_REQUEST_ERRORS, NEW_LINE,
    PAUSING_WAIT_TIMEOUT
)
from lib.parse.rawrequest import parse_raw
from lib.parse.url import clean_path, parse_path, join_path
from lib.utils.common import get_valid_filename, human_size, pickle, unpickle
from lib.utils.file import FileUtils


class Controller(object):
    def __init__(self, options, output):
        if options.session_file:
            self._import(options.session_file)
            self.from_export = True
        else:
            self.setup(options, output)
            self.from_export = False

        try:
            self.run()
        except KeyboardInterrupt:
            self.close("Canceled by the user")

    def _import(self, session_file):
        with open(session_file, "rb") as fd:
            export = unpickle(fd)

        self.__dict__ = {**export, **vars(self)}

    def _export(self, session_file):
        # Add the current item back to the queue
        self.targets.insert(0, self.url)
        self.directories.insert(0, self.current_directory)
        self.current_job -= 1
        # Save written output
        self.last_output = self.output.buffer.rstrip()

        # This attribute doesn't need to be saved
        del self.fuzzer

        with open(session_file, "wb") as fd:
            pickle(vars(self), fd)

    def setup(self, options, output):
        self.options, self.output = options, output

        if self.options.raw_file:
            self.options.update(
                zip(["urls", "httpmethod", "headers", "data"], parse_raw(self.options.raw_file))
            )
        else:
            self.options.headers = {**DEFAULT_HEADERS, **self.options.headers}

            if self.options.cookie:
                self.options.headers["Cookie"] = self.options.cookie
            if self.options.useragent:
                self.options.headers["User-Agent"] = self.options.useragent

        self.random_agents = None
        if self.options.use_random_agents:
            self.random_agents = FileUtils.get_lines(
                FileUtils.build_path(SCRIPT_PATH, "db", "user-agents.txt")
            )

        self.requester = Requester(
            max_pool=self.options.threads_count,
            max_retries=self.options.max_retries,
            timeout=self.options.timeout,
            ip=self.options.ip,
            proxy=self.options.proxy,
            proxylist=self.options.proxylist,
            follow_redirects=self.options.follow_redirects,
            httpmethod=self.options.httpmethod,
            headers=self.options.headers,
            data=self.options.data,
            scheme=self.options.scheme,
            random_agents=self.random_agents,
        )
        self.dictionary = Dictionary(
            paths=self.options.wordlist,
            extensions=self.options.extensions,
            suffixes=self.options.suffixes,
            prefixes=self.options.prefixes,
            lowercase=self.options.lowercase,
            uppercase=self.options.uppercase,
            capitalization=self.options.capitalization,
            force_extensions=self.options.force_extensions,
            exclude_extensions=self.options.exclude_extensions,
            no_extension=self.options.no_extension,
            only_selected=self.options.only_selected
        )
        self.blacklists = Dictionary.generate_blacklists(self.options.extensions)
        self.targets = deque(self.options.urls)
        self.current_job = 0
        self.batch = False
        self.report = None
        self.current_directory = None
        self.directories = deque()
        self.passed_urls = set()
        self.start_time = time.time()
        self.jobs_count = 0
        self.errors = 0
        self.consecutive_errors = 0

        if self.options.auth:
            self.requester.set_auth(self.options.auth_type, self.options.auth)

        if self.options.proxy_auth:
            self.requester.set_proxy_auth(self.options.proxy_auth)

        if self.options.log_file:
            self.options.log_file = FileUtils.get_abs_path(self.options.log_file)

            try:
                FileUtils.create_dir(FileUtils.parent(self.options.log_file))
                if not FileUtils.can_write(self.options.log_file):
                    raise Exception

            except Exception:
                self.output.error(f"Couldn't create log file at {self.options.log_file}")
                exit(1)

        if self.options.autosave_report:
            self.report_path = self.options.output_path or FileUtils.build_path(SCRIPT_PATH, "reports")

            try:
                FileUtils.create_dir(self.report_path)
                if not FileUtils.can_write(self.report_path):
                    raise Exception

            except Exception:
                self.output.error(f"Couldn't create report folder at {self.report_path}")
                exit(1)

        self.output.header(BANNER)
        self.output.config(
            ', '.join(self.options["extensions"]),
            ', '.join(self.options["prefixes"]),
            ', '.join(self.options["suffixes"]),
            str(self.options["threads_count"]),
            str(len(self.dictionary)),
            str(self.options["httpmethod"]),
        )

        self.setup_reports()

        if self.options.log_file:
            self.output.log_file(self.options.log_file)

    def run(self):
        match_callbacks = (self.match_callback, self.append_traffic_log)
        not_found_callbacks = (self.not_found_callback, self.append_traffic_log)
        error_callbacks = (self.error_callback, self.append_error_log)

        while len(self.targets):
            try:
                url = self.targets.popleft()

                try:
                    self.requester.set_target(url if url.endswith('/') else url + '/')
                    self.url = self.requester.url + self.requester.base_path

                    if not self.directories:
                        for subdir in self.options.scan_subdirs:
                            self.add_directory(subdir)

                    if self.from_export:
                        # Rewrite the output from the last scan
                        print(self.last_output)
                    else:
                        self.output.set_target(self.url)

                    # Test request to check if server is up
                    self.requester.request('')
                    log(self.options.log_file, "info", f"Test request sent for: {self.url}")

                    self.output.url = self.requester.url
                    self.report = self.report or Report(
                        self.requester.host, self.requester.port,
                        self.requester.scheme, self.requester.base_path
                    )

                except InvalidURLException as e:
                    self.output.error(e.args[0])
                    raise SkipTargetInterrupt

                except RequestException as e:
                    self.output.error(e.args[0])
                    self.append_error_log('', e.args[1])
                    raise SkipTargetInterrupt

                self.fuzzer = Fuzzer(
                    self.requester,
                    self.dictionary,
                    suffixes=self.options.suffixes,
                    prefixes=self.options.prefixes,
                    exclude_response=self.options.exclude_response,
                    threads=self.options.threads_count,
                    delay=self.options.delay,
                    maxrate=self.options.maxrate,
                    match_callbacks=match_callbacks,
                    not_found_callbacks=not_found_callbacks,
                    error_callbacks=error_callbacks,
                )

                try:
                    self.start()
                except RequestException as e:
                    self.output.error(e.args[0])
                    self.append_error_log('', e.args[1])
                    raise SkipTargetInterrupt

            except SkipTargetInterrupt:
                self.jobs_count -= len(self.directories)
                self.directories.clear()
                self.dictionary.reset()

                if self.report:
                    self.report.completed = True

                continue

        self.output.warning("\nTask Completed")

    def start(self):
        first = True

        while len(self.directories):
            gc.collect()

            self.current_directory = self.directories.popleft()
            self.current_job += 1

            if not self.from_export or not first:
                current_time = time.strftime('%H:%M:%S')
                msg = '\n' if first else ''
                msg += f"[{current_time}] Starting: {self.current_directory}"

                self.output.warning(msg)

            self.fuzzer.set_base_path(self.requester.base_path + self.current_directory)
            self.fuzzer.start()
            self.process()
            self.dictionary.reset()

            first = False

        self.report.completed = True

    # Create batch report folder
    def setup_batch_reports(self):
        self.batch = True
        current_time = time.strftime("%y-%m-%d_%H-%M-%S")
        batch_session = f"BATCH-{current_time}"
        batch_directory_path = FileUtils.build_path(self.report_path, batch_session)

        try:
            FileUtils.create_dir(batch_directory_path)
        except Exception:
            self.output.error(f"Couldn't create batch folder at {batch_directory_path}")
            exit(1)

        return batch_directory_path

    # Get file extension for report format
    def get_output_extension(self):
        if self.options.output_format not in ("plain", "simple"):
            return f".{self.options.output_format}"
        else:
            return ".txt"

    # Create report file
    def setup_reports(self):
        output_file = None

        if self.options.output_file:
            output_file = FileUtils.get_abs_path(self.options.output_file)
        elif self.options.autosave_report:
            if len(self.targets) > 1:
                directory_path = self.setup_batch_reports()
                filename = "BATCH" + self.get_output_extension()
            else:
                parsed = urlparse(self.options.urls[0])
                filename = get_valid_filename(f"{parsed.path}_")
                filename += time.strftime("%y-%m-%d_%H-%M-%S")
                filename += self.get_output_extension()
                directory_path = FileUtils.build_path(
                    self.report_path, get_valid_filename(parsed.netloc)
                )

            output_file = FileUtils.build_path(directory_path, filename)

            if FileUtils.exists(output_file):
                i = 2
                while FileUtils.exists(f"{output_file}_{i}"):
                    i += 1

                output_file += f"_{i}"

            try:
                FileUtils.create_dir(directory_path)
            except Exception:
                self.output.error(f"Couldn't create the reports folder at {directory_path}")
                exit(1)

        self.report_manager = ReportManager(self.options.output_format, output_file)

        if output_file:
            self.output.output_file(output_file)

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

        if res.length > self.options.maximum_response_size > 0:
            return False

        if any(ex_text in res.content for ex_text in self.options.exclude_texts):
            return False

        if self.options.exclude_regex and re.search(self.options.exclude_regex, res.content) is not None:
            return False

        if self.options.exclude_redirect and (
            self.options.exclude_redirect in res.redirect or re.search(
                self.options.exclude_redirect, res.redirect
            ) is not None
        ):
            return False

        return True

    def reset_consecutive_errors(self):
        self.consecutive_errors = 0

    def match_callback(self, path, response):
        if response.status in self.options.skip_on_status:
            raise SkipTargetInterrupt(f"Skipped the target due to {response.status} status code")

        if not self.is_valid(path, response):
            return

        self.output.status_report(response, self.options.full_url)

        if response.status in self.options.recursion_status_codes and any(
            (self.options.recursive, self.options.deep_recursive, self.options.force_recursive)
        ):
            if response.redirect:
                added_to_queue = self.recur_for_redirect(path, response)
            else:
                added_to_queue = self.recur(path)

            self.output.new_directories(added_to_queue)

        if self.options.replay_proxy:
            self.requester.request(path, proxy=self.options.replay_proxy)

        self.report.add_result(self.current_directory + path, response)
        self.report_manager.update_report(self.report)
        self.reset_consecutive_errors()

    def not_found_callback(self, *args):
        self.output.last_path(
            self.dictionary.index,
            len(self.dictionary),
            self.current_job,
            self.jobs_count,
            self.fuzzer.rate,
            self.errors
        )
        self.reset_consecutive_errors()

    def error_callback(self, path, error_msg):
        if self.options.exit_on_error:
            raise QuitInterrupt("Canceled due to an error")

        self.errors += 1
        self.consecutive_errors += 1

        if self.consecutive_errors > MAX_CONSECUTIVE_REQUEST_ERRORS:
            raise SkipTargetInterrupt("Too many request errors")

    # Write request to log file
    def append_traffic_log(self, path, response):
        url = join_path(self.requester.url, response.path)
        msg = f"{self.requester.ip or '0'} {response.status} "
        msg += f"{self.options.httpmethod} {url}"

        if response.redirect:
            msg += f" - REDIRECT TO: {response.redirect}"
        msg += f" (LENGTH: {response.length})"

        log(self.options.log_file, "traffic", msg)

    # Write error to log file
    def append_error_log(self, path, error_msg):
        url = join_path(self.url, self.current_directory, path)
        msg = f"{self.options.httpmethod} {url}"
        msg += NEW_LINE
        msg += ' ' * 4
        msg += error_msg
        log(self.options.log_file, "error", msg)

    # Handle CTRL+C
    def handle_pause(self):
        self.output.warning("CTRL+C detected: Pausing threads, please wait...", do_save=False)
        self.fuzzer.pause()

        start_time = time.time()
        while 1:
            is_timed_out = time.time() - start_time > PAUSING_WAIT_TIMEOUT
            if self.fuzzer.is_stopped() or is_timed_out:
                break

            time.sleep(0.2)

        while True:
            msg = "[q]uit / [c]ontinue"

            if len(self.directories):
                msg += " / [n]ext"

            if len(self.targets):
                msg += " / [s]kip target"

            self.output.in_line(msg + ": ")

            option = input()

            if option.lower() == 'q':
                self.output.in_line("[s]ave / [q]uit without saving: ")

                option = input()

                if option.lower() == 'q':
                    self.close("Canceled by the user")
                elif option.lower() == 's':
                    msg = f"Save to file [{self.options.session_file or DEFAULT_SESSION_FILE}]: "

                    self.output.in_line(msg)

                    session_file = input() or DEFAULT_SESSION_FILE

                    self._export(session_file)
                    self.close(f"Session saved to: {session_file}")
            elif option.lower() == 'c':
                self.fuzzer.resume()
                return
            elif option.lower() == 'n' and len(self.directories):
                self.fuzzer.stop()
                return
            elif option.lower() == 's' and len(self.targets):
                raise SkipTargetInterrupt

    def is_timed_out(self):
        return time.time() - self.start_time > self.options.maxtime > 0

    # Monitor the fuzzing process
    def process(self):
        while True:
            try:
                while not self.fuzzer.wait(0.3):
                    if self.is_timed_out():
                        raise SkipTargetInterrupt("Runtime exceeded the maximum set by the user")

                break

            except KeyboardInterrupt:
                self.handle_pause()

            except SkipTargetInterrupt as e:
                self.output.error(e.args[0])
                raise e

            except QuitInterrupt as e:
                self.close(e.args[0])

    # Add directory to the recursion queue
    def add_directory(self, path):
        # Pass if path is in exclusive directories
        if any(path.startswith(directory) for directory in self.options.exclude_subdirs):
            raise GenericException

        dir = join_path(self.current_directory, path)
        url = join_path(self.url, dir)

        if url in self.passed_urls or dir.count('/') > self.options.recursion_depth > 0:
            raise GenericException

        self.directories.append(dir)
        self.passed_urls.add(url)
        self.jobs_count += 1

    # Check for recursion
    def recur(self, path):
        dirs = []
        path = clean_path(path)

        if self.options.force_recursive and not path.endswith('/'):
            path += '/'

        if self.options.deep_recursive:
            i = 0
            for _ in range(path.count('/')):
                i = path.index('/', i) + 1
                dirs.append(path[:i])
        elif self.options.recursive and path.endswith('/') and re.search(
            EXTENSION_REGEX, path[:-1]
        ):
            dirs.append(path)

        for dir in dirs:
            try:
                self.add_directory(dir)
                yield dir
            except GenericException:
                pass

    # Resolve the redirect and add the path to the recursion queue
    # if it's a subdirectory of the current URL
    def recur_for_redirect(self, path, response):
        redirect_path = parse_path(response.redirect)

        if redirect_path == response.path + '/':
            path = redirect_path[len(self.requester.base_path + self.current_directory) + 1:]
            return self.recur(path)

    def close(self, msg):
        self.output.error(msg)
        self.report_manager.update_report(self.report)
        exit(0)
