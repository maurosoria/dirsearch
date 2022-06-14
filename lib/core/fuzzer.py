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

from urllib.parse import urlparse

from lib.core.decorators import cached
from lib.core.exceptions import InvalidURLException, RequestException
from lib.core.scanner import Scanner
from lib.core.settings import (
    DEFAULT_TEST_PREFIXES, DEFAULT_TEST_SUFFIXES,
    RATE_UPDATE_DELAY, STANDARD_PORTS, UNKNOWN,
    WILDCARD_TEST_POINT_MARKER,
)
from lib.parse.url import clean_path
from lib.utils.crawl import crawl
from lib.utils.schemedet import detect_scheme


class Fuzzer:
    def __init__(self, requester, dictionary, **kwargs):
        self._threads = []
        self._entries = set()
        self._requester = requester
        self._dictionary = dictionary
        self._is_running = False
        self._play_event = threading.Event()
        self._paused_semaphore = threading.Semaphore(0)
        # _base_path is immutable and base_path is mutable
        self._base_path = ""
        self.base_path = ""
        self.base_url = ""
        self.suffixes = kwargs.get("suffixes", ())
        self.prefixes = kwargs.get("prefixes", ())
        self.exclude_response = kwargs.get("exclude_response", None)
        self.threads_count = kwargs.get("threads", 15)
        self.delay = kwargs.get("delay", 0)
        self.maxrate = kwargs.get("maxrate", 0)
        self.default_scheme = kwargs.get("scheme", None)
        self.crawl = kwargs.get("crawl", False)
        self.default_scanners = []
        self.exc = None
        self.match_callbacks = kwargs.get("match_callbacks", [])
        self.not_found_callbacks = kwargs.get("not_found_callbacks", [])
        self.error_callbacks = kwargs.get("error_callbacks", [])

        if len(self._dictionary) < self.threads_count:
            self.threads_count = len(self._dictionary)

    def set_target(self, url):
        self._entries.clear()

        # If no scheme specified, unset it first
        if "://" not in url:
            url = f"{self.default_scheme or UNKNOWN}://{url}"
        if not url.endswith("/"):
            url += "/"

        parsed = urlparse(url)

        self.base_path = parsed.path
        if parsed.path.startswith("/"):
            self.base_path = parsed.path[1:]

        # Credentials in URL (https://[user]:[password]@website.com)
        if "@" in parsed.netloc:
            cred, parsed.netloc = parsed.netloc.split("@")
            self._requester.set_auth("basic", cred)

        host = parsed.netloc.split(":")[0]

        if parsed.scheme not in (UNKNOWN, "https", "http"):
            raise InvalidURLException(f"Unsupported URI scheme: {parsed.scheme}")

        # If no port specified, set default (80, 443)
        try:
            port = int(parsed.netloc.split(":")[1])

            if not 0 < port < 65536:
                raise ValueError
        except IndexError:
            port = STANDARD_PORTS.get(parsed.scheme, None)
        except ValueError:
            invalid_port = parsed.netloc.split(":")[1]
            raise InvalidURLException(f"Invalid port number: {invalid_port}")

        try:
            # If no scheme is found, detect it by port number
            scheme = (
                parsed.scheme
                if parsed.scheme != UNKNOWN
                else detect_scheme(host, port)
            )
        except ValueError:
            # If the user neither provides the port nor scheme, guess them based
            # on standard website characteristics
            scheme = detect_scheme(host, 443)
            port = STANDARD_PORTS[scheme]

        self.base_url = f"{scheme}://{host}"

        if port != STANDARD_PORTS[scheme]:
            self.base_url += f":{port}"

        self.base_url += "/"
        self._requester.set_url(self.base_url)

    @property
    def url(self):
        return self.base_url + self.base_path

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
            "prefixes": {},
            "suffixes": {},
        }

        # Default scanners (wildcard testers)
        self.default_scanners = [
            Scanner(self._requester, "/"),
            Scanner(self._requester, WILDCARD_TEST_POINT_MARKER),
        ]

        if self.exclude_response:
            self.default_scanners.append(
                Scanner(
                    self._requester, custom=self.exclude_response, tested=self.scanners
                )
            )

        for prefix in self.prefixes + DEFAULT_TEST_PREFIXES:
            path = f"{self.base_path}{prefix}{WILDCARD_TEST_POINT_MARKER}"
            self.scanners["prefixes"][prefix] = Scanner(
                self._requester, path, tested=self.scanners
            )

        for suffix in self.suffixes + DEFAULT_TEST_SUFFIXES:
            path = f"{self.base_path}{WILDCARD_TEST_POINT_MARKER}{suffix}"
            self.scanners["suffixes"][suffix] = Scanner(
                self._requester, path, tested=self.scanners
            )

        for extension in self._dictionary.extensions:
            if "." + extension not in self.scanners["suffixes"]:
                path = f"{self.base_path}{WILDCARD_TEST_POINT_MARKER}.{extension}"
                self.scanners["suffixes"]["." + extension] = Scanner(
                    self._requester, path, tested=self.scanners
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

        for prefix in self.prefixes:
            if path.startswith(prefix):
                yield self.scanners["prefixes"][prefix]

        for suffix in self.suffixes:
            if path.endswith(suffix):
                yield self.scanners["suffixes"][suffix]

        for extension in self._dictionary.extensions:
            if path.endswith("." + extension):
                yield self.scanners["suffixes"]["." + extension]

        for scanner in self.default_scanners:
            yield scanner

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

    def scan(self, path, scanners):
        # Avoid scanned paths from being re-scanned
        if path in self._entries:
            return

        # Pause if the request rate exceeded the maximum
        while self.is_rate_exceeded():
            time.sleep(0.1)

        self.increase_rate()
        self._entries.add(path)

        response = self._requester.request(path)

        for tester in scanners:
            # Check if the response is unique, not wildcard
            if not tester.check(path, response):
                for callback in self.not_found_callbacks:
                    callback(path, response)

                return

        try:
            for callback in self.match_callbacks:
                callback(path, response)
        except Exception as e:
            self.exc = e

        if self.crawl:
            for path in crawl(self.base_url, response):
                self.scan(path, self.get_scanners_for(path))

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

    def set_base_path_suffix(self, suffix):
        self.base_path = self._base_path + suffix

    def thread_proc(self):
        self._play_event.wait()

        while True:
            try:
                path = next(self._dictionary)
                scanners = self.get_scanners_for(path)
                full_path = self.base_path + path

                self.scan(full_path, scanners)

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
