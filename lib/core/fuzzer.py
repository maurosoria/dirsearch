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

from lib.connection.native import NativeHTTPBackend
from lib.connection.requester import AsyncRequester, BaseRequester, Requester
from lib.connection.response import BaseResponse
from lib.core.data import blacklists, options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import RequestException
from lib.core.filters import matches_numeric_ranges, matches_time_filters
from lib.core.logger import logger
from lib.core.scanner import AsyncScanner, BaseScanner, Scanner
from lib.core.settings import (
    DEFAULT_TEST_PREFIXES,
    DEFAULT_TEST_SUFFIXES,
    NATIVE_PAUSE_TIMEOUT,
    WILDCARD_TEST_POINT_MARKER,
)
from lib.parse.url import clean_path
from lib.utils.common import lstrip_once
from lib.utils.diff import normalize_dynamic_content


AUTO_CALIBRATION_DUPLICATE_THRESHOLD = 8
AUTO_CALIBRATION_FORCED_THRESHOLD = 3
AUTO_CALIBRATION_MIN_CONTENT_LENGTH = 32


def response_headers_text(resp: BaseResponse) -> str:
    return "\n".join(f"{name}: {value}" for name, value in resp.headers.items())


def matches_header_text(resp: BaseResponse, patterns: list[str]) -> bool:
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
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
    ) -> None:
        self._requester = requester
        self._dictionary = dictionary
        self._base_path: str = ""
        self._hashes: dict = {}
        self.match_callbacks = match_callbacks
        self.not_found_callbacks = not_found_callbacks
        self.error_callbacks = error_callbacks
        self._similar_fingerprints: dict[tuple, int] = {}
        self._auto_calibrated_fingerprints: set[tuple] = set()

        self.scanners: dict[str, dict[str, Scanner]] = {
            "default": {},
            "prefixes": {},
            "suffixes": {},
        }

    def set_base_path(self, path: str) -> None:
        self._base_path = path

    def get_scanners_for(self, path: str) -> Generator[BaseScanner, None, None]:
        # Clean the path, so can check for extensions/suffixes
        path = clean_path(path)

        for prefix in self.scanners["prefixes"]:
            if path.startswith(prefix):
                yield self.scanners["prefixes"][prefix]

        for suffix in self.scanners["suffixes"]:
            if path.endswith(suffix):
                yield self.scanners["suffixes"][suffix]

        for scanner in self.scanners["default"].values():
            yield scanner

    def is_excluded(self, resp: BaseResponse) -> bool:
        """Validate the response by different filters"""

        if resp.status in options["exclude_status_codes"]:
            return True

        if (
            options["include_status_codes"]
            and resp.status not in options["include_status_codes"]
        ):
            return True

        if (
            resp.status in blacklists
            and any(
                resp.path.endswith(lstrip_once(suffix, "/"))
                for suffix in blacklists.get(resp.status)
            )
        ):
            return True

        if resp.length in options["exclude_sizes"]:
            return True

        if resp.length < options["minimum_response_size"]:
            return True

        if resp.length > options["maximum_response_size"] > 0:
            return True

        if any(text in resp.content for text in options["exclude_texts"]):
            return True

        if options["exclude_regex"] and re.search(options["exclude_regex"], resp.content):
            return True

        if (
            options["exclude_redirect"]
            and (
                options["exclude_redirect"] in resp.redirect
                or re.search(options["exclude_redirect"], resp.redirect)
            )
        ):
            return True

        if not self.matches_advanced_matchers(resp):
            return True

        if self.matches_advanced_filters(resp):
            return True

        if self.is_auto_calibrated(resp):
            return True

        if (
            options["filter_threshold"]
            and self._hashes.get(hash(resp), 0) >= options["filter_threshold"]
        ):
            return True

        return False

    def matches_advanced_matchers(self, resp: BaseResponse) -> bool:
        checks = []

        if options["match_status_codes"]:
            checks.append(resp.status in options["match_status_codes"])
        if options["match_sizes"]:
            checks.append(matches_numeric_ranges(resp.length, options["match_sizes"]))
        if options["match_words"]:
            checks.append(matches_numeric_ranges(resp.words, options["match_words"]))
        if options["match_lines"]:
            checks.append(matches_numeric_ranges(resp.lines, options["match_lines"]))
        if options["match_regex"]:
            checks.append(bool(re.search(options["match_regex"], resp.text)))
        if options["match_headers"]:
            checks.append(matches_header_text(resp, options["match_headers"]))
        if options["match_header_regex"]:
            checks.append(matches_header_regex(resp, options["match_header_regex"]))
        if options["match_time"]:
            checks.append(matches_time_filters(resp.elapsed, options["match_time"]))

        return self._combine_advanced_checks(checks, options["matcher_mode"], default=True)

    def matches_advanced_filters(self, resp: BaseResponse) -> bool:
        checks = []

        if options["filter_status_codes"]:
            checks.append(resp.status in options["filter_status_codes"])
        if options["filter_sizes"]:
            checks.append(matches_numeric_ranges(resp.length, options["filter_sizes"]))
        if options["filter_words"]:
            checks.append(matches_numeric_ranges(resp.words, options["filter_words"]))
        if options["filter_lines"]:
            checks.append(matches_numeric_ranges(resp.lines, options["filter_lines"]))
        if options["filter_regex"]:
            checks.append(bool(re.search(options["filter_regex"], resp.text)))
        if options["filter_headers"]:
            checks.append(matches_header_text(resp, options["filter_headers"]))
        if options["filter_header_regex"]:
            checks.append(matches_header_regex(resp, options["filter_header_regex"]))
        if options["filter_time"]:
            checks.append(matches_time_filters(resp.elapsed, options["filter_time"]))

        return self._combine_advanced_checks(checks, options["filter_mode"], default=False)

    @staticmethod
    def _combine_advanced_checks(checks: list[bool], mode: str, default: bool) -> bool:
        if not checks:
            return default

        if mode == "and":
            return all(checks)

        return any(checks)

    def is_auto_calibrated(self, resp: BaseResponse) -> bool:
        fingerprint = self.response_fingerprint(resp)
        if fingerprint in self._auto_calibrated_fingerprints:
            logger.debug(f'"{resp.url}" filtered by auto-calibration fingerprint')
            return True

        if not self.should_record_auto_calibration(resp):
            return False

        self._similar_fingerprints[fingerprint] = (
            self._similar_fingerprints.get(fingerprint, 0) + 1
        )
        threshold = (
            AUTO_CALIBRATION_FORCED_THRESHOLD
            if options["auto_calibration"]
            else AUTO_CALIBRATION_DUPLICATE_THRESHOLD
        )

        if self._similar_fingerprints[fingerprint] < threshold:
            return False

        self._auto_calibrated_fingerprints.add(fingerprint)
        logger.debug(
            f'"{resp.url}" filtered by repeated response auto-calibration '
            f'(threshold={threshold})'
        )
        return True

    def should_record_auto_calibration(self, resp: BaseResponse) -> bool:
        if self.has_advanced_matchers():
            return False

        if resp.length < AUTO_CALIBRATION_MIN_CONTENT_LENGTH:
            return False

        if options["auto_calibration"]:
            return True

        if 400 <= resp.status <= 599:
            return True

        path = clean_path(resp.full_path).strip("/")
        if path and path in resp.text:
            return True

        return bool(resp.redirect)

    @staticmethod
    def has_advanced_matchers() -> bool:
        return any(
            (
                options["match_status_codes"],
                options["match_sizes"],
                options["match_words"],
                options["match_lines"],
                options["match_regex"],
                options["match_headers"],
                options["match_header_regex"],
                options["match_time"],
            )
        )

    @staticmethod
    def response_fingerprint(resp: BaseResponse) -> tuple:
        path = clean_path(resp.full_path).strip("/")
        body = normalize_dynamic_content(resp.text)
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

        if options["filter_threshold"]:
            hash_ = hash(response)
            self._hashes.setdefault(hash_, 0)
            self._hashes[hash_] += 1

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
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
    ) -> None:
        super().__init__(
            requester,
            dictionary,
            match_callbacks=match_callbacks,
            not_found_callbacks=not_found_callbacks,
            error_callbacks=error_callbacks,
        )
        self._exc: Exception | None = None
        self._exc_lock = threading.Lock()
        self._threads = []
        self._play_event = threading.Event()
        self._quit_event = threading.Event()
        self._pause_semaphore = threading.Semaphore(0)

    def setup_scanners(self) -> None:
        # Default scanners (wildcard testers)
        self.scanners["default"]["random"] = Scanner(
            self._requester, path=self._base_path + WILDCARD_TEST_POINT_MARKER
        )

        if options["exclude_response"]:
            self.scanners["default"]["custom"] = Scanner(
                self._requester, tested=self.scanners, path=options["exclude_response"]
            )

        for prefix in set(options["prefixes"] + DEFAULT_TEST_PREFIXES):
            self.scanners["prefixes"][prefix] = Scanner(
                self._requester,
                tested=self.scanners,
                path=f"{self._base_path}{prefix}{WILDCARD_TEST_POINT_MARKER}",
                context=f"/{self._base_path}{prefix}***",
            )

        for suffix in set(options["suffixes"] + DEFAULT_TEST_SUFFIXES):
            self.scanners["suffixes"][suffix] = Scanner(
                self._requester,
                tested=self.scanners,
                path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}{suffix}",
                context=f"/{self._base_path}***{suffix}",
            )

        for extension in options["extensions"]:
            if "." + extension not in self.scanners["suffixes"]:
                self.scanners["suffixes"]["." + extension] = Scanner(
                    self._requester,
                    tested=self.scanners,
                    path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}.{extension}",
                    context=f"/{self._base_path}***.{extension}",
                )

    def setup_threads(self) -> None:
        if self._threads:
            self._threads = []

        for _ in range(options["thread_count"]):
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
        logger.info(f'THREAD-{threading.get_ident()} started"')

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
                time.sleep(options["delay"])

                if not self._play_event.is_set():
                    logger.info(f'THREAD-{threading.get_ident()} paused"')
                    self._pause_semaphore.release()
                    self._play_event.wait()
                    logger.info(f'THREAD-{threading.get_ident()} continued"')

                if self._quit_event.is_set():
                    should_quit = True

            if should_quit:
                break


