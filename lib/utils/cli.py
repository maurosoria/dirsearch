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

import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import NoReturn


def print_diagnostic(message: object) -> None:
    print(message, file=sys.stderr)


def fail(*messages: object) -> NoReturn:
    for message in messages:
        print_diagnostic(message)
    raise SystemExit(1)


@contextmanager
def cli_interrupts(on_interrupt: Callable[[], None]) -> Iterator[None]:
    """Borrow SIGINT/SIGTERM for one CLI execution, then restore their owners.

    Enter only on the main thread, after scan preparation. ExitStack rolls back
    partial installation and attempts both restorations even if one fails. This
    is an exclusive CLI scope, not a concurrent-controller signal dispatcher.
    Force-quit via os._exit still deliberately bypasses normal unwinding.
    """
    def handle_interrupt(_number, _frame):
        on_interrupt()

    with ExitStack() as cleanup:
        for number in (signal.SIGINT, signal.SIGTERM):
            previous = signal.signal(number, handle_interrupt)
            cleanup.callback(signal.signal, number, previous)
        yield
