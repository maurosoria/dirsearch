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

import http.client
import random
import re
import socket
import ssl
import threading
import time
from typing import Any, Generator
from urllib.parse import urlparse

import httpx
import requests
from httpx._transports.default import AsyncResponseStream, map_httpcore_exceptions
from requests.auth import AuthBase, HTTPBasicAuth, HTTPDigestAuth
from requests.packages import urllib3
from urllib3 import connection as urllib3_connection
from urllib3 import connectionpool as urllib3_connectionpool
from urllib3 import poolmanager as urllib3_poolmanager
from urllib3.contrib import socks as urllib3_socks
from requests_ntlm import HttpNtlmAuth
from httpx_ntlm import HttpNtlmAuth as HttpxNtlmAuth
from requests_toolbelt.adapters.socket_options import SocketOptionsAdapter

try:
    from ssl import SSLCertVerificationError
except ImportError:
    SSLCertVerificationError = None

from lib.connection.dns import DNSResolver
from lib.connection.proxy import (
    PROXY_AUTHENTICATION_REQUIRED,
    format_proxy_error,
    proxy_error_status,
)
from lib.connection.rate_limiter import RequestRateLimiter
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
from lib.parse.url import append_query_string
from lib.utils.common import safequote
from lib.utils.file import FileUtils
from lib.utils.mimetype import guess_mimetype

# Disable InsecureRequestWarning from urllib3
urllib3.disable_warnings(urllib3.exceptions.SecurityWarning)
_request_target_state = threading.local()


def _join_request_target(base_url: str, quoted_path: str) -> str:
    base_path = urlparse(base_url).path or "/"
    target = "/" if base_path == "/" else f"{base_path.rstrip('/')}/"
    return target + quoted_path.lstrip("/")


# urllib3 encodes origin-form targets before writing them to the socket. Keep
# the already-quoted dirsearch target for direct requests so fuzzed characters
# such as malformed percent escapes and backslashes reach the server unchanged.
class _ScopedDNSConnection:
    def __init__(self, *args, dns_resolver: DNSResolver | None = None, **kwargs):
        self._dns_resolver = dns_resolver
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        if self._dns_resolver is None:
            return super()._new_conn()

        original_host = self._dns_host
        self._dns_host = self._dns_resolver.resolve(original_host, self.port)
        try:
            return super()._new_conn()
        finally:
            self._dns_host = original_host


class _PathPreservingRequestMixin:
    def request(self, method, url, body=None, headers=None, *args, **kwargs):
        target = getattr(_request_target_state, "target", None)
        if target:
            url = target

        return super().request(method, url, body, headers, *args, **kwargs)


class PathPreservingHTTPConnection(
    _PathPreservingRequestMixin,
    _ScopedDNSConnection,
    urllib3_connection.HTTPConnection,
):
    pass


class PathPreservingHTTPSConnection(
    _PathPreservingRequestMixin,
    _ScopedDNSConnection,
    urllib3_connection.HTTPSConnection,
):
    pass


class PathPreservingSOCKSConnection(
    _PathPreservingRequestMixin,
    urllib3_socks.SOCKSConnection,
):
    pass


class PathPreservingSOCKSHTTPSConnection(
    _PathPreservingRequestMixin,
    urllib3_socks.SOCKSHTTPSConnection,
):
    pass


class PathPreservingHTTPConnectionPool(urllib3_connectionpool.HTTPConnectionPool):
    ConnectionCls = PathPreservingHTTPConnection


class PathPreservingHTTPSConnectionPool(urllib3_connectionpool.HTTPSConnectionPool):
    ConnectionCls = PathPreservingHTTPSConnection


class PathPreservingSOCKSConnectionPool(urllib3_socks.SOCKSHTTPConnectionPool):
    ConnectionCls = PathPreservingSOCKSConnection


class PathPreservingSOCKSHTTPSConnectionPool(
    urllib3_socks.SOCKSHTTPSConnectionPool
):
    ConnectionCls = PathPreservingSOCKSHTTPSConnection


class PathPreservingPoolManager(urllib3_poolmanager.PoolManager):
    def __init__(self, *args, dns_resolver: DNSResolver, **kwargs):
        self._dns_resolver = dns_resolver
        super().__init__(*args, **kwargs)
        self.pool_classes_by_scheme = {
            "http": PathPreservingHTTPConnectionPool,
            "https": PathPreservingHTTPSConnectionPool,
        }

    def _new_pool(self, scheme, host, port, request_context=None):
        pool = super()._new_pool(scheme, host, port, request_context)
        pool.conn_kw["dns_resolver"] = self._dns_resolver
        return pool