class NativeFuzzer(Fuzzer):
    def __init__(
        self,
        requester: Requester,
        dictionary: Dictionary,
        *,
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
    ) -> None:
        super().__init__(
            requester,
            dictionary,
            match_callbacks=match_callbacks,
            not_found_callbacks=not_found_callbacks,
            error_callbacks=error_callbacks,
        )
        self._finished = False
        self._native_backend: NativeHTTPBackend | None = None
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
            self._native_backend = self._native_backend or NativeHTTPBackend()
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
                    for path, response, error in self._native_backend.scan(
                        self._requester._url,
                        paths,
                        getattr(self._requester, "_query", ""),
                    ):
                        if (
                            self._quit_event.is_set()
                            or not self._play_event.is_set()
                        ):
                            break
                        try:
                            if error is not None:
                                for callback in self.error_callbacks:
                                    callback(error)
                                continue
                            if response.filtered:
                                for callback in self.not_found_callbacks:
                                    callback(response)
                                continue
                            self.process_response(path, response)
                        finally:
                            dictionary_path = lstrip_once(path, self._base_path)
                            self._dictionary.release_claim(dictionary_path)
                finally:
                    if not self._play_event.is_set():
                        self._dictionary.requeue_claims()
        finally:
            self._finished = True
            self._started_event.set()
            self._paused_event.set()

    def _next_chunk(self) -> list[str]:
        chunk_size = max(1000, options["thread_count"] * 100)
        paths = []
        for _ in range(chunk_size):
            try:
                paths.append(self._base_path + self._dictionary.claim_next())
            except StopIteration:
                break
        return paths

    def is_finished(self) -> bool:
        return self._finished

    def play(self) -> None:
        self._reset_native_cancellation()
        self._paused_event.clear()
        super().play()

    def _reset_native_cancellation(self) -> None:
        if self._native_backend is None:
            return
        reset_cancel = getattr(self._native_backend, "reset_cancel", None)
        if reset_cancel is not None:
            reset_cancel()

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
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
    ) -> None:
        super().__init__(
            requester,
            dictionary,
            match_callbacks=match_callbacks,
            not_found_callbacks=not_found_callbacks,
            error_callbacks=error_callbacks,
        )
        self._play_event = asyncio.Event()
        self._background_tasks = set()

    async def setup_scanners(self) -> None:
        # Default scanners (wildcard testers)
        self.scanners["default"]["random"] = await AsyncScanner.create(
            self._requester, path=self._base_path + WILDCARD_TEST_POINT_MARKER
        )

        if options["exclude_response"]:
            self.scanners["default"]["custom"] = await AsyncScanner.create(
                self._requester, tested=self.scanners, path=options["exclude_response"]
            )

        for prefix in options["prefixes"] + DEFAULT_TEST_PREFIXES:
            self.scanners["prefixes"][prefix] = await AsyncScanner.create(
                self._requester,
                tested=self.scanners,
                path=f"{self._base_path}{prefix}{WILDCARD_TEST_POINT_MARKER}",
                context=f"/{self._base_path}{prefix}***",
            )

        for suffix in options["suffixes"] + DEFAULT_TEST_SUFFIXES:
            self.scanners["suffixes"][suffix] = await AsyncScanner.create(
                self._requester,
                tested=self.scanners,
                path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}{suffix}",
                context=f"/{self._base_path}***{suffix}",
            )

        for extension in options["extensions"]:
            if "." + extension not in self.scanners["suffixes"]:
                self.scanners["suffixes"]["." + extension] = await AsyncScanner.create(
                    self._requester,
                    tested=self.scanners,
                    path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}.{extension}",
                    context=f"/{self._base_path}***.{extension}",
                )

    async def start(self) -> None:
        # In Python 3.9, initialize the Semaphore within the coroutine
        # to avoid binding to a different event loop.
        self.sem = asyncio.Semaphore(options["thread_count"])
        await self.setup_scanners()
        self.play()

        tasks = []
        for _ in range(min(options["thread_count"], len(self._dictionary))):
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

            await asyncio.sleep(options["delay"])
