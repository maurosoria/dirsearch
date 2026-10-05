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
import inspect
import re
import threading
import time
from typing import Any, Callable, Generator

from lib.connection.native import NativeHTTPBackend, NativeRequester, NativeScanChunk
from lib.connection.requester import AsyncRequester, BaseRequester, Requester
from lib.connection.response import BaseResponse
from lib.core.dictionary import Dictionary
from lib.core.discovery_config import DiscoveryConfig
from lib.core.exceptions import RequestException
from lib.core.execution_config import ExecutionConfig
from lib.core.filter_config import FilterConfig
from lib.core.filter_state import FilterState
from lib.core.filters import matches_numeric_ranges, matches_time_filters
from lib.core.logger import RunLogger
from lib.core.scanner import AsyncScanner, BaseScanner, Scanner
from lib.core.settings import (
    DEFAULT_TEST_PREFIXES,
    DEFAULT_TEST_SUFFIXES,
    NATIVE_PAUSE_TIMEOUT,
    WILDCARD_TEST_POINT_MARKER,
)
from lib.core.wordlist_backend import NativeWordlistChunk
from lib.parse.url import clean_path
from lib.utils.common import lstrip_once


AUTO_CALIBRATION_DUPLICATE_THRESHOLD = 8
AUTO_CALIBRATION_FORCED_THRESHOLD = 3
AUTO_CALIBRATION_MIN_CONTENT_LENGTH = 32


def response_headers_text(resp: BaseResponse) -> str:
    return "\n".join(f"{name}: {value}" for name, value in resp.headers.items())


def matches_header_text(resp: BaseResponse, patterns: tuple[str, ...]) -> bool:
    headers = response_headers_text(resp).lower()
    return any(pattern.lower() in headers for pattern in patterns)


def matches_header_regex(resp: BaseResponse, pattern: str) -> bool:
    return bool(re.search(pattern, response_headers_text(resp), re.IGNORECASE))


