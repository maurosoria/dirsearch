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

import http.client
import socket
import random
import re
import requests

from requests.adapters import HTTPAdapter
from requests.auth import AuthBase, HTTPBasicAuth, HTTPDigestAuth
from requests.packages.urllib3 import disable_warnings
from requests_ntlm import HttpNtlmAuth
from urllib.parse import urlparse

from lib.core.exceptions import RequestException
from lib.core.settings import READ_RESPONSE_ERROR_REGEX, STANDARD_PORTS, PROXY_SCHEMES
from lib.core.structures import CaseInsensitiveDict
from lib.connection.dns import cache_dns, cached_getaddrinfo
from lib.connection.response import Response
from lib.utils.common import safequote
from lib.utils.mimetype import guess_mimetype

# Disable InsecureRequestWarning from urllib3
disable_warnings()
# Use custom `socket.getaddrinfo` for `requests` which supports DNS caching
socket.getaddrinfo = cached_getaddrinfo


class HTTPBearerAuth(AuthBase):
    def __init__(self, token):
        self.token = token

    def __call__(self, request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request


class Requester:
    def __init__(self, **kwargs):
        self._proxy_cred = None
        self._url = None
        self.httpmethod = kwargs.get("httpmethod", "get")
        self.data = kwargs.get("data", None)
        self.max_pool = kwargs.get("max_pool", 100)
        self.max_retries = kwargs.get("max_retries", 3)
        self.timeout = kwargs.get("timeout", 10)
        self.ip = kwargs.get("ip", None)
        self.proxy = kwargs.get("proxy", [])
        self.follow_redirects = kwargs.get("follow_redirects", False)
        self.random_agents = kwargs.get("random_agents", None)
        self.headers = CaseInsensitiveDict(kwargs.get("headers", {}))
        self.session = requests.Session()
        self.session.verify = False
        self.session.cert = (
            kwargs.get("cert_file", None),
            kwargs.get("key_file", None),
        )

        # Guess the mime type of request data if not specified
        if self.data and "content-type" not in self.headers:
            self.set_header("content-type", guess_mimetype(self.data))

        for scheme in ("http://", "https://"):
            self.session.mount(scheme, HTTPAdapter(max_retries=0, pool_maxsize=self.max_pool))

    def set_url(self, url):
        self._url = url

        if self.ip:
            host = url.split("/")[2]

            if ":" in host:
                host, port = host.split(":")
            else:
                scheme = url.split("/")[0].rstrip(":")
                port = STANDARD_PORTS.get(scheme)

            cache_dns(host, port, self.ip)

    def set_header(self, key, value):
        self.headers[key] = value.lstrip()

    def set_auth(self, type, credential):
        if type in ("bearer", "jwt", "oath2"):
            self.session.auth = HTTPBearerAuth(credential)
        else:
            user = credential.split(":")[0]
            try:
                password = ":".join(credential.split(":")[1:])
            except IndexError:
                password = ""

            if type == "basic":
                self.session.auth = HTTPBasicAuth(user, password)
            elif type == "digest":
                self.session.auth = HTTPDigestAuth(user, password)
            else:
                self.session.auth = HttpNtlmAuth(user, password)

    def set_proxy(self, proxy):
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

    def set_proxy_auth(self, credential):
        self._proxy_cred = credential

    def request(self, path, proxy=None):
        err_msg = None
        simple_err_msg = None

        # Why using a loop instead of max_retries argument? Check issue #1009
        for _ in range(self.max_retries + 1):
            try:
                try:
                    proxy = proxy or random.choice(self.proxy)
                    self.set_proxy(proxy)
                except IndexError:
                    pass

                if self.random_agents:
                    self.set_header("user-agent", random.choice(self.random_agents))

                # Safe quote all special characters to prevent them from being encoded
                url = safequote(path if not self._url else (self._url + path))

                headers = self.headers.copy()
                # Use prepared request to avoid the URL path from being normalized
                # Reference: https://github.com/psf/requests/issues/5289
                request = requests.Request(
                    self.httpmethod,
                    url,
                    headers=headers,
                    data=self.data,
                )
                prepped = self.session.prepare_request(request)
                prepped.url = url

                response = self.session.send(
                    prepped,
                    allow_redirects=self.follow_redirects,
                    timeout=self.timeout,
                    stream=True,
                )

                return Response(response)

            except Exception as e:
                err_msg = str(e)

                if e == socket.gaierror:
                    simple_err_msg = "Couldn't resolve DNS"
                elif "SSLError" in err_msg:
                    simple_err_msg = "Unexpected SSL error"
                elif "TooManyRedirects" in err_msg:
                    simple_err_msg = f"Too many redirects: {url}"
                elif "ProxyError" in err_msg:
                    simple_err_msg = f"Error with the proxy: {proxy}"
                    # Prevent from re-using it in the future
                    if proxy in self.proxy and len(self.proxy) > 1:
                        self.proxy.remove(proxy)
                elif "InvalidURL" in err_msg:
                    simple_err_msg = f"Invalid URL: {url}"
                elif "InvalidProxyURL" in err_msg:
                    simple_err_msg = f"Invalid proxy URL: {proxy}"
                elif "ConnectionError" in err_msg:
                    simple_err_msg = f"Cannot connect to: {urlparse(url).netloc}"
                elif re.search(READ_RESPONSE_ERROR_REGEX, err_msg):
                    simple_err_msg = f"Failed to read response body: {url}"
                elif "Timeout" in err_msg or e in (
                    http.client.IncompleteRead,
                    socket.timeout,
                ):
                    simple_err_msg = f"Request timeout: {url}"
                else:
                    simple_err_msg = (
                        f"There was a problem in the request to: {url}"
                    )

        raise RequestException(simple_err_msg, err_msg)
