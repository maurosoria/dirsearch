# -*- coding: utf-8 -*-
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program; if not, write to the Free
# Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# Author: Mauro Soria


import urlparse
import socket
import urllib
from thirdparty.urllib3 import *
from thirdparty.urllib3.exceptions import *
from Response import *
from RequestException import *


class Requester(object):

    headers = {
        'User-agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1468.0 Safari/537.36',
        'Accept-Language': 'en-us',
        'Accept-Encoding': 'identity',
        'Keep-Alive': '300',
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0',
        }

    def __init__(self, url, cookie=None, useragent=None, maxPool=1, maxRetries=5, timeout=30, ip=None, proxy=None,
                 redirect=False):
        # if no backslash, append one
        if url[-1] is not '/':
            url = url + '/'
        parsed = urlparse.urlparse(url)
        self.basePath = parsed.path

        # if not protocol specified, set http by default
        if parsed.scheme != 'http' and parsed.scheme != 'https':
            parsed = urlparse.urlparse('http://' + url)
            self.basePath = parsed.path
        self.protocol = parsed.scheme
        if self.protocol != 'http' and self.protocol != 'https':
            self.protocol = 'http'
        self.host = parsed.netloc.split(':')[0]

        # resolve DNS to decrease proxychains overhead
        if ip is not None:
            self.ip = ip
        else:
            try:
                self.ip = socket.gethostbyname(self.host)
            except socket.gaierror:
                raise RequestException({'message': "Couldn't resolve DNS"})
        self.headers['Host'] = self.host

        # If no port specified, set default (80, 443)
        try:
            self.port = parsed.netloc.split(':')[1]
        except IndexError:
            self.port = (443 if self.protocol == 'https' else 80)

        # Set cookie and user-agent headers
        if cookie != None:
            self.setHeader('Cookie', cookie)
        if useragent != None:
            self.setHeader('User-agent', useragent)
        self.maxRetries = maxRetries
        self.maxPool = maxPool
        self.timeout = timeout
        self.pool = None
        self.proxy = proxy
        self.redirect = redirect

    def setHeader(self, header, content):
        self.headers[header] = content

    @property
    def connection(self):
        if self.pool == None:
            if self.proxy is not None:
                return self.connectionWithProxy()
            if self.protocol == 'https':
                self.pool = HTTPSConnectionPool(self.ip, port=self.port, timeout=self.timeout, maxsize=self.maxPool,
                                                block=True, cert_reqs='CERT_NONE', assert_hostname=False)
            else:
                self.pool = HTTPConnectionPool(self.ip, port=self.port, timeout=self.timeout, maxsize=self.maxPool,
                                               block=True)
        return self.pool

    def connectionWithProxy(self):
        if self.protocol == 'https':
            self.pool = proxy_from_url(self.proxy, timeout=self.timeout, maxsize=self.maxPool, block=True,
                                       cert_reqs='CERT_NONE', assert_hostname=False)
        else:
            self.pool = proxy_from_url(self.proxy, timeout=self.timeout, maxsize=self.maxPool, block=True)
        return self.pool

    def request(self, path, method='GET', params='', data=''):
        i = 0
        while i <= self.maxRetries:
            try:
                if self.proxy is None:
                    url = '{0}{1}?{2}'.format(self.basePath, path, params)
                else:
                    url = '{5}://{3}:{4}{0}{1}?{2}'.format(self.basePath, path, params, self.host, self.port,
                                                           self.protocol)
                response = self.connection.urlopen(method, url, headers=self.headers, redirect=self.redirect,
                                                   assert_same_host=False)
                result = Response(response.status, response.reason, response.headers, response.data)
                break
            except ProxyError, e:
                raise RequestException({'message': 'Error with the proxy: {0}'.format(e)})
            except (MaxRetryError, ReadTimeoutError):
                continue
            finally:
                i = i + 1
        if i > self.maxRetries:
            raise RequestException({'message': 'CONNECTION TIMEOUT: There was a problem in the request to: {0}'.format(path)})
        return result