class BaseFuzzer:
    def __init__(
        self,
        requester: BaseRequester,
        dictionary: Dictionary,
        *,
        filter_config: FilterConfig,
        discovery_config: DiscoveryConfig,
        execution_config: ExecutionConfig,
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
        logger: RunLogger | None = None,
    ) -> None:
        self.logger = logger if logger is not None else RunLogger()
        self._requester = requester
        self._dictionary = dictionary
        self._base_path: str = ""
        self.filter_config = filter_config
        self.discovery_config = discovery_config
        self.execution_config = execution_config
        self.filter_state = FilterState()
        self.match_callbacks = match_callbacks
        self.not_found_callbacks = not_found_callbacks
        self.error_callbacks = error_callbacks

    def set_base_path(self, path: str) -> None:
        self._base_path = path

    def get_scanners_for(self, path: str) -> Generator[BaseScanner, None, None]:
        scanners = self.filter_state.scanners
        # Clean the path, so can check for extensions/suffixes
        path = clean_path(path)

        for prefix in scanners["prefixes"]:
            if path.startswith(prefix):
                yield scanners["prefixes"][prefix]

        for suffix in scanners["suffixes"]:
            if path.endswith(suffix):
                yield scanners["suffixes"][suffix]

        for scanner in scanners["default"].values():
            yield scanner

    def is_excluded(self, resp: BaseResponse) -> bool:
        """Validate the response by different filters"""
        config = self.filter_config

        if resp.status in config.exclude_status_codes:
            return True

        if (
            config.include_status_codes
            and resp.status not in config.include_status_codes
        ):
            return True

        if (
            resp.status in config.blacklists
            and any(
                resp.path.endswith(lstrip_once(suffix, "/"))
                for suffix in config.blacklists[resp.status]
            )
        ):
            return True

        if resp.length in config.exclude_sizes:
            return True

        if resp.length < config.minimum_response_size:
            return True

        if resp.length > config.maximum_response_size > 0:
            return True

        if any(text in resp.content for text in config.exclude_texts):
            return True

        if config.exclude_regex and re.search(config.exclude_regex, resp.content):
            return True

        if (
            config.exclude_redirect
            and (
                config.exclude_redirect in resp.redirect
                or re.search(config.exclude_redirect, resp.redirect)
            )
        ):
            return True

        if not self.matches_advanced_matchers(resp):
            return True

        if self.matches_advanced_filters(resp):
            return True

        if self.is_auto_calibrated(resp):
            return True

        return False

    def matches_advanced_matchers(self, resp: BaseResponse) -> bool:
        config = self.filter_config
        checks = []

        if config.match_status_codes:
            checks.append(resp.status in config.match_status_codes)
        if config.match_sizes:
            checks.append(matches_numeric_ranges(resp.length, config.match_sizes))
        if config.match_words:
            checks.append(matches_numeric_ranges(resp.words, config.match_words))
        if config.match_lines:
            checks.append(matches_numeric_ranges(resp.lines, config.match_lines))
        if config.match_regex:
            checks.append(bool(re.search(config.match_regex, resp.text)))
        if config.match_headers:
            checks.append(matches_header_text(resp, config.match_headers))
        if config.match_header_regex:
            checks.append(matches_header_regex(resp, config.match_header_regex))
        if config.match_time:
            checks.append(matches_time_filters(resp.elapsed, config.match_time))

        return self._combine_advanced_checks(checks, config.matcher_mode, default=True)

    def matches_advanced_filters(self, resp: BaseResponse) -> bool:
        config = self.filter_config
        checks = []

        if config.filter_status_codes:
            checks.append(resp.status in config.filter_status_codes)
        if config.filter_sizes:
            checks.append(matches_numeric_ranges(resp.length, config.filter_sizes))
        if config.filter_words:
            checks.append(matches_numeric_ranges(resp.words, config.filter_words))
        if config.filter_lines:
            checks.append(matches_numeric_ranges(resp.lines, config.filter_lines))
        if config.filter_regex:
            checks.append(bool(re.search(config.filter_regex, resp.text)))
        if config.filter_headers:
            checks.append(matches_header_text(resp, config.filter_headers))
        if config.filter_header_regex:
            checks.append(matches_header_regex(resp, config.filter_header_regex))
        if config.filter_time:
            checks.append(matches_time_filters(resp.elapsed, config.filter_time))

        return self._combine_advanced_checks(checks, config.filter_mode, default=False)

    @staticmethod
    def _combine_advanced_checks(checks: list[bool], mode: str, default: bool) -> bool:
        if not checks:
            return default

        if mode == "and":
            return all(checks)

        return any(checks)

    def is_auto_calibrated(self, resp: BaseResponse) -> bool:
        state = self.filter_state
        fingerprint = self.response_fingerprint(resp)
        should_record = self.should_record_auto_calibration(resp)
        threshold = (
            AUTO_CALIBRATION_FORCED_THRESHOLD
            if self.filter_config.auto_calibration
            else AUTO_CALIBRATION_DUPLICATE_THRESHOLD
        )
        repeated_fingerprint = False
        with state.lock:
            if fingerprint in state.auto_calibrated_fingerprints:
                repeated_fingerprint = True
            elif not should_record:
                return False
            else:
                count = state.similar_fingerprints.get(fingerprint, 0) + 1
                state.similar_fingerprints[fingerprint] = count
                if count < threshold:
                    return False
                state.auto_calibrated_fingerprints.add(fingerprint)

        if repeated_fingerprint:
            self.logger.debug(f'"{resp.url}" filtered by auto-calibration fingerprint')
        else:
            self.logger.debug(
                f'"{resp.url}" filtered by repeated response auto-calibration '
                f'(threshold={threshold})'
            )
        return True

    def is_filter_threshold_reached(self, resp: BaseResponse) -> bool:
        state = self.filter_state
        threshold = self.filter_config.filter_threshold
        if not threshold:
            return False

        fingerprint = resp.filter_fingerprint
        with state.lock:
            count = state.filter_fingerprints.get(fingerprint, 0)
            if count >= threshold:
                return True
            state.filter_fingerprints[fingerprint] = count + 1
        return False

    def should_record_auto_calibration(self, resp: BaseResponse) -> bool:
        if self.has_advanced_matchers():
            return False

        if resp.length < AUTO_CALIBRATION_MIN_CONTENT_LENGTH:
            return False

        if self.filter_config.auto_calibration:
            return True

        if 400 <= resp.status <= 599:
            return True

        path = clean_path(resp.full_path).strip("/")
        if path and path in resp.text:
            return True

        return bool(resp.redirect)

    def has_advanced_matchers(self) -> bool:
        config = self.filter_config
        return any(
            (
                config.match_status_codes,
                config.match_sizes,
                config.match_words,
                config.match_lines,
                config.match_regex,
                config.match_headers,
                config.match_header_regex,
                config.match_time,
            )
        )

    @staticmethod
    def response_fingerprint(resp: BaseResponse) -> tuple:
        path = clean_path(resp.full_path).strip("/")
        body = resp.normalized_content
        redirect = clean_path(resp.redirect)

        if path:
            body = body.replace(path, "__PATH__")
            redirect = redirect.replace(path, "__PATH__")

        return (
            resp.status,
            resp.type,
            redirect,
            len(body) // 64,
            hash(body[:4096]),
        )

    def response_callbacks(
        self, path: str, response: BaseResponse
    ) -> tuple[Callable[[BaseResponse], Any], ...]:
        scanners = self.get_scanners_for(path)

        if self.is_excluded(response):
            return self.not_found_callbacks

        for tester in scanners:
            # Check if the response is unique, not wildcard
            if not tester.check(path, response):
                return self.not_found_callbacks

        if self.is_filter_threshold_reached(response):
            return self.not_found_callbacks

        return self.match_callbacks

    def process_response(self, path: str, response: BaseResponse) -> None:
        for callback in self.response_callbacks(path, response):
            callback(response)


