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

from __future__ import annotations

import asyncio
import http.client
import random
import re
import socket
from ssl import SSLError
import threading
import time
from typing import Any, Generator
from urllib.parse import urlparse

import httpx
import requests
from requests.auth import AuthBase, HTTPBasicAuth, HTTPDigestAuth
from requests.packages import urllib3
from requests_ntlm import HttpNtlmAuth
from httpx_ntlm import HttpNtlmAuth as HttpxNtlmAuth
from requests_toolbelt.adapters.socket_options import SocketOptionsAdapter

from lib.connection.dns import cached_getaddrinfo
from lib.connection.response import AsyncResponse, Response
from lib.core.data import options
from lib.core.decorators import cached
from lib.core.exceptions import RequestException
from lib.core.logger import logger
from lib.core.settings import (
    PROXY_SCHEMES,
    RATE_UPDATE_DELAY,
    READ_RESPONSE_ERROR_REGEX,
    SCRIPT_PATH,
)
from lib.core.structures import CaseInsensitiveDict
from lib.utils.common import safequote
from lib.utils.file import FileUtils
from lib.utils.mimetype import guess_mimetype

# Disable InsecureRequestWarning from urllib3
urllib3.disable_warnings(urllib3.exceptions.SecurityWarning)
# Use custom `socket.getaddrinfo` for `requests` which supports DNS caching
socket.getaddrinfo = cached_getaddrinfo


class BaseRequester:
    def __init__(self) -> None:
        self._url: str = ""
        self._rate = 0
        self.proxy_cred = options["proxy_auth"]
        self.headers = CaseInsensitiveDict(options["headers"])
        self.agents: list[str] = []
        self.session = None

        self._cert = None
        if options["cert_file"] and options["key_file"]:
            self._cert = (options["cert_file"], options["key_file"])

        self._socket_options = []
        if options["network_interface"]:
            self._socket_options.append(
                (
                    socket.SOL_SOCKET,
                    socket.SO_BINDTODEVICE,
                    options["network_interface"].encode("utf-8"),
                )
            )

        if options["random_agents"]:
            self._fetch_agents()

        # Guess the mime type of request data if not specified
        if options["data"] and "content-type" not in self.headers:
            self.set_header("content-type", guess_mimetype(options["data"]))

    def _fetch_agents(self) -> None:
        self.agents = FileUtils.get_lines(
            FileUtils.build_path(SCRIPT_PATH, "db", "user-agents.txt")
        )

    def set_url(self, url: str) -> None:
        self._url = url

    def set_header(self, key: str, value: str) -> None:
        self.headers[key] = value.lstrip()

    def is_rate_exceeded(self) -> bool:
        return self._rate >= options["max_rate"] > 0

    def decrease_rate(self) -> None:
        self._rate -= 1

    def increase_rate(self) -> None:
        self._rate += 1
        threading.Timer(1, self.decrease_rate).start()

    @property
    @cached(RATE_UPDATE_DELAY)
    def rate(self) -> int:
        return self._rate


class HTTPBearerAuth(AuthBase):
    def __init__(self, token: str) -> None:
        self.token = token

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request


