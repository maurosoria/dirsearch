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

from urllib.parse import urlparse, urljoin

from lib.core.exceptions import InvalidURLException, RequestException, DNSError
from lib.core.settings import PROXY_SCHEMES, MAX_REDIRECTS
from lib.connection.response import Response
from lib.utils.fmt import safequote
from lib.utils.schemedet import detect_scheme
from thirdparty import requests
from thirdparty.requests.adapters import HTTPAdapter
from thirdparty.requests.auth import HTTPBasicAuth, HTTPDigestAuth
from thirdparty.requests.packages.urllib3 import disable_warnings
from thirdparty.requests_ntlm import HttpNtlmAuth

# Disable InsecureRequestWarning from urllib3
disable_warnings()
# Add support for all cipher suites
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = "ALL"


# I was forced to make this because of https://github.com/psf/requests/issues/3829
class Session(requests.Session):
    def merge_environment_settings(self, url, proxies, stream, verify, *args, **kwargs):
        return super(Session, self).merge_environment_settings(url, proxies, stream, self.verify, *args, **kwargs)


class Requester(object):
    def __init__(self, url, **kwargs):
        self.httpmethod = kwargs.get("httpmethod", "get")
        self.data = kwargs.get("data", None)
        self.max_pool = kwargs.get("max_pool", 100)
        self.max_retries = kwargs.get("max_retries", 3)
        self.timeout = kwargs.get("timeout", 10)
        self.proxy = kwargs.get("proxy", None)
        self.proxylist = kwargs.get("proxylist", None)
        self.follow_redirects = kwargs.get("follow_redirects", False)
        self.random_agents = kwargs.get("random_agents", None)
        self.request_by_hostname = kwargs.get("request_by_hostname", False)
        self.ip = kwargs.get("ip", None)
        self.auth = None
        self.headers = {}

        parsed = urlparse(url)
        scheme = kwargs.get("scheme", None)

        # If no scheme specified, unset it first
        if "://" not in url:
            parsed = urlparse(f"{scheme or 'unknown'}://{url}")

        self.base_path = parsed.path
        if parsed.path.startswith("/"):
            self.base_path = parsed.path[1:]

        # Safe quote all special characters in base_path to prevent from being encoded
        self.base_path = safequote(self.base_path)

        # Credentials in URL (https://[user]:[password]@website.com)
        if "@" in parsed.netloc:
            cred, parsed.netloc = parsed.netloc.split("@")
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
            # If the user neither provides the port nor scheme, guess them based
            # on standard website characteristics
            self.scheme = detect_scheme(self.host, 443)
            self.port = port_for_scheme[self.scheme]

        # Set the Host header, read the line 126 to know why
        self.headers["Host"] = self.host

        # Include port in Host header if it's non-standard
        if self.port != port_for_scheme[self.scheme]:
            self.headers["Host"] += f":{self.port}"

        self.base_url = self.url = f"{self.scheme}://{self.headers['Host']}/"

    def setup(self):
        '''
        To improve dirsearch performance, we resolve the hostname before scanning
        and then send requests by IP instead of hostname, so the library won't have to
        resolve it before every request. This also keeps the scan stable despite any
        issue with the system DNS resolver (running tools like Amass might cause such
        things). If you don't like it, you can disable it with `-b` command-line flag
        '''
        if not self.request_by_hostname:
            try:
                self.ip = self.ip or socket.gethostbyname(self.host)
            except socket.gaierror:
                # Check if hostname resolves to IPv6 address only
                try:
                    self.ip = socket.getaddrinfo(self.host, None, socket.AF_INET6)[0][4][0]
                except socket.gaierror:
                    raise DNSError

            self.url = f"{self.scheme}://{self.ip}:{self.port}/"

        self.session = Session()
        self.session.verify = False
        self.session.mount(self.scheme + "://", HTTPAdapter(max_retries=0, pool_maxsize=self.max_pool))

    def set_header(self, key, value):
        self.headers[key.strip()] = value.strip() if value else value

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
        for _ in range(self.max_retries + 1):
            result = None
            redirects = []

            try:
                url = self.url + self.base_path + path

                if not proxy:
                    if self.proxylist:
                        proxy = random.choice(self.proxylist)
                    elif self.proxy:
                        proxy = self.proxy

                if proxy:
                    url = self.base_url + self.base_path + path

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

                '''
                We can't just do `allow_redirects=True` because we set the host header in
                request headers, which will be kept in next requests (follow redirects)
                '''
                headers = self.headers.copy()
                for _ in range(MAX_REDIRECTS):
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
                        allow_redirects=False,
                        timeout=self.timeout,
                        stream=True,
                    )
                    result = Response(response, redirects)

                    if self.follow_redirects and result.redirect:
                        url = urljoin(url, result.redirect)
                        headers["Host"] = url.split("/")[2]
                        redirects.append(url)
                        continue
                    else:
                        return result

                raise requests.exceptions.TooManyRedirects

            except Exception as e:
                err_msg = str(e)

                if "SSLError" in err_msg:
                    simple_err_msg = "Unexpected SSL error, probably the server is broken or try updating your OpenSSL"
                elif "ProxyError" in err_msg:
                    simple_err_msg = f"Error with the proxy: {proxy}"
                elif "InvalidURL" in err_msg:
                    simple_err_msg = f"Invalid URL: {self.base_url}"
                elif "InvalidProxyURL" in err_msg:
                    simple_err_msg = f"Invalid proxy URL: {proxy}"
                elif "ConnectionError" in err_msg:
                    simple_err_msg = f"Cannot connect to: {self.host}:{self.port}"
                elif re.search("ChunkedEncodingError|StreamConsumedError|UnrewindableBodyError", err_msg):
                    simple_err_msg = f"Failed to read response body: {self.base_url}"
                elif e == requests.exceptions.TooManyRedirects:
                    simple_err_msg = f"Too many redirects: {self.base_url}"
                elif "Timeout" in err_msg or e in (
                    http.client.IncompleteRead,
                    socket.timeout,
                ):
                    simple_err_msg = f"Request timeout: {self.base_url}"
                else:
                    simple_err_msg = f"There was a problem in the request to: {self.base_url}"

        raise RequestException(simple_err_msg, err_msg)
