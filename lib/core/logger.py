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

from lib.core.data import options
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


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.disabled = True


def redact_log_text(text: str) -> str:
    """Remove credentials and query values from rendered log output."""
    proxy_auth = options.get("proxy_auth")
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
    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record))


def enable_logging() -> None:
    logger.disabled = False
    formatter = RedactingFormatter('%(asctime)s [%(levelname)s] %(message)s')
    handler = RotatingFileHandler(options["log_file"], maxBytes=options["log_file_size"])
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