class Requester(BaseRequester):
    def __init__(self):
        super().__init__()

        self.session = requests.Session()
        self.session.verify = False
        self.session.cert = self._cert

        for scheme in ("http://", "https://"):
            self.session.mount(
                scheme,
                SocketOptionsAdapter(
                    max_retries=0,
                    pool_maxsize=options["thread_count"],
                    socket_options=self._socket_options,
                ),
            )

        if options["auth"]:
            self.set_auth(options["auth_type"], options["auth"])

    def set_auth(self, type: str, credential: str) -> None:
        if type in ("bearer", "jwt"):
            self.session.auth = HTTPBearerAuth(credential)
        else:
            try:
                user, password = credential.split(":", 1)
            except ValueError:
                user = credential
                password = ""

            if type == "basic":
                self.session.auth = HTTPBasicAuth(user, password)
            elif type == "digest":
                self.session.auth = HTTPDigestAuth(user, password)
            else:
                self.session.auth = HttpNtlmAuth(user, password)

    # :path: is expected not to start with "/"
    def request(self, path: str, proxy: str | None = None) -> Response:
        # Pause if the request rate exceeded the maximum
        while self.is_rate_exceeded():
            time.sleep(0.1)

        self.increase_rate()

        err_msg = None
        url = self._url + safequote(path)

        # Why using a loop instead of max_retries argument? Check issue #1009
        for _ in range(options["max_retries"] + 1):
            try:
                proxies = {}
                try:
                    proxy_url = proxy or random.choice(options["proxies"])
                    if not proxy_url.startswith(PROXY_SCHEMES):
                        proxy_url = f"http://{proxy_url}"

                    if self.proxy_cred and "@" not in proxy_url:
                        # socks5://localhost:9050 => socks5://[credential]@localhost:9050
                        proxy_url = proxy_url.replace("://", f"://{self.proxy_cred}@", 1)

                    proxies["https"] = proxy_url
                    if not proxy_url.startswith("https://"):
                        proxies["http"] = proxy_url
                except IndexError:
                    pass

                if self.agents:
                    self.set_header("user-agent", random.choice(self.agents))

                # Use prepared request to avoid the URL path from being normalized
                # Reference: https://github.com/psf/requests/issues/5289
                request = requests.Request(
                    options["http_method"],
                    url,
                    headers=self.headers,
                    data=options["data"],
                )
                prep = self.session.prepare_request(request)
                prep.url = url

                origin_response = self.session.send(
                    prep,
                    allow_redirects=options["follow_redirects"],
                    timeout=options["timeout"],
                    proxies=proxies,
                    stream=True,
                )
                response = Response(url, origin_response)

                log_msg = f'"{options["http_method"]} {response.url}" {response.status} - {response.length}B'

                if response.redirect:
                    log_msg += f" - LOCATION: {response.redirect}"

                logger.info(log_msg)

                return response

            except Exception as e:
                logger.exception(e)

                if e == socket.gaierror:
                    err_msg = "Couldn't resolve DNS"
                elif "SSLError" in str(e):
                    err_msg = "Unexpected SSL error"
                elif "TooManyRedirects" in str(e):
                    err_msg = f"Too many redirects: {url}"
                elif "ProxyError" in str(e):
                    if proxy:
                        err_msg = f"Error with the proxy: {proxy}"
                    else:
                        err_msg = "Error with the system proxy"
                    # Prevent from reusing it in the future
                    if proxy in options["proxies"] and len(options["proxies"]) > 1:
                        options["proxies"].remove(proxy)
                elif "InvalidURL" in str(e):
                    err_msg = f"Invalid URL: {url}"
                elif "InvalidProxyURL" in str(e):
                    err_msg = f"Invalid proxy URL: {proxy}"
                elif "ConnectionError" in str(e):
                    err_msg = f"Cannot connect to: {urlparse(url).netloc}"
                elif re.search(READ_RESPONSE_ERROR_REGEX, str(e)):
                    err_msg = f"Failed to read response body: {url}"
                elif "Timeout" in str(e) or e in (
                    http.client.IncompleteRead,
                    socket.timeout,
                ):
                    err_msg = f"Request timeout: {url}"
                else:
                    err_msg = f"There was a problem in the request to: {url}"

        raise RequestException(err_msg)


class HTTPXBearerAuth(httpx.Auth):
    def __init__(self, token: str) -> None:
        self.token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, None, None]:
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


class ProxyRoatingTransport(httpx.AsyncBaseTransport):
    def __init__(self, proxies: list[str], **kwargs: Any) -> None:
        self._transports = [
            httpx.AsyncHTTPTransport(proxy=proxy, **kwargs) for proxy in proxies
        ]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request.extensions["target"] = str(request.url).encode()
        transport = random.choice(self._transports)
        return await transport.handle_async_request(request)


