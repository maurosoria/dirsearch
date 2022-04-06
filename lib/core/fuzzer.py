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

from lib.core.decorators import cached
from lib.core.exceptions import RequestException
from lib.core.scanner import Scanner
from lib.core.settings import (
    DEFAULT_SCAN_PREFIXES, DEFAULT_SCAN_SUFFIXES,
    RATE_UPDATE_DELAY,
)
from lib.parse.url import clean_path


class Fuzzer:
    def __init__(self, requester, dictionary, **kwargs):
        self._threads = []
        self._requester = requester
        self._dictionary = dictionary
        self._is_running = False
        self._play_event = threading.Event()
        self._paused_semaphore = threading.Semaphore(0)
        self.suffixes = kwargs.get("suffixes", [])
        self.prefixes = kwargs.get("prefixes", [])
        self.exclude_response = kwargs.get("exclude_response", None)
        self.threads_count = kwargs.get("threads", 15)
        self.delay = kwargs.get("delay", 0)
        self.maxrate = kwargs.get("maxrate", 0)
        self.calibration = None
        self.default_scanner = None
        self.match_callbacks = kwargs.get("match_callbacks", [])
        self.not_found_callbacks = kwargs.get("not_found_callbacks", [])
        self.error_callbacks = kwargs.get("error_callbacks", [])
        self.scanners = {
            "prefixes": {},
            "suffixes": {},
        }
        self.exc = None

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
        if len(self.scanners):
            self.scanners = {
                "prefixes": {},
                "suffixes": {},
            }

        # Default scanners (wildcard testers)
        self.default_scanner = Scanner(self._requester)

        for prefix in self.prefixes.union(DEFAULT_SCAN_PREFIXES):
            self.scanners["prefixes"][prefix] = Scanner(
                self._requester, prefix=prefix, tested=self.scanners
            )

        for suffix in self.suffixes.union(DEFAULT_SCAN_SUFFIXES):
            self.scanners["suffixes"][suffix] = Scanner(
                self._requester, suffix=suffix, tested=self.scanners
            )

        for extension in self._dictionary.extensions:
            if "." + extension not in self.scanners["suffixes"]:
                self.scanners["suffixes"]["." + extension] = Scanner(
                    self._requester, suffix="." + extension, tested=self.scanners
                )

        if self.exclude_response:
            self.calibration = Scanner(
                self._requester, custom=self.exclude_response, tested=self.scanners
            )

    def setup_threads(self):
        if self._threads:
            self._threads = []

        for _ in range(self.threads_count):
            new_thread = threading.Thread(target=self.thread_proc)
            new_thread.daemon = True
            self._threads.append(new_thread)

    def get_scanner_for(self, path):
        # Clean the path, so can check for extensions/suffixes
        path = clean_path(path)

        if self.exclude_response:
            yield self.calibration

        for prefix in self.prefixes:
            if path.startswith(prefix):
                yield self.scanners["prefixes"][prefix]

        for suffix in self.suffixes:
            if path.endswith(suffix):
                yield self.scanners["suffixes"][suffix]

        for extension in self._dictionary.extensions:
            if path.endswith("." + extension):
                yield self.scanners["suffixes"]["." + extension]

        yield self.default_scanner

    def start(self):
        self.setup_scanners()
        self.setup_threads()

        self._running_threads_count = len(self._threads)
        self._is_running = True
        self._rate = 0
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

    def scan(self, path):
        wildcard = False
        response = self._requester.request(path)

        for tester in list(set(self.get_scanner_for(path))):
            if not tester.scan(path, response):
                wildcard = True
                break

        return wildcard, response

    def is_stopped(self):
        return self._running_threads_count == 0

    def is_rate_exceeded(self):
        return self._rate >= self.maxrate > 0

    def decrease_threads(self):
        self._running_threads_count -= 1

    def increase_threads(self):
        self._running_threads_count += 1

    def decrease_rate(self):
        self._rate -= 1

    def increase_rate(self):
        self._rate += 1
        threading.Timer(1, self.decrease_rate).start()

    def set_base_path(self, path):
        self._requester.base_path = path

    def thread_proc(self):
        self._play_event.wait()

        while True:
            try:
                path = next(self._dictionary)

                # Pause if the request rate exceeded the maximum
                while self.is_rate_exceeded():
                    time.sleep(0.1)

                self.increase_rate()

                wildcard, response = self.scan(path)

                try:
                    if not wildcard:
                        for callback in self.match_callbacks:
                            callback(path, response)
                    else:
                        for callback in self.not_found_callbacks:
                            callback(path, response)
                except Exception as e:
                    self.exc = e

            except StopIteration:
                self._is_running = False

            except RequestException as e:
                for callback in self.error_callbacks:
                    callback(path, e.args[1])

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

    @property
    @cached(RATE_UPDATE_DELAY)
    def rate(self):
        return self._rate
