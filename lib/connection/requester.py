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

import urllib3
import http.client
import random
import socket
import ssl
import thirdparty.requests as requests

from urllib.parse import urlparse, urljoin

from lib.utils.fmt import safequote
from thirdparty.requests.adapters import HTTPAdapter
from thirdparty.requests.auth import HTTPBasicAuth, HTTPDigestAuth
from thirdparty.requests_ntlm import HttpNtlmAuth
from .request_exception import RequestException
from .response import Response

urllib3.disable_warnings()


class Requester(object):
    def __init__(
        self,
        url,
        max_pool=1,
        max_retries=5,
        timeout=20,
        ip=None,
        proxy=None,
        proxylist=None,
        redirect=False,
        request_by_hostname=False,
        httpmethod="get",
        data=None,
        scheme=None,
    ):
        self.httpmethod = httpmethod
        self.data = data
        self.headers = {}

        parsed = urlparse(url)

        # If no scheme specified, unset it first
        if "://" not in url:
            parsed = urlparse("{0}://{1}".format(scheme or "unknown", url))

        self.base_path = parsed.path
        if parsed.path.startswith("/"):
            self.base_path = parsed.path[1:]

        # Safe quote all special characters in base_path to prevent from being encoded
        self.base_path = safequote(self.base_path)
        self.host = parsed.netloc.split(":")[0]

        port_for_scheme = {"http": 80, "https": 443, "unknown": 0}

        # If no port specified, set default (80, 443)
        try:
            self.port = int(parsed.netloc.split(":")[1])
        except IndexError:
            self.port = port_for_scheme[parsed.scheme]
        except ValueError:
            raise RequestException(
                {"message": "Invalid port number: {0}".format(parsed.netloc.split(":")[1])}
            )

        # If no scheme is found, detect it by port number
        self.scheme = parsed.scheme if parsed.scheme != "unknown" else self.get_scheme(self.port)

        # If the user neither provide the port nor scheme, guess them based
        # on standard website characteristics
        if not self.scheme:
            if self.get_scheme(443) == "https":
                self.port = 443
                self.scheme = "https"
            else:
                self.port = 80
                self.scheme = "http"
        # If the scheme is not supported
        elif self.scheme not in ["https", "http"]:
            raise RequestException({"message": "Unsupported URI scheme: {0}".format(self.scheme)})

        # Set the Host header, read the line 126 to know why
        self.headers["Host"] = self.host

        # Include port in Host header if it's non-standard
        if (self.scheme == "https" and self.port != 443) or (
            self.scheme == "http" and self.port != 80
        ):
            self.headers["Host"] += ":{0}".format(self.port)

        self.max_retries = max_retries
        self.max_pool = max_pool
        self.timeout = timeout
        self.pool = None
        self.proxy = proxy
        self.proxylist = proxylist
        self.redirect = redirect
        self.random_agents = None
        self.auth = None
        self.request_by_hostname = request_by_hostname
        self.ip = ip
        self.base_url = self.url = "{0}://{1}/".format(
            self.scheme,
            self.headers["Host"],
        )

    def setup(self):
        # To improve dirsearch performance, we resolve the hostname before scanning
        # and then send requests by IP instead of hostname, so the library won't have to
        # resolve it before every request. This also keeps the scan stable despite any
        # issue with the system DNS resolver (running tools like Amass might cause such
        # things). If you don't like it, you can disable it with `-b` command-line flag
        #
        # Note: A proxy could have a different DNS that would resolve the name. ThereFore.
        # resolving the name when using proxy to raise an error is pointless
        if not self.request_by_hostname and not self.proxy and not self.proxylist:
            try:
                self.ip = self.ip or socket.gethostbyname(self.host)
            except socket.gaierror:
                # Check if hostname resolves to IPv6 address only
                try:
                    self.ip = socket.getaddrinfo(self.host, None, socket.AF_INET6)[0][4][0]
                except socket.gaierror:
                    raise RequestException({"message": "Couldn't resolve DNS"})

            self.url = "{0}://{1}:{2}/".format(
                self.scheme,
                self.ip,
                self.port,
            )

        self.session = requests.Session()
        self.set_adapter()

    def get_scheme(self, port):
        if port == 0:
            return None

        s = socket.socket()
        conn = ssl.SSLContext().wrap_socket(s)
        try:
            conn.connect((self.host, port))
            conn.close()
            return "https"
        except Exception:
            return "http"

    def set_adapter(self):
        self.session.mount(self.url, HTTPAdapter(max_retries=self.max_retries))

    def set_header(self, key, value):
        self.headers[key.strip()] = value.strip() if value else value

    def set_random_agents(self, agents):
        self.random_agents = list(agents)

    def set_auth(self, type, credential):
        if type == "bearer":
            self.set_header("Authorization", "Bearer {0}".format(credential))
        else:
            user = credential.split(":")[0]
            try:
                password = ":".join(credential.split(":")[1:])
            except IndexError:
                password = ""

            if type == "basic":
                self.auth = HTTPBasicAuth(user, password)
            elif type == "digest":
                self.auth = HTTPDigestAuth(user, password)
            else:
                self.auth = HttpNtlmAuth(user, password)

    def request(self, path, proxy=None):
        result = None

        try:
            if not proxy:
                if self.proxylist:
                    proxy = random.choice(self.proxylist)
                elif self.proxy:
                    proxy = self.proxy

            if proxy:
                if not proxy.startswith(
                    ("http://", "https://", "socks5://", "socks5h://", "socks4://", "socks4a://")
                ):
                    proxy = "http://" + proxy

                if proxy.startswith("https://"):
                    proxies = {"https": proxy}
                else:
                    proxies = {"https": proxy, "http": proxy}
            else:
                proxies = None

            url = self.url + self.base_path + path

            if self.random_agents:
                self.headers["User-Agent"] = random.choice(self.random_agents)

            """
            We can't just do `allow_redirects=True` because we set the host header in
            optional request headers, which will be kept in next requests (follow redirects)
            """
            headers = self.headers.copy()
            for i in range(6):
                request = requests.Request(
                    self.httpmethod,
                    url=url,
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
                    verify=False,
                )
                result = Response(response)

                if self.redirect and result.redirect:
                    url = urljoin(url, result.redirect)
                    headers["Host"] = url.split("/")[2]
                    continue
                elif i == 5:
                    raise requests.exceptions.TooManyRedirects

                break

        except requests.exceptions.SSLError:
            self.url = self.base_url
            self.set_adapter()
            result = self.request(path, proxy=proxy)

        except requests.exceptions.TooManyRedirects:
            raise RequestException(
                {"message": "Too many redirects: {0}".format(self.base_url)}
            )

        except requests.exceptions.ProxyError:
            raise RequestException(
                {"message": "Error with the proxy: {0}".format(proxy)}
            )

        except requests.exceptions.ConnectionError:
            raise RequestException(
                {"message": "Cannot connect to: {0}:{1}".format(self.host, self.port)}
            )

        except requests.exceptions.InvalidURL:
            raise RequestException(
                {"message": "Invalid URL: {0}".format(self.base_url)}
            )

        except requests.exceptions.InvalidProxyURL:
            raise RequestException(
                {"message": "Invalid proxy URL: {0}".format(proxy)}
            )

        except (
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.Timeout,
            http.client.IncompleteRead,
            socket.timeout,
        ):
            raise RequestException(
                {"message": "Request timeout: {0}".format(self.base_url)}
            )

        except Exception:
            raise RequestException(
                {"message": "There was a problem in the request to: {0}".format(self.base_url)}
            )

        return result
