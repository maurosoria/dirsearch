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
import urllib.parse

import thirdparty.requests as requests

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

        parsed = urllib.parse.urlparse(url)

        # If no protocol specified, set http by default
        if "://" not in url:
            parsed = urllib.parse.urlparse("{0}://{1}".format(scheme, url))

        # If protocol is not supported
        elif parsed.scheme not in ["https", "http"]:
            raise RequestException({"message": "Unsupported URL scheme: {0}".format(parsed.scheme)})

        if parsed.path.startswith("/"):
            self.base_path = parsed.path[1:]
        else:
            self.base_path = parsed.path

        # Safe quote all special characters in base_path to prevent from being encoded when performing requests
        self.base_path = urllib.parse.quote(self.base_path, safe="!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
        self.protocol = parsed.scheme
        self.host = parsed.netloc.split(":")[0]

        # Resolve DNS to decrease overhead
        if ip:
            self.ip = ip
        # A proxy could have a different DNS that would resolve the name. ThereFore.
        # resolving the name when using proxy to raise an error is pointless
        elif not proxy and not proxylist:
            try:
                self.ip = socket.gethostbyname(self.host)
            except socket.gaierror:
                raise RequestException({"message": "Couldn't resolve DNS"})

        # If no port specified, set default (80, 443)
        try:
            self.port = int(parsed.netloc.split(":")[1])
        except IndexError:
            self.port = 443 if self.protocol == "https" else 80
        except ValueError:
            raise RequestException(
                {"message": "Invalid port number: {0}".format(parsed.netloc.split(":")[1])}
            )

        # Set the Host header, this will be overwritten if the user has already set the header
        self.headers["Host"] = self.host

        # Include port in Host header if it's non-standard
        if (self.protocol == "https" and self.port != 443) or (
            self.protocol == "http" and self.port != 80
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
        self.session = requests.Session()
        self.url = "{0}://{1}:{2}/".format(
            self.protocol,
            self.host if self.request_by_hostname else self.ip,
            self.port,
        )
        self.base_url = "{0}://{1}:{2}/".format(
            self.protocol,
            self.host,
            self.port,
        )

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
        error = None

        for i in range(self.max_retries):
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

                request = requests.Request(
                    self.httpmethod,
                    url=url,
                    headers=dict(self.headers),
                    auth=self.auth,
                    data=self.data,
                )
                prepare = request.prepare()
                prepare.url = url
                response = self.session.send(
                    prepare,
                    proxies=proxies,
                    allow_redirects=self.redirect,
                    timeout=self.timeout,
                    stream=True,
                    verify=False,
                )

                result = Response(response)

                break

            except requests.exceptions.SSLError:
                self.url = self.base_url
                continue

            except requests.exceptions.TooManyRedirects:
                error = "Too many redirects: {0}".format(self.base_url)

            except requests.exceptions.ProxyError:
                error = "Error with the proxy: {0}".format(proxy)

            except requests.exceptions.ConnectionError:
                error = "Cannot connect to: {0}:{1}".format(self.host, self.port)

            except requests.exceptions.InvalidURL:
                error = "Invalid URL: {0}".format(self.base_url)

            except requests.exceptions.InvalidProxyURL:
                error = "Invalid proxy URL: {0}".format(proxy)

            except (
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ReadTimeout,
                requests.exceptions.Timeout,
                http.client.IncompleteRead,
                socket.timeout,
            ):
                error = "Request timeout: {0}".format(self.base_url)

            except Exception:
                error = "There was a problem in the request to: {0}".format(self.base_url)

        if error:
            raise RequestException({"message": error})

        return result
