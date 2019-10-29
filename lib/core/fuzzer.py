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

from lib.connection.request_exception import RequestException
from .path import *
from .scanner import *


class Fuzzer(object):
    def __init__(self, requester, dictionary, test_fail_path=None, threads=1, match_callbacks=None, not_found_callbacks=None,
                 error_callbacks=None):

        self.requester = requester
        self.dictionary = dictionary
        self.test_fail_path = test_fail_path
        self.base_path = self.requester.basePath
        self.threads = []
        self.threads_count = threads if len(self.dictionary) >= threads else len(self.dictionary)
        self.running = False
        self.scanners = {}
        self.default_scanner = None
        self.match_callbacks = match_callbacks or []
        self.not_found_callbacks = not_found_callbacks or []
        self.error_callbacks = error_callbacks or []
        self.matches = []
        self.errors = []

        # the following are set on start
        self.index = None
        self.running_threads_count = None
        self.play_event = None
        self.paused_semaphore = None
        self.exit = None

    def wait(self, timeout=None):
        for thread in self.threads:
            thread.join(timeout)

            if timeout is not None and thread.is_alive():
                return False

        return True

    def setup_scanners(self):
        if len(self.scanners) != 0:
            self.scanners = {}

        self.default_scanner = Scanner(self.requester, self.test_fail_path, "")
        self.scanners['/'] = Scanner(self.requester, self.test_fail_path, "/")

        for extension in self.dictionary.extensions:
            self.scanners[extension] = Scanner(self.requester, self.test_fail_path, "." + extension)

    def setup_threads(self):
        if len(self.threads) != 0:
            self.threads = []

        for thread in range(self.threads_count):
            newThread = threading.Thread(target=self.thread_proc)
            newThread.daemon = True
            self.threads.append(newThread)

    def get_scanner_for(self, path):
        if path.endswith('/'):
            return self.scanners['/']

        for extension in list(self.scanners.keys()):
            if path.endswith(extension):
                return self.scanners[extension]

        # By default, returns empty tester
        return self.default_scanner

    def start(self):
        # Setting up testers
        self.setup_scanners()
        # Setting up threads
        self.setup_threads()
        self.index = 0
        self.dictionary.reset()
        self.running_threads_count = len(self.threads)
        self.running = True
        self.play_event = threading.Event()
        self.paused_semaphore = threading.Semaphore(0)
        self.play_event.clear()
        self.exit = False

        for thread in self.threads:
            thread.start()

        self.play()

    def play(self):
        self.play_event.set()

    def pause(self):
        self.play_event.clear()
        for thread in self.threads:
            if thread.is_alive():
                self.paused_semaphore.acquire()

    def stop(self):
        self.running = False
        self.play()

    def scan(self, path):
        response = self.requester.request(path)
        result = None
        if self.get_scanner_for(path).scan(path, response):
            result = (None if response.status == 404 else response.status)
        return result, response

    def is_running(self):
        return self.running

    def finish_threads(self):
        self.running = False
        self.finishedEvent.set()

    def is_finished(self):
        return self.running_threads_count == 0

    def stop_thread(self):
        self.running_threads_count -= 1

    def thread_proc(self):
        self.play_event.wait()
        try:
            path = next(self.dictionary)
            while path is not None:
                try:
                    status, response = self.scan(path)
                    result = Path(path=path, status=status, response=response)

                    if status is not None:
                        self.matches.append(result)
                        for callback in self.match_callbacks:
                            callback(result)
                    else:
                        for callback in self.not_found_callbacks:
                            callback(result)
                    del status
                    del response

                except RequestException as e:

                    for callback in self.error_callbacks:
                        callback(path, e.args[0]['message'])

                    continue

                finally:
                    if not self.play_event.isSet():
                        self.paused_semaphore.release()
                        self.play_event.wait()

                    path = next(self.dictionary)  # Raises StopIteration when finishes

                    if not self.running:
                        break

        except StopIteration:
            return

        finally:
            self.stop_thread()
