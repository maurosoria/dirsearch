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

import hashlib
import logging
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING
from logging.handlers import RotatingFileHandler

from lib.core.log_config import LogConfig
from lib.utils.command import REDACTED_VALUE

if TYPE_CHECKING:
    from lib.connection.response import BaseResponse


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


MAX_LOG_DIGEST_BYTES = 64 * 1024


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

    def response(
        self, method: str, response: "BaseResponse", *, backend: str,
        filter_reason: str | None = None,
    ) -> None:
        """Log bounded capture evidence, never bodies or arbitrary headers.

        Large captures hash at most a 64 KiB prefix, labelled separately from
        complete retained-capture hashes. Native exclusions carry metadata only.
        """
        if not self.isEnabledFor(logging.INFO):
            return
        digest = sample = "unavailable"
        hashed_length = 0
        if filter_reason is None:
            hashed_length = min(len(response.body), MAX_LOG_DIGEST_BYTES)
            captured_hash = hashlib.sha256(memoryview(response.body)[:hashed_length]).hexdigest()
            if len(response.body) <= MAX_LOG_DIGEST_BYTES:
                digest = captured_hash
            else:
                sample = captured_hash
        self.response_metadata(
            method, response.url, backend=backend, status=response.status,
            headers=response.headers, http_version=response.http_version,
            length=response.length, retained_length=len(response.body),
            body_complete=response.body_complete, history=response.history,
            final_url=response.final_url, filter_reason=filter_reason,
            retained_sha256=digest, sample_sha256=sample, hashed_length=hashed_length,
        )

    def response_metadata(
        self, method: str, url: str, *, backend: str, status: int,
        headers: Mapping[str, str], http_version: str | None, length: int,
        retained_length: int, body_complete: bool, history: Sequence[str],
        final_url: str, filter_reason: str | None = None,
        retained_sha256: str = "unavailable", sample_sha256: str = "unavailable",
        hashed_length: int = 0,
    ) -> None:
        """Accept compact transport metadata without a decoded response object."""
        if not self.isEnabledFor(logging.INFO):
            return
        encoding = headers.get("content-encoding", "identity").lower()
        codings = [part.strip() for part in encoding.split(",")]
        safe_encoding = ",".join(codings) if all(
            part in {"identity", "gzip", "x-gzip", "deflate", "br", "zstd"}
            for part in codings
        ) else "other"
        redirect = headers.get("location", "").split("#", 1)[0].replace("\r", "").replace("\n", "")
        location = f" - LOCATION: {redirect}" if redirect else ""
        self.info(
            '"%s %s" %s - %sB%s - RESPONSE backend=%s http_version=%s '
            'content_encoding=%s retained_length=%s body_complete=%s '
            'retained_sha256=%s sample_sha256=%s hashed_length=%s '
            'redirect_hops=%s final_url=%s native_filter=%s',
            method, url.split("#", 1)[0], status, length, location, backend,
            http_version or "unknown", safe_encoding, retained_length,
            str(body_complete).lower(), retained_sha256, sample_sha256, hashed_length,
            len(history), final_url.split("#", 1)[0], filter_reason or "none",
        )

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