class PathPreservingSocketOptionsAdapter(SocketOptionsAdapter):
    def __init__(self, **kwargs):
        self._dns_resolver = kwargs.pop("dns_resolver")
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PathPreservingPoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            socket_options=self.socket_options,
            dns_resolver=self._dns_resolver,
        )

    def request_url(self, request: requests.PreparedRequest, proxies: dict[str, str]) -> str:
        target = getattr(request, "_dirsearch_request_target", None)
        if not target:
            return super().request_url(request, proxies)

        request_url = super().request_url(request, proxies)
        if request_url.startswith("/"):
            return target

        parsed_url = urlparse(request_url)
        return f"{parsed_url.scheme}://{parsed_url.netloc}{target}"

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        manager = super().proxy_manager_for(proxy, **proxy_kwargs)
        if proxy.lower().startswith("socks"):
            manager.pool_classes_by_scheme = {
                "http": PathPreservingSOCKSConnectionPool,
                "https": PathPreservingSOCKSHTTPSConnectionPool,
            }
        else:
            manager.pool_classes_by_scheme = {
                "http": PathPreservingHTTPConnectionPool,
                "https": PathPreservingHTTPSConnectionPool,
            }
        return manager

    def send(self, request, **kwargs):
        target = getattr(request, "_dirsearch_request_target", None)
        proxies = kwargs.get("proxies") or {}
        if not target:
            return super().send(request, **kwargs)

        _request_target_state.target = self.request_url(request, proxies)
        try:
            return super().send(request, **kwargs)
        finally:
            del _request_target_state.target


def _is_requests_ssl_error(exc: Exception) -> bool:
    """Check if the exception is a requests-wrapped SSL error.

    The requests library wraps ssl.SSLError inside requests.exceptions.SSLError,
    so we need to inspect the exception chain to detect SSL errors that aren't
    direct instances of ssl.SSLError.
    """
    if isinstance(exc, requests.exceptions.SSLError):
        return True

    # Check the exception cause chain (PEP 3134)
    cause = exc.__cause__
    while cause is not None:
        if isinstance(cause, ssl.SSLError):
            return True
        cause = cause.__cause__

    # Also check __context__ for implicit chaining
    context = exc.__context__
    while context is not None:
        if isinstance(context, ssl.SSLError):
            return True
        context = context.__context__

    return False


def _iter_exception_chain(exc: BaseException) -> Generator[BaseException, None, None]:
    seen = set()
    pending = [exc]

    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue

        seen.add(id(current))
        yield current

        for attr in ("__cause__", "__context__"):
            chained = getattr(current, attr, None)
            if chained is not None:
                pending.append(chained)


def _find_ssl_error(exc: Exception) -> ssl.SSLError | None:
    for current in _iter_exception_chain(exc):
        if isinstance(current, ssl.SSLError):
            return current

    return None


def _is_timeout_error(exc: Exception) -> bool:
    for current in _iter_exception_chain(exc):
        if isinstance(
            current,
            (
                requests.exceptions.Timeout,
                urllib3.exceptions.TimeoutError,
                httpx.TimeoutException,
                socket.timeout,
            ),
        ):
            return True

        message = str(current).lower()
        if "timed out" in message or "timeout" in message:
            return True

    return False


def _is_response_read_error(exc: Exception) -> bool:
    for current in _iter_exception_chain(exc):
        if isinstance(
            current,
            (
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ContentDecodingError,
                requests.exceptions.StreamConsumedError,
                requests.exceptions.UnrewindableBodyError,
                httpx.DecodingError,
                httpx.ReadError,
                httpx.RemoteProtocolError,
            ),
        ):
            return True

        if re.search(READ_RESPONSE_ERROR_REGEX, type(current).__name__):
            return True

    return False


def _is_ssl_error(exc: Exception) -> bool:
    return isinstance(exc, requests.exceptions.SSLError) or _find_ssl_error(exc) is not None


