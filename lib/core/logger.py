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

import logging
import re
from logging.handlers import RotatingFileHandler

from lib.core.log_config import LogConfig
from lib.utils.command import REDACTED_VALUE


URL_USERINFO_PATTERN = re.compile(
    r"(?P<scheme>\b[a-zA-Z][a-zA-Z0-9+.-]*://)"
    r"(?P<userinfo>[^/\s?#\"'<>]+)@"
)
QUERY_VALUE_PATTERN = re.compile(
    r"(?P<prefix>[?&;])"
    r"(?P<key>[^=&;#\s\"'<>]*)="
    r"(?P<value>[^&;#\s\"'<>]*)"
)
BARE_QUERY_COMPONENT_PATTERN = re.compile(
    r"(?P<prefix>[?&;])"
    r"(?P<component>[^=&;#\s\"'<>]+)"
    r"(?=[&;#\s\"'<>]|$)"
)


def redact_log_text(text: str, *, proxy_auth: str | None = None) -> str:
    """Remove credentials and query values from rendered log output."""
    if proxy_auth:
        text = re.sub(
            rf"(?P<scheme>\b[a-zA-Z][a-zA-Z0-9+.-]*://)?"
            rf"{re.escape(str(proxy_auth))}(?=@)",
            lambda match: f'{match.group("scheme") or ""}{REDACTED_VALUE}',
            text,
        )

    text = URL_USERINFO_PATTERN.sub(
        lambda match: f'{match.group("scheme")}{REDACTED_VALUE}@',
        text,
    )
    text = QUERY_VALUE_PATTERN.sub(
        lambda match: (
            f'{match.group("prefix")}{match.group("key")}={REDACTED_VALUE}'
        ),
        text,
    )
    return BARE_QUERY_COMPONENT_PATTERN.sub(
        lambda match: f'{match.group("prefix")}{REDACTED_VALUE}',
        text,
    )


class RedactingFormatter(logging.Formatter):
    def __init__(self, *, proxy_auth: str | None = None) -> None:
        super().__init__('%(asctime)s [%(levelname)s] %(message)s')
        self._proxy_auth = proxy_auth

    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record), proxy_auth=self._proxy_auth)


class _RunFileHandler(RotatingFileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        # Handler.handle() and FileHandler.close() share the handler lock.
        # A record dispatched before close may acquire it afterwards. Append
        # mode would otherwise reopen the file, including during rollover.
        if not self._closed:
            super().emit(record)


class RunLogger(logging.Logger):
    """One invocation's file handler, borrowed by its runtime components.

    Construct directly instead of registering a process-global named logger.
    No file means disabled logging, with no fallback to the host/root logger.
    The controller closes this resource after its borrowers have cleaned up.
    Standalone components may use their own disabled, resource-free instance.
    """

    def __init__(self, config: LogConfig = LogConfig()) -> None:
        super().__init__(__name__, level=logging.DEBUG)
        self.propagate = False
        self.disabled = True
        self._file_handler: _RunFileHandler | None = None
        if config.file_path:
            handler = _RunFileHandler(
                config.file_path, maxBytes=config.max_bytes, backupCount=1,
            )
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(RedactingFormatter(proxy_auth=config.proxy_auth))
            self._file_handler = handler
            self.addHandler(handler)
            self.disabled = False

    def close(self) -> None:
        """Stop intake and drain the handler's active write; safe to repeat.

        The standard logging lock covers local file I/O only, never network or
        worker joins. Removing the handler also releases the formatter's policy.
        """
        self.disabled = True
        handler = self._file_handler
        if handler is not None:
            self.removeHandler(handler)
            try:
                handler.close()
            finally:
                self._file_handler = None