class Fuzzer(BaseFuzzer):
    def __init__(
        self,
        requester: Requester,
        dictionary: Dictionary,
        *,
        filter_config: FilterConfig,
        discovery_config: DiscoveryConfig,
        execution_config: ExecutionConfig,
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
        logger: RunLogger | None = None,
    ) -> None:
        super().__init__(
            requester,
            dictionary,
            filter_config=filter_config,
            discovery_config=discovery_config,
            execution_config=execution_config,
            match_callbacks=match_callbacks,
            not_found_callbacks=not_found_callbacks,
            error_callbacks=error_callbacks,
            logger=logger,
        )
        self._exc: Exception | None = None
        self._exc_lock = threading.Lock()
        self._threads = []
        self._play_event = threading.Event()
        self._quit_event = threading.Event()
        self._pause_semaphore = threading.Semaphore(0)

    def setup_scanners(self) -> None:
        scanners = self.filter_state.scanners
        # Default scanners (wildcard testers)
        scanners["default"]["random"] = Scanner(
            self._requester,
            filter_config=self.filter_config,
            delay=self.execution_config.delay,
            logger=self.logger,
            path=self._base_path + WILDCARD_TEST_POINT_MARKER,
        )

        if self.filter_config.exclude_response:
            scanners["default"]["custom"] = Scanner(
                self._requester,
                filter_config=self.filter_config,
                delay=self.execution_config.delay,
                logger=self.logger,
                tested=scanners,
                path=self.filter_config.exclude_response,
            )

        for prefix in set(self.discovery_config.prefixes + DEFAULT_TEST_PREFIXES):
            scanners["prefixes"][prefix] = Scanner(
                self._requester,
                filter_config=self.filter_config,
                delay=self.execution_config.delay,
                logger=self.logger,
                tested=scanners,
                path=f"{self._base_path}{prefix}{WILDCARD_TEST_POINT_MARKER}",
                context=f"/{self._base_path}{prefix}***",
            )

        for suffix in set(self.discovery_config.suffixes + DEFAULT_TEST_SUFFIXES):
            scanners["suffixes"][suffix] = Scanner(
                self._requester,
                filter_config=self.filter_config,
                delay=self.execution_config.delay,
                logger=self.logger,
                tested=scanners,
                path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}{suffix}",
                context=f"/{self._base_path}***{suffix}",
            )

        for extension in self.discovery_config.extensions:
            if "." + extension not in scanners["suffixes"]:
                scanners["suffixes"]["." + extension] = Scanner(
                    self._requester,
                    filter_config=self.filter_config,
                    delay=self.execution_config.delay,
                    logger=self.logger,
                    tested=scanners,
                    path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}.{extension}",
                    context=f"/{self._base_path}***.{extension}",
                )

    def setup_threads(self) -> None:
        if self._threads:
            self._threads = []

        for _ in range(self.execution_config.concurrency):
            new_thread = threading.Thread(target=self.thread_proc)
            new_thread.daemon = True
            self._threads.append(new_thread)

    def start(self) -> None:
        self.setup_scanners()
        self.setup_threads()
        self.play()
        self._quit_event.clear()

        for thread in self._threads:
            thread.start()

    def is_finished(self) -> bool:
        for thread in self._threads:
            if thread.is_alive():
                return False

        if self._exc:
            raise self._exc

        return True

    def play(self) -> None:
        self._play_event.set()

    def pause(self) -> bool:
        """Pause all threads and wait for them to acknowledge.

        Returns True if all threads paused successfully, False if timeout occurred.
        """
        self._play_event.clear()
        # Wait for all threads to stop (with timeout to avoid deadlock)
        for thread in self._threads:
            if thread.is_alive():
                # Use timeout to prevent deadlock when threads are blocked on I/O
                if not self._pause_semaphore.acquire(timeout=2):
                    return False
        return True

    def quit(self) -> None:
        self._quit_event.set()
        self.play()

    def stop(self, timeout: float) -> bool:
        workers = [thread for thread in self._threads if thread.is_alive()]
        if not workers:
            return True

        self.quit()
        deadline = time.monotonic() + max(0.0, timeout)
        for worker in workers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(timeout=remaining)

        return not any(worker.is_alive() for worker in workers)

    def _stop_with_exception(self, exception: Exception) -> None:
        with self._exc_lock:
            if self._exc is None:
                self._exc = exception
        self.quit()

    def scan(self, path: str) -> None:
        try:
            response = self._requester.request(path)
        except RequestException as e:
            for callback in self.error_callbacks:
                callback(e)
            return

        self.process_response(path, response)

    def thread_proc(self) -> None:
        self.logger.info(f'THREAD-{threading.get_ident()} started"')

        while True:
            should_quit = False
            try:
                path = self._dictionary.claim_next()
                try:
                    self.scan(self._base_path + path)
                finally:
                    self._dictionary.release_claim(path)

            except StopIteration:
                break

            except Exception as e:
                self._stop_with_exception(e)

            finally:
                time.sleep(self.execution_config.delay)

                if not self._play_event.is_set():
                    self.logger.info(f'THREAD-{threading.get_ident()} paused"')
                    self._pause_semaphore.release()
                    self._play_event.wait()
                    self.logger.info(f'THREAD-{threading.get_ident()} continued"')

                if self._quit_event.is_set():
                    should_quit = True

            if should_quit:
                break


