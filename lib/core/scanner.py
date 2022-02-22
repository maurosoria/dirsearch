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

from urllib.parse import unquote

from lib.core.settings import TEST_PATH_LENGTH
from lib.parse.url import clean_path
from lib.utils.matcher import generate_matching_regex
from lib.utils.random import rand_string
from thirdparty.sqlmap import DynamicContentParser


class Scanner(object):
    def __init__(self, requester, **kwargs):
        self.calibration = kwargs.get("calibration", None)
        self.suffix = kwargs.get("suffix", '')
        self.prefix = kwargs.get("prefix", '')
        self.tested = kwargs.get("tested", [])
        self.requester = requester
        self.tester = None
        self.response = None
        self.dynamic_parser = None
        self.wildcard_redirect_regex = None
        self.mark = None
        self.setup()

    def get_duplicate(self, response):
        for t in self.tested:
            for tester in self.tested[t].values():
                if (response.status, response.body, response.redirect) == (
                    tester.response.status, tester.response.body, tester.response.redirect
                ):
                    return tester

        return

    '''
    Generate wildcard response information containers, this will be
    used to compare with other path responses
    '''
    def setup(self):
        first_path = self.prefix + (
            self.calibration if self.calibration else rand_string(TEST_PATH_LENGTH)
        ) + self.suffix
        first_response = self.requester.request(first_path)
        self.response = first_response

        if self.response.status == 404:
            # Using the response status code is enough :-}
            return

        duplicate = self.get_duplicate(first_response)
        # Another test was performed before and has the same response as this
        if duplicate:
            self.ratio = duplicate.ratio
            self.dynamic_parser = duplicate.dynamic_parser
            self.wildcard_redirect_regex = duplicate.wildcard_redirect_regex
            self.mark = duplicate.mark
            return

        second_path = self.prefix + (
            self.calibration if self.calibration else rand_string(TEST_PATH_LENGTH, omit=first_path)
        ) + self.suffix
        second_response = self.requester.request(second_path)

        if first_response.redirect and second_response.redirect:
            self.wildcard_redirect_regex = self.generate_redirect_regex(
                first_response.redirect, first_path,
                second_response.redirect, second_path,
            )

        # Analyze response bodies
        if first_response.body is not None and second_response.body is not None:
            self.dynamic_parser = DynamicContentParser(
                self.requester, first_path, first_response.body, second_response.body
            )
        else:
            self.dynamic_parser = None

        self.ratio = round(self.dynamic_parser.comparisonRatio, 2)

        # The wildcard response is static
        if self.ratio == 1:
            pass
        # Adjusting ratio based on response length
        elif len(first_response) < 100:
            self.ratio -= 0.1
        elif len(first_response) < 500:
            self.ratio -= 0.05
        elif len(first_response) < 2000:
            self.ratio -= 0.02
        else:
            self.ratio -= 0.01

        '''
        If the path is reflected in response, decrease the ratio. Because
        the difference between path lengths can affect the similarity ratio
        '''
        if first_path in first_response.content:
            if len(first_response) < 200:
                self.ratio -= 0.15 + 15 / len(first_response)
            elif len(first_response) < 800:
                self.ratio -= 0.06 + 30 / len(first_response)
            elif len(first_response) < 5000:
                self.ratio -= 0.03 + 80 / len(first_response)
            elif len(first_response) < 20000:
                self.ratio -= 0.02 + 200 / len(first_response)
            else:
                self.ratio -= 0.01

    '''
    From 2 redirects of wildcard responses, generate a regexp that matches
    every wildcard redirect.

    How it works:
    1. Replace path in 2 redirect URLs (if it gets reflected in) with an unique mark
    (e.g. /path1 -> /foo/path1 and /path2 -> /foo/path2 will become /foo/[mark] for both)
    2. Compare 2 redirects and generate a regex that matches both
    (e.g. /foo/[mark]?a=1 and /foo/[mark]?a=2 will have the regex: ^/foo/[mark]?a=(.*)$)
    3. Next time if it redirects, replace mark in regex with the path and check if it matches
    (e.g. /path3 -> /foo/path3?a=5, the regex becomes ^/foo/path3?a=(.*)$, which matches)
    '''
    def generate_redirect_regex(self, first_loc, first_path, second_loc, second_path):
        self.mark = rand_string(20)
        first_loc = unquote(first_loc).replace(first_path, self.mark)
        second_loc = unquote(second_loc).replace(second_path, self.mark)
        return generate_matching_regex(first_loc, second_loc)

    '''
    Check if redirect matches the wildcard redirect regex or the response
    has high similarity with wildcard tested at the start
    '''
    def scan(self, path, response):
        if self.response.status == response.status == 404:
            return False

        if self.response.status != response.status:
            return True

        # Read from line 129 to 138 to understand the workflow of this.
        if self.wildcard_redirect_regex and response.redirect:
            '''
            - unquote(): Sometimes, some path characters get encoded or decoded in the response redirect
            but it's still a wildcard redirect, so unquote everything to prevent false positives
            - clean_path(): Get rid of queries and DOM in URL because of weird behaviours could happen
            with them, so messy that I give up on finding a way to test them
            '''
            path = re.escape(unquote(clean_path(path)))
            redirect = unquote(clean_path(response.redirect))
            regex_to_compare = self.wildcard_redirect_regex.replace(self.mark, path)
            is_wildcard_redirect = re.match(regex_to_compare, redirect, re.IGNORECASE)

            # If redirection doesn't match the rule, mark as found
            if not is_wildcard_redirect:
                return True

        # Compare 2 responses (wildcard one and given one)
        ratio = self.dynamic_parser.compareTo(response.body)

        # If the similarity ratio is high enough to proof it's wildcard
        if ratio >= self.ratio:
            return False
        elif "is_wildcard_redirect" in locals() and ratio >= (self.ratio - 0.18):
            return False

        return True