def _format_ssl_error(exc: Exception, url: str = "") -> str:
    """Format SSL error with specific, actionable error messages.

    Provides detailed error messages based on the specific type of SSL error
    instead of a generic 'Unexpected SSL error' message. This helps users
    diagnose and fix SSL-related issues.
    """
    # Resolve the underlying ssl.SSLError from the exception chain
    ssl_exc = _find_ssl_error(exc)

    err_detail = str(ssl_exc or exc)

    # Certificate verification errors
    if SSLCertVerificationError is not None and isinstance(ssl_exc, SSLCertVerificationError):
        if "self signed certificate" in err_detail.lower():
            msg = f"SSL certificate verification failed (self-signed certificate): {url}"
        elif "certificate has expired" in err_detail.lower():
            msg = f"SSL certificate verification failed (certificate expired): {url}"
        elif "certificate is not yet valid" in err_detail.lower():
            msg = f"SSL certificate verification failed (certificate not yet valid): {url}"
        elif "unable to get local issuer certificate" in err_detail.lower():
            msg = f"SSL certificate verification failed (missing local issuer certificate): {url}"
        elif "hostname" in err_detail.lower() and "match" in err_detail.lower():
            msg = f"SSL certificate verification failed (hostname mismatch): {url}"
        else:
            msg = f"SSL certificate verification failed: {err_detail}"
        logger.warning(f"SSL certificate error: {err_detail}")
        return msg

    # SSL handshake / protocol errors
    if ssl_exc is not None:
        err_lib = getattr(ssl_exc, "library", "")
        err_reason = getattr(ssl_exc, "reason", "")

        if "wrong version" in err_detail.lower() or "unsupported protocol" in err_detail.lower():
            msg = f"SSL protocol version mismatch: {url}"
        elif "handshake" in err_detail.lower():
            msg = f"SSL handshake failed: {url}"
        elif "no shared cipher" in err_detail.lower() or "no ciphers" in err_detail.lower():
            msg = f"SSL handshake failed (no shared cipher suites): {url}"
        elif err_lib == "SSL" and "EOF" in err_detail:
            msg = f"SSL connection terminated unexpectedly: {url}"
        elif "CERTIFICATE_VERIFY_FAILED" in err_detail:
            msg = f"SSL certificate verification failed: {url}"
        else:
            msg = f"SSL error ({err_reason or err_lib or 'unknown'}): {err_detail}"

        logger.warning(f"SSL error for {url}: library={err_lib}, reason={err_reason}, detail={err_detail}")
        return msg

    # Fallback for wrapped SSL errors where we can't get the underlying exception
    if "CERTIFICATE_VERIFY_FAILED" in err_detail:
        msg = f"SSL certificate verification failed: {url}"
    elif "wrong version" in err_detail.lower():
        msg = f"SSL protocol version mismatch: {url}"
    else:
        msg = f"SSL error: {err_detail}"

    logger.warning(f"SSL error for {url}: {err_detail}")
    return msg