class NativeFuzzer(Fuzzer):
    def __init__(
        self,
        requester: NativeRequester,
        dictionary: Dictionary,
        *,
        filter_config: FilterConfig,
        discovery_config: DiscoveryConfig,
        execution_config: ExecutionConfig,
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
        logger: RunLogger | None = None,
        filtered_chunk_callbacks: tuple[Callable[[int], Any], ...] = (),
    ) -> None:
        super().__init__(
            requester,
            dictionary,
            filter_config=filter_config,
            discovery_config=discovery_config,
            execution_config=execution_config,
            match_callbacks=match_callbacks,
            not_found_callbacks=not_found_callbacks,
            error_callbacks=error_callbacks,
            logger=logger,
        )
        self._finished = False
        self.filtered_chunk_callbacks = filtered_chunk_callbacks
        self._native_backend: NativeHTTPBackend | None = requester.backend
        self._paused_event = threading.Event()
        self._started_event = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._prepared = False

    def prepare_start(self) -> None:
        with self._lifecycle_lock:
            self._quit_event.clear()
            self._finished = False
            self._paused_event.clear()
            self._started_event.clear()
            self._reset_native_cancellation()
            self._prepared = True

    def start(self) -> None:
        with self._lifecycle_lock:
            if not self._prepared:
                self._quit_event.clear()
                self._finished = False
                self._paused_event.clear()
                self._started_event.clear()
                self._reset_native_cancellation()
            self._prepared = False

        try:
            if self._native_backend is None:
                self._native_backend = self._requester.get_backend()
            self.setup_scanners()
            super().play()
            self._started_event.set()

            while not self._quit_event.is_set():
                if not self._play_event.is_set():
                    # Acknowledge pause only after claims are recoverable.
                    self._dictionary.requeue_claims()
                    self._paused_event.set()
                    self._play_event.wait()
                    self._paused_event.clear()
                    continue

                paths = self._next_chunk()
                if not paths:
                    break

                try:
                    self._native_backend.scan_chunks(
                        self._requester._url,
                        paths,
                        lambda chunk: self._process_native_chunk(paths, chunk),
                        self._requester._query,
                    )
                except BaseException:
                    # A callback or native failure must not strand claims. A
                    # saved Python session will resume at the first prefix that
                    # was not successfully processed.
                    self._dictionary.requeue_claims()
                    raise
                finally:
                    if not self._play_event.is_set():
                        self._dictionary.requeue_claims()
        finally:
            self._finished = True
            self._started_event.set()
            self._paused_event.set()

    def _process_native_chunk(
        self,
        paths: list[str] | NativeWordlistChunk,
        chunk: NativeScanChunk,
    ) -> None:
        """Expand Rust's compact event stream without rebuilding miss responses."""

        next_index = chunk.start_index
        for event in chunk.events:
            if self._should_stop_processing():
                return
            # Missing indexes are responses that Rust already classified as
            # filtered. Only their progress and dictionary claims matter here.
            if event.request_index > next_index:
                self._process_filtered_range(paths, next_index, event.request_index)
            if self._should_stop_processing():
                return
            try:
                self._process_native_result(
                    event.path,
                    event.response,
                    event.error,
                )
            finally:
                if isinstance(paths, NativeWordlistChunk):
                    self._dictionary.release_native_claims(paths, 1)
                else:
                    self._release_paths((event.path,))
            next_index = event.request_index + 1

        # end_index is the exclusive end of this ordered chunk, so it
        # also releases a filtered tail after the last actionable event.
        if not self._should_stop_processing() and chunk.end_index > next_index:
            self._process_filtered_range(paths, next_index, chunk.end_index)

    def _process_filtered_range(
        self,
        paths: list[str] | NativeWordlistChunk,
        start: int,
        end: int,
    ) -> None:
        count = end - start
        if count <= 0:
            return
        if isinstance(paths, NativeWordlistChunk):
            try:
                for callback in self.filtered_chunk_callbacks:
                    callback(count)
            finally:
                self._dictionary.release_native_claims(paths, count)
            return

        # The common miss-only chunk spans the original list. Avoid a second
        # list of references merely to report/release its progress.
        filtered_paths = paths if start == 0 and end == len(paths) else paths[start:end]
        self._process_filtered_paths(filtered_paths)

    def _process_filtered_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        try:
            for callback in self.filtered_chunk_callbacks:
                callback(len(paths))
        finally:
            self._release_paths(paths)

    def _process_native_result(
        self,
        path: str,
        response: BaseResponse | None,
        error: RequestException | None,
    ) -> None:
        if error is not None:
            for callback in self.error_callbacks:
                callback(error)
            return
        if response is None:
            raise RuntimeError("Native backend returned neither response nor error")
        if response.filtered:
            for callback in self.not_found_callbacks:
                callback(response)
            return
        self.process_response(path, response)

    def _release_paths(self, paths) -> None:
        dictionary_paths = paths
        if self._base_path:
            dictionary_paths = [
                lstrip_once(path, self._base_path)
                for path in paths
            ]
        elif not isinstance(paths, list):
            dictionary_paths = list(paths)
        self._dictionary.release_claims(dictionary_paths)

    def _should_stop_processing(self) -> bool:
        return self._quit_event.is_set() or not self._play_event.is_set()

    def _next_chunk(self) -> list[str] | NativeWordlistChunk:
        chunk_size = max(1000, self.execution_config.concurrency * 100)
        paths = self._dictionary.claim_native_many(chunk_size, self._base_path)
        if isinstance(paths, NativeWordlistChunk):
            return paths
        if not self._base_path:
            return paths
        return [self._base_path + path for path in paths]

    def is_finished(self) -> bool:
        return self._finished

    def play(self) -> None:
        self._reset_native_cancellation()
        self._paused_event.clear()
        super().play()

    def _reset_native_cancellation(self) -> None:
        if self._native_backend is None:
            return
        self._native_backend.reset_cancel()

    def pause(self) -> bool:
        deadline = time.monotonic() + NATIVE_PAUSE_TIMEOUT
        if not self._started_event.wait(timeout=NATIVE_PAUSE_TIMEOUT):
            return self._finished

        self._play_event.clear()
        if self._finished:
            return True
        if self._native_backend is not None:
            self._native_backend.cancel()
        timeout = max(0.0, deadline - time.monotonic())
        return self._paused_event.wait(timeout=timeout)

    def quit(self) -> None:
        self._quit_event.set()
        self._paused_event.clear()
        super().play()
        if self._native_backend is not None:
            self._native_backend.cancel()


