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

from lib.connection.request_exception import RequestException
from .path import Path
from .scanner import Scanner


class Fuzzer(object):
    def __init__(
        self,
        requester,
        dictionary,
        suffixes=None,
        prefixes=None,
        exclude_content=None,
        threads=1,
        delay=0,
        maxrate=0,
        match_callbacks=[],
        not_found_callbacks=[],
        error_callbacks=[],
    ):

        self.requester = requester
        self.dictionary = dictionary
        self.suffixes = suffixes if suffixes else []
        self.prefixes = prefixes if prefixes else []
        self.exclude_content = exclude_content
        self.base_path = self.requester.base_path
        self.threads = []
        self.threads_count = (
            threads if len(self.dictionary) >= threads else len(self.dictionary)
        )
        self.delay = delay
        self.maxrate = maxrate
        self.running = False
        self.calibration = None
        self.default_scanner = None
        self.match_callbacks = match_callbacks
        self.not_found_callbacks = not_found_callbacks
        self.error_callbacks = error_callbacks
        self.matches = []
        self.scanners = {
            "prefixes": {},
            "suffixes": {},
        }

    def wait(self, timeout=None):
        for thread in self.threads:
            thread.join(timeout)

            if timeout and thread.is_alive():
                return False

        return True

    def rate_adjuster(self):
        while not self.wait(0.15):
            self.stand_rate = self.rate

    def setup_scanners(self):
        if len(self.scanners):
            self.scanners = {
                "prefixes": {},
                "suffixes": {},
            }

        # Default scanners (wildcard testers)
        self.default_scanner = Scanner(self.requester)
        self.prefixes.append(".")
        self.suffixes.append("/")

        for prefix in self.prefixes:
            self.scanners["prefixes"][prefix] = Scanner(
                self.requester, prefix=prefix, tested=self.scanners
            )

        for suffix in self.suffixes:
            self.scanners["suffixes"][suffix] = Scanner(
                self.requester, suffix=suffix, tested=self.scanners
            )

        for extension in self.dictionary.extensions:
            if "." + extension not in self.scanners["suffixes"]:
                self.scanners["suffixes"]["." + extension] = Scanner(
                    self.requester, suffix="." + extension, tested=self.scanners
                )

        if self.exclude_content:
            if self.exclude_content.startswith("/"):
                self.exclude_content = self.exclude_content[1:]
            self.calibration = Scanner(
                self.requester, calibration=self.exclude_content, tested=self.scanners
            )

    def setup_threads(self):
        if len(self.threads):
            self.threads = []

        for thread in range(self.threads_count):
            new_thread = threading.Thread(target=self.thread_proc)
            new_thread.daemon = True
            self.threads.append(new_thread)

    def get_scanner_for(self, path):
        # Clean the path, so can check for extensions/suffixes
        path = path.split("?")[0].split("#")[0]

        if self.exclude_content:
            yield self.calibration

        for prefix in self.prefixes:
            if path.startswith(prefix):
                yield self.scanners["prefixes"][prefix]

        for suffix in self.suffixes:
            if path.endswith(suffix):
                yield self.scanners["suffixes"][suffix]

        for extension in self.dictionary.extensions:
            if path.endswith("." + extension):
                yield self.scanners["suffixes"]["." + extension]

        yield self.default_scanner

    def start(self):
        # Setting up testers
        self.setup_scanners()
        # Setting up threads
        self.setup_threads()
        self.index = 0
        self.rate = 0
        self.stand_rate = 0
        self.dictionary.reset()
        self.running_threads_count = len(self.threads)
        self.running = True
        self.paused = False
        self.play_event = threading.Event()
        self.paused_semaphore = threading.Semaphore(0)
        self.play_event.clear()

        for thread in self.threads:
            thread.start()
        threading.Thread(target=self.rate_adjuster, daemon=True).start()

        self.play()

    def play(self):
        self.play_event.set()

    def pause(self):
        self.paused = True
        self.play_event.clear()
        for thread in self.threads:
            if thread.is_alive():
                self.paused_semaphore.acquire()

    def resume(self):
        self.paused = False
        self.paused_semaphore.release()
        self.play()

    def stop(self):
        self.running = False
        self.play()

    def scan(self, path):
        response = self.requester.request(path)
        result = response.status

        for tester in list(set(self.get_scanner_for(path))):
            if not tester.scan(path, response):
                result = None
                break

        return result, response

    def is_paused(self):
        return self.paused

    def is_running(self):
        return self.running

    def finish_threads(self):
        self.running = False
        self.finished_event.set()

    def is_stopped(self):
        return self.running_threads_count == 0

    def decrease_threads(self):
        self.running_threads_count -= 1

    def increase_threads(self):
        self.running_threads_count += 1

    def reduce_rate(self):
        self.rate -= 1

    def thread_proc(self):
        self.play_event.wait()

        try:
            path = next(self.dictionary)

            while path:
                try:
                    # Pause if the request rate exceeded the maximum
                    while self.maxrate and self.rate >= self.maxrate:
                        pass
                    self.rate += 1
                    threading.Timer(1, self.reduce_rate).start()

                    status, response = self.scan(path)
                    result = Path(path=path, status=status, response=response)

                    if status:
                        self.matches.append(result)
                        for callback in self.match_callbacks:
                            callback(result)
                    else:
                        for callback in self.not_found_callbacks:
                            callback(result)

                except RequestException as e:
                    for callback in self.error_callbacks:
                        callback(path, e.args[0]["message"])

                    continue

                finally:
                    if not self.play_event.is_set():
                        self.decrease_threads()
                        self.paused_semaphore.release()
                        self.play_event.wait()
                        self.increase_threads()

                    path = next(self.dictionary)  # Raises StopIteration when finishes

                    if not self.running:
                        break

                    time.sleep(self.delay)

        except StopIteration:
            pass