class BaseRequester:
    def __init__(self) -> None:
        self._url: str = ""
        self._query: str = ""
        self._dns_resolver = DNSResolver()
        self._rate_limiter = RequestRateLimiter()
        self.proxy_cred = options["proxy_auth"]
        self.headers = CaseInsensitiveDict(options["headers"])
        self.agents: list[str] = []
        self.session = None
        self._configured_auth = None

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

    def set_query(self, query: str) -> None:
        self._query = query

    def set_ip(self, host: str, port: int, address: str) -> None:
        self._dns_resolver.add_override(host, port, address)

    def request_path(self, path: str) -> str:
        return append_query_string(path, getattr(self, "_query", ""))

    def set_header(self, key: str, value: str) -> None:
        self.headers[key] = value.lstrip()

    def reset_auth(self) -> None:
        self.session.auth = self._configured_auth

    def wait_for_rate_limit(self) -> None:
        self._rate_limiter.wait(options["max_rate"])

    @property
    @cached(RATE_UPDATE_DELAY)
    def rate(self) -> int:
        return self._rate_limiter.rate


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
                PathPreservingSocketOptionsAdapter(
                    max_retries=0,
                    pool_maxsize=options["thread_count"],
                    socket_options=self._socket_options,
                    dns_resolver=self._dns_resolver,
                ),
            )

        if options["auth"]:
            self.set_auth(options["auth_type"], options["auth"])
        self._configured_auth = self.session.auth

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

    def close(self) -> None:
        self.session.close()

    # :path: is expected not to start with "/"
    def request(self, path: str, proxy: str | None = None) -> Response:
        self.wait_for_rate_limit()

        err_msg = None
        request_path = self.request_path(path)
        quoted_request_path = safequote(request_path)
        url = self._url + quoted_request_path

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

                    proxies["http"] = proxy_url
                    proxies["https"] = proxy_url
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
                prep._dirsearch_request_target = _join_request_target(
                    self._url, quoted_request_path
                )

                start_time = time.perf_counter()
                origin_response = self.session.send(
                    prep,
                    allow_redirects=options["follow_redirects"],
                    timeout=options["timeout"],
                    proxies=proxies,
                    stream=True,
                )
                try:
                    if (
                        proxies
                        and origin_response.status_code
                        == PROXY_AUTHENTICATION_REQUIRED
                    ):
                        raise RequestException("Proxy authentication required")
                    response = Response(
                        url,
                        origin_response,
                        capture_full_body=bool(
                            options["save_response"]
                            or options["save_response_jsonl"]
                        ),
                    )
                finally:
                    origin_response.close()
                response.elapsed = time.perf_counter() - start_time

                log_msg = f'"{options["http_method"]} {response.url}" {response.status} - {response.length}B'

                if response.redirect:
                    log_msg += f" - LOCATION: {response.redirect}"

                logger.info(log_msg)

                return response

            except RequestException:
                raise
            except Exception as e:
                logger.exception(e)

                if e == socket.gaierror:
                    err_msg = "Couldn't resolve DNS"
                elif _is_timeout_error(e):
                    err_msg = f"Request timeout: {url}"
                elif _is_ssl_error(e):
                    err_msg = _format_ssl_error(e, url)
                elif isinstance(e, requests.exceptions.TooManyRedirects):
                    err_msg = f"Too many redirects: {url}"
                elif isinstance(e, requests.exceptions.ProxyError):
                    err_msg = format_proxy_error(e)
                    if proxy_error_status(e) in (407, 429):
                        raise RequestException(err_msg) from e
                elif "InvalidURL" in str(e):
                    err_msg = f"Invalid URL: {url}"
                elif "InvalidProxyURL" in str(e):
                    err_msg = f"Invalid proxy URL: {proxy}"
                elif _is_response_read_error(e):
                    err_msg = f"Failed to read response body: {url}"
                elif "ConnectionError" in str(e):
                    err_msg = f"Cannot connect to: {urlparse(url).netloc}"
                elif isinstance(e, http.client.IncompleteRead):
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


class ScopedDNSAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport,
        dns_resolver: DNSResolver,
    ) -> None:
        self._transport = transport
        self._dns_resolver = dns_resolver

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        port = request.url.port
        address = self._dns_resolver.resolve(host, port)
        if address == host:
            return await self._transport.handle_async_request(request)

        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = host

        resolved_request = httpx.Request(
            request.method,
            request.url.copy_with(host=address),
            headers=request.headers.raw,
            stream=request.stream,
            extensions=extensions,
        )
        return await self._transport.handle_async_request(resolved_request)

    async def aclose(self) -> None:
        await self._transport.aclose()


class PathPreservingAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """Pass a raw target into httpcore without leaking it into proxy subrequests."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        target = request.extensions.get("target")
        if target is None:
            return await super().handle_async_request(request)

        import httpcore

        # httpcore constructs its own absolute-form or CONNECT request. Leaving
        # the override in extensions would replace those generated targets too.
        extensions = dict(request.extensions)
        extensions.pop("target")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=target,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=extensions,
        )
        with map_httpcore_exceptions():
            core_response = await self._pool.handle_async_request(core_request)

        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=AsyncResponseStream(core_response.stream),
            extensions=core_response.extensions,
        )


class ProxyRoatingTransport(httpx.AsyncBaseTransport):
    def __init__(self, proxies: list[str], **kwargs: Any) -> None:
        self._transports = [
            PathPreservingAsyncHTTPTransport(proxy=proxy, **kwargs)
            for proxy in proxies
        ]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
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
            else ScopedDNSAsyncTransport(
                httpx.AsyncHTTPTransport(**tpargs),
                self._dns_resolver,
            )
        )

        transport_options = (
            {"transport": transport}
            if options["proxies"]
            else {"mounts": {"all://": transport}}
        )
        self.session = httpx.AsyncClient(
            timeout=httpx.Timeout(options["timeout"]),
            **transport_options,
        )
        self.replay_session = None

        if options["auth"]:
            self.set_auth(options["auth_type"], options["auth"])
        self._configured_auth = self.session.auth

    def parse_proxy(self, proxy: str) -> str | httpx.Proxy | None:
        if not proxy:
            return None

        if not proxy.startswith(PROXY_SCHEMES):
            proxy = f"http://{proxy}"

        if self.proxy_cred and "@" not in proxy:
            # socks5://localhost:9050 => socks5://[credential]@localhost:9050
            proxy = proxy.replace("://", f"://{self.proxy_cred}@", 1)

        if proxy.startswith("https://"):
            proxy_ssl_context = ssl.create_default_context()
            proxy_ssl_context.check_hostname = False
            proxy_ssl_context.verify_mode = ssl.CERT_NONE
            return httpx.Proxy(proxy, ssl_context=proxy_ssl_context)

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

    async def close(self) -> None:
        try:
            if self.replay_session is not None:
                await self.replay_session.aclose()
        finally:
            await self.session.aclose()

    async def replay_request(self, path: str, proxy: str) -> AsyncResponse:
        if self.replay_session is None:
            transport = PathPreservingAsyncHTTPTransport(
                verify=False,
                cert=self._cert,
                limits=httpx.Limits(max_connections=options["thread_count"]),
                proxy=self.parse_proxy(proxy),
                socket_options=self._socket_options,
            )
            self.replay_session = httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(options["timeout"]),
            )
        return await self.request(path, self.replay_session, replay=True)

    # :path: is expected not to start with "/"
    async def request(
        self, path: str, session: httpx.AsyncClient | None = None, replay: bool = False
    ) -> AsyncResponse:
        await self.wait_for_rate_limit()

        err_msg = None
        request_path = self.request_path(path)
        quoted_request_path = safequote(request_path)
        url = self._url + quoted_request_path
        session = session or self.session
        using_proxy = replay or bool(options["proxies"])

        for _ in range(options["max_retries"] + 1):
            try:
                if self.agents:
                    self.set_header("user-agent", random.choice(self.agents))

                # Use "target" extension to avoid the URL path from being normalized
                request = session.build_request(
                    options["http_method"],
                    url,
                    headers=self.headers,
                    content=options["data"],
                    extensions={
                        "target": _join_request_target(
                            self._url, quoted_request_path
                        ).encode()
                    },
                )

                start_time = time.perf_counter()
                xresponse = await session.send(
                    request,
                    stream=True,
                    follow_redirects=options["follow_redirects"],
                )
                try:
                    if (
                        using_proxy
                        and xresponse.status_code
                        == PROXY_AUTHENTICATION_REQUIRED
                    ):
                        raise RequestException("Proxy authentication required")
                    response = await AsyncResponse.create(
                        url,
                        xresponse,
                        capture_full_body=bool(
                            options["save_response"]
                            or options["save_response_jsonl"]
                        ),
                    )
                finally:
                    await xresponse.aclose()
                # Measure the whole streamed request lifecycle so sync and async
                # modes report the same thing.
                response.elapsed = time.perf_counter() - start_time

                log_msg = f'"{options["http_method"]} {response.url}" {response.status} - {response.length}B'

                if response.redirect:
                    log_msg += f" - LOCATION: {response.redirect}"

                logger.info(log_msg)

                return response

            except RequestException:
                raise
            except Exception as e:
                logger.exception(e)

                if _is_timeout_error(e):
                    err_msg = f"Request timeout: {url}"
                elif isinstance(e, httpx.ConnectError) and not _is_ssl_error(e):
                    if str(e).startswith("[Errno -2]"):
                        err_msg = "Couldn't resolve DNS"
                    else:
                        err_msg = f"Cannot connect to: {urlparse(url).netloc}"
                elif _is_ssl_error(e):
                    err_msg = _format_ssl_error(e, url)
                elif isinstance(e, httpx.TooManyRedirects):
                    err_msg = f"Too many redirects: {url}"
                elif isinstance(e, httpx.ProxyError):
                    err_msg = format_proxy_error(e)
                    if proxy_error_status(e) in (407, 429):
                        raise RequestException(err_msg) from e
                elif isinstance(e, httpx.InvalidURL):
                    err_msg = f"Invalid URL: {url}"
                elif _is_response_read_error(e):
                    err_msg = f"Failed to read response body: {url}"
                else:
                    err_msg = f"There was a problem in the request to: {url}"

        raise RequestException(err_msg)

    async def wait_for_rate_limit(self) -> None:
        await self._rate_limiter.wait_async(options["max_rate"])
