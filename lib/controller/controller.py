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
import re
import threading
import time
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Awaitable, TextIO

from urllib.parse import unquote, urlparse

from lib.connection.response import BaseResponse
from lib.core.data import options
from lib.core.decorators import locked
from lib.core.dictionary import Dictionary, get_blacklists
from lib.core.discovery_config import DiscoveryConfig
from lib.core.exceptions import (
    CannotConnectException,
    FileExistsException,
    InvalidRawRequest,
    InvalidURLException,
    RequestException,
    SkipTargetInterrupt,
    QuitInterrupt,
    UnpicklingError,
    WordlistLimitError,
)
from lib.core.execution_config import ExecutionConfig, ScanEngine
from lib.core.filter_config import FilterConfig
from lib.core.request_config import RequestConfig
from lib.core.report_config import ReportConfig
from lib.core.result_config import ResultConfig
from lib.core.log_config import LogConfig
from lib.core.logger import RunLogger
from lib.core.options import (
    validate_numeric_options,
    validate_random_agent_headers,
    validate_regex_options,
)
from lib.core.request_backend import get_native_request_backend_error
from ..core.scan_run_state import ScanRunState
from lib.core.target_config import TargetConfig
from lib.core.target_progress import TargetProgress
from lib.core.terminal_config import TerminalConfig
from lib.core.settings import (
    BANNER,
    DEFAULT_HEADERS,
    DEFAULT_SESSION_FILE,
    EXTENSION_RECOGNITION_REGEX,
    MAX_CONSECUTIVE_REQUEST_ERRORS,
    NATIVE_WORKER_POLL_INTERVAL,
    NATIVE_WORKER_SHUTDOWN_TIMEOUT,
    NEW_LINE,
    SIGINT_FORCE_QUIT_THRESHOLD,
    SIGINT_WINDOW_SECONDS,
    STANDARD_PORTS,
    START_TIME,
    THREADED_WORKER_SHUTDOWN_TIMEOUT,
    UNKNOWN,
)
from lib.core.wordlist_config import WordlistConfig
from lib.core.wordlist_template import generate_backup_paths
from lib.parse.rawrequest import parse_raw
from lib.parse.url import (
    clean_path,
    ensure_trailing_path_slash,
    same_origin_path,
)
from lib.report.manager import ReportManager
from lib.report.response_store import (
    BaseResponseStore,
    ResponseArtifact,
    create_response_stores,
)
from lib.utils.cli import fail
from lib.utils.common import lstrip_once
from lib.utils.crawl import Crawler
from lib.utils.file import FileUtils
from lib.utils.schemedet import detect_scheme
from lib.view.terminal import CLI, create_terminal
from .session import SessionStore
from .session_snapshot import RunCheckpoint, SessionSnapshot
from ..core.task_checkpoint import DictionaryCheckpoint, TaskCheckpoint


class ForceQuitHandler:
    """Strategy for handling force quit on repeated Ctrl+C.

    Different platforms have different signal handling behaviors. This base
    class defines the interface, with subclasses implementing platform-specific
    logic.
    """

    def check_force_quit(self, terminal: CLI) -> bool:
        """Check if force quit should be triggered.

        Returns True if force quit was triggered (program will exit).
        """
        raise NotImplementedError

    def on_pause_start(self) -> None:
        """Called when pause mode is entered."""
        pass

    def on_resume(self) -> None:
        """Called when resuming from pause."""
        pass


class StandardForceQuitHandler(ForceQuitHandler):
    """Force quit handler for standard platforms.

    Immediately exits on any Ctrl+C during pause mode.
    """

    def check_force_quit(self, terminal: CLI) -> bool:
        terminal.warning("\nForce quit!", do_save=False)
        os._exit(1)
        return True  # Unreachable, but satisfies type checker


class PyInstallerLinuxForceQuitHandler(ForceQuitHandler):
    """Force quit handler for PyInstaller Linux builds.

    PyInstaller on Linux has signal handling quirks that require multiple
    rapid Ctrl+C presses to force quit. Uses SIGKILL for reliable termination.
    """

    def __init__(self) -> None:
        self._sigint_count = 0
        self._last_sigint_time = 0.0

    def check_force_quit(self, terminal: CLI) -> bool:
        now = time.monotonic()
        if now - self._last_sigint_time <= SIGINT_WINDOW_SECONDS:
            self._sigint_count += 1
        else:
            self._sigint_count = 1
        self._last_sigint_time = now

        if self._sigint_count >= SIGINT_FORCE_QUIT_THRESHOLD:
            terminal.warning("\nForce quit!", do_save=False)
            os.kill(os.getpid(), signal.SIGKILL)
            os._exit(1)
        return False

    def on_pause_start(self) -> None:
        self._sigint_count = 1
        self._last_sigint_time = time.monotonic()

    def on_resume(self) -> None:
        self._sigint_count = 0


