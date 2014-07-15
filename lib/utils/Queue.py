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

try:
    import threading as _threading
except ImportError:
    import dummy_threading as _threading
from collections import deque
import heapq

class Queue(object):
    def __init__(self):
        self._init()
        self.mutex = _threading.Lock()
        self.not_empty = _threading.Event()

    def qsize(self):
        """Return the approximate size of the queue (not reliable!)."""
        try:
            self.mutex.acquire()
            n = self._qsize()
            return n
        finally:
            try:
                self.mutex.release()
            except:
                pass

    def empty(self):
        """Return True if the queue is empty, False otherwise (not reliable!)."""
        try:
            self.mutex.acquire()
            n = not self._qsize()
            return n
        finally:
            try:
                self.mutex.release()
            except:
                pass

    def put(self, item):
        try:
            self.mutex.acquire()
            if not self.not_empty.isSet():
                self.not_empty.set()
            self._put(item)
            
        finally:
            try:
                self.mutex.release()
            except:
                pass

    def get(self):
        try:
            self.mutex.acquire()
            while not self.not_empty.isSet():
                self.mutex.release()
                self.not_empty.wait()
                self.mutex.acquire()
            item = self._get()
            if self._qsize() == 0:
                self.not_empty.clear()
            return item
        finally:
            try:
                self.mutex.release()
            except:
                pass

    def _init(self):
        self.queue = deque()

    def _qsize(self, len=len):
        return len(self.queue)

    # Put a new item in the queue
    def _put(self, item):
        self.queue.append(item)

    # Get an item from the queue
    def _get(self):
        return self.queue.popleft()