class AsyncRequester(BaseRequester):
    def __init__(self) -> None:
        super().__init__()

        tpargs = {
            "verify": False,
            "cert": self._cert,
            "limits": httpx.Limits(max_connections=options["thread_count"]),
            "socket_options": self._socket_options,
        }
        transport = (
            ProxyRoatingTransport(
                [self.parse_proxy(p) for p in options["proxies"]], **tpargs
            )
            if options["proxies"]
            else httpx.AsyncHTTPTransport(**tpargs)
        )

        self.session = httpx.AsyncClient(
            mounts={"all://": transport},
            timeout=httpx.Timeout(options["timeout"]),
        )
        self.replay_session = None

        if options["auth"]:
            self.set_auth(options["auth_type"], options["auth"])

    def parse_proxy(self, proxy: str) -> str:
        if not proxy:
            return None

        if not proxy.startswith(PROXY_SCHEMES):
            proxy = f"http://{proxy}"

        if self.proxy_cred and "@" not in proxy:
            # socks5://localhost:9050 => socks5://[credential]@localhost:9050
            proxy = proxy.replace("://", f"://{self.proxy_cred}@", 1)

        return proxy

    def set_auth(self, type: str, credential: str) -> None:
        if type in ("bearer", "jwt"):
            self.session.auth = HTTPXBearerAuth(credential)
        else:
            try:
                user, password = credential.split(":", 1)
            except ValueError:
                user = credential
                password = ""

            if type == "basic":
                self.session.auth = httpx.BasicAuth(user, password)
            elif type == "digest":
                self.session.auth = httpx.DigestAuth(user, password)
            else:
                self.session.auth = HttpxNtlmAuth(user, password)

    async def replay_request(self, path: str, proxy: str) -> AsyncResponse:
        if self.replay_session is None:
            transport = httpx.AsyncHTTPTransport(
                verify=False,
                cert=self._cert,
                limits=httpx.Limits(max_connections=options["thread_count"]),
                proxy=self.parse_proxy(proxy),
                socket_options=self._socket_options,
            )
            self.replay_session = httpx.AsyncClient(
                mounts={"all://": transport},
                timeout=httpx.Timeout(options["timeout"]),
            )
        return await self.request(path, self.replay_session, replay=True)

    # :path: is expected not to start with "/"
    async def request(
        self, path: str, session: httpx.AsyncClient | None = None, replay: bool = False
    ) -> AsyncResponse:
        while self.is_rate_exceeded():
            await asyncio.sleep(0.1)

        self.increase_rate()

        err_msg = None
        url = self._url + safequote(path)
        session = session or self.session

        for _ in range(options["max_retries"] + 1):
            try:
                if self.agents:
                    self.set_header("user-agent", random.choice(self.agents))

                # Use "target" extension to avoid the URL path from being normalized
                request = session.build_request(
                    options["http_method"],
                    url,
                    headers=self.headers,
                    data=options["data"],
                    extensions={"target": (url if replay else f"/{safequote(path)}").encode()},
                )

                xresponse = await session.send(
                    request,
                    stream=True,
                    follow_redirects=options["follow_redirects"],
                )
                response = await AsyncResponse.create(url, xresponse)
                await xresponse.aclose()

                log_msg = f'"{options["http_method"]} {response.url}" {response.status} - {response.length}B'

                if response.redirect:
                    log_msg += f" - LOCATION: {response.redirect}"

                logger.info(log_msg)

                return response

            except Exception as e:
                logger.exception(e)

                if isinstance(e, httpx.ConnectError):
                    if str(e).startswith("[Errno -2]"):
                        err_msg = "Couldn't resolve DNS"
                    else:
                        err_msg = f"Cannot connect to: {urlparse(url).netloc}"
                elif isinstance(e, SSLError):
                    err_msg = "Unexpected SSL error"
                elif isinstance(e, httpx.TooManyRedirects):
                    err_msg = f"Too many redirects: {url}"
                elif isinstance(e, httpx.ProxyError):
                    err_msg = "Cannot establish the proxy connection"
                elif isinstance(e, httpx.InvalidURL):
                    err_msg = f"Invalid URL: {url}"
                elif isinstance(e, httpx.TimeoutException):
                    err_msg = f"Request timeout: {url}"
                elif isinstance(e, httpx.ReadError) or isinstance(e, httpx.DecodingError):  # not sure
                    err_msg = f"Failed to read response body: {url}"
                else:
                    err_msg = f"There was a problem in the request to: {url}"

        raise RequestException(err_msg)

    def increase_rate(self) -> None:
        self._rate += 1
        asyncio.get_running_loop().call_later(1, self.decrease_rate)