def _create_force_quit_handler() -> ForceQuitHandler:
    """Factory function to create the appropriate force quit handler."""
    is_pyinstaller_linux = (
        getattr(sys, "frozen", False) and sys.platform.startswith("linux")
    )
    if is_pyinstaller_linux:
        return PyInstallerLinuxForceQuitHandler()
    return StandardForceQuitHandler()


def format_session_path(path: str) -> str:
    date_token = START_TIME.split()[0]
    datetime_token = FileUtils.format_datetime_for_path(START_TIME)
    return path.replace("{date}", date_token).replace("{datetime}", datetime_token)


class Controller:
    def __init__(self, *, output: TextIO | None = None) -> None:
        self._terminal_stream = sys.stdout if output is None else output
        # Bootstrap presentation handles errors before input preparation finishes.
        self.interface = create_terminal(
            TerminalConfig.from_options(options), stream=self._terminal_stream
        )
        self.logger = RunLogger()
        self._operation_lock = threading.Lock()
        self._handling_pause = False
        self._force_quit_handler = _create_force_quit_handler()
        self.requester = None
        self.loop = None  # Will be set if async mode is used
        self.reporter = None
        self._reporter_finished = False
        self.response_stores = ()
        self._native_worker = None
        self.run_state = ScanRunState()
        self.target_progress = TargetProgress()
        self.output_history: list[dict[str, Any]] = []

        try:
            if options["session_file"]:
                self.run_state.old_session = True
                self._import(options["session_file"])
            else:
                self.setup()
                self.run_state.old_session = False

            self.run()
        finally:
            try:
                self._close_reporter()
            finally:
                try:
                    self._close_requester()
                finally:
                    try:
                        self._close_response_stores()
                    finally:
                        try:
                            self.interface.close()
                        finally:
                            self.logger.close()

    def _refresh_terminal(self) -> None:
        """Replace bootstrap policy after raw parsing or restored session options.

        No scan output has been emitted yet. Construct the replacement first so
        a creation failure leaves a valid terminal for error reporting/cleanup.
        """
        terminal = create_terminal(
            TerminalConfig.from_options(options), stream=self._terminal_stream
        )
        previous = self.interface
        self.interface = terminal
        previous.close()

    def _prepare_logging(self) -> None:
        """Replace bootstrap logging only after effective options are available."""
        config = LogConfig.from_options(options)
        try:
            if config.file_path:
                FileUtils.create_dir(FileUtils.parent(config.file_path))
                if not FileUtils.can_write(config.file_path):
                    raise OSError(f"Cannot write log file: {config.file_path}")
            logger = RunLogger(config)
        except OSError:
            self.interface.error(f"Couldn't create log file at {config.file_path}")
            sys.exit(1)
        previous = self.logger
        self.logger = logger
        previous.close()

    def _close_reporter(self) -> None:
        reporter = self.reporter
        if reporter is None or getattr(self, "_reporter_finished", False):
            return

        try:
            reporter.finish()
        finally:
            self._reporter_finished = True

    def _close_requester(self) -> None:
        requester = self.requester
        loop = self.loop

        if requester is None:
            if loop is not None:
                loop.close()
            return

        if loop is None:
            requester.close()
            return

        try:
            loop.run_until_complete(requester.close())
        finally:
            loop.close()

    def _import(self, session_file: str) -> None:
        try:
            if os.path.isfile(session_file) and session_file.endswith((".pickle", ".pkl")):
                self.interface.warning(
                    "Pickle session files are no longer supported. "
                    "Please start a new scan to create a JSON session."
                )
                sys.exit(1)
            session_store = SessionStore()
            snapshot = session_store.load(session_file)
            # Keep the explicit session path so resume/overwrite works as expected.
            loaded_session_file = session_file
            options.update(deepcopy(snapshot.options))
            options["urls"] = [task.target for task in snapshot.remaining_tasks]
            options["session_file"] = loaded_session_file
            validate_random_agent_headers(SimpleNamespace(**options))
            validate_numeric_options(SimpleNamespace(**options))
            validate_regex_options(SimpleNamespace(**options))
            self._refresh_terminal()
            self._prepare_logging()
            output_history = snapshot.output_history
            if not output_history:
                legacy_output = snapshot.last_output
                if legacy_output:
                    start_time = snapshot.run.start_time
                    output_history = [
                        {"start_time": start_time, "output": legacy_output}
                    ]
            self.output_history = deepcopy(output_history)
            if output_history:
                last_output = self._format_output_history(output_history)
            else:
                last_output = ""
            self.wordlist_config = WordlistConfig.from_options(options)
            self._restore_session(snapshot, ReportConfig.from_options(options))
            self.result_config = ResultConfig.from_options(options)
            self._prepare_response_stores()
            self._confirm_session_overwrite(session_file)
            self._session_options = deepcopy(options)
        except InvalidURLException as error:
            self.logger.exception(error)
            self.interface.error(str(error))
            sys.exit(1)
        except (OSError, KeyError, TypeError, UnpicklingError):
            self.interface.error(
                f"{session_file} is not a valid session file or it's in an old format"
            )
            sys.exit(1)
        self.interface.new_line(last_output, do_save=False)

    def _restore_session(
        self, snapshot: SessionSnapshot, report_config: ReportConfig
    ) -> None:
        """Rebuild owned runtime objects from already validated session data.

        Storage does not construct resources. Keep their ownership here so the
        normal controller cleanup also covers partial restoration failures.
        """
        progress = snapshot.run
        task = snapshot.task_checkpoint
        self.run_state = ScanRunState(spec.target for spec in snapshot.remaining_tasks)
        self.target_progress = TargetProgress(
            url=task.url, base_path=task.base_path, directories=task.directories,
        )
        self.start_time = progress.start_time
        self.run_state.passed_urls = set(progress.passed_urls)
        self.run_state.jobs_processed = progress.jobs_processed
        self.run_state.errors = progress.errors
        self.run_state.consecutive_errors = progress.consecutive_errors
        self.run_state.old_session = progress.old_session
        self.dictionary = Dictionary(self.wordlist_config)
        self.dictionary.__setstate__(task.dictionary.to_state())
        self.reporter = ReportManager(report_config)

    def _snapshot_session(
        self, session_options: dict[str, Any], last_output: str
    ) -> SessionSnapshot:
        """Capture data at the paused save boundary, without advancing progress.

        Dictionary serialization retains outstanding claims for cross-engine
        resume. History is committed to this controller only after save succeeds.
        """
        dictionary = DictionaryCheckpoint(*self.dictionary.__getstate__())
        history = list(self.output_history)
        if last_output:
            history.append({"start_time": self.start_time, "output": last_output})
        return SessionSnapshot(
            remaining_tasks=self.run_state.snapshot_tasks(),
            run=RunCheckpoint(
                start_time=self.start_time,
                passed_urls=sorted(self.run_state.passed_urls),
                jobs_processed=self.run_state.jobs_processed,
                errors=self.run_state.errors,
                consecutive_errors=self.run_state.consecutive_errors,
                old_session=self.run_state.old_session,
            ),
            task_checkpoint=TaskCheckpoint(
                url=self.target_progress.url,
                base_path=self.target_progress.base_path,
                directories=self.target_progress.directories,
                dictionary=dictionary,
            ),
            options={key: value for key, value in session_options.items() if key != "urls"},
            last_output=last_output,
            output_history=history,
        )

    def _format_output_history(self, output_history: list[dict[str, Any]]) -> str:
        formatted: list[str] = []
        for entry in output_history:
            if not isinstance(entry, dict):
                continue
            output = entry.get("output")
            if not output:
                continue
            start_time = entry.get("start_time")
            if isinstance(start_time, (int, float)):
                start_label = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(start_time)
                )
                formatted.append(f"--- Previous run started: {start_label} ---")
            else:
                formatted.append("--- Previous run ---")
            formatted.append(output.rstrip())
        return "\n".join(formatted).rstrip()

    def _confirm_session_overwrite(self, session_file: str) -> None:
        self.interface.in_line(
            f"Resume session from {session_file}. Overwrite on save? [o]verwrite/[n]ew: "
        )
        choice = input().strip().lower()
        if choice == "n":
            options["session_file"] = None

    def _export(self, session_file: str) -> None:
        # Save written output
        last_output = self.interface.buffer.rstrip()
        session_file = format_session_path(session_file)
        parent_dir = FileUtils.parent(session_file)
        if parent_dir:
            FileUtils.create_dir(parent_dir)

        # A saved session must never advance beyond durable report rows.
        self.reporter.flush()
        # Owned task input and progress are captured together, never reread from
        # process-wide URLs. Storage alone maps task input to version-1 options.
        snapshot = self._snapshot_session(self._session_options, last_output)
        SessionStore().save(snapshot, session_file)
        self.output_history = snapshot.output_history

    def setup(self) -> None:
        if options["raw_file"]:
            try:
                options.update(
                    zip(
                        ["urls", "http_method", "headers", "data"],
                        parse_raw(options["raw_file"]),
                    )
                )
                validate_random_agent_headers(SimpleNamespace(**options))
            except InvalidRawRequest as e:
                self.logger.exception(e)
                fail(e)

            if options["request_backend"] == "native":
                if error := get_native_request_backend_error(SimpleNamespace(**options)):
                    fail(error)
        else:
            options["headers"] = {**DEFAULT_HEADERS, **options["headers"]}

        self._refresh_terminal()
        self.wordlist_config = WordlistConfig.from_options(options)
        try:
            self.dictionary = Dictionary(
                self.wordlist_config, files=options["wordlists"]
            )
        except WordlistLimitError as e:
            self.interface.error(str(e))
            sys.exit(1)
        self.start_time = time.time()
        self.run_state = ScanRunState()
        self.target_progress = TargetProgress()

        self._prepare_logging()

        self.result_config = ResultConfig.from_options(options)
        self._prepare_response_stores()

        self.interface.header(BANNER)
        self.interface.print_config(len(self.dictionary))

        try:
            self.reporter = ReportManager(ReportConfig.from_options(options))
        except InvalidURLException as e:
            self.logger.exception(e)
            self.interface.error(str(e))
            sys.exit(1)

        if options["log_file"]:
            self.interface.log_file(options["log_file"])
        self._session_options = deepcopy(options)

    def run(self) -> None:
        # Resolve only after setup/session restoration, before imports, callbacks
        # or workers can choose an execution model. A restored invalid pair of
        # flags must fail here rather than dispatch through conflicting branches.
        try:
            self.execution_config = ExecutionConfig.from_options(options)
        except ValueError as error:
            fail(error)

        if self.execution_config.engine is ScanEngine.NATIVE:
            from lib.connection.native import NativeRequester as Requester
            from lib.core.fuzzer import NativeFuzzer as Fuzzer
        elif self.execution_config.engine is ScanEngine.ASYNC:
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
        match_callbacks = [self.match_callback, self._report_match_callback()]
        if self.response_stores:
            match_callbacks.append(
                self.save_response_async
                if self.execution_config.engine is ScanEngine.ASYNC
                else self.save_response
            )
        match_callbacks.append(self.reset_consecutive_errors)
        not_found_callbacks = (
            self.update_progress_bar, self.reset_consecutive_errors
        )
        error_callbacks = (self.raise_error, self.append_error_log)

        # setup() has parsed raw requests, or _import() has restored the session.
        # Snapshot once, before any requester or lazy native engine is created.
        self.run_state.prepare_targets(options["urls"])
        self.target_config = TargetConfig.from_options(options)
        # Stores were prepared before run(). Their frozen policy determines
        # body capture even if composition options have changed in between.
        # Keep destination paths out of the transport's configuration.
        self.request_config = replace(
            RequestConfig.from_options(options),
            capture_full_body=self.result_config.capture_full_body,
        )
        self.discovery_config = DiscoveryConfig.from_options(options)
        self.filter_config = FilterConfig.from_options(
            options, blacklists=get_blacklists(self.wordlist_config)
        )
        if self.execution_config.engine is ScanEngine.NATIVE:
            self.requester = Requester(
                self.request_config, filter_config=self.filter_config
            )
        else:
            self.requester = Requester(self.request_config, logger=self.logger)
        if self.execution_config.engine is ScanEngine.ASYNC:
            self.loop = asyncio.new_event_loop()

        signal.signal(signal.SIGINT, lambda *_: self.handle_pause())
        signal.signal(signal.SIGTERM, lambda *_: self.handle_pause())

        while (task := self.run_state.activate_next()) is not None:
            fuzzer_options = {}
            if self.execution_config.engine is ScanEngine.NATIVE:
                fuzzer_options["filtered_chunk_callbacks"] = (
                    self.update_progress_bar_batch,
                    self.reset_consecutive_errors_batch,
                )
            self.fuzzer = Fuzzer(
                self.requester,
                self.dictionary,
                filter_config=self.filter_config,
                discovery_config=self.discovery_config,
                execution_config=self.execution_config,
                match_callbacks=tuple(match_callbacks),
                not_found_callbacks=not_found_callbacks,
                error_callbacks=error_callbacks,
                logger=self.logger,
                **fuzzer_options,
            )

            try:
                self.set_target(task.target)

                if not self.target_progress.directories:
                    for subdir in self.discovery_config.subdirs:
                        self.add_directory(self.target_progress.base_path + subdir)

                if not self.run_state.old_session:
                    self.interface.target(self.target_progress.url)

                self.reporter.prepare(self.target_progress.url)
                self.crawl_target()
                self.start()

            except (
                CannotConnectException,
                FileExistsException,
                InvalidURLException,
                RequestException,
                SkipTargetInterrupt,
                KeyboardInterrupt,
            ) as e:
                self.target_progress.directories.clear()
                self.dictionary.reset()

                if e.args:
                    self.interface.error(str(e))

            except QuitInterrupt as e:
                self._close_reporter()
                self.interface.error(e.args[0])
                sys.exit(0)

            finally:
                self.run_state.finish_active()

        self.interface.warning("\nTask Completed")
        self._close_reporter()

        if options["session_file"]:
            try:
                SessionStore().delete(options["session_file"])
            except OSError:
                self.interface.error("Failed to delete old session file, remove it to free some space")

    def _report_match_callback(self):
        if (
            self.reporter.reports
            and self.execution_config.engine is ScanEngine.ASYNC
        ):
            return self.reporter.save_async
        return self.reporter.save

    def start(self) -> None:
        start_time = time.time()

        while self.target_progress.directories:
            try:
                gc.collect()

                current_directory = self.target_progress.directories[0]

                if not self.run_state.old_session:
                    current_time = time.strftime("%H:%M:%S")
                    msg = f"{NEW_LINE}[{current_time}] Scanning: {current_directory}"

                    self.interface.warning(msg)

                self.fuzzer.set_base_path(current_directory)
                if self.execution_config.engine is ScanEngine.ASYNC:
                    # use a future to get exceptions from handle_pause
                    # https://stackoverflow.com/a/64230941
                    self.pause_future = self.loop.create_future()
                    self.loop.run_until_complete(self.start_coroutines(start_time))
                elif self.execution_config.engine is ScanEngine.NATIVE:
                    self.start_native_fuzzer(start_time)
                else:
                    self.fuzzer.start()
                    self.process(start_time)

            except (KeyboardInterrupt, asyncio.CancelledError):
                pass

            finally:
                if (
                    self.execution_config.engine is ScanEngine.THREADED
                    and not self.fuzzer.stop(THREADED_WORKER_SHUTDOWN_TIMEOUT)
                ):
                    raise QuitInterrupt("Threaded scan did not stop safely")

                if (
                    self._native_worker is not None
                    and self._native_worker.is_alive()
                ):
                    raise QuitInterrupt("Native scan did not stop safely")

                self.dictionary.reset()
                self.target_progress.directories.pop(0)

                self.run_state.jobs_processed += 1
                self.run_state.old_session = False

    def get_time_limit(
        self, start_time: float
    ) -> tuple[float | None, Exception | None]:
        now = time.time()
        time_limits = []

        if self.execution_config.max_time > 0:
            time_limits.append(
                (
                    self.execution_config.max_time - (now - self.start_time),
                    QuitInterrupt("Runtime exceeded the maximum set by the user"),
                )
            )
        if self.execution_config.target_max_time > 0:
            time_limits.append(
                (
                    self.execution_config.target_max_time - (now - start_time),
                    SkipTargetInterrupt(
                        "Runtime for target exceeded the maximum set by the user"
                    ),
                )
            )

        for remaining, limit_error in time_limits:
            if remaining <= 0:
                raise limit_error

        if time_limits:
            return min(time_limits, key=lambda limit: limit[0])

        return None, None

    def start_native_fuzzer(self, start_time: float) -> None:
        timeout, timeout_error = self.get_time_limit(start_time)
        deadline_reached = threading.Event()
        worker_errors = []

        def run_fuzzer() -> None:
            try:
                self.fuzzer.start()
            except BaseException as error:
                worker_errors.append(error)

        def stop_at_deadline() -> None:
            deadline_reached.set()
            self.fuzzer.quit()

        # Keep the blocking native scan off the signal-handling thread.
        worker = threading.Thread(target=run_fuzzer, name="dirsearch-native")
        worker.daemon = True
        self._native_worker = worker
        timer = None
        pending_error = None
        try:
            self.fuzzer.prepare_start()
            worker.start()

            if timeout is not None:
                timer = threading.Timer(timeout, stop_at_deadline)
                timer.daemon = True
                timer.start()

            while worker.is_alive() and not deadline_reached.is_set():
                worker.join(timeout=NATIVE_WORKER_POLL_INTERVAL)
        except BaseException as error:
            pending_error = error
            if worker.is_alive():
                self.fuzzer.quit()
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()

        if worker.is_alive():
            worker.join(timeout=NATIVE_WORKER_SHUTDOWN_TIMEOUT)
        if worker.is_alive():
            raise QuitInterrupt("Native scan did not stop safely")

        self._native_worker = None

        if pending_error is not None:
            raise pending_error

        if worker_errors:
            raise worker_errors[0]

        if deadline_reached.is_set():
            raise timeout_error

        if timeout is not None:
            # The scan may finish after the deadline before the timer callback
            # gets scheduled. Recheck here so a late completion cannot win.
            self.get_time_limit(start_time)

    async def start_coroutines(self, start_time: float) -> None:
        timeout, timeout_error = self.get_time_limit(start_time)

        task = self.loop.create_task(self.fuzzer.start())

        try:
            try:
                await asyncio.wait_for(
                    asyncio.wait(
                        [self.pause_future, task],
                        return_when=asyncio.FIRST_COMPLETED,
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                if timeout_error is None:
                    raise
                raise timeout_error

            if self.pause_future.done():
                task.cancel()
                await self.pause_future  # propagate the exception, if raised

            await task  # propagate the exception, if raised
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def process(self, start_time: float) -> None:
        while True:
            while not self.fuzzer.is_finished():
                now = time.time()
                if now - self.start_time > self.execution_config.max_time > 0:
                    raise QuitInterrupt(
                        "Runtime exceeded the maximum set by the user"
                    )
                if now - start_time > self.execution_config.target_max_time > 0:
                    raise SkipTargetInterrupt(
                        "Runtime for target exceeded the maximum set by the user"
                    )

                time.sleep(0.5)

            break

    def set_target(self, url: str) -> None:
        target_config = self.target_config
        # If no scheme specified, unset it first
        if "://" not in url:
            url = f'{target_config.default_scheme or UNKNOWN}://{url}'
        url = ensure_trailing_path_slash(url)

        parsed = urlparse(url)
        if parsed.scheme == UNKNOWN and target_config.proxy_configured:
            raise InvalidURLException(
                "Cannot auto-detect the scheme when using a proxy or Tor. "
                "Specify http:// or https:// in the target, or use --scheme"
            )
        self.target_progress.base_path = lstrip_once(parsed.path, "/")

        # Parse target-scoped credentials without changing requester state until
        # the target has been validated.
        credential = None
        if parsed.username is not None:
            credential = unquote(parsed.username)
            if parsed.password is not None:
                credential += f":{unquote(parsed.password)}"

        if parsed.scheme not in (UNKNOWN, "https", "http"):
            raise InvalidURLException(f"Unsupported URI scheme: {parsed.scheme}")

        try:
            port = parsed.port
        except ValueError as error:
            raise InvalidURLException(
                f"Invalid port in target URL: {error}"
            ) from error
        # If no port is specified, set default (80, 443) based on the scheme
        if not port:
            port = STANDARD_PORTS.get(parsed.scheme, None)
        elif not 0 < port < 65536:
            raise InvalidURLException(f"Invalid port number: {port}")

        try:
            # If no scheme is found, detect it by port number
            scheme = (
                parsed.scheme
                if parsed.scheme != UNKNOWN
                else detect_scheme(
                    parsed.hostname,
                    port,
                    connect_host=target_config.connect_host,
                )
            )
        except ValueError:
            # If the user neither provides the port nor scheme, guess them based
            # on standard website characteristics
            scheme = detect_scheme(
                parsed.hostname,
                443,
                connect_host=target_config.connect_host,
            )
            port = STANDARD_PORTS[scheme]

        if target_config.connect_host:
            self.requester.set_ip(parsed.hostname, port, target_config.connect_host)

        hostname = parsed.hostname
        url_hostname = f"[{hostname}]" if hostname and ":" in hostname else hostname
        self.target_progress.url = f"{scheme}://{url_hostname}"

        if port != STANDARD_PORTS[scheme]:
            self.target_progress.url += f":{port}"

        self.target_progress.url += "/"

        self.requester.reset_auth()
        if credential is not None:
            self.requester.set_auth("basic", credential)
        self.requester.set_url(self.target_progress.url)
        self.requester.set_query(parsed.query)

    def crawl_target(self) -> None:
        if not self.discovery_config.crawl:
            return

        try:
            if self.execution_config.engine is ScanEngine.ASYNC:
                response = self.loop.run_until_complete(
                    self.requester.request(self.target_progress.base_path)
                )
            else:
                response = self.requester.request(self.target_progress.base_path)
        except RequestException as error:
            self.raise_error(error)
            self.append_error_log(error)
            return

        self.add_crawled_paths(response)

    def add_crawled_paths(self, response: BaseResponse) -> None:
        for path in Crawler.crawl(response):
            path = lstrip_once(path, self.target_progress.base_path)
            if not self._is_excluded_subdir(path):
                self.dictionary.add_extra(path)

    def reset_consecutive_errors(self, response: BaseResponse) -> None:
        self.run_state.consecutive_errors = 0

    def reset_consecutive_errors_batch(self, _count: int) -> None:
        self.run_state.consecutive_errors = 0

    def _prepare_response_stores(self) -> None:
        self.response_stores = ()
        try:
            self.response_stores = create_response_stores(
                self.result_config.response_directory,
                self.result_config.response_jsonl_file,
            )
        except (OSError, ValueError) as error:
            self.logger.exception(error)
            self.interface.error(
                f"Couldn't prepare response storage: {error}"
            )
            sys.exit(1)

    def save_response(self, response: BaseResponse) -> None:
        artifact = ResponseArtifact.from_response(response)
        for store in self.response_stores:
            try:
                store.save(artifact)
            except (OSError, ValueError) as error:
                self._report_response_store_error(store, artifact, error)

    async def save_response_async(self, response: BaseResponse) -> None:
        artifact = ResponseArtifact.from_response(response)
        await asyncio.gather(
            *(
                self._save_response_to_store_async(store, artifact)
                for store in self.response_stores
            )
        )

    async def _save_response_to_store_async(
        self,
        store: BaseResponseStore,
        artifact: ResponseArtifact,
    ) -> None:
        try:
            await store.save_async(artifact)
        except (OSError, ValueError) as error:
            self._report_response_store_error(store, artifact, error)

    def _report_response_store_error(
        self,
        store: BaseResponseStore,
        artifact: ResponseArtifact,
        error: OSError | ValueError,
    ) -> None:
        self.logger.exception(error)
        self.interface.error(
            f"Couldn't save response for {artifact.url} to "
            f"{store.name} store at {store.destination}: {error}"
        )

    def _close_response_stores(self) -> None:
        for store in self.response_stores:
            try:
                store.close()
            except OSError as error:
                self.logger.exception(error)
                self.interface.error(
                    f"Couldn't close {store.name} response store at "
                    f"{store.destination}: {error}"
                )

    def match_callback(
        self, response: BaseResponse
    ) -> Awaitable[BaseResponse] | None:
        discovery = self.discovery_config
        replay = None

        if response.status in self.execution_config.skip_on_status:
            raise SkipTargetInterrupt(
                f"Skipped the target due to {response.status} status code"
            )

        self.interface.status_report(response, self.result_config.full_url)

        if response.status in discovery.recursion_status_codes and any(
            (
                discovery.recursive,
                discovery.deep_recursive,
                discovery.force_recursive,
            )
        ):
            if response.redirect:
                new_path = same_origin_path(response.url, response.redirect)
                added_to_queue = (
                    self.recur_for_redirect(response.path, clean_path(new_path))
                    if new_path is not None
                    else []
                )
            elif len(response.history):
                final_path = same_origin_path(response.url, response.final_url)
                added_to_queue = (
                    self.recur_for_redirect(
                        response.path,
                        clean_path(final_path),
                    )
                    if final_path is not None
                    else []
                )
            else:
                added_to_queue = self.recur(response.path)

            if added_to_queue:
                self.interface.new_directories(added_to_queue)

        if self.result_config.replay_proxy:
            # Replay the request with new proxy
            if self.execution_config.engine is ScanEngine.ASYNC:
                # AsyncFuzzer awaits callback results, so replay remains inside
                # the scan lifecycle and receives cancellation with its worker.
                replay = self.requester.replay_request(
                    response.full_path,
                    proxy=self.result_config.replay_proxy,
                )
            else:
                self.requester.request(
                    response.full_path,
                    proxy=self.result_config.replay_proxy,
                )

        if discovery.crawl:
            self.add_crawled_paths(response)

        if discovery.find_backup:
            path = lstrip_once(response.path, self.target_progress.base_path)
            for backup_path in generate_backup_paths(path):
                self.dictionary.add_extra(backup_path)

        return replay

    def update_progress_bar(self, response: BaseResponse | None) -> None:
        jobs_count = (
            # Jobs left for unscanned targets
            len(self.discovery_config.subdirs) * self.run_state.pending_count
            # Jobs left for the current target
            + len(self.target_progress.directories)
            # Finished jobs
            + self.run_state.jobs_processed
        )

        self.interface.last_path(
            self.dictionary.index,
            len(self.dictionary),
            self.run_state.jobs_processed + 1,
            jobs_count,
            self.requester.rate,
            self.run_state.errors,
        )

    def update_progress_bar_batch(self, _count: int) -> None:
        self.update_progress_bar(None)

    def raise_error(self, exception: RequestException) -> None:
        if self.execution_config.exit_on_error:
            raise QuitInterrupt("Canceled due to an error")

        self.run_state.errors += 1
        self.run_state.consecutive_errors += 1

        if self.run_state.consecutive_errors > MAX_CONSECUTIVE_REQUEST_ERRORS:
            raise SkipTargetInterrupt("Too many request errors")

    def append_error_log(self, exception: RequestException) -> None:
        self.logger.exception(exception)

    def _force_exit(self) -> None:
        """Force process termination, stopping asyncio loop if running."""
        self.interface.warning("\nForce quit!", do_save=False)
        # Stop asyncio loop first if running (prevents hang in async mode)
        if self.loop and self.loop.is_running():
            try:
                self.loop.stop()
            except Exception:
                pass
        os._exit(1)

    def _reset_pause_state(self) -> None:
        self._handling_pause = False
        self._force_quit_handler.on_resume()

    def handle_pause(self) -> None:
        """Handle SIGINT (Ctrl+C) by pausing execution and showing options."""
        if self._handling_pause:
            self._force_quit_handler.check_force_quit(self.interface)
            return

        self._handling_pause = True
        self._force_quit_handler.on_pause_start()

        try:
            try:
                self.interface.warning(
                    "CTRL+C detected: Pausing threads, please wait...", do_save=False
                )
                if not self.fuzzer.pause():
                    self.interface.warning(
                        "Could not pause all threads (some may be blocked on I/O). "
                        "Press CTRL+C again to force quit.",
                        do_save=False
                    )
            except Exception:
                # If pause fails for any reason, still show the menu
                pass

            while True:
                msg = "[q]uit / [c]ontinue"

                if len(self.target_progress.directories) > 1:
                    msg += " / [n]ext"

                if self.run_state.pending_count:
                    msg += " / [s]kip target"

                self.interface.in_line(msg + ": ")

                option = input()

                if option.lower() == "q":
                    self.interface.in_line("[s]ave / [q]uit without saving: ")

                    option = input()

                    if option.lower() == "s":
                        default_session_path = format_session_path(
                            options["session_file"] or DEFAULT_SESSION_FILE
                        )
                        msg = f"Save to file [{default_session_path}]: "

                        self.interface.in_line(msg)

                        session_file = format_session_path(input() or default_session_path)

                        self._export(session_file)
                        quitexc = QuitInterrupt(f"Session saved to: {session_file}")
                        if self.execution_config.engine is ScanEngine.ASYNC:
                            self.pause_future.set_exception(quitexc)
                            break
                        else:
                            raise quitexc
                    elif option.lower() == "q":
                        quitexc = QuitInterrupt("Canceled by the user")
                        if self.execution_config.engine is ScanEngine.ASYNC:
                            self.pause_future.set_exception(quitexc)
                            break
                        else:
                            raise quitexc

                elif option.lower() == "c":
                    self._reset_pause_state()
                    self.fuzzer.play()
                    break

                elif option.lower() == "n" and len(self.target_progress.directories) > 1:
                    self._reset_pause_state()
                    self.fuzzer.quit()
                    break

                elif option.lower() == "s" and self.run_state.pending_count:
                    self._reset_pause_state()
                    skipexc = SkipTargetInterrupt("Target skipped by the user")
                    if self.execution_config.engine is ScanEngine.ASYNC:
                        self.pause_future.set_exception(skipexc)
                        break
                    else:
                        raise skipexc
        finally:
            pass

    def add_directory(self, path: str) -> None:
        """Add directory to the recursion queue"""

        # Pass if path is in exclusive directories
        if self._is_excluded_subdir(path):
            return

        url = self.target_progress.url + path
        depth_limit = self.discovery_config.recursion_depth

        if (
            path.count("/") - self.target_progress.base_path.count("/") > depth_limit > 0
            or url in self.run_state.passed_urls
        ):
            return

        self.target_progress.directories.append(path)
        self.run_state.passed_urls.add(url)

    def _is_excluded_subdir(self, path: str) -> bool:
        resource_path = path.split("?", 1)[0].lstrip("/")
        return any(
            resource_path.startswith(subdir) or f"/{subdir}" in resource_path
            for subdir in self.discovery_config.exclude_subdirs
        )

    @locked
    def recur(self, path: str) -> list[str]:
        dirs_count = len(self.target_progress.directories)
        path = clean_path(path)

        if self.discovery_config.force_recursive and not path.endswith("/"):
            path += "/"

        if self.discovery_config.deep_recursive:
            i = 0
            for _ in range(path.count("/")):
                i = path.index("/", i) + 1
                self.add_directory(path[:i])
        elif (
            self.discovery_config.recursive
            and path.endswith("/")
            and re.search(EXTENSION_RECOGNITION_REGEX, path[:-1]) is None
        ):
            self.add_directory(path)

        # Return newly added directories
        return self.target_progress.directories[dirs_count:]

    def recur_for_redirect(self, path: str, redirect_path: str) -> list[str]:
        if redirect_path == path + "/":
            return self.recur(redirect_path)

        return []
