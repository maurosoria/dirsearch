import random
import re
import socket
from urllib.parse import urlparse

import httpx

from lib.connection.asynchronous.response import Response
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


class HTTPXBearerAuth(httpx.Auth):
    def __init__(self, token: str) -> None:
        self.token = token

    def auth_flow(self, request: httpx.Request) -> any:
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


class Requester:
    def __init__(self) -> None:
        self._url = None
        self._proxy_cred = None
        self._rate = 0
        self.headers = CaseInsensitiveDict(options["headers"])
        self.agents = []

        if options["random_agents"]:
            self._fetch_agents()

        # Guess the mime type of request data if not specified
        if options["data"] and "content-type" not in self.headers:
            self.set_header("content-type", guess_mimetype(options["data"]))

        socket_options = []
        if options["network_interface"]:
            socket_options.append(
                (
                    socket.SOL_SOCKET,
                    socket.SO_BINDTODEVICE,
                    options["network_interface"].encode("utf-8"),
                )
            )

        transport = httpx.AsyncHTTPTransport(
            # FIXME: max_connections != thread_count
            limits=httpx.Limits(max_connections=options["thread_count"]),
            socket_options=socket_options,
        )

        cert = (options["cert_file"], options["key_file"])

        self.session = httpx.AsyncClient(
            verify=False,
            cert=cert if cert[0] and cert[1] else None,
            mounts={"http://": transport, "https://": transport},
            timeout=httpx.Timeout(
                timeout=options["timeout"],
                pool=None,
            ),
        )

    def _fetch_agents(self) -> None:
        self.agents = FileUtils.get_lines(
            FileUtils.build_path(SCRIPT_PATH, "db", "user-agents.txt")
        )

    def set_url(self, url: str) -> None:
        self._url = url

    def set_header(self, key: str, value: str) -> None:
        self.headers[key] = value.lstrip()

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
                pass  # TODO: HttpNtlmAuth

    def set_proxy(self, proxy: str) -> None:
        if not proxy:
            return

        if not proxy.startswith(PROXY_SCHEMES):
            proxy = f"http://{proxy}"

        if self._proxy_cred and "@" not in proxy:
            # socks5://localhost:9050 => socks5://[credential]@localhost:9050
            proxy = proxy.replace("://", f"://{self._proxy_cred}@", 1)

        self.session.proxies = {"https": proxy}
        if not proxy.startswith("https://"):
            self.session.proxies["http"] = proxy

    def set_proxy_auth(self, credential: str) -> None:
        self._proxy_cred = credential

    # :path: is expected not to start with "/"
    async def request(self, path: str, proxy: str = None) -> Response:
        # TODO: request rate limit
        # Pause if the request rate exceeded the maximum
        # while self.is_rate_exceeded():
        #     await asyncio.sleep(0.1)

        # self.increase_rate()

        err_msg = None

        # Safe quote all special characters to prevent them from being encoded
        url = safequote(self._url + path if self._url else path)
        parsed_url = urlparse(url)

        # Why using a loop instead of max_retries argument? Check issue #1009
        for _ in range(options["max_retries"] + 1):
            try:
                try:
                    proxy = proxy or random.choice(options["proxies"])
                    self.set_proxy(proxy)
                except IndexError:
                    pass

                if self.agents:
                    self.set_header("user-agent", random.choice(self.agents))

                # Use "target" extension to avoid the URL path from being normalized
                request = self.session.build_request(
                    options["http_method"],
                    # url.removesuffix(parsed_url.path),
                    url,
                    headers=self.headers,
                    data=options["data"],
                )
                if p := parsed_url.path:
                    request.extensions = {"target": p.encode()}

                xresponse = await self.session.send(
                    request,
                    stream=True,
                    follow_redirects=options["follow_redirects"],
                )
                response = await Response.create(xresponse)
                await xresponse.aclose()

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
                    # Prevent from re-using it in the future
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
                    httpx.ConnectTimeout,
                    httpx.ReadTimeout,
                    socket.timeout,
                ):
                    err_msg = f"Request timeout: {url}"
                else:
                    err_msg = f"There was a problem in the request to: {url}"

        raise RequestException(err_msg)

    def is_rate_exceeded(self):
        return self._rate >= options["max_rate"] > 0

    def decrease_rate(self):
        self._rate -= 1

    def increase_rate(self):
        self._rate += 1

    @property
    @cached(RATE_UPDATE_DELAY)
    def rate(self):
        return self._rate
