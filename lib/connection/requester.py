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

import re
import random
import socket
import http.client

from urllib.parse import urlparse

from lib.core.exceptions import InvalidURLException, RequestException
from lib.core.settings import PROXY_SCHEMES
from lib.connection.response import Response
from lib.utils.common import safequote
from lib.utils.dns import cached_getaddrinfo, set_default_addr
from lib.utils.schemedet import detect_scheme
from thirdparty import requests
from thirdparty.requests.adapters import HTTPAdapter
from thirdparty.requests.auth import HTTPBasicAuth, HTTPDigestAuth
from thirdparty.requests.packages.urllib3 import disable_warnings
from thirdparty.requests_ntlm import HttpNtlmAuth

# Disable InsecureRequestWarning from urllib3
disable_warnings()
# Use custom `socket.getaddrinfo` for `requests` which supports DNS caching
socket.getaddrinfo = cached_getaddrinfo


# I was forced to make this because of https://github.com/psf/requests/issues/3829
class Session(requests.Session):
    def merge_environment_settings(self, url, proxies, stream, verify, *args, **kwargs):
        return super(Session, self).merge_environment_settings(url, proxies, stream, self.verify, *args, **kwargs)


class Requester(object):
    def __init__(self, **kwargs):
        self.httpmethod = kwargs.get("httpmethod", "get")
        self.data = kwargs.get("data", None)
        self.max_pool = kwargs.get("max_pool", 100)
        self.max_retries = kwargs.get("max_retries", 3)
        self.timeout = kwargs.get("timeout", 10)
        self.ip = kwargs.get("ip", None)
        self.proxy = kwargs.get("proxy", None)
        self.proxylist = kwargs.get("proxylist", None)
        self.default_scheme = kwargs.get("scheme", None)
        self.follow_redirects = kwargs.get("follow_redirects", False)
        self.random_agents = kwargs.get("random_agents", None)
        self.auth = None
        self.headers = {}
        self.session = Session()
        self.session.verify = False

        set_default_addr(self.ip)

    def set_target(self, url):
        parsed = urlparse(url)

        # If no scheme specified, unset it first
        if "://" not in url:
            parsed = urlparse(f"{self.default_scheme or 'unknown'}://{url}")

        self.base_path = parsed.path
        if parsed.path.startswith('/'):
            self.base_path = parsed.path[1:]

        # Credentials in URL (https://[user]:[password]@website.com)
        if "@" in parsed.netloc:
            cred, parsed.netloc = parsed.netloc.split('@')
            self.set_auth("basic", cred)

        self.host = parsed.netloc.split(":")[0]

        # Standard ports for different schemes
        port_for_scheme = {"http": 80, "https": 443, "unknown": None}

        if parsed.scheme not in ("unknown", "https", "http"):
            raise InvalidURLException(f"Unsupported URI scheme: {parsed.scheme}")

        # If no port specified, set default (80, 443)
        try:
            self.port = int(parsed.netloc.split(":")[1])

            if not 0 < self.port < 65536:
                raise ValueError
        except IndexError:
            self.port = port_for_scheme[parsed.scheme]
        except ValueError:
            invalid_port = parsed.netloc.split(':')[1]
            raise InvalidURLException(f"Invalid port number: {invalid_port}")

        try:
            # If no scheme is found, detect it by port number
            self.scheme = parsed.scheme if parsed.scheme != "unknown" else detect_scheme(self.host, self.port)
        except ValueError:
            '''
            If the user neither provides the port nor scheme, guess them based
            on standard website characteristics
            '''
            self.scheme = detect_scheme(self.host, 443)
            self.port = port_for_scheme[self.scheme]

        self.netloc = f"{self.host}:{self.port}"
        self.url = f"{self.scheme}://{self.host}"

        if self.port != port_for_scheme[self.scheme]:
            self.url += f":{self.port}"

        self.url += "/"

        self.session.mount(self.scheme + "://", HTTPAdapter(max_retries=0, pool_maxsize=self.max_pool))

    def set_header(self, key, value):
        try:
            self.headers[key.strip()] = value.strip()
        except AttributeError:
            pass

    def set_auth(self, type, credential):
        if type in ("bearer", "jwt", "oath2"):
            self.set_header("Authorization", f"Bearer {credential}")
        else:
            user = credential.split(":")[0]
            try:
                password = ':'.join(credential.split(':')[1:])
            except IndexError:
                password = ''

            if type == "basic":
                self.auth = HTTPBasicAuth(user, password)
            elif type == "digest":
                self.auth = HTTPDigestAuth(user, password)
            else:
                self.auth = HttpNtlmAuth(user, password)

    def request(self, path, proxy=None):
        err_msg = None
        simple_err_msg = None

        # Why using a loop instead of max_retries argument? Check issue #1009
        for _ in range(self.max_retries + 1):
            redirects = []

            try:
                if not proxy:
                    if self.proxylist:
                        proxy = random.choice(self.proxylist)
                    elif self.proxy:
                        proxy = self.proxy

                if proxy:
                    if not proxy.startswith(PROXY_SCHEMES):
                        proxy = f"http://{proxy}"

                    if proxy.startswith("https://"):
                        proxies = {"https": proxy}
                    else:
                        proxies = {"https": proxy, "http": proxy}
                else:
                    proxies = None

                if self.random_agents:
                    self.headers["User-Agent"] = random.choice(self.random_agents)

                # Safe quote all special characters to prevent them from being encoded
                url = safequote(self.url + self.base_path + path)
                headers = self.headers.copy()
                request = requests.Request(
                    self.httpmethod,
                    url,
                    headers=headers,
                    auth=self.auth,
                    data=self.data,
                )

                prepare = request.prepare()
                prepare.url = url
                response = self.session.send(
                    prepare,
                    proxies=proxies,
                    allow_redirects=self.follow_redirects,
                    timeout=self.timeout,
                    stream=True,
                )

                if self.follow_redirects and len(response.history):
                    # Ignore the first response because it's for original request
                    redirects = [response.url for response in response.history[1:]]

                return Response(response, redirects)

            except Exception as e:
                err_msg = str(e)

                if e == socket.gaierror:
                    simple_err_msg = "Couldn't resolve DNS"
                elif "SSLError" in err_msg:
                    simple_err_msg = "Unexpected SSL error, probably the server is broken or try updating your OpenSSL"
                elif "TooManyRedirects" in err_msg:
                    simple_err_msg = f"Too many redirects: {self.url}"
                elif "ProxyError" in err_msg:
                    simple_err_msg = f"Error with the proxy: {proxy}"
                elif "InvalidURL" in err_msg:
                    simple_err_msg = f"Invalid URL: {self.url}"
                elif "InvalidProxyURL" in err_msg:
                    simple_err_msg = f"Invalid proxy URL: {proxy}"
                elif "ConnectionError" in err_msg:
                    simple_err_msg = f"Cannot connect to: {self.netloc}"
                elif re.search("ChunkedEncodingError|StreamConsumedError|UnrewindableBodyError", err_msg):
                    simple_err_msg = f"Failed to read response body: {self.url}"
                elif "Timeout" in err_msg or e in (
                    http.client.IncompleteRead,
                    socket.timeout,
                ):
                    simple_err_msg = f"Request timeout: {self.url}"
                else:
                    simple_err_msg = f"There was a problem in the request to: {self.url}"

        raise RequestException(simple_err_msg, err_msg)