class AsyncFuzzer(BaseFuzzer):
    def __init__(
        self,
        requester: AsyncRequester,
        dictionary: Dictionary,
        *,
        filter_config: FilterConfig,
        discovery_config: DiscoveryConfig,
        execution_config: ExecutionConfig,
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
        logger: RunLogger | None = None,
    ) -> None:
        super().__init__(
            requester,
            dictionary,
            filter_config=filter_config,
            discovery_config=discovery_config,
            execution_config=execution_config,
            match_callbacks=match_callbacks,
            not_found_callbacks=not_found_callbacks,
            error_callbacks=error_callbacks,
            logger=logger,
        )
        self._play_event = asyncio.Event()
        self._background_tasks = set()

    async def setup_scanners(self) -> None:
        scanners = self.filter_state.scanners
        # Default scanners (wildcard testers)
        scanners["default"]["random"] = await AsyncScanner.create(
            self._requester,
            filter_config=self.filter_config,
            delay=self.execution_config.delay,
            logger=self.logger,
            path=self._base_path + WILDCARD_TEST_POINT_MARKER,
        )

        if self.filter_config.exclude_response:
            scanners["default"]["custom"] = await AsyncScanner.create(
                self._requester,
                filter_config=self.filter_config,
                delay=self.execution_config.delay,
                logger=self.logger,
                tested=scanners,
                path=self.filter_config.exclude_response,
            )

        for prefix in self.discovery_config.prefixes + DEFAULT_TEST_PREFIXES:
            scanners["prefixes"][prefix] = await AsyncScanner.create(
                self._requester,
                filter_config=self.filter_config,
                delay=self.execution_config.delay,
                logger=self.logger,
                tested=scanners,
                path=f"{self._base_path}{prefix}{WILDCARD_TEST_POINT_MARKER}",
                context=f"/{self._base_path}{prefix}***",
            )

        for suffix in self.discovery_config.suffixes + DEFAULT_TEST_SUFFIXES:
            scanners["suffixes"][suffix] = await AsyncScanner.create(
                self._requester,
                filter_config=self.filter_config,
                delay=self.execution_config.delay,
                logger=self.logger,
                tested=scanners,
                path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}{suffix}",
                context=f"/{self._base_path}***{suffix}",
            )

        for extension in self.discovery_config.extensions:
            if "." + extension not in scanners["suffixes"]:
                scanners["suffixes"]["." + extension] = await AsyncScanner.create(
                    self._requester,
                    filter_config=self.filter_config,
                    delay=self.execution_config.delay,
                    logger=self.logger,
                    tested=scanners,
                    path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}.{extension}",
                    context=f"/{self._base_path}***.{extension}",
                )

    async def start(self) -> None:
        # In Python 3.9, initialize the Semaphore within the coroutine
        # to avoid binding to a different event loop.
        self.sem = asyncio.Semaphore(self.execution_config.concurrency)
        await self.setup_scanners()
        self.play()

        tasks = []
        for _ in range(min(self.execution_config.concurrency, len(self._dictionary))):
            task = asyncio.create_task(self.task_proc())
            tasks.append(task)
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def play(self) -> None:
        self._play_event.set()

    def pause(self) -> bool:
        self._play_event.clear()
        return True

    def quit(self) -> None:
        for task in tuple(self._background_tasks):
            task.cancel()

    async def scan(self, path: str) -> None:
        try:
            response = await self._requester.request(path)
        except RequestException as e:
            await self.run_callbacks(self.error_callbacks, e)
            return

        await self.run_callbacks(self.response_callbacks(path, response), response)

    @staticmethod
    async def run_callbacks(
        callbacks: tuple[Callable[[Any], Any], ...], value: Any
    ) -> None:
        for callback in callbacks:
            result = callback(value)
            if inspect.isawaitable(result):
                await result

    async def task_proc(self) -> None:
        while True:
            await self._play_event.wait()

            try:
                path = self._dictionary.claim_next()
            except StopIteration:
                return

            try:
                async with self.sem:
                    await self.scan(self._base_path + path)
            finally:
                self._dictionary.release_claim(path)

            await asyncio.sleep(self.execution_config.delay)
