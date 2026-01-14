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
import signal
import sys
import psycopg
import re
import time
import mysql.connector
from typing import Optional

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
)
from lib.core.logger import enable_logging, logger
from lib.core.session_db import (
    SessionDatabase,
    SessionStatus,
    TargetStatus,
    DirectoryStatus,
)
from lib.core.settings import (
    BANNER,
    DEFAULT_HEADERS,
    DEFAULT_SESSION_DB,
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


class Controller:
    def __init__(self) -> None:
        self._handling_pause = False  # Reentrancy guard for signal handler
        self._session_db: Optional[SessionDatabase] = None
        self._session_id: Optional[int] = None
        self._current_target_id: Optional[int] = None
        self._current_directory_id: Optional[int] = None

        if options["session_file"]:
            self._import_session(options["session_file"])
            self.old_session = True
        elif options["resume_session"]:
            self._resume_session(options["resume_session"])
            self.old_session = True
        elif options["list_sessions"]:
            self._list_sessions()
            sys.exit(0)
        elif options.get("delete_session"):
            self._delete_session(options["delete_session"])
            sys.exit(0)
        elif options.get("clean_sessions"):
            self._clean_sessions()
            sys.exit(0)
        else:
            self.setup()
            self.old_session = False

        self.run()

    def _get_session_db(self) -> SessionDatabase:
        """Get or create session database connection."""
        if self._session_db is None:
            db_path = options.get("session_db") or DEFAULT_SESSION_DB
            self._session_db = SessionDatabase(db_path)
        return self._session_db

    def _list_sessions(self) -> None:
        """List all saved sessions."""
        db = self._get_session_db()
        sessions = db.list_sessions()

        if not sessions:
            interface.warning("No saved sessions found.")
            return

        interface.header(BANNER)
        interface.warning("Saved sessions:\n")

        for session in sessions:
            status_color = {
                SessionStatus.PENDING: "",
                SessionStatus.RUNNING: "[RUNNING] ",
                SessionStatus.PAUSED: "[PAUSED] ",
                SessionStatus.COMPLETED: "[DONE] ",
                SessionStatus.FAILED: "[FAILED] ",
            }.get(session.status, "")

            created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session.created_at))
            urls = session.options.get("urls", [])
            url_preview = urls[0] if urls else "N/A"
            if len(urls) > 1:
                url_preview += f" (+{len(urls) - 1} more)"

            interface.warning(
                f"  ID: {session.id} | {status_color}{created} | {url_preview}"
            )

    def _delete_session(self, session_id: int) -> None:
        """Delete a session by ID."""
        db = self._get_session_db()
        session = db.get_session(session_id)

        if session is None:
            interface.error(f"Session {session_id} not found")
            return

        db.delete_session(session_id)
        interface.warning(f"Session {session_id} deleted successfully")

    def _clean_sessions(self) -> None:
        """Remove all completed sessions from the database."""
        db = self._get_session_db()
        sessions = db.list_sessions(SessionStatus.COMPLETED)

        if not sessions:
            interface.warning("No completed sessions to clean")
            return

        count = 0
        for session in sessions:
            db.delete_session(session.id)
            count += 1

        interface.warning(f"Removed {count} completed session(s)")
        db.vacuum()

    def _resume_session(self, session_id: int) -> None:
        """Resume a session from SQLite database."""
        db = self._get_session_db()
        session = db.get_session(session_id)

        if session is None:
            interface.error(f"Session {session_id} not found")
            sys.exit(1)

        if session.status == SessionStatus.COMPLETED:
            interface.error(f"Session {session_id} is already completed")
            sys.exit(1)

        # Restore options
        options.update(session.options)
        self._session_id = session_id

        # Print saved terminal buffer
        if session.terminal_buffer:
            print(session.terminal_buffer)

        # Setup with restored state
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
        self.errors = 0
        self.consecutive_errors = 0
        self.jobs_processed = 0

        # Restore passed URLs
        self.passed_urls = db.get_passed_urls(session_id)

        # Restore directories from database
        self.directories: list[str] = []

        # Get pending targets
        targets = db.get_targets(session_id)
        pending_urls = []
        for target_id, url, status in targets:
            if status in (TargetStatus.PENDING, TargetStatus.SCANNING):
                pending_urls.append(url)
                # Get pending directories for this target
                dirs = db.get_pending_directories(target_id)
                for dir_id, path in dirs:
                    if path not in self.directories:
                        self.directories.append(path)
                # Store first pending target
                if self._current_target_id is None:
                    self._current_target_id = target_id

        # Update URLs to only include pending
        if pending_urls:
            options["urls"] = pending_urls

        # Restore dictionary state
        dict_state = db.get_dictionary_state(session_id)
        if dict_state:
            main_index, extra_index, extra_items = dict_state
            self.dictionary.set_state(main_index, extra_index, extra_items)

        # Update session status
        db.update_session_status(session_id, SessionStatus.RUNNING)

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
        interface.warning(f"Resuming session {session_id}")
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

    def _import_session(self, session_file: str) -> None:
        """Import session - supports both SQLite (.db) and legacy pickle (.pickle) formats."""
        if session_file.endswith(".db"):
            # SQLite format - find latest paused session
            db = SessionDatabase(session_file)
            sessions = db.list_sessions(SessionStatus.PAUSED)
            if not sessions:
                sessions = db.list_sessions(SessionStatus.RUNNING)
            if not sessions:
                interface.error(f"No resumable sessions found in {session_file}")
                sys.exit(1)
            self._session_db = db
            self._resume_session(sessions[0].id)
        else:
            # Legacy pickle format - convert to SQLite
            interface.warning(
                f"Legacy pickle format detected. Converting to SQLite..."
            )
            self._import_legacy_pickle(session_file)

    def _import_legacy_pickle(self, session_file: str) -> None:
        """Import legacy pickle session and convert to SQLite."""
        import pickle

        try:
            with open(session_file, "rb") as fd:
                dict_, last_output, opt = pickle.load(fd)
                options.update(opt)
        except Exception:
            interface.error(
                f"{session_file} is not a valid session file or it's in an old format"
            )
            sys.exit(1)

        # Setup from pickle data
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

        # Restore state from pickle
        self.dictionary = dict_.get("dictionary", Dictionary(files=options["wordlists"]))
        self.start_time = dict_.get("start_time", time.time())
        self.passed_urls = dict_.get("passed_urls", set())
        self.directories = dict_.get("directories", [])
        self.jobs_processed = dict_.get("jobs_processed", 0)
        self.errors = dict_.get("errors", 0)
        self.consecutive_errors = dict_.get("consecutive_errors", 0)

        # Print saved output
        if last_output:
            print(last_output)

        # Create SQLite session for future saves
        db = self._get_session_db()
        self._session_id = db.create_session(dict(options))

        # Save URLs and state to SQLite
        db.add_targets(self._session_id, options["urls"])
        db.add_passed_urls_bulk(self._session_id, self.passed_urls)

        if options["log_file"]:
            try:
                FileUtils.create_dir(FileUtils.parent(options["log_file"]))
                if not FileUtils.can_write(options["log_file"]):
                    raise Exception
                enable_logging()
            except Exception:
                interface.error(f'Couldn\'t create log file at {options["log_file"]}')
                sys.exit(1)

        interface.header(BANNER)
        interface.warning("Converted legacy session to SQLite format")
        interface.config(len(self.dictionary))

        try:
            self.reporter = ReportManager(options["output_formats"])
        except (InvalidURLException, mysql.connector.Error, psycopg.Error) as e:
            logger.exception(e)
            interface.error(str(e))
            sys.exit(1)

        if options["log_file"]:
            interface.log_file(options["log_file"])

    def _export_session(self, session_file: str) -> None:
        """Export session to SQLite database."""
        # Determine if we should use the provided file or session DB
        if session_file.endswith(".db"):
            db_path = session_file
        else:
            # Convert .pickle path to .db
            if session_file.endswith(".pickle"):
                db_path = session_file[:-7] + ".db"
            else:
                db_path = session_file + ".db"

        db = SessionDatabase(db_path)

        # Create or update session
        if self._session_id is None:
            self._session_id = db.create_session(dict(options))

        session_id = self._session_id

        # Save terminal buffer
        db.update_session_buffer(session_id, interface.buffer.rstrip())

        # Save targets
        db.add_targets(session_id, options["urls"])

        # Save current target and directories
        targets = db.get_targets(session_id)
        for target_id, url, _ in targets:
            if url == options["urls"][0] if options["urls"] else None:
                self._current_target_id = target_id
                db.update_target_status(target_id, TargetStatus.SCANNING)

                # Save directories
                for idx, path in enumerate(self.directories):
                    dir_id = db.add_directory(target_id, path, idx)
                    if idx == 0:
                        self._current_directory_id = dir_id
                        db.update_directory_status(dir_id, DirectoryStatus.SCANNING)
                break

        # Save dictionary state
        db.save_dictionary_state(
            session_id,
            self.dictionary.index,
            self.dictionary.extra_index,
            self.dictionary.extra_items,
            self._current_directory_id,
        )

        # Save thread checkpoints
        for thread_id, index in self.dictionary.get_thread_indices().items():
            db.save_thread_checkpoint(
                session_id, thread_id, index, self._current_directory_id
            )

        # Save passed URLs
        db.add_passed_urls_bulk(session_id, self.passed_urls)

        # Update session status
        db.update_session_status(session_id, SessionStatus.PAUSED)

        self._session_db = db
        return db_path

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

        # Setup checkpoint callback for dictionary (patator-style)
        self.dictionary.set_checkpoint_callback(
            self._on_checkpoint, interval=500
        )

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

    def _on_checkpoint(self, thread_id: int, index: int) -> None:
        """Callback for dictionary checkpoint - saves thread progress to SQLite."""
        if self._session_id is None or self._session_db is None:
            return

        try:
            self._session_db.save_thread_checkpoint(
                self._session_id,
                thread_id,
                index,
                self._current_directory_id,
            )
        except Exception:
            # Don't fail scanning on checkpoint errors
            pass

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

        # Mark session as completed and cleanup
        if self._session_id and self._session_db:
            self._session_db.update_session_status(
                self._session_id, SessionStatus.COMPLETED
            )
            self._session_db.close()

        # Remove legacy pickle session file if exists
        if options.get("session_file") and os.path.exists(options["session_file"]):
            try:
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
                    default_session = options.get("session_db") or DEFAULT_SESSION_DB
                    msg = f"Save to file [{default_session}]: "

                    interface.in_line(msg)

                    session_file = input() or default_session

                    saved_path = self._export_session(session_file)
                    quitexc = QuitInterrupt(
                        f"Session {self._session_id} saved to: {saved_path}"
                    )
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
