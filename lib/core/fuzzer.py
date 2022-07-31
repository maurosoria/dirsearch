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

import threading
import time

from lib.core.exceptions import RequestException
from lib.core.logger import logger
from lib.core.scanner import Scanner
from lib.core.settings import (
    DEFAULT_TEST_PREFIXES, DEFAULT_TEST_SUFFIXES,
    WILDCARD_TEST_POINT_MARKER,
)
from lib.parse.url import clean_path
from lib.utils.crawl import Crawler


class Fuzzer:
    def __init__(self, requester, dictionary, **kwargs):
        self._threads = []
        self._scanned = set()
        self._requester = requester
        self._dictionary = dictionary
        self._is_running = False
        self._play_event = threading.Event()
        self._paused_semaphore = threading.Semaphore(0)
        self._base_path = None
        self.suffixes = kwargs.get("suffixes", tuple())
        self.prefixes = kwargs.get("prefixes", tuple())
        self.exclude_response = kwargs.get("exclude_response", None)
        self.threads_count = kwargs.get("threads", 15)
        self.delay = kwargs.get("delay", 0)
        self.crawl = kwargs.get("crawl", False)
        self.exc = None
        self.match_callbacks = kwargs.get("match_callbacks", [])
        self.not_found_callbacks = kwargs.get("not_found_callbacks", [])
        self.error_callbacks = kwargs.get("error_callbacks", [])

        if len(self._dictionary) < self.threads_count:
            self.threads_count = len(self._dictionary)

    def wait(self, timeout=None):
        if self.exc:
            raise self.exc

        for thread in self._threads:
            thread.join(timeout)

            if thread.is_alive():
                return False

        return True

    def setup_scanners(self):
        self.scanners = {
            "default": {},
            "prefixes": {},
            "suffixes": {},
        }

        # Default scanners (wildcard testers)
        self.scanners["default"].update({
            "index": Scanner(self._requester, path=self._base_path),
            "random": Scanner(self._requester, path=self._base_path + WILDCARD_TEST_POINT_MARKER),
        })

        if self.exclude_response:
            self.scanners["default"]["custom"] = Scanner(
                self._requester, tested=self.scanners, path=self.exclude_response
            )

        for prefix in self.prefixes + DEFAULT_TEST_PREFIXES:
            self.scanners["prefixes"][prefix] = Scanner(
                self._requester, tested=self.scanners,
                path=f"{self._base_path}{prefix}{WILDCARD_TEST_POINT_MARKER}",
                info=f"/{self._base_path}{prefix}***",
            )

        for suffix in self.suffixes + DEFAULT_TEST_SUFFIXES:
            self.scanners["suffixes"][suffix] = Scanner(
                self._requester, tested=self.scanners,
                path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}{suffix}",
                info=f"/{self._base_path}***{suffix}",
            )

        for extension in self._dictionary.extensions:
            if "." + extension not in self.scanners["suffixes"]:
                self.scanners["suffixes"]["." + extension] = Scanner(
                    self._requester, tested=self.scanners,
                    path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}.{extension}",
                    info=f"/{self._base_path}***.{extension}",
                )

    def setup_threads(self):
        if self._threads:
            self._threads = []

        for _ in range(self.threads_count):
            new_thread = threading.Thread(target=self.thread_proc)
            new_thread.daemon = True
            self._threads.append(new_thread)

    def get_scanners_for(self, path):
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

    def start(self):
        self.setup_scanners()
        self.setup_threads()

        self._running_threads_count = len(self._threads)
        self._is_running = True
        self._play_event.clear()

        for thread in self._threads:
            thread.start()

        self.play()

    def play(self):
        self._play_event.set()

    def pause(self):
        self._play_event.clear()
        for thread in self._threads:
            if thread.is_alive():
                self._paused_semaphore.acquire()

        self._is_running = False

    def resume(self):
        self._is_running = True
        self._paused_semaphore.release()
        self.play()

    def stop(self):
        self._is_running = False
        self.play()

    def scan(self, path, scanners):
        # Avoid scanned paths from being re-scanned
        if path in self._scanned:
            return
        else:
            self._scanned.add(path)

        response = self._requester.request(path)

        for tester in scanners:
            # Check if the response is unique, not wildcard
            if not tester.check(path, response):
                for callback in self.not_found_callbacks:
                    callback(response)
                return

        try:
            for callback in self.match_callbacks:
                callback(response)
        except Exception as e:
            self.exc = e

        if self.crawl:
            logger.info(f'THREAD-{threading.get_ident()}: crawling "/{path}"')
            for path_ in Crawler.crawl(response):
                logger.info(f'THREAD-{threading.get_ident()}: found new path "/{path_}" in "/{path}"')
                self.scan(path, self.get_scanners_for(path_))

    def is_stopped(self):
        return self._running_threads_count == 0

    def decrease_threads(self):
        self._running_threads_count -= 1

    def increase_threads(self):
        self._running_threads_count += 1

    def set_base_path(self, path):
        self._base_path = path

    def thread_proc(self):
        self._play_event.wait()

        while True:
            try:
                path = next(self._dictionary)
                scanners = self.get_scanners_for(path)
                self.scan(self._base_path + path, scanners)

            except StopIteration:
                self._is_running = False

            except RequestException as e:
                for callback in self.error_callbacks:
                    callback(e)

                continue

            finally:
                if not self._play_event.is_set():
                    self.decrease_threads()
                    self._paused_semaphore.release()
                    self._play_event.wait()
                    self.increase_threads()

                if not self._is_running:
                    break

                time.sleep(self.delay)
