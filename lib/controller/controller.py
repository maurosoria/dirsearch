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

import asyncio
import gc
import os
import shutil
import signal
import sys
import psycopg
import re
import time
import mysql.connector

from urllib.parse import urlparse

from lib.connection.dns import cache_dns
from lib.connection.response import BaseResponse
from lib.core.data import blacklists, options
from lib.core.decorators import locked
from lib.core.dictionary import Dictionary, get_blacklists
from lib.core.exceptions import (
    CannotConnectException,
    FileExistsException,
    InvalidRawRequest,
    InvalidURLException,
    RequestException,
    SkipTargetInterrupt,
    QuitInterrupt,
    UnpicklingError,
)
from lib.core.logger import enable_logging, logger
from lib.core.settings import (
    BANNER,
    DEFAULT_HEADERS,
    DEFAULT_SESSION_FILE,
    EXTENSION_RECOGNITION_REGEX,
    MAX_CONSECUTIVE_REQUEST_ERRORS,
    NEW_LINE,
    STANDARD_PORTS,
    UNKNOWN,
)
from lib.parse.rawrequest import parse_raw
from lib.parse.url import clean_path, parse_path
from lib.report.manager import ReportManager
from lib.utils.common import lstrip_once
from lib.utils.crawl import Crawler
from lib.utils.file import FileUtils
from lib.utils.schemedet import detect_scheme
from lib.view.terminal import interface
from lib.controller.session import SessionStore


