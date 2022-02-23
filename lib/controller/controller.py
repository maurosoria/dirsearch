
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

import ast
import gc
import time
import re
import socket

from queue import Queue, deque
from urllib.parse import urlparse

from lib.connection.requester import Requester
from lib.core.dictionary import Dictionary
from lib.core.exceptions import InvalidURLException, RequestException, SkipTargetInterrupt, QuitInterrupt
from lib.core.fuzzer import Fuzzer
from lib.core.logger import log
from lib.core.report_manager import Report, ReportManager
from lib.core.settings import SCRIPT_PATH, BANNER, NEW_LINE, DEFAULT_HEADERS, EXCLUDE_EXPORT_VARIABLES, DEFAULT_SESSION_FILE, EXTENSION_REGEX
from lib.parse.rawrequest import parse_raw
from lib.parse.url import clean_path, parse_path, join_path
from lib.utils.common import get_valid_filename, human_size
from lib.utils.file import FileUtils


class Controller(object):
    def __init__(self, options, output):
        self.targets = Queue()
        self.directories = Queue()
        self.output = output

        if options["session_file"]:
            self._import(FileUtils.read(options["session_file"]))
            self.from_export = True
        else:
            self.setup(options)
            self.from_export = False

        if not self.options["autosave_report"] and not self.options["output_file"]:
            global Report
            global ReportManager

            class Report:
                def __init__(*args):
                    pass

                def add_result(*args):
                    pass

            class ReportManager:
                def __init__(*args):
                    pass

                def update_report(*args):
                    pass

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

        if self.options["log_file"]:
            self.output.log_file(self.options["log_file"])

        try:
            self.run()
        except KeyboardInterrupt:
            self.close("Canceled by the user")

    def setup(self, options):
        self.options = options
        self.pass_dirs = {''}

        if options["raw_file"]:
            self.options.update(
                zip(["urls", "httpmethod", "headers", "data"], parse_raw(options["raw_file"]))
            )
        else:
            self.options["headers"] = {**DEFAULT_HEADERS, **options["headers"]}

            if options["cookie"]:
                self.options["headers"]["Cookie"] = options["cookie"]
            if options["useragent"]:
                self.options["headers"]["User-Agent"] = options["useragent"]

        self.random_agents = None

        if options["use_random_agents"]:
            self.random_agents = FileUtils.get_lines(
                FileUtils.build_path(SCRIPT_PATH, "db", "user-agents.txt")
            )

        self.targets.queue = deque(options["urls"])
        self.blacklists = Dictionary.generate_blacklists(options["extensions"])
        self.dictionary = Dictionary(
            paths=options["wordlist"],
            extensions=options["extensions"],
            suffixes=options["suffixes"],
            prefixes=options["prefixes"],
            lowercase=options["lowercase"],
            uppercase=options["uppercase"],
            capitalization=options["capitalization"],
            force_extensions=options["force_extensions"],
            exclude_extensions=options["exclude_extensions"],
            no_extension=options["no_extension"],
            only_selected=options["only_selected"]
        )
        self.current_job = 0
        self.batch = False
        self.report = None
        self.current_directory = ''
        self.start_time = time.time()
        self.jobs_count = self.targets.qsize() * (
            len(options["scan_subdirs"]) if options["scan_subdirs"] else 1
        )

        if options["autosave_report"]:
            self.report_path = options["output_location"] or FileUtils.build_path(SCRIPT_PATH, "reports")

            try:
                FileUtils.create_dir(self.report_path)

                if not FileUtils.can_write(self.report_path):
                    raise Exception
            except Exception:
                self.output.error(f"Couldn't create report folder at {self.report_path}")
                exit(1)

        if options["log_file"]:
            self.options["log_file"] = FileUtils.get_abs_path(options["log_file"])

            try:
                FileUtils.create_dir(FileUtils.parent(self.options["log_file"]))

                if not FileUtils.can_write(self.options["log_file"]):
                    raise Exception
            except Exception:
                self.output.error(f"Couldn't create log file at {self.options['log_file']}")
                exit(1)

    def _import(self, data):
        export = ast.literal_eval(data)
        self.targets.queue = deque(export["targets"])
        self.directories.queue = deque(export["directories"])
        self.dictionary = Dictionary()
        self.dictionary.set_state(export["dictionary_items"], export["dictionary_index"])
        self.__dict__ = {**export, **vars(self)}

    def _export(self, session_file):
        self.targets.queue.insert(0, self.url)
        self.directories.queue.insert(0, self.current_directory)

        # Queue() objects, convert them to list
        for item in ("targets", "directories"):
            self.__dict__[item] = list(vars(self)[item].queue)

        self.dictionary_items, self.dictionary_index = self.dictionary.get_state()
        self.last_output = self.output.buffer.rstrip()
        self.current_job -= 1
        data = {
            key: value for key, value in vars(self).items() if key not in EXCLUDE_EXPORT_VARIABLES
        }

        FileUtils.write_lines(session_file, str(data), overwrite=True)

    def run(self):
        match_callbacks = (self.match_callback, self.append_traffic_log)
        not_found_callbacks = (self.not_found_callback, self.append_traffic_log)
        error_callbacks = (self.error_callback, self.append_error_log)
        self.requester = Requester(
            max_pool=self.options["threads_count"],
            max_retries=self.options["max_retries"],
            timeout=self.options["timeout"],
            ip=self.options["ip"],
            proxy=self.options["proxy"],
            proxylist=self.options["proxylist"],
            follow_redirects=self.options["follow_redirects"],
            httpmethod=self.options["httpmethod"],
            data=self.options["data"],
            scheme=self.options["scheme"],
            random_agents=self.random_agents,
        )

        while not self.targets.empty():
            try:
                url = self.targets.get()

                try:
                    self.requester.set_target(url if url.endswith('/') else url + '/')
                    self.url = self.requester.url + self.requester.base_path

                    for key, value in self.options["headers"].items():
                        self.requester.set_header(key, value)

                    if self.options["auth"]:
                        self.requester.set_auth(self.options["auth_type"], self.options["auth"])

                    if self.from_export:
                        # Rewrite the output from the last scan
                        print(self.last_output)
                    else:
                        self.output.set_target(self.url)

                    # Test request to check if server is up
                    self.requester.request('')
                    log(self.options["log_file"], "info", f"Test request sent for: {self.url}")

                    self.output.url = self.requester.url
                    self.report = Report(
                        self.requester.host, self.requester.port, self.requester.scheme, self.requester.base_path
                    )
                except (InvalidURLException, RequestException, socket.gaierror) as e:
                    if e == socket.gaierror:
                        e.args[0] = e.args[1] = "Couldn't resolve DNS"

                    self.output.error(e.args[0])
                    self.append_error_log('', e.args[1])
                    raise SkipTargetInterrupt

                if self.directories.empty():
                    self.directories.queue = deque(self.options["scan_subdirs"])
                    self.pass_dirs.update(self.options["scan_subdirs"])

                self.fuzzer = Fuzzer(
                    self.requester,
                    self.dictionary,
                    suffixes=self.options["suffixes"],
                    prefixes=self.options["prefixes"],
                    exclude_response=self.options["exclude_response"],
                    threads=self.options["threads_count"],
                    delay=self.options["delay"],
                    maxrate=self.options["maxrate"],
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
                self.jobs_count -= self.directories.qsize()
                self.directories = Queue()
                self.dictionary.reset()

                if self.report:
                    self.report.completed = True

                continue

        self.output.warning("\nTask Completed")

    def start(self):
        first = True

        while not self.directories.empty():
            gc.collect()

            self.current_directory = self.directories.get()
            self.current_job += 1

            if not self.from_export or not first:
                current_time = time.strftime('%H:%M:%S')
                msg = '\n' if first else ''
                msg += f"[{current_time}] Starting: {self.current_directory}"

                self.output.warning(msg)

            self.fuzzer.set_base_path(self.requester.base_path + self.current_directory)
            self.fuzzer.start()
            self.process()

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
        if self.options["output_format"] not in ("plain", "simple"):
            return f".{self.options['output_format']}"
        else:
            return ".txt"

    # Create report file
    def setup_reports(self):
        output_file = None

        if self.options["output_file"]:
            output_file = FileUtils.get_abs_path(self.options["output_file"])
        elif self.options["autosave_report"]:
            if self.targets.qsize() > 1:
                directory_path = self.setup_batch_reports()
                filename = "BATCH" + self.get_output_extension()
            else:
                parsed = urlparse(self.targets.queue[0])
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

        self.report_manager = ReportManager(self.options["output_format"], output_file)

        if output_file:
            self.output.output_file(output_file)

    # Validate the response by different filters
    def is_valid(self, path, res):
        if res.status in self.options["exclude_status_codes"]:
            return False

        if res.status not in (self.options["include_status_codes"] or range(100, 1000)):
            return False

        if self.blacklists.get(res.status) and path in self.blacklists.get(res.status):
            return False

        if human_size(res.length) in self.options["exclude_sizes"]:
            return False

        if res.length < self.options["minimum_response_size"]:
            return False

        if res.length > self.options["maximum_response_size"] != 0:
            return False

        if any(ex_text in res.content for ex_text in self.options["exclude_texts"]):
            return False

        if self.options["exclude_regex"] and re.search(self.options["exclude_regex"], res.content) is not None:
            return False

        if self.options["exclude_redirect"] and (
            self.options["exclude_redirect"] in res.redirect or re.search(
                self.options["exclude_redirect"], res.redirect
            ) is not None
        ):
            return False

        return True

    # Callback for found paths
    def match_callback(self, path, response):
        if response.status in self.options["skip_on_status"]:
            raise SkipTargetInterrupt(f"Skipped the target due to {response.status} status code")

        if not self.is_valid(path, response):
            return

        added_to_queue = False

        if response.status in self.options["recursion_status_codes"] and any(
            (self.options["recursive"], self.options["deep_recursive"], self.options["force_recursive"])
        ):
            if response.redirect:
                added_to_queue = self.recur_for_redirect(path, response)
            else:
                added_to_queue = self.recur(path)

        if self.options["replay_proxy"]:
            self.requester.request(path, proxy=self.options["replay_proxy"])

        self.output.status_report(response, self.options["full_url"], added_to_queue)
        self.report.add_result(self.current_directory + path, response)
        self.report_manager.update_report(self.report)

    # Callback for invalid paths
    def not_found_callback(self, *args):
        self.output.last_path(
            self.dictionary.index,
            len(self.dictionary),
            self.current_job,
            self.jobs_count,
            self.fuzzer.get_rate(),
        )

    # Callback for errors while fuzzing
    def error_callback(self, path, error_msg):
        if self.options["exit_on_error"]:
            raise QuitInterrupt("Canceled due to an error")

        self.output.add_connection_error()

    # Write request to log file
    def append_traffic_log(self, path, response):
        url = join_path(self.requester.url, response.path)
        msg = f"{self.requester.ip or '0'} {response.status} "
        msg += f"{self.options['httpmethod']} {url}"

        if response.redirect:
            msg += f" - REDIRECT TO: {response.redirect}"
        msg += f" (LENGTH: {response.length})"

        log(self.options["log_file"], "traffic", msg)

    # Write error to log file
    def append_error_log(self, path, error_msg):
        url = self.url + self.current_directory + path
        msg = f"{self.options['httpmethod']} {url}"
        msg += NEW_LINE
        msg += ' ' * 4
        msg += error_msg
        log(self.options["log_file"], "error", msg)

    # Handle CTRL+C
    def handle_pause(self):
        self.output.warning("CTRL+C detected: Pausing threads, please wait...", save=False)
        self.fuzzer.pause()

        # Wait maximum 7 seconds
        for _ in range(20):
            if self.fuzzer.is_stopped():
                break

            time.sleep(0.35)

        while True:
            msg = "[q]uit / [c]ontinue"

            if not self.directories.empty():
                msg += " / [n]ext"

            if not self.targets.empty():
                msg += " / [s]kip target"

            self.output.in_line(msg + ": ")

            option = input()

            if option.lower() == 'q':
                self.output.in_line("[s]ave / [q]uit without saving: ")

                option = input()

                if option.lower() == 'q':
                    self.close("Canceled by the user")
                elif option.lower() == 's':
                    msg = f"Save to file [{DEFAULT_SESSION_FILE}]: "

                    self.output.in_line(msg)

                    session_file = input() or DEFAULT_SESSION_FILE

                    self._export(session_file)
                    self.close(f"Session saved to: {session_file}")
            elif option.lower() == 'c':
                self.fuzzer.resume()
                return
            elif option.lower() == 'n' and not self.directories.empty():
                self.fuzzer.stop()
                return
            elif option.lower() == 's' and not self.targets.empty():
                raise SkipTargetInterrupt

    def is_timed_out(self):
        return time.time() - self.start_time > self.options["maxtime"] != 0

    # Monitor the fuzzing process
    def process(self):
        while True:
            try:
                while not self.fuzzer.wait(0.3):
                    if self.is_timed_out():
                        raise SkipTargetInterrupt("Canceled because the runtime exceeded the maximum set by user")

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
        # Pass if path is in "exclusive directories" or if it has an extension (means it's a file)
        if any(
            path.startswith(directory) for directory in self.options["exclude_subdirs"]
        ) or re.search(EXTENSION_REGEX, path[:-1]):
            return False

        dir = self.current_directory + path

        if dir in self.pass_dirs or dir.count('/') > self.options["recursion_depth"] != 0:
            return False

        self.directories.put(dir)
        self.pass_dirs.add(dir)
        self.jobs_count += 1

        return True

    # Check for recursion
    def recur(self, path):
        added = False
        path = clean_path(path)

        if self.options["force_recursive"] and not path.endswith('/'):
            path += '/'

        if self.options["deep_recursive"]:
            i = 0
            for _ in range(path.count('/')):
                i = path.index('/', i) + 1
                added = self.add_directory(path[:i]) or added
        elif self.options["recursive"] and path.endswith('/'):
            added = self.add_directory(path) or added

        return added

    # Resolve the redirect and add the path to the recursion queue
    # if it's a subdirectory of the current URL
    def recur_for_redirect(self, path, response):
        redirect_path = parse_path(response.redirect)

        if redirect_path == response.path + '/':
            path = redirect_path[len(self.requester.base_path + self.current_directory) + 1:]
            return self.recur(path)

        return False

    def close(self, msg):
        self.fuzzer.stop()
        self.output.error(msg)
        self.report_manager.update_report(self.report)
        exit(0)
