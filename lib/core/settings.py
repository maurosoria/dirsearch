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

import os
import sys

from pathlib import Path

# Version format: <major version>.<minor version>.<revision>[.<month>]
VERSION = "0.4.2.2"

BANNER = f'''
  _|. _ _  _  _  _ _|_    v{VERSION}
 (_||| _) (/_(_|| (_| )
'''

SCRIPT_PATH = Path(__file__).parents[2]

IS_WINDOWS = sys.platform in ("win32", "msys")

DEFAULT_ENCODING = "utf-8"

NEW_LINE = os.linesep

INVALID_CHARS_FOR_WINDOWS_FILENAME = ('"', '*', '<', '>', '?', '\\', '|', '/', ':')

OUTPUT_FORMATS = ("simple", "plain", "json", "xml", "md", "csv", "html", "sqlite")

COMMON_EXTENSIONS = ("php", "jsp", "asp", "aspx", "do", "action", "cgi", "html", "htm", "js", "json", "tar.gz", "bak")

AUTHENTICATION_TYPES = ("basic", "digest", "bearer", "ntlm", "jwt", "oauth2")

PROXY_SCHEMES = ("http://", "https://", "socks5://", "socks5h://", "socks4://", "socks4a://")

INSECURE_CSV_CHARS = ('+', '-', '=', '@')

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36"

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept-Language": "*",
    "Accept-Encoding": "*",
    "Keep-Alive": "timeout=15, max=1000",
    "Cache-Control": "max-age=0",
}

DEFAULT_SESSION_FILE = "session.json"

EXCLUDED_EXPORT_VARIABLES = ("output", "threads_lock", "report", "report_manager", "requester", "fuzzer")

EXTENSION_TAG = "%ext%"

EXTENSION_REGEX = r"\w[.][a-zA-Z0-9]{2,5}"

MAX_REDIRECTS = 5

MAX_NUMBER_OF_THREADS = 100

SOCKET_TIMEOUT = 6

RATE_UPDATE_DELAY = 0.15

CHUNK_SIZE = 8192

TEST_PATH_LENGTH = 6