class Controller:
    def __init__(self) -> None:
        self._handling_pause = False  # Reentrancy guard for signal handler

        if options["session_file"]:
            self._import(options["session_file"])
            if not hasattr(self, "old_session"):
                self.old_session = True
        else:
            self.setup()
            self.old_session = False

        self.run()

    def _import(self, session_file: str) -> None:
        try:
            session_store = SessionStore(options)
            payload = session_store.load(session_file)
            options.update(session_store.restore_options(payload["options"]))
            if options["log_file"]:
                try:
                    FileUtils.create_dir(FileUtils.parent(options["log_file"]))
                    if not FileUtils.can_write(options["log_file"]):
                        raise Exception
                    enable_logging()
                except Exception:
                    interface.error(
                        f'Couldn\'t create log file at {options["log_file"]}'
                    )
                    sys.exit(1)
            last_output = payload.get("last_output", "")
            session_store.apply_to_controller(self, payload)
        except (OSError, KeyError, TypeError, UnpicklingError):
            interface.error(
                f"{session_file} is not a valid session file or it's in an old format"
            )
            sys.exit(1)
        print(last_output)

    def _export(self, session_file: str) -> None:
        # Save written output
        last_output = interface.buffer.rstrip()
        session_store = SessionStore(options)
        session_store.save(self, session_file, last_output)

    def setup(self) -> None:
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
                sys.exit(1)
        else:
            options["headers"] = {**DEFAULT_HEADERS, **options["headers"]}

        self.dictionary = Dictionary(files=options["wordlists"])
        self.start_time = time.time()
        self.passed_urls: set[str] = set()
        self.directories: list[str] = []
        self.jobs_processed = 0
        self.errors = 0
        self.consecutive_errors = 0

        if options["log_file"]:
            try:
                FileUtils.create_dir(FileUtils.parent(options["log_file"]))
                if not FileUtils.can_write(options["log_file"]):
                    raise Exception

                enable_logging()

            except Exception:
                interface.error(
                    f'Couldn\'t create log file at {options["log_file"]}'
                )
                sys.exit(1)

        interface.header(BANNER)
        interface.config(len(self.dictionary))

        try:
            self.reporter = ReportManager(options["output_formats"])
        except (
            InvalidURLException,
            mysql.connector.Error,
            psycopg.Error,
        ) as e:
            logger.exception(e)
            interface.error(str(e))
            sys.exit(1)

        if options["log_file"]:
            interface.log_file(options["log_file"])

    def run(self) -> None:
        if options["async_mode"]:
            from lib.connection.requester import AsyncRequester as Requester
            from lib.core.fuzzer import AsyncFuzzer as Fuzzer

            try:
                import uvloop
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            except ImportError:
                pass
        else:
            from lib.connection.requester import Requester
            from lib.core.fuzzer import Fuzzer

        # match_callbacks and not_found_callbacks callback values:
        #  - *args[0]: lib.connection.Response() object
        #
        # error_callbacks callback values:
        #  - *args[0]: exception
        match_callbacks = (
            self.match_callback, self.reporter.save, self.reset_consecutive_errors
        )
        not_found_callbacks = (
            self.update_progress_bar, self.reset_consecutive_errors
        )
        error_callbacks = (self.raise_error, self.append_error_log)

        self.requester = Requester()
        if options["async_mode"]:
            self.loop = asyncio.new_event_loop()

        signal.signal(signal.SIGINT, lambda *_: self.handle_pause())
        signal.signal(signal.SIGTERM, lambda *_: self.handle_pause())

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

                self.reporter.prepare(self.url)
                self.start()

            except (
                CannotConnectException,
                FileExistsException,
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
                self.reporter.finish()
                interface.error(e.args[0])
                sys.exit(0)

            finally:
                options["urls"].pop(0)

        interface.warning("\nTask Completed")
        self.reporter.finish()

        if options["session_file"]:
            try:
                if os.path.isdir(options["session_file"]):
                    shutil.rmtree(options["session_file"])
                else:
                    os.remove(options["session_file"])
            except Exception:
                interface.error("Failed to delete old session file, remove it to free some space")

    def start(self) -> None:
        start_time = time.time()

        while self.directories:
            try:
                gc.collect()

                current_directory = self.directories[0]

                if not self.old_session:
                    current_time = time.strftime("%H:%M:%S")
                    msg = f"{NEW_LINE}[{current_time}] Scanning: {current_directory}"

                    interface.warning(msg)

                self.fuzzer.set_base_path(current_directory)
                if options["async_mode"]:
                    # use a future to get exceptions from handle_pause
                    # https://stackoverflow.com/a/64230941
                    self.pause_future = self.loop.create_future()
                    self.loop.run_until_complete(self.start_coroutines(start_time))
                else:
                    self.fuzzer.start()
                    self.process(start_time)

            except (KeyboardInterrupt, asyncio.CancelledError):
                pass

            finally:
                self.dictionary.reset()
                self.directories.pop(0)

                self.jobs_processed += 1
                self.old_session = False

    async def start_coroutines(self, start_time: float) -> None:
        task = self.loop.create_task(self.fuzzer.start())
        timeout = min(
            t for t in [
                options["max_time"] - (time.time() - self.start_time),
                options["target_max_time"] - (time.time() - start_time),
            ] if t > 0
        ) if options["max_time"] or options["target_max_time"] else None

        try:
            await asyncio.wait_for(
                asyncio.wait(
                    [self.pause_future, task],
                    return_when=asyncio.FIRST_COMPLETED,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            if time.time() - self.start_time > options["max_time"] > 0:
                raise QuitInterrupt("Runtime exceeded the maximum set by the user")

            raise SkipTargetInterrupt("Runtime for target exceeded the maximum set by the user")

        if self.pause_future.done():
            task.cancel()
            await self.pause_future  # propagate the exception, if raised

        await task  # propagate the exception, if raised

    def process(self, start_time: float) -> None:
        while True:
            while not self.fuzzer.is_finished():
                now = time.time()
                if now - self.start_time > options["max_time"] > 0:
                    raise QuitInterrupt(
                        "Runtime exceeded the maximum set by the user"
                    )
                if now - start_time > options["target_max_time"] > 0:
                    raise SkipTargetInterrupt(
                        "Runtime for target exceeded the maximum set by the user"
                    )

                time.sleep(0.5)

            break

    def set_target(self, url: str) -> None:
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

        if parsed.scheme not in (UNKNOWN, "https", "http"):
            raise InvalidURLException(f"Unsupported URI scheme: {parsed.scheme}")

        port = parsed.port
        # If no port is specified, set default (80, 443) based on the scheme
        if not port:
            port = STANDARD_PORTS.get(parsed.scheme, None)
        elif not 0 < port < 65536:
            raise InvalidURLException(f"Invalid port number: {port}")

        if options["ip"]:
            cache_dns(parsed.hostname, port, options["ip"])

        try:
            # If no scheme is found, detect it by port number
            scheme = (
                parsed.scheme
                if parsed.scheme != UNKNOWN
                else detect_scheme(parsed.hostname, port)
            )
        except ValueError:
            # If the user neither provides the port nor scheme, guess them based
            # on standard website characteristics
            scheme = detect_scheme(parsed.hostname, 443)
            port = STANDARD_PORTS[scheme]

        self.url = f"{scheme}://{parsed.hostname}"

        if port != STANDARD_PORTS[scheme]:
            self.url += f":{port}"

        self.url += "/"

        self.requester.set_url(self.url)

    def reset_consecutive_errors(self, response: BaseResponse) -> None:
        self.consecutive_errors = 0

    def match_callback(self, response: BaseResponse) -> None:
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
            if options["async_mode"]:
                self.loop.create_task(self.requester.replay_request(response.full_path, proxy=options["replay_proxy"]))
            else:
                self.requester.request(response.full_path, proxy=options["replay_proxy"])

        if options["crawl"]:
            for path in Crawler.crawl(response):
                if not self.dictionary.is_valid(path):
                    continue
                path = lstrip_once(path, self.base_path)
                self.dictionary.add_extra(path)

    def update_progress_bar(self, response: BaseResponse) -> None:
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

    def raise_error(self, exception: RequestException) -> None:
        if options["exit_on_error"]:
            raise QuitInterrupt("Canceled due to an error")

        self.errors += 1
        self.consecutive_errors += 1

        if self.consecutive_errors > MAX_CONSECUTIVE_REQUEST_ERRORS:
            raise SkipTargetInterrupt("Too many request errors")

    def append_error_log(self, exception: RequestException) -> None:
        logger.exception(exception)

    def handle_pause(self) -> None:
        # Force quit on second Ctrl+C if already handling pause
        if self._handling_pause:
            interface.warning("\nForce quit!", do_save=False)
            os._exit(1)

        self._handling_pause = True

        try:
            interface.warning(
                "CTRL+C detected: Pausing threads, please wait...", do_save=False
            )
            if not self.fuzzer.pause():
                interface.warning(
                    "Could not pause all threads (some may be blocked on I/O). "
                    "Press CTRL+C again to force quit.",
                    do_save=False
                )
        except Exception:
            # If pause fails for any reason, still show the menu
            pass

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
                    quitexc = QuitInterrupt(f"Session saved to: {session_file}")
                    if options["async_mode"]:
                        self.pause_future.set_exception(quitexc)
                        break
                    else:
                        raise quitexc
                elif option.lower() == "q":
                    quitexc = QuitInterrupt("Canceled by the user")
                    if options["async_mode"]:
                        self.pause_future.set_exception(quitexc)
                        break
                    else:
                        raise quitexc

            elif option.lower() == "c":
                self._handling_pause = False
                self.fuzzer.play()
                break

            elif option.lower() == "n" and len(self.directories) > 1:
                self.fuzzer.quit()
                break

            elif option.lower() == "s" and len(options["urls"]) > 1:
                skipexc = SkipTargetInterrupt("Target skipped by the user")
                if options["async_mode"]:
                    self.pause_future.set_exception(skipexc)
                    break
                else:
                    raise skipexc

    def add_directory(self, path: str) -> None:
        """Add directory to the recursion queue"""

        # Pass if path is in exclusive directories
        if any(
            path.startswith(dir) or "/" + dir in path
            for dir in options["exclude_subdirs"]
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
    def recur(self, path: str) -> list[str]:
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

    def recur_for_redirect(self, path: str, redirect_path: str) -> list[str]:
        if redirect_path == path + "/":
            return self.recur(redirect_path)

        return []
